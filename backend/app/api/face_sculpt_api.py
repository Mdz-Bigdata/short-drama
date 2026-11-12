# -*- coding: utf-8 -*-
"""捏脸 / 捏表情：读控件表、预览、保存、重置。只改文字资产，不调用任何模型、不花钱。

保存后角色描述与第 3 阶段各造型状态的长相层随之更新，设定集、分镜、视频都读这一份。
已经画好的设定集和定妆图还是旧脸，预览里的 ``sheet_stale`` 会提示，重出由人决定(付费)。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.auth_api import get_current_user
from app.api.drama_api import require_owned_drama_task, service
from app.core import actor_sheet_style, face_sculpt, face_sculpt_sync, usage_ledger
from app.core.character_dashboard import compile_character_dashboard
from app.core.storyboard_quality import build_actor_sheet_prompt
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore

catalog_router = APIRouter(prefix="/api/face-sculpt", tags=["捏脸"], dependencies=[Depends(get_current_user)])
router = APIRouter(prefix="/api/drama", tags=["捏脸"], dependencies=[Depends(require_owned_drama_task)])

# 用量账本里这类调用的用途名。
_PURPOSE = "face_sculpt"
_NO_TEXT_MODEL = "没有可用的文本模型"
# 第 3 阶段 config.director_style 没填时的默认值(drama_service 出图时同样这么取)；风格词本身在
# app/data/prompt/actor_sheet.json，经 actor_sheet_style 和真正出图的 ModelGateway 读同一份。
_SHEET_DIR_STYLE_DEFAULT = "真人电影写实"


class FaceSculptBody(BaseModel):
    face: dict[str, Any] = Field(default_factory=dict, max_length=64)
    notes: dict[str, str] = Field(default_factory=dict, max_length=8)
    expressions: dict[str, Any] = Field(default_factory=dict, max_length=32)
    preset: str = Field("", max_length=40)
    # 这张脸的突出点(一个骨相或五官控件键)，空串表示没定。
    focus: str = Field("", max_length=40)
    # 这一步怎么来的，进撤销历史；不填按「手动调整」。
    label: str = Field("", max_length=60)


class InstructBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    model: str = Field("", max_length=80)
    apply: bool = False


class RevertBody(BaseModel):
    snapshot_id: str = Field(..., min_length=1, max_length=16)


def _llm(task: Mapping[str, Any], model: str = "") -> face_sculpt.LLM:
    """项目配置的文本模型(或这次点名的)；离线模板的回答按没有算。没配模型就 422，不悄悄用模板。"""
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    chosen = model or str(config.get("llm_model") or "")
    if not chosen:
        raise HTTPException(status_code=422, detail=_NO_TEXT_MODEL)
    title = str(config.get("title_suggestion") or config.get("titleSuggestion") or task.get("stage_name") or "")
    task_id = str(task.get("task_id") or "")

    def call(system: str, user: str, max_tokens: int) -> Optional[str]:
        with usage_ledger.bind_task(task_id, _PURPOSE):
            answer = service.gateway.call_llm(chosen, system, user, title, max_tokens=max_tokens)
        return None if service.gateway.last_answer_was_offline() else answer

    return call


def _validated(body: FaceSculptBody) -> face_sculpt.Sculpt:
    try:
        return face_sculpt.validate(body.model_dump())
    except face_sculpt.SculptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _task(task_id: str) -> dict[str, Any]:
    task = service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _edit(task_id: str, name: str, edit) -> tuple[dict[str, Any], dict[str, Any]]:
    """改完重算角色总览；返回 (结果, 改后的任务)，任务给元素库写回认主人和项目用。"""
    edited: dict[str, Any] = {}

    def mutation(task: dict[str, Any]) -> dict[str, Any]:
        result = edit(task, name)
        assets = task.setdefault("assets", {})
        assets["3_character_dashboard"] = compile_character_dashboard(task).model_dump(mode="json", by_alias=True)
        edited.update(task)
        return result

    try:
        result = service.repo.mutate_task(task_id, mutation)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result, edited


async def _edited(store: PlatformStore, task_id: str, name: str, edit) -> dict[str, Any]:
    """捏脸写进资产，再把新描述写回元素库里这位演员；写回的结果放在 ``library`` 里，失败不影响保存。"""
    result, task = await run_in_threadpool(_edit, task_id, name, edit)
    description = str((result.get("preview") or {}).get("description") or "")
    result["library"] = await face_sculpt_sync.sync_actor_description_async(store, task, name, description)
    return result


def _sheet_prompt(task: Mapping[str, Any], record: Mapping[str, Any]) -> str:
    """第 3 阶段重出设定集时会交给图像模型的画面描述(不含负面词)，照 regenerate_character 的入参拼。"""
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    gateway = service.gateway
    genre = str(gateway.get_genre(str(config.get("title_suggestion") or "")) or "")
    era_costume = str((getattr(gateway, "GENRE_ERA_COSTUME", None) or {}).get(genre, "") or "")
    style_word = actor_sheet_style.style_word(str(config.get("director_style") or _SHEET_DIR_STYLE_DEFAULT), era_costume)
    description = str(record.get("desc") or record.get("description") or "")
    return build_actor_sheet_prompt(str(record.get("name") or ""), description, style_word,
                                    era_note=actor_sheet_style.era_clause(era_costume))


@catalog_router.get("/catalog")
def get_catalog():
    """捏脸控件(按资产卡分层)、预设、表情控件与情绪清单。"""
    return face_sculpt.describe_catalog()


@router.get("/{task_id}/characters/{name}/face-sculpt")
async def get_face_sculpt(task_id: str, name: str):
    task = await run_in_threadpool(_task, task_id)
    try:
        return face_sculpt.current(task, name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{task_id}/characters/{name}/face-sculpt/preview")
async def preview_face_sculpt(task_id: str, name: str, body: FaceSculptBody):
    """不保存，只看捏出来的描述、近景提示词里的脸、资产卡警告和表情写法。"""
    sculpt = _validated(body)
    task = await run_in_threadpool(_task, task_id)
    try:
        record = face_sculpt.record_of(task, name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return face_sculpt.preview(record, sculpt, task)


@router.get("/{task_id}/characters/{name}/sheet-prompt")
async def get_sheet_prompt(task_id: str, name: str):
    """只读：第 3 阶段重出这个人的设定集时会用的画面描述，捏完脸先看一眼再决定要不要花钱重出。不调用模型。"""
    task = await run_in_threadpool(_task, task_id)
    try:
        record = face_sculpt.record_of(task, name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    stored = record.get(face_sculpt.RECORD_KEY) if isinstance(record.get(face_sculpt.RECORD_KEY), Mapping) else {}
    return {
        "name": name,
        "prompt": _sheet_prompt(task, record),
        "sheet_stale": face_sculpt.sheet_is_stale(record, task),
        "revision": int(stored.get("revision") or 0),
    }


@router.put("/{task_id}/characters/{name}/face-sculpt")
async def save_face_sculpt(task_id: str, name: str, body: FaceSculptBody, store: PlatformStore = Depends(get_platform_store)):
    sculpt = _validated(body)
    return await _edited(store, task_id, name, lambda task, who: face_sculpt.save(task, who, sculpt, label=body.label))


@router.post("/{task_id}/characters/{name}/face-sculpt/instruct")
async def instruct_face_sculpt(task_id: str, name: str, body: InstructBody, store: PlatformStore = Depends(get_platform_store)):
    """一句话捏脸：模型把要求翻成控件取值，返回合并后的捏脸、预览与说明；``apply`` 为真才写进资产。"""
    task = await run_in_threadpool(_task, task_id)
    llm = _llm(task, body.model)
    try:
        result = await run_in_threadpool(face_sculpt.apply_instruction, task, name, body.message, llm, model_name=body.model)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except face_sculpt.SculptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    sculpt: face_sculpt.Sculpt = result["sculpt"]
    saved = None
    if body.apply:
        cat = face_sculpt.catalog()
        label = str(cat.wording["history_instruct"]).replace("{message}", body.message.strip()[:int(cat.limits["label_message_chars"])])
        saved = await _edited(store, task_id, name, lambda t, who: face_sculpt.save(t, who, sculpt, label=label))
    return {
        "reply": result["reply"],
        "patch": result["patch"],
        "unknown": result["unknown"],
        "sculpt": sculpt.dump(),
        "preview": saved["preview"] if saved else result["preview"],
        "saved": saved is not None,
        "current": saved,
        "library": saved.get("library") if saved else None,
    }


@router.post("/{task_id}/characters/{name}/face-sculpt/revert")
async def revert_face_sculpt(task_id: str, name: str, body: RevertBody, store: PlatformStore = Depends(get_platform_store)):
    """退回撤销历史里的某一步；只保留最近几步，找不到的 404。"""
    return await _edited(store, task_id, name, lambda task, who: face_sculpt.revert(task, who, body.snapshot_id))


@router.delete("/{task_id}/characters/{name}/face-sculpt")
async def reset_face_sculpt(task_id: str, name: str, store: PlatformStore = Depends(get_platform_store)):
    """放回第一次捏脸前的描述，去掉捏脸与表情习惯。"""
    return await _edited(store, task_id, name, face_sculpt.reset)

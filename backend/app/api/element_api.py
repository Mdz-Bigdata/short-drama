from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi import Response
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app import settings
from app.platform.billing_book import BillingRefused
from app.core.prop_board import compose_prop_board
from app.core.prop_turnaround import (
    PROP_ALL_SLOTS,
    PROP_BOARD_SLOT,
    PROP_CLOSING,
    PROP_REFERENCE_SLOT,
    PROP_VIEWS,
    PropPlan,
    plan_prop,
    prop_instruction,
    split_prop_sheet,
)
from app.core import prompt_data, real_person, scene_scale, xianxia_props
from app.core.asset_sheets import EMPTY_SCENE_PREFIX, EMPTY_SCENE_SUFFIX
from app.core.look_board import LAYOUT_MAKEUP, LAYOUT_PLAIN, LOOK_VIEW_SLOTS, split_look_board
from app.core.scene_turnaround import (
    SCENE_TURNAROUND_CLOSING,
    SCENE_TURNAROUND_INSTRUCTION,
    SCENE_GRID_SLOTS,
    SCENE_REVERSE_SLOT,
    SCENE_TURNAROUND_SIZE,
    SCENE_VIEW_SLOTS,
    split_scene_turnaround,
)
from app.core import character_variants
from app.core import wuxia_vfx
from app.core.character_looks import (
    LOOK_BOARD_SIZE, LOOK_CHECK_SYSTEM, look_check_prompt, look_fix_prompt, look_prompt, parse_look_check, wears_makeup,
)
from app.core.element_scope import element_in_task, element_name_keys, element_task_ids, normalized_asset_name
from app.api.auth_api import get_current_user
from app.core.media_compositor import MEDIA_DIR
from app.core.model_gateway import ModelGateway
from app.core.storyboard_assets import MAX_REMOTE_IMAGE_BYTES, fetch_remote_image_bytes
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore, StorageMutationCommittedWithError
from app.platform.uploads import (
    MAX_IMAGE_UPLOAD_BYTES,
    MAX_MODEL_UPLOAD_BYTES,
    UploadValidationError,
    inspect_glb_upload,
    validate_image_upload,
)
from app.schema.production import IDENTITY_VIEW_ORDER
from app.repository.task_repo import TaskRepository, TaskStoreUnavailableError
from app.service import asset_sync
from app.schema.platform import (
    BulkRegenerateElementsRequest,
    RealPersonRequest,
    ElementCreateRequest,
    PropSizeRequest,
    ElementFolderCreateRequest,
    ElementFolderMoveRequest,
    ElementFolderUpdateRequest,
    ElementKind,
    ElementRevisionReason,
    ElementUpdateRequest,
    ElementVariantRequest,
    RegenerateElementRequest,
)


_WORDING_FILE = "element_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/element_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


router = APIRouter(prefix="/api/elements", tags=list(_words_of("module.tags")))
logger = logging.getLogger(__name__)
element_image_gateway = ModelGateway()
element_task_repository = TaskRepository()

#: 设定写法改了、图还是按旧写法画的：提示人重画，不自动花钱。重新生成后清掉。
NEEDS_REDRAW = "needs_redraw"
#: 定妆图画完后看图模型核对妆效的结论 ``{passed, problems}``；重画一次仍不合格就留在卡片上给人看。
LOOK_CHECK = "look_check"
# 定妆图展示板用的版式：决定切出来的三格特写各叫什么(见 core/look_board)。
LOOK_LAYOUT = "look_layout"
#: 看图模型多半先推理再作答：给少了答案还没写出来就被截断。
LOOK_CHECK_MAX_TOKENS = 8000
LOOK_CHECK_ATTEMPTS = 2
_NON_ACTOR_KINDS = {"scene", "prop", "effect", "extra", "vehicle", "stunt", "set_dressing"}
_generation_jobs: dict[str, dict[str, object]] = {}


def _private_image_storage_root() -> Path:
    root = settings.private_storage_dir("ELEMENT_IMAGE_STORAGE_DIR", "element_images", MEDIA_DIR)
    public_media_root = Path(MEDIA_DIR).resolve()
    if root == public_media_root or public_media_root in root.parents:
        raise RuntimeError("ELEMENT_IMAGE_STORAGE_DIR must be outside the public media directory")
    return root


# New reference images are never written beneath the public /media mount.  Keep
# the legacy root read-only so existing database rows can still be served by the
# authenticated content endpoint while installations migrate their files.
ELEMENT_MEDIA_ROOT = _private_image_storage_root()
LEGACY_ELEMENT_MEDIA_ROOT = Path(MEDIA_DIR) / "elements"
ELEMENT_MODEL_ROOT = settings.private_storage_dir("ELEMENT_MODEL_STORAGE_DIR", "element_models", MEDIA_DIR)


ELEMENT_STORAGE_MIN_FREE_BYTES = settings.env_int(
    "ELEMENT_STORAGE_MIN_FREE_BYTES", 5 * 1024**3, minimum=512 * 1024**2, maximum=1024**4
)
ELEMENT_STORAGE_MAX_USED_PERCENT = settings.env_int(
    "ELEMENT_STORAGE_MAX_USED_PERCENT", 98, minimum=80, maximum=99
)
ELEMENT_IMAGE_GENERATION_CONCURRENCY = settings.env_int(
    "ELEMENT_IMAGE_GENERATION_CONCURRENCY", 3, minimum=1, maximum=4
)


_GENERATION_KIND_PROMPTS = {
    # 场地出一张空景四视角(主场景全景 / 45°斜角 / 纵深视角 / 关键细节)的 2×2 四宫格，切成四张，见 core/scene_turnaround。
    "scene": SCENE_TURNAROUND_INSTRUCTION,
    "effect": (
        _text_of("module.generation_kind_prompts.effect")
    ),
}


# 多格版式的资产要指定画布尺寸，其余用图像模型默认尺寸。
_GENERATION_KIND_SIZES = {"scene": SCENE_TURNAROUND_SIZE}


def _element_metadata(item) -> dict:
    return item.metadata_json if isinstance(item.metadata_json, dict) else {}


async def _element_generation_context(item, owner_id: str) -> tuple[str, str]:
    """Resolve the project's selected image model and style without trusting foreign task ids."""
    task_id = str(_element_metadata(item).get("task_id") or "").strip()
    if not task_id:
        return "", ""
    try:
        task = await run_in_threadpool(element_task_repository.get_task, task_id)
    except TaskStoreUnavailableError:
        logger.warning("资产参考图生成时任务库不可用，改用默认图像模型", extra={"task_id": task_id})
        return "", ""
    if not task or str(task.get("owner_user_id") or "") != owner_id:
        return "", ""
    config = task.get("config") if isinstance(task.get("config"), dict) else {}
    style_parts = [
        str(config.get("director_style") or "").strip(),
        str(config.get("shot_style") or "").strip(),
        str(config.get("genre") or "").strip(),
    ]
    return str(config.get("image_model") or "").strip(), "，".join(part for part in style_parts if part)


def _prop_length(item) -> float | None:
    length = _element_metadata(item).get("prop_length_cm")
    return float(length) if isinstance(length, (int, float)) and length > 0 else None


def _prop_plan(item, extra_prompt: str = "") -> PropPlan:
    return plan_prop(str(item.name or ""), f"{item.description or ''} {extra_prompt}", length_cm=_prop_length(item))


def _element_reference_prompt(item, extra_prompt: str, project_style: str) -> str:
    description = str(item.description or "").strip()
    # 道具画几个视图看物件本身，见 core/prop_turnaround。
    kind_instruction = (
        prop_instruction(_prop_plan(item, extra_prompt)) if str(item.kind) == "prop"
        else _GENERATION_KIND_PROMPTS.get(str(item.kind), "")
    )
    prompt = (
        _text_of("_element_reference_prompt.prompt").format(kind_instruction, str(item.name).strip(), description or '按资产名称建立清晰、完整、可复用的影视参考设计')
    )
    if project_style:
        prompt += _text_of("_element_reference_prompt.text").format(project_style)
    if extra_prompt.strip():
        prompt += _text_of("_element_reference_prompt.text.2").format(extra_prompt.strip())
    if str(item.kind) == "effect":
        # 修仙特效先定形、分三层、颜色材质成对；武侠的内力画受力，不画发光体。
        prompt += wuxia_vfx.reference_rules(str(item.name or ""), description) + "\n"
    if str(item.kind) == "prop":
        # 修仙道具：丹药的丹纹丹香、飞剑、符箓、阵盘、法宝品阶的光；寻常器物照常。
        xianxia = xianxia_props.prop_rules(str(item.name or ""), description)
        return prompt + (f"{xianxia}\n" if xianxia else "") + PROP_CLOSING
    if str(item.kind) == "scene":
        scale_line = scene_scale.prompt_line(scene_scale.plan(str(item.name), description))
        # 修仙场地(洞府、秘境、藏经阁……)的样子；寻常场地照常。
        place_line = xianxia_props.place_rules(str(item.name or ""), description)
        return prompt + f"{scale_line}\n" + (f"{place_line}\n" if place_line else "") + SCENE_TURNAROUND_CLOSING
    return (
        prompt
        + _text_of("_element_reference_prompt.text.3")
    )


def _load_generated_image_bytes(url: str) -> bytes:
    value = str(url or "").strip()
    if value.startswith("data:image/"):
        try:
            encoded = value.split(",", 1)[1]
            content = base64.b64decode(encoded, validate=True)
        except (IndexError, ValueError) as exc:
            raise ValueError(_text_of("_load_generated_image_bytes.text")) from exc
        if len(content) > MAX_REMOTE_IMAGE_BYTES:
            raise ValueError(_text_of("_load_generated_image_bytes.text.2"))
        return content
    if value.startswith(("https://", "http://")):
        return fetch_remote_image_bytes(value)
    raise ValueError(_text_of("_load_generated_image_bytes.text.3"))


def _validated_generated_image(content: bytes) -> tuple[str, str]:
    signatures = (
        (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
        (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
        (b"RIFF", ".webp", "image/webp"),
    )
    detected = next((entry for entry in signatures if content.startswith(entry[0])), None)
    if detected is None:
        raise ValueError(_text_of("_validated_generated_image.text"))
    _, suffix, mime = detected
    validate_image_upload(f"generated{suffix}", mime, content, max_bytes=MAX_REMOTE_IMAGE_BYTES)
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ValueError(_text_of("_validated_generated_image.text.2")) from exc
    return suffix, mime


def _file(element_id: str, element_version: int, item) -> dict:
    is_model = item.mime_type == "model/gltf-binary"
    return {
        "id": item.id,
        "slot": item.slot,
        "mime_type": item.mime_type,
        "size_bytes": item.size_bytes,
        "sha256": item.sha256,
        "url": (
            None
            if is_model
            else f"/api/elements/{element_id}/files/{item.id}/content?v={element_version}"
        ),
        "media_kind": "model" if is_model else "image",
    }


def _model3d(item) -> dict | None:
    model = next((file for file in item.files if file.slot == "model_glb"), None)
    if not model:
        return None
    metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
    stored = metadata.get("model3d") if isinstance(metadata.get("model3d"), dict) else {}
    return {
        "schemaVersion": "element-model.v1",
        "state": "ready",
        "format": "glb",
        "contentUrl": f"/api/elements/{item.id}/model/content?v={item.version}",
        "sha256": model.sha256,
        "sizeBytes": model.size_bytes,
        "stats": stored.get("stats", {}),
        "validation": stored.get("validation", {"passed": True, "warnings": []}),
        "unit": stored.get("unit", "meter"),
        "upAxis": stored.get("upAxis", "Y"),
    }


def _prop_scale(item) -> dict:
    plan, manual = _prop_plan(item), _prop_length(item)
    return {
        "longest_cm": plan.longest_cm,
        "manual_cm": manual,
        "source": plan.size_source,
        # 参照表里查到的长宽高，给人看是按什么定的。
        "size_text": plan.size_text,
    }


def _scene_scale(item) -> dict:
    plan = scene_scale.plan(str(item.name), str(item.description or ""))
    return {"text": plan.text(), "source": plan.source}


def _element(item) -> dict:
    return {
        **({"prop_scale": _prop_scale(item)} if str(item.kind) == "prop" else {}),
        **({"scene_scale": _scene_scale(item)} if str(item.kind) == "scene" else {}),
        "id": item.id,
        "kind": item.kind,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "version": item.version,
        "metadata": item.metadata_json,
        "files": [_file(item.id, item.version, file) for file in item.files],
        "model3d": _model3d(item),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _element_snapshot(view: dict, owner_id: str) -> dict:
    """asset_sync 要的那几项，取自刚返回的资产视图。"""
    return {
        "id": view.get("id"),
        "owner_id": owner_id,
        "kind": str(view.get("kind") or ""),
        "name": view.get("name"),
        "description": view.get("description") or "",
        "version": view.get("version"),
        "metadata": view.get("metadata") if isinstance(view.get("metadata"), dict) else {},
    }


async def _synced(
    view, owner_id: str, reason: ElementRevisionReason, *, old_name: str | None = None,
):
    """资产改动已提交：通知挂着它的项目，结果放进响应的 ``sync``。同步失败只记日志，不让这次请求失败。"""
    if not isinstance(view, dict) or not view.get("id"):
        return view
    try:
        sync = await run_in_threadpool(
            asset_sync.element_changed, _element_snapshot(view, owner_id), reason=reason, old_name=old_name,
        )
    except Exception as exc:  # noqa: BLE001 - 资产已改好，项目同步失败不能把请求也拖失败
        logger.warning("资产改动同步到项目失败: element=%s reason=%s error=%s", view.get("id"), reason, exc)
        sync = {"error": str(exc) or type(exc).__name__}
    return {**view, "sync": sync}


async def _trimming_history(owner_id: str, element_id: str, mutate):
    """跑一次会记版本的改动：被裁掉的旧版本独占的文件提交前先隔离，提交成功清掉，失败放回原处。"""
    quarantine = _DeletionQuarantine(owner_id, element_id, operation="history")
    try:
        result = await mutate(quarantine.stage)
    except StorageMutationCommittedWithError as committed:
        quarantine.purge()
        raise committed.original_error from committed
    except BaseException as exc:
        _restore_quarantine(quarantine, exc)
        raise
    quarantine.purge()
    return result


@router.get("")
async def list_elements(
    kind: ElementKind,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    task_id: str | None = Query(None, max_length=120),
    folder: str | None = Query(None, max_length=36, description=_text_of("list_elements.description")),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    # With task_id only the project's own and linked assets are listed; the
    # rest of the owner's library stays stored but out of the project's view.
    items, total = await store.list_elements(
        user["user_id"], kind, page, page_size, task_id=(task_id or "").strip() or None, folder=(folder or "").strip() or None,
    )
    placed = await store.element_folder_ids(user["user_id"], [item.id for item in items])
    return {
        "items": [{**_element(item), "folder_id": placed.get(item.id)} for item in items],
        "page": page, "page_size": page_size, "total": total,
    }


@router.post("")
async def create_element(
    request: ElementCreateRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        safe_metadata = {key: value for key, value in request.metadata.items() if key != "model3d"}
        item = await store.create_element(
            owner_id=user["user_id"], kind=request.kind, name=request.name,
            description=request.description, metadata=safe_metadata,
        )
        item = await store.get_element(item.id, user["user_id"])
        return _element(item)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _cover_url(cover) -> str | None:
    image = next((file for file in (cover.files if cover else []) if file.mime_type != "model/gltf-binary"), None)
    return _file(cover.id, cover.version, image)["url"] if image else None


async def _folders_view(store: PlatformStore, owner_id: str, kind: ElementKind | None) -> dict:
    listing = await store.list_element_folders(owner_id, kind)
    return {
        "folders": [
            {
                "id": entry["folder"].id, "name": entry["folder"].name, "count": entry["count"],
                # A cover whose element was deleted reads as no cover.
                "cover_element_id": entry["cover"].id if entry["cover"] else None,
                "cover_url": _cover_url(entry["cover"]),
            }
            for entry in listing["folders"]
        ],
        "total": listing["total"],
        "unfiled": listing["unfiled"],
    }


# These sit above /{element_id}, which would otherwise take "folders" for an id.
@router.get("/folders")
async def list_element_folders(
    kind: ElementKind | None = None,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    return await _folders_view(store, user["user_id"], kind)


@router.post("/folders", status_code=201)
async def create_element_folder(
    request: ElementFolderCreateRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        folder = await store.create_element_folder(user["user_id"], request.name, request.cover_element_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": folder.id, "name": folder.name}


@router.post("/folders/move")
async def move_elements_to_folder(
    request: ElementFolderMoveRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """File elements in a folder, or take them out with ``folder_id: null``."""
    try:
        moved = await store.move_elements_to_folder(user["user_id"], request.element_ids, request.folder_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"moved": moved, "folder_id": request.folder_id}


@router.patch("/folders/{folder_id}")
async def update_element_folder(
    folder_id: str,
    request: ElementFolderUpdateRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        folder = await store.update_element_folder(
            user["user_id"], folder_id, name=request.name, cover_element_id=request.cover_element_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if folder is None:
        raise HTTPException(status_code=404, detail=_text_of("update_element_folder.detail"))
    return {"id": folder.id, "name": folder.name, "cover_element_id": folder.cover_element_id}


@router.delete("/folders/{folder_id}")
async def delete_element_folder(
    folder_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """Delete the folder only; its elements go back to unfiled."""
    if not await store.delete_element_folder(user["user_id"], folder_id):
        raise HTTPException(status_code=404, detail=_text_of("delete_element_folder.detail"))
    return {"deleted": True}


@router.get("/{element_id}")
async def get_element(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    item = await store.get_element(element_id, user["user_id"])
    if not item:
        raise HTTPException(status_code=404, detail=_text_of("get_element.detail"))
    placed = await store.element_folder_ids(user["user_id"], [item.id])
    return {**_element(item), "folder_id": placed.get(item.id)}


@router.put("/{element_id}/variant")
async def set_element_variant(
    element_id: str,
    request: ElementVariantRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """Make an actor element a derived look of another character (少年 / 婚纱 / 受伤后 …)."""
    item = await store.get_element(element_id, user["user_id"])
    if not item:
        raise HTTPException(status_code=404, detail=_text_of("set_element_variant.detail"))
    try:
        # 表单只有一段集数和这几个字段：定妆图的来源和分散的集数跟着条目走，见 clean_variant。
        # 改过的定妆图记下来，之后同步剧本不再覆盖。
        current = character_variants.variant_of({"metadata": _element_metadata(item)}) or {}
        facts = character_variants.clean_variant(
            {
                **request.model_dump(),
                **{key: current.get(key) for key in ("source", "spans", "outfit", "makeups", "starts")},
                "edited": current.get("source") == character_variants.LOOK_SOURCE,
            },
            element_name=item.name,
        )
        updated = await _trimming_history(
            user["user_id"], element_id,
            lambda hook: store.set_element_variant(element_id, user["user_id"], facts, before_commit=hook),
        )
    except character_variants.VariantError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _synced(_element(updated), user["user_id"], "variant")


@router.delete("/{element_id}/variant")
async def clear_element_variant(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        updated = await _trimming_history(
            user["user_id"], element_id,
            lambda hook: store.set_element_variant(element_id, user["user_id"], None, before_commit=hook),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await _synced(_element(updated), user["user_id"], "variant")


@router.patch("/{element_id}")
async def update_element(
    element_id: str,
    request: ElementUpdateRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    before = await store.get_element(element_id, user["user_id"])
    try:
        updated = await _trimming_history(
            user["user_id"], element_id,
            lambda hook: store.update_element(
                element_id, user["user_id"], name=request.name, description=request.description, before_commit=hook,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    renamed = before is not None and before.name != updated.name
    result = _element(updated)
    # 描述里改了尺寸，比例总览上的数字也要跟着变。
    if str(updated.kind) == "prop" and before and _prop_plan(before).longest_cm != _prop_plan(updated).longest_cm:
        result = await _redraw_prop_board(updated, user["user_id"], store) or result
    elif str(updated.kind) == "scene" and before and _scene_scale(before) != _scene_scale(updated):
        result = await _redraw_scene_scale(updated, user["user_id"], store) or result
    return await _synced(
        result, user["user_id"], "rename" if renamed else "edit", old_name=before.name if renamed else None,
    )


@router.put("/{element_id}/prop-size")
async def set_prop_size(
    element_id: str,
    request: PropSizeRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """人填的最长边。比例总览当场重画，不调用图像模型；还没有新版视图的道具等下次生成时用。"""
    try:
        updated = await _trimming_history(
            user["user_id"], element_id,
            lambda hook: store.set_prop_length(element_id, user["user_id"], request.length_cm, before_commit=hook),
        )
    except ValueError as exc:
        status = 404 if _text_of("set_prop_size.status") in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    result = await _redraw_prop_board(updated, user["user_id"], store) or _element(updated)
    return await _synced(result, user["user_id"], "prop_size")


@router.post("/{element_id}/scene-scale")
async def draw_scene_scale(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """给已有主场景全景的场地画人物比例参照(比例尺、人形、尺寸)。只在本地画，不调用图像模型。"""
    item = await store.get_element(element_id, user["user_id"])
    if item is None:
        raise HTTPException(status_code=404, detail=_text_of("draw_scene_scale.detail"))
    if str(item.kind) != "scene":
        raise HTTPException(status_code=422, detail=_text_of("draw_scene_scale.detail.2"))
    result = await _redraw_scene_scale(item, user["user_id"], store)
    if result is None:
        raise HTTPException(status_code=409, detail=_text_of("draw_scene_scale.detail.3"))
    return await _synced(result, user["user_id"], "file")


@router.post("/{element_id}/scene-reverse")
async def draw_scene_reverse(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """给已有主场景全景的场地补一张反打视角空景(调用图像模型，一张图)。"""
    item = await store.get_element(element_id, user["user_id"])
    if item is None:
        raise HTTPException(status_code=404, detail=_text_of("draw_scene_reverse.detail"))
    if str(item.kind) != "scene":
        raise HTTPException(status_code=422, detail=_text_of("draw_scene_reverse.detail.2"))
    return await _synced(await _draw_scene_reverse(item, user["user_id"], store), user["user_id"], "file")


@router.post("/{element_id}/files")
async def upload_element_file(
    element_id: str,
    slot: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    element = await store.get_element(element_id, user["user_id"])
    if not element:
        raise HTTPException(status_code=404, detail=_text_of("upload_element_file.detail"))

    filename = file.filename or ""
    content = await file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
    try:
        mime = validate_image_upload(filename, file.content_type or "", content)
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    suffix = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }[mime]
    stored = await _persist_element_file(
        element_id=element_id,
        owner_id=user["user_id"],
        slot=slot,
        suffix=suffix,
        mime=mime,
        content=content,
        store=store,
    )
    return await _synced(stored, user["user_id"], "file")


def _safe_media_path(relative_path: Path | str, storage_root: Path | None = None) -> Path:
    root = (storage_root or ELEMENT_MEDIA_ROOT).resolve()
    absolute = (root / relative_path).resolve()
    if root not in absolute.parents:
        raise HTTPException(status_code=422, detail=_text_of("_safe_media_path.detail"))
    return absolute


def _safe_owned_media_path(
    relative_path: Path | str,
    storage_root: Path,
    owner_id: str,
    element_id: str,
) -> Path:
    root = storage_root.resolve()
    owned_element_root = (root / owner_id / element_id).resolve()
    if root not in owned_element_root.parents:
        raise HTTPException(status_code=422, detail=_text_of("_safe_owned_media_path.detail"))
    absolute = _safe_media_path(relative_path, storage_root)
    if owned_element_root not in absolute.parents:
        raise HTTPException(status_code=422, detail=_text_of("_safe_owned_media_path.detail.2"))
    return absolute


def _owned_reference_path(
    relative_path: Path | str,
    owner_id: str,
    element_id: str,
) -> tuple[Path, Path]:
    """Resolve a private image, falling back to the authenticated legacy root."""
    candidates: list[tuple[Path, Path]] = []
    for root in (ELEMENT_MEDIA_ROOT, LEGACY_ELEMENT_MEDIA_ROOT):
        resolved_root = root.resolve()
        if any(existing_root == resolved_root for _, existing_root in candidates):
            continue
        try:
            candidate = _safe_owned_media_path(
                relative_path,
                resolved_root,
                owner_id,
                element_id,
            )
        except HTTPException:
            continue
        candidates.append((candidate, resolved_root))
        if candidate.is_file():
            return candidate, resolved_root
    if not candidates:
        raise HTTPException(status_code=422, detail=_text_of("_owned_reference_path.detail"))
    return candidates[0]


def _remove_file(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@dataclass(frozen=True)
class _QuarantinedFile:
    original: Path
    quarantined: Path
    manifest: Path


class _DeletionQuarantine:
    """Moves public files aside atomically before their database rows commit."""

    def __init__(self, owner_id: str, element_id: str, *, operation: str = "delete"):
        self.owner_id = owner_id
        self.element_id = element_id
        self.operation = operation
        self.transaction_id = uuid.uuid4().hex
        self._files: list[_QuarantinedFile] = []

    @staticmethod
    def _root(storage_root: Path) -> Path:
        resolved = storage_root.resolve()
        # ELEMENT_MEDIA_ROOT lives directly inside the public StaticFiles
        # mount, so its sibling would still be web-readable. Place quarantine
        # beside that mount instead. os.replace verifies the same-filesystem
        # assumption and fails closed on EXDEV.
        public_container = resolved.parent
        return (
            public_container.parent
            / f".{public_container.name}-{resolved.name}-quarantine"
        )

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_manifest(self, item: _QuarantinedFile) -> None:
        item.manifest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = item.manifest.with_suffix(".tmp")
        payload = {
            "schema_version": "element-quarantine.v1",
            "transaction_id": self.transaction_id,
            "owner_id": self.owner_id,
            "element_id": self.element_id,
            "operation": self.operation,
            "original_path": str(item.original),
            "quarantined_path": str(item.quarantined),
        }
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, item.manifest)
            self._fsync_directory(item.manifest.parent)
        except BaseException:
            _remove_file(temporary)
            raise

    @staticmethod
    def _cleanup_empty_directories(item: _QuarantinedFile) -> None:
        for directory in (item.manifest.parent, item.manifest.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                pass

    @staticmethod
    def _mapping(item: _QuarantinedFile) -> str:
        return f"original={item.original} quarantined={item.quarantined} manifest={item.manifest}"

    def log_stranded(self, message: str) -> None:
        for item in self._files:
            logger.error(
                "%s: %s",
                message,
                self._mapping(item),
                extra={"owner_id": self.owner_id, "element_id": self.element_id},
            )

    async def stage(self, files) -> dict[str, object]:
        skipped_ids: list[str] = []
        missing_ids: list[str] = []
        try:
            for item in files:
                try:
                    if item.mime_type == "model/gltf-binary":
                        storage_root = ELEMENT_MODEL_ROOT.resolve()
                        original = _safe_owned_media_path(
                            item.storage_path,
                            storage_root,
                            self.owner_id,
                            self.element_id,
                        )
                    else:
                        original, storage_root = _owned_reference_path(
                            item.storage_path,
                            self.owner_id,
                            self.element_id,
                        )
                except HTTPException:
                    skipped_ids.append(item.id)
                    logger.warning(
                        "%s cleanup skipped path outside owned element directory",
                        self.operation,
                        extra={
                            "owner_id": self.owner_id,
                            "element_id": self.element_id,
                            "file_id": item.id,
                        },
                    )
                    continue
                if not original.is_file():
                    missing_ids.append(item.id)
                    continue

                quarantine_root = self._root(storage_root)
                transaction_root = quarantine_root / self.transaction_id
                file_token = uuid.uuid4().hex
                quarantined = transaction_root / f"{file_token}.asset"
                manifest = transaction_root / f"{file_token}.json"
                quarantined_file = _QuarantinedFile(original, quarantined, manifest)
                self._write_manifest(quarantined_file)
                self._files.append(quarantined_file)
                os.replace(original, quarantined)
        except OSError as exc:
            try:
                self.restore()
            except OSError:
                self.log_stranded("failed to restore partially quarantined element files")
            raise HTTPException(status_code=500, detail=_text_of("stage.detail")) from exc
        return {
            "quarantined_count": len(self._files),
            "skipped_unowned_file_ids": skipped_ids,
            "missing_file_ids": missing_ids,
        }

    def restore(self) -> None:
        failures: list[OSError] = []
        remaining: list[_QuarantinedFile] = []
        for item in reversed(self._files):
            if not item.quarantined.exists() and item.original.exists():
                _remove_file(item.manifest)
                self._cleanup_empty_directories(item)
                continue
            try:
                item.original.parent.mkdir(parents=True, exist_ok=True)
                os.replace(item.quarantined, item.original)
                _remove_file(item.manifest)
                self._cleanup_empty_directories(item)
            except OSError as exc:
                failures.append(exc)
                remaining.append(item)
        self._files = list(reversed(remaining))
        if failures:
            raise OSError(_text_of("restore.text")) from failures[0]

    def purge(self) -> None:
        remaining: list[_QuarantinedFile] = []
        for item in self._files:
            if not _remove_file(item.quarantined):
                logger.warning(
                    "failed to purge non-public element quarantine file: %s",
                    self._mapping(item),
                    extra={
                        "owner_id": self.owner_id,
                        "element_id": self.element_id,
                    },
                )
                remaining.append(item)
                continue
            _remove_file(item.manifest)
            self._cleanup_empty_directories(item)
        self._files = remaining


def _restore_quarantine(plan: _DeletionQuarantine, error: BaseException) -> None:
    try:
        plan.restore()
    except OSError as restore_error:
        plan.log_stranded("database mutation failed and quarantined files could not all be restored")
        error.add_note(f"quarantine restore failed: {restore_error}")


def _ensure_disk_capacity(storage_root: Path, incoming_bytes: int) -> None:
    probe = storage_root
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    projected_free = usage.free - incoming_bytes
    projected_used_percent = ((usage.used + incoming_bytes) / usage.total) * 100
    if (
        projected_free < ELEMENT_STORAGE_MIN_FREE_BYTES
        or projected_used_percent >= ELEMENT_STORAGE_MAX_USED_PERCENT
    ):
        raise HTTPException(status_code=507, detail=_text_of("_ensure_disk_capacity.detail"))


async def _persist_element_file(
    *,
    element_id: str,
    owner_id: str,
    slot: str,
    suffix: str,
    mime: str,
    content: bytes,
    store: PlatformStore,
    model_metadata: dict | None = None,
    storage_root: Path | None = None,
) -> dict:
    target_root = storage_root or ELEMENT_MEDIA_ROOT
    relative_dir = Path(owner_id) / element_id
    relative_path = relative_dir / f"{uuid.uuid4().hex}{suffix}"
    absolute = _safe_media_path(relative_path, target_root)
    _ensure_disk_capacity(target_root, len(content))
    absolute.parent.mkdir(parents=True, exist_ok=True)
    try:
        await run_in_threadpool(absolute.write_bytes, content)
    except (Exception, asyncio.CancelledError):
        _remove_file(absolute)
        raise
    quarantine = _DeletionQuarantine(owner_id, element_id, operation="replacement")
    try:
        stored = await store.add_element_file(
            element_id=element_id,
            owner_id=owner_id,
            slot=slot,
            storage_path=str(relative_path),
            mime_type=mime,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            model_metadata=model_metadata,
            before_commit=quarantine.stage,
        )
    except StorageMutationCommittedWithError as committed:
        quarantine.purge()
        raise committed.original_error from committed
    except ValueError as exc:
        _restore_quarantine(quarantine, exc)
        _remove_file(absolute)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BaseException as exc:
        _restore_quarantine(quarantine, exc)
        _remove_file(absolute)
        raise
    quarantine.purge()
    return _element(stored.element)


@router.delete("/{element_id}/files/{file_id}")
async def delete_element_file(
    element_id: str,
    file_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    return await _synced(await _drop_element_file(element_id, file_id, user["user_id"], store), user["user_id"], "file_delete")


async def _drop_element_file(element_id: str, file_id: str, owner_id: str, store: PlatformStore) -> dict:
    quarantine = _DeletionQuarantine(owner_id, element_id)
    try:
        deleted = await store.delete_element_file(
            element_id,
            file_id,
            owner_id,
            before_commit=quarantine.stage,
        )
    except StorageMutationCommittedWithError as committed:
        quarantine.purge()
        raise committed.original_error from committed
    except ValueError as exc:
        _restore_quarantine(quarantine, exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BaseException as exc:
        _restore_quarantine(quarantine, exc)
        raise
    quarantine.purge()
    return _element(deleted.element)


@router.get("/{element_id}/files/{file_id}/content")
async def get_element_file_content(
    element_id: str,
    file_id: str,
    version: int = Query(..., alias="v", ge=1),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    element = await store.get_element(element_id, user["user_id"])
    if not element:
        raise HTTPException(status_code=404, detail=_text_of("get_element_file_content.detail"))
    if version != element.version:
        raise HTTPException(status_code=404, detail=_text_of("get_element_file_content.detail.2"))
    reference = next((entry for entry in element.files if entry.id == file_id), None)
    if not reference or reference.mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=404, detail=_text_of("get_element_file_content.detail.3"))
    try:
        absolute, _ = _owned_reference_path(
            reference.storage_path,
            user["user_id"],
            element_id,
        )
    except HTTPException as exc:
        raise HTTPException(status_code=404, detail=_text_of("get_element_file_content.detail.4")) from exc
    if not absolute.is_file():
        raise HTTPException(status_code=404, detail=_text_of("get_element_file_content.detail.5"))
    return FileResponse(
        absolute,
        media_type=reference.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "ETag": f'"{reference.sha256}"',
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{element_id}")
async def delete_element(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    quarantine = _DeletionQuarantine(user["user_id"], element_id)
    try:
        deleted = await store.delete_element(
            element_id,
            user["user_id"],
            before_commit=quarantine.stage,
        )
    except StorageMutationCommittedWithError as committed:
        quarantine.purge()
        raise committed.original_error from committed
    except ValueError as exc:
        _restore_quarantine(quarantine, exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BaseException as exc:
        _restore_quarantine(quarantine, exc)
        raise
    quarantine.purge()
    return {"id": deleted.element_id, "deleted": True}


@router.post("/{element_id}/model")
async def upload_element_model(
    element_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    element = await store.get_element(element_id, user["user_id"])
    if not element:
        raise HTTPException(status_code=404, detail=_text_of("upload_element_model.detail"))
    if element.kind not in {"prop", "scene"}:
        raise HTTPException(status_code=422, detail=_text_of("upload_element_model.detail.2"))

    content = await file.read(MAX_MODEL_UPLOAD_BYTES + 1)
    max_triangles = 1_000_000 if element.kind == "prop" else 2_000_000
    try:
        stats = await run_in_threadpool(
            inspect_glb_upload,
            file.filename or "",
            file.content_type or "",
            content,
            max_triangles=max_triangles,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    recommended_triangles = 150_000 if element.kind == "prop" else 500_000
    warnings = []
    if stats["triangles"] > recommended_triangles:
        warnings.append(_text_of("upload_element_model.text").format(recommended_triangles))
    if len(content) > 5 * 1024 * 1024:
        warnings.append(_text_of("upload_element_model.text.2"))
    sha256 = hashlib.sha256(content).hexdigest()
    stored = await _persist_element_file(
        element_id=element_id,
        owner_id=user["user_id"],
        slot="model_glb",
        suffix=".glb",
        mime="model/gltf-binary",
        content=content,
        store=store,
        model_metadata={
            "schemaVersion": "element-model.v1",
            "format": "glb",
            "unit": "meter",
            "upAxis": "Y",
            "sourceHash": sha256,
            "stats": stats,
            "validation": {"passed": True, "warnings": warnings},
        },
        storage_root=ELEMENT_MODEL_ROOT,
    )
    return await _synced(stored, user["user_id"], "file")


@router.get("/{element_id}/model/content")
async def get_element_model_content(
    element_id: str,
    version: int | None = Query(default=None, alias="v", ge=1),
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    element = await store.get_element(element_id, user["user_id"])
    if not element:
        raise HTTPException(status_code=404, detail=_text_of("get_element_model_content.detail"))
    if version is not None and version != element.version:
        raise HTTPException(status_code=404, detail=_text_of("get_element_model_content.detail.2"))
    model = next((entry for entry in element.files if entry.slot == "model_glb"), None)
    if not model:
        raise HTTPException(status_code=404, detail=_text_of("get_element_model_content.detail.3"))
    absolute = _safe_media_path(model.storage_path, ELEMENT_MODEL_ROOT)
    if not absolute.is_file():
        raise HTTPException(status_code=404, detail=_text_of("get_element_model_content.detail.4"))
    return FileResponse(
        absolute,
        media_type="model/gltf-binary",
        headers={
            # Authenticated model responses must never be retained by a shared
            # browser/proxy cache and replayed after an account switch.
            "Cache-Control": "private, no-store",
            "ETag": f'"{model.sha256}"',
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _generate_non_actor_reference(
    *,
    item,
    owner_id: str,
    store: PlatformStore,
    extra_prompt: str = "",
) -> dict:
    if str(item.kind) not in _NON_ACTOR_KINDS:
        raise HTTPException(status_code=422, detail=_text_of("_generate_non_actor_reference.detail"))
    image_model, project_style = await _element_generation_context(item, owner_id)
    prompt = _element_reference_prompt(item, extra_prompt, project_style)
    prop_plan = _prop_plan(item, extra_prompt) if str(item.kind) == "prop" else None
    size = prop_plan.size if prop_plan else _GENERATION_KIND_SIZES.get(str(item.kind))
    try:
        generated_url, provider = await run_in_threadpool(
            element_image_gateway.generate_image,
            image_model,
            prompt,
            **({"size": size} if size else {}),
        )
        if not generated_url:
            raise RuntimeError(_text_of("_generate_non_actor_reference.text"))
        content = await run_in_threadpool(_load_generated_image_bytes, generated_url)
        suffix, mime = await run_in_threadpool(_validated_generated_image, content)
    except HTTPException:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning(
            "资产参考图生成失败: element=%s kind=%s provider=%s error=%s",
            item.id,
            item.kind,
            locals().get("provider"),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail=_text_of("_generate_non_actor_reference.detail.2"),
        ) from exc
    if prop_plan:
        return await _persist_prop_views(
            item=item, owner_id=owner_id, store=store, content=content, suffix=suffix, mime=mime, plan=prop_plan,
        )
    if str(item.kind) == "scene":
        result = await _persist_board_views(
            item=item, owner_id=owner_id, store=store, content=content, suffix=suffix, mime=mime,
            split=split_scene_turnaround, slots=SCENE_GRID_SLOTS, what=_text_of("_generate_non_actor_reference.what"),
        )
        current = await store.get_element(item.id, owner_id)
        result = (await _redraw_scene_scale(current, owner_id, store) if current else None) or result
        # 反打视角照着刚切好的全景另出一张；没出来不影响四视角，卡片上可以单独补。
        if current is not None:
            try:
                result = await _draw_scene_reverse(current, owner_id, store, extra_prompt=extra_prompt)
            except HTTPException as exc:
                logger.warning("场地反打视角生成失败: element=%s detail=%s", item.id, exc.detail)
                # 旧的反打是照上一版全景画的，和这版对不上：去掉，卡片上显示「点此生成」。
                for file in current.files:
                    if file.slot == SCENE_REVERSE_SLOT:
                        result = await _drop_element_file(item.id, file.id, owner_id, store)
        return result
    result = await _persist_element_file(
        element_id=item.id,
        owner_id=owner_id,
        slot="reference",
        suffix=suffix,
        mime=mime,
        content=content,
        store=store,
    )
    if _element_metadata(item).get(NEEDS_REDRAW):
        return _element(await store.merge_element_metadata(item.id, owner_id, {NEEDS_REDRAW: False}))
    return result


def _is_look(item) -> bool:
    return str(item.kind) == "actor" and character_variants.is_look({"metadata": _element_metadata(item)})


async def _generate_look_image(*, item, owner_id: str, store: PlatformStore, extra_prompt: str = "") -> dict:
    """角色穿好这套戏服的定妆图：以这名角色现有的正脸/全身为身份参考，没有身份参考就不出图。"""
    facts = character_variants.variant_of({"metadata": _element_metadata(item)}) or {}
    wanted = normalized_asset_name(facts.get("of"))
    task_ids = set(element_task_ids(_element_metadata(item)))
    bases = [
        other for other in await store.list_all_elements(owner_id, "actor")
        if wanted in element_name_keys(other.name, other.metadata_json) and not _is_look(other)
    ]
    bases.sort(key=lambda other: not task_ids & set(element_task_ids(_element_metadata(other))))
    reference = None
    for base in bases:
        reference = await run_in_threadpool(_actor_reference_bytes, base)
        if reference:
            break
    if not reference:
        raise HTTPException(status_code=422, detail=_text_of("_generate_look_image.detail").format(facts.get('of')))
    # 旧项目已经确认过的服装图、妆效图不白费：一起给模型当设计参考。
    earlier: list[bytes] = []
    worn = {normalized_asset_name(name) for name in character_variants.worn_names({"name": item.name, "metadata": _element_metadata(item)})}
    for kind in ("costume", "makeup"):
        for other in await store.list_all_elements(owner_id, kind):
            if worn & element_name_keys(other.name, other.metadata_json) and (content := await run_in_threadpool(_first_image_bytes, other)):
                earlier.append(content)
    image_model, project_style = await _element_generation_context(item, owner_id)
    wardrobe = str(item.description or "")
    try:
        references = []
        for picture in (reference, *earlier):
            _suffix, picture_mime = await run_in_threadpool(_validated_generated_image, picture)
            references.append(f"data:{picture_mime};base64,{base64.b64encode(picture).decode('ascii')}")

        async def draw(fix: str = "") -> tuple[bytes, str, str]:
            wanted = "\n".join(part for part in (extra_prompt.strip(), fix) if part)
            prompt = look_prompt(str(item.name or ""), wardrobe, project_style, wanted, earlier_designs=len(earlier))
            generated_url, _provider = await run_in_threadpool(
                lambda: element_image_gateway.generate_image(
                    image_model, prompt, ref_images=references, size=LOOK_BOARD_SIZE, require_reference_support=True,
                )
            )
            if not generated_url:
                raise RuntimeError(_text_of("draw.text"))
            drawn = await run_in_threadpool(_load_generated_image_bytes, generated_url)
            drawn_suffix, drawn_mime = await run_in_threadpool(_validated_generated_image, drawn)
            return drawn, drawn_suffix, drawn_mime

        # 上一张没过核对：这次一开始就带着它的问题画，不白花第一张。描述改过的，旧问题不算数。
        earlier_check = _element_metadata(item).get(LOOK_CHECK)
        earlier_fix = (
            look_fix_prompt(list(earlier_check.get("problems") or []), wardrobe)
            if wears_makeup(wardrobe) and not _element_metadata(item).get(NEEDS_REDRAW)
            and isinstance(earlier_check, dict) and earlier_check.get("passed") is False and earlier_check.get("problems")
            else ""
        )
        content, suffix, mime = await draw(earlier_fix)
        check = await _check_look(content, wardrobe) if wears_makeup(wardrobe) else None
        if check is not None and not check["passed"]:
            try:
                redrawn = await draw(look_fix_prompt(check["problems"], wardrobe))
            except (OSError, RuntimeError, ValueError) as exc:  # 重画没出来，留第一张和它的问题
                logger.warning("定妆图按核对问题重画失败: element=%s error=%s", item.id, type(exc).__name__)
            else:
                content, suffix, mime = redrawn
                check = await _check_look(content, wardrobe)
    except HTTPException:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("角色定妆图生成失败: element=%s error=%s", item.id, type(exc).__name__)
        raise HTTPException(status_code=502, detail=_text_of("_generate_look_image.detail.2")) from exc
    # 定妆图是整张展示板，放在分镜优先取的正面槽；切出来的七张单独存，给人点开放大看。
    await _persist_element_file(
        element_id=item.id, owner_id=owner_id, slot="front", suffix=suffix, mime=mime, content=content, store=store,
    )
    await _persist_look_views(item.id, owner_id, store, content)
    layout = LAYOUT_MAKEUP if wears_makeup(wardrobe) else LAYOUT_PLAIN
    return _element(await store.merge_element_metadata(item.id, owner_id, {NEEDS_REDRAW: False, LOOK_CHECK: check, LOOK_LAYOUT: layout}))


async def _persist_look_views(element_id: str, owner_id: str, store: PlatformStore, content: bytes) -> None:
    """把展示板切成四格全身、三格特写存进各自的槽位。切不开时去掉旧板留下的那几张，免得和新板对不上。"""
    try:
        views = await run_in_threadpool(split_look_board, content)
    except (OSError, ValueError) as exc:
        logger.warning("定妆图展示板切分失败，只留整板: element=%s error=%s", element_id, type(exc).__name__)
        current = await store.get_element(element_id, owner_id)
        for file in (current.files if current else []):
            if file.slot in LOOK_VIEW_SLOTS:
                await _drop_element_file(element_id, file.id, owner_id, store)
        return
    for slot, image in views.items():
        await _persist_element_file(
            element_id=element_id, owner_id=owner_id, slot=slot, suffix=".png", mime="image/png", content=image, store=store,
        )


async def _check_look(content: bytes, wardrobe: str) -> dict | None:
    """看图模型核对这张定妆图的妆效；没有看图模型、没答或答不清时返回 None，不拦出图。

    推理型看图模型偶尔想过了头、没写出答案，这种情况再问一次。
    """
    try:
        picture = await run_in_threadpool(_look_check_image, content)
        for _attempt in range(LOOK_CHECK_ATTEMPTS):
            answer, used = await run_in_threadpool(
                lambda: element_image_gateway.describe_image(
                    "", LOOK_CHECK_SYSTEM, look_check_prompt(wardrobe), picture, max_tokens=LOOK_CHECK_MAX_TOKENS,
                )
            )
            if not used:
                return None
            if check := parse_look_check(answer):
                return {**check, "model": used}
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("定妆图妆效核对失败: error=%s", type(exc).__name__)
    return None


def _look_check_image(content: bytes) -> str:
    """缩到看图模型收得下、特写还看得清伤口的 JPEG。"""
    with Image.open(io.BytesIO(content)) as image:
        image = image.convert("RGB")
        image.thumbnail((2048, 2048))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


async def _persist_prop_views(
    *, item, owner_id: str, store: PlatformStore, content: bytes, suffix: str, mime: str, plan: PropPlan,
) -> dict:
    """道具的各个视图、比例总览和主参考图。这一版不画的视图从上一版里清掉，免得新旧混在一起。"""
    try:
        views = await run_in_threadpool(split_prop_sheet, content, plan)
    except (OSError, ValueError) as exc:
        logger.warning("道具视图切分失败，整张存为参考图: element=%s error=%s", item.id, type(exc).__name__)
        return await _persist_element_file(
            element_id=item.id, owner_id=owner_id, slot="reference", suffix=suffix, mime=mime,
            content=content, store=store,
        )
    try:
        views[PROP_BOARD_SLOT] = await run_in_threadpool(compose_prop_board, plan, views)
    except (OSError, ValueError) as exc:  # 总览画不出来，视图还在
        logger.warning("道具比例总览生成失败: element=%s error=%s", item.id, type(exc).__name__)
    for slot, image in views.items():
        await _persist_element_file(
            element_id=item.id, owner_id=owner_id, slot=slot, suffix=".png", mime="image/png",
            content=image, store=store,
        )
    result = await _persist_element_file(
        element_id=item.id, owner_id=owner_id, slot="reference", suffix=".png", mime="image/png",
        content=views[plan.views[0]], store=store,
    )
    current = await store.get_element(item.id, owner_id)
    for file in (current.files if current else []):
        if file.slot in PROP_ALL_SLOTS and file.slot not in views:
            result = await _drop_element_file(item.id, file.id, owner_id, store)
    return result


async def _redraw_prop_board(item, owner_id: str, store: PlatformStore) -> dict | None:
    """用已存的视图按现在的尺寸重画比例总览。旧版四视图没有比例参照格，画不了，返回 None。"""
    files = {file.slot: file for file in item.files}
    plan = _prop_plan(item)
    views = tuple(slot for slot in (*plan.views, *PROP_VIEWS) if slot in files)
    views = tuple(dict.fromkeys(views))
    if PROP_REFERENCE_SLOT not in files or not views:
        return None
    plan = replace(plan, views=views, measured=tuple(slot for slot in plan.measured if slot in files) or views[:1])

    def draw() -> bytes:
        stored = {
            slot: _owned_reference_path(files[slot].storage_path, owner_id, item.id)[0].read_bytes()
            for slot in plan.slots
        }
        return compose_prop_board(plan, stored)

    try:
        board = await run_in_threadpool(draw)
    except (HTTPException, OSError, ValueError) as exc:
        logger.warning("道具比例总览重画失败: element=%s error=%s", item.id, type(exc).__name__)
        return None
    return await _persist_element_file(
        element_id=item.id, owner_id=owner_id, slot=PROP_BOARD_SLOT, suffix=".png", mime="image/png",
        content=board, store=store,
    )


async def _redraw_scene_scale(item, owner_id: str, store: PlatformStore) -> dict | None:
    """用已存的主场景全景按现在的尺寸画人物比例参照；不调用图像模型。没有全景时返回 None。"""
    main = next((file for file in item.files if file.slot == SCENE_VIEW_SLOTS[0]), None)
    if main is None:
        return None
    plan = scene_scale.plan(str(item.name), str(item.description or ""))

    def draw() -> bytes:
        return scene_scale.compose(_owned_reference_path(main.storage_path, owner_id, item.id)[0].read_bytes(), plan)

    try:
        board = await run_in_threadpool(draw)
    except (HTTPException, OSError, ValueError) as exc:
        logger.warning("场地人物比例参照生成失败: element=%s error=%s", item.id, type(exc).__name__)
        return None
    return await _persist_element_file(
        element_id=item.id, owner_id=owner_id, slot=scene_scale.SCENE_SCALE_SLOT, suffix=".png", mime="image/png",
        content=board, store=store,
    )


def _scene_reverse_prompt(item, extra_prompt: str, project_style: str) -> str:
    """反打视角空景的提示词：以主场景全景为参考图，场地描述、尺寸和修仙场地的写法与四宫格同一套。"""
    description = str(item.description or "").strip()
    lines = [
        EMPTY_SCENE_PREFIX + prompt_data.text("scene_views", "reverse_view_instruction"),
        _text_of("_scene_reverse_prompt.lines").format(str(item.name).strip()),
        _text_of("_scene_reverse_prompt.lines.2").format(description or '按资产名称建立清晰、完整、可复用的影视参考设计'),
        _text_of("_scene_reverse_prompt.lines.3").format(project_style) if project_style else "",
        _text_of("_scene_reverse_prompt.lines.4").format(extra_prompt.strip()) if extra_prompt.strip() else "",
        scene_scale.prompt_line(scene_scale.plan(str(item.name), description)),
        xianxia_props.place_rules(str(item.name or ""), description),
        prompt_data.text("scene_views", "reverse_view_closing") + EMPTY_SCENE_SUFFIX,
    ]
    return "\n".join(line for line in lines if line)


async def _draw_scene_reverse(item, owner_id: str, store: PlatformStore, *, extra_prompt: str = "") -> dict:
    """以已存的主场景全景为参考，出一张反打视角空景存进 ``scene_reverse``(付费，一张图)。"""
    main = next((file for file in item.files if file.slot == SCENE_VIEW_SLOTS[0]), None)
    if main is None:
        raise HTTPException(status_code=409, detail=_text_of("_draw_scene_reverse.detail"))
    image_model, project_style = await _element_generation_context(item, owner_id)
    prompt = _scene_reverse_prompt(item, extra_prompt, project_style)
    try:
        plate = await run_in_threadpool(lambda: _owned_reference_path(main.storage_path, owner_id, item.id)[0].read_bytes())
        _suffix, plate_mime = await run_in_threadpool(_validated_generated_image, plate)
        reference = f"data:{plate_mime};base64,{base64.b64encode(plate).decode('ascii')}"
        generated_url, _provider = await run_in_threadpool(
            lambda: element_image_gateway.generate_image(
                image_model, prompt, ref_images=[reference], size=SCENE_TURNAROUND_SIZE, require_reference_support=True,
            )
        )
        if not generated_url:
            raise RuntimeError(_text_of("_draw_scene_reverse.text"))
        content = await run_in_threadpool(_load_generated_image_bytes, generated_url)
        suffix, mime = await run_in_threadpool(_validated_generated_image, content)
    except HTTPException:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("场地反打视角生成失败: element=%s error=%s", item.id, type(exc).__name__)
        raise HTTPException(status_code=502, detail=_text_of("_draw_scene_reverse.detail.2")) from exc
    return await _persist_element_file(
        element_id=item.id, owner_id=owner_id, slot=SCENE_REVERSE_SLOT, suffix=suffix, mime=mime,
        content=content, store=store,
    )


async def _persist_board_views(
    *, item, owner_id: str, store: PlatformStore, content: bytes, suffix: str, mime: str,
    split, slots: tuple[str, ...], what: str,
) -> dict:
    """把四宫格切成各自的槽位：道具是正面 / 左45° / 右45° / 背面，场地是全景 / 45° / 纵深 / 细节。

    第一格(道具正面、场地全景)同时作为主参考图。切不开(图片损坏)时整张存成主参考图，至少不丢这次付费出的图。
    """
    try:
        views = await run_in_threadpool(split, content)
    except (OSError, ValueError) as exc:
        logger.warning("%s切分失败，整张存为参考图: element=%s error=%s", what, item.id, type(exc).__name__)
        return await _persist_element_file(
            element_id=item.id, owner_id=owner_id, slot="reference", suffix=suffix, mime=mime,
            content=content, store=store,
        )
    result: dict = {}
    for slot in slots:
        result = await _persist_element_file(
            element_id=item.id, owner_id=owner_id, slot=slot, suffix=".png", mime="image/png",
            content=views[slot], store=store,
        )
    return await _persist_element_file(
        element_id=item.id, owner_id=owner_id, slot="reference", suffix=".png", mime="image/png",
        content=views[slots[0]], store=store,
    ) or result


def _public_generation_job(job: dict[str, object]) -> dict[str, object]:
    return {
        "id": job["id"],
        "kind": job["kind"],
        "task_id": job.get("task_id"),
        "status": job["status"],
        "total": job["total"],
        "processed": job["processed"],
        "succeeded": job["succeeded"],
        "failed": job["failed"],
        "remaining": job["remaining"],
        "errors": list(job.get("errors") or []),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


def _prune_generation_jobs() -> None:
    if len(_generation_jobs) < 200:
        return
    completed = sorted(
        (
            job for job in _generation_jobs.values()
            if job.get("status") in {"completed", "partial", "failed"}
        ),
        key=lambda job: float(job.get("updated_at") or 0),
    )
    for job in completed[: max(0, len(_generation_jobs) - 150)]:
        _generation_jobs.pop(str(job["id"]), None)


async def _run_generation_job(
    job_id: str,
    items: list,
    *,
    owner_id: str,
    store: PlatformStore,
) -> None:
    job = _generation_jobs.get(job_id)
    if not job:
        return
    job["status"] = "running"
    job["updated_at"] = time.time()
    semaphore = asyncio.Semaphore(ELEMENT_IMAGE_GENERATION_CONCURRENCY)
    replace_existing = bool(job.get("replace_existing"))

    async def generate_one(item) -> None:
        async with semaphore:
            try:
                current = await store.get_element(item.id, owner_id)
                if not current:
                    raise ValueError(_text_of("generate_one.text"))
                if any(file.mime_type.startswith("image/") for file in current.files) and not replace_existing:
                    job["succeeded"] = int(job["succeeded"]) + 1
                elif _is_look(current):
                    await _synced(await _generate_look_image(item=current, owner_id=owner_id, store=store), owner_id, "file")
                    job["succeeded"] = int(job["succeeded"]) + 1
                else:
                    generated = await _generate_non_actor_reference(
                        item=current,
                        owner_id=owner_id,
                        store=store,
                        extra_prompt=_text_of("generate_one.extra_prompt"),
                    )
                    await _synced(generated, owner_id, "file")
                    job["succeeded"] = int(job["succeeded"]) + 1
            except (Exception, asyncio.CancelledError, BillingRefused) as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                job["failed"] = int(job["failed"]) + 1
                errors = job.get("errors")
                if isinstance(errors, list) and len(errors) < 20:
                    detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                    errors.append({"element_id": item.id, "name": item.name, "detail": str(detail)[:300]})
            finally:
                job["processed"] = int(job["succeeded"]) + int(job["failed"])
                job["remaining"] = max(0, int(job["total"]) - int(job["processed"]))
                job["updated_at"] = time.time()

    try:
        await asyncio.gather(*(generate_one(item) for item in items))
    except asyncio.CancelledError:
        job["status"] = "partial" if int(job["succeeded"]) else "failed"
        job["updated_at"] = time.time()
        raise
    else:
        job["status"] = "completed" if int(job["failed"]) == 0 else "partial"
        job["updated_at"] = time.time()


@router.post("/generation-jobs", status_code=202)
async def start_element_generation_job(
    request: BulkRegenerateElementsRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    looks_only = request.looks and request.kind == "actor"
    if request.kind not in _NON_ACTOR_KINDS and not looks_only:
        raise HTTPException(status_code=422, detail=_text_of("start_element_generation_job.detail"))
    owner_id = user["user_id"]
    items = await store.list_all_elements(owner_id, request.kind)
    task_id = str(request.task_id or "").strip()
    candidates = [
        item for item in items
        if (not task_id or element_in_task(_element_metadata(item), task_id))
        and (not looks_only or character_variants.is_current_look({"metadata": _element_metadata(item)}))
        and (
            request.replace_existing
            or not any(file.mime_type.startswith("image/") for file in item.files)
        )
    ]
    for existing in _generation_jobs.values():
        if (
            existing.get("owner_id") == owner_id
            and existing.get("kind") == request.kind
            and existing.get("task_id") == (task_id or None)
            and bool(existing.get("replace_existing")) == request.replace_existing
            and existing.get("status") in {"queued", "running"}
        ):
            return _public_generation_job(existing)

    _prune_generation_jobs()
    now = time.time()
    job_id = str(uuid.uuid4())
    job: dict[str, object] = {
        "id": job_id,
        "owner_id": owner_id,
        "kind": request.kind,
        "task_id": task_id or None,
        "replace_existing": request.replace_existing,
        "status": "queued" if candidates else "completed",
        "total": len(candidates),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "remaining": len(candidates),
        "errors": [],
        "created_at": now,
        "updated_at": now,
    }
    _generation_jobs[job_id] = job
    if candidates:
        background_tasks.add_task(
            _run_generation_job,
            job_id,
            candidates,
            owner_id=owner_id,
            store=store,
        )
    return _public_generation_job(job)


@router.get("/generation-jobs/{job_id}")
async def get_element_generation_job(
    job_id: str,
    user: dict = Depends(get_current_user),
):
    job = _generation_jobs.get(job_id)
    if not job or job.get("owner_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail=_text_of("get_element_generation_job.detail"))
    return _public_generation_job(job)


#: 资产库里数字演员「重新生成」的后台进度键（element.metadata_json）；超过这个时长仍是 running 视为服务重启中断。
ACTOR_REGENERATION_KEY = "regeneration"
ACTOR_REGENERATION_STALE_SECONDS = 15 * 60


def _actor_regenerating(metadata: dict) -> bool:
    state = metadata.get(ACTOR_REGENERATION_KEY)
    if not isinstance(state, dict) or state.get("status") != "running":
        return False
    try:
        started = float(state.get("started_epoch") or 0)
    except (TypeError, ValueError):
        return False
    return time.time() - started < ACTOR_REGENERATION_STALE_SECONDS


def _actor_reference_bytes(item) -> bytes | None:
    """现有的正脸/正面全身做身份参考；一张都没有就不带参考出图。"""
    files = {file.slot: file for file in item.files or [] if str(file.mime_type or "").startswith("image/")}
    for slot in ("face_front", "front", "face_three_quarter", "profile"):
        file = files.get(slot)
        if file is None:
            continue
        try:
            absolute, _ = _owned_reference_path(file.storage_path, item.owner_id, item.id)
        except HTTPException:
            continue
        if absolute.is_file():
            return absolute.read_bytes()
    return None


def _first_image_bytes(item) -> bytes | None:
    """这个条目的第一张图；读不到就算没有。"""
    for file in item.files or []:
        if not str(file.mime_type or "").startswith("image/"):
            continue
        try:
            absolute, _ = _owned_reference_path(file.storage_path, item.owner_id, item.id)
        except HTTPException:
            continue
        if absolute.is_file():
            return absolute.read_bytes()
    return None


def _media_url_bytes(url: str) -> bytes:
    """设定集切出的身份格都落在本地 /media 下；只读媒体根之内的文件。"""
    path = urlparse(str(url or "")).path
    if not path.startswith(settings.MEDIA_PREFIX):
        raise ValueError(_text_of("_media_url_bytes.text"))
    media_root = os.path.realpath(MEDIA_DIR)
    absolute = os.path.realpath(os.path.join(media_root, unquote(path[len(settings.MEDIA_PREFIX):])))
    if not absolute.startswith(media_root + os.sep) or not os.path.isfile(absolute):
        raise ValueError(_text_of("_media_url_bytes.text.2"))
    with open(absolute, "rb") as handle:
        return handle.read()


async def _file_actor_views(
    *, element_id: str, owner_id: str, store: PlatformStore, views: list, sheet: str,
) -> dict:
    """五个身份视图换进资产库演员对应槽位，返回要合进 metadata 的部分。

    先把五张都读出来并校验，再逐个替换：缺一张或读不到就一张都不换(抛 RuntimeError/ValueError)。
    """
    by_view = {
        str(view.get("view")): str(view.get("image_url") or "")
        for view in views if isinstance(view, dict)
    }
    missing = [view for view in IDENTITY_VIEW_ORDER if not by_view.get(view)]
    if missing:
        raise RuntimeError(_text_of("_file_actor_views.text") + "、".join(missing))
    prepared = []
    for view in IDENTITY_VIEW_ORDER:
        content = await run_in_threadpool(_media_url_bytes, by_view[view])
        suffix, mime = await run_in_threadpool(_validated_generated_image, content)
        prepared.append((view, suffix, mime, content))
    for view, suffix, mime, content in prepared:
        await _persist_element_file(
            element_id=element_id, owner_id=owner_id, slot=view,
            suffix=suffix, mime=mime, content=content, store=store,
        )
    return {
        "views": [{"view": view, "image_url": by_view[view]} for view in IDENTITY_VIEW_ORDER],
        "five_view_passed": True,
        **({"sheet_url": sheet} if sheet else {}),
    }


async def _sync_project_actor(
    *, owner_id: str, task_id: str, name: str, views: list, sheet: str, store: PlatformStore,
) -> int:
    """把项目里重新生成的身份视图换进资产库里挂在该项目的同名演员；返回同步了几个。"""
    wanted = normalized_asset_name(name)
    synced = 0
    for item in await store.list_all_elements(owner_id, "actor"):
        metadata = _element_metadata(item)
        if not element_in_task(metadata, task_id) or wanted not in element_name_keys(item.name, metadata):
            continue
        # 资产库那边发起的重新生成会自己把结果归档(它正标着 running)，这里不重复写。
        # 真人演员的照片就是身份，项目里画出来的视图不能换掉它。
        if _actor_regenerating(metadata) or real_person.is_real_person(metadata):
            continue
        try:
            patch = await _file_actor_views(
                element_id=item.id, owner_id=owner_id, store=store, views=views, sheet=sheet,
            )
            await store.merge_element_metadata(item.id, owner_id, {**patch, "synced_from_task": task_id})
            synced += 1
        except Exception as exc:  # noqa: BLE001 - 同步是尽力而为，项目里的新图已经落库
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            logger.warning("项目新图同步到资产库失败: element=%s error=%s", item.id, str(detail)[:200])
    return synced


def sync_project_actor_to_library(task: dict, name: str) -> int:
    """项目里某个角色重新生成成功后(在出图的工作线程里调用)，把新的身份视图同步到资产库。

    只动本人资产库里已挂到这个项目、名字对得上的数字演员；资产库里没有就什么都不做，
    也不新建。任何失败只记日志，不影响项目里已经换好的图。
    """
    owner_id = str(task.get("owner_user_id") or "").strip()
    task_id = str(task.get("task_id") or "").strip()
    record = next((
        item for item in (task.get("assets") or {}).get("3_characters") or []
        if isinstance(item, dict) and str(item.get("name") or "").strip() == name
    ), None)
    if not owner_id or not task_id or record is None:
        return 0
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        logger.warning("项目新图同步到资产库只能在工作线程里执行，本次跳过")
        return 0

    async def run() -> int:
        store = PlatformStore(settings.database_url())
        try:
            return await _sync_project_actor(
                owner_id=owner_id, task_id=task_id, name=name,
                views=list(record.get("views") or []), sheet=str(record.get("sheet") or ""), store=store,
            )
        finally:
            await store.close()

    try:
        return asyncio.run(run())
    except Exception as exc:  # noqa: BLE001
        logger.warning("项目新图同步到资产库失败: task=%s name=%s error=%s", task_id, name, type(exc).__name__)
        return 0


async def _regenerate_library_actor(element_id: str, owner_id: str, store: PlatformStore) -> None:
    """后台：重出设定集 → 五个身份视图替换进资产库对应槽位 → 记下完成或失败。失败时旧图原样保留。"""
    from app.api.drama_api import service as drama_service  # 与 drama_api 共用同一个服务实例

    patch: dict = {}
    error = ""
    try:
        item = await store.get_element(element_id, owner_id)
        if not item:
            raise RuntimeError(_text_of("_regenerate_library_actor.text"))
        metadata = _element_metadata(item)
        reference = await run_in_threadpool(_actor_reference_bytes, item)
        result = await run_in_threadpool(
            lambda: drama_service.regenerate_library_actor(
                owner_id=owner_id,
                name=str(item.name),
                name_keys=element_name_keys(item.name, metadata),
                desc=str(item.description or ""),
                task_ids=element_task_ids(metadata),
                reference=reference,
            )
        )
        patch = await _file_actor_views(
            element_id=element_id, owner_id=owner_id, store=store,
            views=result.get("views") or [], sheet=str(result.get("sheet") or ""),
        )
        refreshed = await store.get_element(element_id, owner_id)
        if refreshed is not None:
            await _synced(_element(refreshed), owner_id, "file")
    except (Exception, BillingRefused) as exc:  # noqa: BLE001 - 失败只记在该演员名下，旧图不动
        detail = exc.detail if isinstance(exc, (HTTPException, BillingRefused)) else str(exc)
        error = str(detail or "").strip()[:260] or _text_of("_regenerate_library_actor.error")
        logger.warning("资产库数字演员重新生成失败: element=%s error=%s", element_id, error)
    state = (
        {"status": "failed", "error": error, "finished_epoch": time.time()}
        if error else {"status": "done", "finished_epoch": time.time()}
    )
    try:
        await store.merge_element_metadata(element_id, owner_id, {**patch, ACTOR_REGENERATION_KEY: state})
    except ValueError:
        logger.warning("资产库数字演员重新生成结果写回失败: element=%s", element_id)


@router.put("/{element_id}/real-person")
async def set_real_person(
    element_id: str,
    request: RealPersonRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """设为真人演员：本人照片就是身份，按照片出分镜和视频。必须确认持有肖像授权。"""
    element = await store.get_element(element_id, user["user_id"])
    if not element or str(element.kind) != "actor" or _is_look(element):
        raise HTTPException(status_code=404, detail=_text_of("set_real_person.detail"))
    try:
        record = real_person.clean_record(
            person=request.person, scope=request.scope, expires=request.expires, ark_assets=request.ark_assets,
            confirmed=request.confirmed, confirmed_by=user["user_id"],
        )
        updated = await _trimming_history(
            user["user_id"], element.id,
            lambda hook: store.set_real_person(element.id, user["user_id"], record, before_commit=hook),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _synced(_element(updated), user["user_id"], "real_person")


@router.delete("/{element_id}/real-person")
async def clear_real_person(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """取消真人演员：照片留着，之后可以照常重新生成设定集。"""
    element = await store.get_element(element_id, user["user_id"])
    if not element or str(element.kind) != "actor":
        raise HTTPException(status_code=404, detail=_text_of("clear_real_person.detail"))
    try:
        updated = await _trimming_history(
            user["user_id"], element.id,
            lambda hook: store.set_real_person(element.id, user["user_id"], None, before_commit=hook),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _synced(_element(updated), user["user_id"], "real_person")


@router.post("/{element_id}/look-views")
async def split_look_views(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """把已经画好的定妆图展示板切成单张；不调用模型。较早的展示板按当时的版式(腰带、袖口特写)命名。"""
    element = await store.get_element(element_id, user["user_id"])
    if not element or not _is_look(element):
        raise HTTPException(status_code=404, detail=_text_of("split_look_views.detail"))
    board = next((file for file in element.files if file.slot == "front" and str(file.mime_type or "").startswith("image/")), None)
    if board is None:
        raise HTTPException(status_code=422, detail=_text_of("split_look_views.detail.2"))
    try:
        absolute, _ = _owned_reference_path(board.storage_path, element.owner_id, element.id)
        content = await run_in_threadpool(absolute.read_bytes)
    except (HTTPException, OSError) as exc:
        raise HTTPException(status_code=422, detail=_text_of("split_look_views.detail.3")) from exc
    await _persist_look_views(element.id, user["user_id"], store, content)
    patch = {} if _element_metadata(element).get(LOOK_LAYOUT) else {LOOK_LAYOUT: LAYOUT_PLAIN}
    updated = await store.merge_element_metadata(element.id, user["user_id"], patch) if patch else await store.get_element(element.id, user["user_id"])
    return await _synced(_element(updated), user["user_id"], "file")


@router.post("/{element_id}/regenerate")
async def regenerate_element(
    element_id: str,
    request: RegenerateElementRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    element = await store.get_element(element_id, user["user_id"])
    if not element:
        raise HTTPException(status_code=404, detail=_text_of("regenerate_element.detail"))
    if str(element.kind) in ("costume", "makeup"):
        raise HTTPException(status_code=422, detail=_text_of("regenerate_element.detail.2"))
    if _is_look(element):
        generated = await _generate_look_image(item=element, owner_id=user["user_id"], store=store, extra_prompt=request.prompt)
        return await _synced(generated, user["user_id"], "file")
    if str(element.kind) == "actor" and real_person.is_real_person(_element_metadata(element)):
        raise HTTPException(status_code=409, detail=_text_of("regenerate_element.detail.3"))
    if str(element.kind) in _NON_ACTOR_KINDS:
        generated = await _generate_non_actor_reference(
            item=element,
            owner_id=user["user_id"],
            store=store,
            extra_prompt=request.prompt,
        )
        return await _synced(generated, user["user_id"], "file")
    # 数字演员：后台重出一张设定集（付费），五个身份视图通过质检后替换；列表里的 metadata.regeneration 报进度。
    if _actor_regenerating(_element_metadata(element)):
        raise HTTPException(status_code=409, detail=_text_of("regenerate_element.detail.4").format(element.name))
    updated = await store.merge_element_metadata(
        element_id,
        user["user_id"],
        {ACTOR_REGENERATION_KEY: {"status": "running", "started_epoch": time.time()}},
    )
    background_tasks.add_task(_regenerate_library_actor, element_id, user["user_id"], store)
    response.status_code = 202
    return _element(updated)


def _revision_file_url(element_id: str, revision: int, slot: str) -> str:
    # 历史版本的文件不会再变，不用 ?v= 防缓存。
    return f"/api/elements/{element_id}/revisions/{revision}/files/{slot}/content"


def _revision(element_id: str, item) -> dict:
    return {
        "revision": item.revision,
        "version": item.version,
        "name": item.name,
        "description": item.description,
        "reason": item.reason,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "files": [
            {"slot": entry.get("slot"), "url": _revision_file_url(element_id, item.revision, str(entry.get("slot")))}
            for entry in item.files_json or []
            if isinstance(entry, dict) and entry.get("slot")
        ],
    }


@router.get("/{element_id}/revisions")
async def list_element_revisions(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """这个资产留着的旧版本(最多 REVISION_LIMIT 个)，最新的在前。"""
    try:
        revisions = await store.list_element_revisions(user["user_id"], element_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"items": [_revision(element_id, item) for item in revisions]}


@router.get("/{element_id}/revisions/{revision}/files/{slot}/content")
async def get_element_revision_file_content(
    element_id: str,
    revision: int,
    slot: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    item = await store.get_element_revision(user["user_id"], element_id, revision)
    if item is None:
        raise HTTPException(status_code=404, detail=_text_of("get_element_revision_file_content.detail"))
    entry = next((entry for entry in item.files_json or [] if isinstance(entry, dict) and entry.get("slot") == slot), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=_text_of("get_element_revision_file_content.detail.2"))
    mime = str(entry.get("mime_type") or "")
    try:
        if mime == "model/gltf-binary":
            absolute = _safe_owned_media_path(entry.get("storage_path") or "", ELEMENT_MODEL_ROOT, user["user_id"], element_id)
        elif mime in {"image/png", "image/jpeg", "image/webp"}:
            absolute, _ = _owned_reference_path(entry.get("storage_path") or "", user["user_id"], element_id)
        else:
            raise HTTPException(status_code=404, detail=_text_of("get_element_revision_file_content.detail.3"))
    except HTTPException as exc:
        raise HTTPException(status_code=404, detail=_text_of("get_element_revision_file_content.detail.4")) from exc
    if not absolute.is_file():
        raise HTTPException(status_code=404, detail=_text_of("get_element_revision_file_content.detail.5"))
    return FileResponse(
        absolute,
        media_type=mime,
        headers={
            "Cache-Control": "private, no-store",
            "ETag": f'"{entry.get("sha256") or ""}"',
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{element_id}/revisions/{revision}/restore")
async def restore_element_revision(
    element_id: str,
    revision: int,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """回到某个旧版本；现在这一版先记进历史，所以恢复本身也能再撤回。"""
    before = await store.get_element(element_id, user["user_id"])
    if before is None:
        raise HTTPException(status_code=404, detail=_text_of("restore_element_revision.detail"))
    try:
        restored = await _trimming_history(
            user["user_id"], element_id,
            lambda hook: store.restore_element_revision(user["user_id"], element_id, revision, before_commit=hook),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    placed = await store.element_folder_ids(user["user_id"], [restored.id])
    renamed = before.name != restored.name
    return await _synced(
        {**_element(restored), "folder_id": placed.get(restored.id)}, user["user_id"], "restore",
        old_name=before.name if renamed else None,
    )


@router.get("/{element_id}/usages")
async def list_element_usages(
    element_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """哪些项目的哪些镜头用了这个资产。"""
    item = await store.get_element(element_id, user["user_id"])
    if item is None:
        raise HTTPException(status_code=404, detail=_text_of("list_element_usages.detail"))
    items = await run_in_threadpool(asset_sync.usages, _element_snapshot(_element(item), user["user_id"]))
    return {"items": items}

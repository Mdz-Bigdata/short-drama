"""Canvas additions written from BeefTV's described behaviour: a read-only look at an older canvas version,
the reference caps a clip node is checked against, and the prompt optimizer."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.auth_api import get_current_user
from app.api.drama_api import require_owned_drama_task, service as drama
from app.api.studio_api import _canvas_id, _owner, _safe_error, get_studio_service
from app.core import camera_doctor, prompt_structure
from app.core import canvas_beef_prompt_optimizer as optimizer
from app.core import reference_limits, usage_ledger
from app.platform.runtime_models import runtime_model_registry
from app.service.studio_service import StudioService

logger = logging.getLogger("app.api.canvas_beef_api")
studio_router = APIRouter(prefix="/api/studio", tags=["canvas"])
drama_router = APIRouter(prefix="/api/drama", tags=["canvas"], dependencies=[Depends(require_owned_drama_task)])
PURPOSE = "canvas_prompt_optimizer"


class OptimizeRequest(BaseModel):
    prompt: str = Field(default="", max_length=20_000)
    medium: str = Field(min_length=1, max_length=16)
    mode: str = Field(min_length=1, max_length=24)
    target_model: str = Field(default="", max_length=200)
    references: list[str] = Field(default_factory=list, max_length=32)
    image_references: int = Field(default=0, ge=0, le=64)
    note: str = Field(default="", max_length=2000)
    text_model: str = Field(default="", max_length=200)
    # The clip node's length in seconds; 0 when unknown. Only the structure mode reads it.
    duration: float = Field(default=0, ge=0, le=600)


@studio_router.get("/projects/{project_id}/canvas/versions/{version}")
def canvas_version(
    project_id: str,
    version: int,
    canvas_id: str = Depends(_canvas_id),
    current_user: dict = Depends(get_current_user),
    studio: StudioService = Depends(get_studio_service),
):
    """An older version's nodes and edges, to look at before restoring; reading it changes nothing."""
    try:
        record = studio.repository.get_canvas_version(project_id, _owner(current_user), version, canvas_id=canvas_id)
    except Exception as exc:
        raise _safe_error(exc) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return record.model_dump(mode="json")


@drama_router.get("/{task_id}/canvas-beef/reference-limits")
def canvas_reference_limits(task_id: str, model: str = ""):
    """How many references a video node may carry: what the model that will run it takes (``model`` or the project's)."""
    task = drama.repo.get_task(task_id) or {}
    chosen = model or str((task.get("config") or {}).get("video_model") or "")
    probe = getattr(getattr(drama, "gateway", None), "video_reference_model", None)
    renders = probe(chosen) if callable(probe) else ""
    caps = reference_limits.caps_of(renders if isinstance(renders, str) and renders.strip() else chosen)
    return {"images": caps.images, "videos": caps.videos, "audios": caps.audios}


@drama_router.get("/{task_id}/canvas-beef/prompt-optimize")
async def optimizer_options(task_id: str):
    """The ways to optimize, and the text models it may use (the project's own first)."""
    task = await run_in_threadpool(drama.repo.get_task, task_id) or {}
    default = str((task.get("config") or {}).get("llm_model") or "")
    return {"modes": optimizer.modes(), "text_models": _text_models(default), "default_text_model": default}


def _text_models(default: str) -> list[str]:
    configured = [model for item in runtime_model_registry.list("text") for model in item.model_ids]
    return list(dict.fromkeys(model for model in (default, *configured) if model))


@drama_router.post("/{task_id}/canvas-beef/prompt-optimize")
async def optimize_prompt(task_id: str, request: OptimizeRequest):
    """One text call; the node's prompt is never changed here, only the person adopting the result changes it."""
    task = await run_in_threadpool(drama.repo.get_task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Not Found")
    config = task.get("config") if isinstance(task.get("config"), dict) else {}
    model = request.text_model.strip() or str(config.get("llm_model") or "")
    if request.text_model.strip() and model not in _text_models(str(config.get("llm_model") or "")):
        raise HTTPException(status_code=422, detail=str(optimizer._error("unknown_text_model", model=model)))
    try:
        checked = optimizer.checked(optimizer.Request(
            prompt=request.prompt, medium=request.medium, mode=request.mode, target_model=request.target_model,
            references=request.references, image_references=request.image_references, note=request.note,
            duration=request.duration,
        ))
    except optimizer.OptimizerError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    system, user = optimizer.prompts(checked)

    def ask() -> str:
        with usage_ledger.bind_task(task_id, PURPOSE):
            return drama.gateway.call_llm(model, system, user, str(config.get("title_suggestion") or "")) or ""

    answer = await run_in_threadpool(ask)
    try:
        result = optimizer.parse(answer)
    except optimizer.OptimizerError as error:
        logger.warning("提示词优化没有可用结果: task=%s mode=%s reason=%s", task_id, checked.mode, error)
        raise HTTPException(status_code=422, detail=str(error)) from error
    payload = {**result.as_dict(), "mode": checked.mode, "text_model": model}
    if checked.mode in optimizer.LAYOUT_MODES:
        # Sections and timed segments, checked by rule; a problem is shown beside the result, never fixed silently.
        payload["structure_check"] = prompt_structure.check(
            result.prompt, checked.duration, checked.note, checked.mode, checked.medium,
        )
    if checked.mode == "camera":
        payload["diagnosis"] = camera_doctor.diagnose(checked.prompt, checked.medium).as_dict()
        # A bare emotion word left in the rewrite is taken out here, whatever the model did, and said so.
        cleaned, removed = camera_doctor.without_bare_emotions(payload["prompt"])
        if removed and cleaned:
            payload["prompt"] = cleaned
            payload["changes"] = [*payload["changes"], camera_doctor.bare_emotion_change(removed)]
        payload["alternatives"] = [camera_doctor.without_bare_emotions(item)[0] or item for item in payload["alternatives"]]
    return payload


class DiagnoseRequest(BaseModel):
    prompt: str = Field(default="", max_length=20_000)
    medium: str = Field(default="video", max_length=16)


@drama_router.post("/{task_id}/canvas-beef/camera-diagnosis")
def diagnose_camera(task_id: str, request: DiagnoseRequest):
    """Why a prompt comes out flat, by rule: no model is called, nothing is charged, nothing is changed."""
    medium = request.medium if request.medium in camera_doctor.MEDIA else "video"
    return {**camera_doctor.diagnose(request.prompt, medium).as_dict(), "reference": camera_doctor.reference()}

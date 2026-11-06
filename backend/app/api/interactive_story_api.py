# -*- coding: utf-8 -*-
"""Interactive stories (互动剧): one branching graph per project, its media, playtests and player exports."""

from __future__ import annotations

import os
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from app.api import drama_api
from app.service.interactive_story_service import (
    MAX_VIDEO_UPLOAD_BYTES,
    ExportFile,
    InteractiveStoryService,
    StoryConflict,
    StoryInputError,
    StoryPlanError,
)

router = APIRouter(
    prefix="/api/drama/{task_id}/interactive-story",
    tags=["互动剧"],
    dependencies=[Depends(drama_api.require_owned_drama_task)],
)


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: int = Field(ge=0)
    graph: dict[str, Any]


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: dict[str, Any]


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: str = Field(min_length=4, max_length=4000)
    endings: int = Field(default=3, ge=2, le=12)
    minutes: int = Field(default=10, ge=1, le=120)
    language: Literal["zh", "en", "vi"] = "zh"
    use_project: bool = True


class PlaytestStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment: str = Field(max_length=64)
    choice: str | None = Field(default=None, max_length=80)


class PlaytestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[PlaytestStep] = Field(max_length=2000)
    ending: str | None = Field(default=None, max_length=64)
    from_start: bool = True
    timeouts: int = Field(default=0, ge=0, le=2000)


def _service() -> InteractiveStoryService:
    # Looked up per call: drama_api owns the one configured service, repo and gateway.
    return InteractiveStoryService(drama_api.service.repo, drama_api.service.gateway)


def _guarded(call):
    try:
        return call()
    except StoryConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (StoryInputError, StoryPlanError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _disposition(filename: str) -> str:
    # The quoted form is for old clients; filename* carries a non-ASCII title without letting it reach the header raw.
    stem, extension = os.path.splitext(filename)
    plain = stem.encode("ascii", "ignore").decode("ascii").replace('"', "").strip() or "interactive-story"
    return f"attachment; filename=\"{plain}{extension}\"; filename*=UTF-8''{quote(filename)}"


def _send(export: ExportFile):
    headers = {"Content-Disposition": _disposition(export.filename)}
    if export.path:
        return FileResponse(export.path, media_type=export.media_type, headers=headers, background=BackgroundTask(os.remove, export.path))
    return Response(content=export.content, media_type=export.media_type, headers=headers)


@router.get("")
def get_story(task_id: str):
    """The project's story with its current problems, path analysis and playtest statistics."""
    return _guarded(lambda: _service().view(task_id))


@router.put("")
def save_story(task_id: str, req: SaveRequest):
    """Replace the graph; ``base_revision`` must be the revision this editor loaded, or the answer is 409."""
    return _guarded(lambda: _service().save(task_id, req.base_revision, req.graph))


@router.post("/segments/{segment_id}/canvas")
def segment_to_canvas(task_id: str, segment_id: str, current_user: dict = Depends(drama_api.require_owned_drama_task)):
    """Put a first-frame node and a video node for this segment on the project's canvas. Nothing runs or is charged here."""
    from app.api.studio_api import get_studio_service

    return _guarded(lambda: _service().canvas_handoff(task_id, segment_id, owner_id=str(current_user["user_id"]), studio=get_studio_service()))


@router.post("/analyze")
def analyze_story(task_id: str, req: AnalyzeRequest):
    """Validate and analyse an unsaved draft; nothing is stored."""
    return _guarded(lambda: _service().analyze(req.graph))


@router.post("/plan")
def plan_story(task_id: str, req: PlanRequest):
    """Have the text model draft a story from a brief (one model call, retried on junk). Not saved until applied."""
    return _guarded(lambda: _service().plan(
        task_id, req.brief, endings=req.endings, minutes=req.minutes, language=req.language, use_project=req.use_project,
    ))


@router.get("/media")
def list_media(task_id: str):
    """The project's shots, generated clips, finished films and this story's uploads."""
    return _guarded(lambda: _service().media_library(task_id))


@router.post("/media")
def upload_media(
    task_id: str,
    file: UploadFile = File(..., description="图片（PNG / JPEG / WebP ≤ 10 MB）或视频（MP4 / WebM ≤ 200 MB）"),
    duration_s: float = Form(0.0, ge=0),
):
    if file.size is not None and file.size > MAX_VIDEO_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail=f"文件不能超过 {MAX_VIDEO_UPLOAD_BYTES // (1024 * 1024)} MB")
    return _guarded(lambda: _service().add_upload(task_id, file.file, filename=file.filename or "", duration_s=duration_s))


@router.delete("/media/{upload_id}")
def delete_media(task_id: str, upload_id: str):
    """Delete an upload; one a segment still uses is refused rather than left dangling."""
    return _guarded(lambda: _service().remove_upload(task_id, upload_id))


@router.post("/playtest")
def record_playtest(task_id: str, req: PlaytestRequest):
    """Add one playthrough to the statistics. Does not move the graph's revision."""
    return _guarded(lambda: _service().record_playtest(task_id, req.model_dump(mode="json")))


@router.delete("/playtest")
def reset_playtest(task_id: str):
    return _guarded(lambda: _service().reset_playtest(task_id))


@router.get("/export/preview")
def export_preview(task_id: str):
    """Whether the story can be exported, and what each piece of media will do in the player."""
    return _guarded(lambda: _service().export_preview(task_id))


@router.get("/export.html")
def export_html(task_id: str, lang: Literal["zh-CN", "en", "vi"] = Query("zh-CN")):
    """One self-contained player page; refused while the story has errors."""
    return _send(_guarded(lambda: _service().export_html(task_id, lang=lang)))


@router.get("/export.zip")
def export_zip(task_id: str, lang: Literal["zh-CN", "en", "vi"] = Query("zh-CN")):
    """The player with its media beside it, for offline playback; refused while the story has errors."""
    return _send(_guarded(lambda: _service().export_zip(task_id, lang=lang)))

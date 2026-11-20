# -*- coding: utf-8 -*-
"""A scene's 360° panoramas, for the director desk's backdrop. The desk itself is set through the spatial PATCH route."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api import drama_api
from app.service import director_desk_service as desk
from app.service import panorama_service
from app.service.spatial_stage_service import scene_record
from app.core import prompt_data


_WORDING_FILE = "api_panorama_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/api_panorama_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

logger = logging.getLogger("app.api.panorama_api")

router = APIRouter(
    prefix="/api/drama",
    tags=list(_words_of("module.tags")),
    dependencies=[Depends(drama_api.require_owned_drama_task)],
)

_REFERENCE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _scene_task(task_id: str, scene_id: str) -> dict:
    task = drama_api.service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=_text_of("_scene_task.detail"))
    if scene_record(task, scene_id) is None:
        raise HTTPException(status_code=404, detail=_text_of("_scene_task.detail.2").format(scene_id))
    return task


@router.get("/{task_id}/panoramas/scenes/{scene_id}")
def list_panoramas(task_id: str, scene_id: str):
    return panorama_service.scene_view(_scene_task(task_id, scene_id), scene_id)


@router.post("/{task_id}/panoramas/scenes/{scene_id}", status_code=201)
def generate_panorama(
    task_id: str, scene_id: str,
    description: str = Form("", max_length=1500),
    reference: UploadFile | None = File(None, description=_text_of("generate_panorama.description")),
):
    """Generate a 2:1 panorama from text and/or a picture; this is one paid image call."""
    _scene_task(task_id, scene_id)
    content, media_type = None, ""
    if reference is not None:
        content = reference.file.read(desk.MAX_STILL_BYTES + 1)
        if len(content) > desk.MAX_STILL_BYTES:
            raise HTTPException(status_code=422, detail=_text_of("generate_panorama.detail"))
        media_type = desk.sniff_media(content[:4096]) or ""
        if media_type not in _REFERENCE_TYPES:
            raise HTTPException(status_code=422, detail=_text_of("generate_panorama.detail.2"))
    try:
        result = panorama_service.generate(
            drama_api.service, task_id, scene_id, description=description, reference=content, reference_type=media_type,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except desk.CaptureError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - provider errors can carry keys and URLs; the person gets a plain line
        logger.warning("全景生成失败: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail=_text_of("generate_panorama.detail.3")) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=_text_of("generate_panorama.detail.4"))
    return result

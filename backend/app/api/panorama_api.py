# -*- coding: utf-8 -*-
"""A scene's 360° panoramas, for the director desk's backdrop. The desk itself is set through the spatial PATCH route."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api import drama_api
from app.service import director_desk_service as desk
from app.service import panorama_service
from app.service.spatial_stage_service import scene_record

logger = logging.getLogger("app.api.panorama_api")

router = APIRouter(
    prefix="/api/drama",
    tags=["360 全景"],
    dependencies=[Depends(drama_api.require_owned_drama_task)],
)

_REFERENCE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _scene_task(task_id: str, scene_id: str) -> dict:
    task = drama_api.service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if scene_record(task, scene_id) is None:
        raise HTTPException(status_code=404, detail=f"场景 {scene_id} 不在剧本大纲里")
    return task


@router.get("/{task_id}/panoramas/scenes/{scene_id}")
def list_panoramas(task_id: str, scene_id: str):
    return panorama_service.scene_view(_scene_task(task_id, scene_id), scene_id)


@router.post("/{task_id}/panoramas/scenes/{scene_id}", status_code=201)
def generate_panorama(
    task_id: str, scene_id: str,
    description: str = Form("", max_length=1500),
    reference: UploadFile | None = File(None, description="可选的参考图：按它的地点与色调扩展成全景"),
):
    """Generate a 2:1 panorama from text and/or a picture; this is one paid image call."""
    _scene_task(task_id, scene_id)
    content, media_type = None, ""
    if reference is not None:
        content = reference.file.read(desk.MAX_STILL_BYTES + 1)
        if len(content) > desk.MAX_STILL_BYTES:
            raise HTTPException(status_code=422, detail="参考图不能超过 10 MB")
        media_type = desk.sniff_media(content[:4096]) or ""
        if media_type not in _REFERENCE_TYPES:
            raise HTTPException(status_code=422, detail="参考图只支持 PNG、JPEG、WebP；文件内容不是其中任何一种")
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
        raise HTTPException(status_code=502, detail="图像模型未能生成全景，请稍后重试") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result

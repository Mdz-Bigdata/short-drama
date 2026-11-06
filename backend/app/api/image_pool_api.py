# -*- coding: utf-8 -*-
"""A project's image pool: the index, cutting a grid image into it, and giving a pool image to a shot."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api import drama_api
from app.core import episode_cycle, image_pool, media_compositor
from app.core.grid_split import MAX_GRID_SIDE
from app.core.storyboard_assets import fetch_remote_image_bytes

logger = logging.getLogger("app.api.image_pool_api")

router = APIRouter(
    prefix="/api/drama",
    tags=["图片池"],
    dependencies=[Depends(drama_api.require_owned_drama_task)],
)


class PoolSplitRequest(BaseModel):
    image_id: str = Field(min_length=1, max_length=120)
    rows: int = Field(ge=1, le=MAX_GRID_SIDE)
    columns: int = Field(ge=1, le=MAX_GRID_SIDE)
    revision: int | None = Field(None, ge=0)


class PoolRebuildRequest(BaseModel):
    revision: int | None = Field(None, ge=0)


class PoolAssignRequest(BaseModel):
    image_id: str = Field(min_length=1, max_length=120)
    shot_id: int = Field(ge=1)
    scene_id: str = Field("", max_length=40)
    shot_uid: int | None = Field(None, ge=1)


def _task(task_id: str) -> dict:
    task = drama_api.service.repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _image_bytes(url: str) -> bytes:
    local = media_compositor.local_media_path(url)
    if local:
        with open(local, "rb") as handle:
            return handle.read()
    if url.startswith(("http://", "https://")):
        return fetch_remote_image_bytes(url)
    raise ValueError("这张图的文件已不存在")


@router.get("/{task_id}/image-pool")
def get_image_pool(task_id: str):
    return image_pool.view(_task(task_id))


@router.post("/{task_id}/image-pool/rebuild")
def rebuild_image_pool(task_id: str, req: PoolRebuildRequest | None = None):
    """Throw the index away and find everything again from the project and the files on disk."""
    _task(task_id)
    try:
        return drama_api.service.repo.mutate_task(
            task_id, lambda task: image_pool.rebuild(task, expected_revision=req.revision if req else None),
        )
    except image_pool.PoolConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/image-pool/split")
def split_into_pool(task_id: str, req: PoolSplitRequest):
    """Cut a pool image rows×columns, trimming the borders, and add the cells to the pool."""
    task = _task(task_id)
    source = image_pool.find(task, req.image_id)
    if source is None:
        raise HTTPException(status_code=404, detail="图片池里没有这张图")
    # Checked before the work as well as after: the cheap refusal should not cost a cut.
    if req.revision is not None and req.revision != image_pool.view(task)["revision"]:
        raise HTTPException(status_code=409, detail="图片池已被更新，请刷新后再试")
    try:
        content = _image_bytes(str(source["url"]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - a remote image that has gone is the person's to redo, not a crash
        logger.warning("图片池取图失败: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="原图下载失败，请稍后重试") from exc
    try:
        cells = image_pool.cut(task_id, source, content, req.rows, req.columns)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=422, detail="这个文件不是可切分的图片") from exc
    try:
        pool = drama_api.service.repo.mutate_task(
            task_id, lambda current: image_pool.add_cells(current, cells, expected_revision=req.revision),
        )
    except image_pool.PoolConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**pool, "added": [cell["id"] for cell in cells]}


@router.post("/{task_id}/image-pool/assign")
def assign_pool_image(task_id: str, req: PoolAssignRequest):
    """Make a pool image the shot's frame; as with any shot edit its clip goes stale and the workflow stays put."""
    service = drama_api.service

    def mutate(task: dict) -> dict:
        if service._has_running_generation(task):
            raise ValueError("任务正在执行阶段，暂不能更换分镜图")
        image = image_pool.find(task, req.image_id)
        if image is None:
            raise LookupError("图片池里没有这张图")
        assets = task.setdefault("assets", {})
        target, number = service._find_shot(assets.get("4"), req.shot_id, scene_id=req.scene_id, uid=req.shot_uid)
        if target is None:
            raise LookupError("镜头不存在，请先完成第 4 阶段分镜")
        target["image_url"] = str(image["url"])
        clip = episode_cycle.clip_for({**target, "shot_id": number}, assets.get("5") or [])
        if clip is not None:
            clip["stale"] = True
            clip["stale_reason"] = "分镜图已从图片池更换，需重跑第 5 阶段后生效"
        return task

    try:
        updated = service.repo.mutate_task(task_id, mutate)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409 if "正在执行" in str(exc) else 422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="任务不存在")
    return service.get_shot_visual_workspace(task_id)

# -*- coding: utf-8 -*-
"""What of the 3D director desk belongs to a person rather than to a project: the saved-pose library."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.api.auth_api import get_current_user
from app.core.spatial_stage.models import StagePose
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.schema.director_desk import DeskUserPosesResponse, DeskUserSavePoseRequest

router = APIRouter(prefix="/api/director-desk", tags=["3D 导演台"])


def _serialize(item) -> dict:
    return {
        "id": item.id, "name": item.name, "pose": dict(item.pose_json or {}),
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }


async def _library(store: PlatformStore, user_id: str) -> dict:
    return {"poses": [_serialize(item) for item in await store.list_desk_poses(user_id)]}


@router.get("/poses", response_model=DeskUserPosesResponse)
async def list_user_poses(user: dict = Depends(get_current_user), store: PlatformStore = Depends(get_platform_store)):
    """The signed-in person's saved poses, in every project they open."""
    return await _library(store, user["user_id"])


@router.post("/poses", response_model=DeskUserPosesResponse)
async def save_user_pose(
    req: DeskUserSavePoseRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    """Save a pose under a name; saving the same name again replaces it."""
    try:
        pose = StagePose.model_validate(req.pose)
    except ValidationError as error:
        raise HTTPException(
            status_code=422, detail="姿态数据不合法：关节角度须在 ±180° 内、最多 120 个关节，clip_phase 在 0 到 1 之间",
        ) from error
    try:
        await store.save_desk_pose(user["user_id"], req.name, pose.model_dump(mode="json"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return await _library(store, user["user_id"])


@router.delete("/poses/{pose_id}", response_model=DeskUserPosesResponse)
async def delete_user_pose(
    pose_id: str, user: dict = Depends(get_current_user), store: PlatformStore = Depends(get_platform_store),
):
    if not await store.delete_desk_pose(user["user_id"], pose_id):
        raise HTTPException(status_code=404, detail="这个姿势不存在，可能已被删除")
    return await _library(store, user["user_id"])

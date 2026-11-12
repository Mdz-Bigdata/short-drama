# -*- coding: utf-8 -*-
"""What of the 3D director desk belongs to a person rather than to a project: the saved-pose library."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.api.auth_api import get_current_user
from app.core.spatial_stage import model_kit
from app.core.spatial_stage.models import StagePose
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.schema.director_desk import DeskUserPosesResponse, DeskUserSavePoseRequest
from app.core import prompt_data


_WORDING_FILE = "api_director_desk_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/api_director_desk_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

router = APIRouter(prefix="/api/director-desk", tags=list(_words_of("module.tags")))


def _serialize(item) -> dict:
    return {
        "id": item.id, "name": item.name, "pose": dict(item.pose_json or {}),
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }


async def _library(store: PlatformStore, user_id: str) -> dict:
    return {"poses": [_serialize(item) for item in await store.list_desk_poses(user_id)]}


@router.get("/kits")
async def list_model_kits(user: dict = Depends(get_current_user)):
    """The built-in white models: furniture, architecture, vehicles, set pieces, at their real sizes."""
    return {"kits": model_kit.catalog()}


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
            status_code=422, detail=_text_of("save_user_pose.detail"),
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
        raise HTTPException(status_code=404, detail=_text_of("delete_user_pose.detail"))
    return await _library(store, user["user_id"])

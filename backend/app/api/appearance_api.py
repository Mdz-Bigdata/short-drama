"""The deployment's brand: read by anyone before the interface draws, changed by an administrator."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.auth_api import require_permission
from app.core import appearance
from app.platform.dependencies import get_platform_store
from app.platform.permissions import CAPABILITY_MANAGE
from app.platform.store import PlatformStore

public_router = APIRouter(prefix="/api/public/appearance", tags=["appearance"])
router = APIRouter(prefix="/api/platform/appearance", tags=["appearance"])
ASSET_BASE = "/api/public/appearance/assets"
#: Read at most this much of an upload; the slot's own limit is lower and gives the message.
_READ_CAP = 4 * 1024 * 1024


class AppearanceUpdateRequest(BaseModel):
    text: dict[str, str] = Field(default_factory=dict)
    logo_frame: str | None = Field(default=None, max_length=16)


@public_router.get("")
async def public_appearance(store: PlatformStore = Depends(get_platform_store)):
    return appearance.public_view(await store.get_setting(appearance.SETTING_KEY), asset_base=ASSET_BASE)


@public_router.get("/assets/{slot}")
async def public_asset(slot: str, v: str = Query(default="", max_length=64), store: PlatformStore = Depends(get_platform_store)):
    found = appearance.image(await store.get_setting(appearance.SETTING_KEY), slot)
    if found is None:
        raise HTTPException(status_code=404, detail="Not Found")
    # A versioned address never changes content; an unversioned one may, so it is kept only briefly.
    lasting = bool(v) and found.sha256.startswith(v)
    return FileResponse(
        found.path, media_type=found.mime,
        headers={"Cache-Control": "public, max-age=31536000, immutable" if lasting else "public, max-age=300"},
    )


@router.get("")
async def edit_view(
    _: dict = Depends(require_permission(CAPABILITY_MANAGE)),
    store: PlatformStore = Depends(get_platform_store),
):
    return appearance.admin_view(await store.get_setting(appearance.SETTING_KEY), asset_base=ASSET_BASE)


@router.put("")
async def update_text(
    request: AppearanceUpdateRequest,
    admin: dict = Depends(require_permission(CAPABILITY_MANAGE)),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        changed = appearance.updated(
            await store.get_setting(appearance.SETTING_KEY), text=request.text, logo_frame=request.logo_frame,
        )
    except appearance.AppearanceError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await store.put_setting(appearance.SETTING_KEY, changed, actor_id=admin["user_id"])
    return appearance.admin_view(changed, asset_base=ASSET_BASE)


@router.post("/assets/{slot}")
async def upload_asset(
    slot: str,
    file: UploadFile = File(...),
    admin: dict = Depends(require_permission(CAPABILITY_MANAGE)),
    store: PlatformStore = Depends(get_platform_store),
):
    data = await file.read(_READ_CAP + 1)
    try:
        changed = appearance.store_image(await store.get_setting(appearance.SETTING_KEY), slot, data)
    except appearance.AppearanceError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await store.put_setting(appearance.SETTING_KEY, changed, actor_id=admin["user_id"])
    return appearance.admin_view(changed, asset_base=ASSET_BASE)


@router.delete("/assets/{slot}")
async def remove_asset(
    slot: str,
    admin: dict = Depends(require_permission(CAPABILITY_MANAGE)),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        changed = appearance.remove_image(await store.get_setting(appearance.SETTING_KEY), slot)
    except appearance.AppearanceError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await store.put_setting(appearance.SETTING_KEY, changed, actor_id=admin["user_id"])
    return appearance.admin_view(changed, asset_base=ASSET_BASE)

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth_api import _public_user, get_current_user, require_admin
from app.platform.dependencies import get_platform_store
from app.platform.bootstrap import bootstrap_admin_login, remove_bootstrap_credential_file
from app.platform.store import PlatformStore
from app.schema.platform import AdminUserUpdateRequest, PasswordChangeRequest, ProfileUpdateRequest


router = APIRouter(tags=["用户中心与管理"])


@router.get("/api/users/me")
async def user_center(
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    record = await store.get_user(user["user_id"])
    membership = await store.get_membership(user["user_id"])
    return {
        "user": _public_user(record),
        "membership": None if not membership else {
            "plan_id": membership[1].id,
            "plan_name": membership[1].name,
            "status": membership[0].status,
            "started_at": membership[0].started_at,
            "expires_at": membership[0].expires_at,
        },
    }


@router.patch("/api/users/me")
async def update_user_center(
    request: ProfileUpdateRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        record = await store.update_profile(
            user["user_id"], display_name=request.display_name, phone=request.phone
        )
        return {"user": _public_user(record)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/users/me/password")
async def change_password(
    request: PasswordChangeRequest,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        record = await store.change_password(
            user["user_id"], request.current_password, request.new_password
        )
        if record.username == "admin" and record.email == bootstrap_admin_login():
            remove_bootstrap_credential_file()
        return {"status": "success", "user": _public_user(record)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/admin/users")
async def admin_list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
):
    items, total = await store.list_users(page, page_size)
    return {
        "items": [_public_user(item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.patch("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    request: AdminUserUpdateRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        record = await store.admin_update_user(
            admin["user_id"], user_id, role=request.role, status=request.status
        )
        return {"user": _public_user(record)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

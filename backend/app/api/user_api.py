from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth_api import _public_user, get_current_user, require_permission
from app.platform.permissions import (
    AUDIT_READ,
    ROLE_ASSIGN,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    USER_MANAGE,
    USER_READ,
    has_permission,
)
from app.platform import account_linkage
from app.platform.billing_book import account_status_changed
from app.platform.dependencies import get_platform_store
from app.platform.bootstrap import bootstrap_admin_login, remove_bootstrap_credential_file
from app.platform.store import PlatformStore
from app.schema.platform import AdminUserUpdateRequest, PasswordChangeRequest, ProfileUpdateRequest, UserRolesRequest


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
    _: dict = Depends(require_permission(USER_READ)),
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
    admin: dict = Depends(require_permission(USER_MANAGE)),
    store: PlatformStore = Depends(get_platform_store),
):
    target = await store.get_user(user_id)
    # 客服可以停用客户，但不能通过停用别的管理人员来绕过角色授予。
    if target and target.roles and not has_permission(admin, ROLE_ASSIGN):
        raise HTTPException(status_code=403, detail="只有可授予角色的人才能更改管理人员的账号状态")
    try:
        user = await store.set_user_status(admin["user_id"], user_id, request.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    account_status_changed(user_id)
    if request.status == "suspended":
        await account_linkage.finish_closing(store, user_id)
    return {"user": _public_user(user)}


@router.delete("/api/admin/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    admin: dict = Depends(require_permission(USER_MANAGE)),
    store: PlatformStore = Depends(get_platform_store),
):
    """Who they were goes for good. Orders, ledger and audit stay, because those records are not theirs alone to remove."""
    target = await store.get_user(user_id)
    if target and target.roles and not has_permission(admin, ROLE_ASSIGN):
        raise HTTPException(status_code=403, detail="只有可授予角色的人才能删除管理人员的账号")
    try:
        user = await store.delete_account(actor_id=admin["user_id"], user_id=user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await account_linkage.finish_closing(store, user_id)
    return {"user": _public_user(user)}


@router.put("/api/admin/users/{user_id}/roles")
async def admin_set_user_roles(
    user_id: str,
    request: UserRolesRequest,
    admin: dict = Depends(require_permission(ROLE_ASSIGN)),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        return {"user": _public_user(await store.set_user_roles(admin["user_id"], user_id, request.roles))}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/admin/roles")
async def admin_list_roles(_: dict = Depends(require_permission(USER_READ))):
    return {"items": [
        {"role": role, "label": ROLE_LABELS[role][0], "description": ROLE_LABELS[role][1], "permissions": sorted(granted)}
        for role, granted in ROLE_PERMISSIONS.items()
    ]}


@router.get("/api/admin/audit-events")
async def admin_list_audit_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: dict = Depends(require_permission(AUDIT_READ)),
    store: PlatformStore = Depends(get_platform_store),
):
    items, total = await store.list_audit_events(page, page_size)
    return {
        "items": [{
            "id": item.id, "actor_id": item.actor_id, "action": item.action, "resource_type": item.resource_type,
            "resource_id": item.resource_id, "details": item.details, "created_at": item.created_at,
        } for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
    }

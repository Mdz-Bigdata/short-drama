"""What this person should know about, and for operators what is waiting on them."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth_api import get_current_user
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore

router = APIRouter(prefix="/api/notifications", tags=["站内通知"])


@router.get("")
async def my_notifications(
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    items, unread = await store.list_notifications(user["user_id"])
    return {
        "unread": unread,
        "to_do": await store.staff_to_do(user),
        "items": [{
            "id": item.id, "kind": item.kind, "data": item.data, "read": item.read_at is not None, "created_at": item.created_at,
        } for item in items],
    }


@router.post("/read-all")
async def read_all(
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    return {"marked": await store.mark_notifications_read(user["user_id"])}


@router.post("/{notification_id}/read")
async def read_one(
    notification_id: str,
    user: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    return {"marked": await store.mark_notifications_read(user["user_id"], notification_id)}

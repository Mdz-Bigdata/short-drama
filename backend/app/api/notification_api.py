"""What this person should know about, and for operators what is waiting on them."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth_api import get_current_user
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.core import prompt_data


_WORDING_FILE = "api_notification_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/api_notification_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

router = APIRouter(prefix="/api/notifications", tags=list(_words_of("module.tags")))


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

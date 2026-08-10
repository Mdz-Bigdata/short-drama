from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth_api import get_current_user, require_admin
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.schema.platform import CapabilityToggleRequest, CommandRequest


router = APIRouter(prefix="/api/platform", tags=["全局能力与命令"])


def _ability(item) -> dict:
    return {
        "id": item.capability_id,
        "label": item.label,
        "command": item.command,
        "entrypoint": item.entrypoint,
        "enabled": item.enabled,
        "updated_at": item.updated_at,
    }


@router.get("/capabilities")
async def list_capabilities(
    _: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    grouped: dict[str, dict] = {}
    for item in await store.list_capabilities():
        source = grouped.setdefault(item.source_id, {
            "source_id": item.source_id,
            "source_url": item.source_url,
            "enabled_count": 0,
            "abilities": [],
        })
        source["abilities"].append(_ability(item))
        source["enabled_count"] += int(item.enabled)
    return {"items": list(grouped.values()), "total": len(grouped)}


@router.patch("/capabilities/{source_id}/{capability_id}")
async def toggle_capability(
    source_id: str,
    capability_id: str,
    request: CapabilityToggleRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        item = await store.set_capability_enabled(
            source_id, capability_id, request.enabled, actor_id=admin["user_id"]
        )
        return _ability(item)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _resolve(request: CommandRequest, store: PlatformStore) -> dict:
    try:
        resolved = await store.resolve_command(request.command)
        return {
            "status": "resolved",
            "source_id": resolved.source_id,
            "capability_id": resolved.capability_id,
            "label": resolved.label,
            "command": resolved.command,
            "entrypoint": resolved.entrypoint,
            "payload": resolved.payload,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/commands/resolve")
async def resolve_command(
    request: CommandRequest,
    _: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    return await _resolve(request, store)


@router.post("/commands/invoke")
async def invoke_command(
    request: CommandRequest,
    _: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    result = await _resolve(request, store)
    result["status"] = "accepted"
    result["message"] = "命令已通过全局能力白名单，可由对应入口继续处理"
    return result

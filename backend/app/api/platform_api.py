from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth_api import get_current_user, require_permission
from app.platform.permissions import CAPABILITY_MANAGE
from app.core.capability_manifest import capability_command_catalog
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.schema.platform import CapabilityToggleRequest, CommandRequest
from app.core.provenance import upstream_source_by_id
from app.core import prompt_data


_WORDING_FILE = "api_platform_api"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/api_platform_api.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


router = APIRouter(prefix="/api/platform", tags=list(_words_of("module.tags")))
_CAPABILITY_EVIDENCE = {
    (record["source_id"], record["capability_id"]): record
    for record in capability_command_catalog()
}


def _capability_evidence(source_id: str, capability_id: str) -> dict:
    return _CAPABILITY_EVIDENCE.get((source_id, capability_id), {})


def _ability(item) -> dict:
    evidence = _capability_evidence(item.source_id, item.capability_id)
    return {
        "id": item.capability_id,
        "label": item.label,
        "command": item.command,
        "entrypoint": item.entrypoint,
        "enabled": item.enabled,
        "updated_at": item.updated_at,
        "implementation_status": evidence.get("implementation_status", "unverified"),
        "evidence": evidence.get("evidence", ""),
    }


@router.get("/capabilities")
async def list_capabilities(
    _: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    grouped: dict[str, dict] = {}
    provenance = upstream_source_by_id()
    for item in await store.list_capabilities():
        source_record = provenance[item.source_id]
        source = grouped.setdefault(item.source_id, {
            "source_id": item.source_id,
            "source_url": item.source_url,
            "reviewed_commit": source_record.reviewed_commit,
            "reviewed_at": source_record.reviewed_at,
            "license_observation": source_record.license_observation,
            "code_treatment": source_record.code_treatment,
            "attribution": source_record.attribution,
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
    admin: dict = Depends(require_permission(CAPABILITY_MANAGE)),
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
        evidence = _capability_evidence(resolved.source_id, resolved.capability_id)
        return {
            "status": "resolved",
            "source_id": resolved.source_id,
            "capability_id": resolved.capability_id,
            "label": resolved.label,
            "command": resolved.command,
            "entrypoint": resolved.entrypoint,
            "implementation_status": evidence.get("implementation_status", "unverified"),
            "evidence": evidence.get("evidence", ""),
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
    result["message"] = _text_of("invoke_command.text")
    return result

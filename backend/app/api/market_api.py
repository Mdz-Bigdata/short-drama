# -*- coding: utf-8 -*-
"""Market routes: sources, entries, installs and the export bundle (see ``app.core.market``).

Browsing is open to any signed-in user; changing sources and installing are
administrator actions, like the rest of the configuration centre. Fetches are
injectable so tests never reach the network.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr

from app.api.auth_api import get_current_user, require_admin
from app.core.market import Fetch, Market, MarketError, http_fetch
from app.core.model_configuration import ModelSecretCipher
from app.platform.dependencies import get_model_secret_cipher, get_platform_store
from app.platform.runtime_models import hydrate_runtime_model_registry
from app.platform.store import PlatformStore

router = APIRouter(prefix="/api/market", tags=["market"])


def get_market_fetch() -> Fetch:
    return http_fetch


def _market(store: PlatformStore, fetch: Fetch) -> Market:
    return Market(store, fetch=fetch)


def _raise(error: MarketError) -> None:
    raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error), **error.details})


class SourceAddRequest(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    label: str = Field(default="", max_length=120)


class SourceToggleRequest(BaseModel):
    enabled: bool


class InstallRequest(BaseModel):
    api_key: SecretStr | None = None
    family: str = Field(default="", max_length=40, pattern=r"^[a-z0-9_]*$")
    overwrite: bool = False
    discard_local: bool = False


class ExportRequest(BaseModel):
    author: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=600)


@router.get("/sources")
async def list_sources(_user: dict = Depends(get_current_user), store: PlatformStore = Depends(get_platform_store), fetch: Fetch = Depends(get_market_fetch)):
    return {"items": await _market(store, fetch).sources()}


@router.post("/sources")
async def add_source(request: SourceAddRequest, admin: dict = Depends(require_admin), store: PlatformStore = Depends(get_platform_store), fetch: Fetch = Depends(get_market_fetch)):
    try:
        return await _market(store, fetch).add_source(request.url, label=request.label, actor_id=admin["user_id"])
    except MarketError as error:
        _raise(error)


@router.patch("/sources/{source_id}")
async def toggle_source(source_id: str, request: SourceToggleRequest, admin: dict = Depends(require_admin), store: PlatformStore = Depends(get_platform_store), fetch: Fetch = Depends(get_market_fetch)):
    try:
        return await _market(store, fetch).set_source_enabled(source_id, request.enabled, actor_id=admin["user_id"])
    except MarketError as error:
        _raise(error)


@router.delete("/sources/{source_id}")
async def remove_source(source_id: str, admin: dict = Depends(require_admin), store: PlatformStore = Depends(get_platform_store), fetch: Fetch = Depends(get_market_fetch)):
    try:
        return await _market(store, fetch).remove_source(source_id, actor_id=admin["user_id"])
    except MarketError as error:
        _raise(error)


@router.post("/sources/{source_id}/refresh")
async def refresh_source(source_id: str, admin: dict = Depends(require_admin), store: PlatformStore = Depends(get_platform_store), fetch: Fetch = Depends(get_market_fetch)):
    try:
        return await _market(store, fetch).refresh_source(source_id, actor_id=admin["user_id"])
    except MarketError as error:
        _raise(error)


@router.post("/sources/refresh")
async def refresh_all(admin: dict = Depends(require_admin), store: PlatformStore = Depends(get_platform_store), fetch: Fetch = Depends(get_market_fetch)):
    return {"items": await _market(store, fetch).refresh_all(actor_id=admin["user_id"])}


@router.get("/entries")
async def list_entries(_user: dict = Depends(get_current_user), store: PlatformStore = Depends(get_platform_store), fetch: Fetch = Depends(get_market_fetch)):
    return {"items": await _market(store, fetch).entries()}


@router.get("/installed")
async def list_installed(_user: dict = Depends(get_current_user), store: PlatformStore = Depends(get_platform_store), fetch: Fetch = Depends(get_market_fetch)):
    return {"items": await _market(store, fetch).installed()}


@router.post("/sources/{source_id}/entries/{slug}/install")
async def install_entry(
    source_id: str, slug: str, request: InstallRequest, admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store), cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
    fetch: Fetch = Depends(get_market_fetch),
):
    """Install, or update, one entry: the endpoint and its install record land together."""
    try:
        result = await _market(store, fetch).install(
            source_id, slug, actor_id=admin["user_id"], cipher=cipher,
            api_key=request.api_key.get_secret_value() if request.api_key else "", family=request.family,
            overwrite=request.overwrite, discard_local=request.discard_local,
        )
    except MarketError as error:
        _raise(error)
    await hydrate_runtime_model_registry(store, cipher)
    endpoint = result["endpoint"]
    spec = endpoint.get("spec") or {}
    return {
        "updated": result["updated"], "record": result["record"],
        "endpoint": {"family": spec.get("family"), "label": spec.get("label"), "model_ids": list(spec.get("model_ids") or []), "key_hint": f"****{endpoint.get('api_key_hint')}" if endpoint.get("api_key_hint") else ""},
    }


@router.post("/export/{family}")
async def export_bundle(family: str, request: ExportRequest, _user: dict = Depends(get_current_user), store: PlatformStore = Depends(get_platform_store), fetch: Fetch = Depends(get_market_fetch)):
    try:
        return await _market(store, fetch).export_bundle(family, author=request.author, summary=request.summary)
    except MarketError as error:
        _raise(error)

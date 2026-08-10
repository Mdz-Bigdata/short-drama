from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth_api import get_current_user, require_admin
from app.core.model_configuration import (
    ModelDiscoveryClient,
    ModelSecretCipher,
    provider_label,
    provider_options,
)
from app.platform.dependencies import (
    get_model_discovery_client,
    get_model_secret_cipher,
    get_platform_store,
)
from app.platform.runtime_models import hydrate_runtime_model_registry
from app.platform.store import PlatformStore
from app.schema.platform import (
    CapabilityToggleRequest,
    ModelDiscoveryRequest,
    ModelSaveRequest,
    ModelTestRequest,
)


router = APIRouter(prefix="/api/model-configurations", tags=["模型配置"])


def _entry(item) -> dict:
    return {
        "id": item.id,
        "model_id": item.model_id,
        "display_name": item.display_name,
        "description": item.description,
        "category": item.category,
        "subcategory": item.subcategory or None,
        "capabilities": list(item.capabilities or []),
        "enabled": item.enabled,
        "discovered_at": item.discovered_at,
    }


def _configuration(item) -> dict:
    return {
        "id": item.id,
        "category": item.category,
        "provider": item.provider,
        "provider_label": provider_label(item.provider),
        "base_url": item.base_url,
        "has_api_key": bool(item.api_key_ciphertext),
        "key_hint": f"****{item.api_key_hint}" if item.api_key_hint else "",
        "enabled": item.enabled,
        "models": [_entry(model) for model in item.models],
        "updated_at": item.updated_at,
    }


async def _resolve_key(
    request: ModelDiscoveryRequest,
    store: PlatformStore,
    cipher: ModelSecretCipher,
) -> str:
    if request.api_key:
        return request.api_key.get_secret_value().strip()
    assert request.configuration_id is not None
    configuration = await store.get_model_configuration(request.configuration_id)
    if not configuration:
        raise ValueError("模型配置不存在")
    if configuration.category != request.category or configuration.provider != request.provider:
        raise ValueError("已有配置与当前分类或供应商不匹配")
    if configuration.base_url.rstrip("/") != request.base_url.rstrip("/"):
        raise ValueError("修改基础 URL 时必须重新输入 API Key")
    return cipher.decrypt(configuration.api_key_ciphertext)


async def _discover(
    request: ModelDiscoveryRequest,
    store: PlatformStore,
    cipher: ModelSecretCipher,
    discovery: ModelDiscoveryClient,
):
    key = await _resolve_key(request, store, cipher)
    result = await discovery.discover(
        category=request.category,
        provider=request.provider,
        base_url=request.base_url,
        api_key=key,
    )
    return key, result


@router.get("/providers")
async def list_model_providers(_: dict = Depends(get_current_user)):
    return {"items": provider_options()}


@router.get("")
async def list_model_configurations(
    _: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    items = await store.list_model_configurations()
    summary = {"text": 0, "image": 0, "video": 0, "audio": 0}
    for configuration in items:
        summary[configuration.category] += sum(
            int(configuration.enabled and model.enabled) for model in configuration.models
        )
    return {"items": [_configuration(item) for item in items], "summary": summary}


@router.post("/discover")
async def discover_models(
    request: ModelDiscoveryRequest,
    _: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
    discovery: ModelDiscoveryClient = Depends(get_model_discovery_client),
):
    try:
        _, result = await _discover(request, store, cipher, discovery)
        return {
            "items": [item.model_dump() for item in result.models],
            "total": len(result.models),
            "source_endpoint": result.source_endpoint,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/test")
async def test_model_connection(
    request: ModelTestRequest,
    _: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
    discovery: ModelDiscoveryClient = Depends(get_model_discovery_client),
):
    try:
        _, result = await _discover(request, store, cipher, discovery)
        discovered = {item.model_id for item in result.models}
        missing = [model_id for model_id in request.selected_model_ids if model_id not in discovered]
        if missing:
            raise ValueError("所选模型已不在供应商返回的动态列表中")
        return {
            "connected": True,
            "message": f"连接成功，已验证 {len(request.selected_model_ids)} 个模型",
            "selected_model_ids": request.selected_model_ids,
            "source_endpoint": result.source_endpoint,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("")
async def save_model_configuration(
    request: ModelSaveRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
    discovery: ModelDiscoveryClient = Depends(get_model_discovery_client),
):
    try:
        key, result = await _discover(request, store, cipher, discovery)
        by_id = {item.model_id: item for item in result.models}
        if any(model_id not in by_id for model_id in request.selected_model_ids):
            raise ValueError("所选模型已不在供应商返回的动态列表中")
        saved = await store.save_model_configuration(
            actor_id=admin["user_id"],
            category=request.category,
            provider=request.provider,
            base_url=request.base_url.rstrip("/"),
            api_key_ciphertext=cipher.encrypt(key),
            api_key_hint=key[-4:],
            models=[by_id[model_id].model_dump() for model_id in request.selected_model_ids],
        )
        await hydrate_runtime_model_registry(store, cipher)
        return _configuration(saved)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{configuration_id}")
async def toggle_model_configuration(
    configuration_id: str,
    request: CapabilityToggleRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
):
    try:
        item = await store.set_model_configuration_enabled(
            configuration_id, request.enabled, actor_id=admin["user_id"]
        )
        await hydrate_runtime_model_registry(store, cipher)
        return _configuration(item)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{configuration_id}/models/{entry_id}")
async def toggle_configured_model(
    configuration_id: str,
    entry_id: str,
    request: CapabilityToggleRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
):
    try:
        item = await store.set_configured_model_enabled(
            configuration_id, entry_id, request.enabled, actor_id=admin["user_id"]
        )
        await hydrate_runtime_model_registry(store, cipher)
        return _entry(item)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

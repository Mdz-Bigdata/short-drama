from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth_api import get_current_user, require_admin
from app.core.model_configuration import (
    DOCUMENTED_VIDEO_CATALOG_PROVIDERS,
    ModelDiscoveryClient,
    ModelSecretCipher,
    provider_label,
    provider_options,
)
from app.core.credential_pool import credential_pool
from app.core.market import Market
from app.core.providers import comfyui
from app.core.providers.declarative_video import PLACEHOLDERS, VideoEndpointSpec, declared_video_endpoints
from app.core.providers.elevenlabs_capabilities import elevenlabs_capability_catalog
from app.platform.dependencies import (
    get_model_discovery_client,
    get_model_secret_cipher,
    get_platform_store,
)
from app.platform.runtime_models import hydrate_runtime_model_registry
from app.platform.store import PlatformStore
from app.schema.platform import (
    CapabilityToggleRequest,
    ModelCredentialCreateRequest,
    ModelCredentialUpdateRequest,
    ModelDiscoveryRequest,
    ModelSaveRequest,
    ModelTestRequest,
    VideoEndpointSaveRequest,
)


router = APIRouter(prefix="/api/model-configurations", tags=["模型配置"])
MODEL_CATEGORIES = ("text", "image", "video", "audio")


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


def _credential(item, configuration_id: str) -> dict:
    return {
        "id": item.id,
        "label": item.label or f"****{item.api_key_hint}",
        "key_hint": f"****{item.api_key_hint}",
        "buckets": list(item.buckets or []),
        "enabled": item.enabled,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        **credential_pool.status(configuration_id, item.id),
    }


def _video_endpoint(raw: dict) -> dict:
    spec = raw.get("spec") or {}
    return {
        "family": spec.get("family"), "label": spec.get("label"), "base_url": spec.get("base_url"),
        "model_ids": list(spec.get("model_ids") or []), "modes": list(spec.get("modes") or []),
        "has_api_key": bool(raw.get("api_key_ciphertext")), "key_hint": f"****{raw.get('api_key_hint')}" if raw.get("api_key_hint") else "",
        "enabled": raw.get("enabled", True), "ready": declared_video_endpoints.ready(str(spec.get("family") or "")), "spec": spec,
    }


async def _settings_view(store: PlatformStore) -> dict:
    endpoints = (await store.get_setting("video_endpoints")).get("items") or []
    return {
        "video_endpoints": [_video_endpoint(raw) for raw in endpoints if isinstance(raw, dict)],
        "video_endpoint_placeholders": list(PLACEHOLDERS),
        "comfyui": comfyui.status(),
    }


def _configuration(item, credentials: list | None = None) -> dict:
    response = {
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
        "credentials": [_credential(credential, item.id) for credential in (credentials or [])],
    }
    response["service_capabilities"] = (
        elevenlabs_capability_catalog() if item.provider == "elevenlabs" else []
    )
    return response


def _global_status(items) -> tuple[dict[str, int], dict]:
    enabled_models: dict[str, list] = {category: [] for category in MODEL_CATEGORIES}
    for configuration in items:
        if not configuration.enabled:
            continue
        enabled_models[configuration.category].extend(
            model for model in configuration.models if model.enabled
        )

    enabled_model_ids = {
        category: list(dict.fromkeys(model.model_id for model in models))
        for category, models in enabled_models.items()
    }
    default_model_ids: dict[str, str | None] = {}
    for category, models in enabled_models.items():
        preferred = (
            next((model for model in models if model.subcategory == "tts"), None)
            if category == "audio"
            else None
        )
        selected = preferred or (models[0] if models else None)
        default_model_ids[category] = selected.model_id if selected else None

    summary = {
        category: len(enabled_models[category]) for category in MODEL_CATEGORIES
    }
    enabled_total = sum(len(model_ids) for model_ids in enabled_model_ids.values())
    return summary, {
        "configured": enabled_total > 0,
        "enabled_total": enabled_total,
        "enabled_model_ids": enabled_model_ids,
        "default_model_ids": default_model_ids,
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
    *,
    allow_catalog_fallback: bool = False,
    allow_invalid_key_fallback: bool = True,
):
    key = await _resolve_key(request, store, cipher)
    # Documented-catalog video providers have no enumeration endpoint to verify against.
    allow_catalog_fallback = allow_catalog_fallback or (
        request.category == "video" and request.provider in DOCUMENTED_VIDEO_CATALOG_PROVIDERS
    )
    result = await discovery.discover(
        category=request.category,
        provider=request.provider,
        base_url=request.base_url,
        api_key=key,
        allow_catalog_fallback=allow_catalog_fallback,
        allow_invalid_key_fallback=allow_invalid_key_fallback,
    )
    return key, result


@router.get("/providers")
async def list_model_providers(_: dict = Depends(get_current_user)):
    return {"items": provider_options(), "self_hosted": [comfyui.status()]}


@router.get("")
async def list_model_configurations(
    _: dict = Depends(get_current_user),
    store: PlatformStore = Depends(get_platform_store),
):
    items = await store.list_model_configurations()
    summary, global_status = _global_status(items)
    credentials: dict[str, list] = {}
    for credential in await store.list_model_credentials():
        credentials.setdefault(credential.configuration_id, []).append(credential)
    return {
        "items": [_configuration(item, credentials.get(item.id)) for item in items],
        "summary": summary,
        "global_status": global_status,
        "settings": await _settings_view(store),
    }


# ---------------------------------------------------------------- global settings: declared video endpoints


@router.put("/settings/video-endpoints/{family}")
async def save_video_endpoint(
    family: str,
    request: VideoEndpointSaveRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
):
    """Declare (or update) one video provider in data; the key is kept encrypted like any other."""
    try:
        spec = VideoEndpointSpec.model_validate({**request.spec, "family": family})
        spec.check()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    current = (await store.get_setting("video_endpoints")).get("items") or []
    existing = next((raw for raw in current if isinstance(raw, dict) and (raw.get("spec") or {}).get("family") == family), None)
    key = request.api_key.get_secret_value().strip() if request.api_key else ""
    if not key and not (existing or {}).get("api_key_ciphertext"):
        raise HTTPException(status_code=422, detail="首次声明端点时必须提供 API Key")
    entry = {
        "spec": spec.model_dump(mode="json"),
        "enabled": request.enabled,
        "api_key_ciphertext": cipher.encrypt(key) if key else existing["api_key_ciphertext"],
        "api_key_hint": key[-4:] if key else existing.get("api_key_hint", ""),
    }
    items = [raw for raw in current if isinstance(raw, dict) and (raw.get("spec") or {}).get("family") != family] + [entry]
    await store.put_setting("video_endpoints", {"items": items}, actor_id=admin["user_id"])
    await hydrate_runtime_model_registry(store, cipher)
    return _video_endpoint(entry)


@router.delete("/settings/video-endpoints/{family}")
async def delete_video_endpoint(
    family: str,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
):
    current = (await store.get_setting("video_endpoints")).get("items") or []
    items = [raw for raw in current if isinstance(raw, dict) and (raw.get("spec") or {}).get("family") != family]
    if len(items) == len(current):
        raise HTTPException(status_code=404, detail="没有这个声明式端点")
    await store.put_setting("video_endpoints", {"items": items}, actor_id=admin["user_id"])
    # Uninstalling a market entry is deleting its endpoint: the install record goes with it.
    await Market(store).forget_install(family, actor_id=admin["user_id"])
    await hydrate_runtime_model_registry(store, cipher)
    return {"family": family, "deleted": True}


# ---------------------------------------------------------------- extra credentials per configuration


@router.post("/{configuration_id}/credentials")
async def add_model_credential(
    configuration_id: str,
    request: ModelCredentialCreateRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
):
    key = request.api_key.get_secret_value().strip()
    if len(key) < 6:
        raise HTTPException(status_code=422, detail="API Key 太短")
    try:
        credential = await store.add_model_credential(
            configuration_id, actor_id=admin["user_id"], label=request.label.strip(),
            api_key_ciphertext=cipher.encrypt(key), api_key_hint=key[-4:], buckets=request.buckets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await hydrate_runtime_model_registry(store, cipher)
    return _credential(credential, configuration_id)


@router.patch("/{configuration_id}/credentials/{credential_id}")
async def update_model_credential(
    configuration_id: str,
    credential_id: str,
    request: ModelCredentialUpdateRequest,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
):
    try:
        credential = await store.update_model_credential(
            configuration_id, credential_id, actor_id=admin["user_id"], enabled=request.enabled, buckets=request.buckets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await hydrate_runtime_model_registry(store, cipher)
    return _credential(credential, configuration_id)


@router.delete("/{configuration_id}/credentials/{credential_id}")
async def delete_model_credential(
    configuration_id: str,
    credential_id: str,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
):
    try:
        result = await store.delete_model_credential(configuration_id, credential_id, actor_id=admin["user_id"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await hydrate_runtime_model_registry(store, cipher)
    return result


@router.post("/discover")
async def discover_models(
    request: ModelDiscoveryRequest,
    _: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
    discovery: ModelDiscoveryClient = Depends(get_model_discovery_client),
):
    try:
        _, result = await _discover(
            request, store, cipher, discovery, allow_catalog_fallback=True
        )
        return {
            "items": [item.model_dump() for item in result.models],
            "total": len(result.models),
            "source_endpoint": result.source_endpoint,
            "credential_verified": result.credential_verified,
            "warnings": list(result.warnings),
            "service_capabilities": (
                elevenlabs_capability_catalog()
                if request.provider == "elevenlabs" and request.category == "audio"
                else []
            ),
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
            "message": (
                f"连接成功，已验证 {len(request.selected_model_ids)} 个模型"
                if result.credential_verified
                else f"已加载 {len(request.selected_model_ids)} 个官方目录模型；该供应商不提供模型枚举接口，凭据将在首次生成时验证"
            ),
            "credential_verified": result.credential_verified,
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
        key, result = await _discover(
            request,
            store,
            cipher,
            discovery,
            allow_catalog_fallback=request.provider == "elevenlabs" and request.category == "audio",
            allow_invalid_key_fallback=False,
        )
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
        response = _configuration(saved)
        response["credential_verified"] = result.credential_verified
        response["warnings"] = list(result.warnings)
        return response
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


@router.delete("/{configuration_id}/models/{entry_id}")
async def delete_configured_model(
    configuration_id: str,
    entry_id: str,
    admin: dict = Depends(require_admin),
    store: PlatformStore = Depends(get_platform_store),
    cipher: ModelSecretCipher = Depends(get_model_secret_cipher),
):
    try:
        result = await store.delete_configured_model(
            configuration_id, entry_id, actor_id=admin["user_id"]
        )
        await hydrate_runtime_model_registry(store, cipher)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

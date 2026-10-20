"""Process-local view of encrypted global model configuration for provider adapters."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from app import settings
from app.core.credential_pool import Credential
from app.core.model_configuration import ModelSecretCipher


@dataclass(frozen=True)
class RuntimeModelConfiguration:
    configuration_id: str
    category: str
    provider: str
    base_url: str
    api_key: str
    model_ids: tuple[str, ...]
    # The primary key first, then every enabled extra credential; calls rotate across them.
    credentials: tuple[Credential, ...] = ()
    # Text models the configuration centre marked as able to read images.
    multimodal_ids: tuple[str, ...] = ()

    def credentials_for(self, bucket: str) -> tuple[Credential, ...]:
        pool = self.credentials or (Credential(id="primary", api_key=self.api_key, label="主凭据"),)
        return tuple(c for c in pool if c.serves(bucket))


class RuntimeModelRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._configurations: tuple[RuntimeModelConfiguration, ...] = ()

    def replace(self, configurations: list[RuntimeModelConfiguration]) -> None:
        with self._lock:
            self._configurations = tuple(configurations)

    def resolve(self, model_id: str, category: str) -> RuntimeModelConfiguration | None:
        with self._lock:
            return next(
                (
                    item for item in self._configurations
                    if item.category == category and model_id in item.model_ids
                ),
                None,
            )

    def first(self, provider: str, category: str) -> RuntimeModelConfiguration | None:
        with self._lock:
            return next(
                (
                    item for item in self._configurations
                    if item.provider == provider and item.category == category
                ),
                None,
            )

    def list(self, category: str) -> tuple[RuntimeModelConfiguration, ...]:
        with self._lock:
            return tuple(item for item in self._configurations if item.category == category)

    def vision_model(self, preferred: str = "") -> tuple[RuntimeModelConfiguration, str] | None:
        """A text model that can read images: ``preferred`` when it can, else the first configured one."""
        with self._lock:
            texts = [item for item in self._configurations if item.category == "text"]
        for item in texts:
            if preferred and preferred in item.multimodal_ids:
                return item, preferred
        for item in texts:
            if item.multimodal_ids:
                return item, item.multimodal_ids[0]
        return None

    def first_for_category(self, category: str) -> RuntimeModelConfiguration | None:
        """Return the deterministic global fallback for an enabled model category."""
        with self._lock:
            return next(
                (
                    item for item in self._configurations
                    if item.category == category and item.model_ids
                ),
                None,
            )


runtime_model_registry = RuntimeModelRegistry()


def provider_key_available(provider: str, category: str, env_name: str) -> bool:
    """Whether a provider can be called: a key saved in the configuration centre, or one in the environment."""
    saved = runtime_model_registry.first(provider, category)
    return bool(saved and saved.api_key.strip()) or settings.is_configured(os.getenv(env_name))


async def hydrate_runtime_model_registry(store, cipher: ModelSecretCipher) -> int:
    runtime: list[RuntimeModelConfiguration] = []
    extra = {}
    for credential in await store.list_model_credentials():
        extra.setdefault(credential.configuration_id, []).append(credential)
    for configuration in await store.list_model_configurations():
        if not configuration.enabled:
            continue
        model_ids = tuple(item.model_id for item in configuration.models if item.enabled)
        if not model_ids:
            continue
        primary = cipher.decrypt(configuration.api_key_ciphertext)
        credentials = [Credential(id="primary", api_key=primary, label="主凭据")]
        for item in extra.get(configuration.id, []):
            if item.enabled:
                credentials.append(Credential(
                    id=item.id, api_key=cipher.decrypt(item.api_key_ciphertext), label=item.label or f"****{item.api_key_hint}",
                    buckets=tuple(str(b) for b in (item.buckets or [])),
                ))
        runtime.append(RuntimeModelConfiguration(
            configuration_id=configuration.id,
            category=configuration.category,
            provider=configuration.provider,
            base_url=configuration.base_url,
            api_key=primary,
            model_ids=model_ids,
            credentials=tuple(credentials),
            multimodal_ids=tuple(
                item.model_id for item in configuration.models
                if item.enabled and "multimodal" in (item.capabilities or [])
            ),
        ))
    runtime_model_registry.replace(runtime)
    await hydrate_runtime_settings(store, cipher)
    return len(runtime)


async def hydrate_runtime_settings(store, cipher: ModelSecretCipher) -> None:
    """Global settings the gateway reads at call time: text tiers and declared video endpoints."""
    from app.core.providers.declarative_video import VideoEndpointSpec, declared_video_endpoints

    entries = []
    for raw in (await store.get_setting("video_endpoints")).get("items") or []:
        try:
            spec = VideoEndpointSpec.model_validate(raw.get("spec") or {})
            spec.check()
            key = cipher.decrypt(raw["api_key_ciphertext"]) if raw.get("api_key_ciphertext") else ""
        except (ValueError, KeyError, TypeError, RuntimeError):
            continue
        if raw.get("enabled", True):
            entries.append((spec, key))
    declared_video_endpoints.replace(entries)

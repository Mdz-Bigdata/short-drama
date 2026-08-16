"""Process-local view of encrypted global model configuration for provider adapters."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from app.core.model_configuration import ModelSecretCipher


@dataclass(frozen=True)
class RuntimeModelConfiguration:
    configuration_id: str
    category: str
    provider: str
    base_url: str
    api_key: str
    model_ids: tuple[str, ...]


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


async def hydrate_runtime_model_registry(store, cipher: ModelSecretCipher) -> int:
    runtime: list[RuntimeModelConfiguration] = []
    for configuration in await store.list_model_configurations():
        if not configuration.enabled:
            continue
        model_ids = tuple(item.model_id for item in configuration.models if item.enabled)
        if not model_ids:
            continue
        runtime.append(RuntimeModelConfiguration(
            configuration_id=configuration.id,
            category=configuration.category,
            provider=configuration.provider,
            base_url=configuration.base_url,
            api_key=cipher.decrypt(configuration.api_key_ciphertext),
            model_ids=model_ids,
        ))
    runtime_model_registry.replace(runtime)
    return len(runtime)

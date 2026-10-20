from __future__ import annotations

from functools import lru_cache

from app import settings
from app.core.model_configuration import ModelDiscoveryClient, ModelSecretCipher
from app.platform.store import PlatformStore



@lru_cache(maxsize=1)
def get_platform_store() -> PlatformStore:
    return PlatformStore(settings.database_url())


@lru_cache(maxsize=1)
def get_model_discovery_client() -> ModelDiscoveryClient:
    return ModelDiscoveryClient()


@lru_cache(maxsize=1)
def get_model_secret_cipher() -> ModelSecretCipher:
    return ModelSecretCipher.from_environment(settings.RUNTIME_DIR)

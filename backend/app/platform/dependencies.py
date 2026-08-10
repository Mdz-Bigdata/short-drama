from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.core.model_configuration import ModelDiscoveryClient, ModelSecretCipher
from app.platform.store import PlatformStore


DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/short-drama"


@lru_cache(maxsize=1)
def get_platform_store() -> PlatformStore:
    return PlatformStore(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))


@lru_cache(maxsize=1)
def get_model_discovery_client() -> ModelDiscoveryClient:
    return ModelDiscoveryClient()


@lru_cache(maxsize=1)
def get_model_secret_cipher() -> ModelSecretCipher:
    backend_root = Path(__file__).resolve().parents[2]
    return ModelSecretCipher.from_environment(backend_root / "runtime")

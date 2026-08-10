from __future__ import annotations

import os
from pathlib import Path

from app.platform.store import PlatformStore


RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
BOOTSTRAP_CREDENTIAL_FILE = RUNTIME_DIR / "bootstrap-admin.txt"
DEVELOPMENT_DEFAULT_ADMIN_LOGIN = "admin@short-drama"
DEVELOPMENT_DEFAULT_ADMIN_PASSWORD = "admin@123"


def bootstrap_admin_login() -> str:
    return (os.getenv("BOOTSTRAP_ADMIN_LOGIN") or DEVELOPMENT_DEFAULT_ADMIN_LOGIN).strip().lower()


async def initialize_platform(store: PlatformStore) -> dict:
    environment = (os.getenv("ENVIRONMENT") or "development").lower()
    default_enabled = "0" if environment in {"prod", "production"} else "1"
    bootstrap_enabled = os.getenv("BOOTSTRAP_ADMIN", default_enabled) == "1"
    login = bootstrap_admin_login()
    configured_password = (os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or "").strip()
    password = configured_password or (
        DEVELOPMENT_DEFAULT_ADMIN_PASSWORD
        if environment not in {"prod", "production"}
        else ""
    )

    if bootstrap_enabled and environment in {"prod", "production"}:
        if password == DEVELOPMENT_DEFAULT_ADMIN_PASSWORD:
            raise RuntimeError("生产环境禁止使用默认管理员密码 admin@123")
        if len(password) < 12:
            raise RuntimeError("生产环境启用管理员初始化时必须配置至少 12 位独立强密码")

    await store.create_schema()
    await store.seed_capabilities()
    await store.seed_billing_plans()

    if not bootstrap_enabled:
        return {"admin_created": False, "credential_file": None}

    admin, created = await store.bootstrap_admin(password, login=login)
    return {
        "admin_created": created,
        "admin_id": admin.id,
        "admin_login": login,
        "credential_file": None,
    }


def remove_bootstrap_credential_file() -> None:
    BOOTSTRAP_CREDENTIAL_FILE.unlink(missing_ok=True)

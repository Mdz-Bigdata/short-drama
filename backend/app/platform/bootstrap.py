from __future__ import annotations

import os

from app import settings
from app.platform.store import PlatformStore
from app.core import prompt_data


_WORDING_FILE = "platform_bootstrap"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/platform_bootstrap.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


BOOTSTRAP_CREDENTIAL_FILE = settings.RUNTIME_DIR / "bootstrap-admin.txt"
DEVELOPMENT_DEFAULT_ADMIN_LOGIN = "admin@short-drama"
DEVELOPMENT_DEFAULT_ADMIN_PASSWORD = "admin@123"


def bootstrap_admin_login() -> str:
    return (os.getenv("BOOTSTRAP_ADMIN_LOGIN") or DEVELOPMENT_DEFAULT_ADMIN_LOGIN).strip().lower()


def bootstrap_admin_enabled() -> bool:
    default_enabled = "0" if settings.is_production() else "1"
    return os.getenv("BOOTSTRAP_ADMIN", default_enabled) == "1"


def development_admin_login_hint() -> str | None:
    """Login of the local bootstrap administrator, for the development login page only."""
    if settings.is_production() or not bootstrap_admin_enabled():
        return None
    return bootstrap_admin_login()


async def initialize_platform(store: PlatformStore) -> dict:
    production = settings.is_production()
    bootstrap_enabled = bootstrap_admin_enabled()
    login = bootstrap_admin_login()
    configured_password = (os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or "").strip()
    password = configured_password or (
        DEVELOPMENT_DEFAULT_ADMIN_PASSWORD
        if not production
        else ""
    )

    if bootstrap_enabled and production:
        if password == DEVELOPMENT_DEFAULT_ADMIN_PASSWORD:
            raise RuntimeError(_text_of("initialize_platform.text"))
        if len(password) < settings.PRODUCTION_ADMIN_PASSWORD_MIN_LENGTH:
            raise RuntimeError(
                _text_of("initialize_platform.text.2").format(settings.PRODUCTION_ADMIN_PASSWORD_MIN_LENGTH)
            )

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

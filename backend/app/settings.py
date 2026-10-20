"""Deployment-dependent values, resolved from the environment in one place.

Hosts, ports, origins and public addresses differ between a laptop and a real
deployment, so none of them may be written into the modules that use them.
Every accessor reads the environment when it is called rather than at import:
``main.py`` loads ``backend/.env`` before the application is imported, and the
tests patch ``os.environ`` around individual calls.

This module depends on the standard library only, so the synchronous task
repository can use it without importing the async platform stack.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit


BACKEND_ROOT = Path(__file__).resolve().parents[1]
# Keys, private uploads and local stores that must never sit under the public media mount.
RUNTIME_DIR = BACKEND_ROOT / "runtime"
# Every skill — and all production knowledge, which lives inside skills — is found under this directory.
DEFAULT_SKILLS_DIR = BACKEND_ROOT / "skills"

DEFAULT_ENVIRONMENT = "development"
PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production"})

DEFAULT_SERVER_HOST = "0.0.0.0"
DEFAULT_SERVER_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173
# Browsers treat these as different origins, so local development allows both.
LOCAL_DEVELOPMENT_HOSTS = ("localhost", "127.0.0.1")
LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})

# Generated audio, images and video are served from this route by ``main.py``.
MEDIA_ROUTE = "/media"
MEDIA_PREFIX = MEDIA_ROUTE + "/"

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/short-drama"
DEFAULT_SHARE_LINK_BASE_URL = "https://short-drama.volces.com/s"

AUTH_COOKIE_NAME = "auth_token"
DEFAULT_SESSION_TTL_SECONDS = 86_400
SESSION_TTL_BOUNDS = (300, 2_592_000)
DEFAULT_LOG_LEVEL = "INFO"

# Account policy. The login page reads these from the session endpoint instead of repeating them.
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 256
# The local bootstrap administrator may start shorter; it must be changed on first login.
BOOTSTRAP_ADMIN_PASSWORD_MIN_LENGTH = 8
PRODUCTION_ADMIN_PASSWORD_MIN_LENGTH = 12
VERIFICATION_CODE_LENGTH = 6
VERIFICATION_CODE_MAX_ATTEMPTS = 5
DEFAULT_CODE_COOLDOWN_SECONDS = 60
CODE_COOLDOWN_BOUNDS = (10, 300)
DEFAULT_CODE_TTL_SECONDS = 300
CODE_TTL_BOUNDS = (60, 900)
DEFAULT_SMS_ENDPOINT = "dysmsapi.aliyuncs.com"
# Example files ship keys as YOUR_<NAME>; such a value means "not configured".
PLACEHOLDER_PREFIX = "YOUR_"

_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _text(name: str) -> str:
    return (os.getenv(name) or "").strip()


def env_int(name: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    """An integer knob clamped to its bounds; an unparseable value means the default."""
    try:
        value = int(_text(name) or default)
    except ValueError:
        value = default
    value = max(minimum, value)
    return value if maximum is None else min(maximum, value)


def env_float(name: str, default: float, *, minimum: float, maximum: float | None = None) -> float:
    try:
        value = float(_text(name) or default)
    except ValueError:
        value = default
    value = max(minimum, value)
    return value if maximum is None else min(maximum, value)


def env_flag(name: str, default: bool) -> bool:
    """A switch: unset keeps the default, and 0 / false / no / off turn it off."""
    raw = _text(name).lower()
    return default if not raw else raw not in _FALSE_VALUES


def is_configured(value: object) -> bool:
    """Whether a credential or address was really supplied, not left as a placeholder."""
    return bool(isinstance(value, str) and value.strip() and not value.startswith(PLACEHOLDER_PREFIX))


def _port(name: str, default: int) -> int:
    raw = _text(name)
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a TCP port number, got {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError(f"{name} must be between 1 and 65535, got {port}")
    return port


def skills_root() -> Path:
    """Where the bundled skills live; ``SKILLS_DIR`` moves them (a deployment that ships them elsewhere)."""
    configured = _text("SKILLS_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_SKILLS_DIR


def environment() -> str:
    return (_text("ENVIRONMENT") or DEFAULT_ENVIRONMENT).lower()


def is_production() -> bool:
    return environment() in PRODUCTION_ENVIRONMENTS


def server_host() -> str:
    return _text("BACKEND_HOST") or DEFAULT_SERVER_HOST


def server_port() -> int:
    return _port("BACKEND_PORT", DEFAULT_SERVER_PORT)


def server_reload() -> bool:
    """Auto-reload on source changes; a development convenience by default."""
    return env_flag("BACKEND_RELOAD", not is_production())


def log_level() -> str:
    return (_text("LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper()


def cookie_secure() -> bool:
    """Send the session cookie over HTTPS only; switch on behind TLS."""
    return _text("COOKIE_SECURE") == "1"


def session_ttl_seconds() -> int:
    """Lifetime shared by the signed session token and the cookie that carries it."""
    minimum, maximum = SESSION_TTL_BOUNDS
    return env_int("AUTH_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS, minimum=minimum, maximum=maximum)


def code_cooldown_seconds() -> int:
    """Seconds one login id must wait before requesting another verification code."""
    minimum, maximum = CODE_COOLDOWN_BOUNDS
    return env_int("AUTH_CODE_COOLDOWN_SECONDS", DEFAULT_CODE_COOLDOWN_SECONDS, minimum=minimum, maximum=maximum)


def code_ttl_seconds() -> int:
    minimum, maximum = CODE_TTL_BOUNDS
    return env_int("AUTH_CODE_TTL_SECONDS", DEFAULT_CODE_TTL_SECONDS, minimum=minimum, maximum=maximum)


def sms_endpoint() -> str:
    return _text("ALIBABA_CLOUD_SMS_ENDPOINT") or DEFAULT_SMS_ENDPOINT


def frontend_port() -> int:
    return _port("FRONTEND_PORT", DEFAULT_FRONTEND_PORT)


def allowed_origins() -> list[str]:
    """Origins allowed to send credentialed and state-changing requests."""
    configured = [item.strip() for item in _text("ALLOWED_ORIGINS").split(",") if item.strip()]
    if configured:
        return configured
    port = frontend_port()
    return [f"http://{host}:{port}" for host in LOCAL_DEVELOPMENT_HOSTS]


def public_base_url() -> str:
    """Address clients use to reach this backend, without a trailing slash."""
    configured = _text("PUBLIC_BASE_URL").rstrip("/")
    return configured or f"http://localhost:{server_port()}"


def media_public_base_url() -> str:
    """Public address of the generated-media route."""
    return _text("MEDIA_PUBLIC_BASE_URL") or f"{public_base_url()}{MEDIA_ROUTE}"


def own_media_hostnames(media_base_url: str | None = None) -> frozenset[str]:
    """Hostnames whose ``/media`` URLs are this server's own files on disk."""
    base = media_public_base_url() if media_base_url is None else media_base_url
    configured = (urlsplit(base).hostname or "").lower()
    return LOOPBACK_HOSTNAMES | {configured} if configured else LOOPBACK_HOSTNAMES


def database_url() -> str:
    return _text("DATABASE_URL") or DEFAULT_DATABASE_URL


def share_link_url(slug: str) -> str:
    base = _text("SHARE_LINK_BASE_URL") or DEFAULT_SHARE_LINK_BASE_URL
    return f"{base.rstrip('/')}/{slug}"


def private_storage_dir(variable: str, name: str, media_dir: str | os.PathLike[str]) -> Path:
    """A private upload directory: its own variable, else beside the media directory's runtime folder."""
    configured = _text(variable)
    root = Path(configured) if configured else Path(media_dir).parent / RUNTIME_DIR.name / name
    return root.expanduser().resolve()


# A local proxy in fake-IP mode (Clash, Surge, sing-box …) answers every DNS query from
# 198.18.0.0/15, the RFC 2544 benchmarking block, and carries the connection to the real
# host itself. Such an address is not a private network, so the public-host guards accept
# it — by default in development; a production server opts in with ALLOW_PROXY_FAKE_IP=1.
DEFAULT_PROXY_FAKE_IP_CIDR = "198.18.0.0/15"


def proxy_fake_ip_networks() -> tuple:
    import ipaddress

    if not env_flag("ALLOW_PROXY_FAKE_IP", not is_production()):
        return ()
    networks = []
    for part in (_text("PROXY_FAKE_IP_CIDR") or DEFAULT_PROXY_FAKE_IP_CIDR).split(","):
        try:
            networks.append(ipaddress.ip_network(part.strip(), strict=False))
        except ValueError:
            continue
    return tuple(networks)


def is_public_address(address: str) -> bool:
    """Whether a resolved address may be connected to: a global one, or the local proxy's fake-IP pool."""
    import ipaddress

    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip.is_global:
        return True
    return any(ip in network for network in proxy_fake_ip_networks())

"""What state the server is in, in checks an operator can read, and a bundle to hand to whoever helps.

Start-up runs the checks once and logs what is not well. The platform page runs them again on demand
and downloads the bundle: the report, which settings are set, and the recent log. Nothing in the bundle
is project content, and what it does carry goes through :func:`redact` first: keys and tokens, the
credentials and query of an address, e-mail addresses, phone numbers and long opaque strings are
masked, and the home directory is written ``~``. A setting's value is exported only when it is a number
or a switch; every other setting is exported as its length.

Names of the checks, what each outcome says, the limits and the bundle's note are in
``app/data/prompt/system_diagnostics.json``.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import platform
import re
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from app import settings
from app.core import prompt_data

logger = logging.getLogger("app.core.system_diagnostics")

_DATA = "system_diagnostics"
OK, WARNING, ERROR = "ok", "warning", "error"
_SEVERITY = {OK: 0, WARNING: 1, ERROR: 2}
MODEL_KINDS = ("text", "image", "video", "audio")
#: A project cannot be made without these three; sound has other routes.
REQUIRED_MODEL_KINDS = ("text", "image", "video")
MASK = "***"


def _says(section: str, key: str, **values: object) -> str:
    return str(prompt_data.value(_DATA, section)[key]).format(**values)


def _limit(key: str) -> int:
    return int(prompt_data.value(_DATA, "limits")[key])


@dataclass(frozen=True)
class Finding:
    id: str
    label: str
    status: str
    detail: str
    elapsed_ms: int = 0


class _Problem(Exception):
    """A check's own verdict that something is not well."""

    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


# ---------------------------------------------------------------------------------------------
# Masking


def _home_patterns() -> tuple[str, ...]:
    home = str(Path.home())
    return tuple(dict.fromkeys(p for p in (home, os.path.realpath(home)) if len(p) > 1))


_SECRET_NAME = r"(?:api[_-]?key|secret|token|password|passwd|pwd|authorization|access[_-]?key|signature|credential|cookie|session)"
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
#: A long run of key-like characters. A slash is left out so that a folder path is not taken for one;
#: base64 that does contain slashes is caught by its padding instead.
_OPAQUE = re.compile(r"(?<![A-Za-z0-9+_-])[A-Za-z0-9+_-]{32,}={0,2}|(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={1,2}")
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}"), rf"\1 {MASK}"),
    (re.compile(rf"(?i)([\w-]*{_SECRET_NAME}[\w-]*[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&]+"), rf"\1{MASK}"),
    (re.compile(r"\b(?:sk|pk|ak|rk)-[A-Za-z0-9_-]{8,}"), MASK),
    (re.compile(r"://[^/\s:@]+:[^/\s@]+@"), f"://{MASK}:{MASK}@"),
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s?\"'<>]+)\?[^\s\"'<>]+", re.I), rf"\1?{MASK}"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), f"{MASK}@{MASK}"),
    (re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"), MASK),
)


def redact(text: object) -> str:
    """``text`` with secrets, personal details and the home directory masked."""
    out = str(text)
    for home in _home_patterns():
        out = out.replace(home, "~")
    for rule, replacement in _RULES:
        out = rule.sub(replacement, out)
    return _OPAQUE.sub(lambda found: found.group(0) if _UUID.fullmatch(found.group(0)) else MASK, out)


# ---------------------------------------------------------------------------------------------
# The recent log


class RecentLog(logging.Handler):
    """The last lines the server logged, kept in memory for the bundle."""

    def __init__(self, capacity: int):
        super().__init__(level=logging.INFO)
        self._lines: deque[str] = deque(maxlen=max(1, capacity))
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._lines.append(self.format(record)[: _limit("log_line_chars")])
        except Exception:  # noqa: BLE001 - a log line that cannot be kept must not break the caller
            pass

    def lines(self) -> list[str]:
        return list(self._lines)


_recent: RecentLog | None = None
_recent_lock = threading.Lock()


def install_log_buffer() -> RecentLog:
    """Start keeping the recent log (once per process)."""
    global _recent
    with _recent_lock:
        if _recent is None:
            _recent = RecentLog(_limit("log_lines"))
            logging.getLogger().addHandler(_recent)
        return _recent


def recent_log() -> list[str]:
    return [redact(line) for line in (_recent.lines() if _recent else [])]


# ---------------------------------------------------------------------------------------------
# Checks


def format_bytes(count: float) -> str:
    size = max(0.0, float(count))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" or size >= 100 else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _writable(path: Path) -> str:
    if not path.is_dir():
        raise _Problem(ERROR, _says("details", "dir_missing", path=path))
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".diagnostics-", delete=True):
            pass
    except OSError as error:
        raise _Problem(ERROR, _says("details", "dir_readonly", path=path)) from error
    return _says("details", "dir_ok", path=path)


def _media_dir() -> Path:
    from app.core.media_compositor import MEDIA_DIR

    return Path(MEDIA_DIR)


def _check_runtime() -> str:
    return _says(
        "details", "runtime", python=sys.version.split()[0],
        system=f"{platform.system()} {platform.release()}", environment=settings.environment(),
    )


def _check_disk() -> str:
    usage = shutil.disk_usage(_media_dir() if _media_dir().exists() else settings.BACKEND_ROOT)
    said = {"free": format_bytes(usage.free), "total": format_bytes(usage.total)}
    if usage.free < _limit("disk_error_bytes"):
        raise _Problem(ERROR, _says("details", "disk_full", **said))
    if usage.free < _limit("disk_warning_bytes"):
        raise _Problem(WARNING, _says("details", "disk_low", **said))
    return _says("details", "disk_ok", **said)


def _check_binary(name: str) -> str:
    from app.core import media_compositor

    path = media_compositor._ffmpeg() if name == "ffmpeg" else media_compositor._ffprobe()
    if not path:
        raise _Problem(ERROR if name == "ffmpeg" else WARNING, _says("details", f"{name}_missing"))
    return _says("details", "binary_ok", path=path)


def _check_cipher() -> str:
    from app.platform.dependencies import get_model_secret_cipher

    try:
        get_model_secret_cipher()
    except Exception as error:  # noqa: BLE001 - whatever stops the cipher is the finding
        raise _Problem(ERROR, _says("details", "cipher_failed", error=_brief(error))) from error
    return _says("details", "cipher_ok")


def _check_models() -> str:
    from app.platform.runtime_models import runtime_model_registry

    counts = {
        kind: sum(len(item.model_ids) for item in runtime_model_registry.list(kind)) for kind in MODEL_KINDS
    }
    missing = [kind for kind in REQUIRED_MODEL_KINDS if not counts[kind]]
    if missing:
        names = prompt_data.value(_DATA, "kinds")
        kinds = str(prompt_data.value(_DATA, "kind_joiner")).join(str(names[kind]) for kind in missing)
        raise _Problem(WARNING, _says("details", "models_missing", kinds=kinds, **counts))
    return _says("details", "models_ok", **counts)


def _ratio_of(width: int, height: int) -> str:
    from math import gcd

    common = gcd(width, height) or 1
    return f"{width // common}:{height // common}"


def _check_aspect_ratio() -> str:
    """Storyboard pictures and video requests in one frame, and that frame 9:16 or 16:9."""
    import re as _re

    from app.core.providers.defaults import DEFAULT_ASPECT_RATIO, DEFAULT_SEEDANCE_IMAGE_SIZE

    image = (os.getenv("SEEDANCE_IMAGE_SIZE") or DEFAULT_SEEDANCE_IMAGE_SIZE).strip()
    found = _re.fullmatch(r"(\d{2,5})\s*[xX×*]\s*(\d{2,5})", image)
    if not found:
        raise _Problem(WARNING, _says("details", "ratio_unreadable", image=image))
    image_ratio = _ratio_of(int(found.group(1)), int(found.group(2)))
    videos = {
        name: (os.getenv(name) or DEFAULT_ASPECT_RATIO).strip() for name in ("VIDEO_ASPECT_RATIO", "MINIMAX_H3_ASPECT_RATIO")
    }
    if any(value != image_ratio for value in videos.values()):
        shown = "、".join(f"{name}={value}" for name, value in videos.items())
        raise _Problem(WARNING, _says("details", "ratio_mismatch", image_ratio=image_ratio, image=image, videos=shown))
    if image_ratio not in ("9:16", "16:9"):
        raise _Problem(WARNING, _says("details", "ratio_unusual", ratio=image_ratio))
    return _says("details", "ratio_ok", image=image, video=next(iter(videos.values())), ratio=image_ratio)


def _check_skills() -> str:
    root = settings.skills_root()
    count = sum(1 for _ in root.glob("*/SKILL.md")) if root.is_dir() else 0
    if not count:
        raise _Problem(ERROR, _says("details", "skills_missing", path=root))
    return _says("details", "skills_ok", count=count, path=root)


def _brief(error: BaseException) -> str:
    return f"{type(error).__name__}: {str(error)[:200]}"


def _timed_store(count: Callable[[], int], ok_key: str) -> Callable[[], str]:
    def check() -> str:
        started = time.monotonic()
        try:
            total = count()
        except Exception as error:  # noqa: BLE001 - whatever stops the store is the finding
            raise _Problem(ERROR, _says("details", "store_failed", error=_brief(error))) from error
        spent = int((time.monotonic() - started) * 1000)
        if spent > _limit("slow_store_ms"):
            raise _Problem(WARNING, _says("details", "store_slow", ms=spent))
        return _says("details", ok_key, count=total, ms=spent)

    return check


def _finding(check_id: str, check: Callable[[], str]) -> Finding:
    label = str(prompt_data.value(_DATA, "labels")[check_id])
    started = time.monotonic()
    try:
        status, detail = OK, check()
    except _Problem as problem:
        status, detail = problem.status, problem.detail
    except Exception as error:  # noqa: BLE001 - one check that breaks must not hide the others
        status, detail = ERROR, _says("details", "check_failed", error=_brief(error))
    return Finding(check_id, label, status, redact(detail), int((time.monotonic() - started) * 1000))


def local_checks(count_tasks: Callable[[], int] | None = None) -> list[Finding]:
    """Every check that needs no event loop. Blocking: it touches the disk and the project store."""
    checks: list[tuple[str, Callable[[], str]]] = [
        ("runtime", _check_runtime),
        ("media_dir", lambda: _writable(_media_dir())),
        ("runtime_dir", lambda: _writable(Path(settings.RUNTIME_DIR))),
        ("disk", _check_disk),
    ]
    if count_tasks is not None:
        checks.append(("task_store", _timed_store(count_tasks, "store_ok")))
    checks += [
        ("ffmpeg", lambda: _check_binary("ffmpeg")),
        ("ffprobe", lambda: _check_binary("ffprobe")),
        ("secret_cipher", _check_cipher),
        ("models", _check_models),
        ("aspect_ratio", _check_aspect_ratio),
        ("skills", _check_skills),
    ]
    return [_finding(check_id, check) for check_id, check in checks]


async def _platform_finding(count_users: Callable[[], Awaitable[int]]) -> Finding:
    label = str(prompt_data.value(_DATA, "labels")["platform_store"])
    started = time.monotonic()
    try:
        total = await count_users()
    except Exception as error:  # noqa: BLE001 - whatever stops the store is the finding
        spent = int((time.monotonic() - started) * 1000)
        return Finding("platform_store", label, ERROR, redact(_says("details", "store_failed", error=_brief(error))), spent)
    spent = int((time.monotonic() - started) * 1000)
    if spent > _limit("slow_store_ms"):
        return Finding("platform_store", label, WARNING, _says("details", "store_slow", ms=spent), spent)
    return Finding("platform_store", label, OK, _says("details", "platform_ok", count=total, ms=spent), spent)


def summarise(findings: Iterable[Finding]) -> dict[str, Any]:
    items = list(findings)
    worst = max((item.status for item in items), key=_SEVERITY.__getitem__, default=OK)
    return {
        "status": worst,
        "counts": {status: sum(1 for item in items if item.status == status) for status in (OK, WARNING, ERROR)},
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checks": [asdict(item) for item in items],
    }


async def run(
    count_users: Callable[[], Awaitable[int]] | None = None,
    count_tasks: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Run every check and say what was found."""
    findings = await asyncio.to_thread(local_checks, count_tasks)
    if count_users is not None:
        at = next((i + 1 for i, item in enumerate(findings) if item.id == "task_store"), len(findings))
        findings.insert(at, await _platform_finding(count_users))
    return summarise(findings)


_startup: dict[str, Any] | None = None


def startup_report() -> dict[str, Any] | None:
    """What the checks found when this process started."""
    return _startup


async def startup_self_check(
    count_users: Callable[[], Awaitable[int]] | None = None,
    count_tasks: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """Run the checks once at start-up, keep the result and log what is not well. Never raises."""
    global _startup
    try:
        report = await run(count_users, count_tasks)
    except Exception as error:  # noqa: BLE001 - the self-check must never stop the server starting
        logger.error("[启动自检] %s", _brief(error))
        return {}
    _startup = report
    problems = [item for item in report["checks"] if item["status"] != OK]
    for item in problems:
        log = logger.error if item["status"] == ERROR else logger.warning
        log(_says("startup", "problem", label=item["label"], detail=item["detail"]))
    if not problems:
        logger.info(_says("startup", "clear", count=len(report["checks"])))
    return report


# ---------------------------------------------------------------------------------------------
# Settings and the bundle

_ENV_NAME = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]{2,})\s*=")
_PLAIN_VALUE = re.compile(r"^(?:-?\d+(?:\.\d+)?|true|false|yes|no|on|off)$", re.I)


def known_setting_names(*files: Path) -> list[str]:
    """Setting names the server documents or was given: every ``NAME=`` line of the given env files."""
    names: set[str] = set()
    for file in files:
        try:
            lines = file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        names.update(found.group(1) for line in lines if (found := _ENV_NAME.match(line)))
    return sorted(names)


def settings_report(names: Iterable[str], environ: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Which settings are set. A value is shown only when it is a number or a switch."""
    env = os.environ if environ is None else environ
    report: dict[str, dict[str, Any]] = {}
    for name in names:
        value = (env.get(name) or "").strip()
        if not value:
            report[name] = {"set": False, "value": _says("settings", "unset")}
        elif _PLAIN_VALUE.match(value):
            report[name] = {"set": True, "value": value}
        else:
            report[name] = {"set": True, "value": _says("settings", "hidden", length=len(value))}
    return report


def _env_files() -> tuple[Path, Path]:
    return settings.BACKEND_ROOT / ".env.example", settings.BACKEND_ROOT / ".env"


def bundle(report: dict[str, Any], *, version: str = "") -> bytes:
    """The zip an operator hands over: the report, which settings are set, the recent log, and a note."""
    lines = recent_log()
    body = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": version,
        "python": sys.version.split()[0],
        "system": f"{platform.system()} {platform.release()} {platform.machine()}",
        "environment": settings.environment(),
        "directories": {
            "backend": redact(settings.BACKEND_ROOT), "media": redact(_media_dir()),
            "runtime": redact(settings.RUNTIME_DIR), "skills": redact(settings.skills_root()),
        },
        "now": report,
        "at_startup": startup_report(),
    }
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", _says("bundle", "readme", lines=_limit("log_lines")))
        archive.writestr("report.json", json.dumps(body, ensure_ascii=False, indent=2))
        archive.writestr(
            "settings.json",
            json.dumps(settings_report(known_setting_names(*_env_files())), ensure_ascii=False, indent=2),
        )
        archive.writestr("recent_log.txt", "\n".join(lines) if lines else _says("bundle", "empty_log"))
    return packed.getvalue()


def bundle_name(now: datetime | None = None) -> str:
    return f"diagnostics-{(now or datetime.now()).strftime('%Y%m%d-%H%M%S')}.zip"

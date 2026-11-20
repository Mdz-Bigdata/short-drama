"""Read-only share links for one canvas: issue, rotate, stop, and the stripped-down public view.

The idea follows open-ai-canvas share links (MIT): an unguessable token opens a frozen read of
the canvas for anyone holding it, and creating the link again rotates it.
"""

from __future__ import annotations

import hashlib
import math
import posixpath
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote, urlsplit

from app import settings
from app.repository.studio_repo import StudioRepository

SHARE_PATH_PREFIX = "/share/canvas/"
# secrets.token_urlsafe(24) is 32 characters; anything not shaped like one is not looked up at all.
_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{32}$")

# Node fields an anonymous viewer gets; the payload is filtered down to these and nothing else.
_NODE_FIELDS = ("id", "kind", "x", "y", "width", "height")
_PAYLOAD_TEXT = ("label", "title", "text", "prompt", "styleText", "medium", "groupId")
_PARAM_FIELDS = ("duration", "aspect")
# Belt and braces: even a whitelisted name is dropped if it reads like a credential.
_SECRET_MARKERS = ("token", "key", "secret", "cookie", "auth")
_FILENAME_LIMIT = 200


class CanvasShareNotFound(LookupError):
    """Unknown, expired and stopped tokens all end here, so they cannot be told apart."""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class SlidingWindowLimiter:
    """At most ``limit`` accepted hits per key in any ``window_seconds``; memory bounded by ``max_keys``."""

    def __init__(
        self, limit: int = 60, window_seconds: float = 60.0, *, clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self.max_keys:
                    self._prune(cutoff)
                hits = self._hits[key] = deque()
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def retry_after(self, key: str) -> int:
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 1
            return max(1, math.ceil(hits[0] + self.window_seconds - self.clock()))

    def _prune(self, cutoff: float) -> None:
        for key, hits in list(self._hits.items()):
            if not hits or hits[-1] <= cutoff:
                del self._hits[key]
        while len(self._hits) >= self.max_keys:
            del self._hits[next(iter(self._hits))]


# One per process: 60 public reads a minute from one client address.
PUBLIC_SHARE_LIMITER = SlidingWindowLimiter(limit=60, window_seconds=60.0)


def _is_secret_key(name: str) -> bool:
    lowered = name.casefold()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _normalized_path(path: str) -> str:
    # The same normalisation main._security_boundary applies before StaticFiles opens a file.
    decoded = unquote(path).replace("\\", "/")
    return posixpath.normpath("/" + decoded.lstrip("/")).casefold()


def _is_private_media(normalized: str) -> bool:
    private = f"{settings.MEDIA_ROUTE.casefold()}/elements"
    return normalized == private or normalized.startswith(private + "/")


def _media_path_is_public(path: str) -> bool:
    normalized = _normalized_path(path)
    return not _is_private_media(normalized) and normalized.startswith(settings.MEDIA_ROUTE.casefold() + "/")


def public_url(value: Any) -> str | None:
    """A /media/... path (never /media/elements) or an http(s) URL; data:, blob: and everything else are dropped."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or any(ch in text for ch in "\r\n\t\0"):
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.scheme in {"http", "https"}:
        if not parts.netloc:
            return None
        # Private element images stay private even when spelled as an absolute URL.
        return None if _is_private_media(_normalized_path(parts.path or "/")) else text
    if parts.scheme or parts.netloc or not text.startswith("/"):
        return None
    return text if _media_path_is_public(parts.path) else None


def sanitize_node(node: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {name: node.get(name) for name in _NODE_FIELDS}
    payload = node.get("payload") if isinstance(node.get("payload"), Mapping) else {}
    kept: dict[str, Any] = {}
    for name in _PAYLOAD_TEXT:
        if isinstance(payload.get(name), str) and not _is_secret_key(name):
            kept[name] = payload[name]
    if isinstance(payload.get("collapsed"), bool):
        kept["collapsed"] = payload["collapsed"]
    size = payload.get("expandedSize")
    if isinstance(size, (list, tuple)) and len(size) == 2 and all(_is_number(item) for item in size):
        kept["expandedSize"] = [size[0], size[1]]
    params = payload.get("params") if isinstance(payload.get("params"), Mapping) else {}
    kept_params: dict[str, Any] = {}
    if _is_number(params.get("duration")):
        kept_params["duration"] = params["duration"]
    if isinstance(params.get("aspect"), str):
        kept_params["aspect"] = params["aspect"]
    if kept_params:
        kept["params"] = {name: value for name, value in kept_params.items() if not _is_secret_key(name)}
    clean["payload"] = kept
    return clean


def sanitize_edge(edge: Mapping[str, Any]) -> dict[str, Any]:
    payload = edge.get("payload") if isinstance(edge.get("payload"), Mapping) else {}
    clean_payload = {"role": payload["role"]} if isinstance(payload.get("role"), str) else {}
    return {"id": edge.get("id"), "source": edge.get("source"), "target": edge.get("target"), "kind": edge.get("kind"), "payload": clean_payload}


def sanitize_output(output: Mapping[str, Any], *, medium: str = "") -> dict[str, Any] | None:
    url = public_url(output.get("url"))
    text = output.get("text") if isinstance(output.get("text"), str) and output.get("text") else None
    if url is None and text is None:
        return None
    filename = output.get("filename")
    filename = posixpath.basename(str(filename).replace("\\", "/"))[:_FILENAME_LIMIT] if isinstance(filename, str) and filename else None
    out_medium = output.get("medium") if isinstance(output.get("medium"), str) and output.get("medium") else medium
    return {"medium": str(out_medium or ""), "url": url, "text": text, "filename": filename or None}


class CanvasShareService:
    def __init__(self, repository: StudioRepository, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self.repository = repository
        self.clock = clock

    def _now(self) -> datetime:
        now = self.clock()
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)

    def _expired(self, row: Mapping[str, Any]) -> bool:
        expires = _parse_iso(row.get("expires_at"))
        return expires is not None and expires <= self._now()

    @staticmethod
    def _owner_view(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "token": row["token"], "url_path": SHARE_PATH_PREFIX + str(row["token"]),
            "expires_at": row.get("expires_at"), "created_at": row["created_at"],
        }

    def get_share(self, project_id: str, owner_id: str, canvas_id: str) -> dict[str, Any] | None:
        """The canvas's live link, or None when there is none (an expired link counts as none)."""
        row = self.repository.get_canvas_share(project_id, owner_id, canvas_id)
        if not row or self._expired(row):
            return None
        return self._owner_view(row)

    def create_share(self, project_id: str, owner_id: str, canvas_id: str, expires_days: int | None) -> dict[str, Any]:
        """A fresh token; whatever link the canvas had before stops working in the same write."""
        now = self._now()
        token = secrets.token_urlsafe(24)
        expires_at = (now + timedelta(days=expires_days)).isoformat() if expires_days else None
        row = self.repository.put_canvas_share(
            project_id, owner_id, canvas_id, token=token, token_hash=hash_token(token), expires_at=expires_at, created_at=now.isoformat(),
        )
        return self._owner_view(row)

    def stop_share(self, project_id: str, owner_id: str, canvas_id: str) -> dict[str, bool]:
        return {"stopped": self.repository.delete_canvas_share(project_id, owner_id, canvas_id)}

    def public_canvas(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or not _TOKEN_SHAPE.match(token):
            raise CanvasShareNotFound()
        row = self.repository.find_canvas_share(hash_token(token))
        if not row or self._expired(row):
            raise CanvasShareNotFound()
        project_id, owner_id, canvas_id = str(row["project_id"]), str(row["owner_id"]), str(row["canvas_id"])
        try:
            record = self.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
            active = self.repository.canvas_active_runs(project_id, owner_id, canvas_id=canvas_id)
        except PermissionError as exc:
            raise CanvasShareNotFound() from exc
        nodes = [node.model_dump(mode="json") for node in record.nodes] if record else []
        edges = [edge.model_dump(mode="json") for edge in record.edges] if record else []
        node_ids = {node["id"] for node in nodes}
        outputs: dict[str, dict[str, Any]] = {}
        # An upload carries its file on the node itself; a generated node shows its active run.
        for node in nodes:
            held = (node.get("payload") or {}).get("output")
            if isinstance(held, Mapping):
                clean = sanitize_output(held)
                if clean:
                    outputs[node["id"]] = clean
        for node_id, run in active.items():
            if node_id in node_ids and run.output:
                clean = sanitize_output(run.output, medium=run.medium)
                if clean:
                    outputs[node_id] = clean
        return {
            "title": self.repository.canvas_title(project_id, canvas_id),
            "canvas_id": canvas_id,
            "version": record.version if record else 0,
            "nodes": [sanitize_node(node) for node in nodes],
            "edges": [sanitize_edge(edge) for edge in edges if edge.get("source") in node_ids and edge.get("target") in node_ids],
            "outputs": outputs,
            "expires_at": row.get("expires_at"),
        }

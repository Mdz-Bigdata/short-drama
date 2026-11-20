# -*- coding: utf-8 -*-
"""A canvas together with its media, as one zip: export it, and import it into another project or board.

The plain export (``frontend/src/features/canvas/canvasExport.ts``) is the canvas JSON alone: pictures,
clips and sound stay as links to this server, so on another server, or once those files are gone, the
import shows empty nodes. The bundle carries the files:

* **Export** — the board's JSON in the same ``novara-canvas`` format (each node's current result
  written into it, as the plain export does) plus every file of this server's media it refers to,
  stored as ``media/<sha256>.<ext>``; the JSON points at them as ``bundle:media/<name>``. Private
  element-library files (``/media/elements``) are never packed, and links to other hosts are left
  as they are. Limits on file count and size come from ``app/data/prompt/canvas_bundle.json``.
* **Import** — every packed file is checked again by the rules of a canvas upload
  (``StudioService.store_canvas_upload``: the bytes decide the type, sizes are capped) and stored
  as a new file of the importing project; the JSON's references are rewritten to those files. What
  comes back is a plain ``novara-canvas`` manifest that the browser merges like any import (fresh
  ids, placed to the right, one undo step). A file that fails its check is dropped and counted, so
  one bad file never loses the whole canvas.

Capability after NovaNova Studio's canvas ZIP export / import (MIT, see THIRD_PARTY_NOTICES.md);
the format, checks and wording are this project's own.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import posixpath
import re
import zipfile
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote

from app import settings
from app.core import media_compositor, prompt_data

_DATA = "canvas_bundle"
EXPORT_FORMAT = "novara-canvas"
BUNDLE_VERSION = 2
PLAIN_VERSION = 1
REF_PREFIX = "bundle:media/"
_ENTRY = re.compile(r"^media/([0-9a-f]{16,64})\.(png|jpg|webp|mp4|webm|mp3|wav|m4a|aac|ogg)$")
_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "mp4": "video/mp4", "webm": "video/webm",
    "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "aac": "audio/aac", "ogg": "audio/ogg",
}


class BundleError(ValueError):
    """The bundle cannot be made or read; the message is for the person."""


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _limit(name: str) -> int:
    return int(prompt_data.value(_DATA, "limits")[name])


def _private(url: str) -> bool:
    """A file of the private element library: never leaves the server in a bundle."""
    path = url.split("?", 1)[0].split("#", 1)[0]
    base = media_compositor.PUBLIC_BASE_URL.rstrip("/")
    if path.startswith(base + "/"):
        path = settings.MEDIA_ROUTE + path[len(base):]
    normalized = posixpath.normpath("/" + unquote(path).replace("\\", "/").lstrip("/")).casefold()
    private = f"{settings.MEDIA_ROUTE.casefold()}/elements"
    return normalized == private or normalized.startswith(private + "/")


def _walk(value: Any, change) -> Any:
    """``value`` with every string passed through ``change`` (dicts and lists followed, other values kept)."""
    if isinstance(value, str):
        return change(value)
    if isinstance(value, Mapping):
        return {key: _walk(item, change) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk(item, change) for item in value]
    return value


def safe_title(title: str) -> str:
    printable = "".join(" " if ord(char) < 32 else char for char in str(title or ""))
    stem = re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|]+', " ", printable)).strip()[:80]
    return stem or _text("default_title")


def export_bundle(document: Mapping[str, Any], outputs: Mapping[str, Mapping[str, Any]], *, title: str) -> tuple[str, bytes, dict[str, int]]:
    """``(file name, zip bytes, counts)`` for a board: its JSON and the files of this server it shows.

    ``outputs`` are the nodes' current results (``StudioService.canvas_outputs()["outputs"]``).
    Counts: ``files`` packed, ``private`` element files left out, ``missing`` local links whose file is gone.
    """
    nodes = [dict(node) for node in document.get("nodes") or [] if isinstance(node, Mapping)]
    if not nodes:
        raise BundleError(_text("no_canvas"))
    packed: dict[str, str] = {}          # local file path -> entry name
    contents: dict[str, bytes] = {}      # entry name -> bytes
    counts = {"files": 0, "private": 0, "missing": 0}
    budget = {"bytes": 0}

    def change(text: str) -> str:
        if _private(text):
            counts["private"] += 1
            return ""
        path = media_compositor.local_media_path(text)
        if not path:
            return text
        if path in packed:
            return REF_PREFIX + packed[path].split("/", 1)[1]
        if not os.path.isfile(path):
            counts["missing"] += 1
            return text
        extension = os.path.splitext(path)[1].lstrip(".").lower()
        if extension not in _TYPES:
            return text
        if len(packed) >= _limit("max_files"):
            raise BundleError(_text("too_many").format(limit=_limit("max_files")))
        size = os.path.getsize(path)
        if budget["bytes"] + size > _limit("max_total_bytes"):
            raise BundleError(_text("too_big").format(limit=_limit("max_total_bytes") // (1024 * 1024)))
        with open(path, "rb") as handle:
            content = handle.read()
        budget["bytes"] += len(content)
        name = f"media/{hashlib.sha256(content).hexdigest()[:32]}.{'jpg' if extension == 'jpeg' else extension}"
        packed[path] = name
        contents.setdefault(name, content)
        return REF_PREFIX + name.split("/", 1)[1]

    shown = []
    for node in nodes:
        payload = dict(node.get("payload") or {})
        current = outputs.get(str(node.get("id") or ""))
        if isinstance(current, Mapping) and current.get("url"):
            payload["output"] = {key: value for key, value in current.items() if key != "run_id"}
        payload.pop("committed", None)
        shown.append({**node, "payload": _walk(payload, change)})
    counts["files"] = len(contents)
    manifest = {
        "format": EXPORT_FORMAT, "version": BUNDLE_VERSION, "title": str(title or ""),
        "exported_at": datetime.now(timezone.utc).isoformat(), "nodes": shown,
        "edges": [dict(edge) for edge in document.get("edges") or [] if isinstance(edge, Mapping)], "viewport": None,
        "bundle": {"files": counts["files"], "private_left_out": counts["private"], "missing": counts["missing"]},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(_text("manifest_name"), json.dumps(manifest, ensure_ascii=False, indent=2), compress_type=zipfile.ZIP_DEFLATED)
        for name, content in sorted(contents.items()):
            # Pictures, clips and sound are compressed already.
            archive.writestr(name, content, compress_type=zipfile.ZIP_STORED)
    return _text("file_name").format(title=safe_title(title)), buffer.getvalue(), counts


def import_bundle(data: bytes, store) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(plain manifest, report)`` from a bundle; ``store(name, content_type, bytes) -> {"url": …}`` keeps one file.

    ``store`` is the canvas upload of the importing project (it checks the bytes and raises ``ValueError``
    for a file it refuses). The manifest that comes back has links to the stored files and is version 1, the
    plain format the browser's import reads. Report: ``files`` stored, ``failed`` ``[{name, reason}]``,
    ``missing`` references to files the bundle does not hold.
    """
    if len(data) > _limit("max_upload_bytes"):
        raise BundleError(_text("upload_too_big").format(limit=_limit("max_upload_bytes") // (1024 * 1024)))
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError) as error:
        raise BundleError(_text("not_zip")) from error
    manifest_name = _text("manifest_name")
    entries: dict[str, zipfile.ZipInfo] = {}
    manifest_info = None
    for info in infos:
        if info.is_dir():
            continue
        if info.filename == manifest_name:
            manifest_info = info
            continue
        if not _ENTRY.match(info.filename):
            raise BundleError(_text("bad_entry").format(name=info.filename[:80]))
        entries[info.filename] = info
    if manifest_info is None:
        raise BundleError(_text("no_manifest"))
    if len(entries) > _limit("max_files"):
        raise BundleError(_text("too_many").format(limit=_limit("max_files")))
    if manifest_info.file_size > _limit("max_manifest_bytes"):
        raise BundleError(_text("bad_manifest"))
    total = sum(info.file_size for info in entries.values())
    if total > _limit("max_total_bytes"):
        raise BundleError(_text("too_big").format(limit=_limit("max_total_bytes") // (1024 * 1024)))
    try:
        manifest = json.loads(_read(archive, manifest_info, _limit("max_manifest_bytes")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise BundleError(_text("bad_manifest")) from error
    if not isinstance(manifest, dict) or manifest.get("format") != EXPORT_FORMAT or not isinstance(manifest.get("nodes"), list):
        raise BundleError(_text("bad_manifest"))

    stored: dict[str, str] = {}
    report: dict[str, Any] = {"files": 0, "failed": [], "missing": 0}
    per_entry = _limit("max_entry_bytes")

    def change(text: str) -> str:
        if not text.startswith(REF_PREFIX):
            return text
        name = "media/" + text[len(REF_PREFIX):]
        if name in stored:
            return stored[name]
        info = entries.get(name)
        if info is None:
            report["missing"] += 1
            stored[name] = ""
            return ""
        extension = name.rsplit(".", 1)[1]
        try:
            content = _read(archive, info, per_entry)
            url = str(store(os.path.basename(name), _TYPES[extension], content).get("url") or "")
        except (ValueError, PermissionError, zipfile.BadZipFile, OSError) as error:
            if isinstance(error, PermissionError):
                raise
            report["failed"].append({"name": os.path.basename(name), "reason": str(error)[:200]})
            url = ""
        else:
            report["files"] += 1
        stored[name] = url
        return url

    plain = {
        "format": EXPORT_FORMAT, "version": PLAIN_VERSION, "title": str(manifest.get("title") or ""),
        "exported_at": str(manifest.get("exported_at") or ""),
        "nodes": _walk(manifest.get("nodes") or [], change), "edges": manifest.get("edges") or [], "viewport": manifest.get("viewport"),
    }
    return plain, report


def export_for(service: Any, project_id: str, owner_id: str, canvas_id: str) -> tuple[str, bytes, dict[str, int]]:
    """A board of a project the person owns, packed: its saved version and each node's current result."""
    if not service.repository.get_project(project_id, owner_id):
        raise PermissionError("project not found or not owned by actor")
    canvas = service.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
    if canvas is None:
        raise BundleError(_text("no_canvas"))
    board = next((item for item in service.repository.list_canvases(project_id, owner_id) if item.id == canvas_id), None)
    outputs = service.canvas_outputs(project_id, owner_id, canvas_id=canvas_id).get("outputs") or {}
    return export_bundle(canvas.model_dump(mode="json"), outputs, title=board.title if board else "")


def import_for(service: Any, project_id: str, owner_id: str, data: bytes) -> dict[str, Any]:
    """A bundle opened into a project the person owns: its files stored as that project's canvas uploads."""
    if not service.repository.get_project(project_id, owner_id):
        raise PermissionError("project not found or not owned by actor")
    manifest, report = import_bundle(
        data, lambda name, content_type, content: service.store_canvas_upload(project_id, owner_id, name, content_type, content),
    )
    return {"manifest": manifest, "report": report}


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """An entry's bytes, never more than ``limit`` whatever its header claims (a zip bomb stops here)."""
    with archive.open(info) as handle:
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise BundleError(_text("entry_too_big").format(name=os.path.basename(info.filename), limit=limit // (1024 * 1024)))
    return content


__all__ = ["BUNDLE_VERSION", "BundleError", "REF_PREFIX", "export_bundle", "export_for", "import_bundle", "import_for", "safe_title"]

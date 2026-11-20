"""The brand a deployment shows: its name, a few lines of text, a logo and a page icon.

An administrator sets them; everyone, signed in or not, reads them through a public projection that carries
only the public fields: text that was set (a field left empty is ``null``, so the interface keeps its own,
translatable wording), the logo's frame, and a versioned address for each image slot whose file is actually
there. Internal names, paths and who changed what are not in it.

Images are checked before they are kept: PNG, JPEG or WebP only (no SVG, which can carry script), within the
slot's byte and pixel limits, and opened by Pillow to make sure they are what they say. They are written
beside the other private uploads and served by the public asset route, never from the media mount.

Field names, limits, frames, slots and messages are in ``app/data/prompt/appearance.json``.
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app import settings
from app.core import prompt_data

_DATA = "appearance"
SETTING_KEY = "appearance"
_EXTENSION = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class AppearanceError(ValueError):
    """A field, frame or image that cannot be kept, with the reason in words."""


@dataclass(frozen=True)
class StoredImage:
    slot: str
    path: Path
    mime: str
    sha256: str
    size: int


def _rules() -> dict[str, Any]:
    return prompt_data.load(_DATA)


def _error(key: str, **values: object) -> AppearanceError:
    return AppearanceError(str(_rules()["errors"][key]).format(**values))


def fields() -> dict[str, dict[str, Any]]:
    return dict(_rules()["fields"])


def frames() -> tuple[str, ...]:
    return tuple(_rules()["logo_frames"])


def slots() -> dict[str, dict[str, Any]]:
    return dict(_rules()["slots"])


def storage_dir() -> Path:
    from app.core.media_compositor import MEDIA_DIR

    return settings.private_storage_dir("APPEARANCE_STORAGE_DIR", "appearance", MEDIA_DIR)


def _clean_line(value: object) -> str:
    """One line of display text: control characters and line breaks become spaces, runs of space one."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(value or ""))
    return " ".join(text.split())


def normalise_text(changes: Mapping[str, Any]) -> dict[str, str]:
    """The text fields as they are kept; an empty field means the interface's own wording."""
    known = fields()
    kept: dict[str, str] = {}
    for name, value in changes.items():
        if name not in known:
            raise _error("unknown_field", field=name)
        clean = _clean_line(value)
        limit = int(known[name]["max"])
        if len(clean) > limit:
            raise _error("too_long", label=known[name]["label"], limit=limit, length=len(clean))
        kept[name] = clean
    return kept


def updated(current: Mapping[str, Any], *, text: Mapping[str, Any] | None = None, logo_frame: str | None = None) -> dict[str, Any]:
    """``current`` with the given text fields and frame changed; images are left as they are."""
    result = {key: value for key, value in dict(current).items()}
    if text:
        result.update(normalise_text(text))
    if logo_frame is not None:
        if logo_frame not in frames():
            raise _error("unknown_frame", frame=logo_frame)
        result["logo_frame"] = logo_frame
    return result


def _format_bytes(count: int) -> str:
    return f"{count / 1024 / 1024:.1f} MB" if count >= 1024 * 1024 else f"{max(1, round(count / 1024))} KB"


def check_image(slot: str, data: bytes) -> tuple[str, int, int]:
    """The format and size of an image fit for ``slot``, or :class:`AppearanceError` saying why not."""
    from PIL import Image, UnidentifiedImageError

    known = slots()
    if slot not in known:
        raise _error("unknown_slot", slot=slot)
    rule = known[slot]
    if len(data) > int(rule["max_bytes"]):
        raise _error("too_big", label=rule["label"], limit=_format_bytes(int(rule["max_bytes"])), size=_format_bytes(len(data)))
    try:
        with Image.open(io.BytesIO(data)) as probe:
            kind = str(probe.format or "")
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise _error("not_image", label=rule["label"]) from error
    if kind not in tuple(_rules()["formats"]):
        raise _error("not_image", label=rule["label"])
    side = int(rule["max_side"])
    if width > side or height > side:
        raise _error("too_large_side", label=rule["label"], limit=side, width=width, height=height)
    return kind, width, height


def store_image(current: Mapping[str, Any], slot: str, data: bytes, *, root: Path | None = None) -> dict[str, Any]:
    """Keep an image for ``slot`` and return the setting with it recorded. The old file of the slot is replaced."""
    kind, width, height = check_image(slot, data)
    folder = root or storage_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{slot}.{_EXTENSION[kind]}"
    temporary = folder / f".{name}.{os.getpid()}.tmp"
    temporary.write_bytes(data)
    os.replace(temporary, folder / name)
    for other in folder.glob(f"{slot}.*"):
        if other.name != name:
            other.unlink(missing_ok=True)
    images = dict(current.get("images") or {})
    images[slot] = {
        "file": name, "mime": _MIME[kind], "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data), "width": width, "height": height,
    }
    return {**dict(current), "images": images}


def remove_image(current: Mapping[str, Any], slot: str, *, root: Path | None = None) -> dict[str, Any]:
    if slot not in slots():
        raise _error("unknown_slot", slot=slot)
    images = dict(current.get("images") or {})
    record = images.pop(slot, None)
    if isinstance(record, dict) and record.get("file"):
        ((root or storage_dir()) / Path(str(record["file"])).name).unlink(missing_ok=True)
    return {**dict(current), "images": images}


def image(current: Mapping[str, Any], slot: str, *, root: Path | None = None) -> StoredImage | None:
    """The kept image of ``slot`` when its file is there; ``None`` otherwise."""
    if slot not in slots():
        return None
    record = (current.get("images") or {}).get(slot)
    if not isinstance(record, dict) or not record.get("file"):
        return None
    path = (root or storage_dir()) / Path(str(record["file"])).name
    if not path.is_file():
        return None
    return StoredImage(slot, path, str(record.get("mime") or "application/octet-stream"), str(record.get("sha256") or ""), path.stat().st_size)


def public_view(current: Mapping[str, Any], *, asset_base: str, root: Path | None = None) -> dict[str, Any]:
    """What anyone may read: set text (``None`` when unset), the logo frame, and a versioned address per image."""
    text = {name: (_clean_line(current.get(name)) or None) for name in fields()}
    frame = str(current.get("logo_frame") or "")
    assets: dict[str, str] = {}
    for slot in slots():
        found = image(current, slot, root=root)
        if found is not None:
            assets[slot] = f"{asset_base}/{slot}?v={found.sha256[:12]}"
    return {
        **text,
        "logo_frame": frame if frame in frames() else str(_rules()["default_logo_frame"]),
        "assets": assets,
        "customised": any(text.values()) or bool(assets),
    }


def admin_view(current: Mapping[str, Any], *, asset_base: str, root: Path | None = None) -> dict[str, Any]:
    """The editor's view: the public view plus each field's and slot's limits."""
    rules = _rules()
    return {
        **public_view(current, asset_base=asset_base, root=root),
        "fields": [{"id": name, "label": rule["label"], "max": int(rule["max"])} for name, rule in fields().items()],
        "logo_frames": list(frames()),
        "slots": [
            {"id": slot, "label": rule["label"], "max_bytes": int(rule["max_bytes"]), "max_side": int(rule["max_side"])}
            for slot, rule in slots().items()
        ],
        "formats": list(rules["formats"]),
    }

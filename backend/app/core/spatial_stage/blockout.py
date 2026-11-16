# -*- coding: utf-8 -*-
"""A grey-box set read off a reference image.

A person shows the place — a concept painting, a location photo, an aerial view — and a model
that can see lists it as simple volumes on the floor plan: boxes, cylinders, wedges with a name,
a footprint and a height. The result is a proposal; ``apply_blockout`` (operations.py) puts it on
the stage as ordinary set pieces a person can then move, scale or delete one by one.

Nothing here calls a model; ``analysis_prompt`` is what to send and ``parse_blockout`` reads what
came back; their wording is in ``app/data/prompt/stage_blockout.json``. A reply is taken apart piece by piece so one malformed row costs that row, not the
whole set: models write these lists long and a reply can be cut off at the token limit.

Behavioural reference: the 3D director stage shown in DramaClaw's README (Elastic License 2.0,
implementation not published). Nothing of DramaClaw's is used; see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core import prompt_data
from app.core.spatial_stage.model_kit import catalog_text, find_kit
from app.core.spatial_stage.models import LandmarkKind, LandmarkShape, MAX_LANDMARKS, SpacePoint

_WORDING = "stage_blockout"


def _says(key: str, /, **values: object) -> str:
    """A sentence of ``stage_blockout.json``'s ``says`` with its values filled in."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _text(key: str) -> str:
    """A text of ``stage_blockout.json`` used as it stands (its braces are JSON examples, not placeholders)."""
    return prompt_data.text(_WORDING, key)


REFERENCE_CAMERA_LABEL = _text("reference_camera_label")
# Enough for a whole street; the rest of the stage's capacity stays for what a person adds by hand.
MAX_BLOCKOUT_PIECES = 200
MAX_ARRAY_COUNT = 40
# 和 director_ai 的上限同理：给推理模型留够思考预算，免得正文没写就被截断(按实际输出计费)。
BLOCKOUT_MAX_TOKENS = 32000
_MAX_HINT = 300
MAX_DESCRIPTION = 2000
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_SIZE_RANGE = (0.02, 200.0)

_SYSTEM = _text("system")

_INSTRUCTIONS = _text("instructions") + _says("piece_limit", max_pieces=MAX_BLOCKOUT_PIECES)


class BlockoutError(ValueError):
    """The reply could not be read as a blockout, or a submitted one is not usable."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class BlockoutPiece(_Model):
    name: str = Field(min_length=1, max_length=120)
    kind: LandmarkKind = "architecture"
    shape: LandmarkShape = "box"
    center: tuple[float, float]
    size: tuple[float, float, float]
    yaw_deg: float = Field(0.0, ge=-360, le=360)
    elevation_m: float = Field(0.0, ge=0, le=100)
    color: str = ""
    # A built-in model or a list of volumes, drawn inside the piece's size instead of one plain volume.
    kit: str = ""
    parts: list[Any] = Field(default_factory=list, max_length=64)
    # Without a size of its own a kit piece comes out at the size that kind of thing really is.
    size_given: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def trimmed(cls, value: Any) -> Any:
        return value.strip()[:120] if isinstance(value, str) else value

    @field_validator("center")
    @classmethod
    def on_the_stage(cls, value: tuple[float, float]) -> tuple[float, float]:
        if any(not math.isfinite(item) or abs(item) > 500 for item in value):
            raise ValueError("a piece must stand within ±500 metres")
        return (round(value[0], 3), round(value[1], 3))

    @field_validator("size")
    @classmethod
    def real_volume(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if any(not math.isfinite(item) or item <= 0 for item in value):
            raise ValueError("a piece needs a positive size")
        low, high = _SIZE_RANGE
        return tuple(round(max(low, min(high, item)), 3) for item in value)  # type: ignore[return-value]

    @field_validator("color", mode="before")
    @classmethod
    def colour_or_nothing(cls, value: Any) -> str:
        text = str(value or "").strip()
        return text if _HEX.match(text) else ""


class BlockoutCamera(_Model):
    position: SpacePoint
    target: SpacePoint
    lens_mm: float = Field(35.0, ge=8, le=600)

    @field_validator("position")
    @classmethod
    def above_the_floor(cls, value: list[float]) -> list[float]:
        return [value[0], max(0.05, value[1]), value[2]]


class Blockout(_Model):
    summary: str = Field("", max_length=300)
    extent_m: tuple[float, float] | None = None
    reference_camera: BlockoutCamera | None = None
    pieces: list[BlockoutPiece]
    # Rows of the reply that could not be used; surfaced so a person knows the set is incomplete.
    dropped: int = 0

    @field_validator("summary", mode="before")
    @classmethod
    def short(cls, value: Any) -> str:
        return str(value or "")[:300]


_TEXT_SYSTEM = _text("text_system")

_TEXT_NOTES = _text("text_notes")


def text_prompt(description: str, width_m: float | None = None) -> tuple[str, str]:
    """The same floor-plan contract as a reference image, from words, with the model library on offer."""
    prompt = _INSTRUCTIONS + "\n\n" + _TEXT_NOTES + catalog_text()
    if width_m:
        prompt += _says("width", width_m=width_m)
    return _TEXT_SYSTEM, prompt + _says("description", description=description.strip()[:MAX_DESCRIPTION])


def analysis_prompt(hint: str = "", width_m: float | None = None) -> tuple[str, str]:
    prompt = _INSTRUCTIONS
    if width_m:
        prompt += _says("width", width_m=width_m)
    if hint.strip():
        prompt += _says("hint", hint=hint.strip()[:_MAX_HINT])
    return _SYSTEM, prompt


def _json_of(text: str) -> Mapping[str, Any]:
    """The reply as an object; a reply cut off inside the list keeps every piece it finished."""
    body = re.sub(r"^```(?:json)?|```$", "", str(text or "").strip(), flags=re.MULTILINE).strip()
    start = body.find("{")
    if start < 0:
        raise BlockoutError(_text("unreadable"))
    body = body[start:]
    try:
        parsed = json.JSONDecoder().raw_decode(body)[0]
    except json.JSONDecodeError:
        parsed = _salvage(body)
    if not isinstance(parsed, Mapping):
        raise BlockoutError(_text("unreadable"))
    return parsed


def _salvage(body: str) -> Mapping[str, Any]:
    """Cut a truncated reply back to its last complete piece and close what is still open."""
    opening = body.find('"pieces"')
    bracket = body.find("[", opening) if opening >= 0 else -1
    if bracket < 0:
        raise BlockoutError(_text("truncated"))
    depth, in_string, escaped, last = 0, False, False, -1
    for index in range(bracket + 1, len(body)):
        char = body[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                last = index
    if last < 0:
        raise BlockoutError(_text("truncated"))
    try:
        return json.loads(body[: last + 1] + "]}")
    except json.JSONDecodeError as error:
        raise BlockoutError(_text("unrepairable")) from error


def _expand(rows: Sequence[Any]) -> list[Any]:
    """A row with an ``array`` becomes that many pieces, numbered and stepped along it."""
    expanded: list[Any] = []
    for row in rows:
        spec = row.get("array") if isinstance(row, Mapping) else None
        if not isinstance(spec, Mapping):
            expanded.append(row)
            continue
        try:
            count = max(1, min(MAX_ARRAY_COUNT, int(spec.get("count", 1))))
            dx, dz = float(spec.get("dx", 0)), float(spec.get("dz", 0))
            x, z = float(row["center"][0]), float(row["center"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            expanded.append(row)  # let validation say what is wrong with it
            continue
        for index in range(count):
            expanded.append({
                **{key: value for key, value in row.items() if key != "array"},
                "name": f"{str(row.get('name') or '').strip()[:112]} {index + 1}" if count > 1 else row.get("name"),
                "center": [x + dx * index, z + dz * index],
            })
    return expanded


def _kit_defaults(row: Any) -> Any:
    """A row that only names a library model takes its size and kind from there; an unknown name is a plain volume."""
    if isinstance(row, Mapping) and row.get("parts") and not row.get("size"):
        return {**row, "size_given": False, "size": [1.0, 1.0, 1.0]}
    if not isinstance(row, Mapping) or not row.get("kit"):
        return row
    kit = find_kit(row["kit"])
    if kit is None:
        return {**row, "kit": ""} if row.get("size") else row
    has_size = isinstance(row.get("size"), Sequence) and not isinstance(row.get("size"), (str, bytes))
    return {
        "kind": kit.kind, **row, "kit": kit.id, "size_given": has_size,
        "size": row["size"] if has_size else list(kit.size),
    }


def _read_rows(rows: Sequence[Any]) -> tuple[list[BlockoutPiece], int]:
    pieces: list[BlockoutPiece] = []
    dropped = 0
    names: set[str] = set()
    for row in _expand(rows):
        try:
            piece = BlockoutPiece.model_validate(_kit_defaults(row))
        except ValidationError:
            dropped += 1
            continue
        # Names are how the stage addresses a piece, so a repeat gets a number rather than losing the piece.
        name, suffix = piece.name, 2
        while name in names:
            name, suffix = f"{piece.name[:112]} {suffix}", suffix + 1
        names.add(name)
        pieces.append(piece.model_copy(update={"name": name}))
    overflow = max(0, len(pieces) - MAX_BLOCKOUT_PIECES)
    return pieces[:MAX_BLOCKOUT_PIECES], dropped + overflow


def parse_blockout(text: str) -> Blockout:
    """What the model said, with the unusable rows counted and left out."""
    data = _json_of(text)
    rows = data.get("pieces")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise BlockoutError(_text("no_list"))
    pieces, dropped = _read_rows(rows)
    if not pieces:
        raise BlockoutError(_text("no_pieces"))
    camera = None
    try:
        camera = BlockoutCamera.model_validate(data["reference_camera"]) if data.get("reference_camera") else None
        if camera is not None and sum((camera.position[i] - camera.target[i]) ** 2 for i in range(3)) < 1e-4:
            camera = None
    except ValidationError:
        camera = None
    extent = data.get("extent_m")
    try:
        extent_m = (float(extent[0]), float(extent[1])) if isinstance(extent, Sequence) and len(extent) == 2 else None
    except (TypeError, ValueError):
        extent_m = None
    return Blockout(summary=data.get("summary") or "", extent_m=extent_m, reference_camera=camera, pieces=pieces, dropped=dropped)


def read_pieces(rows: Any) -> list[BlockoutPiece]:
    """The pieces of an ``apply_blockout`` operation; unlike a model's reply, a submitted row must be right."""
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise BlockoutError(_text("pieces_not_list"))
    if len(rows) > MAX_LANDMARKS:
        raise BlockoutError(_says("too_many_pieces", limit=MAX_LANDMARKS))
    pieces, dropped = _read_rows(rows)
    if dropped:
        raise BlockoutError(_says("bad_rows", count=dropped))
    return pieces


__all__ = [
    "BLOCKOUT_MAX_TOKENS", "Blockout", "BlockoutCamera", "BlockoutError", "BlockoutPiece", "MAX_BLOCKOUT_PIECES",
    "REFERENCE_CAMERA_LABEL", "analysis_prompt", "parse_blockout", "read_pieces", "text_prompt",
]

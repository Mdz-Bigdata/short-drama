# -*- coding: utf-8 -*-
"""Two things done to a picture right on the canvas: crop a piece out of it, cut it into a grid.

Both read the picture a node currently shows (its active generation, else the file it holds),
through the readers the element library's canvas link already uses, so the same refusals apply:
somebody else's project, a node with no picture, a private element path. The cutting is done here
with PIL, each piece is written into the canvas's own media storage (the place and URL shape an
upload or a run's result has), and every piece becomes a new ``media`` node beside the source.
One request is one canvas edit: one new version, or nothing (and then the files are removed again).

A ``media`` node takes no input, so the connection rules allow no edge from the source to a piece.
Where a piece came from is kept on the piece instead: ``payload.output.source`` names the source
node, the generation it was cut from when it was one, and the rectangle or grid cell.

Capability after NovaNova Studio's canvas (crop, grid split); the implementation, node model and
wording are this project's own. Wording and limits: ``app/data/prompt/canvas_image_ops.json``.
"""

from __future__ import annotations

import io
import logging
import math
import os
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from PIL import Image, ImageOps

from app.core import canvas_tools, media_compositor, prompt_data, studio_canvas
from app.repository.studio_repo import ConcurrencyError
from app.schema.studio import CANVAS_MAX_NODES
from app.service import canvas_elements

logger = logging.getLogger(__name__)

_DATA = "canvas_image_ops"
#: What the element link says when it cannot read a node's picture; said here in this feature's own words.
_REWORDED = ("node_missing", "node_no_image", "result_unreadable", "result_private")


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _own_words(error: ValueError) -> ValueError:
    for key in _REWORDED:
        if str(error) == prompt_data.text("canvas_elements", key):
            return ValueError(_text(key))
    return error


# ---------------------------------------------------------------------------- the picture


def _picture(service: Any, project_id: str, owner_id: str, canvas_id: str, node_id: str) -> tuple[dict[str, Any], Image.Image]:
    """The picture this node shows now, opened upright; refuses what the element link refuses."""
    library = canvas_elements._library()
    try:
        found = canvas_elements._node_picture(service, project_id, owner_id, canvas_id, node_id)
        content = canvas_elements._picture_bytes(library, found["url"])
    except ValueError as error:
        raise _own_words(error) from error
    library._validated_generated_image(content)
    with Image.open(io.BytesIO(content)) as opened:
        upright = ImageOps.exif_transpose(opened)
        # A cut-out keeps its transparency; everything else is plain RGB, as the other canvas tools write it.
        keeps_alpha = upright.mode in {"RGBA", "LA"} or "transparency" in upright.info
        image = upright.convert("RGBA" if keeps_alpha else "RGB")
    return found, image


def _keep(image: Image.Image, prefix: str) -> str:
    """Write a piece where the canvas keeps its files, under a name the server made up; returns its URL."""
    os.makedirs(media_compositor.MEDIA_DIR, exist_ok=True)
    name = f"{prefix}{uuid.uuid4().hex}.png"
    image.save(os.path.join(media_compositor.MEDIA_DIR, name), "PNG")
    return media_compositor.public_url(name)


def _discard(url: str, prefix: str) -> None:
    path = media_compositor.local_media_path(url)
    if path and os.path.basename(path).startswith(prefix):
        try:
            os.unlink(path)
        except OSError:
            logger.warning("[Canvas] 没用上的裁剪图片没能删掉: %s", os.path.basename(path))


# ---------------------------------------------------------------------------- where the pieces go


def _card(width: int, height: int) -> tuple[float, float]:
    """The media card that shows a picture of these pixels without bars: the rule the frontend sizes an upload by."""
    layout = prompt_data.value(_DATA, "layout")
    long_side, short_min = float(layout["long_side"]), float(layout["short_side_min"])
    aspect = width / height
    wide = long_side if aspect >= 1 else max(short_min, long_side * aspect)
    tall = max(short_min, long_side / aspect) if aspect >= 1 else long_side
    return float(round(wide + float(layout["chrome_width"]))), float(round(tall + float(layout["chrome_height"])))


def _beside(document: Mapping[str, Any], source: Mapping[str, Any], width: float, height: float, gap: float) -> tuple[float, float]:
    """Top-left of a block this big to the right of the source, moved further right until it covers no other node."""
    others = [
        (float(node.get("x") or 0), float(node.get("y") or 0), float(node.get("width") or 0), float(node.get("height") or 0))
        for node in document.get("nodes") or [] if isinstance(node, Mapping) and node.get("kind") != "group"
    ]
    x, y = float(source.get("x") or 0) + float(source.get("width") or 0) + gap, float(source.get("y") or 0)
    for _ in range(len(others) + 1):
        hits = [box for box in others if not (x + width + gap <= box[0] or x >= box[0] + box[2] + gap or y + height <= box[1] or y >= box[1] + box[3])]
        if not hits:
            break
        x = max(box[0] + box[2] for box in hits) + gap
    return x, y


def _state(service: Any, project_id: str, owner_id: str, canvas_id: str, node_id: str, base_version: int | None, adding: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """The stored canvas and the source node on it, once the request is known to fit."""
    canvas = service.repository.get_canvas(project_id, owner_id, canvas_id=canvas_id)
    latest = canvas.version if canvas else 0
    if base_version is not None and int(base_version) != latest:
        # Said before anything is written; edit_canvas checks again under its lock.
        raise ConcurrencyError(f"canvas version conflict: expected {base_version}, latest is {latest}")
    document = canvas.model_dump(mode="json") if canvas else {"nodes": [], "edges": []}
    source = next((node for node in document["nodes"] if str(node.get("id")) == str(node_id)), None)
    if source is None:
        raise ValueError(_text("node_missing"))
    if len(document["nodes"]) + adding > CANVAS_MAX_NODES:
        raise ValueError(_text("too_many_nodes").format(limit=CANVAS_MAX_NODES, count=adding))
    return document, source


def _add(
    service: Any, *, project_id: str, owner_id: str, canvas_id: str, base_version: int | None, prefix: str, pieces: Sequence[tuple[Image.Image, dict[str, Any]]],
) -> dict[str, Any]:
    """Write every piece and add its node in one canvas edit; whatever fails, no file is left behind."""
    written: list[str] = []
    try:
        operations = []
        for index, (image, operation) in enumerate(pieces):
            url = _keep(image, prefix)
            written.append(url)
            operations.append({**operation, "op": "add_node", "kind": "media", "ref": f"piece{index}", "output": {**operation["output"], "medium": "image", "url": url}})
        try:
            done = service.edit_canvas(project_id, owner_id, operations, canvas_id=canvas_id, base_version=base_version)
        except studio_canvas.CanvasOperationError as error:
            raise ValueError(str(error)) from error
    except BaseException:
        for url in written:
            _discard(url, prefix)
        raise
    return {"version": done["version"], "node_ids": [done["created"][f"piece{index}"] for index in range(len(pieces))]}


def _source_note(node_id: str, found: Mapping[str, Any], **cut: Any) -> dict[str, Any]:
    return {"node_id": str(node_id), **({"run_id": found["run_id"]} if found.get("run_id") else {}), **cut}


# ---------------------------------------------------------------------------- crop


def _unit(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(_text("bad_rect")) from error
    if not math.isfinite(number):
        raise ValueError(_text("bad_rect"))
    return number


def crop_box(rect: Mapping[str, Any], width: int, height: int) -> tuple[tuple[int, int, int, int], dict[str, float]]:
    """A rectangle in 0–1 units of the picture, as a pixel box and as the rectangle that box really is."""
    x, y, w, h = (_unit(rect.get(key)) for key in ("x", "y", "w", "h"))
    slack = 1e-6
    if x < -slack or y < -slack or w <= 0 or h <= 0 or x + w > 1 + slack or y + h > 1 + slack:
        raise ValueError(_text("bad_rect"))
    least = float(prompt_data.value(_DATA, "min_edge"))
    if w < least - slack or h < least - slack:
        raise ValueError(_text("rect_too_small").format(percent=round(least * 100)))
    left, top = max(0, min(width - 1, round(x * width))), max(0, min(height - 1, round(y * height)))
    right, bottom = max(left + 1, min(width, round((x + w) * width))), max(top + 1, min(height, round((y + h) * height)))
    return (left, top, right, bottom), {"x": round(left / width, 6), "y": round(top / height, 6), "w": round((right - left) / width, 6), "h": round((bottom - top) / height, 6)}


def crop(service: Any, *, project_id: str, owner_id: str, canvas_id: str, node_id: str, rect: Mapping[str, Any], base_version: int | None = None) -> dict[str, Any]:
    """Cut ``rect`` (0–1 units) out of the node's picture into a new media node beside it."""
    found, image = _picture(service, project_id, owner_id, canvas_id, node_id)
    box, kept = crop_box(rect, image.width, image.height)
    document, source = _state(service, project_id, owner_id, canvas_id, node_id, base_version, 1)
    piece = image.crop(box)
    width, height = _card(piece.width, piece.height)
    x, y = _beside(document, source, width, height, float(prompt_data.value(_DATA, "layout")["gap"]))
    label = _text("crop_label").format(label=studio_canvas._label(source))[:120]
    done = _add(service, project_id=project_id, owner_id=owner_id, canvas_id=canvas_id, base_version=base_version, prefix=_text("crop_prefix"), pieces=[(piece, {
        "label": label, "x": x, "y": y, "width": width, "height": height,
        "output": {"name": label, "source": _source_note(node_id, found, crop=kept)},
    })])
    return {**done, "source_node_id": str(node_id), "connected": False, "width": piece.width, "height": piece.height}


# ---------------------------------------------------------------------------- grid split


def _count(value: Any) -> int:
    limit = prompt_data.number(_DATA, "max_grid")
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= limit:
        raise ValueError(_text("bad_grid").format(max=limit))
    return value


def split(service: Any, *, project_id: str, owner_id: str, canvas_id: str, node_id: str, rows: int, columns: int, base_version: int | None = None) -> dict[str, Any]:
    """Cut the node's picture into ``rows`` × ``columns`` cells: one media node each, laid out as the grid they came from."""
    rows, columns = _count(rows), _count(columns)
    if rows * columns == 1:
        raise ValueError(_text("single_cell"))
    found, image = _picture(service, project_id, owner_id, canvas_id, node_id)
    if image.width < columns or image.height < rows:
        raise ValueError(_text("cell_too_small").format(width=image.width, height=image.height, rows=rows, columns=columns))
    document, source = _state(service, project_id, owner_id, canvas_id, node_id, base_version, rows * columns)
    layout = prompt_data.value(_DATA, "layout")
    gap, cell_gap = float(layout["gap"]), float(layout["cell_gap"])
    # Every card is the size the first cell asks for, so the grid of cards reads as the grid of the picture.
    width, height = _card(image.width // columns, image.height // rows)
    left, top = _beside(document, source, columns * width + (columns - 1) * cell_gap, rows * height + (rows - 1) * cell_gap, gap)
    name = studio_canvas._label(source)
    pieces = []
    for index in range(rows * columns):
        row, column = divmod(index, columns)
        # The grid_cell tool's own boxes: the cells tile the picture exactly, whatever the remainder.
        piece = image.crop(canvas_tools.grid_box(image.width, image.height, rows, columns, index))
        label = _text("cell_label").format(label=name, row=row + 1, column=column + 1)[:120]
        pieces.append((piece, {
            "label": label, "x": left + column * (width + cell_gap), "y": top + row * (height + cell_gap), "width": width, "height": height,
            "output": {"name": label, "source": _source_note(node_id, found, grid={"rows": rows, "columns": columns, "row": row + 1, "column": column + 1})},
        }))
    done = _add(service, project_id=project_id, owner_id=owner_id, canvas_id=canvas_id, base_version=base_version, prefix=_text("cell_prefix"), pieces=pieces)
    return {**done, "source_node_id": str(node_id), "connected": False, "rows": rows, "columns": columns}


__all__ = ["crop", "crop_box", "split"]

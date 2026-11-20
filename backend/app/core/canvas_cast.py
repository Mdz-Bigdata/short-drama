# -*- coding: utf-8 -*-
"""Put one character on the canvas: their look sheet as a media node, labelled the way the storyboard layout labels it.

The label (``canvas_storyboard.json`` ``cast_label``) is what the project sync follows, so when the sheet is drawn
again later the canvas node is offered the new picture. A sheet already on the canvas is not added twice.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import prompt_data
from app.core.canvas_storyboard import _media_urls, _usable  # noqa: PLC2701 - the layout's own helpers

_LAYOUT = "canvas_storyboard"


class CastPictureMissing(ValueError):
    """The character has no look sheet yet, so there is nothing to put on the canvas."""


def sheet_of(task: Mapping[str, Any], name: str) -> str:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    sheets = assets.get("3_sheets") if isinstance(assets.get("3_sheets"), Mapping) else {}
    return _usable(sheets.get(name))


def plan(task: Mapping[str, Any], document: Mapping[str, Any], name: str) -> dict[str, Any]:
    """``{"operations", "existing"}``: the node to add, or the id of the node already showing this sheet."""
    url = sheet_of(task, name)
    if not url:
        raise CastPictureMissing(prompt_data.text(_LAYOUT, "cast_missing").format(name=name))
    existing = _media_urls(document).get(url)
    if existing:
        return {"operations": [], "existing": existing}
    grid = prompt_data.value(_LAYOUT, "layout")
    nodes = [node for node in document.get("nodes") or [] if isinstance(node, Mapping)]
    right = max((float(node.get("x") or 0) + float(node.get("width") or 0) for node in nodes), default=0.0)
    top = min((float(node.get("y") or 0) for node in nodes), default=0.0)
    return {"existing": "", "operations": [{
        "op": "add_node", "ref": "cast", "kind": "media", "label": prompt_data.text(_LAYOUT, "cast_label").format(name=name),
        "output": {"medium": "image", "url": url, "name": name},
        "x": right + (grid["cast_margin"] if nodes else 0), "y": top, "width": grid["cast_width"], "height": grid["cast_height"],
    }]}


__all__ = ["CastPictureMissing", "plan", "sheet_of"]

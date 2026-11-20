"""Tidying a node canvas: align, distribute and arrange nodes. Pure geometry on node dicts, no I/O.

The frontend's layout commands follow the same rules, so the assistant tidying a board and a
person pressing the buttons get the same picture:

* a selected group moves its members (and its nested groups' members) with it; a node whose group
  is selected too is not moved on its own;
* ``align`` lines the selection up on the selection's bounding box;
* ``distribute`` keeps the outermost two in place and evens out the gaps between the rest;
* ``arrange`` lays the selection out from its top-left corner: ``row`` / ``column`` / ``grid``
  with a 40 gap, ``edges`` in columns left to right by dependency depth (column gap 120, row gap 40).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from typing import Any
from app.core import prompt_data


_WORDING_FILE = "canvas_layout"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/canvas_layout.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

ALIGN_MODES = ("left", "hcenter", "right", "top", "vcenter", "bottom")
DISTRIBUTE_AXES = ("horizontal", "vertical")
ARRANGE_LAYOUTS = ("row", "column", "grid", "edges")
ARRANGE_GAP = 40.0
EDGES_COLUMN_GAP = 120.0
EDGES_ROW_GAP = 40.0
MAX_GAP = 10_000.0
# How far a group's frame reaches past what it holds: sides and bottom, and the title bar on top.
GROUP_PAD = 40.0
GROUP_PAD_TOP = 60.0

Node = MutableMapping[str, Any]


def _box(node: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return float(node.get("x") or 0), float(node.get("y") or 0), float(node.get("width") or 0), float(node.get("height") or 0)


def bounds(nodes: Iterable[Mapping[str, Any]]) -> dict[str, float] | None:
    """The box around these nodes, or ``None`` when there are none."""
    boxes = [_box(node) for node in nodes]
    if not boxes:
        return None
    left = min(x for x, _, _, _ in boxes)
    top = min(y for _, y, _, _ in boxes)
    right = max(x + w for x, _, w, _ in boxes)
    bottom = max(y + h for _, y, _, h in boxes)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def group_of(node: Mapping[str, Any]) -> str:
    payload = node.get("payload") if isinstance(node.get("payload"), Mapping) else {}
    return str(payload.get("groupId") or "")


def descendants(nodes: Sequence[Mapping[str, Any]], group_id: str) -> list[str]:
    """Everything inside this group, nested groups' members included."""
    children: dict[str, list[str]] = {}
    for node in nodes:
        parent = group_of(node)
        if parent:
            children.setdefault(parent, []).append(str(node.get("id")))
    found: list[str] = []
    stack, seen = [group_id], {group_id}
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in seen:
                seen.add(child)
                found.append(child)
                stack.append(child)
    return found


def _units(nodes: Sequence[Node], node_ids: Sequence[str]) -> list[Node]:
    """The selected nodes that move as one piece each: a node inside a selected group rides with it."""
    by_id = {str(node.get("id")): node for node in nodes}
    wanted = list(dict.fromkeys(str(item) for item in node_ids))
    missing = [item for item in wanted if item not in by_id]
    if missing:
        raise ValueError(_text_of("_units.text").format('、'.join(missing[:5])))
    selected = set(wanted)
    units = []
    for node_id in wanted:
        ancestor, seen = group_of(by_id[node_id]), {node_id}
        inside_selected = False
        while ancestor and ancestor not in seen:
            if ancestor in selected:
                inside_selected = True
                break
            seen.add(ancestor)
            ancestor = group_of(by_id[ancestor]) if ancestor in by_id else ""
        if not inside_selected:
            units.append(by_id[node_id])
    return units


def _move(nodes: Sequence[Node], unit: Node, x: float, y: float, changed: set[str]) -> None:
    dx, dy = x - float(unit.get("x") or 0), y - float(unit.get("y") or 0)
    if dx == 0 and dy == 0:
        return
    moving = [str(unit.get("id"))]
    if unit.get("kind") == "group":
        moving += descendants(nodes, str(unit.get("id")))
    wanted = set(moving)
    for node in nodes:
        if str(node.get("id")) in wanted:
            node["x"] = float(node.get("x") or 0) + dx
            node["y"] = float(node.get("y") or 0) + dy
            changed.add(str(node.get("id")))


def align(nodes: Sequence[Node], node_ids: Sequence[str], mode: str) -> set[str]:
    """Line the selection up on one side or centre line of its bounding box. Returns the ids that moved."""
    if mode not in ALIGN_MODES:
        raise ValueError(_text_of("align.text").format('、'.join(ALIGN_MODES)))
    units = _units(nodes, node_ids)
    if len(units) < 2:
        raise ValueError(_text_of("align.text.2"))
    box = bounds(units) or {"x": 0, "y": 0, "width": 0, "height": 0}
    changed: set[str] = set()
    for unit in units:
        x, y, w, h = _box(unit)
        if mode == "left":
            x = box["x"]
        elif mode == "hcenter":
            x = box["x"] + box["width"] / 2 - w / 2
        elif mode == "right":
            x = box["x"] + box["width"] - w
        elif mode == "top":
            y = box["y"]
        elif mode == "vcenter":
            y = box["y"] + box["height"] / 2 - h / 2
        else:
            y = box["y"] + box["height"] - h
        _move(nodes, unit, x, y, changed)
    return changed


def distribute(nodes: Sequence[Node], node_ids: Sequence[str], axis: str) -> set[str]:
    """Even gaps along an axis; the first and the last stay where they are."""
    if axis not in DISTRIBUTE_AXES:
        raise ValueError(_text_of("distribute.text").format('、'.join(DISTRIBUTE_AXES)))
    units = _units(nodes, node_ids)
    if len(units) < 3:
        raise ValueError(_text_of("distribute.text.2"))
    horizontal = axis == "horizontal"
    start, size = (0, 2) if horizontal else (1, 3)
    ordered = sorted(units, key=lambda unit: (_box(unit)[start], _box(unit)[1 - start], str(unit.get("id"))))
    first, last = _box(ordered[0]), _box(ordered[-1])
    span = last[start] + last[size] - first[start]
    gap = (span - sum(_box(unit)[size] for unit in ordered)) / (len(ordered) - 1)
    changed: set[str] = set()
    cursor = first[start] + first[size] + gap
    for unit in ordered[1:-1]:
        x, y, w, h = _box(unit)
        if horizontal:
            _move(nodes, unit, cursor, y, changed)
            cursor += w + gap
        else:
            _move(nodes, unit, x, cursor, changed)
            cursor += h + gap
    return changed


def _depths(units: Sequence[Node], nodes: Sequence[Node], edges: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Each unit's column: the longest chain of connections leading into it from inside the selection."""
    owner: dict[str, str] = {}
    for unit in units:
        unit_id = str(unit.get("id"))
        owner[unit_id] = unit_id
        if unit.get("kind") == "group":
            for member in descendants(nodes, unit_id):
                owner.setdefault(member, unit_id)
    upstream: dict[str, set[str]] = {str(unit.get("id")): set() for unit in units}
    for edge in edges:
        source, target = owner.get(str(edge.get("source"))), owner.get(str(edge.get("target")))
        if source and target and source != target:
            upstream[target].add(source)
    depth: dict[str, int] = {}
    remaining = set(upstream)
    while remaining:
        ready = [item for item in remaining if upstream[item] <= depth.keys()]
        if not ready:
            # A loop drawn by hand: break it at the node that sits furthest left.
            ready = [min(remaining, key=lambda item: (sum(1 for dep in upstream[item] if dep not in depth), item))]
        for item in ready:
            depth[item] = 1 + max((depth[dep] for dep in upstream[item] if dep in depth), default=-1)
            remaining.discard(item)
    return depth


def arrange(
    nodes: Sequence[Node], node_ids: Sequence[str], layout: str, *, gap: float | None = None, edges: Sequence[Mapping[str, Any]] = (),
) -> set[str]:
    """Lay the selection out from its top-left corner."""
    if layout not in ARRANGE_LAYOUTS:
        raise ValueError(_text_of("arrange.text").format('、'.join(ARRANGE_LAYOUTS)))
    if gap is not None:
        gap = float(gap)
        if not math.isfinite(gap) or not 0 <= gap <= MAX_GAP:
            raise ValueError(_text_of("arrange.text.2").format(MAX_GAP))
    units = _units(nodes, node_ids)
    if len(units) < 2:
        raise ValueError(_text_of("arrange.text.3"))
    box = bounds(units) or {"x": 0, "y": 0}
    left, top = box["x"], box["y"]
    changed: set[str] = set()
    reading = sorted(units, key=lambda unit: (_box(unit)[1], _box(unit)[0], str(unit.get("id"))))
    if layout == "row":
        step = ARRANGE_GAP if gap is None else gap
        cursor = left
        for unit in sorted(units, key=lambda unit: (_box(unit)[0], _box(unit)[1], str(unit.get("id")))):
            _move(nodes, unit, cursor, top, changed)
            cursor += _box(unit)[2] + step
    elif layout == "column":
        step = ARRANGE_GAP if gap is None else gap
        cursor = top
        for unit in reading:
            _move(nodes, unit, left, cursor, changed)
            cursor += _box(unit)[3] + step
    elif layout == "grid":
        step = ARRANGE_GAP if gap is None else gap
        columns = math.ceil(math.sqrt(len(reading)))
        cell = max(_box(unit)[2] for unit in reading)
        y = top
        for start in range(0, len(reading), columns):
            row = reading[start:start + columns]
            for index, unit in enumerate(row):
                _move(nodes, unit, left + index * (cell + step), y, changed)
            y += max(_box(unit)[3] for unit in row) + step
    else:
        column_gap = EDGES_COLUMN_GAP if gap is None else gap
        depth = _depths(units, nodes, edges)
        columns_of: dict[int, list[Node]] = {}
        for unit in reading:
            columns_of.setdefault(depth[str(unit.get("id"))], []).append(unit)
        x = left
        for level in sorted(columns_of):
            column = columns_of[level]
            y = top
            for unit in column:
                _move(nodes, unit, x, y, changed)
                y += _box(unit)[3] + EDGES_ROW_GAP
            x += max(_box(unit)[2] for unit in column) + column_gap
    return changed


def fit_groups(nodes: Sequence[Node], group_ids: Iterable[str]) -> set[str]:
    """Grow these groups (and the groups they sit in) until their frames hold every member. Never shrinks one."""
    by_id = {str(node.get("id")): node for node in nodes}
    changed: set[str] = set()
    pending = [item for item in dict.fromkeys(group_ids) if item in by_id and by_id[item].get("kind") == "group"]
    seen: set[str] = set()
    while pending:
        group_id = pending.pop(0)
        if group_id in seen:
            continue
        seen.add(group_id)
        group = by_id[group_id]
        members = [node for node in nodes if group_of(node) == group_id and str(node.get("id")) != group_id]
        # A folded group shows only its title bar; its frame is not stretched over what it hides.
        folded = bool((group.get("payload") or {}).get("collapsed"))
        box = None if folded else bounds(members)
        if box is not None:
            x, y, w, h = _box(group)
            left = min(x, box["x"] - GROUP_PAD)
            top = min(y, box["y"] - GROUP_PAD_TOP)
            right = max(x + w, box["x"] + box["width"] + GROUP_PAD)
            bottom = max(y + h, box["y"] + box["height"] + GROUP_PAD)
            if (left, top, right - left, bottom - top) != (x, y, w, h):
                group.update({"x": left, "y": top, "width": right - left, "height": bottom - top})
                changed.add(group_id)
        parent = group_of(group)
        if parent in by_id and parent not in seen:
            pending.append(parent)
    return changed

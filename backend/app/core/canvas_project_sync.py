# -*- coding: utf-8 -*-
"""Keeping a canvas in step with its project's storyboard, without ever losing what was done on the canvas.

``canvas_storyboard`` lays shots out once. A sync goes further and can be repeated:

* shots the canvas does not have yet are laid out (a new shot of a scene already on the canvas goes
  beside its siblings, in that scene's group, when there is room there);
* what the project changed since the last sync is brought over to the nodes that came from it: a
  video node's text and length, a first frame's prompt or storyboard picture, a look sheet;
* nothing the canvas changed is overwritten. Each synced node remembers, per field, a digest of what
  the project said last time (``payload.projectSync``). A field the canvas left alone takes the
  project's new value; a field the canvas changed stays, unless both sides changed, which is put to
  the person; a node from before syncing existed has no memory, so any difference is put to them;
* nothing is moved or deleted. A node whose shot left the project, and a frame still to be drawn
  whose shot now has a storyboard picture, are only reported.

Which nodes came from the project: a video node bound to a shot, a media or image node labelled as
that shot's first frame or storyboard picture, a media node labelled as a character's look sheet
(the labels ``canvas_storyboard`` gives them), or any node carrying the sync's own mark. A node
somebody bound or made by hand keeps its own text.

The idea of a canvas that follows its project is AID Studio's (MIT, see THIRD_PARTY_NOTICES.md);
its canvas is a read-only projection, this one stays editable. Wording: ``canvas_project_sync.json``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core import canvas_layout, canvas_storyboard, prompt_data, studio_canvas
from app.core.canvas_storyboard import StoryboardLayoutError

_DATA = "canvas_project_sync"
_LAYOUT = "canvas_storyboard"
#: The payload key a synced node keeps its memory under.
MARK = "projectSync"

# What a sync reads from the project for each kind of node it follows (canvas_storyboard decides the text).
_clip_prompt = canvas_storyboard._clip_prompt  # noqa: SLF001 - the same text the layout writes
_frame_prompt = canvas_storyboard._prompt  # noqa: SLF001
_seconds = canvas_storyboard._seconds  # noqa: SLF001
_usable = canvas_storyboard._usable  # noqa: SLF001
_project_shots = canvas_storyboard._shots  # noqa: SLF001
_names = canvas_storyboard._names  # noqa: SLF001


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _digest(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _payload(node: Mapping[str, Any]) -> dict[str, Any]:
    payload = node.get("payload")
    return payload if isinstance(payload, dict) else {}


def _mark(node: Mapping[str, Any]) -> dict[str, Any] | None:
    mark = _payload(node).get(MARK)
    return mark if isinstance(mark, Mapping) and str(mark.get("key") or "") else None


def _label(key: str, **names: Any) -> str:
    return prompt_data.text(_LAYOUT, key).format(**names)


def _binding(node: Mapping[str, Any]) -> tuple[str, int] | None:
    binding = _payload(node).get("binding")
    if not isinstance(binding, Mapping) or not str(binding.get("sceneId") or "").strip():
        return None
    try:
        shot = int(binding.get("shotId") or 0)
    except (TypeError, ValueError):
        return None
    return (str(binding["sceneId"]).strip(), shot) if shot > 0 else None


def _shot_key(scene: str, shot: int, role: str) -> str:
    return f"shot:{scene}:{shot}:{role}"


def _cast_key(name: str) -> str:
    return f"cast:{name}"


# ---------------------------------------------------------------------------------------------- what the canvas holds


@dataclass
class _Followed:
    """A node that came from the project, what it stands for, and the project's current value of each field it follows."""

    node: dict[str, Any]
    key: str
    scene: str = ""
    shot: int = 0
    fields: dict[str, Any] = field(default_factory=dict)


def _canvas_value(node: Mapping[str, Any], name: str) -> Any:
    payload = _payload(node)
    if name == "prompt":
        return str(payload.get("prompt") or "")
    if name == "duration":
        params = payload.get("params") if isinstance(payload.get("params"), Mapping) else {}
        try:
            return int(params.get("durationSeconds")) if params.get("durationSeconds") not in (None, "") else None
        except (TypeError, ValueError):
            return None
    output = payload.get("output") if isinstance(payload.get("output"), Mapping) else {}
    return str(output.get("url") or "")


def _set_canvas_value(node: dict[str, Any], name: str, value: Any) -> None:
    payload = dict(_payload(node))
    if name == "prompt":
        payload["prompt"] = value
    elif name == "duration":
        payload["params"] = {**(payload.get("params") if isinstance(payload.get("params"), Mapping) else {}), "durationSeconds": int(value)}
    else:
        output = dict(payload.get("output")) if isinstance(payload.get("output"), Mapping) else {"medium": "image"}
        output["url"] = value
        payload["output"] = output
    node["payload"] = payload


def _followed(task: Mapping[str, Any], document: Mapping[str, Any]) -> tuple[list[_Followed], list[dict[str, Any]]]:
    """Every node that came from the project with the fields it follows, and the notes (shots gone, pictures ready)."""
    shots = {(shot["scene_id"], shot["shot_id"]): shot for shot in _project_shots(task)}
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    sheets = assets.get("3_sheets") if isinstance(assets.get("3_sheets"), Mapping) else {}
    frame_labels: dict[tuple[str, str], tuple[str, int]] = {}
    for scene, number in shots:
        names = {"scene": scene, "shot": number}
        frame_labels[("media", _label("board_label", **names))] = (scene, number)
        frame_labels[("image_gen", _label("frame_label", **names))] = (scene, number)
    cast_labels = {_label("cast_label", name=str(name)): str(name) for name in sheets}

    followed: list[_Followed] = []
    notes: list[dict[str, Any]] = []
    for node in document.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        kind, mark = str(node.get("kind") or ""), _mark(node)
        label = str(_payload(node).get("label") or "")
        if kind == "video_gen" and (bound := _binding(node)):
            scene, number = bound
            key = _shot_key(scene, number, "clip")
            if bound not in shots:
                # The shot left the project: say so, change nothing (its runs and history stay where they are).
                notes.append({"kind": "gone", "node_id": node["id"], "label": label, "scene": scene, "shot": number})
                continue
            if (mark and mark["key"] == key) or (not mark and label == _label("clip_label", scene=scene, shot=number)):
                shot = shots[bound]
                followed.append(_Followed(node, key, scene, number, {"prompt": _clip_prompt(shot), "duration": _seconds(shot.get("duration"))}))
            continue
        if kind in ("media", "image_gen"):
            place: tuple[str, int] | None = None
            if mark and mark["key"].startswith("shot:") and mark["key"].endswith(":frame"):
                scene, _, number = mark["key"][len("shot:"):-len(":frame")].rpartition(":")
                try:
                    place = (scene, int(number))
                except ValueError:
                    place = None
            elif not mark:
                place = frame_labels.get((kind, label))
            if place and place in shots:
                shot = shots[place]
                picture = _usable(shot.get("image_url"))
                if kind == "media":
                    followed.append(_Followed(node, _shot_key(*place, "frame"), *place, {"picture": picture}))
                else:
                    followed.append(_Followed(node, _shot_key(*place, "frame"), *place, {"prompt": _frame_prompt(shot)}))
                    if picture:
                        notes.append({"kind": "board_ready", "node_id": node["id"], "label": label, "scene": place[0], "shot": place[1], "url": picture})
                continue
        if kind == "media":
            name = ""
            if mark and mark["key"].startswith("cast:"):
                name = mark["key"][len("cast:"):]
            elif not mark:
                name = cast_labels.get(label, "")
            if name and name in sheets:
                followed.append(_Followed(node, _cast_key(name), fields={"picture": _usable(sheets.get(name))}))
    return followed, notes


# ---------------------------------------------------------------------------------------------- what differs


def _state(node: Mapping[str, Any], name: str, project: Any) -> str:
    """``same``, ``update`` (the project moved, the canvas did not), ``kept`` (the canvas moved, the project did not) or ``conflict``."""
    here, there = _digest(_canvas_value(node, name)), _digest(project)
    if here == there:
        return "same"
    mark = _mark(node) or {}
    seen = mark.get("seen") if isinstance(mark.get("seen"), Mapping) else {}
    before = seen.get(name)
    if before is None:
        return "conflict"
    if here == before:
        return "update"
    if there == before:
        return "kept"
    return "conflict"


def _shown(value: Any) -> Any:
    limit = prompt_data.number(_DATA, "shown_chars")
    return value[:limit] if isinstance(value, str) else value


def _differences(followed: Sequence[_Followed]) -> list[dict[str, Any]]:
    items = []
    for entry in followed:
        for name, project in entry.fields.items():
            if project in (None, ""):
                # The project says nothing here (no length, no picture yet): the canvas keeps what it has.
                continue
            state = _state(entry.node, name, project)
            if state not in ("update", "conflict"):
                continue
            items.append({
                "id": f"{entry.node['id']}:{name}", "node_id": entry.node["id"], "key": entry.key, "field": name, "state": state,
                "label": str(_payload(entry.node).get("label") or ""), "scene": entry.scene, "shot": entry.shot,
                "canvas": _shown(_canvas_value(entry.node, name)), "project": _shown(project),
                # Taking the project's side is the default only where the canvas was left alone.
                "checked": state == "update",
            })
    return items


def _new_shots(task: Mapping[str, Any], document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Per storyboard scene, in order: how many shots the canvas does not have, and whether the scene is on it already."""
    held = canvas_storyboard._bound(document)  # noqa: SLF001 - the layout's own rule for "already on the canvas"
    scenes: dict[str, dict[str, Any]] = {}
    for shot in _project_shots(task):
        row = scenes.setdefault(shot["scene_id"], {"scene_id": shot["scene_id"], "shots": 0, "new": 0, "on_canvas": False})
        row["shots"] += 1
        if (shot["scene_id"], shot["shot_id"]) in held:
            row["on_canvas"] = True
        else:
            row["new"] += 1
    return list(scenes.values())


def _this_time(scenes: Sequence[Mapping[str, Any]]) -> list[str]:
    """The scenes with new shots that fit in one sync, in storyboard order; the rest wait for the next."""
    limit, total, picked = prompt_data.number(_LAYOUT, "max_shots"), 0, []
    for scene in scenes:
        if not scene["new"]:
            continue
        if total + scene["new"] > limit:
            break
        picked.append(scene["scene_id"])
        total += scene["new"]
    return picked


def review(task: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
    """What a sync would do, changing nothing.

    ``{"storyboard", "new": {"shots", "this_time", "later", "scenes"}, "items", "notes", "followed", "token"}``.
    ``token`` stands for this exact review: a sync is applied only while it still holds.
    """
    if not _project_shots(task):
        return {"storyboard": False, "new": {"shots": 0, "this_time": 0, "later": 0, "scenes": []}, "items": [], "notes": [], "followed": 0,
                "token": _digest("empty")}
    scenes = _new_shots(task, document)
    picked = set(_this_time(scenes))
    followed, notes = _followed(task, document)
    items = _differences(followed)
    fresh = sum(scene["new"] for scene in scenes)
    this_time = sum(scene["new"] for scene in scenes if scene["scene_id"] in picked)
    token = _digest([
        [(scene["scene_id"], scene["new"]) for scene in scenes],
        [(item["id"], item["state"], _digest(item["canvas"]), _digest(item["project"])) for item in items],
        [(note["kind"], note["node_id"]) for note in notes],
    ])
    return {
        "storyboard": True,
        "new": {"shots": fresh, "this_time": this_time, "later": fresh - this_time,
                "scenes": [{**scene, "this_time": scene["scene_id"] in picked} for scene in scenes if scene["new"]]},
        "items": items, "notes": notes, "followed": len(followed), "token": token,
    }


# ---------------------------------------------------------------------------------------------- applying it


class SyncOutdated(ValueError):
    """The project or the canvas changed after the review the person answered."""


def _rect(op: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return float(op["x"]), float(op["y"]), float(op["width"]), float(op["height"])


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _beside_siblings(document: Mapping[str, Any], scene: str, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A scene already on the canvas: its new shots continue its row and join its group, when that space is free."""
    nodes = [node for node in document.get("nodes") or [] if isinstance(node, Mapping)]
    clips = [node for node in nodes if node.get("kind") == "video_gen" and (_binding(node) or ("", 0))[0] == scene]
    if not clips:
        return operations
    clip_ids = {str(node["id"]) for node in clips}
    frame_ids = {
        str(edge.get("source")) for edge in document.get("edges") or []
        if str(edge.get("target")) in clip_ids and ((edge.get("payload") or {}).get("role") == "first_frame")
    }
    frames = [node for node in nodes if str(node.get("id")) in frame_ids]
    members = clips + frames
    grid = prompt_data.value(_LAYOUT, "layout")
    right = max(float(node.get("x") or 0) + float(node.get("width") or 0) for node in members)
    clip_top = min(float(node.get("y") or 0) for node in clips)
    frame_top = min((float(node.get("y") or 0) for node in frames), default=clip_top - grid["frame_height"] - grid["pair_gap"])
    groups = {canvas_layout.group_of(node) for node in members}
    group = next(iter(groups)) if len(groups) == 1 and next(iter(groups)) else ""

    moved = [dict(op) for op in operations]
    column = -1
    for op in moved:
        if op.get("op") != "add_node":
            continue
        ref = str(op.get("ref") or "")
        if ref.startswith("frame_"):
            column += 1
            op["y"] = frame_top
        elif ref.startswith("clip_"):
            op["y"] = clip_top
        else:
            continue
        op["x"] = right + prompt_data.number(_DATA, "sibling_gap") + max(column, 0) * grid["column"]
    # Only into free space: anything else in the way (outside this scene's own group) keeps the layout's own placement.
    inside = set(canvas_layout.descendants(nodes, group)) if group else set()
    others = [
        (float(node.get("x") or 0), float(node.get("y") or 0), float(node.get("width") or 0), float(node.get("height") or 0))
        for node in nodes if node.get("kind") != "group" and str(node.get("id")) not in inside and str(node.get("id")) not in clip_ids | frame_ids
    ]
    placed = [_rect(op) for op in moved if op.get("op") == "add_node" and str(op.get("ref") or "").startswith(("frame_", "clip_"))]
    if any(_overlaps(rect, other) for rect in placed for other in others):
        return operations
    if group:
        for op in moved:
            if op.get("op") == "group":
                ids = list(op.get("ids") or [])
                op.clear()
                op.update({"op": "set_group", "node_ids": ids, "group_id": group})
    return moved


def _marks_for(operations: Sequence[Mapping[str, Any]], refs: Mapping[str, str]) -> dict[str, str]:
    """``node id -> sync key`` for what the layout just added: each clip, its first frame, each look sheet."""
    clips = {str(op["ref"]): op for op in operations if op.get("op") == "add_node" and op.get("kind") == "video_gen" and op.get("binding")}
    marks: dict[str, str] = {}
    for ref, op in clips.items():
        scene, number = str(op["binding"]["sceneId"]), int(op["binding"]["shotId"])
        if ref in refs:
            marks[refs[ref]] = _shot_key(scene, number, "clip")
        for edge in operations:
            if edge.get("op") == "connect" and edge.get("role") == "first_frame" and str(edge.get("target")) == ref and str(edge.get("source")) in refs:
                marks[refs[str(edge["source"])]] = _shot_key(scene, number, "frame")
    for op in operations:
        output = op.get("output") if isinstance(op.get("output"), Mapping) else {}
        if op.get("op") == "add_node" and op.get("kind") == "media" and output.get("name") and str(op.get("ref")) in refs:
            marks[refs[str(op["ref"])]] = _cast_key(str(output["name"]))
    return marks


def _lay_out(task: Mapping[str, Any], document: dict[str, Any], scenes: Sequence[str]) -> tuple[dict[str, Any], list[str], dict[str, str], int]:
    """Lay these scenes' new shots out: scenes not on the canvas yet in one go, the others one by one beside their siblings."""
    held = {scene for scene, _ in canvas_storyboard._bound(document)}  # noqa: SLF001
    fresh_scenes = [scene for scene in scenes if scene not in held]
    created: list[str] = []
    marks: dict[str, str] = {}
    shots = 0
    batches = ([fresh_scenes] if fresh_scenes else []) + [[scene] for scene in scenes if scene in held]
    for batch in batches:
        try:
            planned = canvas_storyboard.plan(task, document, batch)
        except StoryboardLayoutError:
            continue
        operations = planned["operations"]
        if batch[0] in held:
            operations = _beside_siblings(document, batch[0], operations)
        document, refs = studio_canvas.apply_operations(document, operations)
        created += [node_id for ref, node_id in refs.items() if not ref.startswith("scene_")]
        marks.update(_marks_for(operations, refs))
        shots += int(planned["shots"])
    return document, created, marks, shots


def apply(task: Mapping[str, Any], document: Mapping[str, Any], *, token: str, accept: Collection[str], add_new: bool) -> dict[str, Any]:
    """Carry out the review the person answered: ``{"document", "changed", "shots", "updated", "kept", "node_ids"}``.

    Raises ``SyncOutdated`` when the review no longer holds; ``studio_canvas.CanvasOperationError`` when the
    layout cannot be placed (a canvas at its node limit).
    """
    current = review(task, document)
    if current["token"] != token:
        raise SyncOutdated(_text("outdated"))
    working = copy.deepcopy(dict(document))
    working.setdefault("nodes", [])
    working.setdefault("edges", [])
    created: list[str] = []
    marks: dict[str, str] = {}
    shots = 0
    if add_new and current["new"]["this_time"]:
        picked = [scene["scene_id"] for scene in current["new"]["scenes"] if scene["this_time"]]
        working, created, marks, shots = _lay_out(task, working, picked)

    by_id = {str(node.get("id")): node for node in working["nodes"]}
    for node_id, key in marks.items():
        if node_id in by_id:
            payload = dict(_payload(by_id[node_id]))
            payload[MARK] = {"key": key, "seen": {}}
            by_id[node_id]["payload"] = payload

    followed, _ = _followed(task, working)
    chosen = set(accept)
    updated: list[str] = []
    kept = 0
    for entry in followed:
        node = entry.node
        seen: dict[str, str] = {}
        for name, project in entry.fields.items():
            if project in (None, ""):
                continue
            state = _state(node, name, project)
            if state in ("update", "conflict"):
                if f"{node['id']}:{name}" in chosen:
                    _set_canvas_value(node, name, project)
                    updated.append(str(node["id"]))
                else:
                    kept += 1
            # Declined or kept, the canvas's own value now stands: next time only a new project change is news.
            seen[name] = _digest(project)
        payload = dict(_payload(node))
        old = payload.get(MARK) if isinstance(payload.get(MARK), Mapping) else {}
        mark = {"key": entry.key, "seen": {**(old.get("seen") if isinstance(old.get("seen"), Mapping) else {}), **seen}}
        if payload.get(MARK) != mark:
            payload[MARK] = mark
            node["payload"] = payload

    changed = working != document
    return {
        "document": working, "changed": changed, "shots": shots, "updated": len(set(updated)), "kept": kept,
        "node_ids": list(dict.fromkeys(created + updated)),
    }


__all__ = ["MARK", "SyncOutdated", "apply", "review"]

# -*- coding: utf-8 -*-
"""The project's storyboard laid out on the canvas: every shot becomes nodes that can be run on their own.

Stage 5 only runs whole batches. On the canvas a single shot can be drawn, compared and paid for by
itself, and what it makes is committed back to the shot it is bound to. So each chosen shot becomes
a pair: its first frame (the storyboard picture it already has, as a media node; or an image node
with the shot's prompt when it has none) feeding a video node bound to that shot. The characters in
those shots stand beside them as media nodes holding their look sheets, connected as reference
images to every first frame that still has to be drawn. A scene is one group. When two or more
shots are laid out, a "film" compose node below them takes every video node in shot order, so
running the whole canvas ends in the scenes joined into one clip.

Laid out left to right by shot, one row per scene, to the right of whatever the canvas already
holds. A shot already on the canvas (a video node bound to it) is not laid out twice.

Capability after NovaNova Studio's "storyboard to canvas nodes" (MIT, see THIRD_PARTY_NOTICES.md);
the implementation, node model and wording are this project's own. Labels and layout numbers:
``app/data/prompt/canvas_storyboard.json``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core import prompt_data

_DATA = "canvas_storyboard"


class StoryboardLayoutError(ValueError):
    """Nothing can be laid out as asked; the message is for the person."""


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _usable(url: Any) -> str:
    value = str(url or "").strip()
    return value if value.startswith(("http://", "https://", "/media/")) else ""


def _seconds(value: Any) -> int | None:
    from app.core.writer_dashboard import parse_duration_seconds

    try:
        seconds = int(round(float(parse_duration_seconds(str(value or "")) or 0)))
    except (TypeError, ValueError):
        seconds = 0
    return seconds if seconds > 0 else None


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        import re

        value = re.split(r"[、,，/\s]+", value)
    return [str(name).strip() for name in value or [] if str(name or "").strip() and str(name).strip() not in ("无", "空镜")]


def _shots(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    found = []
    for number, shot in enumerate(assets.get("4") or [], start=1):
        if isinstance(shot, Mapping) and str(shot.get("scene_id") or "").strip():
            found.append({**shot, "shot_id": int(shot.get("shot_id") or number), "scene_id": str(shot["scene_id"]).strip()})
    return found


def scenes_of(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The storyboard's scenes in order, with how many shots each has: what the picker lists."""
    order: dict[str, int] = {}
    for shot in _shots(task):
        order[shot["scene_id"]] = order.get(shot["scene_id"], 0) + 1
    return [{"scene_id": scene, "shots": count} for scene, count in order.items()]


def _bound(document: Mapping[str, Any]) -> set[tuple[str, int]]:
    """The shots a video node of this canvas is already bound to."""
    held: set[tuple[str, int]] = set()
    for node in document.get("nodes") or []:
        payload = node.get("payload") if isinstance(node.get("payload"), Mapping) else {}
        binding = payload.get("binding") if isinstance(payload.get("binding"), Mapping) else {}
        if node.get("kind") == "video_gen" and binding.get("sceneId"):
            try:
                held.add((str(binding["sceneId"]), int(binding.get("shotId") or 0)))
            except (TypeError, ValueError):
                continue
    return held


def _media_urls(document: Mapping[str, Any]) -> dict[str, str]:
    """``url -> node id`` of the media nodes already on the canvas, so a look sheet is placed once."""
    held: dict[str, str] = {}
    for node in document.get("nodes") or []:
        payload = node.get("payload") if isinstance(node.get("payload"), Mapping) else {}
        output = payload.get("output") if isinstance(payload.get("output"), Mapping) else {}
        if node.get("kind") == "media" and output.get("url"):
            held.setdefault(str(output["url"]), str(node.get("id") or ""))
    return held


def _prompt(shot: Mapping[str, Any]) -> str:
    return str(shot.get("storyboard_prompt") or shot.get("visual") or shot.get("desc") or "").strip()[:4000]


def _clip_prompt(shot: Mapping[str, Any]) -> str:
    parts = [str(shot.get("desc") or shot.get("visual") or "").strip()]
    dialogue = str(shot.get("dialogue") or "").strip()
    if dialogue and dialogue not in ("无", "-", "—"):
        parts.append(_text("dialogue_lead") + dialogue)
    return "\n".join(part for part in parts if part)[:4000]


def plan(task: Mapping[str, Any], document: Mapping[str, Any], scene_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """The edit operations that lay the chosen scenes out, and what they amount to.

    ``{"operations", "shots", "skipped", "frames_to_draw", "cast", "scenes"}``. Raises
    ``StoryboardLayoutError`` when there is no storyboard, no such scene, nothing new, or too much at once.
    """
    shots = _shots(task)
    if not shots:
        raise StoryboardLayoutError(_text("no_storyboard"))
    wanted = [str(scene).strip() for scene in scene_ids or [] if str(scene or "").strip()]
    if wanted:
        known = {shot["scene_id"] for shot in shots}
        missing = [scene for scene in wanted if scene not in known]
        if missing:
            raise StoryboardLayoutError(_text("no_scene").format(scenes="、".join(missing)))
        shots = [shot for shot in shots if shot["scene_id"] in set(wanted)]
    already = _bound(document)
    fresh = [shot for shot in shots if (shot["scene_id"], shot["shot_id"]) not in already]
    skipped = len(shots) - len(fresh)
    if not fresh:
        raise StoryboardLayoutError(_text("nothing_new"))
    limit = prompt_data.number(_DATA, "max_shots")
    if len(fresh) > limit:
        raise StoryboardLayoutError(_text("too_many").format(limit=limit, count=len(fresh)))

    grid = prompt_data.value(_DATA, "layout")
    nodes = [node for node in document.get("nodes") or [] if isinstance(node, Mapping)]
    left = max((float(node.get("x") or 0) + float(node.get("width") or 0) for node in nodes), default=0.0)
    top = min((float(node.get("y") or 0) for node in nodes), default=0.0)
    origin_x = left + (grid["cast_margin"] if nodes else 0)

    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    sheets = assets.get("3_sheets") if isinstance(assets.get("3_sheets"), Mapping) else {}
    on_canvas = _media_urls(document)
    operations: list[dict[str, Any]] = []
    cast_refs: dict[str, str] = {}
    cast_names = list(dict.fromkeys(name for shot in fresh if not _usable(shot.get("image_url")) for name in _names(shot.get("characters"))))
    row = 0
    for name in cast_names:
        url = _usable(sheets.get(name))
        if not url:
            continue
        if url in on_canvas:
            cast_refs[name] = on_canvas[url]
            continue
        ref = f"cast{len(cast_refs)}"
        operations.append({
            "op": "add_node", "ref": ref, "kind": "media", "label": _text("cast_label").format(name=name),
            "output": {"medium": "image", "url": url, "name": name},
            "x": origin_x, "y": top + row * (grid["cast_height"] + grid["cast_gap"]), "width": grid["cast_width"], "height": grid["cast_height"],
        })
        cast_refs[name] = ref
        row += 1
    shots_x = origin_x + (grid["cast_width"] + grid["cast_margin"] if row else 0)

    by_scene: dict[str, list[dict[str, Any]]] = {}
    for shot in fresh:
        by_scene.setdefault(shot["scene_id"], []).append(shot)
    row_height = grid["frame_height"] + grid["pair_gap"] + grid["clip_height"] + grid["row_gap"]
    frames_to_draw = 0
    clips: list[str] = []
    for scene_row, (scene, members) in enumerate(by_scene.items()):
        y = top + scene_row * row_height
        refs: list[str] = []
        for column, shot in enumerate(members):
            x = shots_x + column * grid["column"]
            key = f"{scene}_{shot['shot_id']}"
            names = {"scene": scene, "shot": shot["shot_id"]}
            picture = _usable(shot.get("image_url"))
            frame = {"op": "add_node", "ref": f"frame_{key}", "x": x, "y": y, "width": grid["column"] - 60, "height": grid["frame_height"]}
            if picture:
                operations.append({**frame, "kind": "media", "label": _text("board_label").format(**names), "output": {"medium": "image", "url": picture}})
            else:
                frames_to_draw += 1
                operations.append({**frame, "kind": "image_gen", "label": _text("frame_label").format(**names), "prompt": _prompt(shot)})
                for name in _names(shot.get("characters")):
                    if name in cast_refs:
                        operations.append({"op": "connect", "source": cast_refs[name], "target": f"frame_{key}", "role": "ref_image"})
            seconds = _seconds(shot.get("duration"))
            operations.append({
                "op": "add_node", "ref": f"clip_{key}", "kind": "video_gen", "label": _text("clip_label").format(**names), "prompt": _clip_prompt(shot),
                **({"params": {"durationSeconds": seconds}} if seconds else {}), "binding": {"sceneId": scene, "shotId": shot["shot_id"]},
                "x": x, "y": y + grid["frame_height"] + grid["pair_gap"], "width": grid["column"] - 60, "height": grid["clip_height"],
            })
            operations.append({"op": "connect", "source": f"frame_{key}", "target": f"clip_{key}", "role": "first_frame"})
            refs += [f"frame_{key}", f"clip_{key}"]
            clips.append(f"clip_{key}")
        operations.append({"op": "group", "ids": refs, "label": _text("scene_label").format(scene=scene), "ref": f"scene_{scene}"})
    if len(clips) >= 2:
        # The scenes joined: every video node, in shot order (a compose node joins its clips in connection order).
        operations.append({
            "op": "add_node", "ref": "film", "kind": "video_compose", "label": _text("film_label").format(count=len(clips)),
            "x": shots_x, "y": top + len(by_scene) * row_height, "width": grid["film_width"], "height": grid["film_height"],
        })
        operations += [{"op": "connect", "source": clip, "target": "film", "role": "clip"} for clip in clips]
    return {
        "operations": operations, "shots": len(fresh), "skipped": skipped, "frames_to_draw": frames_to_draw,
        "cast": sum(1 for ref in cast_refs.values() if ref.startswith("cast")), "scenes": list(by_scene),
    }


__all__ = ["StoryboardLayoutError", "plan", "scenes_of"]

# -*- coding: utf-8 -*-
"""Glue between the spatial stage and a drama task.

The stage package is pure; this module reads a scene out of a task (cast, set,
props, the storyboard table when stage 4 has run), keeps the plans under
``assets["4_spatial"]`` and hands the storyboard pipeline what it needs from a
plan: the four spatial sentences of each panel, the director's frame positions,
landmarks and continuity locks, and the checks that gate stage 5.

Two memories live next to the plans and are what make consistency hold *across*
scenes rather than inside one:

- ``side_memory``   — which side of the frame a character was first promised;
  the next scene that pairs them keeps it.
- ``locations``     — the set pieces of each location; every later scene shot in
  the same place inherits them at the same coordinates.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.spatial_stage.coverage import ShotSpec
from app.core.spatial_stage.models import StageLandmark, StagePlan
from app.core.spatial_stage.operations import apply_operations
from app.core.spatial_stage.planner import (
    EMPTY_CAST,
    SceneBrief,
    build_plan,
    cast_fingerprint,
    location_key,
    refresh,
    speaker_of,
)
from app.core.spatial_stage.prompting import array_members, frame_positions, landmark_relative_position, master_camera
from app.core.storyboard_scene_context import compile_scene_context
from app.service.director_desk_service import mark_captures_stale

logger = logging.getLogger("app.service.spatial_stage")

ASSET_KEY = "4_spatial"
STORE_VERSION = 1
# Screen states are measurements of the plan; they are recomputed on load, not stored.
_DERIVED = {"shots": {"__all__": {"screen"}}}
_ASPECTS = {"9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "2.39:1"}


class StageConflict(ValueError):
    """The plan changed since the caller read it, or the task cannot be edited right now."""


def store_of(task: dict[str, Any]) -> dict[str, Any]:
    assets = task.setdefault("assets", {})
    store = assets.get(ASSET_KEY)
    if not isinstance(store, dict) or store.get("version") != STORE_VERSION:
        store = {"version": STORE_VERSION, "scenes": {}, "side_memory": {}, "locations": {}}
        assets[ASSET_KEY] = store
    for key in ("scenes", "side_memory", "locations"):
        if not isinstance(store.get(key), dict):
            store[key] = {}
    return store


def _peek_store(task: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    store = assets.get(ASSET_KEY)
    return store if isinstance(store, Mapping) and store.get("version") == STORE_VERSION else {}


def aspect_ratio_of(task: Mapping[str, Any]) -> str:
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    value = str(config.get("aspect_ratio") or "9:16").replace("：", ":").strip()
    return value if value in _ASPECTS else "9:16"


def load_plan(task: Mapping[str, Any], scene_id: str) -> StagePlan | None:
    raw = (_peek_store(task).get("scenes") or {}).get(str(scene_id))
    if not isinstance(raw, Mapping):
        return None
    try:
        return refresh(StagePlan.model_validate(raw))
    except ValueError as error:
        logger.warning("[Spatial] 场景 %s 的空间方案无法读取，将重新规划: %s", scene_id, str(error)[:200])
        return None


def save_plan(task: dict[str, Any], plan: StagePlan) -> None:
    """Store ``plan`` and let it teach the two cross-scene memories."""
    store = store_of(task)
    store["scenes"][plan.scene_id] = plan.model_dump(mode="json", exclude=_DERIVED)
    memory = store["side_memory"]
    for actor in plan.actors:
        if actor.role == "principal" and actor.screen_side in {"left", "right"}:
            # An edit is a decision: it re-teaches the promise. An automatic plan only fills gaps.
            if plan.source == "edited" or actor.name not in memory:
                memory[actor.name] = actor.screen_side
    if plan.location_key:
        known = {item.get("name"): item for item in store["locations"].get(plan.location_key, []) if isinstance(item, dict)}
        for landmark in plan.landmarks:
            if plan.source == "edited" or landmark.name not in known:
                known[landmark.name] = landmark.model_dump(mode="json")
        store["locations"][plan.location_key] = list(known.values())[:80]


def _location_landmarks(task: Mapping[str, Any], location: str) -> list[StageLandmark]:
    items = (_peek_store(task).get("locations") or {}).get(location_key(location)) or []
    landmarks: list[StageLandmark] = []
    for item in items:
        try:
            landmarks.append(StageLandmark.model_validate(item))
        except ValueError:
            continue
    return landmarks


def breakdown_scene(task: Mapping[str, Any], scene_id: str) -> dict[str, Any] | None:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), Mapping) else {}
    for scene in breakdown.get("scenes") or []:
        if isinstance(scene, dict) and str(scene.get("scene_id") or "").strip() == str(scene_id):
            return scene
    return None


def scene_record(task: Mapping[str, Any], scene_id: str) -> dict[str, Any] | None:
    """The breakdown scene, or — for a task whose scenes survive only as storyboard shots — one read back from them."""
    scene = breakdown_scene(task, scene_id)
    if scene is not None:
        return scene
    shots = scene_shots(task, scene_id)
    if not shots:
        return None
    cast: list[str] = []
    for shot in shots:
        for name in shot.get("characters") or []:
            if str(name).strip() not in EMPTY_CAST and str(name).strip() not in cast:
                cast.append(str(name).strip())
    return {
        "scene_id": scene_id,
        "content": "。".join(str(shot.get("desc") or "") for shot in shots)[:4000] or str(shots[0].get("scene") or scene_id),
        "characters": cast,
    }


def try_plan_scene(
    task: dict[str, Any], scene: Mapping[str, Any], shots: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any] | None = None,
) -> StagePlan | None:
    """``plan_scene`` for the storyboard pipeline: a scene the stage cannot plan is drawn the old way, not failed."""
    try:
        return plan_scene(task, scene, shots, context)
    except Exception as error:  # noqa: BLE001 - blocking is an enhancement; never the reason a board fails
        logger.warning(
            "[Spatial] 场景 %s 空间方案规划失败，本场沿用固定调度措辞: %s: %s",
            scene.get("scene_id"), type(error).__name__, str(error)[:300],
        )
        return None


def scene_shots(task: Mapping[str, Any], scene_id: str) -> list[dict[str, Any]]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    shots = [
        shot for shot in (assets.get("4") or [])
        if isinstance(shot, dict) and str(shot.get("scene_id") or "") == str(scene_id)
    ]
    return sorted(shots, key=lambda shot: int(shot.get("shot_id") or 0))


def shot_specs(shots: Sequence[Mapping[str, Any]], cast: Sequence[str]) -> list[ShotSpec]:
    specs: list[ShotSpec] = []
    for index, shot in enumerate(shots, start=1):
        names = shot.get("characters") if isinstance(shot.get("characters"), list) else []
        specs.append(ShotSpec(
            shot_id=int(shot.get("shot_id") or index),
            subjects=[str(name).strip() for name in names if str(name).strip() not in EMPTY_CAST],
            speaker=speaker_of(str(shot.get("dialogue") or ""), cast),
            size=str(shot.get("size") or "中景"),
            angle=str(shot.get("angle") or ""),
            motion=str(shot.get("motion") or ""),
            desc=str(shot.get("desc") or "")[:1000],
        ))
    return specs


def brief_for(
    task: Mapping[str, Any], scene: Mapping[str, Any], shots: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any] | None = None,
) -> SceneBrief:
    context = context if context is not None else compile_scene_context(dict(task), dict(scene))
    cast = [str(name) for name in (context.get("characters") or []) if str(name).strip() not in EMPTY_CAST]
    for shot in shots:
        for name in shot.get("characters") or []:
            if str(name).strip() not in EMPTY_CAST and str(name).strip() not in cast:
                cast.append(str(name).strip())
    location = "；".join(str(item.get("name") or "") for item in (context.get("scenes") or []) if isinstance(item, Mapping))
    return SceneBrief(
        scene_id=str(scene.get("scene_id") or "E1S01"),
        location=(location or str(scene.get("content") or "")[:60])[:500],
        text=str(context.get("script") or scene.get("content") or "")[:20_000],
        characters=cast,
        props=[str(item.get("name") or "") for item in (context.get("props") or []) if isinstance(item, Mapping)],
        shots=shot_specs(shots, cast),
        aspect_ratio=aspect_ratio_of(task),
    )


def plan_scene(
    task: dict[str, Any], scene: Mapping[str, Any], shots: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any] | None = None, *, keep_edits: bool = True,
) -> StagePlan:
    """The stage for ``scene`` with cameras solved for ``shots``.

    Blocking is decided once per cast and set: a re-plan keeps the marks of the stored plan
    (the one the storyboard table was written against, or a person's edit) and only solves
    cameras again. ``keep_edits=False`` derives the blocking afresh.
    """
    brief = brief_for(task, scene, shots, context)
    prior = load_plan(task, brief.scene_id) if keep_edits else None
    fingerprint = cast_fingerprint(brief.characters, brief.location)
    keep = prior if prior is not None and prior.cast_fingerprint == fingerprint else None
    plan = build_plan(
        brief,
        side_memory=(_peek_store(task).get("side_memory") or {}),
        location_landmarks=_location_landmarks(task, brief.location),
        blocking_from=keep,
    )
    save_plan(task, plan)
    return plan


def ensure_plan(task: dict[str, Any], scene_id: str) -> StagePlan | None:
    """The stored plan of a scene, or one planned now from the breakdown and whatever shots exist."""
    plan = load_plan(task, scene_id)
    if plan is not None:
        return plan
    scene = scene_record(task, scene_id)
    return plan_scene(task, scene, scene_shots(task, scene_id)) if scene is not None else None


# --------------------------------------------------------------------------- storyboard hand-off


def panel_fields(plan: StagePlan, shot_id: int) -> dict[str, Any]:
    """The spatial fields of a ``StoryboardPanel``; empty when the plan has no such shot."""
    shot = plan.shot(shot_id)
    camera = plan.camera(shot.camera_id) if shot is not None else None
    if shot is None or camera is None:
        return {}
    text = shot.text
    return {
        "camera_angle": text.camera_angle, "lens_mm": int(round(max(8.0, min(600.0, camera.lens_mm)))),
        "composition": text.composition, "action_axis": text.action_axis,
        "eyeline": text.eyeline, "blocking": text.blocking,
    }


def screen_direction(plan: StagePlan, shot_id: int) -> str:
    """``ContinuityState.screen_direction`` of a shot, measured instead of guessed from its wording.

    Relative to the side coverage was established on: a shot there reads left-to-right, one
    that crossed reads right-to-left, and an on-axis / crossing / re-establishing shot is the
    neutral bridge between them.
    """
    shot = plan.shot(shot_id)
    if shot is None or plan.axis.kind == "none" or shot.axis_side == 0 or shot.crossing != "none":
        return "neutral"
    return "left_to_right" if shot.axis_side == (plan.axis.camera_side or 1) else "right_to_left"


def shot_summary(plan: StagePlan, shot_id: int) -> dict[str, Any]:
    """What a storyboard shot records about its place on the stage."""
    shot = plan.shot(shot_id)
    camera = plan.camera(shot.camera_id) if shot is not None else None
    if shot is None or camera is None:
        return {}
    return {
        "camera_id": camera.id, "function": camera.function, "axis_side": shot.axis_side, "crossing": shot.crossing,
        "screen_direction": screen_direction(plan, shot_id),
        "lens_mm": camera.lens_mm, "plan_revision": plan.revision,
        "screen": [
            {"name": state.name, "region": state.region, "depth": state.depth_layer, "facing": state.facing}
            for state in shot.screen if state.visible
        ],
    }


def director_context(plan: StagePlan) -> dict[str, Any]:
    """What ``compile_storyboard_prompt_detail`` reads from a plan (under ``production_context["spatial"]``)."""
    master = master_camera(plan)
    master_shot = next((shot for shot in plan.shots if master is not None and shot.camera_id == master.id), None)
    first = plan.shots[0] if plan.shots else None
    last = plan.shots[-1] if plan.shots else None
    lead = master_shot or first
    return {
        "scene_bible": plan.scene_bible,
        "frame_positions": [
            item.model_dump()
            for item in (frame_positions(lead, plan.camera(lead.camera_id), array_members(plan)) if lead is not None else [])
        ],
        "landmarks": [
            {"name": item.name, "relative_position": landmark_relative_position(plan, item), "form_and_count": "1处，位置固定"}
            for item in plan.landmarks
        ][:50],
        "camera_axis": lead.text.action_axis if lead is not None else "",
        "screen_direction": lead.text.eyeline if lead is not None else "",
        "spatial_orientation": lead.text.blocking if lead is not None else "",
        "camera_start": first.text.camera_start if first is not None else "",
        "camera_end": last.text.camera_end if last is not None else "",
        "checks": [check.model_dump() for check in plan.checks],
    }


def summaries(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    boards = assets.get("4_scene_boards") if isinstance(assets.get("4_scene_boards"), Mapping) else {}
    rows: list[dict[str, Any]] = []
    for scene_id, raw in (_peek_store(task).get("scenes") or {}).items():
        plan = load_plan(task, scene_id)
        if plan is None or not isinstance(raw, Mapping):
            continue
        failed = [check for check in plan.checks if not check.passed]
        board = boards.get(scene_id) if isinstance(boards.get(scene_id), Mapping) else {}
        rows.append({
            "scene_id": scene_id, "location": plan.location, "formation": plan.formation,
            "actor_count": len(plan.actors), "camera_count": len(plan.cameras), "source": plan.source,
            "revision": plan.revision, "coverage": plan.coverage,
            "errors": [check.code for check in failed if check.severity == "error"],
            "warnings": [check.code for check in failed if check.severity == "warning"],
            "stale": bool(board.get("spatial_stale")),
        })
    return rows


# --------------------------------------------------------------------------- edits


def edit_plan(
    task: dict[str, Any], scene_id: str, *, base_revision: int, operations: Sequence[Mapping[str, Any]],
    solve: bool | None = None,
) -> StagePlan:
    plan = ensure_plan(task, scene_id)
    if plan is None:
        raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
    if plan.revision != int(base_revision):
        raise StageConflict("空间方案已在其他页面更新，请刷新后重试")
    edited = apply_operations(plan, operations, solve=solve)
    save_plan(task, edited)
    mark_board_stale(task, scene_id)
    mark_captures_stale(task, scene_id)
    return edited


def rebuild_plan(task: dict[str, Any], scene_id: str) -> StagePlan:
    scene = scene_record(task, scene_id)
    if scene is None:
        raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
    prior = load_plan(task, scene_id)
    plan = plan_scene(task, scene, scene_shots(task, scene_id), keep_edits=False)
    if prior is not None:
        plan = plan.model_copy(update={"revision": prior.revision + 1})
        save_plan(task, plan)
    mark_board_stale(task, scene_id)
    mark_captures_stale(task, scene_id)
    return plan


def mark_board_stale(task: dict[str, Any], scene_id: str) -> None:
    """A finished board was drawn from the old blocking; say so until it is drawn again."""
    boards = (task.get("assets") or {}).get("4_scene_boards")
    entry = boards.get(scene_id) if isinstance(boards, dict) else None
    if isinstance(entry, dict) and entry.get("status") == "done":
        entry["spatial_stale"] = True


def request_redraw(task: dict[str, Any], scene_id: str) -> bool:
    """Send one finished scene back to stage 4 so its board is drawn again from the current blocking."""
    assets = task.setdefault("assets", {})
    boards = assets.get("4_scene_boards")
    entry = boards.get(scene_id) if isinstance(boards, dict) else None
    if not isinstance(entry, dict):
        return False
    entry.update(status="pending", shots_done=0)
    for key in ("spatial_stale", "error", "continuity"):
        entry.pop(key, None)
    assets["4"] = [
        shot for shot in (assets.get("4") or [])
        if not (isinstance(shot, dict) and str(shot.get("scene_id") or "") == str(scene_id))
    ]
    return True


__all__ = [
    "ASSET_KEY", "StageConflict", "aspect_ratio_of", "breakdown_scene", "brief_for", "director_context",
    "edit_plan", "ensure_plan", "load_plan", "mark_board_stale", "panel_fields", "plan_scene",
    "rebuild_plan", "request_redraw", "save_plan", "scene_record", "scene_shots", "screen_direction", "shot_specs",
    "shot_summary", "store_of", "summaries", "try_plan_scene",
]

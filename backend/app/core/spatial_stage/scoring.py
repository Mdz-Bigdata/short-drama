# -*- coding: utf-8 -*-
"""How good a stage is, in numbers, so candidate plans can be ranked and a lens can be searched for.

The checks in ``validation.py`` say what is broken. This says how well the rest works: whether the people a
shot is about are in frame and large enough for its shot size, sit away from the frame's edge, are not hidden
by a person or a set piece, whether anybody stands inside a wall, and whether the scene has depth and more than
one kind of shot. Every number is measured from the plan's own geometry; nothing here calls a model.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.coverage import canonical_size, keep_side, lens_bearing
from app.core.spatial_stage.models import StageActor, StageCamera, StageLandmark, StagePlan, StageShot
from app.core.spatial_stage.projection import SHOT_SIZE_HEIGHTS, posture_height, screen_states

_ERROR_COST = 12.0
_WARNING_COST = 4.0
_SIZE_COVER = dict(SHOT_SIZE_HEIGHTS)
# A flat floor or rug under the action blocks nothing.
_LOW_PIECE_M = 0.25
_BODY_RADIUS_M = 0.22
# Screen x runs -1 … +1 across the frame; a subject past this has no room left on its side.
_FRAME_EDGE = 0.8
_ORBIT_DEGREES = (0.0, -15.0, 15.0, -30.0, 30.0, -45.0, 45.0)
_HEIGHT_FACTORS = (1.0, 0.72, 1.3)
_REACH_FACTORS = (1.0, 0.88, 1.14)
_WORTH_MOVING = 2.0
# Actors above this are crowds; a search that costs seconds per shot is not worth it for them.
_SEARCH_ACTOR_LIMIT = 40


def _local(point: Sequence[float], piece: StageLandmark) -> tuple[float, float]:
    """``point`` (x, z) in the piece's own axes, with its yaw taken off."""
    dx, dz = point[0] - piece.position[0], point[1] - piece.position[1]
    yaw = math.radians(piece.yaw_deg)
    return (dx * math.cos(yaw) - dz * math.sin(yaw), dx * math.sin(yaw) + dz * math.cos(yaw))


def inside_piece(point: Sequence[float], piece: StageLandmark, margin: float = 0.0) -> bool:
    x, z = _local(point, piece)
    return abs(x) <= piece.size[0] / 2 + margin and abs(z) <= piece.size[1] / 2 + margin


def piece_blocks_ray(start: Sequence[float], end: Sequence[float], piece: StageLandmark) -> bool:
    """Does the straight line ``start`` → ``end`` (x, y, z) pass through this piece's bounding volume?"""
    bottom, top = piece.elevation_m, piece.elevation_m + piece.size[2]
    if top - bottom < _LOW_PIECE_M and bottom < _LOW_PIECE_M:
        return False
    x0, z0 = _local((start[0], start[2]), piece)
    x1, z1 = _local((end[0], end[2]), piece)
    low, high = 0.0, 1.0
    for origin, stop, half in ((x0, x1, piece.size[0] / 2), (z0, z1, piece.size[1] / 2), (start[1] - (top + bottom) / 2, end[1] - (top + bottom) / 2, (top - bottom) / 2)):
        delta = stop - origin
        if abs(delta) < 1e-9:
            if abs(origin) > half:
                return False
            continue
        first, second = (-half - origin) / delta, (half - origin) / delta
        low, high = max(low, min(first, second)), min(high, max(first, second))
        if low > high:
            return False
    # Starting or ending inside the piece is reported by the standing checks instead.
    return high - low > 1e-3 and low > 1e-3 and high < 1 - 1e-3


def _expected_fraction(actor: StageActor, size: str) -> float:
    """How much of the frame's height the whole figure spans at this shot size (1 is the full frame)."""
    cover = _SIZE_COVER.get(canonical_size(size))
    return posture_height(actor) / cover if cover else 0.0


def score_camera(
    camera: StageCamera, actors: Sequence[StageActor], landmarks: Sequence[StageLandmark], *, over_shoulder: bool = False,
) -> tuple[float, list[str]]:
    """0 to 100 for what this lens sees of its subjects, and what cost it points."""
    by_name = {actor.name: actor for actor in actors}
    subjects = [name for name in camera.subjects if name in by_name]
    if not subjects:
        return 70.0, []
    states = {state.name: state for state in screen_states(actors, camera)}
    wanted = [states[name] for name in subjects if name in states]
    notes: list[str] = []
    visible = [state for state in wanted if state.visible]
    sight = 40.0 * len(visible) / len(wanted)
    if len(visible) < len(wanted):
        notes.append("、".join(state.name for state in wanted if not state.visible) + " 不在画内")
    clear = 25.0
    for state in visible:
        if state.occluded_by and not over_shoulder:
            clear -= 25.0 / len(wanted)
            notes.append(f"{state.name} 被 {state.occluded_by} 挡住")
    for name in subjects:
        actor = by_name[name]
        chest = (actor.position[0], posture_height(actor) * 0.72, actor.position[1])
        blocker = next((piece for piece in landmarks if piece_blocks_ray(camera.position, chest, piece)), None)
        if blocker is not None:
            clear -= 25.0 / len(wanted)
            notes.append(f"{name} 被布景「{blocker.name}」挡住")
    framing = 20.0
    # In a narrow frame a group is held by its width, not its height: being small is what fitting them takes.
    tolerance = 6.0 if len(wanted) > 1 else 12.0
    for state in visible:
        expected = _expected_fraction(by_name[state.name], camera.shot_size)
        if expected > 0 and state.height_fraction > 0:
            off = abs(math.log(state.height_fraction / expected))
            framing -= min(20.0, tolerance * off) / len(wanted)
    placing = 15.0
    for state in visible:
        if abs(state.x) > _FRAME_EDGE:
            placing -= 15.0 * min(1.0, (abs(state.x) - _FRAME_EDGE) / (1.0 - _FRAME_EDGE)) / len(wanted)
    return max(0.0, sight + clear + framing + placing), notes


def score_shot(plan: StagePlan, shot: StageShot) -> tuple[float, list[str]]:
    camera = next((item for item in plan.cameras if item.id == shot.camera_id), None)
    if camera is None:
        return 0.0, ["镜头没有机位"]
    return score_camera(camera, plan.actors_in(shot), plan.landmarks, over_shoulder=camera.function == "over_shoulder")


def _standing_problems(plan: StagePlan) -> list[str]:
    problems: list[str] = []
    for actor in plan.actors:
        if actor.crowd_id:
            continue
        for piece in plan.landmarks:
            solid = piece.elevation_m < posture_height(actor) and piece.size[2] > _LOW_PIECE_M and piece.shape != "plane"
            if solid and inside_piece(actor.position, piece):
                problems.append(f"{actor.name} 站在「{piece.name}」里面")
                break
    used = {shot.camera_id for shot in plan.shots}
    for camera in plan.cameras:
        if camera.id not in used:
            continue
        for piece in plan.landmarks:
            within = piece.elevation_m <= camera.position[1] <= piece.elevation_m + piece.size[2]
            if within and piece.shape != "plane" and inside_piece((camera.position[0], camera.position[2]), piece):
                problems.append(f"机位「{camera.label}」在「{piece.name}」里面")
                break
    return problems


def _variety(plan: StagePlan) -> float:
    """Up to 8 points for a coverage that does not repeat one size from one side."""
    if len(plan.shots) < 2:
        return 8.0
    cameras = {camera.id: camera for camera in plan.cameras}
    used = [cameras[shot.camera_id] for shot in plan.shots if shot.camera_id in cameras]
    sizes = {canonical_size(camera.shot_size) for camera in used}
    bearings = {
        round(math.degrees(math.atan2(bearing[1], bearing[0])) / 30.0)
        for camera in used if (bearing := lens_bearing(camera)) is not None
    }
    return min(4.0, 2.0 * (len(sizes) - 1)) + min(4.0, 1.5 * (len(bearings) - 1))


def _depth(plan: StagePlan) -> float:
    """Up to 7 points when the people of the scene are not all on one line across the frame."""
    people = [actor for actor in plan.actors if actor.role != "crowd" and not actor.crowd_id]
    if len(people) < 3:
        return 7.0
    camera = next((item for item in plan.cameras if plan.shots and item.id == plan.shots[0].camera_id), None)
    if camera is None:
        return 0.0
    depths = [state.depth_m for state in screen_states(people, camera)]
    return min(7.0, 3.5 * (max(depths) - min(depths)))


def score_plan(plan: StagePlan) -> dict[str, Any]:
    """The plan's score out of 100, what went into it, and what the worst of it is in words."""
    failed = [check for check in plan.checks if not check.passed]
    errors = sum(check.severity == "error" for check in failed)
    warnings = len(failed) - errors
    shot_scores: dict[str, float] = {}
    notes: list[str] = []
    for shot in plan.shots:
        value, said = score_shot(plan, shot)
        shot_scores[str(shot.shot_id)] = round(value, 1)
        notes.extend(f"第{shot.shot_id}镜：{item}" for item in said)
    average = sum(shot_scores.values()) / len(shot_scores) if shot_scores else 70.0
    standing = _standing_problems(plan)
    notes = standing + notes
    variety, depth = _variety(plan), _depth(plan)
    total = (
        average * 0.85 + variety + depth
        - errors * _ERROR_COST - warnings * _WARNING_COST - len(standing) * _ERROR_COST
    )
    return {
        "score": round(max(0.0, min(100.0, total)), 1),
        "errors": errors, "warnings": warnings,
        "failing": [check.code for check in failed],
        "shots": shot_scores, "variety": round(variety, 1), "depth": round(depth, 1),
        "standing": len(standing), "notes": notes[:12],
    }


def _moved(camera: StageCamera, position: geo.Vec3) -> StageCamera:
    update: dict[str, Any] = {"position": geo.rounded(position)}
    if camera.move.end_position is not None:
        shift = [position[index] - camera.position[index] for index in range(3)]
        update["move"] = camera.move.model_copy(update={
            "end_position": geo.rounded([camera.move.end_position[index] + shift[index] for index in range(3)]),
        })
    return camera.model_copy(update=update)


def candidate_cameras(plan: StagePlan, shot: StageShot, *, limit: int = 3) -> list[tuple[float, StageCamera]]:
    """The best lenses found around this shot's camera, best first; the first is never worse than the current one.

    Orbits the aim point, raises and lowers the lens and moves it in and out, keeping the axis side. Lenses that
    land inside a set piece or under the floor are skipped.
    """
    camera = next((item for item in plan.cameras if item.id == shot.camera_id), None)
    if camera is None:
        return []
    actors, landmarks = plan.actors_in(shot), plan.landmarks
    over_shoulder = camera.function == "over_shoulder"
    target = camera.target
    dx, dz = camera.position[0] - target[0], camera.position[2] - target[2]
    reach = math.hypot(dx, dz)
    base_score = score_camera(camera, actors, landmarks, over_shoulder=over_shoulder)[0]
    found: list[tuple[float, StageCamera]] = [(base_score, camera)]
    if reach < 1e-3 or len(actors) > _SEARCH_ACTOR_LIMIT:
        return found
    base = math.atan2(dz, dx)
    for degrees in _ORBIT_DEGREES:
        for height in _HEIGHT_FACTORS:
            for far in _REACH_FACTORS:
                if degrees == 0.0 and height == 1.0 and far == 1.0:
                    continue
                angle = base + math.radians(degrees)
                position = (
                    target[0] + reach * far * math.cos(angle),
                    max(0.25, camera.position[1] * height),
                    target[2] + reach * far * math.sin(angle),
                )
                if axis_rules.has_axis(plan.axis) and keep_side(position, plan.axis, target) != position:
                    continue
                blocked = any(
                    piece.elevation_m <= position[1] <= piece.elevation_m + piece.size[2]
                    and inside_piece((position[0], position[2]), piece, 0.1)
                    for piece in landmarks if piece.shape != "plane"
                )
                if blocked:
                    continue
                trial = _moved(camera, position)
                # Staying put wins a near tie: a lens should not wander for a rounding error.
                value = score_camera(trial, actors, landmarks, over_shoulder=over_shoulder)[0]
                found.append((value - 0.2 * abs(degrees) / 45.0, trial))
    found.sort(key=lambda item: -item[0])
    return found[:max(1, limit)]


def best_lens_is_worth_it(found: Sequence[tuple[float, StageCamera]], current: StageCamera, current_score: float) -> bool:
    return bool(found) and found[0][1].position != current.position and found[0][0] - current_score >= _WORTH_MOVING


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """One line for a person: what a change did to the stage."""
    delta = float(after["score"]) - float(before["score"])
    change = "不变" if abs(delta) < 0.05 else f"{'+' if delta > 0 else ''}{delta:.1f}"
    return f"评分 {before['score']} → {after['score']}（{change}），错误 {before['errors']} → {after['errors']}，警告 {before['warnings']} → {after['warnings']}"


__all__ = [
    "best_lens_is_worth_it", "candidate_cameras", "compare", "inside_piece", "piece_blocks_ray", "score_camera", "score_plan", "score_shot",
]

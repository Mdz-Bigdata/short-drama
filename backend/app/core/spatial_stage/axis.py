# -*- coding: utf-8 -*-
"""The axis of action and the 180-degree rule, as geometry.

The axis is the floor line between the two characters a scene is about (or a
character and what they look at). Coverage stays on one side of it; a cut to
the other side swaps everyone's screen side and reverses their eyelines. Here
the side of every camera is a sign, and a sequence of shots is legal when no
cut flips that sign without a bridge: a shot on the axis itself, a camera that
travels across it, or a wide that re-establishes the space.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import StageAxis, StageCamera, StageShot

# A lens this close to the axis line (degrees off it, seen from the axis midpoint) reads as neutral.
NEUTRAL_ANGLE_DEG = 6.0
_WIDE_SIZES = ("大远景", "远景", "全景", "中全景")
_CROSSING_MOVES = frozenset({"orbit", "track", "follow"})


def axis_vector(axis: StageAxis) -> geo.Vec2:
    return geo.sub((axis.end[0], axis.end[1]), (axis.start[0], axis.start[1]))


def has_axis(axis: StageAxis) -> bool:
    return axis.kind != "none" and geo.length(axis_vector(axis)) > 1e-4


def camera_side_normal(axis: StageAxis) -> geo.Vec2:
    """Unit floor vector pointing from the axis toward the side coverage lives on.

    With the axis running start→end, the side ``(-a_z, a_x)`` shows ``start`` on
    screen left and ``end`` on screen right; ``camera_side`` picks it or its mirror.
    """
    direction = geo.unit(axis_vector(axis), (1.0, 0.0))
    normal = (-direction[1], direction[0])
    return geo.scale(normal, -1.0) if axis.camera_side < 0 else normal


def side_of(axis: StageAxis, ground_point: geo.Vec2) -> int:
    """+1 / -1 for the two sides of the axis, 0 on the line (within the neutral wedge)."""
    if not has_axis(axis):
        return 0
    start = (axis.start[0], axis.start[1])
    direction = geo.unit(axis_vector(axis), (1.0, 0.0))
    offset = geo.sub(ground_point, geo.midpoint(start, (axis.end[0], axis.end[1])))
    if geo.length(offset) <= 1e-4:
        return 0
    lateral = geo.dot(offset, (-direction[1], direction[0]))
    angle = math.degrees(math.asin(max(-1.0, min(1.0, abs(lateral) / geo.length(offset)))))
    if angle < NEUTRAL_ANGLE_DEG:
        return 0
    return 1 if lateral > 0 else -1


def is_overhead(camera: StageCamera, *, end: bool = False) -> bool:
    """A lens looking straight down shows no side of the axis: it is the classic neutral bridge."""
    position = camera.move.end_position if end and camera.move.end_position else camera.position
    target = camera.move.end_target if end and camera.move.end_target else camera.target
    drop = position[1] - target[1]
    return drop > 0 and math.hypot(position[0] - target[0], position[2] - target[2]) < 0.05 * drop


def camera_side(axis: StageAxis, camera: StageCamera, *, end: bool = False) -> int:
    if is_overhead(camera, end=end):
        return 0
    position = camera.move.end_position if end and camera.move.end_position else camera.position
    return side_of(axis, (position[0], position[2]))


def is_reestablishing(camera: StageCamera, principals: Sequence[str]) -> bool:
    """A wide that shows every principal again lets the audience re-read the space."""
    wide = any(camera.shot_size.startswith(size) for size in _WIDE_SIZES)
    return wide and bool(principals) and all(name in camera.subjects for name in principals)


def crossing_kind(axis: StageAxis, camera: StageCamera, principals: Sequence[str]) -> str:
    """How this shot may legally carry coverage across the axis, if at all."""
    start_side, end_side = camera_side(axis, camera), camera_side(axis, camera, end=True)
    if camera.move.kind in _CROSSING_MOVES and start_side * end_side < 0:
        return "moving"
    if start_side == 0:
        return "neutral"
    if is_reestablishing(camera, principals):
        return "reestablish"
    return "none"


def illegal_crossings(shots: Sequence[StageShot]) -> list[tuple[int, int]]:
    """``(previous_shot_id, shot_id)`` for every cut that jumps the axis with no bridge.

    A bridge on either side of the cut legalises it: the shot being left may be
    neutral / moving / re-establishing, or the shot being entered may itself
    carry the audience across (its camera travels over the line) or re-establish
    the space from the new side.
    """
    jumps: list[tuple[int, int]] = []
    established = 0
    previous: StageShot | None = None
    for shot in shots:
        side = shot.axis_side
        if side == 0:
            previous = shot
            continue
        if established and side != established:
            bridged = (previous is not None and previous.crossing != "none") or shot.crossing in {"reestablish", "moving"}
            if not bridged:
                jumps.append((previous.shot_id if previous else 0, shot.shot_id))
        established = side
        previous = shot
    return jumps


__all__ = [
    "NEUTRAL_ANGLE_DEG",
    "axis_vector",
    "camera_side",
    "camera_side_normal",
    "crossing_kind",
    "has_axis",
    "illegal_crossings",
    "is_overhead",
    "is_reestablishing",
    "side_of",
]

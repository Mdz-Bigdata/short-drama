# -*- coding: utf-8 -*-
"""A drawn route, turned into timeline keys.

A person draws a walk or a camera move as a line on the ground (or hands one over as a list of
points); this lays keys along it at even distances so a scrub, a preview and an exported frame
all read the same route. Pointer jitter is smoothed once before sampling; nothing else is
invented. The route is honoured as drawn: it is a person's decision, so the axis is *not*
enforced here — the checks will say if it crosses the line, and a repair can re-solve the lens.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.camera_moves import MOVE_EASINGS, eased_time
from app.core.spatial_stage.models import MAX_TRACK_KEYS, ActorKey, CameraKey, StagePose

MAX_PATH_POINTS = 400
MIN_PATH_POINTS = 2
# A key roughly every so many metres; a long route still gets no more than the track allows.
ACTOR_KEY_SPACING_M = 0.6
CAMERA_KEY_SPACING_M = 0.5
MAX_PATH_KEYS = 24
_MIN_STEP_S = 0.001


class PathError(ValueError):
    """The route cannot be turned into keys."""


Point3 = tuple[float, float, float]


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PathError(f"{label} 必须是有限数字")
    if abs(value) > 500:
        raise PathError(f"{label} 超出场地范围（±500 米）")
    return float(value)


def read_points(points: object, *, height_m: float | None) -> list[Point3]:
    """``[[x, z], …]`` or ``[[x, y, z], …]`` as 3-D points; 2-D points take ``height_m`` (0 for the ground)."""
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        raise PathError("points 必须是点的列表")
    if not MIN_PATH_POINTS <= len(points) <= MAX_PATH_POINTS:
        raise PathError(f"路径需要 {MIN_PATH_POINTS} 到 {MAX_PATH_POINTS} 个点")
    result: list[Point3] = []
    for index, point in enumerate(points):
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) not in (2, 3):
            raise PathError(f"points[{index}] 必须是 [x, z] 或 [x, y, z]")
        if len(point) == 2:
            x, z = (_finite(point[0], f"points[{index}][0]"), _finite(point[1], f"points[{index}][1]"))
            result.append((x, height_m if height_m is not None else 0.0, z))
        else:
            result.append((
                _finite(point[0], f"points[{index}][0]"), _finite(point[1], f"points[{index}][1]"),
                _finite(point[2], f"points[{index}][2]"),
            ))
    return result


def chaikin(points: Sequence[Point3], rounds: int = 1) -> list[Point3]:
    """Corner cutting: takes the jitter out of a hand-drawn line while keeping both ends in place."""
    current = list(points)
    for _ in range(max(0, rounds)):
        if len(current) < 3:
            break
        cut: list[Point3] = [current[0]]
        for a, b in zip(current, current[1:]):
            cut.append(tuple(a[i] + (b[i] - a[i]) * 0.25 for i in range(3)))
            cut.append(tuple(a[i] + (b[i] - a[i]) * 0.75 for i in range(3)))
        cut.append(current[-1])
        current = cut
    return current


def _dedupe(points: Sequence[Point3]) -> list[Point3]:
    kept: list[Point3] = []
    for point in points:
        if not kept or math.dist(kept[-1], point) > 1e-6:
            kept.append(point)
    return kept


def arc_length(points: Sequence[Point3]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def resample(points: Sequence[Point3], count: int) -> list[Point3]:
    """``count`` points at even arc length along the polyline, first and last kept exactly."""
    route = _dedupe(points)
    if len(route) < 2:
        raise PathError("路径的起点和终点不能重合")
    total = arc_length(route)
    if count < 2:
        return [route[0], route[-1]]
    result: list[Point3] = []
    cursor, travelled = 0, 0.0
    for index in range(count):
        wanted = total * index / (count - 1)
        while cursor < len(route) - 2 and travelled + math.dist(route[cursor], route[cursor + 1]) < wanted - 1e-9:
            travelled += math.dist(route[cursor], route[cursor + 1])
            cursor += 1
        a, b = route[cursor], route[cursor + 1]
        span = math.dist(a, b)
        t = 0.0 if span < 1e-9 else max(0.0, min(1.0, (wanted - travelled) / span))
        result.append(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))
    result[0], result[-1] = route[0], route[-1]
    return result


def key_count(length_m: float, spacing_m: float) -> int:
    return max(2, min(MAX_PATH_KEYS, MAX_TRACK_KEYS, math.ceil(length_m / spacing_m) + 1))


def key_times(count: int, start_s: float, end_s: float, easing: str) -> list[float]:
    """When each of ``count`` evenly spaced route samples is reached, eased over ``start_s``…``end_s``."""
    if easing not in MOVE_EASINGS:
        raise PathError(f"easing 只能是 {' / '.join(MOVE_EASINGS)}")
    if not 0 <= start_s < end_s <= 30:
        raise PathError("start_s 必须小于 end_s，且都在 0 到 30 秒之间")
    times: list[float] = []
    for index in range(count):
        progress = index / (count - 1)
        time = start_s if index == 0 else end_s if index == count - 1 else start_s + (end_s - start_s) * eased_time(progress, easing)
        time = round(time, 3)
        if times and time <= times[-1]:
            time = round(times[-1] + _MIN_STEP_S, 3)
        times.append(time)
    if times[-1] > end_s + 1e-6:
        raise PathError("路径的点太密，无法在这段时间内分配关键帧")
    return times


def heading_deg(a: Point3, b: Point3, fallback: float) -> float:
    """The yaw of someone walking from ``a`` to ``b``."""
    if geo.distance((a[0], a[2]), (b[0], b[2])) < 1e-6:
        return fallback
    return geo.yaw_toward((a[0], a[2]), (b[0], b[2]), fallback)


def actor_keys(
    points: Sequence[Point3], *, start_s: float, end_s: float, easing: str = "linear", smooth: bool = True,
    face: str = "path", face_point: geo.Vec2 | None = None, fallback_yaw: float = 0.0, pose: StagePose | None = None,
) -> list[ActorKey]:
    """Whole-figure keys along a drawn walk.

    ``face`` is ``"path"`` (turn with the route), ``"hold"`` (keep whatever yaw the track carries)
    or ``"point"`` (keep looking at ``face_point`` — a partner, a camera — while walking).
    """
    route = chaikin(points) if smooth else list(points)
    samples = resample(route, key_count(arc_length(_dedupe(route)), ACTOR_KEY_SPACING_M))
    times = key_times(len(samples), start_s, end_s, easing)
    keys: list[ActorKey] = []
    yaw = fallback_yaw
    for index, (sample, time) in enumerate(zip(samples, times)):
        if face == "path":
            # Walk facing the next sample; the last key keeps looking the way it arrived.
            if index + 1 < len(samples):
                yaw = heading_deg(sample, samples[index + 1], yaw)
            else:
                yaw = heading_deg(samples[index - 1], sample, yaw)
        elif face == "point" and face_point is not None:
            yaw = geo.yaw_toward((sample[0], sample[2]), face_point, yaw)
        keys.append(ActorKey(
            time=time, position=geo.rounded((sample[0], sample[2])),
            yaw_deg=None if face == "hold" else round(geo.normalize_yaw(yaw), 2),
            pose=pose if index == 0 and pose is not None else None,
            # The sampling already placed the keys in eased time; between two of them the route is straight.
            easing="linear",
        ))
    return keys


def camera_keys(
    points: Sequence[Point3], *, start_s: float, end_s: float, lens_mm: float, easing: str = "linear",
    smooth: bool = True, look_at: Point3 | None = None, ahead_height_m: float | None = None,
) -> list[CameraKey]:
    """Camera keys along a drawn move: the lens looks at ``look_at`` throughout, or ahead along the route."""
    route = chaikin(points) if smooth else list(points)
    samples = resample(route, key_count(arc_length(_dedupe(route)), CAMERA_KEY_SPACING_M))
    times = key_times(len(samples), start_s, end_s, easing)
    keys: list[CameraKey] = []
    for index, (sample, time) in enumerate(zip(samples, times)):
        if look_at is not None:
            target = look_at
        else:
            # Look along the route: at the next sample, or on from the previous one at the end.
            frm, to = (sample, samples[index + 1]) if index + 1 < len(samples) else (samples[index - 1], sample)
            direction = (to[0] - frm[0], 0.0, to[2] - frm[2])
            if math.hypot(direction[0], direction[2]) < 1e-6:
                direction = (0.0, 0.0, 1.0)
            height = sample[1] if ahead_height_m is None else ahead_height_m
            target = (sample[0] + direction[0], height, sample[2] + direction[2])
        if math.dist(sample, target) < 1e-2:
            # The route runs through the point it is told to look at: look just past it.
            target = (target[0], target[1], target[2] + 0.1)
        keys.append(CameraKey(
            time=time, position=geo.rounded(sample), target=geo.rounded(target), lens_mm=round(lens_mm, 1), easing="linear",
        ))
    return keys


__all__ = [
    "ACTOR_KEY_SPACING_M", "CAMERA_KEY_SPACING_M", "MAX_PATH_KEYS", "MAX_PATH_POINTS", "MIN_PATH_POINTS",
    "PathError", "actor_keys", "arc_length", "camera_keys", "chaikin", "heading_deg", "key_count", "key_times",
    "read_points", "resample",
]

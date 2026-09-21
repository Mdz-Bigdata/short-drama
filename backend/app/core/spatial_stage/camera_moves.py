# -*- coding: utf-8 -*-
"""Camera move presets, written out as ordinary keys a person can then edit.

A preset is only a way to *author* keys: nothing downstream knows a track came from one. Each
key interpolates linearly to the next; a move's overall easing is expressed by where the keys
sit in *time* (a smooth push has its samples bunched toward both ends), so a key dragged later
still behaves like any other. Every sample stays on the established side of the axis, and a
move is scaled down until the people the shot is about are still in frame along it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.coverage import keep_side
from app.core.spatial_stage.models import CameraKey, StageActor, StageAxis, StageCamera
from app.core.spatial_stage.projection import posture_height, screen_states

PRESETS: tuple[str, ...] = (
    "push", "pull", "truck", "rise", "descend", "arc", "arc-push", "crane-reveal", "ground-rise",
    "whip-pan", "push-pause", "dolly-zoom", "roll-recover", "reframe",
)
MOVE_EASINGS: tuple[str, ...] = ("linear", "smooth", "ease-in", "ease-out", "whip")
SIDES: tuple[str, ...] = ("auto", "left", "right")
ARC_SAMPLES = 12
_EASED_SAMPLES = 8
_MIN_LENS_MM, _MAX_LENS_MM = 8.0, 600.0
_GROUND_HEIGHT_M = 0.3
_PAUSE_AT = 0.6
_SHRINK = (1.0, 0.75, 0.5, 0.3, 0.15)
_DEFAULT_EASING = {"whip-pan": "whip", "roll-recover": "ease-out"}
_DEFAULT_ANGLE = {"whip-pan": 60.0}
# These start away from the solved frame and arrive on it, so only their arrival has to hold the subjects.
_ARRIVALS = frozenset({"whip-pan"})

Pose = tuple[geo.Vec3, geo.Vec3, float]


class CameraMoveError(ValueError):
    """The preset cannot be laid out for this camera."""


def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


_CURVES: dict[str, Callable[[float], float]] = {
    "linear": lambda t: t,
    "smooth": _smooth,
    "ease-in": lambda t: t * t,
    "ease-out": lambda t: 1 - (1 - t) * (1 - t),
    # Nearly still, a snap through the middle, nearly still again.
    "whip": lambda t: _smooth(_smooth(t)),
}


def eased_time(progress: float, easing: str) -> float:
    """When (0…1) a move eased by ``easing`` has covered ``progress`` of its path: the curve, inverted."""
    curve = _CURVES[easing]
    low, high = 0.0, 1.0
    for _ in range(40):
        middle = (low + high) / 2
        if curve(middle) < progress:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def default_easing(preset: str) -> str:
    return _DEFAULT_EASING.get(preset, "smooth")


def default_angle(preset: str) -> float:
    return _DEFAULT_ANGLE.get(preset, 45.0)


def _blend(a: Sequence[float], b: Sequence[float], t: float) -> geo.Vec3:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _line(start: Pose, end: Pose, samples: int) -> list[Pose]:
    return [
        (_blend(start[0], end[0], i / samples), _blend(start[1], end[1], i / samples), start[2] + (end[2] - start[2]) * i / samples)
        for i in range(samples + 1)
    ]


def _path(
    preset: str, camera: StageCamera, amplitude: float, angle: float, sign: int, samples: int,
    subjects: Sequence[StageActor], stage_center: geo.Vec2,
) -> list[Pose]:
    """The poses of the move at evenly spaced *progress* (not time), the current pose included."""
    position, target, lens = tuple(camera.position), tuple(camera.target), camera.lens_mm
    here: Pose = (position, target, lens)
    offset = tuple(position[i] - target[i] for i in range(3))
    look = geo.unit((target[0] - position[0], target[2] - position[2]))
    right = geo.right_of(look)
    frame_width = geo.visible_height(math.dist(position, target), camera.fov_deg) * geo.parse_aspect(camera.aspect)

    def toward(factor: float) -> geo.Vec3:
        return tuple(target[i] + offset[i] * factor for i in range(3))

    def slid(meters: float) -> geo.Vec3:
        return (position[0] + right[0] * meters * sign, position[1], position[2] + right[1] * meters * sign)

    if preset in {"push", "push-pause"}:
        return _line(here, (toward(max(0.25, 1 - 0.35 * amplitude)), target, lens), samples)
    if preset == "pull":
        return _line(here, (toward(1 + 0.45 * amplitude), target, lens), samples)
    if preset == "dolly-zoom":
        # Subject size is d · 36 / f: closing to k·d while the lens goes to k·f holds it, and the
        # background swells. Both are linear in progress, so the ratio holds at every sample.
        factor = max(0.25, 1 - 0.35 * amplitude, _MIN_LENS_MM / lens)
        return _line(here, (toward(factor), target, lens * factor), samples)
    if preset == "truck":
        return _line(here, (slid(max(0.12, frame_width * 0.35 * amplitude)), target, lens), samples)
    if preset == "roll-recover":
        # There is no roll channel: what survives of a roll recovering is the small sideways settle.
        return _line((slid(max(0.05, frame_width * 0.12 * amplitude)), target, lens), here, samples)
    if preset == "rise":
        return _line(here, ((position[0], position[1] + 0.9 * amplitude, position[2]), target, lens), samples)
    if preset == "descend":
        return _line(here, ((position[0], max(_GROUND_HEIGHT_M, position[1] - 0.6 * amplitude), position[2]), target, lens), samples)
    if preset == "crane-reveal":
        away = toward(1 + 0.4 * amplitude)
        return _line(here, ((away[0], away[1] + 1.2 * amplitude, away[2]), target, lens), samples)
    if preset == "ground-rise":
        low = min(position[1], _GROUND_HEIGHT_M + (position[1] - _GROUND_HEIGHT_M) * max(0.0, 1 - amplitude))
        return _line(((position[0], low, position[2]), target, lens), here, samples)
    if preset in {"arc", "arc-push"}:
        ground = (offset[0], offset[2])
        closing = 0.3 * amplitude if preset == "arc-push" else 0.0
        poses: list[Pose] = []
        for index in range(ARC_SAMPLES + 1):
            progress = index / ARC_SAMPLES
            turned = geo.scale(geo.rotate(ground, angle * amplitude * sign * progress), max(0.25, 1 - closing * progress))
            height = target[1] + offset[1] * max(0.25, 1 - closing * progress)
            poses.append(((target[0] + turned[0], height, target[2] + turned[1]), target, lens))
        return poses
    if preset == "whip-pan":
        sweep = geo.rotate((target[0] - position[0], target[2] - position[2]), -angle * amplitude * sign)
        return _line((position, (position[0] + sweep[0], target[1], position[2] + sweep[1]), lens), here, samples)
    if preset == "reframe":
        if subjects:
            centre = geo.centroid([(actor.position[0], actor.position[1]) for actor in subjects])
            height = sum(posture_height(actor) for actor in subjects) / len(subjects) * 0.75
        else:
            centre, height = stage_center, target[1]
        aim = _blend(target, (centre[0], height, centre[1]), min(1.0, amplitude))
        return _line(here, (position, aim, lens), samples)
    raise CameraMoveError(f"未知的运镜预设 {preset!r}")


def _holds(poses: Sequence[Pose], camera: StageCamera, subjects: Sequence[StageActor]) -> bool:
    aspect = geo.parse_aspect(camera.aspect)
    for position, target, lens in poses:
        probe = camera.model_copy(update={
            "position": geo.rounded(position), "target": geo.rounded(target),
            "fov_deg": round(geo.vertical_fov(lens, aspect), 2), "move": camera.move.model_copy(update={"kind": "static"}),
        })
        if not all(state.visible for state in screen_states(subjects, probe)):
            return False
    return True


def build_keys(
    preset: str, camera: StageCamera, *, duration_s: float, amplitude: float = 1.0, angle: float | None = None,
    side: str = "auto", easing: str | None = None, axis: StageAxis, subjects: Sequence[StageActor] = (),
    stage_center: geo.Vec2 = (0.0, 0.0),
) -> list[CameraKey]:
    """The keys of ``preset`` for ``camera`` over ``duration_s`` seconds."""
    if preset not in PRESETS:
        raise CameraMoveError(f"preset 只能是 {' / '.join(PRESETS)}")
    easing = easing or default_easing(preset)
    if easing not in MOVE_EASINGS:
        raise CameraMoveError(f"easing 只能是 {' / '.join(MOVE_EASINGS)}")
    if side not in SIDES:
        raise CameraMoveError(f"side 只能是 {' / '.join(SIDES)}")
    angle = default_angle(preset) if angle is None else angle
    overhead = axis_rules.is_overhead(camera)
    guarded = axis_rules.has_axis(axis) and axis.camera_side != 0 and not overhead
    samples = ARC_SAMPLES if preset in {"arc", "arc-push"} else (1 if easing == "linear" else _EASED_SAMPLES)

    def on_side(poses: Sequence[Pose]) -> bool:
        return not guarded or all(axis_rules.side_of(axis, (pose[0][0], pose[0][2])) in {axis.camera_side, 0} for pose in poses)

    def lay(sign: int, shrink: float) -> list[Pose]:
        return _path(preset, camera, amplitude * shrink, angle, sign, samples, subjects, stage_center)

    def settled(poses: Sequence[Pose]) -> list[Pose]:
        return [(keep_side(position, axis, target), target, lens) for position, target, lens in poses] if guarded else list(poses)

    def bent(poses: Sequence[Pose]) -> float:
        """How far staying clear of the axis pushed the path off the one that was asked for."""
        return max(math.dist(before[0], after[0]) for before, after in zip(poses, settled(poses)))

    # "auto" goes the way the axis bends least (heading for the line gets a move pushed back off it);
    # screen right when it makes no difference.
    signs = {"left": (-1,), "right": (1,)}.get(side, (1, -1))
    chosen: list[Pose] | None = None
    fallback: list[Pose] | None = None
    for shrink in _SHRINK:
        legal = [poses for poses in (lay(sign, shrink) for sign in signs) if on_side(poses)]
        fallback = fallback or (min(legal, key=bent) if legal else None)
        holding = [
            poses for poses in legal
            if not subjects or _holds(settled(poses)[-1:] if preset in _ARRIVALS else settled(poses), camera, subjects)
        ]
        if holding:
            chosen = min(holding, key=bent)
            break
    if chosen is None and fallback is None:
        raise CameraMoveError("这个方向的运镜会越过轴线，请换一侧或先调整轴线")
    # Nothing holds the subjects when the frame it starts from already loses them: that is the
    # camera's problem, not the move's, so the move is written as asked.
    poses = settled(chosen or fallback or [])
    if preset == "dolly-zoom":
        # The lens answers to where the camera really ended up, axis clearance included.
        reach = math.dist(camera.position, camera.target)
        poses = [(position, target, camera.lens_mm * math.dist(position, target) / reach) for position, target, _ in poses]

    span = duration_s * (_PAUSE_AT if preset == "push-pause" else 1.0)
    keys: list[CameraKey] = []
    for index, (position, target, lens) in enumerate(poses):
        time = round(span * eased_time(index / (len(poses) - 1), easing), 3) if 0 < index < len(poses) - 1 else (0.0 if index == 0 else round(span, 3))
        if keys and time <= keys[-1].time:
            time = round(keys[-1].time + 0.001, 3)
        keys.append(CameraKey(
            time=time, position=geo.rounded(position), target=geo.rounded(target),
            lens_mm=round(max(_MIN_LENS_MM, min(_MAX_LENS_MM, lens)), 1),
        ))
    if preset == "push-pause":
        keys.append(keys[-1].model_copy(update={"time": round(duration_s, 3)}))
    return keys


__all__ = [
    "ARC_SAMPLES", "MOVE_EASINGS", "PRESETS", "SIDES", "CameraMoveError", "build_keys", "default_angle",
    "default_easing", "eased_time",
]

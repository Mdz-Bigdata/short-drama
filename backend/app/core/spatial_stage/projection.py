# -*- coding: utf-8 -*-
"""What a camera on the stage actually sees.

A perspective projection of the actors into the delivery frame, reported in the
screen-coordinate grammar the storyboard already speaks (``frame_position``):
picture region, depth layer, screen facing, quantified occlusion. "A stands on
the left, looking right" stops being a sentence someone wrote and becomes a
measurement of the plan, so it cannot disagree with the blocking.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import ScreenState, StageActor, StageCamera

# Normalised screen x (-1 left edge … +1 right edge) → picture region.
_REGION_EDGES: tuple[tuple[float, str], ...] = (
    (-0.4, "画面左侧三分之一"),
    (-0.12, "画面中左侧"),
    (0.12, "画面中央"),
    (0.4, "画面中右侧"),
)
_REGION_RIGHT = "画面右侧三分之一"
# Only a facing within ~5° of the lens axis reads as "to camera": a single or an over-the-shoulder
# shot a few degrees off the axis still shows its subject looking past the lens to one side, and
# that side is the eyeline every reverse shot has to answer.
_LENS_FACING_COSINE = 0.996
_NEAR_PLANE_M = 0.2
_FRAME_MARGIN = 1.02
_ACTOR_HALF_WIDTH_M = 0.24
_EYE_FRACTION = 0.93
_CHEST_FRACTION = 0.75
# World height a frame covers for each shot size (meters of a standing adult).
SHOT_SIZE_HEIGHTS: tuple[tuple[str, float], ...] = (
    ("大特写", 0.22),
    ("特写", 0.38),
    ("近景", 0.72),
    ("中近景", 0.95),
    ("中景", 1.3),
    ("中全景", 1.85),
    ("全景", 2.35),
    ("远景", 5.0),
    ("大远景", 10.0),
)
POSTURE_HEIGHT: dict[str, float] = {
    "stand": 1.0, "walk": 1.0, "run": 0.96, "fight": 0.94, "lean": 0.97, "bow": 0.8,
    "sit": 0.74, "crouch": 0.6, "kneel": 0.68, "lie": 0.22,
}


def pose_posture(preset: str) -> str:
    """The posture a pose preset implies, or ``""``.

    Desk preset ids lead with the posture word (``sit``, ``kneel-one``, ``crouch_low``), so the
    leading token is looked up in the posture vocabulary; a free pose (no preset) implies nothing.
    """
    token = str(preset or "").strip().lower().replace("_", "-").split("-", 1)[0]
    return token if token in POSTURE_HEIGHT else ""


def posture_height(actor: StageActor) -> float:
    """How tall the actor actually stands: by its pose preset when that implies a posture, else by its posture."""
    posture = pose_posture(actor.pose.preset) if actor.pose is not None else ""
    return actor.height_m * POSTURE_HEIGHT.get(posture or actor.posture, 1.0)


def classify_shot_size(covered_height_m: float) -> str:
    """The shot size whose framing is nearest to a frame covering ``covered_height_m``."""
    best = min(SHOT_SIZE_HEIGHTS, key=lambda item: abs(math.log(max(covered_height_m, 0.01) / item[1])))
    return best[0]


@dataclass(frozen=True)
class CameraView:
    position: geo.Vec3
    target: geo.Vec3
    fov_deg: float
    aspect: float

    @classmethod
    def of(cls, camera: StageCamera, *, end: bool = False) -> "CameraView":
        position = camera.move.end_position if end and camera.move.end_position else camera.position
        target = camera.move.end_target if end and camera.move.end_target else camera.target
        return cls(
            position=(position[0], position[1], position[2]),
            target=(target[0], target[1], target[2]),
            fov_deg=camera.fov_deg,
            aspect=geo.parse_aspect(camera.aspect),
        )

    def basis(self) -> tuple[geo.Vec3, geo.Vec3, geo.Vec3]:
        """``(forward, right, up)`` of the lens."""
        fx, fy, fz = (self.target[i] - self.position[i] for i in range(3))
        size = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
        forward = (fx / size, fy / size, fz / size)
        if abs(forward[1]) < 0.999:
            world_up = (0.0, 1.0, 0.0)
        else:
            # Straight down: the frame's top is the way the lens leans, so overhead keeps screen left / right.
            lean = math.hypot(fx, fz)
            world_up = (fx / lean, 0.0, fz / lean) if lean > 1e-9 else (0.0, 0.0, -1.0)
        right = _cross3(forward, world_up)
        right_size = math.sqrt(sum(value * value for value in right)) or 1.0
        right = (right[0] / right_size, right[1] / right_size, right[2] / right_size)
        return forward, right, _cross3(right, forward)

    def ground_forward(self) -> geo.Vec2:
        return geo.unit((self.target[0] - self.position[0], self.target[2] - self.position[2]))

    def ground_right(self) -> geo.Vec2:
        return geo.right_of(self.ground_forward())

    def project(self, point: geo.Vec3) -> tuple[float, float, float]:
        """``(x, y, depth)``: x and y are -1…+1 across the frame, depth is meters along the lens."""
        forward, right, up = self.basis()
        delta = tuple(point[i] - self.position[i] for i in range(3))
        depth = sum(delta[i] * forward[i] for i in range(3))
        if depth <= 1e-6:
            return (0.0, 0.0, depth)
        half_height = depth * math.tan(math.radians(self.fov_deg) / 2)
        half_width = half_height * self.aspect
        x = sum(delta[i] * right[i] for i in range(3)) / half_width
        y = sum(delta[i] * up[i] for i in range(3)) / half_height
        return (x, y, depth)


    def offscreen_side(self, ground_point: geo.Vec2) -> str:
        """``"left"`` / ``"right"`` of the frame a point lies toward — valid even behind the lens."""
        delta = geo.sub(ground_point, (self.position[0], self.position[2]))
        return "right" if geo.dot(delta, self.ground_right()) >= 0 else "left"


def _cross3(a: geo.Vec3, b: geo.Vec3) -> geo.Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def region_of(x: float) -> str:
    for edge, label in _REGION_EDGES:
        if x < edge:
            return label
    return _REGION_RIGHT


def screen_facing(actor: StageActor, view: CameraView) -> str:
    """The actor's facing as the audience reads it."""
    forward = geo.forward_of(actor.yaw_deg)
    toward_lens = -geo.dot(forward, view.ground_forward())
    if toward_lens >= _LENS_FACING_COSINE:
        return "面向镜头"
    if toward_lens <= -_LENS_FACING_COSINE:
        return "背对镜头"
    return "朝向画面右侧" if geo.dot(forward, view.ground_right()) >= 0 else "朝向画面左侧"


def screen_interval(actor: StageActor, view: CameraView) -> tuple[float, float, float]:
    """``(left, right, depth)`` of the actor's body across the frame."""
    x, _, depth = view.project((actor.position[0], posture_height(actor) * _CHEST_FRACTION, actor.position[1]))
    if depth <= _NEAR_PLANE_M:
        return (x, x, depth)
    half = _ACTOR_HALF_WIDTH_M / (depth * math.tan(math.radians(view.fov_deg) / 2) * view.aspect)
    return (x - half, x + half, depth)


def _depth_layers(depths: dict[str, float], focus: Sequence[str]) -> dict[str, str]:
    """Foreground / midground / background relative to the subjects the shot is about."""
    focal = [depths[name] for name in focus if name in depths and depths[name] > _NEAR_PLANE_M]
    reference = sum(focal) / len(focal) if focal else (sum(depths.values()) / len(depths) if depths else 1.0)
    layers: dict[str, str] = {}
    for name, depth in depths.items():
        ratio = depth / reference if reference > 1e-6 else 1.0
        if ratio < 0.4:
            layers[name] = "近前景"
        elif ratio < 0.7:
            layers[name] = "前景"
        elif ratio <= 1.5:
            layers[name] = "中景"
        elif ratio <= 2.6:
            layers[name] = "中远景"
        else:
            layers[name] = "背景"
    return layers


def screen_states(actors: Sequence[StageActor], camera: StageCamera, *, end: bool = False) -> list[ScreenState]:
    """Every actor's place in the frame, with who stands in front of whom."""
    view = CameraView.of(camera, end=end)
    focus = list(camera.subjects)
    measured: dict[str, tuple[float, float, float, float]] = {}
    head_y: dict[str, float] = {}
    intervals: dict[str, tuple[float, float, float]] = {}
    spans: dict[str, tuple[float, float]] = {}
    for actor in actors:
        height = posture_height(actor)
        head = view.project((actor.position[0], height * _EYE_FRACTION, actor.position[1]))
        feet = view.project((actor.position[0], 0.0, actor.position[1]))
        chest = view.project((actor.position[0], height * _CHEST_FRACTION, actor.position[1]))
        fraction = abs(head[1] - feet[1]) / 2 / _EYE_FRACTION if chest[2] > _NEAR_PLANE_M else 0.0
        measured[actor.name] = (chest[0], chest[1], chest[2], fraction)
        head_y[actor.name] = head[1]
        intervals[actor.name] = screen_interval(actor, view)
        # Vertical extent on screen, padded by half a body width: seen from above a person is a
        # shoulder-wide disc, not a head-to-feet line.
        pad = _ACTOR_HALF_WIDTH_M / (chest[2] * math.tan(math.radians(view.fov_deg) / 2)) if chest[2] > _NEAR_PLANE_M else 0.0
        spans[actor.name] = (min(head[1], feet[1]) - pad, max(head[1], feet[1]) + pad)
    layers = _depth_layers({name: values[2] for name, values in measured.items()}, focus)
    states: list[ScreenState] = []
    for actor in actors:
        x, y, depth, fraction = measured[actor.name]
        left, right, _ = intervals[actor.name]
        # On screen when the torso overlaps the frame sideways and the face or the chest is inside it
        # vertically (a close-up frames the eyes and legitimately cuts the chest off).
        visible = (
            depth > _NEAR_PLANE_M and right >= -_FRAME_MARGIN and left <= _FRAME_MARGIN
            and min(abs(y), abs(head_y[actor.name])) <= 1.1
        )
        blocker = ""
        # A crowd is background: nobody asks whether one of its members is covered, and skipping
        # them keeps a 200-strong array from costing a member × member comparison per shot.
        if visible and actor.role != "crowd":
            width = max(right - left, 1e-6)
            for other in actors:
                if other.name == actor.name:
                    continue
                other_left, other_right, other_depth = intervals[other.name]
                if other_depth <= _NEAR_PLANE_M or other_depth >= depth - 0.15:
                    continue
                overlap = min(right, other_right) - max(left, other_left)
                low, high = spans[actor.name]
                other_low, other_high = spans[other.name]
                vertical = (min(high, other_high) - max(low, other_low)) / max(high - low, 1e-6)
                if overlap / width >= 0.6 and vertical >= 0.5:
                    blocker = other.name
                    break
        states.append(ScreenState(
            name=actor.name,
            visible=visible,
            x=round(max(-50.0, min(50.0, x)), 3),
            y=round(max(-50.0, min(50.0, y)), 3),
            depth_m=round(depth, 3),
            height_fraction=round(min(fraction, 100.0), 3),
            region=region_of(x) if visible else "",
            depth_layer=layers.get(actor.name, "") if visible else "",
            facing=screen_facing(actor, view) if visible else "",
            occluded_by=blocker,
        ))
    return states


__all__ = [
    "CameraView",
    "POSTURE_HEIGHT",
    "SHOT_SIZE_HEIGHTS",
    "classify_shot_size",
    "pose_posture",
    "posture_height",
    "region_of",
    "screen_facing",
    "screen_interval",
    "screen_states",
]

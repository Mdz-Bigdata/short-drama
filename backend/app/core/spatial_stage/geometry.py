# -*- coding: utf-8 -*-
"""Ground-plane geometry for the spatial stage.

Conventions (this project's own, stated once so every module agrees):

- Right-handed, Y up, meters. The floor is the XZ plane at ``y = 0``.
- A ground point is ``(x, z)``. A facing is a yaw in **degrees** about Y; yaw 0
  faces ``+Z`` and ``forward = (sin yaw, cos yaw)`` — exactly a three.js object
  whose ``rotation.y`` is that yaw, so the viewport needs no conversion.
- "Right" of any forward (a person's right hand, a camera's screen right) is
  ``cross(forward, up)`` flattened to the floor: ``(-f_z, f_x)``.
- A lens is a full-frame focal length; the 36 mm side of the sensor lies along
  the long side of the delivery frame, so a 9:16 frame sees 36 mm vertically.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]

SENSOR_LONG_SIDE_MM = 36.0
_EPSILON = 1e-6


def add(a: Vec2, b: Vec2) -> Vec2:
    return (a[0] + b[0], a[1] + b[1])


def sub(a: Vec2, b: Vec2) -> Vec2:
    return (a[0] - b[0], a[1] - b[1])


def scale(a: Vec2, factor: float) -> Vec2:
    return (a[0] * factor, a[1] * factor)


def dot(a: Vec2, b: Vec2) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Vec2, b: Vec2) -> float:
    """Z-less 2D cross product: its sign says which side of ``a`` the vector ``b`` lies on."""
    return a[0] * b[1] - a[1] * b[0]


def length(a: Vec2) -> float:
    return math.hypot(a[0], a[1])


def distance(a: Vec2, b: Vec2) -> float:
    return length(sub(a, b))


def unit(a: Vec2, fallback: Vec2 = (0.0, 1.0)) -> Vec2:
    size = length(a)
    return (a[0] / size, a[1] / size) if size > _EPSILON else fallback


def rotate(a: Vec2, degrees: float) -> Vec2:
    """Rotate in the direction yaw grows: ``rotate(forward_of(y), d) == forward_of(y + d)``."""
    radians = math.radians(degrees)
    sin, cos = math.sin(radians), math.cos(radians)
    # (x, z) with forward = (sin yaw, cos yaw): adding yaw rotates z toward x.
    return (a[0] * cos + a[1] * sin, -a[0] * sin + a[1] * cos)


def midpoint(a: Vec2, b: Vec2) -> Vec2:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def centroid(points: Sequence[Vec2]) -> Vec2:
    if not points:
        return (0.0, 0.0)
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def forward_of(yaw_degrees: float) -> Vec2:
    radians = math.radians(yaw_degrees)
    return (math.sin(radians), math.cos(radians))


def right_of(forward: Vec2) -> Vec2:
    return (-forward[1], forward[0])


def normalize_yaw(yaw_degrees: float) -> float:
    """Wrap into ``(-180, 180]`` so equal facings compare equal."""
    wrapped = math.fmod(yaw_degrees + 180.0, 360.0)
    if wrapped <= 0:
        wrapped += 360.0
    return round(wrapped - 180.0, 3)


def yaw_toward(source: Vec2, target: Vec2, fallback: float = 0.0) -> float:
    """The yaw that makes something standing on ``source`` face ``target``."""
    delta = sub(target, source)
    if length(delta) <= _EPSILON:
        return normalize_yaw(fallback)
    return normalize_yaw(math.degrees(math.atan2(delta[0], delta[1])))


# --------------------------------------------------------------------------- lens and framing


def vertical_fov(lens_mm: float, aspect: float) -> float:
    """Vertical field of view in degrees of a full-frame lens on a frame of ``aspect`` (w / h)."""
    lens = max(1.0, float(lens_mm))
    sensor_height = SENSOR_LONG_SIDE_MM if aspect < 1 else SENSOR_LONG_SIDE_MM / max(aspect, _EPSILON)
    return math.degrees(2 * math.atan(sensor_height / (2 * lens)))


def horizontal_fov(vertical_degrees: float, aspect: float) -> float:
    half = math.tan(math.radians(vertical_degrees) / 2) * aspect
    return math.degrees(2 * math.atan(half))


def visible_height(distance_m: float, vertical_degrees: float) -> float:
    """World height the frame covers at ``distance_m`` in front of the lens."""
    return 2 * max(0.0, distance_m) * math.tan(math.radians(vertical_degrees) / 2)


def framing_distance(visible_height_m: float, vertical_degrees: float) -> float:
    """How far the lens must stand so the frame covers exactly ``visible_height_m``."""
    half = math.tan(math.radians(vertical_degrees) / 2)
    return max(0.0, visible_height_m) / (2 * half) if half > _EPSILON else 0.0


def parse_aspect(value: str | float | None, default: float = 9 / 16) -> float:
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    text = str(value or "").replace("：", ":").strip()
    if ":" in text:
        left, _, right = text.partition(":")
        try:
            width, height = float(left), float(right)
        except ValueError:
            return default
        return width / height if width > 0 and height > 0 else default
    return default


# --------------------------------------------------------------------------- formations


def pair_positions(center: Vec2, axis: Vec2, separation: float) -> tuple[Vec2, Vec2]:
    """Two marks ``separation`` apart on ``axis`` through ``center``; the first is on the negative end."""
    direction = unit(axis, (1.0, 0.0))
    half = max(0.2, separation) / 2
    return add(center, scale(direction, -half)), add(center, scale(direction, half))


def line_positions(count: int, center: Vec2, axis: Vec2, spacing: float) -> list[Vec2]:
    direction = unit(axis, (1.0, 0.0))
    return [add(center, scale(direction, (index - (count - 1) / 2) * spacing)) for index in range(count)]


def arc_positions(count: int, center: Vec2, facing: Vec2, radius: float, arc_degrees: float) -> list[Vec2]:
    """Marks on an arc of ``radius`` around ``center``, spread symmetrically about ``facing``."""
    if count <= 0:
        return []
    direction = unit(facing)
    if count == 1:
        return [add(center, scale(direction, radius))]
    span = max(1.0, min(359.0, arc_degrees))
    return [
        add(center, scale(rotate(direction, -span / 2 + span * index / (count - 1)), radius))
        for index in range(count)
    ]


def circle_positions(count: int, center: Vec2, start: Vec2, radius: float) -> list[Vec2]:
    direction = unit(start)
    return [add(center, scale(rotate(direction, 360.0 * index / max(1, count)), radius)) for index in range(count)]


def grid_positions(count: int, center: Vec2, axis: Vec2, spacing: float, columns: int | None = None) -> list[Vec2]:
    """Rows along ``axis``, stacked along its perpendicular; a short last row stays centred."""
    if count <= 0:
        return []
    direction = unit(axis, (1.0, 0.0))
    depth = right_of(direction)
    per_row = max(1, columns or math.ceil(math.sqrt(count)))
    rows = math.ceil(count / per_row)
    marks: list[Vec2] = []
    for index in range(count):
        row, column = divmod(index, per_row)
        in_row = min(per_row, count - row * per_row)
        along = (column - (in_row - 1) / 2) * spacing
        back = (row - (rows - 1) / 2) * spacing
        marks.append(add(center, add(scale(direction, along), scale(depth, back))))
    return marks


def separate(points: list[Vec2], minimum: float, *, rounds: int = 12) -> list[Vec2]:
    """Push marks apart until no two stand closer than ``minimum`` (a few relaxation rounds)."""
    marks = list(points)
    for _ in range(rounds):
        moved = False
        for first in range(len(marks)):
            for second in range(first + 1, len(marks)):
                gap = distance(marks[first], marks[second])
                if gap >= minimum - _EPSILON:
                    continue
                direction = unit(sub(marks[second], marks[first]), (1.0, 0.0))
                push = (minimum - gap) / 2 + 1e-4
                marks[first] = add(marks[first], scale(direction, -push))
                marks[second] = add(marks[second], scale(direction, push))
                moved = True
        if not moved:
            break
    return marks


def rounded(point: Sequence[float], digits: int = 3) -> list[float]:
    return [round(float(value), digits) + 0.0 for value in point]


__all__ = [
    "SENSOR_LONG_SIDE_MM",
    "Vec2",
    "Vec3",
    "add",
    "arc_positions",
    "centroid",
    "circle_positions",
    "cross",
    "distance",
    "dot",
    "forward_of",
    "framing_distance",
    "grid_positions",
    "horizontal_fov",
    "length",
    "line_positions",
    "midpoint",
    "normalize_yaw",
    "pair_positions",
    "parse_aspect",
    "right_of",
    "rotate",
    "rounded",
    "scale",
    "separate",
    "sub",
    "unit",
    "vertical_fov",
    "visible_height",
    "yaw_toward",
]

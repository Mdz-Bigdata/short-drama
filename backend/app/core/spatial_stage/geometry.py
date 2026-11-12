# -*- coding: utf-8 -*-
"""Ground-plane geometry for the spatial stage.

Conventions (this project's own, stated once so every module agrees):

- Right-handed, Y up, meters. The floor is the XZ plane at ``y = 0``.
- A ground point is ``(x, z)``. A facing is a yaw in **degrees** about Y; yaw 0
  faces ``+Z`` and ``forward = (sin yaw, cos yaw)`` — exactly a three.js object
  whose ``rotation.y`` is that yaw, so the viewport needs no conversion.
- "Right" of any forward (a person's right hand, a camera's screen right) is
  ``cross(forward, up)`` flattened to the floor: ``(-f_z, f_x)``.
- A lens is a focal length on a sensor whose long side (36 mm unless the camera
  says otherwise) lies along the long side of the delivery frame, so a 9:16 frame
  on a full-frame sensor sees 36 mm vertically.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

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


def vertical_fov(lens_mm: float, aspect: float, sensor_mm: float = SENSOR_LONG_SIDE_MM) -> float:
    """Vertical field of view in degrees of a lens on a frame of ``aspect`` (w / h); ``sensor_mm`` lies along its long side."""
    lens = max(1.0, float(lens_mm))
    sensor_height = sensor_mm if aspect < 1 else sensor_mm / max(aspect, _EPSILON)
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


# ---- set pieces as volumes. A piece is anything with ``position`` (x, z), ``size`` (width, depth, height),
# ---- ``yaw_deg``, ``elevation_m`` and ``parts``: the stage's landmarks, read here without importing them.

# A flat floor or rug under the action blocks nothing.
LOW_PIECE_M = 0.25
# Nor does something that thin and no wider than this, wherever it lies: a cup on a table, a sword on a rack.
_SMALL_PIECE_M = 0.5


def local_point(point: Sequence[float], piece: Any) -> Vec2:
    """``point`` (x, z) in the piece's own axes, with its yaw taken off."""
    dx, dz = point[0] - piece.position[0], point[1] - piece.position[1]
    yaw = math.radians(piece.yaw_deg)
    return (dx * math.cos(yaw) - dz * math.sin(yaw), dx * math.sin(yaw) + dz * math.cos(yaw))


def inside_piece(point: Sequence[float], piece: Any, margin: float = 0.0) -> bool:
    """Is the ground point within the piece's footprint, grown by ``margin`` on every side?"""
    x, z = local_point(point, piece)
    return abs(x) <= piece.size[0] / 2 + margin and abs(z) <= piece.size[1] / 2 + margin


def _crosses_box(origin: Sequence[float], stop: Sequence[float], half: Sequence[float]) -> bool:
    """Does the segment pass through the box of half extents ``half`` centred on the origin of its axes?"""
    low, high = 0.0, 1.0
    for start, end, reach in zip(origin, stop, half):
        delta = end - start
        if abs(delta) < 1e-9:
            if abs(start) > reach:
                return False
            continue
        first, second = (-reach - start) / delta, (reach - start) / delta
        low, high = max(low, min(first, second)), min(high, max(first, second))
        if low > high:
            return False
    # Starting or ending inside the volume is a different problem (someone stands in it), reported elsewhere.
    return high - low > 1e-3 and low > 1e-3 and high < 1 - 1e-3


def _in_piece_axes(point: Sequence[float], piece: Any) -> Vec3:
    """``point`` (x, y, z) in the piece's axes: its ground centre is the origin, y is height above its underside."""
    x, z = local_point((point[0], point[2]), piece)
    return (x, point[1] - piece.elevation_m, z)


def piece_blocks_ray(start: Sequence[float], end: Sequence[float], piece: Any) -> bool:
    """Does the straight line ``start`` → ``end`` (x, y, z) pass through this piece's bounding volume?"""
    height = piece.size[2]
    if height < LOW_PIECE_M and (piece.elevation_m < LOW_PIECE_M or min(piece.size[0], piece.size[1]) < _SMALL_PIECE_M):
        return False
    (x0, y0, z0), (x1, y1, z1) = _in_piece_axes(start, piece), _in_piece_axes(end, piece)
    return _crosses_box(
        (x0, y0 - height / 2, z0), (x1, y1 - height / 2, z1), (piece.size[0] / 2, height / 2, piece.size[1] / 2),
    )


def _part_axes(piece: Any, part: Any) -> tuple[Vec3, Vec3, tuple[Vec3, Vec3, Vec3]]:
    """A part's centre and half extents (x, y, z; metres, in the piece's axes) and the axes it is turned to."""
    width, depth, height = piece.size
    centre = (part.center[0] * width, part.center[1] * height, part.center[2] * depth)
    half = (part.size[0] * width / 2, part.size[2] * height / 2, part.size[1] * depth / 2)
    a, b, c = (math.radians(value) for value in part.rotation)
    (sa, ca), (sb, cb), (sc, cc) = (math.sin(a), math.cos(a)), (math.sin(b), math.cos(b)), (math.sin(c), math.cos(c))
    # The viewport turns a part by x, then y, then z (three.js' default order); these are that turn's columns.
    axes = (
        (cb * cc, ca * sc + sa * sb * cc, sa * sc - ca * sb * cc),
        (-cb * sc, ca * cc - sa * sb * sc, sa * cc + ca * sb * sc),
        (sb, -sa * cb, ca * cb),
    )
    return centre, half, axes


def _in_part_axes(point: Vec3, centre: Vec3, axes: tuple[Vec3, Vec3, Vec3]) -> Vec3:
    offset = (point[0] - centre[0], point[1] - centre[1], point[2] - centre[2])
    return tuple(sum(offset[index] * axis[index] for index in range(3)) for axis in axes)  # type: ignore[return-value]


def piece_blocks_sight(start: Sequence[float], end: Sequence[float], piece: Any) -> bool:
    """Is the line ``start`` → ``end`` (x, y, z) cut by something solid of this piece?

    A piece built from parts (a wall with a doorway, a pavilion on posts) is only as solid as its parts, so a
    lens that looks through the doorway is not blocked; a single-volume piece is its bounding volume.
    """
    parts = getattr(piece, "parts", None)
    if not parts:
        return piece_blocks_ray(start, end, piece)
    origin, stop = _in_piece_axes(start, piece), _in_piece_axes(end, piece)
    for part in parts:
        centre, half, axes = _part_axes(piece, part)
        if half[1] * 2 < LOW_PIECE_M and piece.elevation_m + centre[1] - half[1] < LOW_PIECE_M:
            continue
        if _crosses_box(_in_part_axes(origin, centre, axes), _in_part_axes(stop, centre, axes), half):
            return True
    return False


def piece_holds_point(point: Sequence[float], piece: Any) -> bool:
    """Is ``point`` (x, y, z) inside something solid of this piece (one of its parts when it has them)?"""
    x, y, z = _in_piece_axes(point, piece)
    if not (0.0 <= y <= piece.size[2] and abs(x) <= piece.size[0] / 2 and abs(z) <= piece.size[1] / 2):
        return False
    parts = getattr(piece, "parts", None)
    if not parts:
        return True
    for part in parts:
        centre, half, axes = _part_axes(piece, part)
        local = _in_part_axes((x, y, z), centre, axes)
        if all(abs(local[index]) <= half[index] for index in range(3)):
            return True
    return False


__all__ = [
    "LOW_PIECE_M",
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
    "inside_piece",
    "length",
    "line_positions",
    "local_point",
    "midpoint",
    "normalize_yaw",
    "pair_positions",
    "parse_aspect",
    "piece_blocks_ray",
    "piece_blocks_sight",
    "piece_holds_point",
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

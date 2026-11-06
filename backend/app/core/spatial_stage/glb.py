# -*- coding: utf-8 -*-
"""A set piece as a binary glTF file, written without any 3D library.

A piece built from parts is what the desk draws, the Blender stage renders and, through this, what a person can
take to another tool or put in the element library. Each tone of the piece's colour is one primitive with one
material; the geometry is flat-shaded triangles, as a white model should be.
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Sequence
from typing import Any

from app.core.spatial_stage.models import LandmarkPart, StageLandmark

_SEGMENTS = 16
_RINGS = 10
_TONES = {"": 1.0, "dark": 0.62, "light": 1.28}
_KIND_COLORS = {"prop": "#8d99ae", "furniture": "#a0826d", "architecture": "#b8b2a8", "light": "#f4d03f"}

Matrix = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
Vec = tuple[float, float, float]


def euler_matrix(rotation: Sequence[float]) -> Matrix:
    """three.js XYZ Euler order, degrees: R = Rx·Ry·Rz."""
    rx, ry, rz = (math.radians(float(value)) for value in rotation)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return (
        (cy * cz, -cy * sz, sy),
        (cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy),
        (sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy),
    )


def multiply(a: Matrix, b: Matrix) -> Matrix:
    return tuple(tuple(sum(a[row][k] * b[k][col] for k in range(3)) for col in range(3)) for row in range(3))  # type: ignore[return-value]


def multiply_vector(a: Matrix, v: Sequence[float]) -> Vec:
    return tuple(sum(a[row][col] * v[col] for col in range(3)) for row in range(3))  # type: ignore[return-value]


def tinted(color: str, tone: str) -> str:
    """The piece's colour made darker or lighter for a part, still "#rrggbb"."""
    factor = _TONES.get(tone, 1.0)
    channels = [int(color[index:index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(f"{max(0, min(255, round(value * factor))):02x}" for value in channels)


def _unit_triangles(shape: str) -> list[tuple[Vec, Vec, Vec]]:
    """The shape in a unit cube centred on the origin, counter-clockwise from outside."""
    if shape == "cylinder" or shape == "cone":
        top_radius = 0.5 if shape == "cylinder" else 0.0
        triangles: list[tuple[Vec, Vec, Vec]] = []
        for index in range(_SEGMENTS):
            a, b = 2 * math.pi * index / _SEGMENTS, 2 * math.pi * (index + 1) / _SEGMENTS
            low_a, low_b = (0.5 * math.cos(a), -0.5, 0.5 * math.sin(a)), (0.5 * math.cos(b), -0.5, 0.5 * math.sin(b))
            high_a, high_b = (top_radius * math.cos(a), 0.5, top_radius * math.sin(a)), (top_radius * math.cos(b), 0.5, top_radius * math.sin(b))
            triangles.append((low_a, high_a, low_b))
            if top_radius:
                triangles.append((low_b, high_a, high_b))
                triangles.append(((0.0, 0.5, 0.0), high_b, high_a))
            triangles.append(((0.0, -0.5, 0.0), low_a, low_b))
        return triangles
    if shape == "sphere":
        def point(ring: int, segment: int) -> Vec:
            polar, around = math.pi * ring / _RINGS, 2 * math.pi * segment / _SEGMENTS
            return (0.5 * math.sin(polar) * math.cos(around), 0.5 * math.cos(polar), 0.5 * math.sin(polar) * math.sin(around))

        triangles = []
        for ring in range(_RINGS):
            for segment in range(_SEGMENTS):
                a, b = point(ring, segment), point(ring, segment + 1)
                c, d = point(ring + 1, segment), point(ring + 1, segment + 1)
                if ring:
                    triangles.append((a, b, c))
                if ring < _RINGS - 1:
                    triangles.append((b, d, c))
        return triangles
    if shape == "wedge":
        low = (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, -0.5, -0.5), (-0.5, -0.5, -0.5)
        high = (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5)
        return [
            (low[0], low[1], high[1]), (low[0], high[1], high[0]),  # slope
            (low[3], high[0], high[1]), (low[3], high[1], low[2]),  # back
            (low[0], low[3], low[2]), (low[0], low[2], low[1]),  # bottom
            (low[0], high[0], low[3]), (low[1], low[2], high[1]),  # sides
        ]
    if shape == "plane":
        return [((-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0)), ((-0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0))]
    corners = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
    faces = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    triangles = []
    for a, b, c, d in faces:
        triangles += [(corners[a], corners[b], corners[c]), (corners[a], corners[c], corners[d])]
    return triangles


def _normal(a: Vec, b: Vec, c: Vec) -> Vec:
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(item * item for item in n)) or 1.0
    return (n[0] / length, n[1] / length, n[2] / length)


def _part_triangles(part: LandmarkPart, size: Sequence[float]) -> list[tuple[Vec, Vec, Vec]]:
    width, depth, height = size
    scale = (part.size[0] * width, part.size[2] * height, part.size[1] * depth)
    place = (part.center[0] * width, part.center[1] * height, part.center[2] * depth)
    rotation = euler_matrix(part.rotation)
    placed = []
    for triangle in _unit_triangles(part.shape):
        corners = []
        for vertex in triangle:
            turned = multiply_vector(rotation, (vertex[0] * scale[0], vertex[1] * scale[1], vertex[2] * scale[2]))
            corners.append((turned[0] + place[0], turned[1] + place[1], turned[2] + place[2]))
        placed.append(tuple(corners))
    return placed


def _srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def landmark_glb(piece: StageLandmark) -> bytes:
    """The piece at its real size, standing on y = 0 at the origin with its front towards +Z."""
    parts = piece.parts or [LandmarkPart(shape=piece.shape, center=[0.0, 0.5, 0.0], size=[1.0, 1.0, 1.0])]
    base = piece.color or _KIND_COLORS.get(piece.kind, "#8d99ae")
    by_tone: dict[str, list[tuple[Vec, Vec, Vec]]] = {}
    for part in parts:
        by_tone.setdefault(part.tone, []).extend(_part_triangles(part, piece.size))
    buffer = bytearray()
    views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []
    primitives: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    for index, (tone, triangles) in enumerate(by_tone.items()):
        positions, normals = bytearray(), bytearray()
        lows, highs = [math.inf] * 3, [-math.inf] * 3
        for triangle in triangles:
            normal = _normal(*triangle)
            for vertex in triangle:
                positions += struct.pack("<3f", *vertex)
                normals += struct.pack("<3f", *normal)
                # The accessor bounds are required to be the exact float32 values written.
                single = struct.unpack("<3f", struct.pack("<3f", *vertex))
                for axis in range(3):
                    lows[axis], highs[axis] = min(lows[axis], single[axis]), max(highs[axis], single[axis])
        for data, extra in ((positions, {"min": lows, "max": highs}), (normals, {})):
            views.append({"buffer": 0, "byteOffset": len(buffer), "byteLength": len(data), "target": 34962})
            buffer += data
            accessors.append({
                "bufferView": len(views) - 1, "componentType": 5126, "count": len(triangles) * 3, "type": "VEC3", **extra,
            })
        primitives.append({"attributes": {"POSITION": len(accessors) - 2, "NORMAL": len(accessors) - 1}, "material": index, "mode": 4})
        color = tinted(base, tone)
        linear = [_srgb_to_linear(int(color[at:at + 2], 16) / 255) for at in (1, 3, 5)]
        materials.append({
            "name": tone or "body", "doubleSided": True,
            "pbrMetallicRoughness": {"baseColorFactor": [*linear, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.85},
        })
    document = {
        "asset": {"version": "2.0", "generator": "short-drama director desk"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": piece.name}],
        "meshes": [{"name": piece.name, "primitives": primitives}],
        "materials": materials, "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(buffer)}],
    }
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    buffer += b"\x00" * (-len(buffer) % 4)
    total = 12 + 8 + len(text) + 8 + len(buffer)
    return b"".join((
        struct.pack("<4sII", b"glTF", 2, total),
        struct.pack("<I4s", len(text), b"JSON"), text,
        struct.pack("<I4s", len(buffer), b"BIN\x00"), bytes(buffer),
    ))


__all__ = ["euler_matrix", "landmark_glb", "multiply", "multiply_vector", "tinted"]

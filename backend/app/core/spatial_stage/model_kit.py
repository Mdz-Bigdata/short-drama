# -*- coding: utf-8 -*-
"""Built-in white models, and the reading of a model a text model wrote part by part.

A set piece can be one volume or a stack of them. ``build_kit`` makes the stack for a named thing — a
chair, a sedan, a pavilion — at any size; ``read_parts`` takes a list of volumes in metres from a model
(or a person) and fits them to the piece. Both end in ``LandmarkPart`` rows in fractions of the piece's
size, which is all the desk, the Blender stage and the GLB export need to know.

Ported with attribution from mangfufu/director-desk (MIT, © 2026 DirectorDesk contributors):
``src/assets/catalog/{furniture,architecture,production-props,buildings}.ts`` for the real-world sizes and
names, ``src/assets/furniture/*.ts``, ``vehicles.ts``, ``architecture.ts`` for how each thing is built from
boxes and cylinders. What changed: three.js groups became data rows; the contact anchors, opening doors and
per-part parameters are left out; everything is normalised to the piece's size. Trees, the carriage, the
sword and the other period pieces are this project's own, since its stories are often set in the past.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.spatial_stage.models import MAX_LANDMARK_PARTS, LandmarkPart

_SHAPES = ("box", "cylinder", "sphere", "cone", "wedge", "plane")
_TONES = ("", "dark", "light")
_MIN_SIZE_M = 0.005


class ModelKitError(ValueError):
    """A named kit does not exist, or a list of parts cannot be built."""


@dataclass
class _Parts:
    """Writes volumes in metres, in the same argument order as the upstream builders: width, height, depth, x, y, z."""

    w: float
    d: float
    h: float
    rows: list[dict[str, Any]] = field(default_factory=list)

    def _add(self, shape: str, width: float, height: float, depth: float, x: float, y: float, z: float, tone: str, rot: Sequence[float]) -> None:
        self.rows.append({
            "shape": shape, "center": [x, y, z], "size": [width, depth, height], "rotation": list(rot), "tone": tone,
        })

    def b(self, width: float, height: float, depth: float, x: float = 0.0, y: float | None = None, z: float = 0.0, tone: str = "", rot: Sequence[float] = (0, 0, 0)) -> None:
        self._add("box", width, height, depth, x, height / 2 if y is None else y, z, tone, rot)

    def c(self, radius: float, height: float, x: float = 0.0, y: float | None = None, z: float = 0.0, tone: str = "", rot: Sequence[float] = (0, 0, 0)) -> None:
        self._add("cylinder", radius * 2, height, radius * 2, x, height / 2 if y is None else y, z, tone, rot)

    def s(self, width: float, height: float, depth: float, x: float = 0.0, y: float = 0.0, z: float = 0.0, tone: str = "") -> None:
        self._add("sphere", width, height, depth, x, y, z, tone, (0, 0, 0))

    def cone(self, radius: float, height: float, x: float = 0.0, y: float | None = None, z: float = 0.0, tone: str = "") -> None:
        self._add("cone", radius * 2, height, radius * 2, x, height / 2 if y is None else y, z, tone, (0, 0, 0))

    def wedge(self, width: float, height: float, depth: float, x: float = 0.0, y: float | None = None, z: float = 0.0, tone: str = "", yaw: float = 0.0) -> None:
        self._add("wedge", width, height, depth, x, height / 2 if y is None else y, z, tone, (0, yaw, 0))

    def legs(self, height: float, thick: float, inset: float | None = None, tone: str = "dark") -> None:
        inset = thick if inset is None else inset
        for x in (-self.w / 2 + inset, self.w / 2 - inset):
            for z in (-self.d / 2 + inset, self.d / 2 - inset):
                self.b(thick, height, thick, x, height / 2, z, tone)


Builder = Callable[[_Parts], None]


@dataclass(frozen=True)
class Kit:
    id: str
    name: str
    group: str
    kind: str
    size: tuple[float, float, float]  # width, depth, height in metres
    build: Builder
    aliases: tuple[str, ...] = ()


def _chair(p: _Parts) -> None:
    seat = p.h * 0.5
    p.legs(seat - 0.03, 0.035)
    p.b(p.w, 0.04, p.d, 0, seat - 0.02, 0, "light")
    p.b(p.w, p.h - seat, 0.035, 0, seat + (p.h - seat) / 2, -p.d / 2 + 0.018)


def _stool(p: _Parts) -> None:
    p.legs(p.h - 0.04, 0.03)
    p.c(p.w / 2, 0.04, 0, p.h - 0.02, 0, "light")


def _bench(p: _Parts) -> None:
    p.legs(p.h - 0.05, 0.05, 0.1)
    p.b(p.w, 0.05, p.d, 0, p.h - 0.025, 0, "light")


def _armchair(p: _Parts) -> None:
    seat = p.h * 0.48
    p.legs(seat - 0.05, 0.05)
    p.b(p.w, 0.08, p.d, 0, seat - 0.04, 0, "light")
    p.b(p.w, p.h - seat, 0.08, 0, seat + (p.h - seat) / 2, -p.d / 2 + 0.04)
    for sign in (-1, 1):
        p.b(0.07, 0.22, p.d - 0.08, sign * (p.w / 2 - 0.035), seat + 0.11, 0.04)


def _sofa(p: _Parts) -> None:
    seat = p.h * 0.48
    arm = p.w * 0.09
    back = min(p.d * 0.2, 0.18)
    p.b(p.w - arm * 2, seat * 0.72, p.d - back, 0, seat * 0.36, back / 2, "dark")
    count = max(1, int(p.w / 0.7))
    span = (p.w - arm * 2) / count
    for index in range(count):
        p.b(span - 0.02, seat * 0.28, p.d - back, -p.w / 2 + arm + (index + 0.5) * span, seat * 0.86, back / 2, "light")
    p.b(p.w, p.h, back, 0, p.h / 2, -p.d / 2 + back / 2)
    for sign in (-1, 1):
        p.b(arm, seat + 0.14, p.d, sign * (p.w / 2 - arm / 2), (seat + 0.14) / 2, 0)


def _table(p: _Parts) -> None:
    p.legs(p.h - 0.04, 0.06, 0.07)
    p.b(p.w, 0.04, p.d, 0, p.h - 0.02, 0, "light")


def _round_table(p: _Parts) -> None:
    p.c(p.w * 0.25, 0.04, 0, 0.02, 0, "dark")
    p.c(0.05, p.h - 0.08, 0, (p.h - 0.04) / 2, 0, "dark")
    p.c(p.w / 2, 0.04, 0, p.h - 0.02, 0, "light")


def _desk(p: _Parts) -> None:
    p.b(p.w, 0.04, p.d, 0, p.h - 0.02, 0, "light")
    p.b(p.w * 0.32, p.h - 0.04, p.d - 0.04, p.w / 2 - p.w * 0.16 - 0.01, (p.h - 0.04) / 2, 0)
    p.b(0.04, p.h - 0.04, p.d - 0.04, -p.w / 2 + 0.03, (p.h - 0.04) / 2, 0)
    for index in range(3):
        p.b(p.w * 0.28, (p.h - 0.08) / 3 - 0.02, 0.01, p.w / 2 - p.w * 0.16 - 0.01, 0.04 + (index + 0.5) * (p.h - 0.08) / 3, p.d / 2 - 0.015, "dark")


def _counter(p: _Parts) -> None:
    p.b(p.w, p.h - 0.05, p.d - 0.1, 0, (p.h - 0.05) / 2, -0.03)
    p.b(p.w + 0.06, 0.05, p.d, 0, p.h - 0.025, 0, "light")


def _wardrobe(p: _Parts) -> None:
    p.b(p.w, p.h, p.d, 0, p.h / 2, 0)
    p.b(0.012, p.h - 0.12, 0.012, 0, p.h / 2, p.d / 2 + 0.002, "dark")
    for sign in (-1, 1):
        p.b(0.025, 0.2, 0.025, sign * 0.07, p.h * 0.5, p.d / 2 + 0.015, "dark")


def _shelf(p: _Parts) -> None:
    layers = 5
    for sign in (-1, 1):
        p.b(0.035, p.h, p.d, sign * (p.w / 2 - 0.018), p.h / 2, 0)
    p.b(p.w, p.h, 0.015, 0, p.h / 2, -p.d / 2 + 0.008, "dark")
    for index in range(layers + 1):
        p.b(p.w - 0.05, 0.03, p.d - 0.02, 0, 0.03 + index * (p.h - 0.06) / layers, 0, "light")


def _bed(p: _Parts) -> None:
    surface = p.h * 0.5
    p.b(p.w, surface * 0.55, p.d, 0, surface * 0.275, 0, "dark")
    p.b(p.w - 0.04, surface * 0.45, p.d - 0.08, 0, surface * 0.775, 0.02, "light")
    p.b(p.w, p.h, 0.08, 0, p.h / 2, -p.d / 2 + 0.04)
    p.b(p.w * 0.8, 0.12, 0.42, 0, surface + 0.06, -p.d / 2 + 0.34, "light")


def _nightstand(p: _Parts) -> None:
    p.b(p.w, p.h, p.d, 0, p.h / 2, 0)
    for y in (0.3, 0.72):
        p.b(p.w * 0.84, p.h * 0.32, 0.012, 0, p.h * y, p.d / 2, "light")


def _screen(p: _Parts) -> None:
    panels = 4
    span = p.w / panels
    for index in range(panels):
        yaw = 12 if index % 2 else -12
        p.b(span - 0.03, p.h, 0.03, -p.w / 2 + (index + 0.5) * span, p.h / 2, 0, "" if index % 2 else "light", (0, yaw, 0))


def _coatstand(p: _Parts) -> None:
    p.c(p.w * 0.4, 0.03, 0, 0.015, 0, "dark")
    p.c(0.018, p.h, 0, p.h / 2, 0)
    for yaw in (0, 90, 180, 270):
        rad = math.radians(yaw)
        p.b(0.18, 0.02, 0.02, 0.09 * math.cos(rad), p.h - 0.1, 0.09 * math.sin(rad), "dark", (0, -yaw, 0))


def _cabinet(p: _Parts) -> None:
    p.b(p.w, p.h - 0.03, p.d - 0.02, 0, (p.h - 0.03) / 2, 0)
    p.b(p.w + 0.02, 0.03, p.d, 0, p.h - 0.015, 0, "light")
    for sign in (-1, 1):
        p.b(p.w / 2 - 0.03, p.h - 0.1, 0.012, sign * p.w / 4, (p.h - 0.03) / 2, p.d / 2 - 0.006, "light")


def _fridge(p: _Parts) -> None:
    p.b(p.w, p.h, p.d)
    p.b(p.w - 0.02, 0.012, 0.012, 0, p.h * 0.68, p.d / 2, "dark")
    p.b(0.03, p.h * 0.2, 0.03, p.w * 0.34, p.h * 0.46, p.d / 2 + 0.015, "dark")
    p.b(0.03, p.h * 0.12, 0.03, p.w * 0.34, p.h * 0.83, p.d / 2 + 0.015, "dark")


def _bathtub(p: _Parts) -> None:
    base = 0.08
    p.b(p.w, base, p.d)
    for x in (-p.w / 2 + 0.04, p.w / 2 - 0.04):
        p.b(0.08, p.h - base, p.d, x, (p.h + base) / 2, 0)
    for z in (-p.d / 2 + 0.04, p.d / 2 - 0.04):
        p.b(p.w, p.h - base, 0.08, 0, (p.h + base) / 2, z)


def _toilet(p: _Parts) -> None:
    p.b(p.w * 0.75, p.h * 0.34, p.d * 0.6, 0, p.h * 0.17, p.d * 0.08)
    p.c(p.w * 0.5, 0.04, 0, p.h * 0.5, p.d * 0.08, "light")
    p.b(p.w * 0.9, p.h * 0.5, p.d * 0.25, 0, p.h * 0.75, -p.d * 0.375)


def _monitor(p: _Parts) -> None:
    p.b(p.w * 0.5, 0.02, p.d, 0, 0.01, 0, "dark")
    p.b(0.04, p.h * 0.35, 0.04, 0, p.h * 0.175, 0, "dark")
    p.b(p.w, p.h * 0.72, 0.03, 0, p.h * 0.64, 0, "dark")
    p.b(p.w - 0.03, p.h * 0.72 - 0.03, 0.005, 0, p.h * 0.64, 0.016, "light")


def _lectern(p: _Parts) -> None:
    p.b(p.w * 0.7, p.h - 0.1, p.d * 0.65, 0, (p.h - 0.1) / 2, -0.03)
    p.wedge(p.w, 0.12, p.d, 0, p.h - 0.06, 0, "light", 180)


def _blackboard(p: _Parts) -> None:
    for sign in (-1, 1):
        p.b(0.05, p.h, 0.05, sign * (p.w / 2 - 0.03), p.h / 2, 0)
    p.b(p.w, p.h * 0.62, 0.03, 0, p.h * 0.66, 0, "dark")


def _wall(p: _Parts) -> None:
    p.b(p.w, p.h, p.d)


def _wall_door(p: _Parts) -> None:
    opening, top = min(1.1, p.w * 0.5), min(2.2, p.h * 0.8)
    side = (p.w - opening) / 2
    for sign in (-1, 1):
        p.b(side, p.h, p.d, sign * (p.w + opening) / 4, p.h / 2, 0)
    p.b(opening, p.h - top, p.d, 0, (p.h + top) / 2, 0)


def _wall_window(p: _Parts) -> None:
    opening, sill, top = min(1.5, p.w * 0.5), min(0.9, p.h * 0.32), min(2.2, p.h * 0.78)
    side = (p.w - opening) / 2
    for sign in (-1, 1):
        p.b(side, p.h, p.d, sign * (p.w + opening) / 4, p.h / 2, 0)
    p.b(opening, sill, p.d, 0, sill / 2, 0)
    p.b(opening, p.h - top, p.d, 0, (p.h + top) / 2, 0)


def _door(p: _Parts) -> None:
    frame = 0.08
    for sign in (-1, 1):
        p.b(frame, p.h, p.d, sign * (p.w - frame) / 2, p.h / 2, 0)
    p.b(p.w, frame, p.d, 0, p.h - frame / 2, 0)
    p.b(p.w - frame * 2, p.h - frame, 0.045, 0, (p.h - frame) / 2, 0, "light")
    p.b(0.12, 0.025, 0.06, p.w / 2 - frame - 0.1, p.h * 0.47, 0.03, "dark")


def _window(p: _Parts) -> None:
    frame = 0.07
    for sign in (-1, 1):
        p.b(frame, p.h, p.d, sign * (p.w - frame) / 2, p.h / 2, 0)
    for y in (frame / 2, p.h - frame / 2):
        p.b(p.w, frame, p.d, 0, y, 0)
    p.b(frame * 0.6, p.h - frame * 2, p.d * 0.5, 0, p.h / 2, 0, "light")
    p.b(p.w - frame * 2, frame * 0.6, p.d * 0.5, 0, p.h / 2, 0, "light")


def _column(p: _Parts) -> None:
    base = 0.14
    p.b(p.w * 1.25, base, p.d * 1.25, 0, base / 2, 0, "dark")
    p.c(p.w * 0.45, p.h - base * 2, 0, p.h / 2, 0)
    p.b(p.w * 1.25, base, p.d * 1.25, 0, p.h - base / 2, 0, "dark")


def _stairs(p: _Parts) -> None:
    steps = 10
    rise, tread = p.h / steps, p.d / steps
    for index in range(steps):
        height = rise * (index + 1)
        p.b(p.w, height, tread, 0, height / 2, p.d / 2 - (index + 0.5) * tread, "light" if index % 2 else "")


def _ramp(p: _Parts) -> None:
    p.wedge(p.w, p.h, p.d)


def _railing(p: _Parts) -> None:
    posts = max(2, int(p.w / 0.8) + 1)
    for index in range(posts):
        p.b(0.05, p.h, 0.05, -p.w / 2 + index * p.w / (posts - 1), p.h / 2, 0, "dark")
    for y in (p.h - 0.03, p.h * 0.55):
        p.b(p.w, 0.04, 0.04, 0, y, 0)


def _gable(p: _Parts, base: float, width: float, depth: float, rise: float, tone: str = "dark") -> None:
    for sign, yaw in ((-1, 180), (1, 0)):
        p.wedge(width, rise, depth / 2, 0, base + rise / 2, sign * depth / 4, tone, yaw)


def _storeys(p: _Parts, levels: int, roof: float) -> None:
    body = p.h - roof
    level = body / levels
    p.b(p.w, body, p.d, 0, body / 2, 0)
    for index in range(levels):
        y = (index + 0.55) * level
        for slot in range(3):
            p.b(p.w * 0.16, level * 0.42, 0.04, -p.w / 3 + slot * p.w / 3, y, p.d / 2, "dark")
    p.b(p.w * 0.17, min(2.2, level * 0.8), 0.04, 0, min(1.1, level * 0.4), p.d / 2 + 0.01, "light")


def _bungalow(p: _Parts) -> None:
    _storeys(p, 1, p.h * 0.32)
    _gable(p, p.h * 0.68, p.w * 1.08, p.d * 1.1, p.h * 0.32)


def _house(p: _Parts) -> None:
    _storeys(p, 2, p.h * 0.2)
    _gable(p, p.h * 0.8, p.w * 1.08, p.d * 1.1, p.h * 0.2)


def _apartment(p: _Parts) -> None:
    _storeys(p, 5, p.h * 0.04)
    p.b(p.w + 0.1, p.h * 0.04, p.d + 0.1, 0, p.h * 0.98, 0, "dark")


def _shop(p: _Parts) -> None:
    p.b(p.w, p.h, p.d)
    p.b(p.w * 0.8, p.h * 0.5, 0.04, 0, p.h * 0.38, p.d / 2, "light")
    p.b(p.w, 0.08, 0.9, 0, p.h * 0.72, p.d / 2 + 0.45, "dark", (-12, 0, 0))
    p.b(p.w, p.h * 0.16, 0.06, 0, p.h * 0.88, p.d / 2, "dark")


def _warehouse(p: _Parts) -> None:
    p.b(p.w, p.h * 0.72, p.d, 0, p.h * 0.36, 0)
    p.b(p.w * 0.4, p.h * 0.5, 0.05, 0, p.h * 0.25, p.d / 2, "dark")
    _gable(p, p.h * 0.72, p.w * 1.03, p.d * 1.03, p.h * 0.28)


def _pavilion(p: _Parts) -> None:
    base = p.h * 0.06
    p.b(p.w, base, p.d, 0, base / 2, 0, "light")
    posts = p.h * 0.56
    for x in (-p.w * 0.4, p.w * 0.4):
        for z in (-p.d * 0.4, p.d * 0.4):
            p.c(0.09, posts, x, base + posts / 2, z, "dark")
    p.b(p.w * 0.92, 0.12, p.d * 0.92, 0, base + posts, 0)
    p.cone(p.w * 0.56, p.h - base - posts, 0, base + posts + (p.h - base - posts) / 2, 0, "dark")


def _fortwall(p: _Parts) -> None:
    crest = p.h * 0.84
    p.b(p.w, crest, p.d, 0, crest / 2, 0)
    teeth = max(3, int(p.w / 1.2))
    span = p.w / teeth
    for index in range(teeth):
        p.b(span * 0.55, p.h - crest, p.d * 0.3, -p.w / 2 + (index + 0.5) * span, crest + (p.h - crest) / 2, p.d * 0.35, "dark")


def _tower(p: _Parts) -> None:
    body = p.h * 0.72
    p.b(p.w * 0.84, body, p.d * 0.84, 0, body / 2, 0)
    p.b(p.w, p.h * 0.05, p.d, 0, body, 0, "dark")
    p.b(p.w * 0.7, p.h * 0.12, p.d * 0.7, 0, body + p.h * 0.085, 0)
    p.cone(p.w * 0.5, p.h * 0.14, 0, p.h * 0.93, 0, "dark")


def _wheels(p: _Parts, radius: float, x: float, zs: Sequence[float], width: float = 0.1) -> None:
    for sign in (-1, 1):
        for z in zs:
            p.c(radius, width, sign * x, radius, z, "dark", (0, 0, 90))


def _car(p: _Parts, cabin: float, cabin_z: float, floor_ratio: float = 0.28) -> None:
    wheel = p.h * 0.22
    floor = p.h * floor_ratio
    p.b(p.w * 0.95, p.h * 0.28, p.d, 0, floor + p.h * 0.14, 0)
    roof = p.h - floor - p.h * 0.28
    p.b(p.w * 0.84, roof * 0.9, p.d * cabin, 0, floor + p.h * 0.28 + roof * 0.45, cabin_z, "light")
    p.b(p.w * 0.86, roof * 0.1, p.d * cabin, 0, p.h - roof * 0.05, cabin_z)
    _wheels(p, wheel, p.w * 0.44, (-p.d * 0.3, p.d * 0.3), p.w * 0.11)


def _sedan(p: _Parts) -> None:
    _car(p, 0.5, -0.03 * p.d)


def _suv(p: _Parts) -> None:
    _car(p, 0.66, -0.06 * p.d, 0.26)


def _van(p: _Parts) -> None:
    _car(p, 0.82, -0.02 * p.d, 0.22)


def _bus(p: _Parts) -> None:
    wheel = p.h * 0.15
    p.b(p.w, p.h * 0.84, p.d, 0, wheel + p.h * 0.42 - 0.05, 0)
    p.b(p.w + 0.02, p.h * 0.28, p.d * 0.94, 0, p.h * 0.62, 0, "light")
    _wheels(p, wheel, p.w * 0.44, (-p.d * 0.3, p.d * 0.32), 0.25)


def _truck(p: _Parts) -> None:
    wheel = p.h * 0.17
    floor = wheel * 1.5
    p.b(p.w * 0.95, p.h * 0.1, p.d, 0, floor, 0, "dark")
    p.b(p.w, p.h * 0.5, p.d * 0.62, 0, floor + p.h * 0.3, -p.d * 0.18)
    p.b(p.w * 0.94, p.h * 0.56, p.d * 0.26, 0, floor + p.h * 0.33, p.d * 0.36, "light")
    _wheels(p, wheel, p.w * 0.44, (-p.d * 0.32, -p.d * 0.12, p.d * 0.34), 0.28)


def _two_wheels(p: _Parts, motor: bool) -> None:
    radius = p.h * 0.28
    rear, front, crank, saddle = p.d * -0.3, p.d * 0.3, p.d * -0.04, p.d * -0.13
    for z in (rear, front):
        p.c(radius, 0.06, 0, radius, z, "dark", (0, 0, 90))
    length = front - rear
    p.b(0.05, 0.05, length * 0.72, 0, p.h * 0.56, (rear + front) / 2, "", (-8, 0, 0))
    p.b(0.04, p.h * 0.42, 0.04, 0, p.h * 0.48, crank)
    p.b(0.04, p.h * 0.72, 0.04, 0, p.h * 0.62, front - 0.04, "", (-12, 0, 0))
    p.b(p.w * 0.9, 0.04, 0.04, 0, p.h * 0.95, front - 0.1)
    p.b(0.24, 0.05, 0.3, 0, p.h * 0.7, saddle, "dark")
    if motor:
        p.b(0.32, p.h * 0.24, p.d * 0.22, 0, p.h * 0.42, 0, "dark")
        p.s(0.3, p.h * 0.18, p.d * 0.22, 0, p.h * 0.72, p.d * 0.06)


def _bicycle(p: _Parts) -> None:
    _two_wheels(p, False)


def _motorcycle(p: _Parts) -> None:
    _two_wheels(p, True)


def _boat(p: _Parts) -> None:
    p.b(p.w, p.h * 0.1, p.d * 0.8, 0, p.h * 0.05, -p.d * 0.05, "dark")
    for sign in (-1, 1):
        p.b(0.06, p.h * 0.8, p.d * 0.78, sign * (p.w / 2 - 0.03), p.h * 0.45, -p.d * 0.05)
        p.b(0.06, p.h * 0.8, p.d * 0.36, sign * p.w * 0.25, p.h * 0.45, p.d * 0.33, "", (0, sign * -36, 0))
    p.b(p.w, p.h * 0.8, 0.06, 0, p.h * 0.45, -p.d * 0.44)
    for z in (-p.d * 0.2, p.d * 0.1):
        p.b(p.w * 0.9, 0.05, 0.22, 0, p.h * 0.55, z, "light")


def _carriage(p: _Parts) -> None:
    wheel = p.h * 0.28
    floor = wheel * 1.1
    body = p.h * 0.5
    p.b(p.w * 0.9, 0.08, p.d * 0.62, 0, floor, -p.d * 0.1, "dark")
    p.b(p.w * 0.86, body, p.d * 0.58, 0, floor + body / 2 + 0.04, -p.d * 0.1)
    _gable(p, floor + body + 0.04, p.w, p.d * 0.66, p.h - floor - body - 0.04)
    _wheels(p, wheel, p.w * 0.5, (-p.d * 0.1,), 0.07)
    for sign in (-1, 1):
        p.b(0.05, 0.05, p.d * 0.46, sign * p.w * 0.28, floor, p.d * 0.27, "dark")


def _throne(p: _Parts) -> None:
    seat = p.h * 0.3
    p.b(p.w, p.h * 0.08, p.d, 0, p.h * 0.04, 0, "dark")
    p.b(p.w * 0.72, seat, p.d * 0.72, 0, p.h * 0.08 + seat / 2, 0)
    p.b(p.w * 0.76, p.h * 0.92, p.d * 0.12, 0, p.h * 0.54, -p.d * 0.34, "light")
    for sign in (-1, 1):
        p.b(p.w * 0.12, p.h * 0.28, p.d * 0.72, sign * p.w * 0.42, p.h * 0.08 + seat + p.h * 0.02, 0)


def _altar(p: _Parts) -> None:
    for index in range(3):
        scale = 1 - index * 0.2
        p.b(p.w * scale, p.h / 3, p.d * scale, 0, (index + 0.5) * p.h / 3, 0, "light" if index % 2 else "")


def _tent(p: _Parts) -> None:
    _gable(p, 0.0, p.w, p.d, p.h, "")
    p.b(p.w * 0.3, p.h * 0.6, 0.02, 0, p.h * 0.3, p.d * 0.49, "dark")


def _stall(p: _Parts) -> None:
    table = p.h * 0.38
    p.b(p.w, table, p.d * 0.7, 0, table / 2, 0, "light")
    for x in (-p.w * 0.46, p.w * 0.46):
        for z in (-p.d * 0.42, p.d * 0.42):
            p.b(0.06, p.h * 0.88, 0.06, x, p.h * 0.44, z, "dark")
    p.b(p.w * 1.04, 0.06, p.d * 1.1, 0, p.h * 0.94, 0, "", (8, 0, 0))


def _flagpole(p: _Parts) -> None:
    p.c(0.05, p.h, -p.w * 0.4, p.h / 2, 0, "dark")
    p.b(p.w * 0.8, p.h * 0.26, 0.015, 0, p.h * 0.85, 0)


def _weapon_rack(p: _Parts) -> None:
    for sign in (-1, 1):
        p.b(0.08, p.h, p.d * 0.4, sign * (p.w / 2 - 0.04), p.h / 2, 0, "dark")
    for y in (0.3, 0.72):
        p.b(p.w, 0.05, 0.05, 0, p.h * y, 0.08, "dark")
    for index in range(5):
        p.b(0.04, p.h * 0.9, 0.03, -p.w * 0.36 + index * p.w * 0.18, p.h * 0.5, 0.11, "light")


def _ring(p: _Parts) -> None:
    deck = p.h * 0.45
    p.b(p.w, deck, p.d, 0, deck / 2, 0)
    for x in (-p.w * 0.47, p.w * 0.47):
        for z in (-p.d * 0.47, p.d * 0.47):
            p.c(0.08, p.h - deck, x, deck + (p.h - deck) / 2, z, "dark")
    for y in (deck + (p.h - deck) * 0.4, deck + (p.h - deck) * 0.85):
        for sign in (-1, 1):
            p.b(p.w * 0.94, 0.03, 0.03, 0, y, sign * p.d * 0.47, "light")
            p.b(0.03, 0.03, p.d * 0.94, sign * p.w * 0.47, y, 0, "light")


def _container(p: _Parts) -> None:
    p.b(p.w, p.h, p.d)
    ribs = 8
    for index in range(ribs):
        z = -p.d / 2 + (index + 0.5) * p.d / ribs
        for sign in (-1, 1):
            p.b(0.03, p.h * 0.92, p.d / ribs * 0.4, sign * p.w / 2, p.h / 2, z, "dark")


def _pallet(p: _Parts) -> None:
    for x in (-p.w * 0.4, 0, p.w * 0.4):
        p.b(0.1, p.h * 0.6, p.d, x, p.h * 0.3, 0, "dark")
    for index in range(5):
        p.b(p.w, p.h * 0.28, p.d / 7, 0, p.h * 0.86, -p.d * 0.4 + index * p.d * 0.2)


def _barrel(p: _Parts) -> None:
    p.c(p.w / 2, p.h, 0, p.h / 2, 0)
    for y in (0.3, 0.7):
        p.c(p.w / 2 + 0.008, 0.03, 0, p.h * y, 0, "dark")


def _scaffold(p: _Parts) -> None:
    levels = 3
    for x in (-p.w / 2, p.w / 2):
        for z in (-p.d / 2, p.d / 2):
            p.c(0.03, p.h, x, p.h / 2, z, "dark")
    for index in range(1, levels + 1):
        p.b(p.w, 0.05, p.d, 0, index * p.h / levels - 0.03, 0, "light")


def _handcart(p: _Parts) -> None:
    radius = p.h * 0.22
    p.b(p.w, p.h * 0.32, p.d * 0.62, 0, radius + p.h * 0.2, -p.d * 0.1)
    _wheels(p, radius, p.w * 0.5, (-p.d * 0.1,), 0.06)
    for sign in (-1, 1):
        p.b(0.04, 0.04, p.d * 0.5, sign * p.w * 0.4, radius + p.h * 0.1, p.d * 0.3, "dark")
        p.b(0.04, p.h - radius - p.h * 0.1, 0.04, sign * p.w * 0.4, (p.h + radius + p.h * 0.1) / 2, p.d * 0.52, "dark")


def _cone(p: _Parts) -> None:
    p.b(p.w, p.h * 0.06, p.d, 0, p.h * 0.03, 0, "dark")
    p.cone(p.w * 0.36, p.h * 0.94, 0, p.h * 0.53, 0)


def _tree(p: _Parts) -> None:
    trunk = p.h * 0.42
    p.c(p.w * 0.06, trunk, 0, trunk / 2, 0, "dark")
    p.s(p.w, p.h * 0.5, p.d, 0, p.h * 0.68, 0)
    p.s(p.w * 0.66, p.h * 0.34, p.d * 0.66, p.w * 0.2, p.h * 0.5, p.d * 0.1, "light")


def _pine(p: _Parts) -> None:
    trunk = p.h * 0.18
    p.c(p.w * 0.06, trunk, 0, trunk / 2, 0, "dark")
    for index, scale in enumerate((1.0, 0.76, 0.5)):
        height = p.h * 0.38
        p.cone(p.w / 2 * scale, height, 0, trunk + index * p.h * 0.24 + height / 2, 0)


def _bush(p: _Parts) -> None:
    p.s(p.w * 0.8, p.h, p.d * 0.8, 0, p.h / 2, 0)
    p.s(p.w * 0.5, p.h * 0.7, p.d * 0.5, p.w * 0.25, p.h * 0.35, p.d * 0.1, "light")
    p.s(p.w * 0.5, p.h * 0.7, p.d * 0.5, -p.w * 0.25, p.h * 0.35, -p.d * 0.1, "dark")


def _rock(p: _Parts) -> None:
    p.s(p.w, p.h, p.d, 0, p.h * 0.5, 0)
    p.s(p.w * 0.5, p.h * 0.6, p.d * 0.55, p.w * 0.25, p.h * 0.3, p.d * 0.15, "dark")


def _lamp(p: _Parts) -> None:
    p.c(0.12, 0.08, 0, 0.04, 0, "dark")
    p.c(0.045, p.h, 0, p.h / 2, 0, "dark")
    p.b(p.w, 0.05, 0.06, p.w / 2 - 0.03, p.h - 0.03, 0, "dark")
    p.b(0.32, 0.08, 0.16, p.w - 0.1, p.h - 0.08, 0, "light")


def _lantern(p: _Parts) -> None:
    p.b(p.w * 1.1, p.h * 0.08, p.d * 1.1, 0, p.h * 0.04, 0, "dark")
    p.c(p.w / 2, p.h * 0.84, 0, p.h / 2, 0, "light")
    p.b(p.w * 1.1, p.h * 0.08, p.d * 1.1, 0, p.h * 0.96, 0, "dark")


def _crate(p: _Parts) -> None:
    p.b(p.w, p.h, p.d)
    for y in (0.06, 0.94):
        p.b(p.w + 0.01, p.h * 0.1, p.d + 0.01, 0, p.h * y, 0, "dark")


def _well(p: _Parts) -> None:
    rim = p.h * 0.32
    p.c(p.w * 0.42, rim, 0, rim / 2, 0)
    for sign in (-1, 1):
        p.b(0.08, p.h * 0.7, 0.08, sign * p.w * 0.38, rim + p.h * 0.3, 0, "dark")
    _gable(p, p.h * 0.82, p.w, p.d * 0.9, p.h * 0.18)


def _sword(p: _Parts) -> None:
    grip = p.h * 0.2
    p.c(0.016, grip, 0, grip / 2, 0, "dark")
    p.b(p.w, 0.025, 0.04, 0, grip, 0, "dark")
    p.b(0.045, p.h - grip, 0.008, 0, grip + (p.h - grip) / 2, 0, "light")


def _phone(p: _Parts) -> None:
    p.b(p.w, p.h, p.d, 0, p.h / 2, 0, "dark")
    p.b(p.w * 0.9, p.h * 0.92, 0.002, 0, p.h / 2, p.d / 2, "light")


def _suitcase(p: _Parts) -> None:
    body = p.h * 0.82
    p.b(p.w, body, p.d, 0, body / 2, 0)
    p.b(p.w * 0.3, p.h * 0.12, 0.03, 0, p.h * 0.94, 0, "dark")


_K = Kit
KITS: tuple[Kit, ...] = (
    # 座具
    _K("chair", "餐椅", "座具", "furniture", (0.48, 0.5, 0.9), _chair, ("椅子", "木椅", "chair")),
    _K("stool", "凳子", "座具", "furniture", (0.38, 0.38, 0.44), _stool, ("板凳", "圆凳", "stool")),
    _K("bench", "长凳", "座具", "furniture", (1.6, 0.43, 0.46), _bench, ("长椅", "bench")),
    _K("armchair", "扶手椅", "座具", "furniture", (0.65, 0.62, 0.93), _armchair, ("太师椅", "armchair")),
    _K("sofa", "沙发", "座具", "furniture", (2.2, 0.9, 0.9), _sofa, ("sofa", "couch")),
    # 桌台柜架
    _K("table", "方桌", "桌台柜架", "furniture", (1.4, 0.85, 0.76), _table, ("桌子", "餐桌", "长桌", "table")),
    _K("round-table", "圆桌", "桌台柜架", "furniture", (1.2, 1.2, 0.75), _round_table, ("round table",)),
    _K("desk", "书桌", "桌台柜架", "furniture", (1.3, 0.65, 0.75), _desk, ("书案", "办公桌", "案几", "desk")),
    _K("coffee-table", "茶几", "桌台柜架", "furniture", (1.05, 0.6, 0.42), _table, ("茶桌", "coffee table")),
    _K("counter", "吧台", "桌台柜架", "furniture", (2.0, 0.65, 1.08), _counter, ("柜台", "前台", "收银台", "counter")),
    _K("wardrobe", "衣柜", "桌台柜架", "furniture", (1.5, 0.58, 2.1), _wardrobe, ("立柜", "wardrobe")),
    _K("bookshelf", "书架", "桌台柜架", "furniture", (0.9, 0.32, 1.9), _shelf, ("书柜", "货架", "shelf")),
    _K("cabinet", "橱柜", "桌台柜架", "furniture", (1.2, 0.6, 0.88), _cabinet, ("矮柜", "cabinet")),
    # 卧室与厨卫
    _K("bed", "床", "卧室厨卫", "furniture", (1.8, 2.1, 1.05), _bed, ("双人床", "病床", "bed")),
    _K("nightstand", "床头柜", "卧室厨卫", "furniture", (0.48, 0.42, 0.55), _nightstand, ("nightstand",)),
    _K("folding-screen", "屏风", "卧室厨卫", "furniture", (1.8, 0.12, 1.8), _screen, ("隔断", "screen")),
    _K("coatstand", "衣帽架", "卧室厨卫", "furniture", (0.6, 0.5, 1.75), _coatstand, ("衣架",)),
    _K("fridge", "冰箱", "卧室厨卫", "furniture", (0.72, 0.7, 1.8), _fridge, ("fridge",)),
    _K("bathtub", "浴缸", "卧室厨卫", "furniture", (0.8, 1.7, 0.58), _bathtub, ("浴桶", "bathtub")),
    _K("toilet", "马桶", "卧室厨卫", "furniture", (0.42, 0.7, 0.82), _toilet, ("toilet",)),
    # 公共设施
    _K("monitor", "显示器", "公共设施", "prop", (0.55, 0.2, 0.42), _monitor, ("电脑", "monitor")),
    _K("lectern", "讲台", "公共设施", "furniture", (0.8, 0.55, 1.1), _lectern, ("演讲台", "lectern")),
    _K("blackboard", "黑板", "公共设施", "furniture", (2.0, 0.05, 1.8), _blackboard, ("白板", "blackboard")),
    # 建筑构件
    _K("wall", "墙", "建筑构件", "architecture", (4.0, 0.18, 3.0), _wall, ("墙面", "wall")),
    _K("wall-door", "带门洞的墙", "建筑构件", "architecture", (4.0, 0.18, 3.0), _wall_door, ("门洞",)),
    _K("wall-window", "带窗洞的墙", "建筑构件", "architecture", (4.0, 0.18, 3.0), _wall_window, ("窗洞",)),
    _K("door", "门", "建筑构件", "architecture", (1.1, 0.18, 2.2), _door, ("房门", "door")),
    _K("window", "窗", "建筑构件", "architecture", (1.5, 0.16, 1.2), _window, ("窗户", "window")),
    _K("column", "立柱", "建筑构件", "architecture", (0.4, 0.4, 3.0), _column, ("柱子", "廊柱", "column")),
    _K("slab", "楼板", "建筑构件", "architecture", (4.0, 4.0, 0.18), _wall, ("地台", "平台", "slab")),
    _K("stairs", "楼梯", "建筑构件", "architecture", (1.2, 2.8, 1.8), _stairs, ("台阶", "stairs")),
    _K("ramp", "坡道", "建筑构件", "architecture", (1.2, 3.0, 0.6), _ramp, ("斜坡", "ramp")),
    _K("railing", "栏杆", "建筑构件", "architecture", (3.0, 0.08, 1.05), _railing, ("护栏", "railing")),
    # 建筑
    _K("bungalow", "平房", "建筑", "architecture", (6.0, 5.0, 4.4), _bungalow, ("小屋", "瓦房", "bungalow")),
    _K("house", "两层住宅", "建筑", "architecture", (7.0, 6.0, 7.5), _house, ("民居", "住宅", "house")),
    _K("apartment", "公寓楼", "建筑", "architecture", (10.0, 8.0, 15.6), _apartment, ("居民楼", "写字楼", "apartment")),
    _K("shop", "商铺", "建筑", "architecture", (5.0, 6.0, 3.6), _shop, ("店铺", "铺子", "shop")),
    _K("warehouse", "仓库", "建筑", "architecture", (12.0, 8.0, 6.0), _warehouse, ("厂房", "warehouse")),
    _K("pavilion", "亭子", "建筑", "architecture", (4.0, 4.0, 4.2), _pavilion, ("凉亭", "pavilion")),
    _K("fortwall", "城墙", "建筑", "architecture", (10.0, 2.5, 4.0), _fortwall, ("宫墙", "fort wall")),
    _K("tower", "塔楼", "建筑", "architecture", (4.0, 4.0, 12.0), _tower, ("角楼", "瞭望塔", "tower")),
    # 车船
    _K("sedan", "轿车", "车船", "furniture", (1.8, 4.5, 1.45), _sedan, ("汽车", "小汽车", "sedan", "car")),
    _K("suv", "SUV", "车船", "furniture", (1.95, 4.8, 1.8), _suv, ("越野车", "suv")),
    _K("van", "面包车", "车船", "furniture", (1.8, 4.6, 2.0), _van, ("van",)),
    _K("bus", "公交车", "车船", "furniture", (2.5, 10.0, 3.1), _bus, ("大巴", "bus")),
    _K("truck", "卡车", "车船", "furniture", (2.5, 7.0, 3.2), _truck, ("货车", "truck")),
    _K("bicycle", "自行车", "车船", "prop", (0.6, 1.8, 1.1), _bicycle, ("单车", "bicycle")),
    _K("motorcycle", "摩托车", "车船", "prop", (0.8, 2.1, 1.3), _motorcycle, ("电动车", "motorcycle")),
    _K("boat", "小船", "车船", "furniture", (1.5, 3.6, 0.8), _boat, ("木船", "boat")),
    _K("carriage", "马车", "车船", "furniture", (1.6, 3.8, 2.3), _carriage, ("轿子", "carriage")),
    # 古装与场面
    _K("throne", "宝座", "场面", "furniture", (1.1, 0.9, 1.8), _throne, ("龙椅", "王座", "throne")),
    _K("altar", "祭坛", "场面", "architecture", (3.0, 2.4, 1.3), _altar, ("法坛", "altar")),
    _K("tent", "帐篷", "场面", "architecture", (3.0, 4.0, 2.5), _tent, ("营帐", "tent")),
    _K("stall", "摊位", "场面", "furniture", (2.0, 1.2, 2.4), _stall, ("小摊", "货摊", "stall")),
    _K("flagpole", "旗杆", "场面", "prop", (1.2, 0.1, 4.0), _flagpole, ("旗帜", "flag")),
    _K("weapon-rack", "兵器架", "场面", "furniture", (1.8, 0.25, 1.8), _weapon_rack, ("武器架",)),
    _K("ring", "擂台", "场面", "architecture", (5.0, 5.0, 1.6), _ring, ("拳台", "ring")),
    _K("well", "水井", "场面", "architecture", (1.4, 1.4, 2.4), _well, ("古井", "well")),
    # 工业
    _K("container", "集装箱", "工业", "architecture", (2.44, 6.06, 2.59), _container, ("container",)),
    _K("pallet", "托盘", "工业", "prop", (1.2, 1.0, 0.15), _pallet, ("pallet",)),
    _K("barrel", "油桶", "工业", "prop", (0.6, 0.6, 0.9), _barrel, ("木桶", "酒坛", "barrel")),
    _K("scaffold", "脚手架", "工业", "architecture", (2.0, 1.2, 6.0), _scaffold, ("scaffold",)),
    _K("handcart", "手推车", "工业", "prop", (0.7, 1.2, 1.1), _handcart, ("板车", "handcart")),
    _K("traffic-cone", "路锥", "工业", "prop", (0.4, 0.4, 0.7), _cone, ("cone",)),
    _K("crate", "木箱", "工业", "prop", (0.8, 0.8, 0.8), _crate, ("箱子", "crate")),
    # 环境
    _K("tree", "树", "环境", "prop", (3.0, 3.0, 6.0), _tree, ("大树", "tree")),
    _K("pine", "松树", "环境", "prop", (2.6, 2.6, 7.0), _pine, ("柏树", "pine")),
    _K("bush", "灌木", "环境", "prop", (1.4, 1.4, 1.0), _bush, ("草丛", "bush")),
    _K("rock", "岩石", "环境", "prop", (1.6, 1.2, 1.0), _rock, ("石头", "假山", "rock")),
    _K("street-lamp", "路灯", "环境", "light", (1.4, 0.3, 4.5), _lamp, ("街灯", "street lamp")),
    _K("lantern", "灯笼", "环境", "light", (0.4, 0.4, 0.55), _lantern, ("宫灯", "lantern")),
    # 手持道具
    _K("sword", "长剑", "手持道具", "prop", (0.18, 0.05, 1.05), _sword, ("剑", "刀", "sword")),
    _K("phone", "手机", "手持道具", "prop", (0.075, 0.009, 0.16), _phone, ("phone",)),
    _K("suitcase", "行李箱", "手持道具", "prop", (0.45, 0.25, 0.75), _suitcase, ("箱包", "suitcase")),
)
_BY_ID = {kit.id: kit for kit in KITS}


def find_kit(text: Any) -> Kit | None:
    """The kit a name refers to: its id, its Chinese name, or an alias; longest match inside a phrase wins."""
    wanted = str(text or "").strip().lower()
    if not wanted:
        return None
    if wanted in _BY_ID:
        return _BY_ID[wanted]
    best: tuple[int, Kit] | None = None
    for kit in KITS:
        for word in (kit.name, *kit.aliases):
            word = word.lower()
            if word == wanted:
                return kit
            if word in wanted and (best is None or len(word) > best[0]):
                best = (len(word), kit)
    return best[1] if best else None


def _rotated_half_extents(size: Sequence[float], rotation: Sequence[float]) -> tuple[float, float, float]:
    """Half extents along x, y, z of a volume after its rotation; ``size`` is [width, depth, height]."""
    half = (size[0] / 2, size[2] / 2, size[1] / 2)
    rx, ry, rz = (math.radians(float(value)) for value in rotation)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    # three.js XYZ Euler order: R = Rx·Ry·Rz.
    matrix = (
        (cy * cz, -cy * sz, sy),
        (cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy),
        (sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy),
    )
    return tuple(sum(abs(matrix[row][col]) * half[col] for col in range(3)) for row in range(3))  # type: ignore[return-value]


def _normalise(rows: Sequence[Mapping[str, Any]], size: Sequence[float] | None) -> tuple[list[LandmarkPart], list[float]]:
    """Centre the volumes on the ground and turn metres into fractions of ``size`` (or of their own bounds)."""
    lows, highs = [math.inf] * 3, [-math.inf] * 3
    for row in rows:
        extents = _rotated_half_extents(row["size"], row["rotation"])
        for axis in range(3):
            lows[axis] = min(lows[axis], row["center"][axis] - extents[axis])
            highs[axis] = max(highs[axis], row["center"][axis] + extents[axis])
    bounds = [max(_MIN_SIZE_M, highs[axis] - lows[axis]) for axis in range(3)]  # x, y, z
    natural = [round(bounds[0], 3), round(bounds[2], 3), round(bounds[1], 3)]  # width, depth, height
    middle = ((lows[0] + highs[0]) / 2, lows[1], (lows[2] + highs[2]) / 2)
    parts = [
        LandmarkPart(
            shape=row["shape"],
            center=[
                round((row["center"][0] - middle[0]) / bounds[0], 4),
                round((row["center"][1] - middle[1]) / bounds[1], 4),
                round((row["center"][2] - middle[2]) / bounds[2], 4),
            ],
            size=[
                round(min(4.0, max(1e-4, row["size"][0] / bounds[0])), 4),
                round(min(4.0, max(1e-4, row["size"][1] / bounds[2])), 4),
                round(min(4.0, max(1e-4, row["size"][2] / bounds[1])), 4),
            ],
            rotation=[round(float(value), 2) for value in row["rotation"]],
            tone=row["tone"],
        )
        for row in rows
    ]
    return parts, [float(item) for item in (size if size is not None else natural)]


def build_kit(name: Any, size: Sequence[float] | None = None) -> tuple[Kit, list[LandmarkPart], list[float]]:
    """The parts of a built-in model, built at ``size`` ([width, depth, height] metres) or at its real size."""
    kit = find_kit(name)
    if kit is None:
        raise ModelKitError(f"模型库里没有「{str(name)[:40]}」，可用：{'、'.join(item.name for item in KITS)}")
    width, depth, height = (float(value) for value in (size if size is not None else kit.size))
    if min(width, depth, height) <= 0:
        raise ModelKitError("模型尺寸必须大于 0")
    parts = _Parts(w=width, d=depth, h=height)
    kit.build(parts)
    # The bounds of what was built, not the size asked for: fitting one to the other would squash a wheel out of round.
    built, overall = _normalise(parts.rows[:MAX_LANDMARK_PARTS], None)
    return kit, built, overall


def _number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("not finite")
    return number


def read_parts(rows: Any, size: Sequence[float] | None = None) -> tuple[list[LandmarkPart], list[float], int]:
    """A model's own list of volumes in metres: ``{shape, center:[x,y,z], size:[宽,深,高], rotation?, tone?}``.

    A row that cannot be read costs that row, since models write these lists long. Returns the parts,
    the piece's overall size, and how many rows were dropped.
    """
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise ModelKitError("parts 必须是非空的体块列表")
    clean: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        try:
            shape = str(row.get("shape") or "box")
            center = [_number(item) for item in row["center"]]
            measure = [abs(_number(item)) for item in row["size"]]
            rotation = [_number(item) for item in (row.get("rotation") or (0, 0, 0))]
            tone = str(row.get("tone") or "")
            if shape not in _SHAPES or len(center) != 3 or len(measure) != 3 or len(rotation) != 3 or tone not in _TONES:
                raise ValueError("bad row")
            if min(measure) <= 0 or max(map(abs, center)) > 500 or max(measure) > 200:
                raise ValueError("out of range")
        except (AttributeError, KeyError, IndexError, TypeError, ValueError):
            dropped += 1
            continue
        clean.append({"shape": shape, "center": center, "size": measure, "rotation": rotation, "tone": tone})
    if not clean:
        raise ModelKitError("parts 里没有可用的体块（需要 center:[x,y,z]、size:[宽,深,高]）")
    dropped += max(0, len(clean) - MAX_LANDMARK_PARTS)
    parts, overall = _normalise(clean[:MAX_LANDMARK_PARTS], size)
    return parts, overall, dropped


def catalog() -> list[dict[str, Any]]:
    """What the desk's model library lists; the parts are built when one is placed."""
    return [
        {"id": kit.id, "name": kit.name, "group": kit.group, "kind": kit.kind, "size": list(kit.size), "aliases": list(kit.aliases)}
        for kit in KITS
    ]


def catalog_text() -> str:
    """The library in one line per group, for a prompt."""
    groups: dict[str, list[str]] = {}
    for kit in KITS:
        groups.setdefault(kit.group, []).append(f"{kit.id}({kit.name} {kit.size[0]:g}×{kit.size[1]:g}×{kit.size[2]:g})")
    return "\n".join(f"- {group}：{'、'.join(items)}" for group, items in groups.items())


__all__ = ["KITS", "Kit", "ModelKitError", "build_kit", "catalog", "catalog_text", "find_kit", "read_parts"]

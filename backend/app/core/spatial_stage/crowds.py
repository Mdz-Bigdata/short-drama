# -*- coding: utf-8 -*-
"""A crowd array: a centred rows × columns grid of stand-ins with repeatable per-member variation.

The variation comes from mulberry32 — the 32-bit generator browsers commonly carry — seeded per
member with ``seed + index``, so the desk can preview the very same crowd before the server has
answered, and the same ``seed`` always yields the same crowd. Each member draws four numbers, in
this order: sideways offset, depth offset, turn, height.
"""

from __future__ import annotations

from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import StageActor, StageCrowd

POSITION_JITTER = 0.18   # of the spacing, either way, along each grid direction
YAW_JITTER_DEG = 12.0
HEIGHT_JITTER = 0.04
BASE_HEIGHT_M = 1.7
_MASK = 0xFFFFFFFF


def mulberry32(seed: int):
    """The mulberry32 generator: successive floats in ``[0, 1)``."""
    state = seed & _MASK

    def draw() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & _MASK
        value = state
        value = ((value ^ (value >> 15)) * (value | 1)) & _MASK
        value ^= (value + (((value ^ (value >> 7)) * (value | 61)) & _MASK)) & _MASK
        return ((value ^ (value >> 14)) & _MASK) / 4294967296

    return draw


def member_name(label: str, index: int) -> str:
    return f"{label}-{index + 1:02d}"


def members(crowd: StageCrowd) -> list[StageActor]:
    """The people of ``crowd``, front row first, each row from the array's left to its right."""
    forward = geo.forward_of(crowd.yaw_deg)
    right = geo.right_of(forward)
    people: list[StageActor] = []
    for index in range(crowd.rows * crowd.columns):
        row, column = divmod(index, crowd.columns)
        draw = mulberry32(crowd.seed + index)
        along = (column - (crowd.columns - 1) / 2 + (draw() * 2 - 1) * POSITION_JITTER) * crowd.spacing
        back = (row - (crowd.rows - 1) / 2 + (draw() * 2 - 1) * POSITION_JITTER) * crowd.spacing
        turn = (draw() * 2 - 1) * YAW_JITTER_DEG
        height = BASE_HEIGHT_M * (1 + (draw() * 2 - 1) * HEIGHT_JITTER)
        spot = geo.add((crowd.center[0], crowd.center[1]), geo.add(geo.scale(right, along), geo.scale(forward, -back)))
        people.append(StageActor(
            id=f"{crowd.id}-{index + 1:03d}", name=member_name(crowd.label, index), position=geo.rounded(spot),
            yaw_deg=geo.normalize_yaw(crowd.yaw_deg + turn), height_m=round(height, 3), role="crowd",
            body_type=crowd.body_type, crowd_id=crowd.id,
        ))
    return people


def moved(actor: StageActor, before: StageCrowd, after: StageCrowd) -> StageActor:
    """``actor`` carried along when its crowd goes from ``before`` to ``after``: a rigid move plus a
    re-spacing about the centre, so a member someone nudged by hand keeps its nudge."""
    offset = geo.scale(geo.sub((actor.position[0], actor.position[1]), (before.center[0], before.center[1])), after.spacing / before.spacing)
    turned = geo.rotate(offset, after.yaw_deg - before.yaw_deg)
    return actor.model_copy(update={
        "position": geo.rounded(geo.add((after.center[0], after.center[1]), turned)),
        "yaw_deg": geo.normalize_yaw(actor.yaw_deg + after.yaw_deg - before.yaw_deg),
    })


__all__ = ["BASE_HEIGHT_M", "HEIGHT_JITTER", "POSITION_JITTER", "YAW_JITTER_DEG", "member_name", "members", "moved", "mulberry32"]

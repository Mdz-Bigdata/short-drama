"""Deterministic per-shot seeds: one seed per shot, neighbouring values within a scene.

Same-scene shots share a base derived from the scene id so their looks stay
related; each shot then takes the next integer, and best-of-N candidates add a
small offset on top. Nothing here is random, so re-assigning yields the same table.
"""

from __future__ import annotations

import zlib
from typing import Any

MAX_SEED = 2_147_483_647
_SCENE_SPAN = 1_000  # room for shots and candidate offsets within one scene


def scene_seed_base(scene_id: str) -> int:
    return (zlib.crc32(str(scene_id or "scene").encode("utf-8")) % 1_000_000) * _SCENE_SPAN


def assign_scene_seeds(shots: list[dict[str, Any]]) -> dict[int, int]:
    """shot_id -> seed; shots of the same scene get consecutive seeds."""
    ordinal: dict[str, int] = {}
    seeds: dict[int, int] = {}
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            continue
        scene_id = str(shot.get("scene_id") or "")
        ordinal[scene_id] = ordinal.get(scene_id, 0) + 1
        seed = scene_seed_base(scene_id) + ordinal[scene_id]
        seeds[int(shot.get("shot_id") or index)] = min(seed, MAX_SEED)
    return seeds


def candidate_seed(base: int | None, candidate_index: int) -> int | None:
    """Seed for the k-th candidate of a shot (k from 0); None stays None."""
    if base is None:
        return None
    return min(base + candidate_index * 7, MAX_SEED)

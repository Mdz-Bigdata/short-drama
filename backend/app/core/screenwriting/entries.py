# -*- coding: utf-8 -*-
"""Per-shot content fingerprints so a plan edit only rewrites the shots it touched.

A finished script remembers, per shot, the fingerprint of the plan entry it was
authored from. When the plan changes, comparing fingerprints answers "which
shots are stale" — the unchanged ones keep their visual prompts and any
generated media downstream.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

REVISION_PREFIX = "sha256-v1:"
ENTRY_REVISION_FIELD = "plan_entry_revision"
# The plan fields that feed the visual layer. Ids are the map key, not content.
ENTRY_CONTENT_FIELDS: tuple[str, ...] = (
    "duration_seconds",
    "segment_break",
    "setting",
    "characters_in_scene",
    "scenes",
    "props",
    "scene_description",
    "utterances",
    "source_text",
)


def canonical_digest(data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def revision_of(data: Any) -> str:
    """Optimistic-concurrency token for a whole plan / script aggregate."""
    return REVISION_PREFIX + canonical_digest(data)


def entry_revision(entry: Mapping[str, Any]) -> str:
    projected = {key: entry.get(key) for key in ENTRY_CONTENT_FIELDS}
    return REVISION_PREFIX + canonical_digest(projected)


@dataclass
class EntryCurrency:
    stale_ids: list[str] = field(default_factory=list)
    fresh_ids: list[str] = field(default_factory=list)
    removed_ids: list[str] = field(default_factory=list)
    reordered: bool = False

    @property
    def rewrite_ids(self) -> list[str]:
        return [*self.stale_ids, *self.fresh_ids]


def evaluate_entry_currency(plan_entries: Iterable[Mapping[str, Any]], script_entries: Iterable[Mapping[str, Any]]) -> EntryCurrency:
    """Which plan entries need a new visual layer given the script's remembered fingerprints."""
    plan_list = [dict(entry) for entry in plan_entries]
    script_by_id = {str(entry.get("scene_id")): dict(entry) for entry in script_entries if entry.get("scene_id")}
    result = EntryCurrency()
    plan_ids = [str(entry.get("scene_id")) for entry in plan_list]
    for entry in plan_list:
        sid = str(entry.get("scene_id"))
        existing = script_by_id.get(sid)
        if existing is None:
            result.fresh_ids.append(sid)
        elif existing.get(ENTRY_REVISION_FIELD) != entry_revision(entry):
            result.stale_ids.append(sid)
    result.removed_ids = [sid for sid in script_by_id if sid not in set(plan_ids)]
    kept = [sid for sid in plan_ids if sid in script_by_id]
    script_order = [sid for sid in script_by_id if sid in set(plan_ids)]
    result.reordered = kept != script_order
    return result


__all__ = [
    "ENTRY_CONTENT_FIELDS",
    "ENTRY_REVISION_FIELD",
    "EntryCurrency",
    "REVISION_PREFIX",
    "canonical_digest",
    "entry_revision",
    "evaluate_entry_currency",
    "revision_of",
]

# -*- coding: utf-8 -*-
"""How a story is built: the script structure chosen when the project is made (三幕式, 五幕式, 英雄旅程 …).

The stage-1 director is told which structure to plan with, and every batch of the episode planner is told how
that structure shapes the episodes it is planning. Structures measured by share of the story (three acts, five
acts, the hero's journey) are turned into episode ranges for the project's own episode count, and a batch only
hears about the parts it overlaps; with fewer episodes than parts (a short film has one) the parts are given as
a share of the running time instead.

Nothing chosen means nothing is added: the director picks the structure as before. Short dramas, narration and
short films get it; an advert, and a project made from an uploaded script, do not. Every sentence is
``app/data/prompt/script_structure.json``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import prompt_data

_DATA = "script_structure"
CONFIG_KEY = "script_structure"
MODES = frozenset({"drama", "narration", "film"})


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _table() -> dict[str, Mapping[str, Any]]:
    raw = prompt_data.value(_DATA, "structures")
    return {str(key): row for key, row in raw.items() if isinstance(row, Mapping)} if isinstance(raw, Mapping) else {}


def keys() -> tuple[str, ...]:
    return tuple(_table())


def normalize(raw: Any) -> str:
    """The structure's code, or ``""`` (not chosen) for anything unknown."""
    key = str(raw or "").strip()
    return key if key in _table() else ""


def of(config: Mapping[str, Any] | None) -> str:
    return normalize((config or {}).get(CONFIG_KEY))


def applies(config: Mapping[str, Any] | None) -> bool:
    data = config or {}
    mode = str(data.get("creation_mode") or "drama").strip() or "drama"
    return mode in MODES and not data.get("script_content")


def label(key: str) -> str:
    return str(_table().get(key, {}).get("label") or "")


def director_rule(config: Mapping[str, Any] | None) -> str:
    """What the stage-1 director is told; empty when nothing was chosen or the structure does not apply."""
    key = of(config)
    if not key or not applies(config):
        return ""
    row = _table()[key]
    return _text("director_set").format(label=row["label"], director=row["director"])


def _spans(parts: list[Mapping[str, Any]], total: int) -> list[tuple[Mapping[str, Any], int, int]]:
    """Each part's episodes ``first..last`` of ``total``: cumulative shares rounded, every part at least one episode."""
    weight = sum(float(part.get("share") or 0) for part in parts) or 1.0
    spans: list[tuple[Mapping[str, Any], int, int]] = []
    done = 0.0
    previous = 0
    for index, part in enumerate(parts):
        done += float(part.get("share") or 0)
        remaining = len(parts) - index - 1
        last = total if not remaining else min(total - remaining, max(previous + 1, round(total * done / weight)))
        spans.append((part, previous + 1, last))
        previous = last
    return spans


def outline_rules(creation: Mapping[str, Any] | None, *, first: int, last: int, total: int) -> list[str]:
    """Rule lines for planning episodes ``first..last`` of a ``total``-episode project."""
    key = normalize((creation or {}).get(CONFIG_KEY))
    if not key or not applies(creation):
        return []
    row = _table()[key]
    lines = [_text("outline_lead").format(label=row["label"], outline=row["outline"])]
    parts = [part for part in row.get("parts") or [] if isinstance(part, Mapping)]
    if not parts:
        return lines
    total = max(1, int(total))
    if total < len(parts):
        shown = [_text("outline_part_share").format(name=part["name"], share=part["share"], task=part["task"]) for part in parts]
    else:
        shown = [
            _text("outline_part" if end > start else "outline_part_single").format(name=part["name"], first=start, last=end, task=part["task"])
            for part, start, end in _spans(parts, total) if start <= last and end >= first
        ]
    if shown:
        lines.append(_text("outline_parts_lead") + "".join(shown))
    return lines


__all__ = ["CONFIG_KEY", "applies", "director_rule", "keys", "label", "normalize", "of", "outline_rules"]

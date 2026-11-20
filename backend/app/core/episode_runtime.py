"""An episode's storyboard against the length its script aims at.

Stage 4 times every shot; nothing compared their sum with the episode's target (``episode_target_duration``, or
the creation type's default), so an episode could leave stage 4 at twice its length and be found out only after
the paid clips. This reports it in the stage's own report, within or outside the tolerance; it changes nothing.

Tolerance and sentences: ``app/data/prompt/episode_runtime.json``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.core import creation_modes, prompt_data
from app.core.screenwriting.durations import resolve_episode_target_seconds
from app.core.writer_dashboard import parse_duration_seconds

_DATA = "episode_runtime"
_EPISODE = re.compile(r"^E(\d+)S", re.IGNORECASE)


def _says(key: str, **values: object) -> str:
    return prompt_data.text(_DATA, key).format(**values)


def planned_seconds(shots: Sequence[Mapping[str, Any]], episode: int) -> int:
    """The planned seconds of every shot of ``episode`` (scene ids ``E{n}S…``)."""
    total = 0
    for shot in shots:
        found = _EPISODE.match(str(shot.get("scene_id") or ""))
        if found and int(found.group(1)) == int(episode):
            total += parse_duration_seconds(shot.get("duration")) or 0
    return total


def report_line(shots: Sequence[Mapping[str, Any]], config: Mapping[str, Any] | None, episode: int) -> str:
    """One line for the stage-4 report; empty when the episode has no timed shots or no target."""
    target = creation_modes.episode_target_for(config, resolve_episode_target_seconds(config))
    planned = planned_seconds(shots, episode)
    if not target or not planned:
        return ""
    tolerance = float(prompt_data.value(_DATA, "tolerance"))
    ratio = planned / target - 1
    percent = round(tolerance * 100)
    if abs(ratio) <= tolerance:
        line = _says("within", episode=episode, planned=planned, target=target, signed=f"{ratio * 100:+.0f}", percent=percent)
    else:
        longer = ratio > 0
        line = _says(
            "outside", episode=episode, planned=planned, target=target, off=round(abs(ratio) * 100), percent=percent,
            direction=prompt_data.text(_DATA, "longer" if longer else "shorter"),
            advice=prompt_data.text(_DATA, "advice_longer" if longer else "advice_shorter"),
        )
    return f"{prompt_data.text(_DATA, 'heading')}{line}"

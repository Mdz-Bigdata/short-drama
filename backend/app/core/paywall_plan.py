# -*- coding: utf-8 -*-
"""Where the paywall episodes of a long serial fall, and what the writers are told about them.

A serial long enough to be sold by the episode stops, a handful of times, on a cliff the viewer has
to pay to see resolved. :func:`positions` works those episodes out from the length alone: the first
around episode ten, the last a few episodes before the end, the rest spread through the middle, never
closer together than a minimum gap. Each gets a kind of cliff (identity about to be revealed, a life
on the line, a feeling about to be spoken, the opponent's scheme landing, the truth about to come
out); the first takes the one the lead genre's audience waits for most, and no two in a row share one.

The stage-1 director is told the episodes and the rules of a paywall cliff (among them: what a paywall
holds is not answered anywhere earlier in the plan); each batch of the episode
planner is told which of its episodes are paywall episodes, where to cut, to pay the cliff off at
the head of the next episode, and which paywall episodes still lie ahead so their suspense is only
prepared and not spent early. After a batch is planned two hints may be noted (an empty hook on a
paywall episode, two paywalls in a row stopping the same way); nothing is sent back to the model.

The plan is opt-in (``config["paywall_plan"]``, set from the new-project form), only for serials
written by the pipeline, and only from a minimum length. No model is called. Tables, numbers and
sentences are data (``app/data/prompt/paywall_plan.json``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.core import prompt_data, serial_brief, series_rhythm

_DATA = "paywall_plan"
CONFIG_KEY = "paywall_plan"


def _data() -> Mapping[str, Any]:
    return prompt_data.load(_DATA)


def min_episodes() -> int:
    return int(_data()["min_episodes"])


def _half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def positions(total: int) -> list[int]:
    """The paywall episodes of a serial of ``total`` episodes, ascending; empty when it is too short."""
    data = _data()
    total = int(total or 0)
    if total < min_episodes():
        return []
    count = next((int(band["count"]) for band in data["bands"] if total <= int(band["upto"])),
                 _half_up(total / float(data["beyond_per_episodes"])))
    gap = int(data["min_gap"])
    low, high = (int(value) for value in data["first_range"])
    first = min(high, max(low, int(data["first_episode"])))
    last = total - int(data["last_before_end"])
    middle_end = int(math.floor(total * float(data["middle_until_share"])))
    tail = [last]
    if count >= int(data["tail_extra_from_count"]):
        extra = _half_up(total * float(data["tail_extra_share"]))
        if last - extra >= gap and extra - middle_end >= gap:
            tail.insert(0, extra)
    middle = max(0, count - 1 - len(tail))
    while middle and (middle_end - first) / middle < gap:
        middle -= 1
    step = (middle_end - first) / middle if middle else 0
    found = [first, *[_half_up(first + step * index) for index in range(1, middle + 1)], *tail]
    kept: list[int] = []
    for episode in sorted(set(found)):
        if not kept or episode - kept[-1] >= gap:
            kept.append(episode)
    # The last paywall always stands: one that crowds it gives way.
    if kept[-1] != last:
        kept = [episode for episode in kept if last - episode >= gap] + [last]
    return kept


def plan(total: int, genre: str = "") -> list[dict[str, Any]]:
    """Each paywall episode with the kind of cliff it stops on: ``[{episode, kind, label, cut}]``."""
    data = _data()
    kinds = data["kinds"]
    rotation = [str(kind) for kind in data["rotation"]]
    lead = serial_brief.paywall_kind(genre)
    order = ([lead] if lead in kinds else []) + [kind for kind in rotation if kind != lead]
    rows: list[dict[str, Any]] = []
    for index, episode in enumerate(positions(total)):
        kind = order[index % len(order)]
        if rows and rows[-1]["kind"] == kind:
            kind = order[(index + 1) % len(order)]
        rows.append({"episode": episode, "kind": kind, "label": str(kinds[kind]["label"]), "cut": str(kinds[kind]["cut"])})
    return rows


def applies(config: Mapping[str, Any] | None) -> bool:
    data = config or {}
    return bool(data.get(CONFIG_KEY)) and serial_brief.applies(data)


def of(config: Mapping[str, Any] | None, total: int | None = None) -> list[dict[str, Any]]:
    """The plan of a project that asked for one; empty otherwise."""
    data = config or {}
    if not applies(data):
        return []
    return plan(int(total if total is not None else data.get("episode_count") or 0), serial_brief.lead_genre(data))


def summary(total: int, genre: str = "") -> dict[str, Any]:
    """What the new-project form shows for a length and a lead genre."""
    says = _data()["summary"]
    rows = plan(total, genre)
    if not rows:
        return {"episodes": [], "text": str(says["none"]).format(min=min_episodes()), "min_episodes": min_episodes()}
    listed = str(says["joiner"]).join(str(_data()["director"]["item"]).format(episode=row["episode"], label=row["label"]) for row in rows)
    return {"episodes": rows, "text": str(says["line"]).format(count=len(rows), episodes=listed), "min_episodes": min_episodes()}


def director_rule(config: Mapping[str, Any] | None) -> str:
    """The paywall episodes and the rules of a paywall cliff, for the stage-1 director; empty without a plan."""
    rows = of(config)
    if not rows:
        return ""
    says = _data()["director"]
    listed = str(_data()["summary"]["joiner"]).join(str(says["item"]).format(episode=row["episode"], label=row["label"]) for row in rows)
    total = int((config or {}).get("episode_count") or 0)
    return str(says["head"]).format(total=total, count=len(rows), episodes=listed) + "\n" + str(says["rules"])


def outline_rules(creation: Mapping[str, Any] | None, *, first: int, last: int, total: int) -> list[str]:
    """What one batch of the episode planner is told: the free run, its paywall episodes, the episodes right after one,
    and the paywall episodes still ahead of it, whose suspense it may prepare but not open."""
    rows = of(creation, total)
    if not rows:
        return []
    says = _data()["outline"]
    rules: list[str] = []
    opening = rows[0]["episode"]
    if first < opening:
        rules.append(str(says["free"]).format(first=first, last=min(last, opening), paywall=opening))
    for row in rows:
        if first <= row["episode"] <= last:
            rules.append(str(says["item"]).format(episode=row["episode"], label=row["label"], cut=row["cut"]))
        if first <= row["episode"] + 1 <= last:
            rules.append(str(says["after"]).format(episode=row["episode"] + 1))
    ahead = [row for row in rows if row["episode"] > last]
    if ahead:
        listed = str(_data()["summary"]["joiner"]).join(
            str(_data()["director"]["item"]).format(episode=row["episode"], label=row["label"]) for row in ahead)
        rules.append(str(says["later"]).format(episodes=listed))
    return rules


def warnings(entries: Sequence[Mapping[str, Any]], creation: Mapping[str, Any] | None, *, total: int,
             fresh: Sequence[int] | None = None) -> list[str]:
    """Hints about the planned paywall episodes among ``entries``; only those in ``fresh`` (all when ``None``)."""
    rows = of(creation, total)
    if not rows:
        return []
    says = _data()["warnings"]
    hooks = {int(entry.get("episode") or 0): str(entry.get("hook") or "") for entry in entries if isinstance(entry, Mapping)}
    new = set(hooks) if fresh is None else {int(episode) for episode in fresh}
    found: list[str] = []
    previous: tuple[int, str] | None = None
    for row in rows:
        episode = row["episode"]
        if episode not in hooks:
            previous = None
            continue
        hook = hooks[episode]
        kind = series_rhythm.hook_kind(hook)
        if episode in new and not hook.strip():
            found.append(str(says["no_hook"]).format(episode=episode))
        if previous and kind and kind == previous[1] and (episode in new or previous[0] in new):
            found.append(str(says["same_kind"]).format(first=previous[0], second=episode, kind=kind))
        previous = (episode, kind)
    return found


__all__ = ["CONFIG_KEY", "applies", "director_rule", "min_episodes", "of", "outline_rules", "plan", "positions", "summary", "warnings"]

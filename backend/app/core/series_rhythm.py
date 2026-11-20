# -*- coding: utf-8 -*-
"""How a serial keeps people watching across episodes, and how its people are named.

Four things a planned serial tends to get wrong on its own, each written as a rule the planner reads
and, where a cheap look at the result can tell, as a hint for a person:

* every episode stops on the same kind of cliffhanger — the ledger's ``hook`` opens with its kind, and
  a run of the same kind is pointed out;
* nothing escalates, or nothing ever turns over — how often each should happen is said up front;
* a payoff that is only a reaction ("he froze") — a payoff beat with no result in it is pointed out;
* stretches where nothing new is learned, nothing strong pays off, or nothing changes at all — said as
  rules over a window of episodes, and pointed out when the planned ledger shows such a stretch;
* names every viewer has seen a hundred times, or leads who share a surname.

The kinds, word lists, numbers and sentences are ``app/data/prompt/series_rhythm.json``. Every finding
here is a hint: nothing is sent back to the model and no extra call is made for it.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from app.core import emotion_points, prompt_data

_DATA = "series_rhythm"


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _words(key: str) -> tuple[str, ...]:
    return tuple(str(word) for word in prompt_data.value(_DATA, key))


def _pairs(key: str) -> tuple[tuple[str, str], ...]:
    return tuple((str(first), str(second)) for first, second in prompt_data.value(_DATA, key))


def cliffhanger_kinds() -> tuple[str, ...]:
    """The ways an episode may stop, in the table's order."""
    return tuple(kind for kind, _how in _pairs("cliffhangers"))


def _tag_head() -> re.Pattern[str]:
    opening, closing = _text("hook_tag").split("{kind}")
    return re.compile(r"^\s*" + re.escape(opening) + r"\s*(.+?)\s*" + re.escape(closing))


def hook_kind(hook: Any) -> str:
    """The cliffhanger kind an episode's hook opens with; ``""`` when it names none of the table's."""
    found = _tag_head().match(str(hook or ""))
    kind = found.group(1) if found else ""
    return kind if kind in cliffhanger_kinds() else ""


def outline_rules(total: int, *, cadence: bool = True) -> list[str]:
    """What the episode planner is told about stopping and escalating, for a serial of ``total`` episodes.

    ``cadence=False`` leaves out how often to escalate and turn over: an adaptation takes its events from the
    source and is not asked to invent bigger ones on a schedule."""
    rules: list[str] = []
    if total >= prompt_data.number(_DATA, "min_episodes_for_cliffhangers"):
        menu = _text("menu_separator").join(_text("menu_item").format(kind=kind, how=how) for kind, how in _pairs("cliffhangers"))
        rules.append(_text("cliffhanger_rule").format(menu=menu, run=prompt_data.number(_DATA, "same_kind_run")))
    escalate, reversal = prompt_data.value(_DATA, "escalate"), prompt_data.value(_DATA, "reversal")
    if cadence and total >= int(escalate[0]):
        rules.append(_text("cadence_rule").format(
            escalate_low=escalate[0], escalate_high=escalate[1], reversal_low=reversal[0], reversal_high=reversal[1],
        ))
    low, high = (int(value) for value in prompt_data.value(_DATA, "news_every"))
    if total >= high:
        rules.append(_text("news_rule").format(low=low, high=high))
    if total >= prompt_data.number(_DATA, "window"):
        rules.append(_text("window_rule").format(window=prompt_data.number(_DATA, "window")))
    return rules


def repeat_warnings(hooks: Sequence[tuple[int, Any]]) -> list[str]:
    """One sentence per run of consecutive episodes that stop the same way. ``hooks`` are ``(episode, hook)`` in order."""
    limit = int(prompt_data.number(_DATA, "same_kind_run"))
    found: list[str] = []
    run: list[int] = []
    kind = ""

    def close() -> None:
        if kind and len(run) >= limit:
            others = _text("name_separator").join(other for other in cliffhanger_kinds() if other != kind)
            found.append(_text("repeat_warning").format(first=run[0], last=run[-1], kind=kind, count=len(run), others=others))

    for episode, hook in hooks:
        current = hook_kind(hook)
        if current and current == kind and run and int(episode) == run[-1] + 1:
            run.append(int(episode))
            continue
        close()
        kind, run = current, [int(episode)] if current else []
    close()
    return found


def hollow_payoffs(beats: Sequence[Any], *, label: str) -> list[str]:
    """A payoff beat that shows only how someone reacts, with nothing that has actually happened in it."""
    kinds, hollow, results = _words("payoff_kinds"), _words("hollow_words"), _words("result_words")
    words: list[str] = []
    for beat in beats:
        text = str(beat or "")
        if emotion_points.beat_kind(text) not in kinds or any(word in text for word in results):
            continue
        words.extend(word for word in hollow if word in text and word not in words)
    # A longer word already says the shorter one inside it ("你给我等着" / "给我等着").
    words = [word for word in words if not any(word != other and word in other for other in words)]
    if not words:
        return []
    marks = "".join(_text("name_mark").format(name=word) for word in words)
    return [_text("hollow_warning").format(label=label, words=marks)]


def _stretches(episodes: Sequence[tuple[int, bool | None]], at_least: int) -> list[list[int]]:
    """Runs of at least ``at_least`` consecutive episodes for which the flag is true.

    ``None`` means the episode cannot be judged (its beats carry no kinds): it ends a run without being part of one."""
    runs: list[list[int]] = []
    current: list[int] = []
    for episode, flag in episodes:
        if flag and (not current or episode == current[-1] + 1):
            current.append(episode)
            continue
        if len(current) >= at_least:
            runs.append(current)
        current = [episode] if flag else []
    if len(current) >= at_least:
        runs.append(current)
    return runs


def window_warnings(rows: Sequence[Mapping[str, Any]], *, fresh: Collection[int] | None = None) -> list[str]:
    """Stretches of the ledger with no news, no strong emotion point, or no change at all.

    ``rows`` are ledger entries in any order; only stretches that reach into ``fresh`` (the episodes just
    planned; every episode when ``None``) are reported, so an old stretch is not pointed out again."""
    ledger = sorted((int(row.get("episode") or 0), row) for row in rows if isinstance(row, Mapping) and int(row.get("episode") or 0) > 0)
    new = {episode for episode, _row in ledger} if fresh is None else {int(episode) for episode in fresh}
    joiner = _text("name_separator")
    kinds_of = [(episode, {emotion_points.beat_kind(beat) for beat in row.get("story_beats") or []} - {""}) for episode, row in ledger]
    low, high = (int(value) for value in prompt_data.value(_DATA, "news_every"))
    window = int(prompt_data.number(_DATA, "window"))
    found: list[str] = []

    def lacking(wanted: tuple[str, ...]) -> list[tuple[int, bool | None]]:
        return [(episode, None if not kinds else not (kinds & set(wanted))) for episode, kinds in kinds_of]

    for run in _stretches(lacking(_words("news_kinds")), high):
        if new & set(run):
            found.append(_text("news_warning").format(
                first=run[0], last=run[-1], count=len(run), kinds=joiner.join(_words("news_kinds")), low=low, high=high,
            ))
    for run in _stretches(lacking(_words("strong_kinds")), window):
        if new & set(run):
            found.append(_text("strong_warning").format(
                first=run[0], last=run[-1], count=len(run), kinds=joiner.join(_words("strong_kinds")), window=window,
            ))
    # Only a ledger that keeps the cross-episode sheet at all can be said to have left it empty.
    if any(row.get("state_changes") for _episode, row in ledger):
        for run in _stretches([(episode, not row.get("state_changes")) for episode, row in ledger], window):
            if new & set(run):
                found.append(_text("still_warning").format(first=run[0], last=run[-1], count=len(run)))
    return found


def naming_rule() -> str:
    """What whoever invents the cast is told about names."""
    joiner = _text("name_separator")
    return _text("naming_rule").format(
        names=joiner.join(_words("overused_names")), surnames=joiner.join(_words("overused_surnames")),
        characters=joiner.join(_words("overused_characters")),
    )


def _overused(name: str) -> bool:
    if name in _words("overused_names"):
        return True
    return len(name) >= 2 and name[0] in _words("overused_surnames") and any(char in name[1:] for char in _words("overused_characters"))


def name_warnings(names: Sequence[Any]) -> list[str]:
    """Names of the overused kind anywhere in the cast, and main characters who share a surname."""
    cast = [str(name).strip() for name in names if str(name or "").strip()]
    found: list[str] = []
    worn = [name for name in cast if _overused(name)]
    if worn:
        found.append(_text("name_warning").format(names="".join(_text("name_mark").format(name=name) for name in worn)))
    by_surname: dict[str, list[str]] = {}
    for name in cast[: int(prompt_data.number(_DATA, "main_cast"))]:
        by_surname.setdefault(name[0], []).append(name)
    for surname, sharing in by_surname.items():
        if len(sharing) > 1:
            marks = "".join(_text("name_mark").format(name=name) for name in sharing)
            found.append(_text("same_surname_warning").format(names=marks, surname=surname))
    return found


def knowledge_rule() -> str:
    """The writing rule for what a character may know."""
    return _text("knowledge_rule")


def outline_warnings(
    entries: Sequence[Mapping[str, Any]], *, earlier: Sequence[Mapping[str, Any]] = (), cast: Mapping[str, Any] | None = None,
) -> list[str]:
    """Every hint for a freshly planned run of episodes: repeated stops (counting the ``earlier`` episodes
    that lead into it), hollow payoffs, and — when the run opens the serial — the cast's names."""
    rows = [row for row in entries if isinstance(row, Mapping)]
    before = [row for row in earlier if isinstance(row, Mapping)]
    fresh = {int(row.get("episode") or 0) for row in rows}
    hooks = [(int(row.get("episode") or 0), row.get("hook")) for row in [*before, *rows]]
    hooks = sorted({episode: hook for episode, hook in hooks if episode > 0}.items())
    found: list[str] = []
    # A run that ended before this batch was already reported when it was planned.
    for run in _runs(hooks):
        if fresh & set(run["episodes"]):
            found.extend(repeat_warnings([(episode, _text("hook_tag").format(kind=run["kind"])) for episode in run["episodes"]]))
    found.extend(window_warnings([*before, *rows], fresh=fresh))
    for row in rows:
        found.extend(hollow_payoffs(row.get("story_beats") or [], label=_text("episode_label").format(episode=row.get("episode"))))
    if 1 in fresh and isinstance(cast, Mapping) and isinstance(cast.get("characters"), Mapping):
        found.extend(name_warnings(list(cast["characters"])))
    return found


def _runs(hooks: Sequence[tuple[int, Any]]) -> list[dict[str, Any]]:
    """Maximal runs of consecutive episodes whose hooks open with the same kind."""
    runs: list[dict[str, Any]] = []
    for episode, hook in hooks:
        kind = hook_kind(hook)
        if kind and runs and runs[-1]["kind"] == kind and runs[-1]["episodes"][-1] == episode - 1:
            runs[-1]["episodes"].append(episode)
        elif kind:
            runs.append({"kind": kind, "episodes": [episode]})
    return runs


__all__ = [
    "cliffhanger_kinds", "hollow_payoffs", "hook_kind", "knowledge_rule", "name_warnings", "naming_rule", "outline_rules",
    "outline_warnings", "repeat_warnings", "window_warnings",
]

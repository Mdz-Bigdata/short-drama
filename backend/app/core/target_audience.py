# -*- coding: utf-8 -*-
"""Who a serial is written for: 男频 or 女频, and an age band, chosen when the project is made.

The two leans want different things from the start. A 男频 serial has to catch the viewer in its very first
scene and give a sense of gain within three episodes; a 女频 serial has to set its core conflict inside
episode 1 and build a relationship worth following within three. The stage-1 director is told who the
serial is for (or, when nobody chose, to decide and write it at the head of the plan), and the episode
planner is told the matching rules, plus two that hold for any serial: the main line fits in one sentence
by episode 3 with a goal that can carry the whole run, and a complex world is shown through events by
episode 3 rather than listed.

Only serials get any of this (creation types ``drama`` and ``narration``); a short film and an advert do not.
Every sentence is ``app/data/prompt/target_audience.json``. Nothing here is checked afterwards or sent back.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import prompt_data

_DATA = "target_audience"
CONFIG_KEY = "target_audience"
SERIAL_MODES = frozenset({"drama", "narration"})


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _table(key: str) -> dict[str, dict[str, str]]:
    raw = prompt_data.value(_DATA, key)
    return {str(code): {str(k): str(v) for k, v in row.items()} for code, row in raw.items()} if isinstance(raw, Mapping) else {}


def leans() -> tuple[str, ...]:
    return tuple(_table("leans"))


def ages() -> tuple[str, ...]:
    return tuple(_table("ages"))


def normalize(raw: Any) -> dict[str, str]:
    """``{"lean": …, "age": …}`` with anything unknown cleared to ``""`` (not chosen)."""
    data = raw if isinstance(raw, Mapping) else {}
    lean = str(data.get("lean") or "").strip()
    age = str(data.get("age") or "").strip()
    return {"lean": lean if lean in _table("leans") else "", "age": age if age in _table("ages") else ""}


def of(config: Mapping[str, Any] | None) -> dict[str, str]:
    return normalize((config or {}).get(CONFIG_KEY))


def applies(config: Mapping[str, Any] | None) -> bool:
    mode = str((config or {}).get("creation_mode") or "drama").strip() or "drama"
    return mode in SERIAL_MODES


def _who(audience: Mapping[str, str]) -> str:
    lean = _table("leans").get(audience.get("lean") or "", {}).get("label", "")
    age = _table("ages").get(audience.get("age") or "", {}).get("label", "")
    if lean and age:
        return _text("who_lean_age").format(lean=lean, age=age)
    if lean:
        return _text("who_lean").format(lean=lean)
    if age:
        return _text("who_age").format(age=age)
    return ""


def who(config: Mapping[str, Any] | None) -> str:
    """「女频的青中年观众」 for a serial whose audience was chosen; empty when nothing was chosen or it is not a serial."""
    return _who(of(config)) if applies(config) else ""


def _lean_rows(audience: Mapping[str, str]) -> list[dict[str, str]]:
    """The chosen lean, or both when none was chosen (the plan decides which one applies)."""
    table = _table("leans")
    chosen = audience.get("lean") or ""
    return [table[chosen]] if chosen in table else list(table.values())


def _age_row(audience: Mapping[str, str]) -> dict[str, str] | None:
    return _table("ages").get(audience.get("age") or "")


def director_rule(config: Mapping[str, Any] | None) -> str:
    """What the stage-1 director is told about the audience; empty for a short film or an advert."""
    if not applies(config):
        return ""
    audience = of(config)
    prefs = [_text("pref_line").format(**row) for row in _lean_rows(audience)]
    age = _age_row(audience)
    if age:
        prefs.append(_text("age_line").format(**age))
    who = _who(audience)
    if who:
        return _text("director_set").format(who=who, prefs="".join(prefs))
    return _text("director_unset").format(prefs="".join(prefs))


def outline_rules(creation: Mapping[str, Any] | None, *, first: int, total: int) -> list[str]:
    """Rule lines for planning episodes ``first``… of a ``total``-episode serial written from a director's plan."""
    if not applies(creation):
        return []
    audience = normalize((creation or {}).get(CONFIG_KEY))
    early = first <= 3 and total >= prompt_data.number(_DATA, "first_three_min")
    who = _who(audience)
    lines = [_text("outline_set_lead").format(who=who) if who and audience.get("lean") else _text("outline_unset_lead")]
    for row in _lean_rows(audience):
        if early:
            lines.append(_text("outline_pref").format(**row))
        lines.append(_text("outline_keep").format(**row))
    age = _age_row(audience)
    if age:
        lines.append(_text("outline_age").format(**age))
    if early:
        lines += [_text("main_line").format(total=total), _text("world")]
    return lines


def adaptation_rules(creation: Mapping[str, Any] | None, *, opens_series: bool) -> list[str]:
    """Rule lines for re-staging a novel: only a chosen lean, and its opening rules only where episode 1 is planned.

    An adaptation keeps the novel's own main line and world, so neither rule about them is added; with no lean
    chosen there is no director's plan to say which one applies, so nothing is added either."""
    if not applies(creation):
        return []
    audience = normalize((creation or {}).get(CONFIG_KEY))
    if not audience.get("lean"):
        return []
    row = _table("leans")[audience["lean"]]
    lines = [_text("outline_set_lead").format(who=_who(audience))]
    if opens_series:
        lines.append(_text("outline_pref").format(**row))
    lines.append(_text("outline_keep").format(**row))
    age = _age_row(audience)
    if age:
        lines.append(_text("outline_age").format(**age))
    return lines


__all__ = ["CONFIG_KEY", "adaptation_rules", "ages", "applies", "director_rule", "leans", "normalize", "of", "outline_rules", "who"]

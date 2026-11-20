# -*- coding: utf-8 -*-
"""What an actor plays from: the reason behind a shot, and how a line is said.

A video model told only "演得伤心一点" plays a generic face. A director gives an actor
the situation instead — what the person wants, fears, knows and does not yet know —
and lets the face follow. The shot plan carries that as ``subtext`` (one sentence per
person in the shot); the clip prompt passes it on as motive only, so the reason never
turns into a flashback or a third person on screen.

A line's ``delivery`` is written as the whole act of saying it: the state before the
first word, how the voice moves inside the line, and the half-beat after it.

The wording lives in ``app/data/prompt/acting.json``.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.core import prompt_data

_DATA = "acting"

SUBTEXT_MAX_CHARS = prompt_data.number(_DATA, "subtext_max_chars")
DELIVERY_MAX_CHARS = prompt_data.number(_DATA, "delivery_max_chars")


def subtext_schema() -> str:
    """The JSON-schema note for the shot plan's ``subtext`` field."""
    return prompt_data.text(_DATA, "subtext_schema")


def subtext_rule() -> str:
    """How the writer fills ``subtext`` (field guide of the shot plan prompt)."""
    return prompt_data.text(_DATA, "subtext_field")


def delivery_rule() -> str:
    """How the writer fills a line's ``delivery`` when the lines are the writer's own."""
    return prompt_data.text(_DATA, "delivery_rule")


def pacing_rule(*, verbatim: bool = False) -> str:
    """How fast each line is played and how long its shot runs: the model judges the pace, nothing is sped up.

    ``verbatim`` is for lines taken from a finished screenplay, which keep every word.
    """
    return prompt_data.text(_DATA, "pacing_rule_verbatim" if verbatim else "pacing_rule")


def subtext_of(scene: Mapping[str, Any] | None) -> str:
    return " ".join(str((scene or {}).get("subtext") or "").split())[:SUBTEXT_MAX_CHARS]


def clip_line(scene: Mapping[str, Any] | None) -> str:
    """The motive line of a clip prompt; empty when the shot plan gave none."""
    subtext = subtext_of(scene)
    return prompt_data.text(_DATA, "clip_line").format(subtext=subtext) if subtext else ""


__all__ = [
    "DELIVERY_MAX_CHARS", "SUBTEXT_MAX_CHARS", "clip_line", "delivery_rule", "pacing_rule", "subtext_of", "subtext_rule", "subtext_schema",
]

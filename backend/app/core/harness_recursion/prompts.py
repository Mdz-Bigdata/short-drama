"""The wording of the improvement stages, read from ``app/data/prompt/harness_recursion.json``.

Structure after Harness²'s ``core/prompts.py``: the same blocks (what you do not have, evidence is
data, the editable surface, ground it here and shape it for the domain) around a propose, a compose,
a select and a reflect mission. The sentences are this project's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core import prompt_data

_FILE = "harness_recursion"


def table(section: str) -> Mapping[str, Any]:
    return prompt_data.load(_FILE)[section]


def says(section: str, key: str, /, **values: object) -> str:
    """One sentence of the table, its named placeholders filled."""
    text = str(table(section)[key])
    return text.format(**values) if values else text


def limit(key: str) -> int:
    return int(table("limits")[key])


def label(key: str) -> str:
    return str(table("labels")[key])


KEEP_BASE = label("keep_base")
NO_ENTRY = label("no_entry")


def clip(text: str, size: int) -> str:
    """``text`` within ``size`` characters, saying so when it was cut: a silent cut reads as a defect."""
    text = str(text or "")
    return text if len(text) <= size else text[:size] + label("truncated")


def _join(parts: Sequence[str]) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


WORK_FIELDS = ("work", "downstream", "lens", "yardstick", "checks")


def work_of(stage: int) -> dict[str, str]:
    """What the stage produces, who reads it next, and how its work is looked at; all empty for a stage nobody described."""
    entry = table("works").get(str(stage)) or {}
    return {key: str(entry.get(key) or "") for key in WORK_FIELDS}


def _surface() -> str:
    components = "\n".join(f"- <{name}>：{meaning}" for name, meaning in table("components").items())
    return says("blocks", "surface", components=components,
                component_chars=limit("component_chars"), total_chars=limit("total_chars"))


def _common(work: str, domain: str, lens: str = "") -> tuple[list[str], list[str]]:
    return [
        says("blocks", "work", work=work),
        says("blocks", "lens", lens=lens) if lens else "",
    ], [
        says("blocks", "answer_free"),
        says("blocks", "evidence_boundary"),
        _surface(),
        says("blocks", "generalize", domain=domain),
        says("blocks", "keep_base", keep_base=KEEP_BASE),
        says("blocks", "reply_format", keep_base=KEEP_BASE),
    ]


def propose(dim: str, *, work: str, domain: str, k: int, index: int, round_t: int | None = None, lens: str = "") -> str:
    """The mission of one proposer: ``dim`` is INV (how the agent works) or DOM (what a practitioner knows)."""
    if dim not in ("INV", "DOM"):
        raise ValueError(f"unknown dimension {dim!r}; the method has two: INV and DOM")
    head, tail = _common(work, domain, lens)
    return _join([
        says("propose", "head", count=2 * k, index=index),
        says("propose", "round", round=round_t, rounds=k) if round_t else "",
        *head,
        says("propose", dim.lower()),
        *tail,
    ])


def compose(
    *, work: str, domain: str, k: int, base_count: int, index: int = 1, round_t: int | None = None, lens: str = "", yardstick: str = "",
) -> str:
    """The mission of a composer: one overlay from the base executions and every probed candidate."""
    head, tail = _common(work, domain, lens)
    return _join([
        says("compose", "head"),
        says("compose", "round", round=round_t, rounds=k) if round_t else "",
        *head,
        says("compose", "have", base_count=base_count, candidate_count=2 if round_t else 2 * k, k=1 if round_t else k),
        says("compose", "weigh"),
        says("compose", "job", keep_base=KEEP_BASE),
        says("compose", "independent", count=k) if k > 1 and not round_t else "",
        says("blocks", "yardstick", yardstick=yardstick) if yardstick else "",
        *tail,
    ])


def select(*, work: str, downstream: str, count: int, lens: str = "", checks: str = "") -> str:
    """Blind selection over produced outputs; the candidates' origins are not in the mission."""
    return _join([
        says("select", "head", count=count),
        says("blocks", "work", work=work),
        says("blocks", "lens", lens=lens) if lens else "",
        says("select", "anonymous"),
        says("select", "criteria", downstream=downstream or label("none")),
        says("blocks", "checks", checks=checks) if checks else "",
        says("blocks", "answer_free"),
        says("blocks", "evidence_boundary"),
        says("select", "reply_format"),
    ])


def reflect(*, work: str, lens: str = "") -> str:
    """What each edit did, then the one lesson that transfers (or none)."""
    return _join([
        says("reflect", "head"),
        says("blocks", "work", work=work),
        says("blocks", "lens", lens=lens) if lens else "",
        says("reflect", "not_only"),
        says("reflect", "edits"),
        says("reflect", "lesson", no_entry=NO_ENTRY),
        says("blocks", "answer_free"),
        says("blocks", "evidence_boundary"),
        says("reflect", "reply_format"),
    ])


def rejected(error: str) -> str:
    return says("blocks", "rejected", error=error)


__all__ = ["KEEP_BASE", "NO_ENTRY", "WORK_FIELDS", "clip", "compose", "label", "limit", "propose", "reflect", "rejected", "says", "select", "table", "work_of"]

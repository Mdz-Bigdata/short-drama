"""The editable surface of a stage agent: a few named text components appended to its fixed prompt.

Harness² edits a tree of eight components around a tool-using agent. A stage agent here is one model
call, so six remain, each a paragraph: ``system_prompt``, ``guardrails``, ``memory``,
``tool_guidance`` (the shape of what it hands on), ``skills`` (triggered procedures) and ``scripts``
(checks a machine can run, see ``checks``). Subagents and plugins have nothing to attach to. A proposal
naming anything else is off the surface and is sent back, as upstream sends back a stray file.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.core.harness_recursion import checks, prompts

Harness = dict[str, str]

# In the order they are rendered and listed.
COMPONENTS: tuple[str, ...] = tuple(prompts.table("components"))

_BLOCK = re.compile(r"<harness>(.*?)</harness>", re.S | re.I)
_PART = re.compile(r"<([a-z_]+)>(.*?)</\1>", re.S | re.I)
_NOTES = re.compile(r"<notes>(.*?)</notes>", re.S | re.I)
# 「当……时：……」, or its English shape for a production written in English.
_TRIGGER = re.compile(r"^((当|每当|若|如果|遇到|一旦|凡).{1,80}?[：:，,]|(when|if|whenever)\b.{1,160}?[:,])", re.I)
_BULLET = re.compile(r"^\s*[-•*]\s*")


def _skill_lines(text: str) -> list[str]:
    """The skills a component lists: its bulleted lines when it uses bullets (other lines continue them), else every line."""
    lines = [line for line in text.splitlines() if line.strip()]
    if any(_BULLET.match(line) for line in lines):
        lines = [line for line in lines if _BULLET.match(line)]
    return [_BULLET.sub("", line).strip() for line in lines]


class ProposalError(ValueError):
    """A reply that cannot be taken as an overlay; the message goes back to its author as it is."""


def normalise(harness: Mapping[str, object] | None) -> Harness:
    """Known components with something in them, in surface order."""
    harness = harness or {}
    return {name: str(harness[name]).strip() for name in COMPONENTS if str(harness.get(name) or "").strip()}


def notes_of(reply: str) -> str:
    found = _NOTES.search(reply or "")
    return prompts.clip((found.group(1) if found else _BLOCK.sub("", reply or "")).strip(), prompts.limit("notes_chars"))


def parse_reply(reply: str, current: Mapping[str, str]) -> Harness:
    """The overlay a proposer or composer answered with, laid over ``current``.

    A component the reply does not mention is kept, an empty one is removed, and KEEP_BASE keeps
    everything: the author edits the current overlay, as upstream's author edits a copy of the tree.
    """
    if not (reply or "").strip():
        raise ProposalError(prompts.says("errors", "empty_reply"))
    block = _BLOCK.search(reply)
    if block is None:
        raise ProposalError(prompts.says("errors", "no_block"))
    body = block.group(1)
    if body.strip().upper() == prompts.KEEP_BASE:
        return normalise(current)
    merged = dict(normalise(current))
    stray: list[str] = []
    for name, text in _PART.findall(body):
        name = name.lower()
        if name not in COMPONENTS:
            stray.append(name)
        elif text.strip() and text.strip() != prompts.label("empty"):
            merged[name] = text.strip()
        else:
            # Empty, or the "(empty)" mark the author was shown for a component with nothing in it, copied back.
            merged.pop(name, None)
    if stray:
        raise ProposalError(prompts.says("errors", "off_surface", names="、".join(sorted(set(stray))[:6]), allowed="、".join(COMPONENTS)))
    if not _PART.search(body):
        raise ProposalError(prompts.says("errors", "no_block"))
    return normalise(merged)


def grader_word(text: str) -> str | None:
    """A word about being judged or scored, if ``text`` carries one.

    The overlay may only describe the work. One that says what a checker wants would teach the agent
    to satisfy the checker, and could never be shown to a later task as evidence.
    """
    low = str(text or "").lower()
    return next((word for word in prompts.table("grader_words") if str(word).lower() in low), None)


# Verified on one project only; never carried to another.
PROJECT_ONLY: tuple[str, ...] = ("memory",)


def project_terms_in(text: str, terms: Sequence[str]) -> list[str]:
    """This project's own names (cast, title) that ``text`` mentions."""
    return [term for term in dict.fromkeys(str(term).strip() for term in terms) if len(term) >= 2 and term in str(text or "")]


def carried(harness: Mapping[str, str], terms: Sequence[str] = ()) -> Harness:
    """The overlay as another project of the kind gets it: without the project-only component, and without
    any line that still names this project's cast. Validation keeps such lines out of a new overlay; this is
    for one that was stored before the rule, or whose project named someone only later."""
    kept: Harness = {}
    for name, text in normalise(harness).items():
        if name in PROJECT_ONLY:
            continue
        lines = [line for line in text.splitlines() if not project_terms_in(line, terms)]
        if "\n".join(lines).strip():
            kept[name] = "\n".join(lines).strip()
    return kept


def validate(harness: Mapping[str, str], project_terms: Sequence[str] = ()) -> None:
    """Raise ``ProposalError`` listing every problem, in words its author can act on.

    ``project_terms`` are this project's own names: outside ``memory`` they are refused, because every
    other component is what the next project of the kind runs with (seen in a real run, 2026-11-16: a
    character-design overlay whose checks required another film's cast by name).
    """
    problems: list[str] = []
    component_limit, total_limit = prompts.limit("component_chars"), prompts.limit("total_chars")
    for name, text in harness.items():
        if name not in COMPONENTS:
            problems.append(prompts.says("errors", "off_surface", names=name, allowed="、".join(COMPONENTS)))
            continue
        if len(text) > component_limit:
            problems.append(prompts.says("errors", "component_too_long", name=name, size=len(text), limit=component_limit))
        word = grader_word(text)
        if word:
            problems.append(prompts.says("errors", "grader_word", name=name, word=word))
        if name not in PROJECT_ONLY:
            problems.extend(prompts.says("errors", "project_term", name=name, term=term) for term in project_terms_in(text, project_terms)[:3])
        if name == "scripts":
            try:
                checks.parse(text)
            except checks.CheckError as unreadable:
                problems.append(str(unreadable))
        if name == "skills":
            # An untriggered skill is dead weight (upstream refuses a skill the always-on text never names):
            # here a skill is one line, and the line must open with the situation that triggers it.
            problems.extend(
                prompts.says("errors", "skill_trigger", line=line[:60])
                for line in _skill_lines(text)
                if not _TRIGGER.match(line)
            )
    total = sum(len(text) for text in harness.values())
    if total > total_limit:
        problems.append(prompts.says("errors", "total_too_long", size=total, limit=total_limit))
    if problems:
        raise ProposalError("\n".join(problems))


def changed(before: Mapping[str, str], after: Mapping[str, str]) -> dict[str, list[str]]:
    """Which components an edit added, removed or rewrote."""
    before, after = normalise(before), normalise(after)
    return {
        "added": [name for name in COMPONENTS if name in after and name not in before],
        "removed": [name for name in COMPONENTS if name in before and name not in after],
        "modified": [name for name in COMPONENTS if name in before and name in after and before[name] != after[name]],
    }


def same(before: Mapping[str, str], after: Mapping[str, str]) -> bool:
    return not any(changed(before, after).values())


def render(harness: Mapping[str, str]) -> str:
    """The block appended to the stage's fixed prompt; empty for an empty overlay, so nothing changes."""
    harness = normalise(harness)
    if not harness:
        return ""
    titles = prompts.table("titles")
    # The agent reads the checks in words; the grammar is for the engine and for whoever edits the overlay.
    shown = {name: checks.readable(text) if name == "scripts" else text for name, text in harness.items()}
    parts = [prompts.says("overlay", "component", title=titles[name], body=text) for name, text in shown.items() if text]
    return prompts.says("overlay", "header") + "\n" + "\n".join(parts) if parts else ""


def describe(harness: Mapping[str, str]) -> str:
    """The overlay as a proposer reads it: every component by its tag, the empty ones marked."""
    harness = normalise(harness)
    return "\n".join(f"<{name}>{harness.get(name) or prompts.label('empty')}</{name}>" for name in COMPONENTS)


__all__ = ["COMPONENTS", "Harness", "PROJECT_ONLY", "ProposalError", "carried", "changed", "describe", "grader_word", "normalise", "notes_of", "parse_reply", "project_terms_in", "render", "same", "validate"]

# -*- coding: utf-8 -*-
"""The script supervisor's sheet across episodes: what each episode leaves changed.

Every episode's plan is written on its own (and several at once), from its own slice of the
source or its own outline. Left alone, episode 3 asks again what episode 1 already asked, a
wound heals between episodes, and someone uses what they were never told. So the ledger
planner writes down, for each episode, what is different once it has played
(``state_changes`` on the ledger row, each line opening with its kind), and three things read it:

* the ledger planner itself, for the episodes it plans next (``context_changes``, ``earlier_lasting``);
* each episode's shot plan, which is told what the earlier episodes settled, how the
  previous one ended and what its own episode must leave behind (``plan_block``);
* a check after the plan is written (``check``): does it contradict the sheet, replay what was
  already played, or fail to play what it must leave behind? One send-back, then a note.

The sheet is read from the ledger, so plans can still be written side by side. The kinds, the
budgets and every sentence are ``app/data/prompt/story_state.json``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import settings
from app.core import prompt_data
from app.core.screenwriting.structured_llm import LLMCaller, StructuredOutputError, call_structured

logger = logging.getLogger("app.core.screenwriting.story_state")

_DATA = "story_state"
ENABLED_ENV = "SCREENWRITING_STATE_CHECK"
LABEL = "story_state_check"
# A plan that still disagrees with the sheet after its one send-back: kept, flagged for the editor.
CONFLICT = "story_state_conflict"

KINDS: tuple[str, ...] = tuple(kind for kind, _ in prompt_data.pairs(_DATA, "kinds"))
LASTING: frozenset[str] = frozenset(prompt_data.words(_DATA, "lasting"))


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _tag_head() -> re.Pattern[str]:
    opening, closing = _text("tag").split("{kind}")
    return re.compile(r"^\s*" + re.escape(opening) + r"\s*(.+?)\s*" + re.escape(closing))


def kind_of(change: Any) -> str:
    """The kind a change opens with; ``""`` when it names none of the table's."""
    found = _tag_head().match(str(change or ""))
    kind = found.group(1) if found else ""
    return kind if kind in KINDS else ""


def field() -> str:
    """What the ledger planner is told to write in ``state_changes`` (the schema carries it)."""
    menu = _text("menu_separator").join(_text("menu_item").format(kind=kind, what=what) for kind, what in prompt_data.pairs(_DATA, "kinds"))
    return _text("field").format(names=_text("name_separator").join(KINDS), menu=menu)


def changes_of(entry: Mapping[str, Any] | None) -> list[str]:
    """One ledger row's changes, blanks dropped."""
    raw = (entry or {}).get("state_changes") if isinstance(entry, Mapping) else None
    return [str(item).strip() for item in raw or [] if str(item or "").strip()] if isinstance(raw, (list, tuple)) else []


def _rows(ledger: Sequence[Any], before: int) -> list[tuple[int, list[str]]]:
    """(episode, changes) of the rows before ``before`` that have any, in broadcast order."""
    rows = [
        (int(entry.get("episode") or 0), changes_of(entry)) for entry in ledger or []
        if isinstance(entry, Mapping) and 0 < int(entry.get("episode") or 0) < int(before)
    ]
    return sorted((row for row in rows if row[1]), key=lambda row: row[0])


def _block(episode: int, changes: Sequence[str]) -> list[str]:
    return [_text("episode_line").format(episode=episode), *(_text("item").format(text=change) for change in changes)]


def _size(lines: Sequence[str]) -> int:
    return sum(len(line) for line in lines)


def table_before(ledger: Sequence[Any], episode: int) -> list[str]:
    """The sheet as ``episode`` reads it: the nearest episodes whole, the older ones for what still holds.

    Filled from the previous episode backwards within ``recent_chars``; of the episodes that
    no longer fit, only the lasting kinds (a planted setup, a promise, a rule, a wound, who
    holds what) are kept, nearest first, within ``lasting_chars``. Returned in broadcast order.
    """
    rows = _rows(ledger, episode)
    recent_budget, lasting_budget = prompt_data.number(_DATA, "recent_chars"), prompt_data.number(_DATA, "lasting_chars")
    recent: list[list[str]] = []
    older: list[list[str]] = []
    used = 0
    cut = len(rows)
    for index in range(len(rows) - 1, -1, -1):
        block = _block(*rows[index])
        # The previous episode is always told whole: it is what this one picks up from.
        if recent and used + _size(block) > recent_budget:
            break
        recent.append(block)
        used += _size(block)
        cut = index
    used = 0
    for number, changes in reversed(rows[:cut]):
        kept = [change for change in changes if kind_of(change) in LASTING]
        if not kept:
            continue
        block = _block(number, kept)
        if used + _size(block) > lasting_budget:
            break
        older.append(block)
        used += _size(block)
    return [line for block in [*reversed(older), *reversed(recent)] for line in block]


def earlier_lasting(ledger: Sequence[Any], before: int) -> list[str]:
    """For the ledger planner: what the episodes before ``before`` settled that still holds, under its heading.

    The planner is shown its last few rows in full (see ``context_changes``); this is the part
    of the sheet older than those rows. Nothing when there is none.
    """
    budget = prompt_data.number(_DATA, "lasting_chars")
    blocks: list[list[str]] = []
    used = 0
    for number, changes in reversed(_rows(ledger, before)):
        kept = [change for change in changes if kind_of(change) in LASTING]
        if not kept:
            continue
        block = _block(number, kept)
        if used + _size(block) > budget:
            break
        blocks.append(block)
        used += _size(block)
    lines = [line for block in reversed(blocks) for line in block]
    return ["", _text("earlier_heading"), *lines] if lines else []


def context_changes(entry: Mapping[str, Any]) -> str:
    """The line under an already-planned episode in the planner's context; ``""`` when it changed nothing."""
    changes = changes_of(entry)
    return _text("context_item").format(changes=_text("context_separator").join(changes)) if changes else ""


def plan_block(*, sheet: Sequence[str], previous_outline: Sequence[str], landing: Sequence[str]) -> str:
    """What an episode's shot plan is told: how the last one ended, the sheet so far, what this one must leave.

    ``""`` for a first episode with nothing to leave, so its prompt reads as it always did.
    """
    parts: list[str] = []
    if previous_outline:
        parts.append(_text("previous_wrap").format(lines="\n".join(previous_outline)))
    if sheet:
        parts.append(_text("state_wrap").format(lines="\n".join(sheet)))
    if previous_outline or sheet:
        parts.append(_text("plan_rule"))
    if landing:
        parts.append(_text("landing_wrap").format(lines="\n".join(_text("item").format(text=change) for change in landing)))
    return ("\n\n".join(parts) + "\n\n") if parts else ""


# --------------------------------------------------------------------------- the check after a plan


class Finding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene_id: str = Field(default="", description="出问题的分镜；整集的问题留空")
    quote: str = Field(default="", description="分镜里出问题的那句或那个动作")
    fact: str = Field(default="", description="对不上或被重演的那条场记；没演出来的留空")
    fix: str = Field(default="", description="一句话怎么改")

    def reason(self) -> str:
        """The finding as the model (send-back) and the editor (note) read it."""
        values = self.model_dump()
        if not self.fact.strip():
            return _text("reason_missing").format(**values)
        return _text("reason" if self.scene_id.strip() else "reason_whole").format(**values)


class CheckDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    findings: list[Finding] = Field(default_factory=list)


def enabled() -> bool:
    return settings.env_flag(ENABLED_ENV, True)


def _shots_text(scenes: Sequence[Mapping[str, Any]]) -> str:
    limit = prompt_data.number(_DATA, "description_chars")
    lines: list[str] = []
    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        cast = _text("name_separator").join(str(name) for name in scene.get("characters_in_scene") or []) or _text("check_none")
        lines.append(_text("check_shot").format(scene_id=scene.get("scene_id") or "", setting=scene.get("setting") or "", cast=cast))
        description = str(scene.get("scene_description") or "").strip()
        if description:
            lines.append(_text("check_description").format(description=description[:limit]))
        for utterance in scene.get("utterances") or []:
            if not isinstance(utterance, Mapping) or not str(utterance.get("text") or "").strip():
                continue
            if utterance.get("kind") == "voiceover":
                lines.append(_text("check_voiceover").format(text=utterance["text"]))
            else:
                lines.append(_text("check_dialogue").format(speaker=utterance.get("speaker") or "", text=utterance["text"]))
    return "\n".join(lines)


def build_check_prompt(*, episode: int, sheet: Sequence[str], landing: Sequence[str], scenes: Sequence[Mapping[str, Any]]) -> str:
    leaving = "\n".join(_text("item").format(text=change) for change in landing) or _text("check_none")
    return (
        f"{_text('check_head').format(episode=episode)}\n\n<story_state>\n" + "\n".join(sheet) + "\n</story_state>\n\n"
        f"<episode_changes>\n{leaving}\n</episode_changes>\n\n<shots>\n{_shots_text(scenes)}\n</shots>"
    )


def check(
    caller: LLMCaller, *, episode: int, sheet: Sequence[str], landing: Sequence[str], scenes: Sequence[Mapping[str, Any]],
    temperature: float | None = None, max_tokens: int | None = None,
) -> list[Finding]:
    """Ask once whether the plan agrees with the sheet; no usable answer counts as agreement (the check must never cost the episode).

    ``max_tokens`` is the caller's own output budget. A model that reasons before it answers spends
    that budget thinking first: with the table's small number the whole answer came back empty, which
    reads as "nothing found". The table's number is only the fallback when no budget is given.
    """
    try:
        result = call_structured(
            caller, system_prompt=_text("check_system"),
            user_prompt=build_check_prompt(episode=episode, sheet=sheet, landing=landing, scenes=scenes), schema=CheckDraft,
            max_tokens=max(int(max_tokens or 0), prompt_data.number(_DATA, "max_tokens")), attempts=2, label=f"{LABEL}_E{episode}", temperature=temperature,
        )
    except StructuredOutputError as error:
        logger.warning("[Screenwriting] story-state check of episode %s gave no usable answer; taken as agreement: %s", episode, "; ".join(error.reasons)[:200])
        return []
    found = [item for item in CheckDraft.model_validate(result.data).findings if item.quote.strip() and item.fix.strip()]
    return found[: prompt_data.number(_DATA, "max_items")]


__all__ = [
    "CONFLICT", "ENABLED_ENV", "KINDS", "LABEL", "LASTING", "CheckDraft", "Finding", "build_check_prompt", "changes_of", "check",
    "context_changes", "earlier_lasting", "enabled", "field", "kind_of", "plan_block", "table_before",
]

# -*- coding: utf-8 -*-
"""The script supervisor's look at a one-episode film against itself.

A serial is checked episode by episode against what earlier episodes settled (``story_state``). A short
film has no earlier episode, and its mistakes are inside the one it has: an errand run twice, a number that
changes between the premise and the dialogue, a question put on screen and never answered. So its planned
shots are read once against the settled facts (the overview), the episode's own outline and each other.

Findings go back to the planner once; whatever is still wrong after that is kept as notes for the editor.
The check must never cost the film its episode: no usable answer counts as agreement. Wording, budgets
and limits are ``app/data/prompt/script_self_check.json``; ``SCREENWRITING_SELF_CHECK`` turns it off.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import settings
from app.core import prompt_data
from app.core.screenwriting.structured_llm import LLMCaller, StructuredOutputError, call_structured
from app.core.screenwriting.violations import DraftViolation

logger = logging.getLogger("app.core.screenwriting.self_check")

_DATA = "script_self_check"
ENABLED_ENV = "SCREENWRITING_SELF_CHECK"
LABEL = "script_self_check"
CONFLICT = "episode_self_conflict"
# The kinds of film that are one complete episode, and the one source whose text is not ours to rewrite.
_SINGLE_EPISODE_KINDS = frozenset({"film"})
_AUTHORED = "screenplay"


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


class Finding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene_id: str = Field(default="", description="the shot at fault; empty for the episode as a whole")
    quote: str = Field(default="", description="the line or action at fault")
    problem: str = Field(default="", description="what it disagrees with")
    fix: str = Field(default="", description="how to mend it, in a sentence")

    def reason(self) -> str:
        """The finding as the model (send-back) and the editor (note) read it."""
        return _text("reason" if self.scene_id.strip() else "reason_whole").format(**self.model_dump())


class CheckDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    findings: list[Finding] = Field(default_factory=list)


def enabled() -> bool:
    return settings.env_flag(ENABLED_ENV, True)


def applies(creation: Mapping[str, Any] | None, source_kind: str = "") -> bool:
    """Whether this project's episodes are checked against themselves: a short film we wrote, with the check on."""
    kind = str((creation or {}).get("creation_mode") or "")
    return enabled() and kind in _SINGLE_EPISODE_KINDS and str(source_kind or "") != _AUTHORED


def facts(overview: Mapping[str, Any] | None, ledger: Mapping[str, Any] | None) -> tuple[list[str], list[str]]:
    """``(settled facts, the episode's outline)`` as lines: what the shots are read against."""
    overview = overview if isinstance(overview, Mapping) else {}
    ledger = ledger if isinstance(ledger, Mapping) else {}
    settled = [
        _text("fact_line").format(label=label, text=str(overview[key]).strip())
        for key, label in prompt_data.value(_DATA, "fact_labels") if str(overview.get(key) or "").strip()
    ]
    outline = [_text("beat_item").format(text=str(beat).strip()) for beat in ledger.get("story_beats") or [] if str(beat).strip()]
    if str(ledger.get("hook") or "").strip():
        outline.append(_text("fact_line").format(label=_text("ending_label"), text=str(ledger["hook"]).strip()))
    return settled, outline


def _shots_text(scenes: Sequence[Mapping[str, Any]]) -> str:
    limit = prompt_data.number(_DATA, "description_chars")
    lines: list[str] = []
    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        cast = _text("name_separator").join(str(name) for name in scene.get("characters_in_scene") or []) or _text("none")
        lines.append(_text("shot").format(scene_id=scene.get("scene_id") or "", setting=scene.get("setting") or "", cast=cast))
        description = str(scene.get("scene_description") or "").strip()
        if description:
            lines.append(_text("description").format(description=description[:limit]))
        for utterance in scene.get("utterances") or []:
            if not isinstance(utterance, Mapping) or not str(utterance.get("text") or "").strip():
                continue
            if utterance.get("kind") == "voiceover":
                lines.append(_text("voiceover").format(text=utterance["text"]))
            else:
                lines.append(_text("dialogue").format(speaker=utterance.get("speaker") or "", text=utterance["text"]))
    return "\n".join(lines)


def build_check_prompt(*, episode: int, settled: Sequence[str], outline: Sequence[str], scenes: Sequence[Mapping[str, Any]]) -> str:
    return (
        f"{_text('head').format(episode=episode)}\n\n<facts>\n" + ("\n".join(settled) or _text("none")) + "\n</facts>\n\n"
        "<outline>\n" + ("\n".join(outline) or _text("none")) + f"\n</outline>\n\n<shots>\n{_shots_text(scenes)}\n</shots>"
    )


def check(
    caller: LLMCaller, *, episode: int, settled: Sequence[str], outline: Sequence[str], scenes: Sequence[Mapping[str, Any]],
    temperature: float | None = None, max_tokens: int | None = None,
) -> list[Finding]:
    """Ask once whether the shots agree with the facts and with each other; no usable answer counts as agreement.

    ``max_tokens`` is the output ceiling of the call. A model that reasons before it answers spends the same
    budget on both, and a short ceiling leaves no answer at all — which would read as agreement — so the engine
    passes its own (large) ceiling; the table's number is only the fallback."""
    try:
        result = call_structured(
            caller, system_prompt=_text("system"),
            user_prompt=build_check_prompt(episode=episode, settled=settled, outline=outline, scenes=scenes), schema=CheckDraft,
            max_tokens=max(int(max_tokens or 0), prompt_data.number(_DATA, "max_tokens")), attempts=2, label=f"{LABEL}_E{episode}",
            temperature=temperature,
        )
    except StructuredOutputError as error:
        logger.warning("[Screenwriting] self-check of episode %s gave no usable answer; taken as agreement: %s", episode, "; ".join(error.reasons)[:200])
        return []
    found = [item for item in CheckDraft.model_validate(result.data).findings if item.quote.strip() and item.fix.strip()]
    return found[: prompt_data.number(_DATA, "max_items")]


PlanResult = tuple[dict[str, Any], list[DraftViolation], list[str], Any]


def checked(
    result: PlanResult, *, caller: LLMCaller, creation: Mapping[str, Any] | None, source_kind: str, episode: int,
    overview: Mapping[str, Any] | None, ledger: Mapping[str, Any] | None, replan: Callable[[dict[str, Any]], PlanResult],
    label: str, temperature: float | None = None, max_tokens: int | None = None,
) -> PlanResult:
    """``result`` (a planned episode) after the self-check: unchanged when the check does not apply or finds nothing.

    ``replan`` plans the episode again from a repair request (the findings and the plan they are about); its answer
    replaces the plan only when it is not a quarantined draft, and is then checked once more."""
    plan, warnings, flagged, draft = result
    if draft is not None or not applies(creation, source_kind):
        return result
    settled, outline = facts(overview, ledger)
    ask = dict(episode=episode, settled=settled, outline=outline, temperature=temperature, max_tokens=max_tokens)
    found = check(caller, scenes=plan["scenes"], **ask)
    if not found:
        return result
    try:
        again = replan({"reasons": [item.reason() for item in found], "plan": plan, "error_count": 0})
    except RuntimeError as error:  # the planner could not do better: the first plan stands
        logger.warning("[Screenwriting] self-check repair of episode %s failed; the first plan stands: %s", episode, str(error)[:200])
        again = None
    if again is not None and again[3] is None:
        plan, warnings, flagged, draft = again
        found = check(caller, scenes=plan["scenes"], **ask)
    notes = [DraftViolation(CONFLICT, item.reason(), label, "warning", item.scene_id.strip() or None) for item in found]
    return plan, [*warnings, *notes], flagged, draft


__all__ = ["CONFLICT", "ENABLED_ENV", "LABEL", "CheckDraft", "Finding", "applies", "build_check_prompt", "check", "checked", "enabled", "facts"]

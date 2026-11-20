# -*- coding: utf-8 -*-
"""Rewrite a few consecutive shots of one episode, and say what the change breaks.

The person picks shots in an episode's plan and says how to change them. One text call rewrites
only those shots (each keeps its id and length; the shots around them are context). A second,
separate call compares before and after against the cross-episode sheet (``story_state``): what
this episode was supposed to leave behind, and what later episodes pay off, use or pick up. It
reports what no longer has a source, and writes this episode's sheet as it should read afterwards.

Nothing is written here. Adopting the rewrite goes through the plan edit (optimistic revision,
downstream invalidation, re-authoring only the changed shots); updating the sheet is a separate,
optional write of this episode's ``state_changes``. Asking again with ``keep`` set to what the
last version lost is how the person makes the rewrite hold on to it.

Every sentence and budget is ``app/data/prompt/passage_rewrite.json``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core import prompt_data
from app.core.screenwriting import story_state
from app.core.screenwriting.structured_llm import LLMCaller, StructuredOutputError, call_structured

logger = logging.getLogger("app.core.screenwriting.passage_rewrite")

_DATA = "passage_rewrite"
LABEL = "passage_rewrite"
IMPACT_LABEL = "passage_rewrite_impact"
EDITED_FIELDS = ("setting", "characters_in_scene", "scene_description", "utterances")
# One send-back with the validator's reasons, then the person is told what still did not fit.
REWRITE_ATTEMPTS = 2


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _number(key: str) -> int:
    return int(prompt_data.number(_DATA, key))


class PassageError(ValueError):
    """The request cannot be served as asked (unknown shots, a gap in the selection, no instruction)."""


# ---------------------------------------------------------------------------- what the models answer


class RewrittenUtterance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str = "dialogue"
    speaker: str | None = None
    text: str = ""
    delivery: str | None = None


class RewrittenShot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene_id: str = ""
    setting: str = ""
    characters_in_scene: list[str] = Field(default_factory=list)
    scene_description: str = ""
    utterances: list[RewrittenUtterance] = Field(default_factory=list)


class RewriteDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scenes: list[RewrittenShot] = Field(default_factory=list)


class ImpactFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    episode: int = 0
    fact: str = ""
    quote: str = ""
    fix: str = ""


class ImpactDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    findings: list[ImpactFinding] = Field(default_factory=list)
    state_changes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------- choosing the passage


def select(scenes: Sequence[Mapping[str, Any]], scene_ids: Sequence[str], *, episode: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """(the chosen shots in plan order, the shot before them, the shot after them).

    The chosen shots must be consecutive: a rewrite reads as one passage, and the shots around it
    are what it has to join up with.
    """
    order = [dict(scene) for scene in scenes if isinstance(scene, Mapping)]
    wanted = [str(item).strip() for item in scene_ids if str(item or "").strip()]
    positions = {str(scene.get("scene_id")): index for index, scene in enumerate(order)}
    missing = [item for item in wanted if item not in positions]
    if not wanted or missing:
        raise PassageError(_text("no_scenes").format(episode=episode, ids=_text("name_separator").join(missing or wanted) or _text("none")))
    limit = _number("max_scenes")
    if len(set(wanted)) > limit:
        raise PassageError(_text("too_many").format(limit=limit, count=len(set(wanted))))
    indexes = sorted({positions[item] for item in wanted})
    if indexes[-1] - indexes[0] + 1 != len(indexes):
        raise PassageError(_text("not_contiguous").format(ids=_text("name_separator").join(wanted)))
    before = order[indexes[0] - 1] if indexes[0] > 0 else None
    after = order[indexes[-1] + 1] if indexes[-1] + 1 < len(order) else None
    return [order[index] for index in indexes], before, after


# ---------------------------------------------------------------------------- how shots read in a prompt


def shot_text(scene: Mapping[str, Any], *, limit: int | None = None) -> str:
    cast = _text("name_separator").join(str(name) for name in scene.get("characters_in_scene") or []) or _text("none")
    lines = [_text("shot_head").format(
        scene_id=scene.get("scene_id") or "", seconds=scene.get("duration_seconds") or "", setting=scene.get("setting") or "", cast=cast,
    )]
    description = str(scene.get("scene_description") or "").strip()
    if description:
        lines.append(_text("shot_description").format(text=description))
    for utterance in scene.get("utterances") or []:
        if not isinstance(utterance, Mapping) or not str(utterance.get("text") or "").strip():
            continue
        if utterance.get("kind") == "voiceover":
            lines.append(_text("shot_voiceover").format(text=utterance["text"]))
        else:
            lines.append(_text("shot_dialogue").format(speaker=utterance.get("speaker") or "", text=utterance["text"]))
    key_line = str(scene.get("key_line") or "").strip()
    if key_line:
        lines.append(_text("shot_key_line").format(text=key_line))
    text = "\n".join(lines)
    return text[:limit] if limit else text


def _shots_text(scenes: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(shot_text(scene) for scene in scenes)


# ---------------------------------------------------------------------------- the rewrite


def build_rewrite_prompt(
    *, episode: int, chosen: Sequence[Mapping[str, Any]], before: Mapping[str, Any] | None, after: Mapping[str, Any] | None,
    sheet: Sequence[str], cast: Sequence[str], instruction: str, keep: Sequence[str] = (),
) -> str:
    neighbour = _number("neighbour_chars")
    parts = [_text("rewrite_head").format(episode=episode, count=len(chosen))]
    parts.append(_text("instruction_wrap").format(text=instruction.strip()[: _number("instruction_chars")]))
    kept = [item.strip() for item in keep if str(item or "").strip()]
    if kept:
        parts.append(_text("keep_wrap").format(lines="\n".join(_text("item").format(text=item) for item in kept)))
    if cast:
        parts.append(_text("cast_wrap").format(names=_text("name_separator").join(cast)))
    if sheet:
        # The same sheet, wording and "carry on from it" rule an episode's shot plan is given.
        parts.append(story_state.plan_block(sheet=sheet, previous_outline=[], landing=[]).strip())
    if before:
        parts.append(_text("before_wrap").format(text=shot_text(before, limit=neighbour)))
    parts.append(_text("selected_wrap").format(text=_shots_text(chosen)))
    if after:
        parts.append(_text("after_wrap").format(text=shot_text(after, limit=neighbour)))
    return "\n\n".join(parts)


def _rewrite_validator(chosen: Sequence[Mapping[str, Any]], cast: Sequence[str]):
    wanted = [str(scene.get("scene_id")) for scene in chosen]
    key_lines = {str(scene.get("scene_id")): str(scene.get("key_line") or "").strip() for scene in chosen}
    known = {str(name) for name in cast}

    def check(data: dict[str, Any]) -> list[str]:
        shots = [shot for shot in data.get("scenes") or [] if isinstance(shot, Mapping)]
        got = [str(shot.get("scene_id") or "") for shot in shots]
        if sorted(got) != sorted(wanted):
            return [_text("problem_ids").format(wanted=_text("name_separator").join(wanted), got=_text("name_separator").join(got) or _text("none"))]
        problems: list[str] = []
        for shot in shots:
            scene_id = str(shot.get("scene_id"))
            if not str(shot.get("scene_description") or "").strip():
                problems.append(_text("problem_empty").format(scene_id=scene_id))
            strangers = [str(name) for name in shot.get("characters_in_scene") or [] if known and str(name) not in known]
            if strangers:
                problems.append(_text("problem_cast").format(scene_id=scene_id, names=_text("name_separator").join(strangers)))
            key_line = key_lines.get(scene_id) or ""
            spoken = {str((item or {}).get("text") or "").strip() for item in shot.get("utterances") or [] if isinstance(item, Mapping)}
            if key_line and key_line not in spoken:
                problems.append(_text("problem_key_line").format(scene_id=scene_id, text=key_line))
        return problems

    return check


def _fields_of(shot: Mapping[str, Any]) -> dict[str, Any]:
    """The edited fields of one rewritten shot, shaped the way the plan edit takes them."""
    utterances = []
    for item in shot.get("utterances") or []:
        if not isinstance(item, Mapping) or not str(item.get("text") or "").strip():
            continue
        kind = "voiceover" if str(item.get("kind") or "").strip().lower() in {"voiceover", "旁白", "narration"} else "dialogue"
        speaker = str(item.get("speaker") or "").strip() or None
        utterances.append({
            "kind": kind, "speaker": None if kind == "voiceover" else speaker,
            "text": str(item["text"]).strip(), "delivery": (str(item.get("delivery") or "").strip() or None),
        })
    return {
        "setting": str(shot.get("setting") or "").strip(),
        "characters_in_scene": [str(name).strip() for name in shot.get("characters_in_scene") or [] if str(name or "").strip()],
        "scene_description": str(shot.get("scene_description") or "").strip(),
        "utterances": utterances,
    }


def rewrite(
    caller: LLMCaller, *, episode: int, chosen: Sequence[Mapping[str, Any]], before: Mapping[str, Any] | None, after: Mapping[str, Any] | None,
    sheet: Sequence[str], cast: Sequence[str], instruction: str, keep: Sequence[str] = (), max_tokens: int, temperature: float | None = None,
) -> list[dict[str, Any]]:
    """The chosen shots rewritten, in plan order: ``{scene_id, before, after}`` with the edited fields only."""
    if not instruction.strip():
        raise PassageError(_text("no_instruction"))
    try:
        result = call_structured(
            caller, system_prompt=_text("rewrite_system"),
            user_prompt=build_rewrite_prompt(episode=episode, chosen=chosen, before=before, after=after, sheet=sheet, cast=cast, instruction=instruction, keep=keep),
            schema=RewriteDraft, max_tokens=max_tokens, attempts=REWRITE_ATTEMPTS, validators=(_rewrite_validator(chosen, cast),),
            label=f"{LABEL}_E{episode}", temperature=temperature,
        )
    except StructuredOutputError as error:
        raise RuntimeError(_text("failed").format(attempts=REWRITE_ATTEMPTS, reasons=_text("reason_separator").join(error.reasons)[:300])) from error
    by_id = {shot.scene_id: shot.model_dump() for shot in RewriteDraft.model_validate(result.data).scenes}
    return [
        {"scene_id": str(scene.get("scene_id")), "before": {field: scene.get(field) for field in EDITED_FIELDS}, "after": _fields_of(by_id[str(scene.get("scene_id"))])}
        for scene in chosen
    ]


# ---------------------------------------------------------------------------- what the change breaks


def own_changes(ledger: Sequence[Any], episode: int) -> list[str]:
    row = next((entry for entry in ledger or [] if isinstance(entry, Mapping) and int(entry.get("episode") or 0) == int(episode)), None)
    return story_state.changes_of(row)


def later_lines(ledger: Sequence[Any], episode: int) -> list[str]:
    """Later episodes as the check reads them, nearest first, within ``later_chars``: title, sheet, a few beats."""
    budget = _number("later_chars")
    beats = _number("beats_per_episode")
    rows = sorted(
        (entry for entry in ledger or [] if isinstance(entry, Mapping) and int(entry.get("episode") or 0) > int(episode)),
        key=lambda entry: int(entry.get("episode") or 0),
    )
    lines: list[str] = []
    used = 0
    for entry in rows:
        block = [_text("later_episode").format(episode=int(entry.get("episode") or 0), title=str(entry.get("title") or ""))]
        changes = story_state.changes_of(entry)
        if changes:
            block.append(_text("later_changes").format(text=_text("later_separator").join(changes)))
        block.extend(_text("later_beat").format(text=str(beat)) for beat in (entry.get("story_beats") or [])[:beats] if str(beat or "").strip())
        size = sum(len(line) for line in block)
        if lines and used + size > budget:
            break
        lines.extend(block)
        used += size
    return lines


def build_impact_prompt(*, episode: int, before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]], own: Sequence[str], later: Sequence[str]) -> str:
    own_lines = "\n".join(_text("item").format(text=item) for item in own) or _text("none")
    return "\n\n".join([
        _text("impact_head").format(episode=episode),
        _text("old_wrap").format(text=_shots_text(before)),
        _text("new_wrap").format(text=_shots_text(after)),
        _text("own_wrap").format(lines=own_lines),
        _text("later_wrap").format(lines="\n".join(later) or _text("none")),
    ])


def impact(
    caller: LLMCaller, *, episode: int, before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]], own: Sequence[str], later: Sequence[str],
    max_tokens: int, temperature: float | None = None,
) -> dict[str, Any]:
    """``{findings, state_changes, checked}``. No usable answer leaves the sheet as it was and says it was not checked."""
    try:
        result = call_structured(
            caller, system_prompt=_text("impact_system").format(episode=episode),
            user_prompt=build_impact_prompt(episode=episode, before=before, after=after, own=own, later=later),
            schema=ImpactDraft, max_tokens=max_tokens, attempts=2, label=f"{IMPACT_LABEL}_E{episode}", temperature=temperature,
        )
    except StructuredOutputError as error:
        logger.warning("[Screenwriting] impact check of a rewrite in episode %s gave no usable answer: %s", episode, "; ".join(error.reasons)[:200])
        return {"findings": [], "state_changes": list(own), "checked": False}
    draft = ImpactDraft.model_validate(result.data)
    findings = [
        {"episode": item.episode if item.episode > 0 else int(episode), "fact": item.fact.strip(), "quote": item.quote.strip(), "fix": item.fix.strip()}
        for item in draft.findings if item.fact.strip() and item.fix.strip()
    ][: _number("max_findings")]
    changes = [item.strip() for item in draft.state_changes if item.strip()]
    return {"findings": findings, "state_changes": changes if changes or not own else list(own), "checked": True}


def lost_key_lines(rows: Sequence[Mapping[str, Any]], chosen: Sequence[Mapping[str, Any]]) -> list[str]:
    """Key lines the rewrite no longer speaks (the validator asks for them; this is the last word)."""
    after = {row["scene_id"]: row["after"] for row in rows}
    lost: list[str] = []
    for scene in chosen:
        key_line = str(scene.get("key_line") or "").strip()
        spoken = {str(item.get("text") or "").strip() for item in (after.get(str(scene.get("scene_id"))) or {}).get("utterances") or []}
        if key_line and key_line not in spoken:
            lost.append(_text("finding_key_line").format(text=key_line))
    return lost


def offline_text() -> str:
    return _text("offline")


__all__ = [
    "EDITED_FIELDS", "IMPACT_LABEL", "LABEL", "PassageError", "build_impact_prompt", "build_rewrite_prompt", "impact", "later_lines",
    "lost_key_lines", "offline_text", "own_changes", "rewrite", "select", "shot_text",
]

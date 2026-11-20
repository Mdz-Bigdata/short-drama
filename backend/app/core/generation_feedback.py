# -*- coding: utf-8 -*-
"""What to do when a generated shot comes back wrong.

A person watching a clip says "脸崩了" or "手是六根手指" — not "reduce the clear
character count to two". This turns that sentence into a category, a fix plan the
shot workspace can apply, and a line in the project's ledger.

Two things make it a loop rather than a form:

- **One kind of change per round.** Every fix belongs to one class of variable — the action
  (what the bodies do), the camera (size, setup, axis, cut points) or the reference material
  (first frame, character and weapon images, the gap between first and last frame); sound has
  its own. A retry changes one class only, so the next result says whether that class was the
  problem, and it gives something up in that class in a fixed order. Two rounds in one class
  without improvement mean the failure was put in the wrong class: the next round turns to another.
  A sound failure that no class fixes ends by taking the dialogue out of the video model: the
  clip is rendered without the line and the line is dubbed in post.
- **Memory.** The same failure twice on the same model becomes a weakness on that
  model's profile, and a fix that worked twice becomes a project pattern. Both are
  replayed as preventive notes the next time a shot like that is generated.

The variable classes, the round discipline and the fight symptoms are adapted, in this project's own
words, from the diagnostics reference of the MIT ``fight-prompt-director`` skill vendored in
``backend/skills/fight-prompt-director``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from app.core import prompt_data

Result = Literal["success", "partial", "failed"]
# A failure seen this many times on one model is treated as that model's weakness.
PROMOTE_AFTER = 2
LEDGER_KEY = "5_feedback"
MAX_HISTORY_PER_SHOT = 20


# The failure catalogue's names, trigger words, diagnoses, fixes, negatives and prevention, the
# escalation ladders, the class names and every sentence a fix plan says:
# app/data/prompt/generation_feedback.json.
_WORDING = "generation_feedback"


def _entry(key: str) -> Any:
    """A top-level entry of the wording table, used as it stands."""
    return prompt_data.value(_WORDING, key)


def _says(key: str, /, **values: object) -> str:
    """A sentence of the wording table's ``says``, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(_entry("says")[key]).format(**values)


Variable = Literal["action", "camera", "reference", "sound"]
# What each class of variable is called where a person reads it: ``variable_names``.
VARIABLE_NAMES: dict[str, str] = {variable: str(_entry("variable_names")[variable]) for variable in get_args(Variable)}
# Two rounds in one class with no improvement: the failure was filed under the wrong class.
STALL_ROUNDS = 2
# Where to look next when a class has been tried and did not help.
RECONSIDER_ORDER: dict[str, tuple[str, ...]] = {
    "action": ("camera", "reference"),
    "camera": ("action", "reference"),
    "reference": ("action", "camera"),
    "sound": ("action",),
}


@dataclass(frozen=True)
class Fix:
    """One concrete change, and the class of variable it touches."""

    variable: Variable
    text: str


def _fixes(variable: Variable, *texts: str) -> tuple[Fix, ...]:
    return tuple(Fix(variable, text) for text in texts)


@dataclass(frozen=True)
class Failure:
    """One way a generated shot goes wrong, and what to do about it."""

    id: str
    name: str
    triggers: tuple[str, ...]
    diagnosis: str
    # The class to change first; ``fixes`` may also hold fixes of other classes for later rounds.
    variable: Variable
    fixes: tuple[Fix, ...]
    # Knobs the shot workspace can actually turn.
    negatives: tuple[str, ...] = ()
    prevention: str = ""


# Every failure the reports can name, in the order a report is matched against them: its id, the
# class to change first, and the classes its fixes touch, in the order the fixes are listed. The
# name, trigger words, diagnosis, fix texts, negatives and prevention of each are in the wording
# table under ``failures.<id>``.
_CATALOGUE: tuple[tuple[str, Variable, tuple[Variable, ...]], ...] = (
    ("face_collapse", "action", ("action", "camera", "reference")),
    ("hand_failure", "action", ("action", "camera")),
    ("occlusion", "action", ("action", "camera")),
    ("action_blur", "action", ("action", "camera")),
    ("colour_drift", "reference", ("reference", "camera")),
    ("spatial_break", "camera", ("camera", "action")),
    ("style_drift", "reference", ("reference",)),
    # Before expression_failure: 「表情突变」 and 「眼神呆滞」 name these, not a stiff face.
    ("face_flip", "action", ("action", "camera")),
    ("dead_eyes", "action", ("action", "camera")),
    ("floating", "action", ("action", "camera")),
    ("expression_failure", "action", ("action", "camera")),
    ("lip_sync", "sound", ("sound",)),
    ("audio_muddy", "sound", ("sound",)),
    ("wrong_speaker", "sound", ("sound",)),
    ("sfx_timing", "sound", ("sound", "action")),
    # Fight symptoms: each names the class to look at first and the change to make there.
    ("action_dwindle", "action", ("action",)),
    ("contact_unclear", "camera", ("camera", "action")),
    ("fight_disconnected", "action", ("action",)),
    ("jump_cut", "camera", ("camera",)),
    ("body_merge", "reference", ("reference", "action")),
    ("weapon_failure", "reference", ("reference",)),
    ("weightless_hit", "action", ("action",)),
    ("damage_reset", "action", ("action",)),
    ("endframe_warp", "reference", ("reference",)),
    ("vfx_unsourced", "action", ("action",)),
    # Timeline symptoms (when things happen rather than what): see the clip timeline rules.
    ("early_action", "action", ("action",)),
    ("missed_cut", "camera", ("camera",)),
    ("silent_mouth", "sound", ("sound",)),
    ("crammed_actions", "action", ("action", "camera")),
    ("tail_extra", "action", ("action",)),
)


def _failure(failure_id: str, variable: Variable, fix_classes: tuple[Variable, ...]) -> Failure:
    """One catalogue entry, worded from ``failures.<id>`` of the wording table."""
    entry = _entry("failures")[failure_id]
    return Failure(
        failure_id, str(entry["name"]), tuple(str(word) for word in entry["triggers"]),
        diagnosis=str(entry["diagnosis"]),
        variable=variable,
        fixes=tuple(fix for kind in fix_classes for fix in _fixes(kind, *(str(text) for text in entry["fixes"][kind]))),
        negatives=tuple(str(term) for term in entry["negatives"]),
        prevention=str(entry["prevention"]),
    )


FAILURES: tuple[Failure, ...] = tuple(_failure(*item) for item in _CATALOGUE)
_BY_ID = {failure.id: failure for failure in FAILURES}

# What a class gives up when a shot keeps failing in it, in this order: ``escalation.<class>``.
ESCALATION: dict[str, tuple[str, ...]] = {
    variable: tuple(str(rung) for rung in _entry("escalation")[variable]) for variable in VARIABLE_NAMES
}


def _walk(primary: str, rounds: Sequence[tuple[str, bool]]) -> tuple[str | None, int, list[str]]:
    """Which class this round changes, how many rounds that class already had, and which were dropped.

    ``rounds`` are the earlier retries, oldest first: the class each one changed and whether the
    result after it improved. A round in another class (a change made by hand) does not count.
    """
    order = [primary, *RECONSIDER_ORDER.get(primary, ())]
    index, spent, stalled, dropped = 0, 0, 0, []
    for variable, improved in rounds:
        if index >= len(order) or variable != order[index]:
            continue
        spent += 1
        stalled = 0 if improved else stalled + 1
        if stalled >= STALL_ROUNDS:
            dropped.append(order[index])
            index, spent, stalled = index + 1, 0, 0
    return (order[index] if index < len(order) else None), spent, dropped


@dataclass
class FailureMatch:
    failure: Failure
    matched: str


@dataclass
class FixPlan:
    """What to do with this shot next."""

    primary: Failure
    secondary: list[Failure] = field(default_factory=list)
    attempt: int = 1
    steps: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)
    escalation: str = ""
    give_up: bool = False
    # The one class of variable this round changes; empty once every class has been tried.
    variable: str = ""
    # Classes already tried for two rounds without improvement, oldest first.
    reconsidered: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "category": self.primary.id, "category_name": self.primary.name,
            "diagnosis": self.primary.diagnosis,
            "secondary": [item.id for item in self.secondary],
            "attempt": self.attempt, "steps": list(self.steps),
            "negatives": list(self.negatives), "escalation": self.escalation,
            "give_up": self.give_up,
            "variable": self.variable, "variable_name": VARIABLE_NAMES.get(self.variable, ""),
            "reconsidered": list(self.reconsidered),
        }


def get_failure(failure_id: str) -> Failure | None:
    return _BY_ID.get(str(failure_id or "").strip().lower())


def classify(text: str) -> list[FailureMatch]:
    """Every failure the report names, in the order the words appear."""
    haystack = str(text or "").lower()
    hits: list[tuple[int, FailureMatch]] = []
    for failure in FAILURES:
        found = [(haystack.find(word.lower()), word) for word in failure.triggers if word.lower() in haystack]
        if found:
            position, word = min(found)
            hits.append((position, FailureMatch(failure=failure, matched=word)))
    return [match for _, match in sorted(hits, key=lambda item: item[0])]


def plan_fix(
    text: str = "", *, category: str = "", attempt: int = 1, rounds: Sequence[tuple[str, bool]] | None = None,
) -> FixPlan | None:
    """The fix for this report; ``None`` when nothing in it names a known failure.

    ``rounds`` are the earlier retries on this shot (class changed, improved afterwards); without
    them every earlier retry is taken to have followed the plan and not helped.
    """
    matches = classify(text)
    chosen = get_failure(category) or (matches[0].failure if matches else None)
    if chosen is None:
        return None
    secondary = [match.failure for match in matches if match.failure.id != chosen.id][:2]
    attempt = max(1, int(attempt or 1))
    if rounds is None:
        rounds = []
        for _ in range(attempt - 1):
            variable, _, _ = _walk(chosen.variable, rounds)
            if variable is None:
                break
            rounds.append((variable, False))
    variable, spent, dropped = _walk(chosen.variable, rounds)
    steps: list[str] = []
    escalation = ""
    give_up = variable is None
    if give_up:
        tried = prompt_data.text(_WORDING, "list_separator").join(VARIABLE_NAMES[item] for item in dropped)
        if chosen.variable == "sound":
            # 声音修不好就不再让视频模型出声：画面照拍，对白与音效全部后期合成。
            steps.append(_says("give_up_sound", tried=tried, rounds=STALL_ROUNDS))
        else:
            steps.append(_says("give_up_picture", tried=tried, rounds=STALL_ROUNDS))
    else:
        if dropped:
            steps.append(_says(
                "reconsidered", rounds=STALL_ROUNDS, dropped=VARIABLE_NAMES[dropped[-1]], variable=VARIABLE_NAMES[variable],
            ))
        steps.extend(fix.text for fix in chosen.fixes if fix.variable == variable)
        # The first round in the failure's own class is the fix itself; every later round, and the
        # first round in a class turned to after a stall, gives something up in that class.
        ladder = ESCALATION[variable]
        rung = spent - 1 if variable == chosen.variable else spent
        if rung >= 0:
            escalation = ladder[min(rung, len(ladder) - 1)]
            steps.append(_says("escalation_step", attempt=attempt, escalation=escalation))
        others = prompt_data.text(_WORDING, "list_separator").join(
            name for key, name in VARIABLE_NAMES.items() if key != variable and key != "sound"
        )
        steps.append(_says("this_round_only", variable=VARIABLE_NAMES[variable], others=others))
    return FixPlan(
        primary=chosen, secondary=secondary, attempt=attempt, steps=steps,
        negatives=list(dict.fromkeys([*chosen.negatives, *(term for item in secondary for term in item.negatives)])),
        escalation=escalation, give_up=give_up, variable=variable or "", reconsidered=dropped,
    )


_RESULT_RANK = {"failed": 0, "partial": 1, "success": 2}


def _rounds(history: Sequence[Mapping[str, Any]], result: str) -> list[tuple[str, bool]]:
    """Earlier retries on one shot: the class each plan changed, and whether the next report was better."""
    entries = [entry for entry in history if entry.get("result") != "success"]
    rounds: list[tuple[str, bool]] = []
    for index, entry in enumerate(entries):
        variable = str(entry.get("variable") or "")
        if not variable:
            # Ledgers written before the variable classes: the category's own class.
            failure = get_failure(str(entry.get("category") or ""))
            variable = failure.variable if failure else ""
        if not variable:
            continue
        after = entries[index + 1].get("result") if index + 1 < len(entries) else result
        rounds.append((variable, _RESULT_RANK.get(str(after), 0) > _RESULT_RANK.get(str(entry.get("result")), 0)))
    return rounds


# ---------------------------------------------------------------------------------------------
# The ledger


def _ledger(task: Mapping[str, Any]) -> dict:
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    stored = assets.get(LEDGER_KEY)
    ledger = stored if isinstance(stored, dict) else {}
    ledger.setdefault("shots", {})
    ledger.setdefault("model_profiles", {})
    ledger.setdefault("patterns", [])
    ledger.setdefault("stats", {"reports": 0, "success": 0, "partial": 0, "failed": 0})
    return ledger


def _scene_shot_key(key: str) -> str:
    """The key an older ledger filed this shot under: its number within the scene.

    Reports now arrive under the drama-wide shot number (集·100000 + 场·100 + 镜, see
    ``episode_cycle.shot_uid``), because every scene numbers its shots from 1. The first
    report under the new number takes the old entries along, so the attempts keep counting.
    """
    return str(int(key) % 100) if key.isdigit() and int(key) >= 100000 else ""


def record(
    task: dict[str, Any], *, shot_id: Any, result: Result, text: str = "", category: str = "", model: str = "",
    applied_fix: str = "",
) -> dict:
    """Write one report into the project's ledger and return what to do next.

    A failure seen twice on the same model becomes that model's weakness; a fix that
    worked twice becomes a project pattern. Both are replayed later as prevention.
    """
    assets = task.setdefault("assets", {})
    ledger = _ledger(task)
    key = str(shot_id)
    if key not in ledger["shots"]:
        earlier = _scene_shot_key(key)
        ledger["shots"][key] = ledger["shots"].pop(earlier, []) if earlier else []
    history = ledger["shots"][key]
    attempt = sum(1 for entry in history if entry.get("result") != "success") + 1

    plan = (
        plan_fix(text, category=category, attempt=attempt, rounds=_rounds(history, result))
        if result != "success" else None
    )
    entry = {
        "result": result, "text": str(text or "")[:500], "model": str(model or ""),
        "category": plan.primary.id if plan else "", "attempt": attempt,
        "variable": plan.variable if plan else "",
        "applied_fix": str(applied_fix or "")[:300],
    }
    history.append(entry)
    del history[:-MAX_HISTORY_PER_SHOT]

    stats = ledger["stats"]
    stats["reports"] = int(stats.get("reports", 0)) + 1
    stats[result] = int(stats.get(result, 0)) + 1

    if plan is not None and model:
        profile = ledger["model_profiles"].setdefault(model, {"counts": {}, "weaknesses": []})
        counts = profile["counts"]
        counts[plan.primary.id] = int(counts.get(plan.primary.id, 0)) + 1
        if counts[plan.primary.id] >= PROMOTE_AFTER and plan.primary.id not in profile["weaknesses"]:
            profile["weaknesses"].append(plan.primary.id)
    if result == "success" and applied_fix:
        worked = [item for item in ledger["patterns"] if item.get("fix") == applied_fix]
        if worked:
            worked[0]["hits"] = int(worked[0].get("hits", 1)) + 1
        else:
            ledger["patterns"].append({"fix": applied_fix, "hits": 1})

    assets[LEDGER_KEY] = ledger
    return {"ledger": ledger, "plan": plan.as_dict() if plan else None, "attempt": attempt}


def weaknesses(task: Mapping[str, Any], model: str) -> list[Failure]:
    """What this model has already proved it is bad at on this project."""
    profile = _ledger(task)["model_profiles"].get(str(model or ""), {})
    return [failure for failure in (get_failure(item) for item in profile.get("weaknesses", [])) if failure]


def preventive_notes(task: Mapping[str, Any], model: str) -> list[str]:
    """Lines to put in the next prompt, so a known weakness is designed around."""
    notes = [
        _says("weakness_note", name=failure.name, prevention=failure.prevention)
        for failure in weaknesses(task, model) if failure.prevention
    ]
    patterns = [
        item["fix"] for item in _ledger(task)["patterns"]
        if isinstance(item, Mapping) and int(item.get("hits", 0)) >= PROMOTE_AFTER and item.get("fix")
    ]
    notes.extend(_says("pattern_note", fix=fix) for fix in patterns[:3])
    return notes


def preventive_negatives(task: Mapping[str, Any], model: str) -> list[str]:
    """Negative terms a known weakness earns, added on top of the usual ones."""
    return list(dict.fromkeys(term for failure in weaknesses(task, model) for term in failure.negatives))


def summary(task: Mapping[str, Any]) -> dict:
    """The ledger as the workspace shows it."""
    ledger = _ledger(task)
    by_category: dict[str, int] = {}
    for entries in ledger["shots"].values():
        for entry in entries:
            if entry.get("category"):
                by_category[entry["category"]] = by_category.get(entry["category"], 0) + 1
    return {
        "stats": dict(ledger["stats"]),
        "top_failures": [
            {"category": key, "name": _BY_ID[key].name if key in _BY_ID else key, "count": count}
            for key, count in sorted(by_category.items(), key=lambda item: -item[1])[:5]
        ],
        "model_profiles": {
            model: {
                "weaknesses": [
                    {"category": item, "name": _BY_ID[item].name if item in _BY_ID else item}
                    for item in profile.get("weaknesses", [])
                ],
            }
            for model, profile in ledger["model_profiles"].items()
        },
        "patterns": [item for item in ledger["patterns"] if int(item.get("hits", 0)) >= PROMOTE_AFTER],
        "shots": {
            shot: {"attempts": len(entries), "last": entries[-1] if entries else None}
            for shot, entries in ledger["shots"].items()
        },
    }


def describe() -> list[dict]:
    """The catalogue the reporting UI shows."""
    return [
        {
            "id": failure.id, "name": failure.name, "triggers": list(failure.triggers),
            "diagnosis": failure.diagnosis, "variable": failure.variable,
            "fixes": [fix.text for fix in failure.fixes],
            "fix_variables": [fix.variable for fix in failure.fixes],
            "negatives": list(failure.negatives),
        }
        for failure in FAILURES
    ]


__all__ = [
    "ESCALATION", "FAILURES", "LEDGER_KEY", "PROMOTE_AFTER", "RECONSIDER_ORDER", "STALL_ROUNDS", "VARIABLE_NAMES",
    "Failure", "FailureMatch", "Fix", "FixPlan", "classify", "describe", "get_failure", "plan_fix", "preventive_negatives", "preventive_notes",
    "record", "summary", "weaknesses",
]

# -*- coding: utf-8 -*-
"""A text model as the director of a stage: it plans first, the rules check what it planned.

Three things run on the same contract, a JSON reply carrying the stage's own semantic operations:

- ``plan_candidates`` asks for several complete stagings of a scene (set, marks, poses, lenses, moves),
  repairs and scores each and recommends one. The rule planner's stage is kept as the comparison and the fallback.
- ``run_turn`` is one message of a conversation: the model edits a working copy, reads back what its edit did to
  the checks and the frame, and goes again until it is satisfied or out of rounds. Nothing is saved here.
- ``read_model_reply`` reads one object written part by part, for the model library.

Every sentence sent to a model or shown to a person is in ``app/data/prompt/stage_director_ai.json``.
Nothing here calls a provider: ``llm(system, user, max_tokens)`` is handed in, so every path can be driven by a
stub, and an operation a model got wrong costs that operation with its error sent back rather than the whole turn.

The shape of the conversation, a transaction per turn with its result read back, an optional scope of selected
objects, is what mangfufu/director-desk's built-in assistant does (``desktop/ai-conversation.cjs``, MIT); its prompts
are not used. The text / image / pose / object generation split is described in GuiYi-Xi/monoform-previs-studio's
README; that repository has no licence, so none of its code or prompts were read. Set-dressing and lens rules are
taken from the MIT-licensed arjun988/blender-skills vendored under ``backend/skills/blender-skills``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.screenwriting.structured_llm import extract_json_object
from app.core import project_memory, prompt_data
from app.core.spatial_stage import model_kit, repair, scoring
from app.core.spatial_stage.models import StagePlan
from app.core.spatial_stage.operations import MAX_OPERATIONS, StageEditError, apply_operations

logger = logging.getLogger(__name__)

LLM = Callable[[str, str, int], "str | None"]

PLAN_MAX_TOKENS = 8000
TURN_MAX_TOKENS = 6000
MODEL_MAX_TOKENS = 4000
MAX_TURN_ROUNDS = 3
MAX_CANDIDATES = 3
MAX_MESSAGE = 2000
_DIGEST_LANDMARKS = 60
_DIGEST_SHOTS = 40
_FAILED_OP_COST = 3.0
_FAILED_OP_LIMIT = 15.0

_WORDING = "stage_director_ai"


def _says(key: str, /, **values: object) -> str:
    """A sentence of ``stage_director_ai.json``'s ``says`` with its values filled in."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _text(key: str) -> str:
    """A text of ``stage_director_ai.json`` used as it stands (its braces are JSON examples, not placeholders)."""
    return prompt_data.text(_WORDING, key)


def _log(key: str) -> str:
    """A log line of ``stage_director_ai.json``, filled in by the logger."""
    return str(prompt_data.load(_WORDING)["logs"][key])


# The ids the desk draws (``lib/poses.ts`` holds their angles) and what each is called.
POSE_PRESETS: tuple[tuple[str, str], ...] = prompt_data.pairs("stage_poses", "presets")

STRATEGIES: tuple[tuple[str, str], ...] = prompt_data.pairs(_WORDING, "strategies")

OP_GUIDE = (
    _text("op_guide_people")
    + _says("pose_choices", poses=_text("list_separator").join(_says("pose_choice", preset=key, label=label) for key, label in POSE_PRESETS))
    + _text("op_guide_set_and_lens")
)

_RULES = _text("rules")


class DirectorAIError(ValueError):
    """The model gave nothing usable; the stage is untouched."""


@dataclass
class Applied:
    plan: StagePlan
    applied: list[Mapping[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Scope:
    """What a person selected: the turn may only touch these. Empty means the whole stage."""

    names: tuple[str, ...] = ()
    shot_id: int | None = None

    @property
    def limited(self) -> bool:
        return bool(self.names) or self.shot_id is not None

    def describe(self) -> str:
        if not self.limited:
            return ""
        words = []
        if self.names:
            words.append(_says("scope_names", names=_text("list_separator").join(self.names)))
        if self.shot_id is not None:
            words.append(_says("scope_shot", shot_id=self.shot_id))
        return _says("scope", selection=_text("clause_separator").join(words))


_SKILL_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("set-dressing", ("Density Rules", "Cluster Method")),
    ("prop-artist", ("Design Principles",)),
    ("camera-cinematography", ("Lens Guide", "Composition Checklist")),
)
# Asked for by what the scene is, each under the same budget.
_SKILL_ROUTES: tuple[tuple[tuple[str, ...], str, tuple[str, ...]], ...] = tuple(
    (tuple(str(word) for word in route["words"]), str(route["skill"]), tuple(str(heading) for heading in route["headings"]))
    for route in prompt_data.value(_WORDING, "skill_routes")
)
_SKILL_BUDGET = 2400


def _skills_dir() -> Path:
    from app import settings

    return Path(settings.skills_root()) / "blender-skills"


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else ""


def craft_notes(scene_text: str = "") -> str:
    """Craft rules for this kind of scene from the vendored skills; empty when they are not installed."""
    wanted = list(_SKILL_SECTIONS) + [
        (skill, headings) for words, skill, headings in _SKILL_ROUTES if any(word in scene_text for word in words)
    ]
    chunks: list[str] = []
    used = 0
    for skill, headings in wanted:
        try:
            text = (_skills_dir() / skill / "SKILL.md").read_text(encoding="utf-8")
        except OSError:
            continue
        for heading in headings:
            body = _section(text, heading)
            if body and used + len(body) <= _SKILL_BUDGET:
                chunks.append(f"[{skill} · {heading}]\n{body}")
                used += len(body)
    return "\n\n".join(chunks)


def digest(plan: StagePlan) -> str:
    """The stage as a model should read it: positions, lenses and what each lens actually sees."""
    actors = [
        {
            "name": actor.name, "position": actor.position, "yaw": actor.yaw_deg, "posture": actor.posture, "role": actor.role,
            "height": actor.height_m, "figure": actor.figure, **({"pose": actor.pose.preset} if actor.pose and actor.pose.preset else {}),
        }
        for actor in plan.actors if not actor.crowd_id
    ]
    pieces = [
        {
            "name": piece.name, "kind": piece.kind, "position": piece.position, "size": piece.size, "yaw": piece.yaw_deg,
            **({"kit": piece.kit} if piece.kit else {}), **({"elevation": piece.elevation_m} if piece.elevation_m else {}),
        }
        for piece in plan.landmarks[:_DIGEST_LANDMARKS]
    ]
    cameras = {camera.id: camera for camera in plan.cameras}
    shots = []
    for shot in plan.shots[:_DIGEST_SHOTS]:
        camera = cameras.get(shot.camera_id)
        seen = [
            {"name": state.name, "x": round(state.x, 2), "h": round(state.height_fraction, 2), **({"hidden_by": state.occluded_by} if state.occluded_by else {})}
            if state.visible else {"name": state.name, "out_of_frame": True}
            for state in shot.screen if camera and state.name in camera.subjects
        ]
        shots.append({
            "shot_id": shot.shot_id, "action": shot.action[:100], "speaker": shot.speaker, "subjects": shot.subjects,
            **({"camera": {
                "id": camera.id, "position": camera.position, "target": camera.target, "lens_mm": camera.lens_mm,
                "size": camera.shot_size, "angle": camera.angle, "function": camera.function, "move": camera.move.kind,
            }} if camera else {}),
            "sees": seen,
            **({"overrides": [item.name for item in shot.overrides]} if shot.overrides else {}),
        })
    state = {
        "location": plan.location, "aspect": plan.aspect_ratio, "actors": actors,
        **({"crowds": [{"id": crowd.id, "label": crowd.label, "rows": crowd.rows, "columns": crowd.columns, "center": crowd.center} for crowd in plan.crowds]} if plan.crowds else {}),
        "set": pieces,
        **({"set_more": len(plan.landmarks) - _DIGEST_LANDMARKS} if len(plan.landmarks) > _DIGEST_LANDMARKS else {}),
        "axis": {"kind": plan.axis.kind, "from": plan.axis.from_name, "to": plan.axis.to_name, "side": plan.axis.camera_side},
        "shots": shots,
    }
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def _report(plan: StagePlan) -> str:
    """What the checks and the score say about a stage right now."""
    measured = scoring.score_plan(plan)
    lines = [_says("report_score", score=measured["score"])]
    lines += [
        _says("report_failed", code=check.code, severity=check.severity, detail=check.detail[:200])
        for check in plan.checks if not check.passed
    ]
    lines += [_says("report_note", note=item) for item in measured["notes"]]
    return "\n".join(lines)


def _salvage_operations(text: str) -> dict[str, Any] | None:
    """A reply cut off inside its list keeps every operation it finished."""
    opening = text.find('"operations"')
    bracket = text.find("[", opening) if opening >= 0 else -1
    if bracket < 0:
        return None
    decoder = json.JSONDecoder()
    index, operations = bracket + 1, []
    while True:
        while index < len(text) and text[index] in " \r\n\t,":
            index += 1
        if index >= len(text) or text[index] != "{":
            break
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            break
        operations.append(value)
    return {"operations": operations, "done": False} if operations else None


def read_reply(text: Any) -> dict[str, Any] | None:
    """The JSON object of a reply, or what can be saved of one; a sentence with no JSON comes back as a reply."""
    body = str(text or "").strip()
    if not body:
        return None
    parsed = extract_json_object(body) or _salvage_operations(body)
    if parsed is None:
        return {"reply": body[:2000], "operations": [], "done": True, "remember": [], "title": "", "rationale": ""}
    operations = parsed.get("operations")
    return {
        "reply": str(parsed.get("reply") or parsed.get("rationale") or "")[:2000],
        "title": str(parsed.get("title") or "")[:60],
        "rationale": str(parsed.get("rationale") or parsed.get("reply") or "")[:600],
        "operations": [item for item in operations if isinstance(item, Mapping)][:MAX_OPERATIONS] if isinstance(operations, list) else [],
        "done": parsed.get("done") is not False,
        "remember": parsed.get("remember") if isinstance(parsed.get("remember"), list) else [],
    }


_OP_NAME_KEYS = ("name", "first", "second", "anchor", "target")
_ALWAYS_ALLOWED = frozenset({"repair_checks"})


def out_of_scope(op: Mapping[str, Any], scope: Scope, plan: StagePlan) -> str:
    """Why this operation reaches past what a person selected; empty when it does not."""
    if not scope.limited or str(op.get("op")) in _ALWAYS_ALLOWED:
        return ""
    if scope.shot_id is not None:
        if op.get("shot_id") is not None and int(op["shot_id"]) != scope.shot_id:
            return _says("out_of_shot", shot_id=scope.shot_id)
        camera_id = op.get("camera_id")
        shot = next((item for item in plan.shots if item.shot_id == scope.shot_id), None)
        if camera_id and shot is not None and camera_id != shot.camera_id and camera_id not in shot.alt_camera_ids:
            return _says("out_of_shot_camera", shot_id=scope.shot_id)
    if scope.names:
        kind = str(op.get("op"))
        if kind in ("orient_toward", "set_path", "auto_route"):
            touched = [op.get("name") or op.get("target")]
        elif kind in ("face_pair",):
            touched = [op.get("first"), op.get("second")]
        elif kind == "arrange_group":
            touched = list(op.get("names") or [])
        else:
            touched = [op.get("name")] if op.get("name") else []
        strays = [str(name) for name in touched if name and name not in scope.names and name != "camera"]
        if strays:
            return _says("out_of_names", names=_text("list_separator").join(strays))
    return ""


def apply_each(plan: StagePlan, operations: Sequence[Mapping[str, Any]], scope: Scope = Scope()) -> Applied:
    """Apply one by one, so a wrong operation costs itself and its error can go back to the model."""
    outcome = Applied(plan=plan)
    for index, op in enumerate(operations, start=1):
        reason = out_of_scope(op, scope, plan)
        if reason:
            outcome.errors.append(_says("op_error", index=index, op=op.get("op"), reason=reason))
            continue
        try:
            outcome.plan = apply_operations(outcome.plan, [op])
        except StageEditError as error:
            outcome.errors.append(_says("op_error", index=index, op=op.get("op"), reason=str(error)[:240]))
            continue
        except Exception as error:  # noqa: BLE001 - a model's op must not be able to fail the turn
            logger.warning(_log("op_crashed"), op.get("op"), error)
            outcome.errors.append(_says("op_error", index=index, op=op.get("op"), reason=_text("op_invalid")))
            continue
        outcome.applied.append(op)
    return outcome


def _mannequins_for_poses(plan: StagePlan) -> StagePlan:
    """A pose on a stand-in draws nothing; whoever a model posed gets a figure that shows it."""
    shot_poses = {item.name for shot in plan.shots for item in shot.overrides if item.pose}
    posed = [
        {"op": "set_figure", "name": actor.name, "figure": "mannequin"}
        for actor in plan.actors
        if actor.figure == "standin" and not actor.crowd_id and (actor.pose or actor.name in shot_poses)
    ]
    return apply_operations(plan, posed) if posed else plan


def polish(plan: StagePlan) -> StagePlan:
    """What needs no model: fix what the rules can fix, then look for better lenses. Never returns something worse."""
    current = plan
    for step in ({"op": "repair_checks"}, {"op": "best_camera"}):
        try:
            trial = apply_operations(current, [step])
        except (StageEditError, ValueError):
            continue
        if scoring.score_plan(trial)["score"] >= scoring.score_plan(current)["score"]:
            current = trial
    return current


def _system(extra: str = "", scene_text: str = "") -> str:
    craft = craft_notes(scene_text)
    return (
        _says("system", guide=OP_GUIDE, catalog=model_kit.catalog_text(), rules=_RULES)
        + (_says("system_craft", craft=craft) if craft else "")
        + (f"\n\n{extra}" if extra else "")
    )


_PLAN_FORMAT = _text("plan_format")


@dataclass
class Candidate:
    id: str
    title: str
    rationale: str
    source: str  # "model" or "rules"
    plan: StagePlan
    measured: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    rounds: int = 1

    def as_dict(self, *, with_plan: bool = True) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "rationale": self.rationale, "source": self.source,
            "score": self.measured["score"], "measured": self.measured, "errors": self.errors[:12], "rounds": self.rounds,
            **({"plan": self.plan.model_dump(mode="json")} if with_plan else {}),
        }


def _strategies(count: int) -> Sequence[tuple[str, str]]:
    return STRATEGIES[:max(1, min(count, len(STRATEGIES)))]


def plan_prompt(baseline: StagePlan, scene_text: str, strategy: tuple[str, str], goal: str = "", memory: str = "") -> str:
    return (
        _says("plan_script", script=scene_text[:6000])
        + (f"{memory}\n\n" if memory else "")
        + _says("plan_baseline", stage=digest(baseline), name=strategy[0], direction=strategy[1])
        + (_says("plan_goal", goal=goal.strip()[:MAX_MESSAGE]) if goal.strip() else "")
        + f"\n{_PLAN_FORMAT}"
    )


def build_candidate(
    baseline: StagePlan, scene_text: str, strategy: tuple[str, str], llm: LLM, index: int, goal: str = "", memory: str = "",
) -> Candidate | None:
    """One complete staging from the model, or None when it gave nothing that could be used."""
    system = _system(scene_text=scene_text)
    prompt = plan_prompt(baseline, scene_text, strategy, goal, memory)
    reply = read_reply(llm(system, prompt, PLAN_MAX_TOKENS))
    if not reply or not reply["operations"]:
        return None
    done = apply_each(baseline, reply["operations"])
    if not done.applied:
        logger.warning(_log("plan_failed"), strategy[0], len(reply["operations"]), done.errors[:3])
        return None
    plan, errors, rounds = done.plan, done.errors, 1
    # One round to answer for what failed: the errors are specific, and a fix is much cheaper than a new plan.
    failing = repair.failing(plan.checks) or scoring.score_plan(plan)["notes"]
    if errors or failing:
        follow_up = (
            _says("follow_up", stage=digest(plan), report=_report(plan))
            + (_says("follow_up_errors", errors="\n".join(errors)) if errors else "")
            + _text("follow_up_ask")
        )
        again = read_reply(llm(system, follow_up, TURN_MAX_TOKENS))
        rounds = 2
        if again and again["operations"]:
            fixed = apply_each(plan, again["operations"])
            if scoring.score_plan(fixed.plan)["score"] >= scoring.score_plan(plan)["score"]:
                plan, errors = fixed.plan, fixed.errors
    plan = polish(_mannequins_for_poses(plan))
    return Candidate(
        id=f"model-{index + 1}", title=reply["title"] or strategy[0], rationale=reply["rationale"],
        source="model", plan=plan.model_copy(update={"planner": "model", "planner_note": reply["rationale"][:600]}),
        measured=scoring.score_plan(plan), errors=errors, rounds=rounds,
    )


def rank(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Model plans first unless they still break a check the rule plan does not: a passing plan always beats a failing one.

    Among those, what the model meant counts: a plan most of whose operations failed is mostly the baseline it started from.
    """
    return sorted(candidates, key=lambda item: (
        item.measured["errors"] > 0 or item.measured["standing"] > 0, item.source != "model",
        -(item.measured["score"] - min(_FAILED_OP_LIMIT, _FAILED_OP_COST * len(item.errors))),
    ))


def rules_candidate(baseline: StagePlan) -> Candidate:
    plan = polish(baseline)
    return Candidate(
        id="rules", title=_text("rules_title"), rationale=_text("rules_rationale"),
        source="rules", plan=plan, measured=scoring.score_plan(plan), rounds=0,
    )


def run_turn(
    plan: StagePlan, message: str, llm: LLM, *, history: Sequence[Mapping[str, Any]] = (), scope: Scope = Scope(),
    scene_text: str = "", max_rounds: int = MAX_TURN_ROUNDS, memory: str = "",
) -> dict[str, Any]:
    """One message: edit a working copy until the model is done or the rounds run out; nothing is saved."""
    system = _system(_text("turn_format") + project_memory.REMEMBER_INSTRUCTION, scene_text)
    past = "\n".join(
        _says(
            "history_line", speaker=_text("speaker_user") if item.get("role") == "user" else _text("speaker_model"),
            text=str(item.get("text") or "")[:400],
        )
        for item in history[-8:]
    )
    working, errors, reply_text, applied = plan, [], "", []
    remembered: list[Any] = []
    rounds = 0
    feedback = ""
    for rounds in range(1, max(1, max_rounds) + 1):
        # The script and the past conversation do not change between rounds of one turn: once is enough.
        prompt = (
            (_says("turn_script", script=scene_text[:3000]) if scene_text and rounds == 1 else "")
            + (f"{memory}\n\n" if memory and rounds == 1 else "")
            + (_says("turn_history", history=past) if past and rounds == 1 else "")
            + _says("turn_stage", stage=digest(working), report=_report(working))
            + (f"{scope.describe()}\n" if scope.limited else "")
            + _says("turn_message", message=message.strip()[:MAX_MESSAGE])
            + (f"\n\n{feedback}" if feedback else "")
        )
        reply = read_reply(llm(system, prompt, TURN_MAX_TOKENS))
        if reply is None:
            if rounds == 1:
                raise DirectorAIError(_text("no_reply"))
            break
        reply_text = reply["reply"] or reply_text
        remembered.extend(reply["remember"])
        if not reply["operations"]:
            break
        before = set(repair.failing(working.checks))
        done = apply_each(working, reply["operations"], scope)
        working, errors = done.plan, done.errors
        applied.extend(done.applied)
        introduced = set(repair.failing(working.checks)) - before
        if reply["done"] and not errors and not introduced:
            break
        feedback = (
            _text("feedback_head")
            + (_says("feedback_errors", errors="\n".join(errors)) if errors else "")
            + (_says("feedback_introduced", codes=_text("list_separator").join(sorted(introduced))) if introduced else "")
            + _text("feedback_ask")
        )
    return {
        "reply": reply_text or (_text("turn_changed") if applied else _text("turn_unchanged")),
        "plan": working, "applied": applied, "errors": errors, "rounds": rounds, "remember": remembered,
    }


OPTIMIZE_MESSAGE = _text("optimize_message")


def optimize(plan: StagePlan, llm: LLM | None, *, goal: str = "", scene_text: str = "", scope: Scope = Scope(), memory: str = "") -> dict[str, Any]:
    """Make the stage better: rules first, then the model; a result that scores lower is thrown away."""
    start = scoring.score_plan(plan)
    best = polish(plan) if not scope.limited else plan
    reply = _text("optimize_rules")
    applied: list[Mapping[str, Any]] = []
    errors: list[str] = []
    rounds = 0
    used_model = False
    if llm is not None:
        try:
            outcome = run_turn(best, goal.strip() or OPTIMIZE_MESSAGE, llm, scope=scope, scene_text=scene_text, memory=memory)
        except DirectorAIError:
            reply += _text("optimize_model_silent")
        else:
            used_model, errors, rounds = True, outcome["errors"], outcome["rounds"]
            trial = _mannequins_for_poses(outcome["plan"]) if outcome["applied"] else outcome["plan"]
            if scoring.score_plan(trial)["score"] >= scoring.score_plan(best)["score"]:
                best, applied, reply = trial, outcome["applied"], outcome["reply"]
            else:
                reply = _text("optimize_model_worse")
    finish = scoring.score_plan(best)
    if finish["score"] < start["score"]:
        best, finish = plan, start
    return {
        "plan": best, "reply": reply, "applied": applied, "errors": errors, "rounds": rounds, "used_model": used_model,
        "before": start, "after": finish,
    }


_MODEL_SYSTEM = _text("model_system")
_MODEL_FORMAT = _text("model_format")


def model_prompt(description: str, size: Sequence[float] | None = None) -> tuple[str, str]:
    craft = craft_notes(description)
    user = _says("model_user", format=_MODEL_FORMAT, catalog=model_kit.catalog_text(), description=description.strip()[:MAX_MESSAGE])
    if size:
        user += _says("model_size", width=size[0], depth=size[1], height=size[2])
    return _MODEL_SYSTEM + (f"\n\n{craft}" if craft else ""), user


def read_model_reply(text: Any, description: str, size: Sequence[float] | None = None) -> dict[str, Any]:
    """A proposal for one object: its name, overall size and parts, ready for ``add_landmark``."""
    data = extract_json_object(str(text or ""))
    if data is None:
        raise DirectorAIError(_text("model_unreadable"))
    name = str(data.get("name") or description).strip()[:40] or _text("model_default_name")
    kind = data.get("kind") if data.get("kind") in ("prop", "furniture", "architecture", "light") else "prop"
    kit_id = str(data.get("kit") or "").strip()
    try:
        if data.get("parts"):
            parts, overall, dropped = model_kit.read_parts(data["parts"], size)
            kit = ""
        elif kit_id:
            found, parts, overall = model_kit.build_kit(kit_id, size)
            kit, kind, dropped = found.id, found.kind, 0
        else:
            raise DirectorAIError(_text("model_no_parts"))
    except model_kit.ModelKitError as error:
        raise DirectorAIError(str(error)) from error
    return {
        "name": name, "kind": kind, "kit": kit, "size": overall, "summary": str(data.get("summary") or "")[:200],
        "parts": [part.model_dump(mode="json") for part in parts], "dropped": dropped,
    }


__all__ = [
    "Applied", "Candidate", "DirectorAIError", "LLM", "MAX_CANDIDATES", "MAX_MESSAGE", "MODEL_MAX_TOKENS", "OP_GUIDE", "POSE_PRESETS",
    "PLAN_MAX_TOKENS", "STRATEGIES", "Scope", "TURN_MAX_TOKENS", "apply_each", "build_candidate", "craft_notes", "digest", "model_prompt",
    "optimize", "out_of_scope", "plan_prompt", "polish", "rank", "read_model_reply", "read_reply", "rules_candidate", "run_turn",
]

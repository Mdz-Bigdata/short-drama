# -*- coding: utf-8 -*-
"""Turn a failing spatial check into the edit that would clear it.

The checks in :mod:`validation` say what is wrong; this module says what to do about it, as
ordinary desk operations — the same ones a person issues by hand — so a proposal can be shown,
applied through the normal patch path, undone, and audited. Nothing here moves anything on its
own: :func:`propose` only reads, and the ``repair_checks`` operation applies what it proposes.

What each check gets:

* ``spatial_actor_spacing`` — the crowded people are pushed apart along the lines joining them.
* ``spatial_facing_partner`` — whoever looks away from their scene partner is turned to face them.
* ``spatial_screen_sides_stable`` (when the scene *opens* mirrored) — the pair swap marks, so the
  promised screen left / right holds without touching a single camera.
* ``spatial_subjects_in_frame``, ``spatial_subject_occlusion``, ``spatial_move_keeps_subjects``,
  ``spatial_camera_clearance``, ``spatial_axis_consistent`` — the offending shot's lens is solved
  again from its own brief (size, angle, subjects); the solver already frames everyone, keeps
  clear of the foreground and stays on the established side of the axis.
* ``spatial_set_clearance`` — the lens is searched for a place near where it stands from which the
  set no longer hides the shot's subjects (``best_camera``); a lens with keys, one that serves
  several shots, or one with no clear place nearby is left to a person. People are never moved
  out of a set piece: someone seated on a bed or riding a sedan chair is inside one on purpose.
* ``spatial_action_changes_state`` — a posture the storyboard names is written as that shot's
  override. A walk the storyboard names cannot be invented: that needs a mark or a drawn path,
  and the proposal says so instead of guessing.
* ``spatial_contact_kept`` (「贴合接触」) — the contact resolver is applied to the stored marks again:
  the held prop is put back in the hand, the thing back on its support, the sitter back on the seat.
  A seat nobody can sit on, or a holder who is not on the set in a shot, is left to a person.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core import prompt_data
from app.core.spatial_stage import contacts as contact_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage import scoring
from app.core.spatial_stage.language import posture_in, travel_in
from app.core.spatial_stage.models import StageCheck, StagePlan
from app.core.spatial_stage.validation import MIN_ACTOR_SPACING_M, contact_findings, set_blockers
from app.core.spatial_stage.wording import phrase, posture_zh

# A little more than the check demands, so a repaired pair does not sit exactly on the limit.
SPACING_TARGET_M = round(MIN_ACTOR_SPACING_M + 0.1, 3)
_LENS_CODES = frozenset({
    "spatial_subjects_in_frame", "spatial_subject_occlusion", "spatial_move_keeps_subjects",
    "spatial_camera_clearance", "spatial_axis_consistent",
})
_WORDING = "stage_checks"
# The button each repair is shown under on the desk, by check code.
LABELS: dict[str, str] = {
    str(code): str(label) for code, label in prompt_data.load(_WORDING)["repairs"]["labels"].items()
}


def _says(key: str, **values: object) -> str:
    """A repair sentence (``app/data/prompt/stage_checks.json``), filled in."""
    return str(prompt_data.load(_WORDING)["repairs"][key]).format(**values)


@dataclass(frozen=True)
class Repair:
    """One failing check and the operations that would clear it (or why none can)."""

    code: str
    label: str
    detail: str
    shot_ids: list[int] = field(default_factory=list)
    operations: list[dict[str, Any]] = field(default_factory=list)
    # Set when the check needs a person: what they have to decide.
    manual: str = ""

    @property
    def automatic(self) -> bool:
        return bool(self.operations)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "label": self.label, "detail": self.detail, "shot_ids": list(self.shot_ids),
            "operations": [dict(op) for op in self.operations], "manual": self.manual, "automatic": self.automatic,
        }


def _wanted(check: StageCheck, codes: Iterable[str] | None, shot_ids: Iterable[int] | None) -> bool:
    if check.passed:
        return False
    if codes is not None and check.code not in set(codes):
        return False
    if shot_ids is not None:
        wanted = {int(item) for item in shot_ids}
        # A scene-wide check (no shot ids) is asked for by any shot.
        if check.shot_ids and not wanted.intersection(check.shot_ids):
            return False
    return True


def _spacing(plan: StagePlan, check: StageCheck) -> Repair:
    solid = [actor for actor in plan.actors if actor.role != "crowd"]
    points = [(actor.position[0], actor.position[1]) for actor in solid]
    spread = geo.separate(points, SPACING_TARGET_M)
    operations = [
        {"op": "move_actor", "name": actor.name, "position": geo.rounded(point)}
        for actor, before, point in zip(solid, points, spread)
        if geo.distance(before, point) > 1e-3
    ]
    names = "、".join(op["name"] for op in operations)
    return Repair(
        check.code, LABELS[check.code],
        _says("spacing", names=names, target=SPACING_TARGET_M) if operations else check.detail,
        operations=operations,
        manual="" if operations else _says("spacing_manual"),
    )


def _facing(plan: StagePlan, check: StageCheck) -> Repair:
    pair = [plan.actor(plan.axis.from_name), plan.actor(plan.axis.to_name)]
    operations: list[dict[str, Any]] = []
    if all(pair):
        for actor, partner in ((pair[0], pair[1]), (pair[1], pair[0])):
            toward = geo.unit(geo.sub((partner.position[0], partner.position[1]), (actor.position[0], actor.position[1])))
            if geo.dot(geo.forward_of(actor.yaw_deg), toward) < 0.82:
                operations.append({"op": "orient_toward", "name": actor.name, "target": partner.name})
    names = "、".join(op["name"] for op in operations)
    return Repair(
        check.code, LABELS[check.code],
        _says("facing", names=names) if operations else check.detail,
        operations=operations,
        manual="" if operations else _says("facing_manual"),
    )


def _screen_sides(plan: StagePlan, check: StageCheck) -> Repair:
    if check.severity != "error":
        return Repair(
            check.code, LABELS[check.code], check.detail, shot_ids=list(check.shot_ids),
            manual=_says("screen_sides_after_crossing_manual"),
        )
    first, second = plan.actor(plan.axis.from_name), plan.actor(plan.axis.to_name)
    if first is None or second is None:
        return Repair(
            check.code, LABELS[check.code], check.detail, shot_ids=list(check.shot_ids), manual=_says("screen_sides_missing_manual"),
        )
    operations = [
        {"op": "move_actor", "name": first.name, "position": list(second.position), "yaw_deg": second.yaw_deg},
        {"op": "move_actor", "name": second.name, "position": list(first.position), "yaw_deg": first.yaw_deg},
    ]
    return Repair(
        check.code, LABELS[check.code], _says("screen_sides", first=first.name, second=second.name),
        shot_ids=list(check.shot_ids), operations=operations,
    )


def _lens(plan: StagePlan, check: StageCheck) -> Repair:
    shots = [shot_id for shot_id in check.shot_ids if plan.shot(shot_id) is not None]
    if not shots:
        return Repair(check.code, LABELS[check.code], check.detail, manual=_says("lens_manual"))
    operations = [{"op": "solve_camera", "shot_id": shot_id} for shot_id in shots]
    labels = "、".join(phrase("shot_named", shot=shot_id) for shot_id in shots)
    return Repair(
        check.code, LABELS[check.code],
        _says("lens", shots=labels),
        shot_ids=shots, operations=operations,
    )


def _set_clearance(plan: StagePlan, check: StageCheck) -> Repair:
    operations: list[dict[str, Any]] = []
    stuck: list[int] = []
    for shot_id in check.shot_ids:
        shot = plan.shot(shot_id)
        camera = plan.camera(shot.camera_id) if shot is not None else None
        if shot is None or camera is None:
            continue
        timeline = plan.timelines.get(str(shot.shot_id))
        # What ``best_camera`` will not touch: a lens animated by keys, and one several shots look through.
        searchable = not (timeline is not None and timeline.camera) and sum(other.camera_id == camera.id for other in plan.shots) == 1
        found = scoring.candidate_cameras(plan, shot, limit=1) if searchable else []
        better = scoring.best_lens_is_worth_it(found, camera, scoring.score_shot(plan, shot)[0])
        if better and not set_blockers(plan, shot, found[0][1]):
            operations.append({"op": "best_camera", "shot_id": shot.shot_id})
        else:
            stuck.append(shot.shot_id)
    moved = "、".join(phrase("shot_named", shot=op["shot_id"]) for op in operations)
    left = "、".join(phrase("shot_named", shot=shot_id) for shot_id in stuck)
    return Repair(
        check.code, LABELS[check.code],
        phrase("set_clearance_repair", shots=moved) if operations else check.detail,
        shot_ids=list(check.shot_ids), operations=operations,
        manual=phrase("set_clearance_manual", shots=left) if stuck else "",
    )


def _action(plan: StagePlan, check: StageCheck) -> Repair:
    operations: list[dict[str, Any]] = []
    manual: list[str] = []
    walkers = {item.name for shot in plan.shots for item in shot.overrides if item.position is not None and not item.hold}
    for shot in plan.shots:
        if check.shot_ids and shot.shot_id not in check.shot_ids:
            continue
        changes = {item.name: item for item in shot.overrides}
        for actor in plan.actors_in(shot):
            if actor.role == "crowd":
                continue
            change = changes.get(actor.name)
            moved = change is not None and change.position is not None
            if travel_in(actor.name, shot.action) and actor.name not in walkers:
                manual.append(_says("walk_manual", shot=shot.shot_id, name=actor.name))
            implied = posture_in(actor.name, shot.action, None)
            if implied and not moved and implied != actor.posture:
                current = change or None
                operation: dict[str, Any] = {
                    "op": "set_shot_override", "shot_id": shot.shot_id, "name": actor.name, "posture": implied,
                    # The reason is read back in the shot's blocking sentence, so it names the posture in Chinese.
                    "reason": phrase("posture_named", posture=posture_zh(implied)),
                }
                if current is not None:
                    # set_shot_override rewrites the whole override: carry what it already says.
                    if current.position is not None:
                        operation["position"] = list(current.position)
                    if current.yaw_deg is not None:
                        operation["yaw_deg"] = current.yaw_deg
                    operation["offstage"] = current.offstage
                    operation["hold"] = current.hold
                    if current.reason:
                        operation["reason"] = current.reason
                operations.append(operation)
    done = "；".join(_says("posture", shot=op["shot_id"], name=op["name"], posture=posture_zh(op["posture"])) for op in operations)
    return Repair(
        check.code, LABELS[check.code],
        _says("postures_done", changes=done) if done else check.detail,
        shot_ids=list(check.shot_ids), operations=operations, manual="；".join(manual)[:1900],
    )


def _contacts(plan: StagePlan, check: StageCheck) -> Repair:
    findings = contact_findings(plan)
    actors, landmarks = contact_rules.settle(plan.actors, plan.landmarks, plan.contacts)
    operations: list[dict[str, Any]] = []
    if any(kind == "settle" for kind, _, _ in findings):
        for before, after in zip(plan.actors, actors):
            if geo.distance(tuple(before.position), tuple(after.position)) > 1e-3 or before.posture != after.posture:
                operations.append({"op": "move_actor", "name": after.name, "position": list(after.position), "posture": after.posture})
        for before, after in zip(plan.landmarks, landmarks):
            if (
                geo.distance(tuple(before.position), tuple(after.position)) > 1e-3
                or abs(before.elevation_m - after.elevation_m) > 1e-3 or abs(before.yaw_deg - after.yaw_deg) > 1e-3
            ):
                operations.append({
                    "op": "transform_landmark", "name": after.name, "position": list(after.position),
                    "elevation_m": after.elevation_m, "yaw_deg": after.yaw_deg,
                })
    manual = "；".join(text for kind, _, text in findings if kind == "manual")
    return Repair(
        check.code, LABELS[check.code],
        _says("contact", names="、".join(op["name"] for op in operations)) if operations else check.detail,
        shot_ids=list(check.shot_ids), operations=operations,
        manual=_says("contact_manual", findings=manual[:1800]) if manual else "",
    )


_HANDLERS = {
    "spatial_actor_spacing": _spacing,
    "spatial_facing_partner": _facing,
    "spatial_screen_sides_stable": _screen_sides,
    "spatial_action_changes_state": _action,
    "spatial_set_clearance": _set_clearance,
    "spatial_contact_kept": _contacts,
    **{code: _lens for code in _LENS_CODES},
}


def propose(
    plan: StagePlan, *, codes: Iterable[str] | None = None, shot_ids: Iterable[int] | None = None,
) -> list[Repair]:
    """A repair per failing check of ``plan`` (whose checks must be current), in check order."""
    repairs: list[Repair] = []
    for check in plan.checks:
        if not _wanted(check, codes, shot_ids):
            continue
        handler = _HANDLERS.get(check.code)
        if handler is None:
            repairs.append(Repair(
                check.code, _says("unhandled"), check.detail, shot_ids=list(check.shot_ids), manual=_says("unhandled_manual"),
            ))
            continue
        repairs.append(handler(plan, check))
    return repairs


def combined_operations(repairs: Sequence[Repair]) -> list[dict[str, Any]]:
    """Every proposed operation once, in proposal order: two checks may ask for the same lens solve."""
    seen: set[str] = set()
    operations: list[dict[str, Any]] = []
    for repair in repairs:
        for operation in repair.operations:
            key = json.dumps(operation, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            operations.append(dict(operation))
    return operations


def summary(repairs: Sequence[Repair]) -> dict[str, Any]:
    automatic = [item for item in repairs if item.automatic]
    manual = [item for item in repairs if not item.automatic]
    return {
        "repairs": [item.as_dict() for item in repairs],
        "operations": combined_operations(repairs),
        "automatic": len(automatic),
        "manual": len(manual),
    }


def failing(checks: Sequence[StageCheck] | Sequence[Mapping[str, Any]]) -> list[str]:
    codes: list[str] = []
    for item in checks:
        code = item.code if isinstance(item, StageCheck) else str(item.get("code") or "")
        passed = item.passed if isinstance(item, StageCheck) else bool(item.get("passed"))
        if code and not passed:
            codes.append(code)
    return codes


__all__ = ["LABELS", "SPACING_TARGET_M", "Repair", "combined_operations", "failing", "propose", "summary"]

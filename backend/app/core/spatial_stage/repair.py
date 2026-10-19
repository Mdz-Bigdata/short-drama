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
* ``spatial_action_changes_state`` — a posture the storyboard names is written as that shot's
  override. A walk the storyboard names cannot be invented: that needs a mark or a drawn path,
  and the proposal says so instead of guessing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.language import posture_in, travel_in
from app.core.spatial_stage.models import StageCheck, StagePlan
from app.core.spatial_stage.validation import MIN_ACTOR_SPACING_M

# A little more than the check demands, so a repaired pair does not sit exactly on the limit.
SPACING_TARGET_M = round(MIN_ACTOR_SPACING_M + 0.1, 3)
_LENS_CODES = frozenset({
    "spatial_subjects_in_frame", "spatial_subject_occlusion", "spatial_move_keeps_subjects",
    "spatial_camera_clearance", "spatial_axis_consistent",
})
LABELS: dict[str, str] = {
    "spatial_actor_spacing": "拉开站位",
    "spatial_facing_partner": "转向对手",
    "spatial_screen_sides_stable": "换回站位",
    "spatial_subjects_in_frame": "重解机位",
    "spatial_subject_occlusion": "重解机位",
    "spatial_move_keeps_subjects": "重解机位",
    "spatial_camera_clearance": "重解机位",
    "spatial_axis_consistent": "重解机位",
    "spatial_action_changes_state": "补上姿态",
}


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
        f"把{names}沿彼此的连线推开到至少 {SPACING_TARGET_M:g} 米。" if operations else check.detail,
        operations=operations,
        manual="" if operations else "人物重叠但无法自动推开，请手动调整站位。",
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
        f"让{names}转身面向对手。" if operations else check.detail,
        operations=operations,
        manual="" if operations else "找不到对手戏的两个人物，请手动调整朝向。",
    )


def _screen_sides(plan: StagePlan, check: StageCheck) -> Repair:
    if check.severity != "error":
        return Repair(
            check.code, LABELS[check.code], check.detail, shot_ids=list(check.shot_ids),
            manual="这些镜头在合法越轴之后拍摄，左右相反是有意为之；若非本意，请在越轴镜头上换边或重解机位。",
        )
    first, second = plan.actor(plan.axis.from_name), plan.actor(plan.axis.to_name)
    if first is None or second is None:
        return Repair(check.code, LABELS[check.code], check.detail, shot_ids=list(check.shot_ids), manual="轴线两端的人物不在场上。")
    operations = [
        {"op": "move_actor", "name": first.name, "position": list(second.position), "yaw_deg": second.yaw_deg},
        {"op": "move_actor", "name": second.name, "position": list(first.position), "yaw_deg": first.yaw_deg},
    ]
    return Repair(
        check.code, LABELS[check.code], f"对调{first.name}与{second.name}的站位和朝向，恢复既定的画左 / 画右。",
        shot_ids=list(check.shot_ids), operations=operations,
    )


def _lens(plan: StagePlan, check: StageCheck) -> Repair:
    shots = [shot_id for shot_id in check.shot_ids if plan.shot(shot_id) is not None]
    if not shots:
        return Repair(check.code, LABELS[check.code], check.detail, manual="检查没有指向具体镜头，无法自动重解。")
    operations = [{"op": "solve_camera", "shot_id": shot_id} for shot_id in shots]
    labels = "、".join(f"第{shot_id}镜" for shot_id in shots)
    return Repair(
        check.code, LABELS[check.code],
        f"按景别、角度和主体重新求解{labels}的机位：主体入画、避开前景遮挡、守住轴线同侧。",
        shot_ids=shots, operations=operations,
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
                manual.append(f"第{shot.shot_id}镜{actor.name}写了走位：请在导演台为其画一条路径，或设置本镜的起始位置")
            implied = posture_in(actor.name, shot.action, None)
            if implied and not moved and implied != actor.posture:
                current = change or None
                operation: dict[str, Any] = {
                    "op": "set_shot_override", "shot_id": shot.shot_id, "name": actor.name, "posture": implied,
                    "reason": f"分镜写明「{implied}」",
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
    done = "；".join(f"第{op['shot_id']}镜{op['name']}改为「{op['posture']}」" for op in operations)
    return Repair(
        check.code, LABELS[check.code],
        (done + "。") if done else check.detail,
        shot_ids=list(check.shot_ids), operations=operations, manual="；".join(manual)[:1900],
    )


_HANDLERS = {
    "spatial_actor_spacing": _spacing,
    "spatial_facing_partner": _facing,
    "spatial_screen_sides_stable": _screen_sides,
    "spatial_action_changes_state": _action,
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
            repairs.append(Repair(check.code, "需人工处理", check.detail, shot_ids=list(check.shot_ids), manual="这项检查没有自动修正。"))
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

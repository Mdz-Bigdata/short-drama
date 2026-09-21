# -*- coding: utf-8 -*-
"""Numeric checks of a spatial stage.

These are the checks a person does by eye on a 3D director desk — is everyone
the shot is about actually in frame, is anyone hidden behind someone else, did
a cut jump the axis, did two people swap screen sides — done as measurements so
they hold for a plan a person has dragged around as well as for a solved one.
"""

from __future__ import annotations

from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.language import posture_in, travel_in
from app.core.spatial_stage.models import StageCheck, StagePlan
from app.core.spatial_stage.projection import screen_states

MIN_ACTOR_SPACING_M = 0.4
MIN_CAMERA_CLEARANCE_M = 0.3


def _ids(values: list[int]) -> list[int]:
    return sorted(dict.fromkeys(values))[:200]


def check_plan(plan: StagePlan) -> list[StageCheck]:
    """Every spatial check of ``plan``; expects each shot's ``screen`` / ``axis_side`` / ``crossing`` to be current."""
    checks: list[StageCheck] = []
    cameras = {camera.id: camera for camera in plan.cameras}

    # ---- nobody shares a mark
    crowded: list[str] = []
    solid = [actor for actor in plan.actors if actor.role != "crowd"]
    for index, first in enumerate(solid):
        for second in solid[index + 1:]:
            gap = geo.distance((first.position[0], first.position[1]), (second.position[0], second.position[1]))
            if gap < MIN_ACTOR_SPACING_M:
                crowded.append(f"{first.name}与{second.name}仅相距{gap:.2f}米")
    checks.append(StageCheck(
        code="spatial_actor_spacing",
        passed=not crowded,
        detail="；".join(crowded)[:1900] + "，人物会穿模重叠，请拉开站位。" if crowded else "所有人物站位互不重叠。",
    ))

    # ---- the people a shot is about are inside its frame, at both ends of a move
    out_of_frame: list[str] = []
    out_ids: list[int] = []
    drift: list[str] = []
    drift_ids: list[int] = []
    hidden: list[str] = []
    hidden_ids: list[int] = []
    # A crowd is background by nature; being partly covered is how it is meant to read.
    crowd_names = {actor.name for actor in plan.actors if actor.role == "crowd"}
    for shot in plan.shots:
        camera = cameras.get(shot.camera_id)
        if camera is None:
            continue
        states = {state.name: state for state in shot.screen}
        for name in camera.subjects:
            state = states.get(name)
            if state is None:
                continue
            if not state.visible:
                out_of_frame.append(f"第{shot.shot_id}镜的{name}")
                out_ids.append(shot.shot_id)
            elif state.occluded_by and camera.function != "over_shoulder" and name not in crowd_names:
                hidden.append(f"第{shot.shot_id}镜的{name}被{state.occluded_by}挡住")
                hidden_ids.append(shot.shot_id)
        if camera.move.kind != "static":
            ending = {state.name: state for state in screen_states(plan.actors_in(shot, at_end=True), camera, end=True)}
            lost = [name for name in camera.subjects if name in ending and not ending[name].visible]
            if camera.move.kind == "pan" and camera.subjects:
                # A pan hands the frame from its subject to whoever it turns to; it only fails when it lands on nobody.
                lost = [] if any(state.visible for name, state in ending.items() if name not in crowd_names) else lost
            if lost:
                drift.append(f"第{shot.shot_id}镜运镜结束时{'、'.join(lost)}出画")
                drift_ids.append(shot.shot_id)
    checks.append(StageCheck(
        code="spatial_subjects_in_frame",
        passed=not out_of_frame,
        detail=(
            "、".join(out_of_frame)[:1800] + "不在该机位的画面内，请调整机位或站位。"
            if out_of_frame else "每一镜要拍的人物都在该机位画面内。"
        ),
        shot_ids=_ids(out_ids),
    ))
    checks.append(StageCheck(
        code="spatial_move_keeps_subjects",
        passed=not drift,
        severity="warning",
        detail="；".join(drift)[:1900] if drift else "运镜起止两端主体均在画内。",
        shot_ids=_ids(drift_ids),
    ))
    checks.append(StageCheck(
        code="spatial_subject_occlusion",
        passed=not hidden,
        severity="warning",
        detail="；".join(hidden)[:1900] + "，请错开站位或换机位。" if hidden else "主体未被前景人物遮挡。",
        shot_ids=_ids(hidden_ids),
    ))

    # ---- 180-degree rule
    jumps = axis_rules.illegal_crossings(plan.shots) if axis_rules.has_axis(plan.axis) else []
    checks.append(StageCheck(
        code="spatial_axis_consistent",
        passed=not jumps,
        detail=(
            "；".join(f"第{before}镜→第{after}镜越轴" for before, after in jumps)[:1800]
            + "：两镜之间没有轴线上的中性镜头、越轴运动镜头或重新建立空间的全景，人物左右会翻转。"
            if jumps else "全部机位守在轴线同一侧，或经合法的桥接镜头换边。"
        ),
        shot_ids=_ids([after for _, after in jumps]),
    ))

    # ---- the promised screen sides hold wherever the pair shares a frame
    # On the established side this is true by construction; what it catches is a scene whose marks
    # were swapped under its cameras (it *opens* mirrored: an error) and coverage that carried on
    # from the far side after a legal crossing (mirrored on purpose: worth a warning, not a stop).
    mirrored: list[int] = []
    opens_mirrored = False
    promised = {actor.name: actor.screen_side for actor in plan.actors if actor.screen_side in {"left", "right"}}
    if axis_rules.has_axis(plan.axis) and plan.axis.kind != "motion":
        first, second = plan.axis.from_name, plan.axis.to_name
        seen_pair = False
        for shot in plan.shots:
            states = {state.name: state for state in shot.screen if state.visible}
            if first not in states or second not in states or abs(states[first].x - states[second].x) <= 0.05:
                continue
            left_name = first if states[first].x < states[second].x else second
            right_name = second if left_name == first else first
            if promised.get(left_name) == "right" or promised.get(right_name) == "left":
                mirrored.append(shot.shot_id)
                opens_mirrored = opens_mirrored or not seen_pair
            seen_pair = True
    checks.append(StageCheck(
        code="spatial_screen_sides_stable",
        passed=not mirrored,
        severity="error" if opens_mirrored or not mirrored else "warning",
        detail=(
            f"第{'、'.join(str(item) for item in _ids(mirrored))}镜里{plan.axis.from_name}与{plan.axis.to_name}"
            "的左右位置与既定的画左 / 画右关系相反；"
            + ("本场从第一次同框起就是反的，请换回站位，或重新确立本场的左右关系。" if opens_mirrored
               else "这些镜头在合法越轴之后拍摄，左右相反是有意为之，生成时请留意人物不要串位。")
            if mirrored else "人物的画左 / 画右关系在所有同框镜头中与既定关系一致。"
        ),
        shot_ids=_ids(mirrored),
    ))

    # ---- people playing a scene to each other actually face each other
    averted: list[str] = []
    if plan.axis.kind == "dialogue" and axis_rules.has_axis(plan.axis) and plan.formation.startswith("面对面"):
        pair = [plan.actor(plan.axis.from_name), plan.actor(plan.axis.to_name)]
        if all(pair):
            for actor, partner in ((pair[0], pair[1]), (pair[1], pair[0])):
                toward = geo.unit(geo.sub((partner.position[0], partner.position[1]), (actor.position[0], actor.position[1])))
                if geo.dot(geo.forward_of(actor.yaw_deg), toward) < 0.82:
                    averted.append(f"{actor.name}没有面向{partner.name}")
    checks.append(StageCheck(
        code="spatial_facing_partner",
        passed=not averted,
        severity="warning",
        detail="；".join(averted) + "，与面对面的站位不符。" if averted else "对手戏人物彼此相向。",
    ))

    # ---- the lens is not inside somebody
    inside: list[str] = []
    inside_ids: list[int] = []
    for shot in plan.shots:
        camera = cameras.get(shot.camera_id)
        if camera is None:
            continue
        for actor in plan.actors_in(shot):
            gap = geo.distance((camera.position[0], camera.position[2]), (actor.position[0], actor.position[1]))
            if gap < MIN_CAMERA_CLEARANCE_M and camera.position[1] < actor.height_m + 0.2:
                inside.append(f"第{shot.shot_id}镜机位距{actor.name}仅{gap:.2f}米")
                inside_ids.append(shot.shot_id)
    checks.append(StageCheck(
        code="spatial_camera_clearance",
        passed=not inside,
        severity="warning",
        detail="；".join(inside)[:1900] + "，机位穿入人物。" if inside else "机位与人物保持安全距离。",
        shot_ids=_ids(inside_ids),
    ))

    # ---- what the storyboard says someone does is on the stage
    frozen: list[str] = []
    frozen_ids: list[int] = []
    # One mark holds one move: a walk written after someone has already entered or moved stays unstaged.
    walkers = {item.name for shot in plan.shots for item in shot.overrides if item.position is not None and not item.hold}
    for shot in plan.shots:
        changes = {item.name: item for item in shot.overrides}
        for actor in plan.actors_in(shot):
            if actor.role == "crowd":
                continue
            change = changes.get(actor.name)
            moved = change is not None and change.position is not None
            if travel_in(actor.name, shot.action) and actor.name not in walkers:
                frozen.append(f"第{shot.shot_id}镜{actor.name}写了走位，站位却没有变化")
                frozen_ids.append(shot.shot_id)
            implied = posture_in(actor.name, shot.action, None)
            if implied and not moved and implied != actor.posture:
                frozen.append(f"第{shot.shot_id}镜{actor.name}的姿态应为「{implied}」，空间方案里是「{actor.posture}」")
                frozen_ids.append(shot.shot_id)
    checks.append(StageCheck(
        code="spatial_action_changes_state",
        passed=not frozen,
        severity="warning",
        detail="；".join(frozen)[:1900] + "。" if frozen else "分镜里写到的走位与姿态变化都落在了空间方案上。",
        shot_ids=_ids(frozen_ids),
    ))
    return checks


def passed(checks: list[StageCheck]) -> bool:
    return not any(not item.passed and item.severity == "error" for item in checks)


__all__ = ["MIN_ACTOR_SPACING_M", "MIN_CAMERA_CLEARANCE_M", "check_plan", "passed"]

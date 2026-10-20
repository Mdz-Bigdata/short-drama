# -*- coding: utf-8 -*-
"""Say the stage in the storyboard's own words.

Every sentence here is a reading of the plan: screen regions come from the
projection, distances from the floor, the axis statement from the side the
camera stands on. The shot contract (composition / action_axis / eyeline /
blocking), the director's frame positions, scene landmarks and continuity locks
are all fed from these strings, so the prompt can never claim a blocking the
plan does not hold.
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection

from app.core.frame_position import FramePosition, render_frame_positions
from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import (
    ShotText,
    StageActor,
    StageCamera,
    StageLandmark,
    StagePlan,
    StageShot,
)
from app.core.spatial_stage.projection import CameraView, posture_height

_POSTURE_ZH = {
    "stand": "站立", "walk": "行走", "run": "奔跑", "sit": "坐着", "crouch": "蹲伏",
    "kneel": "跪地", "lie": "倒卧", "fight": "格斗架势", "bow": "躬身", "lean": "倚靠",
}
_MOVE_ZH = {
    "static": "固定机位", "push": "推近", "pull": "拉远", "pan": "摇镜", "track": "横移",
    "orbit": "弧形环绕", "rise": "升", "fall": "降", "follow": "跟拍",
}
_CROSSING_ZH = {
    "neutral": "本镜机位落在轴线上，属中性镜头，可作为换边的桥",
    "moving": "本镜机位带着观众越过轴线，越轴过程完整可见",
    "reestablish": "本镜为重新建立空间的全景，可在此后换边",
}


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip("，；、 ") + "…"


def bearing_from(actor: StageActor, point: geo.Vec2) -> tuple[str, float]:
    """``(bearing, meters)`` of ``point`` as the actor would say it: 前方 / 左前方 / 右侧 / 后方 …"""
    origin = (actor.position[0], actor.position[1])
    delta = geo.sub(point, origin)
    meters = geo.length(delta)
    if meters < 0.05:
        return "身旁", 0.0
    forward = geo.forward_of(actor.yaw_deg)
    ahead = geo.dot(geo.unit(delta), forward)
    to_right = geo.dot(geo.unit(delta), geo.right_of(forward))
    angle = math.degrees(math.atan2(to_right, ahead))
    side = "右" if angle > 0 else "左"
    magnitude = abs(angle)
    if magnitude <= 22.5:
        label = "前方"
    elif magnitude <= 67.5:
        label = f"{side}前方"
    elif magnitude <= 112.5:
        label = f"{side}侧"
    elif magnitude <= 157.5:
        label = f"{side}后方"
    else:
        label = "后方"
    return label, meters


def _anchor_actor(plan: StagePlan) -> StageActor | None:
    return plan.actor(plan.axis.from_name) or next((a for a in plan.actors if a.role != "crowd"), None) or (
        plan.actors[0] if plan.actors else None
    )


def master_camera(plan: StagePlan) -> StageCamera | None:
    """The camera whose frame defines "screen left" for the scene: the first establishing view."""
    return next(
        (camera for camera in plan.cameras if camera.function == "establish"),
        next((camera for camera in plan.cameras if len(camera.subjects) >= 2), plan.cameras[0] if plan.cameras else None),
    )


def landmark_relative_position(plan: StagePlan, landmark: StageLandmark) -> str:
    """Bearing and distance from the scene's anchor character, plus where the master frame shows it."""
    anchor = _anchor_actor(plan)
    point = (landmark.position[0], landmark.position[1])
    if anchor is None:
        centre = geo.centroid([(item.position[0], item.position[1]) for item in plan.landmarks])
        return _clip(f"距场地中心约{geo.distance(point, centre):.1f}米，位置固定不镜像", 500)
    bearing, meters = bearing_from(anchor, point)
    text = f"位于{anchor.name}{bearing}约{meters:.1f}米"
    master = master_camera(plan)
    if master is not None:
        x, _, depth = CameraView.of(master).project((point[0], landmark.size[2] / 2, point[1]))
        if depth > 0.2:
            side = "左侧" if x < -0.12 else "右侧" if x > 0.12 else "中央"
            text += f"，主机位画面{side}"
    return _clip(text, 500)


def array_members(plan: StagePlan) -> frozenset[str]:
    """Names of the people who stand in a crowd array: background texture, described as one group."""
    return frozenset(actor.name for actor in plan.actors if actor.crowd_id)


def frame_positions(
    shot: StageShot, camera: StageCamera, grouped: Collection[str] = (),
) -> list[FramePosition]:
    """The visible characters of the shot in screen coordinates: subjects left to right, then bystanders by depth.

    A shot of nobody (an empty frame, a prop insert) lists no one even if a mark happens to fall inside it.
    ``grouped`` (the members of crowd arrays) are never listed one by one unless the shot is about them.
    """
    if not camera.subjects:
        return []
    order = {name: index for index, name in enumerate(camera.subjects)}
    visible = sorted(
        (state for state in shot.screen if state.visible and (state.name in order or state.name not in grouped)),
        key=lambda state: (0, state.x) if state.name in order else (1, state.depth_m),
    )
    positions: list[FramePosition] = []
    for state in visible:
        occlusion, keep = "", ""
        if camera.function == "over_shoulder" and state.name not in order:
            edge = "左侧" if state.x < 0 else "右侧"
            occlusion = f"肩背虚化，遮挡画面{edge}约四分之一"
            keep = f"保留{camera.subjects[0]}的完整面部" if camera.subjects else ""
        elif state.occluded_by and camera.function != "over_shoulder":
            occlusion = f"被{state.occluded_by}遮挡约二分之一"
        positions.append(FramePosition(
            subject=state.name[:120], region=state.region, depth=state.depth_layer,
            facing=state.facing, occlusion=occlusion, keep_visible=keep,
        ))
    return positions[:30]


def _axis_angle(plan: StagePlan, camera: StageCamera) -> float:
    """Degrees between the lens and the axis: 90 is the square-on master, small is down the line."""
    direction = geo.unit(axis_rules.axis_vector(plan.axis), (1.0, 0.0))
    cosine = abs(geo.dot(CameraView.of(camera).ground_forward(), direction))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _axis_text(plan: StagePlan, shot: StageShot, camera: StageCamera) -> str:
    axis = plan.axis
    if not axis_rules.has_axis(axis):
        return "本场无人物关系轴线；以场景地标的左右位置为准，任何镜头不得左右镜像"
    left, right = (axis.from_name, axis.to_name) if axis.camera_side >= 0 else (axis.to_name, axis.from_name)
    if axis.kind == "gaze":
        head = f"视线轴线为{axis.from_name}→{axis.to_name}；全场机位守在轴线同一侧，{left}恒在画左、{right}恒在画右"
    elif axis.kind == "motion":
        head = f"运动轴线沿{axis.from_name}→{axis.to_name}；全场机位守在轴线同一侧，运动方向恒为画面由左向右"
    else:
        head = f"关系轴线为{axis.from_name}—{axis.to_name}连线；全场机位守在轴线同一侧，{left}恒在画左、{right}恒在画右"
    if shot.crossing in _CROSSING_ZH:
        tail = _CROSSING_ZH[shot.crossing]
    else:
        tail = f"本镜机位在既定一侧，与轴线夹角约{_axis_angle(plan, camera):.0f}度，不越轴"
    return _clip(f"{head}；{tail}", 500)


def _eyeline_text(plan: StagePlan, shot: StageShot, camera: StageCamera) -> str:
    states = {state.name: state for state in shot.screen}
    actors = {actor.name: actor for actor in plan.actors_in(shot)}
    view = CameraView.of(camera)
    clauses: list[str] = []
    for name in camera.subjects:
        state = states.get(name)
        if state is None or not state.visible:
            continue
        clause = f"{name}视线{state.facing}"
        partner_name = (
            plan.axis.to_name if name == plan.axis.from_name
            else plan.axis.from_name if name == plan.axis.to_name else ""
        )
        partner = states.get(partner_name)
        if partner is not None and partner_name in actors:
            if partner.visible:
                clause += f"，看向画内的{partner_name}"
            else:
                side = view.offscreen_side((actors[partner_name].position[0], actors[partner_name].position[1]))
                clause += f"，看向画外{'右' if side == 'right' else '左'}侧的{partner_name}"
        elif partner_name and plan.axis.kind == "gaze":
            clause += f"，看向{partner_name}"
        clauses.append(clause)
    if not clauses:
        return "本镜无人物视线；保持场景地标与光向的左右关系"
    lead = actors.get(camera.subjects[0]) if camera.subjects else None
    if lead is not None:
        delta = camera.position[1] - posture_height(lead) * 0.93
        level = "镜头与视线齐平" if abs(delta) < 0.18 else "镜头高于视线，略俯" if delta > 0 else "镜头低于视线，略仰"
        clauses.append(level)
    return _clip("；".join(clauses), 500)


def _blocking_text(plan: StagePlan, shot: StageShot, camera: StageCamera) -> str:
    actors = plan.actors_in(shot)
    by_name = {actor.name: actor for actor in actors}
    parts: list[str] = []
    first, second = by_name.get(plan.axis.from_name), by_name.get(plan.axis.to_name)
    if first is not None and second is not None:
        gap = geo.distance((first.position[0], first.position[1]), (second.position[0], second.position[1]))
        facing_each_other = geo.dot(geo.forward_of(first.yaw_deg), geo.forward_of(second.yaw_deg)) < -0.5
        relation = "面对面" if facing_each_other else "同向并肩"
        parts.append(
            f"{first.name}（{_POSTURE_ZH.get(first.posture, '站立')}）与{second.name}"
            f"（{_POSTURE_ZH.get(second.posture, '站立')}）相距{gap:.1f}米{relation}"
        )
    anchor = first or (actors[0] if actors else None)
    for actor in actors:
        if anchor is None or actor.name in {plan.axis.from_name, plan.axis.to_name} or actor is anchor or actor.crowd_id:
            continue
        bearing, meters = bearing_from(anchor, (actor.position[0], actor.position[1]))
        parts.append(f"{actor.name}（{_POSTURE_ZH.get(actor.posture, '站立')}）在{anchor.name}{bearing}{meters:.1f}米")
    for crowd in plan.crowds:
        if anchor is not None:
            bearing, meters = bearing_from(anchor, (crowd.center[0], crowd.center[1]))
            parts.append(f"{crowd.label}{crowd.rows * crowd.columns}人列阵于{anchor.name}{bearing}{meters:.1f}米")
    if anchor is not None and first is None:
        parts.insert(0, f"{anchor.name}（{_POSTURE_ZH.get(anchor.posture, '站立')}）位于场地中央")
    for change in shot.overrides:
        if change.reason:
            parts.append(f"本镜{change.name}{change.reason}")
    lead = by_name.get(camera.subjects[0]) if camera.subjects else anchor
    if lead is not None:
        reach = geo.distance((camera.position[0], camera.position[2]), (lead.position[0], lead.position[1]))
        parts.append(f"机位距{lead.name}{reach:.1f}米、机高{camera.position[1]:.1f}米")
    for landmark in plan.landmarks[:3]:
        parts.append(f"{landmark.name}{landmark_relative_position(plan, landmark)}")
    return _clip("；".join(parts) or "空镜：按场景圣经保持地标位置", 800)


# The one clause of ``blocking`` that states where the lens is. Kept next to the code that writes it.
_CAMERA_POSE_CLAUSE = re.compile(r"(?:^|；)机位距[^；。]*?机高\d+(?:\.\d+)?米")


def without_camera_pose(text: str) -> str:
    """``text`` minus the measured lens-pose clause.

    A blockout clip owns the camera track (blockout rule 3): a sentence that also states where the
    lens stands is a second, competing camera instruction, so it is withheld while a clip is applied.
    """
    return _CAMERA_POSE_CLAUSE.sub("", str(text or "")).lstrip("；")


def _camera_pose_text(plan: StagePlan, shot: StageShot, camera: StageCamera, *, end: bool) -> str:
    position = camera.move.end_position if end and camera.move.end_position else camera.position
    by_name = {actor.name: actor for actor in plan.actors_in(shot)}
    lead = by_name.get(camera.subjects[0]) if camera.subjects else _anchor_actor(plan)
    where = f"机高{position[1]:.1f}米"
    if lead is not None:
        bearing, meters = bearing_from(lead, (position[0], position[2]))
        where = f"位于{lead.name}{bearing}{meters:.1f}米、" + where
    return _clip(f"{where}，{camera.lens_mm:g}mm，{camera.angle}", 500)


def shot_text(plan: StagePlan, shot: StageShot, camera: StageCamera) -> ShotText:
    positions = frame_positions(shot, camera, array_members(plan))
    placed = render_frame_positions(positions)
    composition = f"{camera.shot_size}，{camera.lens_mm:g}mm"
    if placed:
        composition += f"；{placed}"
    else:
        view = CameraView.of(camera)
        seen = []
        for landmark in plan.landmarks:
            x, y, depth = view.project((landmark.position[0], landmark.size[2] / 2, landmark.position[1]))
            if depth > 0.2 and abs(x) <= 1.0 and abs(y) <= 1.2:
                seen.append(f"{landmark.name}位于{'画面左侧' if x < -0.12 else '画面右侧' if x > 0.12 else '画面中央'}")
        composition += "；空镜，不出现人物" + (f"；{'，'.join(seen[:4])}" if seen else "；按场景圣经的地标左右位置构图")
    move = _MOVE_ZH.get(camera.move.kind, "固定机位")
    return ShotText(
        camera_angle=_clip(camera.angle or "平视", 120),
        composition=_clip(composition, 1000),
        action_axis=_axis_text(plan, shot, camera),
        eyeline=_eyeline_text(plan, shot, camera),
        blocking=_blocking_text(plan, shot, camera),
        camera_start=_camera_pose_text(plan, shot, camera, end=False),
        camera_end=(
            f"{move}至：" + _camera_pose_text(plan, shot, camera, end=True)
            if camera.move.kind != "static" else f"{move}，机位不变"
        )[:500],
    )


def scene_bible(plan: StagePlan) -> str:
    """The scene's spatial bible: one paragraph every shot of the scene inherits."""
    lines = [f"【空间圣经】{plan.location or plan.scene_id}；单位米；左右一律以主机位的画面为准，任何镜头不得镜像。"]
    if plan.formation:
        lines.append(f"站位：{plan.formation}。")
    for actor in plan.actors:
        if actor.crowd_id:
            continue
        side = {"left": "恒在画左", "right": "恒在画右"}.get(actor.screen_side, "")
        lines.append(
            f"{actor.name}：{_POSTURE_ZH.get(actor.posture, '站立')}，地面坐标({actor.position[0]:.1f}, {actor.position[1]:.1f})"
            + (f"，{side}" if side else "") + "。"
        )
    for crowd in plan.crowds:
        lines.append(
            f"{crowd.label}：{crowd.rows}排×{crowd.columns}列共{crowd.rows * crowd.columns}人，"
            f"阵心地面坐标({crowd.center[0]:.1f}, {crowd.center[1]:.1f})，间距{crowd.spacing:.1f}米。"
        )
    for landmark in plan.landmarks:
        lines.append(f"{landmark.name}：{landmark_relative_position(plan, landmark)}。")
    if axis_rules.has_axis(plan.axis):
        lines.append(
            f"轴线：{plan.axis.from_name}—{plan.axis.to_name}；全部机位位于轴线同一侧，"
            "换边必须先经过轴线上的中性镜头、越轴运动镜头或重新建立空间的全景。"
        )
    return _clip("".join(lines), 4000)


def table_brief(plan: StagePlan) -> str:
    """What the storyboard table writer must not contradict: sides, distances, set pieces. Kept short."""
    parts: list[str] = []
    if axis_rules.has_axis(plan.axis) and plan.axis.kind == "dialogue":
        left, right = (
            (plan.axis.from_name, plan.axis.to_name) if plan.axis.camera_side >= 0
            else (plan.axis.to_name, plan.axis.from_name)
        )
        gap = geo.distance((plan.axis.start[0], plan.axis.start[1]), (plan.axis.end[0], plan.axis.end[1]))
        parts.append(f"{left}恒在画左、{right}恒在画右，相距约{gap:.1f}米（{plan.formation.split('；')[0]}）")
    elif plan.actors:
        lead = plan.actors[0]
        parts.append(f"{lead.name}{'恒在画左' if lead.screen_side == 'left' else '恒在画右' if lead.screen_side == 'right' else '居中'}")
    others = [actor.name for actor in plan.actors if actor.role != "principal"]
    if others:
        parts.append(f"{'、'.join(others[:6])}在两人后方")
    for landmark in plan.landmarks[:4]:
        parts.append(f"{landmark.name}{landmark_relative_position(plan, landmark)}")
    if not parts:
        return ""
    return _clip(
        "【空间调度（系统已定站位，机位由系统按此求解）】" + "；".join(parts)
        + "。画面内容里的左右、朝向与远近须与此一致，不写越轴与镜像；景别、机位角度照常填写。",
        600,
    )


__all__ = [
    "array_members",
    "bearing_from",
    "frame_positions",
    "landmark_relative_position",
    "master_camera",
    "scene_bible",
    "shot_text",
    "table_brief",
    "without_camera_pose",
]

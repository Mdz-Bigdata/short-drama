# -*- coding: utf-8 -*-
"""导演台上摆好的东西，写成视频模型读得懂的几行字。

第 4 阶段只把站位、视线、机位的说明抄进镜头契约，之后再改导演台，契约不会变；多瞬间片段又只带第一个瞬间的
锁。这里在第 5 阶段直接读当前的方案，逐镜写出每个人的姿态、姿势、动作、画面位置、朝向、身高体型，人物之间的
空间关系、布景，以及机位的位置、高度、焦距、角度和运动。不写绝对秒数：模型会把秒数当成逐帧指令。
"""

from __future__ import annotations

import math

from app.core import prompt_data
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.director_ai import POSE_PRESETS
from app.core.spatial_stage.models import ShotTimeline, StageActor, StageCamera, StagePlan, StagePose, StageShot
from app.core.spatial_stage.prompting import (
    _MOVE_ZH,
    _POSTURE_ZH,
    bearing_from,
    landmark_size,
    prompt_landmarks,
    shot_text,
    without_camera_pose,
)
from app.core.spatial_stage.projection import CameraView

_DATA = "stage_brief"
_PRESET_NAMES = dict(POSE_PRESETS)


def _data() -> dict:
    return prompt_data.load(_DATA)


def title() -> str:
    return prompt_data.text(_DATA, "title")


def _joint_label(key: str) -> str:
    data = _data()
    if key in data["joint_named"]:
        return data["joint_named"][key]
    joint, _, axis = key.partition(".")
    for side, side_name in data["joint_sides"].items():
        part = data["joint_parts"].get(joint[len(side):]) if joint.startswith(side) else None
        if part and axis in data["joint_axes"]:
            return f"{side_name}{part}{data['joint_axes'][axis]}"
    return ""  # 手指这类细节，视频模型按角度也做不出来


def pose_text(pose: StagePose | None) -> str:
    """姿势：有预设就说名字；手调的姿势说幅度最大的几个关节；动画片段说它的名字。"""
    if pose is None:
        return ""
    data = _data()
    if pose.clip and data["clip_names"].get(pose.clip):
        return str(data["clip_names"][pose.clip])
    if pose.preset and _PRESET_NAMES.get(pose.preset):
        return _PRESET_NAMES[pose.preset]
    bent = sorted(
        ((abs(value), _joint_label(key)) for key, value in pose.joints.items() if abs(value) >= data["min_joint_degrees"]),
        key=lambda item: -item[0],
    )
    return "、".join(f"{label}约{degrees:.0f}°" for degrees, label in bent if label)[: 80] if bent else ""


def _frame_side(view: CameraView, x: float, y: float, height: float) -> str:
    across, _, depth = view.project((x, height, y))
    if depth <= 0.2:
        return "画外"
    return "画面左侧" if across < -0.12 else "画面右侧" if across > 0.12 else "画面中央"


def _movement(actor: StageActor, keys: list, end: StageActor | None, view: CameraView) -> str:
    """走位：从哪走到哪、走了多远、转了多少。"""
    # 动作轨道上有关键帧就以它为准；没有时才看这一镜结束时回到的站位。
    end = None if keys else end
    keyed = [(key.position[0], key.position[1]) for key in keys if key.position]
    # 第一帧就有位置关键帧时从那里起步，否则从站位起步。
    opens_on_key = bool(keys and keys[0].time == 0 and keys[0].position)
    points = keyed if opens_on_key else [(actor.position[0], actor.position[1]), *keyed]
    if end is not None and (end.position[0], end.position[1]) != points[-1]:
        points.append((end.position[0], end.position[1]))
    meters = sum(geo.distance(a, b) for a, b in zip(points, points[1:]))
    parts: list[str] = []
    if meters >= 0.2:
        height = actor.height_m * 0.55
        start, stop = _frame_side(view, *points[0], height), _frame_side(view, *points[-1], height)
        parts.append(f"从{start}走到{stop}，走位约{meters:.1f}米" if start != stop else f"走位约{meters:.1f}米")
    yaws = [actor.yaw_deg, *(key.yaw_deg for key in keys if key.yaw_deg is not None)]
    if end is not None:
        yaws.append(end.yaw_deg)
    turned = abs((yaws[-1] - yaws[0] + 180) % 360 - 180)
    if turned >= 20:
        parts.append(f"转身约{turned:.0f}°")
    return "，".join(parts)


def _actions(name: str, keys: list, timeline: ShotTimeline | None) -> str:
    """动作：动作轨道上的片段和姿势关键帧，按先后。"""
    names = _data()["clip_names"]
    clips = sorted((timeline.clips.get(name) or []) if timeline else [], key=lambda clip: clip.start)
    steps = [str(names[clip.clip]) for clip in clips if names.get(clip.clip)]
    if not steps:
        steps = [text for text in (pose_text(key.pose) for key in keys if key.pose) if text]
    steps = list(dict.fromkeys(steps))
    return "→".join(steps)


def _person_line(plan: StagePlan, shot: StageShot, actor: StageActor, end: StageActor | None, timeline: ShotTimeline | None, view: CameraView) -> str:
    data = _data()
    screen = next((state for state in shot.screen if state.name == actor.name), None)
    keys = (timeline.actors.get(actor.name) or []) if timeline else []
    parts = [_POSTURE_ZH.get(actor.posture, "站立")]
    pose = pose_text(actor.pose)
    if pose:
        parts.append(f"姿势{pose}")
    if screen is not None and screen.visible:
        parts.append("、".join(item for item in (screen.region, screen.depth_layer, screen.facing) if item))
        if screen.occluded_by:
            parts.append(f"被{screen.occluded_by}遮挡")
    build = data["body_types"].get(actor.body_type, "")
    parts.append(f"身高约{actor.height_m * 100:.0f}cm" + (f"、{build}" if build else ""))
    movement = _movement(actor, keys, end, view)
    if movement:
        parts.append(movement)
    actions = _actions(actor.name, keys, timeline)
    if actions:
        parts.append(f"动作{actions}")
    if actor.note:
        parts.append(actor.note)
    return f"{actor.name}：" + "；".join(part for part in parts if part)[: int(data["person_chars"])]


def _camera_text(plan: StagePlan, shot: StageShot, camera: StageCamera, timeline: ShotTimeline | None, *, start: str, end: str) -> str:
    parts = [start, end]
    if timeline is not None:
        by_id = {item.id: item for item in plan.cameras}
        for clip in sorted(timeline.follow, key=lambda clip: clip.start):
            parts.append(f"跟拍{clip.actor}，保持约{math.hypot(*clip.offset):.1f}米")
        for cut in sorted(timeline.cuts, key=lambda cut: cut.start):
            other = by_id.get(cut.camera_id)
            if other is not None:
                parts.append(f"片内切到{other.label}（{other.equivalent_lens_mm:g}mm，{other.angle}）")
        if len(timeline.camera) >= 2:
            first, last = timeline.camera[0], timeline.camera[-1]
            parts.append(f"机位轨迹{len(timeline.camera)}个关键点，机高{first.position[1]:.1f}米到{last.position[1]:.1f}米，焦距{first.lens_mm:g}mm到{last.lens_mm:g}mm")
    if camera.move.kind != "static" and not end:
        parts.append(_MOVE_ZH.get(camera.move.kind, ""))
    return "；".join(part for part in parts if part)


def shot_lines(plan: StagePlan | None, shot_id: object, *, camera: bool = True) -> list[str]:
    """这一镜在导演台上的样子，一行一件事；方案里没有这一镜时是空的。

    ``camera=False``：这一镜跟着导演台白模视频走，视频是唯一的机位参考，文字不再写机位。
    """
    if plan is None:
        return []
    try:
        shot = plan.shot(int(shot_id))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return []
    filming = plan.camera(shot.camera_id) if shot is not None else None
    if shot is None or filming is None:
        return []
    data = _data()
    labels = data["labels"]
    text = shot.text if shot.text.blocking else shot_text(plan, shot, filming)
    timeline = plan.timelines.get(str(shot.shot_id))
    view = CameraView.of(filming)
    actors = [actor for actor in plan.actors_in(shot) if not actor.crowd_id]
    ends = {actor.name: actor for actor in plan.actors_in(shot, at_end=True)}
    wanted = set(filming.subjects) | {state.name for state in shot.screen if state.visible}
    people = sorted([actor for actor in actors if actor.name in wanted], key=lambda actor: actor.role != "principal")
    lines = [
        f"{labels['person']}：{_person_line(plan, shot, actor, ends.get(actor.name), timeline, view)}"
        for actor in people[: int(data["max_people"])]
    ]
    anchor = people[0] if people else None
    for crowd in plan.crowds:
        where = ""
        if anchor is not None:
            bearing, meters = bearing_from(anchor, (crowd.center[0], crowd.center[1]))
            where = f"，在{anchor.name}{bearing}{meters:.1f}米"
        lines.append(f"{labels['crowd']}：{crowd.label}{crowd.rows}排{crowd.columns}列，间距约{crowd.spacing:g}米{where}")
    # 机位单独一行写，空间这一行不再说镜头站在哪。
    blocking = without_camera_pose(text.blocking)
    if blocking:
        lines.append(f"{labels['space']}：{blocking}")
    if text.eyeline:
        lines.append(f"{labels['gaze']}：{text.eyeline}")
    if text.action_axis:
        lines.append(f"{labels['axis']}：{text.action_axis}")
    for landmark in prompt_landmarks(plan)[: int(data["max_landmarks"])]:
        # 道具的尺寸是占位盒子(玉扳指也是半米见方)，写出来模型真会画那么大：道具只说备注。
        size = landmark_size(landmark) if landmark.kind != "prop" else ""
        if size or landmark.note:
            lines.append(f"{labels['set']}：{landmark.name}{size}" + (f"，{landmark.note}" if landmark.note else ""))
    if camera:
        pose = _camera_text(plan, shot, filming, timeline, start=text.camera_start, end=text.camera_end)
        if pose:
            lines.append(f"{labels['camera']}：{pose}")
    return lines


def new_clauses(lines: list[str], seen: set[str]) -> list[str]:
    """片段里前面的瞬间已经说过的分句不再说；一行全说过就整行不写。``seen`` 跟着记下。"""
    kept: list[str] = []
    for line in lines:
        label, _, body = line.partition("：")
        if label == _data()["labels"]["person"]:
            fresh = [body] if body not in seen else []
        else:
            fresh = [clause for clause in body.split("；") if clause and clause not in seen]
        seen.update(fresh)
        if fresh:
            kept.append(f"{label}：" + "；".join(fresh))
    return kept


def not_restated(lines: list[str], written: str) -> list[str]:
    """去掉正文已经一字不差写过的那部分(单镜的空间锚、视线锁就是同一句)。"""
    return [line for line in lines if line.partition("：")[2] not in written]


__all__ = ["new_clauses", "not_restated", "pose_text", "shot_lines", "title"]

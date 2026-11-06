# -*- coding: utf-8 -*-
"""每一镜的表演：姿势和动作轨道，按分镜的画面文字自动排好。

规划器只定站位、朝向和姿态；这里再给每个人物一个姿势预设（出拳、抱臂、鞠躬……从写到他名字的那个分句里读）
和一条动作轨道（走位走多久、坐下站起的过渡、说话的人用交谈片段），写进方案的 ``overrides`` 和
``timelines``。轨道只排分镜表写了时长的镜；导演台上人摆过的那一镜整条保留，不被自动的覆盖；词表在
``app/data/prompt/stage_performance.json``。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.core import prompt_data
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.coverage import ShotSpec
from app.core.spatial_stage.models import ActionClip, ActorKey, ActorOverride, ShotTimeline, StagePlan, StagePose, StageShot

_DATA = "stage_performance"
_CLAUSE_GAP = r"[^，,。；！？\n]{0,%d}?"


def _data() -> dict:
    return prompt_data.load(_DATA)


def _own_clauses(name: str, text: str, others: Sequence[str]) -> str:
    """从写到 ``name`` 起、到下一个写到别人为止的那几句：没有主语的后半句（「黄琰起身，抬手指向」）还是他的。"""
    text = str(text or "")
    start = text.find(name)
    if not name or start < 0:
        return ""
    tail = text[start + len(name):]
    # 别人当主语开头的分句才算换了人；「走向黄琰，一拳砸在案上」里的黄琰是宾语，后半句还是他的。
    stops = [
        found.start() for other in others if other and other != name
        for found in [re.search(r"[，,。；；！？\n]\s*" + re.escape(other), tail)] if found
    ]
    if not others:
        stops = [found.start() for found in [re.search(r"[，,。；！？\n]", tail)] if found]
    tail = tail[: min(stops)] if stops else tail
    return tail[: int(_data()["name_gap"]) * 4]


def gesture_in(name: str, text: str, others: Sequence[str] = ()) -> str:
    """写到 ``name`` 的那几句里做的手势，对应的姿势预设；没有就是空串。"""
    own = _own_clauses(name, text, others)
    for pattern, preset in _data()["gestures"]:
        if re.search(pattern, own):
            return str(preset)
    return ""


def pose_for(name: str, posture: str, text: str, others: Sequence[str] = ()) -> StagePose | None:
    """这一镜该摆的姿势：手势优先；没有手势时按姿态，站着不写（站立不是信息）。"""
    # 走和跑在动作轨道里，站着不是信息：这三种姿态不另写姿势。
    still = posture not in {"stand", "walk", "run"}
    preset = gesture_in(name, text, others) or (str(_data()["posture_presets"].get(posture) or "") if still else "")
    return StagePose(preset=preset) if preset else None


def _seconds(spec: ShotSpec) -> float:
    return max(1.0, min(30.0, float(spec.seconds)))


def _clips(slot: int, posture: str, before: str, *, speaks: bool, walk_s: float, duration: float) -> list[ActionClip]:
    """一个人的动作轨道：走位 → 坐下 / 站起过渡 → 待机或交谈。``slot`` 是这个人在本镜轨道里的序号，编号用它。"""
    data = _data()
    name = f"auto-{slot}"
    rest = str((data["talk_clips"] if speaks else data["posture_clips"]).get(posture) or data["posture_clips"].get(posture) or "")
    clips: list[ActionClip] = []
    at = 0.0
    if walk_s > 0.05:
        moving = str(data["posture_clips"]["run" if posture == "run" else "walk"])
        clips.append(ActionClip(id=f"{name}-move", clip=moving, start=0.0, end=round(min(walk_s, duration), 2)))
        at = clips[-1].end
        # 走到位就站住：之后的待机或交谈按站姿排，不再一路走到底。
        posture = "stand" if posture in {"walk", "run"} else posture
        rest = str((data["talk_clips"] if speaks else data["posture_clips"]).get(posture) or "")
    elif posture in {"walk", "run"}:
        rest = str(data["posture_clips"]["stand" if not speaks else "stand"]) if not speaks else str(data["talk_clips"]["stand"])
    transition = None
    if posture == "sit" and before != "sit":
        transition = data["sit_enter"]
    elif posture != "sit" and before == "sit":
        transition = data["sit_exit"]
    if transition and at + float(transition[1]) < duration:
        clips.append(ActionClip(id=f"{name}-change", clip=str(transition[0]), start=round(at, 2), end=round(at + float(transition[1]), 2)))
        at = clips[-1].end
    if rest and duration - at > 0.3:
        clips.append(ActionClip(id=f"{name}-rest", clip=rest, start=round(at, 2), end=round(duration, 2)))
    return clips


def _timeline(plan: StagePlan, shot: StageShot, spec: ShotSpec, before: dict[str, str]) -> ShotTimeline | None:
    """这一镜的动作轨道；分镜表没写时长就不排——时长是编出来的，轨道也就是编的。"""
    if not spec.seconds:
        return None
    duration = _seconds(spec)
    data = _data()
    staged = {actor.name: actor for actor in plan.actors_in(shot) if not actor.crowd_id}
    ending = {actor.name: actor for actor in plan.actors_in(shot, at_end=True)}
    changes = {item.name: item for item in shot.overrides}
    keys: dict[str, list[ActorKey]] = {}
    clips: dict[str, list[ActionClip]] = {}
    for slot, (name, actor) in enumerate(staged.items(), start=1):
        if name not in spec.subjects and name not in spec.desc:
            continue
        end = ending.get(name)
        change = changes.get(name)
        walk_s = 0.0
        if change is not None and change.position is not None and not change.hold and end is not None:
            start, mark = (actor.position[0], actor.position[1]), (end.position[0], end.position[1])
            meters = geo.distance(start, mark)
            if meters >= 0.2:
                speed = float(data["run_speed_mps"] if actor.posture == "run" else data["walk_speed_mps"])
                walk_s = min(meters / speed, duration * 0.8)
                keys[name] = [
                    ActorKey(time=0.0, position=list(start), yaw_deg=actor.yaw_deg),
                    ActorKey(time=round(walk_s, 2), position=list(mark), yaw_deg=end.yaw_deg),
                ]
        track = _clips(slot, actor.posture, before.get(name, actor.posture), speaks=spec.speaker == name, walk_s=walk_s, duration=duration)
        if track:
            clips[name] = track
    if not keys and not clips:
        return None
    return ShotTimeline(duration_s=round(duration, 2), actors=keys, clips=clips)


def stage(plan: StagePlan, specs: Sequence[ShotSpec], *, keep: StagePlan | None = None) -> StagePlan:
    """给 ``plan`` 的每一镜排上姿势与动作轨道。``keep`` 是人在导演台上编辑过的旧方案：它排过的镜照旧。"""
    kept = keep if keep is not None and keep.source == "edited" else None
    by_id = {spec.shot_id: spec for spec in specs}
    before: dict[str, str] = {actor.name: actor.posture for actor in plan.actors}
    shots: list[StageShot] = []
    timelines = dict(plan.timelines)
    for shot in plan.shots:
        spec = by_id.get(shot.shot_id)
        if spec is None:
            shots.append(shot)
            continue
        old = kept.shot(shot.shot_id) if kept is not None else None
        old_poses = {item.name: item.pose for item in (old.overrides if old is not None else []) if item.pose is not None}
        changes = {item.name: item for item in shot.overrides}
        for actor in plan.actors_in(shot):
            if actor.crowd_id or (actor.name not in spec.subjects and actor.name not in spec.desc):
                continue
            pose = old_poses.get(actor.name) or pose_for(actor.name, actor.posture, spec.desc, [item.name for item in plan.actors])
            if pose is None:
                continue
            current = changes.get(actor.name)
            if current is not None and current.pose is not None:
                continue
            changes[actor.name] = (current or ActorOverride(name=actor.name)).model_copy(update={"pose": pose})
        staged = shot.model_copy(update={"overrides": list(changes.values())})
        key = str(shot.shot_id)
        if kept is not None and key in kept.timelines:
            timelines[key] = kept.timelines[key]
        else:
            timeline = _timeline(plan, staged, spec, before)
            if timeline is not None:
                timelines[key] = timeline
            else:
                timelines.pop(key, None)
        shots.append(staged)
        for actor in plan.actors_in(staged, at_end=True):
            before[actor.name] = actor.posture
    return plan.model_copy(update={"shots": shots, "timelines": timelines, "actors": figures_for(plan, shots, timelines)})


def figures_for(plan: StagePlan, shots: Sequence[StageShot], timelines: dict[str, ShotTimeline]) -> list:
    """占位柱体画不出姿势和动作：摆了姿势的人换成假人（能看见关节），只有动作片段的人换成带蒙皮的人形。
    人自己选过模型的不动；群演不动。"""
    posed = {item.name for shot in shots for item in shot.overrides if item.pose is not None}
    moving = {name for timeline in timelines.values() for name in (*timeline.clips, *timeline.actors)}
    actors = []
    for actor in plan.actors:
        figure = actor.figure
        if figure == "standin" and not actor.crowd_id:
            figure = "mannequin" if actor.name in posed or actor.pose is not None else "humanoid" if actor.name in moving else figure
        actors.append(actor.model_copy(update={"figure": figure}) if figure != actor.figure else actor)
    return actors


__all__ = ["figures_for", "gesture_in", "pose_for", "stage"]

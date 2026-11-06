# -*- coding: utf-8 -*-
"""把一场的空间方案(StagePlan)换成 Blender 预演规格：每个镜头一段、镜与镜之间硬切。

- 坐标：方案是 three.js 的 Y 轴向上、地面点 (x, z)、yaw 0 面向 +Z；Blender 是 Z 轴向上。
  换算 (x, y, z)_three → (x, -z, y)_blender，yaw 数值不变(两边都是绕竖轴右手旋转)，Blender 代理的"前"是本地 -Y。
- 人物：胶囊体，按身高与姿态定尺寸；主要角色各用一种颜色，群演统一灰色；不在场的镜头隐藏。
- 机位：镜头有时间线就按时间线的机位/目标/焦段关键帧；没有就用镜头所用摄影机的起止位置(运镜 move)。
- 道具与布景：方案里的地标按形状与尺寸摆上去。
"""

from __future__ import annotations

from typing import Any, Mapping

from app.core.spatial_stage.glb import euler_matrix, multiply, multiply_vector, tinted
from app.core.spatial_stage.models import StageActor, StageLandmark, StagePlan, StageShot

from .spec import MAX_SET_BLOCKS, BlockingSpec, Block, Camera, Cut, Floor, Handheld, Key, LensKey, Proxy, Reserved, SetDressing, Target

#: 主要角色的区分色：相邻两色差得够远，视频参考里一眼分得清。
ACTOR_PALETTE = ("#2b2f8f", "#c8a24a", "#b03a2e", "#1e8449", "#8e44ad", "#d35400", "#17a589", "#c0392b",
                 "#2e86c1", "#7d6608", "#6c3483", "#117864")
EXTRA_COLOR = "#9a9a9a"
LANDMARK_COLORS = {"prop": "#8d99ae", "furniture": "#a0826d", "architecture": "#b8b2a8", "light": "#f4d03f"}
DEFAULT_SHOT_SECONDS = 4.0
ASPECT_RESOLUTIONS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1440, 1440), "4:3": (1440, 1080),
                      "3:4": (1080, 1440), "21:9": (2520, 1080)}
#: 姿态 → 代理高度系数；躺姿另外放倒。
POSTURE_HEIGHT = {"stand": 1.0, "walk": 1.0, "run": 0.97, "fight": 0.92, "lean": 0.97, "bow": 0.8,
                  "sit": 0.62, "kneel": 0.7, "crouch": 0.58, "lie": 0.28}


def to_blender(point: list[float] | tuple[float, ...]) -> tuple[float, float, float]:
    """three.js (x, y, z) → Blender (x, -z, y)。"""
    x, y, z = (float(v) for v in point)
    return (round(x, 4), round(-z, 4), round(y, 4))


def ground_to_blender(point: list[float] | tuple[float, ...], height: float = 0.0) -> tuple[float, float, float]:
    x, z = (float(v) for v in point)
    return (round(x, 4), round(-z, 4), round(height, 4))


def from_blender(point: list[float] | tuple[float, ...]) -> list[float]:
    """Blender (x, y, z) → three.js (x, z_up, -y)。"""
    x, y, z = (float(v) for v in point)
    return [round(x, 4), round(z, 4), round(-y, 4)]


def _resolution(aspect: str, long_edge: int) -> tuple[int, int]:
    width, height = ASPECT_RESOLUTIONS.get(aspect or "16:9", (1920, 1080))
    scale = long_edge / max(width, height)
    # H.264 要求偶数边长。
    return (int(round(width * scale / 2) * 2), int(round(height * scale / 2) * 2))


def _actor_size(actor: StageActor) -> tuple[float, float, float]:
    height = actor.height_m * POSTURE_HEIGHT.get(actor.posture, 1.0)
    width = max(0.32, min(0.6, actor.height_m * 0.27))
    return (width, width, max(height, 0.3))


def _single_block(landmark: StageLandmark) -> Block:
    return Block(
        id=landmark.id, name=landmark.name, shape=landmark.shape if landmark.shape in {"box", "cylinder", "sphere", "cone", "wedge"} else "box",
        size=(landmark.size[0], landmark.size[1], landmark.size[2]), position=ground_to_blender(landmark.position, landmark.elevation_m),
        yaw_deg=landmark.yaw_deg, color=landmark.color or LANDMARK_COLORS.get(landmark.kind, "#8d99ae"),
    )


def _part_blocks(landmark: StageLandmark) -> list[Block]:
    """组合模型拆成一个部件一块。部件的旋转矩阵在 three.js 坐标里算好，再整体换到 Blender 坐标(P·R·Pᵀ)。"""
    width, depth, height = landmark.size
    base = landmark.color or LANDMARK_COLORS.get(landmark.kind, "#8d99ae")
    yaw = euler_matrix((0.0, landmark.yaw_deg, 0.0))
    blocks = []
    for index, part in enumerate(landmark.parts):
        offset = (part.center[0] * width, part.center[1] * height, part.center[2] * depth)
        world = multiply_vector(yaw, offset)
        rotation = multiply(yaw, euler_matrix(part.rotation))
        # (x, y, z)_three → (x, -z, y)_blender
        basis = [
            rotation[0][0], -rotation[0][2], rotation[0][1],
            -rotation[2][0], rotation[2][2], -rotation[2][1],
            rotation[1][0], -rotation[1][2], rotation[1][1],
        ]
        blocks.append(Block(
            id=f"{landmark.id}-{index + 1}", name=landmark.name, shape=part.shape if part.shape != "plane" else "box",
            size=(max(0.005, part.size[0] * width), max(0.005, part.size[1] * depth), max(0.005, part.size[2] * height)),
            position=to_blender((landmark.position[0] + world[0], landmark.elevation_m + world[1], landmark.position[1] + world[2])),
            color=tinted(base, part.tone), basis=[round(value, 5) for value in basis],
        ))
    return blocks


def _blocks(plan: StagePlan) -> list[Block]:
    """布景方块；组合模型一个部件一块，超过规格上限的模型退回一个包围盒。"""
    blocks: list[Block] = []
    room = MAX_SET_BLOCKS - len(plan.landmarks)
    for landmark in plan.landmarks:
        extra = len(landmark.parts) - 1
        if landmark.parts and extra <= room:
            blocks.extend(_part_blocks(landmark))
            room -= extra
        else:
            blocks.append(_single_block(landmark))
    return blocks


def _durations(plan: StagePlan, durations: Mapping[int, float]) -> dict[int, float]:
    out = {}
    for shot in plan.shots:
        timeline = plan.timelines.get(str(shot.shot_id))
        seconds = timeline.duration_s if timeline is not None else durations.get(shot.shot_id) or DEFAULT_SHOT_SECONDS
        out[shot.shot_id] = max(1.0, min(30.0, float(seconds)))
    return out


def _carry(keys) -> list:
    """时间线的演员关键帧只写变化的字段，没写的沿用上一帧。"""
    position = yaw = None
    out = []
    for key in keys:
        position = key.position if key.position is not None else position
        yaw = key.yaw_deg if key.yaw_deg is not None else yaw
        out.append((key.time, position, yaw))
    return out


def build_spec(
    plan: StagePlan,
    *,
    durations: Mapping[int, float] | None = None,
    options: Mapping[str, Any] | None = None,
    shot_ids: list[int] | None = None,
    fps: int = 24,
    long_edge: int = 1920,
) -> tuple[BlockingSpec, list[dict]]:
    """返回 (规格, 镜头段)：段 = {shot_id, camera, start, end, seconds}，帧号从 1 起。"""
    options = dict(options or {})
    chosen = [shot for shot in plan.shots if shot_ids is None or shot.shot_id in set(shot_ids)]
    if not chosen:
        raise ValueError("这一场还没有可预演的镜头")
    seconds_of = _durations(plan, durations or {})
    segments: list[dict] = []
    frame = 1
    for shot in chosen:
        count = max(1, round(seconds_of[shot.shot_id] * fps))
        segments.append({"shot_id": shot.shot_id, "camera": shot.camera_id, "start": frame, "end": frame + count - 1,
                         "seconds": round(count / fps, 3)})
        frame += count
    total = frame - 1

    principals = [actor for actor in plan.actors if not actor.crowd_id]
    colors = {actor.name: (actor.color or ACTOR_PALETTE[index % len(ACTOR_PALETTE)]) for index, actor in enumerate(principals)}
    # 方案里手设的颜色可能撞色：撞了就换调色板里还没人用的。
    used: set[str] = set()
    for actor in principals:
        color = colors[actor.name].lower()
        if color in used:
            color = next(c for c in ACTOR_PALETTE if c.lower() not in used)
        colors[actor.name] = color
        used.add(color)

    proxies: list[Proxy] = []
    for index, actor in enumerate(plan.actors):
        keys: list[Key] = []
        hidden: list[tuple[int, int]] = []
        for segment, shot in zip(segments, chosen):
            staged_start = {a.name: a for a in plan.actors_in(shot)}
            staged_end = {a.name: a for a in plan.actors_in(shot, at_end=True)}
            if actor.name not in staged_start:
                hidden.append((segment["start"], segment["end"]))
                continue
            first, last = staged_start[actor.name], staged_end.get(actor.name, staged_start[actor.name])
            timeline = plan.timelines.get(str(shot.shot_id))
            track = timeline.actors.get(actor.name) if timeline is not None else None
            if track:
                for time, position, yaw in _carry(track):
                    at = min(segment["end"], segment["start"] + round(time * fps))
                    keys.append(Key(frame=at, position=ground_to_blender(position or first.position),
                                    yaw_deg=yaw if yaw is not None else first.yaw_deg))
            else:
                keys.append(Key(frame=segment["start"], position=ground_to_blender(first.position), yaw_deg=first.yaw_deg))
                if (last.position, last.yaw_deg) != (first.position, first.yaw_deg) and segment["end"] > segment["start"]:
                    keys.append(Key(frame=segment["end"], position=ground_to_blender(last.position), yaw_deg=last.yaw_deg))
        keys = _dedupe(keys)
        if not keys:
            keys = [Key(frame=1, position=ground_to_blender(actor.position), yaw_deg=actor.yaw_deg)]
            hidden = [(1, total)]
        extra = bool(actor.crowd_id)
        proxies.append(Proxy(
            id=f"actor-{index + 1:02d}", binds={"kind": "extra" if extra else "actor", "name": actor.name},
            shape="capsule", size=_actor_size(actor), color=EXTRA_COLOR if extra else colors[actor.name],
            keys=keys, hidden=_merge(hidden), lying=actor.posture == "lie",
        ))

    blocks = _blocks(plan)
    extent = max([8.0] + [abs(v) * 2 + 4 for a in plan.actors for v in a.position]
                 + [abs(v) * 2 + 4 for l in plan.landmarks for v in l.position])

    handheld_shots = {int(v) for v in options.get("handheld_shots") or []}
    cameras: list[Camera] = []
    cuts: list[Cut] = []
    for segment, shot in zip(segments, chosen):
        camera = _shot_camera(plan, shot, segment, fps)
        if shot.shot_id in handheld_shots:
            camera = camera.model_copy(update={"handheld": Handheld(start=segment["start"], end=segment["end"], seed=shot.shot_id)})
        cameras.append(camera)
        cuts.append(Cut(frame=segment["start"], camera=camera.id, label=f"镜{shot.shot_id}"))

    reserved = []
    for slot in options.get("reserved") or []:
        segment = next((s for s in segments if s["shot_id"] == int(slot.get("shot_id", 0))), None)
        if segment is None:
            continue
        start = segment["start"] + round(float(slot.get("from_s", 0)) * fps)
        end = segment["start"] + round(float(slot.get("to_s", segment["seconds"])) * fps) - 1
        reserved.append(Reserved(label=str(slot.get("label") or "专项效果")[:40],
                                 start=max(segment["start"], start), end=min(segment["end"], max(start, end))))

    spec = BlockingSpec(
        title=f"{plan.scene_id} {plan.location}"[:200], fps=fps, frames=total,
        resolution=_resolution(plan.aspect_ratio, long_edge),
        set=SetDressing(floor=Floor(size=(extent, extent)), blocks=blocks),
        proxies=proxies, cameras=cameras, cuts=cuts, reserved=reserved,
    )
    return spec, segments


def _shot_camera(plan: StagePlan, shot: StageShot, segment: dict, fps: int) -> Camera:
    """一镜一台 Blender 摄影机：位置与目标各走各的关键帧(摄影机管速度，目标管构图)。"""
    timeline = plan.timelines.get(str(shot.shot_id))
    cam_id = f"shot-{shot.shot_id:03d}"
    if timeline is not None and timeline.camera:
        keys, targets, lenses = [], [], []
        for key in timeline.camera:
            at = min(segment["end"], segment["start"] + round(key.time * fps))
            keys.append(Key(frame=at, position=to_blender(key.position)))
            targets.append(Key(frame=at, position=to_blender(key.target)))
            lenses.append(LensKey(frame=at, lens_mm=key.lens_mm))
        keys, targets = _dedupe(keys), _dedupe(targets)
        lens_keys = list({k.frame: k for k in lenses}.values()) if len({k.lens_mm for k in lenses}) > 1 else []
        return Camera(id=cam_id, lens_mm=timeline.camera[0].lens_mm, keys=keys, lens_keys=lens_keys,
                      target=Target(keys=targets), interpolation="BEZIER")
    stage_cam = plan.camera(shot.camera_id)
    if stage_cam is None:
        raise ValueError(f"第 {shot.shot_id} 镜用的摄影机 {shot.camera_id} 不在方案里")
    keys = [Key(frame=segment["start"], position=to_blender(stage_cam.position))]
    targets = [Key(frame=segment["start"], position=to_blender(stage_cam.target))]
    move = stage_cam.move
    if move.kind != "static" and segment["end"] > segment["start"]:
        if move.end_position is not None:
            keys.append(Key(frame=segment["end"], position=to_blender(move.end_position)))
        if move.end_target is not None:
            targets.append(Key(frame=segment["end"], position=to_blender(move.end_target)))
    return Camera(id=cam_id, lens_mm=stage_cam.lens_mm, keys=keys, target=Target(keys=targets))


def _dedupe(keys: list[Key]) -> list[Key]:
    by_frame: dict[int, Key] = {}
    for key in keys:
        by_frame[key.frame] = key
    return [by_frame[frame] for frame in sorted(by_frame)]


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def operations_from_snapshot(plan: StagePlan, snapshot: Mapping[str, Any], segments: list[dict]) -> list[dict]:
    """在 Blender 里拖过的站位、布景与机位，换回空间方案的语义操作(move_actor / move_landmark / move_camera)。

    只同步与方案差得够多(> 2 厘米或 > 1°)的项；有时间线的镜头机位由时间线管，不在这里改。
    """
    ops: list[dict] = []
    names = {f"actor-{index + 1:02d}": actor for index, actor in enumerate(plan.actors)}
    for item in snapshot.get("proxies") or []:
        actor = names.get(str(item.get("id")))
        if actor is None or actor.crowd_id:
            continue
        ground = from_blender(item["position"])
        position = [ground[0], ground[2]]
        change: dict[str, Any] = {}
        if max(abs(position[0] - actor.position[0]), abs(position[1] - actor.position[1])) > 0.02:
            change["position"] = [round(v, 3) for v in position]
        yaw = float(item.get("yaw_deg") or 0.0)
        if abs(((yaw - actor.yaw_deg + 180) % 360) - 180) > 1.0:
            change["yaw_deg"] = round(yaw, 1)
        if change:
            ops.append({"op": "move_actor", "name": actor.name, **change})
    landmarks = {landmark.id: landmark for landmark in plan.landmarks}
    for item in snapshot.get("blocks") or []:
        landmark = landmarks.get(str(item.get("id")))
        if landmark is None:
            continue
        ground = from_blender(item["position"])
        position = [round(ground[0], 3), round(ground[2], 3)]
        if max(abs(position[0] - landmark.position[0]), abs(position[1] - landmark.position[1])) > 0.02:
            ops.append({"op": "move_landmark", "name": landmark.name, "position": position})
    by_cam = {f"shot-{segment['shot_id']:03d}": segment for segment in segments}
    seen: set[str] = set()
    for item in snapshot.get("cameras") or []:
        segment = by_cam.get(str(item.get("id")))
        if segment is None or plan.timelines.get(str(segment["shot_id"])) is not None:
            continue
        stage_cam = plan.camera(segment["camera"])
        if stage_cam is None or stage_cam.id in seen or item.get("target") is None:
            continue
        position, target = from_blender(item["position"]), from_blender(item["target"])
        moved = max(abs(a - b) for a, b in zip(position + target, list(stage_cam.position) + list(stage_cam.target))) > 0.02
        lens_changed = abs(float(item.get("lens_mm") or stage_cam.lens_mm) - stage_cam.lens_mm) > 0.5
        if moved or lens_changed:
            seen.add(stage_cam.id)
            ops.append({"op": "move_camera", "camera_id": stage_cam.id, "position": position, "target": target,
                        "lens_mm": round(float(item.get("lens_mm") or stage_cam.lens_mm), 1)})
    return ops

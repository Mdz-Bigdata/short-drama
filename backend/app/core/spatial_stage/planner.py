# -*- coding: utf-8 -*-
"""Build the spatial stage of a scene from what the script and the storyboard table say.

Deterministic on purpose: the same cast, location and shot table always give the
same marks, so a re-run does not shuffle who stands where. The rules are the
staging conventions the shot-design skill already teaches — principals play
across one axis, a third person closes an inverted triangle upstage, groups arc
behind, cameras live on one side — turned into coordinates.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.coverage import ShotSpec, fit_move, keep_side, lens_bearing, repeats_the_angle, solve_camera
from app.core.spatial_stage.language import enters_in, posture_in, travel_in
from app.core.spatial_stage.models import (
    ActorOverride,
    StageActor,
    StageAxis,
    StageBackdrop,
    StageCamera,
    StageLandmark,
    StagePlan,
    StageShot,
)
from app.core.spatial_stage.projection import screen_states
from app.core.spatial_stage.prompting import scene_bible, shot_text
from app.core.spatial_stage.validation import MIN_ACTOR_SPACING_M, check_plan

EMPTY_CAST = frozenset({"空镜（无人物）", "空镜", "无", "无人", "无人物", ""})
CROWD_MARKERS: tuple[str, ...] = (
    "群演", "众", "们", "士兵", "追兵", "路人", "人群", "敌人", "杂兵", "护卫", "侍卫",
    "家丁", "打手", "军士", "士卒", "小兵", "匪徒", "围观", "群众", "百姓", "宾客", "随从",
)
_PLACEHOLDER_PROPS = ("本场无", "无额外", "无关键", "无道具")
_SEPARATION_RULES: tuple[tuple[tuple[str, ...], float, str], ...] = (
    (("拥抱", "相拥", "依偎", "搂", "耳语", "贴近", "亲吻", "搀扶", "抱住", "扶住"), 0.7, "贴身"),
    (("对峙", "拔刀", "拔剑", "持剑", "剑指", "交手", "打斗", "厮杀", "搏斗", "追杀", "对战", "举枪", "挥拳"), 2.6, "对峙"),
    (("跪", "叩首", "叩拜", "参拜", "行礼"), 2.2, "上下位"),
)
_SIDE_BY_SIDE = ("并肩", "并排", "同行", "携手", "一同走", "并辔", "结伴")
# Set dressing: (name on the stage, words that name it in a prop list, phrases that imply it in
# running script text, kind, size w/d/h, slot). Script phrases are whole words on purpose — a bare
# 门 / 案 / 几 also lives inside 门派 / 方案 / 几个.
_SET_PIECES: tuple[tuple[str, tuple[str, ...], tuple[str, ...], str, tuple[float, float, float], str], ...] = (
    ("门", ("门",), ("殿门", "宫门", "大门", "院门", "房门", "门口", "门外", "门内", "推门", "进门", "入口"),
     "architecture", (1.4, 0.2, 2.4), "upstage_right_far"),
    ("窗", ("窗",), ("窗前", "窗边", "窗外", "窗棂", "窗纸", "窗户"), "architecture", (1.6, 0.15, 1.4), "upstage_left_far"),
    ("屏风", ("屏风",), ("屏风",), "furniture", (2.4, 0.12, 1.9), "upstage_far"),
    ("床榻", ("床", "榻"), ("床榻", "床边", "床上", "卧榻", "病榻", "龙榻"), "furniture", (2.0, 1.4, 0.55), "upstage_left"),
    ("台阶", ("台阶", "石阶"), ("台阶", "石阶", "阶下", "阶前"), "architecture", (4.0, 1.2, 0.5), "upstage_deep"),
    ("柱", ("柱",), ("廊柱", "柱子", "殿柱", "石柱"), "architecture", (0.5, 0.5, 3.2), "stage_right"),
    ("树", ("树",), ("大树", "树下", "古树", "老树", "树影"), "architecture", (1.2, 1.2, 4.0), "upstage_left_far"),
    ("书案", ("书案", "案几", "桌", "案"), ("书案", "案几", "伏案", "案上", "案前", "桌上", "桌前", "桌边"),
     "furniture", (1.4, 0.7, 0.75), "between"),
    ("灯火", ("炭盆", "火盆", "火炉", "烛", "灯", "篝火"), ("炭盆", "火盆", "火炉", "烛台", "烛火", "灯笼", "油灯", "篝火"),
     "light", (0.4, 0.4, 0.6), "near_left"),
)
_PROP_SLOTS = ("between", "near_left", "near_right", "upstage_left", "upstage_right", "upstage_far")
# Why the planner itself puts someone off their mark for a shot.
ENTRANCE_REASON = "从画外一侧入场，走到既定站位"
APPROACH_REASON = "走近到既定站位"
RETREAT_REASON = "后退到既定站位"
_HOLD_REASONS = {APPROACH_REASON: "还站在稍远处，尚未走近", RETREAT_REASON: "还站在近处，尚未退开"}


@dataclass
class SceneBrief:
    scene_id: str
    location: str = ""
    text: str = ""
    characters: list[str] = field(default_factory=list)
    props: list[str] = field(default_factory=list)
    shots: list[ShotSpec] = field(default_factory=list)
    aspect_ratio: str = "9:16"


def location_key(location: str) -> str:
    """Two scenes share a set when their location reads the same once time of day and INT/EXT are dropped."""
    text = re.sub(r"[\s/／|｜·,，;；:：\-—]+", "", str(location or ""))
    suffix = re.compile(r"(凌晨|清晨|早晨|上午|中午|午后|下午|黄昏|傍晚|深夜|夜晚|白天|内景|外景|日|夜|晨|昼)$")
    while len(text) > 1 and suffix.search(text):
        text = suffix.sub("", text)
    return text[:200]


def is_crowd(name: str) -> bool:
    return any(marker in name for marker in CROWD_MARKERS)


def cast_fingerprint(characters: Sequence[str], location: str) -> str:
    names = sorted({name.strip() for name in characters if name.strip() not in EMPTY_CAST})
    return hashlib.sha1(("|".join(names) + "@" + location_key(location)).encode("utf-8")).hexdigest()[:16]


def speaker_of(dialogue: str, cast: Sequence[str]) -> str:
    """The character a storyboard dialogue cell attributes its line to."""
    text = str(dialogue or "").strip()
    match = re.match(r"^[【\[]?([^：:】\]]{1,20})[】\]]?\s*[（(]?[^：:）)]{0,20}[）)]?\s*[：:]", text)
    if not match:
        return ""
    head = match.group(1).strip()
    return next((name for name in cast if name and (name == head or name in head)), "")


def _slug(index: int) -> str:
    return f"actor-{index:02d}"


def _principals(cast: Sequence[str], shots: Sequence[ShotSpec]) -> list[str]:
    people = [name for name in cast if not is_crowd(name)]
    weight = {name: (len(people) - index) * 0.01 for index, name in enumerate(people)}
    for shot in shots:
        for name in shot.subjects:
            if name in weight:
                weight[name] += 1
        if shot.speaker in weight:
            weight[shot.speaker] += 2
    # The two the scene is about are chosen by how much of it they carry; which of them stands
    # screen left is not a matter of weight but of who the script names first.
    chosen = set(sorted(people, key=lambda name: -weight[name])[:2])
    return [name for name in people if name in chosen]


def _separation(text: str) -> tuple[float, str]:
    for words, meters, label in _SEPARATION_RULES:
        if any(word in text for word in words):
            return meters, label
    return 1.5, "对话"


def _posture(name: str, text: str, default: str = "stand") -> str:
    return posture_in(name, text, default) or default


def _slot(slot: str, left: geo.Vec2, right: geo.Vec2, normal: geo.Vec2, index: int = 0) -> geo.Vec2:
    centre = geo.midpoint(left, right)
    along = geo.unit(geo.sub(right, left), (1.0, 0.0))
    upstage = geo.scale(normal, -1.0)
    spots: dict[str, geo.Vec2] = {
        "between": geo.add(centre, geo.scale(upstage, 0.9)),
        "near_left": geo.add(geo.add(left, geo.scale(along, -0.7)), geo.scale(upstage, 0.6)),
        "near_right": geo.add(geo.add(right, geo.scale(along, 0.7)), geo.scale(upstage, 0.6)),
        "upstage_left": geo.add(geo.add(centre, geo.scale(along, -2.2)), geo.scale(upstage, 2.0)),
        "upstage_right": geo.add(geo.add(centre, geo.scale(along, 2.2)), geo.scale(upstage, 2.0)),
        "stage_right": geo.add(geo.add(centre, geo.scale(along, 3.0)), geo.scale(upstage, 1.2)),
        "upstage_far": geo.add(centre, geo.scale(upstage, 3.4)),
        "upstage_left_far": geo.add(geo.add(centre, geo.scale(along, -2.8)), geo.scale(upstage, 3.4)),
        "upstage_right_far": geo.add(geo.add(centre, geo.scale(along, 2.8)), geo.scale(upstage, 3.4)),
        "upstage_deep": geo.add(centre, geo.scale(upstage, 4.4)),
    }
    base = spots.get(slot, spots["upstage_far"])
    return geo.add(base, geo.scale(along, 1.1 * index)) if index else base


def _landmarks(
    brief: SceneBrief, left: geo.Vec2, right: geo.Vec2, normal: geo.Vec2,
    actors: Sequence[StageActor], inherited: Sequence[StageLandmark],
) -> list[StageLandmark]:
    """Set pieces: what the location already holds from an earlier scene, then this scene's props and named set dressing."""
    placed: dict[str, StageLandmark] = {item.name: item for item in inherited}
    text = f"{brief.location} {brief.text}"
    wanted: list[tuple[str, str, tuple[float, float, float], str]] = []
    covered: set[str] = set()
    for prop in brief.props:
        name = str(prop or "").strip()
        if not name or any(marker in name for marker in _PLACEHOLDER_PROPS) or name in EMPTY_CAST:
            continue
        match = next((entry for entry in _SET_PIECES if any(word in name for word in entry[1])), None)
        if match:
            covered.add(match[0])
        wanted.append((name[:120], match[3] if match else "prop", match[4] if match else (0.5, 0.5, 0.5), match[5] if match else ""))
    for piece, prop_words, phrases, kind, size, slot in _SET_PIECES:
        already = piece in covered or any(any(word in name for word in prop_words) for name in placed)
        if not already and any(phrase in text for phrase in phrases):
            wanted.append((piece, kind, size, slot))
    used: dict[str, int] = {}
    free = list(_PROP_SLOTS)
    for name, kind, size, slot in wanted:
        if name in placed or len(placed) >= 24:
            continue
        chosen = slot or (free.pop(0) if free else "upstage_far")
        if chosen in free:
            free.remove(chosen)
        point = _slot(chosen, left, right, normal, used.get(chosen, 0))
        used[chosen] = used.get(chosen, 0) + 1
        # Nothing is dressed onto a mark someone stands on.
        while any(geo.distance(point, (actor.position[0], actor.position[1])) < 0.55 for actor in actors):
            point = geo.add(point, geo.scale(normal, -0.6))
        taken = {item.id for item in placed.values()}
        number = len(placed) + 1
        while f"mark-{number:02d}" in taken:
            number += 1
        placed[name] = StageLandmark(
            id=f"mark-{number:02d}", name=name, kind=kind, position=geo.rounded(point), size=list(size),
        )
    return list(placed.values())


def _supporting_marks(count: int, separation: float) -> list[geo.Vec2]:
    """Upstage marks that close an inverted triangle, then flank it, never hidden behind a principal.

    Seen from the master (which looks at the pair from +Z), screen x is world x, so every slot keeps
    at least a body width of x clear of both principals.
    """
    half = separation / 2
    depth = max(1.6, half + 1.0)
    slots: list[geo.Vec2] = [(0.0, -depth)] if half >= 0.3 else []
    ring = 1
    while len(slots) < count:
        lateral = half + 1.1 * ring
        slots.extend([(-lateral, -depth * (0.55 if ring == 1 else 1.0)), (lateral, -depth * (0.55 if ring == 1 else 1.0))])
        if ring > 1:
            slots.append((0.0, -depth * ring))
        ring += 1
    return slots[:count]


def _stage_actors(
    brief: SceneBrief, principals: Sequence[str], side_memory: Mapping[str, str],
) -> tuple[list[StageActor], StageAxis, str]:
    cast = [name for name in dict.fromkeys(name.strip() for name in brief.characters) if name not in EMPTY_CAST]
    separation, mood = _separation(brief.text)
    side_by_side = any(word in brief.text for word in _SIDE_BY_SIDE)
    normal: geo.Vec2 = (0.0, 1.0)
    actors: list[StageActor] = []
    axis = StageAxis()
    formation = "空镜：无人物站位"

    if len(principals) >= 2:
        first, second = principals[0], principals[1]
        # A promise made in an earlier scene outranks the default "first named stands screen left".
        if side_memory.get(first) == "right" or (side_memory.get(second) == "left" and side_memory.get(first) != "left"):
            first, second = second, first
        left_mark, right_mark = geo.pair_positions((0.0, 0.0), (1.0, 0.0), separation)
        for name, mark, other, side in ((first, left_mark, right_mark, "left"), (second, right_mark, left_mark, "right")):
            actors.append(StageActor(
                id=_slug(len(actors) + 1), name=name, position=geo.rounded(mark),
                yaw_deg=0.0 if side_by_side else geo.yaw_toward(mark, other),
                posture=_posture(name, brief.text), role="principal", screen_side=side,
            ))
        axis = StageAxis(
            kind="dialogue", from_name=first, to_name=second,
            start=geo.rounded(left_mark), end=geo.rounded(right_mark), camera_side=1,
        )
        formation = ("同向并肩" if side_by_side else "面对面") + f"·{mood}·相距{separation:.1f}米"
    elif len(principals) == 1:
        name = principals[0]
        actors.append(StageActor(
            id=_slug(1), name=name, position=[0.0, 0.0], yaw_deg=90.0,
            posture=_posture(name, brief.text), role="principal",
            screen_side=side_memory.get(name) if side_memory.get(name) in {"left", "right"} else "left",
        ))
        formation = "单人·居中偏左，视线与动作朝画右留出空间"

    centre = (0.0, 0.0)
    supporting = [name for name in cast if name not in principals and not is_crowd(name)]
    if supporting:
        marks = _supporting_marks(len(supporting), separation)
        for name, mark in zip(supporting, marks):
            actors.append(StageActor(
                id=_slug(len(actors) + 1), name=name, position=geo.rounded(mark),
                yaw_deg=geo.yaw_toward(mark, centre), posture=_posture(name, brief.text), role="supporting",
            ))
        formation += f"；{'、'.join(supporting)}在两人后方成{'倒三角' if len(supporting) == 1 else '弧形'}"
    crowds = [name for name in cast if is_crowd(name)]
    if crowds:
        depth = max(3.4, separation / 2 + 2.8)
        # Off the centre line, so a crowd is never hidden exactly behind whoever closes the triangle.
        anchor = geo.add(geo.scale(normal, -depth), (1.5 if supporting else 0.0, 0.0))
        marks = geo.line_positions(len(crowds), anchor, (1.0, 0.0), 1.6)
        for name, mark in zip(crowds, marks):
            actors.append(StageActor(
                id=_slug(len(actors) + 1), name=name, position=geo.rounded(mark),
                yaw_deg=geo.yaw_toward(mark, centre), role="crowd", note="群体，按错落队形分布在此标记周围",
            ))
        formation += f"；{'、'.join(crowds)}在后景错落分布"
    if len(actors) > 1:
        apart = geo.separate([(actor.position[0], actor.position[1]) for actor in actors], 0.6)
        actors = [actor.model_copy(update={"position": geo.rounded(mark)}) for actor, mark in zip(actors, apart)]
    return actors, axis, formation[:200]


def _shot_overrides(plan: StagePlan, specs: Sequence[ShotSpec]) -> dict[int, list[ActorOverride]]:
    """Where the table puts someone off their mark for a shot.

    - A character the table shows arriving is off the set until that shot, and starts it
      2.2 m behind their mark on the side away from their partner.
    - A posture a shot gives a character (kneels, falls, sits) holds in the shots after it
      until another shot stands them up again.
    """
    overrides: dict[int, dict[str, ActorOverride]] = {}
    moved: set[str] = set()
    first_seen: dict[str, int] = {}
    for index, spec in enumerate(specs):
        for name in spec.subjects:
            first_seen.setdefault(name, index)
    for name, index in first_seen.items():
        actor, spec = plan.actor(name), specs[index]
        if actor is None or actor.role == "crowd":
            continue
        if not enters_in(name, spec.desc):
            continue
        mark = (actor.position[0], actor.position[1])
        partner = plan.actor(plan.axis.to_name if name == plan.axis.from_name else plan.axis.from_name)
        away = (
            geo.unit(geo.sub(mark, (partner.position[0], partner.position[1])), (1.0, 0.0))
            if partner is not None and partner.name != name else (1.0, 0.0)
        )
        start = geo.add(mark, geo.scale(away, 2.2))
        for earlier in specs[:index]:
            overrides.setdefault(earlier.shot_id, {})[name] = ActorOverride(name=name, offstage=True, reason="尚未入场")
        overrides.setdefault(spec.shot_id, {})[name] = ActorOverride(
            name=name, position=geo.rounded(start), yaw_deg=geo.yaw_toward(start, mark, actor.yaw_deg),
            posture="walk", reason=ENTRANCE_REASON,
        )
        moved.add(name)

    # Someone who walks up to / backs away from their partner inside a shot starts it off the mark
    # and ends it on the mark, so the move is on the stage and the next shot still finds them there.
    # One mark holds one move: whoever already entered or moved in this scene is not staged again
    # (a second start off the mark would jump them across the floor at the cut into it).
    retreating = {actor.name for spec in specs for actor in plan.actors if travel_in(actor.name, spec.desc) == "retreat"}
    for spec_index, spec in enumerate(specs):
        for actor in plan.actors:
            if actor.role == "crowd" or actor.name in moved or actor.name in overrides.get(spec.shot_id, {}):
                continue
            travel = travel_in(actor.name, spec.desc)
            if not travel:
                continue
            mark = (actor.position[0], actor.position[1])
            partner = plan.actor(plan.axis.to_name if actor.name == plan.axis.from_name else plan.axis.from_name)
            toward = (
                geo.unit(geo.sub((partner.position[0], partner.position[1]), mark), geo.forward_of(actor.yaw_deg))
                if partner is not None and partner.name != actor.name else geo.forward_of(actor.yaw_deg)
            )
            retreat = travel == "retreat"
            step = 1.2
            if retreat:
                # Backing off starts nearer the partner, never past them: of two people who both back
                # off in the scene, each takes half of the room left above arm's length.
                paired = partner is not None and partner.name != actor.name
                gap = geo.distance(mark, (partner.position[0], partner.position[1])) if paired else 2.0
                step = min(0.6, (gap - MIN_ACTOR_SPACING_M - 0.1) / (2 if paired and partner.name in retreating else 1))
                if step < 0.15:
                    continue
            start = geo.add(mark, geo.scale(toward, step if retreat else -step))
            walk = ActorOverride(
                name=actor.name, position=geo.rounded(start),
                yaw_deg=actor.yaw_deg if retreat else geo.yaw_toward(start, mark, actor.yaw_deg),
                posture="stand" if retreat else "walk",
                reason=RETREAT_REASON if retreat else APPROACH_REASON,
            )
            overrides.setdefault(spec.shot_id, {})[actor.name] = walk
            moved.add(actor.name)
            # They have been standing where the walk starts: the shots before it hold them there.
            for earlier in specs[:spec_index]:
                overrides.setdefault(earlier.shot_id, {})[actor.name] = ActorOverride(
                    name=actor.name, position=walk.position, yaw_deg=actor.yaw_deg, hold=True,
                    reason=_HOLD_REASONS[walk.reason],
                )

    held: dict[str, str] = {actor.name: actor.posture for actor in plan.actors}
    for spec in specs:
        for actor in plan.actors:
            held[actor.name] = _posture(actor.name, spec.desc, held[actor.name])
            if held[actor.name] == actor.posture:
                continue
            existing = overrides.setdefault(spec.shot_id, {}).get(actor.name)
            if existing is None:
                overrides[spec.shot_id][actor.name] = ActorOverride(name=actor.name, posture=held[actor.name])
            elif not existing.offstage and (existing.position is None or existing.hold):
                overrides[spec.shot_id][actor.name] = existing.model_copy(update={"posture": held[actor.name]})
    return {shot_id: list(changes.values()) for shot_id, changes in overrides.items() if changes}


def _carry_camera(camera: StageCamera, shot: StageShot, plan: StagePlan) -> StageCamera:
    """A moving camera on a subject who walks to their mark travels with them and lands on the mark."""
    if camera.move.kind == "static" or not camera.subjects:
        return camera
    change = next((item for item in shot.overrides if item.name == camera.subjects[0] and item.position and not item.hold), None)
    actor = plan.actor(camera.subjects[0])
    if change is None or actor is None:
        return camera
    shift = geo.sub((actor.position[0], actor.position[1]), (change.position[0], change.position[1]))
    end_target = camera.move.end_target or camera.target
    end_position = camera.move.end_position or camera.position
    target = [end_target[0] + shift[0], end_target[1], end_target[2] + shift[1]]
    position = list(end_position) if camera.move.kind == "pan" else [
        end_position[0] + shift[0], end_position[1], end_position[2] + shift[1],
    ]
    if not axis_rules.is_overhead(camera):
        position = list(keep_side(tuple(position), plan.axis))
    return camera.model_copy(update={"move": camera.move.model_copy(update={
        "end_position": geo.rounded(position), "end_target": geo.rounded(target),
    })})


def fit_moves(plan: StagePlan) -> StagePlan:
    """Every moving camera ends with the people it frames still in frame."""
    cameras = {camera.id: camera for camera in plan.cameras}
    for shot in plan.shots:
        camera = cameras.get(shot.camera_id)
        if camera is not None and camera.move.kind != "static":
            cameras[camera.id] = fit_move(camera, plan.actors_in(shot), plan.actors_in(shot, at_end=True), plan.axis)
    return plan.model_copy(update={"cameras": [cameras[camera.id] for camera in plan.cameras]})


def template_shots(principals: Sequence[str], cast: Sequence[str]) -> list[ShotSpec]:
    """Standard coverage for a scene that has no storyboard table yet."""
    people = [name for name in cast if name not in EMPTY_CAST]
    if not people:
        return [ShotSpec(shot_id=1, size="全景", desc="环境建立")]
    if len(principals) < 2:
        lead = principals[0] if principals else people[0]
        return [
            ShotSpec(shot_id=1, subjects=[lead], size="全景"),
            ShotSpec(shot_id=2, subjects=[lead], size="中景"),
            ShotSpec(shot_id=3, subjects=[lead], size="特写"),
        ]
    first, second = principals[0], principals[1]
    shots = [
        ShotSpec(shot_id=1, subjects=list(people), size="全景"),
        ShotSpec(shot_id=2, subjects=[first, second], size="中景"),
        ShotSpec(shot_id=3, subjects=[first], speaker=first, size="近景", angle="过肩"),
        ShotSpec(shot_id=4, subjects=[second], speaker=second, size="近景", angle="过肩"),
        ShotSpec(shot_id=5, subjects=[first], speaker=first, size="特写"),
        ShotSpec(shot_id=6, subjects=[second], speaker=second, size="特写"),
    ]
    others = [name for name in people if name not in principals and not is_crowd(name)]
    shots.extend(
        ShotSpec(shot_id=len(shots) + index + 1, subjects=[name], speaker=first, size="近景")
        for index, name in enumerate(others[:3])
    )
    return shots


def sync_axis(plan: StagePlan) -> StagePlan:
    """Keep the axis on the two things it joins when either of them has moved; drop it when one is gone."""
    if plan.axis.kind == "none":
        return plan
    points: dict[str, list[float]] = {actor.name: list(actor.position) for actor in plan.actors}
    points.update({item.name: list(item.position) for item in plan.landmarks if item.name not in points})
    start, end = points.get(plan.axis.from_name), points.get(plan.axis.to_name)
    if start is None or end is None:
        return plan.model_copy(update={"axis": StageAxis()})
    return plan.model_copy(update={"axis": plan.axis.model_copy(update={"start": start, "end": end})})


def refresh(plan: StagePlan) -> StagePlan:
    """Recompute everything a plan *derives* (screen states, axis sides, prose, checks) from what it *states*."""
    plan = sync_axis(plan)
    cameras = {camera.id: camera for camera in plan.cameras}
    principals = [name for name in (plan.axis.from_name, plan.axis.to_name) if plan.actor(name)]
    shots: list[StageShot] = []
    for shot in plan.shots:
        camera = cameras[shot.camera_id]
        staged = plan.actors_in(shot)
        measured = shot.model_copy(update={
            "subjects": list(camera.subjects),
            "function": camera.function,
            "screen": screen_states(staged, camera),
            "axis_side": (
                axis_rules.camera_side(plan.axis, camera, end=camera.move.kind in {"orbit", "track", "follow"})
                if axis_rules.has_axis(plan.axis) else 0
            ),
            "crossing": axis_rules.crossing_kind(plan.axis, camera, principals) if axis_rules.has_axis(plan.axis) else "none",
        })
        shots.append(measured)
    staged_plan = plan.model_copy(update={"shots": shots})
    worded = [
        shot.model_copy(update={"text": shot_text(staged_plan, shot, cameras[shot.camera_id])})
        for shot in staged_plan.shots
    ]
    staged_plan = staged_plan.model_copy(update={"shots": worded})
    return staged_plan.model_copy(update={
        "checks": check_plan(staged_plan),
        "scene_bible": scene_bible(staged_plan),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def build_plan(
    brief: SceneBrief,
    *,
    side_memory: Mapping[str, str] | None = None,
    location_landmarks: Sequence[StageLandmark] = (),
    blocking_from: StagePlan | None = None,
) -> StagePlan:
    """The stage of ``brief``.

    ``blocking_from`` is an earlier plan for the same cast and set (a person's edit, or the
    blocking the storyboard table was written against): its marks, set pieces and axis are
    kept and only the cameras and per-shot changes are solved again for the new shots.
    """
    cast = [name for name in dict.fromkeys(name.strip() for name in brief.characters) if name not in EMPTY_CAST]
    specs = list(brief.shots)
    coverage = "storyboard"
    principals = _principals(cast, specs)
    if not specs:
        specs, coverage = template_shots(principals, cast), "template"

    kept_crowds = list(blocking_from.crowds) if blocking_from is not None else []
    backdrop = blocking_from.backdrop if blocking_from is not None else StageBackdrop()
    if blocking_from is not None:
        actors, axis, formation = list(blocking_from.actors), blocking_from.axis, blocking_from.formation
        landmarks = list(blocking_from.landmarks)
    else:
        actors, axis, formation = _stage_actors(brief, principals, side_memory or {})
        left = (axis.start[0], axis.start[1]) if axis_rules.has_axis(axis) else (-0.75, 0.0)
        right = (axis.end[0], axis.end[1]) if axis_rules.has_axis(axis) else (0.75, 0.0)
        landmarks = _landmarks(brief, left, right, (0.0, 1.0), actors, location_landmarks)
        # A lone character plays to the first thing on the set: that gaze is the scene's axis.
        if len(principals) == 1 and landmarks and actors:
            lead, focus = actors[0], landmarks[0]
            point = (focus.position[0], focus.position[1])
            if geo.distance((lead.position[0], lead.position[1]), point) > 0.3:
                # Keep the character screen left of what they look at.
                if point[0] < lead.position[0]:
                    point = (lead.position[0] + abs(point[0] - lead.position[0]) + 0.8, point[1])
                    landmarks[0] = focus.model_copy(update={"position": geo.rounded(point)})
                actors[0] = lead.model_copy(update={"yaw_deg": geo.yaw_toward((lead.position[0], lead.position[1]), point)})
                axis = StageAxis(
                    kind="gaze", from_name=lead.name, to_name=focus.name,
                    start=list(lead.position), end=geo.rounded(point), camera_side=1,
                )

    centre = geo.centroid([(actor.position[0], actor.position[1]) for actor in actors if actor.role != "crowd"])
    known = {actor.name for actor in actors}
    cameras: list[StageCamera] = []
    shots: list[StageShot] = []
    pair = [name for name in (axis.from_name, axis.to_name) if name in known] or principals

    def solve(index: int, spec: ShotSpec, staged: Sequence[StageActor], avoid: geo.Vec2 | None = None) -> StageCamera:
        return solve_camera(
            spec, staged, axis, aspect_ratio=brief.aspect_ratio, principals=pair,
            landmarks=landmarks, stage_center=centre, first_shot=index == 0, avoid_bearing=avoid,
        )

    for index, spec in enumerate(specs):
        spec.subjects = [name for name in dict.fromkeys(spec.subjects) if name in known]
        cameras.append(solve(index, spec, actors))
        shots.append(StageShot(
            shot_id=spec.shot_id, camera_id=cameras[-1].id, subjects=list(spec.subjects),
            speaker=spec.speaker[:120], action=spec.desc[:1000],
        ))

    plan = StagePlan(
        scene_id=brief.scene_id, location=brief.location[:500], location_key=location_key(brief.location),
        aspect_ratio=brief.aspect_ratio, formation=formation, coverage=coverage,
        # A crowd array is carried with its members: an actor that names a crowd the plan does not
        # hold is not a valid stage, so dropping the record would refuse the re-plan outright.
        actors=actors, crowds=kept_crowds, landmarks=landmarks, axis=axis, backdrop=backdrop,
        cameras=cameras, shots=shots,
        source=blocking_from.source if blocking_from is not None else "auto",
        revision=(blocking_from.revision + 1) if blocking_from is not None else 1,
        cast_fingerprint=cast_fingerprint(cast, brief.location),
    )
    changes = _shot_overrides(plan, specs)
    if changes:
        plan = plan.model_copy(update={"shots": [
            shot.model_copy(update={"overrides": changes.get(shot.shot_id, [])}) for shot in plan.shots
        ]})
        # Someone off their mark is shot where they actually are, and a moving camera goes with them.
        resolved = []
        for index, (spec, camera, shot) in enumerate(zip(specs, plan.cameras, plan.shots)):
            if shot.overrides:
                camera = _carry_camera(solve(index, spec, plan.actors_in(shot)), shot, plan)
            resolved.append(camera)
        plan = plan.model_copy(update={"cameras": resolved})

    # The 30-degree rule: a shot that would repeat the previous one's people, size and direction
    # is taken from somewhere else on the same side instead, so the cut does not read as a jump.
    varied = list(plan.cameras)
    for index in range(1, len(varied)):
        if not repeats_the_angle(varied[index - 1], varied[index]):
            continue
        avoid = lens_bearing(varied[index - 1], (varied[index].target[0], varied[index].target[2]))
        shot = plan.shots[index]
        varied[index] = _carry_camera(solve(index, specs[index], plan.actors_in(shot), avoid), shot, plan)
    plan = plan.model_copy(update={"cameras": varied})
    return refresh(fit_moves(plan))


__all__ = [
    "CROWD_MARKERS",
    "EMPTY_CAST",
    "SceneBrief",
    "build_plan",
    "cast_fingerprint",
    "fit_moves",
    "is_crowd",
    "location_key",
    "refresh",
    "speaker_of",
    "template_shots",
]

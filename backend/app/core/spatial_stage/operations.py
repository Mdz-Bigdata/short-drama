# -*- coding: utf-8 -*-
"""Edit a spatial stage by meaning, not by typing coordinates.

"Put C on A's left", "face these two 1.2 m apart", "arc the guards behind them",
"A is screen left of the master camera" are resolved against an explicit frame
of reference — the world, a character's own facing, or a camera's view — so
"left" is never ambiguous. Every operation returns a refreshed plan: screen
positions, prose and checks are recomputed from the new state.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import camera_moves, crowds
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.coverage import ShotSpec, fit_move, named_size, solve_camera
from app.core.spatial_stage.models import (
    MAX_ACTORS,
    MAX_POSE_JOINTS,
    ActorOverride,
    CameraMove,
    ShotTimeline,
    StageActor,
    StageAxis,
    StageBackdrop,
    StageCamera,
    StageCrowd,
    StageLandmark,
    StagePlan,
    StagePose,
)
from app.core.spatial_stage.planner import refresh
from app.core.spatial_stage.projection import SHOT_SIZE_HEIGHTS, CameraView

RELATIONS = ("front", "behind", "left", "right", "foreground", "background")
REFERENCES = ("actor", "camera", "world")
ORIENTS = ("anchor", "same_direction", "away", "none")
LAYOUTS = ("line", "arc", "circle", "grid")
FACINGS = ("center", "outward", "same_direction", "target", "none")
_MOVE_WORDS = {
    "static": "固定", "push": "推", "pull": "拉", "pan": "摇", "track": "横移",
    "orbit": "环绕", "rise": "升", "fall": "降", "follow": "跟拍",
}
MAX_OPERATIONS = 100
LANDMARK_KINDS = ("prop", "furniture", "architecture", "light")
LANDMARK_SHAPES = ("box", "cylinder", "sphere", "cone", "wedge", "plane")
BACKDROP_KINDS = ("none", "color", "image", "panorama")
FIGURES = ("standin", "mannequin", "humanoid")
MAX_CROWD_MEMBERS = 150
MAX_ALT_CAMERAS = 8
_EXTRA_PREFIX = "extra-"
_JOINT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,59}$")
_HTTP_URL = re.compile(r"^https?://", re.IGNORECASE)
_LOWEST_LENS_M = 0.05


class StageEditError(ValueError):
    """An operation cannot be applied; the message names the operation and what is wrong with it."""


def _ground(value: Any, label: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise StageEditError(f"{label} 必须是 [x, z] 两个米制坐标")
    try:
        point = [float(value[0]), float(value[1])]
    except (TypeError, ValueError) as error:
        raise StageEditError(f"{label} 必须是数字") from error
    if any(abs(item) > 500 or item != item for item in point):
        raise StageEditError(f"{label} 超出场地范围（±500 米）")
    return geo.rounded(point)


def _space(value: Any, label: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise StageEditError(f"{label} 必须是 [x, y, z] 三个米制坐标")
    try:
        point = [float(item) for item in value]
    except (TypeError, ValueError) as error:
        raise StageEditError(f"{label} 必须是数字") from error
    if any(abs(item) > 500 or item != item for item in point):
        raise StageEditError(f"{label} 超出场地范围（±500 米）")
    return geo.rounded(point)


def _number(value: Any, label: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise StageEditError(f"{label} 必须是数字") from error
    if number != number or not low <= number <= high:
        raise StageEditError(f"{label} 必须在 {low:g} 到 {high:g} 之间")
    return number


def _choice(value: Any, options: Sequence[str], label: str, default: str) -> str:
    text = str(value or default)
    if text not in options:
        raise StageEditError(f"{label} 只能是 {' / '.join(options)}")
    return text


def _text(value: Any, label: str, limit: int, *, required: bool = True) -> str:
    text = str(value if value is not None else "").strip()
    if required and not text:
        raise StageEditError(f"{label} 不能为空")
    if len(text) > limit:
        raise StageEditError(f"{label} 不能超过 {limit} 个字符")
    return text


def _whole(value: Any, label: str, low: int, high: int) -> int:
    number = _number(value, label, low, high)
    if number != int(number):
        raise StageEditError(f"{label} 必须是整数")
    return int(number)


def _color(value: Any) -> str:
    text = str(value or "").strip()
    if text and not (len(text) == 7 and text[0] == "#" and all(char in "0123456789abcdefABCDEF" for char in text[1:])):
        raise StageEditError("color 必须是 #rrggbb，或留空使用默认颜色")
    return text.lower()


def _http_url(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) > 2000:
        raise StageEditError("url 不能超过 2000 个字符")
    if text and not _HTTP_URL.match(text):
        raise StageEditError("背景图地址必须是 http(s) 链接")
    return text


def _size(value: Any) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise StageEditError("size 必须是 [宽, 深, 高] 三个米制尺寸")
    return [round(_number(item, "size", 0.02, 200), 3) for item in value]


def _next_number(ids: Sequence[str], prefix: str) -> int:
    tails = [item[len(prefix):].split("-", 1)[0] for item in ids if item.startswith(prefix)]
    return 1 + max((int(tail) for tail in tails if tail.isdigit()), default=0)


class _Editor:
    def __init__(self, plan: StagePlan):
        self.crowds: list[StageCrowd] = list(plan.crowds)
        self.timelines: dict[str, ShotTimeline] = dict(plan.timelines)
        self.actors: list[StageActor] = list(plan.actors)
        self.landmarks: list[StageLandmark] = list(plan.landmarks)
        self.cameras: list[StageCamera] = list(plan.cameras)
        self.shots = list(plan.shots)
        self.axis: StageAxis = plan.axis
        self.backdrop: StageBackdrop = plan.backdrop
        self.formation = plan.formation
        self.plan = plan

    # ---- lookups
    def actor_index(self, name: Any) -> int:
        index = next((i for i, actor in enumerate(self.actors) if actor.name == str(name or "")), None)
        if index is None:
            raise StageEditError(f"场上没有人物「{name}」")
        return index

    def camera_index(self, camera_id: Any) -> int:
        index = next((i for i, camera in enumerate(self.cameras) if camera.id == str(camera_id or "")), None)
        if index is None:
            raise StageEditError(f"场上没有机位「{camera_id}」")
        return index

    def shot_index(self, shot_id: Any) -> int:
        try:
            wanted = int(shot_id)
        except (TypeError, ValueError) as error:
            raise StageEditError("shot_id 必须是镜头编号") from error
        index = next((i for i, shot in enumerate(self.shots) if shot.shot_id == wanted), None)
        if index is None:
            raise StageEditError(f"本场没有第 {wanted} 镜")
        return index

    def landmark_index(self, name: Any) -> int:
        index = next((i for i, item in enumerate(self.landmarks) if item.name == str(name or "")), None)
        if index is None:
            raise StageEditError(f"场上没有地标「{name}」")
        return index

    def crowd_index(self, crowd_id: Any) -> int:
        index = next((i for i, crowd in enumerate(self.crowds) if crowd.id == str(crowd_id or "")), None)
        if index is None:
            raise StageEditError(f"场上没有群演阵列「{crowd_id}」")
        return index

    def free_name(self, name: str) -> bool:
        return not any(actor.name == name for actor in self.actors) and not any(item.name == name for item in self.landmarks)

    def forget(self, names: set[str]) -> None:
        """People who left the stage leave every shot too: subjects, per-shot changes, animation tracks."""
        self.cameras = [
            camera.model_copy(update={"subjects": [name for name in camera.subjects if name not in names]})
            if any(name in names for name in camera.subjects) else camera
            for camera in self.cameras
        ]
        self.shots = [
            shot.model_copy(update={
                "subjects": [name for name in shot.subjects if name not in names],
                "overrides": [item for item in shot.overrides if item.name not in names],
            })
            for shot in self.shots
        ]
        self.timelines = {
            key: timeline.model_copy(update={"actors": {name: keys for name, keys in timeline.actors.items() if name not in names}})
            for key, timeline in self.timelines.items()
        }

    def point_of(self, name: Any) -> geo.Vec2:
        text = str(name or "")
        for actor in self.actors:
            if actor.name == text:
                return (actor.position[0], actor.position[1])
        for landmark in self.landmarks:
            if landmark.name == text:
                return (landmark.position[0], landmark.position[1])
        raise StageEditError(f"场上没有「{text}」")

    def update_actor(self, index: int, **changes: Any) -> None:
        self.actors[index] = self.actors[index].model_copy(update=changes)

    # ---- frames of reference
    def basis(self, op: Mapping[str, Any], anchor: StageActor | None) -> tuple[geo.Vec2, geo.Vec2]:
        reference = _choice(op.get("reference"), REFERENCES, "reference", "actor")
        if reference == "camera":
            camera = self.cameras[self.camera_index(op.get("camera_id") or (self.cameras[0].id if self.cameras else ""))]
            view = CameraView.of(camera)
            return view.ground_forward(), view.ground_right()
        if reference == "actor":
            if anchor is None:
                raise StageEditError("以人物为参照时必须给出 anchor")
            forward = geo.forward_of(anchor.yaw_deg)
            return forward, geo.right_of(forward)
        return (0.0, 1.0), geo.right_of((0.0, 1.0))

    # ---- operations
    def move_actor(self, op: Mapping[str, Any]) -> None:
        index = self.actor_index(op.get("name"))
        changes: dict[str, Any] = {}
        if "position" in op:
            changes["position"] = _ground(op["position"], "position")
        if "yaw_deg" in op:
            changes["yaw_deg"] = geo.normalize_yaw(_number(op["yaw_deg"], "yaw_deg", -360, 360))
        if "posture" in op:
            changes["posture"] = str(op["posture"])
        if "height_m" in op:
            changes["height_m"] = _number(op["height_m"], "height_m", 0.4, 3.0)
        if not changes:
            raise StageEditError("move_actor 需要 position / yaw_deg / posture / height_m 之一")
        self.update_actor(index, **changes)

    def place_relative(self, op: Mapping[str, Any]) -> None:
        index = self.actor_index(op.get("name"))
        anchor_name = op.get("anchor")
        anchor = self.actors[self.actor_index(anchor_name)] if anchor_name and any(a.name == anchor_name for a in self.actors) else None
        origin = self.point_of(anchor_name) if anchor_name else (0.0, 0.0)
        if anchor is not None and anchor.name == self.actors[index].name:
            raise StageEditError("人物不能相对自己摆位")
        relation = _choice(op.get("relation"), RELATIONS, "relation", "front")
        reference = str(op.get("reference") or "actor")
        if relation in {"foreground", "background"} and reference != "camera":
            raise StageEditError("foreground / background 只在以机位为参照时成立")
        forward, right = self.basis(op, anchor)
        direction = {
            "front": forward, "behind": geo.scale(forward, -1.0),
            "right": right, "left": geo.scale(right, -1.0),
            # Toward the lens is the foreground; away from it, the background.
            "foreground": geo.scale(forward, -1.0), "background": forward,
        }[relation]
        if reference == "camera" and relation in {"front", "behind"}:
            direction = geo.scale(direction, -1.0)  # "in front of A" for an audience is nearer the lens
        meters = _number(op.get("distance", 1.0), "distance", 0.0, 100.0)
        spot = geo.add(origin, geo.scale(direction, meters))
        orient = _choice(op.get("orient"), ORIENTS, "orient", "anchor")
        yaw = self.actors[index].yaw_deg
        if orient == "anchor":
            yaw = geo.yaw_toward(spot, origin, yaw)
        elif orient == "away":
            yaw = geo.yaw_toward(origin, spot, yaw)
        elif orient == "same_direction" and anchor is not None:
            yaw = anchor.yaw_deg
        self.update_actor(index, position=geo.rounded(spot), yaw_deg=yaw)

    def face_pair(self, op: Mapping[str, Any]) -> None:
        first, second = self.actor_index(op.get("first")), self.actor_index(op.get("second"))
        if first == second:
            raise StageEditError("face_pair 需要两个不同的人物")
        a, b = self.actors[first], self.actors[second]
        start, end = (a.position[0], a.position[1]), (b.position[0], b.position[1])
        separation = _number(op.get("distance", geo.distance(start, end) or 1.5), "distance", 0.2, 100.0)
        left, right = geo.pair_positions(geo.midpoint(start, end), geo.sub(end, start), separation)
        self.update_actor(first, position=geo.rounded(left), yaw_deg=geo.yaw_toward(left, right, a.yaw_deg))
        self.update_actor(second, position=geo.rounded(right), yaw_deg=geo.yaw_toward(right, left, b.yaw_deg))

    def arrange_group(self, op: Mapping[str, Any]) -> None:
        names = op.get("names")
        if not isinstance(names, Sequence) or isinstance(names, (str, bytes)) or not 1 <= len(names) <= 60:
            raise StageEditError("arrange_group 需要 1-60 个人物名")
        indexes = [self.actor_index(name) for name in names]
        if len(set(indexes)) != len(indexes):
            raise StageEditError("arrange_group 的人物不能重复")
        layout = _choice(op.get("layout"), LAYOUTS, "layout", "line")
        current = [(self.actors[i].position[0], self.actors[i].position[1]) for i in indexes]
        centre = tuple(_ground(op["center"], "center")) if "center" in op else geo.centroid(current)
        forward, right = self.basis({**op, "reference": op.get("reference") or "world"}, None)
        spacing = _number(op.get("spacing", 1.2), "spacing", 0.3, 100.0)
        count = len(indexes)
        radius = _number(op.get("radius", max(spacing, count * spacing / 6.283)), "radius", 0.3, 100.0)
        if layout == "line":
            marks = geo.line_positions(count, centre, right, spacing)
        elif layout == "grid":
            marks = geo.grid_positions(count, centre, right, spacing, int(op["columns"]) if op.get("columns") else None)
        elif layout == "circle":
            marks = geo.circle_positions(count, centre, forward, radius)
        else:
            marks = geo.arc_positions(count, centre, geo.scale(forward, -1.0), radius, _number(op.get("arc_degrees", 120), "arc_degrees", 1, 359))
        facing = _choice(op.get("facing"), FACINGS, "facing", "center")
        target = self.point_of(op["target"]) if facing == "target" and op.get("target") else centre
        for index, mark in zip(indexes, marks):
            yaw = self.actors[index].yaw_deg
            if facing in {"center", "target"}:
                yaw = geo.yaw_toward(mark, target, yaw)
            elif facing == "outward":
                yaw = geo.yaw_toward(centre, mark, yaw)
            elif facing == "same_direction":
                yaw = geo.yaw_toward((0.0, 0.0), forward, yaw)
            self.update_actor(index, position=geo.rounded(mark), yaw_deg=yaw)

    def orient_toward(self, op: Mapping[str, Any]) -> None:
        index = self.actor_index(op.get("name"))
        target = tuple(_ground(op["position"], "position")) if "position" in op else self.point_of(op.get("target"))
        actor = self.actors[index]
        if geo.distance((actor.position[0], actor.position[1]), target) < 1e-3:
            raise StageEditError("不能让人物朝向自己所在的点")
        self.update_actor(index, yaw_deg=geo.yaw_toward((actor.position[0], actor.position[1]), target, actor.yaw_deg))

    def set_axis(self, op: Mapping[str, Any]) -> None:
        if op.get("kind") == "none":
            self.axis = StageAxis()
            return
        first, second = str(op.get("from_name") or ""), str(op.get("to_name") or "")
        if first == second:
            raise StageEditError("轴线需要两个不同的端点")
        start, end = self.point_of(first), self.point_of(second)
        kind = "dialogue" if any(actor.name == second for actor in self.actors) else "gaze"
        side = int(op.get("camera_side") or self.axis.camera_side or 1)
        self.axis = StageAxis(
            kind=kind, from_name=first, to_name=second, start=geo.rounded(start), end=geo.rounded(end),
            camera_side=1 if side >= 0 else -1,
        )
        # The axis decides who is promised screen left: re-issue the promise with it.
        left, right = (first, second) if self.axis.camera_side > 0 else (second, first)
        for index, actor in enumerate(self.actors):
            if actor.name in {left, right}:
                self.update_actor(index, screen_side="left" if actor.name == left else "right", role="principal")

    def flip_camera_side(self, _op: Mapping[str, Any]) -> None:
        if not axis_rules.has_axis(self.axis):
            raise StageEditError("本场没有轴线，无法换边")
        self.set_axis({
            "from_name": self.axis.from_name, "to_name": self.axis.to_name, "camera_side": -self.axis.camera_side,
        })

    def move_landmark(self, op: Mapping[str, Any]) -> None:
        index = self.landmark_index(op.get("name"))
        self.landmarks[index] = self.landmarks[index].model_copy(update={"position": _ground(op.get("position"), "position")})

    def _landmark_changes(self, op: Mapping[str, Any]) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        if "position" in op:
            changes["position"] = _ground(op["position"], "position")
        if "size" in op:
            changes["size"] = _size(op["size"])
        if "yaw_deg" in op:
            changes["yaw_deg"] = geo.normalize_yaw(_number(op["yaw_deg"], "yaw_deg", -360, 360))
        if "shape" in op:
            changes["shape"] = _choice(op["shape"], LANDMARK_SHAPES, "shape", "box")
        if "color" in op:
            changes["color"] = _color(op["color"])
        if "kind" in op:
            changes["kind"] = _choice(op["kind"], LANDMARK_KINDS, "kind", "prop")
        return changes

    def transform_landmark(self, op: Mapping[str, Any]) -> None:
        index = self.landmark_index(op.get("name"))
        changes = self._landmark_changes(op)
        if not changes:
            raise StageEditError("transform_landmark 需要 position / size / yaw_deg / shape / color / kind 之一")
        self.landmarks[index] = self.landmarks[index].model_copy(update=changes)

    def bind_landmark_model(self, op: Mapping[str, Any]) -> None:
        index = self.landmark_index(op.get("name"))
        element_id = _text(op.get("element_id"), "element_id", 120, required=False)
        self.landmarks[index] = self.landmarks[index].model_copy(update={"element_id": element_id})

    def set_backdrop(self, op: Mapping[str, Any]) -> None:
        changes: dict[str, Any] = {}
        if "kind" in op:
            changes["kind"] = _choice(op["kind"], BACKDROP_KINDS, "kind", "none")
        if "color" in op:
            changes["color"] = _color(op["color"])
        if "url" in op:
            changes["url"] = _http_url(op["url"])
        if "yaw_deg" in op:
            changes["yaw_deg"] = geo.normalize_yaw(_number(op["yaw_deg"], "yaw_deg", -360, 360))
        if "opacity" in op:
            changes["opacity"] = round(_number(op["opacity"], "opacity", 0, 1), 3)
        if not changes:
            raise StageEditError("set_backdrop 需要 kind / color / url / yaw_deg / opacity 之一")
        after = self.backdrop.model_copy(update=changes)
        if after.kind in {"image", "panorama"} and not after.url:
            raise StageEditError("图片或全景背景需要同时提供 url")
        self.backdrop = StageBackdrop.model_validate(after.model_dump())

    def add_landmark(self, op: Mapping[str, Any]) -> None:
        name = str(op.get("name") or "").strip()[:120]
        if not name or any(item.name == name for item in self.landmarks) or any(actor.name == name for actor in self.actors):
            raise StageEditError("地标需要一个场上尚未使用的名称")
        if len(self.landmarks) >= 80:
            raise StageEditError("地标数量已达上限")
        number = 1 + max((int(item.id.rsplit("-", 1)[-1]) for item in self.landmarks if item.id.rsplit("-", 1)[-1].isdigit()), default=0)
        self.landmarks.append(StageLandmark(**{
            "id": f"mark-{number:02d}", "name": name, "kind": "prop", "position": [0.0, -1.5],
            **self._landmark_changes(op),
        }))

    def remove_landmark(self, op: Mapping[str, Any]) -> None:
        name = str(op.get("name") or "")
        if not any(item.name == name for item in self.landmarks):
            raise StageEditError(f"场上没有地标「{name}」")
        self.landmarks = [item for item in self.landmarks if item.name != name]
        if self.axis.to_name == name or self.axis.from_name == name:
            self.axis = StageAxis()

    def move_camera(self, op: Mapping[str, Any]) -> None:
        index = self.camera_index(op.get("camera_id"))
        camera = self.cameras[index]
        changes: dict[str, Any] = {}
        if "position" in op:
            changes["position"] = _space(op["position"], "position")
        if "target" in op:
            changes["target"] = _space(op["target"], "target")
        if "lens_mm" in op:
            lens = _number(op["lens_mm"], "lens_mm", 8, 600)
            changes.update(lens_mm=round(lens, 1), fov_deg=round(geo.vertical_fov(lens, geo.parse_aspect(camera.aspect)), 2))
        if not changes:
            raise StageEditError("move_camera 需要 position / target / lens_mm 之一")
        position, target = changes.get("position", camera.position), changes.get("target", camera.target)
        if sum((position[i] - target[i]) ** 2 for i in range(3)) < 1e-4:
            raise StageEditError("机位与注视点不能重合")
        # The move survives a drag (the desk shows its end pose and lets a person place that too);
        # ``reset_move`` is how a caller says the hand-placed camera no longer travels anywhere.
        if op.get("reset_move"):
            changes["move"] = CameraMove(kind="static")
        self.cameras[index] = camera.model_copy(update=changes)

    # ---- director desk: crowds, extras, figures, poses
    def add_crowd(self, op: Mapping[str, Any]) -> None:
        label = _text(op.get("label"), "label", 40)
        rows, columns = _whole(op.get("rows", 3), "rows", 1, 20), _whole(op.get("columns", 4), "columns", 1, 20)
        if rows * columns > MAX_CROWD_MEMBERS:
            raise StageEditError(f"一个群演阵列最多 {MAX_CROWD_MEMBERS} 人")
        if len(self.actors) + rows * columns > MAX_ACTORS:
            raise StageEditError(f"场上人物总数不能超过 {MAX_ACTORS}（当前 {len(self.actors)} 人）")
        if len(self.crowds) >= 20:
            raise StageEditError("群演阵列数量已达上限")
        if any(crowd.label == label for crowd in self.crowds):
            raise StageEditError(f"已有名为「{label}」的群演阵列")
        crowd = StageCrowd(
            id=f"crowd-{_next_number([item.id for item in self.crowds], 'crowd-'):02d}", label=label, rows=rows, columns=columns,
            spacing=round(_number(op.get("spacing", 1.0), "spacing", 0.3, 10), 3),
            # Upstage of the origin by default: a crowd is background until someone moves it.
            center=_ground(op.get("center", [0.0, -3.0]), "center"),
            yaw_deg=geo.normalize_yaw(_number(op.get("yaw_deg", 0.0), "yaw_deg", -360, 360)),
            body_type=_text(op.get("body_type") or "standard", "body_type", 40),
            seed=_whole(op.get("seed", 0), "seed", 0, 2_147_483_647),
        )
        people = crowds.members(crowd)
        taken = next((person.name for person in people if not self.free_name(person.name)), None)
        if taken is not None:
            raise StageEditError(f"场上已有「{taken}」，请换一个阵列名称")
        self.crowds.append(crowd)
        self.actors.extend(people)

    def remove_crowd(self, op: Mapping[str, Any]) -> None:
        crowd = self.crowds.pop(self.crowd_index(op.get("crowd_id")))
        gone = {actor.name for actor in self.actors if actor.crowd_id == crowd.id}
        self.actors = [actor for actor in self.actors if actor.crowd_id != crowd.id]
        self.forget(gone)

    def transform_crowd(self, op: Mapping[str, Any]) -> None:
        index = self.crowd_index(op.get("crowd_id"))
        before = self.crowds[index]
        changes: dict[str, Any] = {}
        if "center" in op:
            changes["center"] = _ground(op["center"], "center")
        if "yaw_deg" in op:
            changes["yaw_deg"] = geo.normalize_yaw(_number(op["yaw_deg"], "yaw_deg", -360, 360))
        if "spacing" in op:
            changes["spacing"] = round(_number(op["spacing"], "spacing", 0.3, 10), 3)
        if not changes:
            raise StageEditError("transform_crowd 需要 center / yaw_deg / spacing 之一")
        after = before.model_copy(update=changes)
        self.crowds[index] = after
        self.actors = [crowds.moved(actor, before, after) if actor.crowd_id == before.id else actor for actor in self.actors]

    def add_extra(self, op: Mapping[str, Any]) -> None:
        name = _text(op.get("name"), "name", 120)
        if not self.free_name(name):
            raise StageEditError(f"场上已有「{name}」")
        if len(self.actors) >= MAX_ACTORS:
            raise StageEditError(f"场上人物总数不能超过 {MAX_ACTORS}")
        number = _next_number([actor.id for actor in self.actors], _EXTRA_PREFIX)
        self.actors.append(StageActor(
            id=f"{_EXTRA_PREFIX}{number:02d}", name=name, role="supporting", note="导演台添加的替身，不在剧本人物表中",
            position=_ground(op.get("position", [0.0, -2.0]), "position"),
            yaw_deg=geo.normalize_yaw(_number(op.get("yaw_deg", 0.0), "yaw_deg", -360, 360)),
            height_m=_number(op.get("height_m", 1.7), "height_m", 0.4, 3.0),
            posture=str(op.get("posture") or "stand"),
            figure=_choice(op.get("figure"), FIGURES, "figure", "standin"),
            body_type=_text(op.get("body_type") or "standard", "body_type", 40),
            color=_color(op.get("color")),
        ))

    def remove_extra(self, op: Mapping[str, Any]) -> None:
        index = self.actor_index(op.get("name"))
        actor = self.actors[index]
        if not actor.id.startswith(_EXTRA_PREFIX):
            raise StageEditError(f"「{actor.name}」是剧本里的人物，不能从场上移除；只有导演台添加的替身可以移除")
        self.actors.pop(index)
        self.forget({actor.name})

    def set_figure(self, op: Mapping[str, Any]) -> None:
        if op.get("crowd_id"):
            crowd_id = self.crowds[self.crowd_index(op["crowd_id"])].id
            indexes = [i for i, actor in enumerate(self.actors) if actor.crowd_id == crowd_id]
        else:
            indexes = [self.actor_index(op.get("name"))]
        changes: dict[str, Any] = {}
        if "figure" in op:
            changes["figure"] = _choice(op["figure"], FIGURES, "figure", "standin")
        if "body_type" in op:
            changes["body_type"] = _text(op["body_type"], "body_type", 40)
        if "color" in op:
            changes["color"] = _color(op["color"])
        if not changes:
            raise StageEditError("set_figure 需要 figure / body_type / color 之一")
        for index in indexes:
            self.update_actor(index, **changes)
        if "body_type" in changes and op.get("crowd_id"):
            crowd_index = self.crowd_index(op["crowd_id"])
            self.crowds[crowd_index] = self.crowds[crowd_index].model_copy(update={"body_type": changes["body_type"]})

    def set_pose(self, op: Mapping[str, Any]) -> None:
        index = self.actor_index(op.get("name"))
        joints = op.get("joints") or {}
        if not isinstance(joints, Mapping):
            raise StageEditError("joints 必须是 {关节名: 角度} 的对象")
        if len(joints) > MAX_POSE_JOINTS:
            raise StageEditError(f"一个姿态最多 {MAX_POSE_JOINTS} 个关节")
        angles: dict[str, float] = {}
        for key, value in joints.items():
            if not _JOINT_KEY.match(str(key)):
                raise StageEditError(f"关节名 {str(key)[:40]!r} 不合法：以字母开头，只含字母、数字和 _ . : -，最长 60")
            angles[str(key)] = round(_number(value, f"关节 {key} 的角度", -180, 180), 3)
        preset, clip = _text(op.get("preset"), "preset", 60, required=False), _text(op.get("clip"), "clip", 80, required=False)
        # Nothing to hold — no preset, no angles, no clip — is how a pose is taken off again.
        pose = StagePose(
            preset=preset, joints=angles, clip=clip, clip_phase=_number(op.get("clip_phase", 0.0), "clip_phase", 0, 1),
        ) if preset or angles or clip else None
        if op.get("shot_id") is None:
            self.update_actor(index, pose=pose)
            return
        shot_index = self.shot_index(op["shot_id"])
        name = self.actors[index].name
        shot = self.shots[shot_index]
        current = next((item for item in shot.overrides if item.name == name), None)
        change = (current or ActorOverride(name=name)).model_copy(update={"pose": pose})
        kept = [item for item in shot.overrides if item.name != name]
        # An override that says nothing any more is not one.
        if change != ActorOverride(name=name):
            kept.append(change)
        self.shots[shot_index] = shot.model_copy(update={"overrides": kept})

    # ---- director desk: candidate lenses, framing, animation
    def add_camera(self, op: Mapping[str, Any]) -> None:
        shot_index = self.shot_index(op.get("shot_id"))
        shot = self.shots[shot_index]
        if len(shot.alt_camera_ids) >= MAX_ALT_CAMERAS:
            raise StageEditError(f"一个镜头最多 {MAX_ALT_CAMERAS} 个候选机位")
        if len(self.cameras) >= 200:
            raise StageEditError("机位数量已达上限")
        filming = self.cameras[self.camera_index(shot.camera_id)]
        prefix = f"alt-{shot.shot_id:02d}-"
        camera_id = f"{prefix}{_next_number([camera.id for camera in self.cameras], prefix):02d}"
        label = _text(op.get("label") or f"{filming.label} · 候选{len(shot.alt_camera_ids) + 1}", "label", 160)
        # A candidate starts as a copy of the lens that films, standing still: it is a place to look from.
        self.cameras.append(filming.model_copy(update={"id": camera_id, "label": label, "move": CameraMove(kind="static")}))
        self.shots[shot_index] = shot.model_copy(update={"alt_camera_ids": [*shot.alt_camera_ids, camera_id]})
        if any(key in op for key in ("position", "target", "lens_mm")):
            self.move_camera({**op, "camera_id": camera_id})

    def remove_camera(self, op: Mapping[str, Any]) -> None:
        index = self.camera_index(op.get("camera_id"))
        camera = self.cameras[index]
        filming = next((shot.shot_id for shot in self.shots if shot.camera_id == camera.id), None)
        if filming is not None:
            raise StageEditError(f"机位「{camera.id}」正在拍摄第 {filming} 镜，不能删除；请先用 use_camera 换用其他候选机位")
        self.cameras.pop(index)
        self.shots = [
            shot.model_copy(update={"alt_camera_ids": [item for item in shot.alt_camera_ids if item != camera.id]})
            if camera.id in shot.alt_camera_ids else shot
            for shot in self.shots
        ]

    def use_camera(self, op: Mapping[str, Any]) -> None:
        shot_index = self.shot_index(op.get("shot_id"))
        shot = self.shots[shot_index]
        camera_id = self.cameras[self.camera_index(op.get("camera_id"))].id
        if camera_id == shot.camera_id:
            return
        if camera_id not in shot.alt_camera_ids:
            raise StageEditError(f"机位「{camera_id}」不是第 {shot.shot_id} 镜的候选机位")
        self.shots[shot_index] = shot.model_copy(update={
            "camera_id": camera_id,
            "alt_camera_ids": [shot.camera_id if item == camera_id else item for item in shot.alt_camera_ids],
        })
        # Camera keys are world poses along the old lens's path; they do not describe this one.
        timeline = self.timelines.get(str(shot.shot_id))
        if timeline is not None and timeline.camera:
            self.timelines[str(shot.shot_id)] = timeline.model_copy(update={"camera": []})

    def frame_shot(self, op: Mapping[str, Any]) -> None:
        shot = self.shots[self.shot_index(op.get("shot_id"))]
        size = named_size(str(op.get("size") or ""))
        if size is None:
            raise StageEditError("size 需要一个景别：" + " / ".join(name for name, _ in SHOT_SIZE_HEIGHTS))
        index = self.camera_index(shot.camera_id)
        camera = self.cameras[index]
        # Film back: a frame of vertical field of view ``fov`` covers ``2·d·tan(fov/2)`` meters at ``d``.
        reach = geo.framing_distance(dict(SHOT_SIZE_HEIGHTS)[size], camera.fov_deg)
        look = CameraView.of(camera).basis()[0]
        position = [camera.target[i] - look[i] * reach for i in range(3)]
        if position[1] < _LOWEST_LENS_M:
            raise StageEditError(f"沿当前视线方向拍{size}，机位会落到地面以下；请先抬高机位或压平仰角")
        if any(abs(value) > 500 for value in position):
            raise StageEditError("按该景别取景，机位会超出场地范围（±500 米）")
        shift = [position[i] - camera.position[i] for i in range(3)]
        move = camera.move
        if move.end_position is not None:
            # The move keeps its shape: it starts from the new frame and travels the same way.
            move = move.model_copy(update={"end_position": geo.rounded([move.end_position[i] + shift[i] for i in range(3)])})
        self.cameras[index] = camera.model_copy(update={"position": geo.rounded(position), "shot_size": size, "move": move})

    def _timeline_of(self, shot_id: int, op: Mapping[str, Any]) -> dict[str, Any]:
        current = self.timelines.get(str(shot_id))
        values: dict[str, Any] = current.model_dump() if current is not None else {}
        if "duration_s" in op:
            values["duration_s"] = _number(op["duration_s"], "duration_s", 1, 30)
        if "fps" in op:
            if op["fps"] not in (24, 25, 30):
                raise StageEditError("fps 只能是 24 / 25 / 30")
            values["fps"] = int(op["fps"])
        return values

    def set_timeline(self, op: Mapping[str, Any]) -> None:
        shot_id = self.shots[self.shot_index(op.get("shot_id"))].shot_id
        values = self._timeline_of(shot_id, op)
        if "camera" in op:
            if not isinstance(op["camera"], Sequence) or isinstance(op["camera"], (str, bytes)):
                raise StageEditError("camera 必须是关键帧列表")
            values["camera"] = list(op["camera"])
        if "actors" in op:
            if not isinstance(op["actors"], Mapping):
                raise StageEditError("actors 必须是 {人物名: 关键帧列表} 的对象")
            for name in op["actors"]:
                self.actor_index(name)
            values["actors"] = {str(name): keys for name, keys in op["actors"].items() if keys}
        if not any(key in op for key in ("duration_s", "fps", "camera", "actors")):
            raise StageEditError("set_timeline 需要 duration_s / fps / camera / actors 之一")
        _refuse_keys_past_the_end(values)
        try:
            self.timelines[str(shot_id)] = ShotTimeline.model_validate(values)
        except ValueError as error:
            raise StageEditError(_timeline_error(error)) from error

    def clear_timeline(self, op: Mapping[str, Any]) -> None:
        shot_id = self.shots[self.shot_index(op.get("shot_id"))].shot_id
        self.timelines.pop(str(shot_id), None)

    def apply_camera_move(self, op: Mapping[str, Any]) -> None:
        shot = self.shots[self.shot_index(op.get("shot_id"))]
        camera = self.cameras[self.camera_index(shot.camera_id)]
        values = self._timeline_of(shot.shot_id, op)
        staged = self.plan.model_copy(update={"actors": self.actors, "shots": self.shots}).actors_in(shot)
        try:
            values["camera"] = camera_moves.build_keys(
                str(op.get("preset") or ""), camera,
                duration_s=float(values.get("duration_s", 5.0)),
                amplitude=_number(op.get("amplitude", 1.0), "amplitude", 0.05, 3),
                angle=_number(op["angle"], "angle", 1, 180) if op.get("angle") is not None else None,
                side=str(op.get("side") or "auto"), easing=str(op["easing"]) if op.get("easing") else None,
                axis=self.axis, subjects=[actor for actor in staged if actor.name in camera.subjects],
                stage_center=geo.centroid([(a.position[0], a.position[1]) for a in self.actors if a.role != "crowd"]),
            )
            self.timelines[str(shot.shot_id)] = ShotTimeline.model_validate(values)
        except camera_moves.CameraMoveError as error:
            raise StageEditError(str(error)) from error

    def _spec_of(self, shot_index: int, op: Mapping[str, Any]) -> ShotSpec:
        shot = self.shots[shot_index]
        camera = self.cameras[self.camera_index(shot.camera_id)]
        angle = str(op.get("angle") or camera.angle)
        if op.get("over_shoulder") is True and "过肩" not in angle:
            angle = f"过肩 {angle}".strip()
        elif op.get("over_shoulder") is False:
            angle = angle.replace("过肩", "").replace("越肩", "").strip() or "平视"
        subjects = op.get("subjects")
        if subjects is not None and (not isinstance(subjects, Sequence) or isinstance(subjects, (str, bytes))):
            raise StageEditError("subjects 必须是人物名列表")
        return ShotSpec(
            shot_id=shot.shot_id,
            subjects=[str(name) for name in (subjects if subjects is not None else camera.subjects)],
            speaker=shot.speaker,
            size=str(op.get("size") or camera.shot_size),
            angle=angle,
            motion=str(op.get("motion") or _MOVE_WORDS.get(camera.move.kind, "固定")),
            desc=shot.action if op.get("over_shoulder") is not False else shot.action.replace("过肩", "").replace("越肩", ""),
        )

    def solve_camera(self, op: Mapping[str, Any]) -> None:
        wanted = [self.shot_index(op["shot_id"])] if "shot_id" in op else list(range(len(self.shots)))
        staged = self.plan.model_copy(update={"actors": self.actors, "axis": self.axis})
        principals = [name for name in (self.axis.from_name, self.axis.to_name) if any(a.name == name for a in self.actors)]
        centre = geo.centroid([(a.position[0], a.position[1]) for a in self.actors if a.role != "crowd"])
        for shot_index in wanted:
            shot = self.shots[shot_index]
            camera_index = self.camera_index(shot.camera_id)
            solved = solve_camera(
                self._spec_of(shot_index, op if "shot_id" in op else {}), staged.actors_in(shot), self.axis,
                aspect_ratio=self.plan.aspect_ratio, principals=principals, landmarks=self.landmarks,
                stage_center=centre, first_shot=shot_index == 0,
            )
            solved = fit_move(solved, staged.actors_in(shot), staged.actors_in(shot, at_end=True), self.axis)
            self.cameras[camera_index] = solved.model_copy(update={"id": self.cameras[camera_index].id})

    def set_shot_override(self, op: Mapping[str, Any]) -> None:
        shot_index = self.shot_index(op.get("shot_id"))
        name = self.actors[self.actor_index(op.get("name"))].name
        change = ActorOverride(
            name=name,
            position=_ground(op["position"], "position") if op.get("position") is not None else None,
            yaw_deg=geo.normalize_yaw(_number(op["yaw_deg"], "yaw_deg", -360, 360)) if op.get("yaw_deg") is not None else None,
            posture=op.get("posture") or None,
            offstage=bool(op.get("offstage")),
            hold=bool(op.get("hold")) and op.get("position") is not None,
            reason=str(op.get("reason") or "")[:200],
            # The pose is set_pose's to write; restaging someone does not un-pose them.
            pose=next((item.pose for item in self.shots[shot_index].overrides if item.name == name), None),
        )
        kept = [item for item in self.shots[shot_index].overrides if item.name != name]
        self.shots[shot_index] = self.shots[shot_index].model_copy(update={"overrides": [*kept, change]})

    def clear_shot_override(self, op: Mapping[str, Any]) -> None:
        shot_index = self.shot_index(op.get("shot_id"))
        name = str(op.get("name") or "")
        kept = [item for item in self.shots[shot_index].overrides if name and item.name != name]
        self.shots[shot_index] = self.shots[shot_index].model_copy(update={"overrides": kept})


def _refuse_keys_past_the_end(values: Mapping[str, Any]) -> None:
    """Name the key a shorter duration would cut off; the model only says that there is one."""
    duration = float(values.get("duration_s", 5.0))
    tracks = [("机位", values.get("camera") or []), *((f"「{name}」", keys) for name, keys in (values.get("actors") or {}).items())]
    for label, keys in tracks:
        times = [key.get("time") for key in keys if isinstance(key, Mapping)]
        late = [float(time) for time in times if isinstance(time, (int, float)) and not isinstance(time, bool) and time > duration + 1e-6]
        if late:
            raise StageEditError(f"关键帧的时间不能超过时间线时长：{label}轨最后一个关键帧在 {max(late):g} 秒，时长是 {duration:g} 秒")


def _timeline_error(error: ValueError) -> str:
    text = str(error)
    for marker, message in (
        ("strictly increasing", "关键帧的时间必须严格递增"),
        ("within the timeline", "关键帧的时间不能超过时间线时长"),
        ("position and target must differ", "机位关键帧的位置与注视点不能重合"),
        ("needs a position", "人物关键帧至少要有 position / yaw_deg / pose 之一"),
        ("at most 120", "每条轨道最多 120 个关键帧"),
    ):
        if marker in text:
            return message
    return f"时间线不合法：{text[:300]}"


_HANDLERS = (
    "move_actor", "place_relative", "face_pair", "arrange_group", "orient_toward", "set_axis",
    "flip_camera_side", "move_landmark", "add_landmark", "remove_landmark", "move_camera",
    "solve_camera", "set_shot_override", "clear_shot_override",
    "transform_landmark", "bind_landmark_model", "set_backdrop", "add_crowd", "remove_crowd", "transform_crowd",
    "add_extra", "remove_extra", "set_figure", "set_pose", "add_camera", "remove_camera", "use_camera",
    "frame_shot", "set_timeline", "clear_timeline", "apply_camera_move",
)
OPERATIONS: tuple[str, ...] = _HANDLERS


def apply_operations(
    plan: StagePlan, operations: Sequence[Mapping[str, Any]], *, solve: bool | None = None,
) -> StagePlan:
    """Apply ``operations`` in order to a copy of ``plan``; all or nothing.

    ``solve`` is whether the edit re-solves the lenses as a side effect: ``True`` solves every
    shot's camera again after the operations, ``False`` promises that no camera moves unless an
    operation names it (what a drag in the viewport needs — the lens the person is looking
    through must not jump), and ``None`` leaves it to the operations themselves.
    """
    if not isinstance(operations, Sequence) or isinstance(operations, (str, bytes)) or not operations:
        raise StageEditError("operations 不能为空")
    if len(operations) > MAX_OPERATIONS:
        raise StageEditError(f"一次最多提交 {MAX_OPERATIONS} 个操作")
    editor = _Editor(plan)
    for index, op in enumerate(operations):
        if not isinstance(op, Mapping):
            raise StageEditError(f"operations[{index}] 必须是对象")
        kind = str(op.get("op") or "")
        if kind not in _HANDLERS:
            raise StageEditError(f"operations[{index}] 未知操作 {kind!r}；支持：{'、'.join(_HANDLERS)}")
        try:
            getattr(editor, kind)(op)
        except StageEditError as error:
            raise StageEditError(f"operations[{index}] {kind}：{error}") from error
        except (ValueError, TypeError) as error:  # a model rejected the value (unknown posture, bad kind …)
            raise StageEditError(f"operations[{index}] {kind}：{str(error)[:300]}") from error
    if solve:
        try:
            editor.solve_camera({})
        except (StageEditError, ValueError, TypeError) as error:
            raise StageEditError(f"重解机位失败：{str(error)[:300]}") from error
    try:
        edited = plan.model_copy(update={
            "actors": [StageActor.model_validate(actor.model_dump()) for actor in editor.actors],
            "landmarks": editor.landmarks, "cameras": editor.cameras, "shots": editor.shots,
            "crowds": editor.crowds, "timelines": editor.timelines, "axis": editor.axis, "backdrop": editor.backdrop,
            "source": "edited", "revision": plan.revision + 1,
        })
        edited = StagePlan.model_validate(edited.model_dump())
    except ValueError as error:
        raise StageEditError(str(error)[:500]) from error
    return refresh(edited)


__all__ = [
    "BACKDROP_KINDS", "FACINGS", "FIGURES", "LANDMARK_KINDS", "LANDMARK_SHAPES", "LAYOUTS", "MAX_ALT_CAMERAS", "MAX_CROWD_MEMBERS", "MAX_OPERATIONS", "OPERATIONS", "ORIENTS", "REFERENCES", "RELATIONS",
    "StageEditError", "apply_operations",
]

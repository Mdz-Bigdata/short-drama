# -*- coding: utf-8 -*-
"""Round-trip a spatial stage through the two 3D director desks' project documents.

- storyai-3d-director-desk: a ``DirectorProject`` (``version: 1``) of flat ``objects``
  (character / prop) with Euler-radian transforms and look-at ``cameras``. Its camera
  record stores the *rig body*, which sits 1.82 m behind the lens along the look direction.
  A stage that carries animation is written as ``version: 2`` with the ``timeline`` of the
  jlmlh fork (camera tracks of position / target / fov keys); version 1 readers ignore it.
- CoStage: a ``director-stage.json`` document (``version: 2``) of ``scenes`` holding
  ``characters`` / ``props`` / ``cameras``; a CoStage character faces its local +X.

Only the data shapes are shared — both formats are written from this project's own
plan, and importing reads nothing but positions, facings and camera poses matched by
name, which then go through the same validation as any other edit.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import StagePlan
from app.core.spatial_stage.projection import posture_height

DESK_RIG_OFFSET_M = 1.82
_DESK_BODY_TYPES = {"principal": "mannequin", "supporting": "slim", "crowd": "broad"}
_DESK_POSES = {
    "stand": "stand", "walk": "walk", "run": "run", "sit": "sit", "crouch": "crouch",
    "kneel": "kneel-one", "lie": "crouch", "fight": "fight", "bow": "bow", "lean": "lean",
}
_COSTAGE_PROP_KINDS = {"architecture": "wall", "furniture": "cube", "light": "light", "prop": "cube"}
_COLORS = ("#E07A5F", "#3D9BE9", "#81B29A", "#F2CC8F", "#9B8AF4", "#E5989B", "#6CC5B0", "#D4A373")
MAX_IMPORT_OBJECTS = 400


class InterchangeError(ValueError):
    """The document is not a project this module can read."""


def _vec(value: Any, size: int) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        return None
    try:
        numbers = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    return numbers if all(math.isfinite(item) and abs(item) <= 500 for item in numbers) else None


def _look(position: list[float], target: list[float]) -> list[float]:
    delta = [target[i] - position[i] for i in range(3)]
    size = math.sqrt(sum(item * item for item in delta)) or 1.0
    return [item / size for item in delta]


# --------------------------------------------------------------------------- storyai-3d-director-desk


def _rig(position: list[float], target: list[float]) -> list[float]:
    look = _look(position, target)
    return [round(position[i] - look[i] * DESK_RIG_OFFSET_M, 4) for i in range(3)]


def _desk_timeline(plan: StagePlan) -> dict[str, Any] | None:
    """The shots' camera keys laid end to end in shot order, one track per lens; ``None`` when nothing is animated."""
    tracks: list[dict[str, Any]] = []
    clock = 0.0
    aspect = geo.parse_aspect(plan.aspect_ratio)
    for shot in plan.shots:
        timeline = plan.timelines.get(str(shot.shot_id))
        if timeline is None:
            continue
        if timeline.camera:
            tracks.append({"cameraId": shot.camera_id, "keyframes": [
                {
                    "id": f"{shot.camera_id}-k{index + 1:03d}", "time": round(clock + key.time, 3),
                    "value": {
                        # The same convention as the camera records: the rig body, not the lens.
                        "position": _rig(key.position, key.target), "target": list(key.target),
                        "fov": round(geo.vertical_fov(key.lens_mm, aspect), 2),
                    },
                }
                for index, key in enumerate(timeline.camera)
            ]})
        clock += timeline.duration_s
    return {"duration": round(clock, 3), "tracks": [], "cameraTracks": tracks} if plan.timelines else None


_BACKDROP_WORDS = {"none": "无", "color": "纯色", "image": "参考图", "panorama": "全景图"}


def _local_notes(plan: StagePlan) -> list[str]:
    """What this desk holds that no other desk's document has a field for.

    Both formats are written for *their* readers, so a backdrop and an element-library binding
    travel as prose rather than as invented keys — and come back as nothing at all, because an
    import only reads positions, facings and lens poses.
    """
    notes: list[str] = []
    backdrop = plan.backdrop
    if backdrop.kind != "none":
        detail = backdrop.color or backdrop.url or "—"
        notes.append(
            f"本场背景：{_BACKDROP_WORDS.get(backdrop.kind, backdrop.kind)}（{detail}，"
            f"偏转 {backdrop.yaw_deg:g}°、不透明度 {backdrop.opacity:g}）；导演台专有，导入时会被忽略"
        )
    for landmark in plan.landmarks:
        if landmark.element_id:
            notes.append(f"「{landmark.name}」绑定元素库模型 {landmark.element_id}；导演台专有，导入时会被忽略")
    return notes


def to_director_desk(plan: StagePlan) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    alternates = {camera_id: shot.shot_id for shot in plan.shots for camera_id in shot.alt_camera_ids}
    for index, actor in enumerate(plan.actors):
        objects.append({
            "id": actor.id, "name": actor.name, "kind": "character", "visible": True, "locked": False,
            "transform": {
                "position": [actor.position[0], 0.0, actor.position[1]],
                # A glTF character faces +Z, so rotation.y is exactly the plan's yaw.
                "rotation": [0.0, round(math.radians(actor.yaw_deg), 6), 0.0],
                "scale": [1.0, round(actor.height_m / 1.75, 4), 1.0],
            },
            "bodyType": actor.body_type if actor.body_type != "standard" else _DESK_BODY_TYPES.get(actor.role, "mannequin"),
            "color": actor.color or _COLORS[index % len(_COLORS)],
            "characterRig": {
                "rigType": "ue4-mannequin",
                "posePresetId": (actor.pose.preset if actor.pose is not None and actor.pose.preset else _DESK_POSES.get(actor.posture, "stand")),
                # Control key → degrees, exactly as the plan holds them.
                "controls": dict(actor.pose.joints) if actor.pose is not None else {},
            },
        })
    for landmark in plan.landmarks:
        objects.append({
            "id": landmark.id, "name": landmark.name, "kind": "prop", "visible": True, "locked": False,
            "transform": {
                "position": [landmark.position[0], 0.0, landmark.position[1]],
                "rotation": [0.0, round(math.radians(landmark.yaw_deg), 6), 0.0],
                "scale": [landmark.size[0], landmark.size[2], landmark.size[1]],
            },
            "geometryType": "cylinder" if landmark.kind == "light" and landmark.shape == "box" else landmark.shape,
            "color": landmark.color or "#8D99AE",
        })
    cameras: list[dict[str, Any]] = []
    for camera in plan.cameras:
        rig = _rig(camera.position, camera.target)
        cameras.append({
            "id": camera.id, "name": camera.label, "fov": camera.fov_deg,
            "transform": {"position": rig, "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            "targetMode": "manual", "targetObjectId": None, "target": list(camera.target), "captures": [],
            # A candidate lens of a shot, not the one that films it.
            **({"alternateOfShot": alternates[camera.id]} if camera.id in alternates else {}),
        })
        objects.append({
            "id": f"{camera.id}-object", "name": camera.label, "kind": "camera", "visible": True, "locked": False,
            "transform": {"position": rig, "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            "linkedCameraId": camera.id,
        })
    timeline = _desk_timeline(plan)
    backdrop = plan.backdrop
    return {
        "version": 2 if timeline is not None else 1,
        **({"timeline": timeline} if timeline is not None else {}),
        "scene": {
            "scale": 1, "position": [0, 0, 0], "rotation": [0, 0, 0],
            "backgroundColor": backdrop.color if backdrop.kind == "color" and backdrop.color else "#10141C",
            "panoramaYaw": backdrop.yaw_deg if backdrop.kind == "panorama" else 0,
            "panoramaRadius": 60, "showLabels": True, "snapToGrid": False,
            "showGround": True, "groundOpacity": 0.4, "groundHeight": 0,
        },
        "assets": [], "objects": objects, "cameras": cameras,
        "activeCameraId": plan.cameras[0].id if plan.cameras else None, "panoramaAssetId": None,
        "notes": _local_notes(plan),
    }


def _from_director_desk(document: Mapping[str, Any]) -> tuple[dict[str, dict], dict[str, dict]]:
    objects = document.get("objects")
    if not isinstance(objects, list) or len(objects) > MAX_IMPORT_OBJECTS:
        raise InterchangeError("导演台工程缺少 objects 或对象过多")
    placed: dict[str, dict] = {}
    for item in objects:
        if not isinstance(item, Mapping) or item.get("kind") not in {"character", "prop"}:
            continue
        transform = item.get("transform") if isinstance(item.get("transform"), Mapping) else {}
        position, rotation = _vec(transform.get("position"), 3), _vec(transform.get("rotation"), 3)
        if position is None:
            continue
        found: dict[str, Any] = {
            "position": [position[0], position[2]],
            "yaw_deg": math.degrees(rotation[1]) if rotation is not None else None,
        }
        if item.get("kind") == "prop":
            scale = _vec(transform.get("scale"), 3)
            if scale is not None and all(0.02 <= value <= 200 for value in scale):
                found["size"] = [scale[0], scale[2], scale[1]]
        else:
            rig = item.get("characterRig") if isinstance(item.get("characterRig"), Mapping) else {}
            controls = rig.get("controls")
            if isinstance(controls, Mapping) and controls:
                found["pose"] = {"preset": str(rig.get("posePresetId") or "")[:60], "joints": dict(controls)}
        placed[str(item.get("name") or "")] = found
    cameras: dict[str, dict] = {}
    for item in document.get("cameras") or []:
        if not isinstance(item, Mapping):
            continue
        transform = item.get("transform") if isinstance(item.get("transform"), Mapping) else {}
        rig, target = _vec(transform.get("position"), 3), _vec(item.get("target"), 3)
        if rig is None or target is None:
            continue
        look = _look(rig, target)
        eye = [rig[i] + look[i] * DESK_RIG_OFFSET_M for i in range(3)]
        fov = item.get("fov")
        cameras[str(item.get("id") or "")] = {"position": eye, "target": target, "fov": fov}
    return placed, cameras


# --------------------------------------------------------------------------- CoStage


def to_costage(plan: StagePlan) -> dict[str, Any]:
    scene = {
        "characters": [
            {
                "id": actor.id, "label": actor.name, "category": "character",
                "position": [actor.position[0], 0.0, actor.position[1]],
                # CoStage faces a character along its local +X: a yaw 90° less points the same way.
                "rotation": [0.0, round(math.radians(actor.yaw_deg - 90.0), 6), 0.0],
                "scale": [1.0, 1.0, 1.0], "visible": True, "locked": False, "color": _COLORS[index % len(_COLORS)],
                "bodyType": _DESK_BODY_TYPES.get(actor.role, "mannequin"),
                "modelScale": [1.0, round(posture_height(actor) / 1.75, 4), 1.0],
            }
            for index, actor in enumerate(plan.actors)
        ],
        "props": [
            {
                "id": landmark.id, "label": landmark.name, "category": "prop",
                "kind": _COSTAGE_PROP_KINDS.get(landmark.kind, "cube"),
                "position": [landmark.position[0], landmark.size[2] / 2, landmark.position[1]],
                "rotation": [0.0, 0.0, 0.0], "scale": [landmark.size[0], landmark.size[2], landmark.size[1]],
                "visible": True, "locked": False, "color": "#8D99AE",
            }
            for landmark in plan.landmarks
        ],
        "cameras": [
            {
                "id": camera.id, "label": camera.label, "position": list(camera.position),
                "target": list(camera.target), "fov": round(max(18.0, min(85.0, camera.fov_deg)), 2),
                "aspect": camera.aspect if camera.aspect in {"16:9", "9:16", "1:1", "4:3"} else "9:16",
                "locked": False, "screenshots": [],
            }
            for camera in plan.cameras
        ],
        "environment": {"groundVisible": True, "groundHeight": 0, "sceneScale": 1, "panorama": None},
    }
    return {
        "version": 2, "title": plan.location or plan.scene_id,
        "scenes": [{
            "id": plan.scene_id, "label": plan.location or plan.scene_id, "scene": scene,
            "activeCameraId": plan.cameras[0].id if plan.cameras else "",
        }],
        "activeSceneId": plan.scene_id,
        "timeline": {"shots": [], "activeShotId": None},
        "notes": _local_notes(plan),
    }


def _from_costage(document: Mapping[str, Any], scene_id: str) -> tuple[dict[str, dict], dict[str, dict]]:
    scenes = document.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise InterchangeError("CoStage 文档缺少 scenes")
    chosen = next(
        (item for item in scenes if isinstance(item, Mapping) and item.get("id") == scene_id),
        next((item for item in scenes if isinstance(item, Mapping) and item.get("id") == document.get("activeSceneId")), scenes[0]),
    )
    body = chosen.get("scene") if isinstance(chosen, Mapping) and isinstance(chosen.get("scene"), Mapping) else {}
    placed: dict[str, dict] = {}
    entries = [*(body.get("characters") or []), *(body.get("props") or [])]
    if len(entries) > MAX_IMPORT_OBJECTS:
        raise InterchangeError("CoStage 场景对象过多")
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        position, rotation = _vec(item.get("position"), 3), _vec(item.get("rotation"), 3)
        if position is None:
            continue
        is_character = item.get("category") == "character"
        placed[str(item.get("label") or "")] = {
            "position": [position[0], position[2]],
            "yaw_deg": math.degrees(rotation[1]) + 90.0 if rotation is not None and is_character else None,
        }
    cameras: dict[str, dict] = {}
    for item in body.get("cameras") or []:
        if not isinstance(item, Mapping):
            continue
        position, target = _vec(item.get("position"), 3), _vec(item.get("target"), 3)
        if position is not None and target is not None:
            cameras[str(item.get("id") or "")] = {"position": position, "target": target, "fov": item.get("fov")}
    return placed, cameras


# --------------------------------------------------------------------------- import as operations


def import_operations(plan: StagePlan, document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The edit operations that bring ``plan`` to the positions of a desk document, matched by name / camera id."""
    if not isinstance(document, Mapping):
        raise InterchangeError("工程文件必须是 JSON 对象")
    version = document.get("version")
    if version in (1, 2) and "objects" in document:
        placed, cameras = _from_director_desk(document)
    elif version == 2 and "scenes" in document:
        placed, cameras = _from_costage(document, plan.scene_id)
    else:
        raise InterchangeError("无法识别的工程文件：需要 3D 导演台工程（含 objects，version 1 / 2）或 CoStage 文档（含 scenes，version 2）")
    operations: list[dict[str, Any]] = []
    for actor in plan.actors:
        found = placed.get(actor.name)
        if not found:
            continue
        operation: dict[str, Any] = {"op": "move_actor", "name": actor.name, "position": geo.rounded(found["position"])}
        if found.get("yaw_deg") is not None:
            operation["yaw_deg"] = geo.normalize_yaw(found["yaw_deg"])
        operations.append(operation)
        if found.get("pose"):
            # set_pose validates the angles like any other edit: a bad control fails the import, loudly.
            operations.append({"op": "set_pose", "name": actor.name, **found["pose"]})
    for landmark in plan.landmarks:
        found = placed.get(landmark.name)
        if not found:
            continue
        operation = {"op": "transform_landmark", "name": landmark.name, "position": geo.rounded(found["position"])}
        if found.get("yaw_deg") is not None:
            operation["yaw_deg"] = geo.normalize_yaw(found["yaw_deg"])
        if found.get("size"):
            operation["size"] = geo.rounded(found["size"])
        operations.append(operation)
    aspect = geo.parse_aspect(plan.aspect_ratio)
    sensor = geo.SENSOR_LONG_SIDE_MM if aspect < 1 else geo.SENSOR_LONG_SIDE_MM / aspect
    for camera in plan.cameras:
        found = cameras.get(camera.id)
        if not found:
            continue
        operation = {"op": "move_camera", "camera_id": camera.id, "position": geo.rounded(found["position"]), "target": geo.rounded(found["target"])}
        try:
            fov = float(found.get("fov"))
        except (TypeError, ValueError):
            fov = 0.0
        if 1.0 <= fov <= 170.0 and abs(fov - camera.fov_deg) > 0.05:
            operation["lens_mm"] = round(max(8.0, min(600.0, sensor / (2 * math.tan(math.radians(fov) / 2)))), 1)
        operations.append(operation)
    if not operations:
        raise InterchangeError("工程文件里没有与本场同名的人物、地标或同编号的机位")
    return operations


__all__ = ["DESK_RIG_OFFSET_M", "InterchangeError", "import_operations", "to_costage", "to_director_desk"]

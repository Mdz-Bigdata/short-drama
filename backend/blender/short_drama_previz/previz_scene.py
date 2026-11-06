# -*- coding: utf-8 -*-
"""在 Blender 里把一份预演规格(blocking spec JSON)搭成白模场景，并按需渲染。

两种用法，同一份代码：
- 后端无界面渲染：``Blender --background --factory-startup --python previz_scene.py -- <spec.json> <out_dir>``；
- 实时桥接插件(同目录 ``__init__.py``)在打开的 Blender 里 import 本文件，对话每改一次就 ``build(spec)`` 重建场景。

只依赖 bpy 与标准库，不 import 项目代码。坐标已由后端换成 Blender 的 Z 轴向上；朝向 yaw 0 = 面向 -Y
(对应导演台 three.js 的 +Z)，代理头顶的小方块标出脸朝哪边。规则见 skills/shot-design-master/references/blender-previz-protocol.md。
"""

from __future__ import annotations

import json
import math
import os
import random
import sys

import bpy
from mathutils import Matrix

COLLECTION = "ShortDramaPreviz"


def _hex(color: str):
    color = (color or "#8a8a8a").lstrip("#")
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (r, g, b, 1.0)


def _material(name: str, color: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = _hex(color)
    return mat


def _link(obj, collection) -> None:
    for owner in list(obj.users_collection):
        owner.objects.unlink(obj)
    collection.objects.link(obj)


def _primitive(shape: str, size) -> bpy.types.Object:
    """以底面中心为原点的基本体，尺寸 [宽 x, 深 y, 高 z] 米。"""
    sx, sy, sz = size
    if shape == "capsule":
        radius = min(sx, sy) / 2
        bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=max(sz - 2 * radius, 0.05), location=(0, 0, sz / 2))
        parts = [bpy.context.object]
        for z in (radius, sz - radius):
            bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=(0, 0, z))
            parts.append(bpy.context.object)
        # 头顶前方的小方块：一眼看出这个人面朝哪边(本地 -Y 为前)。
        bpy.ops.mesh.primitive_cube_add(size=radius * 0.7, location=(0, -radius * 0.9, sz - radius))
        parts.append(bpy.context.object)
        bpy.ops.object.select_all(action="DESELECT")
        for part in parts:
            part.select_set(True)
        bpy.context.view_layer.objects.active = parts[0]
        bpy.ops.object.join()
        # 合并后的原点落在圆柱中心；改到脚底(世界原点)，位置写的才是"站在哪里"。
        bpy.context.scene.cursor.location = (0, 0, 0)
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        return bpy.context.object
    if shape == "wedge":
        # 楔形：高边在 +Y(对应舞台的 -Z)，向 -Y 降到地面。
        mesh = bpy.data.meshes.new("wedge")
        mesh.from_pydata(
            [(-0.5, 0.5, 0), (0.5, 0.5, 0), (0.5, -0.5, 0), (-0.5, -0.5, 0), (-0.5, 0.5, 1), (0.5, 0.5, 1)],
            [],
            [(3, 2, 1, 0), (0, 1, 5, 4), (3, 4, 5, 2), (0, 4, 3), (1, 2, 5)],
        )
        mesh.update()
        obj = bpy.data.objects.new("wedge", mesh)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        obj.scale = (sx, sy, sz)
        bpy.ops.object.transform_apply(scale=True)
        return obj
    if shape == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=1, location=(0, 0, 0.5))
    elif shape == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(0, 0, 0.5))
    elif shape == "cone":
        bpy.ops.mesh.primitive_cone_add(radius1=0.5, depth=1, location=(0, 0, 0.5))
    else:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.5))
    obj = bpy.context.object
    # 把底面中心设为原点后再缩放：位置写的是"放在地上的哪里"。
    bpy.context.scene.cursor.location = (0, 0, 0)
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    obj.scale = (sx, sy, sz)
    bpy.ops.object.transform_apply(scale=True)
    return obj


def _fcurves(action):
    """兼容 Blender 4.4+ 的分层动作与旧版 ``action.fcurves``。"""
    curves = list(getattr(action, "fcurves", []) or [])
    for layer in getattr(action, "layers", []) or []:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []) or []:
                curves.extend(bag.fcurves)
    return curves


def _set_interpolation(owner, interpolation: str) -> None:
    anim = getattr(owner, "animation_data", None)
    if anim and anim.action:
        for curve in _fcurves(anim.action):
            for point in curve.keyframe_points:
                point.interpolation = interpolation


def _key_path(obj, keys, *, base_rotation_x: float = 0.0) -> None:
    for key in keys:
        obj.location = key["position"]
        obj.keyframe_insert("location", frame=int(key["frame"]))
        if key.get("yaw_deg") is not None:
            obj.rotation_euler = (base_rotation_x, 0.0, math.radians(float(key["yaw_deg"])))
            obj.keyframe_insert("rotation_euler", frame=int(key["frame"]))


def _hide_ranges(obj, ranges, frames: int) -> None:
    """不在场的时段：在区间里隐藏(渲染与视口都看不见)，区间外显示；切换是 CONSTANT，没有渐隐。"""
    if not ranges:
        return
    states = {1: False}
    for start, end in ranges:
        states[int(start)] = True
        if int(end) + 1 <= frames:
            states[int(end) + 1] = False
    for frame, hidden in sorted(states.items()):
        obj.hide_render = hidden
        obj.hide_viewport = hidden
        obj.keyframe_insert("hide_render", frame=frame)
        obj.keyframe_insert("hide_viewport", frame=frame)


def _handheld(cam, hand, frames: int, fps: int) -> None:
    """真实手持：低频身体摆动(正弦) + 不规则微震(带种子的衰减随机游走)，叠加在机位路径上。"""
    sway = float(hand.get("sway_cm", 1.5)) / 100.0
    hz = float(hand.get("sway_hz", 0.45))
    jitter = float(hand.get("jitter_cm", 0.3)) / 100.0
    rng = random.Random(int(hand.get("seed", 7)))
    walk = [0.0, 0.0, 0.0]
    start, end = int(hand.get("start", 1)), int(hand.get("end", frames))
    for frame in range(start, end + 1, 2):
        t = frame / fps
        walk = [w * 0.8 + rng.uniform(-jitter, jitter) for w in walk]
        cam.delta_location = (
            sway * math.sin(2 * math.pi * hz * t) + walk[0],
            walk[1],
            sway * 0.6 * math.sin(2 * math.pi * hz * 0.5 * t + 1.3) + walk[2],
        )
        cam.keyframe_insert("delta_location", frame=frame)


def _fresh_collection():
    old = bpy.data.collections.get(COLLECTION)
    if old is not None:
        for obj in list(old.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old)
    collection = bpy.data.collections.new(COLLECTION)
    bpy.context.scene.collection.children.link(collection)
    return collection


def build(spec: dict, *, factory_reset: bool = False) -> dict:
    """按规格(重)建预演场景；返回 {cameras, proxies, cuts}。实时模式只清掉本插件建的集合，不动用户自己的东西。"""
    if factory_reset:
        bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    collection = _fresh_collection()
    scene.timeline_markers.clear()
    width, height = spec.get("resolution", [1920, 1080])
    scene.render.resolution_x, scene.render.resolution_y = int(width), int(height)
    scene.render.resolution_percentage = 100
    fps = int(spec.get("fps", 24))
    frames = int(spec["frames"])
    scene.render.fps = fps
    scene.frame_start, scene.frame_end = 1, frames

    floor = spec.get("set", {}).get("floor", {})
    ground = _primitive("box", (*floor.get("size", [20, 20]), 0.02))
    ground.location = (0, 0, -0.02)
    ground.name = "set:floor"
    ground.data.materials.append(_material("set:floor", floor.get("color", "#8a8a8a")))
    _link(ground, collection)
    for block in spec.get("set", {}).get("blocks", []):
        obj = _primitive(block.get("shape", "box"), block["size"])
        obj.name = f"set:{block['id']}"
        if block.get("basis"):
            # 组合模型的部件：绕自身中心旋转，position 是中心。
            half = block["size"][2] / 2
            for vertex in obj.data.vertices:
                vertex.co.z -= half
            obj.data.update()
            row = block["basis"]
            at = block["position"]
            obj.matrix_world = Matrix((
                (row[0], row[1], row[2], at[0]), (row[3], row[4], row[5], at[1]),
                (row[6], row[7], row[8], at[2]), (0, 0, 0, 1),
            ))
        else:
            obj.location = block["position"]
            obj.rotation_euler = (0, 0, math.radians(block.get("yaw_deg", 0)))
        obj["previz_name"] = block.get("name", block["id"])
        obj.data.materials.append(_material(obj.name, block.get("color", "#b0b0b0")))
        _link(obj, collection)

    proxies = {}
    for proxy in spec.get("proxies", []):
        obj = _primitive(proxy.get("shape", "capsule"), proxy["size"])
        obj.name = f"proxy:{proxy['id']}"
        obj["binds"] = json.dumps(proxy.get("binds", {}), ensure_ascii=False)
        obj.data.materials.append(_material(obj.name, proxy["color"]))
        _link(obj, collection)
        _key_path(obj, proxy["keys"], base_rotation_x=math.radians(90) if proxy.get("lying") else 0.0)
        _set_interpolation(obj, proxy.get("interpolation", "BEZIER"))
        _hide_ranges(obj, proxy.get("hidden", []), frames)
        proxies[proxy["id"]] = obj

    cameras = {}
    for spec_cam in spec.get("cameras", []):
        data = bpy.data.cameras.new(f"cam:{spec_cam['id']}")
        data.lens = float(spec_cam.get("lens_mm", 35))
        # 与导演台同一口径：全画幅 36mm 对应画面长边(横画幅是宽、竖画幅是高)，同一焦段两边取景一致。
        data.sensor_fit = "AUTO"
        data.sensor_width = 36.0
        cam = bpy.data.objects.new(f"cam:{spec_cam['id']}", data)
        collection.objects.link(cam)
        _key_path(cam, spec_cam["keys"])
        for key in spec_cam.get("lens_keys", []):
            data.lens = float(key["lens_mm"])
            data.keyframe_insert("lens", frame=int(key["frame"]))
        _set_interpolation(cam, spec_cam.get("interpolation", "BEZIER"))
        _set_interpolation(data, spec_cam.get("interpolation", "BEZIER"))
        target = bpy.data.objects.new(f"target:{spec_cam['id']}", None)
        target.empty_display_size = 0.15
        collection.objects.link(target)
        aim = spec_cam.get("target") or {}
        if aim.get("proxy") and aim["proxy"] in proxies:
            target.parent = proxies[aim["proxy"]]
            target.location = aim.get("offset", [0, 0, 0])
        else:
            _key_path(target, aim.get("keys") or [{"frame": 1, "position": [0, 0, 1.5]}])
            _set_interpolation(target, spec_cam.get("interpolation", "BEZIER"))
        track = cam.constraints.new("TRACK_TO")
        track.target = target
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"
        if spec_cam.get("handheld"):
            _handheld(cam, spec_cam["handheld"], frames, fps)
        cameras[spec_cam["id"]] = cam

    # 硬切：切点帧上的时间线标记绑定摄影机，从这一帧起换机，没有过渡帧。
    cuts = sorted(spec.get("cuts", []), key=lambda cut: int(cut["frame"]))
    for cut in cuts:
        if cut["camera"] in cameras:
            marker = scene.timeline_markers.new(f"cut:{cut.get('label') or cut['camera']}", frame=int(cut["frame"]))
            marker.camera = cameras[cut["camera"]]
    if cuts and cuts[0]["camera"] in cameras:
        scene.camera = cameras[cuts[0]["camera"]]
    elif cameras:
        scene.camera = next(iter(cameras.values()))
    for slot in spec.get("reserved", []):
        scene.timeline_markers.new(f"留空:{slot['label']}", frame=int(slot["start"]))
        scene.timeline_markers.new(f"留空结束:{slot['label']}", frame=int(slot["end"]))

    if "previz_key" not in bpy.data.objects:
        sun = bpy.data.objects.new("previz_key", bpy.data.lights.new("previz_key", "SUN"))
        sun.rotation_euler = (math.radians(50), 0, math.radians(30))
        collection.objects.link(sun)
    world = bpy.data.worlds.get("previz_world") or bpy.data.worlds.new("previz_world")
    world.color = (0.16, 0.165, 0.18)
    scene.world = world
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "MATERIAL"
    shading.show_shadows = True
    shading.show_cavity = True
    scene.frame_set(1)
    return {"cameras": list(cameras), "proxies": list(proxies), "cuts": cuts}


def snapshot() -> dict:
    """读出当前场景里代理、布景块与摄影机的状态，供"在 Blender 里拖动后同步回导演台"。

    摄影机读它所属镜头首帧的位置与目标；代理与布景读第 1 帧(站位)。坐标仍是 Blender 的 Z 向上。
    """
    scene = bpy.context.scene
    collection = bpy.data.collections.get(COLLECTION)
    if collection is None:
        return {"proxies": [], "blocks": [], "cameras": []}
    current = scene.frame_current
    out = {"proxies": [], "blocks": [], "cameras": []}
    cut_frames = {marker.camera.name: marker.frame for marker in scene.timeline_markers if marker.camera is not None}
    scene.frame_set(1)
    for obj in collection.all_objects:
        if obj.name.startswith("proxy:"):
            out["proxies"].append({"id": obj.name[6:], "binds": json.loads(obj.get("binds", "{}")),
                                   "position": list(obj.location), "yaw_deg": math.degrees(obj.rotation_euler.z)})
        elif obj.name.startswith("set:") and obj.name != "set:floor":
            out["blocks"].append({"id": obj.name[4:], "name": obj.get("previz_name", obj.name[4:]),
                                  "position": list(obj.location), "yaw_deg": math.degrees(obj.rotation_euler.z)})
    for obj in collection.all_objects:
        if obj.type == "CAMERA" and obj.name.startswith("cam:"):
            scene.frame_set(int(cut_frames.get(obj.name, 1)))
            target = bpy.data.objects.get("target:" + obj.name[4:])
            out["cameras"].append({"id": obj.name[4:], "frame": scene.frame_current,
                                   "position": list(obj.matrix_world.translation),
                                   "target": list(target.matrix_world.translation) if target else None,
                                   "lens_mm": obj.data.lens})
    scene.frame_set(current)
    return out


def render(spec: dict, out_dir: str, built: dict) -> dict:
    scene = bpy.context.scene
    os.makedirs(out_dir, exist_ok=True)
    stills = []
    for index, cut in enumerate(built["cuts"] or [{"frame": 1}], start=1):
        scene.frame_set(int(cut["frame"]))
        settings = scene.render.image_settings
        if hasattr(settings, "media_type"):
            settings.media_type = "IMAGE"
        settings.file_format = "PNG"
        path = os.path.join(out_dir, f"cut_{index:02d}.png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        stills.append({"index": index, "frame": int(cut["frame"]), "camera": cut.get("camera"), "path": path})
    video = None
    if spec.get("render_video", True):
        settings = scene.render.image_settings
        if hasattr(settings, "media_type"):
            settings.media_type = "VIDEO"
        settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        video = os.path.join(out_dir, "previz.mp4")
        scene.render.filepath = video
        bpy.ops.render.render(animation=True)
    blend = os.path.join(out_dir, "previz.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, copy=True)
    return {"blend": blend, "video": video, "stills": stills}


def main(argv: list[str]) -> None:
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    spec_path, out_dir = args[0], args[1]
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)
    built = build(spec, factory_reset=True)
    outputs = render(spec, out_dir, built)
    manifest = {**outputs, "frames": spec["frames"], "fps": spec.get("fps", 24), "resolution": spec.get("resolution"),
                "cameras": built["cameras"], "proxies": built["proxies"], "blender": bpy.app.version_string}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    print("PREVIZ_MANIFEST " + json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)

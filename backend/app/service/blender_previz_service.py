# -*- coding: utf-8 -*-
"""Blender 3D 预演台：把一场的空间方案渲染成白模预演，交给第 5 阶段当运动参考，并与打开的 Blender 双向同步。

- 渲染：方案 → 预演规格 → 本机 Blender 无界面渲染(整段 MP4 + 每镜首帧 + .blend)。同一份规格只渲一次(按内容哈希缓存)。
- 交付：按镜头切出片段，走导演台的截取通道登记成该镜的「运动参考视频」，第 5 阶段自动用它管机位、切点与时间。
- 实时：装了桥接插件的 Blender 会随对话里的每次改动重建场景；在 Blender 里拖过的站位与机位可以同步回方案。
记录存在 ``task["assets"]["4_blender_previz"]``。规则见 skills/shot-design-master/references/blender-previz-protocol.md。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.core import media_compositor
from app.core.blender_previz import build_spec, live, operations_from_snapshot, runner
from app.core.spatial_stage.models import StagePlan
from app.service import director_desk_service as director_desk
from app.service import spatial_stage_service as spatial_stage

logger = logging.getLogger("app.service.blender_previz")

STORE_KEY = "4_blender_previz"
MEDIA_SUBDIR = "previz"
MAX_HANDHELD_SHOTS = 200
MAX_RESERVED = 20


class PrevizError(ValueError):
    """这一步做不了；消息直接给用户或对话里的模型看。"""


# --------------------------------------------------------------------------- store


def _store(task: dict[str, Any]) -> dict[str, Any]:
    store = task.setdefault("assets", {}).setdefault(STORE_KEY, {})
    store.setdefault("version", 1)
    store.setdefault("scenes", {})
    return store


def _scene_entry(task: dict[str, Any], scene_id: str) -> dict[str, Any]:
    return _store(task)["scenes"].setdefault(scene_id, {"options": {}, "latest": None})


def _peek(task: Mapping[str, Any], scene_id: str) -> Mapping[str, Any]:
    return (((task.get("assets") or {}).get(STORE_KEY) or {}).get("scenes") or {}).get(scene_id) or {}


def _plan(task: Mapping[str, Any], scene_id: str) -> StagePlan:
    plan = spatial_stage.load_plan(task, scene_id)
    if plan is None:
        raise PrevizError(f"场景 {scene_id} 还没有空间方案；先完成第 4 阶段分镜或在导演台重建方案")
    return plan


def _durations(task: Mapping[str, Any], scene_id: str) -> dict[int, float]:
    out: dict[int, float] = {}
    for shot in spatial_stage.scene_shots(task, scene_id):
        try:
            seconds = float(shot.get("duration") or 0)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            out[int(shot.get("shot_id") or 0)] = seconds
    return out


def _spec(task: Mapping[str, Any], scene_id: str, *, shot_ids: list[int] | None = None, long_edge: int = 1920):
    plan = _plan(task, scene_id)
    try:
        spec, segments = build_spec(plan, durations=_durations(task, scene_id), options=_peek(task, scene_id).get("options") or {},
                                    shot_ids=shot_ids, long_edge=long_edge)
    except ValueError as exc:
        raise PrevizError(str(exc)) from exc
    return plan, spec, segments


def _url(path: Path) -> str:
    root = Path(media_compositor.MEDIA_DIR).resolve()
    return media_compositor.public_url(os.path.relpath(str(path.resolve()), str(root)).replace(os.sep, "/"))


def _safe(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or ch in "-_")[:40] or "x"


# --------------------------------------------------------------------------- status


def status() -> dict[str, Any]:
    binary = runner.find_blender()
    connected = live.ping()
    return {
        "blender_found": bool(binary), "blender_path": binary or "", "blender_version": runner.blender_version(binary) if binary else "",
        "live_connected": bool(connected and connected.get("ok")), "live": connected or {},
        "live_port": live.PORT, "addon_download": "/api/blender/addon.zip",
    }


def get_previz(task: Mapping[str, Any], scene_id: str) -> dict[str, Any]:
    entry = _peek(task, scene_id)
    plan = spatial_stage.load_plan(task, scene_id)
    latest = entry.get("latest")
    stale = bool(latest) and plan is not None and int(latest.get("plan_revision") or -1) != plan.revision
    return {"scene_id": scene_id, "options": entry.get("options") or {}, "latest": latest, "stale": stale,
            "plan_revision": plan.revision if plan is not None else None}


# --------------------------------------------------------------------------- render


def render_scene(service, task_id: str, scene_id: str, *, shot_ids: list[int] | None = None,
                 long_edge: int = 1920, push_live: bool = True) -> dict[str, Any]:
    """渲染一场的白模预演并记下来；同一份规格已经渲过就直接复用。"""
    task = service.repo.get_task(task_id)
    if not task:
        raise LookupError("任务不存在")
    plan, spec, segments = _spec(task, scene_id, shot_ids=shot_ids, long_edge=long_edge)
    digest = hashlib.sha256(spec.model_dump_json().encode("utf-8")).hexdigest()[:12]
    out_dir = Path(media_compositor.MEDIA_DIR) / MEDIA_SUBDIR / _safe(task_id) / _safe(scene_id) / f"r{plan.revision}-{digest}"
    manifest = out_dir / "manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        video = Path(data["video"]) if data.get("video") else None
        stills, version = data.get("stills") or [], data.get("blender") or ""
        reused = True
    else:
        try:
            result = runner.render(spec, out_dir)
        except (runner.BlenderUnavailable, runner.RenderFailed) as exc:
            shutil.rmtree(out_dir, ignore_errors=True)
            raise PrevizError(str(exc)) from exc
        video, stills, version, reused = result.video, result.stills, result.blender_version, False
    record = {
        "plan_revision": plan.revision, "spec_hash": digest, "rendered_at": datetime.now(timezone.utc).isoformat(),
        "video_url": _url(video) if video else "", "blend_url": _url(out_dir / "previz.blend"),
        "stills": [{"shot_id": segment["shot_id"], "url": _url(Path(still["path"]))} for segment, still in zip(segments, stills)],
        "segments": segments, "fps": spec.fps, "frames": spec.frames, "resolution": list(spec.resolution),
        "blender_version": version, "reused": reused,
        "proxies": [{"id": p.id, "name": p.binds.name, "kind": p.binds.kind, "color": p.color} for p in spec.proxies],
    }

    def save(locked: dict[str, Any]) -> dict[str, Any]:
        _scene_entry(locked, scene_id)["latest"] = record
        return locked

    service.repo.mutate_task(task_id, save)
    pushed = live.push(spec) if push_live else None
    return {**record, "live": bool(pushed and pushed.get("ok"))}


# --------------------------------------------------------------------------- options


def set_options(service, task_id: str, scene_id: str, *, handheld_shots: list[int] | None = None,
                reserved: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """手持镜头(低频摆动 + 微震)与专项效果空段；改完下一次渲染生效。"""
    clean_reserved: list[dict[str, Any]] | None = None
    if reserved is not None:
        if len(reserved) > MAX_RESERVED:
            raise PrevizError(f"空段最多 {MAX_RESERVED} 个")
        clean_reserved = []
        for slot in reserved:
            try:
                start, end = float(slot.get("from_s", 0)), float(slot.get("to_s", 0))
                shot_id = int(slot["shot_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PrevizError("空段需要 shot_id、from_s、to_s") from exc
            if not 0 <= start < end <= 30:
                raise PrevizError("空段的 from_s / to_s 须满足 0 ≤ from_s < to_s ≤ 30")
            clean_reserved.append({"shot_id": shot_id, "from_s": start, "to_s": end, "label": str(slot.get("label") or "专项效果")[:40]})
    if handheld_shots is not None and len(handheld_shots) > MAX_HANDHELD_SHOTS:
        raise PrevizError("手持镜头太多")

    def change(task: dict[str, Any]) -> dict[str, Any]:
        _plan(task, scene_id)
        options = _scene_entry(task, scene_id).setdefault("options", {})
        if handheld_shots is not None:
            options["handheld_shots"] = sorted({int(v) for v in handheld_shots})
        if clean_reserved is not None:
            options["reserved"] = clean_reserved
        return task

    task = service.repo.mutate_task(task_id, change)
    if not task:
        raise LookupError("任务不存在")
    return get_previz(task, scene_id)


# --------------------------------------------------------------------------- hand-off to stage 5


def attach_to_shots(service, task_id: str, scene_id: str, *, shot_ids: list[int] | None = None) -> dict[str, Any]:
    """把最近一次预演按镜头切片，登记成导演台截取并应用到分镜：第 5 阶段用它当运动参考视频。"""
    task = service.repo.get_task(task_id)
    if not task:
        raise LookupError("任务不存在")
    plan = _plan(task, scene_id)
    latest = _peek(task, scene_id).get("latest")
    if not latest:
        raise PrevizError("这一场还没有渲染过 Blender 预演；先渲染")
    if int(latest.get("plan_revision") or -1) != plan.revision:
        raise PrevizError("站位或机位在渲染之后改过了；先重新渲染预演，再交给分镜")
    video = director_desk.media_path(str(latest.get("video_url") or ""))
    video_path = Path(video) if video else None
    if video_path is None or not video_path.is_file():
        # 媒体在子目录里：按 URL 的相对路径找。
        relative = str(latest.get("video_url") or "").split("/media/", 1)[-1]
        video_path = Path(media_compositor.MEDIA_DIR) / relative
    if not video_path.is_file():
        raise PrevizError("预演视频文件不见了；请重新渲染")
    wanted = {int(v) for v in shot_ids} if shot_ids else None
    width, height = latest["resolution"]
    attached, failed = [], []
    for segment in latest["segments"]:
        shot_id = int(segment["shot_id"])
        if wanted is not None and shot_id not in wanted:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                clip = runner.cut_clip(video_path, segment["start"], segment["end"], int(latest["fps"]), Path(tmp) / "shot.mp4")
                upload = director_desk.CaptureUpload(
                    content=clip.read_bytes(), kind="clip", shot_id=shot_id, camera_id=f"blender:{segment['camera']}",
                    plan_revision=plan.revision, shows_limbs=False, monochrome=False, labelled=False,
                    width=int(width), height=int(height), duration_s=float(segment["seconds"]), fps=int(latest["fps"]),
                )
                capture = service.add_desk_capture(task_id, scene_id, upload)
                if capture is None:
                    raise PrevizError("任务不存在")
                service.apply_desk_capture(task_id, scene_id, capture["id"])
                attached.append({"shot_id": shot_id, "capture_id": capture["id"], "url": capture["url"]})
            except (runner.RenderFailed, director_desk.CaptureError, PrevizError, LookupError) as exc:
                failed.append({"shot_id": shot_id, "error": str(exc)})
    return {"scene_id": scene_id, "attached": attached, "failed": failed}


# --------------------------------------------------------------------------- live Blender


def push_live(service, task_id: str, scene_id: str) -> dict[str, Any]:
    task = service.repo.get_task(task_id)
    if not task:
        raise LookupError("任务不存在")
    _, spec, segments = _spec(task, scene_id)
    answer = live.push(spec)
    if not answer:
        raise PrevizError("没连上 Blender：请在 Blender 里启用「Short Drama Previz Bridge」插件，并在 N 面板「短剧预演」点「开始连接」")
    if not answer.get("ok"):
        raise PrevizError(f"Blender 重建场景失败：{answer.get('error')}")
    return {"scene_id": scene_id, "segments": segments, "proxies": answer.get("proxies"), "cameras": answer.get("cameras")}


def pull_live(service, task_id: str, scene_id: str, *, apply: bool = False) -> dict[str, Any]:
    """读回在 Blender 里拖过的站位、布景与机位，换成方案的语义操作；apply=True 时写回方案。"""
    task = service.repo.get_task(task_id)
    if not task:
        raise LookupError("任务不存在")
    plan, _, segments = _spec(task, scene_id)
    shot = live.snapshot()
    if not shot or not shot.get("ok"):
        raise PrevizError("没连上 Blender，或 Blender 里还没有预演场景；先「推到 Blender」")
    operations = operations_from_snapshot(plan, shot, segments)
    result: dict[str, Any] = {"scene_id": scene_id, "operations": operations, "applied": False}
    if apply and operations:
        updated = service.patch_spatial_plan(task_id, scene_id, base_revision=plan.revision, operations=operations, solve=False)
        result.update(applied=True, revision=((updated or {}).get("plan") or {}).get("revision"))
    return result

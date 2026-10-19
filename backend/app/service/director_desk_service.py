# -*- coding: utf-8 -*-
"""What the 3D director desk hands back to generation: stills, blockout clips and saved poses.

The stage itself lives in ``assets["4_spatial"]`` and is edited through the spatial service.
This module keeps the *pictures taken of it* under ``assets["4_director_desk"]``:

    {version, scenes: {scene_id: {captures: [Capture], applied: {shot_id: {still, clip}}}}, poses: [SavedPose]}

Applying a capture writes its URL into the two per-shot slots stage 5 already reads — a still
to the front of ``sequence_images``, a clip to the front of ``reference_videos`` — and remembers
it in ``applied`` so it can be taken back out. A capture is a photograph of one revision of the
blocking: once the blocking is edited every capture of the scene is ``stale``, and stage 5
refuses a stale applied clip the same way it refuses a stale board.
"""

from __future__ import annotations

import logging
import math
import os
import re
import struct
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.reference_limits import MAX_REFERENCE_VIDEOS, MAX_SEQUENCE_IMAGES
from app.core import media_compositor
from app.core.spatial_stage.models import StagePose
from app.core.spatial_stage.prompting import without_camera_pose

logger = logging.getLogger("app.service.director_desk")

ASSET_KEY = "4_director_desk"
STORE_VERSION = 1
MAX_CAPTURES_PER_SCENE = 60
# A backdrop is a reference underlay, not a photograph of the blocking: it has its own, smaller
# room so uploading one never costs a scene one of its sixty stills.
MAX_BACKDROPS_PER_SCENE = 20
MAX_SAVED_POSES = 200
_MEBIBYTE = 1024 * 1024
MAX_STILL_BYTES = 10 * _MEBIBYTE
MAX_CLIP_BYTES = 60 * _MEBIBYTE
MAX_CLIP_SECONDS = 30.0
CLIP_FRAME_RATES = (24, 25, 30)
_FRAME_RATE_TEXT = " / ".join(str(rate) for rate in CLIP_FRAME_RATES)
# What stage 5 accepts per shot (``ShotMotionContract.reference_videos``); a fourth would be dropped silently.
_KINDS = ("still", "clip", "backdrop")
# Only these two kinds are ever handed to a shot; a backdrop has no slot on purpose.
_SLOT = {"still": "sequence_images", "clip": "reference_videos"}
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
_SAFE = re.compile(r"[^A-Za-z0-9_-]")
# Blockout rule 2: a video model copies a white model's limbs, so limbs on screen need their motion spelled out.
LIMBS_WARNING = "白模带四肢：请在动作描述里写清分段肢体动作，否则四肢容易僵化"
DEPTH_WARNING = "深度画面：近亮远暗的灰度图，只约束空间层次、走位与运镜，不约束颜色与材质"
DEPTH_REQUIREMENT = (
    "参考视频是导演台导出的灰度深度画面（近处亮、远处暗）：只按它复现人物的前后层次、走位路线和镜头运动，"
    "画面的颜色、材质和光线按文字描述生成，不要复制灰度"
)
LIMBS_REQUIREMENT = (
    "白模参考里的替身带四肢，动作描述须按时间顺序逐段写出肢体动作（前倾角度、步幅、重心、手臂与布料动态），"
    "不得只给结果状态，四肢不照搬白模的僵直姿态"
)


class CaptureError(ValueError):
    """The upload, or what was asked of a capture, is not acceptable; the message says why."""


# --------------------------------------------------------------------------- what the bytes really are


def sniff_media(content: bytes) -> str | None:
    """The media type the leading bytes prove, whatever the client called the file."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        return "video/mp4"
    # EBML; the DocType that follows within the header says WebM rather than any other Matroska.
    if content.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in content[:64]:
        return "video/webm"
    return None


_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4", "video/webm": "webm"}


def mp4_duration(content: bytes) -> float | None:
    """Seconds, from the ``mvhd`` box of an MP4; ``None`` when the file does not carry one where it should."""
    offset, end = 0, len(content)
    while offset + 8 <= end:
        size, kind = struct.unpack(">I4s", content[offset:offset + 8])
        header = 8
        if size == 1 and offset + 16 <= end:
            size, header = struct.unpack(">Q", content[offset + 8:offset + 16])[0], 16
        elif size == 0:
            size = end - offset
        if size < header:
            return None
        if kind == b"moov":
            offset, end = offset + header, min(end, offset + size)
            continue
        if kind == b"mvhd":
            body = content[offset + header:offset + size]
            if len(body) < 20:
                return None
            if body[0] == 1 and len(body) >= 32:
                timescale, duration = struct.unpack(">IQ", body[20:32])
            else:
                timescale, duration = struct.unpack(">II", body[12:20])
            return duration / timescale if timescale else None
        offset += size
    return None


@dataclass(frozen=True)
class CaptureUpload:
    content: bytes
    kind: str
    shot_id: int
    camera_id: str = ""
    plan_revision: int = 0
    shows_limbs: bool = False
    monochrome: bool = False
    labelled: bool = False
    # A depth pass: a grayscale picture of distance, not of the white models.
    depth: bool = False
    width: int = 0
    height: int = 0
    duration_s: float = 0.0
    fps: int = 0


def validate_upload(upload: CaptureUpload) -> str:
    """The proven media type of an acceptable upload; raises :class:`CaptureError` otherwise."""
    if upload.kind not in _KINDS:
        raise CaptureError("kind 只能是 still、clip 或 backdrop")
    if not upload.content:
        raise CaptureError("上传的文件是空的")
    proven = sniff_media(upload.content[:4096])
    if upload.kind == "backdrop":
        if len(upload.content) > MAX_STILL_BYTES:
            raise CaptureError(f"背景图不能超过 {MAX_STILL_BYTES // _MEBIBYTE} MB")
        if proven not in _IMAGE_TYPES:
            raise CaptureError("背景图只支持 PNG、JPEG、WebP；文件内容不是其中任何一种")
    elif upload.kind == "still":
        if len(upload.content) > MAX_STILL_BYTES:
            raise CaptureError(f"静帧不能超过 {MAX_STILL_BYTES // _MEBIBYTE} MB")
        if proven not in _IMAGE_TYPES:
            raise CaptureError("静帧只支持 PNG、JPEG、WebP；文件内容不是其中任何一种")
    else:
        if len(upload.content) > MAX_CLIP_BYTES:
            raise CaptureError(f"白模视频不能超过 {MAX_CLIP_BYTES // _MEBIBYTE} MB")
        if proven not in {"video/mp4", "video/webm"}:
            raise CaptureError("白模视频只支持 MP4、WebM；文件内容不是其中任何一种")
        if not math.isfinite(upload.duration_s) or not 0 < upload.duration_s <= MAX_CLIP_SECONDS:
            raise CaptureError(f"白模视频时长必须在 0 到 {MAX_CLIP_SECONDS:g} 秒之间")
        # The declared length is what gets recorded; when the container states one, it has to agree.
        measured = mp4_duration(upload.content) if proven == "video/mp4" else None
        if measured is not None and measured > MAX_CLIP_SECONDS + 0.5:
            raise CaptureError(f"白模视频实际时长 {measured:.1f} 秒，超过 {MAX_CLIP_SECONDS:g} 秒上限")
    if upload.depth and upload.kind == "backdrop":
        raise CaptureError("背景图没有深度画面一说")
    # A backdrop belongs to the scene, not to one shot, so it may arrive without a shot number.
    if not (0 if upload.kind == "backdrop" else 1) <= upload.shot_id <= 10_000:
        raise CaptureError("shot_id 必须是 1 到 10000 的镜头编号")
    if not 0 <= upload.width <= 8192 or not 0 <= upload.height <= 8192:
        raise CaptureError("width / height 必须在 0 到 8192 之间")
    # A desk clip is one shot's timeline rendered frame by frame, so it can only have a timeline's rate; 0 is "not stated".
    if upload.fps not in (0, *CLIP_FRAME_RATES):
        raise CaptureError(f"fps 只能是 {_FRAME_RATE_TEXT}（与时间线的帧率一致）")
    if upload.plan_revision < 0:
        raise CaptureError("plan_revision 不能为负")
    return proven


# --------------------------------------------------------------------------- the store


def store_of(task: dict[str, Any]) -> dict[str, Any]:
    assets = task.setdefault("assets", {})
    store = assets.get(ASSET_KEY)
    if not isinstance(store, dict) or store.get("version") != STORE_VERSION:
        store = {"version": STORE_VERSION, "scenes": {}, "poses": []}
        assets[ASSET_KEY] = store
    if not isinstance(store.get("scenes"), dict):
        store["scenes"] = {}
    if not isinstance(store.get("poses"), list):
        store["poses"] = []
    return store


def _peek(task: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    store = assets.get(ASSET_KEY)
    return store if isinstance(store, Mapping) and store.get("version") == STORE_VERSION else {}


def _scene(task: dict[str, Any], scene_id: str) -> dict[str, Any]:
    scenes = store_of(task)["scenes"]
    entry = scenes.get(scene_id)
    if not isinstance(entry, dict):
        entry = scenes[scene_id] = {"captures": [], "applied": {}}
    if not isinstance(entry.get("captures"), list):
        entry["captures"] = []
    if not isinstance(entry.get("applied"), dict):
        entry["applied"] = {}
    return entry


def scene_view(task: Mapping[str, Any], scene_id: str) -> dict[str, Any]:
    entry = (_peek(task).get("scenes") or {}).get(scene_id)
    entry = entry if isinstance(entry, Mapping) else {}
    return {
        "task_id": str(task.get("task_id") or ""), "scene_id": scene_id,
        "captures": [dict(item) for item in entry.get("captures") or [] if isinstance(item, Mapping)],
        "applied": {str(key): dict(value) for key, value in (entry.get("applied") or {}).items() if isinstance(value, Mapping)},
    }


def _shot(task: dict[str, Any], scene_id: str, shot_id: int) -> dict[str, Any] | None:
    return next((
        shot for shot in (task.get("assets") or {}).get("4") or []
        if isinstance(shot, dict) and str(shot.get("scene_id") or "") == scene_id and int(shot.get("shot_id") or 0) == shot_id
    ), None)


def _capture(entry: Mapping[str, Any], capture_id: str) -> dict[str, Any]:
    found = next((item for item in entry["captures"] if isinstance(item, dict) and item.get("id") == capture_id), None)
    if found is None:
        raise LookupError("这条导演台截取记录不存在，可能已被删除")
    return found


def media_path(url: str) -> str | None:
    """The file under ``MEDIA_DIR`` a capture URL points at, or ``None`` when it is not one of ours."""
    name = os.path.basename(str(url or ""))
    if not name.startswith("desk_"):
        return None
    return os.path.join(media_compositor.MEDIA_DIR, name)


def store_media(task_id: str, scene_id: str, content: bytes, media_type: str) -> str:
    """Write the bytes under a name the server made up; the public URL of the file."""
    os.makedirs(media_compositor.MEDIA_DIR, exist_ok=True)
    name = "desk_{}_{}_{}.{}".format(
        _SAFE.sub("", task_id)[:40] or "task", _SAFE.sub("", scene_id)[:24] or "scene", uuid.uuid4().hex, _EXTENSIONS[media_type],
    )
    with open(os.path.join(media_compositor.MEDIA_DIR, name), "wb") as handle:
        handle.write(content)
    return media_compositor.public_url(name)


def discard_media(url: str) -> None:
    path = media_path(url)
    if path is None:
        return
    try:
        os.remove(path)
    except OSError:
        logger.warning("[DirectorDesk] 无法删除截取文件 %s", os.path.basename(path))


def ensure_room(task: Mapping[str, Any], scene_id: str, kind: str = "still") -> None:
    captures = scene_view(task, scene_id)["captures"]
    if kind == "backdrop":
        if sum(1 for item in captures if item.get("kind") == "backdrop") >= MAX_BACKDROPS_PER_SCENE:
            raise CaptureError(f"本场已有 {MAX_BACKDROPS_PER_SCENE} 张背景图，请先删除不用的再上传")
        return
    if sum(1 for item in captures if item.get("kind") != "backdrop") >= MAX_CAPTURES_PER_SCENE:
        raise CaptureError(f"本场已有 {MAX_CAPTURES_PER_SCENE} 条截取记录，请先删除不用的再上传")


def add_capture(task: dict[str, Any], scene_id: str, upload: CaptureUpload, url: str) -> dict[str, Any]:
    ensure_room(task, scene_id, upload.kind)
    capture = {
        "id": uuid.uuid4().hex, "kind": upload.kind, "shot_id": upload.shot_id, "camera_id": upload.camera_id[:80],
        "url": url, "width": upload.width, "height": upload.height,
        "duration_s": round(upload.duration_s, 3) if upload.kind == "clip" else 0.0,
        "fps": upload.fps if upload.kind == "clip" else 0,
        "plan_revision": upload.plan_revision,
        # Only a clip can show limbs *moving*, which is what blockout rule 2 is about.
        "shows_limbs": bool(upload.shows_limbs), "monochrome": bool(upload.monochrome), "labelled": bool(upload.labelled),
        "depth": bool(upload.depth),
        "created_at": datetime.now(timezone.utc).isoformat(), "stale": False,
        "warning": DEPTH_WARNING if upload.depth else LIMBS_WARNING if upload.shows_limbs else "",
    }
    _scene(task, scene_id)["captures"].append(capture)
    return capture


def _unslot(shot: dict[str, Any] | None, slot: str, url: str) -> None:
    if shot is not None and isinstance(shot.get(slot), list):
        shot[slot] = [item for item in shot[slot] if item != url]


def unapply_capture(task: dict[str, Any], scene_id: str, capture_id: str) -> dict[str, Any]:
    entry = _scene(task, scene_id)
    capture = _capture(entry, capture_id)
    # A backdrop was never in a shot's slot; there is nothing to take out of one.
    if capture["kind"] not in _SLOT:
        return scene_view(task, scene_id)
    slot = entry["applied"].get(str(capture["shot_id"]))
    if isinstance(slot, dict) and slot.get(capture["kind"]) == capture_id:
        slot.pop(capture["kind"])
        if not slot:
            entry["applied"].pop(str(capture["shot_id"]))
    _unslot(_shot(task, scene_id, int(capture["shot_id"])), _SLOT[capture["kind"]], capture["url"])
    return scene_view(task, scene_id)


def apply_capture(task: dict[str, Any], scene_id: str, capture_id: str) -> dict[str, Any]:
    entry = _scene(task, scene_id)
    capture = _capture(entry, capture_id)
    if capture["kind"] not in _SLOT:
        raise CaptureError("背景图只在导演台的机位画面里作参考，不能应用到分镜")
    if capture.get("stale"):
        raise CaptureError("这条截取是按旧站位拍的，站位已修改；请在导演台重新截取后再应用")
    if capture.get("depth") and capture["kind"] == "still":
        # A first-frame reference is copied by the video model; a depth picture would be copied as a grey frame.
        raise CaptureError("深度静帧不能作为首帧参考图应用到分镜；请导出深度视频作为运动参考，或截取普通静帧")
    shot = _shot(task, scene_id, int(capture["shot_id"]))
    if shot is None:
        raise CaptureError(f"本场分镜里还没有第 {capture['shot_id']} 镜，请先完成第 4 阶段分镜")
    kind = capture["kind"]
    slot, limit = _SLOT[kind], MAX_REFERENCE_VIDEOS if kind == "clip" else MAX_SEQUENCE_IMAGES
    applied = entry["applied"].setdefault(str(capture["shot_id"]), {})
    # One desk still and one desk clip per shot: a newer one takes the older one's place.
    previous = next((item for item in entry["captures"] if item.get("id") == applied.get(kind) and item is not capture), None)
    if previous is not None:
        _unslot(shot, slot, previous["url"])
    current = [item for item in (shot.get(slot) if isinstance(shot.get(slot), list) else []) if item != capture["url"]]
    shot[slot] = [capture["url"], *current][:limit]
    applied[kind] = capture_id
    return scene_view(task, scene_id)


def delete_capture(task: dict[str, Any], scene_id: str, capture_id: str) -> tuple[dict[str, Any], str]:
    """Remove the record (taking it out of its slot first); returns the view and the URL whose file can go."""
    unapply_capture(task, scene_id, capture_id)
    entry = _scene(task, scene_id)
    url = str(_capture(entry, capture_id).get("url") or "")
    entry["captures"] = [item for item in entry["captures"] if not (isinstance(item, dict) and item.get("id") == capture_id)]
    return scene_view(task, scene_id), url


def mark_captures_stale(task: dict[str, Any], scene_id: str) -> None:
    """The blocking changed: every picture taken of the old one says so until it is taken again."""
    entry = (_peek(task).get("scenes") or {}).get(scene_id)
    for capture in (entry.get("captures") or []) if isinstance(entry, Mapping) else []:
        # A backdrop is not a picture *of* the blocking, so moving someone does not date it.
        if isinstance(capture, dict) and capture.get("kind") != "backdrop":
            capture["stale"] = True


# --------------------------------------------------------------------------- stage 5


@dataclass(frozen=True)
class ShotBlockout:
    """What stage 5 needs to know about the desk clip applied to one shot."""

    stale_urls: frozenset[str] = frozenset()
    clip_url: str = ""
    shows_limbs: bool = False
    depth: bool = False

    @property
    def owns_camera(self) -> bool:
        return bool(self.clip_url)


def shot_blockout(task: Mapping[str, Any], shot: Mapping[str, Any]) -> ShotBlockout:
    scene_id = str(shot.get("scene_id") or "")
    entry = (_peek(task).get("scenes") or {}).get(scene_id)
    if not isinstance(entry, Mapping):
        return ShotBlockout()
    captures = [item for item in entry.get("captures") or [] if isinstance(item, Mapping) and item.get("kind") == "clip"]
    # Any stale desk clip is refused, applied or left behind in the slot by an older version of the record.
    stale = frozenset(str(item.get("url")) for item in captures if item.get("stale") and item.get("url"))
    applied = (entry.get("applied") or {}).get(str(shot.get("shot_id")))
    clip_id = applied.get("clip") if isinstance(applied, Mapping) else None
    clip = next((item for item in captures if item.get("id") == clip_id), None)
    references = shot.get("reference_videos") if isinstance(shot.get("reference_videos"), list) else []
    if clip is None or clip.get("stale") or clip.get("url") not in references:
        return ShotBlockout(stale_urls=stale)
    return ShotBlockout(
        stale_urls=stale, clip_url=str(clip["url"]), shows_limbs=bool(clip.get("shows_limbs")), depth=bool(clip.get("depth")),
    )


@dataclass(frozen=True)
class MotionInputs:
    """A shot's motion references and camera wording after the desk has had its say."""

    reference_videos: list[str]
    blocking: str
    motion_prompt: str
    refused: list[str]
    blockout: ShotBlockout


def motion_inputs(
    task: Mapping[str, Any], shot: Mapping[str, Any], reference_videos: list[str], blocking: str, motion_prompt: str,
) -> MotionInputs:
    """Stage 5's gate. A stale desk clip is dropped from the references (the caller logs ``refused``).

    While a fresh one is applied, the measured lens-pose clause is withheld from both texts that
    carry it: the clip is the only camera reference (blockout rule 3), and two camera
    instructions compete.
    """
    blockout = shot_blockout(task, shot)
    refused = [url for url in reference_videos if url in blockout.stale_urls]
    kept = [url for url in reference_videos if url not in blockout.stale_urls]
    if not blockout.owns_camera:
        return MotionInputs(kept, blocking, motion_prompt, refused, blockout)
    motion = without_camera_pose(motion_prompt)
    if blockout.shows_limbs and LIMBS_REQUIREMENT not in motion:
        # Stage 5 has no Sd25CompileRequest to set ``blockout_standin_limbs`` on; the requirement rides
        # with the motion prompt instead, and only while the limbed clip is the one being followed.
        motion = f"{motion.rstrip('。；; ')}。{LIMBS_REQUIREMENT}。" if motion.strip() else f"{LIMBS_REQUIREMENT}。"
    if blockout.depth and DEPTH_REQUIREMENT not in motion:
        # A depth clip carries layers and motion only; say so, or the model paints the grey.
        motion = f"{motion.rstrip('。；; ')}。{DEPTH_REQUIREMENT}。" if motion.strip() else f"{DEPTH_REQUIREMENT}。"
    # ``blocking`` is a required field downstream: a sentence that was nothing but the lens pose stays.
    return MotionInputs(kept, without_camera_pose(blocking) or blocking, motion, refused, blockout)


# --------------------------------------------------------------------------- saved poses


def list_poses(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in _peek(task).get("poses") or [] if isinstance(item, Mapping)]


def save_pose(task: dict[str, Any], name: str, pose: StagePose) -> dict[str, Any]:
    poses = store_of(task)["poses"]
    label = name.strip()
    if not label:
        raise CaptureError("姿态需要一个名称")
    existing = next((item for item in poses if isinstance(item, dict) and item.get("name") == label), None)
    if existing is None and len(poses) >= MAX_SAVED_POSES:
        raise CaptureError(f"最多保存 {MAX_SAVED_POSES} 个姿态，请先删除不用的")
    record = {
        "id": existing["id"] if existing else uuid.uuid4().hex, "name": label, "pose": pose.model_dump(mode="json"),
        "created_at": existing["created_at"] if existing else datetime.now(timezone.utc).isoformat(),
    }
    if existing is not None:
        poses[poses.index(existing)] = record
    else:
        poses.append(record)
    return record


def delete_pose(task: dict[str, Any], pose_id: str) -> None:
    poses = store_of(task)["poses"]
    kept = [item for item in poses if not (isinstance(item, dict) and item.get("id") == pose_id)]
    if len(kept) == len(poses):
        raise LookupError("这个姿态不存在，可能已被删除")
    store_of(task)["poses"] = kept


__all__ = [
    "ASSET_KEY", "CLIP_FRAME_RATES", "LIMBS_REQUIREMENT", "LIMBS_WARNING", "MAX_BACKDROPS_PER_SCENE", "MAX_CAPTURES_PER_SCENE", "MAX_CLIP_BYTES", "MAX_CLIP_SECONDS", "MAX_SAVED_POSES", "MAX_STILL_BYTES",
    "CaptureError", "CaptureUpload", "MotionInputs", "ShotBlockout", "add_capture", "apply_capture", "delete_capture", "delete_pose",
    "discard_media", "ensure_room", "list_poses", "mark_captures_stale", "media_path", "motion_inputs", "mp4_duration", "save_pose",
    "scene_view", "shot_blockout", "sniff_media", "store_media", "store_of", "unapply_capture", "validate_upload",
]

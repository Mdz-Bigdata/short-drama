# -*- coding: utf-8 -*-
"""样片与局部修：先用低分辨率看样，再逐镜出高清；穿帮只修出错的那一段或那一块，不整段重抽。

* **样片**：第 5 阶段开了样片模式时按 ``draft_resolution`` 出片(480p，单价低)；人看过之后逐镜选
  「本地放大」(ffmpeg 放大，不花钱，画面偏软)或「重出高清」(同提示词同种子按全分辨率再出一次)。
* **从这里往后重做**：穿帮之前的画面保留，取穿帮那一刻的画面当首帧，只重新生成后面这几秒，再接回去。
* **区域修补**：这一镜当参考视频发给能编辑视频的模型，只改框出来的那一块。

本模块只管媒体与措辞，不调视频模型；措辞在 data/prompt/clip_fixes.json。
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import logging
import os
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any, Optional
from urllib.parse import urlparse

from app.core import media_compositor, prompt_data

logger = logging.getLogger(__name__)

_DATA = "clip_fixes"
#: 拼接后的两段统一到同一帧率，接缝处不跳帧。
_FPS = 24


def draft_resolution(config: Mapping[str, Any], clip: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """这一镜按什么分辨率出：样片模式下是 480p；人要了「重出高清」的那一镜按全分辨率(None)。"""
    if not config.get("video_draft"):
        return None
    if clip and clip.get("hd_retake"):
        return None
    return prompt_data.text(_DATA, "draft_resolution")


def _source(video_url: str) -> Optional[str]:
    path = media_compositor.local_media_path(video_url)
    return path if path and os.path.exists(path) else None


def _probe(path: str) -> dict[str, Any]:
    probe = media_compositor._ffprobe()
    if not probe:
        raise RuntimeError("找不到 ffprobe")
    out = subprocess.run(
        [probe, "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True, timeout=30, check=True,
    )
    import json

    facts = json.loads(out.stdout or "{}")
    streams = facts.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    return {
        "width": int(video.get("width") or 0), "height": int(video.get("height") or 0),
        "duration": float((facts.get("format") or {}).get("duration") or 0),
        "audio": any(item.get("codec_type") == "audio" for item in streams),
    }


def clip_seconds(video_url: str) -> Optional[float]:
    path = _source(video_url)
    if not path:
        return None
    try:
        return _probe(path)["duration"] or None
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return None


def frame_at(video_url: str, seconds: float) -> Optional[str]:
    """片段第 ``seconds`` 秒的那一帧(data URI)：从这里往后重做时当首帧。"""
    ff, path = media_compositor._ffmpeg(), _source(video_url)
    if not ff or not path:
        return None
    work = os.path.join(media_compositor.MEDIA_DIR, f"_retake_{hashlib.md5(f'{path}|{seconds}'.encode()).hexdigest()[:12]}")
    os.makedirs(work, exist_ok=True)
    frame = os.path.join(work, "frame.jpg")
    try:
        subprocess.run(
            [ff, "-y", "-ss", f"{max(0.0, seconds):.3f}", "-i", path, "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "2", frame],
            check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        with open(frame, "rb") as handle:
            return "data:image/jpeg;base64," + base64.b64encode(handle.read()).decode("ascii")
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("[ClipFixes] 取第 %.2f 秒画面失败: %s", seconds, type(error).__name__)
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _part(ff: str, src: str, start: float, length: float, size: tuple[int, int], has_audio: bool, out: str) -> None:
    """一段统一成同尺寸、同帧率、带声轨(没有就补静音)的片段，好原样拼接。"""
    width, height = size
    video = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={_FPS},format=yuv420p"
    command = [ff, "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", src]
    if not has_audio:
        command += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
    command += [
        "-vf", video, "-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", out,
    ]
    subprocess.run(command, check=True, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def splice(head_url: str, cut_seconds: float, tail_url: str, *, tag: str) -> Optional[str]:
    """原片前 ``cut_seconds`` 秒接上重做的后半段，长度与原片一致；返回本地片段地址。"""
    ff, head, tail = media_compositor._ffmpeg(), _source(head_url), _source(media_compositor.keep_clip(tail_url, tag=f"{tag}_tail") or tail_url)
    if not ff or not head or not tail:
        return None
    work = os.path.join(media_compositor.MEDIA_DIR, f"_splice_{hashlib.md5(f'{head}|{tail}|{cut_seconds}'.encode()).hexdigest()[:12]}")
    os.makedirs(work, exist_ok=True)
    try:
        before, after = _probe(head), _probe(tail)
        size = (before["width"] or media_compositor.OUT_W, before["height"] or media_compositor.OUT_H)
        cut = max(0.0, min(cut_seconds, before["duration"]))
        rest = max(0.5, min(after["duration"], (before["duration"] - cut) or after["duration"]))
        parts = [os.path.join(work, "a.mp4"), os.path.join(work, "b.mp4")]
        _part(ff, head, 0.0, cut, size, before["audio"], parts[0])
        _part(ff, tail, 0.0, rest, size, after["audio"], parts[1])
        listing = os.path.join(work, "list.txt")
        with open(listing, "w", encoding="utf-8") as handle:
            handle.write("".join(f"file '{part}'\n" for part in parts))
        name = f"{tag}_{hashlib.md5(f'{head}|{tail}|{cut}'.encode()).hexdigest()[:16]}.mp4"
        subprocess.run(
            [ff, "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", "-movflags", "+faststart", os.path.join(media_compositor.MEDIA_DIR, name)],
            check=True, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return media_compositor.public_url(name)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        logger.warning("[ClipFixes] 拼接失败: %s", type(error).__name__)
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def upscale(video_url: str, *, tag: str) -> Optional[str]:
    """样片按成片尺寸放大(短边到 1080)并轻度锐化，内容一帧不变；返回本地片段地址。"""
    ff, path = media_compositor._ffmpeg(), _source(video_url)
    if not ff or not path:
        return None
    try:
        facts = _probe(path)
        width, height = facts["width"], facts["height"]
        if not width or not height:
            return None
        short = min(media_compositor.OUT_W, media_compositor.OUT_H)
        factor = short / min(width, height)
        if factor <= 1.01:
            return video_url
        target = (round(width * factor / 2) * 2, round(height * factor / 2) * 2)
        name = f"{tag}_{hashlib.md5(f'{path}|{target}'.encode()).hexdigest()[:16]}.mp4"
        subprocess.run(
            [ff, "-y", "-i", path, "-vf", f"scale={target[0]}:{target[1]}:flags=lanczos,unsharp=5:5:0.6", "-c:v", "libx264", "-crf", "18",
             "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", os.path.join(media_compositor.MEDIA_DIR, name)],
            check=True, timeout=600, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return media_compositor.public_url(name)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        logger.warning("[ClipFixes] 放大失败: %s", type(error).__name__)
        return None


def _seconds(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def retake_prompt(prompt: str, seconds: float, note: str = "") -> str:
    """从这里往后重做：先说首帧是这一镜进行到哪一刻，再接原提示词和要改的问题。"""
    lead = prompt_data.text(_DATA, "retake_lead").format(seconds=_seconds(seconds))
    fix = prompt_data.text(_DATA, "retake_fix").format(note=note.strip().rstrip("。")) if note.strip() else ""
    return f"{lead}{fix}\n{prompt}".strip()


def region_words(box: Mapping[str, Any]) -> str:
    """框(x, y, w, h，都是 0–1 的比例)说成画面上的位置：「画面左下角约占画面四分之一的区域」。"""
    x, y = float(box.get("x") or 0), float(box.get("y") or 0)
    w, h = float(box.get("w") or 0), float(box.get("h") or 0)
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1):
        raise ValueError("修补区域要在画面里")
    row = min(2, int((y + h / 2) * 3))
    column = min(2, int((x + w / 2) * 3))
    place = prompt_data.value(_DATA, "regions")[row][column]
    share = w * h
    portion = "十分之一" if share <= 0.12 else "四分之一" if share <= 0.3 else "一半" if share <= 0.6 else "大部分"
    return f"画面{place.removeprefix('画面')}" + prompt_data.text(_DATA, "region_size").format(portion)


def repair_prompt(note: str, box: Mapping[str, Any], start: Optional[float] = None, end: Optional[float] = None) -> str:
    if not note.strip():
        raise ValueError("写一下这一块要怎么改")
    when = (
        prompt_data.text(_DATA, "repair_when").format(start=_seconds(start), end=_seconds(end))
        if start is not None and end is not None and end > start else ""
    )
    return prompt_data.text(_DATA, "repair").format(region=region_words(box), when=when, note=note.strip().rstrip("。"))


def provider_can_fetch(url: str) -> bool:
    """视频模型从外网取得到这个地址吗：本机、内网地址取不到。"""
    host = (urlparse(str(url or "")).hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (address.is_private or address.is_loopback or address.is_link_local)


def unreachable_note(url: str) -> str:
    return prompt_data.text(_DATA, "unreachable").format(url)


__all__ = [
    "clip_seconds", "draft_resolution", "frame_at", "provider_can_fetch", "region_words", "repair_prompt", "retake_prompt",
    "splice", "unreachable_note", "upscale",
]

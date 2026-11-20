"""A browser-playable copy of an uploaded video whose own encoding a browser may not play (H.265, ProRes, 10-bit).

The original is kept as it is: generation and composition read it. The copy is an H.264 / yuv420p MP4 with
AAC sound and its index at the front, scaled so the long side is at most the configured size; it is only for
watching on the page. A video that a browser already plays gets no copy.

Codecs, pixel formats and containers counted as playable, the preview's size, quality and time limit are in
``app/data/prompt/video_preview.json``.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core import prompt_data

logger = logging.getLogger("app.core.video_preview")
_DATA = "video_preview"


class PreviewError(RuntimeError):
    """The video could not be read or turned into a preview."""


@dataclass(frozen=True)
class VideoFacts:
    codec: str
    pixel_format: str
    profile: str
    width: int
    height: int
    has_audio: bool


def _rules() -> dict[str, Any]:
    return prompt_data.load(_DATA)


def _error(key: str, **values: object) -> PreviewError:
    return PreviewError(str(_rules()["errors"][key]).format(**values))


def _binaries() -> tuple[str, str]:
    from app.core import media_compositor

    ffmpeg, ffprobe = media_compositor._ffmpeg(), media_compositor._ffprobe()
    if not ffmpeg or not ffprobe:
        raise _error("no_ffmpeg")
    return ffmpeg, ffprobe


def probe(path: str | os.PathLike[str]) -> VideoFacts:
    """The first video stream's codec, pixel format, profile and size, and whether there is sound."""
    _, ffprobe = _binaries()
    try:
        found = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name,pix_fmt,profile,width,height", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        streams = json.loads(found.stdout or "{}").get("streams") or []
    except (subprocess.SubprocessError, ValueError, OSError) as error:
        raise _error("unreadable") from error
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not video:
        raise _error("unreadable")
    return VideoFacts(
        codec=str(video.get("codec_name") or "").lower(), pixel_format=str(video.get("pix_fmt") or "").lower(),
        profile=str(video.get("profile") or ""), width=int(video.get("width") or 0), height=int(video.get("height") or 0),
        has_audio=any(item.get("codec_type") == "audio" for item in streams),
    )


def browser_plays(facts: VideoFacts, suffix: str) -> bool:
    """Whether a browser plays this as it is: a common codec, 8-bit 4:2:0, in an MP4 or WebM file."""
    rules = _rules()
    return (
        suffix.lower() in rules["browser_containers"]
        and facts.codec in rules["browser_codecs"]
        and facts.pixel_format in rules["browser_pixel_formats"]
    )


def _scale(facts: VideoFacts) -> str:
    side = int(_rules()["long_side"])
    if max(facts.width, facts.height) <= side:
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    return f"scale={side}:-2" if facts.width >= facts.height else f"scale=-2:{side}"


def make_preview(source: str | os.PathLike[str], target: str | os.PathLike[str], facts: VideoFacts | None = None) -> Path:
    """Write the browser-playable copy of ``source`` to ``target`` (replaced only once it is complete)."""
    ffmpeg, _ = _binaries()
    facts = facts or probe(source)
    rules = _rules()
    target = Path(target)
    partial = target.with_name(f".{target.name}.{os.getpid()}.part.mp4")
    command = [
        ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(source), "-map", "0:v:0", "-vf", _scale(facts),
        "-c:v", "libx264", "-preset", str(rules["preset"]), "-crf", str(rules["crf"]), "-pix_fmt", "yuv420p",
    ]
    command += ["-map", "0:a:0", "-c:a", "aac", "-b:a", str(rules["audio_bitrate"])] if facts.has_audio else ["-an"]
    command += ["-movflags", "+faststart", str(partial)]
    seconds = int(os.getenv("VIDEO_PREVIEW_TIMEOUT_SECONDS") or rules["timeout_seconds"])
    try:
        subprocess.run(command, capture_output=True, text=True, timeout=seconds, check=True)
    except subprocess.TimeoutExpired as error:
        partial.unlink(missing_ok=True)
        raise _error("timeout", seconds=seconds) from error
    except (subprocess.CalledProcessError, OSError) as error:
        partial.unlink(missing_ok=True)
        detail = (getattr(error, "stderr", "") or str(error)).strip().splitlines()[-1:] or [""]
        raise _error("failed", detail=detail[0][:200]) from error
    os.replace(partial, target)
    return target


def preview_name(name: str) -> str:
    """``canvas_up_x.mp4`` → ``canvas_up_x.preview.mp4``."""
    stem = name.rsplit(".", 1)[0]
    return f"{stem}.preview.mp4"


def preview_if_needed(path: str | os.PathLike[str]) -> Path | None:
    """The playable copy beside ``path`` when the browser cannot play ``path`` itself; None when it can or none could be made."""
    source = Path(path)
    try:
        facts = probe(source)
        if browser_plays(facts, source.suffix):
            return None
        return make_preview(source, source.with_name(preview_name(source.name)), facts)
    except PreviewError as error:
        logger.warning("视频预览转码没有完成，页面上可能播不了，原文件照常可用: %s", error)
        return None

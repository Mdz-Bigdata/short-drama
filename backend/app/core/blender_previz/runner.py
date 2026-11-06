# -*- coding: utf-8 -*-
"""找到本机的 Blender，在后台(无界面)按预演规格渲染。

Blender 的位置：环境变量 ``BLENDER_BIN`` 优先；否则按常见安装位置找(macOS /Applications、Linux PATH、Windows Program Files)。
渲染用 Workbench 引擎，白模 + 材质色 + 阴影，几秒出片；同一时间只跑一个，避免把机器拖死。
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from .spec import BlockingSpec

ADDON_DIR = Path(__file__).resolve().parents[3] / "blender" / "short_drama_previz"
SCENE_SCRIPT = ADDON_DIR / "previz_scene.py"
RENDER_TIMEOUT_S = int(os.getenv("BLENDER_RENDER_TIMEOUT", "600"))
_render_lock = threading.Lock()

_CANDIDATES = (
    "/Applications/Blender.app/Contents/MacOS/Blender",
    os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
    "/usr/bin/blender",
    "/usr/local/bin/blender",
    "/snap/bin/blender",
    "C:/Program Files/Blender Foundation/Blender*/blender.exe",
)


class BlenderUnavailable(RuntimeError):
    """本机没有可用的 Blender。"""


class RenderFailed(RuntimeError):
    """Blender 跑了但没出片；消息里带 Blender 的最后几行输出。"""


@dataclass(frozen=True)
class RenderResult:
    out_dir: Path
    video: Path | None
    stills: list[dict]
    blend: Path
    blender_version: str


def find_blender() -> str | None:
    configured = os.getenv("BLENDER_BIN", "").strip()
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("blender")
    if found:
        return found
    for pattern in _CANDIDATES:
        for path in sorted(glob.glob(pattern), reverse=True):
            if Path(path).is_file():
                return path
    return None


def blender_version(binary: str | None = None) -> str | None:
    binary = binary or find_blender()
    if not binary:
        return None
    try:
        output = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = next((line for line in output.splitlines() if line.startswith("Blender")), "")
    return first.replace("Blender", "").strip() or None


def render(spec: BlockingSpec, out_dir: Path) -> RenderResult:
    """无界面渲染：整段 MP4 + 每个切点的首帧 PNG + .blend 工程。"""
    binary = find_blender()
    if not binary:
        raise BlenderUnavailable("本机没有找到 Blender；请安装 Blender 4.2 以上，或在 .env 里设置 BLENDER_BIN 指向可执行文件")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        handle.write(spec.model_dump_json())
        spec_path = handle.name
    try:
        with _render_lock:
            completed = subprocess.run(
                [binary, "--background", "--factory-startup", "--python", str(SCENE_SCRIPT), "--", spec_path, str(out_dir)],
                capture_output=True, text=True, timeout=RENDER_TIMEOUT_S,
            )
    except subprocess.TimeoutExpired as exc:
        raise RenderFailed(f"Blender 渲染超过 {RENDER_TIMEOUT_S} 秒，已中止") from exc
    finally:
        os.unlink(spec_path)
    manifest_line = next((line for line in completed.stdout.splitlines() if line.startswith("PREVIZ_MANIFEST ")), None)
    if completed.returncode != 0 or manifest_line is None:
        tail = "\n".join((completed.stdout + completed.stderr).strip().splitlines()[-12:])
        raise RenderFailed(f"Blender 渲染失败(退出码 {completed.returncode})：{tail[-1500:]}")
    manifest = json.loads(manifest_line[len("PREVIZ_MANIFEST "):])
    return RenderResult(
        out_dir=out_dir,
        video=Path(manifest["video"]) if manifest.get("video") else None,
        stills=list(manifest.get("stills") or []),
        blend=Path(manifest["blend"]),
        blender_version=str(manifest.get("blender") or ""),
    )


def cut_clip(video: Path, start_frame: int, end_frame: int, fps: int, destination: Path) -> Path:
    """从整段预演里切出一个镜头的片段(按帧号精确切，重新编码保证首帧就是切点帧)。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RenderFailed("没有找到 ffmpeg，无法按镜头切片")
    start = (start_frame - 1) / fps
    frames = end_frame - start_frame + 1
    completed = subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-ss", f"{start:.4f}", "-i", str(video), "-frames:v", str(frames),
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20", str(destination)],
        capture_output=True, text=True, timeout=120,
    )
    if completed.returncode != 0 or not destination.is_file():
        raise RenderFailed(f"切镜头片段失败：{completed.stderr.strip()[-400:]}")
    return destination


def addon_zip(destination: Path) -> Path:
    """把实时桥接插件打成 Blender 可直接安装的 zip(顶层目录 short_drama_previz/)。"""
    import zipfile

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ADDON_DIR.glob("*.py")):
            archive.write(path, f"short_drama_previz/{path.name}")
    return destination

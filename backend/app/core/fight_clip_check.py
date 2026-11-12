# -*- coding: utf-8 -*-
"""打戏片段出来后看一眼：动作停没停住、是不是整段慢放、招有没有打到、人有没有糊在一起。

两步，先不花钱再花钱：
1. 均匀抽几帧，比相邻两帧差多少。整段几乎不变 = 人站住了(「站桩」)，直接判不合格，不问模型。
2. 抽出来的帧按时间排成一张联系表，交给看得见图的文本模型按打戏的几条毛病逐条判。

不合格时由调用方带着问题重出一次。没有 ffmpeg、没有看图模型、读不到片子时不拦，记成没检查。
判据和措辞在 app/data/prompt/fight_scene.json。
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageStat

from app.core import media_compositor, prompt_data

_WORDING = "fight_scene"
_CELL = 384


def sample_frames(video: str, count: int | None = None) -> list[Image.Image]:
    """从片子里均匀抽 ``count`` 帧(RGB)；抽不出来返回空。"""
    count = count or prompt_data.number(_WORDING, "clip_check_frames")
    ff = media_compositor._ffmpeg()
    source = media_compositor.local_media_path(video) or video
    if not ff or not source:
        return []
    with tempfile.TemporaryDirectory() as work:
        if str(source).startswith("http"):
            local = os.path.join(work, "clip.mp4")
            if not media_compositor._download(str(source), local):
                return []
            source = local
        duration = media_compositor._probe_duration(str(source)) or 0
        if duration <= 0:
            return []
        frames = []
        for index in range(count):
            at = duration * (index + 0.5) / count
            target = os.path.join(work, f"f{index}.jpg")
            try:
                subprocess.run(
                    [ff, "-y", "-ss", f"{at:.3f}", "-i", str(source), "-frames:v", "1", "-q:v", "3", target],
                    check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                with Image.open(target) as opened:
                    frames.append(opened.convert("RGB"))
            except (OSError, subprocess.SubprocessError):
                continue
        return frames if len(frames) >= 2 else []


def motion_level(frames: list[Image.Image]) -> float:
    """相邻帧的平均差(0–255)：越小越像站住不动。"""
    small = [frame.convert("L").resize((96, 96)) for frame in frames]
    diffs = [ImageStat.Stat(ImageChops.difference(a, b)).mean[0] for a, b in zip(small, small[1:])]
    return sum(diffs) / len(diffs) if diffs else 0.0


def contact_sheet(frames: list[Image.Image]) -> str:
    """按时间顺序排成一张联系表(每格左上角标第几帧)，JPEG data URI。"""
    columns = 3
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * _CELL, rows * _CELL), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        cell = frame.copy()
        cell.thumbnail((_CELL - 8, _CELL - 8))
        x, y = (index % columns) * _CELL, (index // columns) * _CELL
        sheet.paste(cell, (x + (_CELL - cell.width) // 2, y + (_CELL - cell.height) // 2))
        draw.rectangle((x + 4, y + 4, x + 34, y + 26), fill=(0, 0, 0))
        draw.text((x + 10, y + 8), str(index + 1), fill=(255, 255, 255))
    buffer = io.BytesIO()
    sheet.save(buffer, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def parse(answer: str | None) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", str(answer or ""), re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data.get("passed"), bool):
        return None
    problems = [str(item).strip().rstrip("。；;.") for item in data.get("problems") or [] if str(item).strip()][:5]
    passed = data["passed"] and not problems
    return {"passed": passed, "problems": [] if passed else problems or [prompt_data.text(_WORDING, "clip_check_unclear")]}


def check(
    video: str, action: str, describe: Callable[[str, str, str], tuple[str | None, str]],
) -> dict[str, Any] | None:
    """一条打戏片段的结论 ``{passed, problems, motion, model}``；抽不出帧或模型没答就返回 None(不拦)。"""
    frames = sample_frames(video)
    if not frames:
        return None
    motion = round(motion_level(frames), 2)
    if motion < float(prompt_data.value(_WORDING, "clip_still_level")):
        # 整段几乎不动：不必再问模型，就是站住了。
        return {"passed": False, "problems": [prompt_data.text(_WORDING, "clip_still_problem")], "motion": motion, "model": ""}
    answer, used = describe(
        prompt_data.text(_WORDING, "clip_check_system"),
        prompt_data.text(_WORDING, "clip_check_prompt").format(len(frames), str(action or "").strip()[:600]),
        contact_sheet(frames),
    )
    if not used:
        return None
    result = parse(answer)
    return {**result, "motion": motion, "model": used} if result else None


def fix_prompt(problems: list[str]) -> str:
    return prompt_data.text(_WORDING, "clip_fix_lead") + "；".join(problems)


__all__ = ["check", "contact_sheet", "fix_prompt", "motion_level", "parse", "sample_frames"]

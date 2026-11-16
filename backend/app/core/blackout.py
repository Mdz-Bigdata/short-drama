# -*- coding: utf-8 -*-
"""分镜里写的「一帧黑」由剪辑来做，不交给视频模型。

「刀身砸上去，接触瞬间画面骤黑一帧」这种写法，视频模型画不出一帧：它会画成将近一秒的黑屏，
成片验收当硬伤拦下。所以发给视频模型的提示词里去掉这一句(:func:`for_video`)，黑的那一下在合成成片时
盖上去(:func:`plan`)：在片段自己的声音里找最突然的一下(撞击声)，从那一刻起盖几帧黑，声音不动。
找不到明显的那一下就不加，原因记在片段上。措辞、词表和阈值在 ``app/data/prompt/blackout.json``。
"""

from __future__ import annotations

import array
import re
import subprocess
from typing import Any

from app.core import prompt_data

_DATA = "blackout"
SAMPLE_RATE = 8000


def asked(text: Any) -> bool:
    """这段分镜文字要不要一帧黑。"""
    text = str(text or "")
    return any(word in text for word in prompt_data.words(_DATA, "flash_words"))


def for_video(text: str) -> str:
    """发给视频模型的写法：去掉要一帧黑的那句，「再亮时」换成接着往下演的说法。没写一帧黑的原样返回。"""
    text = str(text or "")
    if not asked(text):
        return text
    words = prompt_data.words(_DATA, "flash_words")
    kept = [
        sentence for sentence in re.split(prompt_data.text(_DATA, "sentence_split"), text)
        if not any(word in sentence for word in words)
    ]
    text = "".join(kept)
    for word in sorted(prompt_data.words(_DATA, "resume_words"), key=len, reverse=True):
        text = text.replace(word, prompt_data.text(_DATA, "resume_as"))
    return text


def onset(samples: array.array, rate: int = SAMPLE_RATE) -> float | None:
    """声音里最响的那一下是从第几秒开始的：先找所有突然变响的起点(比它前面一小段的平均响度高出 onset_ratio 倍)，
    再取起点之后一小段最响的那一个(撞击声通常是整段里最响的一下，台词起头没那么冲)。开头结尾各让出一点。"""
    window = max(1, rate * int(prompt_data.number(_DATA, "window_ms")) // 1000)
    before = max(1, int(prompt_data.number(_DATA, "onset_window_ms")) // int(prompt_data.number(_DATA, "window_ms")))
    ratio = float(prompt_data.value(_DATA, "onset_ratio"))
    edge = float(prompt_data.value(_DATA, "skip_edges_seconds"))
    levels = []
    for start in range(0, len(samples) - window + 1, window):
        chunk = samples[start:start + window]
        levels.append((sum(value * value for value in chunk) / window) ** 0.5)
    total = len(samples) / rate
    best, best_level = None, 0.0
    rising = False
    for index in range(before, len(levels)):
        floor = max(sum(levels[index - before:index]) / before, 1.0)
        onset_here = levels[index] / floor >= ratio
        if onset_here and not rising:
            at = index * window / rate
            loudest = max(levels[index:index + before])
            if edge <= at <= total - edge and loudest > best_level:
                best, best_level = at, loudest
        rising = onset_here
    return best


def onset_in_file(path: str, ffmpeg: str = "ffmpeg") -> float | None:
    """片段文件声音里最突然的一下；没有声音、读不出来都是 None。"""
    try:
        raw = subprocess.run(
            [ffmpeg, "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
            check=True, timeout=60, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    return onset(samples) if samples else None


def plan(text: Any, path: str | None, ffmpeg: str = "ffmpeg") -> dict[str, Any] | None:
    """这段片子要不要盖一下黑、盖在第几秒：``{at, frames}``；分镜没要就是 None，找不到那一下时 ``at`` 为 None 并写明原因。"""
    if not asked(text):
        return None
    at = onset_in_file(path, ffmpeg) if path else None
    frames = int(prompt_data.number(_DATA, "frames"))
    if at is None:
        return {"at": None, "frames": frames, "reason": prompt_data.text(_DATA, "not_found")}
    return {"at": round(at, 3), "frames": frames, "source": "sound_onset"}


def window(mark: Any, *, trim_start: float = 0.0, fps: float = 30.0) -> tuple[float, float] | None:
    """合成时在修剪后的片段上从第几秒黑到第几秒；没有可用的时间、或那一刻被剪掉了就是 None。"""
    if not isinstance(mark, dict) or mark.get("at") is None:
        return None
    start = float(mark["at"]) - float(trim_start or 0.0)
    if start < 0:
        return None
    return round(start, 3), round(start + max(1, int(mark.get("frames") or 1)) / float(fps or 30.0), 3)


__all__ = ["asked", "for_video", "onset", "onset_in_file", "plan", "window"]

# -*- coding: utf-8 -*-
"""一场戏写了多长：拆解的 duration，没有就取正文里的「时长：6秒」。

第 4 步拿它定格数和每格秒数。拆解常把 duration 留空、时长只写在正文里；读不到时长，分镜就按模型宜用的
下限(Seedance 2.5 是 10 秒)一格格往上堆，2 分钟的剧本被拉成 9 分钟。写法在 app/data/prompt/scene_seconds.json。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from app.core import prompt_data

_DATA = "scene_seconds"


@lru_cache(maxsize=1)
def _pattern() -> re.Pattern[str]:
    return re.compile(prompt_data.text(_DATA, "pattern"))


def scene_duration(scene: Mapping[str, Any]) -> str:
    """这一场的时长写法(「6秒」)：拆解写了就用它，没写就从正文里取；都没有是空串。"""
    written = str(scene.get("duration") or "").strip()
    if written:
        return written
    match = _pattern().search(str(scene.get("content") or ""))
    if not match:
        return ""
    seconds = float(match.group(1))
    return prompt_data.text(_DATA, "unit").format(int(seconds) if seconds.is_integer() else seconds)


def clip_floor(preferred_floor: int, scene_seconds: int, renderable_floor: int) -> int:
    """每格最短几秒：模型宜用的下限，但不比这场本身长(场短就按场长出)，也不低于模型能出的最短。"""
    if scene_seconds <= 0:
        return preferred_floor
    return max(renderable_floor, min(preferred_floor, scene_seconds))


__all__ = ["clip_floor", "scene_duration"]

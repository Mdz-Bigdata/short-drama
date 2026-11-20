# -*- coding: utf-8 -*-
"""预算上限与每镜尝试上限：写下来，就不会在深夜连着点二十次生成。

项目设置里两项(``config["video_budget_cap"]`` 元、``config["video_max_attempts"]`` 次)。第 5 阶段每提交一次
视频前：本轮已提交的估价 + 这一次的估价超过上限就不提交；这一镜试过的次数(跨轮累计，记在片段上)
到了上限也不提交。两种都抛 :class:`LimitReached`，原因写清楚停在哪、怎么办。措辞在
data/prompt/spend_limits.json。
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from app.core import prompt_data, usage_ledger

_DATA = "spend_limits"


class LimitReached(RuntimeError):
    """到了预算上限或这一镜的尝试上限：这一次没有提交。"""


def _says(key: str, **values: Any) -> str:
    return str(prompt_data.value(_DATA, "says")[key]).format(**values)


def budget_cap(config: Mapping[str, Any]) -> float | None:
    try:
        value = float(config.get("video_budget_cap") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def max_attempts(config: Mapping[str, Any]) -> int | None:
    try:
        value = int(config.get("video_max_attempts") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def validate(budget: float | None, attempts: int | None) -> tuple[float | None, int | None]:
    """设置界面填进来的两项：留空(None / 0)是不限；不合法的抛 ValueError(给人看的话)。"""
    if budget is not None and budget != 0 and budget < 0:
        raise ValueError(_says("bad_cap"))
    if attempts is not None and attempts != 0 and not 1 <= attempts <= prompt_data.number(_DATA, "max_attempts_ceiling"):
        raise ValueError(_says("bad_attempts"))
    return (budget or None), (attempts or None)


def estimate_cny(model: str, seconds: float, resolution: str | None = None) -> float:
    """这一次视频请求大约多少元；价目表里没有就是 0。"""
    units: dict[str, Any] = {"seconds": int(seconds or 0)}
    if resolution:
        units["resolution"] = resolution
    quote = usage_ledger.estimate(model, "video", units)
    if not quote.get("priced"):
        return 0.0
    amount = float(quote.get("cost") or 0.0)
    return amount * float(prompt_data.value(_DATA, "usd_to_cny")) if str(quote.get("currency") or "").upper() == "USD" else amount


class RunGuard:
    """一轮第 5 阶段的两道闸：并发提交时一起记账，线程安全。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.cap = budget_cap(config)
        self.attempt_cap = max_attempts(config)
        self.model = str(config.get("video_model") or "")
        self.spent = 0.0
        self.attempts: dict[int, int] = {}
        self._lock = threading.Lock()

    def admit(self, shot_uid: int, *, earlier_attempts: int, seconds: float, resolution: str | None, label: str) -> None:
        """这一次能不能提交；能就把估价和次数记上，不能就抛 :class:`LimitReached`。"""
        with self._lock:
            tried = int(earlier_attempts or 0) + self.attempts.get(shot_uid, 0)
            if self.attempt_cap is not None and tried >= self.attempt_cap:
                raise LimitReached(_says("attempts", label=label, count=tried, cap=self.attempt_cap))
            cost = estimate_cny(self.model, seconds, resolution)
            if self.cap is not None and self.spent + cost > self.cap:
                raise LimitReached(_says("budget", cap=f"{self.cap:g}", spent=f"{self.spent:.2f}", label=label, cost=f"{cost:.2f}"))
            self.spent += cost
            self.attempts[shot_uid] = self.attempts.get(shot_uid, 0) + 1

    def tried(self, shot_uid: int, earlier_attempts: int = 0) -> int:
        """这一镜到现在一共试了几次(之前各轮 + 这一轮)。"""
        with self._lock:
            return int(earlier_attempts or 0) + self.attempts.get(shot_uid, 0)


__all__ = ["LimitReached", "RunGuard", "budget_cap", "estimate_cny", "max_attempts", "validate"]

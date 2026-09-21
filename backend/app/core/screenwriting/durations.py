# -*- coding: utf-8 -*-
"""Shot-duration and episode-volume constraints for the screenwriting pipeline.

Every shot the Writer plans must be renderable by the selected video model in a
single generation call, so the set of legal shot durations is derived from the
project's video model (``app.core.video_references``) rather than guessed by the
LLM. The episode target duration is a *soft* target: it tells the planner how
many shots to cut, never forces padding or trimming.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.core.screenwriting.speech_rate import speech_rate_units_per_second
from app.core.screenwriting.text_metrics import reading_unit_noun
from app.core.video_references import MIN_SHOT_SECONDS, max_shot_seconds

# 单集成片目标时长的硬区间（秒）：只拦明显误输入，区间内取值是创作决策。
MIN_EPISODE_TARGET_SECONDS = 10
MAX_EPISODE_TARGET_SECONDS = 600
# 本项目短剧单集的默认目标体量（与八 Agent 委员会的 episode_duration_seconds 同口径）。
DEFAULT_EPISODE_TARGET_SECONDS = 90


def supported_shot_durations(video_model: str) -> list[int]:
    """Every whole-second clip length the video model can render in one call."""
    cap = max(MIN_SHOT_SECONDS, max_shot_seconds(video_model))
    return list(range(MIN_SHOT_SECONDS, cap + 1))


def format_duration_constraint(supported_durations: list[int], default_duration: int | None) -> str:
    """Render the legal duration set for a prompt; contiguous runs read as a range."""
    if not supported_durations:
        raise ValueError("supported_durations 不能为空：调用方必须提供模型支持的秒数集合")
    ordered = sorted({int(value) for value in supported_durations})
    contiguous = len(ordered) >= 5 and all(ordered[i] == ordered[i - 1] + 1 for i in range(1, len(ordered)))
    body = (
        f"{ordered[0]} 到 {ordered[-1]} 秒之间的整数任选"
        if contiguous
        else "从 [" + ", ".join(str(value) for value in ordered) + "] 秒中选择"
    )
    if default_duration is not None:
        if default_duration not in ordered:
            raise ValueError(f"default_duration={default_duration} 不在 supported_durations={ordered} 内")
        return f"时长：{body}，默认 {default_duration} 秒"
    return f"时长：{body}，按内容节奏自行决定"


def is_valid_episode_target_seconds(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return MIN_EPISODE_TARGET_SECONDS <= value <= MAX_EPISODE_TARGET_SECONDS


def resolve_episode_target_seconds(config: Mapping[str, Any] | None) -> int | None:
    """Read the project's per-episode target from its config; invalid values fall back to the default."""
    raw = config.get("episode_target_duration") if isinstance(config, Mapping) else None
    if raw is None:
        return DEFAULT_EPISODE_TARGET_SECONDS
    if isinstance(raw, str) and raw.strip().isdigit():
        raw = int(raw.strip())
    return raw if is_valid_episode_target_seconds(raw) else DEFAULT_EPISODE_TARGET_SECONDS


def render_episode_target_rule(target_seconds: int | None) -> str:
    """The soft-target sentence shared by every planning prompt; empty when unset."""
    if target_seconds is None:
        return ""
    return (
        f"本集成片目标时长约 {target_seconds} 秒：据此决定本集拆多少个分镜、拆多细，"
        "让各分镜时长合计向该目标靠拢。这是软目标、不是硬上限——"
        "内容不足以支撑目标时宁可少拆几个，不要靠注水或切碎凑满；"
        "内容确实需要更多篇幅时可以超出目标，不要为压进目标删掉必要情节"
    )


@dataclass(frozen=True)
class EpisodeTargetVolume:
    """How much source text one episode should consume, and where that number came from."""

    units: int
    unit_noun: str
    source: Literal["units", "duration", "episode_count"]
    seconds: int | None = None
    units_per_second: float | None = None


def resolve_episode_target_volume(
    *,
    language: str | None,
    explicit_units: int | None = None,
    target_seconds: int | None = None,
    speech_rate_override: float | None = None,
    total_units: int | None = None,
    episode_count: int | None = None,
) -> EpisodeTargetVolume | None:
    """Explicit units win; then a fixed episode count over the source; then the duration conversion."""
    noun = reading_unit_noun(language)
    if isinstance(explicit_units, int) and not isinstance(explicit_units, bool) and explicit_units >= 1:
        return EpisodeTargetVolume(units=explicit_units, unit_noun=noun, source="units")
    if total_units and episode_count and episode_count >= 1:
        return EpisodeTargetVolume(units=max(1, round(total_units / episode_count)), unit_noun=noun, source="episode_count")
    if target_seconds is None:
        return None
    rate = speech_rate_units_per_second(language, speech_rate_override)
    return EpisodeTargetVolume(
        units=max(1, round(target_seconds * rate)),
        unit_noun=noun,
        source="duration",
        seconds=target_seconds,
        units_per_second=rate,
    )


__all__ = [
    "DEFAULT_EPISODE_TARGET_SECONDS",
    "MIN_EPISODE_TARGET_SECONDS",
    "MAX_EPISODE_TARGET_SECONDS",
    "EpisodeTargetVolume",
    "format_duration_constraint",
    "is_valid_episode_target_seconds",
    "render_episode_target_rule",
    "resolve_episode_target_seconds",
    "resolve_episode_target_volume",
    "supported_shot_durations",
]

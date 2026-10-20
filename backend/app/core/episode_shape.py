"""What one episode must be at the least.

An episode is more than one shot and at least a minute of film; beyond six
minutes it is still accepted, with a notice. The screenwriting engine checks a
drafted episode against this and sends a short one back to the model, the
planning prompts state it up front, and the writer dashboard flags any stored
episode that falls outside it. The rule lives here, apart from the screenwriting
package, so the dashboard can read it without importing the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app import settings


# 一集的最小成形标准：至少两个分镜、合计不少于一分钟；超过六分钟只提醒，不拦截。
MIN_EPISODE_SCENES = 2
MIN_EPISODE_SECONDS = 60
MAX_RECOMMENDED_EPISODE_SECONDS = 360

ShapeSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class EpisodeShapeIssue:
    code: str
    message: str
    severity: ShapeSeverity


@dataclass(frozen=True)
class EpisodeShape:
    """What one episode must be at the least, and how long it should be at the most."""

    min_scenes: int = MIN_EPISODE_SCENES
    min_seconds: int = MIN_EPISODE_SECONDS
    max_seconds: int = MAX_RECOMMENDED_EPISODE_SECONDS

    def issues(self, scene_count: int, total_seconds: int) -> list[EpisodeShapeIssue]:
        """Problems with an episode of this many shots and this total length; empty when it is well formed."""
        found: list[EpisodeShapeIssue] = []
        if scene_count < self.min_scenes:
            found.append(EpisodeShapeIssue(
                "episode_too_few_scenes",
                f"本集只有 {scene_count} 个分镜，至少需要 {self.min_scenes} 个：把这一集的情节拆成多个分镜",
                "error",
            ))
        if total_seconds < self.min_seconds:
            found.append(EpisodeShapeIssue(
                "episode_too_short",
                f"本集各分镜时长合计 {total_seconds} 秒，不能少于 {self.min_seconds} 秒："
                "补足情节与分镜，或把现有分镜取更长的时长档位",
                "error",
            ))
        elif total_seconds > self.max_seconds:
            found.append(EpisodeShapeIssue(
                "episode_over_recommended",
                f"本集各分镜时长合计 {total_seconds} 秒，超过建议上限 {self.max_seconds} 秒",
                "warning",
            ))
        return found

    def rule(self) -> str:
        """The sentence every planning prompt carries, so the model knows the frame before it is checked."""
        return (
            f"单集成形的硬性要求：本集至少 {self.min_scenes} 个分镜，各分镜时长合计不少于 {self.min_seconds} 秒"
            f"（建议控制在 {self.min_seconds}–{self.max_seconds} 秒之间）；不满足会被退回重写"
        )


def configured_episode_shape() -> EpisodeShape:
    """The deployment's episode frame: the defaults, unless SCREENWRITING_EPISODE_* override them."""
    min_seconds = settings.env_int("SCREENWRITING_EPISODE_MIN_SECONDS", MIN_EPISODE_SECONDS, minimum=1)
    return EpisodeShape(
        min_scenes=settings.env_int("SCREENWRITING_EPISODE_MIN_SCENES", MIN_EPISODE_SCENES, minimum=1),
        min_seconds=min_seconds,
        max_seconds=settings.env_int("SCREENWRITING_EPISODE_MAX_SECONDS", MAX_RECOMMENDED_EPISODE_SECONDS, minimum=min_seconds),
    )

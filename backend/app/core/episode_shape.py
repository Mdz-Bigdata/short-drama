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
from app.core import prompt_data


_WORDING_FILE = "episode_shape"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/episode_shape.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


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
                _text_of("issues.text").format(scene_count, self.min_scenes),
                "error",
            ))
        if total_seconds < self.min_seconds:
            found.append(EpisodeShapeIssue(
                "episode_too_short",
                _text_of("issues.text.2").format(total_seconds, self.min_seconds),
                "error",
            ))
        elif total_seconds > self.max_seconds:
            found.append(EpisodeShapeIssue(
                "episode_over_recommended",
                _text_of("issues.text.3").format(total_seconds, self.max_seconds),
                "warning",
            ))
        return found

    def rule(self) -> str:
        """The sentence every planning prompt carries, so the model knows the frame before it is checked."""
        return (
            _text_of("rule.text").format(self.min_scenes, self.min_seconds, self.min_seconds, self.max_seconds)
        )


def configured_episode_shape() -> EpisodeShape:
    """The deployment's episode frame: the defaults, unless SCREENWRITING_EPISODE_* override them."""
    min_seconds = settings.env_int("SCREENWRITING_EPISODE_MIN_SECONDS", MIN_EPISODE_SECONDS, minimum=1)
    return EpisodeShape(
        min_scenes=settings.env_int("SCREENWRITING_EPISODE_MIN_SCENES", MIN_EPISODE_SCENES, minimum=1),
        min_seconds=min_seconds,
        max_seconds=settings.env_int("SCREENWRITING_EPISODE_MAX_SECONDS", MAX_RECOMMENDED_EPISODE_SECONDS, minimum=min_seconds),
    )

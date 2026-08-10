"""Continuity scoring and transition planning between adjacent generated clips."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ContinuityState(BaseModel):
    characters: list[str]
    scene: str
    screen_direction: Literal["left_to_right", "right_to_left", "neutral", "unknown"]
    action: str
    emotion: str
    props: dict[str, str]
    lighting: str
    audio_bed: str


class TransitionPlan(BaseModel):
    accepted: bool
    score: float = Field(ge=0, le=1)
    video_transition: Literal[
        "hard_cut", "match_cut", "crossfade", "dip_to_black", "neutral_bridge"
    ]
    audio_transition: Literal["hard_cut", "j_cut", "l_cut", "crossfade"]
    duration_seconds: float = Field(ge=0, le=2)
    reasons: list[str]


def _is_handoff(previous: ContinuityState, current: ContinuityState) -> bool:
    common_props = set(previous.props).intersection(current.props)
    return any(previous.props[name] != current.props[name] for name in common_props)


def plan_transition(previous: ContinuityState, current: ContinuityState) -> TransitionPlan:
    reasons: list[str] = []
    score = 1.0

    axis_flip = (
        previous.scene == current.scene
        and previous.screen_direction in {"left_to_right", "right_to_left"}
        and current.screen_direction in {"left_to_right", "right_to_left"}
        and previous.screen_direction != current.screen_direction
    )
    if axis_flip:
        score -= 0.55
        reasons.append("检测到180度轴线翻转，需要中性机位桥接后才能合成。")

    if previous.scene != current.scene:
        score -= 0.12
        reasons.append("场景变化，采用声画错位引导新空间。")
        return TransitionPlan(
            accepted=not axis_flip,
            score=max(score, 0),
            video_transition="crossfade",
            audio_transition="j_cut",
            duration_seconds=0.45,
            reasons=reasons,
        )

    if previous.lighting != current.lighting:
        score -= 0.12
        reasons.append("相邻镜头光向或色温不一致。")
    if previous.audio_bed != current.audio_bed:
        score -= 0.08
        reasons.append("环境声底发生变化，需音频交叉淡化。")

    if axis_flip:
        return TransitionPlan(
            accepted=False,
            score=max(score, 0),
            video_transition="neutral_bridge",
            audio_transition="crossfade",
            duration_seconds=0.5,
            reasons=reasons,
        )

    if _is_handoff(previous, current):
        reasons.append("关键道具发生连续交接，使用动作匹配剪辑。")
        return TransitionPlan(
            accepted=score >= 0.72,
            score=max(score, 0),
            video_transition="match_cut",
            audio_transition="l_cut",
            duration_seconds=0.25,
            reasons=reasons,
        )

    return TransitionPlan(
        accepted=score >= 0.72,
        score=max(score, 0),
        video_transition="hard_cut" if score >= 0.88 else "crossfade",
        audio_transition="l_cut" if previous.audio_bed == current.audio_bed else "crossfade",
        duration_seconds=0.0 if score >= 0.88 else 0.3,
        reasons=reasons or ["六项连续性锚点可接受。"],
    )

"""Fail-closed acceptance gate for multimodal or human video measurements."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from app.core import prompt_data


_WORDING_FILE = "video_quality"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/video_quality.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


DimensionName = Literal[
    "identity_consistency",
    "anatomy_integrity",
    "expression_fidelity",
    "photorealism",
    "temporal_continuity",
    "dialogue_emotion_timing",
    "lip_sync",
    "hard_defects",
]


class VideoQualityMeasurements(BaseModel):
    """Scores must come from a real multimodal assessor or signed human review."""

    identity_consistency: float = Field(ge=0, le=1)
    anatomy_integrity: float = Field(ge=0, le=1)
    expression_fidelity: float = Field(ge=0, le=1)
    photorealism: float = Field(ge=0, le=1)
    temporal_continuity: float = Field(ge=0, le=1)
    dialogue_emotion_timing: float = Field(ge=0, le=1)
    lip_sync: float = Field(ge=0, le=1)
    hard_defects: list[str] = Field(default_factory=list, max_length=50)
    assessor: str = Field(default="multimodal_qa", min_length=2, max_length=120)
    evidence_urls: list[str] = Field(default_factory=list, max_length=30)


class VideoQualityReport(BaseModel):
    passed: bool
    overall_score: float = Field(ge=0, le=1)
    failed_dimensions: list[DimensionName]
    retry_actions: list[str]
    thresholds: dict[str, float]
    assessor: str
    evidence_urls: list[str]


_THRESHOLDS = {
    "identity_consistency": 0.90,
    "anatomy_integrity": 0.88,
    "expression_fidelity": 0.82,
    "photorealism": 0.85,
    "temporal_continuity": 0.86,
    "dialogue_emotion_timing": 0.80,
    "lip_sync": 0.80,
}

_ACTIONS = {
    "identity_consistency": _text_of("module.actions.identity_consistency"),
    "anatomy_integrity": _text_of("module.actions.anatomy_integrity"),
    "expression_fidelity": _text_of("module.actions.expression_fidelity"),
    "photorealism": _text_of("module.actions.photorealism"),
    "temporal_continuity": _text_of("module.actions.temporal_continuity"),
    "dialogue_emotion_timing": _text_of("module.actions.dialogue_emotion_timing"),
    "lip_sync": _text_of("module.actions.lip_sync"),
    "hard_defects": _text_of("module.actions.hard_defects"),
}


def evaluate_video_quality(measurements: VideoQualityMeasurements) -> VideoQualityReport:
    values = {
        key: float(getattr(measurements, key))
        for key in _THRESHOLDS
    }
    failed: list[DimensionName] = [
        key for key, threshold in _THRESHOLDS.items()
        if values[key] < threshold
    ]  # type: ignore[list-item]
    if measurements.hard_defects:
        failed.append("hard_defects")
    # Identity, anatomy and continuity receive extra weight because a high
    # average must never hide a broken face/body/cut.
    weights = {
        "identity_consistency": 1.4,
        "anatomy_integrity": 1.3,
        "expression_fidelity": 1.0,
        "photorealism": 1.0,
        "temporal_continuity": 1.3,
        "dialogue_emotion_timing": 1.0,
        "lip_sync": 1.0,
    }
    numerator = sum(values[key] * weights[key] for key in values)
    denominator = sum(weights.values())
    score = round(numerator / denominator, 4)
    return VideoQualityReport(
        passed=not failed,
        overall_score=score,
        failed_dimensions=failed,
        retry_actions=[_ACTIONS[key] for key in failed],
        thresholds=dict(_THRESHOLDS),
        assessor=measurements.assessor,
        evidence_urls=measurements.evidence_urls,
    )


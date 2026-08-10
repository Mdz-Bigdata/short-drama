"""Fail-closed acceptance gate for multimodal or human video measurements."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    "identity_consistency": "重新绑定角色五视图与身份 DNA，减少同镜角色数，并用上一镜验收尾帧作为首帧重生成。",
    "anatomy_integrity": "缩短镜头并拆分复杂手部/身体动作，增加遮挡或中景构图，针对畸形区段局部重生成。",
    "expression_fidelity": "按动机→视线→呼吸→面部肌群→肢体顺序重写微表情节拍，降低夸张幅度后重生成。",
    "photorealism": "锁定自然皮肤纹理、物理可信光线与真实镜头缺陷，移除塑料皮肤、CG渲染和过度磨皮描述。",
    "temporal_continuity": "用上一镜尾态重建首帧，校正轴线、视线、动作方向、道具归属、光色和环境动态。",
    "dialogue_emotion_timing": "按情绪弧重做对白：标记重音、语速、停顿、呼吸和反应空拍，再生成多角色对话音轨。",
    "lip_sync": "按语音时长重切镜头和字幕，保留起音/收音反应帧，并对失配区段重新口型驱动。",
    "hard_defects": "检测到硬缺陷；禁止进入合成，定位缺陷帧并执行局部重生成或逐帧修复。",
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


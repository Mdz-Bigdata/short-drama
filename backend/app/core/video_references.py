"""Explainable routing for frame, multi-image and multimodal video inputs."""

from __future__ import annotations

import re
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field


VideoReferenceMode = Literal[
    "auto", "first_last_frame", "multi_reference", "multimodal",
]
ExecutableVideoMode = Literal[
    "text", "first_frame", "first_last_frame", "multi_reference", "multimodal",
]

_USER_VIDEO_REFERENCE_MODES = {
    "auto", "first_last_frame", "multi_reference", "multimodal",
}


def normalize_video_reference_mode(value: str | None) -> VideoReferenceMode:
    """Migrate removed or unknown project choices to capability-aware auto routing."""

    return cast(VideoReferenceMode, value) if value in _USER_VIDEO_REFERENCE_MODES else "auto"


class VideoGenerationIntent(BaseModel):
    """Semantic controls extracted from the shot, independent from file counts."""

    exact_end_frame_required: bool = False
    narrative_image_sequence: bool = False
    identity_consistency_required: bool = True
    motion_reference_required: bool = False
    audio_rhythm_required: bool = False
    multi_shot_output: bool = False


class VideoProviderProfile(BaseModel):
    family: str
    aliases: list[str]
    modes: list[ExecutableVideoMode]
    max_reference_images: int = Field(ge=0, le=99)
    max_reference_videos: int = Field(ge=0, le=99)
    max_reference_audios: int = Field(ge=0, le=99)
    verification_status: Literal[
        "integrated", "adapter_required", "runtime_configuration_required",
        "capability_probe_required",
    ]
    capability_source: str
    notes: list[str] = Field(default_factory=list)


VIDEO_PROVIDER_PROFILES: tuple[VideoProviderProfile, ...] = (
    VideoProviderProfile(
        family="minimax_h3",
        aliases=["minimax-h3", "minimax_h3", "minimax h3", "h3", "hailuo"],
        modes=["text", "first_frame", "first_last_frame", "multi_reference", "multimodal"],
        max_reference_images=9,
        max_reference_videos=3,
        max_reference_audios=3,
        verification_status="integrated",
        capability_source="project MiniMax H3 adapter and request contract",
        notes=["frame anchoring and mixed Ref2VA references are separate request modes"],
    ),
    VideoProviderProfile(
        family="seedance",
        aliases=["seedance2.5", "seedance-2.5", "seedance2.0", "seedance-2.0", "seedance2", "seedance"],
        modes=["text", "first_frame", "first_last_frame", "multi_reference", "multimodal"],
        max_reference_images=9,
        max_reference_videos=3,
        max_reference_audios=3,
        verification_status="integrated",
        capability_source="project Ark-compatible runtime adapter; exact model access is runtime-configured",
        notes=["the configured endpoint remains authoritative for each Seedance version"],
    ),
    VideoProviderProfile(
        family="kling",
        aliases=["kling-o1", "kling o1", "kling3", "kling-3", "kling"],
        modes=["text", "first_frame", "first_last_frame", "multi_reference", "multimodal"],
        max_reference_images=7,
        max_reference_videos=3,
        max_reference_audios=3,
        verification_status="adapter_required",
        capability_source="Kling official Open Platform and Video O1 guides",
        notes=["audio is not advertised as a conditioning input in the reviewed O1 guide"],
    ),
    VideoProviderProfile(
        family="grok",
        aliases=["grok-imagine-video", "grok imagine", "grok", "gork"],
        modes=["text", "first_frame", "multi_reference"],
        max_reference_images=7,
        max_reference_videos=0,
        max_reference_audios=0,
        verification_status="adapter_required",
        capability_source="xAI Imagine official video and reference-to-video documentation",
        notes=["Gork is normalized as a user-facing alias for Grok"],
    ),
    VideoProviderProfile(
        family="happyhorse",
        aliases=["happyhorse-1.1", "happyhorse-1.0", "happy horse", "happyhorse"],
        modes=["text", "first_frame", "first_last_frame", "multi_reference", "multimodal"],
        max_reference_images=9,
        max_reference_videos=3,
        max_reference_audios=3,
        verification_status="adapter_required",
        capability_source="HappyHorse public model documentation; endpoint contract must be configured",
        notes=["public HappyHorse endpoints differ, so capability probing is required before submission"],
    ),
    VideoProviderProfile(
        family="ltx_2_3",
        aliases=["ltx-2.3", "ltx2.3", "ltx-2-3", "ltx_2_3"],
        modes=["text", "first_frame", "first_last_frame", "multi_reference"],
        max_reference_images=9,
        max_reference_videos=0,
        max_reference_audios=1,
        verification_status="adapter_required",
        capability_source="LTX official v2 text/image/audio-to-video documentation",
        notes=["multi-image storyboard routing follows the configured LTX 2.3 runtime capability"],
    ),
)


class VideoReferencePlan(BaseModel):
    mode: ExecutableVideoMode
    provider_family: str = "custom"
    provider_status: str = "capability_probe_required"
    first_frame: str | None = None
    last_frame: str | None = None
    reference_images: list[str] = Field(default_factory=list)
    reference_videos: list[str] = Field(default_factory=list)
    reference_audios: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    fallbacks: list[str] = Field(default_factory=list)
    unused_assets: list[str] = Field(default_factory=list)
    hard_constraints_satisfied: bool = True


class VideoRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_mode: VideoReferenceMode = "auto"
    model: str = "MiniMax-H3"
    first_frame: str | None = None
    last_frame: str | None = None
    sequence_images: list[str] = Field(default_factory=list, max_length=9)
    reference_images: list[str] = Field(default_factory=list, max_length=9)
    reference_videos: list[str] = Field(default_factory=list, max_length=3)
    reference_audios: list[str] = Field(default_factory=list, max_length=3)
    intent: VideoGenerationIntent = Field(default_factory=VideoGenerationIntent)


def _unique(values: list[str] | None, limit: int) -> list[str]:
    return list(dict.fromkeys(value for value in (values or []) if value))[:limit]


def normalize_video_provider(model: str) -> VideoProviderProfile:
    normalized = re.sub(r"[\s_.]+", "-", (model or "").strip().lower())
    for profile in VIDEO_PROVIDER_PROFILES:
        for alias in sorted(profile.aliases, key=len, reverse=True):
            alias_normalized = re.sub(r"[\s_.]+", "-", alias.lower())
            if alias_normalized in normalized:
                return profile
    return VideoProviderProfile(
        family="custom",
        aliases=[normalized or "custom"],
        modes=["text", "first_frame"],
        max_reference_images=1,
        max_reference_videos=0,
        max_reference_audios=0,
        verification_status="capability_probe_required",
        capability_source="unknown runtime model",
        notes=["unknown models fail closed for advanced reference modes until capabilities are configured"],
    )


def _asset_marker(kind: str, count: int) -> str:
    return f"{kind}:{count}"


def plan_video_references(
    requested_mode: VideoReferenceMode,
    *,
    first_frame: str | None,
    last_frame: str | None = None,
    sequence_images: list[str] | None = None,
    reference_images: list[str] | None = None,
    reference_videos: list[str] | None = None,
    reference_audios: list[str] | None = None,
    model: str = "MiniMax-H3",
    intent: VideoGenerationIntent | None = None,
) -> VideoReferencePlan:
    """Choose a mode from shot intent first, then negotiate provider limits."""

    intent = intent or VideoGenerationIntent()
    profile = normalize_video_provider(model)
    sequences = _unique(sequence_images, 9)
    identities = _unique(reference_images, 9)
    videos = _unique(reference_videos, 3)
    audios = _unique(reference_audios, 3)
    visual_refs = _unique(
        [value for value in [first_frame, *sequences, last_frame, *identities] if value],
        profile.max_reference_images,
    )
    reasons: list[str] = []
    fallbacks: list[str] = []
    unused: list[str] = []

    if requested_mode != "auto" and requested_mode not in profile.modes:
        raise ValueError(
            f"{profile.family} does not declare support for requested mode {requested_mode}"
        )

    if requested_mode == "auto":
        candidates: list[tuple[int, ExecutableVideoMode, str]] = []
        if first_frame and last_frame and "first_last_frame" in profile.modes:
            score = 120 if intent.exact_end_frame_required else 84
            candidates.append((score, "first_last_frame", "首帧和尾帧齐全，可精确控制镜头起止画面"))
        elif intent.exact_end_frame_required:
            raise ValueError(
                f"shot requires an exact end frame but {profile.family} cannot execute first_last_frame"
            )

        has_multimodal = bool(videos or audios)
        if has_multimodal and "multimodal" in profile.modes:
            score = 105
            if intent.motion_reference_required:
                score += 20
            if intent.audio_rhythm_required:
                score += 20
            candidates.append((score, "multimodal", "存在视频或音频参考，需要联合锁定动作、运镜或节奏"))
        elif has_multimodal:
            if videos and intent.motion_reference_required:
                raise ValueError(
                    f"shot requires a motion video reference but {profile.family} cannot execute multimodal mode"
                )
            if audios and intent.audio_rhythm_required:
                raise ValueError(
                    f"shot requires an audio rhythm reference but {profile.family} cannot execute multimodal mode"
                )
            fallbacks.append(f"{profile.family} 不支持当前视频/音频参考，转入视觉参考候选")

        multi_image_signal = len(visual_refs) >= 2 and (
            bool(sequences)
            or intent.narrative_image_sequence
            or intent.identity_consistency_required
        )
        if multi_image_signal and "multi_reference" in profile.modes:
            score = 100 if intent.narrative_image_sequence or intent.multi_shot_output else 76
            candidates.append((score, "multi_reference", "存在连续分镜或角色/场景多图，需要多图一致性约束"))

        if "text" in profile.modes:
            candidates.append((5, "text", "没有更强的兼容视觉锚点，使用文本生成"))
        if not candidates:
            raise ValueError(f"no compatible video mode for {profile.family} and the supplied assets")
        _, mode, reason = max(candidates, key=lambda item: (item[0], item[1]))
        reasons.append(reason)
    else:
        mode = requested_mode
        reasons.append(f"使用人工指定模式：{requested_mode}")

    if mode == "first_last_frame":
        if not first_frame or not last_frame:
            raise ValueError("first-last-frame video requires both a first and last frame")
        else:
            if videos:
                unused.append(_asset_marker("reference_videos", len(videos)))
            if audios:
                unused.append(_asset_marker("reference_audios", len(audios)))
            if identities or sequences:
                unused.append(_asset_marker("reference_images", len(identities) + len(sequences)))
            return VideoReferencePlan(
                mode="first_last_frame",
                provider_family=profile.family,
                provider_status=profile.verification_status,
                first_frame=first_frame,
                last_frame=last_frame,
                reasons=reasons,
                fallbacks=fallbacks,
                unused_assets=unused,
            )

    if mode == "first_frame":
        if not first_frame:
            raise ValueError("first-frame video requires a first frame")
        if identities or sequences:
            unused.append(_asset_marker("reference_images", len(identities) + len(sequences)))
        if videos:
            unused.append(_asset_marker("reference_videos", len(videos)))
        if audios:
            unused.append(_asset_marker("reference_audios", len(audios)))
        return VideoReferencePlan(
            mode="first_frame",
            provider_family=profile.family,
            provider_status=profile.verification_status,
            first_frame=first_frame,
            reasons=reasons,
            fallbacks=fallbacks,
            unused_assets=unused,
        )

    if mode == "text":
        if visual_refs:
            unused.append(_asset_marker("reference_images", len(visual_refs)))
        if videos:
            unused.append(_asset_marker("reference_videos", len(videos)))
        if audios:
            unused.append(_asset_marker("reference_audios", len(audios)))
        return VideoReferencePlan(
            mode="text",
            provider_family=profile.family,
            provider_status=profile.verification_status,
            reasons=reasons,
            fallbacks=fallbacks,
            unused_assets=unused,
        )

    if mode == "multi_reference":
        if not visual_refs:
            raise ValueError("multi-reference video requires at least one image")
        if videos:
            unused.append(_asset_marker("reference_videos", len(videos)))
        if audios:
            unused.append(_asset_marker("reference_audios", len(audios)))
        return VideoReferencePlan(
            mode="multi_reference",
            provider_family=profile.family,
            provider_status=profile.verification_status,
            reference_images=visual_refs,
            reasons=reasons,
            fallbacks=fallbacks,
            unused_assets=unused,
        )

    bound_videos = videos[:profile.max_reference_videos]
    bound_audios = audios[:profile.max_reference_audios]
    if videos and intent.motion_reference_required and not bound_videos:
        raise ValueError(f"{profile.family} cannot preserve the required motion video reference")
    if audios and intent.audio_rhythm_required and not bound_audios:
        raise ValueError(f"{profile.family} cannot preserve the required audio rhythm reference")
    if not visual_refs and not bound_videos:
        raise ValueError("multimodal video requires image or video context")
    if bound_audios and not (visual_refs or bound_videos):
        raise ValueError("audio reference cannot be the only multimodal input")
    if len(videos) > len(bound_videos):
        unused.append(_asset_marker("reference_videos_over_limit", len(videos) - len(bound_videos)))
    if len(audios) > len(bound_audios):
        unused.append(_asset_marker("reference_audios_over_limit", len(audios) - len(bound_audios)))
    return VideoReferencePlan(
        mode="multimodal",
        provider_family=profile.family,
        provider_status=profile.verification_status,
        reference_images=visual_refs,
        reference_videos=bound_videos,
        reference_audios=bound_audios,
        reasons=reasons,
        fallbacks=fallbacks,
        unused_assets=unused,
    )


def decide_video_generation(request: VideoRouteRequest) -> VideoReferencePlan:
    return plan_video_references(
        request.requested_mode,
        model=request.model,
        first_frame=request.first_frame,
        last_frame=request.last_frame,
        sequence_images=request.sequence_images,
        reference_images=request.reference_images,
        reference_videos=request.reference_videos,
        reference_audios=request.reference_audios,
        intent=request.intent,
    )

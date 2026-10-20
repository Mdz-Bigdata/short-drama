"""Explainable routing for frame, multi-image and multimodal video inputs."""

from __future__ import annotations

import re
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from app.core.reference_limits import MAX_REFERENCE_AUDIOS, MAX_REFERENCE_IMAGES, MAX_REFERENCE_VIDEOS, MAX_SEQUENCE_IMAGES


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
        verification_status="runtime_configuration_required",
        capability_source="Kling official Open Platform and Video O1 guides; project adapter for text/image2video, image_tail and multi-image2video",
        notes=[
            "audio is not advertised as a conditioning input in the reviewed O1 guide",
            "the adapter executes text, first-frame, first+last-frame and multi-image modes; Video O1 multimodal references fail closed until their fields are verified",
        ],
    ),
    VideoProviderProfile(
        family="grok",
        aliases=["grok-imagine-video", "grok imagine", "grok", "gork"],
        modes=["text", "first_frame", "first_last_frame", "multi_reference"],
        max_reference_images=3,
        max_reference_videos=0,
        max_reference_audios=0,
        verification_status="runtime_configuration_required",
        capability_source="xAI docs: POST /v1/videos/generations with image, last_frame and up to 3 reference_images",
        notes=[
            "Gork is normalized as a user-facing alias for Grok",
            "reference_audios are xAI voice ids, not uploaded audio, so audio references stay unsupported",
        ],
    ),
    VideoProviderProfile(
        family="happyhorse",
        aliases=["happyhorse-1.1", "happyhorse-1.0", "happy horse", "happyhorse"],
        modes=["text", "first_frame", "multi_reference"],
        max_reference_images=9,
        max_reference_videos=0,
        max_reference_audios=0,
        verification_status="runtime_configuration_required",
        capability_source="fal.ai official-partner endpoints alibaba/happy-horse/v1.1 text-/image-/reference-to-video (1-9 image_urls)",
        notes=["no documented last-frame, video or audio conditioning input on the fal.ai endpoints"],
    ),
    VideoProviderProfile(
        family="ltx_2_3",
        aliases=["ltx-2.3", "ltx2.3", "ltx-2-3", "ltx_2_3", "ltx-2-3-pro", "ltx-2-3-fast"],
        modes=["text", "first_frame", "first_last_frame"],
        max_reference_images=2,
        max_reference_videos=0,
        max_reference_audios=0,
        verification_status="runtime_configuration_required",
        capability_source="LTX OpenAPI: /v2/image-to-video takes image_uri plus optional last_frame_uri; no multi-image input",
        notes=["audio-to-video exists for ltx-2-3-pro but is not wired as a reference mode"],
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
    sequence_images: list[str] = Field(default_factory=list, max_length=MAX_SEQUENCE_IMAGES)
    reference_images: list[str] = Field(default_factory=list, max_length=MAX_REFERENCE_IMAGES)
    reference_videos: list[str] = Field(default_factory=list, max_length=MAX_REFERENCE_VIDEOS)
    reference_audios: list[str] = Field(default_factory=list, max_length=MAX_REFERENCE_AUDIOS)
    intent: VideoGenerationIntent = Field(default_factory=VideoGenerationIntent)


# 每个分镜都必须能被所选视频模型**一次**生成出来，所以镜头时长上限由模型决定。
# 这张表按「版本」而不是按「族」解析：seedance2.0 与 seedance2.5 同属 seedance 族，
# 单次生成上限却是 15s 与 30s，VIDEO_PROVIDER_PROFILES 的族粒度区分不了它们。
# 未登记的模型走保守默认值——切得偏碎只是多几个镜头，切得偏长会让生成请求直接失败。
DEFAULT_MAX_SHOT_SECONDS = 10
# H3VideoRequest declares duration_seconds ge=4 (schema/production.py), and
# providers/capabilities.py records min_duration_seconds=4 for minimax_h3, so a
# shorter shot would be rejected at submission. 4s is the strictest known floor.
MIN_SHOT_SECONDS = 4
VIDEO_MODEL_MAX_SHOT_SECONDS: tuple[tuple[str, int], ...] = (
    # Seedance：2.5 起支持 30s，2.x 之前维持 15s。
    ("seedance2.5", 30),
    ("seedance-2.5", 30),
    ("seedance2.0", 15),
    ("seedance-2.0", 15),
    ("seedance2", 15),
    ("seedance", 15),
    # MiniMax H3 / 海螺系：与 providers/capabilities.py 的 max_duration_seconds 保持一致。
    ("minimax-h3", 15),
    ("minimax h3", 15),
    ("hailuo", 15),
    ("h3", 15),
)


# 单个分镜时长的「宜用区间」：模型能生成的范围之内，按创作习惯取的一段。Seedance 2.5 一次能出 30 秒，
# 用它拍 4 秒碎镜既浪费调用也丢掉长镜头的连贯；2.0 与 H3 的 5–15 秒是它们画面最稳的一段。
# 编剧阶段把分镜时长限定在这里（模型从剧本规划时只能取区间内的整数秒），估算也落在这里。
VIDEO_MODEL_PREFERRED_SHOT_SECONDS: tuple[tuple[str, int, int], ...] = (
    ("seedance2.5", 10, 30),
    ("seedance-2.5", 10, 30),
    ("seedance2.0", 5, 15),
    ("seedance-2.0", 5, 15),
    ("seedance2", 5, 15),
    ("seedance", 5, 15),
    ("minimax-h3", 5, 15),
    ("minimax h3", 5, 15),
    ("hailuo", 5, 15),
    ("h3", 5, 15),
)


def _normalize_model_token(value: str) -> str:
    return re.sub(r"[\s_.]+", "-", (value or "").strip().lower())


def max_shot_seconds(model: str) -> int:
    """Longest single clip the selected video model can generate, in seconds.

    Matched longest-alias-first on the normalized id so ``seedance2.5`` resolves to
    its own 30s entry instead of the generic 15s ``seedance`` one.
    """
    normalized = _normalize_model_token(model)
    if not normalized:
        return DEFAULT_MAX_SHOT_SECONDS
    ranked = sorted(
        VIDEO_MODEL_MAX_SHOT_SECONDS,
        key=lambda item: len(_normalize_model_token(item[0])),
        reverse=True,
    )
    for alias, seconds in ranked:
        if _normalize_model_token(alias) in normalized:
            return seconds
    return DEFAULT_MAX_SHOT_SECONDS


def preferred_shot_seconds(model: str) -> tuple[int, int]:
    """The (shortest, longest) shot length to plan for ``model``: its preferred range, inside what it can render.

    Unlisted models keep the full renderable range, from the strictest known floor to their maximum.
    """
    hard_max = max_shot_seconds(model)
    normalized = _normalize_model_token(model)
    if normalized:
        ranked = sorted(VIDEO_MODEL_PREFERRED_SHOT_SECONDS, key=lambda item: len(_normalize_model_token(item[0])), reverse=True)
        for alias, low, high in ranked:
            if _normalize_model_token(alias) in normalized:
                high = min(high, hard_max)
                return max(MIN_SHOT_SECONDS, min(low, high)), high
    return MIN_SHOT_SECONDS, max(MIN_SHOT_SECONDS, hard_max)


def split_shot_seconds(duration_seconds: int, model: str) -> list[int]:
    """Cut one over-long shot into clips the model can actually render.

    Returns the per-clip seconds, preserving the original total so an episode's
    runtime never changes just because the shot had to be divided.
    """
    cap = max_shot_seconds(model)
    total = max(0, int(duration_seconds or 0))
    if total <= cap:
        return [total] if total else []
    parts = -(-total // cap)  # ceil
    base, remainder = divmod(total, parts)
    return [base + (1 if index < remainder else 0) for index in range(parts)]


def _unique(values: list[str] | None, limit: int) -> list[str]:
    return list(dict.fromkeys(value for value in (values or []) if value))[:limit]


def _declared_profile(model: str) -> VideoProviderProfile | None:
    """A provider the configuration centre declared in data: its spec says which modes it executes."""
    from app.core.providers.declarative_video import declared_video_endpoints

    family = declared_video_endpoints.family_for_model(model)
    spec = declared_video_endpoints.spec(family) if family else None
    if spec is None:
        return None
    return VideoProviderProfile(
        family=spec.family, aliases=list(spec.model_ids), modes=list(spec.modes),
        max_reference_images=spec.max_reference_images, max_reference_videos=spec.max_reference_videos,
        max_reference_audios=spec.max_reference_audios,
        verification_status="integrated" if declared_video_endpoints.ready(spec.family) else "runtime_configuration_required",
        capability_source=f"declared video endpoint {spec.label}",
        notes=["modes and limits come from the declared spec; the credential is proven on first generation"],
    )


def normalize_video_provider(model: str) -> VideoProviderProfile:
    declared = _declared_profile(model)
    if declared is not None:
        return declared
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


_NUMBERED_MENTION = re.compile(r"（参考图(\d+)）")
_REFERENCE_NOTE = re.compile(r"参考图(\d+)(仅锁定[^；。]*?不是额外剧情或额外人物)([；。]?)")


def renumber_reference_mentions(prompt: str, identity_images: list[str], plan: "VideoReferencePlan") -> str:
    """Number every 参考图N by the image the request actually carries.

    The prompt is written before routing and counts only the identity images
    (actor sheets, library references): 参考图k is ``identity_images[k-1]``. The
    router may put the first frame, sequence frames and last frame ahead of them,
    drop some to fit the model's limit, or send none at all (first / first+last
    frame modes). Each mention is renumbered to the image's real position, and a
    mention of an image that is not sent is removed, so no number points at the
    wrong picture. When the first frame travels as an image it is named as such.
    """
    sent = list(plan.reference_images or [])
    position = {url: index for index, url in enumerate(sent, start=1)}

    def target(old: str) -> int | None:
        index = int(old) - 1
        if index < 0 or index >= len(identity_images):
            return None
        return position.get(identity_images[index])

    def mention(match: re.Match[str]) -> str:
        number = target(match.group(1))
        return f"（参考图{number}）" if number else ""

    def note(match: re.Match[str]) -> str:
        number = target(match.group(1))
        return f"参考图{number}{match.group(2)}{match.group(3)}" if number else ""

    text = _REFERENCE_NOTE.sub(note, _NUMBERED_MENTION.sub(mention, prompt or ""))
    text = re.sub(r"；{2,}", "；", text)
    if plan.first_frame is None and sent and sent[0] not in identity_images:
        lead = "参考图1是本镜首帧画面，只决定开场构图、站位与光线；"
        if not text.startswith(lead):
            text = lead + text
    return text


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

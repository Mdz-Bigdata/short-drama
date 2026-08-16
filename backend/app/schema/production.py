"""Strict production contracts shared by storyboard and media providers."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


_DATA_IMAGE_RE = re.compile(
    r"^data:image/(?P<subtype>png|jpeg|webp);base64,(?P<payload>[A-Za-z0-9+/]+={0,2})$",
    re.IGNORECASE,
)
_MAX_INLINE_IMAGE_BYTES = 10 * 1024 * 1024


def _validate_remote_media(value: object, *, allow_inline_image: bool = False) -> str:
    """Accept provider-fetchable HTTP(S) media and bounded image tail frames.

    Tail-frame extraction intentionally returns an inline image. Keeping this
    validation here prevents local paths, arbitrary data URIs, credentials, and
    unbounded payloads from crossing a provider boundary.
    """
    text = str(value or "").strip()
    if allow_inline_image and text.lower().startswith("data:image/"):
        match = _DATA_IMAGE_RE.fullmatch(text)
        if not match:
            raise ValueError("inline frame must be a base64 PNG, JPEG, or WebP data URI")
        try:
            decoded = base64.b64decode(match.group("payload"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("inline frame contains invalid base64") from exc
        if not decoded or len(decoded) > _MAX_INLINE_IMAGE_BYTES:
            raise ValueError("inline frame must contain 1 byte to 10 MiB of image data")
        return text

    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("media must use an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("media URL cannot contain credentials")
    return text


FiveViewName = Literal[
    "front",
    "front_three_quarter",
    "profile",
    "rear_three_quarter",
    "back",
]
FIVE_VIEW_ORDER: tuple[FiveViewName, ...] = (
    "front",
    "front_three_quarter",
    "profile",
    "rear_three_quarter",
    "back",
)


class FiveView(BaseModel):
    view: FiveViewName
    image_url: AnyHttpUrl


class CharacterAsset(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    identity_dna: Annotated[str, Field(min_length=2, max_length=2000)]
    views: Annotated[list[FiveView], Field(min_length=5, max_length=5)]

    @model_validator(mode="after")
    def validate_view_order(self) -> "CharacterAsset":
        actual = tuple(view.view for view in self.views)
        if actual != FIVE_VIEW_ORDER:
            raise ValueError(f"five views must use exact order: {', '.join(FIVE_VIEW_ORDER)}")
        return self


class StoryAssetCatalog(BaseModel):
    """A storyboard cannot silently omit any production asset category."""

    characters: Annotated[list[str], Field(min_length=1)]
    scenes: Annotated[list[str], Field(min_length=1)]
    props: Annotated[list[str], Field(min_length=1)]
    effects: Annotated[list[str], Field(min_length=1)]


class StoryboardPanel(BaseModel):
    index: Annotated[int, Field(ge=1, le=9)]
    characters: Annotated[list[str], Field(min_length=1)]
    shot_size: Annotated[str, Field(min_length=1, max_length=80)]
    camera_angle: Annotated[str, Field(min_length=1, max_length=120)]
    camera_movement: Annotated[str, Field(min_length=1, max_length=160)]
    camera_reason: Annotated[str, Field(min_length=2, max_length=500)]
    lens_mm: Annotated[int, Field(ge=8, le=600)]
    aperture: Annotated[str, Field(min_length=2, max_length=20)]
    composition: Annotated[str, Field(min_length=2, max_length=1000)]
    action_axis: Annotated[str, Field(min_length=2, max_length=500)]
    eyeline: Annotated[str, Field(min_length=2, max_length=500)]
    shot_purpose: Literal["information", "emotion", "suspense", "tension", "reversal", "shock", "clue"] = "information"
    story_beat: Annotated[str, Field(min_length=1, max_length=500)] = "推进当前信息"
    duration_seconds: Annotated[float, Field(ge=0.5, le=300)] = 2.0
    subject_action: Annotated[str, Field(min_length=2, max_length=2000)]
    expression: Annotated[str, Field(min_length=2, max_length=1000)]
    scene: Annotated[str, Field(min_length=1, max_length=500)]
    props: Annotated[list[str], Field(min_length=1)]
    effects: Annotated[list[str], Field(min_length=1)]
    dialogue: str = ""
    sound: Annotated[str, Field(min_length=1, max_length=800)]
    lighting: Annotated[str, Field(min_length=2, max_length=800)]
    edit_in: Annotated[str, Field(min_length=2, max_length=500)]
    edit_out: Annotated[str, Field(min_length=2, max_length=500)]
    generation_mode: Literal["auto", "text", "first_frame", "last_frame", "first_last_frame", "reference"]
    blocking: Annotated[str, Field(min_length=1, max_length=800)] = "遵守场景圣经与180度轴线"
    start_state: Annotated[str, Field(min_length=1, max_length=1000)] = "承接上一格结束状态"
    end_state: Annotated[str, Field(min_length=1, max_length=1000)] = "形成下一格可承接的可见状态"
    continuity_in: Annotated[str, Field(max_length=1000)] = ""
    continuity_out: Annotated[str, Field(min_length=2, max_length=1000)]


class NineGridStoryboard(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    scene_number: Annotated[int, Field(ge=1, le=10_000)] = 1
    page_number: Annotated[int, Field(ge=1, le=1_000)] = 1
    total_pages: Annotated[int, Field(ge=1, le=1_000)] = 1
    rows: Literal[3] = 3
    columns: Literal[3] = 3
    reading_order: Literal["left_to_right_top_to_bottom"] = "left_to_right_top_to_bottom"
    rhythm_profile: Literal["romance", "confrontation", "reversal", "suspense", "horror", "comedy", "clue", "action"] = "confrontation"
    assets: StoryAssetCatalog
    panels: Annotated[list[StoryboardPanel], Field(min_length=1, max_length=9)]

    @model_validator(mode="after")
    def validate_panel_indices(self) -> "NineGridStoryboard":
        actual = [panel.index for panel in self.panels]
        if actual != list(range(1, len(self.panels) + 1)):
            raise ValueError("used nine-grid panels must be sequential from slot 1")
        if self.page_number > self.total_pages:
            raise ValueError("page_number cannot exceed total_pages")
        return self

    @computed_field
    @property
    def empty_slots(self) -> int:
        return 9 - len(self.panels)


H3ReferenceRole = Literal[
    "identity", "scene", "prop", "effect", "style", "motion", "camera",
    "rhythm", "voice", "music", "sound",
]


class H3ReferenceBinding(BaseModel):
    """Stable, auditable reference semantics independent from array position."""

    model_config = ConfigDict(extra="forbid")

    slot_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,119}$")]
    order: Annotated[int, Field(ge=1, le=12)]
    media_type: Literal["image", "video", "audio"]
    uri: str
    role: H3ReferenceRole
    priority: Annotated[int, Field(ge=1, le=100)] = 50
    content_sha256: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{64}$")]
    provenance: Annotated[str, Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def validate_uri(self) -> "H3ReferenceBinding":
        self.uri = _validate_remote_media(self.uri, allow_inline_image=self.media_type == "image")
        return self


class H3VideoRequest(BaseModel):
    prompt: Annotated[str, Field(min_length=1, max_length=20000)]
    model: Annotated[str, Field(min_length=1, max_length=120)] = "MiniMax-H3"
    first_frame: str | None = None
    last_frame: str | None = None
    reference_images: Annotated[list[str], Field(max_length=9)] = Field(default_factory=list)
    reference_videos: Annotated[list[str], Field(max_length=3)] = Field(default_factory=list)
    reference_audios: Annotated[list[str], Field(max_length=3)] = Field(default_factory=list)
    reference_bindings: Annotated[list[H3ReferenceBinding], Field(max_length=12)] = Field(default_factory=list)
    duration_seconds: Annotated[int, Field(ge=4, le=15)] = 6
    resolution: Literal["720p", "1080p", "2k"] = "1080p"
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    native_audio: bool = True
    seed: Annotated[int | None, Field(ge=0, le=2147483647)] = None

    @field_validator("first_frame", "last_frame", mode="before")
    @classmethod
    def validate_frame_locator(cls, value: object) -> str | None:
        return None if value is None else _validate_remote_media(value, allow_inline_image=True)

    @field_validator("reference_images", mode="before")
    @classmethod
    def validate_image_locators(cls, value: object) -> list[str]:
        return [_validate_remote_media(item, allow_inline_image=True) for item in list(value or [])]

    @field_validator("reference_videos", "reference_audios", mode="before")
    @classmethod
    def validate_av_locators(cls, value: object) -> list[str]:
        return [_validate_remote_media(item) for item in list(value or [])]

    @model_validator(mode="after")
    def validate_references(self) -> "H3VideoRequest":
        if self.reference_bindings and (
            self.reference_images or self.reference_videos or self.reference_audios
        ):
            raise ValueError("structured and legacy H3 reference inputs cannot be mixed")
        if self.reference_bindings:
            slot_ids = [binding.slot_id for binding in self.reference_bindings]
            orders = [binding.order for binding in self.reference_bindings]
            if len(slot_ids) != len(set(slot_ids)):
                raise ValueError("H3 reference slot_id values must be unique")
            if orders != list(range(1, len(orders) + 1)):
                raise ValueError("H3 structured reference order must be contiguous and start at 1")
            counts = {
                kind: sum(binding.media_type == kind for binding in self.reference_bindings)
                for kind in ("image", "video", "audio")
            }
            if counts["image"] > 9 or counts["video"] > 3 or counts["audio"] > 3:
                raise ValueError("H3 structured references exceed image/video/audio limits")
            if counts["audio"] and not (counts["image"] or counts["video"]):
                raise ValueError("reference audio requires at least one image or video reference")
        mixed_count = (
            len(self.reference_images)
            + len(self.reference_videos)
            + len(self.reference_audios)
            + len(self.reference_bindings)
        )
        if mixed_count > 12:
            raise ValueError("H3 accepts at most 12 mixed reference files")
        if self.reference_audios and not (
            self.reference_images or self.reference_videos or self.first_frame or self.last_frame
        ):
            raise ValueError("reference audio requires at least one image or video reference")
        if (
            self.reference_images or self.reference_videos or self.reference_audios or self.reference_bindings
        ) and (self.first_frame or self.last_frame):
            raise ValueError(
                "H3 frame anchoring and Ref2VA video/audio references are separate generation modes"
            )
        return self

    @computed_field
    @property
    def inferred_mode(self) -> Literal[
        "text", "first_frame", "last_frame", "first_last_frame", "reference"
    ]:
        if self.reference_images or self.reference_videos or self.reference_audios or self.reference_bindings:
            return "reference"
        if self.first_frame and self.last_frame:
            return "first_last_frame"
        if self.first_frame:
            return "first_frame"
        if self.last_frame:
            return "last_frame"
        return "text"


class PronunciationDictionaryLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pronunciation_dictionary_id: Annotated[str, Field(min_length=1, max_length=200)]
    version_id: Annotated[str, Field(min_length=1, max_length=200)]


class TTSRequest(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=10000)]
    voice_id: Annotated[str, Field(min_length=1, max_length=200)]
    emotion: Annotated[str, Field(max_length=80)] = "neutral"
    speed: Annotated[float, Field(ge=0.7, le=1.2)] = 1.0
    model_id: str = "eleven_multilingual_v2"
    pronunciation_dictionary_locators: Annotated[
        list[PronunciationDictionaryLocator], Field(max_length=3)
    ] = Field(default_factory=list)


class DialogueLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: Annotated[str, Field(min_length=1, max_length=200)]
    text: Annotated[str, Field(min_length=1, max_length=10000)]
    emotion: Annotated[str, Field(max_length=80)] = "neutral"


class DialogueRequest(BaseModel):
    lines: Annotated[list[DialogueLineRequest], Field(min_length=1, max_length=50)]


class SoundEffectRequest(BaseModel):
    prompt: Annotated[str, Field(min_length=1, max_length=1000)]
    duration_seconds: Annotated[float | None, Field(ge=0.5, le=22)] = None
    prompt_influence: Annotated[float, Field(ge=0, le=1)] = 0.5


class MusicRequest(BaseModel):
    prompt: Annotated[str, Field(min_length=1, max_length=4100)]
    duration_seconds: Annotated[float, Field(ge=3, le=600)]
    instrumental: bool = True
    model_id: str = "music_v2"


class DubbingRequest(BaseModel):
    source_url: AnyHttpUrl
    target_language: Annotated[str, Field(min_length=2, max_length=12)]
    source_language: Annotated[str, Field(min_length=2, max_length=12)] = "auto"
    num_speakers: Annotated[int, Field(ge=0, le=32)] = 0


class CreativePresetCompileRequest(BaseModel):
    content: Annotated[str, Field(min_length=1, max_length=30000)]
    asset_context: Annotated[str, Field(max_length=20000)] = ""
    language: Annotated[str, Field(min_length=2, max_length=20)] = "zh-CN"


Sd25MediaType = Literal["image", "video", "audio"]
Sd25AssetRole = Literal[
    "character", "scene", "prop", "effect", "style", "action", "camera",
    "voice", "music", "sound", "keyframe", "source",
]


class Sd25Asset(BaseModel):
    """One read-only reference with one declared primary responsibility."""

    ref: Annotated[str, Field(pattern=r"^@(?:图片|视频|音频|Image|Video|Audio)\s?\d+$")]
    media_type: Sd25MediaType
    role: Sd25AssetRole
    subject: Annotated[str, Field(min_length=1, max_length=120)]
    observations: Annotated[str, Field(min_length=1, max_length=2000)]
    duration_seconds: Annotated[float | None, Field(gt=0, le=30)] = None
    required: bool = False

    @model_validator(mode="after")
    def validate_reference_contract(self) -> "Sd25Asset":
        prefix = self.ref.removeprefix("@").replace(" ", "")
        expected = (
            "image" if prefix.startswith(("图片", "Image"))
            else "video" if prefix.startswith(("视频", "Video"))
            else "audio"
        )
        if self.media_type != expected:
            raise ValueError(f"asset {self.ref} must declare media_type={expected}")
        if self.media_type == "image" and self.duration_seconds is not None:
            raise ValueError("image references may not declare duration_seconds")
        if self.media_type in {"video", "audio"} and self.duration_seconds is None:
            raise ValueError("video and audio references require duration_seconds for hard-limit validation")
        return self


class Sd25DialogueEntry(BaseModel):
    speaker: Annotated[str, Field(min_length=1, max_length=80)]
    text: Annotated[str, Field(max_length=1000)] = ""
    language: Annotated[str, Field(max_length=40)] = ""
    delivery: Annotated[str, Field(min_length=1, max_length=500)]
    position: Literal["画内", "画外", "旁白"] = "画内"
    audio_ref: Annotated[str | None, Field(pattern=r"^@(?:音频|Audio)\s?\d+$")] = None


class Sd25MissingAsset(BaseModel):
    """A declared but inaccessible reference that must not enter prompt text."""

    ref: Annotated[str, Field(pattern=r"^@(?:图片|视频|音频|Image|Video|Audio)\s?\d+$")]
    intended_role: Annotated[str, Field(min_length=1, max_length=500)]


class Sd25CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: Annotated[str, Field(min_length=1, max_length=30000)]
    task: Literal["generation", "edit", "extend", "edit_then_extend"] = "generation"
    edit_scope: Literal["visual", "audio", "both"] = "both"
    edit_scope_closure: Literal["preserve_unspecified", "delete_unspecified"] = "preserve_unspecified"
    assets: Annotated[list[Sd25Asset], Field(max_length=50)] = Field(default_factory=list)
    missing_assets: Annotated[list[Sd25MissingAsset], Field(max_length=50)] = Field(default_factory=list)
    dialogue: Annotated[list[Sd25DialogueEntry], Field(max_length=100)] = Field(default_factory=list)
    first_frame_ref: str | None = None
    last_frame_ref: str | None = None
    keyframe_refs: Annotated[list[str], Field(max_length=30)] = Field(default_factory=list)
    source_video_ref: str | None = None
    extension_direction: Literal["before", "after"] | None = None
    storyboard_ref: str | None = None
    storyboard: NineGridStoryboard | None = None
    blockout_ref: str | None = None
    blockout_granularity: Literal["coarse", "fine"] | None = None
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, str | int | float | bool]):
        if len(value) > 32:
            raise ValueError("sd25 accepts at most 32 separate provider parameters")
        for key, parameter in value.items():
            if not key or len(key) > 80 or not key.replace("_", "").isalnum():
                raise ValueError("sd25 parameter names must be short alphanumeric snake_case names")
            if any(marker in key.lower() for marker in ("api_key", "apikey", "secret", "token", "authorization")):
                raise ValueError("sd25 provider parameters may not contain credentials or secrets")
            if isinstance(parameter, str) and len(parameter) > 500:
                raise ValueError("sd25 string parameters may contain at most 500 characters")
        return value

    @model_validator(mode="after")
    def validate_material_contract(self) -> "Sd25CompileRequest":
        refs = [asset.ref for asset in self.assets]
        if len(refs) != len(set(refs)):
            raise ValueError("each sd25 asset reference must be unique")
        missing_refs = [asset.ref for asset in self.missing_assets]
        if len(missing_refs) != len(set(missing_refs)) or set(refs) & set(missing_refs):
            raise ValueError("missing sd25 references must be unique and cannot also be available")
        images = [asset for asset in self.assets if asset.media_type == "image"]
        videos = [asset for asset in self.assets if asset.media_type == "video"]
        audios = [asset for asset in self.assets if asset.media_type == "audio"]
        if len(images) > 30 or len(videos) > 10 or len(audios) > 10:
            raise ValueError("sd25 hard limits are 30 images, 10 videos and 10 audio files")
        if sum(asset.duration_seconds or 0 for asset in videos) > 30:
            raise ValueError("sd25 reference videos may total at most 30 seconds")
        if sum(asset.duration_seconds or 0 for asset in audios) > 30:
            raise ValueError("sd25 reference audio may total at most 30 seconds")
        by_ref = {asset.ref: asset for asset in self.assets}
        for dialogue in self.dialogue:
            if dialogue.audio_ref:
                audio = by_ref.get(dialogue.audio_ref)
                if not audio or audio.media_type != "audio":
                    raise ValueError("dialogue audio_ref must point to a provided audio asset")
        for frame_ref in (self.first_frame_ref, self.last_frame_ref):
            if frame_ref and (frame_ref not in by_ref or by_ref[frame_ref].media_type != "image"):
                raise ValueError("first and last frame references must point to provided images")
        if len(self.keyframe_refs) != len(set(self.keyframe_refs)):
            raise ValueError("ordered keyframe references must be unique")
        for frame_ref in self.keyframe_refs:
            if frame_ref not in by_ref or by_ref[frame_ref].media_type != "image":
                raise ValueError("ordered keyframes must point to provided images")
        if self.keyframe_refs and len(self.keyframe_refs) < 2:
            raise ValueError("ordered keyframe generation requires at least two images")
        if self.first_frame_ref and self.keyframe_refs and self.keyframe_refs[0] != self.first_frame_ref:
            raise ValueError("the first ordered keyframe must equal first_frame_ref")
        if self.last_frame_ref and self.keyframe_refs and self.keyframe_refs[-1] != self.last_frame_ref:
            raise ValueError("the last ordered keyframe must equal last_frame_ref")
        if self.task in {"edit", "edit_then_extend"}:
            source = by_ref.get(self.source_video_ref or "")
            if not source or source.media_type != "video":
                raise ValueError("video editing requires one provided source video")
        if self.task in {"extend", "edit_then_extend"}:
            source = by_ref.get(self.source_video_ref or "")
            if not source or source.media_type != "video" or not self.extension_direction:
                raise ValueError("video extension requires a source video and before/after direction")
        if self.task != "generation" and (self.first_frame_ref or self.last_frame_ref):
            raise ValueError("keyframe generation and edit/extend are separate primary tasks")
        if bool(self.storyboard_ref) != bool(self.storyboard):
            raise ValueError("storyboard reference and exact nine-grid data must be provided together")
        if self.storyboard_ref:
            source = by_ref.get(self.storyboard_ref)
            if not source or source.media_type != "image":
                raise ValueError("storyboard reference must point to a provided image")
        if bool(self.blockout_ref) != bool(self.blockout_granularity):
            raise ValueError("blockout reference and granularity must be provided together")
        if self.blockout_ref:
            source = by_ref.get(self.blockout_ref)
            if not source or source.media_type != "video":
                raise ValueError("blockout reference must point to a provided video")
        if self.storyboard_ref and self.blockout_ref:
            raise ValueError("storyboard and blockout are separate primary structure references")
        if self.keyframe_refs and (self.storyboard_ref or self.blockout_ref):
            raise ValueError("ordered keyframes, storyboard and blockout are separate structure references")
        return self


class Sd25CompileStep(BaseModel):
    mode: str
    prompt: str
    used_assets: list[str]
    unused_assets: list[str]
    parameters: dict[str, str | int | float | bool]


class Sd25CompileResult(BaseModel):
    mode: str
    prompt: str
    used_assets: list[str]
    unused_assets: list[str]
    parameters: dict[str, str | int | float | bool]
    warnings: list[str] = Field(default_factory=list)
    steps: list[Sd25CompileStep] = Field(default_factory=list)

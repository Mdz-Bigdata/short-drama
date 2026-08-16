"""Typed contracts for the script-to-video prompt production package."""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schema.production import FIVE_VIEW_ORDER, FiveViewName, NineGridStoryboard, Sd25Asset
from app.schema.storyboard_director import StoryboardDirectorResult


ScriptElementType = Literal[
    "scene_heading", "action", "character", "dialogue", "parenthetical", "transition", "note"
]


class ScriptElement(BaseModel):
    type: ScriptElementType
    content: Annotated[str, Field(min_length=1, max_length=20_000)]
    line_number: Annotated[int, Field(ge=1)]
    speaker: Annotated[str, Field(max_length=120)] = ""


class ParsedScreenplayScene(BaseModel):
    number: Annotated[int, Field(ge=1)]
    heading: Annotated[str, Field(min_length=1, max_length=500)]
    location: Annotated[str, Field(min_length=1, max_length=300)]
    time_of_day: Annotated[str, Field(min_length=1, max_length=80)]
    int_ext: Literal["INT", "EXT", "INT/EXT", "UNKNOWN"] = "UNKNOWN"
    characters: list[str] = Field(default_factory=list, max_length=100)
    elements: list[ScriptElement] = Field(default_factory=list, max_length=10_000)
    estimated_duration_seconds: Annotated[float, Field(ge=0, le=86_400)] = 0


class ParsedScreenplay(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=300)]
    scenes: Annotated[list[ParsedScreenplayScene], Field(min_length=1, max_length=1_000)]
    all_characters: list[str] = Field(default_factory=list, max_length=2_000)
    all_locations: list[str] = Field(default_factory=list, max_length=2_000)
    total_duration_seconds: Annotated[float, Field(ge=0, le=31_536_000)] = 0


class CharacterCostumeProfile(BaseModel):
    scene_numbers: Annotated[list[int], Field(min_length=1, max_length=1_000)]
    description: Annotated[str, Field(min_length=1, max_length=2_000)]
    colors: list[str] = Field(default_factory=list, max_length=30)
    accessories: list[str] = Field(default_factory=list, max_length=30)
    source: Literal["script", "override"] = "script"


class CharacterPromptProfile(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    role: Literal["lead", "supporting", "extra", "unknown"] = "unknown"
    identity_status: Literal["bound", "needs_review"]
    identity_dna: Annotated[str, Field(min_length=1, max_length=4_000)]
    appearance_facts: list[str] = Field(default_factory=list, max_length=100)
    personality_expressions: list[str] = Field(default_factory=list, max_length=100)
    costumes: list[CharacterCostumeProfile] = Field(default_factory=list, max_length=1_000)
    props: list[str] = Field(default_factory=list, max_length=100)
    scene_appearances: list[int] = Field(default_factory=list, max_length=1_000)
    evidence_lines: list[int] = Field(default_factory=list, max_length=10_000)
    five_view_order: Annotated[list[FiveViewName], Field(min_length=5, max_length=5)]
    five_view_prompt: Annotated[str, Field(min_length=1, max_length=12_000)]
    consistency_seed: Annotated[str, Field(min_length=1, max_length=5_000)]

    @model_validator(mode="after")
    def ordered_five_views(self) -> "CharacterPromptProfile":
        if tuple(self.five_view_order) != FIVE_VIEW_ORDER:
            raise ValueError("character five-view order must match the project-wide contract")
        return self


class SceneLightingProfile(BaseModel):
    source_type: Literal["natural", "artificial", "mixed", "unspecified"] = "unspecified"
    direction: Annotated[str, Field(min_length=1, max_length=300)] = "按剧本或场景参考锁定"
    intensity: Annotated[str, Field(min_length=1, max_length=120)] = "按剧本可见状态"
    color_temperature: Annotated[str, Field(min_length=1, max_length=120)] = "按剧本时段"
    quality: Annotated[str, Field(min_length=1, max_length=120)] = "自然连续"


class ScenePromptProfile(BaseModel):
    scene_number: Annotated[int, Field(ge=1)]
    heading: Annotated[str, Field(min_length=1, max_length=500)]
    location: Annotated[str, Field(min_length=1, max_length=300)]
    int_ext: Literal["INT", "EXT", "INT/EXT", "UNKNOWN"]
    time_of_day: Annotated[str, Field(min_length=1, max_length=80)]
    weather: Annotated[str, Field(max_length=120)] = ""
    season: Annotated[str, Field(max_length=120)] = ""
    spatial_layout: Annotated[str, Field(min_length=1, max_length=3_000)]
    key_props: list[str] = Field(default_factory=list, max_length=100)
    background_elements: list[str] = Field(default_factory=list, max_length=100)
    lighting: SceneLightingProfile
    color_palette: list[str] = Field(default_factory=list, max_length=30)
    mood_keywords: list[str] = Field(default_factory=list, max_length=30)
    visual_prompt: Annotated[str, Field(min_length=1, max_length=8_000)]
    consistency_seed: Annotated[str, Field(min_length=1, max_length=5_000)]


class ScriptVideoRouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    requested_mode: Literal[
        "auto", "first_frame", "first_last_frame", "multi_reference", "multimodal"
    ] = "auto"
    first_frame: str | None = None
    last_frame: str | None = None
    sequence_images: list[str] = Field(default_factory=list, max_length=9)
    reference_images: list[str] = Field(default_factory=list, max_length=9)
    reference_videos: list[str] = Field(default_factory=list, max_length=3)
    reference_audios: list[str] = Field(default_factory=list, max_length=3)
    exact_end_frame_required: bool = False
    narrative_image_sequence: bool = False
    identity_consistency_required: bool = True
    motion_reference_required: bool = False
    audio_rhythm_required: bool = False
    multi_shot_output: bool = False

    @staticmethod
    def _safe_locator(value: object) -> str:
        text = str(value or "").strip()
        parsed = urlsplit(text)
        if len(text) > 4_000 or parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("video route media must use a bounded absolute HTTP(S) URL")
        if parsed.username or parsed.password:
            raise ValueError("video route media URLs cannot contain credentials")
        return text

    @field_validator("first_frame", "last_frame", mode="before")
    @classmethod
    def validate_optional_locator(cls, value: object) -> str | None:
        return None if value is None else cls._safe_locator(value)

    @field_validator(
        "sequence_images", "reference_images", "reference_videos", "reference_audios",
        mode="before",
    )
    @classmethod
    def validate_locators(cls, value: object) -> list[str]:
        return [cls._safe_locator(item) for item in list(value or [])]


class ShotReferenceAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_number: Annotated[int, Field(ge=1)]
    page_number: Annotated[int, Field(ge=1, le=1_000)] = 1
    panel_index: Annotated[int, Field(ge=1, le=9)]
    assets: Annotated[list[Sd25Asset], Field(max_length=50)] = Field(default_factory=list)
    first_frame_ref: str | None = None
    last_frame_ref: str | None = None
    keyframe_refs: Annotated[list[str], Field(max_length=30)] = Field(default_factory=list)
    storyboard_ref: str | None = None
    blockout_ref: str | None = None
    blockout_granularity: Literal["coarse", "fine"] | None = None
    route: ScriptVideoRouteInput | None = None

    @model_validator(mode="after")
    def unique_keyframes(self) -> "ShotReferenceAssignment":
        if len(self.keyframe_refs) != len(set(self.keyframe_refs)):
            raise ValueError("keyframe references must be unique and ordered")
        return self


class ShotPromptBundle(BaseModel):
    scene_number: int
    page_number: int = 1
    panel_index: int
    beat_index: int
    director_plan_fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    contract_fingerprint: str
    storyboard_image_prompt: str
    motion_prompt: str
    sd25_mode: str
    sd25_prompt: str
    provider_parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    video_reference_plan: dict[str, object] | None = None
    used_assets: list[str] = Field(default_factory=list)
    unused_assets: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PromptConsistencyIssue(BaseModel):
    code: Annotated[str, Field(pattern=r"^[a-z0-9_]{3,80}$")]
    severity: Literal["warning", "error"]
    location: Annotated[str, Field(min_length=1, max_length=300)]
    description: Annotated[str, Field(min_length=1, max_length=2_000)]
    suggestion: Annotated[str, Field(min_length=1, max_length=2_000)]


class PromptConsistencyReport(BaseModel):
    passed: bool
    character_seeds: dict[str, str] = Field(default_factory=dict)
    scene_seeds: dict[str, str] = Field(default_factory=dict)
    issues: list[PromptConsistencyIssue] = Field(default_factory=list)


ExportFormat = Literal["json", "markdown", "csv", "xlsx", "html"]


class ScriptPromptCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=300)] = "Untitled"
    script_text: Annotated[str, Field(min_length=1, max_length=2_000_000)]
    source_format: Literal["text", "markdown", "docx", "pdf", "fdx"] = "text"
    source_sha256: Annotated[str | None, Field(pattern=r"^[a-fA-F0-9]{64}$")] = None
    visual_style: Annotated[str, Field(min_length=1, max_length=2_000)] = "写实真人电影质感"
    prompt_language: Annotated[str, Field(min_length=1, max_length=40)] = "zh-CN"
    output_language: Annotated[str, Field(min_length=1, max_length=40)] = "zh-CN"
    video_model: Annotated[str, Field(min_length=1, max_length=120)] = "Seedance 2.5"
    character_overrides: dict[str, str] = Field(default_factory=dict, max_length=200)
    scene_overrides: dict[int, str] = Field(default_factory=dict, max_length=1_000)
    reference_assignments: list[ShotReferenceAssignment] = Field(default_factory=list, max_length=9_000)
    provider_parameters: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=32)
    exports: Annotated[list[ExportFormat], Field(min_length=1, max_length=5)] = Field(
        default_factory=lambda: ["json", "markdown", "csv", "html"]
    )

    @field_validator("character_overrides")
    @classmethod
    def validate_character_overrides(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not name.strip() or len(name) > 120 or not dna.strip() or len(dna) > 4_000 for name, dna in value.items()):
            raise ValueError("character overrides require short names and non-empty identity DNA")
        return value

    @field_validator("scene_overrides")
    @classmethod
    def validate_scene_overrides(cls, value: dict[int, str]) -> dict[int, str]:
        if any(number < 1 or not description.strip() or len(description) > 3_000 for number, description in value.items()):
            raise ValueError("scene overrides require positive scene numbers and descriptions up to 3000 characters")
        return value

    @field_validator("exports")
    @classmethod
    def unique_exports(cls, value: list[ExportFormat]) -> list[ExportFormat]:
        if len(value) != len(set(value)):
            raise ValueError("export formats must be unique")
        return value

    @model_validator(mode="after")
    def unique_assignments(self) -> "ScriptPromptCompileRequest":
        keys = [
            (item.scene_number, item.page_number, item.panel_index)
            for item in self.reference_assignments
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("each scene/page/panel may have only one reference assignment")
        return self


class ScriptPromptCompileResult(BaseModel):
    schema_version: Literal["script-prompts.v1"] = "script-prompts.v1"
    source_sha256: str
    source_format: str
    prompt_language: str
    output_language: str
    screenplay: ParsedScreenplay
    characters: list[CharacterPromptProfile]
    scenes: list[ScenePromptProfile]
    director_plans: list[StoryboardDirectorResult]
    storyboards: list[NineGridStoryboard]
    shot_prompts: list[ShotPromptBundle]
    consistency: PromptConsistencyReport
    exports: dict[str, str]
    warnings: list[str] = Field(default_factory=list)
    submission_ready: bool
    template_sources: list[str] = Field(
        default_factory=lambda: [
            "script-to-video-prompts", "sd25-pe", "universal-storyboard-prompt"
        ]
    )

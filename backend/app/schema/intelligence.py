"""Typed contracts for traceable novel intake and reference-backed voice direction."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class NovelAnalyzeRequest(BaseModel):
    source_id: Annotated[str, Field(min_length=1, max_length=160)]
    text: Annotated[str, Field(min_length=1, max_length=5_000_000)]
    sample_count: Annotated[int, Field(ge=1, le=100)] = 8


class ChapterSlice(BaseModel):
    index: int
    title: str
    start_char: int
    end_char: int
    start_byte: int
    end_byte: int
    sha256: str
    character_count: int


class NovelAnalysisReport(BaseModel):
    source_id: str
    content_sha256: str
    chapters: list[ChapterSlice]
    sampled_chapter_indices: list[int]
    coverage_ratio: float
    warnings: list[str] = Field(default_factory=list)


class EpisodeBoundary(BaseModel):
    episode_index: Annotated[int, Field(ge=1, le=100_000)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    start_line: Annotated[int, Field(ge=1)]
    end_line: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def ordered_lines(self) -> "EpisodeBoundary":
        if self.end_line < self.start_line:
            raise ValueError("episode end_line must not precede start_line")
        return self


class EpisodeIntakeRequest(BaseModel):
    source_id: Annotated[str, Field(min_length=1, max_length=160)]
    text: Annotated[str, Field(min_length=1, max_length=5_000_000)]
    boundaries: Annotated[list[EpisodeBoundary], Field(max_length=100_000)] = Field(default_factory=list)
    resume_after_episode: Annotated[int, Field(ge=0)] = 0
    output_language: Annotated[str, Field(min_length=2, max_length=35)] = "zh-CN"
    prompt_language: Annotated[str, Field(min_length=2, max_length=35)] = "en"

    @model_validator(mode="after")
    def unique_ordered_boundaries(self) -> "EpisodeIntakeRequest":
        indices = [item.episode_index for item in self.boundaries]
        if len(indices) != len(set(indices)):
            raise ValueError("episode indices must be unique")
        ordered = sorted(self.boundaries, key=lambda item: item.start_line)
        if any(left.end_line >= right.start_line for left, right in zip(ordered, ordered[1:])):
            raise ValueError("episode line boundaries must not overlap")
        return self


class EpisodeSlice(BaseModel):
    episode_index: int
    title: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    sha256: str
    text: str


class EpisodeIntakeReport(BaseModel):
    source_id: str
    content_sha256: str
    output_language: str
    prompt_language: str
    episodes: list[EpisodeSlice]
    pending_episode_indices: list[int]
    warnings: list[str] = Field(default_factory=list)


VoiceAuthorization = Literal["creator_owned", "licensed", "consented_clone"]
VoiceAdmission = Literal["unverified", "approved", "rejected"]


class VoiceReferenceBinding(BaseModel):
    uri: Annotated[str, Field(min_length=1, max_length=2048)]
    content_sha256: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{64}$")]
    authorization: VoiceAuthorization
    consent_record: Annotated[str, Field(max_length=500)] = ""
    admission_status: VoiceAdmission = "unverified"
    may_control: Annotated[list[str], Field(min_length=1, max_length=30)]
    must_not_control: Annotated[list[str], Field(min_length=1, max_length=30)]

    @model_validator(mode="after")
    def enforce_identity_boundary(self) -> "VoiceReferenceBinding":
        may = {item.strip().lower() for item in self.may_control}
        must_not = {item.strip().lower() for item in self.must_not_control}
        if "" in may or "" in must_not or len(may) != len(self.may_control) or len(must_not) != len(self.must_not_control):
            raise ValueError("voice reference control fields must be non-empty and unique")
        if may & must_not:
            raise ValueError("voice reference may_control and must_not_control cannot overlap")
        required_exclusions = {"emotion", "recording_room", "background_content"}
        if not required_exclusions.issubset(must_not):
            raise ValueError("voice identity must exclude emotion, recording_room and background_content")
        if (
            self.admission_status == "approved"
            and self.authorization == "consented_clone"
            and not self.consent_record.strip()
        ):
            raise ValueError("an approved cloned voice requires a consent record")
        return self


class VoiceDirectionRequest(BaseModel):
    character_id: Annotated[str, Field(min_length=1, max_length=160)]
    character_name: Annotated[str, Field(min_length=1, max_length=160)]
    language: Annotated[str, Field(min_length=2, max_length=35)] = "zh-CN"
    reference: VoiceReferenceBinding | None = None
    selection_criteria: Annotated[list[str], Field(min_length=1, max_length=30)]
    rejection_criteria: Annotated[list[str], Field(min_length=1, max_length=30)]
    pronunciations: Annotated[dict[str, str], Field(max_length=200)] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_pronunciations(self) -> "VoiceDirectionRequest":
        if any(
            not term.strip() or not pronunciation.strip()
            or len(term) > 100 or len(pronunciation) > 200
            for term, pronunciation in self.pronunciations.items()
        ):
            raise ValueError("voice pronunciation entries must contain one non-empty canonical reading")
        return self


class VoiceCastingPlan(BaseModel):
    character_id: str
    character_name: str
    language: str
    status: Literal["ready", "needs_reference", "needs_review", "blocked"]
    reference: VoiceReferenceBinding | None
    selection_criteria: list[str]
    rejection_criteria: list[str]
    pronunciations: dict[str, str]
    warnings: list[str] = Field(default_factory=list)

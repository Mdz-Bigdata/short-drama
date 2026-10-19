"""Per-shot visual settings edited in the visual stage (运镜 / 景别 / 时长 / 环境音)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.camera_motion import normalize_camera_motion, normalize_shot_type


class ShotVisualSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_motion: str = Field(min_length=1, max_length=60)
    shot_type: str = Field(min_length=1, max_length=60)
    duration_seconds: int = Field(ge=1, le=60)
    action: str = Field("", max_length=2000)
    ambiance_audio: str = Field("", max_length=500)
    lighting: str = Field("", max_length=500)
    ambiance: str = Field("", max_length=500)
    # Fixed seed per shot (same-scene shots keep neighbouring seeds) and how many
    # candidates to render for this shot before the user picks one.
    seed: int | None = Field(None, ge=0, le=2147483647)
    candidates: int = Field(1, ge=1, le=4)

    @field_validator("camera_motion")
    @classmethod
    def canonical_motion(cls, value: str) -> str:
        canonical, matched = normalize_camera_motion(value)
        if not matched:
            raise ValueError(f"镜头运动「{value}」不在供应商运镜词表内")
        return canonical

    @field_validator("shot_type")
    @classmethod
    def canonical_shot_type(cls, value: str) -> str:
        canonical, matched = normalize_shot_type(value)
        if not matched:
            raise ValueError(f"景别「{value}」不在景别词表内")
        return canonical


class ShotRecipeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=40)
    intensity: Literal["strong", "medium", "soft"] = "medium"


class ShotCandidateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_url: str = Field(min_length=1, max_length=2000)


class ShotVisualRecord(BaseModel):
    shot_id: int
    scene_id: str = ""
    desc: str = ""
    dialogue: str = ""
    sound: str = ""
    settings: ShotVisualSettings
    settings_source: Literal["edited", "derived"]
    derived_notes: list[str] = Field(default_factory=list)
    image_url: str | None = None
    end_frame_url: str | None = None
    video_url: str | None = None
    candidate_urls: list[str] = Field(default_factory=list)
    image_prompt: str = ""
    video_prompt: str = ""
    contract_fingerprint: str = ""
    route: dict[str, Any] | None = None
    stale: bool = False
    stale_reason: str = ""
    # 视频提示词是人工改过的版本(下次重做本镜时用它，而不是重新编译)。
    video_prompt_edited: bool = False
    # 提示词里 @[名字] 对应的资产类型(actor / scene / prop / costume / effect)与参考图序号，供编辑器着色与解析预览。
    mention_kinds: dict[str, str] = Field(default_factory=dict)
    reference_numbers: dict[str, int] = Field(default_factory=dict)


class ShotVideoPromptUpdate(BaseModel):
    """人工改写的视频提示词；``prompt`` 为空表示放弃改写，恢复自动编译。"""
    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(None, max_length=8000)


class ShotRegenerateRequest(BaseModel):
    reason: str = Field("", max_length=300)


class VideoAdmissionRequest(BaseModel):
    """Re-assess with duration tiers the person has accepted; ``persist`` keeps them on the project."""
    confirmed_request_durations: list[dict[str, int]] = Field(default_factory=list, max_length=200)
    persist: bool = False


class ShotVisualWorkspaceResponse(BaseModel):
    task_id: str
    current_stage: int = 0
    running: bool = False
    video_model: str = ""
    provider_family: str = ""
    duration_options: list[int] = Field(default_factory=list)
    camera_motions: list[dict[str, str]] = Field(default_factory=list)
    shot_types: list[dict[str, str]] = Field(default_factory=list)
    recipe_categories: list[dict[str, str]] = Field(default_factory=list)
    shots: list[ShotVisualRecord] = Field(default_factory=list)

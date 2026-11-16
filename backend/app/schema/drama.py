# -*- coding: utf-8 -*-
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Annotated, Optional, Dict, Any, Literal, List

from app.core.style_packs import DEFAULT_PACK_ID
from app.core import prompt_data


_WORDING_FILE = "schema_drama"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/schema_drama.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

# One definition of a new project's range and defaults; requests, stored
# configuration and the pipeline's fallbacks all read these.
EPISODE_COUNT_MIN = 1
EPISODE_COUNT_MAX = 150
DEFAULT_EPISODE_COUNT = 3
DEFAULT_DIRECTOR_STYLE = "cyberpunk"
DEFAULT_SHOT_STYLE = "standard"
DEFAULT_LLM_MODEL = "deepseek"
DEFAULT_IMAGE_MODEL = "seedance"
DEFAULT_VIDEO_MODEL = "seedance2.0"
DEFAULT_TTS_MODEL = "ElevenLabs"


EditableVideoReferenceMode = Literal[
    "auto", "first_last_frame", "multi_reference", "multimodal",
]
StoredVideoReferenceMode = Literal[
    "auto", "first_frame", "first_last_frame", "multi_reference", "multimodal",
]

def to_camel(string: str) -> str:
    """
    将下划线命名转换为小驼峰命名
    """
    temp = string.split('_')
    return temp[0] + ''.join(ele.title() for ele in temp[1:])

class DramaBaseSchema(BaseModel):
    """
    短剧基础校验 Schema，支持驼峰命名转换
    """
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class AdBrief(DramaBaseSchema):
    """An advertisement's brief: what the spot sells and what it asks the viewer to do."""
    product: str = Field("", max_length=200)
    selling_points: str = Field("", max_length=500)
    audience: str = Field("", max_length=200)
    call_to_action: str = Field("", max_length=100)


class DramaCreateRequest(DramaBaseSchema):
    """
    创建短剧任务的请求 Schema
    """
    title_suggestion: str = Field(..., description=_text_of("DramaCreateRequest.description"), min_length=2)
    director_style: str = Field(DEFAULT_DIRECTOR_STYLE, description=_text_of("DramaCreateRequest.description.2"))
    style_pack: Optional[str] = Field(
        None,
        description=(
            _text_of("DramaCreateRequest.description.3")
        ),
        max_length=40,
    )
    shot_style: str = Field(DEFAULT_SHOT_STYLE, description=_text_of("DramaCreateRequest.description.4"))
    llm_model: str = Field(DEFAULT_LLM_MODEL, description=_text_of("DramaCreateRequest.description.5"))
    image_model: str = Field(DEFAULT_IMAGE_MODEL, description=_text_of("DramaCreateRequest.description.6"))
    video_model: str = Field(DEFAULT_VIDEO_MODEL, description=_text_of("DramaCreateRequest.description.7"))
    tts_model: str = Field(DEFAULT_TTS_MODEL, description=_text_of("DramaCreateRequest.description.8"))
    video_reference_mode: EditableVideoReferenceMode = Field(
        "auto", description=_text_of("DramaCreateRequest.description.9")
    )
    narration_delivery: Literal["use_tts", "post_production"] = Field(
        "use_tts", description=_text_of("DramaCreateRequest.description.10")
    )
    creation_mode: Literal["drama", "narration", "ad", "film"] = Field(
        "drama", description=_text_of("DramaCreateRequest.description.11")
    )
    ad_brief: Optional[AdBrief] = Field(None, description=_text_of("DramaCreateRequest.description.12"))
    poetry_sources: Optional[List[Annotated[str, Field(min_length=1, max_length=40)]]] = Field(
        None, max_length=40,
        description=_text_of("DramaCreateRequest.description.13"),
    )
    content_language: Literal["zh", "en", "vi"] = Field(
        "zh", description=_text_of("DramaCreateRequest.description.14")
    )
    one_click: bool = Field(False, description=_text_of("DramaCreateRequest.description.15"))
    episode_count: int = Field(
        DEFAULT_EPISODE_COUNT,
        description=_text_of("DramaCreateRequest.description.16").format(EPISODE_COUNT_MIN, EPISODE_COUNT_MAX),
        ge=EPISODE_COUNT_MIN,
        le=EPISODE_COUNT_MAX,
    )
    script_content: Optional[str] = Field(None, description=_text_of("DramaCreateRequest.description.17"))
    script_name: Optional[str] = Field(None, description=_text_of("DramaCreateRequest.description.18"))


class ScriptUpdateRequest(DramaBaseSchema):
    """Persist a manually edited Markdown or plain-text screenplay."""

    content: str = Field(..., description=_text_of("ScriptUpdateRequest.description"), min_length=1)
    file_name: Optional[str] = Field(
        None,
        description=_text_of("ScriptUpdateRequest.description.2"),
        max_length=255,
    )
    expected_source_hash: str = Field(
        ...,
        description=_text_of("ScriptUpdateRequest.description.3"),
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    confirm_invalidate: bool = Field(
        False,
        description=_text_of("ScriptUpdateRequest.description.4"),
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError(_text_of("validate_content.text"))
        if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise ValueError(_text_of("validate_content.text.2"))
        if not value.strip():
            raise ValueError(_text_of("validate_content.text.3"))
        if len(value.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError(_text_of("validate_content.text.4"))
        return value

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if (
            not cleaned
            or "/" in cleaned
            or "\\" in cleaned
            or any(ord(char) < 32 for char in cleaned)
        ):
            raise ValueError(_text_of("validate_file_name.text"))
        suffix = cleaned.rsplit(".", 1)[-1].lower() if "." in cleaned else ""
        if suffix not in {"md", "txt"}:
            raise ValueError(_text_of("validate_file_name.text.2"))
        return cleaned


class DramaConfigSchema(DramaBaseSchema):
    """
    创建时所用的参数配置 Schema
    """
    title_suggestion: str = Field(..., description=_text_of("DramaConfigSchema.description"))
    director_style: str = Field(DEFAULT_DIRECTOR_STYLE, description=_text_of("DramaConfigSchema.description.2"))
    style_pack: str = Field(DEFAULT_PACK_ID, description=_text_of("DramaConfigSchema.description.3"), max_length=40)
    shot_style: str = Field(DEFAULT_SHOT_STYLE, description=_text_of("DramaConfigSchema.description.4"))
    llm_model: str = Field(DEFAULT_LLM_MODEL, description=_text_of("DramaConfigSchema.description.5"))
    image_model: str = Field(DEFAULT_IMAGE_MODEL, description=_text_of("DramaConfigSchema.description.6"))
    video_model: str = Field(DEFAULT_VIDEO_MODEL, description=_text_of("DramaConfigSchema.description.7"))
    tts_model: str = Field(DEFAULT_TTS_MODEL, description=_text_of("DramaConfigSchema.description.8"))
    video_reference_mode: StoredVideoReferenceMode = Field(
        "auto", description=_text_of("DramaConfigSchema.description.9")
    )
    narration_delivery: Literal["use_tts", "post_production"] = Field("use_tts", description=_text_of("DramaConfigSchema.description.10"))
    creation_mode: Literal["drama", "narration", "ad", "film"] = Field("drama", description=_text_of("DramaConfigSchema.description.11"))
    ad_brief: Optional[dict] = Field(None, description=_text_of("DramaConfigSchema.description.12"))
    poetry_sources: List[str] = Field(default_factory=list, description=_text_of("DramaConfigSchema.description.13"))
    content_language: Literal["zh", "en", "vi"] = Field("zh", description=_text_of("DramaConfigSchema.description.14"))
    one_click: bool = Field(False, description=_text_of("DramaConfigSchema.description.15"))
    episode_count: int = Field(
        DEFAULT_EPISODE_COUNT,
        description=_text_of("DramaConfigSchema.description.16").format(EPISODE_COUNT_MIN, EPISODE_COUNT_MAX),
        ge=EPISODE_COUNT_MIN,
        le=EPISODE_COUNT_MAX,
    )
    script_content: Optional[str] = Field(None, description=_text_of("DramaConfigSchema.description.17"))
    script_name: Optional[str] = Field(None, description=_text_of("DramaConfigSchema.description.18"))

class ShotFeedbackRequest(DramaBaseSchema):
    """One "this shot came back wrong" report from the person watching the clip."""

    result: Literal["success", "partial", "failed"] = Field("failed", description=_text_of("ShotFeedbackRequest.description"))
    text: str = Field("", description=_text_of("ShotFeedbackRequest.description.2"), max_length=500)
    category: str = Field("", description=_text_of("ShotFeedbackRequest.description.3"), max_length=40)
    applied_fix: str = Field("", description=_text_of("ShotFeedbackRequest.description.4"), max_length=300)


class DramaTaskSummary(DramaBaseSchema):
    """Lightweight task row for the polled project list.

    The lobby renders only the id, stage, status and title, while a full
    DramaTaskResponse carries every generated asset — over a megabyte per poll
    once a few projects exist. Listing endpoints use this instead.
    """
    task_id: str = Field(..., description=_text_of("DramaTaskSummary.description"))
    current_stage: int = Field(..., description=_text_of("DramaTaskSummary.description.2"))
    stage_name: str = Field(..., description=_text_of("DramaTaskSummary.description.3"))
    status: str = Field(..., description=_text_of("DramaTaskSummary.description.4"))
    config: DramaConfigSchema = Field(..., description=_text_of("DramaTaskSummary.description.5"))
    video_url: Optional[str] = Field(None, description=_text_of("DramaTaskSummary.description.6"))
    stage_progress: Optional[Dict[str, Any]] = Field(None, description=_text_of("DramaTaskSummary.description.7"))
    fail_reason: Optional[str] = Field(None, description=_text_of("DramaTaskSummary.description.8"))


class DramaTaskResponse(DramaBaseSchema):
    """
    短剧任务状态响应 Schema
    """
    task_id: str = Field(..., description=_text_of("DramaTaskResponse.description"))
    current_stage: int = Field(..., description=_text_of("DramaTaskResponse.description.2"))
    stage_name: str = Field(..., description=_text_of("DramaTaskResponse.description.3"))
    status: str = Field(..., description=_text_of("DramaTaskResponse.description.4"))
    config: DramaConfigSchema = Field(..., description=_text_of("DramaTaskResponse.description.5"))
    assets: Dict[str, Any] = Field(..., description=_text_of("DramaTaskResponse.description.6"))
    workflow: Optional[Dict[str, Any]] = Field(None, description=_text_of("DramaTaskResponse.description.7"))
    chat_history: List[Dict[str, Any]] = Field(default_factory=list, description=_text_of("DramaTaskResponse.description.8"))
    logs: Dict[str, str] = Field(..., description=_text_of("DramaTaskResponse.description.9"))
    video_url: Optional[str] = Field(None, description=_text_of("DramaTaskResponse.description.10"))
    short_link: Optional[str] = Field(None, description=_text_of("DramaTaskResponse.description.11"))
    pr_content: Optional[str] = Field(None, description=_text_of("DramaTaskResponse.description.12"))
    stage_progress: Optional[Dict[str, Any]] = Field(None, description=_text_of("DramaTaskResponse.description.13"))
    fail_reason: Optional[str] = Field(None, description=_text_of("DramaTaskResponse.description.14"))

# -*- coding: utf-8 -*-
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, Dict, Any, Literal, List

from app.core.style_packs import DEFAULT_PACK_ID

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
    title_suggestion: str = Field(..., description="创意大纲/选题提示词", min_length=2)
    director_style: str = Field(DEFAULT_DIRECTOR_STYLE, description="导演视听风格，如 cyberpunk, retro, realistic")
    style_pack: Optional[str] = Field(
        None,
        description=(
            "风格锁：全片统一的画面质感包 (cinematic_realism / film_35mm / atom_punk / anime_2d_cel / anime_3d_cg)。"
            "更新配置时省略该字段表示沿用项目已有的风格锁。"
        ),
        max_length=40,
    )
    shot_style: str = Field(DEFAULT_SHOT_STYLE, description="运镜风格设定")
    llm_model: str = Field(DEFAULT_LLM_MODEL, description="选用的多模态语言大模型")
    image_model: str = Field(DEFAULT_IMAGE_MODEL, description="选用的文生图大模型")
    video_model: str = Field(DEFAULT_VIDEO_MODEL, description="选用的视频生成大模型")
    tts_model: str = Field(DEFAULT_TTS_MODEL, description="选用的语音配音大模型")
    video_reference_mode: EditableVideoReferenceMode = Field(
        "auto", description="运镜视频的参考输入模式（自动、首尾帧、多图/宫格或多模态参考）"
    )
    narration_delivery: Literal["use_tts", "post_production"] = Field(
        "use_tts", description="旁白交付方式：合成旁白配音，或留给后期配音（旁白不进入视频提示词）"
    )
    creation_mode: Literal["drama", "narration", "ad"] = Field(
        "drama", description="创作类型：剧情短剧、旁白解说、广告短片"
    )
    ad_brief: Optional[AdBrief] = Field(None, description="广告短片的产品简报（其它类型忽略）")
    content_language: Literal["zh", "en", "vi"] = Field(
        "zh", description="剧本内容语言：标题、钩子、台词、旁白、正文与画面描述用这种语言写"
    )
    one_click: bool = Field(False, description="是否一键成片模式")
    episode_count: int = Field(
        DEFAULT_EPISODE_COUNT,
        description=f"一次性生成的剧本集数 ({EPISODE_COUNT_MIN}-{EPISODE_COUNT_MAX})，视频按集逐集制作",
        ge=EPISODE_COUNT_MIN,
        le=EPISODE_COUNT_MAX,
    )
    script_content: Optional[str] = Field(None, description="手动上传的剧本文件内容")
    script_name: Optional[str] = Field(None, description="手动上传的剧本文件名")


class ScriptUpdateRequest(DramaBaseSchema):
    """Persist a manually edited Markdown or plain-text screenplay."""

    content: str = Field(..., description="完整剧本文本", min_length=1)
    file_name: Optional[str] = Field(
        None,
        description="可选的原始 .md/.txt 文件名",
        max_length=255,
    )
    expected_source_hash: str = Field(
        ...,
        description="编辑器加载时的剧本资源哈希，用于防止旧标签页覆盖新版本",
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    confirm_invalidate: bool = Field(
        False,
        description="确认归档并使当前剧本的下游制作资产失效",
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("剧本内容不能包含空字节")
        if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise ValueError("剧本内容包含不支持的控制字符")
        if not value.strip():
            raise ValueError("剧本内容不能为空")
        if len(value.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("剧本内容不能超过 2 MiB")
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
            raise ValueError("剧本文件名无效")
        suffix = cleaned.rsplit(".", 1)[-1].lower() if "." in cleaned else ""
        if suffix not in {"md", "txt"}:
            raise ValueError("剧本文件仅支持 .md 或 .txt")
        return cleaned


class DramaConfigSchema(DramaBaseSchema):
    """
    创建时所用的参数配置 Schema
    """
    title_suggestion: str = Field(..., description="创意大纲/选题提示词")
    director_style: str = Field(DEFAULT_DIRECTOR_STYLE, description="导演视听风格")
    style_pack: str = Field(DEFAULT_PACK_ID, description="风格锁：全片统一的画面质感包", max_length=40)
    shot_style: str = Field(DEFAULT_SHOT_STYLE, description="运镜风格设定")
    llm_model: str = Field(DEFAULT_LLM_MODEL, description="选用的多模态语言大模型")
    image_model: str = Field(DEFAULT_IMAGE_MODEL, description="选用的文生图大模型")
    video_model: str = Field(DEFAULT_VIDEO_MODEL, description="选用的视频生成大模型")
    tts_model: str = Field(DEFAULT_TTS_MODEL, description="选用的语音配音大模型")
    video_reference_mode: StoredVideoReferenceMode = Field(
        "auto", description="运镜视频的参考输入模式；响应兼容历史 first_frame 项目"
    )
    narration_delivery: Literal["use_tts", "post_production"] = Field("use_tts", description="旁白交付方式")
    creation_mode: Literal["drama", "narration", "ad"] = Field("drama", description="创作类型")
    ad_brief: Optional[dict] = Field(None, description="广告短片的产品简报")
    content_language: Literal["zh", "en", "vi"] = Field("zh", description="剧本内容语言")
    one_click: bool = Field(False, description="是否一键成片模式")
    episode_count: int = Field(
        DEFAULT_EPISODE_COUNT,
        description=f"一次性生成的剧本集数 ({EPISODE_COUNT_MIN}-{EPISODE_COUNT_MAX})，视频按集逐集制作",
        ge=EPISODE_COUNT_MIN,
        le=EPISODE_COUNT_MAX,
    )
    script_content: Optional[str] = Field(None, description="手动上传的剧本文件内容")
    script_name: Optional[str] = Field(None, description="手动上传的剧本文件名")

class ShotFeedbackRequest(DramaBaseSchema):
    """One "this shot came back wrong" report from the person watching the clip."""

    result: Literal["success", "partial", "failed"] = Field("failed", description="这次生成的结果")
    text: str = Field("", description="用自己的话描述问题，如「脸崩了」「手是六根手指」", max_length=500)
    category: str = Field("", description="可选：直接指定失败类型，留空则按描述归类", max_length=40)
    applied_fix: str = Field("", description="可选：本次生效的修正手段，连续两次有效会写入项目经验", max_length=300)


class DramaTaskSummary(DramaBaseSchema):
    """Lightweight task row for the polled project list.

    The lobby renders only the id, stage, status and title, while a full
    DramaTaskResponse carries every generated asset — over a megabyte per poll
    once a few projects exist. Listing endpoints use this instead.
    """
    task_id: str = Field(..., description="任务唯一 ID")
    current_stage: int = Field(..., description="当前所处步骤阶段 (0-9)")
    stage_name: str = Field(..., description="当前阶段名称")
    status: str = Field(..., description="状态: idle, running, paused, completed, failed")
    config: DramaConfigSchema = Field(..., description="创建时所用的参数配置")
    video_url: Optional[str] = Field(None, description="最终合成视频的播放链接")
    stage_progress: Optional[Dict[str, Any]] = Field(None, description="当前阶段执行进度")
    fail_reason: Optional[str] = Field(None, description="任务失败原因 (status=failed 时)")


class DramaTaskResponse(DramaBaseSchema):
    """
    短剧任务状态响应 Schema
    """
    task_id: str = Field(..., description="任务唯一 ID")
    current_stage: int = Field(..., description="当前所处步骤阶段 (0-9)")
    stage_name: str = Field(..., description="当前阶段名称")
    status: str = Field(..., description="状态: idle, running, paused, completed, failed")
    config: DramaConfigSchema = Field(..., description="创建时所用的参数配置")
    assets: Dict[str, Any] = Field(..., description="各步骤已生成的结构化资产")
    workflow: Optional[Dict[str, Any]] = Field(None, description="基于真实产物的八 Agent 流程引导")
    chat_history: List[Dict[str, Any]] = Field(default_factory=list, description="持久化用户与助手消息")
    logs: Dict[str, str] = Field(..., description="各步骤的执行日志与校验结果")
    video_url: Optional[str] = Field(None, description="最终合成视频的播放链接")
    short_link: Optional[str] = Field(None, description="宣发引流短链接")
    pr_content: Optional[str] = Field(None, description="宣发引流文案")
    stage_progress: Optional[Dict[str, Any]] = Field(None, description="当前阶段执行进度: stage/percent/label/status/calls/error")
    fail_reason: Optional[str] = Field(None, description="任务失败原因 (status=failed 时)")

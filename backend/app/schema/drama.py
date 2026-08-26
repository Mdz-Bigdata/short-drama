# -*- coding: utf-8 -*-
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Dict, Any, Literal


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

class DramaCreateRequest(DramaBaseSchema):
    """
    创建短剧任务的请求 Schema
    """
    title_suggestion: str = Field(..., description="创意大纲/选题提示词", min_length=2)
    director_style: str = Field("cyberpunk", description="导演视听风格，如 cyberpunk, retro, realistic")
    shot_style: str = Field("standard", description="运镜风格设定")
    llm_model: str = Field("deepseek", description="选用的多模态语言大模型")
    image_model: str = Field("seedance", description="选用的文生图大模型")
    video_model: str = Field("seedance2.0", description="选用的视频生成大模型")
    tts_model: str = Field("ElevenLabs", description="选用的语音配音大模型")
    video_reference_mode: EditableVideoReferenceMode = Field(
        "auto", description="运镜视频的参考输入模式（自动、首尾帧、多图/宫格或多模态参考）"
    )
    one_click: bool = Field(False, description="是否一键成片模式")
    episode_count: int = Field(3, description="一次性生成的剧本集数 (1-12)，视频按集逐集制作", ge=1, le=12)
    script_content: Optional[str] = Field(None, description="手动上传的剧本文件内容")
    script_name: Optional[str] = Field(None, description="手动上传的剧本文件名")

class DramaConfigSchema(DramaBaseSchema):
    """
    创建时所用的参数配置 Schema
    """
    title_suggestion: str = Field(..., description="创意大纲/选题提示词")
    director_style: str = Field("cyberpunk", description="导演视听风格")
    shot_style: str = Field("standard", description="运镜风格设定")
    llm_model: str = Field("deepseek", description="选用的多模态语言大模型")
    image_model: str = Field("seedance", description="选用的文生图大模型")
    video_model: str = Field("seedance2.0", description="选用的视频生成大模型")
    tts_model: str = Field("ElevenLabs", description="选用的语音配音大模型")
    video_reference_mode: StoredVideoReferenceMode = Field(
        "auto", description="运镜视频的参考输入模式；响应兼容历史 first_frame 项目"
    )
    one_click: bool = Field(False, description="是否一键成片模式")
    episode_count: int = Field(3, description="一次性生成的剧本集数 (1-12)，视频按集逐集制作", ge=1, le=12)
    script_content: Optional[str] = Field(None, description="手动上传的剧本文件内容")
    script_name: Optional[str] = Field(None, description="手动上传的剧本文件名")

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
    logs: Dict[str, str] = Field(..., description="各步骤的执行日志与校验结果")
    video_url: Optional[str] = Field(None, description="最终合成视频的播放链接")
    short_link: Optional[str] = Field(None, description="宣发引流短链接")
    pr_content: Optional[str] = Field(None, description="宣发引流文案")
    stage_progress: Optional[Dict[str, Any]] = Field(None, description="当前阶段执行进度: stage/percent/label/status/calls/error")
    fail_reason: Optional[str] = Field(None, description="任务失败原因 (status=failed 时)")

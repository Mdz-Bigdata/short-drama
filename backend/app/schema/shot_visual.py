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


class ShotVideoFailure(BaseModel):
    """供应商没给这张看板出片：分类、错误码、原话、下一步，以及发出去的分镜画面。"""
    kind: Literal["input_image_sensitive", "provider_error"] = "provider_error"
    kind_label: str = ""
    code: str = ""
    message: str = ""
    hint: str = ""
    panels: list[str] = Field(default_factory=list)
    scene_id: str = ""
    at: float | None = None


class ShotAsset(BaseModel):
    """这一镜用到的一个资产：分镜里画了它、视频里发了它的图(第几张)、改过之后是否待重做。"""
    kind: str = ""
    name: str = ""
    # 素材库元素 id 与绑定时的版本；只在项目里、不在素材库的资产为空串 / 0。
    element_id: str = ""
    element_version: int = 0
    # 视频提示词里的参考图序号(参考图N)；没进视频请求为空。
    image_number: int | None = None
    in_storyboard: bool = False
    in_video: bool = False
    stale: bool = False


class ShotVisualRecord(BaseModel):
    shot_id: int
    scene_id: str = ""
    # 全剧唯一的镜头编号(集·场·镜)：各场镜号都从 1 起，只靠 shot_id 分不清是哪一场的镜头。
    shot_uid: int = 0
    desc: str = ""
    dialogue: str = ""
    sound: str = ""
    settings: ShotVisualSettings
    settings_source: Literal["edited", "derived"]
    derived_notes: list[str] = Field(default_factory=list)
    image_url: str | None = None
    end_frame_url: str | None = None
    video_url: str | None = None
    # 换了音色后重配过的预览片段(画面同 video_url，声音是新配音)；成片仍按 video_url 和时间线合成。
    preview_url: str | None = None
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
    # 本镜所在看板最近一次没出片的原因(供应商拒单等)；出片后清除。
    failure: ShotVideoFailure | None = None
    # 本镜用到的资产(分镜绑定、分镜表点名、片段参考合并去重)，改了哪个资产就知道哪些镜头要重做。
    assets: list[ShotAsset] = Field(default_factory=list)
    # 样片：按什么分辨率出的(480p；空表示全分辨率)，是否已本地放大，是否已要求重出高清。
    draft_resolution: str = ""
    draft_upscaled: bool = False
    hd_retake: bool = False
    # 局部修：要求从第几秒往后重做(重跑第 5 阶段时执行)，以及区域修补的进度与结果。
    retake_from: float | None = None
    retaken_from: float | None = None
    repair: dict[str, Any] | None = None
    # 控制表：这一镜要保留的几件事各靠哪份素材(动作与运镜、开场站位、空间、外观、节奏、场地)，重复和缺的标出来。
    controls: list[dict[str, Any]] = Field(default_factory=list)


class ShotVideoPromptUpdate(BaseModel):
    """人工改写的视频提示词；``prompt`` 为空表示放弃改写，恢复自动编译。"""
    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(None, max_length=8000)


class ProjectVideoModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_model: str = Field(min_length=1, max_length=200)


class ShotRegenerateRequest(BaseModel):
    reason: str = Field("", max_length=300)


class DraftModeUpdate(BaseModel):
    """样片模式：第 5 阶段按 480p 出片，看过再逐镜出高清。"""
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ShotHdRequest(BaseModel):
    """样片转高清：本地放大(不花钱，偏软) 或 同提示词同种子按全分辨率重出(重跑第 5 阶段时执行)。"""
    model_config = ConfigDict(extra="forbid")

    mode: Literal["upscale", "regenerate"]


class ShotRetakeRequest(BaseModel):
    """从第几秒往后重做：之前的画面保留，只重出后面。"""
    model_config = ConfigDict(extra="forbid")

    from_seconds: float = Field(gt=0, le=60)
    note: str = Field("", max_length=300)


class RepairBox(BaseModel):
    """画面上的一块，都是 0–1 的比例：左上角 (x, y)，宽 w、高 h。"""
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class ShotRepairRequest(BaseModel):
    """区域修补：只改框出来的那一块，其余原样。"""
    model_config = ConfigDict(extra="forbid")

    box: RepairBox
    note: str = Field(min_length=1, max_length=300)
    start: float | None = Field(None, ge=0, le=60)
    end: float | None = Field(None, ge=0, le=60)


class VideoAdmissionRequest(BaseModel):
    """Re-assess with duration tiers the person has accepted; ``persist`` keeps them on the project."""
    confirmed_request_durations: list[dict[str, int]] = Field(default_factory=list, max_length=200)
    persist: bool = False


class ShotVisualWorkspaceResponse(BaseModel):
    task_id: str
    current_stage: int = 0
    running: bool = False
    # 首镜试拍的状态；没有试拍或整批已跑完时为空。
    pilot: dict[str, Any] | None = None
    video_model: str = ""
    provider_family: str = ""
    # 模型配置中心启用的视频模型，以及项目当前视频模型不能用的原因(空串表示可用)。
    enabled_video_models: list[str] = Field(default_factory=list)
    video_model_issue: str = ""
    # 项目原选的型号被配置中心的型号替换时的说明(不阻断)。
    video_model_note: str = ""
    duration_options: list[int] = Field(default_factory=list)
    camera_motions: list[dict[str, str]] = Field(default_factory=list)
    shot_types: list[dict[str, str]] = Field(default_factory=list)
    recipe_categories: list[dict[str, str]] = Field(default_factory=list)
    shots: list[ShotVisualRecord] = Field(default_factory=list)
    # 样片模式是否开着；当前视频模型能不能做区域修补(要能收参考视频)。
    draft_mode: bool = False
    repair_supported: bool = False

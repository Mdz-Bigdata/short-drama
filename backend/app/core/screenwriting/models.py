# -*- coding: utf-8 -*-
"""Structured contracts of the two-stage screenwriting pipeline.

Stage A (script plan) fixes the *content* of every shot once: boundary, cast,
verbatim utterances, source anchor and the visual adaptation text. Stage B
(visual authoring) only adds ``image_prompt`` / ``video_prompt`` and is merged
back by ``scene_id`` — the non-visual fields never pass through the second LLM
call, so they cannot drift.

Enum drift (``MEDIUM_SHOT`` / ``medium_shot``) is folded back onto the
vocabulary; out-of-vocabulary values degrade to a neutral default instead of
failing a whole episode, because both fields are only interpolated into
generation prompts downstream.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, create_model, model_validator

logger = logging.getLogger("app.core.screenwriting.models")

STRICT = ConfigDict(extra="forbid")
LENIENT = ConfigDict(extra="ignore")

ShotType = Literal[
    "Extreme Close-up",
    "Close-up",
    "Medium Close-up",
    "Medium Shot",
    "Medium Long Shot",
    "Long Shot",
    "Extreme Long Shot",
    "Over-the-shoulder",
    "Point-of-view",
]

CameraMotion = Literal[
    "Static",
    "Pan Left",
    "Pan Right",
    "Tilt Up",
    "Tilt Down",
    "Zoom In",
    "Zoom Out",
    "Push In",
    "Pull Out",
    "Truck Left",
    "Truck Right",
    "Pedestal Up",
    "Pedestal Down",
    "Orbit",
    "Tracking Shot",
    "Shake",
]

SHOT_TYPE_ZH: dict[str, str] = {
    "Extreme Close-up": "大特写",
    "Close-up": "特写",
    "Medium Close-up": "中近景",
    "Medium Shot": "中景",
    "Medium Long Shot": "中远景",
    "Long Shot": "全景",
    "Extreme Long Shot": "远景",
    "Over-the-shoulder": "过肩",
    "Point-of-view": "主观视角",
}

CAMERA_MOTION_ZH: dict[str, str] = {
    "Static": "固定",
    "Pan Left": "左摇",
    "Pan Right": "右摇",
    "Tilt Up": "上仰摇",
    "Tilt Down": "下俯摇",
    "Zoom In": "变焦推近",
    "Zoom Out": "变焦拉远",
    "Push In": "缓推",
    "Pull Out": "缓拉",
    "Truck Left": "左横移",
    "Truck Right": "右横移",
    "Pedestal Up": "升镜",
    "Pedestal Down": "降镜",
    "Orbit": "环绕",
    "Tracking Shot": "跟拍",
    "Shake": "手持晃动",
}

DEFAULT_SHOT_TYPE: ShotType = "Medium Shot"
DEFAULT_CAMERA_MOTION: CameraMotion = "Static"
DEFAULT_SCENE_SECONDS = 8


def _canon_key(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").split()).casefold()


_SHOT_TYPE_BY_KEY = {_canon_key(value): value for value in get_args(ShotType)}
_CAMERA_MOTION_BY_KEY = {_canon_key(value): value for value in get_args(CameraMotion)}
# Chinese aliases are accepted too: the project's own storyboard vocabulary is Chinese.
_SHOT_TYPE_BY_KEY.update({_canon_key(zh): en for en, zh in SHOT_TYPE_ZH.items()})
_CAMERA_MOTION_BY_KEY.update({_canon_key(zh): en for en, zh in CAMERA_MOTION_ZH.items()})


def normalize_shot_type(value: object) -> object:
    if not isinstance(value, str):
        return value
    hit = _SHOT_TYPE_BY_KEY.get(_canon_key(value))
    if hit is not None:
        return hit
    logger.warning("[Screenwriting] shot_type 无法归一，降级为 %s: %r", DEFAULT_SHOT_TYPE, value)
    return DEFAULT_SHOT_TYPE


def normalize_camera_motion(value: object) -> object:
    if not isinstance(value, str):
        return value
    hit = _CAMERA_MOTION_BY_KEY.get(_canon_key(value))
    if hit is not None:
        return hit
    logger.warning("[Screenwriting] camera_motion 无法归一，降级为 %s: %r", DEFAULT_CAMERA_MOTION, value)
    return DEFAULT_CAMERA_MOTION


def _none_to_list(value: object) -> object:
    return [] if value is None else value


def _none_to_text(value: object) -> object:
    return "" if value is None else value


# --------------------------------------------------------------------------- overview & assets


class Overview(BaseModel):
    """Project overview extracted from the source (or written from the director plan)."""

    model_config = LENIENT

    title: str = Field(default="", description="作品名，不含书名号")
    synopsis: str = Field(default="", description="150-250 字剧情概述")
    genre: str = Field(default="", description="题材类型")
    theme: str = Field(default="", description="一句话主题")
    world_setting: str = Field(default="", description="世界观与时代背景")


class CharacterAsset(BaseModel):
    model_config = LENIENT

    description: Annotated[str, BeforeValidator(_none_to_text)] = Field(
        default="", description="只写视觉描述：外貌、服装、标志物、色彩关键词"
    )
    voice_style: Annotated[str, BeforeValidator(_none_to_text)] = Field(default="", description="声音/语气风格")
    position: Annotated[str, BeforeValidator(_none_to_text)] = Field(
        default="", description="戏剧位置：女主角 / 男主角 / 反派 / 男配角 / 女配角 / 其它角色"
    )


class VisualAsset(BaseModel):
    model_config = LENIENT

    description: Annotated[str, BeforeValidator(_none_to_text)] = Field(default="", description="视觉描述")


class AssetInventory(BaseModel):
    """Characters / scenes / props that a shot may reference by name."""

    model_config = LENIENT

    characters: dict[str, CharacterAsset] = Field(default_factory=dict)
    scenes: dict[str, VisualAsset] = Field(default_factory=dict)
    props: dict[str, VisualAsset] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_lists(cls, data: object) -> object:
        """Tolerate the ``[{"name": ..., ...}]`` shape a model may emit instead of a mapping."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for key in ("characters", "scenes", "props"):
            value = data.get(key)
            if value is None:
                data[key] = {}
            elif isinstance(value, list):
                mapping: dict[str, Any] = {}
                for item in value:
                    if isinstance(item, dict):
                        name = str(item.get("name") or "").strip()
                        if name:
                            mapping[name] = {k: v for k, v in item.items() if k != "name"}
                    elif isinstance(item, str) and item.strip():
                        mapping[item.strip()] = {}
                data[key] = mapping
        return data


# --------------------------------------------------------------------------- episode ledger


class EpisodeOutlineDraft(BaseModel):
    """One planned episode: title, hook and the beats the script must cover."""

    model_config = STRICT

    title: str = Field(min_length=1, description="吸引人的短标题")
    hook: str = Field(min_length=1, description="集尾钩子：这一刀为什么切在这里、给观众留了什么悬念")
    story_beats: list[str] = Field(min_length=1, description="本集故事节点，按顺序")
    next_episode_teaser: str | None = Field(default=None, description="下集预告语；末集后续未知可为 null")


class AnchoredEpisodeDraft(EpisodeOutlineDraft):
    """Source-anchored variant: the episode ends where ``end_anchor`` appears in the source."""

    end_anchor: str = Field(min_length=2, description="本集结尾处的原文片段，10~30 字，逐字摘抄且在原文中唯一")


class OutlinePlanDraft(BaseModel):
    model_config = STRICT

    episodes: list[EpisodeOutlineDraft] = Field(min_length=1)


class AnchoredPlanDraft(BaseModel):
    model_config = STRICT

    episodes: list[AnchoredEpisodeDraft] = Field(min_length=1)


class LedgerEntry(BaseModel):
    """Persisted episode ledger row — the single source of truth for hooks and outlines."""

    model_config = LENIENT

    episode: int = Field(ge=1)
    title: str = ""
    hook: str = ""
    story_beats: list[str] = Field(default_factory=list)
    next_episode_teaser: str | None = None
    source_range: dict[str, int] | None = Field(
        default=None, description="{start, end} 在归一化源文中的字符偏移；无源文时为 null"
    )
    ledger_status: Literal["planned", "written", "stale"] = "planned"

    def outline(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "hook": self.hook,
            "story_beats": list(self.story_beats),
            "next_episode_teaser": self.next_episode_teaser,
        }


# --------------------------------------------------------------------------- stage A: script plan


UtteranceKind = Literal["dialogue", "voiceover"]


class Utterance(BaseModel):
    """One spoken item; list order is the order inside the shot."""

    model_config = STRICT

    kind: UtteranceKind = Field(description="dialogue=角色发声（必带 speaker）；voiceover=无说话人的旁白")
    speaker: str | None = Field(default=None, description="说话角色名；dialogue 必填，voiceover 必须为 null")
    text: str = Field(min_length=1, description="发声内容，逐字保留")
    delivery: str | None = Field(
        default=None,
        description="表演标注（可选）：情绪类型-强度 / 语速 / 停顿与重音 / 生理表现，如「压抑-克制 / 慢 / 尾音下沉」",
    )

    @model_validator(mode="before")
    @classmethod
    def _blank_speaker_is_none(cls, data: object) -> object:
        if isinstance(data, dict):
            speaker = data.get("speaker")
            if isinstance(speaker, str) and not speaker.strip():
                data = {**data, "speaker": None}
            kind = data.get("kind")
            if isinstance(kind, str):
                folded = kind.strip().lower()
                if folded in {"台词", "对白", "dialog", "dialogue"}:
                    data = {**data, "kind": "dialogue"}
                elif folded in {"旁白", "画外音", "vo", "voice-over", "voiceover", "narration"}:
                    data = {**data, "kind": "voiceover"}
        return data

    @model_validator(mode="after")
    def _kind_matches_speaker(self) -> "Utterance":
        if self.kind == "dialogue":
            if not self.speaker:
                raise ValueError("dialogue 发声必须带非空 speaker")
        elif self.speaker is not None:
            raise ValueError("voiceover 发声不得带 speaker")
        return self


class SceneContent(BaseModel):
    """Stage A output for one shot: everything except the visual prompts."""

    model_config = STRICT

    scene_id: str = Field(min_length=1, description="分镜 ID，格式 E{集}S{两位序号}，拆分后可带 _{子序号}")
    duration_seconds: int = Field(default=DEFAULT_SCENE_SECONDS, ge=1, le=60, description="分镜时长（秒）")
    segment_break: bool = Field(default=False, description="是否为场景切换点（地点 / 时间的重大变化）")
    setting: Annotated[str, BeforeValidator(_none_to_text)] = Field(
        default="", description="场景标题行：地点 时间 内景/外景，如「市井长街 黄昏 外景」"
    )
    characters_in_scene: Annotated[list[str], BeforeValidator(_none_to_list)] = Field(
        default_factory=list, description="出场角色名（须来自候选角色表）"
    )
    scenes: Annotated[list[str], BeforeValidator(_none_to_list)] = Field(
        default_factory=list, description="出场场景名（须来自候选场景表）"
    )
    props: Annotated[list[str], BeforeValidator(_none_to_list)] = Field(
        default_factory=list, description="出场道具名（须来自候选道具表）"
    )
    scene_description: Annotated[str, BeforeValidator(_none_to_text)] = Field(
        default="", description="视觉改编描述：动作、神态、环境、光影，只写画面可见内容，不内嵌口播"
    )
    utterances: Annotated[list[Utterance], BeforeValidator(_none_to_list)] = Field(
        default_factory=list, description="分镜内有序发声：台词（dialogue）与旁白（voiceover）"
    )
    source_text: Annotated[str, BeforeValidator(_none_to_text)] = Field(
        default="", description="逐字原文摘录（追溯锚，不朗读；无把握可留空）"
    )
    needs_replan: bool = Field(default=False, description="口播装不进任何合法时长档时由系统标记，人工重拆")


class ScriptPlan(BaseModel):
    """Stage A output for one episode."""

    model_config = LENIENT

    title: str = Field(default="", description="本集标题")
    scenes: list[SceneContent] = Field(min_length=1, description="分镜内容列表")


# --------------------------------------------------------------------------- stage B: visual layer


class Composition(BaseModel):
    model_config = STRICT

    shot_type: Annotated[ShotType, BeforeValidator(normalize_shot_type)] = Field(
        default=DEFAULT_SHOT_TYPE, description="景别"
    )
    lighting: Annotated[str, BeforeValidator(_none_to_text)] = Field(default="", description="光源、方向、色温")
    ambiance: Annotated[str, BeforeValidator(_none_to_text)] = Field(default="", description="可观察的环境效果")


class ImagePrompt(BaseModel):
    model_config = STRICT

    scene: str = Field(min_length=1, description="单帧静态画面描述")
    composition: Composition = Field(default_factory=Composition)


class VideoPrompt(BaseModel):
    model_config = STRICT

    action: Annotated[str, BeforeValidator(_none_to_text)] = Field(default="", description="该时长内的运动与变化")
    camera_motion: Annotated[CameraMotion, BeforeValidator(normalize_camera_motion)] = Field(
        default=DEFAULT_CAMERA_MOTION, description="镜头运动"
    )
    ambiance_audio: Annotated[str, BeforeValidator(_none_to_text)] = Field(default="", description="画内环境音")


class SceneVisual(BaseModel):
    """Stage B output for one shot: alignment key plus the two prompts."""

    model_config = STRICT

    scene_id: str = Field(min_length=1, description="对齐锚：必须逐字等于分镜内容里的 scene_id")
    image_prompt: ImagePrompt
    video_prompt: VideoPrompt


class VisualScript(BaseModel):
    model_config = LENIENT

    title: str = Field(default="", description="本集标题（可选）")
    scenes: list[SceneVisual] = Field(min_length=1)


# --------------------------------------------------------------------------- merged episode script


class DramaScene(SceneContent):
    """A finished shot: stage A content plus the stage B visual layer."""

    image_prompt: ImagePrompt
    video_prompt: VideoPrompt


class EpisodeScript(BaseModel):
    model_config = LENIENT

    episode: int = Field(ge=1)
    title: str = ""
    hook: str | None = None
    next_episode_teaser: str | None = None
    scenes: list[DramaScene] = Field(default_factory=list)


class VisualMergeError(ValueError):
    """The visual layer does not cover the script plan exactly (missing / orphan / duplicate ids)."""


CONTENT_ONLY_FIELDS: frozenset[str] = frozenset()


def merge_visual_into_scenes(content_scenes: list[dict[str, Any]], visual_scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach visual prompts to script-plan scenes by ``scene_id`` (order follows the plan).

    Every plan scene must get exactly one visual; visuals for unknown ids, duplicate
    ids on either side and visuals missing a prompt all raise ``VisualMergeError``.
    """
    visual_by_id: dict[str, dict[str, Any]] = {}
    for visual in visual_scenes:
        if not isinstance(visual, dict):
            raise VisualMergeError(f"视觉层条目必须是对象: {visual!r}")
        sid = visual.get("scene_id")
        if not isinstance(sid, str) or not sid:
            raise VisualMergeError(f"视觉层条目缺少 scene_id: {visual!r}")
        if sid in visual_by_id:
            raise VisualMergeError(f"视觉层 scene_id 重复: {sid}")
        visual_by_id[sid] = visual

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for content in content_scenes:
        if not isinstance(content, dict):
            raise VisualMergeError(f"分镜内容条目必须是对象: {content!r}")
        sid = content.get("scene_id")
        if not isinstance(sid, str) or not sid:
            raise VisualMergeError(f"分镜内容条目缺少 scene_id: {content!r}")
        if sid in seen:
            raise VisualMergeError(f"分镜内容 scene_id 重复: {sid}")
        seen.add(sid)
        visual = visual_by_id.get(sid)
        if visual is None:
            raise VisualMergeError(f"分镜 {sid} 缺少对应的视觉层")
        if "image_prompt" not in visual or "video_prompt" not in visual:
            raise VisualMergeError(f"视觉层分镜 {sid} 缺少必要的视觉字段")
        scene = {key: value for key, value in content.items() if key not in CONTENT_ONLY_FIELDS}
        scene["image_prompt"] = visual["image_prompt"]
        scene["video_prompt"] = visual["video_prompt"]
        merged.append(scene)

    orphans = sorted(set(visual_by_id) - seen)
    if orphans:
        raise VisualMergeError(f"视觉层含分镜内容中不存在的 scene_id: {orphans}")
    return merged


# --------------------------------------------------------------------------- duration-constrained models


def _coerce_digit_string(value: object) -> object:
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


def duration_literal(supported_durations: list[int]) -> object:
    values = tuple(sorted({int(value) for value in supported_durations}))
    if not values:
        raise ValueError("supported_durations 为空，无法构造 duration 枚举约束")
    return Annotated[Literal[values], BeforeValidator(_coerce_digit_string)]


def build_script_plan_model(supported_durations: list[int]) -> type[ScriptPlan]:
    """``ScriptPlan`` whose ``duration_seconds`` is restricted to the model's legal clip lengths."""
    scene = create_model(
        "SceneContent",
        __base__=SceneContent,
        duration_seconds=(duration_literal(supported_durations), Field(description="分镜时长（秒），必须取支持档位")),
    )
    return create_model("ScriptPlan", __base__=ScriptPlan, scenes=(list[scene], Field(min_length=1)))


__all__ = [
    "AnchoredEpisodeDraft",
    "AnchoredPlanDraft",
    "AssetInventory",
    "CAMERA_MOTION_ZH",
    "CameraMotion",
    "CharacterAsset",
    "Composition",
    "DEFAULT_CAMERA_MOTION",
    "DEFAULT_SCENE_SECONDS",
    "DEFAULT_SHOT_TYPE",
    "DramaScene",
    "EpisodeOutlineDraft",
    "EpisodeScript",
    "ImagePrompt",
    "LedgerEntry",
    "OutlinePlanDraft",
    "Overview",
    "SHOT_TYPE_ZH",
    "SceneContent",
    "SceneVisual",
    "ScriptPlan",
    "ShotType",
    "Utterance",
    "VideoPrompt",
    "VisualAsset",
    "VisualMergeError",
    "VisualScript",
    "build_script_plan_model",
    "duration_literal",
    "merge_visual_into_scenes",
    "normalize_camera_motion",
    "normalize_shot_type",
]

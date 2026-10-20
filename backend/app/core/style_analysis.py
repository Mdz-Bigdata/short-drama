"""A style lock read off a reference image.

The person shows the look they want — a film still, a frame of an animation, a
painting — and a model that can see describes it in fixed fields: the medium,
the light, the palette with hex colours, the camera and its grain, what to
always do and what never to do. That description becomes a project-only style
lock: the same object the built-in locks are, inheriting from the built-in lock
of the same medium whatever the image cannot say (sound policy, situational
negatives, anti-leak rules), so every image and video prompt is compiled from it
exactly as from any other lock.

Nothing here calls a model; ``analysis_prompt`` is what to send and
``parse_profile`` reads what came back.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core import style_packs
from app.core.screenwriting.structured_llm import extract_json_object

Medium = Literal["live_action", "anime_2d", "anime_3d", "mixed"]
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

# The built-in lock each medium inherits from.
_BASE_FOR_MEDIUM = {"live_action": "cinematic_realism", "anime_2d": "anime_2d_cel", "anime_3d": "anime_3d_cg", "mixed": "cinematic_realism"}


class StyleAnalysisError(ValueError):
    """The model's answer could not be read as a style profile."""


class ProfileColour(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    hex: str
    role: str = Field("", max_length=80)

    @field_validator("hex")
    @classmethod
    def hex_colour(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value.startswith("#"):
            value = "#" + value
        if not _HEX.match(value):
            raise ValueError("colour must be #RRGGBB")
        return value.upper()


class StyleProfile(BaseModel):
    """What a reference image says about a look, in the fields a style lock needs."""

    name: str = Field(min_length=1, max_length=40)
    medium: Medium
    summary: str = Field(min_length=1, max_length=300)
    lighting: str = Field(min_length=1, max_length=200)
    palette: list[ProfileColour] = Field(default_factory=list, max_length=6)
    contrast: str = Field("中等", max_length=20)
    temperature: str = Field("中性", max_length=20)
    saturation: str = Field("中等", max_length=20)
    camera_body: str = Field("", max_length=120)
    lens: str = Field("", max_length=120)
    grain: str = Field("", max_length=60)
    texture: str = Field("", max_length=200)
    composition: str = Field("", max_length=200)
    era: str = Field("", max_length=80)
    mood: str = Field("", max_length=120)
    lock: list[str] = Field(min_length=1, max_length=5)
    positives: list[str] = Field(default_factory=list, max_length=12)
    negatives: list[str] = Field(default_factory=list, max_length=12)
    style_caption: str = Field(min_length=10, max_length=600)

    @field_validator("lock", "positives", "negatives")
    @classmethod
    def clean_phrases(cls, values: list[str]) -> list[str]:
        cleaned = [re.sub(r"\s+", " ", str(v)).strip()[:160] for v in values if str(v).strip()]
        return list(dict.fromkeys(cleaned))


_FIELDS = (
    "name（2–12 字的风格名）、medium（live_action 真人实拍 / anime_2d 二维动画 / anime_3d 三维动画 / mixed 混合）、"
    "summary（一句话概括这种质感）、lighting（光源方向、软硬、时段）、palette（3–6 个主色，每个含 name、hex（#RRGGBB）、role：它落在画面里的什么东西上）、"
    "contrast / temperature / saturation（各用两三个字：高 / 中等 / 低、冷 / 中性 / 暖 …）、camera_body、lens、grain（机身、焦段与景深、颗粒）、"
    "texture（材质与笔触，如胶片颗粒、赛璐璐平涂、厚涂）、composition（构图习惯）、era（年代感，没有就留空）、mood（情绪基调）、"
    "lock（3–5 条锁定短语，中英文并写，每条是“特征A + 特征B”的形式，这是每一张图都必须复现的东西）、"
    "positives（最多 12 条应当出现的画面特征）、negatives（最多 12 条必须避免的特征，如与该风格冲突的画法）、"
    "style_caption（一段 60–200 字、可直接放进生图提示词开头的风格锚定句，中英文并写）"
)


def analysis_prompt(hint: str = "") -> tuple[str, str]:
    """(system, user) for a vision model looking at one reference image."""
    system = (
        "你是影视美术指导，负责把一张参考图的画面风格拆解成可复用的风格锁。"
        "只描述画面的视觉风格（媒介、光线、色彩、镜头、质感、构图），不要描述图中的具体人物、情节或文字内容；"
        "不要编造图中看不到的东西。只输出一个 JSON 对象。"
    )
    user = (
        "请分析这张参考图的画面风格，输出一个 JSON 对象，字段如下：\n"
        f"{_FIELDS}。\n"
        "要求：hex 必须从画面中实际取色；lock 与 style_caption 只写风格，不写人物身份、服装细节或剧情；"
        "不要出现任何真实人名、作品名或品牌名。"
    )
    if hint.strip():
        user += f"\n使用者的补充说明（仅作参考，以画面为准）：{hint.strip()[:300]}"
    return system, user


def parse_profile(answer: str) -> StyleProfile:
    data = extract_json_object(answer or "")
    if not data:
        raise StyleAnalysisError("模型没有返回可读的风格描述（不是 JSON）；请换一个支持看图的模型再试")
    try:
        return StyleProfile.model_validate(data)
    except ValidationError as exc:
        fields = "、".join(sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")}))
        raise StyleAnalysisError(f"风格描述缺少或写错了字段：{fields}") from exc


def custom_pack_id(task_id: str) -> str:
    return "custom_" + hashlib.sha1(str(task_id).encode("utf-8")).hexdigest()[:12]


def to_pack(profile: StyleProfile, *, task_id: str) -> style_packs.StylePack:
    """A project-only style lock: the profile's look over the built-in lock of the same medium."""
    base = style_packs.get_pack(_BASE_FOR_MEDIUM[profile.medium]) or style_packs.get_pack(style_packs.DEFAULT_PACK_ID)
    assert base is not None
    knobs = {"contrast": profile.contrast, "temperature": profile.temperature, "saturation": profile.saturation, "vignette": base.palette.knobs.get("vignette", "轻微")}
    colours = [style_packs.PaletteColour(name=c.name, hex=c.hex, bound_to=c.role[:80]) for c in profile.palette]
    tone = " + ".join(part for part in (profile.mood, profile.lighting, "9:16") if part)
    positives = list(dict.fromkeys([*profile.positives, *(p for p in (profile.texture, profile.composition) if p)]))[:30]
    return base.model_copy(update={
        "id": custom_pack_id(task_id),
        "name": f"参考图·{profile.name}"[:60],
        "medium": profile.medium,
        "summary": profile.summary,
        "lock": profile.lock,
        "tone_default": tone[:300],
        "camera": base.camera.model_copy(update={
            "body": profile.camera_body or base.camera.body, "lens": profile.lens or base.camera.lens,
            "grain": profile.grain or base.camera.grain,
        }),
        "palette": base.palette.model_copy(update={"through_colours": colours, "knobs": knobs}),
        "positives": positives,
        "negatives": list(dict.fromkeys([*profile.negatives, *base.negatives]))[:40],
        "extension_restatement": f"全片保持「{profile.name}」的画面质感与色彩基调不变。"[:300],
        "style_caption": profile.style_caption,
        "aliases": [],
    })


def preview(profile: StyleProfile, pack: style_packs.StylePack) -> dict[str, Any]:
    """What the person sees before applying: the profile and the lock it would become."""
    return {"profile": profile.model_dump(), "pack": style_packs.describe(pack), "base_pack": _BASE_FOR_MEDIUM[profile.medium]}


def pack_from_config(config: Mapping[str, Any] | None) -> style_packs.StylePack | None:
    """The stored custom lock of a project, when its ``style_pack`` names it."""
    pack = style_packs.resolve_pack(config)
    return pack if pack.id.startswith("custom_") else None


__all__ = ["StyleAnalysisError", "StyleProfile", "analysis_prompt", "custom_pack_id", "pack_from_config", "parse_profile", "preview", "to_pack"]

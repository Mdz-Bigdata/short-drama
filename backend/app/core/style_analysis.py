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
from app.core import prompt_data


_WORDING_FILE = "style_analysis"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/style_analysis.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

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
    contrast: str = Field(_text_of("StyleProfile.contrast"), max_length=20)
    temperature: str = Field(_text_of("StyleProfile.temperature"), max_length=20)
    saturation: str = Field(_text_of("StyleProfile.saturation"), max_length=20)
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
    _text_of("module.fields")
)


def analysis_prompt(hint: str = "") -> tuple[str, str]:
    """(system, user) for a vision model looking at one reference image."""
    system = (
        _text_of("analysis_prompt.system")
    )
    user = (
        _text_of("analysis_prompt.user").format(_FIELDS)
    )
    if hint.strip():
        user += _text_of("analysis_prompt.text").format(hint.strip()[:300])
    return system, user


def parse_profile(answer: str) -> StyleProfile:
    data = extract_json_object(answer or "")
    if not data:
        raise StyleAnalysisError(_text_of("parse_profile.text"))
    try:
        return StyleProfile.model_validate(data)
    except ValidationError as exc:
        fields = "、".join(sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")}))
        raise StyleAnalysisError(_text_of("parse_profile.text.2").format(fields)) from exc


def custom_pack_id(task_id: str) -> str:
    return "custom_" + hashlib.sha1(str(task_id).encode("utf-8")).hexdigest()[:12]


def to_pack(profile: StyleProfile, *, task_id: str) -> style_packs.StylePack:
    """A project-only style lock: the profile's look over the built-in lock of the same medium."""
    base = style_packs.get_pack(_BASE_FOR_MEDIUM[profile.medium]) or style_packs.get_pack(style_packs.DEFAULT_PACK_ID)
    assert base is not None
    knobs = {"contrast": profile.contrast, "temperature": profile.temperature, "saturation": profile.saturation, "vignette": base.palette.knobs.get("vignette", _text_of("to_pack.knobs.vignette"))}
    colours = [style_packs.PaletteColour(name=c.name, hex=c.hex, bound_to=c.role[:80]) for c in profile.palette]
    tone = " + ".join(part for part in (profile.mood, profile.lighting, "9:16") if part)
    positives = list(dict.fromkeys([*profile.positives, *(p for p in (profile.texture, profile.composition) if p)]))[:30]
    return base.model_copy(update={
        "id": custom_pack_id(task_id),
        "name": _text_of("to_pack.update.name").format(profile.name)[:60],
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
        "extension_restatement": _text_of("to_pack.update.extension_restatement").format(profile.name)[:300],
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

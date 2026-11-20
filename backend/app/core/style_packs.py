# -*- coding: utf-8 -*-
"""Style packs: the look a whole production is locked to, as data.

A production commits to one look and every prompt restates it verbatim — that is the
only thing that keeps a series from drifting between clips. A pack holds what the look
is made of:

- the **style lock**: sentences copied into every prompt and never rewritten;
- a **tone layer** formula that changes per segment (genre overlay, tension, ending beat,
  aspect, time of day) so the lock does not make everything feel the same;
- a **camera kit** (body, lens, stock, grain) with purpose-keyed alternates;
- **palette rules**: through-colours with HEX values and the tonal knobs;
- **positive boosters** for the medium (de-AI wording for live action, line and shading
  words for animation), **negatives** in tiers, and **anti-leak** guards for references
  drawn in a different medium (a colour card, a design sheet, a storyboard, a white model);
- **sound defaults** and the sentence an extension must repeat.

The packs are the project's own writing. The two engine documents they follow are
described in ``docs/style-packs/RESEARCH.md``.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core import prompt_data

Medium = Literal["live_action", "anime_2d", "anime_3d", "mixed"]
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
# What each pack says (names, locks, colours, guards, captions, aliases) and the sentences the
# rules below write: app/data/prompt/style_packs.json.
_WORDING = "style_packs"


def _says(key: str, /, **values: object) -> str:
    """A sentence of the packs' wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _word(key: str) -> str:
    """A word of the packs' wording table (a separator, a marker, a fallback)."""
    return prompt_data.text(_WORDING, key)


class CameraKit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=120)
    lens: str = Field(max_length=120)
    stock: str = Field("", max_length=120)
    grain: str = Field("", max_length=60)
    # purpose → the alternate rig a shot may swap to (action, emotion, tension, chase…)
    alternates: dict[str, str] = Field(default_factory=dict)
    per_shot_swap_allowed: bool = False


class PaletteColour(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    # The object the colour is bound to. "阴影" or "氛围" is not an object: a colour that
    # is not tied to something visible drifts.
    bound_to: str = Field("", max_length=80)


class PaletteRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    through_colours: list[PaletteColour] = Field(default_factory=list, max_length=6)
    card_size: int = Field(13, ge=3, le=24)
    carried: int = Field(7, ge=0, le=24)
    knobs: dict[str, str] = Field(default_factory=dict)  # contrast / temperature / saturation / vignette …
    mask_dark_hex: str = Field("#1A1610", pattern=r"^#[0-9A-Fa-f]{6}$")
    mask_light_hex: str = Field("#E8E8DC", pattern=r"^#[0-9A-Fa-f]{6}$")


class SoundDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bgm_policy: Literal["none", "white_noise", "single_instrument"] = "none"
    ambience_allowed: bool = True
    signature_sfx: list[str] = Field(default_factory=list, max_length=20)
    closing_sentence: str = Field(prompt_data.text(_WORDING, "closing_sentence"), max_length=300)


class StylePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    name: str = Field(max_length=60)
    medium: Medium
    summary: str = Field(max_length=300)
    lock: list[str] = Field(min_length=1, max_length=20)
    tone_slots: list[str] = Field(default_factory=list, max_length=8)
    tone_default: str = Field("", max_length=300)
    camera: CameraKit
    palette: PaletteRules = Field(default_factory=PaletteRules)
    positives: list[str] = Field(default_factory=list, max_length=30)
    negatives: list[str] = Field(default_factory=list, max_length=40)
    situational_negatives: dict[str, list[str]] = Field(default_factory=dict)
    anti_leak: list[str] = Field(default_factory=list, max_length=12)
    extension_restatement: str = Field(max_length=300)
    # 画质段(《运镜提示词》Pa2)：这个媒介下「画质好」具体指什么——材质、光影物理、发光体、运动模糊。
    quality: str = Field("", max_length=400)
    sound: SoundDefaults = Field(default_factory=SoundDefaults)
    # What the Ark request's ``style_caption`` field carries for this look.
    style_caption: str = Field(max_length=600)
    # Words that name this pack in a free-text style setting.
    aliases: list[str] = Field(default_factory=list, max_length=30)

    @property
    def lock_text(self) -> str:
        lines = (_says("lock_line", line=line) if index else line for index, line in enumerate(self.lock))
        return _word("lock_header") + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# The packs

# Pa2 的画质段、常驻负向词、情境负向词：都是数据(app/data/prompt/iron_rules.json)，这里只读。
LIVE_ACTION_QUALITY = str(prompt_data.value("iron_rules", "quality")["live_action"])
ANIME_2D_QUALITY = str(prompt_data.value("iron_rules", "quality")["anime_2d"])
ANIME_3D_QUALITY = str(prompt_data.value("iron_rules", "quality")["anime_3d"])

_LIVE_ACTION_NEGATIVES = list(prompt_data.words("iron_rules", "live_action_negatives"))
_LIVE_ACTION_POSITIVES = list(prompt_data.words("iron_rules", "live_action_positives"))
_CONTINUITY_NEGATIVES = list(prompt_data.words("iron_rules", "continuity_negatives"))
_SITUATIONAL = {key: list(items) for key, items in prompt_data.value("iron_rules", "situational_negatives").items()}


def _pack(
    pack_id: str, *, medium: Medium, quality: str, per_shot_swap_allowed: bool,
    positives: Sequence[str] = (), negatives: Sequence[str] = (), situational: Mapping[str, list[str]] | None = None,
) -> StylePack:
    """One built-in pack: its words from the table, after the shared live-action lists it builds on.

    ``positives`` / ``negatives`` / ``situational`` are what the pack's own entries are appended to
    (the live-action packs start from iron_rules.json); ``camera`` and ``palette`` in the table carry
    only what the pack sets, so everything else keeps the model's default.
    """
    words = prompt_data.value(_WORDING, "packs")[pack_id]
    return StylePack(
        id=pack_id,
        name=words["name"],
        medium=medium,
        summary=words["summary"],
        lock=list(words["lock"]),
        tone_slots=list(words["tone_slots"]),
        tone_default=words["tone_default"],
        camera=CameraKit(**words["camera"], per_shot_swap_allowed=per_shot_swap_allowed),
        palette=PaletteRules.model_validate(words["palette"]),
        positives=[*positives, *words["positives"]],
        negatives=[*negatives, *words["negatives"]],
        situational_negatives={**(situational or {}), **words["situational_negatives"]},
        anti_leak=list(words["anti_leak"]),
        extension_restatement=words["extension_restatement"],
        quality=quality,
        sound=SoundDefaults(bgm_policy="none", ambience_allowed=True, signature_sfx=list(words["signature_sfx"])),
        style_caption=words["style_caption"],
        aliases=list(words["aliases"]),
    )


FILM_35MM = _pack(
    "film_35mm", medium="live_action", quality=LIVE_ACTION_QUALITY, per_shot_swap_allowed=False,
    positives=_LIVE_ACTION_POSITIVES, negatives=_LIVE_ACTION_NEGATIVES, situational=_SITUATIONAL,
)
ATOM_PUNK = _pack(
    "atom_punk", medium="live_action", quality=LIVE_ACTION_QUALITY, per_shot_swap_allowed=True,
    positives=_LIVE_ACTION_POSITIVES, negatives=_LIVE_ACTION_NEGATIVES, situational=_SITUATIONAL,
)
ANIME_2D_CEL = _pack("anime_2d_cel", medium="anime_2d", quality=ANIME_2D_QUALITY, per_shot_swap_allowed=False)
ANIME_3D_CG = _pack("anime_3d_cg", medium="anime_3d", quality=ANIME_3D_QUALITY, per_shot_swap_allowed=True)
CINEMATIC_REALISM = _pack(
    "cinematic_realism", medium="live_action", quality=LIVE_ACTION_QUALITY, per_shot_swap_allowed=True,
    positives=_LIVE_ACTION_POSITIVES, negatives=_LIVE_ACTION_NEGATIVES, situational=_SITUATIONAL,
)

_PACKS: tuple[StylePack, ...] = (CINEMATIC_REALISM, FILM_35MM, ATOM_PUNK, ANIME_2D_CEL, ANIME_3D_CG)
DEFAULT_PACK_ID = CINEMATIC_REALISM.id


# Project-only locks read off a reference image (app/core/style_analysis.py). They live on the
# project's config; resolving one registers it here so code that only holds the id finds it too.
_CUSTOM: dict[str, StylePack] = {}
_CUSTOM_LOCK = threading.Lock()


def list_packs() -> list[StylePack]:
    return list(_PACKS)


def register_custom(pack: StylePack) -> StylePack:
    with _CUSTOM_LOCK:
        _CUSTOM[pack.id] = pack
    return pack


def get_pack(pack_id: str) -> StylePack | None:
    key = str(pack_id or "").strip().lower().replace("-", "_")
    builtin = next((pack for pack in _PACKS if pack.id == key), None)
    if builtin is not None:
        return builtin
    with _CUSTOM_LOCK:
        return _CUSTOM.get(key)


def _custom_from_config(config: Mapping[str, Any]) -> StylePack | None:
    raw = config.get("custom_style_pack")
    if not isinstance(raw, Mapping) or str(config.get("style_pack") or "") != str(raw.get("id") or ""):
        return None
    try:
        return register_custom(StylePack.model_validate(dict(raw)))
    except ValueError:
        return None


def resolve_pack(config: Mapping[str, Any] | None) -> StylePack:
    """The pack a task is locked to: an explicit ``style_pack``, else the one its style words name.

    An unknown or empty setting is the project default, which reproduces the look every
    production had before packs existed.
    """
    config = config or {}
    custom = _custom_from_config(config)
    if custom is not None:
        return custom
    explicit = next((pack for pack in _PACKS if pack.id == str(config.get("style_pack") or "").strip().lower().replace("-", "_")), None)
    if explicit is not None:
        return explicit
    text = " ".join(str(config.get(key) or "") for key in ("style_pack", "visual_style", "director_style")).lower()
    if text.strip():
        # Longest alias wins so 「3D国漫」 is not claimed by 「国漫」 of another pack.
        ranked = sorted(((alias, pack) for pack in _PACKS for alias in pack.aliases), key=lambda item: -len(item[0]))
        for alias, pack in ranked:
            if alias.lower() in text:
                return pack
    return CINEMATIC_REALISM


# ---------------------------------------------------------------------------------------------
# Tone layer, palette card, negatives, rules


def tone_line(pack: StylePack, values: Mapping[str, str] | None = None) -> str:
    """The per-segment tone line: the pack's slots filled from ``values``, defaults elsewhere."""
    values = values or {}
    filled = [str(values.get(slot) or "").strip() for slot in pack.tone_slots]
    if not any(filled):
        return pack.tone_default
    defaults = [part.strip() for part in pack.tone_default.split("+")]
    parts = [filled[index] or (defaults[index] if index < len(defaults) else "") for index in range(len(pack.tone_slots))]
    return " + ".join(part for part in parts if part)


# 场景里本来就有的字(匾额、对联、招牌)要留着；禁的是叠加上去的。只写「无文字」模型会去擦背景。
SIGNAGE_RULE = prompt_data.text("iron_rules", "signage_rule")


def style_lock_block(pack: StylePack, tone: Mapping[str, str] | str | None = None) -> str:
    """The first layer of every prompt: the lock verbatim, then this segment's tone line."""
    line = tone if isinstance(tone, str) and tone.strip() else tone_line(pack, tone if isinstance(tone, Mapping) else None)
    return _says("lock_block", lock=pack.lock_text, tone=line)


class PaletteCard(BaseModel):
    """One scene group's colour card: N colours, each bound to a visible object."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=120)
    colours: list[PaletteColour] = Field(min_length=3, max_length=24)
    carried: int = Field(0, ge=0)

    @property
    def top(self) -> list[PaletteColour]:
        return self.colours[:5]


def build_palette_card(
    pack: StylePack, *, project: str, episode: int, segment: int, subject: str,
    new_colours: Sequence[PaletteColour], carried: Sequence[PaletteColour] = (),
) -> PaletteCard:
    """Carry the through-colours (and whatever the previous card carried), then add the new ones.

    Every colour must be bound to a visible object; a colour bound to nothing, or to an
    abstraction such as 阴影 / 氛围, is refused.
    """
    colours: list[PaletteColour] = []
    seen: set[str] = set()
    for colour in (*pack.palette.through_colours, *carried, *new_colours):
        if not colour.bound_to.strip() or colour.bound_to.strip() in _ABSTRACT_BINDINGS:
            raise ValueError(_says("unbound_colour", name=colour.name, bound_to=colour.bound_to or _word("empty_binding")))
        if colour.hex.upper() in seen:
            continue
        seen.add(colour.hex.upper())
        colours.append(colour)
    if len(colours) > pack.palette.card_size:
        raise ValueError(_says("card_too_big", limit=pack.palette.card_size, count=len(colours)))
    carried_count = len({c.hex.upper() for c in (*pack.palette.through_colours, *carried)})
    title = _says("card_title", project=project, episode=episode, segment=segment, subject=subject)
    return PaletteCard(title=title, colours=colours, carried=carried_count)


_ABSTRACT_BINDINGS = frozenset(prompt_data.words(_WORDING, "abstract_bindings"))


def palette_lines(card: PaletteCard, card_ref: str = "") -> list[str]:
    """The three-part palette instruction: card anchor, the strict-N sentence, top HEX inline."""
    strict = _says("palette_strict", count=len(card.colours))
    entries = (_says("palette_entry", bound_to=c.bound_to, name=c.name, hex=c.hex) for c in card.top)
    inline = _word("palette_entry_separator").join(entries)
    lines = [_says("palette_anchor", card_ref=card_ref, strict=strict) if card_ref else _says("palette_plain", strict=strict)]
    if inline:
        lines.append(_says("palette_main", entries=inline))
    return lines


def negatives_for(pack: StylePack, situations: Iterable[str] = (), extra: Iterable[str] = ()) -> list[str]:
    """Base negatives, then the situational add-ons that apply, then per-film custom items; no duplicates."""
    # 每个镜头都带的连续性负面词(空间重构、比例畸变……)，不分画风；排在最前，截断的地方(延长段只取前 10 条)也留得住。
    terms: list[str] = [*_CONTINUITY_NEGATIVES, *pack.negatives]
    for situation in situations:
        terms.extend(pack.situational_negatives.get(situation, []))
    terms.extend(str(item).strip() for item in extra if str(item).strip())
    return list(dict.fromkeys(terms))


# Reference kinds whose medium is not the finished frame: each needs its anti-leak guard.
_LEAK_KINDS: dict[str, str] = {str(kind): str(name) for kind, name in prompt_data.value(_WORDING, "leak_kinds").items()}

# 具名铁律：规则名与模板(可带 {subjects} / {restatement})，见 app/data/prompt/iron_rules.json。
IRON_RULES: dict[str, tuple[str, str]] = {
    key: (str(name), str(template)) for key, (name, template) in prompt_data.value("iron_rules", "iron_rules").items()
}


def iron_rules(
    pack: StylePack, *, subjects: Sequence[str] = (), reference_kinds: Iterable[str] = (), rule_ids: Iterable[str] = (),
) -> list[str]:
    """Named rules for one prompt: the requested ones, the multi-person rule when two or more subjects
    are named, the pack's style rule, and an anti-leak rule for every non-final-medium reference kind."""
    wanted = list(dict.fromkeys(rule_ids))
    if len(subjects) >= 2 and "multi_person" not in wanted:
        wanted.append("multi_person")
    lines: list[str] = []
    for rule_id in wanted:
        if rule_id not in IRON_RULES:
            raise KeyError(f"unknown iron rule: {rule_id}")
        name, template = IRON_RULES[rule_id]
        named = _word("subject_separator").join(subjects) or _word("default_subject")
        body = template.format(subjects=named, restatement=pack.extension_restatement)
        lines.append(_says("named_rule", name=name, body=body))
    lines.append(_says("style_rule", terms=" + ".join(pack.negatives[:prompt_data.number(_WORDING, "style_rule_terms")])))
    kinds = {_LEAK_KINDS[kind] for kind in reference_kinds if kind in _LEAK_KINDS}
    for guard in pack.anti_leak:
        if guard.split(_word("anti_leak_marker"))[0] in kinds:
            lines.append(guard)
    return lines


def caption_for(pack: StylePack) -> str:
    return pack.style_caption


def image_style_line(pack: StylePack, *, lighting: str = "", aspect_ratio: str = "9:16") -> str:
    """The style sentence a still prompt carries: the pack's own anchor, never a fixed photoreal one."""
    lighting_part = _says("image_lighting", lighting=lighting.strip()) if lighting.strip() else ""
    return _says("image_style", caption=pack.style_caption, lighting=lighting_part, aspect_ratio=aspect_ratio)


_NON_REALISTIC_CLAUSE = prompt_data.text(_WORDING, "non_realistic_clause")


def identity_negative(pack: StylePack, base: str) -> str:
    """The de-identification negatives, minus the anti-animation clause when the pack is animated.

    The clause bans anime, cartoon and 3D renders outright, which is right for live action and
    exactly wrong for a 2D or 3D drama: it would fight the pack's own look.
    """
    if pack.medium == "live_action" or _NON_REALISTIC_CLAUSE not in base:
        return base
    head = base.split(_NON_REALISTIC_CLAUSE)[0].rstrip(_word("clause_trim"))
    return head + ")" if base.startswith("(") and not head.endswith(")") else head


def describe(pack: StylePack) -> dict[str, Any]:
    """What the API and the settings UI show for a pack."""
    return {
        "id": pack.id, "name": pack.name, "medium": pack.medium, "summary": pack.summary,
        "lock": list(pack.lock), "tone_slots": list(pack.tone_slots), "tone_default": pack.tone_default,
        "camera": pack.camera.model_dump(), "through_colours": [c.model_dump() for c in pack.palette.through_colours],
        "negatives": list(pack.negatives), "sound": pack.sound.model_dump(),
    }


__all__ = [
    "ANIME_2D_CEL", "ANIME_2D_QUALITY", "ANIME_3D_CG", "ANIME_3D_QUALITY", "ATOM_PUNK", "CINEMATIC_REALISM", "DEFAULT_PACK_ID",
    "FILM_35MM", "IRON_RULES", "LIVE_ACTION_QUALITY",
    "CameraKit", "PaletteCard", "PaletteColour", "PaletteRules", "SoundDefaults", "StylePack",
    "build_palette_card", "caption_for", "describe", "get_pack", "identity_negative", "image_style_line",
    "SIGNAGE_RULE", "iron_rules", "list_packs", "negatives_for", "register_custom",
    "palette_lines", "resolve_pack", "style_lock_block", "tone_line",
]

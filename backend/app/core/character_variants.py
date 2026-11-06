"""Derived looks of a character: the same person at another age, in another outfit, hurt, transformed.

A variant is an actor element of its own — with its own reference images — that
names the character it derives from. It takes over that character's look where
the story calls for it: a shot or scene that mentions one of its trigger words
(``少年``, ``婚纱``, ``受伤后``), or an episode inside the variant's range. Where
nothing calls for it, the base character's look stands. The variant never
becomes a character of its own: the cast, the dialogue and the voice stay the
base character's.

A look made from one of the script's costumes (``source`` is ``LOOK_SOURCE``)
is the same person dressed and made up differently: only the clothes and the
wounds change, so the base character's face stays in the text. It is rebuilt from
the script until someone edits it (``edited``), and retired when the script no
longer calls for it (``retired``): it keeps its image but is never worn.

Variant facts live on the element's metadata under ``variant``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.core.face_card import parse_face_card, render_face_card

VARIANT_KEY = "variant"
MAX_TRIGGERS = 12
LOOK_SOURCE = "costume"


class VariantError(ValueError):
    """The variant facts do not describe a usable derived look."""


def _clean_spans(raw: Any) -> list[list[int]]:
    """Episode ranges as sorted ``[first, last]`` pairs; anything unusable is dropped."""
    spans: list[list[int]] = []
    for pair in raw if isinstance(raw, (list, tuple)) else ():
        try:
            first, last = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 1 <= first <= last:
            spans.append([first, last])
    return sorted(spans)


def clean_variant(payload: Mapping[str, Any], *, element_name: str = "") -> dict[str, Any]:
    """Validated variant facts: the base character, a label, trigger words, optional episode ranges."""
    base = str(payload.get("of") or "").strip()
    if not base:
        raise VariantError("衍生形象必须指明来源角色")
    if element_name and base == element_name.strip():
        raise VariantError("衍生形象不能以自己为来源角色")
    label = str(payload.get("label") or "").strip()[:40]
    raw = payload.get("triggers") or []
    if isinstance(raw, str):
        raw = re.split(r"[、，,/\s]+", raw)
    triggers = list(dict.fromkeys(str(t).strip()[:20] for t in raw if str(t).strip()))[:MAX_TRIGGERS]
    if label and label not in triggers:
        triggers.insert(0, label)
    episodes = None
    spans = _clean_spans(payload.get("spans"))
    start, end = payload.get("episode_from"), payload.get("episode_to")
    if start not in (None, "") or end not in (None, ""):
        try:
            first = int(start) if start not in (None, "") else 1
            last = int(end) if end not in (None, "") else first
        except (TypeError, ValueError) as exc:
            raise VariantError("集数范围必须是整数") from exc
        if first < 1 or last < first:
            raise VariantError("集数范围无效：起始集要 ≥ 1 且不大于结束集")
        episodes = [first, last]
    elif spans:
        episodes = [spans[0][0], max(span[1] for span in spans)]
    if not triggers and episodes is None:
        raise VariantError("至少给一个触发词或一个集数范围，否则这个形象永远不会被用上")
    facts: dict[str, Any] = {"of": base, "label": label, "triggers": triggers, "episodes": episodes}
    # The form edits one range: scattered ranges only survive while that outer range is unchanged.
    if spans and episodes == [spans[0][0], max(span[1] for span in spans)]:
        facts["spans"] = spans
    if str(payload.get("source") or "") == LOOK_SOURCE:
        facts["source"] = LOOK_SOURCE
    for key in ("outfit", "makeups", "starts", "edited"):
        if payload.get(key):
            facts[key] = payload[key]
    return facts


def variant_of(element: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = element.get("metadata") if isinstance(element.get("metadata"), Mapping) else {}
    facts = metadata.get(VARIANT_KEY)
    return dict(facts) if isinstance(facts, Mapping) and str(facts.get("of") or "").strip() else None


def split(elements: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Actor elements that are characters, and the variants grouped under the character they derive from."""
    bases: list[dict[str, Any]] = []
    variants: dict[str, list[dict[str, Any]]] = {}
    for element in elements:
        facts = variant_of(element)
        if facts is None:
            bases.append(dict(element))
        elif not facts.get("retired"):
            variants.setdefault(str(facts["of"]).strip(), []).append({**element, VARIANT_KEY: facts})
    return bases, variants


def is_look(element: Mapping[str, Any]) -> bool:
    """Whether this actor element is a character dressed in one of the script's costumes."""
    return (variant_of(element) or {}).get("source") == LOOK_SOURCE


def is_current_look(element: Mapping[str, Any]) -> bool:
    """A costume look the script still calls for."""
    return is_look(element) and not (variant_of(element) or {}).get("retired")


def worn_names(element: Mapping[str, Any]) -> set[str]:
    """Every catalog entry this drawn look already shows: itself, its outfit and its makeup."""
    facts = element.get(VARIANT_KEY) or variant_of(element) or {}
    return {str(element.get("name") or ""), str(facts.get("outfit") or ""), *(str(name) for name in facts.get("makeups") or [])} - {""}


def episode_of(scene_id: str) -> int | None:
    match = re.match(r"^E(\d+)", str(scene_id or ""))
    return int(match.group(1)) if match else None


def _trigger_hit(variant: Mapping[str, Any], text: str) -> int:
    """Length of the longest trigger the text contains (0 when none), so 婚纱礼服 beats 婚纱."""
    facts = variant.get(VARIANT_KEY) or {}
    words = [*facts.get("triggers", []), str(variant.get("name") or "")]
    return max((len(word) for word in words if len(word) >= 2 and word in text), default=0)


def scene_of(scene_id: str) -> int | None:
    match = re.match(r"^E\d+S(\d+)", str(scene_id or ""))
    return int(match.group(1)) if match else None


def _span_width(variant: Mapping[str, Any], episode: int, scene: int | None = None) -> int | None:
    """Width of the narrowest range of this variant holding the episode; None when none does.

    ``starts`` is [episode, scene] for a look that begins partway through an episode: earlier scenes don't wear it.
    """
    facts = variant.get(VARIANT_KEY) or {}
    starts = facts.get("starts")
    if starts and scene is not None and int(starts[0]) == episode and scene < int(starts[1]):
        return None
    spans = facts.get("spans") or ([facts["episodes"]] if facts.get("episodes") else [])
    widths = [
        int(span[1]) - int(span[0]) for span in spans
        if isinstance(span, (list, tuple)) and len(span) == 2 and int(span[0]) <= episode <= int(span[1])
    ]
    return min(widths) if widths else None


def _narrowest(variants: Iterable[Mapping[str, Any]], episode: int, scene: int | None) -> dict[str, Any] | None:
    """The look holding this moment: one that began partway through this episode first (the change has happened),
    then the narrowest range, then the one with more makeup."""
    holding = [(variant, _span_width(variant, episode, scene)) for variant in variants]
    holding = [pair for pair in holding if pair[1] is not None]
    if not holding:
        return None

    def rank(pair: tuple[Mapping[str, Any], int]) -> tuple[bool, int, int]:
        facts = pair[0].get(VARIANT_KEY) or {}
        starts = facts.get("starts")
        began_here = bool(starts) and scene is not None and int(starts[0]) == episode
        return (not began_here, pair[1], -len(facts.get("makeups") or []))

    return dict(min(holding, key=rank)[0])


def _by_trigger(variants: list[Mapping[str, Any]], text: str, episode: int | None, scene: int | None = None) -> dict[str, Any] | None:
    """The look the text names. An outfit can be on several looks (with and without a wound): the episode settles it."""
    hits = [(variant, _trigger_hit(variant, text)) for variant in variants or []]
    longest = max((hit for _variant, hit in hits), default=0)
    if longest <= 0:
        return None
    named = [variant for variant, hit in hits if hit == longest]
    if episode is not None:
        held = _narrowest(named, episode, scene)
        if held is not None:
            return held
    return dict(named[0])


def pick(variants: list[Mapping[str, Any]], *, text: str = "", episode: int | None = None, scene: int | None = None) -> dict[str, Any] | None:
    """The look the story calls for: a mentioned trigger, then the narrowest episode range, then the one outfit
    that names no episodes; None keeps the base look. A look that only adds makeup is never the default."""
    if not variants:
        return None
    named = _by_trigger(variants, text, episode, scene)
    if named is not None:
        return named
    if episode is not None:
        held = _narrowest(variants, episode, scene)
        if held is not None:
            return held
    outfits = [
        variant for variant in variants
        if (facts := variant.get(VARIANT_KEY) or {}).get("source") == LOOK_SOURCE and not facts.get("episodes") and not facts.get("makeups")
    ]
    return dict(outfits[0]) if len(outfits) == 1 else None


def triggered(variants: list[Mapping[str, Any]], text: str, episode: int | None = None, scene: int | None = None) -> dict[str, Any] | None:
    """A variant the text names outright (no episode fallback): what one shot asks for."""
    return _by_trigger(variants, text, episode, scene)


def apply(actor: Mapping[str, Any], variant: Mapping[str, Any] | None) -> dict[str, Any]:
    """The actor entry wearing the variant's look; name, cast and voice stay the character's."""
    if variant is None:
        return dict(actor)
    facts = variant.get(VARIANT_KEY) or {}
    description = str(variant.get("description") or "").strip()
    if description and facts.get("source") == LOOK_SOURCE:
        # 妆造只换衣服和妆效：脸还是这个人的，设定里原来那身衣服不再写。
        face = render_face_card(parse_face_card(str(actor.get("description") or "")), include_other=False)
        worn = description if description.startswith("妆效：") else f"服装：{description}"
        description = f"{face}；{worn}" if face else description
    return {
        **actor,
        "description": description or actor.get("description") or "",
        "image_url": variant.get("image_url") or actor.get("image_url") or "",
        "variant": facts.get("label") or str(variant.get("name") or ""),
        "variant_element_id": variant.get("id"),
    }


__all__ = [
    "LOOK_SOURCE", "MAX_TRIGGERS", "VARIANT_KEY", "VariantError", "apply", "clean_variant", "episode_of", "is_current_look", "is_look", "pick", "scene_of", "split",
    "triggered", "variant_of", "worn_names",
]

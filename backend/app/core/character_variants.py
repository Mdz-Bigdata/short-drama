"""Derived looks of a character: the same person at another age, in another outfit, hurt, transformed.

A variant is an actor element of its own — with its own reference images — that
names the character it derives from. It takes over that character's look where
the story calls for it: a shot or scene that mentions one of its trigger words
(``少年``, ``婚纱``, ``受伤后``), or an episode inside the variant's range. Where
nothing calls for it, the base character's look stands. The variant never
becomes a character of its own: the cast, the dialogue and the voice stay the
base character's.

Variant facts live on the element's metadata under ``variant``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

VARIANT_KEY = "variant"
MAX_TRIGGERS = 12


class VariantError(ValueError):
    """The variant facts do not describe a usable derived look."""


def clean_variant(payload: Mapping[str, Any], *, element_name: str = "") -> dict[str, Any]:
    """Validated variant facts: the base character, a label, trigger words, an optional episode range."""
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
    if not triggers and episodes is None:
        raise VariantError("至少给一个触发词或一个集数范围，否则这个形象永远不会被用上")
    return {"of": base, "label": label, "triggers": triggers, "episodes": episodes}


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
        else:
            variants.setdefault(str(facts["of"]).strip(), []).append({**element, VARIANT_KEY: facts})
    return bases, variants


def episode_of(scene_id: str) -> int | None:
    match = re.match(r"^E(\d+)", str(scene_id or ""))
    return int(match.group(1)) if match else None


def _trigger_hit(variant: Mapping[str, Any], text: str) -> int:
    """Length of the longest trigger the text contains (0 when none), so 婚纱礼服 beats 婚纱."""
    facts = variant.get(VARIANT_KEY) or {}
    words = [*facts.get("triggers", []), str(variant.get("name") or "")]
    return max((len(word) for word in words if len(word) >= 2 and word in text), default=0)


def pick(variants: list[Mapping[str, Any]], *, text: str = "", episode: int | None = None) -> dict[str, Any] | None:
    """The look the story calls for: a mentioned trigger first, then an episode range; None keeps the base look."""
    if not variants:
        return None
    by_trigger = sorted(((v, _trigger_hit(v, text)) for v in variants), key=lambda pair: -pair[1])
    if by_trigger and by_trigger[0][1] > 0:
        return dict(by_trigger[0][0])
    if episode is not None:
        for variant in variants:
            span = (variant.get(VARIANT_KEY) or {}).get("episodes")
            if isinstance(span, list) and len(span) == 2 and span[0] <= episode <= span[1]:
                return dict(variant)
    return None


def triggered(variants: list[Mapping[str, Any]], text: str) -> dict[str, Any] | None:
    """A variant the text names outright (no episode fallback): what one shot asks for."""
    best = max(variants or [], key=lambda v: _trigger_hit(v, text), default=None)
    return dict(best) if best is not None and _trigger_hit(best, text) > 0 else None


def apply(actor: Mapping[str, Any], variant: Mapping[str, Any] | None) -> dict[str, Any]:
    """The actor entry wearing the variant's look; name, cast and voice stay the character's."""
    if variant is None:
        return dict(actor)
    facts = variant.get(VARIANT_KEY) or {}
    return {
        **actor,
        "description": str(variant.get("description") or "").strip() or actor.get("description") or "",
        "image_url": variant.get("image_url") or actor.get("image_url") or "",
        "variant": facts.get("label") or str(variant.get("name") or ""),
        "variant_element_id": variant.get("id"),
    }


__all__ = ["MAX_TRIGGERS", "VARIANT_KEY", "VariantError", "apply", "clean_variant", "episode_of", "pick", "split", "triggered", "variant_of"]

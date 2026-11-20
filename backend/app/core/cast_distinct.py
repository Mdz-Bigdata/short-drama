# -*- coding: utf-8 -*-
"""Two characters of one drama written with the same face.

A cast reads as different people when the faces differ, not only the hair and the clothes. This
compares what is *written* about each character's bone structure and features: the option words of
the character studio (face shape, eyes, brows, nose, lips …) slot by slot, and, for faces written
freely, how many of their fragments are the very same words. Two characters who agree on nearly
every slot both of them state, and carry no mark of their own, are reported as a hint on the
character page.

It reads text only: no picture is compared, no model is called, and nothing is blocked. Tables,
limits and sentences are data (``app/data/prompt/cast_distinct.json``); the slot vocabulary is the
studio's own (``face_sculpt.json``), so two characters built from one preset are what it catches first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from typing import Any, Mapping, Sequence

from app.core import prompt_data
from app.core.face_card import FaceCard, parse_face_card

_DATA = "cast_distinct"
_TERM_SPLIT = re.compile(r"[、，,；;]")


def _data() -> Mapping[str, Any]:
    return prompt_data.load(_DATA)


def _limit(key: str) -> float:
    return float(_data()["limits"][key])


@lru_cache(maxsize=1)
def _vocabulary() -> dict[str, tuple[str, ...]]:
    """Slot → the words that name one of its options, longest first so 「杏眼偏长」 is not read as 「杏眼」."""
    controls = {str(control.get("key")): control for control in prompt_data.load("face_sculpt")["controls"]}
    table: dict[str, tuple[str, ...]] = {}
    for slot in _data()["slots"]:
        control = controls.get(str(slot)) or {}
        words = [
            _TERM_SPLIT.split(str(option.get("phrase") or option.get("label") or ""))[0].strip()
            for option in control.get("options") or []
        ]
        table[str(slot)] = tuple(sorted({word for word in words if len(word) >= 2}, key=len, reverse=True))
    return table


def reset() -> None:
    _vocabulary.cache_clear()


@dataclass(frozen=True)
class Alike:
    first: str
    second: str
    item: str
    note: str


def _face_text(card: FaceCard) -> str:
    return "；".join([*card.bone, *card.features])


def slots_of(card: FaceCard) -> dict[str, str]:
    """What the card says in each slot, by the studio's option words; a slot nobody wrote is absent."""
    text = _face_text(card)
    found: dict[str, str] = {}
    for slot, words in _vocabulary().items():
        word = next((word for word in words if word in text), "")
        if word:
            found[slot] = word
    return found


def _marked(card: FaceCard) -> bool:
    text = "；".join([*card.bone, *card.features, *card.skin])
    return any(str(word) in text for word in _data()["mark_words"])


def _fragments(card: FaceCard) -> set[str]:
    return {re.sub(r"\s+", "", fragment) for fragment in [*card.bone, *card.features] if fragment.strip()}


def compare(first: tuple[str, FaceCard], second: tuple[str, FaceCard]) -> Alike | None:
    """The hint for one pair, or ``None`` when their written faces differ enough or either carries its own mark."""
    data = _data()
    joiner = str(data["joiner"])
    (name_a, card_a), (name_b, card_b) = first, second
    if _marked(card_a) != _marked(card_b):
        return None
    slots_a, slots_b = slots_of(card_a), slots_of(card_b)
    shared = [slot for slot in slots_a if slot in slots_b]
    same = [slot for slot in shared if slots_a[slot] == slots_b[slot]]
    item = str(data["item"]).format(first=name_a, second=name_b)
    labels = data["slot_labels"]
    if len(same) >= _limit("min_same_slots") and len(same) / len(shared) >= _limit("min_agreement"):
        other = [slot for slot in shared if slot not in same]
        differs = (str(data["differs_some"]).format(slots=joiner.join(str(labels[slot]) for slot in other))
                   if other else str(data["differs_none"]))
        note = str(data["note_slots"]).format(
            slots=joiner.join(str(labels[slot]) for slot in same), words=joiner.join(slots_a[slot] for slot in same), differs=differs,
        )
        return Alike(name_a, name_b, item, note)
    pieces_a, pieces_b = _fragments(card_a), _fragments(card_b)
    if min(len(pieces_a), len(pieces_b)) >= _limit("min_fragments"):
        common = pieces_a & pieces_b
        share = len(common) / max(len(pieces_a), len(pieces_b))
        if share >= _limit("fragment_overlap"):
            note = str(data["note_fragments"]).format(share=round(share * 100), words=joiner.join(sorted(common)[:6]))
            return Alike(name_a, name_b, item, note)
    return None


def too_alike(cast: Sequence[tuple[str, str]]) -> list[Alike]:
    """Every pair of ``(name, face text)`` written with the same face, in cast order, within the limits."""
    cards = [(name, parse_face_card(text)) for name, text in cast[: int(_limit("characters"))] if str(text or "").strip()]
    cards = [(name, card) for name, card in cards if card.bone or card.features]
    found = [hit for pair in combinations(cards, 2) if (hit := compare(*pair)) is not None]
    return found[: int(_limit("risks"))]


__all__ = ["Alike", "compare", "reset", "slots_of", "too_alike"]

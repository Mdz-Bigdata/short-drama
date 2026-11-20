# -*- coding: utf-8 -*-
"""What "燃一点" or "压抑" actually changes in a shot list.

A director's brief arrives as a feeling, not as parameters. This turns the feeling
into the seven things a storyboard can act on — how the camera tends to move, how
dense the effects are, how fast the cutting is, which shot sizes dominate, how the
frame is composed, how it is lit, and what the sound does — so the same word means
the same thing every time it is used.

A brief has one **primary** feeling and up to two **secondary** ones. The primary
sets the tone and wins every contest; the secondaries only bend the numbers
(roughly 70 / 15 / 15, or 70 / 30 with a single secondary). Feelings that pull
against each other (hot-blooded against oppressive, healing against tragic) are not
merged: the primary stays, the conflicting secondary is dropped and reported.

Nothing here calls a model: the same brief always decodes to the same numbers.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core import prompt_data

# The feelings, the paragraph the storyboard writer is given and why a feeling is dropped:
# app/data/prompt/creative_intent.json.
_WORDING = "creative_intent"


def _says(key: str, /, **values: object) -> str:
    """A sentence of the brief's wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _word(key: str) -> str:
    """A word of the brief's wording table (a separator)."""
    return prompt_data.text(_WORDING, key)


# Shot-size families the distribution is expressed in.
SIZE_BANDS = ("wide", "medium", "close")


@dataclass(frozen=True)
class Intent:
    """One feeling, and the seven offsets it applies."""

    id: str
    name: str
    triggers: tuple[str, ...]
    camera: str                  # how the camera tends to move
    vfx_density: float           # share of shots carrying a visible effect, 0-1
    rhythm: float                # multiplier on shot length: <1 cuts faster
    sizes: tuple[float, float, float]   # wide / medium / close share, sums to 1
    composition: str
    lighting: str
    sound: str
    # Feelings this one cannot be blended with.
    conflicts: tuple[str, ...] = ()


# The feelings, their trigger words and the seven offsets each applies, in the order they are
# matched and fallen back on: app/data/prompt/creative_intent.json.
INTENTS: tuple[Intent, ...] = tuple(
    Intent(
        str(row["id"]), str(row["name"]), tuple(str(word) for word in row["triggers"]),
        camera=str(row["camera"]), vfx_density=float(row["vfx_density"]), rhythm=float(row["rhythm"]),
        sizes=tuple(float(share) for share in row["sizes"]),
        composition=str(row["composition"]), lighting=str(row["lighting"]), sound=str(row["sound"]),
        conflicts=tuple(str(other) for other in row["conflicts"]),
    )
    for row in prompt_data.value(_WORDING, "intents")
)
_BY_ID = {intent.id: intent for intent in INTENTS}
PRIMARY_WEIGHT = 0.7
SECONDARY_WEIGHT_ONE = 0.3
SECONDARY_WEIGHT_TWO = 0.15
MAX_SECONDARY = 2


@dataclass
class IntentPlan:
    """The decoded brief: what the shot list should come out like."""

    primary: Intent
    secondary: list[Intent] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)   # (intent id, why)
    vfx_density: float = 0.0
    rhythm: float = 1.0
    sizes: tuple[float, float, float] = (0.33, 0.34, 0.33)

    @property
    def names(self) -> list[str]:
        return [self.primary.name, *(intent.name for intent in self.secondary)]

    def shot_seconds(self, base: float) -> float:
        """A base shot length under this brief, never outside what a clip can be."""
        return round(max(1.0, base * self.rhythm), 1)

    def camera_line(self, scene_key: str = "") -> str:
        """How the camera tends to move here. Told about a scene, it leads with a different option from its neighbours.

        Given one list every scene, a model takes its first item every time. The choice follows the scene's own number,
        so a rerun asks the same question and neighbouring scenes differ.
        """
        separator, label = _word("list_separator"), _word("camera_label_separator")
        options = [item.split(label)[-1].strip() for item in self.primary.camera.split(separator) if item.strip()]
        if not scene_key or len(options) < 2:
            return _says("camera_plain", camera=self.primary.camera)
        number = re.search(r"(\d+)$", scene_key)
        lead = (int(number.group(1)) if number else zlib.crc32(scene_key.encode("utf-8"))) % len(options)
        rest = separator.join(option for index, option in enumerate(options) if index != lead)
        return _says("camera_lead", lead=options[lead], rest=rest)

    def brief(self, scene_key: str = "") -> str:
        """The paragraph the storyboard writer is given."""
        separator = _word("list_separator")
        mix = separator.join(
            _says("size_share", label=label, percent=round(share * 100))
            for label, share in zip(prompt_data.words(_WORDING, "size_labels"), self.sizes)
        )
        lines = [
            _says("feeling", primary=self.primary.name)
            + (_says("feeling_secondary", names=separator.join(intent.name for intent in self.secondary)) if self.secondary else ""),
            self.camera_line(scene_key),
            _says("sizes", mix=mix, rhythm=self.rhythm),
            _says("vfx", percent=round(self.vfx_density * 100)),
            _says("composition", composition=self.primary.composition),
            _says("lighting", lighting=self.primary.lighting),
            _says("sound", sound=self.primary.sound),
        ]
        for intent in self.secondary:
            lines.append(_says("secondary_weighting", name=intent.name, camera=intent.camera, lighting=intent.lighting))
        if self.dropped:
            lines.append(_says("dropped", items=separator.join(_says("dropped_item", name=name, why=why) for name, why in self.dropped)))
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "primary": self.primary.id, "secondary": [intent.id for intent in self.secondary],
            "dropped": [{"intent": name, "reason": why} for name, why in self.dropped],
            "vfx_density": round(self.vfx_density, 3), "rhythm": round(self.rhythm, 3),
            "sizes": {band: round(share, 3) for band, share in zip(SIZE_BANDS, self.sizes)},
            "names": self.names,
        }


def get_intent(intent_id: str) -> Intent | None:
    return _BY_ID.get(str(intent_id or "").strip().lower())


def detect_intents(text: str) -> list[Intent]:
    """Every feeling named in a brief, strongest signal first.

    Ordered by where the word appears, so the first thing a director says is taken
    as the main feeling.
    """
    haystack = str(text or "")
    if not haystack.strip():
        return []
    hits: list[tuple[int, Intent]] = []
    for intent in INTENTS:
        positions = [haystack.find(word) for word in intent.triggers if word in haystack]
        if positions:
            hits.append((min(positions), intent))
    return [intent for _, intent in sorted(hits, key=lambda item: item[0])]


def decode(
    text: str = "", *, primary: str = "", secondary: Sequence[str] = (), default: str = "tension",
) -> IntentPlan:
    """Decode a brief into one primary feeling, up to two secondaries, and the numbers.

    Explicit ids win over the words in ``text``; an unreadable brief falls back to
    ``default`` so a shot list is never left without direction.
    """
    chosen = [intent for intent in (get_intent(primary),) if intent]
    chosen.extend(intent for intent in (get_intent(item) for item in secondary) if intent)
    if not chosen:
        chosen = detect_intents(text)
    if not chosen:
        fallback = get_intent(default) or INTENTS[0]
        chosen = [fallback]

    lead, rest = chosen[0], []
    dropped: list[tuple[str, str]] = []
    for intent in chosen[1:]:
        if intent.id == lead.id:
            continue
        if intent.id in lead.conflicts or lead.id in intent.conflicts:
            dropped.append((intent.name, _says("conflicts_with_primary", primary=lead.name)))
            continue
        if len(rest) >= MAX_SECONDARY:
            dropped.append((intent.name, _says("too_many_secondary")))
            continue
        rest.append(intent)

    weights = _weights(len(rest))
    parts = [lead, *rest]
    vfx = sum(intent.vfx_density * weight for intent, weight in zip(parts, weights))
    rhythm = sum(intent.rhythm * weight for intent, weight in zip(parts, weights))
    sizes = tuple(
        sum(intent.sizes[index] * weight for intent, weight in zip(parts, weights)) for index in range(3)
    )
    total = sum(sizes) or 1.0
    return IntentPlan(
        primary=lead, secondary=rest, dropped=dropped,
        vfx_density=round(vfx, 3), rhythm=round(rhythm, 3),
        sizes=tuple(round(share / total, 3) for share in sizes),
    )


def _weights(secondary_count: int) -> list[float]:
    if secondary_count == 0:
        return [1.0]
    if secondary_count == 1:
        return [PRIMARY_WEIGHT, SECONDARY_WEIGHT_ONE]
    return [PRIMARY_WEIGHT, SECONDARY_WEIGHT_TWO, SECONDARY_WEIGHT_TWO]


def describe() -> list[dict]:
    """The catalogue a picker shows."""
    return [
        {
            "id": intent.id, "name": intent.name, "triggers": list(intent.triggers),
            "camera": intent.camera, "vfx_density": intent.vfx_density, "rhythm": intent.rhythm,
            "sizes": {band: share for band, share in zip(SIZE_BANDS, intent.sizes)},
            "composition": intent.composition, "lighting": intent.lighting, "sound": intent.sound,
            "conflicts": list(intent.conflicts),
        }
        for intent in INTENTS
    ]


__all__ = [
    "INTENTS", "MAX_SECONDARY", "PRIMARY_WEIGHT", "SIZE_BANDS", "Intent", "IntentPlan",
    "decode", "describe", "detect_intents", "get_intent",
]

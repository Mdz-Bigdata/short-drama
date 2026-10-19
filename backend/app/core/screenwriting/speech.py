"""Who speaks in a shot.

A generated clip carries one voice: the characters in it, or a narrator over
it, or nobody. A shot whose utterances mix character dialogue with narration
cannot be filmed as one clip — the narration would have to be spoken on screen
or the dialogue dubbed later — so it is sent back to planning. Narration is
delivered by the project's choice: synthesised narration audio, or left for
post-production; it never goes into the video prompt.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

SpeechMode = Literal["character_speech", "narrator_voiceover", "silent"]
NarrationDelivery = Literal["use_tts", "post_production"]
NARRATION_DELIVERIES: tuple[str, ...] = ("use_tts", "post_production")
DEFAULT_NARRATION_DELIVERY: NarrationDelivery = "use_tts"

# Speakers that name the narrator rather than a character in the scene.
NARRATOR_SPEAKERS = frozenset({"旁白", "画外音", "旁白音", "解说", "narrator", "vo", "v.o.", "os", "o.s."})


def is_narrator(speaker: str | None) -> bool:
    return str(speaker or "").strip().lower() in NARRATOR_SPEAKERS


def utterance_kinds(scene: Mapping[str, Any]) -> tuple[bool, bool]:
    """(has character dialogue, has narration) for a planned scene's utterances."""
    dialogue = False
    voiceover = False
    for utterance in scene.get("utterances") or []:
        if not isinstance(utterance, Mapping) or not str(utterance.get("text") or "").strip():
            continue
        kind = str(utterance.get("kind") or "dialogue")
        if kind == "voiceover" or is_narrator(utterance.get("speaker")):
            voiceover = True
        else:
            dialogue = True
    return dialogue, voiceover


def speech_mode(scene: Mapping[str, Any]) -> SpeechMode:
    """The one voice of a scene; a mixed scene reads as character speech and is reported by ``speech_problems``."""
    dialogue, voiceover = utterance_kinds(scene)
    if dialogue:
        return "character_speech"
    if voiceover:
        return "narrator_voiceover"
    return "silent"


def speech_problems(scene: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Problem codes that keep a scene from being one clip."""
    dialogue, voiceover = utterance_kinds(scene)
    if dialogue and voiceover:
        return [("mixed_speech", f"分镜 {scene.get('scene_id') or ''} 同时含角色台词与旁白，一镜只能有一种口播：请拆成两镜或改写")]
    return []


def narration_delivery(config: Mapping[str, Any] | None) -> NarrationDelivery:
    value = str((config or {}).get("narration_delivery") or "").strip()
    return value if value in NARRATION_DELIVERIES else DEFAULT_NARRATION_DELIVERY  # type: ignore[return-value]


__all__ = [
    "DEFAULT_NARRATION_DELIVERY",
    "NARRATION_DELIVERIES",
    "NARRATOR_SPEAKERS",
    "is_narrator",
    "narration_delivery",
    "speech_mode",
    "speech_problems",
    "utterance_kinds",
]

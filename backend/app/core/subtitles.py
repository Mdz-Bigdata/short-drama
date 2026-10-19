"""Subtitle drafts from a planned episode.

Each shot's spoken lines are laid across the shot's duration in proportion to
how long they take to read, one cue per sentence. The result is a draft to
start from, not a transcript aligned to audio: once the clips exist the timing
is the editor's to adjust.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.core.screenwriting.speech import is_narrator
from app.core.screenwriting.text_metrics import count_reading_units

# A sentence ends at CJK or Latin terminal punctuation; the ellipsis counts as one.
_CJK_BREAK = re.compile(r"(?<=[。！？…])")
_LATIN_BREAK = re.compile(r"(?<=[.!?])\s+")
MIN_CUE_SECONDS = 0.6


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start: float
    end: float
    text: str
    speaker: str | None
    kind: str
    scene_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "start": round(self.start, 3), "end": round(self.end, 3), "text": self.text,
            "speaker": self.speaker, "kind": self.kind, "scene_id": self.scene_id,
        }


def split_sentences(text: str) -> list[str]:
    """Sentences of a line: CJK text breaks after 。！？…, Latin text at .!? before a space."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    pieces: list[str] = []
    for chunk in _CJK_BREAK.split(cleaned):
        for piece in _LATIN_BREAK.split(chunk):
            if piece.strip():
                pieces.append(piece.strip())
    return pieces


def _spoken_lines(scene: Mapping[str, Any]) -> list[tuple[str, str | None, str]]:
    lines: list[tuple[str, str | None, str]] = []
    for utterance in scene.get("utterances") or []:
        if not isinstance(utterance, Mapping):
            continue
        text = str(utterance.get("text") or "").strip()
        if not text:
            continue
        speaker = str(utterance.get("speaker") or "").strip() or None
        kind = "voiceover" if utterance.get("kind") == "voiceover" or is_narrator(speaker) else "dialogue"
        lines.append((text, None if kind == "voiceover" else speaker, kind))
    return lines


def episode_cues(scenes: Iterable[Mapping[str, Any]], *, language: str | None = "zh") -> list[SubtitleCue]:
    """Cues for an episode's shots in order; each shot's lines share its duration by reading length."""
    cues: list[SubtitleCue] = []
    clock = 0.0
    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        duration = float(scene.get("duration_seconds") or 0) or 0.0
        sentences: list[tuple[str, str | None, str, int]] = []
        for text, speaker, kind in _spoken_lines(scene):
            for sentence in split_sentences(text):
                sentences.append((sentence, speaker, kind, max(1, count_reading_units(sentence, language))))
        if sentences and duration > 0:
            total_units = sum(units for _, _, _, units in sentences)
            cursor = clock
            for position, (sentence, speaker, kind, units) in enumerate(sentences):
                share = duration * units / total_units
                end = clock + duration if position == len(sentences) - 1 else cursor + share
                end = max(end, cursor + MIN_CUE_SECONDS) if position < len(sentences) - 1 else end
                cues.append(SubtitleCue(
                    index=len(cues) + 1, start=cursor, end=min(end, clock + duration) if end > cursor else cursor + MIN_CUE_SECONDS,
                    text=sentence, speaker=speaker, kind=kind, scene_id=str(scene.get("scene_id") or ""),
                ))
                cursor = cues[-1].end
        clock += duration
    return cues


def _timestamp(seconds: float) -> str:
    milliseconds = int(round(max(0.0, seconds) * 1000))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_srt(cues: Iterable[SubtitleCue], *, with_speakers: bool = False) -> str:
    """SubRip text; speakers are prefixed only when asked, as a reading aid."""
    blocks = []
    for cue in cues:
        text = f"{cue.speaker}：{cue.text}" if with_speakers and cue.speaker else cue.text
        blocks.append(f"{cue.index}\n{_timestamp(cue.start)} --> {_timestamp(cue.end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


__all__ = ["MIN_CUE_SECONDS", "SubtitleCue", "episode_cues", "render_srt", "split_sentences"]

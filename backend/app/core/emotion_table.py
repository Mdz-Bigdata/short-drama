# -*- coding: utf-8 -*-
"""One emotion word, everything it implies: face, body, voice and how hard the moment hits.

A screenplay marks a line's emotion once (the shot plan's ``delivery`` note, a
parenthetical in the line, the shot description). The same word has to move the
face and the body in the picture, the voice's pace and pitch, and say whether the
moment is a hit. This table is the single place that says what each word means.

Rules
-----
* **Specific before generic.** The table is ordered and the first rule with a
  matching word wins, so 冷笑 is read before 笑 and 怒吼 before 怒; a sneer never
  turns into a friendly smile.
* **Visible, not named.** Face and body are written as things a camera can see
  (lowered gaze, a jaw set hard), never as the emotion's name, which a video model
  cannot draw.
* **Voice-only words stay off the face.** 低声 / 沙哑 / 提高音量 describe how a line
  is said; they change the voice notes and never enter the face prompt.
* **Two face phrases at most.** Piling on expression words makes models draw none
  of them well.
* **Where the eyes go, and what not to play.** A rule may add a gaze (where the look
  lands and how it moves) and a few things the emotion must not show (不挤笑, 不连续眨眼):
  a held-back moment is ruined by a model that plays it big.

* **A turn is drawn as a turn.** When the text names two emotions in order with a
  turn word between them (愣住，随即苦笑), the face is written first-then; the voice
  still follows the rule that decides the reading.

The wording and values are this project's own and live in
``app/data/prompt/emotion_table.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core import prompt_data

# Voice labels understood by the voice presets (media_compositor.EMOTION_PRESETS) and
# drama_service.dialogue_delivery_profile.
VOICE_LABELS = ("neutral", "angry", "shout", "cold", "sad", "tense", "happy", "tender")


@dataclass(frozen=True)
class EmotionRule:
    words: tuple[str, ...]
    voice: str                 # one of VOICE_LABELS
    rate: float                # speech-rate multiplier against a calm reading
    pitch: float               # pitch factor against a calm reading
    face: tuple[str, ...]      # visible facial detail, most telling first
    body: str                  # visible posture / hands
    impact: bool = False       # an outburst: the moment should land hard
    gaze: str = ""             # where the look lands and how it moves
    hold_back: tuple[str, ...] = ()  # what the moment must not show (each starts with 不)


_DATA = "emotion_table"

# Ordered: a longer, more specific word must come before any rule whose word it contains.
RULES: tuple[EmotionRule, ...] = tuple(
    EmotionRule(
        tuple(rule["words"]), str(rule["voice"]), float(rule["rate"]), float(rule["pitch"]),
        tuple(rule["face"]), str(rule["body"]), bool(rule.get("impact", False)),
        str(rule.get("gaze") or ""), tuple(rule.get("hold_back") or ()),
    )
    for rule in prompt_data.value(_DATA, "rules")
)

# How a line is said, not what the face does: these change only the voice notes.
VOICE_ONLY: tuple[tuple[str, str], ...] = prompt_data.pairs(_DATA, "voice_only")

MAX_FACE_PHRASES = prompt_data.number(_DATA, "max_face_phrases")

# Words that say the face changes within the moment (愣住，随即苦笑).
TURN_MARKERS: tuple[str, ...] = prompt_data.words(_DATA, "turn_markers")


@dataclass(frozen=True)
class EmotionReading:
    """What a piece of text says about the emotion of a moment."""

    matched: str = ""                          # the word that decided it ("" when nothing matched)
    voice: str = "neutral"
    rate: float = 1.0
    pitch: float = 1.0
    face: tuple[str, ...] = ()
    body: str = ""
    impact: bool = False
    gaze: str = ""
    hold_back: tuple[str, ...] = ()
    voice_notes: tuple[str, ...] = field(default_factory=tuple)
    # When the moment turns (愣住，随即苦笑): the face it starts from and the face and body it ends in.
    turn_from: tuple[str, ...] = ()
    turn_to: tuple[str, ...] = ()
    turn_body: str = ""

    @property
    def visible(self) -> str:
        """The face and body, ready for a picture prompt; empty when nothing matched."""
        if self.turn_from and self.turn_to:
            # One face phrase for each side keeps the two-phrase ceiling.
            then = "，".join(part for part in (self.turn_to[0], self.turn_body) if part)
            return prompt_data.text(_DATA, "turn_line").format(first=self.turn_from[0], then=then)
        parts = [*self.face[:MAX_FACE_PHRASES], self.gaze, self.body, "、".join(self.hold_back)]
        return "，".join(part for part in parts if part)


def _strip_voice_only(text: str) -> tuple[str, tuple[str, ...]]:
    notes: list[str] = []
    for word, note in VOICE_ONLY:
        if word in text:
            text = text.replace(word, " ")
            if note not in notes:
                notes.append(note)
    return text, tuple(notes)


def _matches_in_order(text: str) -> list[tuple[int, int, EmotionRule]]:
    """Every rule the text names, as (start, end, rule) by position; a word inside a longer, earlier-ranked one is not counted."""
    claimed: list[tuple[int, int, EmotionRule]] = []
    for rule in RULES:
        for word in rule.words:
            start = text.find(word)
            while start >= 0:
                end = start + len(word)
                if not any(start < taken_end and taken_start < end for taken_start, taken_end, _ in claimed):
                    claimed.append((start, end, rule))
                start = text.find(word, start + 1)
    return sorted(claimed, key=lambda match: match[0])


def _turn(text: str) -> tuple[EmotionRule, EmotionRule] | None:
    """The first two different emotions in the text when a turn word stands between them."""
    matches = _matches_in_order(text)
    if not matches:
        return None
    first_end, first = matches[0][1], matches[0][2]
    for start, _end, rule in matches[1:]:
        if rule is first:
            continue
        between = text[first_end:start]
        return (first, rule) if any(marker in between for marker in TURN_MARKERS) else None
    return None


def read_emotion(*texts: str | None) -> EmotionReading:
    """Read the emotion of a moment from its notes, line and description, in that order of authority.

    Each text is read on its own and the first that names an emotion decides, so an
    explicit delivery note beats a guess from the description. Voice-only words are
    collected from all of them and never decide the face.
    """
    voice_notes: list[str] = []
    cleaned: list[str] = []
    for raw in texts:
        text, notes = _strip_voice_only(str(raw or ""))
        cleaned.append(text)
        voice_notes.extend(note for note in notes if note not in voice_notes)
    for text in cleaned:
        for rule in RULES:
            word = next((candidate for candidate in rule.words if candidate in text), "")
            if word:
                turn = _turn(text)
                return EmotionReading(
                    matched=word, voice=rule.voice, rate=rule.rate, pitch=rule.pitch,
                    face=rule.face[:MAX_FACE_PHRASES], body=rule.body, impact=rule.impact,
                    gaze=rule.gaze, hold_back=rule.hold_back,
                    voice_notes=tuple(voice_notes),
                    **({"turn_from": turn[0].face, "turn_to": turn[1].face, "turn_body": turn[1].body} if turn else {}),
                )
    return EmotionReading(voice_notes=tuple(voice_notes))


def check_order() -> list[str]:
    """Rules whose word is shadowed by an earlier, shorter word that it contains (should be empty)."""
    problems: list[str] = []
    seen: list[tuple[int, str]] = []
    for index, rule in enumerate(RULES):
        for word in rule.words:
            for earlier_index, earlier in seen:
                if earlier != word and earlier in word and earlier_index < index:
                    problems.append(f"「{word}」排在「{earlier}」之后，会被它抢先命中")
        seen.extend((index, word) for word in rule.words)
    return problems


__all__ = ["EmotionReading", "EmotionRule", "MAX_FACE_PHRASES", "RULES", "VOICE_LABELS", "VOICE_ONLY", "check_order", "read_emotion"]

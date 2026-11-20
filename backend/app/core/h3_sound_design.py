# -*- coding: utf-8 -*-
"""Sound for MiniMax H3, which generates picture and sound in one pass.

H3 has one sound entry — the prompt — and no faders. Written as one lump, the
dialogue, the room and the music arrive on top of each other: the line is buried,
everything sits in the centre, and nothing has space. So sound is written as three
named layers in one line, in a fixed order of weight:

``center: <人声>; ambient: <环境>; music: <配乐>``

- **center** is the line, and only the line: who speaks, in what voice, ``clear
  speech``, pinned to the middle and synced to the mouth. No music words here, or
  the model mixes the voice into the score.
- **ambient** fills the room and stays out of the way: concrete sound sources,
  ``continuous``, ``low volume``, and a width word so the picture is not flat.
- **music** is the mood bed at ``low frequency``; this project composes its score
  later, so the default is ``none``.

The other half is identity. A character's voice drifts between clips unless the
same words describe it every time, so each character gets a **voice anchor** —
the short voice description designed for them in stage 3 (``voice_desc``) when there
is one, otherwise derived from their character card — restated verbatim in every
prompt, plus a reference audio slot when the project has a clean sample. The anchor
is the same for every model that renders sound with the picture, not only H3; a
shot's emotion is layered on top of it and never rewrites it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from app.core import prompt_data

# The wording, the word tables and the limits live in app/data/prompt/h3_sound_design.json.
_DATA = "h3_sound_design"


def _says(key: str, /, **values: object) -> str:
    """A sentence of the sound wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_DATA)["says"][key]).format(**values)


def _word(key: str) -> str:
    """A word of the sound wording table (a separator, a default)."""
    return prompt_data.text(_DATA, key)


def _table(key: str):
    """A word table or a limit of the sound wording table, as it stands."""
    return prompt_data.value(_DATA, key)


def _pattern(key: str) -> str:
    """A regular expression of the sound wording table, as text."""
    return str(prompt_data.load(_DATA)["patterns"][key])


_LIMITS = _table("limits")
_TAGS = _table("tags")
# The article's cap: past ~60 words the model stops telling the layers apart.
MAX_SOUND_WORDS = int(_LIMITS["sound_words"])
CENTER_TAG, AMBIENT_TAG, MUSIC_TAG = str(_TAGS["center"]), str(_TAGS["ambient"]), str(_TAGS["music"])
# Words that belong to the music layer; inside `center` they blend voice into score.
_MUSIC_WORDS = tuple(str(word) for word in _table("music_words"))
_LOW_AMBIENT = tuple(str(word) for word in _table("low_ambient_words"))
_LOW_MUSIC = tuple(str(word) for word in _table("low_music_words"))
_SPACE_WORDS = tuple(str(word) for word in _table("space_words"))
_NONE_VALUES = {str(word) for word in _table("none_music_values")}
_HAN_PER_WORD = int(_LIMITS["han_chars_per_word"])

# Voice bands: what the character card says → how the timbre is written. The wording
# is fixed on purpose — a re-worded persona reads to the model as a different actor.
# First match wins, so the table keeps its order.
_TIMBRE_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = tuple(
    (tuple(str(word) for word in words), str(timbre), str(pitch)) for words, timbre, pitch in _table("timbre_rules")
)
_DEFAULT_TIMBRE = tuple(str(word) for word in _table("default_timbre"))
_GENDER_MARKS = _table("gender_marks")
_AGE = re.compile(_pattern("age"))
# Reading speed in characters per second, by how the line is delivered. The tier names are
# code values: callers pass them (delivery="正常") and prompt_packages checks against these keys.
PACE_BY_DELIVERY: dict[str, float] = {"正常": 3.0, "急切": 4.0, "沉重": 2.5}
# How the shot's emotion reads as a pace tier and as the centre layer's mood word.
_DELIVERY_BY_EMOTION: dict[str, tuple[str, str]] = {
    str(emotion): (str(tier), str(mood)) for emotion, (tier, mood) in _table("delivery_by_emotion").items()
}


def delivery_for_emotion(emotion: str) -> tuple[str, str]:
    """``(pace tier, centre-layer mood word)`` for a shot's emotion."""
    return _DELIVERY_BY_EMOTION.get(str(emotion or "").strip().lower(), ("正常", ""))


def emotion_overlay(anchors: Sequence["VoiceAnchor"], notes: str) -> str:
    """本镜情绪只叠加在语气、力度与停顿上；基础音色照锁定句不变。"""
    names = _word("list_separator").join(dict.fromkeys(anchor.name for anchor in anchors))
    notes = " ".join(str(notes or "").split())
    if not names or not notes:
        return ""
    return _says("overlay", names=names, notes=notes)


@dataclass(frozen=True)
class VoiceAnchor:
    """One character's voice, written the same way in every prompt."""

    name: str
    gender: str                    # male | female
    age_years: int | None
    timbre: str                    # 清亮 / 沉稳 / 沙哑 …
    pitch: str                     # 中高音区 / 中音区 / 低音区
    pace_cps: float = 3.0
    ref_audio: str = ""            # @音频N when the project has a clean dry sample
    designed: str = ""             # 第3阶段为角色设计的音色短描述(voice_desc)，有就逐字用它

    @property
    def persona(self) -> str:
        age = _says("persona_age", years=self.age_years) if self.age_years else ""
        voice = _table("persona_voice")["female" if self.gender == "female" else "male"]
        return _says("persona", age=age, timbre=self.timbre, voice=voice)

    def lock_line(self) -> str:
        """The sentence restated verbatim in every prompt that gives this character a line: timbre and pitch, never a pace.

        The reference-audio lead is voice_reference.json's ``lock_lead``: video_references finds
        the placeholder by it and removes both when the sample is not sent.
        """
        if self.designed:
            parts = [_says("lock_head", name=self.name, voice=self.designed)]
        else:
            # 锁音色与音区，不锁语速：语速跟着每句台词的情绪走(speech_pace 的分档、台词表达)，锁死一个数会和它打架。
            parts = [_says("lock_head", name=self.name, voice=self.persona), self.pitch]
        if self.ref_audio:
            parts.append(prompt_data.text("voice_reference", "lock_lead") + self.ref_audio)
        return _word("lock_separator").join(parts) + _says("lock_tail")

    def center_term(self) -> str:
        """How this character is named inside the English-tagged center layer."""
        voice = _table("center_voice")["female" if self.gender == "female" else "male"]
        return _says("center_term", voice=voice, tone=_CENTER_TONE.get(self.timbre, _word("center_tone_default")))


_CENTER_TONE = {str(timbre): str(tone) for timbre, tone in _table("center_tone").items()}


MAX_VOICE_DESC_CHARS = int(_LIMITS["voice_desc_chars"])


def build_voice_anchor(
    name: str, *, description: str = "", gender: str = "female", delivery: str = "正常", ref_audio: str = "",
    voice_desc: str = "",
) -> VoiceAnchor:
    """Derive a character's voice from their card, deterministically.

    The same card always yields the same words, which is the whole point: a voice
    described differently in the next episode is heard as a different person. A
    designed ``voice_desc`` wins over the keyword rules: it is the lock line itself,
    and the rules only read it for the H3 centre-layer words.
    """
    designed = " ".join(str(voice_desc or "").split())[:MAX_VOICE_DESC_CHARS]
    female, male = _GENDER_MARKS["female"], _GENDER_MARKS["male"]
    if designed and (female in designed) != (male in designed):
        gender = "female" if female in designed else "male"
    card = f"{name} {description}"
    timbre, pitch = _DEFAULT_TIMBRE
    # 设计过的音色先读，读不出音区再退回角色卡。
    for text in ((designed, card) if designed else (card,)):
        band = next(((t, p) for words, t, p in _TIMBRE_RULES if any(word in text for word in words)), None)
        if band:
            timbre, pitch = band
            break
    age = _AGE.search(designed) or _AGE.search(card)
    return VoiceAnchor(
        name=str(name).strip(),
        gender="male" if str(gender).lower().startswith("m") or gender == "male" else "female",
        age_years=int(age.group(1)) if age else None,
        timbre=timbre,
        pitch=pitch,
        pace_cps=PACE_BY_DELIVERY.get(str(delivery), 3.0),
        ref_audio=str(ref_audio or "").strip(),
        designed=designed,
    )


@dataclass
class SoundCheck:
    code: str
    passed: bool
    detail: str


@dataclass
class H3SoundPrompt:
    text: str
    center: str
    ambient: str
    music: str
    voice_locks: list[str] = field(default_factory=list)
    checks: list[SoundCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def as_dict(self) -> dict:
        return {
            "text": self.text, "center": self.center, "ambient": self.ambient, "music": self.music,
            "voice_locks": list(self.voice_locks),
            "checks": [{"code": c.code, "passed": c.passed, "detail": c.detail} for c in self.checks],
        }


def _words(text: str) -> int:
    """Rough word count across mixed Chinese and English, as the model reads it."""
    latin = len(re.findall(_pattern("latin_word"), text))
    han = len(re.findall(_pattern("han"), text))
    return latin + han // _HAN_PER_WORD


def _clean(items: Iterable[str]) -> list[str]:
    return [" ".join(str(item).split()) for item in items if str(item).strip()]


def compile_sound_prompt(
    *,
    speakers: Sequence[VoiceAnchor] = (),
    tone: str = "",
    narration: bool = False,
    ambience: Sequence[str] = (),
    music: str = "",
    spacious: bool = False,
    foreground: bool = False,
    silent: bool = False,
) -> H3SoundPrompt:
    """One H3 sound line: three named layers, dialogue loudest, music quietest.

    ``narration`` marks a voice-over, which also tells the picture to keep the
    mouths closed; ``spacious`` is for a hall or a street, where a little reverb
    belongs; ``silent`` is a shot with no one speaking.
    """
    if silent or not speakers:
        center = _says("center_silent")
    else:
        voices = _word("voice_separator").join(dict.fromkeys(anchor.center_term() for anchor in speakers))
        center = _says("center_voices", voices=voices)
        center += _says("center_narration") if narration else _says("center_synced")
        if foreground:
            center += _says("center_foreground")
        if tone.strip():
            center += _says("center_tone", tone=tone.strip())

    beds = _clean(ambience)
    if beds:
        ambient = _says("ambient_beds", beds=_word("bed_separator").join(beds))
        ambient += _says("ambient_room") if not spacious else _says("ambient_spacious")
    else:
        ambient = _says("ambient_empty")

    music_text = " ".join(str(music or "").split())
    music_layer = _says("music_none") if music_text.lower() in _NONE_VALUES else _says("music_bed", music=music_text)

    text = _says(
        "line", center_tag=CENTER_TAG, center=center, ambient_tag=AMBIENT_TAG, ambient=ambient,
        music_tag=MUSIC_TAG, music=music_layer,
    )
    locks = [anchor.lock_line() for anchor in speakers]
    return H3SoundPrompt(
        text=text, center=center, ambient=ambient, music=music_layer,
        voice_locks=locks, checks=check_sound_prompt(text, speakers=speakers),
    )


def check_sound_prompt(text: str, *, speakers: Sequence[VoiceAnchor] = ()) -> list[SoundCheck]:
    """What goes wrong with H3 sound, checked before the prompt is sent."""
    joined = _word("list_separator").join
    layers = {tag: _layer_of(text, tag) for tag in (CENTER_TAG, AMBIENT_TAG, MUSIC_TAG)}
    missing = [tag for tag, body in layers.items() if not body]
    checks = [SoundCheck(
        "h3_sound_three_layers", not missing,
        _says("layers_missing", missing=joined(missing)) if missing else _says("layers_ok"),
    )]

    leaked = [word for word in _MUSIC_WORDS if word in layers[CENTER_TAG].lower()]
    checks.append(SoundCheck(
        "h3_sound_center_clean", not leaked,
        _says("center_leaked", words=joined(leaked)) if leaked else _says("center_clean"),
    ))

    ambient_body, music_body = layers[AMBIENT_TAG].lower(), layers[MUSIC_TAG].lower()
    quiet = (not ambient_body or any(word in ambient_body for word in _LOW_AMBIENT)) and (
        not music_body or any(word in music_body for word in _LOW_MUSIC)
    )
    checks.append(SoundCheck(
        "h3_sound_low_bed", quiet,
        _says("bed_loud") if not quiet else _says("bed_low"),
    ))

    spaced = not ambient_body or any(word in ambient_body for word in _SPACE_WORDS)
    checks.append(SoundCheck(
        "h3_sound_space", spaced,
        _says("space_flat") if not spaced else _says("space_wide"),
    ))

    words = _words(text)
    checks.append(SoundCheck(
        "h3_sound_word_budget", words <= MAX_SOUND_WORDS,
        _says("budget_over", words=words, limit=MAX_SOUND_WORDS) if words > MAX_SOUND_WORDS
        else _says("budget_ok", words=words, limit=MAX_SOUND_WORDS),
    ))

    named = [anchor.name for anchor in speakers]
    locked = not named or all(anchor.persona for anchor in speakers)
    checks.append(SoundCheck(
        "h3_sound_voice_locked", locked,
        _says("voice_unlocked") if not locked
        else (_says("voice_silent") if not named else _says("voice_locked", names=joined(named))),
    ))
    return checks


def _layer_of(text: str, tag: str) -> str:
    match = re.search(_pattern("layer").format(tag=tag), text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def anchors_from_characters(
    characters: Sequence[Mapping[str, object]], *, gender_of, delivery: str = "正常",
    voices: Mapping[str, str] | None = None,
) -> dict[str, VoiceAnchor]:
    """Voice anchors for a cast list, keyed by name; ``gender_of(name)`` supplies the gender.

    ``voices`` maps a name to its designed ``voice_desc`` (from the stage-3 DNA); a card's
    own ``voice_desc`` field is read too.
    """
    voices = voices or {}
    anchors: dict[str, VoiceAnchor] = {}
    for item in characters:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in anchors:
            continue
        description = str(item.get("desc") or item.get("description") or "")
        anchors[name] = build_voice_anchor(
            name, description=description, gender=gender_of(name), delivery=delivery,
            voice_desc=str(item.get("voice_desc") or voices.get(name) or ""),
        )
    return anchors


__all__ = [
    "AMBIENT_TAG", "CENTER_TAG", "MAX_SOUND_WORDS", "MUSIC_TAG", "PACE_BY_DELIVERY",
    "H3SoundPrompt", "SoundCheck", "VoiceAnchor",
    "anchors_from_characters", "build_voice_anchor", "check_sound_prompt", "compile_sound_prompt",
    "delivery_for_emotion", "emotion_overlay",
]

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
derived once from their character card and restated verbatim in every prompt —
plus a reference audio slot when the project has a clean sample.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

# The article's cap: past ~60 words the model stops telling the layers apart.
MAX_SOUND_WORDS = 60
CENTER_TAG, AMBIENT_TAG, MUSIC_TAG = "center", "ambient", "music"
# Words that belong to the music layer; inside `center` they blend voice into score.
_MUSIC_WORDS = (
    "bgm", "music", "piano", "strings", "guitar", "drum", "percussion", "violin", "cello",
    "synth", "pad", "orchestra", "melody", "song", "配乐", "音乐", "旋律", "钢琴", "弦乐",
)
_LOW_AMBIENT = ("low volume", "low", "quiet", "soft")
_LOW_MUSIC = ("low frequency", "low freq", "low", "soft", "none")
_SPACE_WORDS = ("surround", "left-right spread", "spread", "stereo")
_NONE_VALUES = {"", "none", "无", "no music", "silence"}

# Voice bands: what the character card says → how the timbre is written. The wording
# is fixed on purpose — a re-worded persona reads to the model as a different actor.
_TIMBRE_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("少女", "小女孩", "女孩", "少年", "小男孩", "男孩"), "清亮", "中高音区"),
    (("老人", "年迈", "苍老", "老年", "白发苍苍"), "苍哑", "低音区"),
    (("中年", "沉稳", "威严", "将军", "教授", "总裁", "首领"), "沉稳", "中低音区"),
    (("沙哑", "粗粝", "低沉", "嘶哑"), "沙哑", "低音区"),
    (("温柔", "治愈", "轻柔", "柔和"), "温柔", "中音区"),
    (("冷", "清冷", "淡漠", "疏离"), "清冷", "中音区"),
)
_DEFAULT_TIMBRE = ("清亮", "中音区")
_AGE = re.compile(r"(\d{1,2})\s*岁")
# Reading speed in characters per second, by how the line is delivered.
PACE_BY_DELIVERY: dict[str, float] = {"正常": 3.0, "急切": 4.0, "沉重": 2.5}
# How the shot's emotion reads as a pace tier and as the centre layer's mood word.
_DELIVERY_BY_EMOTION: dict[str, tuple[str, str]] = {
    "angry": ("急切", "angry"), "shout": ("急切", "shouting"), "tense": ("急切", "tense"),
    "happy": ("正常", "bright"), "sad": ("沉重", "sorrowful"), "cold": ("沉重", "cold"),
    "tender": ("正常", "gentle"), "neutral": ("正常", ""),
}


def delivery_for_emotion(emotion: str) -> tuple[str, str]:
    """``(pace tier, centre-layer mood word)`` for a shot's emotion."""
    return _DELIVERY_BY_EMOTION.get(str(emotion or "").strip().lower(), ("正常", ""))


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

    @property
    def persona(self) -> str:
        age = f"{self.age_years}岁" if self.age_years else ""
        voice = "女声" if self.gender == "female" else "男声"
        return f"{age}{self.timbre}{voice}"

    def lock_line(self) -> str:
        """The sentence restated verbatim in every prompt that gives this character a line."""
        parts = [f"{self.name}：{self.persona}", self.pitch, f"语速每秒{self.pace_cps:g}字"]
        if self.ref_audio:
            parts.append(f"音色参考{self.ref_audio}")
        return "，".join(parts) + "；全片音色、音调与声线不变"

    def center_term(self) -> str:
        """How this character is named inside the English-tagged center layer."""
        return f"{'female' if self.gender == 'female' else 'male'} {_CENTER_TONE.get(self.timbre, 'steady')}"


_CENTER_TONE = {
    "清亮": "bright", "苍哑": "aged hoarse", "沉稳": "steady", "沙哑": "hoarse",
    "温柔": "gentle", "清冷": "cold calm",
}


def build_voice_anchor(
    name: str, *, description: str = "", gender: str = "female", delivery: str = "正常", ref_audio: str = "",
) -> VoiceAnchor:
    """Derive a character's voice from their card, deterministically.

    The same card always yields the same words, which is the whole point: a voice
    described differently in the next episode is heard as a different person.
    """
    text = f"{name} {description}"
    timbre, pitch = _DEFAULT_TIMBRE
    for words, band_timbre, band_pitch in _TIMBRE_RULES:
        if any(word in text for word in words):
            timbre, pitch = band_timbre, band_pitch
            break
    age = _AGE.search(text)
    return VoiceAnchor(
        name=str(name).strip(),
        gender="male" if str(gender).lower().startswith("m") or gender == "male" else "female",
        age_years=int(age.group(1)) if age else None,
        timbre=timbre,
        pitch=pitch,
        pace_cps=PACE_BY_DELIVERY.get(str(delivery), 3.0),
        ref_audio=str(ref_audio or "").strip(),
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
    latin = len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))
    han = len(re.findall(r"[一-鿿]", text))
    return latin + han // 2


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
        center = "no dialogue, characters silent, mouths closed"
    else:
        voices = " / ".join(dict.fromkeys(anchor.center_term() for anchor in speakers))
        center = f"{voices}, clear speech, center channel"
        center += ", voice-over, mouths closed" if narration else ", synced to mouth"
        if foreground:
            center += ", foreground"
        if tone.strip():
            center += f", {tone.strip()}"

    beds = _clean(ambience)
    if beds:
        ambient = ", ".join(beds) + ", continuous, low volume"
        ambient += ", surround" if not spacious else ", surround, low reverb"
    else:
        ambient = "room tone only, continuous, low volume, surround"

    music_text = " ".join(str(music or "").split())
    music_layer = "none" if music_text.lower() in _NONE_VALUES else f"{music_text}, low frequency, slight spread"

    text = f"{CENTER_TAG}: {center}; {AMBIENT_TAG}: {ambient}; {MUSIC_TAG}: {music_layer}"
    locks = [anchor.lock_line() for anchor in speakers]
    return H3SoundPrompt(
        text=text, center=center, ambient=ambient, music=music_layer,
        voice_locks=locks, checks=check_sound_prompt(text, speakers=speakers),
    )


def check_sound_prompt(text: str, *, speakers: Sequence[VoiceAnchor] = ()) -> list[SoundCheck]:
    """What goes wrong with H3 sound, checked before the prompt is sent."""
    layers = {tag: _layer_of(text, tag) for tag in (CENTER_TAG, AMBIENT_TAG, MUSIC_TAG)}
    missing = [tag for tag, body in layers.items() if not body]
    checks = [SoundCheck(
        "h3_sound_three_layers", not missing,
        f"缺少 {'、'.join(missing)} 层；三层都要写，模型才会分层生成。" if missing
        else "center / ambient / music 三层齐备。",
    )]

    leaked = [word for word in _MUSIC_WORDS if word in layers[CENTER_TAG].lower()]
    checks.append(SoundCheck(
        "h3_sound_center_clean", not leaked,
        f"对白层混进了配乐词「{'、'.join(leaked)}」，人声会和音乐搅在一起。" if leaked
        else "对白层只写人声，没有混进配乐词。",
    ))

    ambient_body, music_body = layers[AMBIENT_TAG].lower(), layers[MUSIC_TAG].lower()
    quiet = (not ambient_body or any(word in ambient_body for word in _LOW_AMBIENT)) and (
        not music_body or any(word in music_body for word in _LOW_MUSIC)
    )
    checks.append(SoundCheck(
        "h3_sound_low_bed", quiet,
        "环境音要写 low volume、配乐要写 low frequency 或 none，否则对白会被盖住。" if not quiet
        else "环境音与配乐都已压低，对白权重最高。",
    ))

    spaced = not ambient_body or any(word in ambient_body for word in _SPACE_WORDS)
    checks.append(SoundCheck(
        "h3_sound_space", spaced,
        "环境音层缺少 surround 或 left-right spread，声音会全挤在中间发平。" if not spaced
        else "环境音铺在四周，画面有空间感。",
    ))

    words = _words(text)
    checks.append(SoundCheck(
        "h3_sound_word_budget", words <= MAX_SOUND_WORDS,
        f"声音提示词约 {words} 词，超过 {MAX_SOUND_WORDS} 词后模型会抓不住主次。" if words > MAX_SOUND_WORDS
        else f"声音提示词 {words} 词，在 {MAX_SOUND_WORDS} 词预算内。",
    ))

    named = [anchor.name for anchor in speakers]
    locked = not named or all(anchor.persona for anchor in speakers)
    checks.append(SoundCheck(
        "h3_sound_voice_locked", locked,
        "说话的角色缺少音色锚定，跨镜会音色漂移。" if not locked
        else ("本镜无台词，不需要音色锚定。" if not named else f"{'、'.join(named)} 的音色、音调与声线已锁定。"),
    ))
    return checks


def _layer_of(text: str, tag: str) -> str:
    match = re.search(rf"{tag}\s*[:：]\s*([^;；]*)", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def anchors_from_characters(
    characters: Sequence[Mapping[str, object]], *, gender_of, delivery: str = "正常",
) -> dict[str, VoiceAnchor]:
    """Voice anchors for a cast list, keyed by name; ``gender_of(name)`` supplies the gender."""
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
        )
    return anchors


__all__ = [
    "AMBIENT_TAG", "CENTER_TAG", "MAX_SOUND_WORDS", "MUSIC_TAG", "PACE_BY_DELIVERY",
    "H3SoundPrompt", "SoundCheck", "VoiceAnchor",
    "anchors_from_characters", "build_voice_anchor", "check_sound_prompt", "compile_sound_prompt",
    "delivery_for_emotion",
]

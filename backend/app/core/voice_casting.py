# -*- coding: utf-8 -*-
"""Casting a character's voice: audition the designed voice, pick a take, keep it.

Stage 3 writes a ``voice_prompt`` for every character — who they are, gender, age, pitch,
texture, articulation and speaking rate, in a neutral mood and dry. Casting turns that
description into real takes: the voice designer renders a few previews of one neutral,
declarative test line, the director listens, re-rolls if none fits, and the chosen take
becomes the character's ``voice_id``.

The test line is deliberately flat. A line full of feeling teaches the take that feeling,
and a take with built-in emotion or pace carries it into every scene the voice is used in.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, MutableMapping
from typing import Any

from app.core.screenwriting.speech import NARRATOR_SPEAKERS
from app.schema.elevenlabs import VoiceDesignRequest

AUDITIONS_KEY = "3_voice_auditions"
NARRATOR_KEY = "3_narrator_voice"
NARRATOR_NAME = "旁白"
# 旁白没有角色 DNA 可读，给一句能直接试听的默认音色设计；同样保持中性、干声。
DEFAULT_NARRATOR_PROMPT = "纪录片式中文旁白，成年声音，音高适中，音色干净沉稳，咬字清晰，语速平稳，情绪保持中性；干声，不含音乐、音效、环境声与混响"
# ElevenLabs voice design refuses preview text shorter than this.
MIN_AUDITION_CHARS = 100
MAX_ROUNDS = 5
MIN_VOICE_PROMPT_CHARS = 20

# 中性陈述句：不带情绪、不带问句和感叹，只听音色本身。
_NEUTRAL_LINES = (
    "今天上午九点，我从家里出发，坐地铁去公司。",
    "路上的人不多，车厢里很安静，我看了一会儿窗外的街道。",
    "到了公司以后，我先把桌上的文件整理好，再给同事回了几封邮件。",
    "中午我在楼下的小店吃了一碗面，下午接着开会，一直到傍晚才结束。",
    "回家的路上下了一点小雨，我在便利店买了一把伞和一瓶水。",
)


def audition_text(name: str, *, min_chars: int = MIN_AUDITION_CHARS) -> str:
    """One neutral, declarative test line, padded to the provider's minimum length."""
    text = f"我是{str(name or '').strip() or '这个角色'}。"
    index = 0
    while len(text) < min_chars:
        text += _NEUTRAL_LINES[index % len(_NEUTRAL_LINES)]
        index += 1
    return text


def dna_characters(assets: Mapping[str, Any]) -> list[dict]:
    dna = assets.get("3_dna")
    characters = dna.get("characters") if isinstance(dna, dict) else None
    return [item for item in characters or [] if isinstance(item, dict)]


def dna_character(assets: Mapping[str, Any], name: str) -> dict | None:
    name = str(name or "").strip()
    return next((item for item in dna_characters(assets) if str(item.get("name") or "").strip() == name), None)


def is_cast_member(assets: Mapping[str, Any], name: str) -> bool:
    name = str(name or "").strip()
    return bool(name) and (
        dna_character(assets, name) is not None
        or any(
            isinstance(item, dict) and str(item.get("name") or "").strip() == name
            for item in assets.get("3_characters") or []
        )
    )


def voice_prompt_of(assets: Mapping[str, Any], name: str) -> str:
    character = dna_character(assets, name) or {}
    return " ".join(str(character.get("voice_prompt") or character.get("voicePrompt") or "").split())


def audition_request(voice_prompt: str, name: str, *, seed: int | None = None) -> VoiceDesignRequest:
    """The design request for one audition round; a fresh seed every round is what re-rolls the takes."""
    prompt = " ".join(str(voice_prompt or "").split())
    if len(prompt) < MIN_VOICE_PROMPT_CHARS:
        raise ValueError(f"「{name}」还没有可用的音色设计提示词（至少 {MIN_VOICE_PROMPT_CHARS} 字），请先在角色 DNA 里补上 voice_prompt")
    return VoiceDesignRequest(
        voice_description=prompt[:1000],
        text=audition_text(name),
        seed=seed if seed is not None else random.randint(0, 2_147_483_647),
    )


def record_round(
    assets: MutableMapping[str, Any], name: str, *, request: VoiceDesignRequest, result: Mapping[str, Any],
) -> dict:
    """Keep one audition round (the newest last); older rounds beyond ``MAX_ROUNDS`` are dropped."""
    previews = [
        {key: value for key, value in preview.items() if key != "audio_base_64"}
        for preview in result.get("previews") or [] if isinstance(preview, Mapping)
    ]
    if not previews:
        raise RuntimeError("音色设计没有返回试听样本")
    entry = {
        "voice_prompt": request.voice_description, "text": request.text, "seed": request.seed,
        "previews": previews,
    }
    store = assets.setdefault(AUDITIONS_KEY, {})
    rounds = store.setdefault(name, [])
    rounds.append(entry)
    del rounds[:-MAX_ROUNDS]
    return entry


def find_preview(assets: Mapping[str, Any], name: str, generated_voice_id: str) -> tuple[dict, dict] | None:
    """``(round, preview)`` of a take this character auditioned, or ``None``."""
    wanted = str(generated_voice_id or "").strip()
    for entry in reversed((assets.get(AUDITIONS_KEY) or {}).get(name) or []):
        for preview in entry.get("previews") or []:
            if isinstance(preview, dict) and str(preview.get("generated_voice_id") or "") == wanted:
                return entry, preview
    return None


def set_voice(assets: MutableMapping[str, Any], name: str, *, voice_id: str, voice_prompt: str = "", take: Mapping[str, Any] | None = None) -> None:
    """Store the cast voice next to the character's other DNA fields."""
    dna = assets.get("3_dna") if isinstance(assets.get("3_dna"), dict) else {}
    assets["3_dna"] = dna
    characters = dna.setdefault("characters", [])
    character = dna_character(assets, name)
    if character is None:
        character = {"name": name}
        characters.append(character)
    character["voice_id"] = str(voice_id)
    if voice_prompt:
        character["voice_prompt"] = voice_prompt
    if take is not None:
        character["voice_take"] = {
            "generated_voice_id": take.get("generated_voice_id"), "url": take.get("url"),
        }


def narrator_voice(assets: Mapping[str, Any]) -> dict:
    stored = assets.get(NARRATOR_KEY)
    return dict(stored) if isinstance(stored, Mapping) and stored.get("voice_id") else {}


def set_narrator_voice(
    assets: MutableMapping[str, Any], *, voice_id: str, source: str, label: str = "", voice_prompt: str = "", take: Mapping[str, Any] | None = None,
) -> None:
    """The narrator is kept beside the cast, never in it: it is not a character and has no face to lock."""
    assets[NARRATOR_KEY] = {
        "voice_id": str(voice_id), "source": source, "label": label, "voice_prompt": voice_prompt,
        "take": {"generated_voice_id": take.get("generated_voice_id"), "url": take.get("url")} if take else None,
    }


def speaker_voice_map(assets: Mapping[str, Any]) -> dict[str, str]:
    """``{speaker: voice_id}`` the dubbing should use: the cast's voices and the narrator's under each of its names."""
    voices = {
        str(character.get("name") or "").strip(): str(character.get("voice_id") or character.get("voiceId") or "").strip()
        for character in dna_characters(assets)
    }
    narrator = narrator_voice(assets).get("voice_id")
    if narrator:
        voices.update({name: str(narrator) for name in NARRATOR_SPEAKERS})
    return {name: voice for name, voice in voices.items() if name and voice}


__all__ = [
    "AUDITIONS_KEY", "DEFAULT_NARRATOR_PROMPT", "MAX_ROUNDS", "MIN_AUDITION_CHARS", "NARRATOR_KEY", "NARRATOR_NAME",
    "audition_request", "audition_text", "dna_character", "dna_characters",
    "find_preview", "is_cast_member", "narrator_voice", "record_round", "set_narrator_voice", "set_voice",
    "speaker_voice_map", "voice_prompt_of",
]

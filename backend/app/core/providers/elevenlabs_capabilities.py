"""Versioned ElevenLabs capability catalog used by discovery and production APIs.

The ElevenLabs navigation mixes model-backed generation with resource and
utility APIs.  Keeping those concepts separate prevents service names such as
``Audio Isolation`` from being persisted as fake model IDs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from app.core import prompt_data


_WORDING_FILE = "providers_elevenlabs_capabilities"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/providers_elevenlabs_capabilities.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


class ElevenLabsCapability(BaseModel):
    id: str
    label: str
    label_en: str
    kind: Literal["model_backed", "service", "resource", "embed"]
    model_ids: list[str] = Field(default_factory=list)
    provider_endpoints: list[str] = Field(default_factory=list)
    project_entrypoints: list[str] = Field(default_factory=list)
    description: str


ELEVENLABS_CAPABILITIES: tuple[ElevenLabsCapability, ...] = (
    ElevenLabsCapability(
        id="text_to_speech",
        label=_text_of("module.label"),
        label_en="Text to Speech",
        kind="model_backed",
        model_ids=[
            "eleven_v3", "eleven_multilingual_v2", "eleven_flash_v2_5",
            "eleven_flash_v2",
        ],
        provider_endpoints=["POST /v1/text-to-speech/{voice_id}"],
        project_entrypoints=[
            "/api/production/audio/tts",
            "/api/production/audio/tts-with-timestamps",
        ],
        description=_text_of("module.description"),
    ),
    ElevenLabsCapability(
        id="speech_to_text",
        label=_text_of("module.label.2"),
        label_en="Speech to Text",
        kind="model_backed",
        model_ids=["scribe_v2", "scribe_v2_realtime"],
        provider_endpoints=["POST /v1/speech-to-text", "WSS /v1/speech-to-text/realtime"],
        project_entrypoints=["/api/production/audio/transcribe"],
        description=_text_of("module.description.2"),
    ),
    ElevenLabsCapability(
        id="music",
        label=_text_of("module.label.3"),
        label_en="Music",
        kind="model_backed",
        model_ids=["music_v2", "music_v1"],
        provider_endpoints=["POST /v1/music", "POST /v1/music/video-to-music"],
        project_entrypoints=[
            "/api/production/audio/music",
            "/api/production/audio/video-to-music",
        ],
        description=_text_of("module.description.3"),
    ),
    ElevenLabsCapability(
        id="speech_engine",
        label=_text_of("module.label.4"),
        label_en="Speech Engine",
        kind="resource",
        model_ids=["eleven_flash_v2_5", "eleven_flash_v2", "eleven_multilingual_v2"],
        provider_endpoints=["GET/POST /v1/speech-engine"],
        project_entrypoints=[
            "/api/production/audio/speech-engines",
        ],
        description=_text_of("module.description.4"),
    ),
    ElevenLabsCapability(
        id="voices",
        label=_text_of("module.label.5"),
        label_en="Voices",
        kind="resource",
        provider_endpoints=["GET /v2/voices"],
        project_entrypoints=["/api/production/audio/voices"],
        description=_text_of("module.description.5"),
    ),
    ElevenLabsCapability(
        id="text_to_dialogue",
        label=_text_of("module.label.6"),
        label_en="Text to Dialogue",
        kind="model_backed",
        model_ids=["eleven_v3"],
        provider_endpoints=["POST /v1/text-to-dialogue"],
        project_entrypoints=[
            "/api/production/audio/dialogue",
            "/api/production/audio/dialogue-with-timestamps",
        ],
        description=_text_of("module.description.6"),
    ),
    ElevenLabsCapability(
        id="voice_changer",
        label=_text_of("module.label.7"),
        label_en="Voice Changer",
        kind="model_backed",
        model_ids=["eleven_multilingual_sts_v2", "eleven_english_sts_v2"],
        provider_endpoints=["POST /v1/speech-to-speech/{voice_id}"],
        project_entrypoints=["/api/production/audio/voice-changer"],
        description=_text_of("module.description.7"),
    ),
    ElevenLabsCapability(
        id="voice_design",
        label=_text_of("module.label.8"),
        label_en="Voice Design",
        kind="model_backed",
        model_ids=["eleven_ttv_v3", "eleven_multilingual_ttv_v2"],
        provider_endpoints=["POST /v1/text-to-voice/design", "POST /v1/text-to-voice"],
        project_entrypoints=[
            "/api/production/audio/voice-design",
            "/api/production/audio/voice-design/voices",
        ],
        description=_text_of("module.description.8"),
    ),
    ElevenLabsCapability(
        id="sound_effects",
        label=_text_of("module.label.9"),
        label_en="Sound Effects",
        kind="model_backed",
        model_ids=["eleven_text_to_sound_v2"],
        provider_endpoints=["POST /v1/sound-generation"],
        project_entrypoints=["/api/production/audio/sound-effect"],
        description=_text_of("module.description.9"),
    ),
    ElevenLabsCapability(
        id="audio_isolation",
        label=_text_of("module.label.10"),
        label_en="Audio Isolation",
        kind="service",
        provider_endpoints=["POST /v1/audio-isolation"],
        project_entrypoints=["/api/production/audio/isolation"],
        description=_text_of("module.description.10"),
    ),
    ElevenLabsCapability(
        id="dubbing",
        label=_text_of("module.label.11"),
        label_en="Dubbing",
        kind="service",
        provider_endpoints=["POST /v1/dubbing"],
        project_entrypoints=["/api/production/audio/dub"],
        description=_text_of("module.description.11"),
    ),
    ElevenLabsCapability(
        id="forced_alignment",
        label=_text_of("module.label.12"),
        label_en="Forced Alignment",
        kind="service",
        provider_endpoints=["POST /v1/forced-alignment"],
        project_entrypoints=["/api/production/audio/forced-alignment"],
        description=_text_of("module.description.12"),
    ),
    ElevenLabsCapability(
        id="pronunciation_dictionaries",
        label=_text_of("module.label.13"),
        label_en="Pronunciation Dictionaries",
        kind="resource",
        model_ids=["eleven_v3", "eleven_flash_v2"],
        provider_endpoints=[
            "GET /v1/pronunciation-dictionaries",
            "POST /v1/pronunciation-dictionaries/add-from-rules",
        ],
        project_entrypoints=[
            "/api/production/audio/pronunciation-dictionaries",
        ],
        description=_text_of("module.description.13"),
    ),
    ElevenLabsCapability(
        id="audio_native",
        label="Audio Native",
        label_en="Audio Native",
        kind="embed",
        model_ids=[
            "eleven_v3", "eleven_multilingual_v2", "eleven_flash_v2_5",
            "eleven_flash_v2",
        ],
        provider_endpoints=["POST /v1/audio-native"],
        project_entrypoints=["/api/production/audio/audio-native"],
        description=_text_of("module.description.14"),
    ),
)


def elevenlabs_capability_catalog() -> list[dict]:
    return [item.model_dump() for item in ELEVENLABS_CAPABILITIES]

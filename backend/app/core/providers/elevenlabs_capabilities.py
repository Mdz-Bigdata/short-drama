"""Versioned ElevenLabs capability catalog used by discovery and production APIs.

The ElevenLabs navigation mixes model-backed generation with resource and
utility APIs.  Keeping those concepts separate prevents service names such as
``Audio Isolation`` from being persisted as fake model IDs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
        label="文本转语音",
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
        description="单人配音与字符级时间戳。",
    ),
    ElevenLabsCapability(
        id="speech_to_text",
        label="语音转文字",
        label_en="Speech to Text",
        kind="model_backed",
        model_ids=["scribe_v2", "scribe_v2_realtime"],
        provider_endpoints=["POST /v1/speech-to-text", "WSS /v1/speech-to-text/realtime"],
        project_entrypoints=["/api/production/audio/transcribe"],
        description="多语言转录、说话人分离、音频事件和词级时间戳。",
    ),
    ElevenLabsCapability(
        id="music",
        label="音乐",
        label_en="Music",
        kind="model_backed",
        model_ids=["music_v2", "music_v1"],
        provider_endpoints=["POST /v1/music", "POST /v1/music/video-to-music"],
        project_entrypoints=[
            "/api/production/audio/music",
            "/api/production/audio/video-to-music",
        ],
        description="文本配乐与视频参考配乐。",
    ),
    ElevenLabsCapability(
        id="speech_engine",
        label="语音引擎",
        label_en="Speech Engine",
        kind="resource",
        model_ids=["eleven_flash_v2_5", "eleven_flash_v2", "eleven_multilingual_v2"],
        provider_endpoints=["GET/POST /v1/speech-engine"],
        project_entrypoints=[
            "/api/production/audio/speech-engines",
        ],
        description="为自有 LLM 提供实时 ASR、轮次控制和 TTS 的语音会话资源。",
    ),
    ElevenLabsCapability(
        id="voices",
        label="声音库",
        label_en="Voices",
        kind="resource",
        provider_endpoints=["GET /v2/voices"],
        project_entrypoints=["/api/production/audio/voices"],
        description="分页查询账号可用的默认、个人、工作区和社区声音。",
    ),
    ElevenLabsCapability(
        id="text_to_dialogue",
        label="文本转对话",
        label_en="Text to Dialogue",
        kind="model_backed",
        model_ids=["eleven_v3"],
        provider_endpoints=["POST /v1/text-to-dialogue"],
        project_entrypoints=[
            "/api/production/audio/dialogue",
            "/api/production/audio/dialogue-with-timestamps",
        ],
        description="多角色自然对白与时间戳生成。",
    ),
    ElevenLabsCapability(
        id="voice_changer",
        label="变声器",
        label_en="Voice Changer",
        kind="model_backed",
        model_ids=["eleven_multilingual_sts_v2", "eleven_english_sts_v2"],
        provider_endpoints=["POST /v1/speech-to-speech/{voice_id}"],
        project_entrypoints=["/api/production/audio/voice-changer"],
        description="保留原始表演、节奏与情绪的语音到语音转换。",
    ),
    ElevenLabsCapability(
        id="voice_design",
        label="声音设计",
        label_en="Voice Design",
        kind="model_backed",
        model_ids=["eleven_ttv_v3", "eleven_multilingual_ttv_v2"],
        provider_endpoints=["POST /v1/text-to-voice/design", "POST /v1/text-to-voice"],
        project_entrypoints=[
            "/api/production/audio/voice-design",
            "/api/production/audio/voice-design/voices",
        ],
        description="按角色声音描述生成可试听的声音候选。",
    ),
    ElevenLabsCapability(
        id="sound_effects",
        label="音效",
        label_en="Sound Effects",
        kind="model_backed",
        model_ids=["eleven_text_to_sound_v2"],
        provider_endpoints=["POST /v1/sound-generation"],
        project_entrypoints=["/api/production/audio/sound-effect"],
        description="生成环境声、拟音和叙事音效。",
    ),
    ElevenLabsCapability(
        id="audio_isolation",
        label="语音隔离器",
        label_en="Audio Isolation",
        kind="service",
        provider_endpoints=["POST /v1/audio-isolation"],
        project_entrypoints=["/api/production/audio/isolation"],
        description="去除背景噪声并提取清晰语音。",
    ),
    ElevenLabsCapability(
        id="dubbing",
        label="配音",
        label_en="Dubbing",
        kind="service",
        provider_endpoints=["POST /v1/dubbing"],
        project_entrypoints=["/api/production/audio/dub"],
        description="保留说话人特征的音视频多语言配音。",
    ),
    ElevenLabsCapability(
        id="forced_alignment",
        label="强制对齐",
        label_en="Forced Alignment",
        kind="service",
        provider_endpoints=["POST /v1/forced-alignment"],
        project_entrypoints=["/api/production/audio/forced-alignment"],
        description="把既有录音与台词对齐为字符级和词级时间戳。",
    ),
    ElevenLabsCapability(
        id="pronunciation_dictionaries",
        label="发音词典",
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
        description="管理别名、IPA 和 CMU 发音规则；模型兼容性按官方约束显示。",
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
        description="把文章内容转换为可嵌入网页的语音播放器项目。",
    ),
)


def elevenlabs_capability_catalog() -> list[dict]:
    return [item.model_dump() for item in ELEVENLABS_CAPABILITIES]

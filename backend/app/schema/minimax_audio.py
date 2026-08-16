"""Validated contracts for MiniMax speech, music and one-step music cover."""

from __future__ import annotations

import ipaddress
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MiniMaxSpeechModel = Literal[
    "speech-2.8-hd",
    "speech-2.8-turbo",
    "speech-2.6-hd",
    "speech-2.6-turbo",
    "speech-02-hd",
    "speech-02-turbo",
    "speech-01-hd",
    "speech-01-turbo",
]
MiniMaxAudioFormat = Literal["mp3", "wav", "flac", "pcm"]
MiniMaxEmotion = Literal[
    "happy",
    "sad",
    "angry",
    "fearful",
    "disgusted",
    "surprised",
    "calm",
    "fluent",
    "whisper",
    "whipser",
]


class MiniMaxTTSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    model: MiniMaxSpeechModel = "speech-2.8-hd"
    text: Annotated[str, Field(min_length=1, max_length=9999)]
    voice_id: Annotated[str, Field(min_length=1, max_length=200)]
    speed: Annotated[float, Field(ge=0.5, le=2.0)] = 1.0
    volume: Annotated[float, Field(ge=0, le=10)] = 1.0
    pitch: Annotated[int, Field(ge=-12, le=12)] = 0
    emotion: MiniMaxEmotion | None = None
    sample_rate: Literal[8000, 16000, 22050, 24000, 32000, 44100] = 32000
    bitrate: Literal[32000, 64000, 128000, 256000] = 128000
    audio_format: MiniMaxAudioFormat = "mp3"
    channel: Literal[1, 2] = 1
    language_boost: Annotated[str | None, Field(min_length=2, max_length=40)] = None
    pronunciation_tones: Annotated[list[str], Field(max_length=100)] = Field(
        default_factory=list
    )
    subtitle_enable: bool = False

    @field_validator("pronunciation_tones")
    @classmethod
    def validate_pronunciation_tones(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 300 for value in cleaned):
            raise ValueError("pronunciation tone entries must contain 1 to 300 characters")
        return list(dict.fromkeys(cleaned))


class MiniMaxMusicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    model: Literal["music-3.0"] = "music-3.0"
    prompt: Annotated[str, Field(min_length=1, max_length=2000)]
    lyrics: Annotated[str | None, Field(max_length=3500)] = None
    lyrics_optimizer: bool = False
    is_instrumental: bool = False
    sample_rate: Literal[32000, 44100] = 44100
    bitrate: Literal[128000, 256000] = 256000
    audio_format: Literal["mp3", "wav", "pcm"] = "mp3"
    aigc_watermark: bool = False

    @model_validator(mode="after")
    def require_lyrics_strategy(self) -> "MiniMaxMusicRequest":
        if not self.is_instrumental and not self.lyrics and not self.lyrics_optimizer:
            raise ValueError(
                "vocal music requires lyrics or lyrics_optimizer=true; "
                "set is_instrumental=true for instrumental music"
            )
        return self


class MiniMaxMusicCoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    model: Literal["music-cover"] = "music-cover"
    audio_url: Annotated[str, Field(min_length=8, max_length=2048)]
    prompt: Annotated[str, Field(min_length=10, max_length=300)]
    lyrics: Annotated[str | None, Field(min_length=10, max_length=1000)] = None
    sample_rate: Literal[32000, 44100] = 44100
    bitrate: Literal[128000, 256000] = 256000
    audio_format: Literal["mp3", "wav", "pcm"] = "mp3"
    aigc_watermark: bool = False

    @field_validator("audio_url")
    @classmethod
    def validate_reference_audio_url(cls, value: str) -> str:
        clean = value.strip()
        parsed = urlsplit(clean)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("cover reference must use an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("cover reference URL cannot contain credentials or fragments")
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(".localhost"):
            raise ValueError("cover reference must be publicly reachable")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("cover reference must be publicly reachable")
        return clean

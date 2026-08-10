"""Server-side ElevenLabs adapter for speech, dialogue, SFX, music, STT and dubbing."""

from __future__ import annotations

import io
import os
import base64
from typing import BinaryIO

import httpx
from pydantic import BaseModel, Field

from app.platform.runtime_models import runtime_model_registry


class DialogueLine(BaseModel):
    voice_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10000)
    emotion: str = Field(default="neutral", max_length=80)


class ElevenLabsClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 180,
    ):
        runtime = runtime_model_registry.first("elevenlabs", "audio")
        key = (
            api_key
            or (runtime.api_key if runtime else None)
            or os.getenv("ELEVENLABS_API_KEY")
            or ""
        ).strip()
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY is required on the server")
        self._client = httpx.Client(
            base_url=(
                base_url
                or (runtime.base_url if runtime else None)
                or os.getenv("ELEVENLABS_BASE_URL")
                or "https://api.elevenlabs.io"
            ).rstrip("/"),
            headers={"xi-api-key": key},
            timeout=timeout_seconds,
            transport=transport,
        )

    @staticmethod
    def _raise_safe(response: httpx.Response) -> None:
        if response.is_success:
            return
        request_id = response.headers.get("request-id", "unknown")
        raise RuntimeError(f"ElevenLabs request failed: HTTP {response.status_code}, request_id={request_id}")

    @staticmethod
    def _voice_settings(emotion: str, speed: float) -> dict:
        if not 0.7 <= speed <= 1.2:
            raise ValueError("ElevenLabs speed must be between 0.7 and 1.2")
        intense = any(word in emotion.lower() for word in ("怒", "崩溃", "激动", "fear", "angry"))
        restrained = any(word in emotion.lower() for word in ("克制", "压抑", "平静", "restrained"))
        return {
            "stability": 0.35 if intense else (0.68 if restrained else 0.5),
            "similarity_boost": 0.78,
            "style": 0.65 if intense else (0.18 if restrained else 0.35),
            "use_speaker_boost": True,
            "speed": speed,
        }

    @staticmethod
    def _emotion_tag(emotion: str) -> str:
        mapping = {
            "愤怒": "angry", "激动": "excited", "悲伤": "sad", "温柔": "gentle",
            "压抑": "restrained", "克制悲伤": "restrained and sad", "恐惧": "fearful",
        }
        tag = mapping.get(emotion.strip(), emotion.strip())
        return f"[{tag}] " if tag and tag.lower() != "neutral" else ""

    def text_to_speech(
        self,
        text: str,
        voice_id: str,
        *,
        emotion: str = "neutral",
        speed: float = 1.0,
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "mp3_44100_128",
    ) -> bytes:
        response = self._client.post(
            f"/v1/text-to-speech/{voice_id}",
            params={"output_format": output_format},
            json={
                "text": text,
                "model_id": model_id,
                "voice_settings": self._voice_settings(emotion, speed),
            },
        )
        self._raise_safe(response)
        return response.content

    @staticmethod
    def _timed_audio(response: httpx.Response) -> dict:
        ElevenLabsClient._raise_safe(response)
        payload = response.json()
        encoded = payload.pop("audio_base64", "")
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("ElevenLabs timing response contained invalid audio") from exc
        if not audio:
            raise RuntimeError("ElevenLabs timing response contained empty audio")
        return {"audio": audio, **payload}

    def text_to_speech_with_timestamps(
        self,
        text: str,
        voice_id: str,
        *,
        emotion: str = "neutral",
        speed: float = 1.0,
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "mp3_44100_128",
    ) -> dict:
        response = self._client.post(
            f"/v1/text-to-speech/{voice_id}/with-timestamps",
            params={"output_format": output_format},
            json={
                "text": text,
                "model_id": model_id,
                "voice_settings": self._voice_settings(emotion, speed),
            },
        )
        return self._timed_audio(response)

    def create_dialogue(
        self,
        lines: list[DialogueLine],
        *,
        output_format: str = "mp3_44100_128",
    ) -> bytes:
        if not lines:
            raise ValueError("dialogue requires at least one line")
        response = self._client.post(
            "/v1/text-to-dialogue",
            params={"output_format": output_format},
            json={"inputs": [
                {"voice_id": line.voice_id, "text": self._emotion_tag(line.emotion) + line.text}
                for line in lines
            ]},
        )
        self._raise_safe(response)
        return response.content

    def create_dialogue_with_timestamps(
        self,
        lines: list[DialogueLine],
        *,
        output_format: str = "mp3_44100_128",
    ) -> dict:
        if not lines:
            raise ValueError("dialogue requires at least one line")
        if len({line.voice_id for line in lines}) > 10:
            raise ValueError("ElevenLabs dialogue accepts at most 10 unique voices")
        if sum(len(line.text) for line in lines) > 2000:
            raise ValueError("timed dialogue should contain at most 2,000 characters")
        response = self._client.post(
            "/v1/text-to-dialogue/with-timestamps",
            params={"output_format": output_format},
            json={"inputs": [
                {"voice_id": line.voice_id, "text": self._emotion_tag(line.emotion) + line.text}
                for line in lines
            ]},
        )
        return self._timed_audio(response)

    def sound_effect(
        self,
        prompt: str,
        *,
        duration_seconds: float | None = None,
        prompt_influence: float = 0.5,
    ) -> bytes:
        payload: dict[str, object] = {
            "text": prompt,
            "prompt_influence": prompt_influence,
        }
        if duration_seconds is not None:
            payload["duration_seconds"] = duration_seconds
        response = self._client.post("/v1/sound-generation", json=payload)
        self._raise_safe(response)
        return response.content

    def compose_music(
        self,
        prompt: str,
        *,
        duration_seconds: float,
        instrumental: bool = True,
        model_id: str = "music_v2",
    ) -> bytes:
        if not 3 <= duration_seconds <= 600:
            raise ValueError("music duration must be between 3 and 600 seconds")
        response = self._client.post(
            "/v1/music",
            json={
                "prompt": prompt,
                "music_length_ms": int(duration_seconds * 1000),
                "force_instrumental": instrumental,
                "model_id": model_id,
            },
        )
        self._raise_safe(response)
        return response.content

    def video_to_music(
        self,
        videos: list[tuple[str, BinaryIO | io.BytesIO]],
        *,
        description: str = "",
        tags: list[str] | None = None,
        model_id: str = "music_v2",
        sign_with_c2pa: bool = False,
        output_format: str = "mp3_44100_128",
    ) -> bytes:
        if not 1 <= len(videos) <= 10:
            raise ValueError("video-to-music requires 1 to 10 video files")
        if len(description) > 1000:
            raise ValueError("video-to-music description exceeds 1,000 characters")
        style_tags = list(tags or [])
        if len(style_tags) > 10 or any(not tag or len(tag) > 80 for tag in style_tags):
            raise ValueError("video-to-music accepts at most 10 short style tags")
        files = [
            ("videos[]", (filename, stream, "video/mp4")) for filename, stream in videos
        ]
        data = {
            "description": description,
            "model_id": model_id,
            "sign_with_c2pa": str(sign_with_c2pa).lower(),
            "tags": style_tags,
        }
        response = self._client.post(
            "/v1/music/video-to-music",
            params={"output_format": output_format},
            data=data,
            files=files,
        )
        self._raise_safe(response)
        return response.content

    def transcribe(
        self,
        file: BinaryIO | io.BytesIO,
        *,
        filename: str,
        language_code: str | None = None,
        diarize: bool = True,
        num_speakers: int | None = None,
    ) -> dict:
        data: dict[str, str] = {
            "model_id": "scribe_v2",
            "diarize": str(diarize).lower(),
            "tag_audio_events": "true",
            "timestamps_granularity": "word",
        }
        if language_code:
            data["language_code"] = language_code
        if num_speakers is not None:
            data["num_speakers"] = str(num_speakers)
        response = self._client.post(
            "/v1/speech-to-text",
            data=data,
            files={"file": (filename, file, "application/octet-stream")},
        )
        self._raise_safe(response)
        return response.json()

    def create_dub(
        self,
        *,
        source_url: str,
        target_language: str,
        source_language: str = "auto",
        num_speakers: int = 0,
    ) -> dict:
        response = self._client.post(
            "/v1/dubbing",
            data={
                "source_url": source_url,
                "source_lang": source_language,
                "target_lang": target_language,
                "num_speakers": str(num_speakers),
            },
        )
        self._raise_safe(response)
        return response.json()

    def close(self) -> None:
        self._client.close()

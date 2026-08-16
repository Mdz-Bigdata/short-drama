"""Server-side ElevenLabs adapter for the complete short-drama audio toolset."""

from __future__ import annotations

import io
import os
import base64
import json
from typing import BinaryIO
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field

from app.platform.runtime_models import runtime_model_registry


class DialogueLine(BaseModel):
    voice_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10000)
    emotion: str = Field(default="neutral", max_length=80)


class ElevenLabsClient:
    _ENDPOINT_SUFFIXES = (
        "/v1/sound-generation",
        "/v1/text-to-dialogue/with-timestamps",
        "/v1/text-to-dialogue",
        "/v1/music/video-to-music",
        "/v1/music",
        "/v1/speech-to-text",
        "/v1/dubbing",
        "/v1/text-to-voice/design",
        "/v1/text-to-voice",
        "/v1/audio-isolation",
        "/v1/forced-alignment",
        "/v1/pronunciation-dictionaries/add-from-rules",
        "/v1/pronunciation-dictionaries",
        "/v1/speech-engine",
        "/v1/audio-native",
        "/v2/voices",
    )

    @classmethod
    def _api_root(cls, configured_url: str) -> str:
        """Accept either an API root or one of the documented endpoint URLs."""
        candidate = configured_url.strip().rstrip("/")
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("ElevenLabs base URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password:
            raise ValueError("ElevenLabs base URL cannot contain credentials")
        path = parsed.path.rstrip("/")
        for suffix in cls._ENDPOINT_SUFFIXES:
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                break
        else:
            if path.endswith("/v1"):
                path = path[:-3]
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")

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
        configured_url = (
                base_url
                or (runtime.base_url if runtime else None)
                or os.getenv("ELEVENLABS_BASE_URL")
                or "https://api.elevenlabs.io"
            )
        self._client = httpx.Client(
            base_url=self._api_root(configured_url),
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
        pronunciation_dictionary_locators: list[dict[str, str]] | None = None,
    ) -> bytes:
        payload: dict[str, object] = {
            "text": text,
            "model_id": model_id,
            "voice_settings": self._voice_settings(emotion, speed),
        }
        if pronunciation_dictionary_locators:
            payload["pronunciation_dictionary_locators"] = pronunciation_dictionary_locators
        response = self._client.post(
            f"/v1/text-to-speech/{voice_id}",
            params={"output_format": output_format},
            json=payload,
        )
        self._raise_safe(response)
        return response.content

    def list_voices(
        self,
        *,
        page_size: int = 100,
        next_page_token: str | None = None,
        search: str | None = None,
        voice_type: str | None = None,
    ) -> dict:
        if not 1 <= page_size <= 100:
            raise ValueError("voice page_size must be between 1 and 100")
        params: dict[str, object] = {
            "page_size": page_size,
            "include_total_count": True,
        }
        if next_page_token:
            params["next_page_token"] = next_page_token
        if search:
            params["search"] = search
        if voice_type:
            params["voice_type"] = voice_type
        response = self._client.get("/v2/voices", params=params)
        self._raise_safe(response)
        return response.json()

    def list_speech_engines(
        self,
        *,
        page_size: int = 30,
        cursor: str | None = None,
        search: str | None = None,
    ) -> dict:
        if not 1 <= page_size <= 100:
            raise ValueError("speech engine page_size must be between 1 and 100")
        params: dict[str, object] = {"page_size": page_size}
        if cursor:
            params["cursor"] = cursor
        if search:
            params["search"] = search
        response = self._client.get("/v1/speech-engine", params=params)
        self._raise_safe(response)
        return response.json()

    def create_speech_engine(
        self,
        *,
        name: str,
        ws_url: str,
        voice_id: str,
        model_id: str,
        language: str,
        tags: list[str],
    ) -> dict:
        response = self._client.post(
            "/v1/speech-engine",
            json={
                "name": name,
                "speech_engine": {"ws_url": ws_url},
                "tts": {"voice_id": voice_id, "model_id": model_id},
                "language": language,
                "tags": tags,
            },
        )
        self._raise_safe(response)
        return response.json()

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
        pronunciation_dictionary_locators: list[dict[str, str]] | None = None,
    ) -> dict:
        payload: dict[str, object] = {
            "text": text,
            "model_id": model_id,
            "voice_settings": self._voice_settings(emotion, speed),
        }
        if pronunciation_dictionary_locators:
            payload["pronunciation_dictionary_locators"] = pronunciation_dictionary_locators
        response = self._client.post(
            f"/v1/text-to-speech/{voice_id}/with-timestamps",
            params={"output_format": output_format},
            json=payload,
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

    def voice_change(
        self,
        audio: BinaryIO | io.BytesIO,
        *,
        filename: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_sts_v2",
        remove_background_noise: bool = False,
        output_format: str = "mp3_44100_128",
    ) -> bytes:
        if model_id not in {"eleven_multilingual_sts_v2", "eleven_english_sts_v2"}:
            raise ValueError("voice changer model does not support speech-to-speech")
        response = self._client.post(
            f"/v1/speech-to-speech/{voice_id}",
            params={"output_format": output_format},
            data={
                "model_id": model_id,
                "remove_background_noise": str(remove_background_noise).lower(),
            },
            files={"audio": (filename, audio, "application/octet-stream")},
        )
        self._raise_safe(response)
        return response.content

    def design_voice(
        self,
        *,
        voice_description: str,
        text: str | None,
        auto_generate_text: bool,
        model_id: str,
        seed: int | None,
        guidance_scale: float,
        should_enhance: bool,
        output_format: str = "mp3_44100_128",
    ) -> dict:
        payload: dict[str, object] = {
            "voice_description": voice_description,
            "auto_generate_text": auto_generate_text,
            "model_id": model_id,
            "guidance_scale": guidance_scale,
            "should_enhance": should_enhance,
        }
        if text is not None:
            payload["text"] = text
        if seed is not None:
            payload["seed"] = seed
        response = self._client.post(
            "/v1/text-to-voice/design",
            params={"output_format": output_format},
            json=payload,
        )
        self._raise_safe(response)
        return response.json()

    def create_designed_voice(
        self,
        *,
        voice_name: str,
        voice_description: str,
        generated_voice_id: str,
        labels: dict[str, str],
    ) -> dict:
        response = self._client.post(
            "/v1/text-to-voice",
            json={
                "voice_name": voice_name,
                "voice_description": voice_description,
                "generated_voice_id": generated_voice_id,
                "labels": labels,
            },
        )
        self._raise_safe(response)
        return response.json()

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

    def isolate_audio(
        self,
        audio: BinaryIO | io.BytesIO,
        *,
        filename: str,
        file_format: str = "other",
    ) -> bytes:
        if file_format not in {"other", "pcm_s16le_16"}:
            raise ValueError("unsupported audio isolation input format")
        response = self._client.post(
            "/v1/audio-isolation",
            data={"file_format": file_format},
            files={"audio": (filename, audio, "application/octet-stream")},
        )
        self._raise_safe(response)
        return response.content

    def force_align(
        self,
        audio: BinaryIO | io.BytesIO,
        *,
        filename: str,
        text: str,
    ) -> dict:
        response = self._client.post(
            "/v1/forced-alignment",
            data={"text": text},
            files={"file": (filename, audio, "application/octet-stream")},
        )
        self._raise_safe(response)
        return response.json()

    def list_pronunciation_dictionaries(
        self,
        *,
        page_size: int = 30,
        cursor: str | None = None,
        include_archived: bool = False,
    ) -> dict:
        if not 1 <= page_size <= 100:
            raise ValueError("dictionary page_size must be between 1 and 100")
        params: dict[str, object] = {
            "page_size": page_size,
            "include_archived": include_archived,
        }
        if cursor:
            params["cursor"] = cursor
        response = self._client.get("/v1/pronunciation-dictionaries", params=params)
        self._raise_safe(response)
        return response.json()

    def create_pronunciation_dictionary(
        self,
        *,
        name: str,
        description: str,
        rules: list[dict],
        workspace_access: str | None = None,
    ) -> dict:
        payload: dict[str, object] = {
            "name": name,
            "description": description,
            "rules": rules,
        }
        if workspace_access:
            payload["workspace_access"] = workspace_access
        response = self._client.post(
            "/v1/pronunciation-dictionaries/add-from-rules",
            json=payload,
        )
        self._raise_safe(response)
        return response.json()

    def create_audio_native(
        self,
        *,
        name: str,
        file: BinaryIO | io.BytesIO | None = None,
        filename: str | None = None,
        author: str | None = None,
        title: str | None = None,
        voice_id: str | None = None,
        model_id: str | None = None,
        auto_convert: bool = False,
        pronunciation_dictionary_locators: list[dict[str, str]] | None = None,
    ) -> dict:
        multipart: list[tuple[str, tuple]] = [("name", (None, name))]
        for field, value in (
            ("author", author), ("title", title), ("voice_id", voice_id),
            ("model_id", model_id),
        ):
            if value:
                multipart.append((field, (None, value)))
        multipart.append(("auto_convert", (None, str(auto_convert).lower())))
        for locator in pronunciation_dictionary_locators or []:
            multipart.append((
                "pronunciation_dictionary_locators",
                (None, json.dumps(locator, ensure_ascii=False, separators=(",", ":"))),
            ))
        if file is not None:
            multipart.append((
                "file",
                (filename or "article.txt", file, "application/octet-stream"),
            ))
        response = self._client.post("/v1/audio-native", files=multipart)
        self._raise_safe(response)
        return response.json()

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

"""Server-side MiniMax adapter for synchronous TTS, Music 3.0 and Music Cover."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.platform.runtime_models import runtime_model_registry
from app.schema.minimax_audio import (
    MiniMaxMusicCoverRequest,
    MiniMaxMusicRequest,
    MiniMaxTTSRequest,
)


@dataclass(frozen=True)
class MiniMaxAudioArtifact:
    model_id: str
    kind: str
    audio: bytes | None = None
    audio_url: str | None = None
    trace_id: str | None = None
    extra_info: dict[str, Any] = field(default_factory=dict)


class MiniMaxAudioClient:
    _ENDPOINT_SUFFIXES = (
        "/v1/music_cover_preprocess",
        "/v1/music_generation",
        "/v1/t2a_async_v2",
        "/v1/t2a_v2",
        "/v2/models",
        "/v1/models",
        "/models",
    )
    _MAX_AUDIO_BYTES = 100 * 1024 * 1024

    @classmethod
    def _api_root(cls, configured_url: str) -> str:
        candidate = configured_url.strip().rstrip("/")
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("MiniMax base URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("MiniMax base URL cannot contain credentials or fragments")
        path = parsed.path.rstrip("/")
        for suffix in cls._ENDPOINT_SUFFIXES:
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                break
        else:
            if path.endswith(("/v1", "/v2")):
                path = path[:-3]
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 300,
    ) -> None:
        runtime = runtime_model_registry.first("minimax", "audio")
        key = (
            api_key
            or (runtime.api_key if runtime else None)
            or os.getenv("MINIMAX_API_KEY")
            or ""
        ).strip()
        if not key:
            raise RuntimeError("MINIMAX_API_KEY is required on the server")
        configured_url = (
            base_url
            or (runtime.base_url if runtime else None)
            or os.getenv("MINIMAX_BASE_URL")
            or "https://api.minimaxi.com"
        )
        self._client = httpx.Client(
            base_url=self._api_root(configured_url),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout_seconds,
            transport=transport,
        )

    @staticmethod
    def _raise_safe(response: httpx.Response) -> None:
        if response.is_success:
            return
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("trace-id")
            or "unknown"
        )
        raise RuntimeError(
            f"MiniMax audio request failed: HTTP {response.status_code}, "
            f"request_id={request_id}"
        )

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(endpoint, json=payload)
        self._raise_safe(response)
        if len(response.content) > self._MAX_AUDIO_BYTES * 2 + 2 * 1024 * 1024:
            raise RuntimeError("MiniMax audio response exceeded the safe size limit")
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("MiniMax audio response was not valid JSON") from exc
        if not isinstance(result, dict):
            raise RuntimeError("MiniMax audio response had an invalid shape")
        base_resp = result.get("base_resp")
        provider_code = base_resp.get("status_code") if isinstance(base_resp, dict) else 0
        if provider_code not in (0, "0", None):
            trace_id = str(result.get("trace_id") or "unknown")
            raise RuntimeError(
                f"MiniMax audio request failed: provider_code={provider_code}, "
                f"trace_id={trace_id}"
            )
        return result

    def _artifact(
        self,
        result: dict[str, Any],
        *,
        model_id: str,
        kind: str,
        output_format: str,
    ) -> MiniMaxAudioArtifact:
        data = result.get("data")
        encoded = data.get("audio") if isinstance(data, dict) else None
        if not isinstance(encoded, str) or not encoded:
            raise RuntimeError("MiniMax audio response did not contain audio")
        trace_id = str(result.get("trace_id")) if result.get("trace_id") else None
        extra_info = result.get("extra_info")
        safe_extra = extra_info if isinstance(extra_info, dict) else {}
        if output_format == "url":
            parsed = urlsplit(encoded)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise RuntimeError("MiniMax audio response contained an invalid audio URL")
            if parsed.username or parsed.password:
                raise RuntimeError("MiniMax audio response contained an unsafe audio URL")
            return MiniMaxAudioArtifact(
                model_id=model_id,
                kind=kind,
                audio_url=encoded,
                trace_id=trace_id,
                extra_info=safe_extra,
            )
        try:
            audio = bytes.fromhex(encoded)
        except ValueError as exc:
            raise RuntimeError("MiniMax audio response contained invalid hex audio") from exc
        if not audio or len(audio) > self._MAX_AUDIO_BYTES:
            raise RuntimeError("MiniMax audio response exceeded the safe audio limit")
        return MiniMaxAudioArtifact(
            model_id=model_id,
            kind=kind,
            audio=audio,
            trace_id=trace_id,
            extra_info=safe_extra,
        )

    def text_to_speech(self, request: MiniMaxTTSRequest) -> MiniMaxAudioArtifact:
        voice_setting: dict[str, Any] = {
            "voice_id": request.voice_id,
            "speed": request.speed,
            "vol": request.volume,
            "pitch": request.pitch,
        }
        if request.emotion:
            voice_setting["emotion"] = (
                "whipser" if request.emotion == "whisper" else request.emotion
            )
        payload: dict[str, Any] = {
            "model": request.model,
            "text": request.text,
            "stream": False,
            "voice_setting": voice_setting,
            "audio_setting": {
                "sample_rate": request.sample_rate,
                "bitrate": request.bitrate,
                "format": request.audio_format,
                "channel": request.channel,
            },
            "subtitle_enable": request.subtitle_enable,
            "output_format": "hex",
        }
        if request.language_boost:
            payload["language_boost"] = request.language_boost
        if request.pronunciation_tones:
            payload["pronunciation_dict"] = {"tone": request.pronunciation_tones}
        result = self._post("/v1/t2a_v2", payload)
        return self._artifact(
            result,
            model_id=request.model,
            kind="tts",
            output_format="hex",
        )

    @staticmethod
    def _audio_setting(
        *, sample_rate: int, bitrate: int, audio_format: str
    ) -> dict[str, Any]:
        return {
            "sample_rate": sample_rate,
            "bitrate": bitrate,
            "format": audio_format,
        }

    def generate_music(self, request: MiniMaxMusicRequest) -> MiniMaxAudioArtifact:
        payload: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "audio_setting": self._audio_setting(
                sample_rate=request.sample_rate,
                bitrate=request.bitrate,
                audio_format=request.audio_format,
            ),
            "output_format": "url",
            "lyrics_optimizer": request.lyrics_optimizer,
            "is_instrumental": request.is_instrumental,
            "aigc_watermark": request.aigc_watermark,
        }
        if request.lyrics:
            payload["lyrics"] = request.lyrics
        result = self._post("/v1/music_generation", payload)
        return self._artifact(
            result,
            model_id=request.model,
            kind="music",
            output_format="url",
        )

    def cover_music(
        self, request: MiniMaxMusicCoverRequest
    ) -> MiniMaxAudioArtifact:
        payload: dict[str, Any] = {
            "model": request.model,
            "audio_url": request.audio_url,
            "prompt": request.prompt,
            "audio_setting": self._audio_setting(
                sample_rate=request.sample_rate,
                bitrate=request.bitrate,
                audio_format=request.audio_format,
            ),
            "output_format": "url",
            "aigc_watermark": request.aigc_watermark,
        }
        if request.lyrics:
            payload["lyrics"] = request.lyrics
        result = self._post("/v1/music_generation", payload)
        return self._artifact(
            result,
            model_id=request.model,
            kind="music_cover",
            output_format="url",
        )

    def close(self) -> None:
        self._client.close()

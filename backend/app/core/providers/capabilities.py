"""Provider capability negotiation before any paid submission."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schema.production import H3VideoRequest


class ProviderCapabilities(BaseModel):
    provider: str
    operations: list[str]
    modes: list[str] = Field(default_factory=list)
    limits: dict[str, int | float | str | bool] = Field(default_factory=dict)


class CapabilityDecision(BaseModel):
    compatible: bool
    provider: str
    operation: str
    mode: str
    reasons: list[str] = Field(default_factory=list)


class ProviderCapabilityRegistry:
    def __init__(self) -> None:
        self._providers = {
            "minimax_h3": ProviderCapabilities(
                provider="minimax_h3",
                operations=["video_generation", "task_polling"],
                modes=["text", "first_frame", "last_frame", "first_last_frame", "reference"],
                limits={
                    "images": 9, "videos": 3, "audios": 3, "mixed_files": 12,
                    "min_duration_seconds": 4, "max_duration_seconds": 15,
                    "native_audio": True, "max_resolution": "2k",
                },
            ),
            "elevenlabs": ProviderCapabilities(
                provider="elevenlabs",
                operations=[
                    "tts", "tts_with_timestamps", "dialogue", "dialogue_with_timestamps",
                    "sound_effect", "music", "video_to_music", "speech_to_text", "dubbing",
                ],
                modes=[
                    "stream_or_file", "character_alignment", "multi_speaker", "instrumental",
                    "video_conditioned_music", "diarization",
                ],
                limits={
                    "sound_effect_max_seconds": 22, "music_max_seconds": 600,
                    "dialogue_unique_voices": 10, "video_to_music_files": 10,
                    "video_to_music_total_bytes": 200 * 1024 * 1024,
                },
            ),
        }

    def list(self) -> dict[str, ProviderCapabilities]:
        return dict(self._providers)

    def negotiate_h3(self, request: H3VideoRequest) -> CapabilityDecision:
        # Pydantic has already enforced all hard count/combination constraints.
        return CapabilityDecision(
            compatible=True,
            provider="minimax_h3",
            operation="video_generation",
            mode=request.inferred_mode,
            reasons=["request satisfies the current H3 mode, reference-count and duration contract"],
        )

"""Provider capability negotiation before any paid submission."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schema.production import H3VideoRequest
from app.core.video_references import VIDEO_PROVIDER_PROFILES


class ProviderCapabilities(BaseModel):
    provider: str
    operations: list[str]
    modes: list[str] = Field(default_factory=list)
    limits: dict[str, int | float | str | bool] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    verification_status: str = "integrated"
    capability_source: str = "project adapter"
    notes: list[str] = Field(default_factory=list)


class CapabilityDecision(BaseModel):
    compatible: bool
    provider: str
    operation: str
    mode: str
    reasons: list[str] = Field(default_factory=list)


class ProviderCapabilityRegistry:
    def __init__(self) -> None:
        video_profiles = {
            profile.family: ProviderCapabilities(
                provider=profile.family,
                operations=["video_generation", "task_polling"],
                modes=profile.modes,
                limits={
                    "images": profile.max_reference_images,
                    "videos": profile.max_reference_videos,
                    "audios": profile.max_reference_audios,
                },
                aliases=profile.aliases,
                verification_status=profile.verification_status,
                capability_source=profile.capability_source,
                notes=profile.notes,
            )
            for profile in VIDEO_PROVIDER_PROFILES
        }
        self._providers = {
            **video_profiles,
            "minimax_h3": ProviderCapabilities(
                provider="minimax_h3",
                operations=["video_generation", "task_polling"],
                modes=[
                    "text", "first_frame", "last_frame", "first_last_frame",
                    "multi_reference", "multimodal", "reference",
                ],
                limits={
                    "images": 9, "videos": 3, "audios": 3, "mixed_files": 12,
                    "min_duration_seconds": 4, "max_duration_seconds": 15,
                    "native_audio": True, "max_resolution": "2k",
                },
                aliases=video_profiles["minimax_h3"].aliases,
                verification_status="integrated",
                capability_source=video_profiles["minimax_h3"].capability_source,
                notes=video_profiles["minimax_h3"].notes,
            ),
            "elevenlabs": ProviderCapabilities(
                provider="elevenlabs",
                operations=[
                    "tts", "tts_with_timestamps", "dialogue", "dialogue_with_timestamps",
                    "sound_effect", "music", "video_to_music", "speech_to_text", "dubbing",
                    "voices_list", "speech_engine_list", "speech_engine_create",
                    "voice_changer", "voice_design", "audio_isolation", "forced_alignment",
                    "pronunciation_dictionary_list", "pronunciation_dictionary_create",
                    "audio_native",
                ],
                modes=[
                    "stream_or_file", "character_alignment", "multi_speaker", "instrumental",
                    "video_conditioned_music", "diarization", "speech_to_speech",
                    "voice_preview", "noise_removal", "forced_timing", "embeddable_player",
                ],
                limits={
                    "sound_effect_max_seconds": 22, "music_max_seconds": 600,
                    "dialogue_unique_voices": 10, "video_to_music_files": 10,
                    "video_to_music_total_bytes": 200 * 1024 * 1024,
                    "voices_page_size": 100, "speech_engines_page_size": 100,
                    "forced_alignment_text_characters": 675_000,
                    "pronunciation_dictionary_page_size": 100,
                },
            ),
            "minimax_audio": ProviderCapabilities(
                provider="minimax",
                operations=["tts", "music_generation", "music_cover"],
                modes=[
                    "synchronous_speech",
                    "emotion_and_paralinguistic_tags",
                    "lyrics_to_music",
                    "prompt_generated_lyrics",
                    "instrumental",
                    "one_step_audio_reference_cover",
                ],
                limits={
                    "speech_text_characters": 9999,
                    "music_prompt_characters": 2000,
                    "music_lyrics_characters": 3500,
                    "cover_prompt_characters": 300,
                    "cover_reference_max_bytes": 50 * 1024 * 1024,
                    "cover_reference_max_seconds": 360,
                    "result_url_expires_seconds": 86400,
                },
                aliases=["MiniMax Speech", "MiniMax Music", "music-3.0", "music-cover"],
                capability_source="MiniMax Speech T2A and Music Generation APIs",
                notes=[
                    "music-cover uses the one-step audio_url flow and automatic ASR lyric extraction",
                    "provider-returned music URLs expire after 24 hours",
                ],
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

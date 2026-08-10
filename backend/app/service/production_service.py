"""Application service for strict storyboards and production media providers."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO

from app.core.capability_manifest import (
    MANDATORY_PIPELINE_GATES,
    UPSTREAM_CAPABILITIES,
    capability_implementation_report,
)
from app.audio.mix_plan import AudioMixPlanner
from app.core.performance import PerformancePlanner
from app.core.providers.capabilities import ProviderCapabilityRegistry
from app.core.creative_presets import CreativePresetRegistry
from app.core.media_compositor import MEDIA_DIR, public_url
from app.core.providers.elevenlabs import DialogueLine, ElevenLabsClient
from app.core.providers.minimax_h3 import H3TaskResult, MiniMaxH3Client
from app.core.skill_registry import SkillRegistry
from app.core.sd25_compiler import Sd25PromptCompiler
from app.core.shotcraft_catalog import ShotcraftCatalogLoader, ShotcraftSelectionRequest
from app.core.storyboard_quality import build_nine_grid_prompt, validate_storyboard_continuity
from app.core.video_quality import VideoQualityMeasurements, evaluate_video_quality
from app.schema.production import (
    DialogueRequest,
    CreativePresetCompileRequest,
    DubbingRequest,
    H3VideoRequest,
    MusicRequest,
    NineGridStoryboard,
    SoundEffectRequest,
    Sd25CompileRequest,
    TTSRequest,
)
from app.schema.advanced import AudioMixRequest, PerformancePlanRequest


class ProductionService:
    def __init__(self) -> None:
        backend_root = Path(__file__).resolve().parents[2]
        configured_sd25 = os.getenv("SD25_PE_SKILL_PATH", "").strip()
        sd25_path = Path(configured_sd25).expanduser() if configured_sd25 else Path.home() / "Desktop" / "sd25-pe"
        self.skill_registry = SkillRegistry([backend_root / "skills", sd25_path])
        self.preset_registry = CreativePresetRegistry()
        self.sd25_compiler = Sd25PromptCompiler()
        self.performance_planner = PerformancePlanner()
        self.audio_mix_planner = AudioMixPlanner()
        self.provider_registry = ProviderCapabilityRegistry()
        self.shotcraft_catalog = ShotcraftCatalogLoader()

    @staticmethod
    def _save_audio(data: bytes, prefix: str, extension: str = "mp3") -> dict[str, str]:
        if not data:
            raise RuntimeError("provider returned empty audio")
        os.makedirs(MEDIA_DIR, exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()[:20]
        filename = f"{prefix}_{digest}.{extension}"
        path = Path(MEDIA_DIR) / filename
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
        return {"url": public_url(filename), "path": str(path)}

    def capabilities(self) -> dict:
        skills = self.skill_registry.list()
        return {
            "sources": UPSTREAM_CAPABILITIES,
            "gates": MANDATORY_PIPELINE_GATES,
            "skills": [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "kind": skill.kind,
                    "path": str(skill.path),
                }
                for skill in skills
            ],
            "providers": {
                "minimax_h3": bool(os.getenv("MINIMAX_API_KEY")),
                "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
            },
            "creative_presets": [preset.model_dump() for preset in self.preset_registry.list()],
        }

    def implementation_report(self) -> list[dict]:
        return capability_implementation_report()

    def provider_capabilities(self) -> dict:
        return {
            provider: capabilities.model_dump()
            for provider, capabilities in self.provider_registry.list().items()
        }

    def build_performance_plan(self, request: PerformancePlanRequest) -> dict:
        return self.performance_planner.build(request).model_dump()

    def build_audio_mix_plan(self, request: AudioMixRequest) -> dict:
        return self.audio_mix_planner.plan(request).model_dump()

    def list_presets(self) -> list[dict]:
        return [preset.model_dump() for preset in self.preset_registry.list()]

    def compile_preset(self, preset_id: str, request: CreativePresetCompileRequest) -> dict:
        return self.preset_registry.compile(
            preset_id,
            request.content,
            asset_context=request.asset_context,
            language=request.language,
        ).model_dump()

    def compile_sd25(self, request: Sd25CompileRequest) -> dict:
        # The local skill contract stops at prompt compilation; provider submission
        # remains a separate, explicit API operation.
        self.skill_registry.get("sd25-pe")
        return self.sd25_compiler.compile(request).model_dump()

    def list_shotcraft_catalog(self) -> dict:
        return self.shotcraft_catalog.catalog.model_dump(mode="json")

    def compile_shotcraft(self, request: ShotcraftSelectionRequest) -> dict:
        return self.shotcraft_catalog.compile_selection(request).model_dump(mode="json")

    @staticmethod
    def decide_video_quality(measurements: VideoQualityMeasurements) -> dict:
        return evaluate_video_quality(measurements).model_dump()

    @staticmethod
    def compile_storyboard(board: NineGridStoryboard) -> dict:
        report = validate_storyboard_continuity(board.panels)
        return {"prompt": build_nine_grid_prompt(board), "quality": report.model_dump()}

    @staticmethod
    def create_h3_video(request: H3VideoRequest, wait: bool = False) -> H3TaskResult:
        client = MiniMaxH3Client()
        try:
            result = client.create_video(request)
            if wait and result.task_id and not result.video_url:
                return client.wait_for_video(result.task_id)
            return result
        finally:
            client.close()

    @staticmethod
    def get_h3_task(task_id: str) -> H3TaskResult:
        client = MiniMaxH3Client()
        try:
            return client.get_task(task_id)
        finally:
            client.close()

    def tts(self, request: TTSRequest) -> dict:
        client = ElevenLabsClient()
        try:
            audio = client.text_to_speech(
                request.text, request.voice_id, emotion=request.emotion,
                speed=request.speed, model_id=request.model_id,
            )
            return self._save_audio(audio, "eleven_tts")
        finally:
            client.close()

    def tts_with_timestamps(self, request: TTSRequest) -> dict:
        client = ElevenLabsClient()
        try:
            timed = client.text_to_speech_with_timestamps(
                request.text, request.voice_id, emotion=request.emotion,
                speed=request.speed, model_id=request.model_id,
            )
            audio = timed.pop("audio")
            return {**self._save_audio(audio, "eleven_tts_timed"), **timed}
        finally:
            client.close()

    def dialogue(self, request: DialogueRequest) -> dict:
        lines = [DialogueLine.model_validate(line.model_dump()) for line in request.lines]
        client = ElevenLabsClient()
        try:
            return self._save_audio(client.create_dialogue(lines), "eleven_dialogue")
        finally:
            client.close()

    def dialogue_with_timestamps(self, request: DialogueRequest) -> dict:
        lines = [DialogueLine.model_validate(line.model_dump()) for line in request.lines]
        client = ElevenLabsClient()
        try:
            timed = client.create_dialogue_with_timestamps(lines)
            audio = timed.pop("audio")
            return {**self._save_audio(audio, "eleven_dialogue_timed"), **timed}
        finally:
            client.close()

    def sound_effect(self, request: SoundEffectRequest) -> dict:
        client = ElevenLabsClient()
        try:
            audio = client.sound_effect(
                request.prompt, duration_seconds=request.duration_seconds,
                prompt_influence=request.prompt_influence,
            )
            return self._save_audio(audio, "eleven_sfx")
        finally:
            client.close()

    def music(self, request: MusicRequest) -> dict:
        client = ElevenLabsClient()
        try:
            audio = client.compose_music(
                request.prompt, duration_seconds=request.duration_seconds,
                instrumental=request.instrumental, model_id=request.model_id,
            )
            return self._save_audio(audio, "eleven_music")
        finally:
            client.close()

    def video_to_music(
        self,
        videos: list[tuple[str, BinaryIO]],
        *,
        description: str,
        tags: list[str],
        model_id: str,
        sign_with_c2pa: bool,
    ) -> dict:
        client = ElevenLabsClient()
        try:
            audio = client.video_to_music(
                videos, description=description, tags=tags, model_id=model_id,
                sign_with_c2pa=sign_with_c2pa,
            )
            return self._save_audio(audio, "eleven_video_music")
        finally:
            client.close()

    @staticmethod
    def transcribe(
        file: BinaryIO,
        *,
        filename: str,
        language_code: str | None,
        diarize: bool,
        num_speakers: int | None,
    ) -> dict:
        client = ElevenLabsClient()
        try:
            return client.transcribe(
                file, filename=filename, language_code=language_code,
                diarize=diarize, num_speakers=num_speakers,
            )
        finally:
            client.close()

    @staticmethod
    def dub(request: DubbingRequest) -> dict:
        client = ElevenLabsClient()
        try:
            return client.create_dub(
                source_url=str(request.source_url), target_language=request.target_language,
                source_language=request.source_language, num_speakers=request.num_speakers,
            )
        finally:
            client.close()

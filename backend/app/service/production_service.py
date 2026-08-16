"""Application service for strict storyboards and production media providers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from pathlib import Path
from typing import BinaryIO

from app.core.capability_manifest import (
    MANDATORY_PIPELINE_GATES,
    UPSTREAM_CAPABILITIES,
    capability_implementation_report,
)
from app.core.agent_council import AgentCouncilCompiler
from app.audio.mix_plan import AudioMixPlanner
from app.core.performance import PerformancePlanner
from app.core.providers.capabilities import ProviderCapabilityRegistry
from app.core.creative_presets import CreativePresetRegistry
from app.core.media_compositor import MEDIA_DIR, public_url
from app.core.providers.elevenlabs import DialogueLine, ElevenLabsClient
from app.core.providers.elevenlabs_capabilities import elevenlabs_capability_catalog
from app.core.providers.minimax_audio import MiniMaxAudioArtifact, MiniMaxAudioClient
from app.core.providers.minimax_h3 import H3TaskResult, MiniMaxH3Client
from app.core.skill_registry import SkillRegistry
from app.core.sd25_compiler import Sd25PromptCompiler
from app.core.script_prompt_pipeline import ScriptPromptPipeline
from app.core.shotcraft_catalog import ShotcraftCatalogLoader, ShotcraftSelectionRequest
from app.core.storyboard_quality import build_nine_grid_prompt, validate_storyboard_continuity
from app.core.storyboard_director import StoryboardDirectorCompiler
from app.core.video_quality import VideoQualityMeasurements, evaluate_video_quality
from app.core.video_references import VideoRouteRequest, decide_video_generation
from app.core.preproduction import PreproductionPlanner
from app.core.production_evidence import ProductionEvidenceService
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
from app.schema.elevenlabs import (
    PronunciationDictionaryCreateRequest,
    SpeechEngineCreateRequest,
    VoiceCreateRequest,
    VoiceDesignRequest,
)
from app.schema.minimax_audio import (
    MiniMaxMusicCoverRequest,
    MiniMaxMusicRequest,
    MiniMaxTTSRequest,
)
from app.schema.advanced import AudioMixRequest, PerformancePlanRequest
from app.schema.evidence import FailureEvidence, GenerationOutcome, ProductionReadinessRequest
from app.schema.intelligence import EpisodeIntakeRequest, NovelAnalyzeRequest, VoiceDirectionRequest
from app.schema.script_prompts import ScriptPromptCompileRequest
from app.schema.storyboard_director import StoryboardDirectorRequest
from app.schema.agent_council import CouncilCompileRequest, CouncilReleaseEvidence


class ProductionService:
    def __init__(self) -> None:
        backend_root = Path(__file__).resolve().parents[2]
        configured_sd25 = os.getenv("SD25_PE_SKILL_PATH", "").strip()
        sd25_paths = (
            [Path(configured_sd25).expanduser()]
            if configured_sd25
            else [Path.home() / ".agents" / "skills" / "sd25-pe", Path.home() / "Desktop" / "sd25-pe"]
        )
        self.skill_registry = SkillRegistry([backend_root / "skills", *sd25_paths])
        self.preset_registry = CreativePresetRegistry()
        self.sd25_compiler = Sd25PromptCompiler()
        self.script_prompt_pipeline = ScriptPromptPipeline()
        self.storyboard_director = StoryboardDirectorCompiler()
        self.performance_planner = PerformancePlanner()
        self.audio_mix_planner = AudioMixPlanner()
        self.provider_registry = ProviderCapabilityRegistry()
        self.shotcraft_catalog = ShotcraftCatalogLoader()
        self.preproduction_planner = PreproductionPlanner()
        self.evidence_service = ProductionEvidenceService()
        self.agent_council = AgentCouncilCompiler()

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
                "minimax_audio": bool(os.getenv("MINIMAX_API_KEY")),
                "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
            },
            "local_capabilities": [
                {
                    "id": "universal-storyboard-director",
                    "entrypoint": "/api/production/storyboard-director/compile",
                    "features": [
                        "natural narrative beat planning",
                        "continuous start/keyframe/end timeline",
                        "verbatim timed dialogue",
                        "single-frame prompts",
                        "adjacent-keyframe video prompts",
                        "3x3 pagination with blank unused cells",
                        "character/scene/prop/light/axis/color continuity locks",
                        "continuity self-check",
                    ],
                },
                {
                    "id": "eight-agent-production-council",
                    "entrypoint": "/api/production/agent-council/compile",
                    "features": [
                        "all 18 supplied Markdown specifications mapped to executable policies",
                        "canonical eight-agent role and handoff contracts",
                        "strict five-view and exact 3x3 nine-grid gates",
                        "first-last/multi-image/multimodal video routing gate",
                        "dialogue/voice/SFX/BGM/mix and ElevenLabs job planning",
                        "S/A/B/C fail-closed release decision",
                    ],
                },
            ],
            "creative_presets": [preset.model_dump() for preset in self.preset_registry.list()],
        }

    def implementation_report(self) -> list[dict]:
        return capability_implementation_report()

    def agent_council_catalog(self) -> dict:
        return self.agent_council.catalog()

    def compile_agent_council(self, request: CouncilCompileRequest) -> dict:
        return self.agent_council.compile(request).model_dump(mode="json")

    def evaluate_agent_council_release(self, request: CouncilReleaseEvidence) -> dict:
        return self.agent_council.evaluate_release(request).model_dump(mode="json")

    def provider_capabilities(self) -> dict:
        return {
            provider: capabilities.model_dump()
            for provider, capabilities in self.provider_registry.list().items()
        }

    @staticmethod
    def elevenlabs_capabilities() -> dict:
        items = elevenlabs_capability_catalog()
        return {"provider": "elevenlabs", "items": items, "total": len(items)}

    @staticmethod
    def decide_video_generation(request: VideoRouteRequest) -> dict:
        return decide_video_generation(request).model_dump(mode="json")

    def build_performance_plan(self, request: PerformancePlanRequest) -> dict:
        return self.performance_planner.build(request).model_dump()

    def build_audio_mix_plan(self, request: AudioMixRequest) -> dict:
        return self.audio_mix_planner.plan(request).model_dump()

    def analyze_novel(self, request: NovelAnalyzeRequest) -> dict:
        return self.preproduction_planner.analyze_novel(request).model_dump()

    def index_episodes(self, request: EpisodeIntakeRequest) -> dict:
        return self.preproduction_planner.index_episodes(request).model_dump()

    def plan_voice(self, request: VoiceDirectionRequest) -> dict:
        return self.preproduction_planner.plan_voice(request).model_dump()

    def evaluate_readiness(self, request: ProductionReadinessRequest) -> dict:
        return self.evidence_service.evaluate_readiness(request).model_dump()

    def normalize_failure(self, request: FailureEvidence) -> dict:
        return self.evidence_service.normalize_failure(request).model_dump()

    def summarize_outcomes(self, outcomes: list[GenerationOutcome]) -> dict:
        return self.evidence_service.summarize(outcomes).model_dump()

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
        # remains a separate, explicit API operation. The deterministic compiler
        # is portable; local skill discovery only enriches model-assisted paths.
        return self.sd25_compiler.compile(request).model_dump()

    def compile_script_prompts(self, request: ScriptPromptCompileRequest) -> dict:
        # Both template sources are compilation references only. This entrypoint
        # never executes ZIP scripts and never submits a provider generation job.
        return self.script_prompt_pipeline.compile(request).model_dump(mode="json")

    def compile_storyboard_director(self, request: StoryboardDirectorRequest) -> dict:
        # Template text is a schema reference only; this endpoint compiles a
        # deterministic plan and never submits provider generation requests.
        return self.storyboard_director.compile(request).model_dump(mode="json")

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

    @staticmethod
    def _minimax_remote_audio(artifact: MiniMaxAudioArtifact) -> dict:
        if not artifact.audio_url:
            raise RuntimeError("MiniMax did not return an audio URL")
        return {
            "url": artifact.audio_url,
            "provider": "minimax",
            "model_id": artifact.model_id,
            "kind": artifact.kind,
            "trace_id": artifact.trace_id,
            "extra_info": artifact.extra_info,
            "expires_in_seconds": 86400,
        }

    def minimax_tts(self, request: MiniMaxTTSRequest) -> dict:
        client = MiniMaxAudioClient()
        try:
            artifact = client.text_to_speech(request)
            if artifact.audio is None:
                raise RuntimeError("MiniMax did not return synthesized speech")
            saved = self._save_audio(
                artifact.audio,
                "minimax_tts",
                extension=request.audio_format,
            )
            return {
                **saved,
                "provider": "minimax",
                "model_id": artifact.model_id,
                "kind": artifact.kind,
                "trace_id": artifact.trace_id,
                "extra_info": artifact.extra_info,
            }
        finally:
            client.close()

    def minimax_music(self, request: MiniMaxMusicRequest) -> dict:
        client = MiniMaxAudioClient()
        try:
            return self._minimax_remote_audio(client.generate_music(request))
        finally:
            client.close()

    def minimax_music_cover(self, request: MiniMaxMusicCoverRequest) -> dict:
        client = MiniMaxAudioClient()
        try:
            return self._minimax_remote_audio(client.cover_music(request))
        finally:
            client.close()

    def tts(self, request: TTSRequest) -> dict:
        client = ElevenLabsClient()
        try:
            audio = client.text_to_speech(
                request.text, request.voice_id, emotion=request.emotion,
                speed=request.speed, model_id=request.model_id,
                pronunciation_dictionary_locators=[
                    item.model_dump() for item in request.pronunciation_dictionary_locators
                ],
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
                pronunciation_dictionary_locators=[
                    item.model_dump() for item in request.pronunciation_dictionary_locators
                ],
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

    @staticmethod
    def list_voices(
        *, page_size: int, next_page_token: str | None, search: str | None,
        voice_type: str | None,
    ) -> dict:
        client = ElevenLabsClient()
        try:
            return client.list_voices(
                page_size=page_size,
                next_page_token=next_page_token,
                search=search,
                voice_type=voice_type,
            )
        finally:
            client.close()

    @staticmethod
    def list_speech_engines(
        *, page_size: int, cursor: str | None, search: str | None,
    ) -> dict:
        client = ElevenLabsClient()
        try:
            return client.list_speech_engines(
                page_size=page_size, cursor=cursor, search=search
            )
        finally:
            client.close()

    @staticmethod
    def create_speech_engine(request: SpeechEngineCreateRequest) -> dict:
        client = ElevenLabsClient()
        try:
            return client.create_speech_engine(
                name=request.name,
                ws_url=request.ws_url,
                voice_id=request.voice_id,
                model_id=request.model_id,
                language=request.language,
                tags=request.tags,
            )
        finally:
            client.close()

    def voice_change(
        self,
        audio: BinaryIO,
        *,
        filename: str,
        voice_id: str,
        model_id: str,
        remove_background_noise: bool,
    ) -> dict:
        client = ElevenLabsClient()
        try:
            result = client.voice_change(
                audio,
                filename=filename,
                voice_id=voice_id,
                model_id=model_id,
                remove_background_noise=remove_background_noise,
            )
            return self._save_audio(result, "eleven_voice_change")
        finally:
            client.close()

    def design_voice(self, request: VoiceDesignRequest) -> dict:
        client = ElevenLabsClient()
        try:
            result = client.design_voice(
                voice_description=request.voice_description,
                text=request.text,
                auto_generate_text=request.auto_generate_text,
                model_id=request.model_id,
                seed=request.seed,
                guidance_scale=request.guidance_scale,
                should_enhance=request.should_enhance,
            )
        finally:
            client.close()

        previews = result.get("previews")
        if not isinstance(previews, list) or not previews:
            raise RuntimeError("ElevenLabs voice design returned no previews")
        normalized = []
        for index, preview in enumerate(previews[:10], start=1):
            if not isinstance(preview, dict):
                raise RuntimeError("ElevenLabs voice design returned an invalid preview")
            encoded = preview.get("audio_base_64")
            if not isinstance(encoded, str):
                raise RuntimeError("ElevenLabs voice design preview omitted audio")
            try:
                audio = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError("ElevenLabs voice design returned invalid audio") from exc
            if not audio or len(audio) > 50 * 1024 * 1024:
                raise RuntimeError("ElevenLabs voice design preview exceeded the safe audio limit")
            safe_preview = {key: value for key, value in preview.items() if key != "audio_base_64"}
            safe_preview.update(self._save_audio(audio, f"eleven_voice_preview_{index}"))
            normalized.append(safe_preview)
        return {"text": result.get("text", ""), "previews": normalized}

    @staticmethod
    def create_designed_voice(request: VoiceCreateRequest) -> dict:
        client = ElevenLabsClient()
        try:
            return client.create_designed_voice(
                voice_name=request.voice_name,
                voice_description=request.voice_description,
                generated_voice_id=request.generated_voice_id,
                labels=request.labels,
            )
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

    def isolate_audio(self, audio: BinaryIO, *, filename: str, file_format: str) -> dict:
        client = ElevenLabsClient()
        try:
            isolated = client.isolate_audio(
                audio, filename=filename, file_format=file_format
            )
            return self._save_audio(isolated, "eleven_isolated")
        finally:
            client.close()

    @staticmethod
    def force_align(audio: BinaryIO, *, filename: str, text: str) -> dict:
        client = ElevenLabsClient()
        try:
            return client.force_align(audio, filename=filename, text=text)
        finally:
            client.close()

    @staticmethod
    def list_pronunciation_dictionaries(
        *, page_size: int, cursor: str | None, include_archived: bool,
    ) -> dict:
        client = ElevenLabsClient()
        try:
            return client.list_pronunciation_dictionaries(
                page_size=page_size,
                cursor=cursor,
                include_archived=include_archived,
            )
        finally:
            client.close()

    @staticmethod
    def create_pronunciation_dictionary(
        request: PronunciationDictionaryCreateRequest,
    ) -> dict:
        client = ElevenLabsClient()
        try:
            return client.create_pronunciation_dictionary(
                name=request.name,
                description=request.description,
                workspace_access=request.workspace_access,
                rules=[rule.model_dump(exclude_none=True) for rule in request.rules],
            )
        finally:
            client.close()

    @staticmethod
    def create_audio_native(
        *,
        name: str,
        file: BinaryIO | None,
        filename: str | None,
        author: str | None,
        title: str | None,
        voice_id: str | None,
        model_id: str | None,
        auto_convert: bool,
        pronunciation_dictionary_locators: list[dict[str, str]],
    ) -> dict:
        client = ElevenLabsClient()
        try:
            return client.create_audio_native(
                name=name,
                file=file,
                filename=filename,
                author=author,
                title=title,
                voice_id=voice_id,
                model_id=model_id,
                auto_convert=auto_convert,
                pronunciation_dictionary_locators=pronunciation_dictionary_locators,
            )
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

"""Production endpoints for strict storyboards, H3 and ElevenLabs."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.api.auth_api import get_current_user
from app.schema.production import (
    CreativePresetCompileRequest,
    DialogueRequest,
    DubbingRequest,
    H3VideoRequest,
    MusicRequest,
    NineGridStoryboard,
    SoundEffectRequest,
    Sd25CompileRequest,
    TTSRequest,
)
from app.service.production_service import ProductionService
from app.core.video_quality import VideoQualityMeasurements
from app.schema.advanced import AudioMixRequest, PerformancePlanRequest
from app.schema.evidence import FailureEvidence, GenerationOutcome, ProductionReadinessRequest
from app.schema.intelligence import EpisodeIntakeRequest, NovelAnalyzeRequest, VoiceDirectionRequest
from app.schema.script_prompts import ExportFormat, ScriptPromptCompileRequest
from app.schema.storyboard_director import StoryboardDirectorRequest
from app.core.shotcraft_catalog import ShotcraftCatalogError, ShotcraftSelectionRequest
from app.core.video_references import VideoRouteRequest
from app.schema.agent_council import CouncilCompileRequest, CouncilReleaseEvidence
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
from app.ingest.parsers import SourceIngestError, SourceIngestor


router = APIRouter(
    prefix="/api/production",
    tags=["AI短剧工业化能力"],
    dependencies=[Depends(get_current_user)],
)
service = ProductionService()


def _provider_error(provider: str, exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=f"{provider} 请求不可执行: {exc}")
    return HTTPException(status_code=502, detail=f"{provider} 服务暂不可用")


def _validate_upload(
    file: UploadFile,
    *,
    maximum_bytes: int,
    extensions: tuple[str, ...],
    media_prefixes: tuple[str, ...],
) -> tuple[str, int]:
    filename = file.filename or "upload.bin"
    content_type = (file.content_type or "").lower()
    known_extension = filename.lower().endswith(extensions)
    known_media_type = any(content_type.startswith(prefix) for prefix in media_prefixes)
    if not (known_extension or known_media_type):
        raise ValueError("上传文件类型不受支持")
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size <= 0 or size > maximum_bytes:
        raise ValueError(f"上传文件必须介于 1 字节和 {maximum_bytes // (1024 * 1024)} MB 之间")
    return filename, size


@router.get("/capabilities")
def capabilities():
    return service.capabilities()


@router.get("/capabilities/report")
def capability_report():
    return service.implementation_report()


@router.get("/agent-council/capabilities")
def agent_council_capabilities():
    return service.agent_council_catalog()


@router.post("/agent-council/compile")
def compile_agent_council(request: CouncilCompileRequest):
    try:
        return service.compile_agent_council(request)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agent-council/release-gate")
def evaluate_agent_council_release(request: CouncilReleaseEvidence):
    return service.evaluate_agent_council_release(request)


@router.get("/providers")
def provider_capabilities():
    return service.provider_capabilities()


@router.post("/video/route")
def route_video_generation(request: VideoRouteRequest):
    try:
        return service.decide_video_generation(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/presets")
def creative_presets():
    return service.list_presets()


@router.post("/presets/{preset_id}/compile")
def compile_creative_preset(preset_id: str, request: CreativePresetCompileRequest):
    try:
        return service.compile_preset(preset_id, request)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/quality/video/decision")
def decide_video_quality(measurements: VideoQualityMeasurements):
    return service.decide_video_quality(measurements)


@router.post("/performance/plan")
def build_performance_plan(request: PerformancePlanRequest):
    return service.build_performance_plan(request)


@router.post("/audio/mix/plan")
def build_audio_mix_plan(request: AudioMixRequest):
    return service.build_audio_mix_plan(request)


@router.post("/preproduction/novel-analyze")
def analyze_novel(request: NovelAnalyzeRequest):
    return service.analyze_novel(request)


@router.post("/preproduction/episodes/index")
def index_episodes(request: EpisodeIntakeRequest):
    try:
        return service.index_episodes(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/preproduction/voice/plan")
def plan_voice(request: VoiceDirectionRequest):
    return service.plan_voice(request)


@router.post("/readiness/evaluate")
def evaluate_readiness(request: ProductionReadinessRequest):
    return service.evaluate_readiness(request)


@router.post("/failures/normalize")
def normalize_failure(request: FailureEvidence):
    return service.normalize_failure(request)


@router.post("/analytics/summarize")
def summarize_outcomes(outcomes: list[GenerationOutcome]):
    return service.summarize_outcomes(outcomes)


@router.post("/storyboards/compile")
def compile_storyboard(board: NineGridStoryboard):
    return service.compile_storyboard(board)


@router.post("/sd25/compile")
def compile_sd25(request: Sd25CompileRequest):
    try:
        return service.compile_sd25(request)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/script-prompts/compile")
def compile_script_prompts(request: ScriptPromptCompileRequest):
    try:
        return service.compile_script_prompts(request)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/storyboard-director/compile")
def compile_storyboard_director(request: StoryboardDirectorRequest):
    try:
        return service.compile_storyboard_director(request)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/script-prompts/compile-file")
async def compile_script_prompt_file(
    file: UploadFile = File(...),
    title: str = Query("", max_length=300),
    visual_style: str = Query("写实真人电影质感", min_length=1, max_length=2000),
    prompt_language: str = Query("zh-CN", min_length=1, max_length=40),
    output_language: str = Query("zh-CN", min_length=1, max_length=40),
    video_model: str = Query("Seedance 2.5", min_length=1, max_length=120),
    exports: list[ExportFormat] = Query(default=["json", "markdown", "csv", "html"]),
):
    content = await file.read(SourceIngestor.MAX_BYTES + 1)
    try:
        document = SourceIngestor().ingest(file.filename or "script.txt", content)
        request = ScriptPromptCompileRequest(
            title=(title.strip() or document.filename.rsplit(".", 1)[0] or "Untitled"),
            script_text=document.text,
            source_format=document.format,
            source_sha256=document.sha256,
            visual_style=visual_style,
            prompt_language=prompt_language,
            output_language=output_language,
            video_model=video_model,
            exports=exports,
        )
        return service.compile_script_prompts(request)
    except SourceIngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/shotcraft/catalog")
def shotcraft_catalog():
    return service.list_shotcraft_catalog()


@router.post("/shotcraft/compile")
def compile_shotcraft(request: ShotcraftSelectionRequest):
    try:
        return service.compile_shotcraft(request)
    except ShotcraftCatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/video/minimax-h3")
def create_minimax_h3_video(request: H3VideoRequest, wait: bool = Query(False)):
    try:
        return service.create_h3_video(request, wait=wait)
    except Exception as exc:
        raise _provider_error("MiniMax H3", exc) from exc


@router.get("/video/minimax-h3/{task_id}")
def get_minimax_h3_video(task_id: str):
    try:
        return service.get_h3_task(task_id)
    except Exception as exc:
        raise _provider_error("MiniMax H3", exc) from exc


@router.post("/audio/minimax/tts")
def minimax_tts(request: MiniMaxTTSRequest):
    try:
        return service.minimax_tts(request)
    except Exception as exc:
        raise _provider_error("MiniMax TTS", exc) from exc


@router.post("/audio/minimax/music")
def minimax_music(request: MiniMaxMusicRequest):
    try:
        return service.minimax_music(request)
    except Exception as exc:
        raise _provider_error("MiniMax Music 3.0", exc) from exc


@router.post("/audio/minimax/music-cover")
def minimax_music_cover(request: MiniMaxMusicCoverRequest):
    try:
        return service.minimax_music_cover(request)
    except Exception as exc:
        raise _provider_error("MiniMax Music Cover", exc) from exc


@router.post("/audio/tts")
def elevenlabs_tts(request: TTSRequest):
    try:
        return service.tts(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs TTS", exc) from exc


@router.get("/audio/capabilities")
def elevenlabs_capabilities():
    return service.elevenlabs_capabilities()


@router.get("/audio/voices")
def elevenlabs_voices(
    page_size: int = Query(100, ge=1, le=100),
    next_page_token: str | None = Query(None, max_length=500),
    search: str | None = Query(None, max_length=200),
    voice_type: str | None = Query(None, pattern=r"^(personal|community|default|workspace|non-default|non-community|saved)$"),
):
    try:
        return service.list_voices(
            page_size=page_size,
            next_page_token=next_page_token,
            search=search,
            voice_type=voice_type,
        )
    except Exception as exc:
        raise _provider_error("ElevenLabs Voices", exc) from exc


@router.get("/audio/speech-engines")
def elevenlabs_speech_engines(
    page_size: int = Query(30, ge=1, le=100),
    cursor: str | None = Query(None, max_length=500),
    search: str | None = Query(None, max_length=200),
):
    try:
        return service.list_speech_engines(
            page_size=page_size, cursor=cursor, search=search
        )
    except Exception as exc:
        raise _provider_error("ElevenLabs Speech Engine", exc) from exc


@router.post("/audio/speech-engines")
def elevenlabs_create_speech_engine(request: SpeechEngineCreateRequest):
    try:
        return service.create_speech_engine(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs Speech Engine", exc) from exc


@router.post("/audio/tts-with-timestamps")
def elevenlabs_tts_with_timestamps(request: TTSRequest):
    try:
        return service.tts_with_timestamps(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs TTS timing", exc) from exc


@router.post("/audio/dialogue")
def elevenlabs_dialogue(request: DialogueRequest):
    try:
        return service.dialogue(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs Dialogue", exc) from exc


@router.post("/audio/dialogue-with-timestamps")
def elevenlabs_dialogue_with_timestamps(request: DialogueRequest):
    try:
        return service.dialogue_with_timestamps(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs Dialogue timing", exc) from exc


@router.post("/audio/voice-changer")
def elevenlabs_voice_changer(
    file: UploadFile = File(...),
    voice_id: str = Query(..., min_length=1, max_length=200),
    model_id: str = Query(
        "eleven_multilingual_sts_v2",
        pattern=r"^eleven_(multilingual|english)_sts_v2$",
    ),
    remove_background_noise: bool = Query(False),
):
    try:
        filename, _ = _validate_upload(
            file,
            maximum_bytes=500 * 1024 * 1024,
            extensions=(".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".aac"),
            media_prefixes=("audio/", "video/webm"),
        )
        return service.voice_change(
            file.file,
            filename=filename,
            voice_id=voice_id,
            model_id=model_id,
            remove_background_noise=remove_background_noise,
        )
    except Exception as exc:
        raise _provider_error("ElevenLabs Voice Changer", exc) from exc


@router.post("/audio/voice-design")
def elevenlabs_voice_design(request: VoiceDesignRequest):
    try:
        return service.design_voice(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs Voice Design", exc) from exc


@router.post("/audio/voice-design/voices")
def elevenlabs_create_designed_voice(request: VoiceCreateRequest):
    try:
        return service.create_designed_voice(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs Voice Design", exc) from exc


@router.post("/audio/sound-effect")
def elevenlabs_sound_effect(request: SoundEffectRequest):
    try:
        return service.sound_effect(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs Sound Effects", exc) from exc


@router.post("/audio/music")
def elevenlabs_music(request: MusicRequest):
    try:
        return service.music(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs Music", exc) from exc


@router.post("/audio/video-to-music")
def elevenlabs_video_to_music(
    files: list[UploadFile] = File(...),
    description: str = Query("", max_length=1000),
    tags: list[str] | None = Query(default=None),
    model_id: str = Query("music_v2", pattern=r"^music_v[12]$"),
    sign_with_c2pa: bool = Query(False),
):
    try:
        if not 1 <= len(files) <= 10:
            raise ValueError("video-to-music requires 1 to 10 video files")
        total_size = 0
        videos = []
        for item in files:
            filename = item.filename or "video.mp4"
            known_video_name = filename.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".avi"))
            if not ((item.content_type or "").startswith("video/") or known_video_name):
                raise ValueError("video-to-music only accepts video uploads")
            item.file.seek(0, 2)
            total_size += item.file.tell()
            item.file.seek(0)
            videos.append((filename, item.file))
        if total_size > 200 * 1024 * 1024:
            raise ValueError("video-to-music uploads may total at most 200 MB")
        return service.video_to_music(
            videos, description=description, tags=tags or [], model_id=model_id,
            sign_with_c2pa=sign_with_c2pa,
        )
    except Exception as exc:
        raise _provider_error("ElevenLabs Video To Music", exc) from exc


@router.post("/audio/transcribe")
async def elevenlabs_transcribe(
    file: UploadFile = File(...),
    language_code: str | None = Query(None),
    diarize: bool = Query(True),
    num_speakers: int | None = Query(None, ge=1, le=32),
):
    try:
        maximum = 500 * 1024 * 1024
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size > maximum:
            raise ValueError("audio upload exceeds 500 MB")
        return service.transcribe(
            file.file,
            filename=file.filename or "audio.bin",
            language_code=language_code,
            diarize=diarize,
            num_speakers=num_speakers,
        )
    except Exception as exc:
        raise _provider_error("ElevenLabs Speech-to-Text", exc) from exc


@router.post("/audio/isolation")
def elevenlabs_audio_isolation(
    file: UploadFile = File(...),
    file_format: str = Query("other", pattern=r"^(other|pcm_s16le_16)$"),
):
    try:
        filename, _ = _validate_upload(
            file,
            maximum_bytes=500 * 1024 * 1024,
            extensions=(".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".aac"),
            media_prefixes=("audio/", "video/webm"),
        )
        return service.isolate_audio(
            file.file, filename=filename, file_format=file_format
        )
    except Exception as exc:
        raise _provider_error("ElevenLabs Audio Isolation", exc) from exc


@router.post("/audio/forced-alignment")
def elevenlabs_forced_alignment(
    file: UploadFile = File(...),
    text: str = Form(..., min_length=1, max_length=675000),
):
    try:
        filename, _ = _validate_upload(
            file,
            maximum_bytes=1024 * 1024 * 1024,
            extensions=(".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm", ".aac", ".mp4", ".mov"),
            media_prefixes=("audio/", "video/"),
        )
        return service.force_align(file.file, filename=filename, text=text)
    except Exception as exc:
        raise _provider_error("ElevenLabs Forced Alignment", exc) from exc


@router.get("/audio/pronunciation-dictionaries")
def elevenlabs_pronunciation_dictionaries(
    page_size: int = Query(30, ge=1, le=100),
    cursor: str | None = Query(None, max_length=500),
    include_archived: bool = Query(False),
):
    try:
        return service.list_pronunciation_dictionaries(
            page_size=page_size,
            cursor=cursor,
            include_archived=include_archived,
        )
    except Exception as exc:
        raise _provider_error("ElevenLabs Pronunciation Dictionaries", exc) from exc


@router.post("/audio/pronunciation-dictionaries")
def elevenlabs_create_pronunciation_dictionary(
    request: PronunciationDictionaryCreateRequest,
):
    try:
        return service.create_pronunciation_dictionary(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs Pronunciation Dictionaries", exc) from exc


@router.post("/audio/audio-native")
def elevenlabs_audio_native(
    name: str = Form(..., min_length=1, max_length=160),
    file: UploadFile | None = File(None),
    author: str | None = Form(None, max_length=160),
    title: str | None = Form(None, max_length=300),
    voice_id: str | None = Form(None, max_length=200),
    model_id: str | None = Form(None, max_length=200),
    auto_convert: bool = Form(False),
    pronunciation_dictionary_locators: list[str] | None = Form(None),
):
    try:
        filename: str | None = None
        if file is not None:
            filename, _ = _validate_upload(
                file,
                maximum_bytes=25 * 1024 * 1024,
                extensions=(".txt", ".html", ".htm"),
                media_prefixes=("text/plain", "text/html"),
            )
        locators: list[dict[str, str]] = []
        for encoded in pronunciation_dictionary_locators or []:
            candidate = json.loads(encoded)
            if not isinstance(candidate, dict) or set(candidate) != {
                "pronunciation_dictionary_id", "version_id"
            } or not all(isinstance(value, str) and 1 <= len(value) <= 200 for value in candidate.values()):
                raise ValueError("发音词典 locator 必须包含有效的 dictionary ID 与 version ID")
            locators.append(candidate)
        return service.create_audio_native(
            name=name,
            file=file.file if file is not None else None,
            filename=filename,
            author=author,
            title=title,
            voice_id=voice_id,
            model_id=model_id,
            auto_convert=auto_convert,
            pronunciation_dictionary_locators=locators,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="发音词典 locator 不是有效 JSON") from exc
    except Exception as exc:
        raise _provider_error("ElevenLabs Audio Native", exc) from exc


@router.post("/audio/dub")
def elevenlabs_dub(request: DubbingRequest):
    try:
        return service.dub(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs Dubbing", exc) from exc

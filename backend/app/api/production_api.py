"""Production endpoints for strict storyboards, H3 and ElevenLabs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

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
from app.core.shotcraft_catalog import ShotcraftCatalogError, ShotcraftSelectionRequest


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


@router.get("/capabilities")
def capabilities():
    return service.capabilities()


@router.get("/capabilities/report")
def capability_report():
    return service.implementation_report()


@router.get("/providers")
def provider_capabilities():
    return service.provider_capabilities()


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


@router.post("/storyboards/compile")
def compile_storyboard(board: NineGridStoryboard):
    return service.compile_storyboard(board)


@router.post("/sd25/compile")
def compile_sd25(request: Sd25CompileRequest):
    try:
        return service.compile_sd25(request)
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


@router.post("/audio/tts")
def elevenlabs_tts(request: TTSRequest):
    try:
        return service.tts(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs TTS", exc) from exc


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


@router.post("/audio/dub")
def elevenlabs_dub(request: DubbingRequest):
    try:
        return service.dub(request)
    except Exception as exc:
        raise _provider_error("ElevenLabs Dubbing", exc) from exc

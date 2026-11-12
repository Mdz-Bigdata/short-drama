# -*- coding: utf-8 -*-
"""素材来源与授权记录：成片里用到的东西各记一条「从哪来、能怎么用」，发布前查得到。

来源按项目数据自动写：视频片段是哪个模型出的、配乐是生成的还是配乐库里上传的、字幕用了哪个字体、
每个人的音色是设计的、音色库里的还是视频模型的原声。说不清使用范围的列为「需人工确认」
(:func:`items` 的 ``status == "confirm"``)，人在验收单上记下授权说明(``config["rights_notes"]``)
就不再列出。真人演员的肖像授权在元素库的真人记录里，不在这里重复。措辞在 data/prompt/rights_ledger.json。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.core import prompt_data

_DATA = "rights_ledger"
NOTES_KEY = "rights_notes"


def _says(key: str, **values: Any) -> str:
    return str(prompt_data.value(_DATA, "says")[key]).format(**values)


def _item(key: str, kind: str, detail: str, status: str, notes: Mapping[str, Any]) -> dict[str, Any]:
    note = notes.get(key) if isinstance(notes.get(key), Mapping) else None
    if note and str(note.get("note") or "").strip():
        return {"key": key, "kind": kind, "detail": detail + _says("noted", note=str(note["note"]).strip()), "status": "recorded"}
    return {"key": key, "kind": kind, "detail": detail, "status": status}


def _music(task: Mapping[str, Any], timeline: Mapping[str, Any], notes: Mapping[str, Any]) -> list[dict[str, Any]]:
    from app.core import bgm_library

    bgm = timeline.get("bgm") if isinstance(timeline.get("bgm"), Mapping) else {}
    source = str(bgm.get("source") or "none")
    if source == "generated":
        model = str(((task.get("assets") or {}).get("6") or {}).get("music_model") or "ElevenLabs Music")
        return [_item("music:generated", "music", _says("music_generated", model=model), "recorded", notes)]
    if source == "library":
        track = bgm_library.get_track(str(bgm.get("library_id") or "")) or {}
        name = str(track.get("name") or bgm.get("name") or "")
        if track.get("source") == "generated":
            return [_item(f"music:library:{bgm.get('library_id')}", "music", _says("music_library_generated", name=name), "recorded", notes)]
        return [_item(f"music:library:{bgm.get('library_id')}", "music", _says("music_library_upload", name=name), "confirm", notes)]
    return []


def _font(notes: Mapping[str, Any]) -> list[dict[str, Any]]:
    from app.core import media_compositor

    path = media_compositor._font_path()
    if not path:
        return [_item("font:none", "font", _says("font_none"), "recorded", notes)]
    font = os.path.basename(path)
    licence = next((text for marker, text in prompt_data.value(_DATA, "open_fonts") if marker.lower() in font.lower()), "")
    if licence:
        return [_item(f"font:{font}", "font", _says("font_open", font=font, license=licence), "recorded", notes)]
    return [_item(f"font:{font}", "font", _says("font_system", font=font), "confirm", notes)]


def _voices(task: Mapping[str, Any], timeline: Mapping[str, Any], notes: Mapping[str, Any]) -> list[dict[str, Any]]:
    from app.core import edit_timeline, media_compositor, voice_casting

    clips = [clip for clip in edit_timeline._cut_clips(timeline) if not clip.get("muted")]
    sources = {edit_timeline.audio_source(clip) for clip in clips}
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    rows: list[dict[str, Any]] = []
    if "native" in sources:
        rows.append(_item("voice:native", "voice", _says("voice_native", model=str(config.get("video_model") or "")), "recorded", notes))
    if "tts" in sources:
        provider = media_compositor.effective_audio_model(str(config.get("tts_model") or ""))[0]
        if provider != "elevenlabs":
            rows.append(_item("voice:local", "voice", _says("voice_local"), "confirm", notes))
        else:
            for character in voice_casting.dna_characters(assets):
                name = str(character.get("name") or "")
                if not character.get("voice_id"):
                    continue
                kind = "voice_library" if character.get("voice_source") == "auto" else "voice_designed"
                rows.append(_item(f"voice:{name}", "voice", _says(kind, name=name), "recorded", notes))
    return rows


def _video(task: Mapping[str, Any], timeline: Mapping[str, Any], notes: Mapping[str, Any]) -> list[dict[str, Any]]:
    from app.core import edit_timeline

    count = len(edit_timeline._cut_clips(timeline))
    if not count:
        return []
    model = str((task.get("config") or {}).get("video_model") or "")
    return [_item("video", "video", _says("video", count=count, model=model), "recorded", notes)]


def items(task: Mapping[str, Any], timeline: Mapping[str, Any]) -> list[dict[str, Any]]:
    """成片里每样素材的来源记录：{key, kind, detail, status(recorded / confirm)}。"""
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    notes = config.get(NOTES_KEY) if isinstance(config.get(NOTES_KEY), Mapping) else {}
    return [*_video(task, timeline, notes), *_music(task, timeline, notes), *_voices(task, timeline, notes), *_font(notes)]


def note(config: dict[str, Any], key: str, text: str) -> None:
    """人记下一条授权说明(来源、授权范围、凭证在哪)；空串就是撤回。"""
    notes = config.get(NOTES_KEY) if isinstance(config.get(NOTES_KEY), dict) else {}
    config[NOTES_KEY] = notes
    text = str(text or "").strip()[: prompt_data.number(_DATA, "max_note")]
    if text:
        notes[str(key)[:120]] = {"note": text, "noted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    else:
        notes.pop(str(key), None)


__all__ = ["NOTES_KEY", "items", "note"]

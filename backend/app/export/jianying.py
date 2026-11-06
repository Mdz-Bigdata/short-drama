"""A JianYing (CapCut CN) draft written from the edit timeline, with the media packed beside it.

JianYing opens a draft folder holding ``draft_content.json`` (materials and
tracks, times in microseconds) and ``draft_meta_info.json`` (name, duration,
the material list). Material paths may use the ``##_draftpath_##`` marker for
"inside this draft folder", which is what lets a zipped folder open on another
machine. This writer puts every clip, voice and music file under
``materials/``, lays the video track out exactly as the timeline does (trims,
title card, rejected clips left out), adds the voices on an audio track at the
clip's start, the music on its own track, and one text segment per subtitle.
A J-cut or L-cut moves the picture's cut the way the film render does: the same
plan decides, so the draft and the film agree on which cuts are offset and by how much.

The format is reproduced from the application's own files; this is a best
effort at the fields JianYing reads, not a vendored schema.
"""

from __future__ import annotations

import io
import json
import os
import time
import uuid
import zipfile
from collections.abc import Callable, Mapping
from typing import Any

from app.core import edit_timeline, media_compositor

DRAFT_PATH_MARKER = "##_draftpath_##"
DRAFT_VERSION = 360000
US = 1_000_000

Resolver = Callable[[str], str | None]
Probe = Callable[[str], float | None]


def _us(seconds: float) -> int:
    return int(round(float(seconds) * US))


def _uid() -> str:
    return str(uuid.uuid4()).upper()


def _text_material(material_id: str, text: str) -> dict[str, Any]:
    content = {
        "styles": [{"fill": {"content": {"solid": {"color": [1.0, 1.0, 1.0]}}}, "font": {"id": "", "path": ""}, "range": [0, len(text)], "size": 10.0,
                    "strokes": [{"content": {"solid": {"color": [0.0, 0.0, 0.0]}}, "width": 0.08}]}],
        "text": text,
    }
    return {
        "id": material_id, "type": "text", "content": json.dumps(content, ensure_ascii=False), "text": text,
        "font_size": 10.0, "alignment": 1, "letter_spacing": 0.0, "line_spacing": 0.02, "has_shadow": False,
        "text_color": "#FFFFFF", "background_alpha": 1.0, "background_color": "", "border_width": 0.08, "border_color": "#000000",
        "typesetting": 0, "font_path": "", "font_resource_id": "", "layer_weight": 1,
    }


def _sound_joins(placed: list[dict[str, Any]], probe: Probe | None) -> tuple[list[float], list[float], list[float], list[dict[str, Any]]]:
    """The film's sound-offset plan over the clips that made it into the draft; a voice of unknown length is not offset."""
    voices = [probe(clip["voice"]) if probe and clip["voice"] else None for clip in placed]
    for clip, seconds in zip(placed, voices):
        clip["voice_seconds"] = seconds
    joins = [{key: value for key, value in (clip["clip"].get("sound_in") or {}).items() if key in {"join", "seconds"}} or None for clip in placed[1:]]
    transitions = [clip["clip"].get("transition_in") or {} for clip in placed[1:]]
    heads, tails, leads, report = media_compositor.plan_sound_joins([clip["seconds"] for clip in placed], voices, joins, transitions)
    return heads, tails, leads, [{**entry, "shot_id": placed[entry["index"]]["clip"].get("shot_id")} for entry in report]


def _without_overlaps(segments: list[dict[str, Any]], end: int) -> None:
    """One audio track cannot hold two segments at once: a long line stops where the next starts, and at the end of the draft."""
    for segment, following in zip(segments, [*segments[1:], None]):
        limit = following["target_timerange"]["start"] if following else end
        length = max(0, min(segment["target_timerange"]["duration"], limit - segment["target_timerange"]["start"]))
        segment["target_timerange"]["duration"] = segment["source_timerange"]["duration"] = length


def build_draft(
    timeline: Mapping[str, Any], *, name: str, resolve_local: Resolver, title_card_path: str | None = None, probe: Probe | None = None,
) -> dict[str, Any]:
    """Returns {"draft_content": {...}, "draft_meta_info": {...}, "files": {draft-relative path: local path}, "skipped": [...], "sound_joins": [...]}.

    ``probe`` reads a voice file's length; without it the voices keep their clip's length and no cut is offset.
    """
    plan = edit_timeline.render_plan(timeline)
    clips = [c for c in timeline.get("clips") or [] if isinstance(c, Mapping) and (c.get("review") or {}).get("decision") != "rejected" and c.get("video_url")]
    files: dict[str, str] = {}
    skipped: list[str] = []
    videos: list[dict[str, Any]] = []
    audios: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    video_segments: list[dict[str, Any]] = []
    voice_segments: list[dict[str, Any]] = []
    text_segments: list[dict[str, Any]] = []
    cursor = 0
    width, height = int(timeline.get("width") or 1080), int(timeline.get("height") or 1920)

    title_seconds = float((timeline.get("title") or {}).get("seconds") or 0)
    if title_seconds and title_card_path and os.path.isfile(title_card_path):
        material_id = _uid()
        rel = f"materials/title{os.path.splitext(title_card_path)[1] or '.png'}"
        files[rel] = title_card_path
        videos.append({"id": material_id, "type": "photo", "path": f"{DRAFT_PATH_MARKER}/{rel}", "material_name": os.path.basename(rel),
                       "duration": _us(title_seconds), "width": width, "height": height, "has_audio": False, "crop_ratio": "free", "crop_scale": 1.0})
        video_segments.append({"id": _uid(), "material_id": material_id, "source_timerange": {"start": 0, "duration": _us(title_seconds)},
                               "target_timerange": {"start": cursor, "duration": _us(title_seconds)}, "speed": 1.0, "volume": 1.0, "visible": True, "extra_material_refs": []})
        cursor += _us(title_seconds)
    elif title_seconds:
        text_id = _uid()
        texts.append(_text_material(text_id, str((timeline.get("title") or {}).get("text") or "")))
        text_segments.append({"id": _uid(), "material_id": text_id, "source_timerange": {"start": 0, "duration": _us(title_seconds)},
                              "target_timerange": {"start": cursor, "duration": _us(title_seconds)}, "visible": True, "extra_material_refs": []})
        cursor += _us(title_seconds)

    placed: list[dict[str, Any]] = []
    for clip in clips:
        local = resolve_local(str(clip["video_url"]))
        if not local or not os.path.isfile(local):
            skipped.append(f"镜头 {clip.get('shot_id')}：片段不在本机，未打包")
            continue
        voice = clip.get("voice_path")
        placed.append({
            "clip": clip, "local": local, "seconds": edit_timeline.clip_seconds(clip) or float(clip.get("duration") or 0) or 5.0,
            "voice": str(voice) if voice and not clip.get("muted") and os.path.isfile(str(voice)) else None,
        })
    heads, tails, leads, sound_joins = _sound_joins(placed, probe)

    for index, entry in enumerate(placed):
        clip, local = entry["clip"], entry["local"]
        seconds = entry["seconds"] - heads[index] - tails[index]
        rel = f"materials/shot_{clip.get('shot_id')}{os.path.splitext(local)[1] or '.mp4'}"
        files[rel] = local
        material_id = _uid()
        videos.append({"id": material_id, "type": "video", "path": f"{DRAFT_PATH_MARKER}/{rel}", "material_name": os.path.basename(rel),
                       "duration": _us(float(clip.get("duration") or entry["seconds"])), "width": width, "height": height, "has_audio": True, "crop_ratio": "free", "crop_scale": 1.0})
        segment = {
            "id": _uid(), "material_id": material_id,
            "source_timerange": {"start": _us(float(clip.get("in") or 0) + heads[index]), "duration": _us(seconds)},
            "target_timerange": {"start": cursor, "duration": _us(seconds)},
            "speed": 1.0, "volume": 0.0 if clip.get("muted") else 1.0, "visible": True, "extra_material_refs": [],
        }
        transition = clip.get("transition_in") if index else None
        if isinstance(transition, Mapping) and transition.get("type") not in (None, "hard_cut", "match_cut"):
            segment["transition"] = {"type": str(transition.get("type")), "duration": _us(float(transition.get("duration") or 0.22))}
        video_segments.append(segment)
        voice = entry["voice"]
        if voice:
            rel_voice = f"materials/voice_{clip.get('shot_id')}{os.path.splitext(voice)[1] or '.mp3'}"
            files[rel_voice] = voice
            audio_id = _uid()
            spoken = entry.get("voice_seconds") or seconds
            audios.append({"id": audio_id, "type": "extract_music", "path": f"{DRAFT_PATH_MARKER}/{rel_voice}", "name": os.path.basename(rel_voice), "duration": _us(spoken)})
            voice_segments.append({"id": _uid(), "material_id": audio_id, "source_timerange": {"start": 0, "duration": _us(spoken)},
                                   "target_timerange": {"start": max(0, cursor - _us(leads[index])), "duration": _us(spoken)}, "speed": 1.0, "volume": 1.0, "visible": True, "extra_material_refs": []})
        subtitle = str(clip.get("subtitle") or "").strip()
        if subtitle:
            text_id = _uid()
            texts.append(_text_material(text_id, subtitle))
            text_segments.append({"id": _uid(), "material_id": text_id, "source_timerange": {"start": 0, "duration": _us(seconds)},
                                  "target_timerange": {"start": cursor, "duration": _us(seconds)}, "visible": True, "extra_material_refs": []})
        cursor += _us(seconds)

    _without_overlaps(voice_segments, cursor)
    tracks: list[dict[str, Any]] = [{"id": _uid(), "type": "video", "attribute": 0, "flag": 0, "segments": video_segments}]
    if voice_segments:
        tracks.append({"id": _uid(), "type": "audio", "attribute": 0, "flag": 0, "segments": voice_segments})
    bgm_path = plan.get("bgm_path")
    if bgm_path and os.path.isfile(str(bgm_path)) and cursor > 0:
        rel_bgm = f"materials/bgm{os.path.splitext(str(bgm_path))[1] or '.mp3'}"
        files[rel_bgm] = str(bgm_path)
        bgm_id = _uid()
        audios.append({"id": bgm_id, "type": "extract_music", "path": f"{DRAFT_PATH_MARKER}/{rel_bgm}", "name": os.path.basename(rel_bgm), "duration": cursor})
        tracks.append({"id": _uid(), "type": "audio", "attribute": 0, "flag": 0, "segments": [{
            "id": _uid(), "material_id": bgm_id, "source_timerange": {"start": 0, "duration": cursor}, "target_timerange": {"start": 0, "duration": cursor},
            "speed": 1.0, "volume": float(plan.get("bgm_volume") or 0.16), "visible": True, "extra_material_refs": [],
        }]})
    if text_segments:
        tracks.append({"id": _uid(), "type": "text", "attribute": 0, "flag": 0, "segments": text_segments})

    draft_id = _uid()
    now_us = int(time.time() * US)
    content = {
        "canvas_config": {"height": height, "width": width, "ratio": "original"},
        "color_space": 0,
        "config": {"adjust_max_index": 1, "audio_track_max_index": len([t for t in tracks if t["type"] == "audio"]) + 1,
                   "maintrack_adsorb": True, "material_save_mode": 0, "sticker_max_index": 1, "subtitle_sync": True, "video_mute": False},
        "create_time": now_us // US, "duration": cursor, "fps": float(timeline.get("fps") or 30),
        "id": draft_id, "name": name,
        "materials": {"videos": videos, "audios": audios, "texts": texts, "speeds": [], "canvases": [], "sound_channel_mappings": [],
                      "transitions": [], "effects": [], "stickers": [], "beats": [], "placeholders": []},
        "tracks": tracks,
        "version": DRAFT_VERSION, "new_version": "110.0.0", "platform": {"app_source": "short-drama", "os": "mac"},
        "update_time": now_us // US,
    }
    meta = {
        "draft_id": draft_id, "draft_name": name, "draft_fold_path": "", "draft_root_path": "", "draft_cover": "",
        "draft_removable_storage_device": "", "draft_cloud_last_action_download": False, "draft_cloud_purchase_info": "",
        "tm_draft_create": now_us, "tm_draft_modified": now_us, "tm_duration": cursor,
        "draft_materials": [{"type": 0, "value": [
            {"id": m["id"], "file_Path": m["path"], "metetype": "video" if m["type"] == "video" else "photo", "duration": m["duration"], "width": width, "height": height, "roughcut_time_range": {"start": 0, "duration": m["duration"]}}
            for m in videos
        ] + [
            {"id": a["id"], "file_Path": a["path"], "metetype": "music", "duration": a["duration"], "width": 0, "height": 0, "roughcut_time_range": {"start": 0, "duration": a["duration"]}}
            for a in audios
        ]}],
    }
    return {"draft_content": content, "draft_meta_info": meta, "files": files, "skipped": skipped, "sound_joins": sound_joins, "duration_seconds": round(cursor / US, 2)}


def pack(draft: Mapping[str, Any], *, folder_name: str) -> bytes:
    """The draft folder as a zip: drop it into JianYing's draft directory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{folder_name}/draft_content.json", json.dumps(draft["draft_content"], ensure_ascii=False, indent=2))
        archive.writestr(f"{folder_name}/draft_meta_info.json", json.dumps(draft["draft_meta_info"], ensure_ascii=False, indent=2))
        archive.writestr(f"{folder_name}/README.txt", "把整个文件夹放进剪映的草稿目录（如 ~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/）后重新打开剪映。\n")
        for rel, local in (draft.get("files") or {}).items():
            archive.write(local, f"{folder_name}/{rel}")
    return buffer.getvalue()


__all__ = ["DRAFT_PATH_MARKER", "DRAFT_VERSION", "build_draft", "pack"]

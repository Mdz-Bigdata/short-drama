# -*- coding: utf-8 -*-
"""The edit timeline: what the final cut is made of, as something a person can change before rendering.

Stage 5 leaves clips, stage 6 leaves voices and a bed of music and ambience.
The timeline lays them out in order — a title card, one clip per shot with its
trim, its subtitle, its voice and the transition into it, a music track with
ducking under dialogue, an ambience track — and remembers what the reviewer
decided about each clip. Stage 7 renders from the timeline, so an edit made here
(a trim, a rejected shot, a different piece of music) is what ends up in the
film, and the same timeline is what a JianYing draft is written from.

Nothing here runs ffmpeg; ``render_plan`` hands the compositor what to do.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.core import episode_cycle
from app.core.spoken_lines import spoken_lines
from app.core import prompt_data


_WORDING_FILE = "edit_timeline"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/edit_timeline.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

TIMELINE_KEY = "7_timeline"
VERSION = 1
FPS = 30
WIDTH, HEIGHT = 1080, 1920
TITLE_SECONDS = 2.6
TRANSITIONS = ("hard_cut", "match_cut", "crossfade", "dip_to_black", "neutral_bridge")
REVIEW_DECISIONS = ("pending", "approved", "rejected")
BGM_SOURCES = ("none", "generated", "library")
SOUND_JOINS = ("j_cut", "l_cut")
#: 这一镜成片里的人声从哪来：片段自己的声音(视频模型的原声)、配音，或者不要。
AUDIO_SOURCES = ("native", "tts", "none")
#: 剪辑合成师的基础设定：转场、对白音轨、嵌入字幕、片名卡与首尾淡入淡出。默认全开。
SETTINGS = ("transitions", "dialogue", "subtitles", "title_card")


class TimelineError(ValueError):
    """The edit names a clip or a value the timeline cannot take."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _subtitle_of(shot: Mapping[str, Any]) -> str:
    """The on-screen line for a shot: only the words spoken in it (see :mod:`app.core.spoken_lines`).

    台词栏里的说话人、语气与音色说明、花括号、舞台说明都不上字幕；没有台词的镜头不出字幕——
    以前会把画面描述的前 24 个字当字幕烧进成片。
    """
    return " ".join(spoken_lines([str(shot.get("dialogue") or "")]))


def _clip_fingerprint(shot: Mapping[str, Any]) -> str:
    raw = json.dumps({"url": shot.get("video_url"), "duration": shot.get("duration"), "contract": shot.get("contract_fingerprint")}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def build(task: Mapping[str, Any], *, transitions: Sequence[Mapping[str, Any]] | None = None, title: str | None = None) -> dict[str, Any]:
    """A fresh timeline from the project's clips and audio; review decisions start pending."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    shots = [s for s in (assets.get("5") or []) if isinstance(s, Mapping) and s.get("video_url")]
    audio = assets.get("6") if isinstance(assets.get("6"), Mapping) else {}
    voices = list(audio.get("shot_voices") or [])
    native = list(audio.get("native_audio_shots") or [])
    all_shots = [s for s in (assets.get("5") or []) if isinstance(s, Mapping)]
    specs = list(transitions or [])
    clips: list[dict[str, Any]] = []
    for position, shot in enumerate(shots):
        index_in_stage = next((i for i, s in enumerate(all_shots) if s is shot), position)
        duration = float(shot.get("duration") or 0) or None
        spec = specs[position - 1] if position >= 1 and position - 1 < len(specs) else None
        clips.append({
            "shot_id": shot.get("shot_id"),
            # 各场镜号都从 1 起：编辑按全剧编号找片段，场号给界面显示。
            "shot_uid": episode_cycle.shot_uid(shot),
            "scene_id": str(shot.get("scene_id") or ""),
            "video_url": shot.get("video_url"),
            "candidates": [u for u in (shot.get("candidates") or [shot.get("video_url")]) if u],
            "duration": duration,
            "in": 0.0,
            "out": None,
            "muted": False,
            "subtitle": _subtitle_of(shot),
            "voice_path": voices[index_in_stage] if index_in_stage < len(voices) else None,
            # 第 6 阶段记了哪几镜用原声就照它；没记的(没跑第 6 阶段、或记录丢了)看片段自己有没有声音。
            "native_audio": bool(native[index_in_stage]) if index_in_stage < len(native) else shot.get("native_audio") is True,
            # 片段里有没有能用的原声：第 5 阶段听过的记在片上，更早的按第 6 阶段的选择算。
            "native_available": (shot.get("native_audio") is not False) if "native_audio" in shot
            else (bool(native[index_in_stage]) if index_in_stage < len(native) else False),
            "transition_in": {"type": str((spec or {}).get("type") or "crossfade"), "duration": float((spec or {}).get("duration") or 0.22)} if position else None,
            "sound_in": {"join": str(spec["sound_join"]), "edited": False} if position and (spec or {}).get("sound_join") else None,
            "review": {"decision": "pending", "note": "", "decided_at": None},
            "fingerprint": _clip_fingerprint(shot),
            # 分镜要的「一帧黑」：第 5 阶段在片子声音里找到的撞击时刻(秒)和盖几帧，合成时盖上(见 blackout)。
            "blackout": dict(shot["blackout"]) if isinstance(shot.get("blackout"), Mapping) else None,
        })
        clips[-1]["audio_source"] = audio_source(clips[-1])
    bgm_path = audio.get("bgm_path")
    return {
        "version": VERSION,
        "fps": FPS, "width": WIDTH, "height": HEIGHT,
        "title": {"text": title or "", "seconds": TITLE_SECONDS if title else 0.0},
        "clips": clips,
        "bgm": {"source": "generated" if bgm_path else "none", "path": bgm_path, "url": audio.get("bgm_url"), "library_id": None, "name": None, "volume": 0.16, "duck": True,
                "start": 0.0},
        "settings": dict.fromkeys(SETTINGS, True),
        "ambience": {"path": audio.get("sfx_path"), "url": audio.get("sfx_url"), "volume": 0.22},
        "voice_track": audio.get("audio_path"),
        "revision": 0,
        "built_at": _now(),
        "updated_at": _now(),
    }


def _touch(timeline: dict[str, Any]) -> None:
    timeline["revision"] = int(timeline.get("revision") or 0) + 1
    timeline["updated_at"] = _now()


def is_current(timeline: Mapping[str, Any] | None, task: Mapping[str, Any]) -> bool:
    """Whether the timeline still describes the clips stage 5 holds now."""
    if not isinstance(timeline, Mapping):
        return False
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    shots = [s for s in (assets.get("5") or []) if isinstance(s, Mapping) and s.get("video_url")]
    wanted = [_clip_fingerprint(s) for s in shots]
    return [str(c.get("fingerprint")) for c in timeline.get("clips") or []] == wanted


def refresh(timeline: Mapping[str, Any], task: Mapping[str, Any], **build_kwargs: Any) -> dict[str, Any]:
    """A rebuilt timeline that keeps the edits of clips whose footage did not change."""
    fresh = build(task, **build_kwargs)
    kept = {str(c.get("fingerprint")): c for c in timeline.get("clips") or [] if isinstance(c, Mapping)}
    for clip in fresh["clips"]:
        old = kept.get(str(clip["fingerprint"]))
        if old:
            for key in ("in", "out", "muted", "subtitle", "transition_in", "review"):
                if key in old:
                    clip[key] = deepcopy(old[key])
            # 人改过的声画错开留着；没改过的跟着新的切点规划走。
            if (old.get("sound_in") or {}).get("edited"):
                clip["sound_in"] = deepcopy(old["sound_in"])
            # 人选过的人声来源也留着(原声要片段里真有声音才留)。
            if old.get("audio_source_edited") and (old.get("audio_source") != "native" or clip.get("native_available")):
                clip["audio_source"], clip["audio_source_edited"] = old.get("audio_source"), True
    for key in ("title", "bgm", "ambience", "settings"):
        if isinstance(timeline.get(key), Mapping):
            fresh[key] = deepcopy(dict(timeline[key]))
    fresh["revision"] = int(timeline.get("revision") or 0) + 1
    return fresh


def with_new_sound(timeline: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    """The timeline after stage 6 made the sound again: voices, music and ambience come from the new stage 6,
    trims, subtitles, reviews and the music the editor picked from the library stay. Not an edit: the revision stays.
    """
    fresh = build(task)
    new = deepcopy(dict(timeline))
    made = {str(c["fingerprint"]): c for c in fresh["clips"]}
    for clip in new.get("clips") or []:
        source = made.get(str(clip.get("fingerprint")))
        if not isinstance(clip, dict) or source is None:
            continue
        for key in ("voice_path", "native_audio", "native_available"):
            clip[key] = source[key]
        kept = clip.get("audio_source_edited") and (clip.get("audio_source") != "native" or clip.get("native_available"))
        if not kept:
            clip["audio_source"], clip["audio_source_edited"] = source["audio_source"], False
    bgm = dict(new.get("bgm") or {})
    if bgm.get("source", "none") in {"none", "generated"}:
        # 库里选的配乐是人挑的，留着；阶段 6 生成的(或原来没有的)换成这一次的。
        keep = {key: bgm[key] for key in ("volume", "duck", "start") if key in bgm}
        new["bgm"] = {**fresh["bgm"], **keep}
    new["ambience"] = fresh["ambience"]
    new["voice_track"] = fresh["voice_track"]
    return new


def with_shot_uids(timeline: dict[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    """A timeline saved before clips carried ``shot_uid`` gets it from the clips it still matches, place by place.

    Only for a timeline that ``is_current``; one that already has the ids comes back as it is.
    """
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    shots = [s for s in (assets.get("5") or []) if isinstance(s, Mapping) and s.get("video_url")]
    new: dict[str, Any] | None = None
    for index, (clip, shot) in enumerate(zip(timeline.get("clips") or [], shots)):
        uid = episode_cycle.shot_uid(shot)
        if isinstance(clip, Mapping) and not clip.get("shot_uid") and uid:
            new = new or deepcopy(dict(timeline))
            new["clips"][index]["shot_uid"] = uid
            new["clips"][index].setdefault("scene_id", str(shot.get("scene_id") or ""))
    return new or timeline


def _clip(timeline: dict[str, Any], shot_id: Any, shot_uid: Any = None) -> dict[str, Any]:
    """The clip an edit names: by ``shot_uid`` when given, since ``shot_id`` repeats in every scene."""
    clips = [clip for clip in timeline.get("clips") or [] if isinstance(clip, dict)]
    if shot_uid is not None:
        for clip in clips:
            if str(clip.get("shot_uid")) == str(shot_uid):
                return clip
        # 旧时间线上的片段没有全剧编号，只能按镜号找。
        clips = [clip for clip in clips if not clip.get("shot_uid")]
    for clip in clips:
        if str(clip.get("shot_id")) == str(shot_id):
            return clip
    raise TimelineError(_text_of("_clip.text").format(shot_id if shot_id is not None else shot_uid))


# ---------------------------------------------------------------------------- edits


def trim(timeline: Mapping[str, Any], shot_id: int | None, *, start: float, end: float | None, shot_uid: int | None = None) -> dict[str, Any]:
    new = deepcopy(dict(timeline))
    clip = _clip(new, shot_id, shot_uid)
    duration = clip.get("duration")
    start = max(0.0, float(start))
    if end is not None:
        end = float(end)
        if end <= start + 0.5:
            raise TimelineError(_text_of("trim.text"))
        if duration and end > float(duration) + 0.01:
            raise TimelineError(_text_of("trim.text.2").format(duration))
    if duration and start >= float(duration):
        raise TimelineError(_text_of("trim.text.3"))
    clip["in"], clip["out"] = round(start, 3), (round(end, 3) if end is not None else None)
    _touch(new)
    return new


def set_transition(timeline: Mapping[str, Any], shot_id: int | None, *, kind: str, duration: float = 0.22, shot_uid: int | None = None) -> dict[str, Any]:
    if kind not in TRANSITIONS:
        raise TimelineError(_text_of("set_transition.text").format(kind, ', '.join(TRANSITIONS)))
    new = deepcopy(dict(timeline))
    clip = _clip(new, shot_id, shot_uid)
    if new["clips"] and new["clips"][0] is clip:
        raise TimelineError(_text_of("set_transition.text.2"))
    clip["transition_in"] = {"type": kind, "duration": max(0.04, min(float(duration), 1.0))}
    _touch(new)
    return new


def set_sound_join(timeline: Mapping[str, Any], shot_id: int | None, *, join: str, seconds: float | None = None, shot_uid: int | None = None) -> dict[str, Any]:
    """这一刀声音和画面错不错开：j_cut 下一镜的声音先到，l_cut 上一镜的声音留下，空串是同切。"""
    if join not in {"", *SOUND_JOINS}:
        raise TimelineError(_text_of("set_sound_join.text").format(join, ', '.join(SOUND_JOINS)))
    new = deepcopy(dict(timeline))
    clip = _clip(new, shot_id, shot_uid)
    if new["clips"] and new["clips"][0] is clip:
        raise TimelineError(_text_of("set_sound_join.text.2"))
    clip["sound_in"] = {"join": join, "edited": True}
    if join and seconds is not None:
        clip["sound_in"]["seconds"] = max(0.1, min(float(seconds), 1.5))
    _touch(new)
    return new


def record_sound_results(timeline: Mapping[str, Any], shot_ids: Sequence[Any], report: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """合成时每一刀错开了没有，记回时间线给剪辑看。不算一次编辑，版本号不变。"""
    new = deepcopy(dict(timeline))
    for clip in new.get("clips") or []:
        if isinstance(clip.get("sound_in"), dict):
            clip["sound_in"].pop("result", None)
    # 报告按成片里的第几段说话；镜号各场重复，所以按位置取片段，镜号只用来核对。
    cut = _cut_clips(new)
    for entry in report:
        index = int(entry.get("index") or 0)
        clip = cut[index] if 0 <= index < len(cut) and index < len(shot_ids) and cut[index].get("shot_id") == shot_ids[index] else None
        if clip is not None and isinstance(clip.get("sound_in"), dict):
            clip["sound_in"]["result"] = {"applied": bool(entry.get("applied")), "seconds": entry.get("seconds"), "reason": str(entry.get("reason") or "")}
    return new


def audio_source(clip: Mapping[str, Any]) -> str:
    """Where a clip's voices come from in the cut. A timeline saved before this field reads from its old flags."""
    chosen = clip.get("audio_source")
    if chosen in AUDIO_SOURCES:
        return str(chosen)
    if clip.get("native_audio"):
        return "native"
    return "tts" if clip.get("voice_path") else "none"


def set_audio_source(timeline: Mapping[str, Any], shot_id: int | None, source: str, *, shot_uid: int | None = None) -> dict[str, Any]:
    """原声 / 配音 / 不要：一镜一选。选配音而这一镜还没配过音的，合成前补配(见 ``needs_voice``)。"""
    if source not in AUDIO_SOURCES:
        raise TimelineError(_text_of("set_audio_source.text").format(', '.join(AUDIO_SOURCES)))
    new = deepcopy(dict(timeline))
    clip = _clip(new, shot_id, shot_uid)
    if source == "native" and not clip.get("native_available"):
        raise TimelineError(_text_of("set_audio_source.text.2"))
    clip["audio_source"], clip["audio_source_edited"] = source, True
    _touch(new)
    return new


def needs_voice(timeline: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The clips in the cut that are set to a dub they do not have yet."""
    return [c for c in _cut_clips(timeline) if audio_source(c) == "tts" and not c.get("voice_path") and not c.get("muted")]


def set_voice(timeline: Mapping[str, Any], shot_id: int | None, voice_path: str | None, *, shot_uid: int | None = None) -> dict[str, Any]:
    """A dub made for a clip after the timeline was built. Not an edit: the revision stays."""
    new = deepcopy(dict(timeline))
    _clip(new, shot_id, shot_uid)["voice_path"] = voice_path
    return new


def settings_of(timeline: Mapping[str, Any]) -> dict[str, bool]:
    saved = timeline.get("settings") if isinstance(timeline.get("settings"), Mapping) else {}
    return {key: bool(saved.get(key, True)) for key in SETTINGS}


def set_settings(timeline: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    unknown = [key for key in changes if key not in SETTINGS]
    if unknown:
        raise TimelineError(_text_of("set_settings.text").format(', '.join(map(str, unknown)), ', '.join(SETTINGS)))
    new = deepcopy(dict(timeline))
    new["settings"] = {**settings_of(new), **{key: bool(value) for key, value in changes.items()}}
    _touch(new)
    return new


def set_subtitle(timeline: Mapping[str, Any], shot_id: int | None, text: str, *, shot_uid: int | None = None) -> dict[str, Any]:
    new = deepcopy(dict(timeline))
    _clip(new, shot_id, shot_uid)["subtitle"] = re.sub(r"\s+", " ", str(text or "")).strip()[:200]
    _touch(new)
    return new


def set_muted(timeline: Mapping[str, Any], shot_id: int | None, muted: bool, *, shot_uid: int | None = None) -> dict[str, Any]:
    new = deepcopy(dict(timeline))
    _clip(new, shot_id, shot_uid)["muted"] = bool(muted)
    _touch(new)
    return new


def choose_candidate(timeline: Mapping[str, Any], shot_id: int | None, video_url: str, *, shot_uid: int | None = None) -> dict[str, Any]:
    new = deepcopy(dict(timeline))
    clip = _clip(new, shot_id, shot_uid)
    if video_url not in (clip.get("candidates") or []):
        raise TimelineError(_text_of("choose_candidate.text"))
    clip["video_url"] = video_url
    _touch(new)
    return new


def review(timeline: Mapping[str, Any], shot_id: int | None, *, decision: str, note: str = "", shot_uid: int | None = None) -> dict[str, Any]:
    """The reviewer's word on a clip: a rejected one is left out of the cut until it is remade."""
    if decision not in REVIEW_DECISIONS:
        raise TimelineError(_text_of("review.text").format(', '.join(REVIEW_DECISIONS)))
    new = deepcopy(dict(timeline))
    _clip(new, shot_id, shot_uid)["review"] = {"decision": decision, "note": str(note or "")[:500], "decided_at": _now() if decision != "pending" else None}
    _touch(new)
    return new


def set_title(timeline: Mapping[str, Any], text: str | None) -> dict[str, Any]:
    new = deepcopy(dict(timeline))
    clean = str(text or "").strip()[:60]
    new["title"] = {"text": clean, "seconds": TITLE_SECONDS if clean else 0.0}
    _touch(new)
    return new


def set_bgm(timeline: Mapping[str, Any], *, source: str, path: str | None = None, url: str | None = None, library_id: str | None = None,
            name: str | None = None, volume: float | None = None, duck: bool | None = None, start: float | None = None) -> dict[str, Any]:
    if source not in BGM_SOURCES:
        raise TimelineError(_text_of("set_bgm.text").format(', '.join(BGM_SOURCES)))
    new = deepcopy(dict(timeline))
    current = dict(new.get("bgm") or {})
    current.update({"source": source, "path": path if source != "none" else None, "url": url if source != "none" else None,
                    "library_id": library_id if source == "library" else None, "name": name if source != "none" else None})
    if volume is not None:
        current["volume"] = max(0.0, min(float(volume), 1.0))
    if duck is not None:
        current["duck"] = bool(duck)
    if start is not None:
        # 音乐定位：配乐从成片第几秒进。
        current["start"] = round(max(0.0, min(float(start), summary(new)["seconds"])), 2)
    new["bgm"] = current
    _touch(new)
    return new


# ---------------------------------------------------------------------------- reading


def summary(timeline: Mapping[str, Any]) -> dict[str, Any]:
    clips = [c for c in timeline.get("clips") or [] if isinstance(c, Mapping)]
    decisions = {d: sum(1 for c in clips if (c.get("review") or {}).get("decision") == d) for d in REVIEW_DECISIONS}
    included = [c for c in clips if (c.get("review") or {}).get("decision") != "rejected"]
    total = float((timeline.get("title") or {}).get("seconds") or 0)
    for clip in included:
        total += clip_seconds(clip)
    return {
        "clips": len(clips), "included": len(included), "review": decisions,
        "seconds": round(total, 2), "bgm": (timeline.get("bgm") or {}).get("source", "none"),
        "revision": int(timeline.get("revision") or 0),
        "audio_sources": {source: sum(1 for c in included if audio_source(c) == source) for source in AUDIO_SOURCES},
    }


def clip_seconds(clip: Mapping[str, Any]) -> float:
    duration = float(clip.get("duration") or 0)
    start = float(clip.get("in") or 0)
    end = clip.get("out")
    end = float(end) if end is not None else duration
    return max(0.0, (end - start) if end else max(0.0, duration - start))


def _cut_clips(timeline: Mapping[str, Any]) -> list[Any]:
    """The clips that make the cut, in order: a rejected one and one without footage are out."""
    return [c for c in timeline.get("clips") or [] if isinstance(c, Mapping) and (c.get("review") or {}).get("decision") != "rejected" and c.get("video_url")]


def render_plan(timeline: Mapping[str, Any]) -> dict[str, Any]:
    """What the compositor needs: the clips in the cut (rejected ones out), with trims, subtitles, voices, transitions and music."""
    clips = _cut_clips(timeline)
    bgm = timeline.get("bgm") or {}
    ambience = timeline.get("ambience") or {}
    settings = settings_of(timeline)
    dialogue = settings["dialogue"]
    sources = [audio_source(c) if dialogue and not c.get("muted") else "none" for c in clips]
    return {
        "shot_video_urls": [str(c["video_url"]) for c in clips],
        "shot_ids": [c.get("shot_id") for c in clips],
        "subtitles": [str(c.get("subtitle") or "") if settings["subtitles"] else "" for c in clips],
        # 原声优先：选了原声的镜头用片段自己的声音，选了配音的才挂配音。
        "shot_voices": [c.get("voice_path") if source == "tts" else None for c, source in zip(clips, sources)],
        "native_audio": [source == "native" for source in sources],
        "trims": [(float(c.get("in") or 0), (float(c["out"]) if c.get("out") is not None else None)) for c in clips],
        "blackouts": [dict(c["blackout"]) if isinstance(c.get("blackout"), Mapping) else None for c in clips],
        "transition_plans": [dict(c.get("transition_in") or {"type": "crossfade", "duration": 0.22}) if settings["transitions"]
                             else {"type": "hard_cut", "duration": 0.04} for c in clips[1:]],
        "sound_joins": [{key: value for key, value in (c.get("sound_in") or {}).items() if key in {"join", "seconds"}} or None for c in clips[1:]],
        "title": (str((timeline.get("title") or {}).get("text") or "") or None) if settings["title_card"] else None,
        "fade_edges": settings["title_card"],
        "bgm": bgm.get("source", "none") != "none",
        "bgm_path": bgm.get("path") if bgm.get("source", "none") != "none" else None,
        "bgm_volume": float(bgm.get("volume") or 0.16),
        "bgm_start": float(bgm.get("start") or 0.0),
        "sfx_path": ambience.get("path"),
        "audio_path": timeline.get("voice_track") if dialogue and not any(source == "native" for source in sources) else None,
    }


__all__ = [
    "AUDIO_SOURCES", "BGM_SOURCES", "REVIEW_DECISIONS", "SETTINGS", "TIMELINE_KEY", "TRANSITIONS", "TimelineError",
    "audio_source", "build", "choose_candidate", "clip_seconds", "is_current", "needs_voice", "refresh", "render_plan", "review",
    "record_sound_results", "set_audio_source", "set_bgm", "set_muted", "set_settings", "set_sound_join", "set_subtitle", "set_title",
    "set_transition", "set_voice", "settings_of", "summary", "trim", "with_new_sound", "with_shot_uids",
]

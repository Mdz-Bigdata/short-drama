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

TIMELINE_KEY = "7_timeline"
VERSION = 1
FPS = 30
WIDTH, HEIGHT = 1080, 1920
TITLE_SECONDS = 2.6
TRANSITIONS = ("hard_cut", "match_cut", "crossfade", "dip_to_black", "neutral_bridge")
REVIEW_DECISIONS = ("pending", "approved", "rejected")
BGM_SOURCES = ("none", "generated", "library")


class TimelineError(ValueError):
    """The edit names a clip or a value the timeline cannot take."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _subtitle_of(shot: Mapping[str, Any]) -> str:
    """The on-screen line for a shot: its dialogue without speaker labels, else a short cue from the description."""
    text = str(shot.get("dialogue") or "").strip()
    text = re.sub(r"[^：:]{1,8}[：:]", "", text).strip() if text else ""
    if not text:
        text = str(shot.get("desc") or "").strip()[:24]
    return re.sub(r"\s+", " ", text)


def _clip_fingerprint(shot: Mapping[str, Any]) -> str:
    raw = json.dumps({"url": shot.get("video_url"), "duration": shot.get("duration"), "contract": shot.get("contract_fingerprint")}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def build(task: Mapping[str, Any], *, transitions: Sequence[Mapping[str, Any]] | None = None, title: str | None = None) -> dict[str, Any]:
    """A fresh timeline from the project's clips and audio; review decisions start pending."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    shots = [s for s in (assets.get("5") or []) if isinstance(s, Mapping) and s.get("video_url")]
    audio = assets.get("6") if isinstance(assets.get("6"), Mapping) else {}
    voices = list(audio.get("shot_voices") or [])
    all_shots = [s for s in (assets.get("5") or []) if isinstance(s, Mapping)]
    specs = list(transitions or [])
    clips: list[dict[str, Any]] = []
    for position, shot in enumerate(shots):
        index_in_stage = next((i for i, s in enumerate(all_shots) if s is shot), position)
        duration = float(shot.get("duration") or 0) or None
        spec = specs[position - 1] if position >= 1 and position - 1 < len(specs) else None
        clips.append({
            "shot_id": shot.get("shot_id"),
            "video_url": shot.get("video_url"),
            "candidates": [u for u in (shot.get("candidates") or [shot.get("video_url")]) if u],
            "duration": duration,
            "in": 0.0,
            "out": None,
            "muted": False,
            "subtitle": _subtitle_of(shot),
            "voice_path": voices[index_in_stage] if index_in_stage < len(voices) else None,
            "transition_in": {"type": str((spec or {}).get("type") or "crossfade"), "duration": float((spec or {}).get("duration") or 0.22)} if position else None,
            "review": {"decision": "pending", "note": "", "decided_at": None},
            "fingerprint": _clip_fingerprint(shot),
        })
    bgm_path = audio.get("bgm_path")
    return {
        "version": VERSION,
        "fps": FPS, "width": WIDTH, "height": HEIGHT,
        "title": {"text": title or "", "seconds": TITLE_SECONDS if title else 0.0},
        "clips": clips,
        "bgm": {"source": "generated" if bgm_path else "none", "path": bgm_path, "url": audio.get("bgm_url"), "library_id": None, "name": None, "volume": 0.16, "duck": True},
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
    for key in ("title", "bgm", "ambience"):
        if isinstance(timeline.get(key), Mapping):
            fresh[key] = deepcopy(dict(timeline[key]))
    fresh["revision"] = int(timeline.get("revision") or 0) + 1
    return fresh


def _clip(timeline: dict[str, Any], shot_id: int) -> dict[str, Any]:
    for clip in timeline.get("clips") or []:
        if str(clip.get("shot_id")) == str(shot_id):
            return clip
    raise TimelineError(f"时间线上没有镜头 {shot_id}")


# ---------------------------------------------------------------------------- edits


def trim(timeline: Mapping[str, Any], shot_id: int, *, start: float, end: float | None) -> dict[str, Any]:
    new = deepcopy(dict(timeline))
    clip = _clip(new, shot_id)
    duration = clip.get("duration")
    start = max(0.0, float(start))
    if end is not None:
        end = float(end)
        if end <= start + 0.5:
            raise TimelineError("出点至少要比入点晚 0.5 秒")
        if duration and end > float(duration) + 0.01:
            raise TimelineError(f"出点超过了片段长度 {duration} 秒")
    if duration and start >= float(duration):
        raise TimelineError("入点超过了片段长度")
    clip["in"], clip["out"] = round(start, 3), (round(end, 3) if end is not None else None)
    _touch(new)
    return new


def set_transition(timeline: Mapping[str, Any], shot_id: int, *, kind: str, duration: float = 0.22) -> dict[str, Any]:
    if kind not in TRANSITIONS:
        raise TimelineError(f"未知转场 {kind}；可用：{', '.join(TRANSITIONS)}")
    new = deepcopy(dict(timeline))
    clip = _clip(new, shot_id)
    if new["clips"] and new["clips"][0] is clip:
        raise TimelineError("第一镜之前没有转场")
    clip["transition_in"] = {"type": kind, "duration": max(0.04, min(float(duration), 1.0))}
    _touch(new)
    return new


def set_subtitle(timeline: Mapping[str, Any], shot_id: int, text: str) -> dict[str, Any]:
    new = deepcopy(dict(timeline))
    _clip(new, shot_id)["subtitle"] = re.sub(r"\s+", " ", str(text or "")).strip()[:200]
    _touch(new)
    return new


def set_muted(timeline: Mapping[str, Any], shot_id: int, muted: bool) -> dict[str, Any]:
    new = deepcopy(dict(timeline))
    _clip(new, shot_id)["muted"] = bool(muted)
    _touch(new)
    return new


def choose_candidate(timeline: Mapping[str, Any], shot_id: int, video_url: str) -> dict[str, Any]:
    new = deepcopy(dict(timeline))
    clip = _clip(new, shot_id)
    if video_url not in (clip.get("candidates") or []):
        raise TimelineError("只能在这一镜已生成的候选版本里选")
    clip["video_url"] = video_url
    _touch(new)
    return new


def review(timeline: Mapping[str, Any], shot_id: int, *, decision: str, note: str = "") -> dict[str, Any]:
    """The reviewer's word on a clip: a rejected one is left out of the cut until it is remade."""
    if decision not in REVIEW_DECISIONS:
        raise TimelineError(f"审看结论只能是 {', '.join(REVIEW_DECISIONS)}")
    new = deepcopy(dict(timeline))
    _clip(new, shot_id)["review"] = {"decision": decision, "note": str(note or "")[:500], "decided_at": _now() if decision != "pending" else None}
    _touch(new)
    return new


def set_title(timeline: Mapping[str, Any], text: str | None) -> dict[str, Any]:
    new = deepcopy(dict(timeline))
    clean = str(text or "").strip()[:60]
    new["title"] = {"text": clean, "seconds": TITLE_SECONDS if clean else 0.0}
    _touch(new)
    return new


def set_bgm(timeline: Mapping[str, Any], *, source: str, path: str | None = None, url: str | None = None, library_id: str | None = None,
            name: str | None = None, volume: float | None = None, duck: bool | None = None) -> dict[str, Any]:
    if source not in BGM_SOURCES:
        raise TimelineError(f"配乐来源只能是 {', '.join(BGM_SOURCES)}")
    new = deepcopy(dict(timeline))
    current = dict(new.get("bgm") or {})
    current.update({"source": source, "path": path if source != "none" else None, "url": url if source != "none" else None,
                    "library_id": library_id if source == "library" else None, "name": name if source != "none" else None})
    if volume is not None:
        current["volume"] = max(0.0, min(float(volume), 1.0))
    if duck is not None:
        current["duck"] = bool(duck)
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
    }


def clip_seconds(clip: Mapping[str, Any]) -> float:
    duration = float(clip.get("duration") or 0)
    start = float(clip.get("in") or 0)
    end = clip.get("out")
    end = float(end) if end is not None else duration
    return max(0.0, (end - start) if end else max(0.0, duration - start))


def render_plan(timeline: Mapping[str, Any]) -> dict[str, Any]:
    """What the compositor needs: the clips in the cut (rejected ones out), with trims, subtitles, voices, transitions and music."""
    clips = [c for c in timeline.get("clips") or [] if isinstance(c, Mapping) and (c.get("review") or {}).get("decision") != "rejected" and c.get("video_url")]
    bgm = timeline.get("bgm") or {}
    ambience = timeline.get("ambience") or {}
    return {
        "shot_video_urls": [str(c["video_url"]) for c in clips],
        "shot_ids": [c.get("shot_id") for c in clips],
        "subtitles": [str(c.get("subtitle") or "") for c in clips],
        "shot_voices": [None if c.get("muted") else c.get("voice_path") for c in clips],
        "trims": [(float(c.get("in") or 0), (float(c["out"]) if c.get("out") is not None else None)) for c in clips],
        "transition_plans": [dict(c.get("transition_in") or {"type": "crossfade", "duration": 0.22}) for c in clips[1:]],
        "title": str((timeline.get("title") or {}).get("text") or "") or None,
        "bgm": bgm.get("source", "none") != "none",
        "bgm_path": bgm.get("path") if bgm.get("source", "none") != "none" else None,
        "bgm_volume": float(bgm.get("volume") or 0.16),
        "sfx_path": ambience.get("path"),
        "audio_path": timeline.get("voice_track"),
    }


__all__ = [
    "BGM_SOURCES", "REVIEW_DECISIONS", "TIMELINE_KEY", "TRANSITIONS", "TimelineError",
    "build", "choose_candidate", "clip_seconds", "is_current", "refresh", "render_plan", "review",
    "set_bgm", "set_muted", "set_subtitle", "set_title", "set_transition", "summary", "trim",
]

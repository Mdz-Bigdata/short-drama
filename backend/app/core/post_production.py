# -*- coding: utf-8 -*-
"""What the 剪辑合成师 page shows beside the timeline, worked out from the project as it is.

The timeline (:mod:`app.core.edit_timeline`) is what gets rendered. This module only reads: how tense each shot
in the cut is (a curve over the film's running time), where each scene starts, how well each piece in the music
library fits this drama, how big the film will be, and the films rendered so far. Weights and word lists live in
``app/data/prompt/post_production.json``; the tension signal words are the ones stage 4 uses.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from app.core import edit_timeline, episode_cycle, prompt_data
from app.core import film_finishing
from app.core.scene_tension import tension_hits

_DATA = "post_production"
FILM_VERSIONS_KEY = "film_versions"
#: 第 6 阶段每次生成的配乐都留一份：键名不以数字开头，重跑前面的阶段不会把它清掉。
MUSIC_VERSIONS_KEY = "music_versions"
# 这部剧锁定的配乐提示词：第一次出配乐时定下，全剧各集同一套音乐语言。
MUSIC_LANGUAGE_KEY = "6_music_language"
MAX_FILM_VERSIONS = 20


def _shots_by_uid(task: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    return {str(episode_cycle.shot_uid(s)): s for s in (assets.get("5") or []) if isinstance(s, Mapping)}


def _shot_text(shot: Mapping[str, Any] | None, clip: Mapping[str, Any]) -> str:
    if not shot:
        return str(clip.get("subtitle") or "")
    return " ".join(str(shot.get(key) or "") for key in ("dialogue", "desc"))


def shot_tension(text: str) -> float:
    rule = prompt_data.value(_DATA, "tension")
    exclaim = sum(text.count(mark) for mark in rule["exclaim_marks"])
    question = sum(text.count(mark) for mark in rule["question_marks"])
    score = rule["base"] + rule["per_hit"] * len(tension_hits(text)) + rule["per_exclaim"] * exclaim + rule["per_question"] * question
    return round(max(0.0, min(1.0, score)), 3)


def running_order(timeline: Mapping[str, Any], task: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The clips in the cut with where each starts in the film, its length and how tense it is."""
    shots = _shots_by_uid(task)
    at = float((timeline.get("title") or {}).get("seconds") or 0) if edit_timeline.settings_of(timeline)["title_card"] else 0.0
    rows = []
    for clip in edit_timeline._cut_clips(timeline):
        seconds = edit_timeline.clip_seconds(clip)
        shot = shots.get(str(clip.get("shot_uid")))
        rows.append({
            "shot_uid": clip.get("shot_uid"), "shot_id": clip.get("shot_id"), "scene_id": str(clip.get("scene_id") or ""),
            "t": round(at, 2), "seconds": round(seconds, 2), "tension": shot_tension(_shot_text(shot, clip)),
        })
        at += seconds
    return rows


def scene_markers(order: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Where each scene starts in the film, for the music placement slider."""
    markers, last = [], None
    for row in order:
        if row["scene_id"] != last:
            markers.append({"scene_id": row["scene_id"], "t": row["t"]})
            last = row["scene_id"]
    return markers


def _mood_weights(text: str) -> dict[str, float]:
    lowered = text.lower()
    counts = {m["id"]: sum(1 for word in m["words"] if word.lower() in lowered) for m in prompt_data.value(_DATA, "moods")}
    total = sum(counts.values())
    return {key: value / total for key, value in counts.items() if value} if total else {}


def film_mood(task: Mapping[str, Any], order: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """This drama's mood as weights over the mood table: its genre and style, its lines, and how tense the cut runs."""
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    shots = _shots_by_uid(task)
    text = " ".join(str(config.get(key) or "") for key in ("genre", "style", "title_suggestion", "story_premise"))
    text += " " + " ".join(_shot_text(shots.get(str(row["shot_uid"])), {}) for row in order)
    weights = _mood_weights(text)
    if order:
        mean = sum(row["tension"] for row in order) / len(order)
        lift = prompt_data.value(_DATA, "match")["tense_from_curve"] * mean
        weights["tense"] = weights.get("tense", 0.0) + lift
        total = sum(weights.values())
        weights = {key: value / total for key, value in weights.items()}
    return weights


def mood_tags(track: Mapping[str, Any]) -> list[str]:
    weights = _mood_weights(f"{track.get('name') or ''} {track.get('mood') or ''}")
    labels = {m["id"]: m["label"] for m in prompt_data.value(_DATA, "moods")}
    ranked = [labels[key] for key, _ in sorted(weights.items(), key=lambda item: -item[1]) if key in labels][:3]
    mood = str(track.get("mood") or "").strip()
    return ranked or ([mood] if mood else [])


def track_match(track: Mapping[str, Any], mood: Mapping[str, float]) -> float:
    rule = prompt_data.value(_DATA, "match")
    weights = _mood_weights(f"{track.get('name') or ''} {track.get('mood') or ''}")
    overlap = sum(mood.get(key, 0.0) * value for key, value in weights.items())
    # 两边都是归一化的权重，点积在 0..1；不同情绪之间的交集稀疏，开方让部分匹配也拉开档次。
    return round(min(0.99, rule["base"] + rule["spread"] * overlap ** 0.5), 2)


def ranked_library(tracks: Sequence[Mapping[str, Any]], mood: Mapping[str, float]) -> list[dict[str, Any]]:
    rows = [{**{k: v for k, v in track.items() if k != "path"}, "match": track_match(track, mood), "tags": mood_tags(track)} for track in tracks]
    return sorted(rows, key=lambda row: -row["match"])


def music_prompt(style: str, genre: str, cluster: str = "") -> str:
    """What stage 6 asks the music model for: the genre's instrumentation, and the same language every episode.

    A genre read only as ``general`` (the title named nothing) takes the drama's genre cluster's
    instrumentation instead, so a wuxia drama with a plain title still gets period instruments.
    """
    palettes = prompt_data.value(_DATA, "music_palettes")
    genre = str(genre or "").strip()
    palette = (palettes.get(genre) or prompt_data.value(_DATA, "music_cluster_palettes").get(str(cluster or "").strip())
               or palettes["default"])
    text = (prompt_data.text(_DATA, "music_prompt").replace("{style}", str(style or ""))
            .replace("{genre}", "" if genre == "general" else genre).replace("{palette}", palette))
    return " ".join(f"{text}, {prompt_data.text(_DATA, 'music_series_suffix')}".split())


def series_music_prompt(assets: Mapping[str, Any], style: str, genre: str, cluster: str = "") -> str:
    """The music prompt this drama is locked to: the first one music was made from, else a fresh one.

    Genre decides the score's tone, and the whole drama keeps one musical language: once an
    episode's music was generated, later episodes ask for it in exactly the same words.
    """
    stored = assets.get(MUSIC_LANGUAGE_KEY)
    if isinstance(stored, Mapping) and str(stored.get("prompt") or "").strip():
        return str(stored["prompt"])
    return music_prompt(style, genre, cluster)


def lock_music_language(assets: dict[str, Any], prompt: str, genre: str) -> None:
    """Keep the prompt the drama's first music was made from; later calls change nothing."""
    if prompt and not (isinstance(assets.get(MUSIC_LANGUAGE_KEY), Mapping) and assets[MUSIC_LANGUAGE_KEY].get("prompt")):
        assets[MUSIC_LANGUAGE_KEY] = {"prompt": prompt, "genre": str(genre or "")}


def ambience_prompt() -> str:
    return prompt_data.text(_DATA, "ambience_prompt")


def estimated_bytes(seconds: float) -> int:
    rate = prompt_data.value(_DATA, "bitrate_kbps")
    return int(max(0.0, seconds) * (rate["video"] + rate["audio"]) * 1000 / 8)


def film_record(url: str | None, *, timeline: Mapping[str, Any], compose_mode: str, rendered_at: str,
                episode: int | None = None, local_path: str | None = None, seconds: float | None = None) -> dict[str, Any] | None:
    """One rendered film for the version list."""
    if not url:
        return None
    size = os.path.getsize(local_path) if local_path and os.path.isfile(local_path) else None
    return {
        "url": url, "revision": timeline.get("revision"), "rendered_at": rendered_at, "compose_mode": compose_mode,
        "seconds": round(float(seconds), 2) if seconds else edit_timeline.summary(timeline)["seconds"], "bytes": size,
        **({"episode": episode} if episode is not None else {}),
    }


def remember_film(assets: dict[str, Any], record: Mapping[str, Any] | None) -> None:
    """Add a rendered film to the version list; the same file rendered again moves to the top."""
    if not record:
        return
    versions = [v for v in (assets.get(FILM_VERSIONS_KEY) or []) if isinstance(v, Mapping) and v.get("url") != record["url"]]
    assets[FILM_VERSIONS_KEY] = ([dict(record)] + versions)[:MAX_FILM_VERSIONS]


def _still_draft(shot: Mapping[str, Any]) -> bool:
    """A shot rendered at draft resolution and neither upscaled nor marked for a full-resolution retake."""
    return bool(shot.get("draft_resolution")) and not shot.get("draft_upscaled") and not shot.get("hd_retake")


def remember_music(assets: dict[str, Any], *, url: str | None, path: str | None, prompt: str | None, created_at: str,
                   episode: int | None = None) -> None:
    """Add a piece of generated music to the version list, newest first; the same file is listed once."""
    if not path:
        return
    entry = {"url": url, "path": path, "prompt": prompt, "created_at": created_at, **({"episode": episode} if episode is not None else {})}
    kept = [v for v in (assets.get(MUSIC_VERSIONS_KEY) or []) if isinstance(v, Mapping) and v.get("path") != path]
    assets[MUSIC_VERSIONS_KEY] = ([entry] + kept)[: prompt_data.number(_DATA, "max_music_versions")]


def music_version(assets: Mapping[str, Any], url: str) -> Mapping[str, Any] | None:
    return next((v for v in assets.get(MUSIC_VERSIONS_KEY) or [] if isinstance(v, Mapping) and v.get("url") == url), None)


def _of_episode(items: Any, episode: Any) -> list[dict[str, Any]]:
    """The versions that belong with the episode on the timeline; per-episode work shows one episode's versions."""
    rows = [dict(item) for item in (items or []) if isinstance(item, Mapping)]
    if episode is None:
        return rows
    return [row for row in rows if row.get("episode") in (None, episode)]


def view(task: Mapping[str, Any], timeline: Mapping[str, Any], tracks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    order = running_order(timeline, task)
    episode = timeline.get("episode")
    shots = _shots_by_uid(task)
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    seconds = edit_timeline.summary(timeline)["seconds"]
    return {
        "settings": edit_timeline.settings_of(timeline),
        # 成片精修：现在的设定、可选项(按 id)、这一集账本里的下集预告(给片尾卡预填)。
        "finishing": film_finishing.view(timeline, task),
        "tension": order,
        "scene_markers": scene_markers(order),
        "bgm_library": ranked_library(tracks, film_mood(task, order)),
        "estimated_bytes": estimated_bytes(seconds),
        "film_versions": _of_episode(assets.get(FILM_VERSIONS_KEY), episode),
        # 生成过的配乐(服务器上的路径不外露)，剪辑合成师页的配乐「版本」从这里选。
        "music_versions": [{k: v for k, v in item.items() if k != "path"} for item in _of_episode(assets.get(MUSIC_VERSIONS_KEY), episode)],
        # 胶片条要的：每镜的定帧图、是不是样片分辨率、人声从哪来。
        "shots": [
            {"shot_uid": clip.get("shot_uid"), "image_url": (shots.get(str(clip.get("shot_uid"))) or {}).get("image_url"),
             "draft": _still_draft(shots.get(str(clip.get("shot_uid"))) or {}),
             "audio_source": edit_timeline.audio_source(clip), "native_available": bool(clip.get("native_available"))}
            for clip in timeline.get("clips") or [] if isinstance(clip, Mapping)
        ],
    }


__all__ = [
    "FILM_VERSIONS_KEY", "MUSIC_VERSIONS_KEY", "ambience_prompt", "estimated_bytes", "music_prompt", "music_version", "remember_music", "film_mood", "film_record", "mood_tags", "ranked_library", "remember_film",
    "running_order", "scene_markers", "shot_tension", "track_match", "view",
]

"""The handoff check for one episode: every cut between two neighbouring clips, in storyboard order.

Each clip's opening and closing windows are measured once and kept on the task under ``5_handoff`` by
clip address (a new or re-picked clip has a new address, so it is measured again). Only that cache is
written; nothing about the clips themselves changes. See ``app.core.clip_handoff`` for what is measured.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import clip_handoff, episode_cycle, media_compositor, prompt_data

CACHE_KEY = "5_handoff"
# The cache is a convenience: it is cut back rather than allowed to grow with every retake.
MAX_CACHED = 600


def _clip_sequence(task: Mapping[str, Any], episode: int) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """(clip, first shot it covers, last shot it covers) in storyboard order, one entry per clip."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    clips = [clip for clip in assets.get("5") or [] if isinstance(clip, dict)]
    sequence: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    clip_of = episode_cycle.clip_finder(clips)
    for shot in episode_cycle.episode_shots(task, episode):
        clip = clip_of(shot)
        if not clip or not clip.get("video_url"):
            continue
        if sequence and sequence[-1][0] is clip:
            sequence[-1] = (clip, sequence[-1][1], shot)
        else:
            sequence.append((clip, shot, shot))
    return sequence


def _profiles(url: str, cached: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """(head, tail, newly measured) for one clip address."""
    known = cached.get(url) if isinstance(cached.get(url), Mapping) else None
    if known and isinstance(known.get("head"), Mapping) and isinstance(known.get("tail"), Mapping):
        return dict(known["head"]), dict(known["tail"]), False
    path = media_compositor.local_media_path(url)
    if not path:
        missing = clip_handoff.Profile(measured=False, reason=prompt_data.text("clip_handoff", "missing_file")).as_dict()
        return missing, missing, False
    return clip_handoff.measure(path, "head").as_dict(), clip_handoff.measure(path, "tail").as_dict(), True


def _where(shot: Mapping[str, Any], clip: Mapping[str, Any]) -> dict[str, Any]:
    return {"scene_id": str(shot.get("scene_id") or ""), "shot_id": shot.get("shot_id"), "video_url": str(clip.get("video_url") or "")}


def episode_report(service: Any, task_id: str, episode: int) -> dict[str, Any] | None:
    """Every cut of the episode with its verdict; ``None`` when the task does not exist."""
    task = service.repo.get_task(task_id)
    if not task:
        return None
    sequence = _clip_sequence(task, episode)
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    cached = dict(assets.get(CACHE_KEY) or {}) if isinstance(assets.get(CACHE_KEY), Mapping) else {}
    measured: dict[str, dict[str, Any]] = {}
    for clip, _first, _last in sequence:
        url = str(clip["video_url"])
        if url in measured:
            continue
        head, tail, fresh = _profiles(url, cached)
        measured[url] = {"head": head, "tail": tail, "fresh": fresh}
    pairs = []
    for (before, _before_first, before_last), (after, after_first, _after_last) in zip(sequence, sequence[1:]):
        tail = clip_handoff.Profile(**{k: v for k, v in measured[str(before["video_url"])]["tail"].items() if k in clip_handoff.Profile.__dataclass_fields__})
        head = clip_handoff.Profile(**{k: v for k, v in measured[str(after["video_url"])]["head"].items() if k in clip_handoff.Profile.__dataclass_fields__})
        report = clip_handoff.compare(tail, head, clip_handoff.planned_from(before_last, after_first))
        pairs.append({"from": _where(before_last, before), "to": _where(after_first, after), **report.as_dict()})
    fresh = {url: {"head": item["head"], "tail": item["tail"]} for url, item in measured.items() if item["fresh"]}
    if fresh:
        def keep(current: dict[str, Any]) -> None:
            store = current.setdefault("assets", {})
            saved = dict(store.get(CACHE_KEY) or {}) if isinstance(store.get(CACHE_KEY), Mapping) else {}
            saved.update(fresh)
            store[CACHE_KEY] = dict(list(saved.items())[-MAX_CACHED:])

        service.repo.mutate_task(task_id, keep)
    suspect = sum(1 for pair in pairs if pair["verdict"] == "suspect")
    summary = prompt_data.text("clip_handoff", "summary").format(count=suspect) if suspect else prompt_data.text("clip_handoff", "summary_good")
    return {"task_id": task_id, "episode": int(episode), "pairs": pairs, "suspect": suspect, "summary": summary if pairs else ""}


__all__ = ["CACHE_KEY", "episode_report"]

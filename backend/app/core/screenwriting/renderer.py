# -*- coding: utf-8 -*-
"""Render the structured screenwriting state into the formats the rest of the
pipeline already consumes: the screenplay text (``assets["2"]``) and the
structured breakdown (``assets["2_breakdown"]``).

The text is what a person reads, so it is prose: a ``第N集 标题`` line, then
narration paragraphs separated by one blank line with dialogue inside “”. The
heading is the only structural line; the episode splitter and the dashboard's
episode count still read it. Shot boundaries, cast, durations and camera work
live in the breakdown and the structured state, never as label lines in the text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.screenwriting.prose import has_episode_heading, prose_from_scenes

_PHASES = ("故事开始", "进展纠葛", "危机", "高潮", "结局")
_PHASE_CUTS = (0.15, 0.55, 0.75, 0.9)
_MAX_CONTENT_CHARS = 6000


def _text(value: object, limit: int = 4000) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]


def _scene_heading(scene: Mapping[str, Any]) -> str:
    setting = _text(scene.get("setting"), 200)
    if setting:
        return setting
    scenes = [item for item in (scene.get("scenes") or []) if isinstance(item, str) and item.strip()]
    return scenes[0].strip() if scenes else "未指定场景"


def _source_slice(state: Mapping[str, Any], episode: int) -> str:
    if state.get("source_kind") == "outline":
        return ""
    source = str(state.get("source_text") or "")
    for entry in state.get("ledger") or []:
        if isinstance(entry, Mapping) and int(entry.get("episode") or 0) == int(episode):
            span = entry.get("source_range")
            if not isinstance(span, Mapping):
                return ""
            return source[int(span.get("start") or 0):int(span.get("end") or len(source))].strip()
    return ""


def episode_body(state: Mapping[str, Any], episode: int) -> str:
    """What ``episode`` reads as: its authored prose, else its own slice of the source.

    An uploaded novel or screenplay is the author's text, so it is shown verbatim
    rather than retold. Empty when neither exists (a state written before prose was
    authored); ``render_episode_text`` then assembles a body from the shots.
    """
    episodes = state.get("episodes")
    entry = episodes.get(str(int(episode))) if isinstance(episodes, Mapping) else None
    prose = str(entry.get("prose") or "").strip() if isinstance(entry, Mapping) else ""
    return prose or _source_slice(state, episode)


def render_episode_text(script: Mapping[str, Any], body: str = "") -> str:
    episode = int(script.get("episode") or 1)
    text = body.strip() or prose_from_scenes([scene for scene in (script.get("scenes") or []) if isinstance(scene, Mapping)])
    if has_episode_heading(text, episode):
        return text
    title = _text(script.get("title"), 200) or f"第{episode}集"
    return f"第{episode}集 {title}\n\n{text}".rstrip()


def episode_scripts(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Episode script dicts of ``state`` ordered by episode number."""
    episodes = state.get("episodes") if isinstance(state.get("episodes"), Mapping) else {}
    ordered: list[tuple[int, dict[str, Any]]] = []
    for key, entry in episodes.items():
        if not isinstance(entry, Mapping):
            continue
        script = entry.get("script")
        if not isinstance(script, Mapping):
            continue
        try:
            number = int(script.get("episode") or key)
        except (TypeError, ValueError):
            continue
        ordered.append((number, dict(script)))
    ordered.sort(key=lambda pair: pair[0])
    return [script for _, script in ordered]


def render_episode_texts(state: Mapping[str, Any]) -> dict[int, str]:
    texts: dict[int, str] = {}
    for script in episode_scripts(state):
        number = int(script.get("episode") or 0)
        texts[number] = render_episode_text(script, episode_body(state, number))
    return texts


def render_screenplay(state: Mapping[str, Any]) -> str:
    return "\n\n".join(render_episode_texts(state).values())


# --------------------------------------------------------------------------- breakdown


def scene_breakdown_entry(scene: Mapping[str, Any]) -> dict[str, Any]:
    duration = scene.get("duration_seconds")
    parts: list[str] = []
    heading = _scene_heading(scene)
    if heading:
        parts.append(heading)
    description = _text(scene.get("scene_description"))
    if description:
        parts.append(description)
    spoken: list[str] = []
    for utterance in scene.get("utterances") or []:
        if not isinstance(utterance, Mapping):
            continue
        text = _text(utterance.get("text"), 500)
        if not text:
            continue
        speaker = _text(utterance.get("speaker"), 80) if utterance.get("kind") == "dialogue" else "旁白"
        spoken.append(f"{speaker}：{text}")
    if spoken:
        parts.append("台词：" + " / ".join(spoken))
    return {
        "scene_id": str(scene.get("scene_id") or ""),
        "duration": f"{duration}s" if isinstance(duration, int) and not isinstance(duration, bool) and duration > 0 else "",
        "content": " ".join(parts)[:_MAX_CONTENT_CHARS],
        "characters": [name for name in (scene.get("characters_in_scene") or []) if isinstance(name, str) and name.strip()],
    }


def _phase_for(position: float) -> str:
    for phase, cut in zip(_PHASES, _PHASE_CUTS):
        if position <= cut:
            return phase
    return _PHASES[-1]


def render_timeline(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    ledger = [entry for entry in (state.get("ledger") or []) if isinstance(entry, Mapping)]
    ledger.sort(key=lambda entry: int(entry.get("episode") or 0))
    total = len(ledger)
    events: list[dict[str, Any]] = []
    for index, entry in enumerate(ledger):
        beats = [_text(beat, 500) for beat in (entry.get("story_beats") or []) if _text(beat)]
        position = index / max(total - 1, 1) if total > 1 else 0.0
        events.append({
            "phase": _phase_for(position),
            "title": f"第{entry.get('episode')}集 {_text(entry.get('title'), 120)}".strip(),
            "desc": "；".join(beats)[:4000] or _text(entry.get("hook"), 4000),
            "points": [*beats[:8], *( [f"集尾钩子：{_text(entry.get('hook'), 400)}"] if entry.get("hook") else [])][:30],
        })
    return events[:500]


def render_breakdown(state: Mapping[str, Any]) -> dict[str, Any]:
    inventory = state.get("inventory") if isinstance(state.get("inventory"), Mapping) else {}
    characters = inventory.get("characters") if isinstance(inventory.get("characters"), Mapping) else {}
    scene_assets = inventory.get("scenes") if isinstance(inventory.get("scenes"), Mapping) else {}
    prop_assets = inventory.get("props") if isinstance(inventory.get("props"), Mapping) else {}
    overview = state.get("overview") if isinstance(state.get("overview"), Mapping) else {}
    scenes: list[dict[str, Any]] = []
    for script in episode_scripts(state):
        for scene in script.get("scenes") or []:
            if isinstance(scene, Mapping) and scene.get("scene_id"):
                scenes.append(scene_breakdown_entry(scene))
    roles = [
        {"name": str(name), "position": _text((entry or {}).get("position") if isinstance(entry, Mapping) else "", 120) or "其它角色"}
        for name, entry in characters.items()
        if str(name).strip()
    ]
    return {
        "overview": {
            "title": _text(overview.get("title"), 60),
            "synopsis": _text(overview.get("synopsis"), 4000),
            "genre": _text(overview.get("genre"), 120),
            "theme": _text(overview.get("theme"), 500),
            "world_setting": _text(overview.get("world_setting"), 4000),
        },
        "scenes": scenes,
        "timeline": render_timeline(state),
        "relationships": [],
        "roles": roles,
        "production_assets": {
            "scenes": [
                {"name": str(name), "description": _text((entry or {}).get("description") if isinstance(entry, Mapping) else "", 1000)}
                for name, entry in scene_assets.items() if str(name).strip()
            ],
            "props": [
                {"name": str(name), "description": _text((entry or {}).get("description") if isinstance(entry, Mapping) else "", 1000)}
                for name, entry in prop_assets.items() if str(name).strip()
            ],
            "costumes": [],
            "effects": [],
        },
    }


__all__ = [
    "episode_body",
    "episode_scripts",
    "render_breakdown",
    "render_episode_text",
    "render_episode_texts",
    "render_screenplay",
    "render_timeline",
    "scene_breakdown_entry",
]

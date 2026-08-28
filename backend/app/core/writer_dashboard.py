# -*- coding: utf-8 -*-
"""Deterministic compiler for the Writer Agent dashboard resource."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from app.schema.writer_dashboard import (
    WriterDashboardEpisode,
    WriterDashboardEvent,
    WriterDashboardRelationship,
    WriterDashboardResponse,
    WriterDashboardRole,
    WriterDashboardScene,
    WriterDashboardStats,
    WriterOverview,
)


_EPISODE_NUMBER = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
                   "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}
_EPISODE_HEADING = re.compile(r"^\s*(?:#{1,6}\s*)?(?:【\s*)?第\s*([0-9]{1,3}|[一二三四五六七八九十]{1,3})\s*集(?:\s*】)?\s*[:：\-—]?\s*(.*)$")
_SCENE_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:【\s*)?(?:场景|SCENE)\s*([0-9]{0,4})(?:\s*】)?\s*[:：\-—]?\s*(.*)$",
    re.IGNORECASE,
)
_INT_EXT_HEADING = re.compile(r"^\s*(?:INT\.|EXT\.|内景|外景)[：:\s-]", re.IGNORECASE)
_SPEAKER = re.compile(r"(?:^|\n)[ \t]*(?:【)?([一-龥A-Za-z][一-龥A-Za-z· \t]{0,15})(?:】)?[ \t]*[：:]")
_NON_SPEAKERS = {"场景", "时间", "地点", "画面", "动作", "音效", "音乐", "环境音", "旁白", "镜头", "时长", "节奏"}
_ALLOWED_EPISODE_STATUS = {"idle", "running", "completed", "failed"}
_MAX_DASHBOARD_SECONDS = 604800
_MAX_INFERRED_CHARACTERS = 100
_MAX_INFERRED_CHARACTERS_PER_SCENE = 32
_MAX_INFERRED_RELATIONSHIPS = 5000
_MAX_SCRIPT_BYTES = 2 * 1024 * 1024


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]


def _script_text(value: Any) -> str:
    """Preserve every valid script byte accepted by the update contract."""
    text = str(value or "").replace("\x00", "")
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= _MAX_SCRIPT_BYTES:
        return text
    return encoded[:_MAX_SCRIPT_BYTES].decode("utf-8", errors="ignore")


def _bounded_int(value: Any, *, minimum: int = 0, maximum: int = 200) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return minimum
    return max(minimum, min(maximum, parsed))


def _text_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        cleaned = _text(item, item_limit)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _episode_number(value: str) -> int:
    if value.isdigit():
        return max(1, min(200, int(value)))
    return _EPISODE_NUMBER.get(value, 1)


def _episode_from_scene_id(scene_id: str) -> int:
    match = re.search(r"E(\d{1,3})", scene_id, flags=re.IGNORECASE)
    return max(1, min(200, int(match.group(1)))) if match else 1


def parse_duration_seconds(value: Any) -> int:
    raw = _text(value, 80).lower()
    if not raw:
        return 0
    colon = re.fullmatch(r"(\d{1,3}):(\d{1,2})", raw)
    if colon:
        return min(86400, int(colon.group(1)) * 60 + int(colon.group(2)))
    minutes = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|min|分钟|分)", raw)
    seconds = re.search(r"(\d+(?:\.\d+)?)\s*(?:s|sec|秒)", raw)
    if minutes or seconds:
        total = float(minutes.group(1)) * 60 if minutes else 0
        total += float(seconds.group(1)) if seconds else 0
        return min(86400, max(0, round(total)))
    number = re.search(r"\d+(?:\.\d+)?", raw)
    return min(86400, max(0, round(float(number.group(0))))) if number else 0


def _characters(text: str) -> list[str]:
    names: list[str] = []
    for match in _SPEAKER.finditer(text):
        name = _text(match.group(1), 80).strip()
        if name and name not in _NON_SPEAKERS and name not in names:
            names.append(name)
    return names[:100]


def _episode_titles(script: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for line in script.splitlines():
        match = _EPISODE_HEADING.match(line)
        if match:
            number = _episode_number(match.group(1))
            result[number] = _text(match.group(2), 500) or f"第 {number} 集"
    return result


def _fallback_scenes(script: str) -> list[dict[str, Any]]:
    if not script.strip():
        return []
    scenes: list[dict[str, Any]] = []
    episode = 1
    scene_counts: defaultdict[int, int] = defaultdict(int)
    current_lines: list[str] = []
    current_heading = ""

    def flush() -> None:
        nonlocal current_lines, current_heading
        body = "\n".join(current_lines).strip()
        if not body and not current_heading:
            return
        scene_counts[episode] += 1
        content = _text(" ".join(part for part in (current_heading, body) if part), 6000)
        scenes.append({
            "scene_id": f"E{episode}S{scene_counts[episode]:02d}",
            "duration": "",
            "content": content,
            "characters": _characters(body),
        })
        current_lines = []
        current_heading = ""

    for raw_line in script.splitlines():
        line = raw_line.strip()
        episode_match = _EPISODE_HEADING.match(line)
        if episode_match:
            flush()
            episode = _episode_number(episode_match.group(1))
            continue
        scene_match = _SCENE_HEADING.match(line)
        if scene_match or _INT_EXT_HEADING.match(line):
            flush()
            current_heading = _text(scene_match.group(2) if scene_match else line, 500)
            continue
        if line:
            current_lines.append(line)
    flush()
    if scenes:
        return scenes[:5000]

    titles = _episode_titles(script)
    if titles:
        for number, title in sorted(titles.items()):
            scenes.append({"scene_id": f"E{number}S01", "duration": "", "content": title, "characters": []})
        return scenes
    return [{"scene_id": "E1S01", "duration": "", "content": _text(script, 6000), "characters": _characters(script)}]


def _normalize_scenes(raw_scenes: Any, script: str) -> list[dict[str, Any]]:
    source = raw_scenes if isinstance(raw_scenes, list) and raw_scenes else _fallback_scenes(script)
    result: list[dict[str, Any]] = []
    elapsed = 0
    for index, item in enumerate(source[:5000], start=1):
        if not isinstance(item, dict):
            continue
        scene_id = _text(item.get("scene_id"), 80) or f"E1S{index:02d}"
        duration_label = _text(item.get("duration"), 80)
        duration = parse_duration_seconds(duration_label)
        result.append({
            "scene_id": scene_id,
            "episode_index": _episode_from_scene_id(scene_id),
            "scene_index": index,
            "start_seconds": min(elapsed, _MAX_DASHBOARD_SECONDS),
            "duration_seconds": duration,
            "duration_label": duration_label,
            "content": _text(item.get("content"), 6000),
            "characters": _text_list(item.get("characters"), limit=100, item_limit=80),
            "key_event_index": None,
        })
        elapsed = min(_MAX_DASHBOARD_SECONDS, elapsed + duration)
    return result


def _fallback_events(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not scenes:
        return []
    count = min(8, len(scenes))
    indexes = sorted({round(index * (len(scenes) - 1) / max(count - 1, 1)) for index in range(count)})
    phases = ["故事开始", "进展纠葛", "危机", "高潮", "结局"]
    return [{
        "phase": phases[min(round(position * (len(phases) - 1) / max(len(indexes) - 1, 1)), len(phases) - 1)],
        "title": _text(scenes[scene_index].get("content"), 120) or f"剧情节点 {position + 1}",
        "desc": "",
        "points": [],
    } for position, scene_index in enumerate(indexes)]


def _normalize_events(raw_events: Any, scenes: list[dict[str, Any]]) -> list[WriterDashboardEvent]:
    source = raw_events if isinstance(raw_events, list) and raw_events else _fallback_events(scenes)
    events: list[WriterDashboardEvent] = []
    valid_source = [item for item in source[:500] if isinstance(item, dict)]
    for index, item in enumerate(valid_source):
        scene_index = round(index * (len(scenes) - 1) / max(len(valid_source) - 1, 1)) if scenes else 0
        scene = scenes[scene_index] if scenes else None
        if scene:
            scene["key_event_index"] = index
        events.append(WriterDashboardEvent(
            event_id=f"event-{index + 1:03d}",
            order=index + 1,
            phase=_text(item.get("phase"), 120) or "剧情节点",
            title=_text(item.get("title"), 500) or f"剧情节点 {index + 1}",
            desc=_text(item.get("desc"), 4000),
            points=_text_list(item.get("points"), limit=30, item_limit=500),
            scene_id=scene.get("scene_id") if scene else None,
            start_seconds=scene.get("start_seconds", 0) if scene else 0,
        ))
    return events


def _normalize_relationships(value: Any) -> list[WriterDashboardRelationship]:
    if not isinstance(value, list):
        return []
    result: list[WriterDashboardRelationship] = []
    seen: set[tuple[str, str, str]] = set()
    for item in value[:5000]:
        if not isinstance(item, dict):
            continue
        source = _text(item.get("from") if "from" in item else item.get("from_"), 80)
        target = _text(item.get("to"), 80)
        relation = _text(item.get("relation"), 120) or "剧情关联"
        key = (source, target, relation)
        if not source or not target or source == target or key in seen:
            continue
        seen.add(key)
        result.append(WriterDashboardRelationship(
            from_=source,
            to=target,
            relation=relation,
            bidirectional=item.get("bidirectional") is True,
        ))
    return result


def _infer_relationships_from_scenes(scenes: list[dict[str, Any]]) -> list[WriterDashboardRelationship]:
    """Build a conservative fallback graph from characters who share a scene.

    The relationship compiler deliberately does not invent dramatic intent.  A
    co-occurrence edge only states the observable fact that two named roles
    interact in one or more scenes; richer LLM-authored relationships continue
    to take precedence when they exist.
    """
    pair_counts: dict[tuple[str, str], int] = {}
    character_order: dict[str, int] = {}
    for scene in scenes:
        raw_names = list(dict.fromkeys(
            name for name in scene.get("characters", [])
            if isinstance(name, str) and name.strip()
        ))
        names: list[str] = []
        for name in raw_names:
            if len(names) >= _MAX_INFERRED_CHARACTERS_PER_SCENE:
                break
            if name not in character_order:
                if len(character_order) >= _MAX_INFERRED_CHARACTERS:
                    continue
                character_order[name] = len(character_order)
            names.append(name)
        for source_index, source in enumerate(names):
            for target in names[source_index + 1:]:
                pair = (
                    (source, target)
                    if character_order[source] < character_order[target]
                    else (target, source)
                )
                if pair in pair_counts:
                    pair_counts[pair] += 1
                elif len(pair_counts) < _MAX_INFERRED_RELATIONSHIPS:
                    pair_counts[pair] = 1

    return [
        WriterDashboardRelationship(
            from_=source,
            to=target,
            relation=f"同场互动 · {count} 场",
            bidirectional=True,
        )
        for (source, target), count in pair_counts.items()
    ]


def _normalize_roles(value: Any, scenes: list[dict[str, Any]], relationships: list[WriterDashboardRelationship], script: str) -> list[WriterDashboardRole]:
    roles: dict[str, str] = {}
    if isinstance(value, list):
        for item in value[:500]:
            if isinstance(item, dict):
                name = _text(item.get("name"), 80)
                if name:
                    roles[name] = _text(item.get("position"), 120) or "剧情角色"
    discovered = [name for scene in scenes for name in scene.get("characters", [])]
    discovered.extend(_characters(script))
    for edge in relationships:
        discovered.extend([edge.from_, edge.to])
    for name in discovered:
        roles.setdefault(name, "剧情角色")
    return [WriterDashboardRole(name=name, position=position) for name, position in list(roles.items())[:500]]


def compile_writer_dashboard(task: dict[str, Any]) -> WriterDashboardResponse:
    config = task.get("config") if isinstance(task.get("config"), dict) else {}
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), dict) else {}
    overview_raw = breakdown.get("overview") if isinstance(breakdown.get("overview"), dict) else {}
    script = _script_text(assets.get("2") or config.get("script_content") or "")
    scenes_payload = _normalize_scenes(breakdown.get("scenes"), script)
    relationships = _normalize_relationships(breakdown.get("relationships"))
    if not relationships:
        relationships = _infer_relationships_from_scenes(scenes_payload)
    roles = _normalize_roles(breakdown.get("roles"), scenes_payload, relationships, script)
    timeline = _normalize_events(breakdown.get("timeline"), scenes_payload)
    scenes = [WriterDashboardScene(**item) for item in scenes_payload]

    task_episodes = task.get("episodes") if isinstance(task.get("episodes"), list) else []
    stored_episodes = {
        _bounded_int(item.get("index"), minimum=1): item
        for item in task_episodes
        if isinstance(item, dict) and str(item.get("index", "")).isdigit()
    }
    requested = _bounded_int(config.get("episode_count"))
    episode_indexes = [scene.episode_index for scene in scenes]
    total_episodes = max([
        requested,
        _bounded_int(task.get("total_episodes")),
        *stored_episodes.keys(),
        *episode_indexes,
        1 if script else 0,
    ])
    title_map = _episode_titles(script)
    scenes_by_episode: defaultdict[int, list[WriterDashboardScene]] = defaultdict(list)
    for scene in scenes:
        scenes_by_episode[scene.episode_index].append(scene)
    episodes: list[WriterDashboardEpisode] = []
    for index in range(1, total_episodes + 1):
        stored = stored_episodes.get(index, {})
        episode_scenes = scenes_by_episode[index]
        fallback_title = _text(episode_scenes[0].content, 120) if episode_scenes else f"第 {index} 集"
        status = str(stored.get("status") or "idle")
        episodes.append(WriterDashboardEpisode(
            index=index,
            title=_text(stored.get("title") or title_map.get(index) or fallback_title, 500) or f"第 {index} 集",
            scene_count=len(episode_scenes),
            duration_seconds=min(_MAX_DASHBOARD_SECONDS, sum(scene.duration_seconds for scene in episode_scenes)),
            status=status if status in _ALLOWED_EPISODE_STATUS else "idle",
            video_url=_text(stored.get("video_url"), 4000) or None,
        ))

    overview = WriterOverview(
        synopsis=_text(overview_raw.get("synopsis"), 4000) or _text(script, 500),
        genre=_text(overview_raw.get("genre"), 120),
        theme=_text(overview_raw.get("theme"), 500),
        world_setting=_text(overview_raw.get("world_setting"), 4000),
    )
    state = "READY" if script and scenes and timeline and roles else "INCOMPLETE" if script else "WAITING"
    source_hash = hashlib.sha256(json.dumps(
        {
            "script": script,
            "breakdown": breakdown,
            "script_file_name": _text(config.get("script_name"), 255),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")).hexdigest()
    stats = WriterDashboardStats(
        total_episodes=total_episodes,
        scene_count=len(scenes),
        character_count=len(roles),
        main_event_count=len(timeline),
        relationship_count=len(relationships),
        total_duration_seconds=min(_MAX_DASHBOARD_SECONDS, sum(scene.duration_seconds for scene in scenes)),
        tone=overview.genre or "待分析",
    )
    return WriterDashboardResponse(
        task_id=_text(task.get("task_id"), 120) or "unknown-task",
        source_hash=source_hash,
        title=_text(config.get("title_suggestion"), 500) or "未命名短剧",
        state=state,
        overview=overview,
        stats=stats,
        scenes=scenes,
        timeline=timeline,
        roles=roles,
        relationships=relationships,
        episodes=episodes,
        script=script,
        script_file_name=_text(config.get("script_name"), 255) or None,
    )

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


# The single episode-heading parser for the whole pipeline. Screenplay generation,
# the dashboard's episode count and the "append the missing episodes" repair all
# read the same headings, so a second, weaker copy of this regex would make a
# complete script look truncated and offer a repair that can never succeed.
EPISODE_HEADING = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,3}[ \t]*)?(?:【[ \t]*)?"
    r"第[ \t]*([0-9]{1,3}|[一二三四五六七八九十]{1,4})[ \t]*集"
    r"(?:[ \t]*】)?[ \t]*[:：\-—]?[ \t]*(.*)$",
    re.M,
)
_CN_EPISODE_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                      "六": 6, "七": 7, "八": 8, "九": 9}


def episode_label_number(label: str) -> int:
    """Read 「12」 and 「十二」 alike; 0 when the label cannot be read."""
    if label.isdigit():
        return int(label)
    if label == "十":
        return 10
    if label.startswith("十"):
        return 10 + _CN_EPISODE_DIGITS.get(label[1:2], 0)
    if "十" in label:
        tens, _, ones = label.partition("十")
        return (
            _CN_EPISODE_DIGITS.get(tens, 0) * 10
            + (_CN_EPISODE_DIGITS.get(ones, 0) if ones else 0)
        )
    return _CN_EPISODE_DIGITS.get(label, 0)


def script_episode_indexes(script: str) -> list[int]:
    """Episode numbers present in a screenplay, in order of first appearance."""
    found: list[int] = []
    for match in EPISODE_HEADING.finditer(script or ""):
        number = episode_label_number(match.group(1))
        if 0 < number <= 200 and number not in found:
            found.append(number)
    return found


def script_episode_gaps(script: str, total: int) -> list[int]:
    """Which episode numbers of ``1..total`` the screenplay body is actually missing.

    「已写 15 集 / 共 30 集」只说得出缺几集，说不出缺哪几集 - 用户得自己把 E15S06
    跳到 E25S01 这件事看出来。断层集号是一等结果：看板据此高亮，补写据此重跑。

    A screenplay with no 第N集 heading at all (an uploaded full script) carries no
    gap information; that is an empty list, never "1..total are all missing".
    """
    produced = set(script_episode_indexes(script))
    if not produced:
        return []
    return [index for index in range(1, max(0, total) + 1) if index not in produced]


def split_script_by_episode(script: str) -> dict[int, str]:
    """Slice a screenplay into ``{episode_number: text}`` on its 第N集 headings."""
    matches = list(EPISODE_HEADING.finditer(script or ""))
    episodes: dict[int, str] = {}
    for position, match in enumerate(matches):
        number = episode_label_number(match.group(1))
        if not 0 < number <= 200:
            continue
        end = matches[position + 1].start() if position + 1 < len(matches) else len(script)
        episodes[number] = script[match.start():end].strip()
    return episodes
_SCENE_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:【\s*)?(?:场景|SCENE)\s*([0-9]{0,4})(?:\s*】)?\s*[:：\-—]?\s*(.*)$",
    re.IGNORECASE,
)
_INT_EXT_HEADING = re.compile(r"^\s*(?:INT\.|EXT\.|内景|外景)[：:\s-]", re.IGNORECASE)
_SPEAKER = re.compile(r"(?:^|\n)[ \t]*(?:【)?([一-龥A-Za-z][一-龥A-Za-z· \t]{0,15})(?:】)?[ \t]*[：:]")
_NON_SPEAKERS = {"场景", "时间", "地点", "画面", "动作", "音效", "音乐", "环境音", "旁白", "镜头", "时长", "节奏"}
# Screenplays carry structural labels in the same "标签：内容" shape as dialogue
# ("双轨节奏：…", "情绪钩子：…"), so the speaker pattern reads them as characters
# and they end up as nodes in the relationship graph.  Character names are short
# and never built from these production morphemes.
_LABEL_MORPHEMES = (
    "节奏", "时长", "时间", "地点", "场景", "画面", "动作", "音效", "音乐", "环境",
    "镜头", "旁白", "字幕", "道具", "服装", "化妆", "灯光", "转场", "景别", "特写",
    "情绪", "情节", "情感", "钩子", "主题", "结构", "说明", "备注", "要点", "要求",
    "集数", "台词", "对白", "预估", "输入", "输出", "来源", "风格", "视觉", "规范",
    "冲突", "目标", "假设", "风险", "交付", "标题", "副标", "总结", "提示", "清单",
    "分镜", "机位", "剪辑", "调度", "配乐", "尺度", "合规", "复用", "付费",
)
_MAX_CHARACTER_NAME_CHARS = 8


def is_character_name(value: Any) -> bool:
    """Reject production labels that share the ``名称：内容`` shape with dialogue."""
    name = _text(value, 80)
    if not name or len(name) > _MAX_CHARACTER_NAME_CHARS or name in _NON_SPEAKERS:
        return False
    return not any(morpheme in name for morpheme in _LABEL_MORPHEMES)
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
    """Bounded index for rendering; an unreadable label sorts as episode 1."""
    return max(1, min(200, episode_label_number(value) or 1))


def episode_from_scene_id(scene_id: str) -> int:
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
        if is_character_name(name) and name not in names:
            names.append(name)
    return names[:100]


_METADATA_LINE = re.compile(
    r"^\s*(?:[-*+#>]|\d+[.、)]|[【\[(（])|"
    r"^\s*(?:输入来源|关键假设|假设|未解决风险|风险|交付物|输出|规范|要求|备注|说明|"
    r"场景复用|核心角色|辅助角色|付费墙|平台|受众|题材|时长|集数|版本|作者)\s*[：:]"
)
_SYNOPSIS_HEADING = re.compile(
    r"(?:故事梗概|剧情梗概|核心梗概|核心剧情|故事大纲|一句话梗概|logline)\s*[：:]\s*(.+)",
    re.IGNORECASE,
)


def _script_synopsis(script: str, limit: int = 320) -> str:
    """Best-effort logline for a project whose structured breakdown is missing.

    Slicing the raw file head put the screenplay's own metadata banner - input
    sources, assumptions, hex codes - into the dashboard's story brief.  Prefer a
    declared synopsis line, else the first lines that actually read as prose.
    """
    labelled = _SYNOPSIS_HEADING.search(script)
    if labelled:
        return _text(labelled.group(1), limit)
    prose: list[str] = []
    for line in script.splitlines():
        candidate = _text(line, limit)
        # Prose runs on; a metadata row is short, bulleted or "label: value".
        if not candidate or len(candidate) < 12 or _METADATA_LINE.match(candidate):
            continue
        if EPISODE_HEADING.match(candidate) or _SCENE_HEADING.match(candidate):
            continue
        prose.append(candidate)
        if sum(len(part) for part in prose) >= limit:
            break
    return _text(" ".join(prose), limit)


# A project is created from a chat prompt, so title_suggestion is often the request
# itself ("请帮我生成一个古装权谋短剧") rather than a name. Such a string must never be
# rendered as the drama's title.
_INSTRUCTION_TITLE = re.compile(
    r"(?:^|[\s，。、])(?:请|帮我|帮忙|给我|替我|麻烦你?|我想|我要|需要你?|来一个|来一部)"
    r"|(?:生成|创作|编写|写|做|来)(?:一)?(?:个|部|篇|集|下)"
    r"|(?:剧本|短剧|故事)(?:大纲|梗概)?\s*$"
)
_SCRIPT_TITLE_LABEL = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,3}[ \t]*)?(?:剧名|片名|剧本名|剧本名称|作品名|项目名称|标题)"
    r"[ \t]*[：:][ \t]*(.+?)[ \t]*$",
    re.M,
)
_BOOK_TITLE = re.compile(r"《([^》\n]{1,32})》")


def is_instruction_like(value: str) -> bool:
    """True when the text reads as a request for a drama rather than its name."""
    text = _text(value, 120)
    if not text:
        return False
    return bool(_INSTRUCTION_TITLE.search(text)) or len(text) > 32


def clean_title(value: Any, limit: int = 60) -> str:
    """Strip book-title marks and markdown decoration from a candidate title."""
    return _text(value, limit).strip("《》〈〉“”\"'*＊#【】 ").strip()


def script_title(script: str) -> str:
    """The drama's own name as written in the screenplay, if it states one.

    Prefers an explicit 「剧名：X」 label, then the first 《X》 in the opening lines -
    screenplays almost always open with 《流氓天子》分集剧本 or similar.
    """
    head = "\n".join((script or "").splitlines()[:40])
    labelled = _SCRIPT_TITLE_LABEL.search(head)
    if labelled:
        candidate = clean_title(labelled.group(1))
        if candidate and not is_instruction_like(candidate):
            return candidate
    for match in _BOOK_TITLE.finditer(head):
        candidate = clean_title(match.group(1))
        # 《黄金叙事结构》-style references to guideline documents are not the drama.
        if candidate and not is_instruction_like(candidate) and "结构" not in candidate:
            return candidate
    return ""


def resolve_drama_title(overview_title: Any, script: str, configured: Any) -> str:
    """Pick the best available name: analysed title, then the screenplay, then the prompt."""
    analysed = clean_title(overview_title)
    if analysed and not is_instruction_like(analysed):
        return analysed
    from_script = script_title(script)
    if from_script:
        return from_script
    configured_title = clean_title(configured, 500)
    if configured_title and not is_instruction_like(configured_title):
        return configured_title
    return "未命名短剧"


def _episode_titles(script: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for line in script.splitlines():
        match = EPISODE_HEADING.match(line)
        if match:
            number = _episode_number(match.group(1))
            # A bold heading leaves its closing ** on the title.
            title = _text(match.group(2), 500).strip("*＊ ").strip()
            result[number] = title or f"第 {number} 集"
    return result


def fallback_scenes_from_script(script: str) -> list[dict[str, Any]]:
    """Shot list read straight out of the screenplay text.

    Grounded in what the script actually says: it is the honest stand-in when
    the model-driven structuring of an episode fails, and it never invents an
    episode the screenplay does not contain.
    """
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
        episode_match = EPISODE_HEADING.match(line)
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
    source = raw_scenes if isinstance(raw_scenes, list) and raw_scenes else fallback_scenes_from_script(script)
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
            "episode_index": episode_from_scene_id(scene_id),
            "scene_index": index,
            "start_seconds": min(elapsed, _MAX_DASHBOARD_SECONDS),
            "duration_seconds": duration,
            "duration_label": duration_label,
            "content": _text(item.get("content"), 6000),
            "characters": [
                name for name in _text_list(item.get("characters"), limit=100, item_limit=80)
                if is_character_name(name)
            ],
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
        if not is_character_name(source) or not is_character_name(target):
            continue
        if source == target or key in seen:
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
                if is_character_name(name):
                    roles[name] = _text(item.get("position"), 120) or "剧情角色"
    discovered = [name for scene in scenes for name in scene.get("characters", [])]
    discovered.extend(_characters(script))
    for edge in relationships:
        discovered.extend([edge.from_, edge.to])
    for name in discovered:
        if is_character_name(name):
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
    relationships_inferred = not relationships
    if relationships_inferred:
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
        title=clean_title(overview_raw.get("title")),
        synopsis=_text(overview_raw.get("synopsis"), 4000) or _script_synopsis(script),
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
        scripted_episodes=len(script_episode_indexes(script)) or (1 if script.strip() else 0),
        # 从正文现算，不落库：手动改稿或补写之后陈旧的断层列表会把已经补好的集数
        # 继续标红，而正文永远是唯一权威。
        missing_episodes=script_episode_gaps(script, total_episodes),
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
        title=resolve_drama_title(overview_raw.get("title"), script, config.get("title_suggestion")),
        state=state,
        overview=overview,
        stats=stats,
        scenes=scenes,
        timeline=timeline,
        roles=roles,
        relationships=relationships,
        relationships_inferred=relationships_inferred,
        episodes=episodes,
        script=script,
        script_file_name=_text(config.get("script_name"), 255) or None,
    )

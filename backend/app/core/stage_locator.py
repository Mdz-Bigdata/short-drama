# -*- coding: utf-8 -*-
"""把人说的「第三场」「林夏的办公室」「沈砚说话的那镜」落到任务里的场景号和镜号。

只读任务字典，不碰服务层：场景来自剧本大纲（assets.2_breakdown.scenes）和分镜表（assets.4），镜头来自空间方案或分镜表。
找不到或有歧义时抛 LookupError，消息里列出候选，便于助手直接转述给人。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from app.core import prompt_data


_WORDING_FILE = "stage_locator"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/stage_locator.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

# 与 drama_service 解析分镜表「场景」列用的是同一条正则：场景号在前，名字在后。
SCENE_HEAD = re.compile(r"^(E\d+S\d+)\s*[-—:：]?\s*(.*)$", re.I)
_SCENE_ID = re.compile(r"E\s*(\d+)\s*S\s*(\d+)", re.I)
_NUMBER = _text_of("module.number")
_EPISODE_WORD = re.compile(_text_of("module.episode_word").format(_NUMBER))
_SCENE_WORD = re.compile(_text_of("module.scene_word").format(_NUMBER))
_SHOT_WORD = re.compile(_text_of("module.shot_word").format(_NUMBER))
# 「X 说话的那镜」「X 的那一镜」「X 的镜头」：去掉这些尾巴剩下的就是名字。
_SHOT_TAIL = re.compile(_text_of("module.shot_tail"))
_SPEAKS = _words_of("module.speaks")
MAX_CANDIDATES = 8
ACTION_CHARS = 60

_DIGITS = {_text_of("module.digits"): 0, "〇": 0, _text_of("module.digits.2"): 1, _text_of("module.digits.3"): 2, _text_of("module.digits.4"): 2, _text_of("module.digits.5"): 3, _text_of("module.digits.6"): 4, _text_of("module.digits.7"): 5, _text_of("module.digits.8"): 6, _text_of("module.digits.9"): 7, _text_of("module.digits.10"): 8, _text_of("module.digits.11"): 9}


def parse_number(token: str) -> int | None:
    """阿拉伯数字或一百以内的中文数字（一、十二、二十三、一百）；读不出返回 None。"""
    text = str(token or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if any(char not in _DIGITS and char not in _text_of("parse_number.text") for char in text):
        return None
    total, current = 0, 0
    for char in text:
        if char == _text_of("parse_number.text.2"):
            total += (current or 1) * 100
            current = 0
        elif char == _text_of("parse_number.text.3"):
            total += (current or 1) * 10
            current = 0
        else:
            current = _DIGITS[char]
    return total + current


def split_scene_id(scene_id: str) -> tuple[int, int] | None:
    match = _SCENE_ID.search(str(scene_id or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def _scene_name(raw: Any) -> str:
    """分镜表「场景」列里的名字：去掉前面的场景号。"""
    text = str(raw or "").strip()
    match = SCENE_HEAD.match(text)
    return (match.group(2).strip() if match else text)


def _names(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    names: list[str] = []
    for item in value:
        name = str(item or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def scenes_of(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    """任务里的每一场：场景号、集、序号、名字、人物和它的镜头，按集和场排序。"""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), Mapping) else {}
    scenes: dict[str, dict[str, Any]] = {}

    def entry(scene_id: str) -> dict[str, Any]:
        found = scenes.get(scene_id)
        if found is None:
            episode, number = split_scene_id(scene_id) or (0, 0)
            found = scenes[scene_id] = {
                "scene_id": scene_id, "episode": episode, "number": number, "name": "", "characters": [], "shots": [],
            }
        return found

    for scene in breakdown.get("scenes") or []:
        if not isinstance(scene, Mapping):
            continue
        scene_id = str(scene.get("scene_id") or "").strip()
        if not scene_id:
            continue
        record = entry(scene_id)
        record["characters"] = _names(scene.get("characters"))
        # 分场表(screenwriting.renderer.scene_breakdown_entry)把地点 / 时间标签存在 label 里；name / location / title 是别处写的。
        record["name"] = str(scene.get("label") or scene.get("name") or scene.get("location") or scene.get("title") or "").strip()
    for shot in assets.get("4") if isinstance(assets.get("4"), list) else []:
        if not isinstance(shot, Mapping):
            continue
        scene_id = str(shot.get("scene_id") or "").strip()
        if not scene_id:
            head = SCENE_HEAD.match(str(shot.get("scene") or "").strip())
            scene_id = head.group(1).upper() if head else ""
        if not scene_id:
            continue
        record = entry(scene_id)
        name = _scene_name(shot.get("scene"))
        if name and name.upper() != scene_id.upper():
            record["name"] = record["name"] or name
        subjects = _names(shot.get("characters"))
        for subject in subjects:
            if subject not in record["characters"]:
                record["characters"].append(subject)
        try:
            shot_id = int(shot.get("shot_id") or 0)
        except (TypeError, ValueError):
            shot_id = 0
        record["shots"].append({"shot_id": shot_id, "subjects": subjects, "action": str(shot.get("desc") or "")[:ACTION_CHARS]})
    for record in scenes.values():
        record["shots"].sort(key=lambda item: item["shot_id"])
    return sorted(scenes.values(), key=lambda item: (item["episode"], item["number"], item["scene_id"]))


def scene_label(task: Mapping[str, Any], scene_id: str) -> str:
    """「E1S02 林夏的办公室」；没有名字时只有场景号。"""
    wanted = str(scene_id or "").strip()
    for scene in scenes_of(task):
        if scene["scene_id"] == wanted:
            return f"{scene['scene_id']} {scene['name']}".strip()
    return wanted


def _candidates(scenes: Sequence[Mapping[str, Any]]) -> str:
    shown = [f"{scene['scene_id']} {scene['name']}".strip() for scene in scenes[:MAX_CANDIDATES]]
    more = "…" if len(scenes) > MAX_CANDIDATES else ""
    return "（" + "、".join(shown) + more + "）" if shown else ""


def _by_number(scenes: Sequence[Mapping[str, Any]], episode: int, number: int) -> Mapping[str, Any] | None:
    return next((scene for scene in scenes if scene["episode"] == episode and scene["number"] == number), None)


def _name_matches(name: str, asked: str) -> bool:
    """场名与说法互为片段就算对上；分场表的标签是「地点 / 时间」，地点那半截单独也算（「办公室那场」对得上「办公室 / 日」）。"""
    heads = {name, name.split("/")[0].strip()}
    return any(head and (asked in head or head in asked) for head in heads)


def resolve_scene_id(task: Mapping[str, Any], text: str, *, default_episode: int | None = None) -> str:
    """场景号、「第三场」（可带「第一集」）、唯一的场景名片段，或只出现在一场里的人物名 → 场景号。"""
    asked = str(text or "").strip()
    scenes = scenes_of(task)
    if not asked:
        raise LookupError(_text_of("resolve_scene_id.text") + _candidates(scenes))
    match = _SCENE_ID.search(asked)
    if match:
        episode, number = int(match.group(1)), int(match.group(2))
        found = _by_number(scenes, episode, number)
        if found is not None:
            return found["scene_id"]
        if not scenes:
            return f"E{episode}S{number:02d}"
        raise LookupError(_text_of("resolve_scene_id.text.2").format(episode, number) + _candidates(scenes))
    scene_word = _SCENE_WORD.search(asked)
    if scene_word:
        number = parse_number(scene_word.group(1))
        episode_word = _EPISODE_WORD.search(asked)
        episode = parse_number(episode_word.group(1)) if episode_word else None
        if episode is None:
            episode = default_episode
        if episode is None:
            episodes = sorted({scene["episode"] for scene in scenes})
            if len(episodes) == 1:
                episode = episodes[0]
            else:
                raise LookupError(_text_of("resolve_scene_id.text.3").format(len(episodes), number) + _candidates(scenes))
        if number is None:
            raise LookupError(_text_of("resolve_scene_id.text.4") + _candidates(scenes))
        found = _by_number(scenes, int(episode), number)
        if found is None:
            raise LookupError(_text_of("resolve_scene_id.text.5").format(episode, number) + _candidates([scene for scene in scenes if scene["episode"] == episode] or scenes))
        return found["scene_id"]
    by_name = [scene for scene in scenes if _name_matches(scene["name"], asked)]
    if len(by_name) == 1:
        return by_name[0]["scene_id"]
    if len(by_name) > 1:
        raise LookupError(_text_of("resolve_scene_id.text.6").format(asked, len(by_name)) + _candidates(by_name))
    by_cast = [scene for scene in scenes if any(name == asked or name in asked for name in scene["characters"])]
    if len(by_cast) == 1:
        return by_cast[0]["scene_id"]
    if len(by_cast) > 1:
        raise LookupError(_text_of("resolve_scene_id.text.7").format(asked, len(by_cast)) + _candidates(by_cast))
    raise LookupError(_text_of("resolve_scene_id.text.8").format(asked) + _candidates(scenes))


def _field(shot: Any, *keys: str) -> Any:
    for key in keys:
        value = shot.get(key) if isinstance(shot, Mapping) else getattr(shot, key, None)
        if value not in (None, "", []):
            return value
    return None


def _shot_row(shot: Any) -> dict[str, Any]:
    try:
        shot_id = int(_field(shot, "shot_id") or 0)
    except (TypeError, ValueError):
        shot_id = 0
    return {
        "shot_id": shot_id, "subjects": _names(_field(shot, "subjects", "characters")),
        "speaker": str(_field(shot, "speaker") or "").strip(), "action": str(_field(shot, "action", "desc") or "")[:ACTION_CHARS],
    }


def _shot_candidates(rows: Sequence[Mapping[str, Any]]) -> str:
    shown = [_text_of("_shot_candidates.shown").format(row['shot_id'], '、'.join(row['subjects']) or row['action'][:20]).strip() for row in rows[:MAX_CANDIDATES]]
    more = "…" if len(rows) > MAX_CANDIDATES else ""
    return "（" + "、".join(shown) + more + "）" if shown else ""


def resolve_shot_id(shots: Sequence[Any], text: str) -> int:
    """「第2镜」「2」「#2」，或「X的那一镜」「X说话的那镜」（X 只在一镜的 subjects 或 speaker 里）→ 镜号。"""
    asked = str(text or "").strip()
    rows = [_shot_row(shot) for shot in shots]
    if not asked:
        raise LookupError(_text_of("resolve_shot_id.text") + _shot_candidates(rows))
    match = _SHOT_WORD.search(asked)
    if match:
        number = parse_number(next(group for group in match.groups() if group))
        if number is not None:
            if not rows or any(row["shot_id"] == number for row in rows):
                return number
            raise LookupError(_text_of("resolve_shot_id.text.2").format(number) + _shot_candidates(rows))
    speaking = any(word in asked for word in _SPEAKS)
    subject = _SHOT_TAIL.sub("", asked).strip()
    for word in _SPEAKS:
        subject = subject.replace(word, "").strip()
    subject = subject.rstrip(_text_of("resolve_shot_id.subject")).strip()
    known = {name for row in rows for name in [*row["subjects"], row["speaker"]] if name}
    named = [name for name in known if name == subject or (name and name in asked)]
    if not named:
        raise LookupError(_text_of("resolve_shot_id.text.3").format(asked) + _shot_candidates(rows))

    def mentions(row: Mapping[str, Any]) -> bool:
        if speaking:
            return row["speaker"] in named
        return any(name in row["subjects"] or name == row["speaker"] for name in named)

    hits = [row for row in rows if mentions(row)]
    if not hits and speaking:
        hits = [row for row in rows if any(name in row["subjects"] for name in named)]
    if len(hits) == 1:
        return hits[0]["shot_id"]
    if not hits:
        raise LookupError(_text_of("resolve_shot_id.text.4").format('、'.join(named)) + _shot_candidates(rows))
    raise LookupError(_text_of("resolve_shot_id.text.5").format('、'.join(named), len(hits)) + _shot_candidates(hits))


__all__ = [
    "ACTION_CHARS", "MAX_CANDIDATES", "SCENE_HEAD", "parse_number", "resolve_scene_id", "resolve_shot_id", "scene_label", "scenes_of",
    "split_scene_id",
]

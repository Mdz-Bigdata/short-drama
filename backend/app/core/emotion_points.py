# -*- coding: utf-8 -*-
"""情绪点：一集戏靠哪几种"一下"抓住人。

类型表是数据（``app/data/prompt/emotion_points.json``）：钩子、冲突、反转、爽点、暖点、泪点、笑点、
揭秘、悬念、抒情、信息交代。分集大纲的每个故事节点以「【类型】」开头，分镜内容的每一格填
``emotion_point``；编剧的方法论、分镜师拿到的场次上下文都从这里读同一张表，写的人和查的人
用的是同一套词。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.core import prompt_data

_DATA = "emotion_points"
KINDS: tuple[str, ...] = tuple(kind for kind, _ in prompt_data.pairs(_DATA, "kinds"))
DEFINITIONS: dict[str, str] = dict(prompt_data.pairs(_DATA, "kinds"))
# 只交代信息的节点不算"命中了情绪点"：一集全是信息交代就是没有戏。
INFORMATIONAL: frozenset[str] = frozenset(prompt_data.words(_DATA, "informational"))
_BEAT_TAG = prompt_data.text(_DATA, "beat_tag")
_TAG_HEAD = re.compile(r"^\s*[【\[]\s*([^】\]]{1,8})\s*[】\]]")


def names() -> str:
    """类型名顿号相连：钩子、冲突、反转……"""
    return "、".join(KINDS)


def menu() -> str:
    """类型名带一句定义，给写的人看。"""
    return "；".join(f"{kind}（{DEFINITIONS[kind]}）" for kind in KINDS)


def tag(kind: str) -> str:
    return _BEAT_TAG.format(kind=kind)


def normalize(value: Any) -> str:
    """字段值归到类型名：去空白、去括号；认不出的原样返回（由校验报出来）。"""
    text = re.sub(r"\s+", "", str(value or ""))
    text = text.strip("【】[]（）()")
    return text


def beat_kind(beat: Any) -> str:
    """故事节点开头的「【类型】」里写的是什么；没写返回空串。"""
    match = _TAG_HEAD.match(str(beat or ""))
    return normalize(match.group(1)) if match else ""


def is_kind(value: Any) -> bool:
    return normalize(value) in KINDS


def hits(kinds: Iterable[Any]) -> list[str]:
    """命中的类型去重、按表的顺序排；信息交代不算。"""
    seen = {normalize(kind) for kind in kinds}
    return [kind for kind in KINDS if kind in seen and kind not in INFORMATIONAL]


def beat_problems(beats: Sequence[Any], *, label: str = "") -> list[str]:
    """分集大纲里写了表外类型的故事节点：每条一句，退回去改。没标类型的不退——提示词已经要求了，
    为一个标签再花一次大纲调用不值。"""
    unknown = [str(beat) for beat in beats if beat_kind(beat) and beat_kind(beat) not in KINDS]
    head = f"{label}：" if label else ""
    return [f"{head}这些节点的情绪点类型不在表里（只能是 {names()}）：" + "；".join(unknown[:3])] if unknown else []


def untagged_beats(beats: Sequence[Any]) -> list[str]:
    """没有以「【类型】」开头的故事节点。"""
    return [str(beat) for beat in beats if not beat_kind(beat)]


def plan_problems(scenes: Sequence[Mapping[str, Any]], *, label: str = "") -> list[str]:
    """分镜内容里 ``emotion_point`` 写了表外的类型：退回去改。"""
    shots = [scene for scene in scenes if isinstance(scene, Mapping)]
    head = f"{label}：" if label else ""
    unknown = [
        f"{scene.get('scene_id') or '?'}「{scene.get('emotion_point')}」"
        for scene in shots if str(scene.get("emotion_point") or "").strip() and not is_kind(scene.get("emotion_point"))
    ]
    return [f"{head}emotion_point 只能是 {names()}（纯转场 / 空镜可留空），这些分镜写了别的：" + "、".join(unknown[:5])] if unknown else []


def episode_without_point(scenes: Sequence[Mapping[str, Any]]) -> str | None:
    """整集没有一格命中情绪点时的提醒（信息交代不算），有就返回一句话；留给人看，不退回模型。"""
    shots = [scene for scene in scenes if isinstance(scene, Mapping)]
    if not shots or hits(scene.get("emotion_point") for scene in shots):
        return None
    return (
        f"整集没有一格命中情绪点（{'、'.join(k for k in KINDS if k not in INFORMATIONAL)}）："
        "每一格在 emotion_point 里写明它是哪一种，一集至少要有一格不是信息交代"
    )


def scene_note(value: Any) -> str:
    """给分镜师看的一行：这一格要打到哪种情绪点上。"""
    kind = normalize(value)
    return f"本场情绪点：{kind}——{DEFINITIONS[kind]}" if kind in KINDS else ""


__all__ = [
    "DEFINITIONS", "INFORMATIONAL", "KINDS", "beat_kind", "beat_problems", "episode_without_point", "hits", "is_kind", "menu",
    "names", "normalize", "plan_problems", "scene_note", "tag", "untagged_beats",
]

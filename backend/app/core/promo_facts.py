# -*- coding: utf-8 -*-
"""宣发阶段的事实底稿与输出解析。

宣发 Agent 以前只看到第 1 阶段的导演大纲，于是总把「成片尚未产出」「总集数待补」写进方案，
还按假设的 60 集排期。这里把已经定下来的事实——几集、每集标题与成片时长、正片里真实说出口的台词——
压成一小段底稿交给它；再约定它在末尾用两个固定标签给出主推标题与引流文案，解析时先认这两个标签。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.core import edit_timeline, episode_cycle

TITLE_LABEL = "【封面大字标题】"
BODY_LABEL = "【黄金引流文案】"

#: 交给宣发 Agent 的输出约定：放在用户提示词末尾。
OUTPUT_CONTRACT = (
    "方案正文写完后，最后单独输出两行，供系统直接上线使用，不要加引号、编号或 Markdown：\n"
    f"{TITLE_LABEL}一句 4–14 字的主推封面标题\n"
    f"{BODY_LABEL}一段 30–80 字的主推引流文案，只用正片里真实发生的情节和台词"
)

LINES_PER_EPISODE = 4
MAX_LINE_CHARS = 40

_EPISODE_PREFIX = re.compile(r"^第\s*\d+\s*集\s*")


def _screenplay_episodes(task: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    screenplay = assets.get("2_screenwriting") if isinstance(assets.get("2_screenwriting"), Mapping) else {}
    episodes = screenplay.get("episodes")
    if isinstance(episodes, Mapping):
        episodes = list(episodes.values())
    return [e for e in episodes or [] if isinstance(e, Mapping)]


def _dialogue(plan: Mapping[str, Any]) -> list[str]:
    lines = []
    for scene in plan.get("scenes") or []:
        for utterance in (scene.get("utterances") or []) if isinstance(scene, Mapping) else []:
            if not isinstance(utterance, Mapping) or utterance.get("kind") != "dialogue":
                continue
            text = str(utterance.get("text") or "").strip()
            line = f"{utterance.get('speaker') or '旁白'}：「{text[:MAX_LINE_CHARS]}」"
            if text and line not in lines:
                lines.append(line)
    return lines


def production_facts(task: Mapping[str, Any]) -> str:
    """已定的制作事实：集数、每集标题 / 成片时长 / 几句真实台词。没有剧本时为空串。"""
    episodes = _screenplay_episodes(task)
    if not episodes:
        return ""
    rows, films = [], 0
    for index, episode in enumerate(episodes, start=1):
        number = int(episode.get("episode") or index)
        plan = episode.get("plan") if isinstance(episode.get("plan"), Mapping) else {}
        title = _EPISODE_PREFIX.sub("", str(plan.get("title") or "")).strip() or "未命名"
        if episode_cycle.film_of(task, number):
            films += 1
            timeline = episode_cycle.record(task, number).get("timeline")
            seconds = edit_timeline.summary(timeline).get("seconds") if isinstance(timeline, Mapping) else None
            state = f"成片已合成，{seconds:.0f} 秒" if seconds else "成片已合成"
        else:
            state = "成片未合成"
        rows.append(f"- 第{number}集「{title}」：{state}")
        rows.extend(f"  · {line}" for line in _dialogue(plan)[:LINES_PER_EPISODE])
    head = f"本剧已写定 {len(episodes)} 集，其中 {films} 集成片已合成。以下为正片事实，宣传主张只能从这里取："
    return head + "\n" + "\n".join(rows)


_WRAPPERS = {"「": "」", "“": "”", "‘": "’", '"': '"', "'": "'", "《": "》"}


def _unwrap(value: str) -> str:
    """去掉整行外层的一对引号；行首的引号若属于正文里的台词（后面还有对应的收引号）则保留。"""
    value = value.strip(" \t*>")
    closer = _WRAPPERS.get(value[:1])
    if closer and len(value) > 1 and value.endswith(closer) and closer not in value[1:-1]:
        value = value[1:-1].strip()
    return value


def _after_label(text: str, label: str) -> str:
    """标签后同一行的文字；取最后一次出现，避开正文里引用到的同名标签。"""
    matches = re.findall(re.escape(label) + r"[ \t：:]*([^\n【]+)", text)
    return _unwrap(matches[-1]) if matches else ""


def labelled_pick(text: str) -> tuple[str, str]:
    """按输出约定取主推标题与引流文案；模型没守约时对应项为空串。"""
    if not text:
        return "", ""
    return _after_label(text, TITLE_LABEL), _after_label(text, BODY_LABEL)


__all__ = ["BODY_LABEL", "OUTPUT_CONTRACT", "TITLE_LABEL", "labelled_pick", "production_facts"]

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
from app.core import prompt_data


_WORDING_FILE = "promo_facts"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/promo_facts.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

TITLE_LABEL = _text_of("module.title_label")
BODY_LABEL = _text_of("module.body_label")

#: 交给宣发 Agent 的输出约定：放在用户提示词末尾。
OUTPUT_CONTRACT = (
    _text_of("module.output_contract").format(TITLE_LABEL, BODY_LABEL)
)

LINES_PER_EPISODE = 4
MAX_LINE_CHARS = 40

_EPISODE_PREFIX = re.compile(_text_of("module.episode_prefix"))


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
            line = f"{utterance.get('speaker') or _text_of('_dialogue.line')}：「{text[:MAX_LINE_CHARS]}」"
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
        title = _EPISODE_PREFIX.sub("", str(plan.get("title") or "")).strip() or _text_of("production_facts.title")
        if episode_cycle.film_of(task, number):
            films += 1
            timeline = episode_cycle.record(task, number).get("timeline")
            seconds = edit_timeline.summary(timeline).get("seconds") if isinstance(timeline, Mapping) else None
            state = _text_of("production_facts.state").format(seconds) if seconds else _text_of("production_facts.state.2")
        else:
            state = _text_of("production_facts.state.3")
        rows.append(_text_of("production_facts.text").format(number, title, state))
        rows.extend(f"  · {line}" for line in _dialogue(plan)[:LINES_PER_EPISODE])
    head = _text_of("production_facts.head").format(len(episodes), films)
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

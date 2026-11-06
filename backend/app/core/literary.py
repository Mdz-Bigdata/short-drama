# -*- coding: utf-8 -*-
"""立意与题眼台词：让剧本有一个被考验的判断，和每集一句挣来的金句。

词表在 ``app/data/prompt/literary.json``。总导演策划写一张立意卡（立意句 / 母题物件 / 终局意象 /
说理方式），项目概述把它接下来（``thesis`` / ``motif`` / ``ending_image``）；分集大纲要求每集的反转考验
立意一次、母题按三次变义排进节点；分镜内容每集最多一句题眼台词（``key_line``，逐字等于该格的一句
口播），只能压在反转 / 揭秘 / 抒情这类情绪点的格子上，从说话人的行当里说理、答非所问、不用抽象名词；
小说体正文在母题和题眼之后留白、结尾落在物上。写的人（提示词）和查的人（校验器、分镜师上下文）
用同一张表。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.core import prompt_data

_DATA = "literary"
OVERVIEW_FIELDS: tuple[tuple[str, str], ...] = prompt_data.pairs(_DATA, "overview_fields")
OVERVIEW_LABELS: dict[str, str] = dict(prompt_data.pairs(_DATA, "overview_labels"))
KEY_LINE_POINTS: tuple[str, ...] = prompt_data.words(_DATA, "key_line_points")
KEY_LINE_MAX_CHARS: int = prompt_data.number(_DATA, "key_line_max_chars")
ABSTRACT_WORDS: tuple[str, ...] = prompt_data.words(_DATA, "abstract_words")


def _points() -> str:
    return " / ".join(KEY_LINE_POINTS)


def thesis_card() -> str:
    """总导演策划里要单列的那一节。"""
    return prompt_data.text(_DATA, "thesis_card")


def overview_ask() -> str:
    """提炼项目概述时，立意三项怎么填。"""
    return prompt_data.text(_DATA, "overview_ask")


def overview_lines(overview: Mapping[str, Any] | None) -> list[str]:
    """项目概述里填了的立意项，一项一行「立意：…」；没填的不写。"""
    overview = overview or {}
    return [f"{OVERVIEW_LABELS[key]}：{str(overview.get(key) or '').strip()}" for key, _ in OVERVIEW_FIELDS if str(overview.get(key) or "").strip()]


def outline_rule() -> str:
    """分集大纲的规划规则：立意被考验、母题三次变义。"""
    return prompt_data.text(_DATA, "outline_rule")


def key_line_rule(*, authored: bool) -> str:
    """分镜内容 ``key_line`` 字段怎么填；``authored`` 是创作模式，才讲怎么写（改编 / 提取的台词是原文的）。"""
    rule = prompt_data.text(_DATA, "key_line_field").format(points=_points())
    if authored:
        craft = prompt_data.text(_DATA, "key_line_craft").format(max_chars=KEY_LINE_MAX_CHARS, abstract="、".join(ABSTRACT_WORDS))
        rule = f"{rule} {craft}"
    return rule


STIFF_WORDS: tuple[str, ...] = prompt_data.words(_DATA, "stiff_words")


def dialogue_rule() -> str:
    """创作模式里每句台词怎么写：潜台词先行、身份焊在嘴上、不问答、不独白、不念稿、高光句式。"""
    stiff = "「" + "」「".join(STIFF_WORDS) + "」"
    return prompt_data.text(_DATA, "dialogue_head") + " ".join(rule.format(stiff=stiff) for rule in prompt_data.words(_DATA, "dialogue_craft"))


def hook_rule() -> str:
    """分集大纲里钩子怎么留：四个信息位只空一个，下一集开头就兑。"""
    return prompt_data.text(_DATA, "hook_rule")


def stiff_hits(text: Any) -> list[str]:
    """这句里的念稿词，按表的顺序。"""
    cleaned = _clean(text)
    return [word for word in STIFF_WORDS if word in cleaned]


def voice_print_rule() -> str:
    """角色 voice_style 还要写什么。"""
    return prompt_data.text(_DATA, "voice_print_rule")


def methodology() -> str:
    """编剧方法论里的一句。"""
    return prompt_data.text(_DATA, "methodology")


def prose_rules() -> tuple[str, ...]:
    """小说体正文的写作要求：母题留白、结尾落在物上。"""
    return prompt_data.words(_DATA, "prose_rules")


def _clean(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def abstract_hits(text: Any) -> list[str]:
    """这句里出现的抽象名词，按表的顺序。"""
    cleaned = _clean(text)
    return [word for word in ABSTRACT_WORDS if word in cleaned]


def key_line_of(scene: Mapping[str, Any]) -> str:
    return str(scene.get("key_line") or "").strip()


def plan_problems(scenes: Sequence[Mapping[str, Any]], *, label: str = "", authored: bool = True) -> list[str]:
    """分镜内容里题眼台词写错的地方：退回去改。

    任何模式都查：题眼必须逐字等于该格的一句口播、一集最多一句、只能压在表里的情绪点上。
    只有创作模式（``authored``）才查写法：长度和抽象名词——改编 / 提取的台词是原文的，不能为它改字。
    """
    from app.core import emotion_points

    head = f"{label}：" if label else ""
    problems: list[str] = []
    marked: list[str] = []
    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        line = key_line_of(scene)
        if not line:
            continue
        scene_id = str(scene.get("scene_id") or "?")
        marked.append(scene_id)
        spoken = [_clean(item.get("text")) for item in (scene.get("utterances") or []) if isinstance(item, Mapping)]
        if _clean(line) not in spoken:
            problems.append(f"{head}{scene_id} 的 key_line 不是这一格 utterances 里的任何一句 text（必须逐字相同）")
        point = emotion_points.normalize(scene.get("emotion_point"))
        if point not in KEY_LINE_POINTS:
            problems.append(f"{head}{scene_id} 的题眼台词压在「{point or '空'}」上，题眼只能放在{_points()}的分镜")
        if authored:
            if len(_clean(line)) > KEY_LINE_MAX_CHARS:
                problems.append(f"{head}{scene_id} 的题眼台词超过 {KEY_LINE_MAX_CHARS} 个字，题眼要短到能复述")
            hits = abstract_hits(line)
            if hits:
                problems.append(f"{head}{scene_id} 的题眼台词用了抽象名词（{'、'.join(hits)}），改成从说话人的行当里说理")
    if len(marked) > 1:
        problems.append(f"{head}一集只能有一句题眼台词，这些分镜都写了 key_line：{'、'.join(marked[:5])}，只留最重的那一句")
    return problems


def _is_question(text: str) -> bool:
    return _clean(text).rstrip("」”\"').）)").endswith(("？", "?"))


def dialogue_warnings(scenes: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """创作的台词里机器查得出的毛病，每条 ``(code, message, scene_id)``：留给人看，不退回模型。

    问答式对白：一格里连着「问—答—问—答」（``qa_pairs`` 对，问句由另一人接）。长话：一句口播超过
    ``long_line_chars`` 个字。念稿：台词里有 ``stiff_words`` 表上的书面语。改编 / 提取的台词是原文的，调用方不对它们查。
    """
    data = prompt_data.load(_DATA)
    pairs_needed, long_chars = int(data["qa_pairs"]), int(data["long_line_chars"])
    found: list[tuple[str, str, str]] = []
    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        scene_id = str(scene.get("scene_id") or "?")
        spoken = [item for item in (scene.get("utterances") or []) if isinstance(item, Mapping) and item.get("kind") == "dialogue"]
        longest = max((len(_clean(item.get("text"))) for item in spoken), default=0)
        if longest > long_chars:
            found.append(("long_line", str(data["long_line"]).format(scene_id=scene_id, chars=longest), scene_id))
        stiff = [word for item in spoken for word in stiff_hits(item.get("text"))]
        if stiff:
            found.append(("stiff_line", str(data["stiff_line"]).format(scene_id=scene_id, words="、".join(dict.fromkeys(stiff))), scene_id))
        run = 0
        for asked, answered in zip(spoken, spoken[1:]):
            if _is_question(str(asked.get("text") or "")) and asked.get("speaker") != answered.get("speaker") and not _is_question(str(answered.get("text") or "")):
                run += 1
                if run >= pairs_needed:
                    found.append(("qa_dialogue", str(data["qa_dialogue"]).format(scene_id=scene_id, pairs=pairs_needed), scene_id))
                    break
            elif not _is_question(str(asked.get("text") or "")):
                # 一个答句接着下一个问句是同一串；两个非问句相连才算断了。
                run = 0 if not _is_question(str(answered.get("text") or "")) else run
    return found


def episode_without_key_line(scenes: Sequence[Mapping[str, Any]]) -> str | None:
    """整集没有题眼台词时的提醒，有就返回一句话；留给人看，不退回模型。没有口播的集不提醒。"""
    shots = [scene for scene in scenes if isinstance(scene, Mapping)]
    spoken = any(scene.get("utterances") for scene in shots)
    if not spoken or any(key_line_of(scene) for scene in shots):
        return None
    return prompt_data.text(_DATA, "no_key_line").format(points=_points())


def clip_note(line: Any) -> str:
    """给视频模型的一句台词表达：题眼说完停一拍，镜头留在脸上。"""
    text = str(line or "").strip()
    return prompt_data.text(_DATA, "clip_note").format(line=text) if text else ""


def scene_note(line: Any) -> str:
    """给分镜师看的一行：这一格有题眼台词，画面给它留停留。"""
    text = str(line or "").strip()
    return prompt_data.text(_DATA, "scene_note").format(line=text) if text else ""


__all__ = [
    "ABSTRACT_WORDS", "KEY_LINE_MAX_CHARS", "KEY_LINE_POINTS", "OVERVIEW_FIELDS", "OVERVIEW_LABELS", "STIFF_WORDS", "abstract_hits", "clip_note",
    "dialogue_rule", "dialogue_warnings", "episode_without_key_line", "hook_rule", "key_line_of", "key_line_rule", "methodology", "outline_rule",
    "overview_ask", "overview_lines", "plan_problems", "prose_rules", "scene_note", "stiff_hits", "thesis_card", "voice_print_rule",
]

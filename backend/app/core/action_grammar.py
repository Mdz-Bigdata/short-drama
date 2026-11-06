# -*- coding: utf-8 -*-
"""动作怎么写才接得上、拍得稳。

两条规矩，来自实际出片的经验：

* **延续动作**：后一段先接住上一段的结尾，再写清下一步。只写「接着往下演」模型不知道从哪接；
  把上一段的结束状态原样写在本段开头，模型才有东西接。
* **复杂动作拆四步**：起始姿态 → 主动作 → 身体联动 → 结束姿态。一句「转身拔刀劈下」模型会漏掉
  重心和手脚；拆开写，成片更稳，下一段也有明确的结束姿态可接。

本模块只做文本：不调模型。
"""

from __future__ import annotations

import re

ACTION_PARTS = ("起始姿态", "主动作", "身体联动", "结束姿态")
ENDING_MAX_CHARS = 160
# 「上一段结尾：」说的是上一段，不是这段自己的结尾。
_LABELLED_ENDING = re.compile(r"(?<!上一段)(?:落幅|结束姿态|结尾|收势)[：:]\s*([^\n]+)")
_SENTENCE = re.compile(r"[^。！？!?\n；;]+[。！？!?；;]?")
_LABEL_PREFIX = re.compile(r"^【[^】]*】|^[A-Za-z_]+[：:]|^接下来[：:]")
#: 表格没写内容时填的占位话：说不出任何姿势，模型接不住。
GENERIC_ENDINGS = frozenset({
    "形成下一格可承接的可见状态", "人物姿态、视线与道具停在下一镜可以直接承接的状态", "锁定人物朝向、道具归属、情绪强度、光向与色温",
})

STRUCTURE_RULE = (
    "复杂动作按「起始姿态→主动作→身体联动→结束姿态」四步写：先写动作开始前的身体姿势和重心，"
    "再写主动作本身，再写手、脚、躯干、视线怎么跟着动，最后写动作停下来时的姿势；结束姿态要写得能被下一段直接接住。"
)
CONTINUATION_RULE = "延续动作时先接住上一段的结尾——把上一段的结束状态原样写在开头——再写清下一步，不要只写「接着往下演」。"

BREAKDOWN_SYSTEM = "你是动作指导。把一句笼统的动作描写拆成视频模型能稳定生成的四步。只输出这四行，不要解释。"
BREAKDOWN_PROMPT = (
    "按这四行输出，每行一个标签加冒号：\n起始姿态：动作开始前的身体姿势、重心、面向\n主动作：这一下到底做了什么，谁对谁，用了哪只手哪条腿\n"
    "身体联动：手、脚、躯干、头和视线怎么跟着动，重心怎么移\n结束姿态：动作停下来时的姿势，要具体到能当下一段的开场\n\n"
    "只写看得见的身体动作，不写心理、不写镜头术语；一行一句，总共不超过 200 字。{context}\n\n动作：{action}"
)


def ending_of(text: str, limit: int = ENDING_MAX_CHARS) -> str:
    """一段提示词的结尾状态：标了「落幅 / 结束姿态」的那句优先，否则最后一句。"""
    body = str(text or "").strip()
    if not body:
        return ""
    labelled = _LABELLED_ENDING.findall(body)
    if labelled:
        return _trim(labelled[-1], limit)
    sentences = [part.strip() for part in _SENTENCE.findall(body) if part.strip()]
    if not sentences:
        return _trim(body, limit)
    last = _LABEL_PREFIX.sub("", sentences[-1]).strip()
    # 最后一句太短(「完。」)说不清状态时带上前一句。
    if len(last) < 6 and len(sentences) > 1:
        last = _LABEL_PREFIX.sub("", sentences[-2]).strip() + last
    return _trim(last, limit)


def concrete_ending(text: str, limit: int = ENDING_MAX_CHARS) -> str:
    """同 ``ending_of``，但占位话算没写。"""
    ending = ending_of(text, limit)
    return "" if ending.rstrip("。") in GENERIC_ENDINGS else ending


def _trim(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip("，、；;") + "…"


def continuation_text(previous_ending: str, next_action: str) -> str:
    """后一段的正文：先接住上一段的结尾，再写下一步。没有上一段结尾时原样返回。"""
    ending = ending_of(previous_ending)
    action = str(next_action or "").strip()
    if not ending:
        return action
    return f"接住上一段结尾：{ending.rstrip('。')}。接下来：{action}" if action else f"接住上一段结尾：{ending.rstrip('。')}。"


def has_structure(text: str) -> bool:
    """这段动作是不是已经按四步写了。"""
    return all(part in str(text or "") for part in ACTION_PARTS)


def breakdown_prompt(action: str, *, previous_ending: str = "") -> str:
    action = " ".join(str(action or "").split())
    if not action:
        raise ValueError("先写一下要拆的动作")
    context = f"\n上一段的结尾是：{previous_ending}，起始姿态要从这里接。" if previous_ending.strip() else ""
    return BREAKDOWN_PROMPT.format(action=action, context=context)


def parse_breakdown(answer: str) -> str:
    """模型回答里的四行；缺了哪一步就说哪一步，不把残缺的拆解当成品。"""
    lines: dict[str, str] = {}
    for raw in str(answer or "").splitlines():
        line = raw.strip().lstrip("-•*1234567890. ")
        for part in ACTION_PARTS:
            if line.startswith(part) and len(line) > len(part) + 1 and line[len(part)] in "：:":
                lines[part] = line[len(part) + 1:].strip()
    missing = [part for part in ACTION_PARTS if not lines.get(part)]
    if missing:
        raise ValueError("模型没有写全四步，缺：" + "、".join(missing))
    return "\n".join(f"{part}：{lines[part]}" for part in ACTION_PARTS)


__all__ = [
    "ACTION_PARTS", "BREAKDOWN_SYSTEM", "CONTINUATION_RULE", "GENERIC_ENDINGS", "STRUCTURE_RULE", "breakdown_prompt", "concrete_ending",
    "continuation_text", "ending_of",
    "has_structure", "parse_breakdown",
]

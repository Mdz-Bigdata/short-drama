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

from app.core import prompt_data


_WORDING_FILE = "action_grammar"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/action_grammar.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

ACTION_PARTS = _words_of("module.action_parts")
ENDING_MAX_CHARS = 160
# 「上一段结尾：」说的是上一段，不是这段自己的结尾。
_LABELLED_ENDING = re.compile(_text_of("module.labelled_ending"))
_SENTENCE = re.compile(r"[^。！？!?\n；;]+[。！？!?；;]?")
_LABEL_PREFIX = re.compile(_text_of("module.label_prefix"))
#: 表格没写内容时填的占位话：说不出任何姿势，模型接不住。
GENERIC_ENDINGS = frozenset({
    _text_of("module.generic_endings"), _text_of("module.generic_endings.2"), _text_of("module.generic_endings.3"),
})

STRUCTURE_RULE = (
    _text_of("module.structure_rule")
)
CONTINUATION_RULE = _text_of("module.continuation_rule")

# 「拆动作」的措辞在 data/prompt/action_breakdown.json：四行里写齐姿态、动线、时序、对位、节奏。
BREAKDOWN_SYSTEM = prompt_data.text("action_breakdown", "system")
BREAKDOWN_PROMPT = prompt_data.text("action_breakdown", "prompt")


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
    return _text_of("continuation_text.text").format(ending.rstrip('。'), action) if action else _text_of("continuation_text.text.2").format(ending.rstrip('。'))


def has_structure(text: str) -> bool:
    """这段动作是不是已经按四步写了。"""
    return all(part in str(text or "") for part in ACTION_PARTS)


def breakdown_prompt(action: str, *, previous_ending: str = "") -> str:
    action = " ".join(str(action or "").split())
    if not action:
        raise ValueError(_text_of("breakdown_prompt.text"))
    context = prompt_data.text("action_breakdown", "previous_ending").format(previous_ending) if previous_ending.strip() else ""
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
        raise ValueError(_text_of("parse_breakdown.text") + "、".join(missing))
    return "\n".join(f"{part}：{lines[part]}" for part in ACTION_PARTS)


__all__ = [
    "ACTION_PARTS", "BREAKDOWN_SYSTEM", "CONTINUATION_RULE", "GENERIC_ENDINGS", "STRUCTURE_RULE", "breakdown_prompt", "concrete_ending",
    "continuation_text", "ending_of",
    "has_structure", "parse_breakdown",
]

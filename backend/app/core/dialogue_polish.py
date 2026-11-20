# -*- coding: utf-8 -*-
"""润色台词：把已有台词改得更像真人当下开口，逐句对应，不增删句子、不换说话人。

保留原意和剧情走向，去书面语和说明腔，情绪藏在说话方式里，按每个人的口吻区分(措辞在
data/prompt/dialogue_polish.json)。本模块只拼提示词、核对模型的回答，不调模型；结果先给人看，
确认后才由调用方写回剧本。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core import prompt_data

_DATA = "dialogue_polish"


@dataclass(frozen=True)
class Line:
    """一句要润色的台词：id 在这次请求里唯一，speaker 是说话人，note 是语气说明(不改)。"""

    id: str
    speaker: str
    text: str
    note: str = ""


class PolishError(ValueError):
    """模型的回答对不上：缺句、多句、空句，或者整段不是要的 JSON。"""


def max_lines() -> int:
    return prompt_data.number(_DATA, "max_lines")


def scene_plugin(kind: str) -> str:
    """戏路对应的那一句(吵架 / 和解 / 安慰 / 暧昧 / 重逢 / 家人)；认不出是空串。"""
    plugins = prompt_data.value(_DATA, "scene_plugins")
    return next((text for key, text in plugins.items() if key and key in str(kind or "")), "")


def build_prompt(
    lines: Sequence[Line], *, voices: Mapping[str, str] | None = None, context: str = "", scene_kind: str = "", extra: str = "",
) -> tuple[str, str]:
    """(system, user)：规则、自检、对照、这场戏、各人口吻、逐句台词和输出格式。"""
    if not lines:
        raise PolishError("没有要润色的台词")
    if len(lines) > max_lines():
        raise PolishError(f"一次最多润色 {max_lines()} 句，这次有 {len(lines)} 句；分成几段来")
    speakers = list(dict.fromkeys(line.speaker for line in lines if line.speaker))
    voice_lines = [f"{name}：{str((voices or {}).get(name) or '').strip()}" for name in speakers if str((voices or {}).get(name) or "").strip()]
    rows = [{"id": line.id, "speaker": line.speaker, "text": line.text, **({"note": line.note} if line.note else {})} for line in lines]
    parts = [
        "\n".join(f"{index}. {rule}" for index, rule in enumerate(prompt_data.words(_DATA, "rules"), start=1)),
        prompt_data.text(_DATA, "self_check"),
        prompt_data.text(_DATA, "examples"),
        f"{prompt_data.text(_DATA, 'context_head')}{context.strip()}" if context.strip() else "",
        scene_plugin(scene_kind),
        f"{prompt_data.text(_DATA, 'voice_head')}\n" + "\n".join(voice_lines) if voice_lines else "",
        f"{prompt_data.text(_DATA, 'extra_head')}{extra.strip()}" if extra.strip() else "",
        f"{prompt_data.text(_DATA, 'lines_head')}\n{json.dumps(rows, ensure_ascii=False)}",
        prompt_data.text(_DATA, "output"),
    ]
    return prompt_data.text(_DATA, "system"), "\n\n".join(part for part in parts if part)


def _json_block(answer: str) -> Any:
    text = str(answer or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise PolishError("模型没有按要求返回 JSON")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as error:
        raise PolishError("模型返回的 JSON 读不出来") from error


def parse_answer(answer: str, lines: Sequence[Line]) -> list[dict[str, str]]:
    """模型的回答逐句对回原句：[{id, speaker, before, after}]。缺句、多句、空句一律当失败，不半截写回。"""
    data = _json_block(answer)
    items = data.get("lines") if isinstance(data, Mapping) else None
    if not isinstance(items, list):
        raise PolishError("回答里没有 lines")
    by_id = {line.id: line for line in lines}
    polished: dict[str, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        line_id = str(item.get("id") if item.get("id") is not None else "")
        if line_id not in by_id:
            raise PolishError(f"回答里多了一句(id {line_id})")
        text = str(item.get("text") or "").strip()
        # 模型偶尔把说话人或括号里的语气说明也写进台词：去掉。
        speaker = by_id[line_id].speaker
        if speaker and text.startswith(speaker) and text[len(speaker):len(speaker) + 1] in ("：", ":"):
            text = text[len(speaker) + 1:].strip()
        text = re.sub(r"^[（(][^）)]{1,16}[）)]\s*", "", text)
        if not text:
            raise PolishError(f"第 {line_id} 句润色后是空的")
        polished[line_id] = text
    missing = [line.id for line in lines if line.id not in polished]
    if missing:
        raise PolishError(f"回答少了 {len(missing)} 句(id {', '.join(missing[:5])})")
    return [
        {"id": line.id, "speaker": line.speaker, "before": line.text, "after": polished[line.id]}
        for line in lines
    ]


__all__ = ["Line", "PolishError", "build_prompt", "max_lines", "parse_answer", "scene_plugin"]

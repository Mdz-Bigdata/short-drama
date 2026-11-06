# -*- coding: utf-8 -*-
"""分集大纲不得推翻已定事实：让模型拿概述和策划方案校对一遍新账本。

结构校验器查得出情绪点类型、集数、锚点，查不出「概述说手没断、大纲把手砍了」。这里在每批分集
大纲出来后多问一次：对着项目概述（梗概 / 主题 / 立意 / 母题 / 终局意象 / 世界观）和策划方案节选，
只找被**推翻**的已定事实。有矛盾就把理由退回去重规划一次；仍有就记进 ``state["warnings"]`` 给人看。
措辞在 ``app/data/prompt/fact_check.json``；开关 ``SCREENWRITING_FACT_CHECK``（测试默认关）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import settings
from app.core import prompt_data
from app.core.screenwriting.structured_llm import LLMCaller, StructuredOutputError, call_structured

logger = logging.getLogger("app.core.screenwriting.fact_check")

_DATA = "fact_check"
ENABLED_ENV = "SCREENWRITING_FACT_CHECK"
LABEL = "ledger_fact_check"


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    episode: int = Field(default=0, ge=0, description="集号")
    beat: str = Field(default="", description="大纲里推翻事实的那句")
    fact: str = Field(default="", description="被推翻的已定事实")
    fix: str = Field(default="", description="一句话怎么改")


class FactCheckDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contradictions: list[Contradiction] = Field(default_factory=list)


def enabled() -> bool:
    return settings.env_flag(ENABLED_ENV, True)


def facts_text(overview: Mapping[str, Any] | None, director_plan: str, limit: int) -> str:
    """已定事实：概述里填了的项，加策划方案的前 ``limit`` 字。"""
    overview = overview or {}
    lines = [
        f"{label}：{str(overview.get(key) or '').strip()}"
        for key, label in prompt_data.pairs(_DATA, "fact_labels") if str(overview.get(key) or "").strip()
    ]
    plan = str(director_plan or "").strip()[: max(0, int(limit))]
    if plan:
        lines += [f"{prompt_data.text(_DATA, 'plan_label')}：", plan]
    return "\n".join(lines)


def ledger_text(entries: Sequence[Mapping[str, Any]]) -> str:
    blocks = []
    for entry in entries:
        lines = [f"第 {entry.get('episode')} 集《{entry.get('title') or ''}》", f"集尾钩子：{entry.get('hook') or ''}", "节点："]
        lines += [f"- {beat}" for beat in entry.get("story_beats") or []]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_prompt(facts: str, entries: Sequence[Mapping[str, Any]]) -> str:
    return f"{prompt_data.text(_DATA, 'head')}\n\n<facts>\n{facts}\n</facts>\n\n<ledger>\n{ledger_text(entries)}\n</ledger>"


def check(
    caller: LLMCaller, *, facts: str, entries: Sequence[Mapping[str, Any]], temperature: float | None = None,
) -> list[Contradiction]:
    """问一次；答不上来按没有矛盾（校对是加分项，不能让规划失败）。"""
    try:
        result = call_structured(
            caller, system_prompt=prompt_data.text(_DATA, "system"), user_prompt=build_prompt(facts, entries), schema=FactCheckDraft,
            max_tokens=prompt_data.number(_DATA, "max_tokens"), attempts=1, label=LABEL, temperature=temperature,
        )
    except StructuredOutputError as error:
        logger.warning("[Screenwriting] 分集大纲事实校对没有可用答案，按无矛盾处理：%s", "；".join(error.reasons)[:200])
        return []
    found = [item for item in FactCheckDraft.model_validate(result.data).contradictions if item.beat.strip() and item.fact.strip()]
    return found[: prompt_data.number(_DATA, "max_items")]


def retry_block(found: Sequence[Contradiction]) -> str:
    """追加在大纲提示词后面的退回理由。"""
    line = prompt_data.text(_DATA, "retry_line")
    return "\n".join([prompt_data.text(_DATA, "retry_head"), *(line.format(**item.model_dump()) for item in found)])


def warning_text(first: int, last: int, found: Sequence[Contradiction]) -> str:
    item = prompt_data.text(_DATA, "warning_item")
    summary = "；".join(item.format(**entry.model_dump()) for entry in found)
    return prompt_data.text(_DATA, "warning").format(first=first, last=last, summary=summary)


__all__ = ["ENABLED_ENV", "LABEL", "Contradiction", "FactCheckDraft", "build_prompt", "check", "enabled", "facts_text", "ledger_text", "retry_block", "warning_text"]

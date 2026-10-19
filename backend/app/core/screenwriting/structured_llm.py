# -*- coding: utf-8 -*-
"""JSON-constrained LLM calls with validation and reason-carrying retries.

The project's model gateway returns free text, so structured output is enforced
here: the prompt ends with the JSON schema, the answer is parsed and validated
against a Pydantic model plus optional semantic validators, and a failed round
is retried with the concrete reasons appended ("上一轮输出未通过校验").
``call_text`` runs the same loop for the one stage that answers in plain text
(the episode's prose body).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.llm_profile import temperature_scope

logger = logging.getLogger("app.core.screenwriting.llm")

#: ``caller(system_prompt, user_prompt, max_tokens) -> str``
LLMCaller = Callable[[str, str, int], str]
#: ``validator(parsed_dict) -> list[reason]``; may mutate the dict for mechanical repairs.
SemanticValidator = Callable[[dict[str, Any]], list[str]]
#: ``validator(text) -> list[reason]`` for a free-text stage.
TextValidator = Callable[[str], list[str]]

ModelT = TypeVar("ModelT", bound=BaseModel)

RETRY_HEADER = "# 上一轮输出未通过校验，请针对性修正后重新输出"
TRUNCATED_REASON = "上一轮输出超出长度上限被截断，本轮已放宽上限；请保持各字段精炼，只输出一个完整的 JSON 对象"
# A cut-off answer is retried with twice the room, up to this (SCREENWRITING_MAX_TOKENS_CAP).
# The gateway brings any figure above a provider's own ceiling back down to it.
DEFAULT_MAX_TOKENS_CAP = 1_000_000


def max_tokens_cap() -> int:
    from app import settings

    return settings.env_int("SCREENWRITING_MAX_TOKENS_CAP", DEFAULT_MAX_TOKENS_CAP, minimum=2_000, maximum=1_000_000)


def looks_truncated(text: str) -> bool:
    """An empty reply, or one that opens a JSON object (or fence) and never closes it: the token limit hit.

    Reasoning models spend part of ``max_tokens`` thinking, so a long shot plan can stop mid-object;
    asking again with the same budget fails the same way every round.
    """
    stripped = (text or "").strip()
    if not stripped:
        return True
    opens = stripped.startswith(("{", "```"))
    closes = stripped.endswith(("}", "```"))
    return opens and not closes
OUTPUT_FORMAT_HEADER = "# 输出格式"


class StructuredOutputError(RuntimeError):
    def __init__(self, message: str, *, reasons: list[str], raw_text: str = ""):
        super().__init__(message)
        self.reasons = reasons
        self.raw_text = raw_text


@dataclass
class StructuredResult:
    data: dict[str, Any]
    raw_text: str
    attempts: int
    prompt: str


class TextOutputError(RuntimeError):
    """A free-text stage never passed validation; ``last_text`` is the final normalised draft."""

    def __init__(self, message: str, *, reasons: list[str], last_text: str = ""):
        super().__init__(message)
        self.reasons = reasons
        self.last_text = last_text


@dataclass
class TextResult:
    text: str
    attempts: int
    prompt: str


def extract_json_object(text: str) -> dict[str, Any] | None:
    """First JSON object in ``text``: a fenced block wins, otherwise the outermost braces."""
    if not text or not text.strip():
        return None
    candidates: list[str] = []
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        candidates.append(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError):
            # Trailing commas are the most common non-JSON habit of chat models.
            try:
                parsed = json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
            except (TypeError, ValueError):
                continue
        if isinstance(parsed, dict):
            return parsed
    return None


def compact_schema(model: type[BaseModel]) -> str:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":"))


def _language_name() -> str:
    from app.core.screenwriting.prompts import output_language_name

    return output_language_name()


def output_format_section(model: type[BaseModel]) -> str:
    return (
        f"{OUTPUT_FORMAT_HEADER}\n"
        "只输出一个合法的 JSON 对象（UTF-8），不要输出 markdown 代码块之外的任何解释文字，不要省略字段，"
        f"不要输出注释或尾随逗号。JSON 键名与枚举值保持英文，其余字符串值使用{_language_name()}。\n"
        f"JSON Schema（必须完全符合）：\n{compact_schema(model)}"
    )


def format_validation_error(error: ValidationError, limit: int = 8) -> list[str]:
    reasons: list[str] = []
    for item in error.errors()[:limit]:
        loc = ".".join(str(part) for part in item.get("loc", ()))
        reasons.append(f"字段 {loc or '(root)'}: {item.get('msg', '')}")
    return reasons


def call_structured(
    caller: LLMCaller,
    *,
    system_prompt: str,
    user_prompt: str,
    schema: type[ModelT],
    max_tokens: int,
    attempts: int = 3,
    validators: Sequence[SemanticValidator] = (),
    label: str = "structured",
    temperature: float | None = None,
) -> StructuredResult:
    """Ask, parse, validate, retry with reasons; raise ``StructuredOutputError`` when exhausted.

    ``temperature`` is the sampling profile the gateway should use for this stage
    (``None`` keeps the gateway's default); a validator may mutate the parsed dict
    for mechanical repairs before the next round is decided.
    """
    reasons: list[str] = []
    raw_text = ""
    budget = max_tokens
    base_prompt = f"{user_prompt.rstrip()}\n\n{output_format_section(schema)}"
    prompt = base_prompt
    for attempt in range(1, max(1, attempts) + 1):
        if reasons:
            prompt = f"{base_prompt}\n\n{RETRY_HEADER}\n" + "\n".join(f"- {reason}" for reason in reasons)
        with temperature_scope(temperature):
            raw_text = caller(system_prompt, prompt, budget) or ""
        parsed = extract_json_object(raw_text)
        if parsed is None:
            if looks_truncated(raw_text):
                grown = min(max(budget * 2, budget + 1), max_tokens_cap())
                logger.warning(
                    "[Screenwriting] %s 第 %d/%d 轮：输出被截断（max_tokens=%d），下一轮上限 %d",
                    label, attempt, attempts, budget, grown,
                )
                budget = grown
                reasons = [TRUNCATED_REASON]
                continue
            reasons = ["输出不是合法 JSON 对象；请只输出一个 JSON 对象，不要附加任何说明文字"]
            logger.warning("[Screenwriting] %s 第 %d/%d 轮：输出不是合法 JSON", label, attempt, attempts)
            continue
        try:
            validated = schema.model_validate(parsed)
        except ValidationError as error:
            reasons = ["输出不符合 schema：" + "；".join(format_validation_error(error))]
            logger.warning("[Screenwriting] %s 第 %d/%d 轮：schema 校验失败 %s", label, attempt, attempts, reasons[0][:300])
            continue
        data = validated.model_dump(mode="json")
        semantic: list[str] = []
        for validator in validators:
            semantic.extend(validator(data))
        if semantic:
            reasons = semantic
            logger.warning("[Screenwriting] %s 第 %d/%d 轮：内容校验失败 %s", label, attempt, attempts, "; ".join(semantic)[:400])
            continue
        return StructuredResult(data=data, raw_text=raw_text, attempts=attempt, prompt=prompt)
    raise StructuredOutputError(
        f"{label} 连续 {attempts} 次未通过校验，最后一轮原因：{'; '.join(reasons)}",
        reasons=reasons,
        raw_text=raw_text,
    )


def call_text(
    caller: LLMCaller,
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    attempts: int = 3,
    normalize: Callable[[str], str] = str.strip,
    validators: Sequence[TextValidator] = (),
    label: str = "text",
    temperature: float | None = None,
) -> TextResult:
    """The free-text twin of ``call_structured``: ask, normalise, validate, retry with reasons."""
    reasons: list[str] = []
    text = ""
    prompt = user_prompt.rstrip()
    for attempt in range(1, max(1, attempts) + 1):
        if reasons:
            prompt = f"{user_prompt.rstrip()}\n\n{RETRY_HEADER}\n" + "\n".join(f"- {reason}" for reason in reasons)
        with temperature_scope(temperature):
            text = normalize(caller(system_prompt, prompt, max_tokens) or "")
        reasons = [reason for validator in validators for reason in validator(text)] if text else ["输出为空；请直接输出正文"]
        if not reasons:
            return TextResult(text=text, attempts=attempt, prompt=prompt)
        logger.warning("[Screenwriting] %s 第 %d/%d 轮：正文校验失败 %s", label, attempt, attempts, "; ".join(reasons)[:400])
    raise TextOutputError(
        f"{label} 连续 {attempts} 次未通过校验，最后一轮原因：{'; '.join(reasons)}",
        reasons=reasons,
        last_text=text,
    )


__all__ = [
    "LLMCaller",
    "RETRY_HEADER",
    "SemanticValidator",
    "StructuredOutputError",
    "StructuredResult",
    "TextOutputError",
    "TextResult",
    "TextValidator",
    "call_structured",
    "call_text",
    "compact_schema",
    "extract_json_object",
    "output_format_section",
]

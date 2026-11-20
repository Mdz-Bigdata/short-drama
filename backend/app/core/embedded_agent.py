# -*- coding: utf-8 -*-
"""The assistant that works inside a project with tools, and asks before it spends.

A turn takes the person's message and the recent transcript, lets the text
model pick a tool from the catalog or answer directly, runs read and write tools
at once, and turns a paid tool into a proposal the person confirms. The model
answers in a small JSON envelope; anything else is taken as a plain reply, so a
model that ignores the format still talks, it just cannot act.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from app.core import project_memory, prompt_data
from app.core.agent_tools import ToolError, catalog
from app.core.screenwriting.structured_llm import extract_json_object


_WORDING_FILE = "embedded_agent"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/embedded_agent.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

# 一轮里最多连调几个工具：Blender 预演常见的「看 → 改 → 渲染 → 交给分镜」要四步，留两步余量。
MAX_TOOL_CALLS_PER_TURN = 6
HISTORY_LIMIT = 24
# The transcript is resent on every step of a turn, so its size is paid many times over.
RECENT_ENTRIES = 10
EARLIER_LINE_CHARS = 60
EARLIER_TOTAL_CHARS = 800
TOOL_RESULT_CHARS = 2000
OLD_RESULT_CHARS = 300
STORED_RESULT_CHARS = 600
MAX_DETAILED_TOOLS = 5
_SYSTEM_PARAMS = frozenset({"task_id", "confirm"})
PENDING_KEY = "agent_pending"
HISTORY_KEY = "agent_history"


def _envelope(answer: str) -> dict[str, Any] | None:
    """模型回的 JSON 信封；字符串里带真换行、外面包了代码块或前后有闲话也照样读出来。"""
    parsed = extract_json_object(answer)
    if parsed:
        return parsed
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", answer.strip(), flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1], strict=False)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _signature(tool: Mapping[str, Any]) -> str:
    """A tool's parameters by name; ``*`` marks the required ones, and task_id and confirm are the system's to fill in."""
    required = set(tool["input_schema"].get("required") or [])
    names = [name for name in tool["input_schema"].get("properties", {}) if name not in _SYSTEM_PARAMS]
    return "、".join(f"{name}*" if name in required else name for name in names) or _text_of("_signature.text")


@lru_cache(maxsize=1)
def _tool_index() -> str:
    """Every tool in a line, the same on every call: this is the part a provider's prefix cache can hold."""
    return "\n".join(_text_of("_tool_index.text").format(t['name'], t['effect'], t['description'], _signature(t)) for t in catalog.describe())


def _tool_words(tool: Mapping[str, Any]) -> set[str]:
    return project_memory._grams(f"{tool['name']} {tool['title']} {tool['description']}")


def tool_details(message: str, used: Sequence[str] = (), *, limit: int = MAX_DETAILED_TOOLS) -> str:
    """Full parameter schemas for the tools this message is likely to need, and for those it has already reached for."""
    asked = project_memory._grams(message)
    tools = catalog.describe()
    scored = sorted(tools, key=lambda tool: -len(asked & _tool_words(tool)) / max(1, len(_tool_words(tool))) ** 0.5)
    chosen = [tool for tool in tools if tool["name"] in used]
    for tool in scored:
        if len(chosen) >= limit:
            break
        if tool not in chosen and asked & _tool_words(tool):
            chosen.append(tool)
    lines = []
    for tool in chosen:
        properties = {key: value for key, value in tool["input_schema"].get("properties", {}).items() if key not in _SYSTEM_PARAMS}
        lines.append(f"- {tool['name']}：{json.dumps(properties, ensure_ascii=False, separators=(',', ':'))}")
    return _text_of("tool_details.text") + "\n".join(lines) if lines else ""


def system_prompt() -> str:
    return (
        _text_of("system_prompt.text").format(project_memory.REMEMBER_INSTRUCTION, _guides(), _tool_index())
    )


def _guides() -> str:
    """捏脸、舞台这些新功能的用法说明，一行一条，措辞在 agent_prompts.json 的 tool_assistant_guides 里。"""
    lines = [str(item).strip() for item in prompt_data.value("agent_prompts", "tool_assistant_guides") if str(item).strip()]
    return "".join(f"{line}\n" for line in lines)


def _short(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else _text_of("_short.text").format(text[:limit])


def _result_limit(tool_name: str) -> int:
    """最新一条工具结果允许的长度：带控件表 / 操作说明的读工具自己说要多长，别的用默认。"""
    try:
        return max(TOOL_RESULT_CHARS, int(catalog.get(tool_name).result_chars or 0))
    except ToolError:
        return TOOL_RESULT_CHARS


def stored_result(result: Any) -> Any:
    """What of a tool's result stays in the transcript: it can always be read again, and it is resent on every call."""
    return _short(result, STORED_RESULT_CHARS)


def _history_text(history: Sequence[Mapping[str, Any]]) -> str:
    """The transcript as a model needs it: recent turns word for word, the latest tool result in full, the rest in a line.

    Older turns are not summarised by a model, which would cost a call to save a call; what has to outlive them is what
    ``project_memory`` is for.
    """
    rows = list(history)[-HISTORY_LIMIT:]
    last_tool = max((index for index, item in enumerate(rows) if item.get("role") == "tool"), default=-1)
    recent_from = max(0, len(rows) - RECENT_ENTRIES)
    earlier = [
        f"{_text_of('_history_text.earlier') if item.get('role') == 'user' else _text_of('_history_text.earlier.2')}：{_short(str(item.get('content') or ''), EARLIER_LINE_CHARS)}"
        for item in rows[:recent_from] if item.get("role") in ("user", "assistant")
    ]
    lines = [_text_of("_history_text.lines").format(' / '.join(earlier))[:EARLIER_TOTAL_CHARS]] if earlier else []
    for index, item in enumerate(rows):
        if index < recent_from:
            continue
        role = item.get("role")
        if role == "tool":
            limit = _result_limit(str(item.get("tool") or "")) if index == last_tool else OLD_RESULT_CHARS
            lines.append(_text_of("_history_text.text").format(item.get('tool'), _short(item.get('result'), limit)))
        else:
            lines.append(f"[{_text_of('_history_text.text.2') if role == 'user' else _text_of('_history_text.text.3')}] {item.get('content')}")
    return "\n".join(lines)


def run_turn(service, *, user: Mapping[str, Any], task_id: str, message: str, history: Sequence[Mapping[str, Any]], config: Mapping[str, Any], memory: str = "") -> dict[str, Any]:
    """One exchange: tool calls the model made, its final reply, and a proposal when a paid tool was asked for."""
    transcript: list[dict[str, Any]] = [*history, {"role": "user", "content": message}]
    calls: list[dict[str, Any]] = []
    proposal: dict[str, Any] | None = None
    reply = ""
    remembered: list[Any] = []
    thoughts: list[str] = []
    model = str(config.get("llm_model") or "")
    system = system_prompt()
    title = str(config.get("title_suggestion") or "")
    seen_reads: dict[str, Any] = {}
    for _ in range(MAX_TOOL_CALLS_PER_TURN + 1):
        details = tool_details(message, [call["tool"] for call in calls])
        context = "\n\n".join(part for part in (memory, details) if part)
        prompt = f"{context}\n\n" if context else ""
        answer = service.gateway.call_llm(model, system, _text_of("run_turn.answer").format(prompt, _history_text(transcript)), title)
        thought = _reasoning_of(service.gateway)
        if thought:
            thoughts.append(thought)
        parsed = _envelope(answer or "")
        if parsed and isinstance(parsed.get("remember"), list):
            remembered.extend(parsed["remember"])
        if not parsed or (not parsed.get("tool") and "reply" not in parsed):
            reply = (answer or "").strip() or _text_of("run_turn.reply")
            break
        if "reply" in parsed and not parsed.get("tool"):
            reply = str(parsed.get("reply") or "").strip()
            break
        name = str(parsed.get("tool") or "")
        arguments = dict(parsed.get("arguments") or {})
        arguments["task_id"] = task_id
        arguments.pop("confirm", None)
        read_key = f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)}"
        try:
            is_read = catalog.get(name).effect == "read"
        except ToolError:
            is_read = False
        if is_read and read_key in seen_reads:
            # The state cannot have changed since nothing was written: the answer is already above.
            result = {"ok": True, "note": _text_of("run_turn.result.note")}
        else:
            try:
                result = catalog.call(name, arguments, service=service, user=user)
            except ToolError as exc:
                result = {"ok": False, "error": str(exc)}
            if is_read:
                seen_reads[read_key] = True
            else:
                seen_reads.clear()
        calls.append({"tool": name, "arguments": {k: v for k, v in arguments.items() if k != "task_id"}, "result": result})
        if result.get("needs_confirmation"):
            proposal = {"tool": name, "arguments": result["arguments"], "message": result["message"]}
            reply = _text_of("run_turn.reply.2").format(result['message'])
            break
        if result.get("ok") is False:
            # The saved call: the model learns the right shape now instead of guessing again.
            result = {**result, **_schema_hint(name)}
        transcript.append({"role": "tool", "tool": name, "result": result})
    else:
        reply = reply or _text_of("run_turn.reply.3")
    if not reply:
        reply = _text_of("run_turn.reply.4")
    return {"reply": reply, "tool_calls": calls, "proposal": proposal, "remember": remembered, "reasoning": _joined_reasoning(thoughts)}


def _reasoning_of(gateway: Any) -> str:
    """The thinking the model returned with its last answer; a gateway that keeps none gives nothing."""
    take = getattr(gateway, "take_reasoning", None)
    try:
        text = take() if callable(take) else ""
    except Exception:  # noqa: BLE001 - thinking is shown for reference; its absence changes nothing
        return ""
    return text.strip() if isinstance(text, str) else ""


def _joined_reasoning(thoughts: Sequence[str]) -> str:
    """Every model call's thinking in this turn, in order, cut to the stored limit."""
    rules = prompt_data.value(_WORDING_FILE, "reasoning")
    text = str(rules["separator"]).join(thoughts)
    limit = int(rules["max_chars"])
    return text if len(text) <= limit else text[:limit].rstrip() + str(rules["cut"])


def _schema_hint(name: str) -> dict[str, Any]:
    try:
        tool = catalog.get(name)
    except ToolError:
        return {"known_tools": [item["name"] for item in catalog.describe()]}
    properties = {key: value for key, value in tool.describe()["input_schema"].get("properties", {}).items() if key not in _SYSTEM_PARAMS}
    return {"expected_arguments": properties}


def confirm_pending(service, *, user: Mapping[str, Any], pending: Mapping[str, Any]) -> dict[str, Any]:
    """Run the paid tool the person just confirmed."""
    arguments = dict(pending.get("arguments") or {})
    arguments["confirm"] = True
    try:
        return catalog.call(str(pending.get("tool")), arguments, service=service, user=user)
    except ToolError as exc:
        return {"ok": False, "error": str(exc)}


__all__ = ["HISTORY_KEY", "HISTORY_LIMIT", "MAX_TOOL_CALLS_PER_TURN", "PENDING_KEY", "confirm_pending", "run_turn", "stored_result", "system_prompt", "tool_details"]

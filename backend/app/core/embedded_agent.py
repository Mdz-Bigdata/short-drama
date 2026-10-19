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
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.agent_tools import ToolError, catalog
from app.core.screenwriting.structured_llm import extract_json_object

MAX_TOOL_CALLS_PER_TURN = 4
HISTORY_LIMIT = 24
PENDING_KEY = "agent_pending"
HISTORY_KEY = "agent_history"


def system_prompt(task_id: str) -> str:
    tools = "\n".join(
        f"- {t['name']}（{t['title']}，{t['effect']}）：{t['description']} 参数：{json.dumps(t['input_schema'].get('properties', {}), ensure_ascii=False)}"
        for t in catalog.describe()
    )
    return (
        "你是短剧制作平台里的工具助手，只能通过下面的工具读取和修改当前项目，不能编造项目状态。\n"
        f"当前项目 task_id 固定为 {task_id}，调用工具时必须带上它。\n"
        "每次只输出一个 JSON 对象，二选一：\n"
        '1. 调用工具：{"thought": "为什么", "tool": "工具名", "arguments": {...}}\n'
        '2. 回答用户：{"reply": "给用户看的话"}\n'
        "规则：先用 read 工具看清状态再动手；write 工具会直接生效；paid 工具会花钱，"
        "你只提出调用，由用户确认后才执行，不要自己传 confirm。不要重复调用同一个工具。\n"
        f"可用工具：\n{tools}\n"
    )


def _history_text(history: Sequence[Mapping[str, Any]]) -> str:
    lines = []
    for item in history[-HISTORY_LIMIT:]:
        role = item.get("role")
        if role == "tool":
            lines.append(f"[工具 {item.get('tool')} 返回] {json.dumps(item.get('result'), ensure_ascii=False)[:2000]}")
        else:
            lines.append(f"[{'用户' if role == 'user' else '助手'}] {item.get('content')}")
    return "\n".join(lines)


def run_turn(service, *, user: Mapping[str, Any], task_id: str, message: str, history: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    """One exchange: tool calls the model made, its final reply, and a proposal when a paid tool was asked for."""
    transcript: list[dict[str, Any]] = [*history, {"role": "user", "content": message}]
    calls: list[dict[str, Any]] = []
    proposal: dict[str, Any] | None = None
    reply = ""
    model = str(config.get("llm_model") or "")
    for _ in range(MAX_TOOL_CALLS_PER_TURN + 1):
        answer = service.gateway.call_llm(model, system_prompt(task_id), _history_text(transcript) + "\n[助手]", str(config.get("title_suggestion") or ""))
        parsed = extract_json_object(answer or "")
        if not parsed or (not parsed.get("tool") and "reply" not in parsed):
            reply = (answer or "").strip() or "我没能理解模型的回答，请换个说法。"
            break
        if "reply" in parsed and not parsed.get("tool"):
            reply = str(parsed.get("reply") or "").strip()
            break
        name = str(parsed.get("tool") or "")
        arguments = dict(parsed.get("arguments") or {})
        arguments["task_id"] = task_id
        arguments.pop("confirm", None)
        try:
            result = catalog.call(name, arguments, service=service, user=user)
        except ToolError as exc:
            result = {"ok": False, "error": str(exc)}
        calls.append({"tool": name, "arguments": {k: v for k, v in arguments.items() if k != "task_id"}, "result": result})
        if result.get("needs_confirmation"):
            proposal = {"tool": name, "arguments": result["arguments"], "message": result["message"]}
            reply = f"{result['message']}。回复 /confirm 执行，或 /cancel 放弃。"
            break
        transcript.append({"role": "tool", "tool": name, "result": result})
    else:
        reply = reply or "这一轮已经调用了多个工具，先停在这里；告诉我接下来要做什么。"
    if not reply:
        reply = "已完成。"
    return {"reply": reply, "tool_calls": calls, "proposal": proposal}


def confirm_pending(service, *, user: Mapping[str, Any], pending: Mapping[str, Any]) -> dict[str, Any]:
    """Run the paid tool the person just confirmed."""
    arguments = dict(pending.get("arguments") or {})
    arguments["confirm"] = True
    try:
        return catalog.call(str(pending.get("tool")), arguments, service=service, user=user)
    except ToolError as exc:
        return {"ok": False, "error": str(exc)}


__all__ = ["HISTORY_KEY", "HISTORY_LIMIT", "MAX_TOOL_CALLS_PER_TURN", "PENDING_KEY", "confirm_pending", "run_turn", "system_prompt"]

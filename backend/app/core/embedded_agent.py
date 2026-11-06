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

from app.core import project_memory
from app.core.agent_tools import ToolError, catalog
from app.core.screenwriting.structured_llm import extract_json_object

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
    return "、".join(f"{name}*" if name in required else name for name in names) or "无"


@lru_cache(maxsize=1)
def _tool_index() -> str:
    """Every tool in a line, the same on every call: this is the part a provider's prefix cache can hold."""
    return "\n".join(f"- {t['name']}（{t['effect']}）{t['description']} 参数：{_signature(t)}" for t in catalog.describe())


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
    return "【可能用到的工具的参数细节】\n" + "\n".join(lines) if lines else ""


def system_prompt() -> str:
    return (
        "你是短剧制作平台里的工具助手，只能通过下面的工具读取和修改当前项目，不能编造项目状态。\n"
        "当前项目由系统确定，调用工具时不用传 task_id。\n"
        "每次只输出一个 JSON 对象，二选一：\n"
        '1. 调用工具：{"tool": "工具名", "arguments": {...}}\n'
        '2. 回答用户：{"reply": "给用户看的话"}\n'
        f"{project_memory.REMEMBER_INSTRUCTION}\n"
        "规则：先用 read 工具看清状态再动手；write 工具会直接生效；paid 工具会花钱，"
        "你只提出调用，由用户确认后才执行，不要自己传 confirm。不要重复调用同一个工具。\n"
        "Blender 3D 预演：改站位或机位前先 describe_stage 看清人名、机位 id 与坐标，再用 edit_stage 改，"
        "然后 render_blender_previz 渲染给用户看；用户满意后再 attach_previz_to_shots 交给分镜。"
        "用户要自动排一场的站位机位，用 auto_plan_stage 出几版方案，再 adopt_stage_plan 采用推荐的那版；要搭道具或场景里的东西，用 build_stage_model。"
        "用户说「在 Blender 里看」就 push_to_blender；说「按我在 Blender 里拖的来」就 pull_from_blender(apply=true)。\n"
        "分镜故事板：用户要「打开 / 看 / 下载」某场的九宫格、提示词、空间调度、3D 导演台、提示词分包、资产设定图，"
        "先用 open_storyboard_view 在界面上打开，再按需用 get_scene_board / get_scene_prompt / get_prompt_packages / get_asset_sheets 读内容回答；"
        "要「重画这一场」就 redraw_scene 再提出 run_stage(stage=4)。\n"
        "节点画布：先 get_canvas 看清现状；要加、连、改多个节点时，把所有操作放进同一次 edit_canvas，不要拆成多次调用；"
        "要运行节点先 quote_canvas_run 告诉用户费用，再提出 run_canvas_nodes。"
        "用户要一整条制作流程时用 plan_canvas_workflow 出草稿，把步骤讲给用户确认后再 apply_canvas_workflow；失败后用 canvas_workflow_status 的 runnable 只重跑没完成的步骤。\n"
        "回答用户时不要出现工具名和参数(如 redraw_scene、run_stage(stage=4))，用界面上的说法："
        "「重画这一场」「重跑分镜阶段」「打开空间调度」「渲染 Blender 预演」。\n"
        "参数名后带 * 的必填；参数细节不清楚时，先看消息里给的细节，没有就按名字传，出错时系统会告诉你正确的格式。\n"
        f"可用工具：\n{_tool_index()}\n"
    )


def _short(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else f"{text[:limit]}…（已截断）"


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
        f"{'用户' if item.get('role') == 'user' else '助手'}：{_short(str(item.get('content') or ''), EARLIER_LINE_CHARS)}"
        for item in rows[:recent_from] if item.get("role") in ("user", "assistant")
    ]
    lines = [f"[更早的对话摘录] {' / '.join(earlier)}"[:EARLIER_TOTAL_CHARS]] if earlier else []
    for index, item in enumerate(rows):
        if index < recent_from:
            continue
        role = item.get("role")
        if role == "tool":
            limit = TOOL_RESULT_CHARS if index == last_tool else OLD_RESULT_CHARS
            lines.append(f"[工具 {item.get('tool')} 返回] {_short(item.get('result'), limit)}")
        else:
            lines.append(f"[{'用户' if role == 'user' else '助手'}] {item.get('content')}")
    return "\n".join(lines)


def run_turn(service, *, user: Mapping[str, Any], task_id: str, message: str, history: Sequence[Mapping[str, Any]], config: Mapping[str, Any], memory: str = "") -> dict[str, Any]:
    """One exchange: tool calls the model made, its final reply, and a proposal when a paid tool was asked for."""
    transcript: list[dict[str, Any]] = [*history, {"role": "user", "content": message}]
    calls: list[dict[str, Any]] = []
    proposal: dict[str, Any] | None = None
    reply = ""
    remembered: list[Any] = []
    model = str(config.get("llm_model") or "")
    system = system_prompt()
    title = str(config.get("title_suggestion") or "")
    seen_reads: dict[str, Any] = {}
    for _ in range(MAX_TOOL_CALLS_PER_TURN + 1):
        details = tool_details(message, [call["tool"] for call in calls])
        context = "\n\n".join(part for part in (memory, details) if part)
        prompt = f"{context}\n\n" if context else ""
        answer = service.gateway.call_llm(model, system, f"{prompt}{_history_text(transcript)}\n[助手]", title)
        parsed = _envelope(answer or "")
        if parsed and isinstance(parsed.get("remember"), list):
            remembered.extend(parsed["remember"])
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
        read_key = f"{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)}"
        try:
            is_read = catalog.get(name).effect == "read"
        except ToolError:
            is_read = False
        if is_read and read_key in seen_reads:
            # The state cannot have changed since nothing was written: the answer is already above.
            result = {"ok": True, "note": "这个工具刚用同样的参数读过，结果不变，直接用上面的结果。"}
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
            reply = f"{result['message']}。回复 /confirm 执行，或 /cancel 放弃。"
            break
        if result.get("ok") is False:
            # The saved call: the model learns the right shape now instead of guessing again.
            result = {**result, **_schema_hint(name)}
        transcript.append({"role": "tool", "tool": name, "result": result})
    else:
        reply = reply or "这一轮已经调用了多个工具，先停在这里；告诉我接下来要做什么。"
    if not reply:
        reply = "已完成。"
    return {"reply": reply, "tool_calls": calls, "proposal": proposal, "remember": remembered}


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

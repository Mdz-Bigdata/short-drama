"""The tools an agent may use on a project: one catalog for the embedded assistant and the MCP server.

Each tool names what it reads or changes, carries a JSON schema for its
arguments, and says what kind of effect it has: ``read`` tools answer from
state, ``write`` tools change the project without spending money, ``paid``
tools start model calls and only run when the caller says ``confirm: true``.
Every call is bound to a user and checked against the project's owner, so a
tool never reaches a project the caller could not open in the UI.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

EFFECTS = ("read", "write", "paid")


class ToolError(ValueError):
    """The call named a tool, a project or an argument the catalog cannot act on."""


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    effect: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]
    needs_task: bool = True
    tags: tuple[str, ...] = field(default_factory=tuple)

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "title": self.title, "description": self.description, "effect": self.effect, "input_schema": self.input_schema}


def _schema(properties: Mapping[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": dict(properties), "required": list(required or []), "additionalProperties": False}


_TASK = {"task_id": {"type": "string", "description": "项目（任务）ID"}}
_CONFIRM = {"confirm": {"type": "boolean", "description": "付费操作必须显式传 true 才会执行；否则只返回将要发生什么"}}


class ToolCatalog:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.effect not in EFFECTS:
            raise ValueError(f"unknown effect {tool.effect}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"没有叫 {name} 的工具")
        return tool

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def describe(self) -> list[dict[str, Any]]:
        return [tool.describe() for tool in self._tools.values()]

    def call(self, name: str, arguments: Mapping[str, Any] | None, *, service: Any, user: Mapping[str, Any]) -> dict[str, Any]:
        """Run one tool as ``user``; the result always says whether it ran, and a paid tool waits for confirmation."""
        tool = self.get(name)
        args = dict(arguments or {})
        if tool.needs_task:
            task_id = str(args.get("task_id") or "").strip()
            if not task_id:
                raise ToolError("缺少 task_id")
            task = service.repo.get_task(task_id)
            if not task:
                raise ToolError(f"项目 {task_id} 不存在")
            owner = str(task.get("owner_user_id") or "")
            if owner and owner != str(user.get("user_id") or "") and user.get("role") != "admin":
                raise ToolError(f"项目 {task_id} 不属于当前用户")
        if tool.effect == "paid" and not args.get("confirm"):
            return {"ok": False, "needs_confirmation": True, "tool": name, "arguments": {k: v for k, v in args.items() if k != "confirm"},
                    "message": f"「{tool.title}」会调用付费模型；确认后再执行（confirm=true）"}
        args.pop("confirm", None)
        try:
            result = tool.handler(service=service, user=user, **args)
        except ToolError:
            raise
        except (ValueError, LookupError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "tool": name, "result": result}


catalog = ToolCatalog()


def tool(name: str, *, title: str, description: str, effect: str, properties: Mapping[str, Any] | None = None,
         required: list[str] | None = None, needs_task: bool = True):
    def decorate(handler: Callable[..., Any]) -> Callable[..., Any]:
        props = dict(_TASK) if needs_task else {}
        props.update(properties or {})
        if effect == "paid":
            props.update(_CONFIRM)
        catalog.register(Tool(
            name=name, title=title, description=description, effect=effect,
            input_schema=_schema(props, (["task_id"] if needs_task else []) + list(required or [])),
            handler=handler, needs_task=needs_task,
        ))
        return handler
    return decorate


def _call(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Call a service method, awaiting it when it is a coroutine function (the MCP server runs in a thread)."""
    result = fn(*args, **kwargs)
    if inspect.iscoroutine(result):
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(result)
        finally:
            loop.close()
    return result


# ---------------------------------------------------------------------------- read tools


@tool("list_projects", title="列出我的项目", description="当前用户的短剧项目：ID、标题、状态、当前阶段。", effect="read", needs_task=False,
      properties={"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}})
def list_projects(*, service, user, limit: int = 20):
    user_id = str(user.get("user_id") or "")
    rows = []
    for task in service.repo.list_all_tasks():
        if not isinstance(task, dict):
            continue
        if user.get("role") != "admin" and str(task.get("owner_user_id") or "") != user_id:
            continue
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        rows.append({"task_id": task.get("task_id"), "title": config.get("title_suggestion"), "status": task.get("status"),
                     "current_stage": task.get("current_stage"), "episode_count": config.get("episode_count")})
    return {"projects": rows[-int(limit):]}


@tool("get_project", title="查看项目状态", description="项目的状态、当前阶段、下一步建议与各阶段完成情况。", effect="read")
def get_project(*, service, user, task_id: str):
    task = service.repo.get_task(task_id)
    snapshot = service.workflow_snapshot(task)
    return {
        "task_id": task_id, "title": (task.get("config") or {}).get("title_suggestion"), "status": task.get("status"),
        "creation_mode": (task.get("config") or {}).get("creation_mode") or "drama",
        "current_stage": task.get("current_stage"), "next_stage": snapshot.get("next_stage"), "mode": snapshot.get("mode"),
        "hint": snapshot.get("hint"), "stages": [{"stage": s.get("stage"), "label": s.get("label"), "status": s.get("status")} for s in snapshot.get("stages") or []],
    }


@tool("get_screenplay", title="查看剧本与审核状态", description="分集账本、每集审核状态（待审 / 已确认 / 草稿）与草稿原因。", effect="read")
def get_screenplay(*, service, user, task_id: str):
    review = service.get_screenwriting_review(task_id)
    ledger = service.get_ledger(task_id)
    return {"review": review, "ledger": {"entries": ledger.get("entries"), "unsplit": ledger.get("unsplit")}}


@tool("get_episode", title="查看一集的分镜", description="一集的分镜内容层（镜号、时长、场景、画面、口播）与违约。", effect="read",
      properties={"episode": {"type": "integer", "minimum": 1}}, required=["episode"])
def get_episode(*, service, user, task_id: str, episode: int):
    from app.service import screenwriting_service as screenwriting

    task = service.repo.get_task(task_id)
    response = screenwriting.episode_response(task, int(episode))
    if response is None:
        raise ToolError(f"第 {episode} 集没有结构化记录")
    data = response.model_dump()
    scenes = [{k: s.get(k) for k in ("scene_id", "duration_seconds", "setting", "scene_description", "utterances", "needs_replan")} for s in data["plan"].get("scenes") or []]
    return {"episode": data["episode"], "title": data["title"], "review": data["review"], "violations": data["violations"], "scenes": scenes}


@tool("get_shots", title="查看镜头工作区", description="第 4 / 5 阶段的镜头：运镜设置、片段、是否过期。", effect="read")
def get_shots(*, service, user, task_id: str):
    workspace = service.get_shot_visual_workspace(task_id) or {}
    shots = [{k: s.get(k) for k in ("shot_id", "scene_id", "settings", "video_url", "stale", "stale_reason")} for s in workspace.get("shots") or []]
    return {"provider_family": workspace.get("provider_family"), "running": workspace.get("running"), "shots": shots}


@tool("get_timeline", title="查看剪辑时间线", description="第 7 阶段时间线：每镜入出点、审看结论、转场、配乐。", effect="read")
def get_timeline(*, service, user, task_id: str):
    return service.get_timeline(task_id)


@tool("get_queue", title="查看生成队列", description="第 5 阶段生成队列：排队 / 运行 / 完成 / 失败项与各桶并发。", effect="read")
def get_queue(*, service, user, task_id: str):
    return service.get_generation_queue(task_id)


@tool("get_usage", title="查看费用台账", description="项目的供应商调用次数与按币种分列的费用。", effect="read")
def get_usage(*, service, user, task_id: str):
    return service.usage_summary(task_id, limit=20)


# ---------------------------------------------------------------------------- write tools


@tool("review_episode", title="确认或重新打开一集", description="把一集标为已确认，或撤回确认。", effect="write",
      properties={"episode": {"type": "integer", "minimum": 1}, "action": {"type": "string", "enum": ["confirm", "reopen"]}}, required=["episode", "action"])
def review_episode(*, service, user, task_id: str, episode: int, action: str):
    from app.core.screenwriting.review import ReviewError

    try:
        response = service.review_screenwriting_episode(task_id, int(episode), action, by=str(user.get("user_id") or "") or None)
    except ReviewError as exc:
        raise ValueError(str(exc)) from exc
    return {"episode": episode, "review": response.model_dump()["review"]}


@tool("edit_timeline", title="编辑剪辑时间线", description="裁剪、转场、字幕、静音、审看、片头、配乐之一；字段按 operation 取用。", effect="write",
      properties={
          "operation": {"type": "string", "enum": ["trim", "transition", "subtitle", "mute", "candidate", "review", "title", "bgm"]},
          "shot_id": {"type": "integer"}, "start": {"type": "number"}, "end": {"type": ["number", "null"]}, "kind": {"type": "string"},
          "duration": {"type": "number"}, "text": {"type": "string"}, "muted": {"type": "boolean"}, "video_url": {"type": "string"},
          "decision": {"type": "string", "enum": ["pending", "approved", "rejected"]}, "note": {"type": "string"},
          "source": {"type": "string", "enum": ["none", "generated", "library"]}, "library_id": {"type": "string"}, "volume": {"type": "number"},
      }, required=["operation"])
def edit_timeline(*, service, user, task_id: str, operation: str, **payload):
    from app.core.edit_timeline import TimelineError

    try:
        result = service.edit_timeline(task_id, operation, payload)
    except TimelineError as exc:
        raise ValueError(str(exc)) from exc
    return {"summary": result["summary"]}


@tool("get_stage_checks", title="查看一场的空间检查与修正建议", description="某场空间方案的检查结果（站位、入画、遮挡、轴线、朝向、姿态）和每条未通过项的自动修正操作。", effect="read",
      properties={"scene_id": {"type": "string", "description": "场景 ID，如 E1S02"}}, required=["scene_id"])
def get_stage_checks(*, service, user, task_id: str, scene_id: str):
    try:
        plan = service.get_spatial_plan(task_id, scene_id)
        repairs = service.get_spatial_repairs(task_id, scene_id)
    except LookupError as exc:
        raise ValueError(str(exc)) from exc
    checks = ((plan or {}).get("plan") or {}).get("checks") or []
    return {
        "revision": repairs["revision"],
        "checks": [{"code": c.get("code"), "passed": c.get("passed"), "severity": c.get("severity"), "detail": c.get("detail"), "shot_ids": c.get("shot_ids")} for c in checks],
        "repairs": repairs["repairs"], "automatic": repairs["automatic"], "manual": repairs["manual"],
    }


def _stage_edit(service, task_id: str, scene_id: str, operations: list, base_revision: int | None):
    from app.core.spatial_stage.operations import StageEditError
    from app.service.spatial_stage_service import StageConflict

    try:
        if base_revision is None:
            current = service.get_spatial_plan(task_id, scene_id)
            base_revision = int(((current or {}).get("plan") or {}).get("revision") or 0)
        result = service.patch_spatial_plan(task_id, scene_id, base_revision=int(base_revision), operations=list(operations), solve=False)
    except (LookupError, StageConflict, StageEditError) as exc:
        raise ValueError(str(exc)) from exc
    plan = (result or {}).get("plan") or {}
    failing = [c.get("code") for c in plan.get("checks") or [] if not c.get("passed")]
    return {"revision": plan.get("revision"), "failing_checks": failing}


@tool("edit_stage", title="编辑一场的空间调度", description="对某场的 3D 空间方案按序执行语义操作（站位、朝向、队形、机位、姿态、路径、阵列等），与导演台同一套操作；返回新版本号与仍未通过的检查。", effect="write",
      properties={
          "scene_id": {"type": "string"},
          "operations": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 100,
                         "description": "每项形如 {\"op\": \"move_actor\", ...}；支持的 op 见导演台操作目录（set_path 画路径、array_landmark 阵列、repair_checks 自动修正……）"},
          "base_revision": {"type": "integer", "description": "省略则以当前版本为准"},
      }, required=["scene_id", "operations"])
def edit_stage(*, service, user, task_id: str, scene_id: str, operations: list, base_revision: int | None = None):
    if not isinstance(operations, list) or not operations:
        raise ValueError("operations 必须是非空列表")
    return _stage_edit(service, task_id, scene_id, operations, base_revision)


@tool("repair_stage", title="自动修正一场的空间检查", description="把某场未通过的空间检查一次修正：拉开站位、转向对手、换回站位、重解机位、补上姿态；无法自动处理的项会在结果里说明。", effect="write",
      properties={"scene_id": {"type": "string"}, "codes": {"type": "array", "items": {"type": "string"}, "description": "只修这些检查代码；省略则全部"}},
      required=["scene_id"])
def repair_stage(*, service, user, task_id: str, scene_id: str, codes: list | None = None):
    operation = {"op": "repair_checks"}
    if codes:
        operation["codes"] = [str(code) for code in codes]
    outcome = _stage_edit(service, task_id, scene_id, [operation], None)
    try:
        left = service.get_spatial_repairs(task_id, scene_id)
    except LookupError as exc:
        raise ValueError(str(exc)) from exc
    outcome["manual"] = [item["manual"] for item in left["repairs"] if item.get("manual")]
    return outcome


@tool("cancel_queued", title="取消排队中的生成项", description="撤回第 5 阶段队列里还在排队的项（一项或全部）；运行中的不受影响。", effect="write",
      properties={"key": {"type": "string", "description": "省略则取消全部排队项"}})
def cancel_queued(*, service, user, task_id: str, key: str | None = None):
    from app.core.generation_queue import CancelError

    try:
        result = service.cancel_generation_item(task_id, key)
    except CancelError as exc:
        raise ValueError(str(exc)) from exc
    return {"counts": result.get("counts"), "withdraw": result.get("withdraw")}


@tool("pause_project", title="暂停或结束项目", description="当前阶段结束后暂停（或结束）后续制作。", effect="write",
      properties={"stop": {"type": "boolean", "default": False}})
def pause_project(*, service, user, task_id: str, stop: bool = False):
    task = service.pause_task(task_id, stop=bool(stop))
    return {"status": (task or {}).get("status")}


@tool("regenerate_shot", title="标记一镜重做", description="把一镜标为过期，下次第 5 阶段只重做它。", effect="write",
      properties={"shot_id": {"type": "integer"}, "reason": {"type": "string"}}, required=["shot_id"])
def regenerate_shot(*, service, user, task_id: str, shot_id: int, reason: str = ""):
    service.regenerate_shot(task_id, int(shot_id), reason=reason)
    return {"shot_id": shot_id, "stale": True}


# ---------------------------------------------------------------------------- paid tools


@tool("run_stage", title="执行一个阶段", description="启动第 N 阶段（1-8）；视频阶段会先过准入门禁。", effect="paid",
      properties={"stage": {"type": "integer", "minimum": 1, "maximum": 8}}, required=["stage"])
def run_stage(*, service, user, task_id: str, stage: int):
    claimed = service._claim_stage_task(task_id, int(stage))
    _start_background(service, task_id, int(stage), claimed, run_all=False)
    return {"started": True, "stage": int(stage)}


@tool("run_all", title="一键完成剩余阶段", description="从下一个未完成阶段起自动推进到成片。", effect="paid")
def run_all(*, service, user, task_id: str):
    task = service.repo.get_task(task_id)
    stage = service.workflow_snapshot(task).get("next_stage")
    if stage is None:
        raise ValueError("所有阶段都已完成")
    claimed = service._claim_stage_task(task_id, int(stage), automatic=True)
    _start_background(service, task_id, int(stage), claimed, run_all=True)
    return {"started": True, "from_stage": int(stage)}


@tool("repair_episode", title="AI 修复一集草稿", description="让模型带着违约原因重写一集；修复没有改善则保留原草稿。", effect="paid",
      properties={"episode": {"type": "integer", "minimum": 1}}, required=["episode"])
def repair_episode(*, service, user, task_id: str, episode: int):
    response = service.repair_screenwriting_episode(task_id, int(episode), owner_user_id=str(user.get("user_id") or ""), is_admin=user.get("role") == "admin")
    data = response.model_dump()
    return {"episode": episode, "repair": data.get("repair"), "review": data.get("review")}


@tool("render_timeline", title="按时间线重新合成", description="按当前剪辑时间线重新合成成片（本机 ffmpeg，不调模型，但耗时）。", effect="paid")
def render_timeline(*, service, user, task_id: str):
    return service.render_timeline(task_id)


def _start_background(service, task_id: str, stage: int, claimed: dict, *, run_all: bool) -> None:
    """Start the stage the way the assistant does: on the running loop when there is one, else on a thread."""
    import asyncio
    import threading

    async def go():
        try:
            if run_all:
                await service.execute_all_stages(task_id, _first_claimed=claimed)
            else:
                await service.execute_stage(task_id, stage, _claimed_task=claimed)
        except Exception as exc:  # noqa: BLE001 - the stage records its own failure on the task
            service.logger_error("[AgentTools] 后台阶段失败: %s", str(exc)[:200]) if hasattr(service, "logger_error") else None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.create_task(go())
    else:
        threading.Thread(target=lambda: asyncio.run(go()), name=f"agent-stage-{stage}", daemon=True).start()


__all__ = ["EFFECTS", "Tool", "ToolCatalog", "ToolError", "catalog", "tool"]

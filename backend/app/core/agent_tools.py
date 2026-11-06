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
from app.core import usage_ledger
from app.platform.access_audit import record_access_from_thread
from app.platform.permissions import PROJECT_READ_ANY, PROJECT_WRITE_ANY, authorize, has_permission

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
            if owner:
                write = tool.effect != "read"
                decision = authorize(user, owner_id=owner, write=write)
                if not decision.allowed:
                    raise ToolError(f"项目 {task_id} 不属于当前用户")
                if decision.cross_account:
                    record_access_from_thread(user, resource_id=task_id, owner_id=owner, write=write, via=f"agent.{name}")
        if tool.effect == "paid" and not args.get("confirm"):
            return {"ok": False, "needs_confirmation": True, "tool": name, "arguments": {k: v for k, v in args.items() if k != "confirm"},
                    "message": f"「{tool.title}」会调用付费模型；确认后再执行（confirm=true）"}
        args.pop("confirm", None)
        # A model gets the shape of a tool wrong; that is an answer for it to act on, not a crash of the turn.
        schema = tool.input_schema
        missing = [key for key in schema.get("required") or [] if key not in args and key != "confirm"]
        unknown = [key for key in args if key not in schema.get("properties", {})]
        if missing or unknown:
            problems = ([f"缺少参数 {'、'.join(missing)}"] if missing else []) + ([f"没有参数 {'、'.join(unknown)}"] if unknown else [])
            return {"ok": False, "error": "；".join(problems)}
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
        if not has_permission(user, PROJECT_READ_ANY) and str(task.get("owner_user_id") or "") != user_id:
            continue
        config = task.get("config") if isinstance(task.get("config"), dict) else {}
        rows.append({"task_id": task.get("task_id"), "title": config.get("title_suggestion"), "status": task.get("status"),
                     "current_stage": task.get("current_stage"), "episode_count": config.get("episode_count")})
    return {"projects": rows[-int(limit):]}


_POETRY_FORMS = ["诗", "词", "曲", "文", "经"]


@tool("search_poetry", title="检索诗词库", effect="read", needs_task=False,
      description="在诗词库里按关键词、作者、题旨、情绪或体裁找古典诗词文章，返回篇名、名句和短剧里的用法。要全文用 get_poem。",
      properties={
          "query": {"type": "string", "description": "关键词，如 离别、明月、壮志未酬；可空"},
          "author": {"type": "string", "description": "作者或别名，如 苏东坡、易安"},
          "theme": {"type": "string"}, "emotion": {"type": "string"},
          "form": {"type": "string", "enum": _POETRY_FORMS},
          "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
      })
def search_poetry(*, service, user, query: str = "", author: str = "", theme: str = "", emotion: str = "", form: str = "", limit: int = 10):
    from app.core import poetry_library

    found = poetry_library.search(query, author=author, theme=theme, emotion=emotion, form=form, limit=limit)
    return {"items": [poetry_library.summary(poem) for poem in found], "count": len(found)}


@tool("get_poem", title="取诗词全文", effect="read", needs_task=False,
      description="取一篇诗词文章的全文、小序、背景与版权提示。传 search_poetry 返回的 id，或篇名（可加作者）。引用时逐字照抄这里的文字。",
      properties={
          "id": {"type": "string", "description": "形如 sushi/nian-nu-jiao-chibi-huai-gu"},
          "title": {"type": "string", "description": "篇名，如 岳阳楼记、念奴娇·赤壁怀古"},
          "author": {"type": "string"},
      })
def get_poem(*, service, user, id: str = "", title: str = "", author: str = ""):
    from app.core import poetry_library

    if id:
        return poetry_library.detail(poetry_library.library().get(id))  # an unknown id comes back as the tool's error
    if not title:
        raise ValueError("请给出 id 或篇名")
    matches = poetry_library.find_titled(title, author=author)
    if not matches:
        raise LookupError(f"诗词库里没有《{title}》" + (f"（{author}）" if author else ""))
    if len(matches) > 1:
        return {"ambiguous": [poetry_library.summary(poem) for poem in matches[:10]]}
    return poetry_library.detail(matches[0])


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
    shots = [{k: s.get(k) for k in ("shot_id", "scene_id", "shot_uid", "settings", "video_url", "stale", "stale_reason")} for s in workspace.get("shots") or []]
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
                         "description": "每项形如 {\"op\": \"move_actor\", ...}；常用 op 与参数见 describe_stage 返回的 operations（另有 set_path 画路径、array_landmark 阵列、set_timeline 关键帧……）"},
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


@tool("regenerate_shot", title="标记一镜重做", description="把一镜所在的那段视频标为过期，下次第 5 阶段只重做它(分镜片段视频连同同场的其他瞬间一起重做)。", effect="write",
      properties={"shot_id": {"type": "integer"},
                  "scene_id": {"type": "string", "description": "镜头所在场次(如 E1S03)；各场镜号都从 1 起，务必给出"},
                  "shot_uid": {"type": "integer", "description": "全剧唯一的镜头编号(视觉工作区里的 shot_uid)，给了就按它找"},
                  "reason": {"type": "string"}}, required=["shot_id"])
def regenerate_shot(*, service, user, task_id: str, shot_id: int, reason: str = "", scene_id: str = "", shot_uid: int | None = None):
    service.regenerate_shot(task_id, int(shot_id), reason=reason, scene_id=str(scene_id or ""), shot_uid=int(shot_uid) if shot_uid else None)
    return {"shot_id": shot_id, "scene_id": scene_id, "stale": True}


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
    response = service.repair_screenwriting_episode(task_id, int(episode), owner_user_id=str(user.get("user_id") or ""), is_admin=has_permission(user, PROJECT_WRITE_ANY))
    data = response.model_dump()
    return {"episode": episode, "repair": data.get("repair"), "review": data.get("review")}


@tool("render_timeline", title="按时间线重新合成", description="按当前剪辑时间线重新合成成片（本机 ffmpeg，不调模型，但耗时）。", effect="paid")
def render_timeline(*, service, user, task_id: str):
    return service.render_timeline(task_id)


# ---------------------------------------------------------------------------- Blender 3D 预演台

#: 编辑站位与机位时最常用的语义操作；完整目录见导演台。坐标：地面点 [x, z] 米，y 为高度；yaw 0 面向 +Z、90 面向 +X。
STAGE_OP_CHEATSHEET = (
    "move_actor {name, position:[x,z], yaw_deg?, posture?(stand/walk/run/fight/sit/crouch/kneel/lie/bow/lean)}；"
    "orient_toward {name, target:\"另一人的名字\"}（面向某人）或 orient_toward {name, position:[x,z]}（面向地面某点；面向镜头就填机位的 [x,z]）——"
    "坐标只能放在 position，target 只能是人名；face_pair {first, second, distance?}；"
    "「画面左/右」取决于机位朝向：先看机位 position 与 target，再换算成地面坐标；"
    "set_shot_override {shot_id, name, position?, yaw_deg?, posture?, offstage?, hold?}（只改某一镜：入场、倒地、离场）；"
    "move_camera {camera_id, position:[x,y,z], target:[x,y,z], lens_mm?}；use_camera {shot_id, camera_id}；"
    "frame_shot {shot_id, size: 大特写/特写/近景/中近景/中景/中全景/全景/远景/大远景}；"
    "apply_camera_move {shot_id, preset: push/pull/truck/rise/descend/arc/arc-push/crane-reveal/ground-rise/whip-pan/"
    "push-pause/dolly-zoom/roll-recover/reframe, amplitude?(0.05–3), angle?, side?}；"
    "add_landmark {name, kind?(prop/furniture/architecture/light), position:[x,z], size:[宽,深,高], elevation_m?}；move_landmark {name, position}；"
    "move_camera 还可带 sensor_mm（传感器长边，全画幅 36、Super35 24.89）；"
    "set_timeline {shot_id, clips?:{人物名:[{id, clip, start, end}]}, follow?:[{id, actor, start, end, offset?:[右,上,后], aim?}]}（人物动作片段与跟拍片段）；"
    "set_path {shot_id, target, points, speed_mps?, clip?}（按速度走完路径，并同时铺上动作）；"
    "set_timeline 的 cuts?:[{id, camera_id, start, end}] 在一镜之内切到候选机位（camera_id 须是本镜的机位或候选）；"
    "repair_checks {}（自动修正未通过的空间检查）；"
    "add_landmark 还可带 kit（内置模型库 id，如 desk / sedan / pavilion）或 parts（体块列表）做成组合模型；"
    "auto_route {shot_id, name, to:[x,z], speed_mps?}（自动绕开布景走到终点）；best_camera {shot_id?, alternates?}（在当前机位附近搜索更好的视角）；"
    "set_pose {name, preset, shot_id?}（四肢要先 set_figure {name, figure:\"mannequin\"} 才看得见）"
)


def _previz():
    from app.service import blender_previz_service

    return blender_previz_service


def _previz_call(fn, *args, **kwargs):
    previz = _previz()
    try:
        return fn(*args, **kwargs)
    except previz.PrevizError as exc:
        raise ValueError(str(exc)) from exc


@tool("describe_stage", title="读出一场的站位与机位", description="某场 3D 空间方案的当前状态：人物站位朝向姿态、道具、每台摄影机的位置/目标/焦段、每镜用哪台机，以及编辑用的常用操作说明。改站位、改机位前先看它。", effect="read",
      properties={"scene_id": {"type": "string"}}, required=["scene_id"])
def describe_stage(*, service, user, task_id: str, scene_id: str):
    from app.service import spatial_stage_service

    task = service.repo.get_task(task_id)
    plan = spatial_stage_service.load_plan(task or {}, scene_id)
    if plan is None:
        raise ValueError(f"场景 {scene_id} 还没有空间方案")
    return {
        "scene_id": scene_id, "revision": plan.revision, "aspect_ratio": plan.aspect_ratio, "location": plan.location,
        "actors": [{"name": a.name, "position": a.position, "yaw_deg": a.yaw_deg, "posture": a.posture, "height_m": a.height_m}
                   for a in plan.actors if not a.crowd_id][:40],
        "crowds": [{"id": c.id, "label": c.label, "rows": c.rows, "columns": c.columns} for c in plan.crowds],
        "landmarks": [{"name": l.name, "kind": l.kind, "position": l.position, "size": l.size} for l in plan.landmarks][:60],
        "cameras": [{"id": c.id, "position": c.position, "target": c.target, "lens_mm": c.lens_mm, "shot_size": c.shot_size, "move": c.move.kind}
                    for c in plan.cameras][:40],
        "shots": [{"shot_id": s.shot_id, "camera_id": s.camera_id, "subjects": s.subjects, "action": s.action[:120],
                   "timeline": str(s.shot_id) in plan.timelines} for s in plan.shots][:80],
        "failing_checks": [c.code for c in plan.checks if not c.passed],
        "operations": STAGE_OP_CHEATSHEET,
    }


@tool("auto_plan_stage", title="模型规划一场的调度方案", description="让文本模型一次给出几版完整调度（布景、站位、姿势、机位、运动），修正、评分并与规则方案比较，推荐最佳；舞台不变，再用 adopt_stage_plan 采用其中一版。每版消耗一到两次文本调用。", effect="paid",
      properties={"scene_id": {"type": "string"}, "count": {"type": "integer", "minimum": 1, "maximum": 3}, "goal": {"type": "string", "description": "导演的额外要求，可省略"}},
      required=["scene_id"])
def auto_plan_stage(*, service, user, task_id: str, scene_id: str, count: int = 3, goal: str = ""):
    from app.service import spatial_stage_service, stage_director_service

    task = service.repo.get_task(task_id) or {}
    plan = spatial_stage_service.load_plan(task, scene_id)
    outcome = stage_director_service.plan_scene(
        service, task_id, scene_id, base_revision=plan.revision if plan is not None else 0, count=count, goal=goal,
    )
    return {
        **{key: outcome[key] for key in ("recommended", "used_model", "note", "current")},
        "candidates": [{key: item[key] for key in ("id", "title", "rationale", "source", "score", "errors")} for item in outcome["candidates"]],
        "next": "调用 adopt_stage_plan 采用其中一版",
    }


@tool("adopt_stage_plan", title="采用一版调度方案", description="把 auto_plan_stage 给出的一版方案放到舞台上；可以在导演台撤销。", effect="write",
      properties={"scene_id": {"type": "string"}, "candidate_id": {"type": "string"}}, required=["scene_id", "candidate_id"])
def adopt_stage_plan(*, service, user, task_id: str, scene_id: str, candidate_id: str):
    from app.service import spatial_stage_service, stage_director_service

    plan = spatial_stage_service.load_plan(service.repo.get_task(task_id) or {}, scene_id)
    outcome = stage_director_service.adopt_candidate(
        service, task_id, scene_id, candidate_id=candidate_id, base_revision=plan.revision if plan is not None else 0,
    )
    return {"revision": outcome["plan"]["revision"], "failing_checks": [c["code"] for c in outcome["plan"]["checks"] if not c["passed"]]}


@tool("build_stage_model", title="搭一个白模", description="按描述搭一件东西（模型库有的直接用，没有的让文本模型用体块搭），放到舞台上。", effect="paid",
      properties={
          "scene_id": {"type": "string"}, "description": {"type": "string"},
          "position": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2, "description": "地面点 [x, z]"},
          "yaw_deg": {"type": "number"}, "name": {"type": "string", "description": "舞台上的名字，默认按模型命名"},
      }, required=["scene_id", "description", "position"])
def build_stage_model(*, service, user, task_id: str, scene_id: str, description: str, position: list, yaw_deg: float = 0.0, name: str = ""):
    from app.service import stage_director_service

    proposal = stage_director_service.propose_model(service, task_id, scene_id, description=description)
    operation = {
        "op": "add_landmark", "name": (name or proposal["name"])[:120], "kind": proposal["kind"], "position": position, "yaw_deg": yaw_deg,
        "size": proposal["size"], "kit": proposal["kit"], "fitted_parts": proposal["parts"],
    }
    outcome = _stage_edit(service, task_id, scene_id, [operation], None)
    return {**outcome, "model": {key: proposal[key] for key in ("name", "kit", "size", "summary")}, "parts": len(proposal["parts"])}


@tool("get_project_memory", title="查看项目记忆", description="这个项目记住的偏好、决定和设定。", effect="read")
def get_project_memory(*, service, user, task_id: str):
    view = service.project_memory_view(task_id)
    return {"entries": [{key: row.get(key) for key in ("id", "text", "kind", "pinned", "source")} for row in (view or {}).get("entries", [])]}


@tool("remember_in_project", title="记住一件事", description="把以后都要遵守的偏好、决定或设定记进项目记忆。", effect="write",
      properties={"text": {"type": "string"}, "kind": {"type": "string", "enum": ["preference", "decision", "fact"]}}, required=["text"])
def remember_in_project(*, service, user, task_id: str, text: str, kind: str = "decision"):
    from app.core import project_memory

    return {"entries": len((service.edit_project_memory(task_id, lambda task: project_memory.add(task, text, kind=kind, source="user")) or {}).get("entries", []))}


@tool("forget_in_project", title="忘记一件事", description="删除项目记忆里的一条。", effect="write",
      properties={"memory_id": {"type": "string"}}, required=["memory_id"])
def forget_in_project(*, service, user, task_id: str, memory_id: str):
    from app.core import project_memory

    try:
        return {"entries": len((service.edit_project_memory(task_id, lambda task: project_memory.remove(task, memory_id)) or {}).get("entries", []))}
    except project_memory.MemoryError as exc:
        raise ValueError(str(exc)) from exc


@tool("blender_status", title="Blender 预演台状态", description="本机有没有 Blender、版本号，以及打开的 Blender 是否已连上实时桥接插件。", effect="read", needs_task=False)
def blender_status(*, service, user):
    return _previz().status()


@tool("get_blender_previz", title="读一场的 Blender 预演", description="某场最近一次 Blender 白模预演：视频、每镜首帧、镜头段帧号、是否已因站位修改而过期，以及手持/空段设置。", effect="read",
      properties={"scene_id": {"type": "string"}}, required=["scene_id"])
def get_blender_previz(*, service, user, task_id: str, scene_id: str):
    return _previz().get_previz(service.repo.get_task(task_id) or {}, scene_id)


@tool("render_blender_previz", title="用 Blender 渲染白模预演", description="把某场的站位、机位与切镜在本机 Blender 里搭成彩色白模并渲染成连续预演视频(每镜一段硬切)和每镜首帧；本机渲染不花模型额度。改完站位/机位后调用它看效果；打开的 Blender 若连着插件会同步刷新。", effect="write",
      properties={"scene_id": {"type": "string"},
                  "shot_ids": {"type": "array", "items": {"type": "integer"}, "description": "只渲这些镜；省略则整场"},
                  "long_edge": {"type": "integer", "minimum": 480, "maximum": 3840, "default": 1920, "description": "长边像素；试看可用 960"}},
      required=["scene_id"])
def render_blender_previz(*, service, user, task_id: str, scene_id: str, shot_ids: list | None = None, long_edge: int = 1920):
    result = _previz_call(_previz().render_scene, service, task_id, scene_id,
                          shot_ids=[int(v) for v in shot_ids] if shot_ids else None, long_edge=int(long_edge))
    return {key: result[key] for key in ("video_url", "stills", "segments", "frames", "fps", "resolution", "reused", "live", "plan_revision")}


@tool("set_previz_options", title="设置预演的手持与空段", description="让某些镜头用真实手持(低频摆动+微震)，或给雷光、液体、粒子等专项效果在镜头里留空段；下一次渲染生效。", effect="write",
      properties={"scene_id": {"type": "string"},
                  "handheld_shots": {"type": "array", "items": {"type": "integer"}, "description": "用手持的镜号；传空数组取消全部手持"},
                  "reserved": {"type": "array", "items": {"type": "object", "properties": {
                      "shot_id": {"type": "integer"}, "from_s": {"type": "number"}, "to_s": {"type": "number"}, "label": {"type": "string"}}},
                      "description": "空段列表(整体替换)"}},
      required=["scene_id"])
def set_previz_options(*, service, user, task_id: str, scene_id: str, handheld_shots: list | None = None, reserved: list | None = None):
    return _previz_call(_previz().set_options, service, task_id, scene_id, handheld_shots=handheld_shots, reserved=reserved)


@tool("attach_previz_to_shots", title="把预演交给分镜当运动参考", description="把最近一次 Blender 预演按镜头切片，登记为这些镜的运动参考视频：第 5 阶段出片时由它管机位、切点与时间，角色设定集只管外观。站位改过就要先重新渲染。", effect="write",
      properties={"scene_id": {"type": "string"}, "shot_ids": {"type": "array", "items": {"type": "integer"}, "description": "省略则整场"}},
      required=["scene_id"])
def attach_previz_to_shots(*, service, user, task_id: str, scene_id: str, shot_ids: list | None = None):
    return _previz_call(_previz().attach_to_shots, service, task_id, scene_id, shot_ids=shot_ids)


@tool("push_to_blender", title="推到打开的 Blender", description="在你本机打开的 Blender 里按当前方案重建预演场景(需启用桥接插件并点「开始连接」)，不渲染。", effect="write",
      properties={"scene_id": {"type": "string"}}, required=["scene_id"])
def push_to_blender(*, service, user, task_id: str, scene_id: str):
    return _previz_call(_previz().push_live, service, task_id, scene_id)


@tool("pull_from_blender", title="从 Blender 同步回方案", description="读回你在 Blender 里拖动过的人物、道具与摄影机位置，换成方案操作；apply=true 才写回方案，否则只列出会改什么。", effect="write",
      properties={"scene_id": {"type": "string"}, "apply": {"type": "boolean", "default": False}}, required=["scene_id"])
def pull_from_blender(*, service, user, task_id: str, scene_id: str, apply: bool = False):
    return _previz_call(_previz().pull_live, service, task_id, scene_id, apply=bool(apply))


# ---------------------------------------------------------------------------- 分镜故事板(第 4 阶段)的场景工具栏

#: 分镜故事板里可以打开的视图，与工具栏按钮一一对应。
STORYBOARD_VIEWS = {
    "board": "九宫格分镜本身", "prompt": "查看提示词", "spatial": "空间调度", "desk": "3D 导演台",
    "blender": "3D 导演台里的 Blender 预演", "packages": "提示词分包", "sheets": "资产设定图", "download": "下载本图",
}


def _compact(value: Any, limit: int = 3500) -> Any:
    """工具结果给模型读：太长的就截断成文本，免得一个结果吃掉整轮上下文。"""
    import json as _json

    text = _json.dumps(value, ensure_ascii=False, default=str)
    return value if len(text) <= limit else {"truncated": True, "preview": text[:limit]}


def _board_entry(service, task_id: str, scene_id: str) -> tuple[dict, dict]:
    task = service.repo.get_task(task_id) or {}
    boards = (task.get("assets") or {}).get("4_scene_boards") or {}
    entry = boards.get(scene_id)
    if not isinstance(entry, dict):
        known = "、".join(list(boards)[:12]) or "无"
        raise ValueError(f"分镜里没有场景 {scene_id}；已有：{known}")
    return task, entry


@tool("get_scene_board", title="读一场的九宫格分镜", description="某场分镜的状态(待创作/生成中/已完成/失败及原因)、每个画格的景别、画面、台词与图片地址，以及整张九宫格图的下载地址。", effect="read",
      properties={"scene_id": {"type": "string", "description": "如 E1S01"}}, required=["scene_id"])
def get_scene_board(*, service, user, task_id: str, scene_id: str):
    task, entry = _board_entry(service, task_id, scene_id)
    shots = [shot for shot in (task.get("assets") or {}).get("4") or []
             if isinstance(shot, dict) and str(shot.get("scene_id") or "") == scene_id]
    return {
        "scene_id": scene_id, "episode": entry.get("episode"), "status": entry.get("status"),
        "error": entry.get("error") or "", "shots_done": entry.get("shots_done"), "shots_total": entry.get("shots_total"),
        "board_image": entry.get("grid_image_url") or entry.get("image_url") or "",
        "download_url": f"/api/drama/{task_id}/storyboard/download?target=scene&scene={scene_id}",
        "shots": [{"shot_id": shot.get("shot_id"), "size": shot.get("size"), "desc": str(shot.get("desc") or "")[:90],
                   "dialogue": shot.get("dialogue") or "", "duration": shot.get("duration"), "image_url": shot.get("image_url") or ""}
                  for shot in shots][:12],
    }


@tool("get_scene_prompt", title="读一场的分镜提示词", description="某场九宫格分镜的生图提示词与提示词明细(工具栏「查看提示词」的内容)。", effect="read",
      properties={"scene_id": {"type": "string"}}, required=["scene_id"])
def get_scene_prompt(*, service, user, task_id: str, scene_id: str):
    _, entry = _board_entry(service, task_id, scene_id)
    detail, prompt = entry.get("prompt_detail"), entry.get("grid_prompt") or ""
    if not detail and not prompt:
        raise ValueError(f"{scene_id} 的提示词尚未生成；完成本场分镜生成后才有")
    return _compact({"scene_id": scene_id, "grid_prompt": prompt, "prompt_detail": detail})


@tool("get_prompt_packages", title="生成提示词分包", description="把已定稿的分镜重新切成可直接粘贴的 Seedance 提示词分包(工具栏「提示词分包」)；只重组不调模型。", effect="read",
      properties={"scene_id": {"type": "string", "description": "留空则整集"},
                  "package_seconds": {"type": "integer", "enum": [10, 15, 20, 30], "default": 15},
                  "variant": {"type": "string", "enum": ["standard", "continuous", "fight", "script_doc"], "default": "standard"},
                  "delivery": {"type": "string", "enum": ["正常", "急切", "沉重"], "default": "正常"}})
def get_prompt_packages(*, service, user, task_id: str, scene_id: str = "", package_seconds: int = 15, variant: str = "standard", delivery: str = "正常"):
    payload = service.compile_prompt_packages(task_id, scene_id=scene_id, package_seconds=int(package_seconds), variant=variant, delivery=delivery)
    return _compact(payload or {})


@tool("get_asset_sheets", title="读资产设定图", description="人物 / 场景 / 道具 / 色板四类设定图：识别锚点、可直接生成的提示词与版式(工具栏「资产设定图」)。", effect="read")
def get_asset_sheets(*, service, user, task_id: str):
    return _compact(service.compile_asset_sheets(task_id) or {})


@tool("redraw_scene", title="把一场送回重画", description="把某场分镜标回待生成并清掉它的旧画格，下一次运行第 4 阶段时只按当前站位重画这一场(本身不花钱；真正重画要再 run_stage 4，需用户确认)。", effect="write",
      properties={"scene_id": {"type": "string"}}, required=["scene_id"])
def redraw_scene(*, service, user, task_id: str, scene_id: str):
    result = service.redraw_spatial_scene(task_id, scene_id)
    if result is None:
        raise ValueError(f"场景 {scene_id} 还没有分镜，无需重画")
    return {"scene_id": scene_id, "status": "pending", "next": "调用 run_stage(stage=4) 重画(付费，需用户确认)"}


@tool("open_storyboard_view", title="在界面上打开分镜视图", description="在用户的分镜故事板界面上选中某场并打开对应视图：board 九宫格 / prompt 查看提示词 / spatial 空间调度 / desk 3D 导演台 / blender Blender 预演 / packages 提示词分包 / sheets 资产设定图 / download 下载本图。用户说「打开」「给我看」「下载」时用它。", effect="read",
      properties={"scene_id": {"type": "string"}, "view": {"type": "string", "enum": list(STORYBOARD_VIEWS)}}, required=["scene_id", "view"])
def open_storyboard_view(*, service, user, task_id: str, scene_id: str, view: str):
    if view not in STORYBOARD_VIEWS:
        raise ValueError(f"view 只能是：{'、'.join(STORYBOARD_VIEWS)}")
    _board_entry(service, task_id, scene_id)
    return {"ui_action": {"type": "storyboard_view", "scene_id": scene_id, "view": view},
            "message": f"已在界面上打开 {scene_id} 的「{STORYBOARD_VIEWS[view]}」"}


# ---------------------------------------------------------------------------- 节点画布


def _canvas_project(service, user, task_id: str) -> tuple[Any, str, str]:
    """The studio service, and the project and owner this person's canvases for the task live under."""
    from app.api.studio_api import get_studio_service

    studio = get_studio_service()
    task = service.repo.get_task(task_id) or {}
    owner = str(user.get("user_id") or task.get("owner_user_id") or "")
    title = str((task.get("config") or {}).get("title_suggestion") or "画布")
    return studio, studio.repository.project_for_task(task_id, owner, title).id, owner


def _canvas_call(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    from app.repository.studio_repo import ConcurrencyError

    try:
        return fn(*args, **kwargs)
    except ConcurrencyError as exc:
        raise ValueError(f"画布已被别处修改，先重新读取：{exc}") from exc
    except PermissionError as exc:
        raise ValueError("没有这个画布") from exc


CANVAS_OP_CHEATSHEET = (
    "add_node {ref?, kind(image_gen/video_gen/audio_gen/video_compose/note/media/style_ref/panorama/previz/group/tool), label?, prompt?, text?, styleText?, "
    "sceneId?, shotId?, params?{model?, durationSeconds?, size?, mode?, tool?}, x?, y?}（kind=tool 时 params.tool 选工具，见 list_canvas_tools）；"
    "connect {source, target, role?}（source、target 可以是节点 id，也可以是本次 add_node 的 ref；image→video_gen 的 role 可选 ref_image/first_frame/last_frame；video→video_gen 的 role 可选 ref_video，或 continue_from（同一连续镜头的后一段：首帧接前一段尾帧，不同镜头之间不要用；后一段的 prompt 先写上一段的结束状态再写下一步；复杂动作按 起始姿态→主动作→身体联动→结束姿态 写，或先用 action_breakdown 工具拆）；"
    "update_node {id, label?, prompt?, text?, styleText?, sceneId?, shotId?, params?, x?, y?}；delete_node {id}；disconnect {source, target}；group {ids, label?}"
)


@tool("get_canvas", title="读节点画布", description="当前项目某张画布的概况：画布列表、版本号、各类节点数量、每个节点的提示词/输入/结果/最近一次运行，以及连线。总结画布、改画布之前先看它。", effect="read",
      properties={"canvas_id": {"type": "string", "description": "画布 id，省略则为主画布"}})
def get_canvas(*, service, user, task_id: str, canvas_id: str = "main"):
    studio, project_id, owner = _canvas_project(service, user, task_id)
    result = _canvas_call(studio.summarize_canvas, project_id, owner, canvas_id=str(canvas_id))
    return {**_compact(result, 9000), "operations": CANVAS_OP_CHEATSHEET}


@tool("list_canvas_tools", title="列出画布工具", description="画布工具节点能用的工具（重绘、扩图、打光、放大、擦除、抽帧、镜头分析、拍点规划……）：每个工具吃什么输入、产出什么、由谁处理、要不要钱；以及风格转绘可选的风格。", effect="read", needs_task=False)
def list_canvas_tools(*, service, user):
    from app.core import canvas_tools

    return {
        "tools": canvas_tools.describe_catalog(),
        "styles": [{"id": look.id, "name": look.names["zh"], "group": look.group} for look in canvas_tools.style_wall()],
    }


@tool("edit_canvas", title="编辑节点画布", description="在画布上加节点、连线、改节点、删节点、分组。一次请求的全部操作作为一个事务生效：只产生一个新版本，任何一步不合法则全部不生效。不花钱，运行节点要另外确认。", effect="write",
      properties={
          "canvas_id": {"type": "string"},
          "operations": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 100, "description": CANVAS_OP_CHEATSHEET},
          "base_version": {"type": "integer", "description": "基于哪一版修改；给了且画布已变化则拒绝"},
      }, required=["operations"])
def edit_canvas(*, service, user, task_id: str, operations: list, canvas_id: str = "main", base_version: int | None = None):
    if not isinstance(operations, list) or not operations or not all(isinstance(item, Mapping) for item in operations):
        raise ValueError("operations 必须是非空的对象列表")
    studio, project_id, owner = _canvas_project(service, user, task_id)
    return _canvas_call(studio.edit_canvas, project_id, owner, operations, canvas_id=str(canvas_id), base_version=base_version)


def _workflows(service, user, task_id: str) -> tuple[Any, str, str]:
    from app.service.canvas_workflow_service import CanvasWorkflowService

    studio, project_id, owner = _canvas_project(service, user, task_id)
    return CanvasWorkflowService(studio), project_id, owner


@tool("plan_canvas_workflow", title="规划画布工作流", description="把一段创作需求规划成画布上的一条流程（每步一个节点，连好线），存成草稿给用户看，不改画布、不运行。调用一次文本模型。返回 workflow id、步骤和问题。", effect="paid",
      properties={"brief": {"type": "string", "description": "用户的创作需求"}, "canvas_id": {"type": "string"}}, required=["brief"])
def plan_canvas_workflow(*, service, user, task_id: str, brief: str, canvas_id: str = "main"):
    workflows, project_id, owner = _workflows(service, user, task_id)
    return _compact(_canvas_call(workflows.plan, project_id, owner, canvas_id=str(canvas_id), brief=str(brief), drama=service, user=user), 9000)


@tool("apply_canvas_workflow", title="把工作流铺到画布", description="把用户看过的工作流草稿铺到画布上：全部步骤作为一次修改生效，不运行、不花钱。之后用 canvas_workflow_status 取 runnable，用 quote_canvas_run 报价，再用 run_canvas_nodes 运行。", effect="write",
      properties={"workflow_id": {"type": "string"}}, required=["workflow_id"])
def apply_canvas_workflow(*, service, user, task_id: str, workflow_id: str):
    workflows, project_id, owner = _workflows(service, user, task_id)
    return _compact(_canvas_call(workflows.apply, project_id, owner, str(workflow_id)), 6000)


@tool("canvas_workflow_status", title="查看工作流进度", description="工作流每一步的状态、失败原因，以及 runnable（还需要运行的节点 id：没开始的、失败的、被跳过的；已完成的不在里面，所以失败后重跑不会重复花钱）。", effect="read",
      properties={"workflow_id": {"type": "string"}}, required=["workflow_id"])
def canvas_workflow_status(*, service, user, task_id: str, workflow_id: str):
    workflows, project_id, owner = _workflows(service, user, task_id)
    return _compact(_canvas_call(workflows.status, project_id, owner, str(workflow_id)), 6000)


@tool("quote_canvas_run", title="估算运行画布节点的费用", description="不运行，只说这些节点能不能跑、缺什么、要不要确认时长档位、大约多少钱。", effect="read",
      properties={"canvas_id": {"type": "string"}, "node_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 50}}, required=["node_ids"])
def quote_canvas_run(*, service, user, task_id: str, node_ids: list, canvas_id: str = "main"):
    studio, project_id, owner = _canvas_project(service, user, task_id)
    return _compact(_canvas_call(studio.assess_canvas_run, project_id, owner, canvas_id=str(canvas_id), node_ids=[str(v) for v in node_ids], confirmed=None, drama=service, user=user))


@tool("run_canvas_nodes", title="运行画布节点", description="按当前已保存的画布生成这些节点（图像、视频、音频、合成），进入生成队列；先过准入，同批有一个不能跑就全部不跑。", effect="paid",
      properties={"canvas_id": {"type": "string"}, "node_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 50},
                  "confirmed_request_durations": {"type": "array", "items": {"type": "object"}, "description": "用户已接受的 {scripted_seconds, requested_seconds} 时长档位"}},
      required=["node_ids"])
def run_canvas_nodes(*, service, user, task_id: str, node_ids: list, canvas_id: str = "main", confirmed_request_durations: list | None = None):
    import uuid

    studio, project_id, owner = _canvas_project(service, user, task_id)
    version = _canvas_call(studio.repository.latest_canvas_version, project_id, owner, canvas_id=str(canvas_id))
    outcome = _canvas_call(
        studio.start_canvas_run, project_id, owner, canvas_id=str(canvas_id), node_ids=[str(v) for v in node_ids], expected_version=version,
        operation_id=f"agent:{uuid.uuid4().hex}", confirm=True,
        confirmed=[{"scripted_seconds": int(item.get("scripted_seconds") or 0), "requested_seconds": int(item.get("requested_seconds") or 0)} for item in confirmed_request_durations or []],
        drama=service, user=user,
    )
    return _compact({key: outcome[key] for key in ("status", "batch_id", "assessment") if key in outcome})


# ---------------------------------------------------------------------------- recipe catalog


@tool("list_recipes", title="查配方库", description="通用提示词配方：短剧关键场面、电商图、社媒图、通用图片 / 视频 / 音频。可按类别、产出类型或关键词筛选，返回每个配方需要的输入。", effect="read", needs_task=False,
      properties={
          "category": {"type": "string", "enum": ["short_drama", "ecommerce_image", "social_image", "general_image", "general_video", "general_audio"]},
          "output_type": {"type": "string", "enum": ["image", "video", "audio"]},
          "query": {"type": "string", "description": "按名称或说明里的关键词筛选"},
      })
def list_recipes(*, service, user, category: str = "", output_type: str = "", query: str = ""):
    from app.core import recipe_catalog

    return recipe_catalog.catalog().describe(category=category, output_type=output_type, query=query)


@tool("render_recipe", title="填写配方", description="把输入填进配方，得到可用的提示词、负面词和建议参数。只生成文字，不调用任何模型、不花钱；要出图或出片需再走付费工具。", effect="read", needs_task=False,
      properties={
          "recipe_id": {"type": "string"},
          "inputs": {"type": "object", "description": "输入名到取值，输入名见 list_recipes"},
      }, required=["recipe_id"])
def render_recipe(*, service, user, recipe_id: str, inputs: dict | None = None):
    from app.core import recipe_catalog

    return recipe_catalog.render(recipe_id, inputs or {})


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
        threading.Thread(target=usage_ledger.carrying_context(lambda: asyncio.run(go())), name=f"agent-stage-{stage}", daemon=True).start()


__all__ = ["EFFECTS", "Tool", "ToolCatalog", "ToolError", "catalog", "tool"]

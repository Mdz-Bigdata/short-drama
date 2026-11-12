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
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from app.core import prompt_data, usage_ledger
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
    # 读工具带参考资料（控件表、操作说明）时，它的结果在对话稿里允许比默认截断长多少字；0 用默认。
    result_chars: int = 0
    # 付费工具可给一句「这次要花在什么范围上」(service=..., **arguments)，进确认提示；抛 ValueError 就不发确认直接报错。
    quote: Callable[..., str] | None = None

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
        confirmed = bool(args.pop("confirm", None))
        # A model gets the shape of a tool wrong; that is an answer for it to act on, not a crash of the turn.
        schema = tool.input_schema
        missing = [key for key in schema.get("required") or [] if key not in args and key != "confirm"]
        unknown = [key for key in args if key not in schema.get("properties", {})]
        if missing or unknown:
            problems = ([f"缺少参数 {'、'.join(missing)}"] if missing else []) + ([f"没有参数 {'、'.join(unknown)}"] if unknown else [])
            return {"ok": False, "error": "；".join(problems)}
        try:
            if tool.effect == "paid" and not confirmed:
                # The proposal says what the money goes on, so the person confirms a scope and not just a tool name.
                scope = str(tool.quote(service=service, **args) or "").strip() if tool.quote else ""
                return {"ok": False, "needs_confirmation": True, "tool": name, "arguments": dict(args),
                        "message": f"「{tool.title}」会调用付费模型{f'（{scope}）' if scope else ''}；确认后再执行（confirm=true）"}
            result = tool.handler(service=service, user=user, **args)
        except ToolError:
            raise
        except (ValueError, LookupError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "tool": name, "result": result}


catalog = ToolCatalog()


def tool(name: str, *, title: str, description: str, effect: str, properties: Mapping[str, Any] | None = None,
         required: list[str] | None = None, needs_task: bool = True, result_chars: int = 0, quote: Callable[..., str] | None = None):
    def decorate(handler: Callable[..., Any]) -> Callable[..., Any]:
        props = dict(_TASK) if needs_task else {}
        props.update(properties or {})
        if effect == "paid":
            props.update(_CONFIRM)
        catalog.register(Tool(
            name=name, title=title, description=description, effect=effect,
            input_schema=_schema(props, (["task_id"] if needs_task else []) + list(required or [])),
            handler=handler, needs_task=needs_task, result_chars=int(result_chars or 0), quote=quote,
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


# ---------------------------------------------------------------------------- 场景、舞台与角色的公共件

#: 每个带 scene_id 的工具都这么说：人可以说场景号、第几场或场名。
_SCENE = {"scene_id": {"type": "string", "description": "场景：E1S02、第3场 或场名"}}
#: 助手在导演台留下的改动标签：「助手：挪 林夏」。
ASSISTANT_LABEL = "助手：{text}"
LABEL_CHARS = 40
_LITERAL_SCENE = re.compile(r"^\s*E\s*\d+\s*S\s*\d+\s*$", re.I)
_DESCRIBE_SHOTS = 40


def _scene_id(task: Mapping[str, Any], text: str) -> str:
    """「第3场」、场名或 E1S02 → 任务里的场景号。写成场景号但大纲里没有的原样放行，由具体工具说明它有没有。"""
    from app.core import stage_locator

    try:
        return stage_locator.resolve_scene_id(task, text)
    except LookupError:
        parts = stage_locator.split_scene_id(text)
        if parts and _LITERAL_SCENE.match(str(text or "")):
            return f"E{parts[0]}S{parts[1]:02d}"
        raise


def _scene(service, task_id: str, scene_id: str) -> tuple[dict[str, Any], str]:
    task = service.repo.get_task(task_id) or {}
    return task, _scene_id(task, scene_id)


def _label(text: str, fallback: str, limit: int = LABEL_CHARS) -> str:
    return ASSISTANT_LABEL.format(text=(str(text or "").strip() or fallback)[:limit])


def _ops_summary(operations: list) -> str:
    """一组操作的一句话：「move_actor 林夏、solve_camera 第2镜」。"""
    parts = []
    for item in operations:
        if not isinstance(item, Mapping):
            continue
        target = next((str(item[key]) for key in ("name", "first", "camera_id", "crowd_id", "names") if item.get(key)), "")
        if not target and item.get("shot_id") is not None:
            target = f"第{item['shot_id']}镜"
        parts.append(f"{item.get('op')} {target}".strip())
    return "、".join(parts)


def _failing(plan: Mapping[str, Any]) -> list[str]:
    return [c.get("code") for c in plan.get("checks") or [] if not c.get("passed")]


def _has_change(changed: Any) -> bool:
    """diff_plans 的结果是几张清单：全空就是没动；False / None 也是没动。"""
    if isinstance(changed, Mapping):
        return any(changed.values())
    return bool(changed)


def _stage_changed(scene_id: str, *, revision: Any, snapshot_id: Any, summary: str, failing: list, changed: Any, stale_clips: int = 0) -> dict[str, Any]:
    """界面按它刷新导演台：哪一场、到了哪一版、这一步的快照、动了什么，以及因此过期的片段数。"""
    return {"type": "stage_changed", "scene_id": scene_id, "revision": revision, "snapshot_id": snapshot_id, "summary": summary,
            "failing_checks": failing, "changed": changed, "stale_clips": int(stale_clips or 0)}


def _stage_result(scene_id: str, *, revision: Any, snapshot_id: Any, summary: str, failing: list, changed: Any, stale_clips: int) -> dict[str, Any]:
    """舞台工具的回执：没动舞台就没有刷新动作，界面不用白刷一次。"""
    result: dict[str, Any] = {"revision": revision, "failing_checks": failing, "snapshot_id": snapshot_id, "changed": changed, "stale_clips": int(stale_clips or 0)}
    if _has_change(changed):
        result["ui_action"] = _stage_changed(scene_id, revision=revision, snapshot_id=snapshot_id, summary=summary, failing=failing, changed=changed,
                                             stale_clips=stale_clips)
    return result


def _mark_scene_stale(service, task_id: str, scene_id: str) -> int:
    """舞台已经落地的改动（导演台服务自己写的那些）之后，把这一场的片段标为过期。"""
    from app.service import stage_director_ops

    count = service.repo.mutate_task(task_id, lambda task: stage_director_ops.mark_scene_clips_stale(task, scene_id))
    return int(count or 0)


def _stage_commit(service, task_id: str, scene_id: str, operations: list, base_revision: int | None, label: str) -> dict[str, Any]:
    """一组操作作为助手的一步提交到导演台：留快照、记一条对话；舞台没变就什么都不写。"""
    from app.service import stage_director_ops

    outcome = stage_director_ops.commit_operations(
        service, task_id, scene_id, operations=list(operations), base_revision=int(base_revision) if base_revision is not None else None,
        label=label, solve=False,
    )
    plan = outcome.get("plan") or {}
    return _stage_result(scene_id, revision=plan.get("revision"), snapshot_id=outcome.get("snapshot_id"), summary=label,
                         failing=list(outcome.get("failing") or _failing(plan)), changed=outcome.get("changed"),
                         stale_clips=outcome.get("stale_clips") or 0)


def _current_stage(service, task_id: str, scene_id: str):
    """这一场现在的舞台（存了的，或按剧本预排的那版），与导演台读的是同一份。"""
    from app.service import stage_director_service

    return stage_director_service._load(service, task_id, scene_id)[1]


def _measured(score: Mapping[str, Any] | None) -> dict[str, Any]:
    score = score or {}
    return {"score": score.get("score"), "errors": score.get("errors"), "warnings": score.get("warnings"), "notes": list(score.get("notes") or [])[:8]}


def _turn_result(service, task_id: str, scene_id: str, before, outcome: Mapping[str, Any], *, summary: str) -> dict[str, Any]:
    """导演台一轮对话 / 优化的结果，按助手要的样子：改了什么、到哪一版、还有哪些检查没过、几段片段因此过期。"""
    plan = outcome.get("plan") or {}
    revision = plan.get("revision", before.revision)
    failing = list(outcome.get("failing") or [])
    message = outcome.get("message") or {}
    changed = bool(outcome.get("changed"))
    result = {
        "reply": str(message.get("text") or ""), "changed": message.get("changed") if changed else False,
        "revision": revision, "snapshot_id": outcome.get("snapshot_id"), "failing_checks": failing, "measured": _measured(outcome.get("measured")),
        "errors": list(message.get("errors") or [])[:8], "stale_clips": _mark_scene_stale(service, task_id, scene_id) if changed else 0,
    }
    if changed:
        result["ui_action"] = _stage_changed(scene_id, revision=revision, snapshot_id=outcome.get("snapshot_id"), summary=summary,
                                             failing=failing, changed=message.get("changed"), stale_clips=result["stale_clips"])
    return result


def _snapshot_rows(rows: list) -> list[dict[str, Any]]:
    return [{key: row.get(key) for key in ("id", "label", "name", "pinned", "revision")} for row in rows]


def _character_name(task: Mapping[str, Any], name: str) -> str:
    """角色名不分大小写和空格，也认第一个别名；找不到就把项目里的角色列出来。"""
    def fold(value: Any) -> str:
        return re.sub(r"\s+", "", str(value or "")).casefold()

    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    records = [item for item in assets.get("3_characters") or [] if isinstance(item, Mapping) and str(item.get("name") or "").strip()]
    wanted = fold(name)
    if wanted:
        for record in records:
            if fold(record.get("name")) == wanted:
                return str(record["name"]).strip()
        for record in records:
            aliases = record.get("aliases") if isinstance(record.get("aliases"), list) else []
            if aliases and fold(aliases[0]) == wanted:
                return str(record["name"]).strip()
    known = "、".join(str(record["name"]).strip() for record in records[:12]) or "无"
    raise LookupError(f"项目里没有角色「{name}」；已有：{known}")


def _face_edit(service, task_id: str, name: str, edit: Callable[[dict[str, Any], str], Any]) -> tuple[Any, dict[str, Any]]:
    """与捏脸接口同一条写路：改完重算角色总览，设定集、分镜、视频读到的就是新脸。返回 (结果, 改后的任务)。"""
    from app.core.character_dashboard import compile_character_dashboard

    edited: dict[str, Any] = {}

    def mutation(task: dict[str, Any]) -> Any:
        result = edit(task, name)
        task.setdefault("assets", {})["3_character_dashboard"] = compile_character_dashboard(task).model_dump(mode="json", by_alias=True)
        edited.update(task)
        return result

    result = service.repo.mutate_task(task_id, mutation)
    if result is None:
        raise LookupError("任务不存在")
    return result, edited


def _face_sync(task: Mapping[str, Any], name: str, description: str) -> dict[str, Any]:
    """写完之后（事务外）把新描述写回元素库里这位演员；库的毛病只进回执，不影响已保存的捏脸。"""
    from app.core import face_sculpt_sync

    try:
        outcome = face_sculpt_sync.sync_actor_description(task, name, description) or {}
    except RuntimeError as exc:  # 在事件循环线程里被拒绝：当作没同步成
        outcome = {"updated": False, "element_id": "", "error": str(exc)[:200]}
    library = {"library_updated": bool(outcome.get("updated")), "element_id": str(outcome.get("element_id") or "")}
    if outcome.get("error"):
        library["error"] = str(outcome["error"])
    return library


def _face_write(service, task_id: str, name: str, before: str, edit: Callable[[dict[str, Any], str], Any]) -> dict[str, Any]:
    """捏脸的一次写：保存（片段过期在保存里一并标好），再同步元素库，最后拼回执。"""
    now, task = _face_edit(service, task_id, name, edit)
    description = str((now.get("preview") or {}).get("description") or "")
    return _face_result(before, now, library=_face_sync(task, name, description))


def _face_patch(face: Mapping | None, notes: Mapping | None, expressions: Mapping | None, preset: str) -> tuple[dict[str, Any], list[str]]:
    """给的改动过一遍控件表：认得的进 patch（None 表示去掉），不认得的连原因一起列出来。"""
    from app.core import face_sculpt

    accepted = face_sculpt._Filter()
    accepted.preset(preset or None)
    accepted.face(dict(face) if isinstance(face, Mapping) else None)
    accepted.notes(dict(notes) if isinstance(notes, Mapping) else None)
    accepted.expressions(dict(expressions) if isinstance(expressions, Mapping) else None)
    return accepted.patch, accepted.unknown


def _face_merge(task: Mapping[str, Any], name: str, patch: Mapping[str, Any], *, merge: bool):
    """当前捏脸 ⊕ 改动（或只有改动），核成一份干净的 Sculpt。"""
    from app.core import face_sculpt

    empty = face_sculpt.Sculpt(face={}, notes={}, expressions={})
    base = (face_sculpt.stored_sculpt(face_sculpt.record_of(task, name)) or empty) if merge else empty
    return face_sculpt.validate(face_sculpt._merge_patch(base, patch))


def _face_result(before: str, now: Mapping[str, Any], *, library: Mapping[str, Any]) -> dict[str, Any]:
    """捏脸改动的回执：新描述、进提示词的脸、定妆照是否过期、几段片段过期、元素库写回了没有，和给界面的刷新动作。"""
    preview = now.get("preview") or {}
    history = list(now.get("history") or [])
    after = str(preview.get("description") or "")
    marked = now.get("downstream") if isinstance(now.get("downstream"), Mapping) else {}
    downstream = {"stale_clips": int(marked.get("clips_marked") or 0), "sheet_stale": bool(marked.get("sheet_stale", preview.get("sheet_stale")))}
    return {
        "name": now.get("name"), "revision": now.get("revision"), "label": now.get("label"), "description": after,
        "face_text": preview.get("face_text"), "sheet_stale": bool(preview.get("sheet_stale")), "stale_note": preview.get("stale_note") or "",
        "issues": preview.get("issues") or [], "changed": before != after, "sculpt": now.get("sculpt"), "history": history,
        "downstream": downstream, "library": dict(library),
        "ui_action": {"type": "face_sculpt_changed", "name": now.get("name"), "before": before, "after": after, "revision": now.get("revision"),
                      "sheet_stale": bool(preview.get("sheet_stale")), "snapshot_id": history[0]["id"] if history else None,
                      "downstream": downstream, "library": dict(library)},
    }


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


@tool("get_timeline", title="查看剪辑时间线", description="剪辑合成师（第 6、7 阶段）的时间线：每镜入出点、审看结论、转场、人声来源(原声/配音/无)、配乐与配乐库匹配度、基础设定、张力曲线、成片与配乐版本。", effect="read")
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


@tool("edit_timeline", title="编辑剪辑时间线（剪辑合成师）",
      description=("裁剪、转场、声画错开、字幕、静音、审看、片头、配乐、一镜的人声来源、基础设定之一；字段按 operation 取用。"
                   "audio_source：native 用视频模型的原声 / tts 配音 / none 不出人声（片段没有原声时不能选 native）。"
                   "settings：transitions 场景转场、dialogue 对白音轨、subtitles 嵌入字幕、title_card 片名卡与首尾淡入淡出，传要改的开关。"
                   "bgm：只传 volume / duck / bgm_start（配乐从第几秒进）就不换曲；换曲传 source，库里的曲子用 get_timeline 返回的 bgm_library 里的 id，"
                   "之前生成过的配乐用 source=generated 加 post.music_versions 里的 url 作 music_version。改完要 render_timeline 才进成片。"),
      effect="write",
      properties={
          "operation": {"type": "string", "enum": ["trim", "transition", "sound_join", "subtitle", "mute", "candidate", "review", "title", "bgm", "audio_source", "settings"]},
          "shot_id": {"type": "integer"},
          "shot_uid": {"type": "integer", "description": "全剧唯一的镜头编号；各集各场镜号都从 1 起，跨集时用它定位"},
          "start": {"type": "number"}, "end": {"type": ["number", "null"]}, "kind": {"type": "string"},
          "duration": {"type": "number"}, "text": {"type": "string"}, "muted": {"type": "boolean"}, "video_url": {"type": "string"},
          "decision": {"type": "string", "enum": ["pending", "approved", "rejected"]}, "note": {"type": "string"},
          "source": {"type": "string", "enum": ["none", "generated", "library"]}, "library_id": {"type": "string"}, "volume": {"type": "number"},
          "duck": {"type": "boolean"}, "bgm_start": {"type": "number", "minimum": 0}, "music_version": {"type": "string"},
          "join": {"type": "string", "enum": ["", "j_cut", "l_cut"]}, "seconds": {"type": "number"},
          "audio_source": {"type": "string", "enum": ["native", "tts", "none"]},
          "settings": {"type": "object", "properties": {key: {"type": "boolean"} for key in ("transitions", "dialogue", "subtitles", "title_card")},
                       "additionalProperties": False},
      }, required=["operation"])
def edit_timeline(*, service, user, task_id: str, operation: str, **payload):
    from app.core.edit_timeline import TimelineError

    try:
        result = service.edit_timeline(task_id, operation, payload)
    except TimelineError as exc:
        raise ValueError(str(exc)) from exc
    timeline = result["timeline"]
    return {"summary": result["summary"], "settings": (result.get("post") or {}).get("settings"),
            "bgm": {k: (timeline.get("bgm") or {}).get(k) for k in ("source", "name", "volume", "start")}}


@tool("get_stage_checks", title="查看一场的空间检查与修正建议", description="某场空间方案的检查结果（站位、入画、遮挡、轴线、朝向、姿态）和每条未通过项的自动修正操作。", effect="read",
      properties=_SCENE, required=["scene_id"])
def get_stage_checks(*, service, user, task_id: str, scene_id: str):
    _, scene_id = _scene(service, task_id, scene_id)
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


@tool("edit_stage", title="编辑一场的空间调度", description="对某场的 3D 空间方案按序执行语义操作（站位、朝向、队形、机位、姿态、路径、阵列等），与导演台同一套操作，不花钱；作为一步可撤销的改动记进导演台，返回新版本号、快照 id 与仍未通过的检查。", effect="write",
      properties={
          **_SCENE,
          "operations": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 100,
                         "description": "每项形如 {\"op\": \"move_actor\", ...}；全部 op 与参数见 describe_stage 返回的 operations"},
          "base_revision": {"type": "integer", "description": "省略则以当前版本为准"},
          "label": {"type": "string", "description": "这一步在导演台里叫什么，如「两人拉开」；省略则按操作生成"},
      }, required=["scene_id", "operations"])
def edit_stage(*, service, user, task_id: str, scene_id: str, operations: list, base_revision: int | None = None, label: str = ""):
    if not isinstance(operations, list) or not operations:
        raise ValueError("operations 必须是非空列表")
    _, scene_id = _scene(service, task_id, scene_id)
    return _stage_commit(service, task_id, scene_id, operations, base_revision, _label(label, _ops_summary(operations)))


@tool("repair_stage", title="自动修正一场的空间检查", description="把某场未通过的空间检查一次修正：拉开站位、转向对手、换回站位、重解机位、补上姿态；无法自动处理的项会在结果里说明。", effect="write",
      properties={**_SCENE, "codes": {"type": "array", "items": {"type": "string"}, "description": "只修这些检查代码；省略则全部"}},
      required=["scene_id"])
def repair_stage(*, service, user, task_id: str, scene_id: str, codes: list | None = None):
    _, scene_id = _scene(service, task_id, scene_id)
    operation = {"op": "repair_checks"}
    if codes:
        operation["codes"] = [str(code) for code in codes]
    outcome = _stage_commit(service, task_id, scene_id, [operation], None, _label("", "自动修正空间检查"))
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

@lru_cache(maxsize=1)
def stage_operations_guide() -> str:
    """舞台全部语义操作的说明，每个只写一处：导演台模型用的 OP_GUIDE，加上它没列到的几条（agent_prompts.json）。"""
    from app.core.spatial_stage.director_ai import OP_GUIDE

    return "\n".join([OP_GUIDE, *prompt_data.words("agent_prompts", "stage_op_supplement")])


def _previz():
    from app.service import blender_previz_service

    return blender_previz_service


def _previz_call(fn, *args, **kwargs):
    previz = _previz()
    try:
        return fn(*args, **kwargs)
    except previz.PrevizError as exc:
        raise ValueError(str(exc)) from exc


# 带参考资料的读工具在对话稿里允许的长度：控件表 / 操作说明放在结果最前面，整份都要让模型看到。
REFERENCE_RESULT_CHARS = 9000


@tool("describe_stage", title="读出一场的站位与机位", description="某场 3D 空间方案的当前状态：人物站位朝向姿态、道具、每台摄影机的位置/目标/焦段、每镜用哪台机、评分与可撤销的快照，以及编辑用的全部操作说明。改站位、改机位前先看它。", effect="read",
      properties=_SCENE, required=["scene_id"], result_chars=REFERENCE_RESULT_CHARS)
def describe_stage(*, service, user, task_id: str, scene_id: str):
    from app.core.spatial_stage import scoring
    from app.service import spatial_stage_service, stage_director_ops

    task, scene_id = _scene(service, task_id, scene_id)
    plan = spatial_stage_service.load_plan(task or {}, scene_id)
    if plan is None:
        raise ValueError(f"场景 {scene_id} 还没有空间方案")
    return {
        # 操作说明放最前：对话稿截断时先丢的是后面的清单，而不是模型改舞台时要照着写的格式。
        "operations": stage_operations_guide(),
        "scene_id": scene_id, "revision": plan.revision, "aspect_ratio": plan.aspect_ratio, "location": plan.location,
        "measured": _measured(scoring.score_plan(plan)),
        "snapshots": _snapshot_rows(stage_director_ops.list_snapshots(service, task_id, scene_id))[:8],
        "actors": [{"name": a.name, "position": a.position, "yaw_deg": a.yaw_deg, "posture": a.posture, "height_m": a.height_m}
                   for a in plan.actors if not a.crowd_id][:40],
        "crowds": [{"id": c.id, "label": c.label, "rows": c.rows, "columns": c.columns} for c in plan.crowds],
        "landmarks": [{"name": piece.name, "kind": piece.kind, "position": piece.position, "size": piece.size} for piece in plan.landmarks][:60],
        "cameras": [{"id": c.id, "position": c.position, "target": c.target, "lens_mm": c.lens_mm, "shot_size": c.shot_size, "move": c.move.kind}
                    for c in plan.cameras][:40],
        "shots": [{"shot_id": s.shot_id, "camera_id": s.camera_id, "subjects": s.subjects, "action": s.action[:120],
                   "timeline": str(s.shot_id) in plan.timelines} for s in plan.shots][:80],
        "failing_checks": [c.code for c in plan.checks if not c.passed],
    }


@tool("list_stage_scenes", title="列出有哪些场", description="项目里的每一场：场景号、集、场名、人物和镜头；用户说「第3场」「办公室那场」时先用它对上场景号。", effect="read")
def list_stage_scenes(*, service, user, task_id: str):
    from app.core import stage_locator

    scenes = stage_locator.scenes_of(service.repo.get_task(task_id) or {})
    return {"count": len(scenes), "scenes": [{**scene, "shots": scene["shots"][:_DESCRIBE_SHOTS]} for scene in scenes]}


@tool("auto_plan_stage", title="模型规划一场的调度方案", description="让文本模型一次给出几版完整调度（布景、站位、姿势、机位、运动），修正、评分并与规则方案比较，推荐最佳；舞台不变，再用 adopt_stage_plan 采用其中一版。每版消耗一到两次文本调用。", effect="paid",
      properties={**_SCENE, "count": {"type": "integer", "minimum": 1, "maximum": 3}, "goal": {"type": "string", "description": "导演的额外要求，可省略"},
                  "from_current": {"type": "boolean", "default": False, "description": "true 以当前舞台（含已有改动）为底稿，否则从剧本重新排"}},
      required=["scene_id"])
def auto_plan_stage(*, service, user, task_id: str, scene_id: str, count: int = 3, goal: str = "", from_current: bool = False):
    from app.service import stage_director_ops, stage_director_service

    _, scene_id = _scene(service, task_id, scene_id)
    current = _current_stage(service, task_id, scene_id)
    planner = stage_director_ops.plan_from_current if from_current else stage_director_service.plan_scene
    outcome = planner(service, task_id, scene_id, base_revision=current.revision, count=count, goal=goal)
    return {
        **{key: outcome[key] for key in ("recommended", "used_model", "note", "current")},
        "candidates": [{key: item[key] for key in ("id", "title", "rationale", "source", "score", "errors")} for item in outcome["candidates"]],
        "next": "调用 adopt_stage_plan 采用其中一版",
    }


@tool("adopt_stage_plan", title="采用一版调度方案", description="把 auto_plan_stage 给出的一版方案放到舞台上；可以用 revert_stage_step 撤销。", effect="write",
      properties={**_SCENE, "candidate_id": {"type": "string"}}, required=["scene_id", "candidate_id"])
def adopt_stage_plan(*, service, user, task_id: str, scene_id: str, candidate_id: str):
    from app.core.spatial_stage.models import StagePlan
    from app.service import stage_director_service

    task, scene_id = _scene(service, task_id, scene_id)
    before = _current_stage(service, task_id, scene_id)
    chosen = next((item for item in stage_director_service._peek(task, scene_id).get("candidates") or []
                   if isinstance(item, Mapping) and item.get("id") == candidate_id), {})
    outcome = stage_director_service.adopt_candidate(service, task_id, scene_id, candidate_id=candidate_id, base_revision=before.revision)
    plan = outcome["plan"]
    changed = stage_director_service.diff_plans(before, StagePlan.model_validate(plan))
    stale = _mark_scene_stale(service, task_id, scene_id) if _has_change(changed) else 0
    return _stage_result(scene_id, revision=plan["revision"], snapshot_id=outcome.get("snapshot_id"), summary=f"采用方案「{chosen.get('title') or candidate_id}」",
                         failing=_failing(plan), changed=changed, stale_clips=stale)


@tool("build_stage_model", title="搭一个白模", description="按描述搭一件东西（模型库有的直接用，没有的让文本模型用体块搭），放到舞台上。", effect="paid",
      properties={
          **_SCENE, "description": {"type": "string"},
          "position": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2, "description": "地面点 [x, z]"},
          "yaw_deg": {"type": "number"}, "name": {"type": "string", "description": "舞台上的名字，默认按模型命名"},
      }, required=["scene_id", "description", "position"])
def build_stage_model(*, service, user, task_id: str, scene_id: str, description: str, position: list, yaw_deg: float = 0.0, name: str = ""):
    from app.service import stage_director_service

    _, scene_id = _scene(service, task_id, scene_id)
    proposal = stage_director_service.propose_model(service, task_id, scene_id, description=description)
    operation = {
        "op": "add_landmark", "name": (name or proposal["name"])[:120], "kind": proposal["kind"], "position": position, "yaw_deg": yaw_deg,
        "size": proposal["size"], "kit": proposal["kit"], "fitted_parts": proposal["parts"],
    }
    outcome = _stage_commit(service, task_id, scene_id, [operation], None, _label("", f"搭{operation['name']}"))
    return {**outcome, "model": {key: proposal[key] for key in ("name", "kit", "size", "summary")}, "parts": len(proposal["parts"])}


def _quote_stage_turn(*, service, task_id: str, scene_id: str, names: list | None = None, shot_id: int | None = None, **_rest) -> str:
    """AI 导演改一场 / 自动优化一场的确认提示：说清改哪一场、限定了谁和哪一镜、花几次调用。"""
    from app.core import stage_locator

    task, scene_id = _scene(service, task_id, scene_id)
    scope = stage_locator.scene_label(task, scene_id)
    if names:
        scope += f"，只改 {'、'.join(str(item) for item in names[:6])}"
    if shot_id:
        scope += f"，只改第{int(shot_id)}镜"
    return f"{scope}，1–3 次文本模型调用"


@tool("direct_stage", title="让 AI 导演改一场（对话）", description="像导演台「AI 导演」页签那样，把含糊的目标交给文本模型改舞台：「更有压迫感」「两人隔着桌子对峙」「镜头跟着她走」。会花 1–3 次文本模型调用，付费，需用户确认（确认提示里会说明改哪一场）；明确的站位 / 机位改动请用 edit_stage（不花钱）。names / shot_id 可限定只改谁、只改哪一镜。", effect="paid",
      properties={**_SCENE, "message": {"type": "string", "description": "对这一场的要求，像对导演说话"},
                  "names": {"type": "array", "items": {"type": "string"}, "description": "只改这些人或布景"},
                  "shot_id": {"type": "integer", "description": "只改这一镜"}},
      required=["scene_id", "message"], quote=_quote_stage_turn)
def direct_stage(*, service, user, task_id: str, scene_id: str, message: str, names: list | None = None, shot_id: int | None = None):
    from app.service import stage_director_ops, stage_director_service

    task, scene_id = _scene(service, task_id, scene_id)
    stage_director_ops.ensure_idle(service, task)   # 正在跑阶段时改动落不下来，别先花模型调用
    before = _current_stage(service, task_id, scene_id)
    outcome = stage_director_service.chat(
        service, task_id, scene_id, message=str(message), base_revision=before.revision,
        names=[str(item) for item in names or []], shot_id=int(shot_id) if shot_id else None,
    )
    return _turn_result(service, task_id, scene_id, before, outcome, summary=str(message).strip()[:LABEL_CHARS])


@tool("optimize_stage", title="自动优化一场", description="让规则先修、再让文本模型把这一场调得更好（评分变低的不留）；花 1–3 次文本模型调用，付费，需用户确认。goal 可说明朝哪个方向优化，names / shot_id 限定范围。", effect="paid",
      properties={**_SCENE, "goal": {"type": "string"}, "names": {"type": "array", "items": {"type": "string"}}, "shot_id": {"type": "integer"}},
      required=["scene_id"], quote=_quote_stage_turn)
def optimize_stage(*, service, user, task_id: str, scene_id: str, goal: str = "", names: list | None = None, shot_id: int | None = None):
    from app.service import stage_director_ops, stage_director_service

    task, scene_id = _scene(service, task_id, scene_id)
    stage_director_ops.ensure_idle(service, task)
    before = _current_stage(service, task_id, scene_id)
    outcome = stage_director_service.optimize(
        service, task_id, scene_id, base_revision=before.revision, goal=str(goal or ""),
        names=[str(item) for item in names or []], shot_id=int(shot_id) if shot_id else None,
    )
    return _turn_result(service, task_id, scene_id, before, outcome, summary=(str(goal or "").strip() or "自动优化")[:LABEL_CHARS])


def _batch_scenes(service, task_id: str, scene_ids: list | None, episode: int | None) -> tuple[dict[str, Any], list[str]]:
    """批量优化的范围：必须指明哪几场或第几集（不默认全剧），场数在 stage_director_ops.MAX_BATCH 以内。"""
    from app.service import stage_director_ops

    if not scene_ids and not episode:
        raise ValueError("请说明优化哪几场（scene_ids）或第几集（episode），不会默认优化全剧")
    task = service.repo.get_task(task_id) or {}
    wanted = [_scene_id(task, str(item)) for item in scene_ids or []]
    return task, stage_director_ops.batch_scope(task, scene_ids=wanted or None, episode=int(episode) if episode else None)


def _quote_optimize_scenes(*, service, task_id: str, scene_ids: list | None = None, episode: int | None = None, goal: str = "") -> str:
    """确认提示里说清这次优化哪几场、每场花多少次。"""
    from app.core import stage_locator

    task, wanted = _batch_scenes(service, task_id, scene_ids, episode)
    if not wanted:
        raise ValueError(f"第{int(episode)}集没有场景" if episode else "没有要优化的场")
    names = "、".join(stage_locator.scene_label(task, scene_id) for scene_id in wanted[:6]) + ("…" if len(wanted) > 6 else "")
    return f"{names}，共 {len(wanted)} 场，每场 1–3 次文本模型调用" + (f"；目标：{str(goal).strip()[:LABEL_CHARS]}" if str(goal or "").strip() else "")


@tool("optimize_scenes", title="批量优化多场", description="依次自动优化多场舞台：必须给 scene_ids 或 episode 说明范围（不会默认全剧），一次最多 12 场；每场都可能花 1–3 次文本模型调用，所以需用户确认，确认提示里会列出要优化的场。", effect="paid",
      properties={"scene_ids": {"type": "array", "items": {"type": "string"}, "description": "场景：E1S02、第3场 或场名；省略则按 episode"},
                  "episode": {"type": "integer", "minimum": 1, "description": "优化这一集的全部场；与 scene_ids 至少给一个"}, "goal": {"type": "string"}},
      quote=_quote_optimize_scenes)
def optimize_scenes(*, service, user, task_id: str, scene_ids: list | None = None, episode: int | None = None, goal: str = ""):
    from app.service import stage_director_ops

    _, wanted = _batch_scenes(service, task_id, scene_ids, episode)
    return stage_director_ops.optimize_scenes(service, task_id, scene_ids=wanted, goal=str(goal or ""))


@tool("revert_stage_step", title="撤销舞台的一步", description="把一场退回某个快照（导演台 / 助手 / AI 导演的每一步都有快照）；snapshot_id 省略则撤销最近的一步。撤销本身也留了快照，可以再撤回来。", effect="write",
      properties={**_SCENE, "snapshot_id": {"type": "string", "description": "见 get_stage_director 的 snapshots；省略则最近一步"}}, required=["scene_id"])
def revert_stage_step(*, service, user, task_id: str, scene_id: str, snapshot_id: str = ""):
    from app.core.spatial_stage.models import StagePlan
    from app.service import stage_director_ops, stage_director_service

    _, scene_id = _scene(service, task_id, scene_id)
    rows = stage_director_ops.list_snapshots(service, task_id, scene_id)
    wanted = str(snapshot_id or "").strip()
    row = next((item for item in rows if str(item.get("id")) == wanted), None) if wanted else (rows[0] if rows else None)
    if row is None:
        raise LookupError("没有可撤销的步骤" if not wanted else "没有这个快照：它可能已被更早的步骤挤掉")
    before = _current_stage(service, task_id, scene_id)
    outcome = stage_director_ops.restore_snapshot(service, task_id, scene_id, snapshot_id=str(row["id"]), base_revision=before.revision)
    plan = outcome["plan"]
    changed = stage_director_service.diff_plans(before, StagePlan.model_validate(plan))
    summary = f"已撤销「{row.get('name') or row.get('label') or row['id']}」"
    return {
        "restored": outcome.get("restored"), "kept_snapshot_id": outcome.get("kept_snapshot_id"),
        **_stage_result(scene_id, revision=plan["revision"], snapshot_id=outcome.get("kept_snapshot_id"), summary=summary,
                        failing=_failing(plan), changed=changed, stale_clips=outcome.get("stale_clips") or 0),
    }


@tool("get_stage_director", title="看导演台的最近改动与快照", description="一场的评分、可撤销的快照（含固定下来的）和最近几条导演台对话。", effect="read",
      properties=_SCENE, required=["scene_id"])
def get_stage_director(*, service, user, task_id: str, scene_id: str):
    from app.service import stage_director_ops, stage_director_service

    _, scene_id = _scene(service, task_id, scene_id)
    view = stage_director_service.state(service, task_id, scene_id)
    return {
        "scene_id": scene_id, "measured": _measured(view.get("measured")), "planner": view.get("planner"),
        "snapshots": _snapshot_rows(stage_director_ops.list_snapshots(service, task_id, scene_id)),
        "chat": [{"role": row.get("role"), "text": str(row.get("text") or "")[:200]} for row in list(view.get("chat") or [])[-6:]],
        "candidates": len(view.get("candidates") or []),
    }


@tool("pin_stage_snapshot", title="固定或取消固定一个快照", description="把舞台的某一步留成有名字的快照，之后不会被新的步骤挤掉；pinned=false 取消固定。", effect="write",
      properties={**_SCENE, "snapshot_id": {"type": "string"}, "name": {"type": "string", "description": "给这一版起个名字"},
                  "pinned": {"type": "boolean", "default": True}},
      required=["scene_id", "snapshot_id"])
def pin_stage_snapshot(*, service, user, task_id: str, scene_id: str, snapshot_id: str, name: str = "", pinned: bool = True):
    from app.service import stage_director_ops

    _, scene_id = _scene(service, task_id, scene_id)
    result = stage_director_ops.pin_snapshot(service, task_id, scene_id, snapshot_id=str(snapshot_id), name=str(name or ""), pinned=bool(pinned))
    return {**result, "snapshots": _snapshot_rows(result.get("snapshots") or [])}


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
      properties=_SCENE, required=["scene_id"])
def get_blender_previz(*, service, user, task_id: str, scene_id: str):
    task, scene_id = _scene(service, task_id, scene_id)
    return _previz().get_previz(task, scene_id)


@tool("render_blender_previz", title="用 Blender 渲染白模预演", description="把某场的站位、机位与切镜在本机 Blender 里搭成彩色白模并渲染成连续预演视频(每镜一段硬切)和每镜首帧；本机渲染不花模型额度。改完站位/机位后调用它看效果；打开的 Blender 若连着插件会同步刷新。", effect="write",
      properties={**_SCENE,
                  "shot_ids": {"type": "array", "items": {"type": "integer"}, "description": "只渲这些镜；省略则整场"},
                  "long_edge": {"type": "integer", "minimum": 480, "maximum": 3840, "default": 1920, "description": "长边像素；试看可用 960"}},
      required=["scene_id"])
def render_blender_previz(*, service, user, task_id: str, scene_id: str, shot_ids: list | None = None, long_edge: int = 1920):
    _, scene_id = _scene(service, task_id, scene_id)
    result = _previz_call(_previz().render_scene, service, task_id, scene_id,
                          shot_ids=[int(v) for v in shot_ids] if shot_ids else None, long_edge=int(long_edge))
    return {key: result[key] for key in ("video_url", "stills", "segments", "frames", "fps", "resolution", "reused", "live", "plan_revision")}


@tool("set_previz_options", title="设置预演的手持与空段", description="让某些镜头用真实手持(低频摆动+微震)，或给雷光、液体、粒子等专项效果在镜头里留空段；下一次渲染生效。", effect="write",
      properties={**_SCENE,
                  "handheld_shots": {"type": "array", "items": {"type": "integer"}, "description": "用手持的镜号；传空数组取消全部手持"},
                  "reserved": {"type": "array", "items": {"type": "object", "properties": {
                      "shot_id": {"type": "integer"}, "from_s": {"type": "number"}, "to_s": {"type": "number"}, "label": {"type": "string"}}},
                      "description": "空段列表(整体替换)"}},
      required=["scene_id"])
def set_previz_options(*, service, user, task_id: str, scene_id: str, handheld_shots: list | None = None, reserved: list | None = None):
    _, scene_id = _scene(service, task_id, scene_id)
    return _previz_call(_previz().set_options, service, task_id, scene_id, handheld_shots=handheld_shots, reserved=reserved)


@tool("attach_previz_to_shots", title="把预演交给分镜当运动参考", description="把最近一次 Blender 预演按镜头切片，登记为这些镜的运动参考视频：第 5 阶段出片时由它管机位、切点与时间，角色设定集只管外观。站位改过就要先重新渲染。", effect="write",
      properties={**_SCENE, "shot_ids": {"type": "array", "items": {"type": "integer"}, "description": "省略则整场"}},
      required=["scene_id"])
def attach_previz_to_shots(*, service, user, task_id: str, scene_id: str, shot_ids: list | None = None):
    _, scene_id = _scene(service, task_id, scene_id)
    return _previz_call(_previz().attach_to_shots, service, task_id, scene_id, shot_ids=shot_ids)


@tool("push_to_blender", title="推到打开的 Blender", description="在你本机打开的 Blender 里按当前方案重建预演场景(需启用桥接插件并点「开始连接」)，不渲染。", effect="write",
      properties=_SCENE, required=["scene_id"])
def push_to_blender(*, service, user, task_id: str, scene_id: str):
    _, scene_id = _scene(service, task_id, scene_id)
    return _previz_call(_previz().push_live, service, task_id, scene_id)


@tool("pull_from_blender", title="从 Blender 同步回方案", description="读回你在 Blender 里拖动过的人物、道具与摄影机位置，换成方案操作；apply=true 才写回方案，否则只列出会改什么。", effect="write",
      properties={**_SCENE, "apply": {"type": "boolean", "default": False}}, required=["scene_id"])
def pull_from_blender(*, service, user, task_id: str, scene_id: str, apply: bool = False):
    _, scene_id = _scene(service, task_id, scene_id)
    return _previz_call(_previz().pull_live, service, task_id, scene_id, apply=bool(apply))


# ---------------------------------------------------------------------------- 捏脸(第 3 阶段角色)

_FACE_PARTS = {
    "face": {"type": "object", "description": "控件键 → 取值：选项控件填 value（选项名也认），刻度控件填 -2..2 的整数；null 去掉这一项"},
    "notes": {"type": "object", "description": "层键 → 补充一句（如 features: \"眼下一粒泪痣\"）；null 去掉"},
    "expressions": {"type": "object", "description": "表情键 → {choices:{表情控件:value}, tell?, habit?}；null 去掉这个表情"},
    "preset": {"type": "string", "description": "先铺一个预设再逐项覆盖"},
}


@lru_cache(maxsize=1)
def _face_catalog() -> dict[str, Any]:
    """给助手看的捏脸控件表，压成 键 → 「名字：可选值」一行：刻度控件只给范围，不带表情词和写进提示词的短语。"""
    from app.core import face_sculpt

    cat = face_sculpt.catalog()
    low, high = face_sculpt.SCALE_RANGE

    def line(label: str, options) -> str:
        return f"{label}：" + "/".join(f"{value}={text}" for value, text, _phrase in options)

    return {
        "scale_range": [low, high],
        "controls": {c.key: line(c.label, c.options) if c.kind == "choice" else f"{c.label}：刻度 {low}..{high}" for c in cat.controls},
        "presets": {key: label for key, label in cat.preset_labels.items()},
        "expression_controls": {key: line(cat.expression_control_labels[key], options) for key, options in cat.expression_controls.items()},
        "expressions": {key: label for key, label, _words in cat.expressions},
        "limits": {key: cat.limits[key] for key in ("note_chars", "tell_chars", "habit_chars") if key in cat.limits},
    }


def _face_arguments(task: Mapping[str, Any], name: str, face, notes, expressions, preset: str, *, merge: bool):
    patch, unknown = _face_patch(face, notes, expressions, preset)
    if unknown:
        raise ValueError("有些改动对不上控件表：" + "；".join(unknown))
    if not any(patch[key] for key in ("face", "notes", "expressions", "preset")):
        raise ValueError("没有给出任何捏脸改动：face / notes / expressions / preset 至少填一项")
    return _face_merge(task, name, patch, merge=merge), patch


@tool("get_face_sculpt", title="看一个角色的捏脸", description="某个角色当前的捏脸取值、合成后的面部描述、定妆照是否已过期、可撤销的历史，以及全部捏脸控件（键、层、类型、可选值）。捏脸前先看它。", effect="read",
      properties={"name": {"type": "string", "description": "角色名（不分大小写，也认别名）"}}, required=["name"], result_chars=REFERENCE_RESULT_CHARS)
def get_face_sculpt(*, service, user, task_id: str, name: str):
    from app.core import face_sculpt

    task = service.repo.get_task(task_id) or {}
    name = _character_name(task, name)
    now = face_sculpt.current(task, name)
    preview = now.get("preview") or {}
    return {
        # 控件表放最前：模型下一步就要照着它填键和取值，对话稿截断时不能先丢它。
        "catalog": _face_catalog(),
        "name": name, "revision": now.get("revision"), "label": now.get("label"), "sculpt": now.get("sculpt"), "history": now.get("history"),
        "description": preview.get("description"), "face_text": preview.get("face_text"), "sheet_stale": bool(preview.get("sheet_stale")),
        "stale_note": preview.get("stale_note") or "", "issues": preview.get("issues") or [],
    }


@tool("get_sheet_prompt", title="看一个角色的设定集提示词", description="第 3 阶段重出这个角色定妆照 / 设定集时会交给图像模型的画面描述（含捏脸后的描述），与接口 GET sheet-prompt 同一段文字；只读不花钱，捏完脸先看一眼再决定要不要付费重出。", effect="read",
      properties={"name": {"type": "string", "description": "角色名（不分大小写，也认别名）"}}, required=["name"], result_chars=REFERENCE_RESULT_CHARS)
def get_sheet_prompt(*, service, user, task_id: str, name: str):
    from app.api import face_sculpt_api   # 提示词只在接口那一处拼，工具读的和界面看的是同一段
    from app.core import face_sculpt

    task = service.repo.get_task(task_id) or {}
    name = _character_name(task, name)
    record = face_sculpt.record_of(task, name)
    stored = record.get(face_sculpt.RECORD_KEY) if isinstance(record.get(face_sculpt.RECORD_KEY), Mapping) else {}
    return {
        "name": name, "prompt": face_sculpt_api._sheet_prompt(task, record), "sheet_stale": face_sculpt.sheet_is_stale(record, task),
        "revision": int(stored.get("revision") or 0),
    }


@tool("preview_face_sculpt", title="预览捏脸效果", description="在当前捏脸上叠加给出的改动，看合成后的面部描述、进提示词的脸和资产卡警告；不写任何数据。", effect="read",
      properties={"name": {"type": "string"}, **_FACE_PARTS}, required=["name"])
def preview_face_sculpt(*, service, user, task_id: str, name: str, face: dict | None = None, notes: dict | None = None, expressions: dict | None = None, preset: str = ""):
    from app.core import face_sculpt

    task = service.repo.get_task(task_id) or {}
    name = _character_name(task, name)
    sculpt, patch = _face_arguments(task, name, face, notes, expressions, preset, merge=True)
    seen = face_sculpt.preview(face_sculpt.record_of(task, name), sculpt, task)
    return {"name": name, "patch": patch, "sculpt": sculpt.dump(), **{key: seen.get(key) for key in ("description", "face_text", "layers", "issues", "expressions", "sheet_stale")}}


@tool("sculpt_face", title="捏脸 / 捏表情", description="按控件改一个角色的脸或表情习惯并保存：默认叠加在当前捏脸上（merge=false 则整份替换）。写进角色描述与各造型状态，设定集、分镜、视频都读这一份；不花钱，已画好的定妆照会标为过期（重出需 run_stage 3，付费）。", effect="write",
      properties={"name": {"type": "string"}, **_FACE_PARTS,
                  "merge": {"type": "boolean", "default": True, "description": "true 叠加在当前捏脸上；false 整份替换"},
                  "label": {"type": "string", "description": "这一步在撤销历史里叫什么；省略则按改动生成"}},
      required=["name"])
def sculpt_face(*, service, user, task_id: str, name: str, face: dict | None = None, notes: dict | None = None, expressions: dict | None = None,
                preset: str = "", merge: bool = True, label: str = ""):
    from app.core import face_sculpt

    task = service.repo.get_task(task_id) or {}
    name = _character_name(task, name)
    sculpt, patch = _face_arguments(task, name, face, notes, expressions, preset, merge=bool(merge))
    before = str(face_sculpt.record_of(task, name).get("desc") or "")
    text = _label(label, face_sculpt._describe_patch(patch), limit=int(face_sculpt.catalog().limits["label_message_chars"]))
    return _face_write(service, task_id, name, before, lambda stored, who: face_sculpt.save(stored, who, sculpt, label=text))


@tool("revert_face_sculpt", title="撤销捏脸的一步", description="退回捏脸撤销历史里的某一步；snapshot_id 省略则退回最近的一步（见 get_face_sculpt 的 history）。", effect="write",
      properties={"name": {"type": "string"}, "snapshot_id": {"type": "string"}}, required=["name"])
def revert_face_sculpt(*, service, user, task_id: str, name: str, snapshot_id: str = ""):
    from app.core import face_sculpt

    task = service.repo.get_task(task_id) or {}
    name = _character_name(task, name)
    now = face_sculpt.current(task, name)
    wanted = str(snapshot_id or "").strip() or (now["history"][0]["id"] if now.get("history") else "")
    if not wanted:
        raise LookupError("这个角色还没有可撤销的捏脸步骤")
    before = str(face_sculpt.record_of(task, name).get("desc") or "")
    return _face_write(service, task_id, name, before, lambda stored, who: face_sculpt.revert(stored, who, wanted))


@tool("reset_face_sculpt", title="恢复捏脸前的样子", description="放回第一次捏脸前的角色描述与造型状态，去掉捏脸、表情习惯和撤销历史。", effect="write",
      properties={"name": {"type": "string"}}, required=["name"])
def reset_face_sculpt(*, service, user, task_id: str, name: str):
    from app.core import face_sculpt

    task = service.repo.get_task(task_id) or {}
    name = _character_name(task, name)
    before = str(face_sculpt.record_of(task, name).get("desc") or "")
    return _face_write(service, task_id, name, before, face_sculpt.reset)


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


def _board_entry(service, task_id: str, scene_id: str) -> tuple[dict, dict, str]:
    """这一场的分镜条目；场景可以说第几场或场名，解析后的场景号一并返回。"""
    task, scene_id = _scene(service, task_id, scene_id)
    boards = (task.get("assets") or {}).get("4_scene_boards") or {}
    entry = boards.get(scene_id)
    if not isinstance(entry, dict):
        known = "、".join(list(boards)[:12]) or "无"
        raise ValueError(f"分镜里没有场景 {scene_id}；已有：{known}")
    return task, entry, scene_id


@tool("get_scene_board", title="读一场的九宫格分镜", description="某场分镜的状态(待创作/生成中/已完成/失败及原因)、每个画格的景别、画面、台词与图片地址，以及整张九宫格图的下载地址。", effect="read",
      properties=_SCENE, required=["scene_id"])
def get_scene_board(*, service, user, task_id: str, scene_id: str):
    task, entry, scene_id = _board_entry(service, task_id, scene_id)
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
      properties=_SCENE, required=["scene_id"])
def get_scene_prompt(*, service, user, task_id: str, scene_id: str):
    _, entry, scene_id = _board_entry(service, task_id, scene_id)
    detail, prompt = entry.get("prompt_detail"), entry.get("grid_prompt") or ""
    if not detail and not prompt:
        raise ValueError(f"{scene_id} 的提示词尚未生成；完成本场分镜生成后才有")
    return _compact({"scene_id": scene_id, "grid_prompt": prompt, "prompt_detail": detail})


@tool("get_prompt_packages", title="生成提示词分包", description="把已定稿的分镜重新切成可直接粘贴的 Seedance 提示词分包(工具栏「提示词分包」)；只重组不调模型。", effect="read",
      properties={"scene_id": {"type": "string", "description": "场景：E1S02、第3场 或场名；留空则整集"},
                  "package_seconds": {"type": "integer", "enum": [10, 15, 20, 30], "default": 15},
                  "variant": {"type": "string", "enum": ["standard", "continuous", "fight", "script_doc"], "default": "standard"},
                  "delivery": {"type": "string", "enum": ["正常", "急切", "沉重"], "default": "正常"}})
def get_prompt_packages(*, service, user, task_id: str, scene_id: str = "", package_seconds: int = 15, variant: str = "standard", delivery: str = "正常"):
    if scene_id:
        _, scene_id = _scene(service, task_id, scene_id)
    payload = service.compile_prompt_packages(task_id, scene_id=scene_id, package_seconds=int(package_seconds), variant=variant, delivery=delivery)
    return _compact(payload or {})


@tool("get_asset_sheets", title="读资产设定图", description="人物 / 场景 / 道具 / 色板四类设定图：识别锚点、可直接生成的提示词与版式(工具栏「资产设定图」)。", effect="read")
def get_asset_sheets(*, service, user, task_id: str):
    return _compact(service.compile_asset_sheets(task_id) or {})


@tool("redraw_scene", title="把一场送回重画", description="把某场分镜标回待生成并清掉它的旧画格，下一次运行第 4 阶段时只按当前站位重画这一场(本身不花钱；真正重画要再 run_stage 4，需用户确认)。", effect="write",
      properties=_SCENE, required=["scene_id"])
def redraw_scene(*, service, user, task_id: str, scene_id: str):
    _, scene_id = _scene(service, task_id, scene_id)
    result = service.redraw_spatial_scene(task_id, scene_id)
    if result is None:
        raise ValueError(f"场景 {scene_id} 还没有分镜，无需重画")
    return {"scene_id": scene_id, "status": "pending", "next": "调用 run_stage(stage=4) 重画(付费，需用户确认)"}


@tool("open_storyboard_view", title="在界面上打开分镜视图", description="在用户的分镜故事板界面上选中某场并打开对应视图：board 九宫格 / prompt 查看提示词 / spatial 空间调度 / desk 3D 导演台 / blender Blender 预演 / packages 提示词分包 / sheets 资产设定图 / download 下载本图。用户说「打开」「给我看」「下载」时用它。", effect="read",
      properties={**_SCENE, "view": {"type": "string", "enum": list(STORYBOARD_VIEWS)}}, required=["scene_id", "view"])
def open_storyboard_view(*, service, user, task_id: str, scene_id: str, view: str):
    if view not in STORYBOARD_VIEWS:
        raise ValueError(f"view 只能是：{'、'.join(STORYBOARD_VIEWS)}")
    _, _, scene_id = _board_entry(service, task_id, scene_id)
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
    "update_node {id, label?, prompt?, text?, styleText?, sceneId?, shotId?, params?, x?, y?, width?, height?, collapsed?, expandedSize?[宽,高]}（collapsed 只对分组：true 折叠、false 展开）；"
    "delete_node {id}（删分组不删成员，成员回到外层分组）；disconnect {source, target}；"
    "group {ids, label?, parent?}（ids 里可以有分组；parent 是外层分组 id，分组最多嵌套一层）；set_group {node_ids, group_id}（移进分组，group_id 为 null 则移出分组）；"
    "align {node_ids, mode(left/hcenter/right/top/vcenter/bottom)}（按所选范围对齐）；distribute {node_ids, axis(horizontal/vertical)}（首尾不动，中间等距，至少三个）；"
    "arrange {node_ids, layout(row/column/grid/edges), gap?}（从所选范围左上角排：row/column/grid 间距默认 40；edges 按连线依赖从左到右分列，列距默认 120、行距 40）。"
    "选中的分组会带着成员一起移动；坐标没有画布边界，读 get_canvas 的 bounds 看节点占的范围、每个节点的 group 看它在哪个分组里"
)


@tool("get_canvas", title="读节点画布", description="当前项目某张画布的概况：画布列表、版本号、各类节点数量、每个节点的提示词/输入/结果/最近一次运行，以及连线。总结画布、改画布之前先看它。", effect="read",
      properties={"canvas_id": {"type": "string", "description": "画布 id，省略则为主画布"}})
def get_canvas(*, service, user, task_id: str, canvas_id: str = "main"):
    studio, project_id, owner = _canvas_project(service, user, task_id)
    result = _canvas_call(studio.summarize_canvas, project_id, owner, canvas_id=str(canvas_id))
    # The extent of the board stays readable even when the node list is cut short.
    return {**_compact(result, 9000), "bounds": result.get("bounds"), "operations": CANVAS_OP_CHEATSHEET}


@tool("list_canvas_tools", title="列出画布工具", description="画布工具节点能用的工具（重绘、扩图、打光、放大、擦除、抽帧、镜头分析、拍点规划……）：每个工具吃什么输入、产出什么、由谁处理、要不要钱；以及风格转绘可选的风格。", effect="read", needs_task=False)
def list_canvas_tools(*, service, user):
    from app.core import canvas_tools

    return {
        "tools": canvas_tools.describe_catalog(),
        "styles": [{"id": look.id, "name": look.names["zh"], "group": look.group} for look in canvas_tools.style_wall()],
    }


@tool("edit_canvas", title="编辑节点画布", description="在画布上加节点、连线、改节点、删节点、分组（可嵌套一层、可折叠）、对齐、等距分布、自动排列。一次请求的全部操作作为一个事务生效：只产生一个新版本，任何一步不合法则全部不生效。不花钱，运行节点要另外确认。", effect="write",
      properties={
          "canvas_id": {"type": "string"},
          "operations": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 100, "description": CANVAS_OP_CHEATSHEET},
          "base_version": {"type": "integer", "description": "基于哪一版修改；给了且画布已变化则拒绝"},
      }, required=["operations"])
def edit_canvas(*, service, user, task_id: str, operations: list, canvas_id: str = "main", base_version: int | None = None):
    if not isinstance(operations, list) or not operations or not all(isinstance(item, Mapping) for item in operations):
        raise ValueError("operations 必须是非空的对象列表")
    from app.core import studio_canvas

    studio, project_id, owner = _canvas_project(service, user, task_id)
    canvas_id = str(canvas_id)
    result = _canvas_call(studio.edit_canvas, project_id, owner, operations, canvas_id=canvas_id, base_version=base_version)
    version = int(result["version"])

    def document(at: int) -> dict[str, Any]:
        record = studio.repository.get_canvas_version(project_id, owner, at, canvas_id=canvas_id) if at > 0 else None
        return record.model_dump(mode="json") if record else {"nodes": [], "edges": []}

    # The UI brings what this edit touched into view; consecutive versions, so nobody else's change is in the diff.
    changed = studio_canvas.changed_node_ids(document(version - 1), document(version))
    return {**result, "ui_action": {"type": "canvas_changed", "canvas_id": canvas_id, "version": version, "node_ids": changed}}


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


__all__ = ["ASSISTANT_LABEL", "EFFECTS", "Tool", "ToolCatalog", "ToolError", "catalog", "stage_operations_guide", "tool"]

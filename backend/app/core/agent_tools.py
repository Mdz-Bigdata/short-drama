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


_WORDING_FILE = "agent_tools"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/agent_tools.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

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


_TASK = {"task_id": {"type": "string", "description": _text_of("module.task.task_id.description")}}
_CONFIRM = {"confirm": {"type": "boolean", "description": _text_of("module.confirm.confirm.description")}}


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
            raise ToolError(_text_of("get.text").format(name))
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
                raise ToolError(_text_of("call.text"))
            task = service.repo.get_task(task_id)
            if not task:
                raise ToolError(_text_of("call.text.2").format(task_id))
            owner = str(task.get("owner_user_id") or "")
            if owner:
                write = tool.effect != "read"
                decision = authorize(user, owner_id=owner, write=write)
                if not decision.allowed:
                    raise ToolError(_text_of("call.text.3").format(task_id))
                if decision.cross_account:
                    record_access_from_thread(user, resource_id=task_id, owner_id=owner, write=write, via=f"agent.{name}")
        confirmed = bool(args.pop("confirm", None))
        # A model gets the shape of a tool wrong; that is an answer for it to act on, not a crash of the turn.
        schema = tool.input_schema
        missing = [key for key in schema.get("required") or [] if key not in args and key != "confirm"]
        unknown = [key for key in args if key not in schema.get("properties", {})]
        if missing or unknown:
            problems = ([_text_of("call.problems").format('、'.join(missing))] if missing else []) + ([_text_of("call.problems.2").format('、'.join(unknown))] if unknown else [])
            return {"ok": False, "error": "；".join(problems)}
        try:
            if tool.effect == "paid" and not confirmed:
                # The proposal says what the money goes on, so the person confirms a scope and not just a tool name.
                scope = str(tool.quote(service=service, **args) or "").strip() if tool.quote else ""
                return {"ok": False, "needs_confirmation": True, "tool": name, "arguments": dict(args),
                        "message": _text_of("call.message").format(tool.title, f'（{scope}）' if scope else '')}
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
_SCENE = {"scene_id": {"type": "string", "description": _text_of("module.scene.scene_id.description")}}
#: 助手在导演台留下的改动标签：「助手：挪 林夏」。
ASSISTANT_LABEL = _text_of("module.assistant_label")
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
            target = _text_of("_ops_summary.target").format(item['shot_id'])
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
    known = "、".join(str(record["name"]).strip() for record in records[:12]) or _text_of("_character_name.known")
    raise LookupError(_text_of("_character_name.text").format(name, known))


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
        raise LookupError(_text_of("_face_edit.text"))
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


@tool("list_projects", title=_text_of("list_projects.title"), description=_text_of("list_projects.description"), effect="read", needs_task=False,
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


_POETRY_FORMS = list(_words_of("module.poetry_forms"))


@tool("search_poetry", title=_text_of("search_poetry.title"), effect="read", needs_task=False,
      description=_text_of("search_poetry.description"),
      properties={
          "query": {"type": "string", "description": _text_of("search_poetry.properties.query.description")},
          "author": {"type": "string", "description": _text_of("search_poetry.properties.author.description")},
          "theme": {"type": "string"}, "emotion": {"type": "string"},
          "form": {"type": "string", "enum": _POETRY_FORMS},
          "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
      })
def search_poetry(*, service, user, query: str = "", author: str = "", theme: str = "", emotion: str = "", form: str = "", limit: int = 10):
    from app.core import poetry_library

    found = poetry_library.search(query, author=author, theme=theme, emotion=emotion, form=form, limit=limit)
    return {"items": [poetry_library.summary(poem) for poem in found], "count": len(found)}


@tool("get_poem", title=_text_of("get_poem.title"), effect="read", needs_task=False,
      description=_text_of("get_poem.description"),
      properties={
          "id": {"type": "string", "description": _text_of("get_poem.properties.id.description")},
          "title": {"type": "string", "description": _text_of("get_poem.properties.title.description")},
          "author": {"type": "string"},
      })
def get_poem(*, service, user, id: str = "", title: str = "", author: str = ""):
    from app.core import poetry_library

    if id:
        return poetry_library.detail(poetry_library.library().get(id))  # an unknown id comes back as the tool's error
    if not title:
        raise ValueError(_text_of("get_poem.text"))
    matches = poetry_library.find_titled(title, author=author)
    if not matches:
        raise LookupError(_text_of("get_poem.text.2").format(title) + (f"（{author}）" if author else ""))
    if len(matches) > 1:
        return {"ambiguous": [poetry_library.summary(poem) for poem in matches[:10]]}
    return poetry_library.detail(matches[0])


@tool("get_project", title=_text_of("get_project.title"), description=_text_of("get_project.description"), effect="read")
def get_project(*, service, user, task_id: str):
    task = service.repo.get_task(task_id)
    snapshot = service.workflow_snapshot(task)
    return {
        "task_id": task_id, "title": (task.get("config") or {}).get("title_suggestion"), "status": task.get("status"),
        "creation_mode": (task.get("config") or {}).get("creation_mode") or "drama",
        "current_stage": task.get("current_stage"), "next_stage": snapshot.get("next_stage"), "mode": snapshot.get("mode"),
        "hint": snapshot.get("hint"), "stages": [{"stage": s.get("stage"), "label": s.get("label"), "status": s.get("status")} for s in snapshot.get("stages") or []],
    }


@tool("get_screenplay", title=_text_of("get_screenplay.title"), description=_text_of("get_screenplay.description"), effect="read")
def get_screenplay(*, service, user, task_id: str):
    review = service.get_screenwriting_review(task_id)
    ledger = service.get_ledger(task_id)
    return {"review": review, "ledger": {"entries": ledger.get("entries"), "unsplit": ledger.get("unsplit")}}


@tool("get_episode", title=_text_of("get_episode.title"), description=_text_of("get_episode.description"), effect="read",
      properties={"episode": {"type": "integer", "minimum": 1}}, required=["episode"])
def get_episode(*, service, user, task_id: str, episode: int):
    from app.service import screenwriting_service as screenwriting

    task = service.repo.get_task(task_id)
    response = screenwriting.episode_response(task, int(episode))
    if response is None:
        raise ToolError(_text_of("get_episode.text").format(episode))
    data = response.model_dump()
    scenes = [{k: s.get(k) for k in ("scene_id", "duration_seconds", "setting", "scene_description", "utterances", "needs_replan")} for s in data["plan"].get("scenes") or []]
    return {"episode": data["episode"], "title": data["title"], "review": data["review"], "violations": data["violations"], "scenes": scenes}


@tool("get_shots", title=_text_of("get_shots.title"), description=_text_of("get_shots.description"), effect="read")
def get_shots(*, service, user, task_id: str):
    workspace = service.get_shot_visual_workspace(task_id) or {}
    shots = [{k: s.get(k) for k in ("shot_id", "scene_id", "shot_uid", "settings", "video_url", "stale", "stale_reason")} for s in workspace.get("shots") or []]
    return {"provider_family": workspace.get("provider_family"), "running": workspace.get("running"), "shots": shots}


@tool("get_timeline", title=_text_of("get_timeline.title"), description=_text_of("get_timeline.description"), effect="read")
def get_timeline(*, service, user, task_id: str):
    return service.get_timeline(task_id)


@tool("get_queue", title=_text_of("get_queue.title"), description=_text_of("get_queue.description"), effect="read")
def get_queue(*, service, user, task_id: str):
    return service.get_generation_queue(task_id)


@tool("get_usage", title=_text_of("get_usage.title"), description=_text_of("get_usage.description"), effect="read")
def get_usage(*, service, user, task_id: str):
    return service.usage_summary(task_id, limit=20)


# ---------------------------------------------------------------------------- write tools


@tool("review_episode", title=_text_of("review_episode.title"), description=_text_of("review_episode.description"), effect="write",
      properties={"episode": {"type": "integer", "minimum": 1}, "action": {"type": "string", "enum": ["confirm", "reopen"]}}, required=["episode", "action"])
def review_episode(*, service, user, task_id: str, episode: int, action: str):
    from app.core.screenwriting.review import ReviewError

    try:
        response = service.review_screenwriting_episode(task_id, int(episode), action, by=str(user.get("user_id") or "") or None)
    except ReviewError as exc:
        raise ValueError(str(exc)) from exc
    return {"episode": episode, "review": response.model_dump()["review"]}


@tool("edit_timeline", title=_text_of("edit_timeline.title"),
      description=(_text_of("edit_timeline.description")),
      effect="write",
      properties={
          "operation": {"type": "string", "enum": ["trim", "transition", "sound_join", "subtitle", "mute", "candidate", "review", "title", "bgm", "audio_source", "settings"]},
          "episode": {"type": "integer", "minimum": 1, "description": prompt_data.text("schema_production", "TimelineOperationRequest.description.episode")},
          "shot_id": {"type": "integer"},
          "shot_uid": {"type": "integer", "description": _text_of("edit_timeline.properties.shot_uid.description")},
          "start": {"type": "number"}, "end": {"type": ["number", "null"]}, "kind": {"type": "string"},
          "duration": {"type": "number"}, "text": {"type": "string"}, "muted": {"type": "boolean"}, "video_url": {"type": "string"},
          "decision": {"type": "string", "enum": ["pending", "approved", "rejected"]}, "note": {"type": "string"},
          "source": {"type": "string", "enum": ["none", "generated", "library"]}, "library_id": {"type": "string"}, "volume": {"type": "number"},
          "duck": {"type": "boolean"}, "bgm_start": {"type": "number", "minimum": 0}, "music_version": {"type": "string"},
          "join": {"type": "string", "enum": ["", "j_cut", "l_cut"]}, "seconds": {"type": "number"},
          "audio_source": {"type": "string", "enum": ["native", "tts", "none"]},
          "settings": {"type": "object", "properties": {key: {"type": "boolean"} for key in ("transitions", "dialogue", "subtitles", "title_card", "name_cards")},
                       "additionalProperties": False},
      }, required=["operation"])
def edit_timeline(*, service, user, task_id: str, operation: str, episode: int | None = None, **payload):
    from app.core.edit_timeline import TimelineError

    try:
        result = service.edit_timeline(task_id, operation, payload, episode=episode)
    except TimelineError as exc:
        raise ValueError(str(exc)) from exc
    timeline = result["timeline"]
    return {"summary": result["summary"], "settings": (result.get("post") or {}).get("settings"),
            "bgm": {k: (timeline.get("bgm") or {}).get(k) for k in ("source", "name", "volume", "start")}}


@tool("get_stage_checks", title=_text_of("get_stage_checks.title"), description=_text_of("get_stage_checks.description"), effect="read",
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


@tool("edit_stage", title=_text_of("edit_stage.title"), description=_text_of("edit_stage.description"), effect="write",
      properties={
          **_SCENE,
          "operations": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 100,
                         "description": _text_of("edit_stage.properties.operations.description")},
          "base_revision": {"type": "integer", "description": _text_of("edit_stage.properties.base_revision.description")},
          "label": {"type": "string", "description": _text_of("edit_stage.properties.label.description")},
      }, required=["scene_id", "operations"])
def edit_stage(*, service, user, task_id: str, scene_id: str, operations: list, base_revision: int | None = None, label: str = ""):
    if not isinstance(operations, list) or not operations:
        raise ValueError(_text_of("edit_stage.text"))
    _, scene_id = _scene(service, task_id, scene_id)
    return _stage_commit(service, task_id, scene_id, operations, base_revision, _label(label, _ops_summary(operations)))


@tool("repair_stage", title=_text_of("repair_stage.title"), description=_text_of("repair_stage.description"), effect="write",
      properties={**_SCENE, "codes": {"type": "array", "items": {"type": "string"}, "description": _text_of("repair_stage.properties.codes.description")}},
      required=["scene_id"])
def repair_stage(*, service, user, task_id: str, scene_id: str, codes: list | None = None):
    _, scene_id = _scene(service, task_id, scene_id)
    operation = {"op": "repair_checks"}
    if codes:
        operation["codes"] = [str(code) for code in codes]
    outcome = _stage_commit(service, task_id, scene_id, [operation], None, _label("", _text_of("repair_stage.outcome")))
    try:
        left = service.get_spatial_repairs(task_id, scene_id)
    except LookupError as exc:
        raise ValueError(str(exc)) from exc
    outcome["manual"] = [item["manual"] for item in left["repairs"] if item.get("manual")]
    return outcome


@tool("cancel_queued", title=_text_of("cancel_queued.title"), description=_text_of("cancel_queued.description"), effect="write",
      properties={"key": {"type": "string", "description": _text_of("cancel_queued.properties.key.description")}})
def cancel_queued(*, service, user, task_id: str, key: str | None = None):
    from app.core.generation_queue import CancelError

    try:
        result = service.cancel_generation_item(task_id, key)
    except CancelError as exc:
        raise ValueError(str(exc)) from exc
    return {"counts": result.get("counts"), "withdraw": result.get("withdraw")}


@tool("pause_project", title=_text_of("pause_project.title"), description=_text_of("pause_project.description"), effect="write",
      properties={"stop": {"type": "boolean", "default": False}})
def pause_project(*, service, user, task_id: str, stop: bool = False):
    task = service.pause_task(task_id, stop=bool(stop))
    return {"status": (task or {}).get("status")}


@tool("regenerate_shot", title=_text_of("regenerate_shot.title"), description=_text_of("regenerate_shot.description"), effect="write",
      properties={"shot_id": {"type": "integer"},
                  "scene_id": {"type": "string", "description": _text_of("regenerate_shot.properties.scene_id.description")},
                  "shot_uid": {"type": "integer", "description": _text_of("regenerate_shot.properties.shot_uid.description")},
                  "reason": {"type": "string"}}, required=["shot_id"])
def regenerate_shot(*, service, user, task_id: str, shot_id: int, reason: str = "", scene_id: str = "", shot_uid: int | None = None):
    service.regenerate_shot(task_id, int(shot_id), reason=reason, scene_id=str(scene_id or ""), shot_uid=int(shot_uid) if shot_uid else None)
    return {"shot_id": shot_id, "scene_id": scene_id, "stale": True}


# ---------------------------------------------------------------------------- paid tools


@tool("run_stage", title=_text_of("run_stage.title"), description=_text_of("run_stage.description"), effect="paid",
      properties={"stage": {"type": "integer", "minimum": 1, "maximum": 8}}, required=["stage"])
def run_stage(*, service, user, task_id: str, stage: int):
    claimed = service._claim_stage_task(task_id, int(stage))
    _start_background(service, task_id, int(stage), claimed, run_all=False)
    return {"started": True, "stage": int(stage)}


@tool("run_all", title=_text_of("run_all.title"), description=_text_of("run_all.description"), effect="paid")
def run_all(*, service, user, task_id: str):
    task = service.repo.get_task(task_id)
    stage = service.workflow_snapshot(task).get("next_stage")
    if stage is None:
        raise ValueError(_text_of("run_all.text"))
    claimed = service._claim_stage_task(task_id, int(stage), automatic=True)
    _start_background(service, task_id, int(stage), claimed, run_all=True)
    return {"started": True, "from_stage": int(stage)}


@tool("repair_episode", title=_text_of("repair_episode.title"), description=_text_of("repair_episode.description"), effect="paid",
      properties={"episode": {"type": "integer", "minimum": 1}}, required=["episode"])
def repair_episode(*, service, user, task_id: str, episode: int):
    response = service.repair_screenwriting_episode(task_id, int(episode), owner_user_id=str(user.get("user_id") or ""), is_admin=has_permission(user, PROJECT_WRITE_ANY))
    data = response.model_dump()
    return {"episode": episode, "repair": data.get("repair"), "review": data.get("review")}


@tool("render_timeline", title=_text_of("render_timeline.title"), description=_text_of("render_timeline.description"), effect="paid")
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


@tool("describe_stage", title=_text_of("describe_stage.title"), description=_text_of("describe_stage.description"), effect="read",
      properties=_SCENE, required=["scene_id"], result_chars=REFERENCE_RESULT_CHARS)
def describe_stage(*, service, user, task_id: str, scene_id: str):
    from app.core.spatial_stage import scoring
    from app.service import spatial_stage_service, stage_director_ops

    task, scene_id = _scene(service, task_id, scene_id)
    plan = spatial_stage_service.load_plan(task or {}, scene_id)
    if plan is None:
        raise ValueError(_text_of("describe_stage.text").format(scene_id))
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


@tool("list_stage_scenes", title=_text_of("list_stage_scenes.title"), description=_text_of("list_stage_scenes.description"), effect="read")
def list_stage_scenes(*, service, user, task_id: str):
    from app.core import stage_locator

    scenes = stage_locator.scenes_of(service.repo.get_task(task_id) or {})
    return {"count": len(scenes), "scenes": [{**scene, "shots": scene["shots"][:_DESCRIBE_SHOTS]} for scene in scenes]}


@tool("auto_plan_stage", title=_text_of("auto_plan_stage.title"), description=_text_of("auto_plan_stage.description"), effect="paid",
      properties={**_SCENE, "count": {"type": "integer", "minimum": 1, "maximum": 3}, "goal": {"type": "string", "description": _text_of("auto_plan_stage.properties.goal.description")},
                  "from_current": {"type": "boolean", "default": False, "description": _text_of("auto_plan_stage.properties.from_current.description")}},
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
        "next": _text_of("auto_plan_stage.next"),
    }


@tool("adopt_stage_plan", title=_text_of("adopt_stage_plan.title"), description=_text_of("adopt_stage_plan.description"), effect="write",
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
    return _stage_result(scene_id, revision=plan["revision"], snapshot_id=outcome.get("snapshot_id"), summary=_text_of("adopt_stage_plan.summary").format(chosen.get('title') or candidate_id),
                         failing=_failing(plan), changed=changed, stale_clips=stale)


@tool("build_stage_model", title=_text_of("build_stage_model.title"), description=_text_of("build_stage_model.description"), effect="paid",
      properties={
          **_SCENE, "description": {"type": "string"},
          "position": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2, "description": _text_of("build_stage_model.properties.position.description")},
          "yaw_deg": {"type": "number"}, "name": {"type": "string", "description": _text_of("build_stage_model.properties.name.description")},
      }, required=["scene_id", "description", "position"])
def build_stage_model(*, service, user, task_id: str, scene_id: str, description: str, position: list, yaw_deg: float = 0.0, name: str = ""):
    from app.service import stage_director_service

    _, scene_id = _scene(service, task_id, scene_id)
    proposal = stage_director_service.propose_model(service, task_id, scene_id, description=description)
    operation = {
        "op": "add_landmark", "name": (name or proposal["name"])[:120], "kind": proposal["kind"], "position": position, "yaw_deg": yaw_deg,
        "size": proposal["size"], "kit": proposal["kit"], "fitted_parts": proposal["parts"],
    }
    outcome = _stage_commit(service, task_id, scene_id, [operation], None, _label("", _text_of("build_stage_model.outcome").format(operation['name'])))
    return {**outcome, "model": {key: proposal[key] for key in ("name", "kit", "size", "summary")}, "parts": len(proposal["parts"])}


def _quote_stage_turn(*, service, task_id: str, scene_id: str, names: list | None = None, shot_id: int | None = None, **_rest) -> str:
    """AI 导演改一场 / 自动优化一场的确认提示：说清改哪一场、限定了谁和哪一镜、花几次调用。"""
    from app.core import stage_locator

    task, scene_id = _scene(service, task_id, scene_id)
    scope = stage_locator.scene_label(task, scene_id)
    if names:
        scope += _text_of("_quote_stage_turn.text").format('、'.join(str(item) for item in names[:6]))
    if shot_id:
        scope += _text_of("_quote_stage_turn.text.2").format(int(shot_id))
    return _text_of("_quote_stage_turn.text.3").format(scope)


@tool("direct_stage", title=_text_of("direct_stage.title"), description=_text_of("direct_stage.description"), effect="paid",
      properties={**_SCENE, "message": {"type": "string", "description": _text_of("direct_stage.properties.message.description")},
                  "names": {"type": "array", "items": {"type": "string"}, "description": _text_of("direct_stage.properties.names.description")},
                  "shot_id": {"type": "integer", "description": _text_of("direct_stage.properties.shot_id.description")}},
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


@tool("optimize_stage", title=_text_of("optimize_stage.title"), description=_text_of("optimize_stage.description"), effect="paid",
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
    return _turn_result(service, task_id, scene_id, before, outcome, summary=(str(goal or "").strip() or _text_of("optimize_stage.summary"))[:LABEL_CHARS])


def _batch_scenes(service, task_id: str, scene_ids: list | None, episode: int | None) -> tuple[dict[str, Any], list[str]]:
    """批量优化的范围：必须指明哪几场或第几集（不默认全剧），场数在 stage_director_ops.MAX_BATCH 以内。"""
    from app.service import stage_director_ops

    if not scene_ids and not episode:
        raise ValueError(_text_of("_batch_scenes.text"))
    task = service.repo.get_task(task_id) or {}
    wanted = [_scene_id(task, str(item)) for item in scene_ids or []]
    return task, stage_director_ops.batch_scope(task, scene_ids=wanted or None, episode=int(episode) if episode else None)


def _quote_optimize_scenes(*, service, task_id: str, scene_ids: list | None = None, episode: int | None = None, goal: str = "") -> str:
    """确认提示里说清这次优化哪几场、每场花多少次。"""
    from app.core import stage_locator

    task, wanted = _batch_scenes(service, task_id, scene_ids, episode)
    if not wanted:
        raise ValueError(_text_of("_quote_optimize_scenes.text").format(int(episode)) if episode else _text_of("_quote_optimize_scenes.text.2"))
    names = "、".join(stage_locator.scene_label(task, scene_id) for scene_id in wanted[:6]) + ("…" if len(wanted) > 6 else "")
    return _text_of("_quote_optimize_scenes.text.3").format(names, len(wanted)) + (_text_of("_quote_optimize_scenes.text.4").format(str(goal).strip()[:LABEL_CHARS]) if str(goal or "").strip() else "")


@tool("optimize_scenes", title=_text_of("optimize_scenes.title"), description=_text_of("optimize_scenes.description"), effect="paid",
      properties={"scene_ids": {"type": "array", "items": {"type": "string"}, "description": _text_of("optimize_scenes.properties.scene_ids.description")},
                  "episode": {"type": "integer", "minimum": 1, "description": _text_of("optimize_scenes.properties.episode.description")}, "goal": {"type": "string"}},
      quote=_quote_optimize_scenes)
def optimize_scenes(*, service, user, task_id: str, scene_ids: list | None = None, episode: int | None = None, goal: str = ""):
    from app.service import stage_director_ops

    _, wanted = _batch_scenes(service, task_id, scene_ids, episode)
    return stage_director_ops.optimize_scenes(service, task_id, scene_ids=wanted, goal=str(goal or ""))


@tool("revert_stage_step", title=_text_of("revert_stage_step.title"), description=_text_of("revert_stage_step.description"), effect="write",
      properties={**_SCENE, "snapshot_id": {"type": "string", "description": _text_of("revert_stage_step.properties.snapshot_id.description")}}, required=["scene_id"])
def revert_stage_step(*, service, user, task_id: str, scene_id: str, snapshot_id: str = ""):
    from app.core.spatial_stage.models import StagePlan
    from app.service import stage_director_ops, stage_director_service

    _, scene_id = _scene(service, task_id, scene_id)
    rows = stage_director_ops.list_snapshots(service, task_id, scene_id)
    wanted = str(snapshot_id or "").strip()
    row = next((item for item in rows if str(item.get("id")) == wanted), None) if wanted else (rows[0] if rows else None)
    if row is None:
        raise LookupError(_text_of("revert_stage_step.text") if not wanted else _text_of("revert_stage_step.text.2"))
    before = _current_stage(service, task_id, scene_id)
    outcome = stage_director_ops.restore_snapshot(service, task_id, scene_id, snapshot_id=str(row["id"]), base_revision=before.revision)
    plan = outcome["plan"]
    changed = stage_director_service.diff_plans(before, StagePlan.model_validate(plan))
    summary = _text_of("revert_stage_step.summary").format(row.get('name') or row.get('label') or row['id'])
    return {
        "restored": outcome.get("restored"), "kept_snapshot_id": outcome.get("kept_snapshot_id"),
        **_stage_result(scene_id, revision=plan["revision"], snapshot_id=outcome.get("kept_snapshot_id"), summary=summary,
                        failing=_failing(plan), changed=changed, stale_clips=outcome.get("stale_clips") or 0),
    }


@tool("get_stage_director", title=_text_of("get_stage_director.title"), description=_text_of("get_stage_director.description"), effect="read",
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


@tool("pin_stage_snapshot", title=_text_of("pin_stage_snapshot.title"), description=_text_of("pin_stage_snapshot.description"), effect="write",
      properties={**_SCENE, "snapshot_id": {"type": "string"}, "name": {"type": "string", "description": _text_of("pin_stage_snapshot.properties.name.description")},
                  "pinned": {"type": "boolean", "default": True}},
      required=["scene_id", "snapshot_id"])
def pin_stage_snapshot(*, service, user, task_id: str, scene_id: str, snapshot_id: str, name: str = "", pinned: bool = True):
    from app.service import stage_director_ops

    _, scene_id = _scene(service, task_id, scene_id)
    result = stage_director_ops.pin_snapshot(service, task_id, scene_id, snapshot_id=str(snapshot_id), name=str(name or ""), pinned=bool(pinned))
    return {**result, "snapshots": _snapshot_rows(result.get("snapshots") or [])}


@tool("get_project_memory", title=_text_of("get_project_memory.title"), description=_text_of("get_project_memory.description"), effect="read")
def get_project_memory(*, service, user, task_id: str):
    view = service.project_memory_view(task_id)
    return {"entries": [{key: row.get(key) for key in ("id", "text", "kind", "pinned", "source")} for row in (view or {}).get("entries", [])]}


@tool("remember_in_project", title=_text_of("remember_in_project.title"), description=_text_of("remember_in_project.description"), effect="write",
      properties={"text": {"type": "string"}, "kind": {"type": "string", "enum": ["preference", "decision", "fact"]}}, required=["text"])
def remember_in_project(*, service, user, task_id: str, text: str, kind: str = "decision"):
    from app.core import project_memory

    return {"entries": len((service.edit_project_memory(task_id, lambda task: project_memory.add(task, text, kind=kind, source="user")) or {}).get("entries", []))}


@tool("forget_in_project", title=_text_of("forget_in_project.title"), description=_text_of("forget_in_project.description"), effect="write",
      properties={"memory_id": {"type": "string"}}, required=["memory_id"])
def forget_in_project(*, service, user, task_id: str, memory_id: str):
    from app.core import project_memory

    try:
        return {"entries": len((service.edit_project_memory(task_id, lambda task: project_memory.remove(task, memory_id)) or {}).get("entries", []))}
    except project_memory.MemoryError as exc:
        raise ValueError(str(exc)) from exc


_RENAME = {
    "kind": {"type": "string", "enum": ["character", "scene", "prop"], "description": _text_of("module.kinds.description")},
    "name": {"type": "string"}, "new_name": {"type": "string"},
}


def _rename(service, task_id: str, kind: str, name: str, new_name: str, *, dry_run: bool):
    try:
        result = service.change_asset_identity(task_id, operation="rename", kind=str(kind), name=str(name), new_name=str(new_name), dry_run=dry_run)
    except RuntimeError as exc:  # a generation is running: the name cannot change under it
        raise ValueError(str(exc)) from exc
    if result is None:
        raise ToolError(_text_of("call.text.2").format(task_id))
    return result


@tool("preview_asset_rename", title=_text_of("preview_asset_rename.title"), description=_text_of("preview_asset_rename.description"), effect="read",
      properties=_RENAME, required=["kind", "name", "new_name"])
def preview_asset_rename(*, service, user, task_id: str, kind: str, name: str, new_name: str):
    return _rename(service, task_id, kind, name, new_name, dry_run=True)


@tool("rename_project_asset", title=_text_of("rename_project_asset.title"), description=_text_of("rename_project_asset.description"), effect="write",
      properties=_RENAME, required=["kind", "name", "new_name"])
def rename_project_asset(*, service, user, task_id: str, kind: str, name: str, new_name: str):
    return _rename(service, task_id, kind, name, new_name, dry_run=False)


@tool("remember_my_style", title=_text_of("remember_my_style.title"), description=_text_of("remember_my_style.description"), effect="write", needs_task=False,
      properties={"agent": {"type": "string", "enum": ["writer", "director_plan", "character_design", "storyboard", "promo"]}, "text": {"type": "string"}},
      required=["text"])
def remember_my_style(*, service, user, text: str, agent: str = "writer"):
    from app.core import prompt_preferences

    choice = prompt_preferences.add_line(str((user or {}).get("user_id") or ""), str(agent or "writer"), text)
    return {"agent": agent, "label": prompt_preferences.operation(agent).label, "mode": choice.mode, "text": choice.text}


@tool("blender_status", title=_text_of("blender_status.title"), description=_text_of("blender_status.description"), effect="read", needs_task=False)
def blender_status(*, service, user):
    return _previz().status()


@tool("get_blender_previz", title=_text_of("get_blender_previz.title"), description=_text_of("get_blender_previz.description"), effect="read",
      properties=_SCENE, required=["scene_id"])
def get_blender_previz(*, service, user, task_id: str, scene_id: str):
    task, scene_id = _scene(service, task_id, scene_id)
    return _previz().get_previz(task, scene_id)


@tool("render_blender_previz", title=_text_of("render_blender_previz.title"), description=_text_of("render_blender_previz.description"), effect="write",
      properties={**_SCENE,
                  "shot_ids": {"type": "array", "items": {"type": "integer"}, "description": _text_of("render_blender_previz.properties.shot_ids.description")},
                  "long_edge": {"type": "integer", "minimum": 480, "maximum": 3840, "default": 1920, "description": _text_of("render_blender_previz.properties.long_edge.description")}},
      required=["scene_id"])
def render_blender_previz(*, service, user, task_id: str, scene_id: str, shot_ids: list | None = None, long_edge: int = 1920):
    _, scene_id = _scene(service, task_id, scene_id)
    result = _previz_call(_previz().render_scene, service, task_id, scene_id,
                          shot_ids=[int(v) for v in shot_ids] if shot_ids else None, long_edge=int(long_edge))
    return {key: result[key] for key in ("video_url", "stills", "segments", "frames", "fps", "resolution", "reused", "live", "plan_revision")}


@tool("set_previz_options", title=_text_of("set_previz_options.title"), description=_text_of("set_previz_options.description"), effect="write",
      properties={**_SCENE,
                  "handheld_shots": {"type": "array", "items": {"type": "integer"}, "description": _text_of("set_previz_options.properties.handheld_shots.description")},
                  "reserved": {"type": "array", "items": {"type": "object", "properties": {
                      "shot_id": {"type": "integer"}, "from_s": {"type": "number"}, "to_s": {"type": "number"}, "label": {"type": "string"}}},
                      "description": _text_of("set_previz_options.properties.reserved.description")}},
      required=["scene_id"])
def set_previz_options(*, service, user, task_id: str, scene_id: str, handheld_shots: list | None = None, reserved: list | None = None):
    _, scene_id = _scene(service, task_id, scene_id)
    return _previz_call(_previz().set_options, service, task_id, scene_id, handheld_shots=handheld_shots, reserved=reserved)


@tool("attach_previz_to_shots", title=_text_of("attach_previz_to_shots.title"), description=_text_of("attach_previz_to_shots.description"), effect="write",
      properties={**_SCENE, "shot_ids": {"type": "array", "items": {"type": "integer"}, "description": _text_of("attach_previz_to_shots.properties.shot_ids.description")}},
      required=["scene_id"])
def attach_previz_to_shots(*, service, user, task_id: str, scene_id: str, shot_ids: list | None = None):
    _, scene_id = _scene(service, task_id, scene_id)
    return _previz_call(_previz().attach_to_shots, service, task_id, scene_id, shot_ids=shot_ids)


@tool("push_to_blender", title=_text_of("push_to_blender.title"), description=_text_of("push_to_blender.description"), effect="write",
      properties=_SCENE, required=["scene_id"])
def push_to_blender(*, service, user, task_id: str, scene_id: str):
    _, scene_id = _scene(service, task_id, scene_id)
    return _previz_call(_previz().push_live, service, task_id, scene_id)


@tool("pull_from_blender", title=_text_of("pull_from_blender.title"), description=_text_of("pull_from_blender.description"), effect="write",
      properties={**_SCENE, "apply": {"type": "boolean", "default": False}}, required=["scene_id"])
def pull_from_blender(*, service, user, task_id: str, scene_id: str, apply: bool = False):
    _, scene_id = _scene(service, task_id, scene_id)
    return _previz_call(_previz().pull_live, service, task_id, scene_id, apply=bool(apply))


# ---------------------------------------------------------------------------- 捏脸(第 3 阶段角色)

_FACE_PARTS = {
    "face": {"type": "object", "description": _text_of("module.face_parts.face.description")},
    "notes": {"type": "object", "description": _text_of("module.face_parts.notes.description")},
    "expressions": {"type": "object", "description": _text_of("module.face_parts.expressions.description")},
    "preset": {"type": "string", "description": _text_of("module.face_parts.preset.description")},
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
        "controls": {
            c.key: line(c.label, c.options) if c.kind == "choice"
            # 档位(磨皮、祛斑祛痘)从 0 数起，0 是不加；刻度是 -2..2，0 是沿用原描述。
            else _text_of("_face_catalog.levels").format(c.label, len(c.steps) - 1) if c.kind == "level"
            else _text_of("_face_catalog.controls").format(c.label, low, high)
            for c in cat.controls
        },
        "presets": {key: label for key, label in cat.preset_labels.items()},
        "expression_controls": {key: line(cat.expression_control_labels[key], options) for key, options in cat.expression_controls.items()},
        "expressions": {key: label for key, label, _words in cat.expressions},
        "limits": {key: cat.limits[key] for key in ("note_chars", "tell_chars", "habit_chars") if key in cat.limits},
    }


def _face_arguments(task: Mapping[str, Any], name: str, face, notes, expressions, preset: str, *, merge: bool):
    patch, unknown = _face_patch(face, notes, expressions, preset)
    if unknown:
        raise ValueError(_text_of("_face_arguments.text") + "；".join(unknown))
    if not any(patch[key] for key in ("face", "notes", "expressions", "preset")):
        raise ValueError(_text_of("_face_arguments.text.2"))
    return _face_merge(task, name, patch, merge=merge), patch


@tool("get_face_sculpt", title=_text_of("get_face_sculpt.title"), description=_text_of("get_face_sculpt.description"), effect="read",
      properties={"name": {"type": "string", "description": _text_of("get_face_sculpt.properties.name.description")}}, required=["name"], result_chars=REFERENCE_RESULT_CHARS)
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


@tool("get_sheet_prompt", title=_text_of("get_sheet_prompt.title"), description=_text_of("get_sheet_prompt.description"), effect="read",
      properties={"name": {"type": "string", "description": _text_of("get_sheet_prompt.properties.name.description")}}, required=["name"], result_chars=REFERENCE_RESULT_CHARS)
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


@tool("preview_face_sculpt", title=_text_of("preview_face_sculpt.title"), description=_text_of("preview_face_sculpt.description"), effect="read",
      properties={"name": {"type": "string"}, **_FACE_PARTS}, required=["name"])
def preview_face_sculpt(*, service, user, task_id: str, name: str, face: dict | None = None, notes: dict | None = None, expressions: dict | None = None, preset: str = ""):
    from app.core import face_sculpt

    task = service.repo.get_task(task_id) or {}
    name = _character_name(task, name)
    sculpt, patch = _face_arguments(task, name, face, notes, expressions, preset, merge=True)
    seen = face_sculpt.preview(face_sculpt.record_of(task, name), sculpt, task)
    return {"name": name, "patch": patch, "sculpt": sculpt.dump(), **{key: seen.get(key) for key in ("description", "face_text", "layers", "issues", "expressions", "sheet_stale")}}


@tool("sculpt_face", title=_text_of("sculpt_face.title"), description=_text_of("sculpt_face.description"), effect="write",
      properties={"name": {"type": "string"}, **_FACE_PARTS,
                  "merge": {"type": "boolean", "default": True, "description": _text_of("sculpt_face.properties.merge.description")},
                  "label": {"type": "string", "description": _text_of("sculpt_face.properties.label.description")}},
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


@tool("revert_face_sculpt", title=_text_of("revert_face_sculpt.title"), description=_text_of("revert_face_sculpt.description"), effect="write",
      properties={"name": {"type": "string"}, "snapshot_id": {"type": "string"}}, required=["name"])
def revert_face_sculpt(*, service, user, task_id: str, name: str, snapshot_id: str = ""):
    from app.core import face_sculpt

    task = service.repo.get_task(task_id) or {}
    name = _character_name(task, name)
    now = face_sculpt.current(task, name)
    wanted = str(snapshot_id or "").strip() or (now["history"][0]["id"] if now.get("history") else "")
    if not wanted:
        raise LookupError(_text_of("revert_face_sculpt.text"))
    before = str(face_sculpt.record_of(task, name).get("desc") or "")
    return _face_write(service, task_id, name, before, lambda stored, who: face_sculpt.revert(stored, who, wanted))


@tool("reset_face_sculpt", title=_text_of("reset_face_sculpt.title"), description=_text_of("reset_face_sculpt.description"), effect="write",
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
    "board": _text_of("module.storyboard_views.board"), "prompt": _text_of("module.storyboard_views.prompt"), "spatial": _text_of("module.storyboard_views.spatial"), "desk": _text_of("module.storyboard_views.desk"),
    "blender": _text_of("module.storyboard_views.blender"), "packages": _text_of("module.storyboard_views.packages"), "sheets": _text_of("module.storyboard_views.sheets"), "download": _text_of("module.storyboard_views.download"),
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
        known = "、".join(list(boards)[:12]) or _text_of("_board_entry.known")
        raise ValueError(_text_of("_board_entry.text").format(scene_id, known))
    return task, entry, scene_id


@tool("get_scene_board", title=_text_of("get_scene_board.title"), description=_text_of("get_scene_board.description"), effect="read",
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


@tool("get_scene_prompt", title=_text_of("get_scene_prompt.title"), description=_text_of("get_scene_prompt.description"), effect="read",
      properties=_SCENE, required=["scene_id"])
def get_scene_prompt(*, service, user, task_id: str, scene_id: str):
    _, entry, scene_id = _board_entry(service, task_id, scene_id)
    detail, prompt = entry.get("prompt_detail"), entry.get("grid_prompt") or ""
    if not detail and not prompt:
        raise ValueError(_text_of("get_scene_prompt.text").format(scene_id))
    return _compact({"scene_id": scene_id, "grid_prompt": prompt, "prompt_detail": detail})


@tool("get_prompt_packages", title=_text_of("get_prompt_packages.title"), description=_text_of("get_prompt_packages.description"), effect="read",
      properties={"scene_id": {"type": "string", "description": _text_of("get_prompt_packages.properties.scene_id.description")},
                  "package_seconds": {"type": "integer", "enum": [10, 15, 20, 30], "default": 15},
                  "variant": {"type": "string", "enum": ["standard", "continuous", "fight", "script_doc"], "default": "standard"},
                  "delivery": {"type": "string", "enum": list(_words_of("get_prompt_packages.properties.delivery.enum")), "default": _text_of("get_prompt_packages.properties.delivery.default")}})
def get_prompt_packages(*, service, user, task_id: str, scene_id: str = "", package_seconds: int = 15, variant: str = "standard", delivery: str = _text_of("get_prompt_packages.text")):
    if scene_id:
        _, scene_id = _scene(service, task_id, scene_id)
    payload = service.compile_prompt_packages(task_id, scene_id=scene_id, package_seconds=int(package_seconds), variant=variant, delivery=delivery)
    return _compact(payload or {})


@tool("get_asset_sheets", title=_text_of("get_asset_sheets.title"), description=_text_of("get_asset_sheets.description"), effect="read")
def get_asset_sheets(*, service, user, task_id: str):
    return _compact(service.compile_asset_sheets(task_id) or {})


@tool("redraw_scene", title=_text_of("redraw_scene.title"), description=_text_of("redraw_scene.description"), effect="write",
      properties=_SCENE, required=["scene_id"])
def redraw_scene(*, service, user, task_id: str, scene_id: str):
    _, scene_id = _scene(service, task_id, scene_id)
    result = service.redraw_spatial_scene(task_id, scene_id)
    if result is None:
        raise ValueError(_text_of("redraw_scene.text").format(scene_id))
    return {"scene_id": scene_id, "status": "pending", "next": _text_of("redraw_scene.next")}


@tool("open_storyboard_view", title=_text_of("open_storyboard_view.title"), description=_text_of("open_storyboard_view.description"), effect="read",
      properties={**_SCENE, "view": {"type": "string", "enum": list(STORYBOARD_VIEWS)}}, required=["scene_id", "view"])
def open_storyboard_view(*, service, user, task_id: str, scene_id: str, view: str):
    if view not in STORYBOARD_VIEWS:
        raise ValueError(_text_of("open_storyboard_view.text").format('、'.join(STORYBOARD_VIEWS)))
    _, _, scene_id = _board_entry(service, task_id, scene_id)
    return {"ui_action": {"type": "storyboard_view", "scene_id": scene_id, "view": view},
            "message": _text_of("open_storyboard_view.message").format(scene_id, STORYBOARD_VIEWS[view])}


# ---------------------------------------------------------------------------- 节点画布


def _canvas_project(service, user, task_id: str) -> tuple[Any, str, str]:
    """The studio service, and the project and owner this person's canvases for the task live under."""
    from app.api.studio_api import get_studio_service

    studio = get_studio_service()
    task = service.repo.get_task(task_id) or {}
    owner = str(user.get("user_id") or task.get("owner_user_id") or "")
    title = str((task.get("config") or {}).get("title_suggestion") or _text_of("_canvas_project.title"))
    return studio, studio.repository.project_for_task(task_id, owner, title).id, owner


def _canvas_call(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    from app.repository.studio_repo import ConcurrencyError

    try:
        return fn(*args, **kwargs)
    except ConcurrencyError as exc:
        raise ValueError(_text_of("_canvas_call.text").format(exc)) from exc
    except PermissionError as exc:
        raise ValueError(_text_of("_canvas_call.text.2")) from exc


CANVAS_OP_CHEATSHEET = (
    _text_of("module.canvas_op_cheatsheet")
)


@tool("get_canvas", title=_text_of("get_canvas.title"), description=_text_of("get_canvas.description"), effect="read",
      properties={"canvas_id": {"type": "string", "description": _text_of("get_canvas.properties.canvas_id.description")}})
def get_canvas(*, service, user, task_id: str, canvas_id: str = "main"):
    studio, project_id, owner = _canvas_project(service, user, task_id)
    result = _canvas_call(studio.summarize_canvas, project_id, owner, canvas_id=str(canvas_id))
    # The extent of the board stays readable even when the node list is cut short.
    return {**_compact(result, 9000), "bounds": result.get("bounds"), "operations": CANVAS_OP_CHEATSHEET}


@tool("list_canvas_tools", title=_text_of("list_canvas_tools.title"), description=_text_of("list_canvas_tools.description"), effect="read", needs_task=False)
def list_canvas_tools(*, service, user):
    from app.core import canvas_tools

    return {
        "tools": canvas_tools.describe_catalog(),
        "styles": [{"id": look.id, "name": look.names["zh"], "group": look.group} for look in canvas_tools.style_wall()],
    }


@tool("edit_canvas", title=_text_of("edit_canvas.title"), description=_text_of("edit_canvas.description"), effect="write",
      properties={
          "canvas_id": {"type": "string"},
          "operations": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 100, "description": CANVAS_OP_CHEATSHEET},
          "base_version": {"type": "integer", "description": _text_of("edit_canvas.properties.base_version.description")},
      }, required=["operations"])
def edit_canvas(*, service, user, task_id: str, operations: list, canvas_id: str = "main", base_version: int | None = None):
    if not isinstance(operations, list) or not operations or not all(isinstance(item, Mapping) for item in operations):
        raise ValueError(_text_of("edit_canvas.text"))
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


@tool("plan_canvas_workflow", title=_text_of("plan_canvas_workflow.title"), description=_text_of("plan_canvas_workflow.description"), effect="paid",
      properties={"brief": {"type": "string", "description": _text_of("plan_canvas_workflow.properties.brief.description")}, "canvas_id": {"type": "string"}}, required=["brief"])
def plan_canvas_workflow(*, service, user, task_id: str, brief: str, canvas_id: str = "main"):
    workflows, project_id, owner = _workflows(service, user, task_id)
    return _compact(_canvas_call(workflows.plan, project_id, owner, canvas_id=str(canvas_id), brief=str(brief), drama=service, user=user), 9000)


@tool("apply_canvas_workflow", title=_text_of("apply_canvas_workflow.title"), description=_text_of("apply_canvas_workflow.description"), effect="write",
      properties={"workflow_id": {"type": "string"}}, required=["workflow_id"])
def apply_canvas_workflow(*, service, user, task_id: str, workflow_id: str):
    workflows, project_id, owner = _workflows(service, user, task_id)
    return _compact(_canvas_call(workflows.apply, project_id, owner, str(workflow_id)), 6000)


@tool("canvas_workflow_status", title=_text_of("canvas_workflow_status.title"), description=_text_of("canvas_workflow_status.description"), effect="read",
      properties={"workflow_id": {"type": "string"}}, required=["workflow_id"])
def canvas_workflow_status(*, service, user, task_id: str, workflow_id: str):
    workflows, project_id, owner = _workflows(service, user, task_id)
    return _compact(_canvas_call(workflows.status, project_id, owner, str(workflow_id)), 6000)


@tool("quote_canvas_run", title=_text_of("quote_canvas_run.title"), description=_text_of("quote_canvas_run.description"), effect="read",
      properties={"canvas_id": {"type": "string"}, "node_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 50}}, required=["node_ids"])
def quote_canvas_run(*, service, user, task_id: str, node_ids: list, canvas_id: str = "main"):
    studio, project_id, owner = _canvas_project(service, user, task_id)
    return _compact(_canvas_call(studio.assess_canvas_run, project_id, owner, canvas_id=str(canvas_id), node_ids=[str(v) for v in node_ids], confirmed=None, drama=service, user=user))


@tool("run_canvas_nodes", title=_text_of("run_canvas_nodes.title"), description=_text_of("run_canvas_nodes.description"), effect="paid",
      properties={"canvas_id": {"type": "string"}, "node_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 50},
                  "confirmed_request_durations": {"type": "array", "items": {"type": "object"}, "description": _text_of("run_canvas_nodes.properties.confirmed_request_durations.description")}},
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


@tool("list_recipes", title=_text_of("list_recipes.title"), description=_text_of("list_recipes.description"), effect="read", needs_task=False,
      properties={
          "category": {"type": "string", "enum": ["short_drama", "ecommerce_image", "social_image", "general_image", "general_video", "general_audio"]},
          "output_type": {"type": "string", "enum": ["image", "video", "audio"]},
          "query": {"type": "string", "description": _text_of("list_recipes.properties.query.description")},
      })
def list_recipes(*, service, user, category: str = "", output_type: str = "", query: str = ""):
    from app.core import recipe_catalog

    return recipe_catalog.catalog().describe(category=category, output_type=output_type, query=query)


@tool("render_recipe", title=_text_of("render_recipe.title"), description=_text_of("render_recipe.description"), effect="read", needs_task=False,
      properties={
          "recipe_id": {"type": "string"},
          "inputs": {"type": "object", "description": _text_of("render_recipe.properties.inputs.description")},
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
            service.logger_error(_text_of("go.text"), str(exc)[:200]) if hasattr(service, "logger_error") else None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.create_task(go())
    else:
        threading.Thread(target=usage_ledger.carrying_context(lambda: asyncio.run(go())), name=f"agent-stage-{stage}", daemon=True).start()


__all__ = ["ASSISTANT_LABEL", "EFFECTS", "Tool", "ToolCatalog", "ToolError", "catalog", "stage_operations_guide", "tool"]

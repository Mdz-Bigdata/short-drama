# -*- coding: utf-8 -*-
"""The stage's model-first director: planning, conversation, optimisation and modelling for one scene.

Everything that asks a model runs outside the task's lock: the stage is read, the model works on a copy for as long as
it takes, and the result is written back only if the revision it started from is still current. What a turn changes is
one undoable step, kept here as a snapshot of the whole plan, because a model's edit has no inverse a person could read.
"""

from __future__ import annotations

import contextvars
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from app.core import project_memory, usage_ledger
from app.core.spatial_stage import blockout as stage_blockout
from app.core.spatial_stage import director_ai, glb, model_kit, repair, scoring
from app.core.spatial_stage.director_ai import DirectorAIError, Scope
from app.core.spatial_stage.models import StagePlan
from app.core.spatial_stage.planner import refresh
from app.service import spatial_stage_service as spatial
from app.service.director_desk_service import mark_captures_stale

logger = logging.getLogger("app.service.stage_director")

ASSET_KEY = "4_stage_director"
MAX_CHAT = 60
MAX_SNAPSHOTS = 4
STAGE_PLANNER_KEY = "stage_planner"
_DIRECTOR_PURPOSE = "stage_director"


class NoModelError(DirectorAIError):
    """No text model answered, so nothing was planned."""


def _entry(task: dict[str, Any], scene_id: str) -> dict[str, Any]:
    assets = task.setdefault("assets", {})
    store = assets.get(ASSET_KEY)
    if not isinstance(store, dict):
        store = assets[ASSET_KEY] = {}
    entry = store.get(scene_id)
    if not isinstance(entry, dict):
        entry = store[scene_id] = {}
    entry.setdefault("chat", [])
    entry.setdefault("snapshots", [])
    entry.setdefault("candidates", [])
    return entry


def _peek(task: Mapping[str, Any], scene_id: str) -> Mapping[str, Any]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    store = assets.get(ASSET_KEY) if isinstance(assets.get(ASSET_KEY), Mapping) else {}
    entry = store.get(scene_id)
    return entry if isinstance(entry, Mapping) else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _llm(service, task: Mapping[str, Any], model: str = "") -> director_ai.LLM:
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    chosen = model or str(config.get("llm_model") or "")
    title = str(config.get("title_suggestion") or config.get("titleSuggestion") or task.get("stage_name") or "")
    task_id = str(task.get("task_id") or "")

    def call(system: str, user: str, max_tokens: int) -> Optional[str]:
        with usage_ledger.bind_task(task_id, _DIRECTOR_PURPOSE):
            answer = service.gateway.call_llm(chosen, system, user, title, max_tokens=max_tokens)
        # The offline template is a story generator: it writes prose whatever it is asked.
        return None if service.gateway.last_answer_was_offline() else answer

    return call


def _load(service, task_id: str, scene_id: str) -> tuple[dict[str, Any], StagePlan]:
    task = service.repo.get_task(task_id)
    if not task:
        raise LookupError("任务不存在")
    if spatial.scene_record(task, scene_id) is None and spatial.load_plan(task, scene_id) is None:
        raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
    # A preview of a plan not stored yet must not be written back by a read.
    plan = spatial.load_plan(task, scene_id) or spatial.ensure_plan(deepcopy(task), scene_id)
    if plan is None:
        raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
    return task, plan


def _scene_text(task: Mapping[str, Any], scene_id: str) -> str:
    scene = spatial.scene_record(task, scene_id)
    if scene is None:
        return ""
    try:
        brief = spatial.brief_for(task, scene, spatial.scene_shots(task, scene_id))
    except Exception as error:  # noqa: BLE001 - the script is context; the stage can be directed without it
        logger.warning("[StageDirector] 场景 %s 的剧本上下文读取失败: %s", scene_id, error)
        return ""
    return brief.text


def _check_revision(plan: StagePlan, base_revision: int) -> None:
    if plan.revision != int(base_revision):
        raise spatial.StageConflict("空间方案已在其他页面更新，请刷新后重试")


def diff_plans(before: StagePlan, after: StagePlan) -> dict[str, list[Any]]:
    """What a change touched, by the names and ids the desk can select."""
    def by(items: Sequence[Any], key: str) -> dict[str, Any]:
        return {getattr(item, key): item.model_dump(mode="json") for item in items}

    people_before, people_after = by([a for a in before.actors if not a.crowd_id], "name"), by([a for a in after.actors if not a.crowd_id], "name")
    pieces_before, pieces_after = by(before.landmarks, "name"), by(after.landmarks, "name")
    lenses_before, lenses_after = by(before.cameras, "id"), by(after.cameras, "id")
    return {
        "actors": [name for name, value in people_after.items() if people_before.get(name) != value],
        "pieces_added": [name for name in pieces_after if name not in pieces_before],
        "pieces_changed": [name for name, value in pieces_after.items() if name in pieces_before and pieces_before[name] != value],
        "pieces_removed": [name for name in pieces_before if name not in pieces_after],
        "cameras": [camera_id for camera_id, value in lenses_after.items() if lenses_before.get(camera_id) != value],
    }


def _commit(
    service, task_id: str, scene_id: str, base_revision: int, plan: StagePlan, *, label: str,
    entry_update=None, snapshot_id: str = "", remember: Any = None,
) -> dict[str, Any]:
    """Write a stage made outside the lock, keeping what it replaces as one undoable step."""
    snapshot_id = snapshot_id or uuid.uuid4().hex[:12]

    def mutate(task: dict[str, Any]) -> dict[str, Any]:
        if service._has_running_generation(task):
            raise spatial.StageConflict("任务正在执行阶段，暂不能修改空间调度")
        project_memory.absorb(task, remember)
        current = spatial.load_plan(task, scene_id)
        if current is None:
            current = spatial.ensure_plan(task, scene_id)
        if current is None:
            raise LookupError(f"场景 {scene_id} 不在剧本大纲里")
        _check_revision(current, base_revision)
        entry = _entry(task, scene_id)
        entry["snapshots"] = [*entry["snapshots"], {
            "id": snapshot_id, "label": label[:80], "at": _now(), "revision": current.revision,
            "plan": current.model_dump(mode="json", exclude={"shots": {"__all__": {"screen"}}}),
        }][-MAX_SNAPSHOTS:]
        written = plan.model_copy(update={"revision": current.revision + 1, "source": "edited"})
        spatial.save_plan(task, written)
        spatial.mark_board_stale(task, scene_id)
        mark_captures_stale(task, scene_id)
        if entry_update is not None:
            entry_update(entry)
        return service._spatial_response(task, scene_id, written, persisted=True)

    response = service.repo.mutate_task(task_id, mutate)
    if not response:
        raise LookupError("任务不存在")
    return {**response, "snapshot_id": snapshot_id}


def _append_chat(service, task_id: str, scene_id: str, *rows: Mapping[str, Any], remember: Any = None) -> None:
    def mutate(task: dict[str, Any]) -> bool:
        entry = _entry(task, scene_id)
        entry["chat"] = [*entry["chat"], *rows][-MAX_CHAT:]
        project_memory.absorb(task, remember)
        return True

    service.repo.mutate_task(task_id, mutate)


def _snapshot_rows(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: item.get(key) for key in ("id", "label", "at", "revision")}
        for item in entry.get("snapshots") or [] if isinstance(item, Mapping)
    ]


def _candidate_rows(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [item for item in entry.get("candidates") or [] if isinstance(item, Mapping)]


def _planner_mode(task: Mapping[str, Any]) -> str:
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    return "rules" if str(config.get(STAGE_PLANNER_KEY) or "") == "rules" else "model"


def state(service, task_id: str, scene_id: str) -> dict[str, Any]:
    """What the desk's director panel shows when it opens."""
    task, plan = _load(service, task_id, scene_id)
    entry = _peek(task, scene_id)
    return {
        "chat": list(entry.get("chat") or []), "snapshots": _snapshot_rows(entry), "candidates": _candidate_rows(entry),
        "measured": scoring.score_plan(plan), "planner": plan.planner, "planner_note": plan.planner_note,
        "pipeline_planner": _planner_mode(task),
    }


def set_pipeline_planner(service, task_id: str, mode: str) -> dict[str, Any]:
    if mode not in ("model", "rules"):
        raise DirectorAIError("mode 只能是 model 或 rules")

    def mutate(task: dict[str, Any]) -> dict[str, Any]:
        task.setdefault("config", {})[STAGE_PLANNER_KEY] = mode
        return {"pipeline_planner": mode}

    result = service.repo.mutate_task(task_id, mutate)
    if not result:
        raise LookupError("任务不存在")
    return result


def plan_scene(
    service, task_id: str, scene_id: str, *, base_revision: int, count: int = 3, goal: str = "", model: str = "",
) -> dict[str, Any]:
    """Ask the model for several stagings and rank them against the rule plan. Nothing goes on the stage until one is adopted."""
    task, current = _load(service, task_id, scene_id)
    _check_revision(current, base_revision)
    count = max(1, min(int(count), director_ai.MAX_CANDIDATES))
    scene_text = _scene_text(task, scene_id)
    scene = spatial.scene_record(task, scene_id)
    # The model and the rules start from the same fresh blocking; a person's edits stay on the stage until one is adopted.
    baseline = spatial.plan_scene(deepcopy(task), scene, spatial.scene_shots(task, scene_id), keep_edits=False) if scene is not None else current
    llm = _llm(service, task, model)
    memory = project_memory.block(task, f"{goal} {scene_text}")

    def attempt(index: int, strategy: tuple[str, str]) -> Optional[director_ai.Candidate]:
        try:
            return director_ai.build_candidate(baseline, scene_text, strategy, llm, index, goal, memory)
        except Exception:  # noqa: BLE001 - one staging failing must not lose the others
            logger.exception("[StageDirector] 场景 %s 的方案「%s」生成失败", scene_id, strategy[0])
            return None

    strategies = list(director_ai._strategies(count))
    with ThreadPoolExecutor(max_workers=len(strategies), thread_name_prefix="stage-plan") as pool:
        futures = [pool.submit(contextvars.copy_context().run, attempt, *pair) for pair in enumerate(strategies)]
        results = [future.result() for future in futures]
    from_model = [item for item in results if item is not None]
    ranked = director_ai.rank([*from_model, director_ai.rules_candidate(baseline)])
    candidates = [item.as_dict() for item in ranked]

    def mutate(stored: dict[str, Any]) -> bool:
        _entry(stored, scene_id)["candidates"] = candidates
        return True

    service.repo.mutate_task(task_id, mutate)
    note = "" if from_model else "模型没有给出可用的方案（未配置文本模型，或它的回复无法解析），这里只有规则方案。"
    return {
        "candidates": candidates, "recommended": ranked[0].id, "used_model": bool(from_model), "note": note,
        "current": scoring.score_plan(current),
    }


def adopt_candidate(service, task_id: str, scene_id: str, *, candidate_id: str, base_revision: int) -> dict[str, Any]:
    task, current = _load(service, task_id, scene_id)
    _check_revision(current, base_revision)
    chosen = next((item for item in _candidate_rows(_peek(task, scene_id)) if item.get("id") == candidate_id), None)
    if chosen is None:
        raise LookupError("这个方案已经不在了，请重新规划")
    plan = StagePlan.model_validate(chosen["plan"])
    snapshot_id = uuid.uuid4().hex[:12]

    def update(entry: dict[str, Any]) -> None:
        entry["candidates"] = []
        entry["chat"] = [*entry["chat"], {
            "role": "assistant", "text": f"采用了方案「{chosen.get('title')}」：{chosen.get('rationale') or ''}",
            "at": _now(), "changed": diff_plans(current, plan), "compare": scoring.compare(scoring.score_plan(current), scoring.score_plan(plan)),
            "snapshot_id": snapshot_id,
        }][-MAX_CHAT:]

    return _commit(service, task_id, scene_id, base_revision, plan, label=f"方案：{chosen.get('title')}", entry_update=update, snapshot_id=snapshot_id)


def _scope_of(names: Sequence[str] | None, shot_id: int | None) -> Scope:
    return Scope(names=tuple(str(name) for name in names or () if str(name).strip()), shot_id=int(shot_id) if shot_id else None)


def chat(
    service, task_id: str, scene_id: str, *, message: str, base_revision: int, names: Sequence[str] | None = None,
    shot_id: int | None = None, model: str = "",
) -> dict[str, Any]:
    """One message of the conversation about this stage."""
    text = str(message or "").strip()
    if not text:
        raise DirectorAIError("请输入要调整的内容")
    task, current = _load(service, task_id, scene_id)
    _check_revision(current, base_revision)
    entry = _peek(task, scene_id)
    scope = _scope_of(names, shot_id)
    asked = {"role": "user", "text": text[:director_ai.MAX_MESSAGE], "at": _now(), **({"scope": scope.describe()} if scope.limited else {})}
    outcome = director_ai.run_turn(
        current, text, _llm(service, task, model), history=list(entry.get("chat") or []), scope=scope, scene_text=_scene_text(task, scene_id),
        memory=project_memory.block(task, text),
    )
    return _finish_turn(service, task_id, scene_id, base_revision, current, outcome, asked=asked, label=text[:40])


def _content(plan: StagePlan) -> dict[str, Any]:
    """What is on the stage, without the bookkeeping every edit bumps."""
    return plan.model_dump(mode="json", exclude={"revision", "source", "updated_at", "planner", "planner_note"})


def _finish_turn(
    service, task_id: str, scene_id: str, base_revision: int, before: StagePlan, outcome: Mapping[str, Any],
    *, asked: Mapping[str, Any], label: str,
) -> dict[str, Any]:
    after: StagePlan = outcome["plan"]
    changed = diff_plans(before, after)
    was, now = scoring.score_plan(before), scoring.score_plan(after)
    row: dict[str, Any] = {
        "role": "assistant", "text": outcome["reply"], "at": _now(), "errors": list(outcome["errors"])[:8],
        "rounds": outcome["rounds"],
    }
    noted = outcome.get("remember")
    if _content(before) == _content(after):
        # A model can say it moved a lens and leave it exactly where it was: the stage is what counts.
        if outcome["applied"]:
            row["text"] = f"{outcome['reply']}\n（这些操作执行后舞台没有实际变化。）"
        _append_chat(service, task_id, scene_id, asked, row, remember=noted)
        return {"message": row, "changed": False, "measured": was, "failing": repair.failing(before.checks)}
    row["changed"], row["compare"], row["snapshot_id"] = changed, scoring.compare(was, now), uuid.uuid4().hex[:12]

    def update(entry: dict[str, Any]) -> None:
        entry["chat"] = [*entry["chat"], asked, row][-MAX_CHAT:]

    response = _commit(service, task_id, scene_id, base_revision, after, label=label, entry_update=update, snapshot_id=row["snapshot_id"], remember=noted)
    return {**response, "message": row, "changed": True, "measured": now, "failing": repair.failing(after.checks)}


def optimize(
    service, task_id: str, scene_id: str, *, base_revision: int, goal: str = "", names: Sequence[str] | None = None,
    shot_id: int | None = None, model: str = "",
) -> dict[str, Any]:
    """Make the stage better on its own; a result that scores lower is not kept."""
    task, current = _load(service, task_id, scene_id)
    _check_revision(current, base_revision)
    scope = _scope_of(names, shot_id)
    outcome = director_ai.optimize(
        current, _llm(service, task, model), goal=goal, scene_text=_scene_text(task, scene_id), scope=scope,
        memory=project_memory.block(task, goal),
    )
    asked = {"role": "user", "text": goal.strip()[:director_ai.MAX_MESSAGE] or "自动优化这版舞台", "at": _now()}
    return _finish_turn(service, task_id, scene_id, base_revision, current, outcome, asked=asked, label="自动优化")


def revert(service, task_id: str, scene_id: str, *, snapshot_id: str, base_revision: int) -> dict[str, Any]:
    """Take back one model step; what came after it goes with it, since each snapshot is the whole stage."""
    def mutate(task: dict[str, Any]) -> dict[str, Any]:
        if service._has_running_generation(task):
            raise spatial.StageConflict("任务正在执行阶段，暂不能修改空间调度")
        current = spatial.load_plan(task, scene_id)
        if current is None:
            raise LookupError(f"场景 {scene_id} 还没有空间方案")
        _check_revision(current, base_revision)
        entry = _entry(task, scene_id)
        index = next((at for at, item in enumerate(entry["snapshots"]) if item.get("id") == snapshot_id), None)
        if index is None:
            raise LookupError("这一步已经撤销不了了：只保留最近几步")
        snapshot = entry["snapshots"][index]
        restored = StagePlan.model_validate(snapshot["plan"]).model_copy(update={"revision": current.revision + 1})
        restored = refresh(restored)
        entry["snapshots"] = entry["snapshots"][:index]
        entry["chat"] = [*entry["chat"], {"role": "assistant", "text": f"已撤销「{snapshot.get('label')}」。", "at": _now()}][-MAX_CHAT:]
        spatial.save_plan(task, restored)
        spatial.mark_board_stale(task, scene_id)
        mark_captures_stale(task, scene_id)
        return service._spatial_response(task, scene_id, restored, persisted=True)

    response = service.repo.mutate_task(task_id, mutate)
    if not response:
        raise LookupError("任务不存在")
    return response


def clear_chat(service, task_id: str, scene_id: str) -> dict[str, Any]:
    def mutate(task: dict[str, Any]) -> dict[str, Any]:
        _entry(task, scene_id)["chat"] = []
        return {"chat": []}

    result = service.repo.mutate_task(task_id, mutate)
    if not result:
        raise LookupError("任务不存在")
    return result


def propose_model(
    service, task_id: str, scene_id: str, *, description: str, size: Sequence[float] | None = None, model: str = "",
    image: bytes | None = None, content_type: str = "",
) -> dict[str, Any]:
    """Build one object from words (and a picture, when given). Nothing goes on the stage until the desk places it."""
    text = str(description or "").strip()
    if not text and not image:
        raise DirectorAIError("请描述要搭的东西，或给一张参考图")
    task, _ = _load(service, task_id, scene_id)
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    if image is None:
        found = model_kit.find_kit(text)
        # A library model that is exactly what was asked for costs nothing and is always the right size.
        if found is not None and text.lower() in {found.id, found.name.lower(), *map(str.lower, found.aliases)}:
            kit, parts, overall = model_kit.build_kit(found.id, size)
            return {
                "name": found.name, "kind": found.kind, "kit": kit.id, "size": overall, "summary": "模型库内置，不调用模型。",
                "parts": [part.model_dump(mode="json") for part in parts], "dropped": 0, "model": "",
            }
    system, user = director_ai.model_prompt(text or "参考图里的主要物体", size)
    if image is not None:
        with usage_ledger.bind_task(task_id, _DIRECTOR_PURPOSE):
            answer, used = service.gateway.describe_image(
                model or str(config.get("llm_model") or ""), system, user,
                service._reference_image_uri(image, content_type), max_tokens=director_ai.MODEL_MAX_TOKENS,
            )
        if not used:
            raise NoModelError("没有可看图的文本模型：请在模型配置里启用一个标为「多模态」的文本模型")
    else:
        answer, used = _llm(service, task, model)(system, user, director_ai.MODEL_MAX_TOKENS), model or str(config.get("llm_model") or "")
    if not answer:
        raise NoModelError("模型没有返回结果（未配置文本模型或请求失败），可以先从模型库里选，或稍后重试")
    return {**director_ai.read_model_reply(answer, text or "模型", size), "model": used}


def describe_blockout(
    service, task_id: str, scene_id: str, *, description: str, width_m: float | None = None, model: str = "",
) -> dict[str, Any]:
    """A grey-box set from words, in the same shape a reference image gives, so the desk treats both alike."""
    text = str(description or "").strip()
    if not text:
        raise stage_blockout.BlockoutError("请描述这个场景")
    task, _ = _load(service, task_id, scene_id)
    system, user = stage_blockout.text_prompt(text, width_m)
    answer = _llm(service, task, model)(system, user, stage_blockout.BLOCKOUT_MAX_TOKENS)
    if not answer:
        raise NoModelError("模型没有返回结果（未配置文本模型或请求失败），请检查模型配置后重试")
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    return {**stage_blockout.parse_blockout(answer).model_dump(mode="json"), "model": model or str(config.get("llm_model") or "")}


def export_model(service, task_id: str, scene_id: str, landmark_id: str) -> tuple[str, bytes]:
    _, plan = _load(service, task_id, scene_id)
    piece = next((item for item in plan.landmarks if item.id == landmark_id), None)
    if piece is None:
        raise LookupError("舞台上没有这个模型")
    safe = re.sub(r"[^\w一-鿿-]+", "_", piece.name).strip("_") or piece.id
    return f"{safe}.glb", glb.landmark_glb(piece)


# ---------------------------------------------------------------------------- the storyboard pipeline


def wants_model_blocking(task: Mapping[str, Any], plan: StagePlan | None) -> bool:
    """A stage the rules made and nobody has touched, in a project that has not opted out."""
    return plan is not None and _planner_mode(task) == "model" and plan.planner == "rules" and plan.source == "auto"


def blocking_model(service, task: Mapping[str, Any], plan: StagePlan | None) -> director_ai.LLM | None:
    """Who to ask for this scene's blocking, or None: a project with no reachable text model stays on the rules silently."""
    if not wants_model_blocking(task, plan):
        return None
    try:
        return _llm(service, task) if service.gateway.has_text_model() else None
    except Exception as error:  # noqa: BLE001 - blocking is an enhancement; never the reason a board fails
        logger.warning("[StageDirector] 判断文本模型是否可用时出错，本场沿用规则方案: %s", str(error)[:200])
        return None


_PIPELINE_ONLY_BLOCKING = "这一轮分镜表还没写，只做搭景、站位、轴线和姿势，不要写任何机位和运动操作（solve_camera、best_camera、move_camera、add_camera、use_camera、frame_shot、apply_camera_move、set_path、auto_route、set_timeline）。"
_CAMERA_OPS = frozenset({
    "solve_camera", "best_camera", "move_camera", "add_camera", "use_camera", "frame_shot", "apply_camera_move", "set_path", "auto_route",
    "set_timeline", "remove_camera", "clear_timeline",
})


def model_blocking(llm: director_ai.LLM, preview: StagePlan, scene_text: str, *, memory: str = "") -> StagePlan | None:
    """The model's set, marks and poses for a scene whose shots are not written yet, or None to keep the rule plan.

    One candidate and one call: this runs for every scene of an episode, and a person can ask for more at the desk.
    """
    try:
        reply = director_ai.read_reply(llm(
            director_ai._system(_PIPELINE_ONLY_BLOCKING, scene_text),
            director_ai.plan_prompt(preview, scene_text, director_ai.STRATEGIES[0], memory=memory),
            director_ai.PLAN_MAX_TOKENS,
        ))
        if not reply or not reply["operations"]:
            return None
        blocking = [op for op in reply["operations"] if op.get("op") not in _CAMERA_OPS]
        done = director_ai.apply_each(preview, blocking)
        if not done.applied:
            return None
        plan = director_ai._mannequins_for_poses(done.plan)
        return plan.model_copy(update={"planner": "model", "planner_note": reply["rationale"][:600], "source": "auto"})
    except Exception as error:  # noqa: BLE001 - blocking is an enhancement; never the reason a board fails
        logger.warning("[StageDirector] 模型规划站位失败，本场沿用规则方案: %s: %s", type(error).__name__, str(error)[:300])
        return None


def refine_lenses(plan: StagePlan) -> StagePlan:
    """After the shots are solved on a model's blocking: look for better lenses, keeping it an automatic plan."""
    try:
        return director_ai.polish(plan).model_copy(update={"source": "auto", "planner": plan.planner, "planner_note": plan.planner_note})
    except Exception as error:  # noqa: BLE001 - see above
        logger.warning("[StageDirector] 机位优化失败，沿用求解结果: %s", str(error)[:300])
        return plan


__all__ = [
    "ASSET_KEY", "NoModelError", "STAGE_PLANNER_KEY", "adopt_candidate", "blocking_model", "chat", "clear_chat", "describe_blockout", "diff_plans", "export_model",
    "model_blocking", "optimize", "plan_scene", "propose_model", "refine_lenses", "revert", "set_pipeline_planner", "state", "wants_model_blocking",
]

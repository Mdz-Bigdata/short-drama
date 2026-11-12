# -*- coding: utf-8 -*-
"""侧栏助手对舞台的操作：把一组编辑提交成一步可撤销的导演改动、固定与恢复快照、以当前舞台为底稿再规划、批量优化多场。

全部建立在 stage_director_service 之上：读（_load）、写（_commit）、对话行（_append_chat）、模型（_llm）都用它的，
这样快照、聊天记录和修订号的规则只有一处。固定的快照放在同一条目下单独的 pinned_snapshots 里，服务层只裁剪自己的 snapshots，
固定的不会被挤掉。
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any, Mapping, Optional, Sequence

from app.core import episode_cycle, project_memory, stage_locator
from app.core.spatial_stage import director_ai, repair, scoring
from app.core.spatial_stage import operations as stage_operations
from app.core.spatial_stage.director_ai import Scope
from app.core.spatial_stage.models import StagePlan
from app.service import spatial_stage_service as spatial
from app.service import stage_director_service as director

logger = logging.getLogger("app.service.stage_director_ops")

PINNED_KEY = "pinned_snapshots"
MAX_PINNED = 12
# 一次批量优化最多多少场：每场 1–3 次付费调用，且整批在同一个请求里顺序跑。
MAX_BATCH = 12
RUNNING_MESSAGE = "任务正在执行阶段，暂不能修改空间调度"
DEFAULT_LABEL = "助手改动"
KEEP_LABEL = "撤销前"
RESTORE_LABEL = "恢复「{name}」"
NOTE_FROM_CURRENT = "这次以当前舞台为底稿（保留了已有改动）。"
NOTE_NO_MODEL = "模型没有给出可用的方案（未配置文本模型，或它的回复无法解析），这里只有规则方案。"
OPTIMIZE_ASKED = "自动优化这版舞台"
OPTIMIZE_LABEL = "自动优化"
# 舞台改过之后，这一场已出的片段上写的过期原因（drama_service 里其他改动的同类文案）。
STALE_CLIP_REASON = "所属场景的站位或机位已由助手修改，需重跑第 5 阶段后生效"


def _now() -> str:
    return director._now()


def _entry(task: dict[str, Any], scene_id: str) -> dict[str, Any]:
    entry = director._entry(task, scene_id)
    if not isinstance(entry.get(PINNED_KEY), list):
        entry[PINNED_KEY] = []
    return entry


def _peek(task: Mapping[str, Any], scene_id: str) -> Mapping[str, Any]:
    return director._peek(task, scene_id)


def _content(plan: StagePlan) -> dict[str, Any]:
    """舞台上有什么，不含每次编辑都会变的记账字段；与对话那条路用同一把尺。"""
    return plan.model_dump(mode="json", exclude={"revision", "source", "updated_at", "planner", "planner_note"})


def _snapshot_of(plan: StagePlan) -> dict[str, Any]:
    return plan.model_dump(mode="json", exclude={"shots": {"__all__": {"screen"}}})


def _max_chat() -> int:
    return int(getattr(director, "MAX_CHAT", 60))


def _max_snapshots() -> int:
    return int(getattr(director, "MAX_SNAPSHOTS", 4))


def ensure_idle(service, task: Mapping[str, Any]) -> None:
    """任务正在跑阶段时 _commit 一定会拒绝：问模型之前先看一眼，别把付费调用花在落不下来的改动上。"""
    if service._has_running_generation(task):
        raise spatial.StageConflict(RUNNING_MESSAGE)


def mark_scene_clips_stale(task: dict[str, Any], scene_id: str, reason: str = STALE_CLIP_REASON) -> int:
    """把这一场已出的片段标为过期，返回标了几段。

    带场号（或镜头编号表）的片段按场号 / 镜头编号对；没有场号的旧片段按它的镜号对到本场的分镜，
    与 episode_cycle.clip_for 找「这一镜的视频」是同一条规则。
    """
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    clips = assets.get("5")
    if not isinstance(clips, list):
        return 0
    wanted = str(scene_id or "").strip()
    shots = [
        shot for shot in (assets.get("4") if isinstance(assets.get("4"), list) else [])
        if isinstance(shot, Mapping) and str(shot.get("scene_id") or "").strip() == wanted
    ]
    uids = {episode_cycle.shot_uid(shot) for shot in shots}
    legacy_ids = {str(shot.get("shot_id")) for shot in shots}
    count = 0
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        if clip.get("scene_id") or clip.get("shot_uids"):
            hit = str(clip.get("scene_id") or "").strip() == wanted or any(uid in uids for uid in episode_cycle.covered_uids(clip))
        else:
            hit = str(clip.get("shot_id")) in legacy_ids
        if hit:
            clip["stale"] = True
            clip["stale_reason"] = reason
            count += 1
    return count


def _mark_stale(service, task_id: str, scene_id: str) -> int:
    """舞台落地之后把这一场的片段标为过期。_commit 的 entry_update 只拿到导演台条目、拿不到任务，所以紧跟着单独写一次。"""
    count = service.repo.mutate_task(task_id, lambda task: mark_scene_clips_stale(task, scene_id))
    if count is None:
        raise LookupError("任务不存在")
    return int(count)


# ---------------------------------------------------------------------------- 1. 提交一组编辑


def commit_operations(
    service, task_id: str, scene_id: str, *, operations: Sequence[Mapping[str, Any]], base_revision: int | None = None,
    label: str = "", solve: bool | None = False,
) -> dict[str, Any]:
    """把一组舞台操作当作助手的一步提交：留快照、记一条对话，舞台没变就什么都不写。"""
    task, before = director._load(service, task_id, scene_id)
    if base_revision is not None:
        director._check_revision(before, base_revision)
    after = stage_operations.apply_operations(before, operations, solve=solve)
    was, now = scoring.score_plan(before), scoring.score_plan(after)
    if _content(before) == _content(after):
        persisted = spatial.load_plan(task, scene_id) is not None
        return {
            **service._spatial_response(task, scene_id, before, persisted=persisted),
            "changed": False, "measured": was, "failing": repair.failing(before.checks), "snapshot_id": None, "stale_clips": 0,
        }
    text = str(label or "").strip() or DEFAULT_LABEL
    diff = director.diff_plans(before, after)
    snapshot_id = uuid.uuid4().hex[:12]
    row = {
        "role": "assistant", "text": text, "at": _now(), "changed": diff, "compare": scoring.compare(was, now), "snapshot_id": snapshot_id,
    }

    def update(entry: dict[str, Any]) -> None:
        entry["chat"] = [*entry["chat"], row][-_max_chat():]

    response = director._commit(
        service, task_id, scene_id, before.revision, after, label=text[:40], entry_update=update, snapshot_id=snapshot_id,
    )
    stale = _mark_stale(service, task_id, scene_id)
    return {**response, "snapshot_id": snapshot_id, "changed": diff, "measured": now, "failing": repair.failing(after.checks), "stale_clips": stale}


# ---------------------------------------------------------------------------- 2. 快照：固定、列出、恢复


def _pinned_rows(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in entry.get(PINNED_KEY) or [] if isinstance(item, Mapping)]


def _service_rows(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in entry.get("snapshots") or [] if isinstance(item, Mapping)]


def _rows(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """服务层的快照和固定的快照合在一起，同一 id 以固定的为准，新的在前。"""
    merged: dict[str, dict[str, Any]] = {}
    order: dict[str, int] = {}
    for index, item in enumerate(_service_rows(entry)):
        merged[str(item.get("id"))] = {
            "id": item.get("id"), "label": item.get("label") or "", "name": "", "pinned": False,
            "revision": item.get("revision"), "at": item.get("at") or "",
        }
        order[str(item.get("id"))] = index
    for item in _pinned_rows(entry):
        merged[str(item.get("id"))] = {
            "id": item.get("id"), "label": item.get("label") or "", "name": item.get("name") or "", "pinned": True,
            "revision": item.get("revision"), "at": item.get("at") or "",
        }
    # Same second and same revision happen within one restore: the service list's own order breaks the tie.
    return sorted(
        merged.values(), key=lambda row: (str(row["at"]), int(row["revision"] or 0), order.get(str(row["id"]), -1)), reverse=True,
    )


def list_snapshots(service, task_id: str, scene_id: str) -> list[dict[str, Any]]:
    task = service.repo.get_task(task_id)
    if not task:
        raise LookupError("任务不存在")
    return _rows(_peek(task, scene_id))


def pin_snapshot(service, task_id: str, scene_id: str, *, snapshot_id: str, name: str = "", pinned: bool = True) -> dict[str, Any]:
    """把一步留成有名字的快照（服务层裁剪时不会丢），或取消固定。"""
    wanted = str(snapshot_id or "").strip()
    title = str(name or "").strip()[:80]

    def mutate(task: dict[str, Any]) -> dict[str, Any]:
        entry = _entry(task, scene_id)
        kept = [item for item in entry[PINNED_KEY] if isinstance(item, Mapping) and str(item.get("id")) != wanted]
        if not pinned:
            entry[PINNED_KEY] = kept
            return {"id": wanted, "pinned": False, "snapshots": _rows(entry)}
        already = next((item for item in entry[PINNED_KEY] if isinstance(item, Mapping) and str(item.get("id")) == wanted), None)
        source = already or next((item for item in entry["snapshots"] if isinstance(item, Mapping) and str(item.get("id")) == wanted), None)
        if source is None:
            raise LookupError("这一步的快照已经不在了，只能固定最近几步")
        if already is None and len(kept) >= MAX_PINNED:
            raise ValueError(f"最多固定 {MAX_PINNED} 个快照，请先取消一些")
        row = {
            "id": wanted, "name": title or str(source.get("name") or source.get("label") or ""), "label": str(source.get("label") or ""),
            "at": source.get("at") or _now(), "revision": source.get("revision"), "plan": deepcopy(source.get("plan")), "pinned": True,
        }
        entry[PINNED_KEY] = [*kept, row]
        return {"id": wanted, "pinned": True, "name": row["name"], "snapshots": _rows(entry)}

    result = service.repo.mutate_task(task_id, mutate)
    if not result:
        raise LookupError("任务不存在")
    return result


def _kept_row(current: StagePlan) -> dict[str, Any]:
    """现在的舞台留成一条「撤销前」快照，恢复这一步就能再做回来。"""
    return {"id": uuid.uuid4().hex[:12], "label": KEEP_LABEL, "at": _now(), "revision": current.revision, "plan": _snapshot_of(current)}


def _append_kept(service, task_id: str, scene_id: str, kept: Mapping[str, Any]) -> int:
    """恢复落地后的那次写：留下「撤销前」，顺手把这一场的片段标为过期；返回标了几段。"""
    def mutate(task: dict[str, Any]) -> int:
        entry = _entry(task, scene_id)
        entry["snapshots"] = [*entry["snapshots"], dict(kept)][-_max_snapshots():]
        return mark_scene_clips_stale(task, scene_id)

    count = service.repo.mutate_task(task_id, mutate)
    if count is None:
        raise LookupError("任务不存在")
    return int(count)


def restore_snapshot(service, task_id: str, scene_id: str, *, snapshot_id: str, base_revision: int | None = None) -> dict[str, Any]:
    """回到某个快照（服务层的或固定的）；先把现在的舞台留成「撤销前」，恢复本身也能撤销。"""
    wanted = str(snapshot_id or "").strip()
    task, current = director._load(service, task_id, scene_id)
    if base_revision is not None:
        director._check_revision(current, base_revision)
    entry = _peek(task, scene_id)
    pinned = next((item for item in _pinned_rows(entry) if str(item.get("id")) == wanted), None)
    in_service = any(str(item.get("id")) == wanted for item in _service_rows(entry))
    if pinned is None and not in_service:
        raise LookupError("没有这个快照：它可能已被更早的步骤挤掉，固定下来的快照不会丢")
    if pinned is None:
        # revert 会把目标之后的快照都裁掉，「撤销前」先留会被挤掉（列表满时还会挤掉目标本身）：恢复完再写。
        # revert 自己会在锁里做占用与修订号检查，被拒绝时还没写任何东西。
        kept = _kept_row(current)
        response = director.revert(service, task_id, scene_id, snapshot_id=wanted, base_revision=current.revision)
        stale = _append_kept(service, task_id, scene_id, kept)
        return {**response, "restored": wanted, "kept_snapshot_id": kept["id"], "stale_clips": stale}
    # 固定快照这条路不单独写「撤销前」：_commit 本来就把被替换的这版留成一条快照（标签是这一步的名字），
    # 而且它在锁里、在占用与修订号检查之后才落地——被拒绝时不会多出一条空撤销。
    name = str(pinned.get("name") or pinned.get("label") or wanted)
    restored = StagePlan.model_validate(pinned["plan"])
    label = RESTORE_LABEL.format(name=name)
    snapshot_id = uuid.uuid4().hex[:12]
    row = {
        "role": "assistant", "text": f"已{label}。", "at": _now(), "changed": director.diff_plans(current, restored),
        "compare": scoring.compare(scoring.score_plan(current), scoring.score_plan(restored)), "snapshot_id": snapshot_id,
    }

    def update(stored_entry: dict[str, Any]) -> None:
        stored_entry["chat"] = [*stored_entry["chat"], row][-_max_chat():]

    response = director._commit(
        service, task_id, scene_id, current.revision, restored, label=label[:80], entry_update=update, snapshot_id=snapshot_id,
    )
    stale = _mark_stale(service, task_id, scene_id)
    return {**response, "restored": wanted, "kept_snapshot_id": snapshot_id, "stale_clips": stale}


# ---------------------------------------------------------------------------- 3. 以当前舞台为底稿再规划


def plan_from_current(
    service, task_id: str, scene_id: str, *, base_revision: int, count: int = 3, goal: str = "", model: str = "",
) -> dict[str, Any]:
    """与 plan_scene 同形，但底稿是现在的舞台（人改过的都在），候选存在同一处，采用的路不变。"""
    task, current = director._load(service, task_id, scene_id)
    director._check_revision(current, base_revision)
    count = max(1, min(int(count), director_ai.MAX_CANDIDATES))
    scene_text = director._scene_text(task, scene_id)
    baseline = current
    llm = director._llm(service, task, model)
    memory = project_memory.block(task, f"{goal} {scene_text}")

    def attempt(index: int, strategy: tuple[str, str]) -> Optional[director_ai.Candidate]:
        try:
            return director_ai.build_candidate(baseline, scene_text, strategy, llm, index, goal, memory)
        except Exception:  # noqa: BLE001 - 一版失败不该连累其他版
            logger.exception("[StageDirectorOps] 场景 %s 的方案「%s」生成失败", scene_id, strategy[0])
            return None

    strategies = list(director_ai._strategies(count))
    with ThreadPoolExecutor(max_workers=len(strategies), thread_name_prefix="stage-plan-current") as pool:
        futures = [pool.submit(contextvars.copy_context().run, attempt, *pair) for pair in enumerate(strategies)]
        results = [future.result() for future in futures]
    from_model = [item for item in results if item is not None]
    ranked = director_ai.rank([*from_model, director_ai.rules_candidate(baseline)])
    candidates = [item.as_dict() for item in ranked]

    def mutate(stored: dict[str, Any]) -> bool:
        director._entry(stored, scene_id)["candidates"] = candidates
        return True

    if not service.repo.mutate_task(task_id, mutate):
        raise LookupError("任务不存在")
    note = NOTE_FROM_CURRENT if from_model else f"{NOTE_FROM_CURRENT}{NOTE_NO_MODEL}"
    return {
        "candidates": candidates, "recommended": ranked[0].id, "used_model": bool(from_model), "note": note,
        "current": scoring.score_plan(current), "baseline": "current",
    }


# ---------------------------------------------------------------------------- 4. 批量优化


def _optimize_one(service, task_id: str, scene_id: str, *, goal: str, model: str) -> tuple[dict[str, Any], bool]:
    """一场走 optimize() 的同一条路：规则先修，再问模型，评分变低的不留。"""
    task, current = director._load(service, task_id, scene_id)
    ensure_idle(service, task)
    outcome = director_ai.optimize(
        current, director._llm(service, task, model), goal=goal, scene_text=director._scene_text(task, scene_id), scope=Scope(),
        memory=project_memory.block(task, goal),
    )
    asked = {"role": "user", "text": goal.strip()[:director_ai.MAX_MESSAGE] or OPTIMIZE_ASKED, "at": _now()}
    finished = director._finish_turn(service, task_id, scene_id, current.revision, current, outcome, asked=asked, label=OPTIMIZE_LABEL)
    changed = bool(finished.get("changed"))
    return {
        "changed": changed, "before": float(outcome["before"]["score"]), "after": float(outcome["after"]["score"]),
        "errors": [str(item) for item in outcome.get("errors") or []][:8], "snapshot_id": finished.get("snapshot_id") if changed else None,
        "stale_clips": _mark_stale(service, task_id, scene_id) if changed else 0,
    }, bool(outcome.get("used_model"))


def batch_scope(task: Mapping[str, Any], *, scene_ids: Sequence[str] | None = None, episode: int | None = None) -> list[str]:
    """这一批要优化哪些场：给了 scene_ids 就按它，否则按 episode（都没给就是全剧）；超过 MAX_BATCH 场拒绝，并说明匹配了多少场。"""
    wanted = [str(item).strip() for item in scene_ids or () if str(item).strip()]
    if not wanted:
        wanted = [
            scene["scene_id"] for scene in stage_locator.scenes_of(task)
            if episode is None or int(scene["episode"]) == int(episode)
        ]
    if len(wanted) > MAX_BATCH:
        where = f"第{int(episode)}集" if episode is not None else "全剧"
        raise ValueError(f"{where}有 {len(wanted)} 场，一次最多优化 {MAX_BATCH} 场，请用 scene_ids 指定要优化的场")
    return wanted


def optimize_scenes(
    service, task_id: str, *, scene_ids: Sequence[str] | None = None, episode: int | None = None, goal: str = "", model: str = "",
) -> dict[str, Any]:
    """依次优化多场（不开线程池）；一场读不出方案就记下错误继续下一场。calls 是用到模型的场数。

    任务正在跑阶段时任何一场都落不下来：开始前就拒绝，中途碰到也立即停下，不再为剩下的场花模型调用。
    """
    task = service.repo.get_task(task_id)
    if not task:
        raise LookupError("任务不存在")
    wanted = batch_scope(task, scene_ids=scene_ids, episode=episode)
    if wanted:
        ensure_idle(service, task)
    results: dict[str, dict[str, Any]] = {}
    calls = 0
    for scene_id in wanted:
        try:
            results[scene_id], used = _optimize_one(service, task_id, scene_id, goal=goal, model=model)
            calls += 1 if used else 0
        except spatial.StageConflict:
            raise
        except Exception as error:  # noqa: BLE001 - 一场失败不该停下其他场
            logger.warning("[StageDirectorOps] 场景 %s 优化失败: %s: %s", scene_id, type(error).__name__, str(error)[:300])
            results[scene_id] = {
                "changed": False, "before": 0.0, "after": 0.0, "errors": [str(error)[:300] or type(error).__name__], "snapshot_id": None, "stale_clips": 0,
            }
    return {"results": results, "scenes": len(wanted), "calls": calls, "stale_clips": sum(int(item.get("stale_clips") or 0) for item in results.values())}


__all__ = [
    "DEFAULT_LABEL", "KEEP_LABEL", "MAX_BATCH", "MAX_PINNED", "PINNED_KEY", "RESTORE_LABEL", "RUNNING_MESSAGE", "STALE_CLIP_REASON", "batch_scope",
    "commit_operations", "ensure_idle", "list_snapshots", "mark_scene_clips_stale", "optimize_scenes", "pin_snapshot", "plan_from_current", "restore_snapshot",
]

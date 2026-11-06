"""What the Task Center shows of a project's generation work, and how a failed item is retried.

A queue item's work only exists inside the stage-5 run that planned it, so a retry
is a new stage-5 run: the admission check, the bucket ceilings and the dependency
order all apply again, and finished clips are reused rather than paid for twice.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.core import generation_queue, video_failures, video_jobs
from app.core.generation_queue import FAILED, QUEUED, RUNNING, STATUS_LABEL
from app.service.drama_service import StagePrerequisiteError

_TERMINAL_FOR_PROGRESS = frozenset({generation_queue.DONE, generation_queue.FAILED, generation_queue.CANCELLED, generation_queue.SKIPPED})


class RetryRefused(Exception):
    def __init__(self, message: str, admission: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.admission = dict(admission) if admission else None


def _run_is_going(task: Mapping[str, Any]) -> bool:
    if task.get("status") != "running":
        return False
    return int((task.get("stage_progress") or {}).get("stage") or 0) == 5


def _failure_for(task: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any] | None:
    failures = (task.get("assets") or {}).get(video_failures.FAILURES_KEY)
    if not isinstance(failures, Mapping) or item.get("status") != FAILED:
        return None
    uid = _shot_uid(item)
    if uid is None:
        return None
    for key, entry in failures.items():
        if not isinstance(entry, Mapping):
            continue
        if str(key) == str(uid) or uid in {int(value) for value in entry.get("shot_uids") or [] if str(value).isdigit()}:
            return {name: entry.get(name) for name in ("kind", "code", "message", "inputs") if entry.get(name) not in (None, "", [])}
    return None


def _shot_uid(item: Mapping[str, Any]) -> int | None:
    job_key = str((item.get("meta") or {}).get("job_key") or "")
    head = job_key.split(":", 1)[0]
    return int(head) if head.isdigit() else None


def _provider_job(task: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any] | None:
    jobs = (task.get("assets") or {}).get(video_jobs.JOBS_KEY)
    if not isinstance(jobs, Mapping):
        return None
    job = jobs.get(str((item.get("meta") or {}).get("job_key") or ""))
    if not isinstance(job, Mapping):
        return None
    return {name: job.get(name) for name in ("job_id", "status", "family", "model", "submitted_at", "error") if job.get(name)}


def _log(item: Mapping[str, Any], job: Mapping[str, Any] | None, retries: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The item's life in order, as it can be told from what the project recorded."""
    log: list[tuple[str, str]] = []
    for retry in retries:
        log.append((str(retry.get("at") or ""), f"重试；上一次的错误：{retry.get('error') or '未记录'}"))
    if item.get("queued_at"):
        log.append((str(item["queued_at"]), "进入队列"))
    if item.get("started_at"):
        log.append((str(item["started_at"]), "开始运行"))
    if job and job.get("job_id"):
        log.append((str(job.get("submitted_at") or item.get("started_at") or ""), f"供应商任务 {job['job_id']}：{job.get('status')}"))
    if item.get("finished_at"):
        text = STATUS_LABEL.get(str(item.get("status")), str(item.get("status")))
        detail = item.get("error") or item.get("reason")
        log.append((str(item["finished_at"]), f"{text}：{detail}" if detail else text))
    return [{"at": at, "text": text} for at, text in sorted(log, key=lambda entry: entry[0])]


def jobs_view(task: Mapping[str, Any], *, statuses: Iterable[str] = ()) -> dict[str, Any]:
    """Every job of the current or last run; ``statuses`` narrows the list, never the counts."""
    snapshot = generation_queue.snapshot_of(task) or {}
    items = [item for item in snapshot.get("items") or [] if isinstance(item, Mapping)]
    wanted = {status for status in statuses if status}
    going = _run_is_going(task)
    retries = [entry for entry in snapshot.get("retries") or [] if isinstance(entry, Mapping)]
    withdrawn = {str(key) for key in snapshot.get("withdraw") or []}
    settled = sum(1 for item in items if item.get("status") in _TERMINAL_FOR_PROGRESS)
    jobs = []
    for item in items:
        if wanted and item.get("status") not in wanted:
            continue
        job = _provider_job(task, item)
        status = item.get("status")
        jobs.append({
            **dict(item),
            "can_cancel": status == QUEUED and str(item.get("key")) not in withdrawn,
            "cancel_requested": str(item.get("key")) in withdrawn,
            # A run still going holds the project; its failures can be retried once it ends.
            "can_retry": status == FAILED and not going,
            "provider_job": job,
            "failure": _failure_for(task, item),
            "log": _log(item, job, [entry for entry in retries if entry.get("key") == item.get("key")]),
        })
    return {
        "task_id": str(task.get("task_id") or ""),
        "running": going,
        "run_id": snapshot.get("run_id"),
        "updated_at": snapshot.get("updated_at"),
        "counts": dict(snapshot.get("counts") or {}),
        "buckets": dict(snapshot.get("buckets") or {}),
        "progress": {
            "settled": settled, "total": len(items),
            "percent": round(100 * settled / len(items)) if items else 0,
            "running": sum(1 for item in items if item.get("status") == RUNNING),
            "label": str((task.get("stage_progress") or {}).get("label") or "") if going else "",
        },
        "jobs": jobs,
    }


def claim_retry(service: Any, task_id: str, key: str) -> dict[str, Any]:
    """Reserve a new stage-5 run for one failed item, or refuse with the reason; nothing is paid here.

    The claim's own prerequisite check holds the admission decision atomically; assessing
    first only gives the person the per-shot answer rather than a one-line refusal.
    """
    task = service.repo.get_task(task_id)
    if not task:
        raise LookupError("任务不存在")
    generation_queue.assert_retryable(task, key)
    if _run_is_going(task):
        raise RetryRefused("第 5 阶段正在运行，等它结束后再重试")
    admission = service.assess_video_admission(task_id)
    if admission and admission.get("decision") != "admitted":
        raise RetryRefused(_refusal_text(admission), admission)
    try:
        claimed = service._claim_stage_task(task_id, 5)
    except StagePrerequisiteError as exc:
        raise RetryRefused(str(exc), admission) from exc

    def remember(current: dict[str, Any]) -> dict[str, Any]:
        generation_queue.note_retry(current, key)
        return current

    # The worker runs on the task it is handed, so it must be handed the one that records the retry.
    return service.repo.mutate_task(task_id, remember) or claimed


def _refusal_text(admission: Mapping[str, Any]) -> str:
    if admission.get("decision") == "confirmation_required":
        tiers = "、".join(
            f"{item.get('scripted_seconds')}s→{item.get('requested_seconds')}s" for item in admission.get("confirmations") or []
            if isinstance(item, Mapping)
        )
        return f"重试前需先确认请求时长档位：{tiers}"
    problems = [
        problem.get("message") for shot in admission.get("shots") or [] if isinstance(shot, Mapping)
        for problem in shot.get("problems") or [] if isinstance(problem, Mapping) and problem.get("blocking")
    ]
    unique = list(dict.fromkeys(str(message) for message in problems if message))
    return "批量视频准入受阻，未重试：" + ("；".join(unique[:5]) or "请查看准入详情")

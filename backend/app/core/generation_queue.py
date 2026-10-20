"""A persistent queue of generation work for one project, run with a ceiling per provider and medium.

Every paid call a stage makes is an item in the queue: it waits (``queued``),
runs, and ends ``done``, ``failed``, ``cancelled`` or ``skipped``. The queue is
written onto the project after every change, so a restart shows exactly what
had been asked for and what was still waiting. Only a queued item can be
cancelled: a running one is already being paid for, so it is left to finish and
its result kept. An item may depend on others; it runs once they are all done,
and is skipped when any of them failed or was cancelled.

Items are grouped into buckets by provider family and medium (``seedance/video``,
``seedream/image``, ``minimax/audio`` …) and each bucket has its own ceiling, so a
slow video provider never starves the image or voice work beside it.
"""

from __future__ import annotations

import contextvars
import logging
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app import settings

logger = logging.getLogger("app.core.generation_queue")

QUEUE_KEY = "5_queue"

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
SKIPPED = "skipped"
FINAL = frozenset({DONE, FAILED, CANCELLED, SKIPPED})

# Default ceilings per medium; a provider family may get its own with
# GENERATION_CONCURRENCY_<MEDIUM>_<FAMILY> (e.g. GENERATION_CONCURRENCY_VIDEO_SEEDANCE=2).
_DEFAULT_CEILING = {"video": 2, "image": 3, "audio": 2, "text": 3}
_MAX_CEILING = 16

# One pool for the whole process; the buckets, not the pool, bound how much runs at once.
_POOL = ThreadPoolExecutor(max_workers=_MAX_CEILING, thread_name_prefix="generation")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bucket_of(family: str, medium: str) -> str:
    return f"{(family or 'unknown').strip().lower()}/{(medium or 'text').strip().lower()}"


def ceiling_for(bucket: str) -> int:
    """How many items of this bucket may run at once: the family's own knob, else the medium's."""
    family, _, medium = bucket.partition("/")
    default = _DEFAULT_CEILING.get(medium, 2)
    medium_wide = settings.env_int(f"GENERATION_CONCURRENCY_{medium.upper()}", default, minimum=1, maximum=_MAX_CEILING)
    key = f"GENERATION_CONCURRENCY_{medium.upper()}_{family.upper().replace('-', '_')}"
    return settings.env_int(key, medium_wide, minimum=1, maximum=_MAX_CEILING)


class CancelError(ValueError):
    """The item cannot be cancelled: it is unknown, already running, or already over."""


@dataclass
class Item:
    key: str
    label: str
    family: str
    medium: str
    depends_on: list[str] = field(default_factory=list)
    status: str = QUEUED
    queued_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    reason: str | None = None
    # Free-form facts for the person: shot id, candidate index, seconds …
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def bucket(self) -> str:
        return bucket_of(self.family, self.medium)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "family": self.family, "medium": self.medium, "bucket": self.bucket,
            "depends_on": list(self.depends_on), "status": self.status, "queued_at": self.queued_at,
            "started_at": self.started_at, "finished_at": self.finished_at, "error": self.error, "reason": self.reason,
            "meta": dict(self.meta),
        }


class Queue:
    """The items of one run, in the order they were added; ``snapshot`` is what gets persisted."""

    def __init__(self, items: Iterable[Item] = ()) -> None:
        self._items: dict[str, Item] = {}
        self._lock = threading.Lock()
        for item in items:
            self.add(item)

    def add(self, item: Item) -> Item:
        with self._lock:
            if item.key in self._items:
                raise ValueError(f"队列里已有 {item.key}")
            unknown = [dep for dep in item.depends_on if dep not in self._items]
            if unknown:
                raise ValueError(f"{item.key} 依赖的 {', '.join(unknown)} 不在队列里（依赖必须先入队）")
            self._items[item.key] = item
            return item

    def __len__(self) -> int:
        return len(self._items)

    def get(self, key: str) -> Item:
        return self._items[key]

    def items(self) -> list[Item]:
        return list(self._items.values())

    def by_status(self, *statuses: str) -> list[Item]:
        return [item for item in self._items.values() if item.status in statuses]

    def runnable(self) -> list[Item]:
        """Queued items whose every dependency is done, in queue order."""
        return [
            item for item in self._items.values()
            if item.status == QUEUED and all(self._items[dep].status == DONE for dep in item.depends_on)
        ]

    def cancel(self, key: str, *, reason: str = "cancelled") -> list[str]:
        """Withdraw one queued item; everything that depended on it is skipped. Returns the keys touched."""
        with self._lock:
            item = self._items.get(key)
            if item is None:
                raise CancelError(f"队列里没有 {key}")
            if item.status == RUNNING:
                raise CancelError(f"{item.label} 已在供应商那里运行，不能取消；等它结束后可以重做")
            if item.status in FINAL:
                raise CancelError(f"{item.label} 已经{STATUS_LABEL[item.status]}，无需取消")
            item.status = CANCELLED
            item.reason = reason
            item.finished_at = _now()
            return [key, *self._skip_dependents(key, f"依赖的 {item.label} 已取消")]

    def cancel_queued(self, *, reason: str = "cancelled") -> list[str]:
        """Withdraw every item still waiting; running ones finish and keep their result."""
        touched: list[str] = []
        for item in self.by_status(QUEUED):
            if item.status == QUEUED:
                touched.extend(self.cancel(item.key, reason=reason))
        return touched

    def _skip_dependents(self, key: str, reason: str) -> list[str]:
        skipped: list[str] = []
        for other in self._items.values():
            if other.status == QUEUED and key in other.depends_on:
                other.status = SKIPPED
                other.reason = reason
                other.finished_at = _now()
                skipped.append(other.key)
                skipped.extend(self._skip_dependents(other.key, reason))
        return skipped

    def mark_started(self, key: str) -> None:
        with self._lock:
            item = self._items[key]
            item.status = RUNNING
            item.started_at = _now()

    def mark_done(self, key: str) -> None:
        with self._lock:
            item = self._items[key]
            item.status = DONE
            item.finished_at = _now()
            item.error = None

    def mark_failed(self, key: str, error: str) -> list[str]:
        with self._lock:
            item = self._items[key]
            item.status = FAILED
            item.error = str(error)[:300]
            item.finished_at = _now()
            return [key, *self._skip_dependents(key, f"依赖的 {item.label} 失败")]

    def running_per_bucket(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.by_status(RUNNING):
            counts[item.bucket] = counts.get(item.bucket, 0) + 1
        return counts

    def snapshot(self, *, run_id: str | None = None) -> dict[str, Any]:
        items = [item.to_dict() for item in self._items.values()]
        buckets = sorted({item.bucket for item in self._items.values()})
        running = self.running_per_bucket()
        return {
            "run_id": run_id,
            "updated_at": _now(),
            "counts": {status: sum(1 for item in self._items.values() if item.status == status) for status in (QUEUED, RUNNING, DONE, FAILED, CANCELLED, SKIPPED)},
            "buckets": {bucket: {"limit": ceiling_for(bucket), "running": running.get(bucket, 0)} for bucket in buckets},
            "items": items,
        }

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any] | None) -> "Queue":
        queue = cls()
        for raw in (data or {}).get("items") or []:
            if not isinstance(raw, Mapping):
                continue
            item = Item(
                key=str(raw.get("key")), label=str(raw.get("label") or raw.get("key")), family=str(raw.get("family") or ""),
                medium=str(raw.get("medium") or "text"), depends_on=[str(d) for d in raw.get("depends_on") or []],
                status=str(raw.get("status") or QUEUED), queued_at=str(raw.get("queued_at") or _now()),
                started_at=raw.get("started_at"), finished_at=raw.get("finished_at"), error=raw.get("error"), reason=raw.get("reason"),
                meta=dict(raw.get("meta") or {}),
            )
            queue._items[item.key] = item
        return queue


STATUS_LABEL = {QUEUED: "排队中", RUNNING: "运行中", DONE: "完成", FAILED: "失败", CANCELLED: "已取消", SKIPPED: "已跳过"}


class RunCancelled(RuntimeError):
    """The run ended with items withdrawn; what finished is kept."""

    def __init__(self, cancelled: Sequence[str], skipped: Sequence[str], *, paused: bool = False):
        self.cancelled = list(cancelled)
        self.skipped = list(skipped)
        self.paused = paused
        head = "已按暂停请求停止派发" if paused else "已按请求取消排队中的项"
        super().__init__(f"{head}：取消 {len(self.cancelled)} 项，连带跳过 {len(self.skipped)} 项；已完成的保留，重跑本阶段只补剩余")


def _in_context(work: Work) -> Callable[[Item], Any]:
    """The worker inherits the caller's context, so usage and job records land on the right project."""
    context = contextvars.copy_context()
    return lambda item: context.run(work, item)


Work = Callable[[Item], Any]
Persist = Callable[[dict[str, Any]], None]
Withdrawn = Callable[[], set[str]]


def run(
    queue: Queue,
    work: Work,
    *,
    persist: Persist,
    withdrawn: Withdrawn | None = None,
    pause_requested: Callable[[], bool] | None = None,
    on_done: Callable[[Item, Any], None] | None = None,
    run_id: str | None = None,
    pool: ThreadPoolExecutor | None = None,
) -> dict[str, Any]:
    """Run every queued item within its bucket ceiling; results keyed by item.

    ``withdrawn`` is asked before each dispatch for the keys someone cancelled
    through the store; ``pause_requested`` stops new dispatches and withdraws
    the rest. ``persist`` receives the snapshot after every change. Raises
    ``RunCancelled`` at the end when anything was withdrawn, after the running
    items finished and their results were kept.
    """
    pool = pool or _POOL
    pending: dict[Future[Any], Item] = {}
    results: dict[str, Any] = {}
    paused = False

    def dispatch() -> None:
        nonlocal paused
        if withdrawn is not None:
            for key in sorted(withdrawn()):
                try:
                    queue.cancel(key, reason="cancelled_by_request")
                except CancelError:
                    continue
        if pause_requested is not None and pause_requested():
            paused = True
            queue.cancel_queued(reason="paused")
        running = queue.running_per_bucket()
        for item in queue.runnable():
            if running.get(item.bucket, 0) >= ceiling_for(item.bucket):
                continue
            queue.mark_started(item.key)
            running[item.bucket] = running.get(item.bucket, 0) + 1
            pending[pool.submit(_in_context(work), item)] = item

    # The waiting list is on record before anything starts, so a cancel can name it.
    persist(queue.snapshot(run_id=run_id))
    dispatch()
    persist(queue.snapshot(run_id=run_id))
    try:
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                item = pending.pop(future)
                try:
                    result = future.result()
                except BaseException as exc:  # noqa: BLE001 - one item's failure is recorded, the run goes on
                    queue.mark_failed(item.key, f"{type(exc).__name__}: {exc}")
                    logger.warning("[Queue] %s 失败：%s", item.label, str(exc)[:200])
                else:
                    results[item.key] = result
                    queue.mark_done(item.key)
                    if on_done is not None:
                        on_done(item, result)
            dispatch()
            persist(queue.snapshot(run_id=run_id))
    except BaseException:
        # Nothing waiting is submitted after a hard failure; running calls are drained, not abandoned.
        for item in queue.by_status(QUEUED):
            queue.cancel(item.key, reason="run_aborted")
        wait(pending)
        persist(queue.snapshot(run_id=run_id))
        raise
    cancelled = [item.key for item in queue.by_status(CANCELLED)]
    skipped = [item.key for item in queue.by_status(SKIPPED)]
    if cancelled:
        raise RunCancelled(cancelled, skipped, paused=paused)
    return results


# ---------------------------------------------------------------------------- task persistence


def snapshot_of(task: Mapping[str, Any]) -> dict[str, Any] | None:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    data = assets.get(QUEUE_KEY)
    return dict(data) if isinstance(data, Mapping) else None


def store_snapshot(task: dict[str, Any], snapshot: Mapping[str, Any]) -> None:
    """Write the runner's snapshot without losing cancel requests recorded in the meantime."""
    previous = snapshot_of(task) or {}
    data = dict(snapshot)
    final = {str(i.get("key")) for i in data.get("items") or [] if isinstance(i, Mapping) and i.get("status") in FINAL}
    withdraw = [str(k) for k in previous.get("withdraw") or [] if str(k) not in final]
    if withdraw:
        data["withdraw"] = withdraw
    task.setdefault("assets", {})[QUEUE_KEY] = data


def withdrawn_in(task: Mapping[str, Any]) -> set[str]:
    """Keys a person cancelled through the store while the run was going."""
    data = snapshot_of(task) or {}
    return {str(key) for key in data.get("withdraw") or []}


def request_cancel(task: dict[str, Any], key: str) -> dict[str, Any]:
    """Record a cancel request on the stored queue; the runner honours it before its next dispatch."""
    data = snapshot_of(task)
    if not data:
        raise CancelError("当前没有生成队列")
    item = next((i for i in data.get("items") or [] if isinstance(i, Mapping) and i.get("key") == key), None)
    if item is None:
        raise CancelError(f"队列里没有 {key}")
    if item.get("status") == RUNNING:
        raise CancelError(f"{item.get('label')} 已在供应商那里运行，不能取消；等它结束后可以重做")
    if item.get("status") in FINAL:
        raise CancelError(f"{item.get('label')} 已经{STATUS_LABEL.get(str(item.get('status')), '结束')}，无需取消")
    withdraw = [str(k) for k in data.get("withdraw") or []]
    if key not in withdraw:
        withdraw.append(key)
    data["withdraw"] = withdraw
    task.setdefault("assets", {})[QUEUE_KEY] = data
    return data


def request_cancel_queued(task: dict[str, Any]) -> dict[str, Any]:
    data = snapshot_of(task)
    if not data:
        raise CancelError("当前没有生成队列")
    queued = [str(i.get("key")) for i in data.get("items") or [] if isinstance(i, Mapping) and i.get("status") == QUEUED]
    if not queued:
        raise CancelError("队列里没有排队中的项")
    data["withdraw"] = sorted(set([str(k) for k in data.get("withdraw") or []] + queued))
    task.setdefault("assets", {})[QUEUE_KEY] = data
    return data


def reconcile_after_restart(task: dict[str, Any]) -> list[str]:
    """Items left ``running`` by a process that died were never finished: back to queued unless a provider job holds them."""
    data = snapshot_of(task)
    if not data:
        return []
    jobs = (task.get("assets") or {}).get("5_jobs") if isinstance(task.get("assets"), Mapping) else {}
    jobs = jobs if isinstance(jobs, Mapping) else {}
    requeued: list[str] = []
    for item in data.get("items") or []:
        if not isinstance(item, Mapping) or item.get("status") != RUNNING:
            continue
        job = jobs.get(str((item.get("meta") or {}).get("job_key") or ""))
        if isinstance(job, Mapping) and job.get("job_id") and job.get("status") == "submitted":
            continue  # the provider still has it; video_jobs resumes it
        item["status"] = QUEUED
        item["started_at"] = None
        item["reason"] = "requeued_after_restart"
        requeued.append(str(item.get("key")))
    data["updated_at"] = _now()
    task["assets"][QUEUE_KEY] = data
    return requeued


__all__ = [
    "CANCELLED", "DONE", "FAILED", "FINAL", "QUEUED", "QUEUE_KEY", "RUNNING", "SKIPPED", "STATUS_LABEL",
    "CancelError", "Item", "Queue", "RunCancelled",
    "bucket_of", "ceiling_for", "reconcile_after_restart", "request_cancel", "request_cancel_queued", "run",
    "snapshot_of", "store_snapshot", "withdrawn_in",
]

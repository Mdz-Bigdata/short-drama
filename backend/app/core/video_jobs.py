"""Provider video jobs a project has submitted, so a restart never pays for them twice.

A video request is submitted to the provider and then polled. If the server
restarts in between, the job keeps running on the provider's side and is paid
for; re-submitting it would pay again. So the job id is written onto the project
as soon as the provider accepts the request, together with a checkpoint of what
was asked for. After a restart, a job with an id is polled to its end and its
clip recorded; stage 5 then reuses that clip instead of asking again. A job
without an id, or whose provider cannot be asked about a job, is simply lost —
reported, never re-submitted on its own.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("app.core.video_jobs")

JOBS_KEY = "5_jobs"
SUBMITTED = "submitted"
DOWNLOADED = "downloaded"
FAILED = "failed"
# Families whose job can be asked about again after a restart.
RESUMABLE_FAMILIES = frozenset({"seedance", "minimax_h3", "kling", "grok", "happyhorse", "ltx_2_3"})

_task: ContextVar[str | None] = ContextVar("video_job_task", default=None)
_shot: ContextVar[dict[str, Any] | None] = ContextVar("video_job_shot", default=None)

Sink = Callable[[str, Mapping[str, Any]], None]
_sink: Sink | None = None
_lock = threading.Lock()


def configure_sink(sink: Sink | None) -> None:
    global _sink
    with _lock:
        _sink = sink


@contextmanager
def bind_shot(task_id: str, shot_id: int, *, candidate: int, checkpoint: Mapping[str, Any]) -> Iterator[None]:
    """Attribute the provider job submitted inside the block to this shot of this project."""
    task_token = _task.set(task_id)
    shot_token = _shot.set({"shot_id": int(shot_id), "candidate": int(candidate), "checkpoint": dict(checkpoint)})
    try:
        yield
    finally:
        _shot.reset(shot_token)
        _task.reset(task_token)


def _write(entry: dict[str, Any]) -> None:
    task_id = _task.get()
    with _lock:
        sink = _sink
    if not task_id or sink is None:
        return
    try:
        sink(task_id, entry)
    except Exception as exc:  # noqa: BLE001 - bookkeeping never fails the generation it describes
        logger.warning("[VideoJobs] 记录任务失败 task=%s: %s", task_id, type(exc).__name__)


def job_key(shot_id: int, candidate: int) -> str:
    return f"{int(shot_id)}:{int(candidate)}"


def note_submitted(family: str, job_id: str, *, model: str, endpoint: str | None = None) -> None:
    """The provider accepted the request: from now on the job exists and is being paid for."""
    shot = _shot.get()
    if not shot or not job_id:
        return
    _write({
        "key": job_key(shot["shot_id"], shot["candidate"]),
        "shot_id": shot["shot_id"],
        "candidate": shot["candidate"],
        "family": family,
        "job_id": str(job_id),
        "model": model,
        "endpoint": endpoint,
        "checkpoint": shot["checkpoint"],
        "status": SUBMITTED,
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "video_url": None,
        "error": None,
    })


def note_finished(job_id: str, video_url: str) -> None:
    shot = _shot.get()
    if not shot or not job_id:
        return
    _write({"key": job_key(shot["shot_id"], shot["candidate"]), "job_id": str(job_id), "status": DOWNLOADED, "video_url": video_url, "error": None})


def note_failed(job_id: str, reason: str) -> None:
    shot = _shot.get()
    if not shot or not job_id:
        return
    _write({"key": job_key(shot["shot_id"], shot["candidate"]), "job_id": str(job_id), "status": FAILED, "error": str(reason)[:300]})


def apply_to_task(task: dict[str, Any], entry: Mapping[str, Any]) -> None:
    """The default sink's mutation: a submitted job is created, later notes update it by key."""
    assets = task.setdefault("assets", {})
    jobs = assets.get(JOBS_KEY)
    if not isinstance(jobs, dict):
        jobs = {}
        assets[JOBS_KEY] = jobs
    key = str(entry.get("key"))
    current = jobs.get(key)
    if entry.get("status") == SUBMITTED or not isinstance(current, dict):
        jobs[key] = dict(entry)
        return
    if current.get("job_id") and entry.get("job_id") and current["job_id"] != entry["job_id"]:
        return
    current.update({name: value for name, value in entry.items() if name not in ("key",)})


def pending_jobs(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Jobs the provider accepted whose result this project never recorded."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    jobs = assets.get(JOBS_KEY) if isinstance(assets.get(JOBS_KEY), Mapping) else {}
    return [dict(job) for job in jobs.values() if isinstance(job, Mapping) and job.get("status") == SUBMITTED and job.get("job_id")]


def downloaded_clip(task: Mapping[str, Any], shot_id: int, *, candidate: int, fingerprint: str) -> str | None:
    """A clip a resumed job already produced for this exact request, if any."""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    jobs = assets.get(JOBS_KEY) if isinstance(assets.get(JOBS_KEY), Mapping) else {}
    job = jobs.get(job_key(shot_id, candidate))
    if not isinstance(job, Mapping) or job.get("status") != DOWNLOADED or not job.get("video_url"):
        return None
    checkpoint = job.get("checkpoint") if isinstance(job.get("checkpoint"), Mapping) else {}
    if fingerprint and str(checkpoint.get("contract_fingerprint") or "") != fingerprint:
        return None
    return str(job["video_url"])


def resume_outcome(job: Mapping[str, Any], resumer: Callable[[Mapping[str, Any]], str | None]) -> dict[str, Any]:
    """Ask the provider about one accepted job; the outcome is recorded, never re-submitted."""
    family = str(job.get("family") or "")
    base = {"key": job.get("key"), "job_id": job.get("job_id")}
    if family not in RESUMABLE_FAMILIES:
        return {**base, "status": FAILED, "error": f"resume_unsupported_provider:{family}"}
    try:
        url = resumer(job)
    except Exception as exc:  # noqa: BLE001 - the provider's answer is the outcome, whatever it is
        return {**base, "status": FAILED, "error": f"resume_failed:{type(exc).__name__}:{str(exc)[:160]}"}
    if url:
        return {**base, "status": DOWNLOADED, "video_url": url, "error": None}
    return {**base, "status": FAILED, "error": "resume_expired_or_failed"}


__all__ = [
    "DOWNLOADED", "FAILED", "JOBS_KEY", "RESUMABLE_FAMILIES", "SUBMITTED",
    "apply_to_task", "bind_shot", "configure_sink", "downloaded_clip", "job_key",
    "note_failed", "note_finished", "note_submitted", "pending_jobs", "resume_outcome",
]

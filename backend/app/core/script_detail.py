"""The detailed screenplay written in the background once stage 2 has its outline.

Stage 2 ends as soon as the structured engine has the overview, the asset inventory and
the episode ledger: the character stage needs no more than that. The episodes themselves
are written by a side thread, and the screenplay lands on the task in one piece when the
last episode is in. Until then the project shows the outline only.

``assets[KEY]`` is the side thread's record. Only ``mutate_task`` writes it (a stage's
whole-task snapshot never overwrites it, see ``task_repo``), and when the screenplay has
been applied the record carries ``applied_at``: a snapshot taken before that moment holds
the outline-only script and must not put it back.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from app import settings

KEY = "2_detail"

WRITING = "writing"
DONE = "done"
FAILED = "failed"

# The keys the finished screenplay replaces; a snapshot older than the apply keeps none of them.
SCRIPT_ASSET_KEYS = ("2", "2_screenwriting", "2_breakdown", "2_writer_dashboard")
SCRIPT_TASK_KEYS = ("scripted_episode_count",)


def enabled() -> bool:
    """SCRIPT_OUTLINE_FIRST=0 writes every episode inside stage 2, as before."""
    return settings.env_flag("SCRIPT_OUTLINE_FIRST", True)


def stall_seconds() -> int:
    """A record that has not moved for this long belongs to a thread that is gone (a restart)."""
    return settings.env_int("SCRIPT_DETAIL_STALL_SECONDS", 1200, minimum=60)


def record_of(task: Mapping[str, Any]) -> dict[str, Any] | None:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    record = assets.get(KEY)
    return record if isinstance(record, dict) else None


def start_record(run_id: str, total: int, script_revision: int) -> dict[str, Any]:
    now = time.time()
    return {
        "status": WRITING, "run_id": run_id, "total": int(total), "written": 0,
        "percent": 0, "label": "等待撰写", "error": None,
        "script_revision": int(script_revision), "started_at": now, "updated_at": now,
    }


def stalled(record: Mapping[str, Any] | None, now: float | None = None) -> bool:
    if not record or record.get("status") != WRITING:
        return False
    moved = float(record.get("updated_at") or 0)
    return (now if now is not None else time.time()) - moved > stall_seconds()


def writing(task: Mapping[str, Any]) -> bool:
    """The side thread is (still believed to be) writing this project's episodes."""
    record = record_of(task)
    return bool(record and record.get("status") == WRITING and not stalled(record))


def pending(task: Mapping[str, Any]) -> bool:
    """The screenplay is not all in: being written, failed part way, or left by a restart."""
    record = record_of(task)
    return bool(record and record.get("status") != DONE)


def blocking_reason(task: Mapping[str, Any]) -> str | None:
    """Why a stage that needs the whole screenplay cannot start yet; ``None`` when it can."""
    record = record_of(task)
    if not record or record.get("status") == DONE:
        return None
    total = int(record.get("total") or 0)
    written = int(record.get("written") or 0)
    if stalled(record):
        return f"详细剧本的后台撰写已中断（{written}/{total} 集），请在编剧页点「补写剧本」继续"
    if record.get("status") == FAILED:
        reason = str(record.get("error") or "未知原因")
        return f"详细剧本后台撰写失败（{written}/{total} 集）：{reason}；请在编剧页点「补写剧本」继续"
    return f"详细剧本仍在后台撰写（{written}/{total} 集），写完后才能进入分镜"


def applied_at(task: Mapping[str, Any]) -> float | None:
    record = record_of(task)
    value = record.get("applied_at") if record else None
    return float(value) if isinstance(value, (int, float)) else None


def keep_applied_script(incoming: dict[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """A snapshot taken before the screenplay was applied keeps the applied screenplay, not its outline."""
    stamp = applied_at(current)
    if stamp is None or applied_at(incoming) == stamp:
        return incoming
    merged = dict(incoming)
    current_assets = current.get("assets") if isinstance(current.get("assets"), Mapping) else {}
    assets = dict(merged.get("assets") or {}) if isinstance(merged.get("assets"), dict) else {}
    for key in SCRIPT_ASSET_KEYS:
        if key in current_assets:
            assets[key] = current_assets[key]
    merged["assets"] = assets
    for key in SCRIPT_TASK_KEYS:
        if key in current:
            merged[key] = current[key]
    return merged


def outline_text(state: Mapping[str, Any]) -> str:
    """The episode ledger as text: what later stages read while the episodes are being written."""
    overview = state.get("overview") if isinstance(state.get("overview"), Mapping) else {}
    lines: list[str] = []
    synopsis = str(overview.get("synopsis") or "").strip()
    if synopsis:
        lines += ["【故事梗概】", synopsis, ""]
    for entry in state.get("ledger") or []:
        if not isinstance(entry, Mapping):
            continue
        lines.append(f"第{int(entry.get('episode') or 0)}集 {str(entry.get('title') or '').strip()}".rstrip())
        hook = str(entry.get("hook") or "").strip()
        if hook:
            lines.append(f"钩子：{hook}")
        for beat in entry.get("story_beats") or []:
            if str(beat).strip():
                lines.append(f"- {str(beat).strip()}")
        teaser = str(entry.get("next_episode_teaser") or "").strip()
        if teaser:
            lines.append(f"下集预告：{teaser}")
        lines.append("")
    return "\n".join(lines).strip()


__all__ = [
    "DONE", "FAILED", "KEY", "SCRIPT_ASSET_KEYS", "WRITING", "applied_at", "blocking_reason", "enabled",
    "keep_applied_script", "outline_text", "pending", "record_of", "stall_seconds", "stalled", "start_record", "writing",
]

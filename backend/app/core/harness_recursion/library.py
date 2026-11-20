"""The experience library: what earlier tasks of the same kind adopted, and why.

After Harness²'s ``core/library.py``. One directory per stage and per kind of production (the
"domain"), one JSON file per task holding the whole adopted overlay with the reflection that
explains it. Retrieval is by construction: a directory only ever holds its own kind. Later proposers
read the entries as examples.

One thing upstream does not do: the newest entry whose edited output won a blind comparison is this
kind's *current overlay* (``current_overlay``). The
stage appends it to its prompt, and the next study of the kind edits it in place instead of starting
from nothing, so an ordinary run benefits from what was learned and the overlay is replaced, never
piled up. Its ``memory`` component stays behind: facts verified on one project are wrong anchors for
the next. The lesson itself is written for whoever edits an overlay, so it is not shown to the agent.

Kept in the knowledge skill's ``learned/`` folder beside the lessons distilled from quality reports.
Reads never raise: a missing or damaged library is an empty one.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import settings
from app.core.harness_recursion import harness as surface
from app.core.harness_recursion import prompts
from app.core.harness_recursion.selection import has_experience

logger = logging.getLogger("app.core.harness_recursion.library")

# Tests point this somewhere else; no caller passes a path (nothing outside the skill is written).
LIBRARY_ROOT = settings.skills_root() / "production-knowledge-master" / "learned" / "harness_library"
RUNS_FILE = "runs.jsonl"
# Letters of any script stay (a kind is named in the story's language); separators and dots do not.
_SAFE = re.compile(r"[^\w\-]+")
_WRITE_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(value: object) -> str:
    """One directory or file name, never a path."""
    return _SAFE.sub("_", str(value or "").strip()).strip("_")[:80] or "unknown"


def domain_dir(stage: int, domain: str) -> Path:
    return Path(LIBRARY_ROOT) / f"stage{int(stage)}" / slug(domain)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("[HarnessLibrary] 跳过读不出的条目 %s", path.name)
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), suffix=".tmp", delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        name = handle.name
    os.replace(name, path)


def entries(stage: int, domain: str) -> list[dict[str, Any]]:
    """This kind's entries, newest first."""
    folder = domain_dir(stage, domain)
    if not folder.is_dir():
        return []
    found = [entry for path in folder.glob("*.json") if (entry := _read(path)) is not None]
    return sorted(found, key=lambda entry: str(entry.get("created_at") or ""), reverse=True)


def add(
    *, stage: int, domain: str, task_id: str, adopted_label: str, harness: Mapping[str, str], why: str,
    experience: Mapping[str, str] | None, adopted_edit: bool, mode: str, k: int, project_terms: Sequence[str] = (),
) -> dict[str, Any] | None:
    """Store one adopted overlay with why it was adopted; nothing without a lesson that has its evidence.

    The overlay and the lesson are checked for words about being judged before anything is written.
    """
    if not has_experience(experience):
        return None
    kept = surface.normalise(harness)
    surface.validate(kept, project_terms)
    if surface.grader_word(f"{why} {' '.join(str(value) for value in experience.values())}"):
        return None
    entry = {
        "task_id": task_id, "stage": int(stage), "domain": domain, "adopted": adopted_label, "harness": kept,
        "why": str(why or "")[:1200], "mode": mode, "k": int(k), "created_at": _now(),
        # The project's own names at the time: a line that mentions one is not carried to another project.
        "project_terms": [str(term) for term in project_terms][:60],
        "experience": {key: str(experience[key])[:1200] for key in ("cue", "lesson", "evidence", "confidence", "edits") if experience.get(key)},
        # Becomes the kind's current overlay when an edited overlay's output won the blind comparison. The
        # reflection has already had its say: without a concrete execution contrast it writes no entry at
        # all. Its confidence is about which single edit did the work, which one step can rarely tell
        # apart, so it is kept on record and does not decide this (a stricter rule applied nothing in the
        # first real run, 2026-11-15, on a clear win).
        "applied": bool(adopted_edit),
    }
    with _WRITE_LOCK:
        folder = domain_dir(stage, domain)
        _write(folder / f"{slug(task_id)}.json", entry)
        for stale in sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)[prompts.limit("library_keep"):]:
            stale.unlink(missing_ok=True)
    return entry


def context_block(stage: int, domain: str) -> str:
    """The library as a proposer reads it: the newest few entries of this kind, each with its whole overlay."""
    shown = entries(stage, domain)[: prompts.limit("library_entries")]
    if not shown:
        return prompts.says("context", "library_empty")
    return prompts.says("context", "library", domain=domain, body="\n\n".join(
        prompts.says(
            "context", "library_entry", task=str(entry.get("task_id") or "")[:12],
            cue=(entry.get("experience") or {}).get("cue", ""), lesson=(entry.get("experience") or {}).get("lesson", ""),
            evidence=(entry.get("experience") or {}).get("evidence", ""),
            confidence=(entry.get("experience") or {}).get("confidence", prompts.label("none")),
            harness=surface.describe(entry.get("harness") or {}),
        )
        for entry in shown
    ))


def verified_lessons(stage: int, domain: str, *, limit: int = 4) -> list[dict[str, str]]:
    """Lessons of this kind that won their comparison, newest first, one per distinct wording."""
    seen: set[str] = set()
    lessons: list[dict[str, str]] = []
    for entry in entries(stage, domain):
        experience = entry.get("experience") or {}
        if not entry.get("applied") or entry.get("retired") or not has_experience(experience):
            continue
        key = re.sub(r"\W+", "", str(experience["lesson"]))
        if key in seen:
            continue
        seen.add(key)
        lessons.append({"cue": str(experience["cue"]), "lesson": str(experience["lesson"]), "task_id": str(entry.get("task_id") or "")})
        if len(lessons) >= limit:
            break
    return lessons


PROJECT_ONLY = surface.PROJECT_ONLY


def current_overlay(stage: int, domain: str) -> surface.Harness:
    """This kind's overlay as later projects run it: the newest one that won, without its project facts
    (the ``memory`` component, and any line elsewhere that names the cast of the project it came from)."""
    for entry in entries(stage, domain):
        if entry.get("applied") and not entry.get("retired"):
            return surface.carried(entry.get("harness") or {}, entry.get("project_terms") or ())
    return {}


def overlay_block(stage: int, domain: str) -> str:
    """The current overlay as the block a stage appends to its prompt; empty when the kind has none."""
    return surface.render(current_overlay(stage, domain))


def retire(stage: int, domain: str, task_id: str) -> bool:
    """Stop offering one task's lesson to the stage prompts; the entry stays for the record."""
    path = domain_dir(stage, domain) / f"{slug(task_id)}.json"
    with _WRITE_LOCK:
        entry = _read(path) if path.is_file() else None
        if entry is None:
            return False
        entry["retired"] = True
        _write(path, entry)
    return True


def retire_all(stage: int, domain: str) -> int:
    """Take every overlay of this kind out of the stage prompts (the kind runs bare again); how many were in use."""
    folder = domain_dir(stage, domain)
    taken = 0
    with _WRITE_LOCK:
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            entry = _read(path)
            if entry is not None and entry.get("applied") and not entry.get("retired"):
                entry["retired"] = True
                _write(path, entry)
                taken += 1
    return taken


# ---------------------------------------------------------------------------- the run log


def _runs_path() -> Path:
    return Path(LIBRARY_ROOT) / RUNS_FILE


def record_run(record: Mapping[str, Any]) -> None:
    """Append one finished step to the audit log; a log that cannot be written costs nothing else."""
    try:
        with _WRITE_LOCK:
            path = _runs_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": _now(), **record}, ensure_ascii=False) + "\n")
    except OSError as error:
        logger.warning("[HarnessLibrary] 进化记录没写下来: %s", type(error).__name__)


def runs(limit: int = 200) -> list[dict[str, Any]]:
    path = _runs_path()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return [row for row in found if isinstance(row, dict)]


def seen(fingerprint: str) -> bool:
    """Whether a step with these exact inputs already ran: the same stage call is not studied twice."""
    return any(row.get("fingerprint") == fingerprint for row in runs(limit=2000))


def report() -> dict[str, Any]:
    """Per stage and kind: how many entries, how many offered to the prompts, and the newest lessons."""
    root = Path(LIBRARY_ROOT)
    kinds: list[dict[str, Any]] = []
    if root.is_dir():
        for stage_dir in sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("stage")):
            for folder in sorted(path for path in stage_dir.iterdir() if path.is_dir()):
                found = [entry for path in folder.glob("*.json") if (entry := _read(path)) is not None]
                found.sort(key=lambda entry: str(entry.get("created_at") or ""), reverse=True)
                kinds.append({
                    "stage": int(stage_dir.name[5:] or 0), "domain": str(found[0].get("domain") or folder.name) if found else folder.name,
                    "entries": len(found), "applied": sum(1 for entry in found if entry.get("applied") and not entry.get("retired")),
                    "lessons": [
                        {"task_id": entry.get("task_id"), "applied": bool(entry.get("applied") and not entry.get("retired")),
                         **{key: (entry.get("experience") or {}).get(key) for key in ("cue", "lesson", "confidence")}}
                        for entry in found[:5]
                    ],
                })
    every = runs(limit=2000)
    return {"kinds": kinds, "runs": len(every), "summary": summarise(every), "recent": every[-10:]}


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How the learning is going, per stage: studies, how often an edited overlay won, was kept out, or was rolled back.

    After upstream's ``core/report.py``, with the blind comparison standing where its benchmark scores stand:
    the share of studies an edit won is this project's measure of whether refinement is paying off.
    """
    stages: dict[int, dict[str, Any]] = {}
    for row in rows:
        entry = stages.setdefault(int(row.get("stage") or 0), {"studies": 0, "edit_won": 0, "base_kept": 0, "rolled_back": 0, "applied": 0,
                                                                "stage_calls": 0, "improvement_calls": 0, "seconds": 0.0})
        entry["studies"] += 1
        adopted = str(row.get("adopted") or "")
        entry["rolled_back"] += bool(row.get("rolled_back"))
        entry["edit_won"] += bool(adopted and not adopted.startswith(("base", "bare")))
        entry["base_kept"] += adopted.startswith("base")
        entry["applied"] += bool(row.get("applied"))
        spent = row.get("spent") or {}
        entry["stage_calls"] += int(spent.get("stage_calls") or 0)
        entry["improvement_calls"] += int(spent.get("improvement_calls") or 0)
        entry["seconds"] = round(entry["seconds"] + float(spent.get("seconds") or 0), 1)
    for entry in stages.values():
        entry["edit_win_rate"] = round(entry["edit_won"] / entry["studies"], 3) if entry["studies"] else 0.0
    return {"studies": len(rows), "by_stage": {str(stage): stages[stage] for stage in sorted(stages)}}


__all__ = [
    "LIBRARY_ROOT", "PROJECT_ONLY", "add", "context_block", "current_overlay", "domain_dir", "entries", "overlay_block",
    "record_run", "report", "retire", "retire_all", "runs", "seen", "slug", "summarise", "verified_lessons",
]

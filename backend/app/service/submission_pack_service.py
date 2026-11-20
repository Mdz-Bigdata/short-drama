"""The platform submission pack of a project: read it any time, write its model items on request.

The layout and the model work are in ``app.core.submission_pack``; this file reads the task, binds the project's
text model and writes the one thing it ever writes: ``assets["2_submission"]``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app import settings
from app.core import llm_profile, submission_pack, usage_ledger
from app.core.screenwriting.structured_llm import StructuredOutputError

USAGE_PURPOSE = "submission_pack"


def _caller(service: Any, config: Mapping[str, Any], offline: list[bool]):
    """The project's text model, called the way the writer engine calls it; an offline template counts as no answer."""
    llm_model = str(config.get("llm_model") or "")
    title = str(config.get("title_suggestion") or "")
    dir_style = str(config.get("director_style") or "")
    shot_style = str(config.get("shot_style") or "")

    def caller(system: str, user: str, max_tokens: int) -> str:
        with llm_profile.reasoning_scope(llm_profile.reasoning_from_env("SCREENWRITING_REASONING")):
            answer = service.gateway.call_llm(llm_model, system, user, title, dir_style, shot_style, user_instruction="", max_tokens=max_tokens) or ""
        if service.gateway.last_answer_was_offline():
            offline.append(True)
            return ""
        return answer

    return caller


def _scenes(service: Any, task: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(service._breakdown_scenes(task))


def current(service: Any, task_id: str) -> dict[str, Any] | None:
    """The pack as the project stands; the model items are whatever was last written (no model call)."""
    task = service.repo.get_task(task_id)
    if not task:
        return None
    scenes = _scenes(service, task)
    if not scenes:
        return None
    return submission_pack.compile_pack(task, scenes)


def build(service: Any, task_id: str, *, refresh: bool = False) -> dict[str, Any] | None:
    """Write the model items unless the kept ones still match the script (or ``refresh``), then return the pack."""
    task = service.repo.get_task(task_id)
    if not task:
        return None
    scenes = _scenes(service, task)
    if not scenes:
        return None
    kept = submission_pack.stored(task)
    if kept and not refresh and kept.get("fingerprint") == submission_pack.fingerprint(task, scenes):
        return submission_pack.compile_pack(task, scenes)
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    offline: list[bool] = []
    max_tokens = settings.env_int("SCREENWRITING_MAX_TOKENS", 1_000_000, minimum=2000)
    with usage_ledger.bind_task(task_id, USAGE_PURPOSE):
        try:
            written = submission_pack.write(_caller(service, config, offline), task, scenes, max_tokens=max_tokens)
        except StructuredOutputError as error:
            raise RuntimeError(submission_pack.offline_text() if offline else str(error)) from error

    def keep(saved: dict[str, Any]) -> bool:
        saved.setdefault("assets", {})[submission_pack.ASSET_KEY] = written
        return True

    service.repo.mutate_task(task_id, keep)
    return current(service, task_id)


__all__ = ["USAGE_PURPOSE", "build", "current"]

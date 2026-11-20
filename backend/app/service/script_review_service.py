"""The review report of a project's script: read the kept one any time, write a new one on request.

The reading and the checks are in ``app.core.script_review``; this file reads the task, binds the project's
text model and writes the one thing it ever writes: ``assets["2_script_review"]``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app import settings
from app.core import llm_profile, script_review, usage_ledger
from app.core.screenwriting.structured_llm import StructuredOutputError

USAGE_PURPOSE = "script_review"


def _config(task: Mapping[str, Any]) -> Mapping[str, Any]:
    return task.get("config") if isinstance(task.get("config"), Mapping) else {}


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


def current(service: Any, task_id: str, focus: str = "") -> dict[str, Any] | None:
    """The kept report (the full review, or one focused check), whether the script changed since, and what a new one would take; no model call."""
    task = service.repo.get_task(task_id)
    if not task:
        return None
    scenes = list(service._breakdown_scenes(task))
    if not scenes:
        raise script_review.error("no_script")
    return script_review.view(task, scenes, model=str(_config(task).get("llm_model") or ""), focus=focus)


def build(service: Any, task_id: str, focus: str = "") -> dict[str, Any] | None:
    """Read the script with the project's text model (one call per block of episodes) and keep the report."""
    task = service.repo.get_task(task_id)
    if not task:
        return None
    scenes = list(service._breakdown_scenes(task))
    if not scenes:
        raise script_review.error("no_script")
    config = _config(task)
    offline: list[bool] = []
    max_tokens = settings.env_int("SCREENWRITING_MAX_TOKENS", 1_000_000, minimum=2000)
    with usage_ledger.bind_task(task_id, USAGE_PURPOSE):
        try:
            written = script_review.write(
                _caller(service, config, offline), task, scenes, max_tokens=max_tokens, model=str(config.get("llm_model") or ""), focus=focus,
            )
        except StructuredOutputError as error:
            raise RuntimeError(script_review.offline_text() if offline else str(error)) from error

    def keep(saved: dict[str, Any]) -> bool:
        saved.setdefault("assets", {})[script_review.asset_key(focus)] = written
        return True

    service.repo.mutate_task(task_id, keep)
    return current(service, task_id, focus)


__all__ = ["USAGE_PURPOSE", "build", "current"]

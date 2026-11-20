"""Rewrite a passage of one episode's plan and report what the change breaks; update an episode's sheet.

The model work and wording are in ``app.core.screenwriting.passage_rewrite``; this file reads the task,
binds the project's text model and writes the one thing it ever writes: an episode's ``state_changes``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app import settings
from app.core import llm_profile, usage_ledger
from app.core.screenwriting import passage_rewrite, story_state
from app.service import screenwriting_service as screenwriting

USAGE_PURPOSE = "passage_rewrite"
# One line of the sheet is a sentence; a whole row of them is a few hundred characters at most.
MAX_STATE_LINES = 20
MAX_STATE_LINE_CHARS = 300


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


def _cast(state: Mapping[str, Any]) -> list[str]:
    inventory = state.get("inventory") if isinstance(state.get("inventory"), Mapping) else {}
    characters = inventory.get("characters") if isinstance(inventory.get("characters"), Mapping) else {}
    return [str(name) for name in characters]


def propose(
    service: Any, task_id: str, episode: int, *, scene_ids: Sequence[str], instruction: str, keep: Sequence[str] = (),
) -> dict[str, Any] | None:
    """Two text calls (rewrite, then impact check); nothing is written. ``None`` when the task does not exist."""
    task = service.repo.get_task(task_id)
    if not task:
        return None
    response = screenwriting.episode_response(task, episode)
    if response is None:
        raise LookupError(str(episode))
    state = screenwriting.state_of(task) or {}
    ledger = state.get("ledger") or []
    chosen, before, after = passage_rewrite.select((response.plan or {}).get("scenes") or [], scene_ids, episode=episode)
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    offline: list[bool] = []
    caller = _caller(service, config, offline)
    max_tokens = settings.env_int("SCREENWRITING_MAX_TOKENS", 1_000_000, minimum=2000)
    with usage_ledger.bind_task(task_id, USAGE_PURPOSE):
        try:
            rows = passage_rewrite.rewrite(
                caller, episode=episode, chosen=chosen, before=before, after=after,
                sheet=story_state.table_before(ledger, episode), cast=_cast(state),
                instruction=instruction, keep=keep, max_tokens=max_tokens,
            )
        except RuntimeError as error:
            if offline:
                raise RuntimeError(passage_rewrite.offline_text()) from error
            raise
        own = passage_rewrite.own_changes(ledger, episode)
        checked = passage_rewrite.impact(
            caller, episode=episode,
            before=chosen, after=[{**scene, **row["after"]} for scene, row in zip(chosen, rows)],
            own=own, later=passage_rewrite.later_lines(ledger, episode), max_tokens=max_tokens,
        )
    lost = passage_rewrite.lost_key_lines(rows, chosen)
    return {
        "task_id": task_id, "episode": int(episode), "plan_revision": response.plan_revision,
        "instruction": instruction, "scenes": rows,
        "impact": {
            "checked": checked["checked"] and not offline,
            "findings": checked["findings"],
            "lost_key_lines": lost,
            "state_changes": {"before": own, "after": checked["state_changes"]},
        },
    }


def set_state_changes(service: Any, task_id: str, episode: int, lines: Sequence[str]) -> list[str] | None:
    """Write one episode's sheet; ``None`` when the task or the episode's ledger row does not exist.

    The sheet only guides what is planned and checked from now on, so nothing already made is invalidated.
    """
    cleaned = [str(line).strip()[:MAX_STATE_LINE_CHARS] for line in lines if str(line or "").strip()][:MAX_STATE_LINES]

    def mutate(task: dict[str, Any]) -> list[str] | None:
        state = screenwriting.state_of(task)
        if state is None:
            return None
        row = next((entry for entry in state.get("ledger") or [] if isinstance(entry, dict) and int(entry.get("episode") or 0) == int(episode)), None)
        if row is None:
            return None
        row["state_changes"] = cleaned
        return cleaned

    return service.repo.mutate_task(task_id, mutate)


__all__ = ["MAX_STATE_LINES", "USAGE_PURPOSE", "propose", "set_state_changes"]

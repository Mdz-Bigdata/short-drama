# -*- coding: utf-8 -*-
"""An answer a project already paid for, kept so the same question is not asked twice.

Only for questions with one right answer: what the relationships in this script are, what assets this source holds,
how this episode ended. Rerunning a stage after a failure, or after a small edit elsewhere, asks them again with the
same text. A creative call (write this scene, plan this stage) is never memoised, because a person who asks again wants
something new.

The memo lives on the project's own record: it goes when the project goes, and one project's text is never another's
answer. Only an answer its caller accepted is kept, so a bad reply cannot be replayed on every retry.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, MutableMapping
from typing import Any

from app.core import prompt_compact, usage_ledger

logger = logging.getLogger("app.core.llm_memo")

MEMO_KEY = "llm_memo"
MAX_ENTRIES = 40
MAX_ANSWER_CHARS = 60_000


def key_of(*parts: Any) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:32]


def _store(task: MutableMapping[str, Any]) -> dict[str, Any]:
    store = task.get(MEMO_KEY)
    if not isinstance(store, dict):
        store = task[MEMO_KEY] = {}
    return store


def get(task: MutableMapping[str, Any], key: str) -> str | None:
    answer = _store(task).get(key)
    return answer if isinstance(answer, str) and answer else None


def put(task: MutableMapping[str, Any], key: str, answer: str) -> None:
    if not answer or len(answer) > MAX_ANSWER_CHARS:
        return
    store = _store(task)
    store.pop(key, None)
    store[key] = answer
    # A dict keeps insertion order: the oldest answer goes first.
    while len(store) > MAX_ENTRIES:
        store.pop(next(iter(store)))


def note_reuse(model: str, *, prompt_chars: int, prompt_tokens: int, answer: str, label: str) -> None:
    """A question not asked: a record with no cost, so a project can see what the memo saved."""
    usage_ledger.record(
        "text", provider="memo", model=model, status="success", purpose=None,
        units={
            "reused": 1, "label": label[:40],
            "saved_input_chars": prompt_chars, "saved_output_chars": len(answer),
            "saved_tokens": prompt_tokens + prompt_compact.estimate_tokens(answer),
        },
    )


def reuse(
    task: MutableMapping[str, Any], *, label: str, model: str, system: str, user: str, ask: Callable[[], str | None],
    accept: Callable[[str], bool] = bool,
) -> str | None:
    """The earlier answer to exactly this question, or ``ask()``'s, kept only if ``accept`` says it was any good."""
    key = key_of(label, model, system, user)
    known = get(task, key)
    if known is not None and accept(known):
        note_reuse(
            model, prompt_chars=len(system) + len(user), answer=known, label=label,
            prompt_tokens=prompt_compact.estimate_tokens(system) + prompt_compact.estimate_tokens(user),
        )
        logger.info("[Memo] %s 复用了上次的结果，没有调用模型", label)
        return known
    answer = ask()
    if answer and accept(answer):
        put(task, key, answer)
    return answer


class ProjectMemo:
    """``call_structured``'s view of one project's memo."""

    def __init__(self, task: MutableMapping[str, Any], model: str) -> None:
        self.task, self.model = task, model

    def recall(self, label: str, system: str, user: str) -> str | None:
        known = get(self.task, key_of(label, self.model, system, user))
        if known is not None:
            note_reuse(
                self.model, prompt_chars=len(system) + len(user), answer=known, label=label,
                prompt_tokens=prompt_compact.estimate_tokens(system) + prompt_compact.estimate_tokens(user),
            )
        return known

    def keep(self, label: str, system: str, user: str, answer: str) -> None:
        put(self.task, key_of(label, self.model, system, user), answer)


__all__ = ["MEMO_KEY", "ProjectMemo", "get", "key_of", "note_reuse", "put", "reuse"]

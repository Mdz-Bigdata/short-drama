"""A creator's own way of working, laid over the platform's creative method for a stage agent.

Each stage agent's system prompt opens with the platform's creative method (who the agent is and how it
works), followed by reference material, this project's facts and the output format. An account may
keep, per stage agent, one of three choices for that opening method:

``follow``   the platform's text, unchanged (and it is byte-for-byte what was sent before this existed);
``append``   the platform's text, then the creator's lines under a heading;
``rewrite``  the creator's text in place of the platform's, where the stage offers it.

Everything after the method is the protected part: it is added by the stage code after this layer, a
closing line says it prevails, and no choice here can remove it. A stage whose method carries names or
shapes that later code reads (the writer's emotion-point names, the character card's fields, the
storyboard table) offers ``append`` only, and says why. A stage may also keep one sentence of its
method through a rewrite (``protected``).

Which stages, which choices, the headings, the closing line and the limits are in
``app/data/prompt/prompt_preferences.json``. ``PROMPT_PREFERENCES=off`` makes every stage follow.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.core import prompt_data

logger = logging.getLogger("app.core.prompt_preferences")

_DATA = "prompt_preferences"
ENABLED_ENV = "PROMPT_PREFERENCES"
FOLLOW, APPEND, REWRITE = "follow", "append", "rewrite"
MODES = (FOLLOW, APPEND, REWRITE)


class PreferenceError(ValueError):
    """The choice is not one this stage offers, or its text is missing or too long."""


@dataclass(frozen=True)
class Operation:
    id: str
    stage: int
    label: str
    description: str
    modes: tuple[str, ...]
    source: str
    protected: str
    why_no_rewrite: str

    def platform_text(self) -> str:
        """The platform's method a rewrite replaces; empty for a stage that does not offer one."""
        return prompt_data.text("agent_prompts", self.source).strip() if self.source else ""


@dataclass(frozen=True)
class Preference:
    mode: str = FOLLOW
    text: str = ""


def _error(key: str, **values: object) -> PreferenceError:
    return PreferenceError(str(prompt_data.value(_DATA, "errors")[key]).format(**values))


def text_limit() -> int:
    return int(prompt_data.value(_DATA, "limits")["text_chars"])


def operations() -> tuple[Operation, ...]:
    return tuple(
        Operation(
            id=str(item["id"]), stage=int(item["stage"]), label=str(item["label"]),
            description=str(item["description"]), modes=tuple(item["modes"]), source=str(item.get("source") or ""),
            protected=str(item.get("protected") or ""), why_no_rewrite=str(item.get("why_no_rewrite") or ""),
        )
        for item in prompt_data.value(_DATA, "operations")
    )


def operation(operation_id: str) -> Operation:
    found = next((item for item in operations() if item.id == operation_id), None)
    if found is None:
        raise _error("unknown_operation", operation=operation_id)
    return found


def mode_label(mode: str) -> str:
    return str(prompt_data.value(_DATA, "modes")[mode]["label"])


def normalise(operation_id: str, mode: str, text: str = "") -> Preference:
    """The choice as it is stored, or :class:`PreferenceError` saying what is wrong with it."""
    target = operation(operation_id)
    if mode not in MODES:
        raise _error("unknown_mode", mode=mode)
    if mode not in target.modes:
        raise _error("mode_not_offered", label=target.label, mode=mode_label(mode), why=target.why_no_rewrite)
    if mode == FOLLOW:
        return Preference()
    # A control character has no business in a prompt; line breaks and tabs are the creator's layout.
    clean = "".join(ch for ch in str(text or "") if ch in "\n\t" or ch.isprintable()).strip()
    if not clean:
        raise _error("text_required", mode=mode_label(mode))
    if len(clean) > text_limit():
        raise _error("text_too_long", limit=text_limit(), length=len(clean))
    return Preference(mode, clean)


def personal(preference: Preference | None) -> bool:
    """Whether the prompt carries a creator's own text. Such a call is not material for shared learning."""
    return preference is not None and preference.mode != FOLLOW and bool(preference.text)


def creative_layer(operation_id: str, platform_text: str, preference: Preference | None = None) -> str:
    """The opening method of a stage agent's system prompt under the creator's choice.

    ``platform_text`` comes back untouched when the creator follows the platform, when the stored choice
    is one the stage no longer offers, or when it holds no text.
    """
    if not personal(preference):
        return platform_text
    target = operation(operation_id)
    if preference.mode not in target.modes:
        return platform_text
    headings = prompt_data.value(_DATA, "headings")
    guard = prompt_data.text(_DATA, "guard")
    if preference.mode == APPEND:
        lead = platform_text.rstrip("\n") + "\n\n" if platform_text.strip() else ""
        return f"{lead}{headings[APPEND]}\n{preference.text}\n{guard}\n\n"
    kept = f"{target.protected}\n" if target.protected else ""
    return f"{headings[REWRITE]}\n{preference.text}\n{kept}{guard}\n\n"


def catalogue(saved: Mapping[str, Preference] | None = None) -> dict[str, Any]:
    """What the settings page shows: every stage, the choices it offers, and what this account chose."""
    chosen = saved or {}
    modes = prompt_data.value(_DATA, "modes")
    return {
        "text_limit": text_limit(),
        "modes": [{"id": mode, "label": str(modes[mode]["label"]), "hint": str(modes[mode]["hint"])} for mode in MODES],
        "operations": [
            {
                "id": item.id, "stage": item.stage, "label": item.label, "description": item.description,
                "modes": list(item.modes), "why_no_rewrite": item.why_no_rewrite,
                "platform_text": item.platform_text(), "protected": item.protected,
                "mode": current.mode if current.mode in item.modes else FOLLOW,
                "text": current.text if current.mode in item.modes else "",
            }
            for item in operations()
            for current in (chosen.get(item.id) or Preference(),)
        ],
    }


# ---------------------------------------------------------------------------------------------
# Reading an account's choices from a stage worker


def enabled() -> bool:
    return (os.getenv(ENABLED_ENV) or "on").strip().lower() not in {"0", "off", "false", "no"}


def from_rows(rows: Any) -> dict[str, Preference]:
    """Stored rows (``operation``, ``mode``, ``text``) as choices; a row that no longer fits is dropped."""
    found: dict[str, Preference] = {}
    for row in rows or ():
        try:
            found[str(row.operation)] = normalise(str(row.operation), str(row.mode), str(row.text or ""))
        except PreferenceError:
            continue
    return {key: value for key, value in found.items() if personal(value)}


async def _read(owner_id: str) -> dict[str, Preference]:
    from app import settings
    from app.platform.store import PlatformStore

    store = PlatformStore(settings.database_url())
    try:
        return from_rows(await store.list_prompt_preferences(owner_id))
    finally:
        await store.close()


def _run_blocking(factory: Callable[[], Awaitable[Any]]) -> Any:
    """Run a private-store coroutine from sync code, even under a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(contextvars.copy_context().run, lambda: asyncio.run(factory())).result()


async def _add_line(owner_id: str, operation_id: str, line: str) -> Preference:
    from app import settings
    from app.platform.store import PlatformStore

    store = PlatformStore(settings.database_url())
    try:
        current = from_rows(await store.list_prompt_preferences(owner_id)).get(operation_id, Preference())
        kept = [row for row in current.text.splitlines() if row.strip()] if current.mode != FOLLOW else []
        if line not in kept:
            kept.append(line)
        # A stage the creator rewrote keeps their text and gains the line; any other stage adds it to the platform's method.
        choice = normalise(operation_id, REWRITE if current.mode == REWRITE else APPEND, "\n".join(kept))
        await store.set_prompt_preference(owner_id, operation_id, choice.mode, choice.text)
        return choice
    finally:
        await store.close()


def add_line(owner_id: str, operation_id: str, line: str) -> Preference:
    """Keep one more standing line for a stage agent on this account, beside what is already kept; said once, never twice.

    This is how "from now on my dialogue defaults to …" said in a conversation reaches every later project.
    """
    owner = str(owner_id or "").strip()
    clean = " ".join(str(line or "").split())
    operation(operation_id)
    if not owner:
        raise _error("no_account")
    if not clean:
        raise _error("text_required", mode=mode_label(APPEND))
    return _run_blocking(lambda: _add_line(owner, operation_id, clean))


def for_task(task: Mapping[str, Any] | None) -> dict[str, Preference]:
    """The project owner's choices, by stage agent. Empty (every stage follows) when they cannot be read."""
    owner = str((task or {}).get("owner_user_id") or "").strip()
    if not owner or not enabled():
        return {}
    try:
        return _run_blocking(lambda: _read(owner))
    except Exception as error:  # noqa: BLE001 - a stage must run on the platform's method rather than not at all
        logger.warning("读不到创作者的提示词偏好，本次按平台默认: %s", type(error).__name__)
        return {}

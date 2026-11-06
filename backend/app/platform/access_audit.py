"""A record of every time a role, not ownership, let someone into another person's project.

Reads are recorded once per person and project in a window, because the interface polls; every write is recorded.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from functools import partial
from typing import Any

import anyio.from_thread

logger = logging.getLogger("app.platform.access_audit")

READ_WINDOW_SECONDS = 600.0
_MAX_REMEMBERED = 4096
_recent_reads: OrderedDict[tuple[str, str], float] = OrderedDict()
_lock = threading.Lock()


def _should_record(actor_id: str, resource_id: str, write: bool) -> bool:
    if write:
        return True
    key, now = (actor_id, resource_id), time.monotonic()
    with _lock:
        seen = _recent_reads.get(key)
        if seen is not None and now - seen < READ_WINDOW_SECONDS:
            return False
        _recent_reads[key] = now
        _recent_reads.move_to_end(key)
        while len(_recent_reads) > _MAX_REMEMBERED:
            _recent_reads.popitem(last=False)
    return True


def _is_login(actor: Mapping[str, Any]) -> bool:
    # Only a real login carries its roles; hand-built actors (tests, scripts) have nobody to attribute it to.
    return "roles" in actor and bool(actor.get("user_id"))


async def record_access(
    store: Any, actor: Mapping[str, Any], *, resource_id: str, owner_id: str, write: bool, via: str,
) -> None:
    if not _is_login(actor) or not _should_record(str(actor["user_id"]), resource_id, write):
        return
    await store.record_audit(
        actor_id=str(actor["user_id"]),
        action=f"project.cross_account_{'write' if write else 'read'}",
        resource_type="project",
        resource_id=resource_id,
        details={"owner_id": owner_id, "via": via, "roles": list(actor.get("roles") or ())},
    )


def record_access_from_thread(
    actor: Mapping[str, Any], *, resource_id: str, owner_id: str, write: bool, via: str,
) -> None:
    """The same, from synchronous code. Out of reach of the event loop it can only go to the log, and says so."""
    if not _is_login(actor):
        return
    from app.platform.dependencies import get_platform_store

    try:
        anyio.from_thread.run(partial(
            record_access, get_platform_store(), actor,
            resource_id=resource_id, owner_id=owner_id, write=write, via=via,
        ))
    except RuntimeError:
        logger.warning(
            "跨账号访问未写入审计表: actor=%s project=%s owner=%s write=%s via=%s",
            actor.get("user_id"), resource_id, owner_id, write, via,
        )

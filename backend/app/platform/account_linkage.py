"""What closing an account sets off outside the database: open codes at the channels, and work still running.

Money and tokens move in the same transaction as the status (``PlatformStore.set_user_status``). These parts talk to
other systems, so they come after it and can each fail without undoing it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Any

from app.core import generation_queue
from app.platform import payment_flow
from app.platform.billing_book import account_status_changed
from app.platform.payments import get_payment_channels
from app.platform.payments.base import ChannelError, PaymentChannel
from app.platform.store import PlatformStore

logger = logging.getLogger("app.platform.account_linkage")

_RUNNING_STATES = {"running", "queued"}


def _project_service() -> Any:
    from app.api.drama_api import service  # the API module owns the one service instance

    return service


def stop_projects_of(user_id: str, service: Any = None) -> int:
    """Stops what is running and withdraws what is queued. Items already at a provider finish, and nothing new starts."""
    drama = service or _project_service()
    stopped = 0
    for task in drama.repo.list_all_tasks():
        if not isinstance(task, dict) or task.get("owner_user_id") != user_id:
            continue
        task_id = str(task.get("task_id") or "")
        snapshot = generation_queue.snapshot_of(task)
        if snapshot and any(item.get("status") == "queued" for item in snapshot.get("items") or []):
            try:
                drama.cancel_generation_item(task_id, None)
            except generation_queue.CancelError as exc:
                logger.warning("撤回排队项失败 %s: %s", task_id, exc)
        if task.get("status") in _RUNNING_STATES or (task.get("workflow_control") or {}).get("active"):
            drama.pause_task(task_id, stop=True)
            stopped += 1
    return stopped


async def finish_closing(
    store: PlatformStore, user_id: str, *, channels: Mapping[str, PaymentChannel] | None = None,
    stop_projects: Callable[[str], int] = stop_projects_of,
) -> None:
    """Never raises: the account is closed either way, and what is left is logged and recorded for someone to see."""
    account_status_changed(user_id)
    active = get_payment_channels() if channels is None else channels
    problems: list[str] = []
    for attempt in await store.open_attempts_of_user(user_id):
        channel = active.get(attempt.provider)
        if channel is None:
            continue
        try:
            await payment_flow.close_at_channel(store, channel, attempt)
        except ChannelError as exc:
            # The sweep closes it once it expires. If it does get paid first, that still posts and is flagged.
            logger.warning("关闭付款码失败 %s: %s", attempt.id, exc)
    try:
        await asyncio.to_thread(stop_projects, user_id)
    except Exception as exc:  # noqa: BLE001 - the provider guard refuses further calls regardless
        logger.exception("停止用户项目失败 %s", user_id)
        problems.append(type(exc).__name__)
    if problems:
        await store.record_audit(
            actor_id=None, action="user.close_incomplete", resource_type="user", resource_id=user_id, details={"problems": problems},
        )

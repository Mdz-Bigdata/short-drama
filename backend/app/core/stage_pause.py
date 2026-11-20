# -*- coding: utf-8 -*-
"""Pausing a stage while it runs, not only between stages.

A pause or stop request used to wait for the running stage to finish; only stage 5's clip queue
stopped early. Now every progress step of a stage is also a pause point: when the run that owns
the stage has been asked to pause, the stage saves what it has (the progress step saves first) and
raises :class:`StagePaused`, and the run ends as paused rather than failed. Saying 「继续」 later
starts the same stage again and reuses what was finished, the way a stage interrupted by a server
restart is resumed.

Only the thread that runs the stage stops at these points. Worker threads inside a stage (pools of
image or prompt calls) carry on, because their results are collected by that thread. A stretch of
work that already handles a pause itself, such as the stage-5 queue (it lets clips in flight finish
and keeps them), runs inside :func:`suspended` so it is not cut short in the middle.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator, Mapping
from typing import Any

_LOCAL = threading.local()


class StagePaused(RuntimeError):
    """The run that owns this stage was asked to pause or stop; what was finished is saved."""


@contextlib.contextmanager
def bound(task_id: str, run_id: str | None) -> Iterator[None]:
    """Mark the current thread as running ``task_id``'s stage for run ``run_id``."""
    previous = getattr(_LOCAL, "owner", None)
    _LOCAL.owner = (str(task_id), str(run_id or ""))
    try:
        yield
    finally:
        _LOCAL.owner = previous


@contextlib.contextmanager
def suspended() -> Iterator[None]:
    """No pause points inside: the code in here stops on a pause by itself."""
    _LOCAL.suspended = getattr(_LOCAL, "suspended", 0) + 1
    try:
        yield
    finally:
        _LOCAL.suspended -= 1


def requested(stored: Mapping[str, Any] | None, run_id: str) -> bool:
    """The stored task asks this run to pause or stop."""
    control = (stored or {}).get("workflow_control") or {}
    return bool(control.get("pause_requested")) and (not run_id or str(control.get("run_id") or "") == run_id)


def check(task_id: str, read: Callable[[str], Mapping[str, Any] | None]) -> None:
    """Raise :class:`StagePaused` when this thread runs ``task_id``'s stage and its run was asked to pause."""
    owner = getattr(_LOCAL, "owner", None)
    if not owner or owner[0] != str(task_id) or getattr(_LOCAL, "suspended", 0):
        return
    if requested(read(str(task_id)), owner[1]):
        raise StagePaused("已按要求暂停，本阶段已完成的部分已保存")


__all__ = ["StagePaused", "bound", "check", "requested", "suspended"]

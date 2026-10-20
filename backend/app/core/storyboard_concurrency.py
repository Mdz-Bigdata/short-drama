"""Bounded provider I/O only; storyline order and task persistence stay on the caller."""

from __future__ import annotations

import contextvars
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Callable, Sequence, TypeVar

from app import settings

_T = TypeVar("_T")
_R = TypeVar("_R")
# Shared across all scenes/tasks in this process. Threads are created lazily by
# the executor; no per-scene pool can multiply the provider concurrency ceiling.
_IMAGE_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="storyboard-image")
# Structuring a screenplay is text-only and hits a different provider budget
# than image generation, so it gets its own ceiling rather than competing for
# the image pool's three slots.
_ANALYSIS_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="script-analysis")


def _bounded_width(variable: str, ceiling: int) -> int:
    return settings.env_int(variable, ceiling, minimum=1, maximum=ceiling)


def map_storyboard_images(work: Callable[[_T], _R], items: Sequence[_T]) -> list[_R]:
    """Keep at most three queued/in-flight calls per board, returning input order.

    STORYBOARD_IMAGE_CONCURRENCY=1 provides a serial rollback, still through the
    shared pool so simultaneous boards cannot evade the process-wide limit.
    """
    return _map_bounded(
        work, items, _IMAGE_POOL, _bounded_width("STORYBOARD_IMAGE_CONCURRENCY", 3)
    )


def character_sheet_concurrency() -> int:
    """How many five-view sheets may be in flight at once."""
    return _bounded_width("CHARACTER_SHEET_CONCURRENCY", 3)


def map_character_sheets(work: Callable[[_T], _R], items: Sequence[_T]) -> list[_R]:
    """Render independent character sheets together, returning input order.

    Shares the image pool with storyboards, so a project generating both cannot
    exceed the process-wide provider ceiling. CHARACTER_SHEET_CONCURRENCY=1
    restores the strictly serial behaviour.
    """
    return _map_bounded(work, items, _IMAGE_POOL, character_sheet_concurrency())


def map_script_analysis(work: Callable[[_T], _R], items: Sequence[_T]) -> list[_R]:
    """Structure independent episode batches in parallel, returning input order.

    Every batch is a self-contained call over its own episodes, so the only thing
    the sequence buys is wall-clock. SCRIPT_ANALYSIS_CONCURRENCY=1 restores the
    strictly serial behaviour.
    """
    return _map_bounded(
        work, items, _ANALYSIS_POOL, _bounded_width("SCRIPT_ANALYSIS_CONCURRENCY", 3)
    )


def _in_context(work: Callable[[_T], _R]) -> Callable[[_T], _R]:
    """A worker inherits the caller's context (usage ledger binding, job attribution); one copy per call."""
    context = contextvars.copy_context()
    return lambda item: context.run(work, item)


def _map_bounded(
    work: Callable[[_T], _R],
    items: Sequence[_T],
    pool: ThreadPoolExecutor,
    width: int,
) -> list[_R]:
    source = iter(enumerate(items))
    pending: dict[Future[_R], int] = {}
    results: dict[int, _R] = {}
    try:
        for _ in range(min(width, len(items))):
            index, item = next(source)
            pending[pool.submit(_in_context(work), item)] = index
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            # Consume every ready result before refilling. A later panel's fatal
            # error must stop new paid work even while an earlier panel is slow.
            completed.update(future for future in pending if future.done())
            for future in completed:
                results[pending[future]] = future.result()
                del pending[future]
            while len(pending) < width:
                try:
                    index, item = next(source)
                except StopIteration:
                    break
                pending[pool.submit(_in_context(work), item)] = index
    except BaseException:
        # Do not leave queued paid work behind after a deterministic failure.
        # Already-running calls cannot be cancelled; drain them before returning.
        for future in pending:
            future.cancel()
        wait(pending)
        raise
    return [results[index] for index in range(len(items))]

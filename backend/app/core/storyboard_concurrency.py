"""Bounded provider I/O only; storyline order and task persistence stay on the caller."""

from __future__ import annotations

import contextvars
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping, Sequence, TypeVar

from app import settings

# How long the other scenes wait for the first table call to fill the provider's cache.
WARM_UP_WAIT_SECONDS = settings.env_int("STORYBOARD_CACHE_WARMUP_SECONDS", 180, minimum=0, maximum=900)

_T = TypeVar("_T")
_R = TypeVar("_R")
# Shared across all scenes/tasks in this process. Threads are created lazily by
# the executor; no per-scene pool can multiply the provider concurrency ceiling.
# Boards are drawn side by side, so this, not a board's own width, is what the provider sees.
_IMAGE_POOL = ThreadPoolExecutor(
    max_workers=settings.env_int("STORYBOARD_IMAGE_CEILING", 6, minimum=1, maximum=12),
    thread_name_prefix="storyboard-image",
)
# Structuring a screenplay is text-only and hits a different provider budget
# than image generation, so it gets its own ceiling rather than competing for
# the image pool's three slots.
_ANALYSIS_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="script-analysis")


def _bounded_width(variable: str, ceiling: int) -> int:
    return settings.env_int(variable, ceiling, minimum=1, maximum=ceiling)


def map_storyboard_images(work: Callable[[_T], _R], items: Sequence[_T]) -> list[_R]:
    """Keep at most three queued/in-flight calls per board, returning input order.

    STORYBOARD_IMAGE_CONCURRENCY=1 provides a serial rollback, still through the
    shared pool so simultaneous boards cannot evade the process-wide limit
    (STORYBOARD_IMAGE_CEILING).
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


class SceneBoardsStopped(RuntimeError):
    """The stage stopped while this scene was waiting for its turn; nothing more is drawn."""


class SceneTurns:
    """Lets boards drawn side by side touch the task one at a time, in story order.

    The cross-scene memories (who stands on which side, what a location holds) and the cut
    into a scene depend on the scenes before it, so those sections run as they would in a
    serial stage; only the provider calls between them overlap. ``state`` also guards the
    caller's own task writes: a save must not serialise a store a section is changing.
    """

    def __init__(self, keys: Sequence[str]) -> None:
        self._order = list(keys)
        self._passed: dict[str, set[str]] = {}
        self._finished: set[str] = set()
        self._stopped = False
        self.state = threading.Condition(threading.RLock())
        self._drafts: dict[str, list[dict[str, Any]]] = {}
        self._warmed = False

    def _earlier_are_through(self, section: str, key: str) -> bool:
        passed = self._passed.get(section, set())
        position = self._order.index(key) if key in self._order else 0
        for earlier in self._order[:position]:
            if earlier not in passed and earlier not in self._finished:
                return False
        return True

    @contextmanager
    def turn(self, section: str, key: str) -> Iterator[None]:
        """Hold the task for ``key`` once every earlier scene is through ``section``."""
        with self.state:
            while not self._stopped and not self._earlier_are_through(section, key):
                self.state.wait()
            if self._stopped:
                raise SceneBoardsStopped(key)
            try:
                yield
            finally:
                self._passed.setdefault(section, set()).add(key)
                self.state.notify_all()

    @contextmanager
    def warm_up(self, key: str) -> Iterator[None]:
        """The first scene's table call goes alone; the others follow once it has answered.

        A provider's prompt cache holds a prefix only after a call has finished, and every table shares one long system
        prompt: six calls started together all pay for it in full (measured: about half cached at best when three
        started together, 94% once one had finished). Bounded, so a slow first call costs time and never blocks a stage.
        """
        first = bool(self._order) and key == self._order[0]
        if not first:
            give_up = time.monotonic() + WARM_UP_WAIT_SECONDS
            with self.state:
                while not (self._warmed or self._stopped or self._order[0] in self._finished):
                    left = give_up - time.monotonic()
                    if left <= 0:
                        break
                    self.state.wait(left)
                if self._stopped:
                    raise SceneBoardsStopped(key)
        try:
            yield
        finally:
            if first:
                with self.state:
                    self._warmed = True
                    self.state.notify_all()

    def finish(self, key: str) -> None:
        """``key`` will take no further turn, whether it was drawn or failed on the way."""
        with self.state:
            self._finished.add(key)
            self.state.notify_all()

    def stop(self) -> None:
        with self.state:
            self._stopped = True
            self.state.notify_all()

    def note_draft(self, key: str, shots: Sequence[Mapping[str, Any]]) -> None:
        """Keep a copy of ``key``'s final table: the next scene cuts from it before its images are in."""
        self._drafts[key] = [dict(shot) for shot in shots]

    def shots_with_drafts(self, flat_shots: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        """The stored shots with this run's final tables laid over those of the same scene."""
        kept = [shot for shot in flat_shots if str(shot.get("scene_id") or "") not in self._drafts]
        return kept + [shot for shots in self._drafts.values() for shot in shots]


def scene_concurrency() -> int:
    """How many scene boards of an episode may be in flight at once."""
    return _bounded_width("STORYBOARD_SCENE_CONCURRENCY", 6)


def draw_scene_boards(
    draw: Callable[[str, SceneTurns], _R],
    keys: Sequence[str],
    *,
    on_started: Callable[[list[str]], None],
    on_finished: Callable[[str, _R | None, Exception | None], None],
) -> None:
    """Draw boards side by side, reporting on the caller's thread while holding ``SceneTurns.state``.

    Scenes start in story order. One scene's failure is reported and the others go on; an
    error from a callback stops the stage: no further scene starts, and a scene still
    waiting for its turn gives up before its images are paid for.
    STORYBOARD_SCENE_CONCURRENCY=1 restores one board at a time.
    """
    turns = SceneTurns(keys)
    width = scene_concurrency()

    def one(key: str) -> _R:
        try:
            return draw(key, turns)
        finally:
            turns.finish(key)

    source = iter(keys)
    pending: dict[Future[_R], str] = {}
    with ThreadPoolExecutor(max_workers=max(1, width), thread_name_prefix="storyboard-scene") as pool:
        try:
            while True:
                starting = [key for _, key in zip(range(width - len(pending)), source)]
                if starting:
                    with turns.state:
                        on_started(starting)
                    for key in starting:
                        pending[pool.submit(_in_context(one), key)] = key
                if not pending:
                    return
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in sorted(completed, key=lambda item: keys.index(pending[item])):
                    key = pending.pop(future)
                    error = future.exception()
                    if error is not None and not isinstance(error, Exception):
                        raise error
                    with turns.state:
                        on_finished(key, None if error else future.result(), error)
        except BaseException:
            turns.stop()
            for future in pending:
                future.cancel()
            raise


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

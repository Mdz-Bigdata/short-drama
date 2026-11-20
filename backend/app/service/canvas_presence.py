"""Live presence between the windows one account has open on the same canvas, plus a "saved" signal.

The idea follows open-ai-canvas same-account multi-window presence (MIT): every window of a board
opens a Server-Sent Events stream and posts its cursor, drag rectangles and selection; the others
draw them. Whenever a new canvas version is written, every window of that board hears ``saved``
at once instead of finding out on its next poll. Whenever one of the board's node runs changes state
it hears ``run`` (ids and a status, nothing else) and reads the outputs again; the poll stays the fallback.

Rooms are keyed by (owner_user_id, project_id, canvas_id): only the owner's own windows ever meet,
so nothing here crosses accounts.

Lifecycle of a window (a "client", named by the client_id it picks):

* opening a stream joins the room (colour from a fixed palette of 8, by join order) and sends
  ``peers`` to everyone; a second stream with the same client_id replaces the first, which ends;
* when its stream closes the window drops out of ``peers`` straight away (``left`` + ``peers``),
  but keeps its slot and colour for ``IDLE_SECONDS`` so a reconnect after a network blip looks the
  same; after that it is garbage-collected. Posting needs an open stream;
* posting ``leave`` removes it at once.

Limitation: everything lives in this process's memory. With several workers (or several servers)
two windows can land on different processes and never see each other, and a ``saved`` written by
one worker only reaches streams held by that worker. Running more than one worker would need a
shared bus such as Redis pub/sub behind this same interface.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("app.service.canvas_presence")

CLIENT_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"
_CLIENT_ID = re.compile(CLIENT_ID_PATTERN)
LABEL_MAX_CHARS = 40
PALETTE = ("#e5484d", "#3e63dd", "#30a46c", "#f76b15", "#8e4ec6", "#12a594", "#d6409f", "#ad7f58")

QUEUE_SIZE = 256
MAX_CLIENTS_PER_ROOM = 20
MAX_ROOMS = 500
RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 1.0
IDLE_SECONDS = 45.0
PING_SECONDS = 15.0
# 推送连接最多保持这么久就主动结束，浏览器 1 秒后自己接上(SSE 的 retry)。连接不会永远挂着，
# 开发时自动重启、上线时正常停机就不会卡在「等待连接关闭」。
MAX_STREAM_SECONDS = 25.0
# 主动换连接后这段时间内接上，其他窗口看不到「离开又进来」；期间的 saved / peers 先攒着，接上后补发。
RECONNECT_GRACE_SECONDS = 5.0
BACKLOG_LIMIT = 32

# What a full queue gives up first: a newer cursor or drag supersedes an older one anyway.
_DROPPABLE = frozenset({"cursor", "drag"})
# Never dropped while anything else is left to drop; when only these remain, an older one of a
# kind is superseded by the newer one of the same kind.
_KEPT = frozenset({"saved", "peers"})
_RELAYED = frozenset({"cursor", "drag", "selection"})
# ``run`` is only ever said by the server (a window cannot post it): the states a node run goes through,
# plus ``finished`` for a whole batch that has stopped.
RUN_STATUSES = frozenset({"queued", "running", "done", "failed", "cancelled", "skipped", "finished"})
RUN_ID_MAX_CHARS = 120

RoomKey = tuple[str, str, str]


class PresenceRefused(Exception):
    """The room or the hub is full."""


class PresenceRateLimited(Exception):
    """A client posted more than RATE_LIMIT messages in RATE_WINDOW_SECONDS."""


class PresenceUnknownClient(LookupError):
    """No open stream for this client in this room."""


@dataclass(frozen=True)
class PresenceEvent:
    name: str
    data: Mapping[str, Any]

    def encode(self) -> str:
        return f"event: {self.name}\ndata: {json.dumps(self.data, ensure_ascii=False, separators=(',', ':'))}\n\n"


_CLOSE = PresenceEvent("__close__", {})


@dataclass
class _Client:
    client_id: str
    label: str
    color: str
    token: int
    loop: asyncio.AbstractEventLoop | None
    queue: asyncio.Queue | None
    last_seen: float
    open: bool = True
    closed_at: float | None = None
    posts: deque = field(default_factory=deque)
    recycling: bool = False
    backlog: list = field(default_factory=list)


@dataclass(frozen=True)
class PresenceSubscription:
    key: RoomKey
    client_id: str
    token: int
    queue: asyncio.Queue


def clean_label(label: str | None) -> str:
    text = "".join(ch for ch in str(label or "") if ch.isprintable())
    return text.strip()[:LABEL_MAX_CHARS]


def valid_client_id(value: str | None) -> bool:
    return bool(value) and bool(_CLIENT_ID.match(str(value)))


def _run_id(value: Any) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= RUN_ID_MAX_CHARS else None


def _enqueue(queue: asyncio.Queue, event: PresenceEvent) -> None:
    """Runs on the stream's own loop. A full queue loses its oldest cursor/drag first, never saved/peers."""
    if event is _CLOSE:
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(event)
        return
    if queue.full() and not _make_room(queue, event):
        return
    queue.put_nowait(event)


def _make_room(queue: asyncio.Queue, incoming: PresenceEvent) -> bool:
    items: list[PresenceEvent] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    victim = next((i for i, item in enumerate(items) if item.name in _DROPPABLE), None)
    if victim is None and incoming.name in _DROPPABLE:
        for item in items:
            queue.put_nowait(item)
        return False
    if victim is None:
        victim = next((i for i, item in enumerate(items) if item.name not in _KEPT and item is not _CLOSE), None)
    if victim is None:
        # Only saved/peers left: an older one is superseded by a newer one of the same kind (or the incoming one).
        names = [item.name for item in items] + [incoming.name]
        victim = next((i for i, item in enumerate(items) if item.name in names[i + 1:]), 0)
    del items[victim]
    for item in items:
        queue.put_nowait(item)
    return True


class PresenceHub:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        queue_size: int = QUEUE_SIZE,
        max_clients_per_room: int = MAX_CLIENTS_PER_ROOM,
        max_rooms: int = MAX_ROOMS,
        rate_limit: int = RATE_LIMIT,
        rate_window: float = RATE_WINDOW_SECONDS,
        idle_seconds: float = IDLE_SECONDS,
        ping_seconds: float = PING_SECONDS,
        max_stream_seconds: float = MAX_STREAM_SECONDS,
        reconnect_grace: float = RECONNECT_GRACE_SECONDS,
    ) -> None:
        self.clock = clock
        self.queue_size = queue_size
        self.max_clients_per_room = max_clients_per_room
        self.max_rooms = max_rooms
        self.rate_limit = rate_limit
        self.rate_window = rate_window
        self.idle_seconds = idle_seconds
        self.ping_seconds = ping_seconds
        self.max_stream_seconds = max_stream_seconds
        self.reconnect_grace = reconnect_grace
        self._rooms: dict[RoomKey, dict[str, _Client]] = {}
        self._lock = threading.Lock()
        self._tokens = itertools.count(1)

    # ------------------------------------------------------------------ streams

    def open_stream(self, owner_id: str, project_id: str, canvas_id: str, client_id: str, label: str = "") -> PresenceSubscription:
        """Join (or rejoin) a room from inside the stream's event loop."""
        if not valid_client_id(client_id):
            raise ValueError("client_id must be 8-64 characters of A-Z a-z 0-9 _ -")
        loop = asyncio.get_running_loop()
        key: RoomKey = (str(owner_id), str(project_id), str(canvas_id))
        self.sweep()
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        now = self.clock()
        with self._lock:
            room = self._rooms.get(key)
            if room is None:
                if len(self._rooms) >= self.max_rooms:
                    raise PresenceRefused("presence is busy, try again later")
                room = {}
            existing = room.get(client_id)
            if existing is None and len(room) >= self.max_clients_per_room:
                raise PresenceRefused("too many windows on this canvas")
            self._rooms[key] = room
            token = next(self._tokens)
            if existing is not None:
                if existing.open and existing.queue is not None:
                    self._schedule(existing.loop, existing.queue, _CLOSE)
                existing.label = clean_label(label)
                existing.token, existing.loop, existing.queue = token, loop, queue
                existing.open, existing.closed_at, existing.last_seen = True, None, now
                # 主动换连接后接回来：补发这几秒里错过的 saved / peers。
                for missed in existing.backlog:
                    _enqueue(queue, missed)
                existing.recycling, existing.backlog = False, []
            else:
                room[client_id] = _Client(
                    client_id=client_id, label=clean_label(label), color=self._free_color(room),
                    token=token, loop=loop, queue=queue, last_seen=now,
                )
            self._broadcast(room, self._peers_event(room))
        return PresenceSubscription(key=key, client_id=client_id, token=token, queue=queue)

    async def stream(self, sub: PresenceSubscription) -> AsyncIterator[str]:
        """The SSE body: events as they come, a ``: ping`` comment every ping_seconds."""
        loop = asyncio.get_running_loop()
        next_ping = loop.time() + self.ping_seconds
        ends_at = loop.time() + self.max_stream_seconds
        recycled = False
        try:
            # 告诉浏览器断开后 1 秒重连。
            yield "retry: 1000\n\n"
            while self._touch(sub):
                now = loop.time()
                if now >= ends_at:
                    recycled = True
                    return
                timeout = max(0.0, min(next_ping, ends_at) - now)
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    if loop.time() >= ends_at:
                        recycled = True
                        return
                    next_ping = loop.time() + self.ping_seconds
                    self.sweep()
                    yield ": ping\n\n"
                    continue
                if event is _CLOSE:
                    return
                yield event.encode()
        finally:
            self.close_stream(sub, quiet=recycled)

    def close_stream(self, sub: PresenceSubscription, *, quiet: bool = False) -> None:
        """The stream ended: out of ``peers`` now, slot and colour kept for idle_seconds.

        ``quiet``: the server ended it on purpose (MAX_STREAM_SECONDS) and the browser reconnects in a second;
        nobody hears about it unless the window fails to come back within reconnect_grace.
        """
        with self._lock:
            room = self._rooms.get(sub.key)
            client = room.get(sub.client_id) if room else None
            if client is None or client.token != sub.token or not client.open:
                return
            if not quiet:
                self._mark_closed(room, client)
                return
            client.open, client.queue, client.loop = False, None, None
            client.closed_at, client.recycling, client.backlog = self.clock(), True, []
        try:
            asyncio.get_running_loop().call_later(self.reconnect_grace + 0.05, self.sweep)
        except RuntimeError:
            pass

    def _touch(self, sub: PresenceSubscription) -> bool:
        with self._lock:
            room = self._rooms.get(sub.key)
            client = room.get(sub.client_id) if room else None
            if client is None or client.token != sub.token or not client.open:
                return False
            client.last_seen = self.clock()
            return True

    # ------------------------------------------------------------------ messages

    def publish(self, owner_id: str, project_id: str, canvas_id: str, client_id: str, message: Mapping[str, Any]) -> None:
        """Relay one validated message from a window to the room's other windows."""
        key: RoomKey = (str(owner_id), str(project_id), str(canvas_id))
        self.sweep()
        kind = str(message.get("type"))
        with self._lock:
            room = self._rooms.get(key)
            client = room.get(client_id) if room else None
            if client is None or not client.open:
                raise PresenceUnknownClient("no open presence stream for this client")
            now = self.clock()
            posts = client.posts
            while posts and posts[0] <= now - self.rate_window:
                posts.popleft()
            if len(posts) >= self.rate_limit:
                raise PresenceRateLimited("too many presence messages")
            posts.append(now)
            client.last_seen = now
            if kind == "leave":
                self._schedule(client.loop, client.queue, _CLOSE)
                del room[client_id]
                self._broadcast(room, PresenceEvent("left", {"client_id": client_id}))
                self._broadcast(room, self._peers_event(room))
                if not room:
                    del self._rooms[key]
                return
            if kind == "cursor":
                data: dict[str, Any] = {"client_id": client_id, "x": message["x"], "y": message["y"]}
            elif kind == "drag":
                data = {"client_id": client_id, "rects": [dict(rect) for rect in message.get("rects") or []]}
            elif kind == "selection":
                data = {"client_id": client_id, "ids": list(message.get("ids") or [])}
            else:
                raise ValueError(f"unknown presence message type: {kind}")
            self._broadcast(room, PresenceEvent(kind, data), skip=client_id)

    def saved(self, project_id: str, canvas_id: str, version: int, client_id: str | None = None, *, owner_id: str | None = None) -> None:
        """A new canvas version landed: tell every window of that board. Never raises into the write path."""
        try:
            source = client_id if valid_client_id(client_id) else None
            event = PresenceEvent("saved", {"version": int(version), "client_id": source})
            with self._lock:
                for key, room in self._rooms.items():
                    if key[1] == str(project_id) and key[2] == str(canvas_id) and (owner_id is None or key[0] == str(owner_id)):
                        self._broadcast(room, event)
        except Exception:  # noqa: BLE001 - presence is a nicety; a save must never fail because of it
            logger.exception("[Presence] saved broadcast failed")

    def run_changed(
        self, owner_id: str, project_id: str, canvas_id: str, *, batch_id: str, status: str, run_id: str | None = None, node_id: str | None = None,
    ) -> None:
        """A node run of that board changed state (or, with no run_id, its batch stopped): tell the owner's windows.

        Ids and a status only: what the run made is read from the outputs, as the poll reads it. Never raises
        into the run and never waits: the lock is held for a dictionary lookup and each delivery is handed to its loop.
        """
        try:
            if status not in RUN_STATUSES or _run_id(batch_id) is None:
                logger.warning("[Presence] run event not sent: unknown status or batch id")
                return
            event = PresenceEvent("run", {"batch_id": batch_id, "run_id": _run_id(run_id), "node_id": _run_id(node_id), "status": status})
            with self._lock:
                room = self._rooms.get((str(owner_id), str(project_id), str(canvas_id)))
                if room:
                    self._broadcast(room, event)
        except Exception:  # noqa: BLE001 - presence is a nicety; a run must never fail because of it
            logger.exception("[Presence] run broadcast failed")

    # ------------------------------------------------------------------ housekeeping

    def sweep(self) -> None:
        """Mark streams silent for idle_seconds as closed; forget clients closed for idle_seconds."""
        now = self.clock()
        with self._lock:
            for key in list(self._rooms):
                room = self._rooms[key]
                for client in list(room.values()):
                    if client.recycling and client.closed_at is not None and now - client.closed_at >= self.reconnect_grace:
                        # 主动换连接后没接回来：这才算离开。
                        client.recycling, client.backlog = False, []
                        self._broadcast(room, PresenceEvent("left", {"client_id": client.client_id}))
                        self._broadcast(room, self._peers_event(room))
                    if client.open and now - client.last_seen >= self.idle_seconds:
                        self._schedule(client.loop, client.queue, _CLOSE)
                        self._mark_closed(room, client, at=client.last_seen)
                    if not client.open and client.closed_at is not None and now - client.closed_at >= self.idle_seconds:
                        del room[client.client_id]
                if not room:
                    del self._rooms[key]

    def peers(self, owner_id: str, project_id: str, canvas_id: str) -> list[dict[str, str]]:
        with self._lock:
            room = self._rooms.get((str(owner_id), str(project_id), str(canvas_id))) or {}
            return list(self._peers_event(room).data["peers"])

    def room_count(self) -> int:
        with self._lock:
            return len(self._rooms)

    def client_count(self, owner_id: str, project_id: str, canvas_id: str) -> int:
        with self._lock:
            return len(self._rooms.get((str(owner_id), str(project_id), str(canvas_id))) or {})

    # ------------------------------------------------------------------ internals (lock held)

    def _mark_closed(self, room: dict[str, _Client], client: _Client, *, at: float | None = None) -> None:
        client.open, client.queue, client.loop = False, None, None
        client.closed_at = self.clock() if at is None else at
        self._broadcast(room, PresenceEvent("left", {"client_id": client.client_id}))
        self._broadcast(room, self._peers_event(room))

    @staticmethod
    def _peers_event(room: Mapping[str, _Client]) -> PresenceEvent:
        peers = [{"client_id": c.client_id, "label": c.label, "color": c.color} for c in room.values() if c.open]
        return PresenceEvent("peers", {"peers": peers})

    @staticmethod
    def _free_color(room: Mapping[str, _Client]) -> str:
        used = [client.color for client in room.values()]
        for color in PALETTE:
            if color not in used:
                return color
        return min(PALETTE, key=used.count)

    def _broadcast(self, room: Mapping[str, _Client], event: PresenceEvent, *, skip: str | None = None) -> None:
        for client in room.values():
            if client.client_id == skip:
                continue
            if client.open:
                self._schedule(client.loop, client.queue, event)
            elif client.recycling and event.name not in _DROPPABLE:
                if event.name == "run":
                    # One is enough to make the window read the outputs again; a batch must not crowd out saved / peers.
                    client.backlog = [missed for missed in client.backlog if missed.name != "run"]
                if len(client.backlog) < BACKLOG_LIMIT:
                    client.backlog.append(event)

    @staticmethod
    def _schedule(loop: asyncio.AbstractEventLoop | None, queue: asyncio.Queue | None, event: PresenceEvent) -> None:
        # Writers run in worker threads; the queue belongs to the stream's loop, so hand it over.
        if loop is None or queue is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(_enqueue, queue, event)
        except RuntimeError:
            pass


hub = PresenceHub()

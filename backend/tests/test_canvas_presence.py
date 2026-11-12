"""Live presence between one account's windows of a canvas: the hub's rooms and queues, the routes, and `saved`.

The hub is driven directly with asyncio; the routes with TestClient (which buffers whole responses, so the
stream itself is read once through a real uvicorn server on a loopback port). No provider is involved.
"""

import asyncio
import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import uvicorn
from fastapi.testclient import TestClient

from app.api import studio_api
from app.api.auth_api import get_current_user
from app.api.canvas_presence_api import MAX_BODY_BYTES, get_allowed_origins, get_presence_hub
from app.api.studio_api import get_studio_service
from app.core import agent_tools
from app.repository.studio_repo import StudioRepository
from app.schema.studio import ProjectCreate
from app.service import canvas_presence
from app.service.canvas_presence import PALETTE, PresenceHub, PresenceRateLimited, PresenceRefused, PresenceUnknownClient
from app.service.studio_service import StudioService
from main import app

A, B, C = "window-aaaa", "window-bbbb", "window-cccc"
ORIGIN = "http://localhost:5173"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _drain(sub):
    items = []
    while not sub.queue.empty():
        items.append(sub.queue.get_nowait())
    return items


def _names(events):
    return [event.name for event in events]


async def _settle():
    # Deliveries are handed to the loop with call_soon_threadsafe; one turn lets them land.
    for _ in range(3):
        await asyncio.sleep(0)


def _node(node_id):
    return {"id": node_id, "kind": "note", "track": "freezone", "x": 0, "y": 0, "width": 200, "height": 100, "artifact_id": None, "payload": {}}


class HubCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = Clock()
        self.hub = PresenceHub(clock=self.clock)

    def open(self, client_id, label="", project="p1", canvas="main", owner="u1"):
        return self.hub.open_stream(owner, project, canvas, client_id, label)

    async def test_join_and_leave_broadcast_peers_with_colours(self):
        a = self.open(A, "桌面")
        await _settle()
        first = _drain(a)
        self.assertEqual(_names(first), ["peers"])
        self.assertEqual(first[0].data["peers"], [{"client_id": A, "label": "桌面", "color": PALETTE[0]}])

        b = self.open(B, "笔记本")
        await _settle()
        expected = [{"client_id": A, "label": "桌面", "color": PALETTE[0]}, {"client_id": B, "label": "笔记本", "color": PALETTE[1]}]
        self.assertEqual([e.data["peers"] for e in _drain(a)], [expected])
        self.assertEqual([e.data["peers"] for e in _drain(b)], [expected])

        self.hub.publish("u1", "p1", "main", B, {"type": "leave"})
        await _settle()
        after = _drain(a)
        self.assertEqual(_names(after), ["left", "peers"])
        self.assertEqual(after[0].data, {"client_id": B})
        self.assertEqual(after[1].data["peers"], [expected[0]])
        self.assertEqual(self.hub.client_count("u1", "p1", "main"), 1)

    async def test_relay_excludes_the_sender(self):
        a, b, c = self.open(A), self.open(B), self.open(C)
        await _settle()
        for sub in (a, b, c):
            _drain(sub)
        self.hub.publish("u1", "p1", "main", A, {"type": "cursor", "x": 1.5, "y": -2})
        self.hub.publish("u1", "p1", "main", A, {"type": "drag", "rects": [{"id": "n1", "x": 0, "y": 0, "width": 10, "height": 5}]})
        self.hub.publish("u1", "p1", "main", A, {"type": "selection", "ids": ["n1", "n2"]})
        await _settle()
        self.assertEqual(_drain(a), [])
        for sub in (b, c):
            events = _drain(sub)
            self.assertEqual(_names(events), ["cursor", "drag", "selection"])
            self.assertEqual(events[0].data, {"client_id": A, "x": 1.5, "y": -2})
            self.assertEqual(events[1].data["rects"][0]["id"], "n1")
            self.assertEqual(events[2].data, {"client_id": A, "ids": ["n1", "n2"]})

    async def test_other_accounts_and_boards_are_other_rooms(self):
        a = self.open(A)
        other_owner = self.open(B, owner="u2")
        other_board = self.open(C, canvas="board-2")
        await _settle()
        for sub in (a, other_owner, other_board):
            _drain(sub)
        self.hub.publish("u1", "p1", "main", A, {"type": "cursor", "x": 1, "y": 1})
        with self.assertRaises(PresenceUnknownClient):
            self.hub.publish("u2", "p1", "main", A, {"type": "cursor", "x": 1, "y": 1})
        await _settle()
        self.assertEqual(_drain(other_owner), [])
        self.assertEqual(_drain(other_board), [])

    async def test_a_second_stream_with_the_same_client_id_replaces_the_first(self):
        old = self.open(A, "旧")
        other = self.open(B)
        await _settle()
        _drain(other)
        new = self.open(A, "新")
        self.assertNotEqual(old.token, new.token)
        await _settle()
        # The old stream is told to close and ends at once; the window keeps its colour.
        self.assertEqual(_names(_drain(old))[-1], "__close__")
        body = [chunk async for chunk in self.hub.stream(old)]
        self.assertEqual(body, ['retry: 1000\n\n'], 'only the reconnect hint, no events')
        peers = _drain(other)[-1].data["peers"]
        self.assertEqual(peers[0], {"client_id": A, "label": "新", "color": PALETTE[0]})
        self.assertEqual(self.hub.client_count("u1", "p1", "main"), 2)
        # The replaced stream finishing later does not close the new one.
        self.hub.close_stream(old)
        self.hub.publish("u1", "p1", "main", A, {"type": "cursor", "x": 0, "y": 0})

    async def test_a_full_queue_drops_cursors_never_saved(self):
        hub = PresenceHub(clock=self.clock, queue_size=4, rate_limit=1000)
        a = hub.open_stream("u1", "p1", "main", A, "")
        hub.open_stream("u1", "p1", "main", B, "")
        await _settle()
        _drain(a)
        hub.publish("u1", "p1", "main", B, {"type": "cursor", "x": 1, "y": 0})
        hub.saved("p1", "main", 7, None)
        hub.publish("u1", "p1", "main", B, {"type": "cursor", "x": 2, "y": 0})
        hub.publish("u1", "p1", "main", B, {"type": "cursor", "x": 3, "y": 0})
        hub.saved("p1", "main", 8, B)
        hub.publish("u1", "p1", "main", B, {"type": "cursor", "x": 4, "y": 0})
        await _settle()
        events = _drain(a)
        self.assertEqual(len(events), 4)
        self.assertEqual([e.data["version"] for e in events if e.name == "saved"], [7, 8])
        self.assertEqual([e.data["x"] for e in events if e.name == "cursor"], [3, 4])

        # A queue of nothing but saved events keeps the newest and still takes the incoming one.
        for version in range(9, 20):
            hub.saved("p1", "main", version, None)
        await _settle()
        last = _drain(a)
        self.assertEqual(len(last), 4)
        self.assertEqual(last[-1].data["version"], 19)

    async def test_rate_limit_is_a_sliding_window(self):
        self.open(A)
        for _ in range(30):
            self.hub.publish("u1", "p1", "main", A, {"type": "cursor", "x": 0, "y": 0})
        with self.assertRaises(PresenceRateLimited):
            self.hub.publish("u1", "p1", "main", A, {"type": "cursor", "x": 0, "y": 0})
        self.clock.now += 1.01
        self.hub.publish("u1", "p1", "main", A, {"type": "cursor", "x": 0, "y": 0})

    async def test_room_and_hub_caps(self):
        hub = PresenceHub(clock=self.clock, max_clients_per_room=2, max_rooms=2)
        hub.open_stream("u1", "p1", "main", A, "")
        hub.open_stream("u1", "p1", "main", B, "")
        with self.assertRaises(PresenceRefused):
            hub.open_stream("u1", "p1", "main", C, "")
        hub.open_stream("u1", "p1", "main", A, "")  # a replacement is not a new client
        hub.open_stream("u1", "p2", "main", A, "")
        with self.assertRaises(PresenceRefused):
            hub.open_stream("u1", "p3", "main", A, "")

    async def test_a_closed_stream_leaves_peers_and_is_collected_after_45s(self):
        a, b = self.open(A), self.open(B)
        await _settle()
        _drain(a)
        self.hub.close_stream(b)
        await _settle()
        self.assertEqual(_names(_drain(a)), ["left", "peers"])
        self.assertEqual([p["client_id"] for p in self.hub.peers("u1", "p1", "main")], [A])
        with self.assertRaises(PresenceUnknownClient):
            self.hub.publish("u1", "p1", "main", B, {"type": "cursor", "x": 0, "y": 0})
        # Its slot (and colour) waits for a reconnect...
        self.clock.now += 44
        self.hub.sweep()
        self.assertEqual(self.hub.client_count("u1", "p1", "main"), 2)
        again = self.open(B)
        self.assertEqual(self.hub.peers("u1", "p1", "main")[1]["color"], PALETTE[1])
        self.hub.close_stream(again)
        # ...and is gone 45s after the stream closed, while A's live stream (it wakes at least every ping) stays.
        self.clock.now += 45
        self.assertTrue(self.hub._touch(a))
        self.hub.sweep()
        self.assertEqual(self.hub.client_count("u1", "p1", "main"), 1)
        self.assertEqual([p["client_id"] for p in self.hub.peers("u1", "p1", "main")], [A])

    async def test_a_silent_stream_is_collected_and_an_empty_room_forgotten(self):
        self.open(A)
        self.assertEqual(self.hub.room_count(), 1)
        self.clock.now += 45
        self.hub.sweep()
        self.assertEqual(self.hub.room_count(), 0)

    async def test_the_stream_body_is_sse_with_pings(self):
        hub = PresenceHub(clock=self.clock, ping_seconds=0.05)
        sub = hub.open_stream("u1", "p1", "main", A, "窗")
        hub.saved("p1", "main", 3, A)
        body = hub.stream(sub)
        # 先告诉浏览器断开后 1 秒重连(连接会定期主动换新)。
        self.assertEqual(await asyncio.wait_for(body.__anext__(), 1), "retry: 1000\n\n")
        first = await asyncio.wait_for(body.__anext__(), 1)
        self.assertTrue(first.startswith("event: peers\ndata: "))
        self.assertTrue(first.endswith("\n\n"))
        saved = await asyncio.wait_for(body.__anext__(), 1)
        self.assertEqual(saved, 'event: saved\ndata: {"version":3,"client_id":"window-aaaa"}\n\n')
        self.assertEqual(await asyncio.wait_for(body.__anext__(), 1), ": ping\n\n")
        await body.aclose()
        self.assertEqual(hub.peers("u1", "p1", "main"), [])

    async def test_a_stream_ends_on_its_own_and_a_quick_reconnect_is_silent(self):
        """连接定期主动换新：其他窗口看不到离开又进来，断开那一秒里的 saved 接上后补发；没接回来才算离开。"""
        hub = PresenceHub(clock=self.clock, max_stream_seconds=0.05, reconnect_grace=5)
        a = hub.open_stream("u1", "p1", "main", A, "甲")
        b = hub.open_stream("u1", "p1", "main", B, "乙")
        await _settle()
        _drain(b)
        body = [chunk async for chunk in hub.stream(a)]  # ends by itself after max_stream_seconds
        self.assertEqual(body[0], "retry: 1000\n\n")
        await _settle()
        self.assertEqual(_drain(b), [], "nobody hears about a planned reconnect")
        hub.saved("p1", "main", 7, None)
        hub.publish("u1", "p1", "main", B, {"type": "cursor", "x": 1, "y": 1})
        await _settle()
        again = hub.open_stream("u1", "p1", "main", A, "甲")
        await _settle()
        names = _names(_drain(again))
        self.assertIn("saved", names, "the save made while reconnecting is delivered")
        self.assertNotIn("cursor", names, "stale cursors are not replayed")
        self.assertNotIn("left", _names(_drain(b)))
        # A window that does not come back within the grace is announced as gone.
        body = [chunk async for chunk in hub.stream(again)]
        self.clock.now += 6
        hub.sweep()
        await _settle()
        self.assertEqual(_names(_drain(b))[:2], ["left", "peers"])

    async def test_saved_reaches_the_board_from_another_thread(self):
        a = self.open(A)
        await _settle()
        _drain(a)
        thread = threading.Thread(target=self.hub.saved, args=("p1", "main", 5, "bad id!"))
        thread.start()
        thread.join()
        got = await asyncio.wait_for(a.queue.get(), 1)
        self.assertEqual((got.name, got.data), ("saved", {"version": 5, "client_id": None}))


class RouteCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = StudioRepository(Path(self.temp.name) / "studio.sqlite3")
        self.addCleanup(self.repo.close)
        self.studio = StudioService(self.repo)
        self.hub = PresenceHub(clock=Clock())  # frozen: the 30-a-second window never slides mid-test
        patcher = mock.patch.object(canvas_presence, "hub", self.hub)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = {"user_id": "u1", "role": "user"}
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_studio_service] = lambda: self.studio
        app.dependency_overrides[get_presence_hub] = lambda: self.hub
        app.dependency_overrides[get_allowed_origins] = lambda: [ORIGIN]
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.project = self.repo.create_project("u1", ProjectCreate(name="雨夜来信")).id
        self.base = f"/api/studio/projects/{self.project}"

    def presence(self, canvas_id="main"):
        return f"{self.base}/canvases/{canvas_id}/presence"

    def joined(self, client_id=A, canvas_id="main", owner="u1"):
        """A window with an open stream, opened on a loop that is gone afterwards (deliveries then go nowhere)."""
        async def open_one():
            return self.hub.open_stream(owner, self.project, canvas_id, client_id, "")
        return asyncio.run(open_one())

    def post(self, body, canvas_id="main", **kwargs):
        return self.client.post(self.presence(canvas_id), json=body, **kwargs)

    def test_a_message_from_an_open_stream_is_204(self):
        self.joined()
        response = self.post({"client_id": A, "type": "cursor", "x": 10, "y": 20})
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")

    def test_unknown_client_is_404(self):
        self.assertEqual(self.post({"client_id": A, "type": "cursor", "x": 1, "y": 2}).status_code, 404)
        self.joined(canvas_id="board-x")
        self.assertEqual(self.post({"client_id": A, "type": "cursor", "x": 1, "y": 2}).status_code, 404)
        # Another account's window in the same room name is not this account's.
        self.joined(client_id=B, owner="u2")
        self.assertEqual(self.post({"client_id": B, "type": "cursor", "x": 1, "y": 2}).status_code, 404)

    def test_body_over_32kb_is_413(self):
        self.joined()
        big = {"client_id": A, "type": "selection", "ids": ["x"], "pad": "y" * MAX_BODY_BYTES}
        self.assertEqual(self.post(big).status_code, 413)

    def test_bad_messages_are_422(self):
        self.joined()
        bad = [
            {"client_id": "short", "type": "cursor", "x": 1, "y": 1},
            {"client_id": A, "type": "wave"},
            {"client_id": A, "type": "cursor", "x": 1},
            {"client_id": A, "type": "drag", "rects": [{"id": "n", "x": 0, "y": 0, "width": 1, "height": 1}] * 101},
            {"client_id": A, "type": "selection", "ids": ["n"] * 201},
            {"client_id": A, "type": "selection", "ids": ["n" * 121]},
        ]
        for body in bad:
            self.assertEqual(self.post(body).status_code, 422, body)
        raw = self.client.post(self.presence(), content=f'{{"client_id":"{A}","type":"cursor","x":NaN,"y":1}}',
                               headers={"Content-Type": "application/json"})
        self.assertEqual(raw.status_code, 422)
        overflow = self.client.post(self.presence(), content=f'{{"client_id":"{A}","type":"cursor","x":1e999,"y":1}}',
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(overflow.status_code, 422)

    def test_more_than_30_a_second_is_429(self):
        self.joined()
        codes = [self.post({"client_id": A, "type": "cursor", "x": i, "y": 0}).status_code for i in range(31)]
        self.assertEqual(codes[:30], [204] * 30)
        self.assertEqual(codes[30], 429)

    def test_leave_removes_the_client(self):
        self.joined()
        self.assertEqual(self.post({"client_id": A, "type": "leave"}).status_code, 204)
        self.assertEqual(self.post({"client_id": A, "type": "cursor", "x": 0, "y": 0}).status_code, 404)

    def test_stream_refuses_strangers_unknown_boards_and_foreign_origins(self):
        stream = f"{self.presence()}/stream"
        self.user = {"user_id": "u2", "role": "user"}
        self.assertEqual(self.client.get(stream, params={"client_id": A}).status_code, 404)
        self.user = {"user_id": "u1", "role": "user"}
        self.assertEqual(self.client.get(f"{self.presence('no-such-board')}/stream", params={"client_id": A}).status_code, 404)
        self.assertEqual(self.client.get("/api/studio/projects/nope/canvases/main/presence/stream", params={"client_id": A}).status_code, 404)
        self.assertEqual(self.client.get(stream, params={"client_id": A}, headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get(stream, params={"client_id": "bad"}).status_code, 422)
        self.assertEqual(self.client.get(stream, params={"client_id": A, "label": "x" * 41}).status_code, 422)
        self.assertEqual(self.hub.room_count(), 0)

    def test_stream_requires_login(self):
        app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.client.get(f"{self.presence()}/stream", params={"client_id": A}).status_code, 401)
        self.assertEqual(self.post({"client_id": A, "type": "leave"}).status_code, 401)

    def test_saved_after_a_canvas_put_carries_the_header_client_id(self):
        async def scenario():
            sub = self.hub.open_stream("u1", self.project, "main", A, "")
            response = await asyncio.to_thread(
                self.client.put, f"{self.base}/canvas", json={"expected_version": 0, "nodes": [_node("n1")], "edges": []},
                headers={"X-Canvas-Client": B},
            )
            self.assertEqual(response.status_code, 200, response.text)
            return await self._next_saved(sub)

        self.assertEqual(asyncio.run(scenario()), {"version": 1, "client_id": B})

    def test_saved_after_the_assistant_edits_the_canvas_has_no_client_id(self):
        drama = SimpleNamespace(repo=SimpleNamespace(get_task=lambda task_id: {"owner_user_id": "u1", "config": {}}))
        project = self.repo.project_for_task("t-1", "u1", "画布").id

        async def scenario():
            sub = self.hub.open_stream("u1", project, "main", A, "")
            with mock.patch.object(studio_api, "get_studio_service", lambda: self.studio):
                done = await asyncio.to_thread(
                    agent_tools.edit_canvas, service=drama, user=self.user, task_id="t-1",
                    operations=[{"op": "add_node", "ref": "n", "kind": "note", "text": "助手加的"}],
                )
            self.assertEqual(done["version"], 1)
            return await self._next_saved(sub)

        self.assertEqual(asyncio.run(scenario()), {"version": 1, "client_id": None})

    def test_every_version_write_announces_saved(self):
        async def scenario():
            sub = self.hub.open_stream("u1", self.project, "main", A, "")
            put = self.studio.put_canvas
            await asyncio.to_thread(put, self.project, "u1", _put(0, [_node("n1")]))
            versions = [(await self._next_saved(sub))["version"]]
            await asyncio.to_thread(self.studio.duplicate_canvas_nodes, self.project, "u1", _duplicate(1, ["n1"]))
            versions.append((await self._next_saved(sub))["version"])
            await asyncio.to_thread(self.studio.restore_canvas_version, self.project, "u1", 1, expected_version=2)
            versions.append((await self._next_saved(sub))["version"])
            return versions

        self.assertEqual(asyncio.run(scenario()), [1, 2, 3])

    async def _next_saved(self, sub):
        while True:
            event = await asyncio.wait_for(sub.queue.get(), 2)
            if event.name == "saved":
                return dict(event.data)


def _put(expected, nodes):
    from app.schema.studio import CanvasPutRequest

    return CanvasPutRequest(expected_version=expected, nodes=nodes, edges=[])


def _duplicate(expected, node_ids):
    from app.schema.studio import CanvasDuplicateRequest

    return CanvasDuplicateRequest(expected_version=expected, node_ids=node_ids, operation_id="dup-op-1", offset_x=10, offset_y=10)


class LiveStreamCase(unittest.TestCase):
    """The stream end to end through the real app and middleware, on a loopback uvicorn."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = StudioRepository(Path(self.temp.name) / "studio.sqlite3")
        self.addCleanup(self.repo.close)
        self.studio = StudioService(self.repo)
        self.hub = PresenceHub()
        patcher = mock.patch.object(canvas_presence, "hub", self.hub)
        patcher.start()
        self.addCleanup(patcher.stop)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        app.dependency_overrides[get_studio_service] = lambda: self.studio
        app.dependency_overrides[get_presence_hub] = lambda: self.hub
        app.dependency_overrides[get_allowed_origins] = lambda: [ORIGIN]
        self.addCleanup(app.dependency_overrides.clear)
        self.project = self.repo.create_project("u1", ProjectCreate(name="雨夜来信")).id

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, lifespan="off", log_level="warning"))
        thread = threading.Thread(target=self.server.run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(setattr, self.server, "should_exit", True)
        deadline = time.time() + 5
        while not self.server.started and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(self.server.started)

    def test_stream_headers_events_relay_and_disconnect(self):
        path = f"/api/studio/projects/{self.project}/canvases/main/presence"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", f"{path}/stream?client_id={A}&label=desk", headers={"Origin": ORIGIN})
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertTrue(response.getheader("Content-Type").startswith("text/event-stream"))
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(response.getheader("X-Accel-Buffering"), "no")

        def next_event():
            name, data = None, None
            while True:
                line = response.fp.readline().decode("utf-8").rstrip("\n")
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                elif line == "" and name:
                    return name, data

        self.assertEqual(next_event(), ("peers", {"peers": [{"client_id": A, "label": "desk", "color": PALETTE[0]}]}))

        async def other_window():
            sub = self.hub.open_stream("u1", self.project, "main", B, "")
            return sub
        asyncio.run(other_window())
        self.assertEqual(next_event()[0], "peers")
        poster = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        poster.request("POST", path, body=json.dumps({"client_id": B, "type": "cursor", "x": 4, "y": 5}),
                       headers={"Content-Type": "application/json", "Origin": ORIGIN})
        self.assertEqual(poster.getresponse().status, 204)
        poster.close()
        self.assertEqual(next_event(), ("cursor", {"client_id": B, "x": 4.0, "y": 5.0}))

        conn.close()
        deadline = time.time() + 5
        while time.time() < deadline and any(p["client_id"] == A for p in self.hub.peers("u1", self.project, "main")):
            time.sleep(0.05)
        self.assertEqual([p["client_id"] for p in self.hub.peers("u1", self.project, "main")], [B])


if __name__ == "__main__":
    unittest.main()

"""A canvas run tells the board's open windows about every change of state, over the presence stream.

The runs go through the real runner and queue with stub providers (nothing paid); the listeners are
presence streams opened straight on a hub, the way tests/test_canvas_presence.py opens them.
"""

import asyncio
import threading
from unittest import mock

from app.service import canvas_presence
from app.service.canvas_presence import PresenceHub
from tests.test_canvas_workspace import CanvasCase, _edge, _node

A, B, C = "window-aaaa", "window-bbbb", "window-cccc"


async def _settle():
    # Deliveries are handed to the loop with call_soon_threadsafe; a few turns let them land.
    for _ in range(5):
        await asyncio.sleep(0)


def _runs(sub):
    events = []
    while not sub.queue.empty():
        event = sub.queue.get_nowait()
        if event.name == "run":
            events.append(dict(event.data))
    return events


class RunEventCase(CanvasCase):
    def setUp(self):
        super().setUp()
        self.hub = PresenceHub()
        patcher = mock.patch.object(canvas_presence, "hub", self.hub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self):
        """Every event the runner publishes, in order, without a hub; `finished` is set when a batch stops."""
        seen, finished = [], threading.Event()

        def publish(owner_id, project_id, canvas_id, **event):
            seen.append({"owner_id": owner_id, "project_id": project_id, "canvas_id": canvas_id, **event})
            if event["status"] == "finished":
                finished.set()

        self.studio.canvas_runs._publish_run = publish
        return seen, finished

    def latest(self):
        return self.client.get(f"{self.base}/canvas/outputs").json()["latest"]


class RunEventTests(RunEventCase):
    def test_queued_running_done_reach_this_boards_windows_in_order_and_no_other_room(self):
        saved = self.put([_node("img", "image_gen", prompt="雨夜的街")])

        async def scenario():
            here = self.hub.open_stream("u1", self.project, "main", A, "")
            other_board = self.hub.open_stream("u1", self.project, "second", B, "")
            other_account = self.hub.open_stream("u2", self.project, "main", C, "")
            answer = await asyncio.to_thread(self.run_nodes, ["img"], saved["version"])
            await _settle()
            return answer, _runs(here), _runs(other_board), _runs(other_account)

        answer, here, other_board, other_account = asyncio.run(scenario())
        self.assertEqual(answer["status"], "started")
        batch, run = answer["batch_id"], answer["runs"][0]["id"]
        self.assertEqual(here, [
            {"batch_id": batch, "run_id": run, "node_id": "img", "status": "queued"},
            {"batch_id": batch, "run_id": run, "node_id": "img", "status": "running"},
            {"batch_id": batch, "run_id": run, "node_id": "img", "status": "done"},
            {"batch_id": batch, "run_id": None, "node_id": None, "status": "finished"},
        ])
        self.assertEqual((other_board, other_account), ([], []))
        # The event says a state changed; what was made is still read from the outputs.
        self.assertEqual(self.latest()["img"]["status"], "done")

    def test_a_failure_and_what_it_skips_are_both_said(self):
        saved = self.put(
            [_node("img", "image_gen", prompt="好"), _node("vid", "video_gen", prompt="推门")], [_edge("img", "vid", role="first_frame")],
        )
        seen, _ = self.record()
        self.gateway.fail_with = "provider exploded"
        answer = self.run_nodes(["vid", "img"], saved["version"])
        self.assertEqual(answer["status"], "started", answer)
        self.assertEqual([(event["node_id"], event["status"]) for event in seen], [
            ("img", "queued"), ("vid", "queued"), ("img", "running"), ("img", "failed"), ("vid", "skipped"), (None, "finished"),
        ])
        self.assertEqual({(event["owner_id"], event["project_id"], event["canvas_id"]) for event in seen}, {("u1", self.project, "main")})
        # Ids and a status, nothing else: no prompt, no error text, no media.
        self.assertEqual({key for event in seen for key in event}, {"owner_id", "project_id", "canvas_id", "batch_id", "run_id", "node_id", "status"})

    def test_a_withdrawn_item_is_said_cancelled_once_the_worker_honours_it(self):
        saved = self.put([_node("a", "image_gen", prompt="一"), _node("b", "image_gen", prompt="二")], [_edge("a", "b")])
        seen, finished = self.record()
        release, started = threading.Event(), threading.Event()
        real = self.gateway.generate_image

        def slow(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(10))
            return real(*args, **kwargs)

        self.gateway.generate_image = slow
        self.studio.canvas_runs._spawn = lambda work: threading.Thread(target=work, daemon=True).start()
        answer = self.run_nodes(["a", "b"], saved["version"])
        self.assertTrue(started.wait(10))
        runs = {run["node_id"]: run["id"] for run in answer["runs"]}
        accepted = self.client.post(f"{self.base}/canvas/runs/{answer['batch_id']}/cancel", json={"key": runs["b"]})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        # Asking is not yet a change of state: nothing is said until the worker withdraws it.
        self.assertNotIn("cancelled", [event["status"] for event in seen])
        release.set()
        self.assertTrue(finished.wait(10))
        self.assertEqual([(event["node_id"], event["status"]) for event in seen], [
            ("a", "queued"), ("b", "queued"), ("a", "running"), ("a", "done"), ("b", "cancelled"), (None, "finished"),
        ])

    def test_a_publisher_that_raises_does_not_fail_the_run(self):
        saved = self.put([_node("img", "image_gen", prompt="好")])

        def broken(*args, **kwargs):
            raise RuntimeError("presence is down")

        self.studio.canvas_runs._publish_run = broken
        with self.assertLogs("app.service.studio_canvas_runs", level="WARNING") as logs:
            answer = self.run_nodes(["img"], saved["version"])
        self.assertEqual(answer["status"], "started")
        self.assertEqual(self.latest()["img"]["status"], "done")
        self.assertTrue(any("run event not published" in line for line in logs.output))

    def test_a_hub_that_breaks_while_delivering_does_not_fail_the_run(self):
        saved = self.put([_node("img", "image_gen", prompt="好")])

        async def scenario():
            self.hub.open_stream("u1", self.project, "main", A, "")
            with mock.patch.object(self.hub, "_broadcast", side_effect=RuntimeError("loop is gone")):
                with self.assertLogs("app.service.canvas_presence", level="ERROR"):
                    return await asyncio.to_thread(self.run_nodes, ["img"], saved["version"])

        self.assertEqual(asyncio.run(scenario())["status"], "started")
        self.assertEqual(self.latest()["img"]["status"], "done")

    def test_runs_go_through_with_no_presence_service_and_with_nobody_listening(self):
        saved = self.put([_node("img", "image_gen", prompt="好")])
        self.assertEqual(self.hub.room_count(), 0)
        self.assertEqual(self.run_nodes(["img"], saved["version"])["status"], "started")
        self.assertEqual(self.latest()["img"]["status"], "done")
        with mock.patch.object(canvas_presence, "hub", None):
            self.assertEqual(self.run_nodes(["img"], saved["version"], op="op-2")["status"], "started")
        self.assertEqual(len(self.gateway.image_calls), 2)
        self.assertEqual(self.hub.room_count(), 0)

    def test_a_repeated_order_is_not_announced_again(self):
        saved = self.put([_node("img", "image_gen", prompt="好")])
        seen, _ = self.record()
        self.run_nodes(["img"], saved["version"])
        said = len(seen)
        self.assertTrue(self.run_nodes(["img"], saved["version"])["reused"])
        self.assertEqual(len(seen), said)


if __name__ == "__main__":
    import unittest

    unittest.main()

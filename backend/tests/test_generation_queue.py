"""The generation queue: ceilings per provider and medium, dependencies, cancel-only-queued, restart reconciliation."""

import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.core import generation_queue as gq
from app.core import usage_ledger, video_jobs
from app.repository.task_repo import TaskRepository


def _item(key, family="seedance", medium="video", depends_on=(), **meta):
    return gq.Item(key=key, label=key, family=family, medium=medium, depends_on=list(depends_on), meta=dict(meta))


class QueueSemanticsTests(unittest.TestCase):
    def test_an_item_runs_only_after_its_dependencies_and_is_skipped_when_one_fails(self):
        queue = gq.Queue([_item("a"), _item("b", depends_on=["a"]), _item("c", depends_on=["b"]), _item("d")])
        self.assertEqual([i.key for i in queue.runnable()], ["a", "d"])
        queue.mark_started("a")
        queue.mark_done("a")
        self.assertEqual([i.key for i in queue.runnable()], ["b", "d"])
        touched = queue.mark_failed("b", "boom")
        self.assertEqual(touched, ["b", "c"])
        self.assertEqual((queue.get("c").status, queue.get("c").reason), (gq.SKIPPED, "依赖的 b 失败"))
        with self.assertRaisesRegex(ValueError, "依赖必须先入队"):
            queue.add(_item("e", depends_on=["nope"]))

    def test_only_a_queued_item_can_be_cancelled_and_its_dependents_go_with_it(self):
        queue = gq.Queue([_item("a"), _item("b", depends_on=["a"]), _item("c")])
        queue.mark_started("a")
        with self.assertRaisesRegex(gq.CancelError, "不能取消"):
            queue.cancel("a")
        self.assertEqual(queue.cancel("c"), ["c"])
        with self.assertRaisesRegex(gq.CancelError, "无需取消"):
            queue.cancel("c")
        queue.mark_done("a")
        self.assertEqual(queue.cancel_queued(), ["b"])
        self.assertEqual(queue.get("b").status, gq.CANCELLED)

    def test_ceilings_come_from_the_medium_then_the_family_knob(self):
        with patch.dict("os.environ", {"GENERATION_CONCURRENCY_VIDEO": "4", "GENERATION_CONCURRENCY_VIDEO_MINIMAX_H3": "1"}):
            self.assertEqual(gq.ceiling_for("seedance/video"), 4)
            self.assertEqual(gq.ceiling_for("minimax_h3/video"), 1)
        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(gq.ceiling_for("seedream/image"), 3)
            self.assertEqual(gq.ceiling_for("elevenlabs/audio"), 2)

    def test_a_snapshot_round_trips(self):
        queue = gq.Queue([_item("a", shot_id=1), _item("b", medium="audio", family="tts", depends_on=["a"])])
        queue.mark_started("a")
        snapshot = queue.snapshot(run_id="r1")
        self.assertEqual(snapshot["counts"][gq.RUNNING], 1)
        self.assertEqual(snapshot["buckets"]["seedance/video"]["running"], 1)
        again = gq.Queue.from_snapshot(snapshot)
        self.assertEqual([(i.key, i.status, i.depends_on) for i in again.items()], [("a", gq.RUNNING, []), ("b", gq.QUEUED, ["a"])])
        self.assertEqual(again.get("a").meta, {"shot_id": 1})


class RunTests(unittest.TestCase):
    def test_items_run_within_their_bucket_ceiling_and_results_are_kept(self):
        queue = gq.Queue([_item(f"v{i}") for i in range(4)] + [_item("img", family="seedream", medium="image")])
        lock = threading.Lock()
        in_flight = {"video": 0, "peak": 0}
        snapshots = []

        def work(item):
            if item.medium == "video":
                with lock:
                    in_flight["video"] += 1
                    in_flight["peak"] = max(in_flight["peak"], in_flight["video"])
                time.sleep(0.02)
                with lock:
                    in_flight["video"] -= 1
            return item.key.upper()

        with patch.dict("os.environ", {"GENERATION_CONCURRENCY_VIDEO": "2"}):
            results = gq.run(queue, work, persist=snapshots.append, pool=ThreadPoolExecutor(max_workers=6))

        self.assertEqual(results["v0"], "V0")
        self.assertEqual(in_flight["peak"], 2)
        self.assertTrue(all(i.status == gq.DONE for i in queue.items()))
        self.assertEqual(snapshots[-1]["counts"][gq.DONE], 5)
        self.assertGreaterEqual(len(snapshots), 2, "the queue is persisted as it changes")

    def test_a_failure_skips_dependents_but_the_rest_of_the_run_finishes(self):
        queue = gq.Queue([_item("a"), _item("b", depends_on=["a"]), _item("c")])

        def work(item):
            if item.key == "a":
                raise RuntimeError("provider said no")
            return item.key

        results = gq.run(queue, work, persist=lambda _s: None, pool=ThreadPoolExecutor(max_workers=2))
        self.assertEqual(results, {"c": "c"})
        self.assertEqual((queue.get("a").status, queue.get("b").status), (gq.FAILED, gq.SKIPPED))
        self.assertIn("provider said no", queue.get("a").error)

    def test_a_request_to_withdraw_is_honoured_before_the_next_dispatch_and_reported(self):
        queue = gq.Queue([_item("a"), _item("b"), _item("c", depends_on=["b"])])
        withdrawn = {"keys": set()}
        done = []

        def work(item):
            withdrawn["keys"].add("b")  # someone cancels b while a runs
            time.sleep(0.01)
            return item.key

        with patch.dict("os.environ", {"GENERATION_CONCURRENCY_VIDEO": "1"}):
            with self.assertRaises(gq.RunCancelled) as caught:
                gq.run(queue, work, persist=lambda _s: None, withdrawn=lambda: set(withdrawn["keys"]),
                       on_done=lambda item, _r: done.append(item.key), pool=ThreadPoolExecutor(max_workers=2))
        self.assertEqual(done, ["a"])
        self.assertEqual((caught.exception.cancelled, caught.exception.skipped), (["b"], ["c"]))
        self.assertIn("已完成的保留", str(caught.exception))

    def test_a_pause_request_stops_new_dispatches_and_lets_the_running_one_finish(self):
        queue = gq.Queue([_item("a"), _item("b")])
        paused = {"flag": False}

        def work(item):
            paused["flag"] = True
            return item.key

        with patch.dict("os.environ", {"GENERATION_CONCURRENCY_VIDEO": "1"}):
            with self.assertRaises(gq.RunCancelled) as caught:
                gq.run(queue, work, persist=lambda _s: None, pause_requested=lambda: paused["flag"], pool=ThreadPoolExecutor(max_workers=2))
        self.assertTrue(caught.exception.paused)
        self.assertEqual((queue.get("a").status, queue.get("b").status, queue.get("b").reason), (gq.DONE, gq.CANCELLED, "paused"))

    def test_workers_see_the_callers_context_so_sinks_attribute_their_calls(self):
        seen = []
        queue = gq.Queue([_item("a")])
        with usage_ledger.bind_task("task-ctx", "stage_5"):
            gq.run(queue, lambda item: seen.append(usage_ledger.current_task_id()), persist=lambda _s: None, pool=ThreadPoolExecutor(max_workers=1))
        self.assertEqual(seen, ["task-ctx"])
        self.assertIsNone(usage_ledger.current_task_id(), "the binding does not leak past the block")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))

    def test_sink_owned_records_survive_a_stale_progress_save(self):
        self.repo.save_task("x", {"task_id": "x", "status": "running", "config": {}, "assets": {}, "chat_history": []})
        stage_copy = self.repo.get_task("x")
        self.repo.mutate_task("x", lambda t: video_jobs.apply_to_task(t, {"key": "1:0", "shot_id": 1, "candidate": 0, "family": "seedance", "job_id": "ark-1", "status": "submitted", "checkpoint": {}}))
        self.repo.mutate_task("x", lambda t: usage_ledger.append_to_task(t, {"id": "u1", "provider": "seedance", "purpose": "stage_5"}))
        self.repo.mutate_task("x", lambda t: t.setdefault("assets", {}).__setitem__(gq.QUEUE_KEY, {"items": [{"key": "video:1", "status": gq.QUEUED}]}))
        stage_copy["stage_progress"] = {"percent": 50}
        stage_copy["assets"]["5"] = [{"shot_id": 1}]

        self.repo.save_task("x", stage_copy)

        stored = self.repo.get_task("x")
        self.assertEqual(stored["assets"]["5_jobs"]["1:0"]["job_id"], "ark-1")
        self.assertEqual([r["id"] for r in stored["usage_records"]], ["u1"])
        self.assertEqual(stored["assets"][gq.QUEUE_KEY]["items"][0]["key"], "video:1")
        self.assertEqual((stored["stage_progress"]["percent"], stored["assets"]["5"]), (50, [{"shot_id": 1}]))

    def test_cancel_requests_are_recorded_on_the_store_and_a_restart_requeues_dead_running_items(self):
        snapshot = {"items": [
            {"key": "video:1", "label": "镜头 1", "status": gq.RUNNING, "meta": {"job_key": "1:0"}},
            {"key": "video:2", "label": "镜头 2", "status": gq.RUNNING, "meta": {"job_key": "2:0"}},
            {"key": "video:3", "label": "镜头 3", "status": gq.QUEUED, "meta": {}},
            {"key": "video:4", "label": "镜头 4", "status": gq.DONE, "meta": {}},
        ]}
        task = {"task_id": "y", "assets": {gq.QUEUE_KEY: snapshot, "5_jobs": {"1:0": {"job_id": "ark-1", "status": "submitted"}}}}

        gq.request_cancel(task, "video:3")
        self.assertEqual(task["assets"][gq.QUEUE_KEY]["withdraw"], ["video:3"])
        self.assertEqual(gq.withdrawn_in(task), {"video:3"})
        with self.assertRaisesRegex(gq.CancelError, "不能取消"):
            gq.request_cancel(task, "video:1")
        with self.assertRaisesRegex(gq.CancelError, "无需取消"):
            gq.request_cancel(task, "video:4")

        self.assertEqual(gq.reconcile_after_restart(task), ["video:2"])
        statuses = {i["key"]: i["status"] for i in task["assets"][gq.QUEUE_KEY]["items"]}
        self.assertEqual(statuses, {"video:1": gq.RUNNING, "video:2": gq.QUEUED, "video:3": gq.QUEUED, "video:4": gq.DONE})


if __name__ == "__main__":
    unittest.main()

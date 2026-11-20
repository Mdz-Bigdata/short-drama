"""One run of a picture or clip node can ask for several results (params.count).

Each result is a run record of its own in the same order: it shows in the node's history, it is
estimated and billed as its own call, and the node reads as working until the last one stops.
Runs go through the real runner and queue with the stub gateway of tests/test_canvas_workspace.py.
"""

import types
import unittest

from app.core import canvas_versions
from tests.test_canvas_workspace import CanvasCase, _edge, _node


def _run(run_id, node_id, batch_id, status, error=None):
    return types.SimpleNamespace(id=run_id, node_id=node_id, batch_id=batch_id, status=status, error=error)


class VersionRuleTests(unittest.TestCase):
    def test_only_picture_and_clip_nodes_take_a_count_and_it_is_capped(self):
        node = lambda kind, count: {"kind": kind, "payload": {"params": {"count": count}}}  # noqa: E731
        self.assertEqual(canvas_versions.versions_of(node("image_gen", 3)), 3)
        self.assertEqual(canvas_versions.versions_of(node("video_gen", 2)), 2)
        self.assertEqual(canvas_versions.versions_of(node("image_gen", 99)), canvas_versions.MAX_VERSIONS)
        self.assertEqual(canvas_versions.versions_of(node("image_gen", 0)), 1)
        self.assertEqual(canvas_versions.versions_of(node("image_gen", "很多")), 1)
        self.assertEqual(canvas_versions.versions_of(node("audio_gen", 3)), 1)
        self.assertEqual(canvas_versions.versions_of(node("tool", 3)), 1)
        self.assertEqual(canvas_versions.versions_of({"kind": "image_gen"}), 1)

    def test_an_estimate_for_all_is_shared_out_and_an_unpriced_one_stays_unpriced(self):
        self.assertEqual(canvas_versions.share_of({"priced": True, "cost": 1.8, "currency": "CNY"}, 3)["cost"], 0.6)
        self.assertEqual(canvas_versions.share_of({"priced": True, "cost": 1.8, "currency": "CNY"}, 1)["cost"], 1.8)
        self.assertEqual(canvas_versions.share_of({"priced": False, "cost": None, "currency": None}, 3), {"priced": False, "cost": None, "currency": None})

    def test_a_single_result_keeps_the_nodes_name_and_several_are_numbered(self):
        self.assertEqual(canvas_versions.label_of("雨夜", 1, 1), "雨夜")
        self.assertIn("2/3", canvas_versions.label_of("雨夜", 2, 3))
        self.assertIn("雨夜", canvas_versions.label_of("雨夜", 2, 3))

    def test_a_node_is_working_until_its_last_result_stops(self):
        runs = [_run("r3", "n", "b2", "done"), _run("r2", "n", "b2", "running"), _run("r1", "n", "b2", "queued"), _run("r0", "n", "b1", "failed", "旧的失败")]
        entry = canvas_versions.latest_of(runs)["n"]
        self.assertEqual((entry["run_id"], entry["status"], entry["batch_id"]), ("r2", "running", "b2"))
        self.assertEqual(entry["versions"], {"total": 3, "done": 1, "failed": 0})

    def test_a_node_with_one_result_and_one_failure_is_done_and_says_how_many_failed(self):
        runs = [_run("r2", "n", "b", "failed", "模型拒绝"), _run("r1", "n", "b", "done")]
        entry = canvas_versions.latest_of(runs)["n"]
        self.assertEqual((entry["run_id"], entry["status"]), ("r1", "done"))
        self.assertEqual(entry["versions"], {"total": 2, "done": 1, "failed": 1})

    def test_a_node_whose_every_result_failed_shows_the_failure(self):
        runs = [_run("r2", "n", "b", "failed", "模型拒绝"), _run("r1", "n", "b", "failed", "模型拒绝")]
        entry = canvas_versions.latest_of(runs)["n"]
        self.assertEqual((entry["status"], entry["error"]), ("failed", "模型拒绝"))

    def test_an_ordinary_run_reads_as_before(self):
        entry = canvas_versions.latest_of([_run("r2", "n", "b2", "done"), _run("r1", "n", "b1", "failed", "x")])["n"]
        self.assertEqual(entry, {"run_id": "r2", "status": "done", "error": None, "batch_id": "b2"})


class SeveralResultsTests(CanvasCase):
    def test_three_pictures_from_one_run_all_land_in_the_history(self):
        saved = self.put([_node("img", "image_gen", prompt="雨夜的街", params={"count": 3})])
        answer = self.run_nodes(["img"], saved["version"])
        self.assertEqual(answer["status"], "started")
        self.assertEqual([run["node_id"] for run in answer["runs"]], ["img", "img", "img"])
        self.assertEqual(sorted(run["request"]["version"] for run in answer["runs"]), [1, 2, 3])
        self.assertEqual(len(self.gateway.image_calls), 3)
        outputs = self.client.get(f"{self.base}/canvas/outputs").json()
        self.assertEqual(outputs["history_counts"]["img"], 3)
        self.assertEqual(outputs["latest"]["img"]["status"], "done")
        self.assertEqual(outputs["latest"]["img"]["versions"], {"total": 3, "done": 3, "failed": 0})
        self.assertEqual(outputs["running"], 0)
        history = self.client.get(f"{self.base}/canvas/nodes/img/history").json()
        self.assertEqual(len({run["output"]["url"] for run in history["runs"]}), 3)
        self.assertTrue(outputs["outputs"]["img"]["url"].startswith("/media/image_"))

    def test_the_estimate_counts_every_result_and_each_record_carries_its_share(self):
        saved = self.put([_node("one", "image_gen", prompt="一张"), _node("three", "image_gen", prompt="三张", params={"count": 3})])
        assessed = self.client.post(f"{self.base}/canvas/runs/assess", json={"node_ids": ["one", "three"]}).json()
        rows = {row["node_id"]: row for row in assessed["nodes"]}
        self.assertEqual((rows["one"]["versions"], rows["three"]["versions"]), (1, 3))
        if rows["one"]["estimate"]["priced"]:
            self.assertAlmostEqual(rows["three"]["estimate"]["cost"], rows["one"]["estimate"]["cost"] * 3, places=6)
        answer = self.run_nodes(["three"], saved["version"])
        for run in answer["runs"]:
            self.assertEqual(run["request"]["versions"], 3)
            if rows["three"]["estimate"]["priced"]:
                self.assertAlmostEqual(run["request"]["estimate"]["cost"] * 3, rows["three"]["estimate"]["cost"], places=5)

    def test_a_count_above_the_ceiling_makes_the_ceiling(self):
        saved = self.put([_node("img", "image_gen", prompt="雨夜的街", params={"count": 50})])
        answer = self.run_nodes(["img"], saved["version"])
        self.assertEqual(len(answer["runs"]), canvas_versions.MAX_VERSIONS)
        self.assertEqual(len(self.gateway.image_calls), canvas_versions.MAX_VERSIONS)

    def test_a_node_downstream_runs_once_after_every_result_upstream(self):
        saved = self.put(
            [_node("img", "image_gen", prompt="雨夜的街", params={"count": 2}), _node("vid", "video_gen", prompt="她转身", params={"durationSeconds": 5})],
            [_edge("img", "vid", role="first_frame")],
        )
        answer = self.run_nodes(["img", "vid"], saved["version"])
        self.assertEqual(answer["status"], "started", answer)
        self.assertEqual(len(self.gateway.image_calls), 2)
        self.assertEqual(len(self.gateway.video_calls), 1)
        # The clip opens on the picture the node shows: the newest of the two.
        shown = self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["img"]["url"]
        self.assertEqual(self.gateway.video_calls[0]["first_frame"], shown)

    def test_two_clips_from_one_run(self):
        saved = self.put(
            [_node("ref", "media", output={"medium": "image", "url": "/media/ref.png"}), _node("vid", "video_gen", prompt="她转身", params={"durationSeconds": 5, "count": 2})],
            [_edge("ref", "vid", role="first_frame")],
        )
        answer = self.run_nodes(["vid"], saved["version"])
        self.assertEqual(answer["status"], "started", answer)
        self.assertEqual(len(self.gateway.video_calls), 2)
        self.assertEqual(self.client.get(f"{self.base}/canvas/outputs").json()["history_counts"]["vid"], 2)

    def test_one_failure_among_the_results_leaves_the_others(self):
        saved = self.put([_node("img", "image_gen", prompt="雨夜的街", params={"count": 2})])
        original = self.gateway.generate_image

        def flaky(model, prompt, **kwargs):
            if not self.gateway.image_calls:
                self.gateway.image_calls.append({"model": model, "prompt": prompt})
                raise RuntimeError("模型这一次没出图")
            return original(model, prompt, **kwargs)

        self.gateway.generate_image = flaky
        self.run_nodes(["img"], saved["version"])
        latest = self.client.get(f"{self.base}/canvas/outputs").json()["latest"]["img"]
        self.assertEqual(latest["status"], "done")
        self.assertEqual(latest["versions"], {"total": 2, "done": 1, "failed": 1})


if __name__ == "__main__":
    unittest.main()

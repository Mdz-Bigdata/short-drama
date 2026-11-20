# -*- coding: utf-8 -*-
"""The storyboard laid out on the canvas: one pair of nodes per shot, bound to it, a scene per group.

No provider is called: laying out costs nothing. What is pinned: a shot with a storyboard picture
gets a media node, one without gets an image node that the cast's look sheets feed; every video
node is bound to its shot and fed its first frame; a shot already on the canvas is not laid out
twice; a preview changes nothing; and the edit operations' new ``binding`` / ``output`` fields.
"""

from app.core import canvas_storyboard, prompt_data, studio_canvas
from tests.test_canvas_workspace import CanvasCase, _node, _task

SHOTS = [
    {"scene_id": "E1S01", "shot_id": 1, "shot_uid": 101, "desc": "林晚推开老宅的门", "characters": ["林晚"], "duration": "5秒",
     "storyboard_prompt": "雨夜老宅门口，林晚推门", "dialogue": "林晚：有人吗？"},
    {"scene_id": "E1S01", "shot_id": 2, "shot_uid": 102, "desc": "她回头", "characters": "林晚、周叔", "image_url": "/media/board_2.png", "duration": "8秒"},
    {"scene_id": "E1S02", "shot_id": 1, "shot_uid": 103, "desc": "雨街空镜", "characters": ["无"]},
]


class StoryboardCase(CanvasCase):
    def setUp(self):
        super().setUp()
        task = _task(shots=[dict(shot) for shot in SHOTS])
        task["assets"]["3_sheets"] = {"林晚": "https://img.test/lin.png", "周叔": "not-a-url"}
        self.drama.repo.save_task("t-1", task)

    def lay(self, **body):
        return self.client.post(f"{self.base}/canvas/storyboard", json=body)

    def canvas(self):
        return self.client.get(f"{self.base}/canvas").json()


class LayoutTests(StoryboardCase):
    def test_every_shot_becomes_a_first_frame_feeding_a_bound_video_node(self):
        done = self.lay()
        self.assertEqual(done.status_code, 200, done.text)
        body = done.json()
        self.assertEqual((body["applied"], body["shots"], body["skipped"], body["frames_to_draw"], body["cast"]), (True, 3, 0, 2, 1))
        self.assertEqual(body["scenes"], ["E1S01", "E1S02"])

        canvas = self.canvas()
        by_label = {node["payload"].get("label"): node for node in canvas["nodes"]}
        self.assertEqual(sorted(node["kind"] for node in canvas["nodes"]),
                         sorted(["media", "image_gen", "video_gen", "media", "video_gen", "image_gen", "video_gen", "group", "group", "video_compose"]))
        # The scenes joined: one compose node fed by every video node, in shot order.
        film = by_label["成片（3 个镜头）"]
        fed = [edge["source"] for edge in canvas["edges"] if edge["target"] == film["id"]]
        self.assertEqual(fed, [by_label[f"{label} 视频"]["id"] for label in ("E1S01 镜1", "E1S01 镜2", "E1S02 镜1")])
        self.assertTrue(all(edge["payload"].get("role") == "clip" for edge in canvas["edges"] if edge["target"] == film["id"]))
        self.assertGreater(film["y"], by_label["E1S02 镜1 视频"]["y"])
        # A shot with no picture yet: an image node with its prompt, fed by the look sheet of who is in it.
        frame = by_label["E1S01 镜1 首帧"]
        self.assertEqual((frame["kind"], frame["payload"]["prompt"]), ("image_gen", "雨夜老宅门口，林晚推门"))
        sheet = by_label["林晚·定妆"]
        self.assertEqual(sheet["payload"]["output"], {"medium": "image", "url": "https://img.test/lin.png", "name": "林晚"})
        edges = {(edge["source"], edge["target"]): edge["payload"].get("role") for edge in canvas["edges"]}
        self.assertEqual(edges[(sheet["id"], frame["id"])], "ref_image")
        # A shot that has its storyboard picture: that picture, as a media node.
        board = by_label["E1S01 镜2 分镜图"]
        self.assertEqual((board["kind"], board["payload"]["output"]["url"]), ("media", "/media/board_2.png"))
        # Each video node: the shot's text and lines, its length, bound to the shot, opening on the first frame.
        clip = by_label["E1S01 镜1 视频"]
        self.assertEqual(clip["payload"]["binding"], {"sceneId": "E1S01", "shotId": 1})
        self.assertEqual(clip["payload"]["params"], {"durationSeconds": 5})
        self.assertEqual(clip["payload"]["prompt"], "林晚推开老宅的门\n台词：林晚：有人吗？")
        self.assertEqual(edges[(frame["id"], clip["id"])], "first_frame")
        self.assertEqual(edges[(board["id"], by_label["E1S01 镜2 视频"]["id"])], "first_frame")
        self.assertNotIn("params", by_label["E1S02 镜1 视频"]["payload"], "no length written when the shot states none")
        # One group per scene, holding that scene's pairs; shots run left to right.
        scene = by_label["E1S01"]
        members = [node for node in canvas["nodes"] if node["payload"].get("groupId") == scene["id"]]
        self.assertEqual(len(members), 4)
        self.assertLess(frame["x"], board["x"])
        self.assertLess(frame["y"], clip["y"])
        self.assertLess(by_label["E1S01 镜1 首帧"]["y"], by_label["E1S02 镜1 首帧"]["y"])

    def test_a_shot_already_on_the_canvas_is_not_laid_out_twice(self):
        self.assertEqual(self.lay(scene_ids=["E1S01"]).json()["shots"], 2)
        again = self.lay().json()
        self.assertEqual((again["shots"], again["skipped"], again["scenes"]), (1, 2, ["E1S02"]))
        self.assertEqual(sum(1 for node in self.canvas()["nodes"] if node["kind"] == "video_compose"), 1, "one shot alone needs no film node")
        self.assertEqual(sum(1 for node in self.canvas()["nodes"] if node["kind"] == "video_gen"), 3)
        nothing = self.lay()
        self.assertEqual(nothing.status_code, 422, nothing.text)
        self.assertIn(prompt_data.text("canvas_storyboard", "nothing_new"), nothing.text)

    def test_new_nodes_go_to_the_right_of_what_the_canvas_holds_and_reuse_a_sheet_already_there(self):
        self.put([{**_node("held", "media", output={"medium": "image", "url": "https://img.test/lin.png"}), "x": 100, "y": 50, "width": 300}])
        body = self.lay(scene_ids=["E1S01"]).json()
        self.assertEqual(body["cast"], 0, "the look sheet already on the canvas is used, not added again")
        canvas = self.canvas()
        added = [node for node in canvas["nodes"] if node["id"] != "held" and node["kind"] != "group"]
        self.assertTrue(all(node["x"] >= 400 for node in added))
        frame = next(node for node in canvas["nodes"] if node["kind"] == "image_gen")
        self.assertIn(("held", frame["id"]), {(edge["source"], edge["target"]) for edge in canvas["edges"]})

    def test_a_preview_counts_and_changes_nothing(self):
        body = self.lay(preview=True).json()
        self.assertEqual((body["applied"], body["shots"], body["frames_to_draw"]), (False, 3, 2))
        self.assertNotIn("version", body)
        self.assertEqual(self.canvas()["nodes"], [])

    def test_the_picker_lists_scenes_with_what_is_still_to_lay_out(self):
        self.lay(scene_ids=["E1S02"])
        listed = self.client.get(f"{self.base}/canvas/storyboard").json()
        self.assertEqual(listed["scenes"], [{"scene_id": "E1S01", "shots": 2, "new": 2}, {"scene_id": "E1S02", "shots": 1, "new": 0}])
        self.assertEqual(listed["max_shots"], prompt_data.number("canvas_storyboard", "max_shots"))

    def test_refusals_are_said_in_words(self):
        unknown = self.lay(scene_ids=["E9S09"])
        self.assertEqual(unknown.status_code, 422)
        self.assertIn("E9S09", unknown.text)
        stale = self.lay(expected_version=7)
        self.assertEqual(stale.status_code, 409, stale.text)
        empty = _task(shots=[])
        self.drama.repo.save_task("t-1", empty)
        none = self.lay()
        self.assertEqual(none.status_code, 422)
        self.assertIn(prompt_data.text("canvas_storyboard", "no_storyboard"), none.text)

    def test_too_many_shots_at_once_are_refused(self):
        limit = prompt_data.number("canvas_storyboard", "max_shots")
        many = [{"scene_id": "E1S01", "shot_id": n, "desc": "走"} for n in range(1, limit + 2)]
        with self.assertRaisesRegex(canvas_storyboard.StoryboardLayoutError, str(limit)):
            canvas_storyboard.plan({"assets": {"4": many}}, {"nodes": [], "edges": []})

    def test_a_bound_result_commits_to_its_shot(self):
        self.lay(scene_ids=["E1S02"])
        canvas = self.canvas()
        clip = next(node for node in canvas["nodes"] if node["kind"] == "video_gen")
        self.assertEqual(studio_canvas._binding(clip), ("E1S02", 1))


class OperationFieldTests(StoryboardCase):
    def edit(self, operations):
        return studio_canvas.apply_operations({"nodes": [], "edges": []}, operations)

    def test_a_media_node_can_be_added_holding_a_file_and_a_node_bound_to_a_shot(self):
        document, refs = self.edit([
            {"op": "add_node", "ref": "m", "kind": "media", "output": {"medium": "image", "url": "/media/a.png", "name": "a"}},
            {"op": "add_node", "ref": "v", "kind": "video_gen", "prompt": "走", "binding": {"sceneId": "E1S01", "shotId": "2"}},
            {"op": "update_node", "id": "v", "binding": {"sceneId": "E1S02"}},
        ])
        by_id = {node["id"]: node for node in document["nodes"]}
        self.assertEqual(by_id[refs["m"]]["payload"]["output"], {"medium": "image", "url": "/media/a.png", "name": "a"})
        self.assertEqual(by_id[refs["v"]]["payload"]["binding"], {"sceneId": "E1S02"})

    def test_bad_fields_refuse_the_whole_request(self):
        for operation in (
            {"op": "add_node", "kind": "image_gen", "output": {"medium": "image", "url": "/media/a.png"}},
            {"op": "add_node", "kind": "media", "output": {"medium": "image", "url": "javascript:alert(1)"}},
            {"op": "add_node", "kind": "media", "output": {"medium": "text", "url": "/media/a.txt"}},
            {"op": "add_node", "kind": "video_gen", "binding": {"shotId": 1}},
            {"op": "add_node", "kind": "video_gen", "binding": {"sceneId": "E1S01", "shotId": "two"}},
        ):
            with self.subTest(operation=operation), self.assertRaises(studio_canvas.CanvasOperationError):
                self.edit([operation])


if __name__ == "__main__":
    import unittest

    unittest.main()

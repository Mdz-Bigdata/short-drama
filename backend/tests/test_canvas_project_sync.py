# -*- coding: utf-8 -*-
"""Syncing a canvas with its project's storyboard: new shots come in, project changes come over, canvas edits stay.

No provider is called. What is pinned: a first sync lays everything out and marks what it placed; a
second finds nothing; a project change reaches a node the canvas left alone and is put to the person
where the canvas changed it too (or where the node predates syncing); nothing is moved or deleted; a
review answered after things moved is refused; a new shot of a scene on the canvas joins its row.
"""

from unittest import mock

from app.core import canvas_project_sync, prompt_data
from tests.test_canvas_storyboard import SHOTS
from tests.test_canvas_workspace import CanvasCase, _task


class SyncCase(CanvasCase):
    def setUp(self):
        super().setUp()
        task = _task(shots=[dict(shot) for shot in SHOTS])
        task["assets"]["3_sheets"] = {"林晚": "https://img.test/lin.png", "周叔": "not-a-url"}
        self.drama.repo.save_task("t-1", task)

    def change_project(self, change):
        task = self.drama.repo.get_task("t-1")
        change(task)
        self.drama.repo.save_task("t-1", task)

    def shot(self, task, scene, number):
        return next(item for item in task["assets"]["4"] if item["scene_id"] == scene and int(item["shot_id"]) == number)

    def review(self):
        response = self.client.get(f"{self.base}/canvas/project-sync")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def sync(self, review=None, accept=None, add_new=True, expect=200):
        review = review or self.review()
        accept = [item["id"] for item in review["items"] if item["checked"]] if accept is None else accept
        response = self.client.post(f"{self.base}/canvas/project-sync", json={
            "expected_version": review["version"], "token": review["token"], "accept": accept, "add_new": add_new,
        })
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def canvas(self):
        return self.client.get(f"{self.base}/canvas").json()

    def by_label(self):
        return {node["payload"].get("label"): node for node in self.canvas()["nodes"]}


class FirstSyncTests(SyncCase):
    def test_a_first_sync_lays_everything_out_and_marks_it_and_a_second_finds_nothing(self):
        first = self.review()
        self.assertTrue(first["storyboard"])
        self.assertEqual((first["new"]["shots"], first["new"]["this_time"], first["new"]["later"]), (3, 3, 0))
        self.assertEqual((first["items"], first["notes"]), ([], []))
        done = self.sync(first)
        self.assertEqual((done["applied"], done["shots"], done["updated"]), (True, 3, 0))
        self.assertTrue(done["node_ids"])

        nodes = self.by_label()
        clip = nodes["E1S01 镜1 视频"]
        self.assertEqual(clip["payload"][canvas_project_sync.MARK]["key"], "shot:E1S01:1:clip")
        self.assertEqual(set(clip["payload"][canvas_project_sync.MARK]["seen"]), {"prompt", "duration"})
        self.assertEqual(nodes["E1S01 镜1 首帧"]["payload"][canvas_project_sync.MARK]["key"], "shot:E1S01:1:frame")
        self.assertEqual(nodes["E1S01 镜2 分镜图"]["payload"][canvas_project_sync.MARK]["key"], "shot:E1S01:2:frame")
        self.assertEqual(nodes["林晚·定妆"]["payload"][canvas_project_sync.MARK]["key"], "cast:林晚")

        again = self.review()
        self.assertEqual((again["new"]["shots"], again["items"], again["notes"]), (0, [], []))
        self.assertEqual(again["followed"], 7)
        self.assertEqual(self.sync(again)["applied"], False)

    def test_a_project_with_no_storyboard_has_nothing_to_sync(self):
        self.change_project(lambda task: task["assets"].update({"4": []}))
        review = self.review()
        self.assertEqual((review["storyboard"], review["new"]["shots"], review["items"]), (False, 0, []))
        self.assertEqual(self.sync(review)["applied"], False)

    def test_too_many_new_shots_come_in_whole_scenes_over_several_syncs(self):
        real = prompt_data.number

        def number(name, key):
            return 2 if (name, key) == ("canvas_storyboard", "max_shots") else real(name, key)

        with mock.patch.object(canvas_project_sync.prompt_data, "number", side_effect=number):
            first = self.review()
            self.assertEqual((first["new"]["this_time"], first["new"]["later"]), (2, 1))
            self.assertEqual([scene["scene_id"] for scene in first["new"]["scenes"] if scene["this_time"]], ["E1S01"])
            self.assertEqual(self.sync(first)["shots"], 2)
            second = self.review()
            self.assertEqual((second["new"]["this_time"], second["new"]["later"]), (1, 0))
            self.assertEqual(self.sync(second)["shots"], 1)


class ProjectChangeTests(SyncCase):
    def setUp(self):
        super().setUp()
        self.sync()

    def test_a_change_in_the_project_reaches_a_node_the_canvas_left_alone(self):
        self.change_project(lambda task: self.shot(task, "E1S01", 1).update({"desc": "林晚用力推开老宅的门", "duration": "6秒"}))
        review = self.review()
        fields = {(item["label"], item["field"]): item for item in review["items"]}
        prompt = fields[("E1S01 镜1 视频", "prompt")]
        self.assertEqual((prompt["state"], prompt["checked"]), ("update", True))
        self.assertEqual(prompt["canvas"], "林晚推开老宅的门\n台词：林晚：有人吗？")
        self.assertEqual(prompt["project"], "林晚用力推开老宅的门\n台词：林晚：有人吗？")
        self.assertEqual((fields[("E1S01 镜1 视频", "duration")]["canvas"], fields[("E1S01 镜1 视频", "duration")]["project"]), (5, 6))
        done = self.sync(review)
        self.assertEqual((done["updated"], done["kept"]), (1, 0))
        clip = self.by_label()["E1S01 镜1 视频"]
        self.assertEqual(clip["payload"]["prompt"], "林晚用力推开老宅的门\n台词：林晚：有人吗？")
        self.assertEqual(clip["payload"]["params"]["durationSeconds"], 6)
        self.assertEqual(self.review()["items"], [])

    def test_an_edit_on_the_canvas_stays_while_the_project_has_not_changed(self):
        canvas = self.canvas()
        for node in canvas["nodes"]:
            if node["payload"].get("label") == "E1S01 镜1 视频":
                node["payload"]["prompt"] = "我自己写的：林晚停在门口"
        self.put(canvas["nodes"], canvas["edges"], expected=canvas["version"])
        self.assertEqual(self.review()["items"], [])

    def test_when_both_sides_changed_the_person_decides_and_a_refusal_is_remembered(self):
        canvas = self.canvas()
        for node in canvas["nodes"]:
            if node["payload"].get("label") == "E1S01 镜1 视频":
                node["payload"]["prompt"] = "我自己写的：林晚停在门口"
        self.put(canvas["nodes"], canvas["edges"], expected=canvas["version"])
        self.change_project(lambda task: self.shot(task, "E1S01", 1).update({"desc": "林晚用力推开老宅的门"}))
        review = self.review()
        [item] = [item for item in review["items"] if item["field"] == "prompt"]
        self.assertEqual((item["state"], item["checked"], item["canvas"]), ("conflict", False, "我自己写的：林晚停在门口"))
        done = self.sync(review)
        self.assertEqual((done["updated"], done["kept"]), (0, 1))
        self.assertEqual(self.by_label()["E1S01 镜1 视频"]["payload"]["prompt"], "我自己写的：林晚停在门口")
        self.assertEqual(self.review()["items"], [], "the canvas's version was kept on purpose; asking again would nag")

    def test_a_conflict_taken_from_the_project_overwrites_the_canvas(self):
        canvas = self.canvas()
        for node in canvas["nodes"]:
            if node["payload"].get("label") == "E1S01 镜1 视频":
                node["payload"]["prompt"] = "我自己写的"
        self.put(canvas["nodes"], canvas["edges"], expected=canvas["version"])
        self.change_project(lambda task: self.shot(task, "E1S01", 1).update({"desc": "新的画面"}))
        review = self.review()
        [item] = [item for item in review["items"] if item["field"] == "prompt"]
        self.sync(review, accept=[item["id"]])
        self.assertEqual(self.by_label()["E1S01 镜1 视频"]["payload"]["prompt"], "新的画面\n台词：林晚：有人吗？")

    def test_a_redrawn_storyboard_picture_and_a_new_look_sheet_come_over(self):
        def redraw(task):
            self.shot(task, "E1S01", 2)["image_url"] = "/media/board_2_v2.png"
            task["assets"]["3_sheets"]["林晚"] = "https://img.test/lin_v2.png"

        self.change_project(redraw)
        review = self.review()
        pictures = {item["label"]: item for item in review["items"] if item["field"] == "picture"}
        self.assertEqual(set(pictures), {"E1S01 镜2 分镜图", "林晚·定妆"})
        self.assertTrue(all(item["checked"] for item in pictures.values()))
        self.sync(review)
        nodes = self.by_label()
        self.assertEqual(nodes["E1S01 镜2 分镜图"]["payload"]["output"]["url"], "/media/board_2_v2.png")
        self.assertEqual(nodes["林晚·定妆"]["payload"]["output"], {"medium": "image", "url": "https://img.test/lin_v2.png", "name": "林晚"})

    def test_a_shot_that_left_the_project_and_a_picture_now_drawn_are_only_reported(self):
        def change(task):
            task["assets"]["4"] = [item for item in task["assets"]["4"] if item["scene_id"] != "E1S02"]
            self.shot(task, "E1S01", 1)["image_url"] = "/media/board_1.png"

        before = self.canvas()
        self.change_project(change)
        review = self.review()
        notes = {(note["kind"], note["label"]) for note in review["notes"]}
        self.assertEqual(notes, {("gone", "E1S02 镜1 视频"), ("board_ready", "E1S01 镜1 首帧")})
        self.assertEqual(review["items"], [])
        self.assertEqual(self.sync(review)["applied"], False)
        self.assertEqual(len(self.canvas()["nodes"]), len(before["nodes"]), "nothing is deleted")

    def test_a_node_bound_by_hand_keeps_its_own_text(self):
        canvas = self.canvas()
        canvas["nodes"].append({
            "id": "mine", "kind": "video_gen", "track": "freezone", "x": 0, "y": 3000, "width": 300, "height": 300, "artifact_id": None,
            "payload": {"label": "我的版本", "prompt": "完全不同的写法", "binding": {"sceneId": "E1S01", "shotId": 1}},
        })
        self.put(canvas["nodes"], canvas["edges"], expected=canvas["version"])
        self.change_project(lambda task: self.shot(task, "E1S01", 1).update({"desc": "林晚用力推开老宅的门"}))
        labels = {item["label"] for item in self.review()["items"]}
        self.assertNotIn("我的版本", labels)
        self.assertIn("E1S01 镜1 视频", labels)


class LegacyLayoutTests(SyncCase):
    def test_nodes_laid_out_before_syncing_existed_are_followed_and_a_difference_is_asked(self):
        self.assertEqual(self.client.post(f"{self.base}/canvas/storyboard", json={}).status_code, 200)
        self.assertEqual(self.review()["items"], [], "laid out from the same storyboard, so nothing differs yet")
        self.change_project(lambda task: self.shot(task, "E1S01", 1).update({"desc": "新的画面"}))
        [item] = [item for item in self.review()["items"] if item["field"] == "prompt"]
        # No memory of what the project said when it was laid out: either side may have moved.
        self.assertEqual((item["label"], item["state"], item["checked"]), ("E1S01 镜1 视频", "conflict", False))


class NewShotTests(SyncCase):
    def setUp(self):
        super().setUp()
        self.sync()

    def add_shot(self, task):
        task["assets"]["4"].append({"scene_id": "E1S01", "shot_id": 3, "desc": "她走进院子", "characters": ["林晚"], "duration": "5秒"})

    def test_a_new_shot_of_a_scene_on_the_canvas_joins_its_row_and_group(self):
        self.change_project(self.add_shot)
        review = self.review()
        self.assertEqual(review["new"]["scenes"], [{"scene_id": "E1S01", "shots": 3, "new": 1, "on_canvas": True, "this_time": True}])
        self.assertEqual(self.sync(review)["shots"], 1)
        nodes = self.by_label()
        new_frame, new_clip = nodes["E1S01 镜3 首帧"], nodes["E1S01 镜3 视频"]
        old_frame, old_clip = nodes["E1S01 镜2 分镜图"], nodes["E1S01 镜2 视频"]
        self.assertEqual((new_frame["y"], new_clip["y"]), (old_frame["y"], old_clip["y"]))
        self.assertEqual(new_frame["x"], old_clip["x"] + old_clip["width"] + prompt_data.number("canvas_project_sync", "sibling_gap"))
        scene_group = old_clip["payload"]["groupId"]
        self.assertEqual((new_frame["payload"]["groupId"], new_clip["payload"]["groupId"]), (scene_group, scene_group))
        group = next(node for node in self.canvas()["nodes"] if node["id"] == scene_group)
        self.assertGreaterEqual(group["x"] + group["width"], new_clip["x"] + new_clip["width"], "the scene's frame grew around it")
        self.assertEqual(sum(1 for node in self.canvas()["nodes"] if node["kind"] == "group"), 2, "no second group for the scene")
        self.assertEqual(new_clip["payload"][canvas_project_sync.MARK]["key"], "shot:E1S01:3:clip")

    def test_something_in_the_way_sends_the_new_shot_to_a_row_of_its_own(self):
        nodes = self.by_label()
        old_clip = nodes["E1S01 镜2 视频"]
        canvas = self.canvas()
        canvas["nodes"].append({
            "id": "blocker", "kind": "note", "track": "freezone", "x": old_clip["x"] + old_clip["width"] + 80, "y": old_clip["y"],
            "width": 240, "height": 150, "artifact_id": None, "payload": {"text": "别挡我"},
        })
        self.put(canvas["nodes"], canvas["edges"], expected=canvas["version"])
        self.change_project(self.add_shot)
        self.sync()
        new_clip = self.by_label()["E1S01 镜3 视频"]
        self.assertNotEqual(new_clip["payload"]["groupId"], old_clip["payload"]["groupId"])
        self.assertGreater(new_clip["x"], old_clip["x"] + old_clip["width"] + 80 + 240)


class RefusalTests(SyncCase):
    def test_a_review_answered_after_the_project_moved_is_refused_and_changes_nothing(self):
        self.sync()
        self.change_project(lambda task: self.shot(task, "E1S01", 1).update({"desc": "第一次改"}))
        review = self.review()
        before = self.canvas()
        self.change_project(lambda task: self.shot(task, "E1S01", 1).update({"desc": "又改了"}))
        refused = self.sync(review, expect=409)
        self.assertIn(prompt_data.text("canvas_project_sync", "outdated"), refused["detail"])
        self.assertEqual(self.canvas()["version"], before["version"])

    def test_a_review_answered_after_the_canvas_moved_is_refused(self):
        review = self.review()
        canvas = self.canvas()
        self.put(canvas["nodes"] + [{"id": "n1", "kind": "note", "track": "freezone", "x": 0, "y": 0, "width": 200, "height": 100, "artifact_id": None, "payload": {}}],
                 canvas["edges"], expected=canvas["version"])
        self.sync(review, expect=409)

    def test_the_window_that_synced_is_not_told_about_its_own_sync(self):
        review = self.review()
        with mock.patch.object(self.studio, "_announce_saved") as announced:
            response = self.client.post(f"{self.base}/canvas/project-sync", headers={"X-Canvas-Client": "window-aaaa"}, json={
                "expected_version": review["version"], "token": review["token"], "accept": [], "add_new": True,
            })
        self.assertEqual(response.status_code, 200, response.text)
        announced.assert_called_once_with(self.project, "u1", "main", response.json()["version"], "window-aaaa")

    def test_someone_else_s_project_is_not_found(self):
        self.user = {"user_id": "intruder", "role": "user"}
        self.assertEqual(self.client.get(f"{self.base}/canvas/project-sync").status_code, 404)

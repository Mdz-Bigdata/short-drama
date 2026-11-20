# -*- coding: utf-8 -*-
"""多人同框不排排站：按人数给占位公式，排成一排的镜头退回改一版。"""

import unittest

from app.core import group_blocking

ROW = "沈砚位于画面左侧三分之一的中景，朝向画面右侧；苏晚位于画面右侧三分之一的中景，朝向画面左侧；李三位于画面中央的中景，朝向画面左侧"
TRIANGLE = "沈砚位于画面中央的前景，朝向画面左侧，手持密信；苏晚位于画面左侧的背景，坐在太师椅上；李三位于画面右侧的背景，朝向画面左侧"


class BriefTest(unittest.TestCase):
    def test_the_formulas_follow_the_head_count(self):
        one = group_blocking.brief(1)
        self.assertIn("一人：位置就是处境", one)
        self.assertNotIn("两人", one)
        self.assertNotIn("画外的人", one, "nobody can be off screen in a one-person scene")
        three = group_blocking.brief(3)
        for words in ("一人", "两人", "三人：摆成三角形", "画外的人"):
            self.assertIn(words, three)
        self.assertNotIn("四人及以上", three)
        self.assertIn("四人及以上", group_blocking.brief(7))
        self.assertEqual(group_blocking.brief(0), "")


class CheckTest(unittest.TestCase):
    def test_three_people_in_a_row_are_sent_back(self):
        rule, detail = group_blocking.shot_issue(ROW, ["沈砚", "苏晚", "李三"])
        self.assertEqual(rule, "多人排排站")
        self.assertIn("三角形", detail)

    def test_depth_height_or_a_frame_within_the_frame_pass(self):
        self.assertIsNone(group_blocking.shot_issue(TRIANGLE, ["沈砚", "苏晚", "李三"]))
        seated = ROW.replace("苏晚位于画面右侧三分之一的中景", "苏晚位于画面右侧三分之一的中景，坐在椅上")
        self.assertIsNone(group_blocking.shot_issue(seated, ["沈砚", "苏晚", "李三"]))
        framed = ROW + "；李三被门框框在中间"
        self.assertIsNone(group_blocking.shot_issue(framed, ["沈砚", "苏晚", "李三"]))

    def test_two_people_only_fail_as_a_tourist_photo(self):
        pose = "沈砚位于画面左侧的中景，面朝镜头；苏晚位于画面右侧的中景，面朝镜头"
        self.assertEqual(group_blocking.shot_issue(pose, ["沈砚", "苏晚"])[0], "两人合影站")
        talk = "沈砚位于画面左侧的中景，朝向画面右侧；苏晚位于画面右侧的中景，朝向画面左侧"
        self.assertIsNone(group_blocking.shot_issue(talk, ["沈砚", "苏晚"]))

    def test_shots_without_full_coordinates_are_left_to_the_coordinate_rule(self):
        self.assertIsNone(group_blocking.shot_issue("三个人站在院子里说话", ["沈砚", "苏晚", "李三"]))
        self.assertIsNone(group_blocking.shot_issue(ROW, ["沈砚"]))

    def test_the_revision_round_reads_one_line_per_shot(self):
        shots = [{"shot_id": 1, "desc": ROW, "characters": "沈砚、苏晚、李三"}, {"shot_id": 2, "desc": TRIANGLE, "characters": ["沈砚", "苏晚", "李三"]}]
        lines = group_blocking.table_issues(shots)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("镜1 多人排排站"))


if __name__ == "__main__":
    unittest.main()


class SceneBoardTest(unittest.TestCase):
    def test_what_still_fails_after_the_revision_is_kept_on_the_scene_board(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from app.repository.task_repo import TaskRepository
        from app.service.drama_service import DramaService
        from tests.test_storyboard_scene_contract import _stub_scene_board, _task

        def stub(service_self, t, config, scene, **kwargs):
            return {**_stub_scene_board(service_self, t, config, scene, **kwargs), "craft_issues": ["镜1 多人排排站：…"]}

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        service = DramaService()
        service.repo = TaskRepository(str(Path(temp.name) / "tasks.json"))
        task = _task([{"scene_id": "E1S01", "content": "三人对峙"}])
        service.repo.save_task(task["task_id"], task)
        with patch.object(DramaService, "_generate_scene_board", stub), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            service._execute_stage_blocking(task["task_id"], 4, _claimed_task=task)
        board = service.repo.get_task(task["task_id"])["assets"]["4_scene_boards"]["E1S01"]
        self.assertEqual(board["craft_issues"], ["镜1 多人排排站：…"])

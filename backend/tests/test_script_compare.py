# -*- coding: utf-8 -*-
"""剧本版本对比：存下的版本和现在的剧本按集对比。"""

import tempfile
import unittest
from pathlib import Path

from app.core import script_compare
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService

OLD = """第1集 暗室

林夏推开实验室的门。
林夏：有人吗？

第2集 回声

周教授站在走廊尽头。
周教授：站住。

第3集 旧稿

这一集后来删了。
"""

NEW = """第1集 暗室

林夏推开实验室的门。
林夏：有人吗？

第2集 回声

周教授站在走廊尽头，手里拿着录音笔。
周教授：站住。
林夏没有回头。

第4集 新的一集

林夏回到实验室。
"""


class CompareTests(unittest.TestCase):
    def test_each_episode_is_same_changed_added_or_removed(self):
        compared = script_compare.compare(OLD, NEW)
        self.assertFalse(compared["identical"])
        self.assertEqual([(row["episode"], row["status"], row["label"]) for row in compared["episodes"]],
                         [(2, "changed", "改了"), (3, "removed", "删掉"), (4, "added", "新增")])
        self.assertEqual({key: compared["summary"][key] for key in ("same", "changed", "added", "removed")},
                         {"same": 1, "changed": 1, "added": 1, "removed": 1})

    def test_a_changed_episode_lists_the_lines_that_went_and_came(self):
        second = script_compare.compare(OLD, NEW)["episodes"][0]
        self.assertEqual(second["title"], "第2集 回声")
        self.assertEqual((second["lines_added"], second["lines_removed"]), (2, 1))
        self.assertEqual(second["changes"][0], {"old": ["周教授站在走廊尽头。"], "new": ["周教授站在走廊尽头，手里拿着录音笔。"]})
        self.assertEqual(second["changes"][1], {"old": [], "new": ["林夏没有回头。"]})

    def test_blank_lines_and_spacing_are_not_changes(self):
        respaced = OLD.replace("\n\n", "\n").replace("林夏：有人吗？", "林夏：有人吗？  ")
        self.assertTrue(script_compare.compare(OLD, respaced)["identical"])
        self.assertEqual(script_compare.compare(OLD, respaced)["episodes"], [])

    def test_text_before_the_first_episode_is_its_own_part_and_long_changes_are_cut(self):
        compared = script_compare.compare("片名：暗室\n" + OLD, "片名：回声\n" + OLD)
        self.assertEqual((compared["episodes"][0]["episode"], compared["episodes"][0]["title"]), (0, "开头（第一集之前）"))
        many_old = "第1集\n" + "\n".join(f"旧的第{i}行" for i in range(40))
        many_new = "第1集\n" + "\n".join(f"新的第{i}行" for i in range(40))
        change = script_compare.compare(many_old, many_new)["episodes"][0]["changes"][0]
        self.assertEqual(change["old"][-1], "…")
        self.assertEqual(len(change["old"]), 7)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("t", {"task_id": "t", "config": {}, "assets": {
            "2": NEW, "2_versions": [{"version_id": "v1", "label": "第一稿", "created_at": "2026-11-19T00:00:00+00:00", "payload": {"2": OLD}}],
        }})
        self.service = DramaService()
        self.service.repo = self.repo

    def test_a_saved_version_is_compared_with_the_current_screenplay(self):
        compared = self.service.compare_script_version("t", "v1")
        self.assertEqual((compared["version_id"], compared["label"]), ("v1", "第一稿"))
        self.assertEqual([row["episode"] for row in compared["episodes"]], [2, 3, 4])
        self.assertEqual(self.repo.get_task("t")["assets"]["2"], NEW)

    def test_an_unknown_version_or_project(self):
        with self.assertRaises(ValueError):
            self.service.compare_script_version("t", "nope")
        self.assertIsNone(self.service.compare_script_version("nope", "v1"))


if __name__ == "__main__":
    unittest.main()

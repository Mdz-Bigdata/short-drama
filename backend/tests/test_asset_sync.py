"""资产库里改了一个资产，挂着它的每个项目逐个、幂等地知道：哪些镜头、场景板和片段过期。"""

import unittest
from copy import deepcopy
from unittest.mock import patch

from app.service import asset_sync
from tests.test_asset_dependents import _task as dependents_task
from tests.test_asset_identity import _task as identity_task


class FakeRepo:
    """和 TaskRepository 同样的两个入口：按行改一个项目、读一个项目。"""

    def __init__(self, tasks: dict):
        self.tasks = {key: deepcopy(value) for key, value in tasks.items()}
        self.mutated: list[str] = []

    def mutate_task(self, task_id, mutation):
        if task_id not in self.tasks:
            return None
        self.mutated.append(task_id)
        task = deepcopy(self.tasks[task_id])
        result = mutation(task)
        self.tasks[task_id] = task
        return result

    def get_task(self, task_id):
        return deepcopy(self.tasks.get(task_id))


def _element(**overrides) -> dict:
    element = {
        "id": "el-zhou", "owner_id": "u1", "kind": "actor", "name": "周教授", "description": "金丝眼镜", "version": 4,
        "metadata": {"task_id": "t1", "task_ids": ["t1", "t2"], "aliases": ["老周"]},
    }
    element.update(overrides)
    return element


def _second_task() -> dict:
    task = dependents_task()
    task["task_id"] = "t2"
    task["config"]["title_suggestion"] = "第二部"
    return task


class ElementChangedTests(unittest.TestCase):
    def test_every_linked_project_is_marked_once(self):
        repo = FakeRepo({"t1": dependents_task(), "t2": _second_task()})

        result = asset_sync.sync_element(_element(), reason="", repo=repo)

        self.assertFalse(result["renamed"])
        self.assertEqual([row["task_id"] for row in result["tasks"]], ["t1", "t2"])
        for row in result["tasks"]:
            self.assertEqual((row["shots_marked"], row["clips_marked"], row["boards_marked"]), (3, 3, 2))
            self.assertNotIn("skipped", row)
        clip = repo.tasks["t2"]["assets"]["5"][2]
        self.assertTrue(clip["stale"])
        self.assertEqual(clip["stale_reason"], "资产「周教授」已修改，需重画本场分镜、重跑第 5 阶段后生效")

        again = asset_sync.sync_element(_element(), reason="", repo=repo)
        self.assertEqual([(row["shots_marked"], row["clips_marked"], row["boards_marked"]) for row in again["tasks"]], [(0, 0, 0), (0, 0, 0)])

    def test_a_generating_project_another_owners_project_and_a_missing_one_are_skipped(self):
        running = _second_task()
        running["status"] = "running"
        foreign = dependents_task()
        foreign["task_id"] = "t3"
        foreign["owner_user_id"] = "someone-else"
        repo = FakeRepo({"t1": dependents_task(), "t2": running, "t3": foreign})
        element = _element(metadata={"task_id": "t1", "task_ids": ["t1", "t2", "t3", "gone"]})

        result = asset_sync.sync_element(element, reason="换了图：{name}", repo=repo)

        rows = {row["task_id"]: row for row in result["tasks"]}
        self.assertNotIn("skipped", rows["t1"])
        self.assertEqual(rows["t2"]["skipped"], asset_sync.SKIPPED_RUNNING)
        self.assertEqual(rows["t3"]["skipped"], asset_sync.SKIPPED_OWNER)
        self.assertEqual(rows["gone"]["skipped"], asset_sync.SKIPPED_MISSING)
        self.assertEqual(repo.tasks["t2"], running)
        self.assertNotIn("stale", repo.tasks["t3"]["assets"]["5"][1])
        self.assertEqual(repo.tasks["t1"]["assets"]["5"][1]["stale_reason"], "换了图：周教授")

    def test_one_failing_project_only_fails_its_own_row(self):
        repo = FakeRepo({"t1": dependents_task(), "t2": _second_task()})
        original = repo.mutate_task

        def flaky(task_id, mutation):
            if task_id == "t1":
                raise RuntimeError("db down")
            return original(task_id, mutation)

        repo.mutate_task = flaky
        result = asset_sync.sync_element(_element(), reason="", repo=repo)
        self.assertIn("db down", result["tasks"][0]["error"])
        self.assertEqual(result["tasks"][1]["shots_marked"], 3)

    def test_the_public_entry_uses_the_service_repo(self):
        repo = FakeRepo({"t1": dependents_task()})
        with patch.object(asset_sync, "_repo", return_value=repo):
            result = asset_sync.element_changed(_element(metadata={"task_id": "t1", "aliases": ["老周"]}), reason="")
        self.assertEqual(result["tasks"][0]["shots_marked"], 3)


class RenameTests(unittest.TestCase):
    def test_a_library_rename_renames_the_project_that_still_uses_the_old_name(self):
        project = identity_task()
        project["owner_user_id"] = "u1"
        other = dependents_task()
        other["task_id"] = "t2"
        repo = FakeRepo({"id-1": project, "t2": other})
        element = _element(id="el-lin", name="沈知微", metadata={"task_id": "id-1", "task_ids": ["id-1", "t2"]})

        result = asset_sync.sync_element(element, reason="", old_name="林夏", repo=repo)

        self.assertTrue(result["renamed"])
        rows = {row["task_id"]: row for row in result["tasks"]}
        self.assertTrue(rows["id-1"]["renamed"])
        stored = repo.tasks["id-1"]
        characters = stored["assets"]["2_screenwriting"]["inventory"]["characters"]
        self.assertNotIn("林夏", characters)
        self.assertEqual(characters["沈知微"]["aliases"], ["林夏"])
        self.assertEqual(stored["assets"]["4"][0]["characters"], ["沈知微", "周教授"])
        self.assertIn("沈知微", stored["assets"]["2"])
        # 改名之后照常标过期：用到这个人的镜头的片段待重跑，另一镜不动。
        self.assertEqual(rows["id-1"]["clips_marked"], 1)
        self.assertTrue(stored["assets"]["5"][0]["stale"])
        self.assertNotIn("stale", stored["assets"]["5"][1])
        # 第二个项目里林夏只是分镜绑定里的旧名字，没有编剧状态：不改名，只按 id 标过期。
        self.assertFalse(rows["t2"]["renamed"])
        self.assertEqual(rows["t2"]["shots_marked"], 1)

    def test_a_rename_onto_a_name_the_project_already_uses_is_reported_not_forced(self):
        project = identity_task()
        project["owner_user_id"] = "u1"
        repo = FakeRepo({"id-1": project})
        element = _element(id="el-lin", name="周教授", metadata={"task_id": "id-1"})

        result = asset_sync.sync_element(element, reason="", old_name="林夏", repo=repo)

        row = result["tasks"][0]
        self.assertFalse(result["renamed"])
        self.assertIn("合并", row["rename_error"])
        self.assertIn("林夏", repo.tasks["id-1"]["assets"]["2_screenwriting"]["inventory"]["characters"])

    def test_kinds_outside_the_script_identity_only_mark(self):
        repo = FakeRepo({"t1": dependents_task()})
        task = repo.tasks["t1"]
        task["assets"]["4"][0]["effects"] = ["雷劫"]
        element = _element(id="el-fx", kind="effect", name="九霄雷劫", metadata={"task_id": "t1"})

        result = asset_sync.sync_element(element, reason="", old_name="雷劫", repo=repo)

        self.assertFalse(result["renamed"])
        self.assertEqual(result["tasks"][0]["shots_marked"], 1)


class UsagesTests(unittest.TestCase):
    def test_usage_rows_name_the_project_and_how_the_shot_uses_the_asset(self):
        repo = FakeRepo({"t1": dependents_task(), "t2": _second_task()})
        element = _element(id="el-lin", name="林夏", metadata={"task_id": "t1", "task_ids": ["t1", "t2"]})

        rows = asset_sync.element_usages(element, repo=repo)

        self.assertEqual(rows, [
            {"task_id": "t1", "title": "暗室回声", "scene_id": "E1S01", "shot_id": 1, "shot_uid": 100101, "in_storyboard": True, "in_video": True},
            {"task_id": "t2", "title": "第二部", "scene_id": "E1S01", "shot_id": 1, "shot_uid": 100101, "in_storyboard": True, "in_video": True},
        ])
        zhou = asset_sync.element_usages(_element(metadata={"task_id": "t1", "aliases": "老周"}), repo=repo)
        self.assertEqual([(row["scene_id"], row["shot_id"], row["in_video"]) for row in zhou], [("E1S01", 1, False), ("E1S01", 2, False), ("E1S02", 1, False)])
        with patch.object(asset_sync, "_repo", return_value=repo):
            self.assertEqual(asset_sync.usages(element), rows)


if __name__ == "__main__":
    unittest.main()

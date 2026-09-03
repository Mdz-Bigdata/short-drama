import unittest

from main import _recover_orphan_task_state


class TaskRecoveryTests(unittest.TestCase):
    def test_completed_stage_is_restored_to_idle_instead_of_interrupted(self):
        task = {
            "task_id": "completed-stage",
            "current_stage": 6,
            "status": "running",
            "fail_reason": "旧的失败原因",
            "stage_progress": {"stage": 6, "status": "success", "percent": 100},
        }

        changed = _recover_orphan_task_state(task)

        self.assertTrue(changed)
        self.assertEqual(task["status"], "idle")
        self.assertIsNone(task["fail_reason"])

    def test_inflight_stage_is_marked_interrupted(self):
        task = {
            "task_id": "inflight-stage",
            "current_stage": 5,
            "status": "running",
            "stage_progress": {"stage": 5, "status": "running", "percent": 47},
        }

        changed = _recover_orphan_task_state(task)

        self.assertTrue(changed)
        self.assertEqual(task["status"], "interrupted")
        self.assertIn("服务重启", task["fail_reason"])

    def test_non_running_task_is_unchanged(self):
        task = {"task_id": "idle-task", "status": "idle"}

        self.assertFalse(_recover_orphan_task_state(task))
        self.assertEqual(task, {"task_id": "idle-task", "status": "idle"})


if __name__ == "__main__":
    unittest.main()

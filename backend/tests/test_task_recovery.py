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

    def test_review_state_releases_orphan_reservation_without_losing_review(self):
        for status in ("awaiting_quality_review", "awaiting_council_review", "completed"):
            task = {"task_id": "review", "status": status, "workflow_control": {"active": True}}
            self.assertTrue(_recover_orphan_task_state(task))
            self.assertFalse(task["workflow_control"]["active"])
            self.assertEqual(task["status"], status)

    def test_stop_request_is_preserved_when_recovering_a_running_task(self):
        task = {"task_id": "stopping", "status": "running", "workflow_control": {
            "active": True, "pause_requested": True, "stop_requested": True}}
        self.assertTrue(_recover_orphan_task_state(task))
        self.assertEqual(task["status"], "stopped")


if __name__ == "__main__":
    unittest.main()

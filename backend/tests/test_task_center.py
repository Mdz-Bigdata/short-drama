"""The Task Center: listing a project's jobs, and a retry that never goes around admission or the queue."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import drama_api, task_center_api
from app.api.auth_api import get_current_user
from app.core import generation_queue
from app.core.generation_queue import Item, Queue
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService, StagePrerequisiteError

ADMITTED = {"decision": "admitted", "shots": [], "confirmations": [], "estimate": {}}


def _snapshot() -> dict:
    queue = Queue()
    queue.add(Item(key="frames:1", label="镜头 1 · 首尾帧", family="seedream", medium="image", meta={"shot_id": 1}))
    queue.add(Item(key="video:1", label="镜头 1 · 视频", family="seedance", medium="video", depends_on=["frames:1"],
                   meta={"shot_id": 1, "job_key": "101:0"}))
    queue.add(Item(key="assemble:1", label="镜头 1 · 入片", family="tts", medium="audio", depends_on=["video:1"], meta={"shot_id": 1}))
    queue.add(Item(key="video:2", label="镜头 2 · 视频", family="seedance", medium="video", meta={"shot_id": 2}))
    queue.mark_started("frames:1")
    queue.mark_done("frames:1")
    queue.mark_started("video:1")
    queue.mark_failed("video:1", "RuntimeError: provider said no")
    return queue.snapshot(run_id="r1")


class TaskCenterRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.task_id = "task-center"
        self.service.repo.save_task(self.task_id, {
            "task_id": self.task_id, "owner_user_id": "u-1", "status": "failed", "config": {},
            "stage_progress": {"stage": 5, "status": "failed"},
            "assets": {
                generation_queue.QUEUE_KEY: _snapshot(),
                "5_jobs": {"101:0": {"key": "101:0", "job_id": "job-9", "status": "failed", "family": "seedance", "error": "nope"}},
                "5_failures": {"101": {"kind": "provider_error", "code": "1026", "message": "provider said no", "shot_uids": [101]}},
            },
        })
        patcher = patch.object(drama_api, "service", self.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(task_center_api.router)
        app.dependency_overrides[drama_api.require_owned_drama_task] = lambda: {"user_id": "u-1", "role": "user"}
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-1", "role": "user"}
        self.client = TestClient(app)

    def _list(self, query=""):
        response = self.client.get(f"/api/drama/{self.task_id}/tasks{query}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_lists_jobs_with_their_rules_log_and_progress(self):
        body = self._list()
        self.assertFalse(body["running"])
        self.assertEqual([job["key"] for job in body["jobs"]], ["frames:1", "video:1", "assemble:1", "video:2"])
        by_key = {job["key"]: job for job in body["jobs"]}
        self.assertTrue(by_key["video:1"]["can_retry"])
        self.assertFalse(by_key["video:1"]["can_cancel"])
        self.assertTrue(by_key["video:2"]["can_cancel"])
        self.assertFalse(by_key["video:2"]["can_retry"])
        self.assertEqual(by_key["assemble:1"]["status"], "skipped")
        self.assertFalse(by_key["assemble:1"]["can_retry"])
        self.assertEqual(by_key["video:1"]["provider_job"]["job_id"], "job-9")
        self.assertEqual(by_key["video:1"]["failure"]["code"], "1026")
        self.assertIn("provider said no", by_key["video:1"]["log"][-1]["text"])
        self.assertEqual(body["progress"], {"settled": 3, "total": 4, "percent": 75, "running": 0, "label": ""})
        self.assertIn("seedance/video", body["buckets"])

    def test_filter_narrows_jobs_but_not_counts(self):
        body = self._list("?status=failed,skipped")
        self.assertEqual([job["key"] for job in body["jobs"]], ["video:1", "assemble:1"])
        self.assertEqual(body["counts"]["queued"], 1)
        self.assertEqual(body["counts"]["done"], 1)

    def test_empty_project_lists_nothing(self):
        self.service.repo.save_task("empty", {"task_id": "empty", "assets": {}})
        body = self.client.get("/api/drama/empty/tasks").json()
        self.assertEqual(body["jobs"], [])
        self.assertEqual(body["progress"]["percent"], 0)

    def test_unknown_project_is_404(self):
        self.assertEqual(self.client.get("/api/drama/none/tasks").status_code, 404)

    def test_retry_is_admitted_claimed_and_run_without_touching_other_items(self):
        claimed = self.service.repo.get_task(self.task_id)
        with patch.object(self.service, "assess_video_admission", return_value=ADMITTED) as assess, \
             patch.object(self.service, "_claim_stage_task", return_value=claimed) as claim, \
             patch.object(self.service, "execute_stage", new=AsyncMock(return_value={})) as execute:
            response = self.client.post(f"/api/drama/{self.task_id}/tasks/video%3A1/retry")
        self.assertEqual(response.status_code, 202, response.text)
        assess.assert_called_once_with(self.task_id)
        claim.assert_called_once_with(self.task_id, 5)
        execute.assert_awaited_once()
        self.assertEqual(execute.await_args.args, (self.task_id, 5))
        stored = generation_queue.snapshot_of(self.service.repo.get_task(self.task_id))
        self.assertEqual(stored["retries"][0]["key"], "video:1")
        self.assertIn("provider said no", stored["retries"][0]["error"])
        self.assertEqual({item["key"]: item["status"] for item in stored["items"]}["video:2"], "queued")

    def test_blocked_admission_refuses_and_starts_nothing(self):
        blocked = {"decision": "blocked", "confirmations": [], "shots": [
            {"shot_id": 1, "problems": [{"code": "missing_assets", "message": "缺少首帧", "blocking": True}]},
        ]}
        with patch.object(self.service, "assess_video_admission", return_value=blocked), \
             patch.object(self.service, "_claim_stage_task") as claim, \
             patch.object(self.service, "execute_stage", new=AsyncMock()) as execute:
            response = self.client.post(f"/api/drama/{self.task_id}/tasks/video%3A1/retry")
        self.assertEqual(response.status_code, 409)
        self.assertIn("缺少首帧", response.json()["detail"])
        self.assertEqual(response.json()["admission"]["decision"], "blocked")
        claim.assert_not_called()
        execute.assert_not_called()
        self.assertNotIn("retries", generation_queue.snapshot_of(self.service.repo.get_task(self.task_id)))

    def test_duration_confirmation_also_refuses(self):
        waiting = {"decision": "confirmation_required", "shots": [], "confirmations": [
            {"scripted_seconds": 7, "requested_seconds": 8, "shot_count": 1},
        ]}
        with patch.object(self.service, "assess_video_admission", return_value=waiting), \
             patch.object(self.service, "_claim_stage_task") as claim:
            response = self.client.post(f"/api/drama/{self.task_id}/tasks/video%3A1/retry")
        self.assertEqual(response.status_code, 409)
        self.assertIn("7s→8s", response.json()["detail"])
        claim.assert_not_called()

    def test_real_claim_rechecks_admission_and_its_refusal_is_reported(self):
        with patch.object(self.service, "assess_video_admission", return_value=ADMITTED), \
             patch.object(self.service, "_assert_stage_prerequisites", side_effect=StagePrerequisiteError("批量视频准入受阻")) as check, \
             patch.object(self.service, "execute_stage", new=AsyncMock()) as execute:
            response = self.client.post(f"/api/drama/{self.task_id}/tasks/video%3A1/retry")
        self.assertEqual(response.status_code, 409)
        self.assertIn("批量视频准入受阻", response.json()["detail"])
        check.assert_called_once()
        execute.assert_not_called()
        self.assertEqual(self.service.repo.get_task(self.task_id)["status"], "failed")

    def test_only_failed_items_retry(self):
        with patch.object(self.service, "assess_video_admission") as assess:
            for key, phrase in (("video%3A2", "只有失败的项"), ("assemble%3A1", "连带跳过"), ("frames%3A1", "只有失败的项"), ("nope", "没有")):
                response = self.client.post(f"/api/drama/{self.task_id}/tasks/{key}/retry")
                self.assertEqual(response.status_code, 409, key)
                self.assertIn(phrase, response.json()["detail"])
        assess.assert_not_called()

    def test_no_retry_while_stage_five_is_running(self):
        self.service.repo.mutate_task(self.task_id, lambda task: task.update(status="running", stage_progress={"stage": 5, "status": "running"}))
        self.assertFalse({job["key"]: job for job in self._list()["jobs"]}["video:1"]["can_retry"])
        with patch.object(self.service, "assess_video_admission") as assess:
            response = self.client.post(f"/api/drama/{self.task_id}/tasks/video%3A1/retry")
        self.assertEqual(response.status_code, 409)
        assess.assert_not_called()

    def test_retried_error_stays_in_the_log_after_the_new_run_replaces_the_items(self):
        def retried(task):
            generation_queue.note_retry(task, "video:1")
            queue = Queue([Item(key="video:1", label="镜头 1 · 视频", family="seedance", medium="video", meta={"job_key": "101:0"})])
            generation_queue.store_snapshot(task, queue.snapshot(run_id="r2"))
        self.service.repo.mutate_task(self.task_id, retried)
        job = self._list()["jobs"][0]
        self.assertEqual(job["status"], "queued")
        self.assertTrue(any("provider said no" in entry["text"] for entry in job["log"]))

    def test_cancel_marks_the_withdrawal_in_the_list(self):
        self.service.repo.mutate_task(self.task_id, lambda task: generation_queue.request_cancel(task, "video:2"))
        job = {job["key"]: job for job in self._list()["jobs"]}["video:2"]
        self.assertTrue(job["cancel_requested"])
        self.assertFalse(job["can_cancel"])


if __name__ == "__main__":
    unittest.main()

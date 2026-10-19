"""Stage 5 runs through the generation queue: shots in parallel under the ceilings, persisted as they finish, cancellable while queued."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core import generation_queue as gq
from app.core.shot_motion_contract import ShotMotionContract
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from main import app
from tests.test_shot_visual_workspace import _panel


def _shot(index: int) -> dict:
    contract = ShotMotionContract.from_panel(_panel(index), storyboard_image=f"/media/p{index}.png")
    return {
        "shot_id": index, "scene_id": "E1S01", "size": "MS", "motion": "Dolly In", "desc": "沈砚推门而入",
        "dialogue": "", "sound": "铁链轻响", "duration": "3", "image_url": f"/media/p{index}.png",
        "motion_contract": contract.model_dump(mode="json"), "contract_fingerprint": contract.contract_fingerprint,
    }


def _task(shot_count: int = 3) -> dict:
    return {
        "task_id": "q5-1", "owner_user_id": "u1", "current_stage": 4, "status": "running",
        "stage_progress": {"stage": 5, "status": "running", "calls": []},
        "workflow_control": {"run_id": "run-1", "active": True, "pause_requested": False},
        "config": {
            "video_model": "seedance2.0", "image_model": "seedream", "tts_model": "elevenlabs", "llm_model": "deepseek",
            "title_suggestion": "朕的江山", "director_style": "realistic", "shot_style": "cinematic", "episode_count": 1,
        },
        "assets": {"1": "方案", "2": "第1集 开场\n场景1：天牢\n沈砚：……", "3": "角色", "3_sheets": {"沈砚": "/media/sheet.png"}, "3_characters": [],
                   "4": [_shot(i) for i in range(1, shot_count + 1)]},
        "logs": {}, "chat_history": [],
    }


class StageFiveQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        self.lock = threading.Lock()
        self.in_flight = {"now": 0, "peak": 0}
        self.submitted: list[int] = []

    def _run(self, task, *, on_video=None, video_ceiling="2"):
        self.repo.save_task(task["task_id"], task)

        def generate_video(model, image_url, prompt, *args, **kwargs):
            with self.lock:
                self.in_flight["now"] += 1
                self.in_flight["peak"] = max(self.in_flight["peak"], self.in_flight["now"])
            try:
                if on_video is not None:
                    on_video(prompt)
                return f"https://cdn/{len(self.submitted) + 1}.mp4"
            finally:
                with self.lock:
                    self.in_flight["now"] -= 1
                    self.submitted.append(1)

        with patch.object(self.service.gateway, "generate_video", side_effect=generate_video), \
             patch.object(self.service.gateway, "generate_image", return_value=("https://cdn/frame.png", {})), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"), \
             patch.dict("os.environ", {"GENERATION_CONCURRENCY_VIDEO": video_ceiling}):
            self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        return self.repo.get_task(task["task_id"])

    def test_shots_are_generated_under_the_video_ceiling_and_the_queue_is_persisted(self):
        stored = self._run(_task(3))

        clips = stored["assets"]["5"]
        self.assertEqual([clip["shot_id"] for clip in clips], [1, 2, 3])
        self.assertTrue(all(clip["video_url"] for clip in clips))
        self.assertLessEqual(self.in_flight["peak"], 2)
        queue = stored["assets"][gq.QUEUE_KEY]
        self.assertEqual(queue["counts"][gq.DONE], 6, "video and assemble items for three shots")
        self.assertEqual(queue["buckets"]["seedance/video"]["limit"], 2)
        by_key = {item["key"]: item for item in queue["items"]}
        self.assertEqual(by_key["assemble:1"]["depends_on"], ["video:1"])
        self.assertEqual(by_key["video:1"]["meta"]["job_key"], "1:0")
        self.assertNotIn("frames:1", by_key, "stage 4 left a first frame and no exact end frame was needed")

    def test_a_queued_shot_can_be_withdrawn_while_another_runs_and_the_finished_ones_are_kept(self):
        task = _task(3)

        def withdraw_the_rest(_prompt):
            # Someone cancels whatever is still waiting while the first clip renders.
            try:
                self.repo.mutate_task("q5-1", gq.request_cancel_queued)
            except gq.CancelError:
                pass  # a later clip finds nothing left to withdraw

        with self.assertRaisesRegex(RuntimeError, "已按请求取消排队中的项"):
            self._run(task, on_video=withdraw_the_rest, video_ceiling="1")

        stored = self.repo.get_task("q5-1")
        queue = stored["assets"][gq.QUEUE_KEY]
        statuses = {item["key"]: item["status"] for item in queue["items"]}
        self.assertEqual(statuses["video:1"], gq.DONE)
        self.assertIn(gq.CANCELLED, {statuses["video:2"], statuses["video:3"]})
        self.assertEqual(len(self.submitted), 1, "nothing withdrawn was submitted")

    def test_the_queue_api_lists_items_and_refuses_to_cancel_a_running_one(self):
        task = _task(2)
        snapshot = {"run_id": "run-1", "items": [
            {"key": "video:1", "label": "镜头 1 · 视频", "family": "seedance", "medium": "video", "bucket": "seedance/video", "depends_on": [], "status": gq.RUNNING, "meta": {}},
            {"key": "video:2", "label": "镜头 2 · 视频", "family": "seedance", "medium": "video", "bucket": "seedance/video", "depends_on": [], "status": gq.QUEUED, "meta": {}},
        ], "counts": {gq.RUNNING: 1, gq.QUEUED: 1}, "buckets": {"seedance/video": {"limit": 2, "running": 1}}}
        task["assets"][gq.QUEUE_KEY] = snapshot
        self.repo.save_task("q5-1", task)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        self.addCleanup(app.dependency_overrides.pop, get_current_user, None)
        client = TestClient(app)
        self.addCleanup(client.close)

        with patch.object(drama_api, "service", self.service):
            listed = client.get("/api/drama/q5-1/queue")
            refused = client.post("/api/drama/q5-1/queue/video:1/cancel")
            accepted = client.post("/api/drama/q5-1/queue/video:2/cancel")
            nothing_left = client.post("/api/drama/q5-1/queue/cancel-queued")

        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertTrue(listed.json()["running"])
        self.assertEqual([item["key"] for item in listed.json()["items"]], ["video:1", "video:2"])
        self.assertEqual(refused.status_code, 409)
        self.assertIn("不能取消", refused.json()["detail"])
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["withdraw"], ["video:2"])
        self.assertEqual(nothing_left.status_code, 200, "the queued item is still queued until the runner honours the request")

    def test_a_restart_requeues_items_a_dead_run_left_running(self):
        task = _task(1)
        task["assets"][gq.QUEUE_KEY] = {"items": [{"key": "video:1", "label": "x", "status": gq.RUNNING, "meta": {"job_key": "1:0"}}]}
        self.repo.save_task("q5-1", task)
        self.assertEqual(self.service.reconcile_generation_queues(), {"requeued": 1})
        self.assertEqual(self.repo.get_task("q5-1")["assets"][gq.QUEUE_KEY]["items"][0]["status"], gq.QUEUED)


if __name__ == "__main__":
    unittest.main()

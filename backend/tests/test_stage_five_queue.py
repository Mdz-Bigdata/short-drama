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
            # 本文件验证逐镜排队机制；每个分镜片段一段视频见 tests/test_slice_video.py。
            "video_granularity": "shot",
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
        # 作业键是全剧唯一的镜头编号(第1集第1场第1镜 = 100101)，不同场的同号镜头不会撞键。
        self.assertEqual(by_key["video:1"]["meta"]["job_key"], "100101:0")
        self.assertNotIn("frames:1", by_key, "stage 4 left a first frame and no exact end frame was needed")

    def test_a_provider_that_returns_no_clip_fails_the_shot_with_its_reason(self):
        """供应商拒单(如 H3 不接受 1080P)时本镜失败并写明原话，不会存成没有视频的空片。"""
        task = _task(1)
        self.repo.save_task(task["task_id"], task)
        refusal = "MiniMax H3 请求失败: RuntimeError: HTTP 400, model MiniMax-H3 does not support resolution 1080P"
        with patch.object(self.service.gateway, "generate_video", return_value=None), \
             patch.object(self.service.gateway, "last_video_failure", return_value=refusal), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            with self.assertRaisesRegex(RuntimeError, "does not support resolution 1080P"):
                self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        stored = self.repo.get_task(task["task_id"])
        self.assertEqual([c for c in stored["assets"].get("5") or [] if not c.get("video_url")], [], "没有视频的片段不会被存下来")
        failed = [item for item in stored["assets"][gq.QUEUE_KEY]["items"] if item["status"] == gq.FAILED]
        self.assertEqual(len(failed), 1)
        self.assertIn("1080P", failed[0]["error"])

    def test_a_rerun_reuses_clips_without_regenerating_their_end_frames(self):
        """首尾帧模式下每镜要出一张尾帧(付费)；上一轮已出片的镜头复用时不再重出。"""
        task = _task(2)
        task["config"]["video_reference_mode"] = "first_last_frame"
        stored = self._run(task)
        self.assertEqual(sum(1 for item in stored["assets"][gq.QUEUE_KEY]["items"] if item["key"].startswith("frames:")), 2)
        stored["status"] = "running"
        stored["workflow_control"] = {"run_id": "run-2", "active": True, "pause_requested": False}
        self.repo.save_task(stored["task_id"], stored)
        with patch.object(self.service.gateway, "generate_video", side_effect=AssertionError("must reuse")), \
             patch.object(self.service.gateway, "generate_image", side_effect=AssertionError("no end frame on reuse")), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(stored["task_id"], 5, _claimed_task=stored)
        again = self.repo.get_task(stored["task_id"])
        self.assertEqual([clip["video_url"] for clip in again["assets"]["5"]], [clip["video_url"] for clip in stored["assets"]["5"]])
        self.assertEqual([item["key"] for item in again["assets"][gq.QUEUE_KEY]["items"] if item["key"].startswith("frames:")], [])

    def test_a_rerun_makes_again_a_clip_whose_link_has_expired(self):
        """供应商签名链接过期的片段拿不回来了：重跑时不能当复用，要重新生成。"""
        task = _task(2)
        stored = self._run(task)
        expired = "https://bucket.oss-cn-shanghai.aliyuncs.com/out.mp4?Expires=1700000000&Signature=x"
        stored["assets"]["5"][0]["video_url"] = expired
        stored["assets"]["5"][0]["candidates"] = [expired]
        stored["status"] = "running"
        stored["workflow_control"] = {"run_id": "run-2", "active": True, "pause_requested": False}
        self.repo.save_task(stored["task_id"], stored)
        calls: list[str] = []
        with patch.object(self.service.gateway, "generate_video", side_effect=lambda *a, **k: calls.append("v") or "https://cdn/fresh.mp4"), \
             patch.object(self.service.gateway, "generate_image", return_value=("https://cdn/frame.png", {})), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(stored["task_id"], 5, _claimed_task=stored)
        again = self.repo.get_task(stored["task_id"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(again["assets"]["5"][0]["video_url"], "https://cdn/fresh.mp4")
        self.assertEqual(again["assets"]["5"][1]["video_url"], stored["assets"]["5"][1]["video_url"])

    def test_a_clip_sent_back_for_a_retake_is_not_returned_through_its_own_job(self):
        """标了重做的片段：它自己那条已下载的任务记录不能当「重启后找回的片段」原样交回。"""
        from app.core import episode_cycle, video_jobs

        task = _task(1)
        stored = self._run(task)
        clip = stored["assets"]["5"][0]
        rejected = clip["video_url"]
        clip["stale"] = True
        stored["assets"][video_jobs.JOBS_KEY] = {video_jobs.job_key(int(episode_cycle.shot_uid(clip)), 0): {
            "status": video_jobs.DOWNLOADED, "video_url": rejected,
            "checkpoint": {"contract_fingerprint": clip["contract_fingerprint"]},
        }}
        stored["status"] = "running"
        stored["workflow_control"] = {"run_id": "run-2", "active": True, "pause_requested": False}
        self.repo.save_task(stored["task_id"], stored)
        with patch.object(self.service.gateway, "generate_video", return_value="https://cdn/retake.mp4") as video, \
             patch.object(self.service.gateway, "generate_image", return_value=("https://cdn/frame.png", {})), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.media_available", return_value=True), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(stored["task_id"], 5, _claimed_task=stored)
        video.assert_called_once()
        self.assertEqual(self.repo.get_task(stored["task_id"])["assets"]["5"][0]["video_url"], "https://cdn/retake.mp4")

    def test_a_rerun_reuses_the_saved_copy_when_only_the_provider_link_expired(self):
        """供应商候选链接过期但片段已存到本机：用本机副本复用，不再付费重出。"""
        task = _task(1)
        stored = self._run(task)
        expired = "https://bucket.oss-cn-shanghai.aliyuncs.com/out.mp4?Expires=1700000000&Signature=x"
        stored["assets"]["5"][0]["candidates"] = [expired]
        saved = stored["assets"]["5"][0]["video_url"]
        stored["status"] = "running"
        stored["workflow_control"] = {"run_id": "run-2", "active": True, "pause_requested": False}
        self.repo.save_task(stored["task_id"], stored)
        available = lambda url: url != expired   # noqa: E731 - 本机副本在盘，只有供应商链接过期
        with patch.object(self.service.gateway, "generate_video", side_effect=AssertionError("must reuse the saved copy")), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.media_available", side_effect=available), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(stored["task_id"], 5, _claimed_task=stored)
        self.assertEqual(self.repo.get_task(stored["task_id"])["assets"]["5"][0]["video_url"], saved)

    def test_a_board_whose_frame_is_judged_sensitive_is_retried_without_the_frames(self):
        """H3 1026「input image sensitive」：去掉分镜帧、只带身份与场地参考再试一次，并记在片上。"""
        task = _task(1)
        task["assets"]["3_characters"] = [{"name": "沈砚", "views": [{"view": "front", "image_url": "/media/character_views/x/03_front.png"}]}]
        self.repo.save_task(task["task_id"], task)
        calls = []

        def generate_video(model, image_url, prompt, *args, **kwargs):
            calls.append({"first": image_url, "refs": list(kwargs.get("ref_images") or [])})
            return None if len(calls) == 1 else "https://cdn/fallback.mp4"

        with patch.object(self.service.gateway, "generate_video", side_effect=generate_video), \
             patch.object(self.service.gateway, "last_video_failure", return_value="MiniMax H3 task ended with status=failed: 1026 input new_sensitive, input image sensitive"), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        stored = self.repo.get_task(task["task_id"])
        [clip] = stored["assets"]["5"]
        self.assertEqual(clip["video_url"], "https://cdn/fallback.mp4")
        self.assertEqual(clip["moderation_fallback"]["dropped"], "storyboard_frames")
        self.assertIn("1026", clip["moderation_fallback"]["reason"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0]["first"] or calls[0]["refs"])
        self.assertIsNone(calls[1]["first"])
        self.assertNotIn("/media/p1.png", "".join(calls[1]["refs"]))

    def test_identity_references_prefer_local_views_over_expiring_sheet_links(self):
        from app.service.drama_service import actor_identity_urls
        task = {"assets": {
            "3_sheets": {"沈砚": "https://ark.example/sheet.jpeg?X-Tos-Expires=86400", "老仆": "https://ark.example/old.jpeg"},
            "3_characters": [{"name": "沈砚", "views": [{"view": "front", "image_url": "http://localhost:8000/media/character_views/a/03_front.png"}]}],
        }}
        with patch("app.service.drama_service.media_compositor.local_media_path", side_effect=lambda url: "/x" if "localhost:8000/media" in str(url) else None):
            urls = actor_identity_urls(task)
        self.assertEqual(urls["沈砚"], "http://localhost:8000/media/character_views/a/03_front.png")
        self.assertEqual(urls["老仆"], "https://ark.example/old.jpeg")

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

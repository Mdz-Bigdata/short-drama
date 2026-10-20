"""Accepted provider jobs are remembered, continued after a restart, and never paid for twice."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import video_jobs
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.written: list[tuple[str, dict]] = []
        video_jobs.configure_sink(lambda task_id, entry: self.written.append((task_id, dict(entry))))
        self.addCleanup(video_jobs.configure_sink, None)

    def test_a_job_is_recorded_when_accepted_then_updated_when_it_ends(self):
        with video_jobs.bind_shot("task-1", 7, candidate=0, checkpoint={"contract_fingerprint": "abc", "seconds": 8}):
            video_jobs.note_submitted("seedance", "ark-123", model="doubao-seedance", endpoint="https://ark.example/api/v3")
            video_jobs.note_finished("ark-123", "https://cdn/7.mp4")

        self.assertEqual([task_id for task_id, _ in self.written], ["task-1", "task-1"])
        submitted, finished = (entry for _, entry in self.written)
        self.assertEqual((submitted["key"], submitted["status"], submitted["family"], submitted["job_id"]), ("7:0", "submitted", "seedance", "ark-123"))
        self.assertEqual(submitted["checkpoint"], {"contract_fingerprint": "abc", "seconds": 8})
        self.assertEqual((finished["key"], finished["status"], finished["video_url"]), ("7:0", "downloaded", "https://cdn/7.mp4"))

    def test_notes_outside_a_bound_shot_are_dropped(self):
        video_jobs.note_submitted("seedance", "ark-1", model="m")
        self.assertEqual(self.written, [])

    def test_the_task_keeps_one_entry_per_shot_candidate_and_ignores_a_foreign_job_id(self):
        task = {"assets": {}}
        video_jobs.apply_to_task(task, {"key": "7:0", "shot_id": 7, "candidate": 0, "family": "seedance", "job_id": "a", "status": "submitted", "checkpoint": {}})
        video_jobs.apply_to_task(task, {"key": "7:0", "job_id": "b", "status": "downloaded", "video_url": "x"})
        self.assertEqual(task["assets"]["5_jobs"]["7:0"]["status"], "submitted")
        video_jobs.apply_to_task(task, {"key": "7:0", "job_id": "a", "status": "downloaded", "video_url": "https://cdn/a.mp4"})
        self.assertEqual(task["assets"]["5_jobs"]["7:0"]["video_url"], "https://cdn/a.mp4")
        self.assertEqual(video_jobs.pending_jobs(task), [])

    def test_a_resumed_clip_is_offered_only_for_the_same_request(self):
        task = {"assets": {"5_jobs": {"7:0": {"status": "downloaded", "video_url": "https://cdn/a.mp4", "checkpoint": {"contract_fingerprint": "abc"}}}}}
        self.assertEqual(video_jobs.downloaded_clip(task, 7, candidate=0, fingerprint="abc"), "https://cdn/a.mp4")
        self.assertIsNone(video_jobs.downloaded_clip(task, 7, candidate=0, fingerprint="changed"))
        self.assertIsNone(video_jobs.downloaded_clip(task, 7, candidate=1, fingerprint="abc"))

    def test_resume_asks_the_provider_once_and_records_what_it_said(self):
        job = {"key": "7:0", "job_id": "ark-123", "family": "seedance"}
        self.assertEqual(video_jobs.resume_outcome(job, lambda _: "https://cdn/a.mp4")["status"], "downloaded")
        self.assertEqual(video_jobs.resume_outcome(job, lambda _: None)["error"], "resume_expired_or_failed")

        def boom(_):
            raise RuntimeError("401 unauthorized")

        self.assertIn("resume_failed:RuntimeError", video_jobs.resume_outcome(job, boom)["error"])
        unsupported = video_jobs.resume_outcome({**job, "family": "agnes"}, lambda _: "never")
        self.assertEqual(unsupported["error"], "resume_unsupported_provider:agnes")


class RestartRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        self.repo.save_task("r-1", {
            "task_id": "r-1", "status": "interrupted", "config": {}, "assets": {"5_jobs": {
                "1:0": {"key": "1:0", "shot_id": 1, "candidate": 0, "family": "seedance", "job_id": "ark-1", "status": "submitted", "checkpoint": {"contract_fingerprint": "f1"}},
                "2:0": {"key": "2:0", "shot_id": 2, "candidate": 0, "family": "minimax_h3", "job_id": "h3-2", "status": "submitted", "checkpoint": {"contract_fingerprint": "f2"}},
                "3:0": {"key": "3:0", "shot_id": 3, "candidate": 0, "family": "seedance", "job_id": "ark-3", "status": "downloaded", "video_url": "https://cdn/3.mp4"},
            }},
        })

    def test_every_accepted_job_is_polled_to_its_end_and_none_is_resubmitted(self):
        asked: list[str] = []

        def resume(job):
            asked.append(str(job["job_id"]))
            return "https://cdn/1.mp4" if job["job_id"] == "ark-1" else None

        with patch.object(self.service.gateway, "resume_video_job", side_effect=resume), \
             patch.object(self.service.gateway, "generate_video") as submit:
            outcome = self.service.resume_interrupted_video_jobs()

        submit.assert_not_called()
        self.assertEqual(sorted(asked), ["ark-1", "h3-2"])
        self.assertEqual(outcome, {"downloaded": 1, "failed": 1})
        jobs = self.repo.get_task("r-1")["assets"]["5_jobs"]
        self.assertEqual((jobs["1:0"]["status"], jobs["1:0"]["video_url"]), ("downloaded", "https://cdn/1.mp4"))
        self.assertEqual((jobs["2:0"]["status"], jobs["2:0"]["error"]), ("failed", "resume_expired_or_failed"))
        self.assertEqual(jobs["3:0"]["status"], "downloaded")
        self.assertEqual(video_jobs.pending_jobs(self.repo.get_task("r-1")), [])


if __name__ == "__main__":
    unittest.main()


class ShotRegenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        self.repo.save_task("g-1", {
            "task_id": "g-1", "status": "idle", "config": {"video_model": "seedance2.0"},
            "assets": {
                "4": [{"shot_id": 1, "scene_id": "E1S01", "desc": "a"}, {"shot_id": 2, "scene_id": "E1S01", "desc": "b"}],
                "5": [
                    {"shot_id": 1, "video_url": "https://cdn/1.mp4", "contract_fingerprint": "f1", "motion_prompt": "p", "duration": 6},
                    {"shot_id": 2, "video_url": "https://cdn/2.mp4", "contract_fingerprint": "f2", "motion_prompt": "p", "duration": 6},
                ],
                "5_jobs": {"1:0": {"key": "1:0", "status": "downloaded", "video_url": "https://cdn/1.mp4", "checkpoint": {"contract_fingerprint": "f1"}}},
            },
        })

    def test_one_shot_is_marked_for_regeneration_and_its_job_forgotten(self):
        with patch.object(self.service, "get_shot_visual_workspace", return_value={"ok": True}):
            self.assertEqual(self.service.regenerate_shot("g-1", 1, reason="人物面部崩坏"), {"ok": True})

        stored = self.repo.get_task("g-1")
        first, second = stored["assets"]["5"]
        self.assertTrue(first["stale"])
        self.assertIn("人物面部崩坏", first["stale_reason"])
        self.assertNotIn("stale", second)
        self.assertEqual(stored["assets"]["5_jobs"], {})

    def test_a_shot_without_a_clip_or_a_running_stage_is_refused(self):
        with self.assertRaisesRegex(ValueError, "尚未生成"):
            self.service.regenerate_shot("g-1", 9)
        task = self.repo.get_task("g-1")
        task["status"] = "running"
        task["stage_progress"] = {"stage": 5, "status": "running"}
        self.repo.save_task("g-1", task)
        with self.assertRaisesRegex(ValueError, "正在运行"):
            self.service.regenerate_shot("g-1", 1)

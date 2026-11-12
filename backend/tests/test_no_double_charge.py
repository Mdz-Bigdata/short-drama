# -*- coding: utf-8 -*-
"""视频任务不付两次钱：提交结果不明不自动重发；等超时的任务留着任务号，下次开拍前按号取回，不重新提交。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

from app.core import video_jobs
from app.core.model_gateway import ModelGateway, _ark_notes


class MaybeAcceptedTests(unittest.TestCase):
    def test_only_failures_before_sending_are_safe_to_retry(self):
        self.assertTrue(video_jobs.maybe_accepted(requests.exceptions.ReadTimeout("read timed out")))
        self.assertTrue(video_jobs.maybe_accepted(requests.exceptions.ChunkedEncodingError("cut")))
        self.assertTrue(video_jobs.maybe_accepted(requests.exceptions.ConnectionError("('Connection aborted.', RemoteDisconnected())")))
        self.assertFalse(video_jobs.maybe_accepted(requests.exceptions.ConnectTimeout("connect timed out")))
        self.assertFalse(video_jobs.maybe_accepted(requests.exceptions.SSLError("handshake failed")))
        self.assertFalse(video_jobs.maybe_accepted(requests.exceptions.ConnectionError("Failed to establish a new connection")))


class SeedanceSubmitTests(unittest.TestCase):
    def setUp(self):
        self.gateway = ModelGateway()
        self.written: list[dict] = []
        video_jobs.configure_sink(lambda _task, entry: self.written.append(dict(entry)))
        self.addCleanup(video_jobs.configure_sink, None)

    def _video(self):
        with video_jobs.bind_shot("task-1", 3, candidate=0, checkpoint={}), \
             patch.object(self.gateway, "_is_host_broken", return_value=False), \
             patch("time.sleep"):
            return self.gateway._ark_video("key", "https://ark.example/api/v3", "沈砚推门", first_frame="https://cdn/f.png")

    def test_a_read_timeout_on_submit_is_not_sent_again(self):
        with patch("requests.post", side_effect=requests.exceptions.ReadTimeout("read timed out")) as post:
            self.assertIsNone(self._video())
        self.assertEqual(post.call_count, 1, "the first request may already be a paid job")
        self.assertIn("没有自动重发", _ark_notes.last)

    def test_a_connect_timeout_is_still_retried(self):
        with patch("requests.post", side_effect=requests.exceptions.ConnectTimeout("connect timed out")) as post:
            self.assertIsNone(self._video())
        self.assertEqual(post.call_count, 2)

    def test_a_job_that_outlasts_the_wait_stays_submitted(self):
        accepted = SimpleNamespace(status_code=200, json=lambda: {"id": "ark-9"})

        def wait(*_args, **_kwargs):
            _ark_notes.wait_timed_out = True
            return None

        with patch("requests.post", return_value=accepted), patch.object(self.gateway, "_ark_wait", side_effect=wait):
            self.assertIsNone(self._video())
        self.assertEqual([entry["status"] for entry in self.written], ["submitted"], "not marked failed: it is fetched by id next time")
        self.assertIn("按任务号接着取", _ark_notes.last)


class CollectBeforeShootingTests(unittest.TestCase):
    def test_pending_jobs_are_fetched_by_id_before_stage_five_submits_anything(self):
        from app.service.drama_service import DramaService

        service = DramaService.__new__(DramaService)
        service.gateway = SimpleNamespace(resume_video_job=lambda job: "https://cdn/3.mp4")
        service.repo = SimpleNamespace(mutate_task=lambda _task_id, change: None)
        task = {"task_id": "", "assets": {video_jobs.JOBS_KEY: {"3:0": {
            "key": "3:0", "status": video_jobs.SUBMITTED, "family": "seedance", "job_id": "ark-9", "checkpoint": {"contract_fingerprint": "fp"},
        }}}}
        self.assertEqual(service._collect_pending_video_jobs(task), 1)
        self.assertEqual(video_jobs.downloaded_clip(task, 3, candidate=0, fingerprint="fp"), "https://cdn/3.mp4")


if __name__ == "__main__":
    unittest.main()

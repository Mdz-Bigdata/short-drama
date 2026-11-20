# -*- coding: utf-8 -*-
"""The handoff check between neighbouring clips, on real clips made with ffmpeg (motion known in advance)."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import auth_service, get_current_user
from app.core import clip_handoff, media_compositor
from app.core.clip_handoff import Planned
from app.repository.task_repo import TaskRepository
from app.service import clip_handoff_service
from app.service.drama_service import DramaService
from main import app

FFMPEG = media_compositor._ffmpeg()


def _make(folder: Path, name: str, seconds: float, x: str, tail: str = "", held: float = 0.0, grain: int = 6) -> str:
    """A white square on a noisy grey ground; ``x`` is its position over time (an ffmpeg expression)."""
    path = folder / f"{name}.mp4"
    subprocess.run([
        FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=0x202020:s=640x360:d={seconds},noise=alls={grain}:allf=t+u",
        "-f", "lavfi", "-i", f"color=white:s=80x80:d={seconds}",
        "-filter_complex", f"[0:v][1:v]overlay=x='{x}':y=140{tail}", "-t", str(seconds + held), "-pix_fmt", "yuv420p", "-r", "24", str(path),
    ], check=True, capture_output=True, timeout=60)
    return str(path)


def _pan(folder: Path, name: str, x: str) -> str:
    path = folder / f"{name}.mp4"
    subprocess.run([
        FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x360:d=3", "-vf", f"crop=640:360:x='{x}':y=0",
        "-t", "3", "-pix_fmt", "yuv420p", "-r", "24", str(path),
    ], check=True, capture_output=True, timeout=60)
    return str(path)


@unittest.skipUnless(FFMPEG and shutil.which(FFMPEG) or (FFMPEG and Path(FFMPEG).exists()), "ffmpeg is needed to make the clips")
class HandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        cls.clips = {
            "right": _make(folder, "right", 3, "t*180"),
            "left": _make(folder, "left", 3, "560-t*180"),
            "exit_right": _make(folder, "exit_right", 2, "300+t*190"),
            "enter_left": _make(folder, "enter_left", 2, "-80+t*190"),
            "enter_right": _make(folder, "enter_right", 2, "640-t*190"),
            "still": _make(folder, "still", 3, "280", grain=30),
            "frozen": _make(folder, "frozen", 2, "t*180", ",tpad=stop_mode=clone:stop_duration=1.2", held=1.2),
            "pan_right": _pan(folder, "pan_right", "t*200"),
            "pan_left": _pan(folder, "pan_left", "600-t*200"),
        }

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check(self, before, after, **plan):
        return clip_handoff.compare(clip_handoff.measure(self.clips[before], "tail"), clip_handoff.measure(self.clips[after], "head"), Planned(**plan))

    def codes(self, report):
        return [item["code"] for item in report.findings]

    def test_a_subject_is_read_by_its_own_movement_and_a_pan_by_the_background(self):
        right, left = clip_handoff.measure(self.clips["right"], "tail"), clip_handoff.measure(self.clips["left"], "head")
        self.assertEqual((right.heading, right.pan), ("right", ""), "a square crossing a plain ground is not a pan")
        self.assertEqual((left.heading, left.pan), ("left", ""))
        pan = clip_handoff.measure(self.clips["pan_right"], "tail")
        self.assertEqual((pan.heading, pan.pan), ("right", "right"), "the background flowing left is the camera moving right")
        self.assertTrue(clip_handoff.measure(self.clips["still"], "tail").still)
        self.assertGreaterEqual(clip_handoff.measure(self.clips["frozen"], "tail").frozen_seconds, 0.5)

    def test_motion_direction_is_continuous_or_flagged(self):
        self.assertEqual(self.check("right", "right", motion_join="moving_to_moving").verdict, "good")
        flipped = self.check("right", "left", motion_join="moving_to_moving")
        self.assertIn("direction", self.codes(flipped))
        self.assertIn("向右", flipped.findings[0]["text"])
        self.assertEqual(self.check("right", "left", turns=True).verdict, "good", "a written turn explains it")
        self.assertEqual(self.check("right", "left", same_scene=False).verdict, "good", "another scene sets its own axis")
        self.assertIn("pan", self.codes(self.check("pan_right", "pan_left", shared_subject=False)))

    def test_the_ending_must_suit_the_planned_way_into_the_next_shot(self):
        frozen = self.check("frozen", "right", motion_join="moving_to_moving")
        self.assertEqual(self.codes(frozen)[:2], ["frozen", "wants_motion"])
        self.assertIn("wants_settle", self.codes(self.check("pan_right", "still", motion_join="moving_to_static")), "the camera is still moving")
        self.assertEqual(self.check("right", "still", motion_join="moving_to_static").verdict, "good", "an actor moving in a locked frame has settled")
        self.assertIn("wants_settle", self.codes(self.check("pan_right", "pan_right", optical=True)), "a dissolve needs a settled picture")
        self.assertEqual(self.check("still", "still", motion_join="static_to_static").verdict, "good")
        self.assertEqual(self.check("frozen", "still", motion_join="moving_to_static").verdict, "good", "a hold into a still shot is the settle")
        self.assertIn("head_still", self.codes(self.check("right", "still", motion_join="moving_to_moving")))

    def test_a_still_ending_or_opening_the_storyboard_asked_for_is_not_a_slip(self):
        self.assertEqual(self.check("still", "right", motion_join="moving_to_moving", ends_settled=True).verdict, "good")
        self.assertEqual(self.check("right", "still", motion_join="moving_to_moving", opens_held=True).verdict, "good")
        self.assertEqual(self.check("still", "still", motion_join="moving_to_moving", same_scene=False).verdict, "good", "a cut to another scene does not carry the move")
        plan = clip_handoff.planned_from(
            {"scene_id": "E1S01", "motion": "缓慢推进，推至近景停稳后不再动"},
            {"scene_id": "E1S01", "motion": "固定起幅三秒后横移", "cut_in": {"motion_join": "moving_to_moving", "kind": "dissolve"}},
        )
        self.assertEqual((plan.ends_settled, plan.opens_held, plan.optical), (True, True, True))

    def test_who_leaves_on_the_right_comes_back_in_on_the_left(self):
        good = self.check("exit_right", "enter_left", motion_join="moving_to_moving")
        self.assertEqual(good.verdict, "good", good.findings)
        self.assertIn("右侧出画", good.tail)
        self.assertIn("左侧入画", good.head)
        wrong = self.check("exit_right", "enter_right", motion_join="moving_to_moving")
        self.assertIn("exit_entry", self.codes(wrong))
        self.assertNotIn("exit_entry", self.codes(self.check("exit_right", "enter_right", turns=True)))

    def test_a_missing_file_is_unknown_not_good(self):
        report = clip_handoff.compare(clip_handoff.measure("/nowhere.mp4", "tail"), clip_handoff.measure(self.clips["right"], "head"))
        self.assertEqual(report.verdict, "unknown")

    def test_the_storyboard_says_what_the_cut_plans(self):
        plan = clip_handoff.planned_from(
            {"scene_id": "E1S01", "characters": ["林夏"], "desc": "林夏向右跑"},
            {"scene_id": "E1S01", "characters": ["林夏", "周教授"], "desc": "林夏转身", "cut_in": {"motion_join": "moving_to_moving"}},
        )
        self.assertEqual((plan.same_scene, plan.shared_subject, plan.motion_join, plan.turns), (True, True, "moving_to_moving", True))
        other = clip_handoff.planned_from({"scene_id": "E1S01", "characters": ["甲"]}, {"scene_id": "E1S02", "characters": ["乙"]})
        self.assertEqual((other.same_scene, other.shared_subject, other.turns), (False, False, False))

    def test_an_episode_report_walks_the_cuts_in_order_and_measures_each_clip_once(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repo = TaskRepository(str(Path(temp.name) / "tasks.json"))
        shots = [
            {"scene_id": "E1S01", "shot_id": 1, "shot_uid": 101101, "characters": ["林夏"], "desc": "林夏向右跑"},
            {"scene_id": "E1S01", "shot_id": 2, "shot_uid": 101102, "characters": ["林夏"], "desc": "林夏继续跑", "cut_in": {"motion_join": "moving_to_moving"}},
            {"scene_id": "E1S01", "shot_id": 3, "shot_uid": 101103, "characters": ["林夏"], "desc": "林夏停下", "cut_in": {"motion_join": "moving_to_static"}},
        ]
        clips = [
            {"scene_id": "E1S01", "shot_id": 1, "shot_uid": 101101, "video_url": "/media/a.mp4"},
            {"scene_id": "E1S01", "shot_id": 2, "shot_uid": 101102, "video_url": "/media/b.mp4"},
            {"scene_id": "E1S01", "shot_id": 3, "shot_uid": 101103, "video_url": "/media/c.mp4"},
        ]
        repo.save_task("h-1", {"task_id": "h-1", "owner_user_id": "u1", "config": {}, "assets": {"4": shots, "5": clips}})
        service = DramaService.__new__(DramaService)
        service.repo = repo
        files = {"/media/a.mp4": self.clips["exit_right"], "/media/b.mp4": self.clips["enter_right"], "/media/c.mp4": self.clips["still"]}
        with patch.object(media_compositor, "local_media_path", side_effect=lambda url: files.get(url)):
            report = clip_handoff_service.episode_report(service, "h-1", 1)
            with patch.object(clip_handoff, "measure", side_effect=AssertionError("measured again")):
                again = clip_handoff_service.episode_report(service, "h-1", 1)
        self.assertEqual([(pair["from"]["shot_id"], pair["to"]["shot_id"]) for pair in report["pairs"]], [(1, 2), (2, 3)])
        self.assertIn("exit_entry", [item["code"] for item in report["pairs"][0]["findings"]])
        self.assertEqual(report["pairs"][1]["verdict"], "good", "the subject still moves, but the frame is locked: settled")
        self.assertEqual(report["suspect"], 1)
        self.assertEqual(again["pairs"], report["pairs"], "the second look reads the cache")
        self.assertEqual(set(repo.get_task("h-1")["assets"][clip_handoff_service.CACHE_KEY]), set(files))

        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        self.addCleanup(app.dependency_overrides.pop, get_current_user, None)
        client = TestClient(app, cookies={"auth_token": auth_service.generate_token("u1")})
        self.addCleanup(client.close)
        with patch.object(drama_api, "service", service), patch.object(media_compositor, "local_media_path", side_effect=lambda url: files.get(url)):
            response = client.get("/api/drama/h-1/episodes/1/handoff")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["suspect"], 1)


if __name__ == "__main__":
    unittest.main()

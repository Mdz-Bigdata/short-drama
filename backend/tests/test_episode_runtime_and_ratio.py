import inspect
import os
import unittest
from unittest import mock

from app.core import episode_runtime, system_diagnostics as diagnostics
from app.service import drama_service


def shots(*pairs):
    return [{"scene_id": scene, "duration": f"{seconds}s"} for scene, seconds in pairs]


class EpisodeRuntimeTest(unittest.TestCase):
    def test_only_the_episodes_own_shots_are_counted(self):
        table = shots(("E1S01", 10), ("E1S02", "8"), ("E2S01", 30), ("bad", 9))
        table[1]["duration"] = "8秒"
        self.assertEqual(episode_runtime.planned_seconds(table, 1), 18)
        self.assertEqual(episode_runtime.planned_seconds(table, 2), 30)

    def test_within_the_tolerance_it_says_so(self):
        line = episode_runtime.report_line(shots(("E1S01", 60), ("E1S02", 64)), {"episode_target_duration": 120}, 1)
        self.assertIn("第1集分镜合计 124 秒，剧本目标 120 秒（+3%）", line)
        self.assertIn("±15%", line)

    def test_outside_it_says_by_how_much_and_what_to_do(self):
        long = episode_runtime.report_line(shots(("E2S01", 100), ("E2S02", 78)), {}, 2)
        self.assertIn("剧本目标 90 秒，长了 98%", long)
        self.assertIn("重拆那几场的分镜", long)
        short = episode_runtime.report_line(shots(("E1S01", 60)), {"episode_target_duration": 90}, 1)
        self.assertIn("短了 33%", short)

    def test_nothing_to_compare_gives_no_line(self):
        self.assertEqual(episode_runtime.report_line([], {"episode_target_duration": 90}, 1), "")
        self.assertEqual(episode_runtime.report_line(shots(("E1S01", 10)), {"episode_target_duration": 90}, 3), "")

    def test_stage_four_puts_it_in_its_report(self):
        source = inspect.getsource(drama_service.DramaService._execute_stage_blocking)
        self.assertIn("runtime_line = episode_runtime.report_line(", source)
        self.assertIn('task["logs"]["4"] = f"{task[\'logs\'][\'4\']}\\n\\n{runtime_line}"', source)


class AspectRatioCheckTest(unittest.TestCase):
    def _check(self, **env):
        clean = {name: "" for name in ("SEEDANCE_IMAGE_SIZE", "VIDEO_ASPECT_RATIO", "MINIMAX_H3_ASPECT_RATIO")}
        with mock.patch.dict(os.environ, {**clean, **env}):
            return {item.id: item for item in diagnostics.local_checks()}["aspect_ratio"]

    def test_the_defaults_agree_on_nine_by_sixteen(self):
        found = self._check()
        self.assertEqual(found.status, "ok")
        self.assertIn("9:16", found.detail)

    def test_a_landscape_picture_with_portrait_video_is_named(self):
        found = self._check(SEEDANCE_IMAGE_SIZE="2560x1440")
        self.assertEqual(found.status, "warning")
        self.assertIn("16:9", found.detail)
        self.assertIn("VIDEO_ASPECT_RATIO=9:16", found.detail)

    def test_all_landscape_is_fine_and_a_square_frame_is_not(self):
        self.assertEqual(self._check(SEEDANCE_IMAGE_SIZE="2560x1440", VIDEO_ASPECT_RATIO="16:9", MINIMAX_H3_ASPECT_RATIO="16:9").status, "ok")
        square = self._check(SEEDANCE_IMAGE_SIZE="2048x2048", VIDEO_ASPECT_RATIO="1:1", MINIMAX_H3_ASPECT_RATIO="1:1")
        self.assertEqual(square.status, "warning")
        self.assertIn("9:16 或 16:9", square.detail)
        self.assertEqual(self._check(SEEDANCE_IMAGE_SIZE="big").status, "warning")


if __name__ == "__main__":
    unittest.main()

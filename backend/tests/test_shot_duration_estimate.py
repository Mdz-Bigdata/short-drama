"""Shots parsed from a free-text script get a duration the project's video model can render."""

import unittest

from app.core.screenwriting.durations import supported_shot_durations
from app.core.writer_dashboard import compile_writer_dashboard, estimated_shot_seconds, spoken_text

ROW = (
    "金銮殿 晨 内景 镜头：特写 缓推 小满从龙椅下抽出一张泛黄戏票，双手托起。沈昭接过，捏在掌心。 "
    "沈昭：[沈昭][释然-克制][慢速][一字一顿] 戏唱完了。票，我不留。"
)


class EstimateTests(unittest.TestCase):
    def test_spoken_words_are_read_without_names_or_cues(self):
        self.assertEqual(spoken_text(ROW), "戏唱完了。票，我不留。")
        self.assertEqual(spoken_text("镜头：特写 缓推"), "")
        self.assertEqual(spoken_text("她低声说：“走吧，天要亮了。”"), "走吧，天要亮了。")

    def test_durations_are_lengths_the_video_model_renders(self):
        supported = supported_shot_durations("seedance2.0")
        short = estimated_shot_seconds(ROW, "seedance2.0", "zh")
        self.assertIn(short, supported)
        self.assertEqual(short, min(supported), "a short line plus a breath fits the shortest clip")
        self.assertEqual(estimated_shot_seconds("镜头：远景 雨夜长街，空无一人。", "seedance2.0", "zh"), min(supported))
        speech = "沈昭：" + "我" * 40  # 40 characters ≈ 8 s at 5 per second, plus a breath
        self.assertEqual(estimated_shot_seconds(speech, "seedance2.0", "zh"), 9)
        endless = "沈昭：" + "我" * 400
        self.assertEqual(estimated_shot_seconds(endless, "seedance2.0", "zh"), max(supported))
        # Another model, another set of lengths: the estimate follows the model.
        longer = supported_shot_durations("seedance2.5")
        self.assertEqual(estimated_shot_seconds(endless, "seedance2.5", "zh"), max(longer))


class PreferredRangeTests(unittest.TestCase):
    def test_each_model_plans_within_its_preferred_range(self):
        from app.core.screenwriting.durations import renderable_shot_durations

        for model, low, high in (
            ("seedance2.5", 10, 30), ("doubao-seedance-2-5-pro", 10, 30),
            ("seedance2.0", 5, 15), ("MiniMax-H3", 5, 15), ("hailuo-02", 5, 15),
        ):
            with self.subTest(model=model):
                planned = supported_shot_durations(model)
                self.assertEqual((planned[0], planned[-1]), (low, high))
                # Planning never asks for more than the model can render in one call.
                self.assertLessEqual(planned[-1], renderable_shot_durations(model)[-1])
        # An unlisted model keeps everything it can render.
        self.assertEqual(supported_shot_durations("kling-v2"), renderable_shot_durations("kling-v2"))

    def test_estimates_start_at_each_models_preferred_floor(self):
        quiet = "镜头：特写 静 箱内静静躺着一顶傀儡戏帽。没有人头。"
        self.assertEqual(estimated_shot_seconds(quiet, "MiniMax-H3", "zh"), 5)
        self.assertEqual(estimated_shot_seconds(quiet, "seedance2.0", "zh"), 5)
        self.assertEqual(estimated_shot_seconds(quiet, "seedance2.5", "zh"), 10)

    def test_a_shot_the_model_can_render_is_still_admitted_below_the_preferred_floor(self):
        from app.core.video_admission import request_tier
        from app.core.screenwriting.durations import renderable_shot_durations

        self.assertEqual(request_tier(4, renderable_shot_durations("seedance2.0")), (4, "exact"))


class DashboardTests(unittest.TestCase):
    def test_a_legacy_script_shows_estimated_durations_and_no_table_rows(self):
        script = (
            "第6集 终局\n场景1：金銮殿 晨 内景\n" + ROW + "\n"
            "【双轨节奏与每集时长预估】\n| 段落 | 情节节奏 | 时长 |\n|---|---|---|\n| 天牢真相 | 紧 | 45秒 |\n"
        )
        task = {"task_id": "d", "config": {"video_model": "seedance2.0", "content_language": "zh", "episode_count": 6},
                "assets": {"2": script}, "episodes": []}
        scenes = compile_writer_dashboard(task).scenes
        self.assertTrue(scenes)
        for scene in scenes:
            self.assertGreater(scene.duration_seconds, 0)
            self.assertIn("按视频模型估算", scene.duration_label)
            self.assertTrue(scene.duration_estimated)
            self.assertNotIn("| 段落 |", scene.content)

    def test_a_planned_duration_is_kept(self):
        task = {"task_id": "d", "config": {"video_model": "seedance2.0"}, "episodes": [],
                "assets": {"2": "第1集\n场景1：街\n林夏：走。", "2_breakdown": {"scenes": [
                    {"scene_id": "E1S01", "duration": "7秒", "content": "林夏：走。", "characters": ["林夏"]},
                ]}}}
        scene = compile_writer_dashboard(task).scenes[0]
        self.assertEqual((scene.duration_seconds, scene.duration_label, scene.duration_estimated), (7, "7秒", False))


if __name__ == "__main__":
    unittest.main()

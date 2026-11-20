# -*- coding: utf-8 -*-
"""打戏：按小节给武打指南、按戏挑骨架、多人同场的编排、动接动、打戏片段抽帧核对。"""

import inspect
import json
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.core import exchange_units, fight_clip_check, fight_design, fight_scene, prompt_data, slice_video
from app.service.drama_service import DramaService
from tests import test_stage_five_queue as queue_tests


class MartialGuideTests(unittest.TestCase):
    def test_the_power_and_flow_sections_go_in_not_the_head_of_the_file(self):
        guide = fight_scene.martial_guide()
        self.assertLessEqual(len(guide), prompt_data.number("fight_scene", "martial_budget"))
        for anchor in ("动作力学拆解", "动能运镜语言", "剪辑避坑", "五镜动作链"):
            self.assertIn(anchor, guide)
        self.assertNotIn("实战模板", guide.splitlines()[0])
        # 冲锋那一镜把距离收到够得着，出招才打得到人
        self.assertIn("一臂(拳脚)或一刃(兵器)之内", guide)
        self.assertIn("冲击帧", guide, "the last section still fits")


class SkeletonTests(unittest.TestCase):
    def test_the_matching_skeleton_is_picked_and_caps_are_not_limits(self):
        crowd = fight_scene.skeleton_for("十几个黑衣人一拥而上，将林夏围攻在巷子中央")
        self.assertIn("群战", crowd)
        self.assertIn(prompt_data.text("fight_scene", "skeleton_lead"), crowd)
        self.assertIn("追逐", fight_scene.skeleton_for("他一路追赶，翻过围墙"))
        self.assertEqual(fight_scene.skeleton_for("两人在擂台上过招，一拳一脚"), "")


class MultiFighterTests(unittest.TestCase):
    def test_three_or_more_fighters_get_staging_without_a_one_exchange_cap(self):
        brief = fight_scene.multi_fighter_brief(4)
        self.assertIn("4", brief)
        self.assertIn("MP", brief, "the multi-fighter mode table comes along")
        self.assertNotIn("只写一个主交锋", brief)
        self.assertEqual(fight_scene.multi_fighter_brief(2), "")

    def test_exchange_units_no_longer_cap_to_one_exchange(self):
        # 措辞已从代码移到 app/data/prompt/exchange_units.json：代码和数据一起看。
        from app.core import prompt_data

        source = inspect.getsource(exchange_units) + json.dumps(prompt_data.load("exchange_units"), ensure_ascii=False)
        self.assertNotIn("只写一个主交锋", source)
        self.assertIn("每一对都写清谁接谁的哪一招", source)


class DetectionTests(unittest.TestCase):
    def test_a_fight_written_as_blows_counts_without_the_word_fight(self):
        scene = "林夏侧身闪开，反手一掌拍在他胸口；他抡起铁棍砸向她，她架住，一脚踹在他膝弯。"
        self.assertTrue(fight_design.looks_like_fight(scene))
        self.assertFalse(fight_design.looks_like_fight("他一脚踹开房门，屋里空无一人。"))
        self.assertFalse(fight_design.looks_like_fight("两人隔着桌子对峙，谁也没有开口。"))


class FlowTests(unittest.TestCase):
    def test_fight_clips_join_motion_to_motion(self):
        self.assertIn("动接动", slice_video.FIGHT_STRUCTURE)
        self.assertNotIn("硬切", slice_video.FIGHT_STRUCTURE)
        self.assertIn("动接动", slice_video.FIGHT_JOIN)
        self.assertNotIn("硬切", slice_video.FIGHT_JOIN)


def _frames(moving: bool) -> list[Image.Image]:
    frames = []
    for index in range(6):
        frame = Image.new("RGB", (160, 120), (40, 40, 40))
        x = 10 + (index * 22 if moving else 0)
        ImageDraw.Draw(frame).rectangle((x, 30, x + 40, 100), fill=(230, 230, 230))
        frames.append(frame)
    return frames


class ClipCheckTests(unittest.TestCase):
    def test_a_still_clip_fails_without_asking_a_model(self):
        describe = unittest.mock.Mock()
        with patch.object(fight_clip_check, "sample_frames", return_value=_frames(False)):
            verdict = fight_clip_check.check("clip.mp4", "甲一拳打向乙", describe)
        describe.assert_not_called()
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["problems"], [prompt_data.text("fight_scene", "clip_still_problem")])

    def test_a_moving_clip_is_judged_by_the_model_from_a_contact_sheet(self):
        seen = []

        def describe(system, prompt, image):
            seen.append((prompt, image))
            return '{"passed": false, "problems": ["第3帧拳头没碰到人就倒了。"]}', "vision-model"

        with patch.object(fight_clip_check, "sample_frames", return_value=_frames(True)):
            verdict = fight_clip_check.check("clip.mp4", "甲一拳打向乙", describe)
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["problems"], ["第3帧拳头没碰到人就倒了"])
        self.assertEqual(verdict["model"], "vision-model")
        self.assertIn("甲一拳打向乙", seen[0][0])
        self.assertTrue(seen[0][1].startswith("data:image/jpeg;base64,"))
        self.assertIn("第3帧拳头没碰到人就倒了", fight_clip_check.fix_prompt(verdict["problems"]))

    def test_no_frames_or_no_model_never_blocks(self):
        with patch.object(fight_clip_check, "sample_frames", return_value=[]):
            self.assertIsNone(fight_clip_check.check("clip.mp4", "", lambda *a: ("", "")))
        with patch.object(fight_clip_check, "sample_frames", return_value=_frames(True)):
            self.assertIsNone(fight_clip_check.check("clip.mp4", "", lambda *a: (None, "")))

    def test_answers_are_read_strictly(self):
        self.assertIsNone(fight_clip_check.parse("挺好的"))
        self.assertEqual(fight_clip_check.parse('{"passed": true, "problems": []}'), {"passed": True, "problems": []})
        unclear = fight_clip_check.parse('{"passed": false, "problems": []}')
        self.assertFalse(unclear["passed"])
        self.assertEqual(unclear["problems"], [prompt_data.text("fight_scene", "clip_check_unclear")])


class StageFiveFightCheckTests(queue_tests.StageFiveQueueTests):
    """沿用第 5 阶段队列测试的替身；打戏场次的片段出来后核对一次，没过带着问题重出。"""

    def _fight_task(self):
        task = queue_tests._task(1)
        task["assets"]["4_scene_boards"] = {"E1S01": {"scene_kind": "fight"}}
        return task

    def _run_checked(self, task, verdicts):
        prompts: list[str] = []
        checked: list[str] = []

        def check(_self, clip_url, req):
            checked.append(clip_url)
            return verdicts.pop(0)

        with patch.dict("os.environ", {"FIGHT_CLIP_CHECK": "1"}), \
                patch.object(DramaService, "_check_fight_clip", check):
            stored = self._run(task, on_video=prompts.append)
        return stored, prompts, checked

    def test_a_failed_fight_clip_is_made_again_with_its_problems_and_the_better_one_kept(self):
        stored, prompts, checked = self._run_checked(self._fight_task(), [
            {"passed": False, "problems": ["人物站住不动"], "motion": 1.0, "model": ""},
            {"passed": True, "problems": [], "motion": 9.0, "model": "vision-model"},
        ])
        self.assertEqual(len(prompts), 2, "one retry, no more")
        self.assertNotIn(prompt_data.text("fight_scene", "clip_fix_lead"), prompts[0])
        self.assertIn(fight_clip_check.fix_prompt(["人物站住不动"]), prompts[1])
        clip = stored["assets"]["5"][0]
        self.assertEqual(clip["video_url"], checked[1])
        self.assertTrue(clip["fight_check"]["passed"])
        self.assertTrue(clip["fight_check"]["retried"])

    def test_a_worse_retry_is_dropped_and_a_passing_clip_is_not_retried(self):
        stored, prompts, checked = self._run_checked(self._fight_task(), [
            {"passed": False, "problems": ["没打到"], "motion": 8.0, "model": "m"},
            {"passed": False, "problems": ["没打到", "人糊在一起"], "motion": 8.0, "model": "m"},
        ])
        self.assertEqual(stored["assets"]["5"][0]["video_url"], checked[0])
        self.assertEqual(stored["assets"]["5"][0]["fight_check"]["problems"], ["没打到"])
        stored, prompts, _ = self._run_checked(self._fight_task(), [{"passed": True, "problems": [], "motion": 8.0, "model": "m"}])
        self.assertEqual(len(prompts), 1)

    def test_other_scenes_and_a_switched_off_check_are_left_alone(self):
        with patch.object(DramaService, "_check_fight_clip") as check:
            self._run(self._fight_task())              # 测试默认 FIGHT_CLIP_CHECK=0
            task = queue_tests._task(1)
            task["task_id"] = "q5-2"
            with patch.dict("os.environ", {"FIGHT_CLIP_CHECK": "1"}):
                self._run(task)
        check.assert_not_called()

    # 父类的逐镜测试在本类里不重复跑。
    test_shots_are_generated_under_the_video_ceiling_and_the_queue_is_persisted = None
    test_a_queued_shot_can_be_withdrawn_while_another_runs_and_the_finished_ones_are_kept = None
    test_the_queue_api_lists_items_and_refuses_to_cancel_a_running_one = None
    test_a_restart_requeues_items_a_dead_run_left_running = None
    test_a_provider_that_returns_no_clip_fails_the_shot_with_its_reason = None
    test_a_rerun_reuses_clips_without_regenerating_their_end_frames = None
    test_a_rerun_makes_again_a_clip_whose_link_has_expired = None
    test_a_rerun_reuses_the_saved_copy_when_only_the_provider_link_expired = None
    test_a_clip_sent_back_for_a_retake_is_not_returned_through_its_own_job = None
    test_a_board_whose_frame_is_judged_sensitive_is_retried_without_the_frames = None
    test_identity_references_prefer_local_views_over_expiring_sheet_links = None


if __name__ == "__main__":
    unittest.main()

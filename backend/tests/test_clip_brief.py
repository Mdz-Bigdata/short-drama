# -*- coding: utf-8 -*-
"""导演台上的姿态、姿势、动作、位置、朝向、空间与机位，跟着提示词进视频模型。"""

import unittest
from unittest.mock import patch

from app.core import prompt_budget, slice_video, style_packs
from app.core.spatial_stage import clip_brief
from app.core.spatial_stage.models import ActionClip, ActorKey, ActorOverride, ShotTimeline, StagePose
from app.core.spatial_stage.planner import build_plan
from app.core.video_prompt_engine import compile_shot_prompt
from tests.test_spatial_stage import _brief
from tests.test_stage_five_queue import StageFiveQueueTests, _task
from tests.test_style_packs import _shot


def _staged():
    plan = build_plan(_brief())
    shot = plan.shot(2)
    shot.overrides = [ActorOverride(name="沈砚", posture="fight", pose=StagePose(preset="punch"), yaw_deg=90.0)]
    plan.timelines["2"] = ShotTimeline(
        duration_s=5,
        actors={"沈砚": [ActorKey(time=0, position=[0, 0]), ActorKey(time=4, position=[3, 0], yaw_deg=180.0)]},
        clips={"沈砚": [ActionClip(id="c1", clip="human-walk-v1", start=0, end=2), ActionClip(id="c2", clip="human-sit-enter-v1", start=2, end=4)]},
    )
    return plan


class ShotLinesTests(unittest.TestCase):
    def test_a_person_carries_posture_pose_action_place_direction_and_build(self):
        lines = clip_brief.shot_lines(_staged(), 2)
        person = next(line for line in lines if line.startswith("人物：沈砚："))
        self.assertIn("格斗架势", person)
        self.assertIn("姿势出拳", person)
        self.assertIn("动作行走→坐下", person)
        self.assertIn("走位约", person)
        self.assertIn("转身约90°", person)
        self.assertIn("走位约3.0米", person)
        self.assertIn("身高约", person)
        self.assertIn("朝向", person)

    def test_space_gaze_axis_and_camera_each_get_a_line(self):
        lines = clip_brief.shot_lines(_staged(), 2)
        for label in ("空间：", "视线：", "轴线：", "机位："):
            self.assertTrue(any(line.startswith(label) for line in lines), label)
        camera = next(line for line in lines if line.startswith("机位："))
        self.assertIn("mm", camera)
        self.assertIn("机高", camera)
        self.assertNotIn("机高", next(line for line in lines if line.startswith("空间：")), "the lens is said once")

    def test_a_blockout_clip_owns_the_camera_so_the_text_says_nothing_about_it(self):
        text = "\n".join(clip_brief.shot_lines(_staged(), 2, camera=False))
        self.assertNotIn("机位：", text)
        self.assertNotIn("机高", text)
        self.assertIn("人物：沈砚", text)

    def test_placeholder_prop_sizes_are_not_sent(self):
        plan = _staged()
        lines = "\n".join(clip_brief.shot_lines(plan, 2))
        props = [landmark.name for landmark in plan.landmarks if landmark.kind == "prop"]
        self.assertTrue(props)
        for name in props:
            self.assertNotIn(f"布景：{name}宽", lines)

    def test_no_plan_or_no_such_shot_means_no_lines(self):
        self.assertEqual(clip_brief.shot_lines(None, 1), [])
        self.assertEqual(clip_brief.shot_lines(_staged(), 999), [])
        self.assertEqual(clip_brief.shot_lines(_staged(), "x"), [])

    def test_hand_set_joints_are_read_as_their_largest_bends(self):
        pose = StagePose(joints={"leftElbow.bend": 90, "rightKnee.bend": 40, "head.yaw": 5, "leftHand.index.curl": 80})
        self.assertEqual(clip_brief.pose_text(pose), "左肘弯曲约90°、右膝弯曲约40°")
        self.assertEqual(clip_brief.pose_text(StagePose(clip="human-walk-v1", preset="sit")), "行走")
        self.assertEqual(clip_brief.pose_text(None), "")


class PromptTests(unittest.TestCase):
    LINES = ["人物：林夏：站立；姿势抱臂", "空间：林夏画左、周教授画右，相距2.6米面对面", "机位：机高1.5米，50mm"]

    def test_a_single_shot_carries_it_up_front_without_repeating_its_locks(self):
        text = compile_shot_prompt(style_packs.FILM_35MM, _shot(stage_lines=self.LINES, cast_refs=["林夏", "周教授"]), model="seedance2.5").text
        self.assertLess(text.index("[空间锚]"), text.index("【导演台占位】"))
        self.assertLess(text.index("【导演台占位】"), text.index("画面："))
        self.assertIn("人物：@[林夏]：站立；姿势抱臂", text)
        self.assertNotIn("空间：", text, "the space lock already says this word for word")
        self.assertNotIn("【导演台占位】", compile_shot_prompt(style_packs.FILM_35MM, _shot(), model="seedance2.5").text)

    def test_the_budget_never_cuts_it(self):
        self.assertIn("stage", prompt_budget.FIXED_SECTIONS)
        long = ["人物：林夏：" + "站立；" * 400]
        compiled = compile_shot_prompt(style_packs.FILM_35MM, _shot(stage_lines=long), model="seedance2.0")
        self.assertIn("stage", compiled.sections)

    def _beat(self, text, stage, override=""):
        return slice_video.Beat(sections={
            "style_lock": "[STYLE LOCK] 写实", "locks": "[空间锚]正堂", "subject": f"画面：{text}。", "rules": "【关键约束】\n物理真实",
        }, size="MS", motion="推", stage=stage, override=override)

    def test_every_moment_of_a_slice_keeps_its_own_staging_and_says_a_clause_once(self):
        beats = [
            self._beat("按手印", ["人物：沈知微：坐着", "轴线：恒在画左；夹角约80度", "机位：机高1.2米"]),
            self._beat("睁眼", ["人物：沈知微：坐着", "轴线：恒在画左；夹角约45度", "机位：机高1.6米"]),
            self._beat("松手", ["机位：机高9米"], override="手改的正文"),
        ]
        text = slice_video.compile_prompt(beats, model="seedance2.0", cast=["沈知微"]).text
        self.assertIn("镜头1：人物：@[沈知微]：坐着", text)
        self.assertEqual(text.count("坐着"), 1)
        self.assertEqual(text.count("恒在画左"), 1)
        self.assertIn("镜头2：轴线：夹角约45度\n机位：机高1.6米", text)
        self.assertNotIn("机高9米", text, "a hand-written moment is left as written")
        self.assertLess(text.index("【导演台占位】"), text.index("【镜头1/3"))
        self.assertEqual(slice_video.beat_count(text), 3)


class StageFiveTests(StageFiveQueueTests):
    def test_the_current_desk_reaches_the_request_of_every_moment(self):
        prompts: list[str] = []
        task = _task(3)
        task["config"].pop("video_granularity", None)
        plan = _staged()
        with patch("app.service.drama_service.spatial_stage.load_plan", return_value=plan):
            self._run(task, on_video=prompts.append)
        [prompt] = prompts
        self.assertIn("【导演台占位】", prompt)
        self.assertIn("镜头2：", prompt)
        self.assertIn("姿势出拳", prompt)
        self.assertIn("动作行走→坐下", prompt)

    test_shots_are_generated_under_the_video_ceiling_and_the_queue_is_persisted = None
    test_a_queued_shot_can_be_withdrawn_while_another_runs_and_the_finished_ones_are_kept = None
    test_the_queue_api_lists_items_and_refuses_to_cancel_a_running_one = None
    test_a_restart_requeues_items_a_dead_run_left_running = None


if __name__ == "__main__":
    unittest.main()

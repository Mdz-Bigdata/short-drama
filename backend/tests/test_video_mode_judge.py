# -*- coding: utf-8 -*-
"""自动模式下由文本模型按戏判定每段视频用首尾帧还是多图参考；能否执行仍由路由把关。"""

import json
import unittest
from unittest.mock import patch

from app.core import video_mode_judge as judge
from app.core.video_references import VideoGenerationIntent, VideoReferencePlan, plan_video_references, renumber_reference_mentions
from app.service.drama_service import extract_json_object
from tests.test_stage_five_queue import StageFiveQueueTests, _task

FRAMES = {"first_frame": "f.png", "last_frame": "l.png", "sequence_images": ["a.png", "b.png"], "reference_images": ["face.png"]}


class ChoiceTests(unittest.TestCase):
    def test_only_clips_with_a_real_choice_are_asked_about(self):
        both = ["first_last_frame", "multi_reference"]
        self.assertTrue(judge.has_a_choice(both, beats=3, fight=False, attached=False))
        self.assertTrue(judge.has_a_choice(both, beats=1, fight=True, attached=False))
        self.assertFalse(judge.has_a_choice(both, beats=1, fight=False, attached=True), "an attached video or audio is kept")
        self.assertFalse(judge.has_a_choice(both, beats=3, fight=True, attached=False), "hard cuts cannot be two frames")
        self.assertFalse(judge.has_a_choice(["multi_reference"], beats=1, fight=False, attached=False))

    def test_an_answer_counts_only_for_clips_and_modes_it_was_asked_about(self):
        answer = json.dumps({"clips": [
            {"id": "c1", "mode": "first_last_frame", "reason": "结尾定格"},
            {"id": "c2", "mode": "text", "reason": "x"},
            {"id": "c9", "mode": "multi_reference", "reason": "x"},
        ]})
        self.assertEqual(
            judge.parse(answer, ["c1", "c2"], extract=extract_json_object), {"c1": judge.Judgement("first_last_frame", "结尾定格")},
        )
        self.assertEqual(judge.parse("不是 JSON", ["c1"], extract=extract_json_object), {})

    def test_the_prompt_does_not_push_every_clip_to_one_mode(self):
        from app.core import prompt_data

        system = prompt_data.text("video_mode_judge", "system")
        self.assertIn("不要因为人物身份就一律选多图参考", system)
        self.assertNotIn("拿不准", system)
        self.assertNotIn("少数", system)

    def test_a_failed_batch_costs_only_that_batch(self):
        clips = [judge.Clip(id=f"c{n}", beats=("画面",)) for n in range(1, 42)]
        asked = []

        def ask(system, user, accept):
            asked.append(user)
            if len(asked) == 1:
                raise RuntimeError("timeout")
            return json.dumps({"clips": [{"id": "c41", "mode": "multi_reference", "reason": "多人"}]})

        found = judge.judge(clips, ask=ask, extract=extract_json_object)
        self.assertEqual(len(asked), 2, "forty clips to a batch")
        self.assertEqual(list(found), ["c41"])


class RoutingTests(unittest.TestCase):
    def _plan(self, preferred, **assets):
        intent = VideoGenerationIntent(preferred_mode=preferred, preferred_reason="结尾定格")
        return plan_video_references("auto", model="seedance2.5", intent=intent, **{**FRAMES, **assets})

    def test_the_routing_follows_the_judgement_and_says_so(self):
        plan = self._plan("first_last_frame")
        self.assertEqual(plan.mode, "first_last_frame")
        self.assertEqual(plan.reasons, ["模型判定：结尾定格"])
        self.assertEqual(self._plan("multi_reference").mode, "multi_reference")

    def test_a_judgement_that_cannot_run_falls_back_to_the_rules(self):
        plan = self._plan("first_last_frame", last_frame=None)
        self.assertEqual(plan.mode, "multi_reference", "the end frame never arrived")
        self.assertIn("模型判定的 first_last_frame 这一镜执行不了", plan.fallbacks[0])

    def test_an_attached_video_is_never_dropped_on_the_models_word(self):
        plan = self._plan("first_last_frame", reference_videos=["move.mp4"])
        self.assertEqual(plan.mode, "multimodal")
        self.assertEqual(plan.reference_videos, ["move.mp4"])


class FramesOnlyWordingTests(unittest.TestCase):
    PROMPT = (
        "【人物锚点·锁脸】沈砚（参考图1）。脸型、发型、服装与体型以参考图为准，情绪前后连贯。画面里只有这一个人，只出现一次；同一人物的多张参考图属于同一个人。\n"
        "【服装绑定】沈砚（参考图1）全程穿素袍（参考图2），款式、颜色与配饰以服装参考图为准，不换装。\n"
        "【参考素材职责】\n"
        "参考图1仅锁定数字演员设定集「沈砚」的脸型，不是额外剧情或额外人物；参考图2仅锁定服装「素袍」的外形，不是额外剧情或额外人物。\n\n"
        "【结构声明】单镜。\n\n【关键约束】\n物理铁律：参考图与物理冲突时以物理为准。\n设定图反偷懒铁律：设定图仅作造型参考\n风格铁律：不要 CGI。"
    )

    def _render(self, **plan):
        return renumber_reference_mentions(self.PROMPT, ["a.png", "b.png"], VideoReferencePlan(mode="first_last_frame", **plan))

    def test_a_request_with_only_frames_never_points_at_a_reference_image(self):
        text = self._render(first_frame="f.png", last_frame="l.png")
        self.assertNotIn("参考图", text)
        self.assertNotIn("【参考素材职责】", text)
        self.assertNotIn("设定图", text)
        self.assertIn("脸型、发型、服装与体型以首帧画面为准", text)
        self.assertIn("款式、颜色与配饰以首帧画面为准", text)
        self.assertIn("只出现一次。\n", text)
        self.assertIn("【服装绑定】", text)
        self.assertIn("风格铁律", text)
        self.assertIn("所给画面与物理冲突时以物理为准", text)

    def test_a_request_that_carries_references_keeps_their_wording(self):
        plan = VideoReferencePlan(mode="multi_reference", first_frame="f.png", reference_images=["a.png", "b.png"])
        text = renumber_reference_mentions(self.PROMPT, ["a.png", "b.png"], plan)
        self.assertIn("以参考图为准", text)
        self.assertIn("【参考素材职责】", text)
        self.assertIn("设定图反偷懒铁律", text)


class StageFiveTests(StageFiveQueueTests):
    def _judged_run(self, task, answer):
        """跑第 5 阶段，返回 (交给文本模型的问题, 视频请求)。"""
        self.questions, self.requests = [], []

        def call_llm(model, system, user, title, **kwargs):
            self.questions.append(user)
            return answer(user) if callable(answer) else answer

        def generate_video(model, image_url, prompt, *args, **kwargs):
            self.requests.append({"prompt": prompt, "first": image_url, **kwargs})
            return f"https://cdn/{len(self.requests)}.mp4"

        with patch.dict("os.environ", {"VIDEO_MODE_JUDGE": "1"}), \
             patch.object(self.service.gateway, "has_text_model", return_value=True), \
             patch.object(self.service.gateway, "call_llm", side_effect=call_llm), \
             patch.object(self.service.gateway, "generate_video", side_effect=generate_video), \
             patch.object(self.service.gateway, "generate_image", return_value=("https://cdn/end.png", {})) as self.images, \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(type(self.service), "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.repo.save_task(task["task_id"], task)
            self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        return self.repo.get_task(task["task_id"])

    def _board(self, count=3):
        task = _task(count)
        task["config"].pop("video_granularity", None)
        return task

    def test_a_board_judged_first_last_sends_its_two_frames_and_says_so(self):
        answer = json.dumps({"clips": [{"id": "c1", "mode": "first_last_frame", "reason": "结尾定格在门内"}]})
        stored = self._judged_run(self._board(), answer)
        self.assertEqual(len(self.questions), 1)
        self.assertIn('"瞬间数": 3', self.questions[0])
        [request] = self.requests
        self.assertEqual(request["last_frame"], "https://cdn/end.png")
        self.assertNotIn("所给3张分镜画面", request["prompt"], "only the first and last frames are sent")
        self.assertIn("以所给尾帧结束：它是镜头3的落幅", request["prompt"])
        [clip] = stored["assets"]["5"]
        self.assertEqual(clip["video_route_decision"]["mode"], "first_last_frame")
        self.assertEqual(clip["video_route_decision"]["reasons"], ["模型判定：结尾定格在门内"])

    def test_a_board_judged_multi_reference_pays_for_no_end_frame(self):
        answer = json.dumps({"clips": [{"id": "c1", "mode": "multi_reference", "reason": "多瞬间"}]})
        stored = self._judged_run(self._board(), answer)
        self.assertFalse(self.requests[0].get("last_frame"))
        self.images.assert_not_called()
        self.assertEqual(stored["assets"]["5"][0]["video_route_decision"]["reasons"], ["模型判定：多瞬间"])

    def test_no_usable_answer_keeps_the_rules(self):
        stored = self._judged_run(self._board(), "我觉得都行")
        self.assertEqual(stored["assets"]["5"][0]["video_route_decision"]["mode"], "multi_reference")
        self.assertFalse(stored["assets"]["5"][0]["video_route_decision"]["reasons"][0].startswith("模型判定"))

    def test_the_same_question_is_not_paid_for_twice(self):
        answer = json.dumps({"clips": [{"id": "c1", "mode": "multi_reference", "reason": "多瞬间"}]})
        stored = self._judged_run(self._board(), answer)
        self.assertEqual(len(self.questions), 1)
        again = _task(3)
        again["config"].pop("video_granularity", None)
        again["llm_memo"] = stored["llm_memo"]
        self._judged_run(again, answer)
        self.assertEqual(self.questions, [], "the memo answered")

    def test_a_chosen_mode_is_not_second_guessed(self):
        task = self._board()
        task["config"]["video_reference_mode"] = "multi_reference"
        self._judged_run(task, "{}")
        self.assertEqual(self.questions, [])

    def test_a_clip_with_an_attached_video_is_not_asked_about(self):
        task = self._board()
        task["assets"]["4"][1]["reference_videos"] = ["https://cdn/move.mp4"]
        stored = self._judged_run(task, "{}")
        self.assertEqual(self.questions, [])
        self.assertEqual(stored["assets"]["5"][0]["video_route_decision"]["mode"], "multimodal")

    # 父类的逐镜队列测试在本类里不重复跑。
    test_shots_are_generated_under_the_video_ceiling_and_the_queue_is_persisted = None
    test_a_queued_shot_can_be_withdrawn_while_another_runs_and_the_finished_ones_are_kept = None
    test_the_queue_api_lists_items_and_refuses_to_cancel_a_running_one = None
    test_a_restart_requeues_items_a_dead_run_left_running = None


if __name__ == "__main__":
    unittest.main()

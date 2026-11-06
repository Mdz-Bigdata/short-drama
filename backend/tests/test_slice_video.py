# -*- coding: utf-8 -*-
"""每个分镜片段一段运镜视频：一张看板上的几个连续瞬间，一次多镜头生成。"""

import unittest

from app.core import episode_cycle as cycle
from app.core import generation_queue as gq
from app.core import slice_video
from app.core.continuity import ContinuityState
from app.core.video_admission import assess_video_batch
from app.service.drama_service import final_cut_transitions
from tests.test_stage_five_queue import StageFiveQueueTests, _shot, _task


def _beat(shot_id, scene_id="E1S01", seconds="5秒", **extra):
    return {"shot_id": shot_id, "scene_id": scene_id, "duration": seconds, "desc": "沈知微抬眼" * 4, "characters": ["沈知微"], **extra}


class PlanTests(unittest.TestCase):
    def test_one_video_per_board_at_the_planned_length(self):
        shots = [_beat(1), _beat(2, seconds="6.5秒"), _beat(1, "E1S02"), _beat(2, "E1S02", "4秒")]
        pieces = slice_video.plan(shots, ceiling=15, planned={"E1S01": 11.5, "E1S02": 13.0})
        self.assertEqual([(p.scene_id, p.indexes, p.seconds) for p in pieces], [("E1S01", [0, 1], 12), ("E1S02", [2, 3], 13)])
        self.assertEqual([p.label for p in pieces], ["E1S01 片段", "E1S02 片段"])

    def test_a_board_longer_than_one_request_is_split_in_order_never_squeezed(self):
        shots = [_beat(k, seconds="6秒") for k in (1, 2, 3, 4)]
        pieces = slice_video.plan(shots, ceiling=15, planned={})
        self.assertEqual([(p.indexes, p.seconds, p.part, p.parts) for p in pieces], [([0, 1], 12, 1, 2), ([2, 3], 12, 2, 2)])
        self.assertEqual(pieces[1].label, "E1S01 片段 2/2")

    def test_hand_set_lengths_win_over_the_board_plan(self):
        shots = [_beat(1, visual={"duration_seconds": 7}), _beat(2, visual={"duration_seconds": 6})]
        self.assertEqual(slice_video.plan(shots, ceiling=15, planned={"E1S01": 10})[0].seconds, 13)

    def test_the_project_can_go_back_to_one_video_per_moment(self):
        self.assertTrue(slice_video.enabled({}))
        self.assertFalse(slice_video.enabled({"video_granularity": "shot"}))


class PromptTests(unittest.TestCase):
    def _beat(self, text):
        return slice_video.Beat(sections={
            "style_lock": "[STYLE LOCK] 写实", "locks": "[空间锚]正堂", "camera": "景别：MS；运镜：推",
            "subject": f"画面：{text}。", "dialogue": "无台词，人物闭口。", "end_state": f"落幅：{text}停住",
            "rules": "【关键约束】\n物理真实", "negatives": "变脸 + 穿模",
        }, size="MS", motion="推")

    def test_every_moment_keeps_its_own_block_and_joins_smoothly(self):
        compiled = slice_video.compile_prompt(
            [self._beat("按手印"), self._beat("睁眼"), self._beat("松手")], model="seedance2.0", cast=["沈知微"], storyboard_frames=3,
        )
        text = compiled.text
        for number, action in enumerate(("按手印", "睁眼", "松手"), start=1):
            self.assertIn(f"【镜头{number}/3｜MS｜推】", text)
            self.assertIn(action, text)
        self.assertEqual(text.count(slice_video.DEFAULT_JOIN), 2)
        self.assertIn("同一场戏连续3个镜头，一次生成一段连贯视频", text)
        self.assertIn("所给3张分镜画面按镜头顺序排列", text)
        self.assertIn("不硬切", text)
        self.assertEqual(text.count("[STYLE LOCK]"), 1)
        self.assertEqual(text.count("物理真实"), 1)
        self.assertEqual(slice_video.beat_count(text), 3)
        self.assertEqual(compiled.pressure.budget, 600 * 3)

    def test_a_slice_writes_the_costume_binding_and_each_persons_look_once(self):
        beats = [self._beat("按手印"), self._beat("睁眼")]
        beats[0].sections["appearance"] = "人物外貌：@[沈知微]：瓜子脸；黑色长发。"
        beats[0].sections["quality"] = "画质：真人实拍电影画质。"
        beats[1].sections["appearance"] = "人物外貌：@[沈知微]：瓜子脸；黑色长发。@[裴砚]：剑眉；短须。"
        text = slice_video.compile_prompt(
            beats, model="seedance2.0", cast=["沈知微", "裴砚"], costumes=[("沈知微", "沈知微·石榴红襦裙")],
        ).text
        self.assertIn("【服装绑定】@[沈知微]全程穿@[沈知微·石榴红襦裙]", text)
        self.assertEqual(text.count("@[沈知微]：瓜子脸；黑色长发。"), 1)
        self.assertIn("@[裴砚]：剑眉；短须。", text)
        self.assertEqual(text.count("画质："), 1)
        self.assertLess(text.index("【镜头2/2"), text.index("[STYLE LOCK]"), "the look paragraph comes after the shot blocks")

    def test_a_fight_cuts_hard_between_its_moments(self):
        compiled = slice_video.compile_prompt(
            [self._beat("出拳"), self._beat("格挡"), self._beat("肘击")], model="seedance2.0", cast=["沈知微"], fight=True,
        )
        text = compiled.text
        self.assertIn("镜头之间全部硬切，不叠化、不淡入淡出", text)
        self.assertIn("每次击中落在特写或大特写", text)
        self.assertNotIn("不硬切", text)
        self.assertEqual(text.count(slice_video.FIGHT_JOIN), 2)
        self.assertIn("从上一个瞬间的收势直接起势、不重新摆架", text)
        self.assertEqual(text.count(slice_video.DEFAULT_JOIN), 0)
        # A planned soft join from the board does not soften a fight.
        soft = self._beat("格挡")
        soft.cut_in = "匹配剪辑·顺接"
        again = slice_video.compile_prompt([self._beat("出拳"), soft], model="seedance2.0", fight=True).text
        self.assertIn(slice_video.FIGHT_JOIN, again)
        self.assertNotIn("匹配剪辑", again)

    def test_a_planned_cut_is_written_as_the_join(self):
        second = self._beat("睁眼")
        second.cut_in = "匹配剪辑：手部动作顺接"
        text = slice_video.compile_prompt([self._beat("按手印"), second], model="seedance2.0").text
        self.assertIn("衔接：匹配剪辑：手部动作顺接。", text)

    def test_an_old_hard_cut_inside_a_board_is_written_as_a_smooth_join(self):
        second = self._beat("睁眼")
        second.cut_in = "硬切·顺接"
        text = slice_video.compile_prompt([self._beat("按手印"), second], model="seedance2.0").text
        self.assertIn("衔接：连贯衔接·顺接。", text)
        self.assertNotIn("硬切·", text)

    def test_a_title_in_the_prompt_points_at_the_named_actor(self):
        from app.core.storyboard_scene_context import name_titles
        text = name_titles("沈知微与侯府嫡女对视；服装「陆婉（侯府嫡女）·石榴红襦裙」", {"侯府嫡女": "陆婉"})
        self.assertEqual(text, "沈知微与@[陆婉]对视；服装「陆婉（侯府嫡女）·石榴红襦裙」")


class CoverageTests(unittest.TestCase):
    def _task(self, clips):
        progress = {"current_episode": 1, "episodes": [{"number": n, "total": 1, "done": 1, "complete": True} for n in (1, 2)]}
        shots = [_beat(1), _beat(2), _beat(1, "E2S01")]
        return {"config": {}, "assets": {"4_progress": progress, "4": shots, "5": clips, cycle.CYCLE_KEY: {"version": 1, "episodes": {}}}}

    def test_one_board_video_covers_every_moment_on_the_board(self):
        clip = {"scene_id": "E1S01", "shot_id": 1, "shot_uids": [100101, 100102], "video_url": "s.mp4", "slice": {"beats": []}}
        task = self._task([clip])
        self.assertEqual(cycle.missing(task, 5), [])
        self.assertIs(cycle.clip_for(_beat(2), task["assets"]["5"]), clip)
        self.assertIsNone(cycle.clip_for(_beat(2, "E1S02"), task["assets"]["5"]))

    def test_a_moment_without_its_board_video_keeps_the_episode_in_video(self):
        task = self._task([{"scene_id": "E1S01", "shot_id": 1, "video_url": "a.mp4"}])
        self.assertEqual(cycle.missing(task, 5), ["第1集视觉(运镜视频)尚未完成"])


class AdmissionTests(unittest.TestCase):
    def _task(self, clips=()):
        return {"task_id": "s-1", "config": {"video_model": "seedance2.0"}, "assets": {
            "4": [_beat(1), _beat(2, seconds="6.5秒"), _beat(1, "E1S02")], "5": list(clips), "3_sheets": {"沈知微": "x"},
            "4_scene_boards": {"E1S01": {"prompt_detail": {"duration_seconds": 11.5}}},
        }}

    def test_the_quote_counts_one_request_per_board(self):
        admission = assess_video_batch(self._task(), provider_ready=lambda *_: True, clip_ceiling=15)
        self.assertEqual(admission.decision, "admitted")
        self.assertEqual([shot.requested_seconds for shot in admission.shots], [12, 0, 5])
        self.assertEqual(admission.estimate["shots_to_generate"], 2)
        self.assertEqual(admission.estimate["requested_seconds"], 17)

    def test_only_a_board_video_is_reused(self):
        per_moment = [{"scene_id": "E1S01", "shot_id": 1, "video_url": "a.mp4"}]
        self.assertEqual(assess_video_batch(self._task(per_moment), provider_ready=lambda *_: True).shots[0].quote, "generate")
        board = [{"scene_id": "E1S01", "shot_id": 1, "shot_uids": [100101, 100102], "video_url": "s.mp4", "slice": {"beats": []}}]
        quotes = [shot.quote for shot in assess_video_batch(self._task(board), provider_ready=lambda *_: True).shots]
        self.assertEqual(quotes, ["reuse", "reuse", "generate"])


class FinalCutTests(unittest.TestCase):
    def test_the_next_board_joins_from_where_the_previous_board_ends(self):
        def state(action, direction):
            return ContinuityState(characters=["沈知微"], scene="正堂", screen_direction=direction, action=action, emotion="平静",
                                   props={"契纸": "在案上"}, lighting="右侧主光", audio_bed="室内底噪").model_dump()
        first = {"shot_id": 1, "continuity_state": state("起身", "neutral"), "continuity_out": state("走向门口", "left_to_right")}
        second = {"shot_id": 1, "continuity_state": state("走向门口", "left_to_right")}
        _, reports = final_cut_transitions([first, second])
        self.assertNotIn("缺少旧任务结构化状态", "".join(reports[0].get("reasons") or []))


class StageFiveSliceTests(StageFiveQueueTests):
    """沿用第 5 阶段队列测试的替身：同一场三个瞬间只提交一次视频。"""

    def _slice_task(self, scenes):
        task = _task(len(scenes))
        task["config"].pop("video_granularity", None)
        for shot, scene_id in zip(task["assets"]["4"], scenes):
            shot["scene_id"] = scene_id
        return task

    def test_three_moments_on_one_board_are_one_video(self):
        prompts: list[str] = []
        stored = self._run(self._slice_task(["E1S01", "E1S01", "E1S01"]), on_video=prompts.append)
        self.assertEqual(len(prompts), 1)
        self.assertIn("【镜头1/3", prompts[0])
        self.assertIn("【镜头3/3", prompts[0])
        [clip] = stored["assets"]["5"]
        self.assertEqual(clip["shot_uids"], [100101, 100102, 100103])
        self.assertEqual(len(clip["slice"]["beats"]), 3)
        self.assertEqual(clip["duration"], 9)
        self.assertTrue(clip["contract_fingerprint"].startswith("slice:"))
        self.assertEqual(clip["video_route_decision"]["mode"], "multi_reference")
        self.assertIn("continuity_out", clip)
        queue = stored["assets"][gq.QUEUE_KEY]
        self.assertEqual([item["label"] for item in queue["items"] if item["key"].startswith("video:")], ["E1S01 片段 · 视频 ×1"])

    def test_each_board_gets_its_own_video(self):
        prompts: list[str] = []
        stored = self._run(self._slice_task(["E1S01", "E1S01", "E1S02"]), on_video=prompts.append)
        self.assertEqual(len(prompts), 2)
        self.assertEqual([clip["scene_id"] for clip in stored["assets"]["5"]], ["E1S01", "E1S02"])

    # 父类的逐镜测试在本类里不重复跑。
    test_shots_are_generated_under_the_video_ceiling_and_the_queue_is_persisted = None
    test_a_queued_shot_can_be_withdrawn_while_another_runs_and_the_finished_ones_are_kept = None
    test_the_queue_api_lists_items_and_refuses_to_cancel_a_running_one = None
    test_a_restart_requeues_items_a_dead_run_left_running = None


if __name__ == "__main__":
    unittest.main()

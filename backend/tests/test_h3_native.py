# -*- coding: utf-8 -*-
"""MiniMax H3 官方 Ref2VA 六段式提示词：改写、校验、发送前落图片编号。"""

import json
import unittest
from unittest.mock import patch

from app.core import h3_native
from tests.test_stage_five_queue import StageFiveQueueTests, _task

BOARD = (
    "【镜头1/2｜中景｜缓慢推进】画面：@[沈无咎]立在@[演武场]左侧，唯一主光为画面左后方火把的暖橙硬光。"
    "台词：@[沈无咎]{剑自己动的。}\n"
    "【镜头2/2｜近景｜固定】衔接：动作顺接。画面：@[裴仲玄]扣住剑鞘。台词：@[裴仲玄]{谁动的剑？}"
)
GOOD = (
    "subject_definitions: <Subject 1> is @[沈无咎], a young swordsman. <Subject 2> is @[裴仲玄], an older sect master. "
    "<Subject 3> is the training ground @[演武场]. <Frame 1> is the storyboard reference for [Shot 1], defining viewpoint, "
    "subject placement and composition. <Frame 2> is the storyboard reference for [Shot 2], defining viewpoint, subject placement and composition.\n\n"
    "summary: [reference generation] A rainy-night confrontation in two shots.\n\n"
    "retention_analysis: <Subject 1> fully_preserved; <Subject 2> fully_preserved; <Frame 1> fully_preserved; <Frame 2> fully_preserved.\n\n"
    "detailed_description: [Shot 1] <Subject 1> stands screen-left, lit by a warm orange torch key light from back-left; the camera pushes in slowly. "
    "The young man (S1) says: <d>[Chinese] 剑自己动的。</d> "
    "[Shot 2] At 00:06.000, the shot transitions to a close-up as <Subject 2> grips the scabbard. The older man (S2) says: <d>[Chinese] 谁动的剑？</d>\n\n"
    "overall_soundscape: Dense rain on stone, the scrape of a blade sliding home.\n\n"
    "non_diegetic_music: N/A"
)


def _job():
    return h3_native.request(BOARD, beat_seconds=[6, 6], seconds=12, frames=2)


class RequestTests(unittest.TestCase):
    def test_shot_timecodes_follow_the_planned_seconds(self):
        self.assertEqual(h3_native.shot_starts([6, 6], 12), ["", "00:06.000"])
        self.assertEqual(h3_native.shot_starts([4, 4, 4], 15), ["", "00:05.000", "00:10.000"])
        self.assertEqual(h3_native.timecode(65.5), "01:05.500")

    def test_the_job_lists_mentions_and_verbatim_dialogue(self):
        job = _job()
        self.assertEqual(job.mentions, {"@[沈无咎]", "@[演武场]", "@[裴仲玄]"})
        self.assertEqual(job.dialogue, ["剑自己动的。", "谁动的剑？"])
        prompt = h3_native.user_prompt(job)
        self.assertIn("[Shot 2] At 00:06.000", prompt)
        self.assertIn("<Frame 1>、<Frame 2>", prompt)


class SpokenLineTests(unittest.TestCase):
    def test_speakers_delivery_notes_quotes_and_placeholders_are_not_part_of_the_line(self):
        lines = h3_native.spoken_lines([
            "裴仲玄（冷硬压嗓）：「谁动的剑？」／沈无咎：“剑自己动的。”", "无", "陈九：（低声）我擦的是你的剑。",
        ])
        self.assertEqual(lines, ["谁动的剑？", "剑自己动的。", "我擦的是你的剑。"])
        self.assertEqual(h3_native.spoken_lines(["沈无咎：{落。}", "无；无"]), ["落。"])
        self.assertEqual(h3_native.spoken_lines(["裴仲玄：{谁？}停顿一拍{谁动的剑？}"]), ["谁？", "谁动的剑？"])
        self.assertEqual(h3_native.spoken_lines(["苏问剑：站住。（中低声区、偏冷带颗粒感"]), ["站住。"])
        self.assertEqual(h3_native.spoken_lines(["陈九：握着。沈无咎：握了。"]), ["握着。", "握了。"])
        self.assertEqual(h3_native.spoken_lines(["裴仲玄：果然在这。停顿一拍，三年了。"]), ["果然在这。", "三年了。"])

    def test_quote_marks_do_not_count_in_the_verbatim_check(self):
        job = h3_native.request(BOARD, beat_seconds=[6, 6], seconds=12, frames=2, dialogue=["沈无咎：「剑自己动的。」", "裴仲玄：谁动的剑？"])
        self.assertEqual(h3_native.check(job, GOOD.replace("剑自己动的。", "「剑自己动的。」")), "")


class CheckTests(unittest.TestCase):
    def test_a_complete_six_section_prompt_passes(self):
        self.assertEqual(h3_native.check(_job(), GOOD), "")

    def test_every_rule_is_enforced(self):
        job = _job()
        cases = {
            "缺少段落 retention_analysis": GOOD.replace("retention_analysis:", "retention:"),
            "没有用给定时间码": GOOD.replace("At 00:06.000", "At 00:05.000"),
            "丢了标记": GOOD.replace("@[裴仲玄]", "Pei"),
            "丢了分镜画面": GOOD.replace("<Frame 2>", "the second frame"),
            "台词没有逐字保留": GOOD.replace("谁动的剑？", "谁动了剑？"),
            "写了硬切": GOOD.replace("the shot transitions to", "a hard cut to"),
            "代码块": "```\n" + GOOD + "\n```",
            "说话人编号": GOOD.replace("<Subject 1> fully_preserved;", "<Subject 1> (S1) fully_preserved;"),
            "超出长度上限": GOOD + " filler" * 1200,
        }
        for reason, text in cases.items():
            self.assertIn(reason, h3_native.check(job, text), reason)

    def test_section_order_is_fixed(self):
        swapped = GOOD.replace("summary:", "SUMMARY_TMP:").replace("retention_analysis:", "summary:").replace("SUMMARY_TMP:", "retention_analysis:")
        self.assertIn("顺序", h3_native.check(_job(), swapped))


class ReferenceTagTests(unittest.TestCase):
    def test_every_numbered_reference_must_survive_and_lands_on_its_real_picture(self):
        board = BOARD + "\n【参考素材职责】参考图1仅锁定数字演员设定集「沈无咎」；参考图4仅锁定拍摄场地「演武场」的45°斜角。"
        job = h3_native.request(board, beat_seconds=[6, 6], seconds=12, frames=2)
        self.assertEqual(job.refs, [1, 4])
        self.assertIn("参考图4 → <Ref 4>", h3_native.user_prompt(job))
        self.assertIn("丢了参考图：<Ref 4>", h3_native.check(job, GOOD + " <Ref 1> is his face."))
        good = GOOD.replace("subject_definitions: ", "subject_definitions: <Ref 1> fixes his face. <Ref 4> is the 45-degree view of the yard. ")
        self.assertEqual(h3_native.check(job, good), "")
        identity = ["shen.png", "pei.png", "yard.png", "yard45.png"]
        out = h3_native.resolve(
            good, sent=["f1.png", "f2.png", *identity], identity_images=identity, numbers={"沈无咎": 1, "裴仲玄": 2, "演武场": 3},
            frames=["f1.png", "f2.png"],
        )
        self.assertIn("<Picture 3> fixes his face. <Picture 6> is the 45-degree view of the yard.", out)


class ResolveTests(unittest.TestCase):
    def test_tags_become_the_real_picture_numbers_of_this_request(self):
        frames = ["f1.png", "f2.png"]
        identity = ["shen.png", "pei.png", "yard.png"]
        numbers = {"沈无咎": 1, "裴仲玄": 2, "演武场": 3}
        sent = ["f1.png", "f2.png", "shen.png", "pei.png", "yard.png"]
        out = h3_native.resolve(GOOD, sent=sent, identity_images=identity, numbers=numbers, frames=frames)
        self.assertIn("<Subject 1> is 沈无咎 (<Picture 3>)", out)
        self.assertIn("<Picture 1> is the storyboard reference for [Shot 1]", out)
        self.assertNotIn("@[", out)
        self.assertNotIn("<Frame", out)

    def test_frames_that_were_not_sent_drop_out_and_a_handoff_frame_is_named(self):
        sent = ["handoff.jpg", "shen.png", "pei.png", "yard.png"]
        out = h3_native.resolve(
            GOOD, sent=sent, identity_images=["shen.png", "pei.png", "yard.png"], numbers={"沈无咎": 1, "裴仲玄": 2, "演武场": 3},
            frames=["f1.png", "f2.png"], handoff="handoff.jpg",
        )
        self.assertNotIn("<Frame", out)
        self.assertNotIn("storyboard reference for [Shot 1]", out)
        self.assertTrue(out.startswith("subject_definitions: <Picture 1> is the last frame of the previous part"))

    def test_the_gateway_recognises_a_native_prompt(self):
        self.assertTrue(h3_native.is_native(GOOD))
        self.assertFalse(h3_native.is_native("[STYLE LOCK] 写实"))


class StageFiveNativeTests(StageFiveQueueTests):
    """沿用第 5 阶段队列测试的替身，视频模型换成 MiniMax H3。"""

    def _h3_task(self):
        task = _task(2)
        task["config"]["video_model"] = "MiniMax-H3"
        task["config"].pop("video_granularity", None)
        return task

    def test_an_h3_board_is_sent_in_the_official_six_section_format(self):
        seen = []

        def call_llm(model, system, user, *args, **kwargs):
            seen.append(user)
            job_lines = [line for line in user.splitlines() if line.startswith("- ") and line != "- 无台词"]
            dialogue = " ".join(f"(S1) says: <d>[Chinese] {line[2:]}</d>" for line in job_lines)
            mentions = " ".join(sorted(set(__import__("re").findall(r"@\[[^\]]+\]", user))))
            mentions += " " + " ".join(sorted(set(__import__("re").findall(r"<Ref \d+>", user))))
            return (
                f"subject_definitions: <Subject 1> is {mentions}. <Frame 1> is the storyboard reference for [Shot 1], defining viewpoint, "
                "subject placement and composition. <Frame 2> is the storyboard reference for [Shot 2], defining viewpoint, subject placement and composition.\n\n"
                "summary: [reference generation] A man pushes the door open.\n\n"
                "retention_analysis: <Subject 1> fully_preserved.\n\n"
                f"detailed_description: [Shot 1] He enters. {dialogue} [Shot 2] At {h3_native.shot_starts([3, 3], 6)[1]}, the shot transitions to his face.\n\n"
                "overall_soundscape: A chain clinks softly.\n\nnon_diegetic_music: N/A"
            )

        prompts: list[str] = []
        with patch.object(self.service.gateway, "call_llm", side_effect=call_llm):
            stored = self._run(self._h3_task(), on_video=prompts.append)
        self.assertEqual(len(seen), 1, "一个分镜片段改写一次")
        self.assertTrue(prompts[0].startswith("subject_definitions:"))
        self.assertIn("<Picture 1> is the storyboard reference for [Shot 1]", prompts[0])
        self.assertNotIn("<Frame", prompts[0])
        self.assertNotIn("@[", prompts[0])
        self.assertNotIn("[STYLE LOCK]", prompts[0])
        [clip] = stored["assets"]["5"]
        # 片上记的就是真正发出去的那一份，也只记这一份。
        self.assertEqual(clip["sent_prompt"], prompts[0])
        self.assertNotIn("native_prompt", clip)
        self.assertNotIn("prompt_sent", clip["video_route_decision"])

    def test_a_conversion_that_fails_the_checks_sends_the_chinese_prompt(self):
        prompts: list[str] = []
        with patch.object(self.service.gateway, "call_llm", return_value="not the six sections"):
            stored = self._run(self._h3_task(), on_video=prompts.append)
        self.assertIn("【镜头1/2", prompts[0])
        self.assertEqual(stored["assets"]["5"][0]["sent_prompt"], prompts[0])

    def test_the_switch_turns_the_conversion_off(self):
        with patch.dict("os.environ", {"H3_NATIVE_PROMPTS": "0"}), \
             patch.object(self.service.gateway, "call_llm", side_effect=AssertionError("must not convert")):
            stored = self._run(self._h3_task())
        self.assertFalse(stored["assets"]["5"][0]["sent_prompt"].startswith("subject_definitions:"))

    # 父类的逐镜测试在本类里不重复跑。
    test_shots_are_generated_under_the_video_ceiling_and_the_queue_is_persisted = None
    test_a_queued_shot_can_be_withdrawn_while_another_runs_and_the_finished_ones_are_kept = None
    test_the_queue_api_lists_items_and_refuses_to_cancel_a_running_one = None
    test_a_restart_requeues_items_a_dead_run_left_running = None
    test_a_provider_that_returns_no_clip_fails_the_shot_with_its_reason = None
    test_a_rerun_reuses_clips_without_regenerating_their_end_frames = None
    test_a_board_whose_frame_is_judged_sensitive_is_retried_without_the_frames = None
    test_identity_references_prefer_local_views_over_expiring_sheet_links = None


class UnsentPromptCleanupTests(unittest.TestCase):
    def _assets(self):
        return {
            "3_negative_prompt_modules": ["a"], "4_negative_prompt_modules": ["b"],
            "5": [{
                "shot_id": 1, "motion_prompt": "原文", "sent_prompt": "中文版", "native_prompt": "subject_definitions: x",
                "contract_motion_prompt": "契约", "agent_policy": "简报", "negative_prompt_modules": ["c"],
                "video_route_decision": {"mode": "multi_reference", "prompt_sent": "subject_definitions: x"},
                "video_url": "/media/a.mp4",
            }, "not a clip"],
            "6": {"agent_policy": "音频", "negative_prompt_modules": ["d"], "audio_url": "/a.mp3", "learned_lessons": "教训"},
            "7": {"agent_policy": "合成", "negative_prompt_ledger": {"x": 1}, "final_video_url": "/f.mp4"},
            "8": {"agent_policy": "宣发", "short_link": "/s"},
        }

    def test_an_older_project_keeps_what_was_sent_and_loses_the_rest(self):
        from app.service.drama_service import drop_unsent_prompts

        assets = self._assets()
        drop_unsent_prompts(assets)
        clip = assets["5"][0]
        self.assertEqual(clip["sent_prompt"], "subject_definitions: x")
        self.assertEqual(clip["motion_prompt"], "原文")
        self.assertEqual(clip["video_url"], "/media/a.mp4")
        for field in ("native_prompt", "contract_motion_prompt", "agent_policy", "negative_prompt_modules"):
            self.assertNotIn(field, clip)
        self.assertEqual(clip["video_route_decision"], {"mode": "multi_reference"})
        self.assertEqual(assets["6"], {"audio_url": "/a.mp3", "learned_lessons": "教训"})
        self.assertEqual(assets["7"], {"final_video_url": "/f.mp4"})
        self.assertEqual(assets["8"], {"short_link": "/s"})
        self.assertNotIn("3_negative_prompt_modules", assets)
        self.assertNotIn("4_negative_prompt_modules", assets)

    def test_board_prompts_the_video_model_never_receives_are_dropped_and_the_rest_stays(self):
        from app.service.drama_service import drop_unsent_prompts

        detail = {
            "duration_seconds": 8, "beats": [{"index": 1}], "foundation": {"a": 1},
            "continuity_checks": [{"code": "ok", "passed": True}],
            "still_prompts": [{"prompt": "静帧"}], "video_segments": [{"prompt": "运镜"}], "grid_pages": [{"composite_prompt": "合成"}],
        }
        kept = {"duration_seconds": 8, "beats": [{"index": 1}], "foundation": {"a": 1}, "continuity_checks": [{"code": "ok", "passed": True}]}
        assets = {"4_prompt_detail": dict(detail), "4_scene_boards": {"E1S01": {"status": "done", "prompt_detail": dict(detail)}, "x": "odd"}}
        drop_unsent_prompts(assets)
        self.assertEqual(assets["4_prompt_detail"], kept)
        self.assertEqual(assets["4_scene_boards"]["E1S01"]["prompt_detail"], kept)
        self.assertEqual(assets["4_scene_boards"]["x"], "odd")

    def test_a_board_drawn_now_stores_no_prompt_the_model_never_receives(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from app.repository.task_repo import TaskRepository
        from app.service.drama_service import DramaService
        from tests.test_storyboard_scene_parallel import _Providers, _task

        providers = _Providers(delay=0)
        task = _task("detail-1")
        with tempfile.TemporaryDirectory() as temp:
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            service.repo.save_task("detail-1", task)
            with patch.object(service.gateway, "call_llm", side_effect=providers.llm), \
                    patch.object(service.gateway, "generate_image", side_effect=providers.image), \
                    patch.object(service.gateway, "validate_image_request", create=True), \
                    patch("app.service.drama_service.load_storyboard_elements", return_value=[]), \
                    patch("app.service.drama_service.persist_storyboard_frame", return_value=None), \
                    patch("app.service.drama_service.compose_nine_grid", lambda sources, path: path), \
                    patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
                service._execute_stage_blocking("detail-1", 4, _claimed_task=task)
            stored = service.repo.get_task("detail-1")["assets"]
        detail = stored["4_scene_boards"]["E1S01"]["prompt_detail"]
        for section in ("still_prompts", "video_segments", "grid_pages"):
            self.assertNotIn(section, detail)
            self.assertNotIn(section, stored["4_prompt_detail"])
        self.assertTrue(detail["beats"])
        self.assertTrue(detail["continuity_checks"])
        self.assertIn("passed", stored["4_scene_boards"]["E1S01"]["continuity"])

    def test_a_second_pass_changes_nothing_and_odd_shapes_are_left_alone(self):
        from app.service.drama_service import drop_unsent_prompts

        assets = self._assets()
        drop_unsent_prompts(assets)
        once = json.loads(json.dumps(assets))
        drop_unsent_prompts(assets)
        self.assertEqual(assets, once)
        drop_unsent_prompts(None)
        odd = {"5": "text", "6": "text"}
        drop_unsent_prompts(odd)
        self.assertEqual(odd, {"5": "text", "6": "text"})


if __name__ == "__main__":
    unittest.main()


class FitTests(unittest.TestCase):
    def test_a_prompt_within_the_limit_is_sent_as_is(self):
        self.assertEqual(h3_native.fit("短。", plain="短。"), "短。")

    def test_an_overlong_prompt_falls_back_to_the_text_before_the_appended_words(self):
        plain = "一句。" * 2000                       # 6000 字符
        sent = h3_native.fit(plain + "负面词" * 500, plain=plain)
        self.assertEqual(sent, plain)

    def test_a_prompt_too_long_even_without_appended_words_is_cut_at_a_sentence_end(self):
        plain = "这一句有十个字符呢。" * 800            # 8000 字符
        sent = h3_native.fit(plain + "负面词", plain=plain)
        self.assertLessEqual(len(sent), h3_native.MAX_CHARS)
        self.assertTrue(sent.endswith("。"))
        self.assertGreater(len(sent), h3_native.MAX_CHARS - 20)

# -*- coding: utf-8 -*-
"""可拍性在剧本阶段就质检：视频提示词里放不下的那几条通用约束(Seedance 2.0 的 2000 字)，剧本写的时候就要满足。"""

import unittest

from app.core.screenwriting import filmability
from app.core.screenwriting.prompts import build_outline_plan_prompt
from app.core.screenwriting.violations import PlanCheckContext, check_script_plan


def _scene(description, scene_id="E1S01"):
    return {"scene_id": scene_id, "duration_seconds": 8, "characters_in_scene": ["沈砚"], "scene_description": description, "utterances": []}


def _ctx(kind="outline"):
    return PlanCheckContext(episode=1, supported_durations=[4, 8, 12], character_names=["沈砚"], source_kind=kind)


class RuleTest(unittest.TestCase):
    def test_each_rule_catches_what_a_video_model_cannot_film(self):
        cases = {
            "她打开信，信上写着「快走」": "on_screen_text",
            "他瞬间变成一只白狐": "sudden_transformation",
            "沈砚凭空出现在门口": "teleport",
            "她换上嫁衣推门而出": "costume_change_in_shot",
            "沈砚站在白底前摆出造型": "posed_shot",
            "他使出分身术，两个沈砚同时出剑": "same_person_twice",
            "画面变成游戏画面": "style_conflict",
        }
        for text, code in cases.items():
            self.assertIn(code, [p.code for p in filmability.scene_problems({"scene_description": text})], text)

    def test_a_change_written_with_its_process_and_an_ordinary_shot_pass(self):
        self.assertEqual(filmability.scene_problems({"scene_description": "他的身形从指尖开始，逐渐化作流光"}), [])
        self.assertEqual(filmability.scene_problems({"scene_description": "沈砚推门而入，铁链垂落"}), [])

    def test_spoken_lines_are_heard_not_seen(self):
        self.assertEqual(filmability.scene_problems({"scene_description": "沈砚低头看信", "utterances": [{"text": "信上写着快走"}]}), [])


class PlanCheckTest(unittest.TestCase):
    def test_an_authored_shot_that_cannot_be_filmed_goes_back(self):
        result = check_script_plan([_scene("她打开信，信上写着「快走」")], _ctx())
        self.assertEqual([v.code for v in result.errors], ["on_screen_text"])
        self.assertIn("念出来", str(result.errors[0]))

    def test_an_uploaded_screenplay_is_only_flagged(self):
        result = check_script_plan([_scene("她打开信，信上写着「快走」")], _ctx("screenplay"))
        self.assertEqual(result.errors, [])
        self.assertEqual([v.code for v in result.warnings], ["on_screen_text"])

    def test_soft_problems_stay_warnings(self):
        result = check_script_plan([_scene("她换上嫁衣推门而出")], _ctx())
        self.assertEqual(result.errors, [])
        self.assertIn("costume_change_in_shot", [v.code for v in result.warnings])


class EarlyCheckTest(unittest.TestCase):
    def test_the_outline_is_checked_as_soon_as_it_is_planned(self):
        reasons = filmability.beat_problems(["沈砚回府", "密信上写着「速逃」", "他瞬移到城外"], label="第 1 集")
        self.assertEqual(len(reasons), 2)
        self.assertTrue(reasons[0].startswith("第 1 集故事节点 2·画面文字"))
        self.assertEqual(filmability.beat_problems(["她换上嫁衣"], label="第 1 集"), [], "only error-level rules hold up an outline")

    def test_the_writers_are_told_the_rules_up_front(self):
        prompt = build_outline_plan_prompt(title="雪夜", director_plan="方案", overview={}, first=1, last=1, total=1,
                                           context_entries=[], target_seconds=None, instructions=None)
        self.assertIn(filmability.writing_rule(), prompt)
        from app.core.screenwriting.prompts import build_script_plan_prompt
        from tests.test_dialogue_pacing import COMMON

        for kind in ("outline", "novel", "screenplay"):
            shots = build_script_plan_prompt(source_text="原文", source_kind=kind, **COMMON)
            self.assertIn(filmability.writing_rule(), shots, kind)


if __name__ == "__main__":
    unittest.main()

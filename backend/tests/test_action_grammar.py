# -*- coding: utf-8 -*-
"""Continuing an action: catch the previous ending, then say the next step; complex actions in four parts."""

import unittest

from app.core import action_grammar as grammar
from app.core import slice_video


class EndingTests(unittest.TestCase):
    def test_a_labelled_ending_wins_over_the_last_sentence(self):
        text = "林夏推门进来。落幅：她停在门边，右手还搭在门把上，面向画右。镜头：固定。"
        self.assertTrue(grammar.ending_of(text).startswith("她停在门边"))

    def test_otherwise_the_last_sentence(self):
        self.assertEqual(grammar.ending_of("林夏推门进来。她走到桌边坐下。"), "她走到桌边坐下。")

    def test_a_too_short_last_sentence_takes_the_one_before(self):
        self.assertEqual(grammar.ending_of("她走到桌边坐下。完。"), "她走到桌边坐下。完。")

    def test_long_endings_are_trimmed_and_empty_is_empty(self):
        self.assertTrue(grammar.ending_of("x" * 400).endswith("…"))
        self.assertEqual(grammar.ending_of(""), "")

    def test_continuation_catches_the_ending_then_says_the_next_step(self):
        text = grammar.continuation_text("她走到桌边坐下。", "她抬头看向窗外")
        self.assertEqual(text, "接住上一段结尾：她走到桌边坐下。接下来：她抬头看向窗外")
        self.assertEqual(grammar.continuation_text("", "她抬头"), "她抬头")


class ConcreteEndingTests(unittest.TestCase):
    def test_a_placeholder_is_not_an_ending(self):
        self.assertEqual(grammar.concrete_ending("落幅：形成下一格可承接的可见状态"), "")
        self.assertEqual(grammar.concrete_ending("落幅：他背靠墙滑坐在地。"), "他背靠墙滑坐在地。")

    def test_a_continued_prompt_ends_on_its_own_next_step_not_on_what_it_caught(self):
        chained = grammar.continuation_text("他在巷口停住，手撑着墙喘气。", "他转身冲出巷口，一头撞上来人")
        self.assertEqual(grammar.ending_of(chained), "他转身冲出巷口，一头撞上来人")


class BreakdownTests(unittest.TestCase):
    def test_the_prompt_asks_for_the_four_parts_and_carries_the_previous_ending(self):
        prompt = grammar.breakdown_prompt("转身拔刀劈下", previous_ending="她背对门站着")
        for part in grammar.ACTION_PARTS:
            self.assertIn(part, prompt)
        self.assertIn("她背对门站着", prompt)
        with self.assertRaises(ValueError):
            grammar.breakdown_prompt("  ")

    def test_a_full_answer_is_kept_in_order_and_a_partial_one_is_refused(self):
        answer = "结束姿态：刀尖指地，重心在前脚\n起始姿态：背对门，重心在右脚\n主动作：右手拔刀，向左劈下\n身体联动：左脚上步，躯干左转，视线跟刀"
        parsed = grammar.parse_breakdown(answer)
        self.assertTrue(parsed.startswith("起始姿态："))
        self.assertTrue(parsed.endswith("刀尖指地，重心在前脚"))
        with self.assertRaises(ValueError) as refused:
            grammar.parse_breakdown("起始姿态：站着\n主动作：劈")
        self.assertIn("身体联动", str(refused.exception))

    def test_has_structure(self):
        self.assertTrue(grammar.has_structure("起始姿态：a 主动作：b 身体联动：c 结束姿态：d"))
        self.assertFalse(grammar.has_structure("转身拔刀"))


class SlicePromptTests(unittest.TestCase):
    def beat(self):
        return slice_video.Beat(sections={"subject": "动作：她推门", "end_state": "落幅：她停在门边，右手搭在门把上"}, size="中景", motion="固定")

    def test_the_second_part_names_the_first_parts_ending(self):
        compiled = slice_video.compile_prompt([self.beat()], model="m", part=2, parts=2, previous_end="落幅：她停在门边，右手搭在门把上")
        self.assertIn("上一段结尾：她停在门边，右手搭在门把上", compiled.text)
        self.assertIn("不重新起势", compiled.text)

    def test_without_an_ending_it_still_says_it_continues(self):
        compiled = slice_video.compile_prompt([self.beat()], model="m", part=2, parts=2)
        self.assertIn("从上一段的落幅接着往下演", compiled.text)

    def test_the_first_part_says_nothing_about_a_previous_part(self):
        compiled = slice_video.compile_prompt([self.beat()], model="m", part=1, parts=2, previous_end="落幅：x")
        self.assertNotIn("上一段结尾", compiled.text)


class SingleBeatPartTests(unittest.TestCase):
    @staticmethod
    def _compiled():
        sections = {"structure": "【结构声明】单镜连续画面，一镜到底不切 + 画幅9:16。", "subject": "他冲出巷口"}
        return slice_video.render(sections, model="seedance", beats=1, style_pack="pack")

    def test_the_part_says_what_it_catches(self):
        compiled = slice_video.continue_single(self._compiled(), model="seedance", part=2, parts=3, previous_end="落幅：他手撑着墙喘气。")
        self.assertIn("画幅9:16 + 本段是该场戏的第2/3段，上一段结尾：他手撑着墙喘气；本段从这个状态接住再往下演", compiled.text)
        self.assertEqual(compiled.style_pack, "pack")
        self.assertIn("他冲出巷口", compiled.text)

    def test_a_placeholder_ending_falls_back_to_the_plain_line(self):
        compiled = slice_video.continue_single(self._compiled(), model="seedance", part=2, parts=2, previous_end="形成下一格可承接的可见状态")
        self.assertIn("从上一段的落幅接着往下演", compiled.text)
        self.assertNotIn("形成下一格", compiled.text)


if __name__ == "__main__":
    unittest.main()

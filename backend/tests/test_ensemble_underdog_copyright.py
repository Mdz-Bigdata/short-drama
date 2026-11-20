"""Additions from the 2026-11-16 articles: staging five or more people, neck-snap wording after a refusal, and what to do
when a clip is refused for copyright. (A smaller-fighter block was added and taken out again after a blind comparison.)"""

import unittest

from app.core import fight_safety, group_blocking, prompt_data, video_failures


class EnsembleStagingTest(unittest.TestCase):
    def test_five_or_more_people_get_the_ensemble_formula_and_fewer_do_not(self):
        five = prompt_data.value("group_blocking", "formulas")["5"]
        self.assertIn(five, group_blocking.brief(5))
        self.assertIn(five, group_blocking.brief(12))
        self.assertNotIn(five, group_blocking.brief(4))
        self.assertEqual(len(group_blocking.brief(3).splitlines()), 5)

    def test_the_formula_asks_for_blocks_and_an_exact_head_count(self):
        five = prompt_data.value("group_blocking", "formulas")["5"]
        for words in ("两到三个视觉团块", "长桌", "两个阵营", "唯一异类", "写明人数", "没有第"):
            self.assertIn(words, five)


class NeckSnapWordingTest(unittest.TestCase):
    def test_a_snapped_neck_is_rewritten_only_after_a_refusal(self):
        text = "她双腿锁住他的脖子，拧断脖子"
        self.assertIn("拧断脖子", fight_safety.clean_gore(text))
        softened = fight_safety.soften(text)
        self.assertNotIn("拧断脖子", softened)
        self.assertIn("头部失去支撑", softened)


class CopyrightRefusalTest(unittest.TestCase):
    def test_a_copyright_refusal_gets_advice_about_wording(self):
        for message in ("task failed: code=2053 OutputVideoCopyright", "Ark HTTP 400 OutputVideoCopyrightDetected", "生成内容涉及版权"):
            with self.subTest(message=message):
                hint = video_failures.hint({"kind": "provider_error", "message": message})
                self.assertEqual(hint, prompt_data.text("video_failures", "hint.copyright"))

    def test_other_refusals_keep_their_hints(self):
        self.assertEqual(video_failures.hint({"kind": "provider_error", "message": "HTTP 500 InternalError"}),
                         prompt_data.text("video_failures", "hint.text.4"))
        sensitive = video_failures.hint({"kind": video_failures.INPUT_IMAGE_SENSITIVE, "message": "copyright", "scene_id": "E1S02"})
        self.assertNotEqual(sensitive, prompt_data.text("video_failures", "hint.copyright"))


if __name__ == "__main__":
    unittest.main()

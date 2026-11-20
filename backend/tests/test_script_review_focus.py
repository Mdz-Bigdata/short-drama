# -*- coding: utf-8 -*-
"""剧本审核的两项专项体检：前三集主线体检、台词对照人物小传。"""

from __future__ import annotations

import json
import unittest

from app.core import prompt_data, script_review
from app.core.script_review import ScriptReviewError

from tests.test_submission_pack import SCENES, Scripted, _task

WORDING = prompt_data.load("script_review")


def _keys(focus):
    return [item["key"] for item in next(item for item in WORDING["focuses"] if item["key"] == focus)["dimensions"]]


def _answer(focus, findings=(), verdicts=None):
    verdicts = verdicts or {}
    return json.dumps({
        "summary": "主角是谁立住了，冲突还只在嘴上。",
        "dimensions": [{"key": key, "verdict": verdicts.get(key, "pass"), "note": f"{key} 的说明"} for key in _keys(focus)],
        "findings": list(findings), "strengths": [],
    }, ensure_ascii=False)


def _many(count):
    """A series of ``count`` one-scene episodes built from the fixture's first scene."""
    return [dict(SCENES[0], scene_id=f"E{number}S01") for number in range(1, count + 1)]


class CatalogTests(unittest.TestCase):
    def test_the_full_review_comes_first_and_each_check_has_its_own_place_to_be_kept(self):
        self.assertEqual([item["key"] for item in script_review.focuses()], ["", "opening", "voice"])
        self.assertEqual(script_review.asset_key(), script_review.ASSET_KEY)
        self.assertEqual(script_review.asset_key("opening"), f"{script_review.ASSET_KEY}_opening")
        with self.assertRaises(ScriptReviewError):
            script_review.asset_key("nope")

    def test_the_default_request_still_reads_seven_aspects(self):
        _, user = script_review.block_prompts(script_review.episodes_of(_task(), SCENES), total=2)
        self.assertIn("【七个方面】", user)
        self.assertIn("dimensions 里七个方面各写一条", user)
        self.assertNotIn("人物小传", user)


class OpeningTests(unittest.TestCase):
    def test_only_the_first_three_episodes_are_read_and_the_request_says_so(self):
        task, scenes = _task(episodes=5), _many(5)
        self.assertEqual([episode["episode"] for episode in script_review.reviewed(task, scenes, "opening")], [1, 2, 3])
        self.assertEqual(len(script_review.reviewed(task, scenes)), 5)
        model = Scripted(_answer("opening", verdicts={"core_conflict": "revise"}))
        written = script_review.write(model, task, scenes, max_tokens=4000, focus="opening")
        user = model.calls[0][1]
        for piece in ("前 3 集（全剧共 5 集，这次只审这几集）", "【三个方面】", "identity（主角身份）", "core_conflict（核心冲突）", "expectation（观众期待）"):
            self.assertIn(piece, user)
        self.assertNotIn("logic（故事逻辑）", user)
        self.assertEqual([item["key"] for item in written["dimensions"]], _keys("opening"))
        self.assertEqual(written["focus"], "opening")

    def test_a_change_after_the_third_episode_does_not_make_it_stale(self):
        task, scenes = _task(episodes=5), _many(5)
        task["assets"][script_review.asset_key("opening")] = script_review.write(Scripted(_answer("opening")), task, scenes, max_tokens=4000, focus="opening")
        later = [*scenes[:4], dict(scenes[4], description="结局改了。")]
        self.assertFalse(script_review.view(task, later, focus="opening")["stale"])
        earlier = [dict(scenes[0], description="开场改了。"), *scenes[1:]]
        self.assertTrue(script_review.view(task, earlier, focus="opening")["stale"])
        # The full review is kept apart: there is none yet.
        self.assertIsNone(script_review.view(task, scenes)["report"])

    def test_an_answer_with_the_full_reviews_aspects_is_sent_back(self):
        seven = json.dumps({"summary": "", "dimensions": [{"key": item["key"], "verdict": "pass", "note": ""} for item in WORDING["dimensions"]],
                            "findings": [], "strengths": []}, ensure_ascii=False)
        model = Scripted(seven, _answer("opening"))
        script_review.write(model, _task(), SCENES, max_tokens=4000, focus="opening")
        self.assertIn("dimensions 要三个方面各一条", model.calls[1][1])

    def test_a_short_series_is_read_whole(self):
        model = Scripted(_answer("opening"))
        script_review.write(model, _task(), SCENES, max_tokens=4000, focus="opening")
        self.assertIn("整部剧本，共 2 集", model.calls[0][1])


class VoiceTests(unittest.TestCase):
    def test_the_lines_are_held_against_the_character_sheet(self):
        finding = {"dimension": "voice", "severity": "medium", "scene": "1-1", "quote": "有人吗？", "issue": "实习研究员深夜进实验室不会这样喊", "fix": "改成压低声音的「周老师？」"}
        model = Scripted(_answer("voice", findings=[finding], verdicts={"voice": "revise"}))
        written = script_review.write(model, _task(), SCENES, max_tokens=4000, focus="voice")
        user = model.calls[0][1]
        for piece in ("【人物小传", "- 林夏：二十六岁的实习研究员", "- 周教授：实验室主任", "【一个方面】", "voice（台词与人设）", "改法直接给出改后的这一句"):
            self.assertIn(piece, user)
        self.assertEqual(written["findings"][0]["quote"], "有人吗？")
        shown = script_review.view({**_task(), "assets": {**_task()["assets"], script_review.asset_key("voice"): written}}, SCENES, focus="voice")
        self.assertEqual((shown["label"], shown["report"]["findings"][0]["dimension_label"], shown["blocked"]), ("台词对照人物小传", "台词与人设", ""))
        self.assertIn("《暗室回声》台词对照人物小传", script_review.render_markdown(shown))

    def test_a_changed_character_sheet_makes_the_check_stale(self):
        task = _task()
        task["assets"][script_review.asset_key("voice")] = script_review.write(Scripted(_answer("voice")), task, SCENES, max_tokens=4000, focus="voice")
        self.assertFalse(script_review.view(task, SCENES, focus="voice")["stale"])
        task["assets"]["2_screenwriting"]["inventory"]["characters"]["林夏"]["description"] = "四十岁的刑警"
        self.assertTrue(script_review.view(task, SCENES, focus="voice")["stale"])

    def test_without_a_character_sheet_the_check_is_blocked_and_no_model_is_called(self):
        task = _task()
        task["assets"]["2_screenwriting"]["inventory"]["characters"] = {}
        self.assertIn("人物小传", script_review.view(task, SCENES, focus="voice")["blocked"])
        model = Scripted(_answer("voice"))
        with self.assertRaises(ScriptReviewError):
            script_review.write(model, task, SCENES, max_tokens=4000, focus="voice")
        self.assertEqual(model.calls, [])


if __name__ == "__main__":
    unittest.main()

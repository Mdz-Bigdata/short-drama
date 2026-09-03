# -*- coding: utf-8 -*-
"""The shot-design skill states rules in the prompt; these tests pin the enforcement.

A prompt is a request, not a guarantee — models still answer with a 110s "shot",
an abstract emotion word, or five identical medium shots in a row.
"""
import unittest

from app.core.shot_table_rules import (
    MIN_DESC_CHARS,
    audit_and_log,
    audit_shot_table,
)
from app.core.video_references import MIN_SHOT_SECONDS


def _shot(**overrides):
    shot = {
        "shot_id": 1,
        "size": "中景",
        "duration": "8s",
        "desc": "陈九站在祭坛边，火把照亮他的侧脸，指节扣紧火把木柄，肩背绷直，袍角垂落没有一丝晃动，眼神冷得没有波澜。",
    }
    shot.update(overrides)
    return shot


def _rules(audit):
    return {issue.rule for issue in audit.issues}


class CleanTableTests(unittest.TestCase):
    def test_a_compliant_table_raises_nothing(self):
        shots = [
            _shot(shot_id=1, size="全景"),
            _shot(shot_id=2, size="中景"),
            _shot(shot_id=3, size="特写"),
        ]

        audit = audit_shot_table(shots, video_model="seedance2.0")

        self.assertTrue(audit.ok, audit.summary())
        self.assertEqual(audit.repaired, 0)
        self.assertIn("通过全部硬性规则", audit.summary())


class DurationRuleTests(unittest.TestCase):
    def test_an_over_long_shot_is_flagged_and_repaired(self):
        audit = audit_shot_table([_shot(duration="110s"), _shot(shot_id=2, size="全景")],
                                 video_model="seedance2.0")

        self.assertIn("时长超模型上限", _rules(audit))
        self.assertEqual(audit.repaired, 1)
        self.assertEqual(audit.shots[0]["duration"], "14s")

    def test_the_ceiling_follows_the_selected_model(self):
        for model, flagged in (("seedance2.0", True), ("seedance2.5", False)):
            audit = audit_shot_table([_shot(duration="20s"), _shot(shot_id=2, size="全景")],
                                     video_model=model)
            self.assertEqual("时长超模型上限" in _rules(audit), flagged, model)

    def test_repair_can_be_disabled_for_reporting_only(self):
        audit = audit_shot_table([_shot(duration="110s"), _shot(shot_id=2, size="全景")],
                                 video_model="seedance2.0", repair=False)

        self.assertIn("时长超模型上限", _rules(audit))
        self.assertEqual(audit.repaired, 0)
        self.assertEqual(audit.shots[0]["duration"], "110s")

    def test_a_shot_below_the_submission_floor_is_flagged(self):
        audit = audit_shot_table([_shot(duration=f"{MIN_SHOT_SECONDS - 1}s"), _shot(shot_id=2, size="全景")],
                                 video_model="seedance2.0")

        self.assertIn("时长低于下限", _rules(audit))

    def test_a_missing_duration_is_not_treated_as_too_short(self):
        audit = audit_shot_table([_shot(duration=""), _shot(shot_id=2, size="全景")],
                                 video_model="seedance2.0")

        self.assertNotIn("时长低于下限", _rules(audit))


class ShotGrammarRuleTests(unittest.TestCase):
    def test_a_term_outside_the_dictionary_is_flagged(self):
        audit = audit_shot_table([_shot(size="超级景"), _shot(shot_id=2, size="全景")],
                                 video_model="seedance2.0")

        self.assertIn("景别不在词典内", _rules(audit))

    def test_english_abbreviations_are_accepted(self):
        for size in ("MS", "ECU", "OTS", "POV", "ews"):
            audit = audit_shot_table([_shot(size=size), _shot(shot_id=2, size="全景")],
                                     video_model="seedance2.0")
            self.assertNotIn("景别不在词典内", _rules(audit), size)

    def test_three_identical_sizes_in_a_row_are_flagged(self):
        shots = [_shot(shot_id=index, size="中景") for index in (1, 2, 3)]

        audit = audit_shot_table(shots, video_model="seedance2.0")

        self.assertIn("同景别连续堆叠", _rules(audit))

    def test_two_in_a_row_is_still_allowed(self):
        shots = [_shot(shot_id=1, size="中景"), _shot(shot_id=2, size="中景"), _shot(shot_id=3, size="特写")]

        audit = audit_shot_table(shots, video_model="seedance2.0")

        self.assertNotIn("同景别连续堆叠", _rules(audit))

    def test_the_run_counter_resets_after_a_different_size(self):
        shots = [
            _shot(shot_id=1, size="中景"), _shot(shot_id=2, size="中景"),
            _shot(shot_id=3, size="全景"),
            _shot(shot_id=4, size="中景"), _shot(shot_id=5, size="中景"),
        ]

        audit = audit_shot_table(shots, video_model="seedance2.0")

        self.assertNotIn("同景别连续堆叠", _rules(audit))


class WritingRedlineTests(unittest.TestCase):
    def test_inner_monologue_is_an_error(self):
        audit = audit_shot_table(
            [_shot(desc="小六心想他一定会回来的，于是站在原地一直等着，等到天色完全暗下来才肯离开这条长街。"),
             _shot(shot_id=2, size="全景")],
            video_model="seedance2.0",
        )

        self.assertIn("出现心理描写", _rules(audit))
        self.assertTrue(any(i.severity == "error" for i in audit.issues if i.rule == "出现心理描写"))

    def test_an_abstract_emotion_without_a_body_cue_is_flagged(self):
        audit = audit_shot_table(
            [_shot(desc="他很愤怒地看着对方，然后转身离开了这个地方，周围一片安静没有任何声响传来。"),
             _shot(shot_id=2, size="全景")],
            video_model="seedance2.0",
        )

        self.assertIn("情绪未具象化", _rules(audit))

    def test_the_same_emotion_with_a_body_cue_passes(self):
        audit = audit_shot_table(
            [_shot(desc="他愤怒地盯着对方，下颌绷紧，鼻翼张开，指节攥得发白，肩背前倾像随时要扑上去，呼吸变得粗重。"),
             _shot(shot_id=2, size="全景")],
            video_model="seedance2.0",
        )

        self.assertNotIn("情绪未具象化", _rules(audit))

    def test_a_short_description_is_flagged(self):
        audit = audit_shot_table([_shot(desc="他转身"), _shot(shot_id=2, size="全景")],
                                 video_model="seedance2.0")

        issue = next(i for i in audit.issues if i.rule == "画面内容过短")
        self.assertIn(str(MIN_DESC_CHARS), issue.detail)


class TableShapeTests(unittest.TestCase):
    def test_a_single_shot_episode_is_an_error(self):
        audit = audit_shot_table([_shot()], video_model="seedance2.0")

        self.assertIn("整集仅一个镜头", _rules(audit))

    def test_malformed_rows_are_skipped_not_fatal(self):
        audit = audit_shot_table(["not a dict", None, _shot(), _shot(shot_id=2, size="全景")],
                                 video_model="seedance2.0")

        self.assertEqual(len(audit.shots), 2)

    def test_an_empty_table_is_handled(self):
        audit = audit_shot_table([], video_model="seedance2.0")

        self.assertEqual(audit.shots, [])
        self.assertTrue(audit.ok)

    def test_audit_and_log_returns_the_repaired_shots(self):
        shots = audit_and_log([_shot(duration="110s"), _shot(shot_id=2, size="全景")],
                              video_model="seedance2.0", task_id="t1")

        self.assertEqual(shots[0]["duration"], "14s")
        self.assertEqual(len(shots), 2)

    def test_the_original_shot_dicts_are_not_mutated(self):
        original = _shot(duration="110s")

        audit_shot_table([original, _shot(shot_id=2, size="全景")], video_model="seedance2.0")

        self.assertEqual(original["duration"], "110s")


class DictionaryAlignmentTests(unittest.TestCase):
    def test_the_size_terms_come_from_the_skill_dictionary(self):
        from app.core.shot_design_skill import SKILL_ROOT
        from app.core.shot_table_rules import SHOT_SIZE_TERMS

        grammar = (SKILL_ROOT / "references" / "shot-grammar.md").read_text(encoding="utf-8")

        # Every Chinese term the validator accepts must be documented in the skill.
        for term in SHOT_SIZE_TERMS:
            if term.isascii():
                continue
            self.assertIn(term, grammar, f"{term} 不在技能的景别词典里")


if __name__ == "__main__":
    unittest.main()

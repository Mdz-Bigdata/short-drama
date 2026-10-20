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


class TensionAndFrameRuleTests(unittest.TestCase):
    def test_character_shots_without_screen_coordinates_are_flagged(self):
        audit = audit_shot_table([
            _shot(shot_id=1, characters=["陈九"]),
            _shot(shot_id=2, size="特写", characters=["陈九"],
                  desc="陈九位于画面左侧三分之一的中景，朝向画面右侧，指节扣紧火把木柄，肩背绷直，火光在脸颊侧面切出明暗，眼神冷得没有波澜。"),
        ], video_model="seedance2.0")
        flagged = {issue.shot_id for issue in audit.issues if issue.rule == "构图未用镜头坐标"}
        self.assertEqual(flagged, {1})

    def test_an_eyeline_flip_between_adjacent_shots_is_flagged_unless_motivated(self):
        left = "陈九位于画面左侧三分之一的中景，朝向画面右侧，指节扣紧火把木柄，肩背绷直，眼神冷得没有波澜，火光在侧脸切出明暗。"
        right = "陈九位于画面右侧三分之一的中景，朝向画面左侧，指节扣紧火把木柄，肩背绷直，眼神冷得没有波澜，火光在侧脸切出明暗。"
        audit = audit_shot_table([
            _shot(shot_id=1, characters=["陈九"], desc=left),
            _shot(shot_id=2, size="近景", characters=["陈九"], desc=right),
            _shot(shot_id=3, size="特写", characters=["陈九"], desc="陈九转身，" + left),
        ], video_model="seedance2.0")
        flagged = {issue.shot_id for issue in audit.issues if issue.rule == "视线左右翻转"}
        self.assertEqual(flagged, {2})

    def test_too_many_moving_shots_and_unprepared_bursts_are_flagged(self):
        moving = [_shot(shot_id=i, size=size, motion="推镜", duration="2s") for i, size in enumerate(("全景", "中景", "特写", "近景"), start=1)]
        moving.append(_shot(shot_id=5, size="全景", motion="固定镜头", duration="2s",
                            desc="陈九挥剑劈向门柱，木屑飞溅，火把翻滚落地，肩背绷直，指节扣紧剑柄，眼神冷得没有波澜。"))
        audit = audit_shot_table(moving, video_model="seedance2.0")
        self.assertIn("运镜过密", _rules(audit))
        self.assertIn("爆发前缺少静置蓄力", _rules(audit))

        prepared = [
            _shot(shot_id=1, size="全景", motion="固定镜头", duration="4s"),
            _shot(shot_id=2, size="特写", motion="推镜", duration="2s",
                  desc="陈九挥剑劈向门柱，木屑飞溅，火把翻滚落地，肩背绷直，指节扣紧剑柄，眼神冷得没有波澜。"),
        ]
        audit = audit_shot_table(prepared, video_model="seedance2.0")
        self.assertNotIn("爆发前缺少静置蓄力", _rules(audit))
        self.assertNotIn("运镜过密", _rules(audit))


class DialogueFitRuleTests(unittest.TestCase):
    """A line has to be sayable inside its own shot, by one person."""

    def test_a_line_longer_than_the_shot_is_flagged(self):
        shot = _shot(
            duration="4s", characters=["林夏"],
            dialogue="林夏：你到底瞒了什么？我等了整整三年，从来没有人给过我一句解释。",
        )

        audit = audit_shot_table([shot, _shot(shot_id=2, size="全景")], video_model="seedance2.5")

        self.assertIn("台词超出本镜时长", _rules(audit))
        detail = next(issue.detail for issue in audit.issues if issue.rule == "台词超出本镜时长")
        self.assertIn("两端各留静默", detail)

    def test_a_line_that_fits_passes(self):
        shot = _shot(duration="8s", characters=["林夏"], dialogue="林夏：你到底瞒了什么？")

        audit = audit_shot_table([shot, _shot(shot_id=2, size="全景")], video_model="seedance2.5")

        self.assertNotIn("台词超出本镜时长", _rules(audit))

    def test_two_speakers_in_one_shot_are_flagged_but_a_quoted_colon_is_not(self):
        two = _shot(characters=["林夏", "周教授"], dialogue="林夏：你说啊。 周教授：够了。")
        quoted = _shot(shot_id=2, size="全景", characters=["林夏"], dialogue="林夏：他说：走。")

        audit = audit_shot_table([two, quoted], video_model="seedance2.5")

        flagged = [issue.shot_id for issue in audit.issues if issue.rule == "一镜多个说话人"]
        self.assertEqual(flagged, [1])


class ShotLoadRuleTests(unittest.TestCase):
    """What one vertical frame can actually hold: people, sound layers, close-ups."""

    def test_a_third_clear_character_is_flagged(self):
        audit = audit_shot_table(
            [_shot(characters=["林夏", "周教授", "助理"]), _shot(shot_id=2, size="全景")],
            video_model="seedance2.5",
        )

        self.assertIn("同框清晰人物过多", _rules(audit))
        self.assertNotIn(
            "同框清晰人物过多",
            _rules(audit_shot_table([_shot(characters=["林夏", "周教授"])], video_model="seedance2.5")),
        )

    def test_sound_layers_are_capped(self):
        noisy = _shot(sound="环境音：空调低鸣·远处车流·钟表滴答；动作音：脚步·纸张·椅子")
        calm = _shot(shot_id=2, size="全景", sound="环境音：空调低鸣·远处车流；动作音：脚步")

        audit = audit_shot_table([noisy, calm], video_model="seedance2.5")

        flagged = [issue.shot_id for issue in audit.issues if issue.rule == "声音层数超标"]
        self.assertEqual(flagged, [1])

    def test_close_ups_are_rationed_and_a_fight_scene_is_stricter(self):
        shots = [
            _shot(shot_id=1, size="特写"), _shot(shot_id=2, size="全景"), _shot(shot_id=3, size="大特写"),
            _shot(shot_id=4, size="中景"), _shot(shot_id=5, size="特写"),
        ]

        drama = audit_shot_table(shots, video_model="seedance2.5")
        fight = audit_shot_table(shots, video_model="seedance2.5", scene_kind="fight")

        self.assertNotIn("特写超配额", _rules(drama))       # 3 close-ups is the drama quota
        self.assertIn("特写超配额", _rules(fight))
        self.assertIn("武戏配额 2", next(issue.detail for issue in fight.issues if issue.rule == "特写超配额"))


class ImpactRuleTests(unittest.TestCase):
    """The two fight rules a model can be held to: no freezes, short bursts."""

    def test_a_frozen_frame_instruction_is_flagged(self):
        shot = _shot(desc="周教授出拳，画面定格在他扭曲的脸上，碎片悬在半空，指节发白，肩膀前压，呼吸粗重。")

        audit = audit_shot_table([shot, _shot(shot_id=2, size="全景")], video_model="seedance2.5")

        self.assertIn("写了模型做不到的定格", _rules(audit))
        self.assertIn("白闪", next(issue.detail for issue in audit.issues if issue.rule == "写了模型做不到的定格"))

    def test_a_burst_shot_may_not_run_long(self):
        long_burst = _shot(duration="8s", desc="周教授出拳砸向桌面，杯子跳起，水花溅开，指节发白，肩膀前压，呼吸粗重起来。")
        short_burst = _shot(shot_id=2, size="全景", duration="4s", desc=long_burst["desc"])

        audit = audit_shot_table([long_burst, short_burst], video_model="seedance2.5")

        flagged = [issue.shot_id for issue in audit.issues if issue.rule == "爆发镜过长"]
        self.assertEqual(flagged, [1])

# -*- coding: utf-8 -*-
"""Reading a shot's dialogue cell: who says what. Stage directions must never reach a voice."""

import unittest

from app.core.spoken_lines import labelled_lines
from app.service.drama_service import cast_genders, dialogue_genders, parse_shot_dialogue, project_leads, project_roster, roster_in_shot

CAST = [
    {"name": "沈无咎", "role": "主角", "desc": "男主角/持拭剑旧布的奴仆；男性，视觉年龄26–30"},
    {"name": "苏问剑", "role": "主角", "desc": "女主角；女性，视觉年龄22–25"},
    {"name": "裴仲玄", "role": "反派", "desc": "男性，视觉年龄50"},
    {"name": "陈九", "role": "配角", "desc": "老仆，须发皆白"},
]


def _read(cell, **kwargs):
    lead, _look, opponent, _opponent_look = project_leads({"3_characters": CAST})
    return parse_shot_dialogue(cell, lead, opponent, *dialogue_genders(CAST, lead, opponent)[:2], genders=cast_genders(CAST), **kwargs)


class LabelledLinesTest(unittest.TestCase):
    def test_a_note_between_the_name_and_the_colon_is_not_spoken(self):
        cell = "裴仲玄（开口前停半拍，语速缓，音量压得低于雨声）：落。／苏问剑（听时眉心先收紧，声音短促发紧）：刀下留人。"
        self.assertEqual(
            [(speaker, line) for speaker, _notes, line in labelled_lines(cell)],
            [("裴仲玄", "落。"), ("苏问剑", "刀下留人。")],
        )

    def test_a_colon_inside_a_note_or_a_quote_is_not_a_speaker(self):
        self.assertEqual(
            [(speaker, line) for speaker, _notes, line in labelled_lines("沈无咎：（语气：低）「主人说：走。」")],
            [("沈无咎", "主人说：走。")],
        )

    def test_notes_are_kept_for_the_voice_to_read(self):
        self.assertEqual(labelled_lines("裴仲玄（冷笑）：落。")[0][1], "冷笑")

    def test_an_unclosed_note_does_not_hide_the_next_speaker(self):
        self.assertIn("沈无咎", [speaker for speaker, _notes, _line in labelled_lines("裴仲玄（语速缓：落。沈无咎：嗯。")])


class ParseCellTest(unittest.TestCase):
    def test_the_real_cells_from_a_project(self):
        self.assertEqual(
            [(segment[3], segment[0], segment[1]) for segment in _read(
                "苏问剑（画左，视线钉住他，停半拍）：站住。 沈无咎（画右，未抬眼，肩背不动）：奴才不敢站。")],
            [("苏问剑", "站住。", "female"), ("沈无咎", "奴才不敢站。", "male")],
        )
        self.assertEqual(
            [(segment[3], segment[0], segment[1]) for segment in _read("裴仲玄：谁？／裴仲玄：谁动的剑？／沈无咎：剑自己动的。")],
            [("裴仲玄", "谁？", "male"), ("裴仲玄", "谁动的剑？", "male"), ("沈无咎", "剑自己动的。", "male")],
        )

    def test_an_unlabelled_line_goes_to_the_lead_and_is_kept_whole(self):
        self.assertEqual(_read("奴才不敢站。")[0][3], "沈无咎")
        self.assertEqual(_read("奴才不敢站。")[0][0], "奴才不敢站。")

    def test_no_line_is_voiced_as_the_word_for_none(self):
        for cell in ("无", "{无}", "沈无咎：无", "（无）"):
            self.assertEqual(_read(cell), [], cell)

    def test_a_note_still_decides_the_emotion(self):
        self.assertEqual(_read("裴仲玄（冷笑）：落。")[0][2], "cold")
        self.assertEqual(_read("（冷笑）落。")[0][2], "cold")

    def test_non_speakers_stay_silent(self):
        self.assertEqual([segment[0] for segment in _read("音效：雷声滚过。沈无咎：走。")], ["走。"])


class CastTest(unittest.TestCase):
    def test_a_card_wins_over_a_guess_from_the_name(self):
        self.assertEqual(cast_genders(CAST), {"沈无咎": "male", "苏问剑": "female", "裴仲玄": "male"})

    def test_the_explicit_word_wins_over_a_relation_to_someone_else(self):
        self.assertEqual(cast_genders([{"name": "阿青", "desc": "男主的师姐；女性"}]), {"阿青": "female"})

    def test_a_gender_nobody_stated_is_still_guessed(self):
        self.assertEqual(dialogue_genders(CAST, "沈无咎", "陈九")[:2], ("male", "female"))


OUTLINE = "- **动作规避**：武侠最大的制作陷阱是打斗。\n- **视觉奇观可做**：剑冢千剑。\n"


class RosterTest(unittest.TestCase):
    def test_cards_replace_names_picked_out_of_the_outline(self):
        leads = project_leads({"1": OUTLINE, "3_characters": CAST})
        self.assertEqual((leads[0], leads[2]), ("沈无咎", "裴仲玄"))
        self.assertIn("男主角", leads[1])

    def test_a_second_lead_is_not_taken_for_the_opponent(self):
        cast = [{"name": "沈无咎", "role": "主角"}, {"name": "苏问剑", "role": "主角"}]
        self.assertEqual(project_leads({"3_characters": cast})[2], "")

    def test_before_stage_3_a_heading_that_is_not_in_the_script_is_not_a_character(self):
        self.assertEqual(project_leads({"1": OUTLINE, "2": "沈无咎：奴才不敢站。"})[::2], ("主角", "反派"))
        self.assertEqual(project_leads({"1": OUTLINE, "2": "沈无咎：奴才不敢站。"})[1], "")

    def test_before_stage_3_outline_names_in_the_script_stand(self):
        assets = {"1": "核心角色：顾沉渊\n对手角色：林婉儿\n", "2": "顾沉渊：走。林婉儿：不。"}
        self.assertEqual(project_leads(assets)[::2], ("顾沉渊", "林婉儿"))

    def test_with_no_script_yet_the_outline_is_all_there_is(self):
        self.assertEqual(project_leads({"1": "核心角色：顾沉渊\n对手角色：林婉儿\n"})[::2], ("顾沉渊", "林婉儿"))

    def test_nothing_known_gives_the_placeholders(self):
        self.assertEqual(project_leads({})[::2], ("主角", "反派"))

    def test_a_shot_finds_everyone_in_it_not_just_the_two_leads(self):
        roster = project_roster({"3_characters": CAST})
        self.assertEqual([person[0] for person in roster_in_shot(roster, "陈九递上一把伞")], ["陈九"])

    def test_a_shot_also_finds_who_is_listed_on_it_by_any_title(self):
        roster = project_roster({"3_characters": CAST})
        found = roster_in_shot(roster, "他抬眼", {"characters": ["盟主", "苏问剑"]}, {"盟主": "裴仲玄"})
        self.assertEqual([person[0] for person in found], ["苏问剑", "裴仲玄"])

    def test_an_empty_shot_has_nobody(self):
        self.assertEqual(roster_in_shot(project_roster({"3_characters": CAST}), "雨打石板"), [])


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Two characters written with the same face are named on the character page."""

from __future__ import annotations

import unittest

from app.core import cast_distinct, prompt_data
from app.core.character_dashboard import compile_character_dashboard
from app.core.face_card import parse_face_card

SAME_FACE = "骨相：鹅蛋脸、下颌线柔和圆润；五官：杏眼、平行双眼皮、柳叶眉、薄唇"


class SlotTests(unittest.TestCase):
    def test_slots_are_read_with_the_studios_own_option_words(self):
        slots = cast_distinct.slots_of(parse_face_card(SAME_FACE))
        self.assertEqual(slots["face_shape"], "鹅蛋脸")
        self.assertEqual(slots["eye_shape"], "杏眼")
        self.assertEqual(slots["lips"], "薄唇")
        self.assertEqual(slots["brow_shape"], "柳叶眉")

    def test_the_longer_option_word_wins(self):
        slots = cast_distinct.slots_of(parse_face_card("五官：杏眼偏长、眼裂横向舒展"))
        self.assertEqual(slots["eye_shape"], "杏眼偏长")

    def test_every_slot_names_a_real_studio_control(self):
        controls = {control["key"] for control in prompt_data.load("face_sculpt")["controls"]}
        data = prompt_data.load("cast_distinct")
        for slot in data["slots"]:
            self.assertIn(slot, controls)
            self.assertIn(slot, data["slot_labels"])


class PairTests(unittest.TestCase):
    def test_two_leads_built_from_one_face_differing_only_in_hair_are_named(self):
        found = cast_distinct.too_alike([
            ("陆沉", SAME_FACE + "；毛发：黑色短发"), ("苏晚", SAME_FACE + "；毛发：及腰长发"),
            ("老周", "骨相：方脸、下颌宽厚；五官：圆眼、单眼皮、浓眉"),
        ])
        self.assertEqual([(hit.first, hit.second) for hit in found], [("陆沉", "苏晚")])
        self.assertEqual(found[0].item, "陆沉 和 苏晚 的脸写得太像")
        self.assertIn("鹅蛋脸", found[0].note)
        self.assertIn("别的五官词都没写出区别", found[0].note)
        self.assertIn("遮住发型和衣服", found[0].note)

    def test_one_differing_slot_is_said_and_two_make_them_different_people(self):
        nearly = cast_distinct.too_alike([("甲", SAME_FACE), ("乙", SAME_FACE.replace("薄唇", "唇形饱满"))])
        self.assertEqual(len(nearly), 1)
        self.assertIn("只有唇形不同", nearly[0].note)
        apart = cast_distinct.too_alike([("甲", SAME_FACE), ("乙", SAME_FACE.replace("薄唇", "唇形饱满").replace("杏眼", "丹凤眼").replace("鹅蛋脸", "方脸"))])
        self.assertEqual(apart, [])

    def test_a_mark_of_ones_own_tells_them_apart(self):
        self.assertEqual(cast_distinct.too_alike([("甲", SAME_FACE), ("乙", SAME_FACE + "、左眼下方一颗泪痣")]), [])

    def test_freely_written_faces_are_compared_by_their_fragments(self):
        free = "骨相：窄长脸、颧骨微突、下颌线锐；五官：眉骨高、内双、眼尾下垂约5°、鼻梁细直"
        found = cast_distinct.too_alike([("甲", free), ("乙", free + "；毛发：白发")])
        self.assertEqual(len(found), 1)
        self.assertIn("100%", found[0].note)
        other = "骨相：圆脸、下颌松垂；五官：眉稀疏、眼袋明显、鼻头大、唇色暗"
        self.assertEqual(cast_distinct.too_alike([("甲", free), ("乙", other)]), [])

    def test_faces_that_say_too_little_are_left_alone(self):
        self.assertEqual(cast_distinct.too_alike([("甲", "五官：杏眼"), ("乙", "五官：杏眼")]), [])
        self.assertEqual(cast_distinct.too_alike([("甲", ""), ("乙", SAME_FACE)]), [])
        self.assertEqual(cast_distinct.too_alike([]), [])


class DashboardTests(unittest.TestCase):
    def _task(self, second_face: str) -> dict:
        return {"task_id": "t-1", "config": {"title_suggestion": "旧仓库"}, "assets": {"3_dna": {
            "risks": [{"item": "服装颜色未定", "status": "PENDING", "note": ""}],
            "characters": [
                {"name": "陆沉", "identity": "男主", "states": [{"title": "日常", "dna": SAME_FACE}]},
                {"name": "苏晚", "identity": "女主", "states": [{"title": "日常", "dna": second_face}]},
            ],
        }}}

    def test_the_hint_joins_the_pages_own_risks_and_nothing_is_stored(self):
        task = self._task(SAME_FACE)
        board = compile_character_dashboard(task)
        self.assertEqual([risk.item for risk in board.risks], ["服装颜色未定", "陆沉 和 苏晚 的脸写得太像"])
        self.assertEqual(board.risks[1].status, "PENDING")
        self.assertEqual(len(task["assets"]["3_dna"]["risks"]), 1)

    def test_distinct_faces_add_nothing(self):
        board = compile_character_dashboard(self._task("骨相：方脸、下颌宽厚；五官：圆眼、单眼皮、浓眉、唇形饱满"))
        self.assertEqual([risk.item for risk in board.risks], ["服装颜色未定"])


if __name__ == "__main__":
    unittest.main()

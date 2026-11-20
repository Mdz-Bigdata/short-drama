# -*- coding: utf-8 -*-
"""What a prop name puts on the stage: a set piece read from the end of the name, else a prop of its real size,
and a stand-in box whose size no prompt states as a fact.

No model, no network.
"""

import unittest

from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan
from app.core.spatial_stage.models import StageLandmark
from app.core.spatial_stage.planner import _is_table, _prop_size, _set_piece
from app.core.spatial_stage.prompting import is_stand_in, scale_reference

STAND_IN = (0.5, 0.5, 0.5)


def _scene(props, text="沈砚与黄琰在屋里对峙。") -> SceneBrief:
    return SceneBrief(
        scene_id="E1S03", location="书房 / 夜 / 内景", text=text, characters=["沈砚", "黄琰"], props=props,
        shots=[ShotSpec(1, ["沈砚", "黄琰"], "", "全景", "平视", "固定", "两人对峙")],
    )


def _pieces(plan):
    return {piece.name: piece for piece in plan.landmarks}


class SetPieceNameTests(unittest.TestCase):
    def test_a_word_inside_the_name_no_longer_makes_it_a_set_piece(self):
        for name in ("档案", "图案", "卷宗档案（旧）", "门牌", "灯笼", "红灯笼", "床头柜", "书案上的录音笔", "河床", "门帘"):
            with self.subTest(name=name):
                self.assertIsNone(_set_piece(name))

    def test_the_end_of_the_name_still_names_the_piece(self):
        cases = {
            "书案": "书案", "书桌": "书案", "餐桌": "书案", "案": "书案", "案几": "书案", "香案（供着牌位）": "书案",
            "屏风": "屏风", "门": "门", "木门": "门", "大门（朱漆）": "门", "窗": "窗", "窗户": "窗",
            "床": "床榻", "卧榻": "床榻", "台阶": "台阶", "石阶": "台阶", "柱": "柱", "柱子": "柱", "大树": "树",
            "炭盆": "灯火", "烛台": "灯火", "蜡烛": "灯火", "油灯": "灯火", "宫灯": "灯火",
            # The desks and fixtures the old word-inside-the-name rule got right, and that must stay right.
            "龙案": "书案", "御案": "书案", "帅案": "书案", "画案": "书案", "案台": "书案", "桌椅": "书案",
            "门框": "门", "窗框": "窗", "窗台": "窗", "灯台": "灯火", "灯盏": "灯火", "灯火": "灯火",
        }
        for name, piece in cases.items():
            with self.subTest(name=name):
                found = _set_piece(name)
                self.assertIsNotNone(found)
                self.assertEqual(found["name"], piece)

    def test_a_false_match_is_sized_and_placed_as_the_prop_it_is(self):
        plan = build_plan(_scene(["档案", "门牌", "灯笼", "录音笔"]))
        pieces = _pieces(plan)
        self.assertEqual(pieces["档案"].kind, "prop")
        self.assertEqual(tuple(pieces["档案"].size), _prop_size("档案"))
        self.assertEqual(pieces["门牌"].kind, "prop")
        self.assertEqual(pieces["灯笼"].kind, "prop")
        # 档案 is no table: the recorder lies on the floor, not on top of a file.
        self.assertFalse(_is_table("档案", pieces["档案"].size))
        self.assertEqual(pieces["录音笔"].elevation_m, 0.0)
        # A 灯笼 named in the props or the text is not a second, stand-alone 灯火.
        self.assertNotIn("灯火", pieces)
        self.assertNotIn("灯火", _pieces(build_plan(_scene([], text="沈砚提着灯笼与黄琰对峙。"))))

    def test_a_true_match_still_dresses_the_set_and_holds_what_lies_on_it(self):
        pieces = _pieces(build_plan(_scene(["书案", "屏风", "木门", "录音笔"])))
        self.assertEqual((pieces["书案"].kind, pieces["书案"].size), ("furniture", [1.4, 0.7, 0.75]))
        self.assertEqual(pieces["屏风"].kind, "furniture")
        self.assertEqual(pieces["木门"].kind, "architecture")
        self.assertAlmostEqual(pieces["录音笔"].elevation_m, 0.75)
        # The props already hold a door, so 推门 in the text adds no second one.
        pieces = _pieces(build_plan(_scene(["木门"], text="沈砚推门而入，与黄琰对峙。")))
        self.assertNotIn("门", pieces)

    def test_an_emperors_desk_still_holds_the_seal(self):
        pieces = _pieces(build_plan(_scene(["龙案", "录音笔"], text="沈砚立在龙案前，与黄琰对峙。")))
        self.assertEqual((pieces["龙案"].kind, pieces["龙案"].size), ("furniture", [1.4, 0.7, 0.75]))
        self.assertAlmostEqual(pieces["录音笔"].elevation_m, 0.75)
        # 案前 in the text names the desk the props already hold: no second 书案.
        self.assertNotIn("书案", pieces)

    def test_a_tea_table_is_still_a_table_at_its_real_size(self):
        self.assertIsNone(_set_piece("茶几"))
        pieces = _pieces(build_plan(_scene(["茶几", "录音笔"])))
        self.assertEqual(pieces["茶几"].size, [1.2, 0.6, 0.45])
        self.assertTrue(_is_table("茶几", pieces["茶几"].size))
        self.assertAlmostEqual(pieces["录音笔"].elevation_m, 0.45)

    def test_only_the_whole_name_is_a_table_for_a_bare_an(self):
        self.assertTrue(_is_table("案", (1.4, 0.7, 0.75)))
        self.assertTrue(_is_table("香案", (1.4, 0.7, 0.75)))
        for name in ("龙案", "御案", "帅案", "画案", "案台"):
            with self.subTest(name=name):
                self.assertTrue(_is_table(name, (1.4, 0.7, 0.75)))
        for name in ("档案", "图案", "方案"):
            with self.subTest(name=name):
                self.assertFalse(_is_table(name, (1.4, 0.7, 0.75)))


class StandInTests(unittest.TestCase):
    def test_the_bible_says_nothing_about_the_size_of_a_stand_in(self):
        self.assertEqual(_prop_size("黄绫"), STAND_IN)
        plan = build_plan(_scene(["黄绫", "录音笔"]))
        self.assertTrue(is_stand_in(_pieces(plan)["黄绫"]))
        self.assertFalse(is_stand_in(_pieces(plan)["录音笔"]))
        self.assertNotIn("黄绫：宽约", plan.scene_bible)
        self.assertIn("黄绫：位于", plan.scene_bible)
        self.assertIn("录音笔：宽约14厘米", plan.scene_bible)

    def test_a_stand_in_is_no_measure_of_a_person(self):
        plan = build_plan(_scene(["黄绫"]))
        self.assertNotIn("黄绫", scale_reference(plan))
        self.assertNotIn("黄绫高约", plan.scene_bible)

    def test_a_set_piece_of_that_size_is_not_a_stand_in(self):
        piece = StageLandmark(id="mark-01", name="石墩", kind="architecture", position=[0, 0], size=list(STAND_IN))
        self.assertFalse(is_stand_in(piece))


if __name__ == "__main__":
    unittest.main()

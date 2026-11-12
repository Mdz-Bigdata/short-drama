# -*- coding: utf-8 -*-
"""修仙术法按名字定样子；修仙 / 武侠剧本带上力量体系底板。"""

import inspect
import unittest

from app.core import technique_look
from app.core.production_knowledge import load_section
from app.service import drama_service
from app.service.screenwriting_service import writer_system_prompt

SCENE = (
    "林渊施展大荒囚天指一掌拍下，魔尊运起天级功法吞天魔功，周身魔气翻涌。她闭目修炼鸿蒙炼神引。"
    "少年使出全力一剑，又以手指点穴。长老催动护山大阵。他施展《青云引气诀》，再使出掌中剑诀。"
)


class NameTests(unittest.TestCase):
    def test_named_techniques_are_found_and_ordinary_words_are_not(self):
        self.assertEqual(
            technique_look.find_names(SCENE),
            ["大荒囚天指", "吞天魔功", "鸿蒙炼神引", "护山大阵", "青云引气诀", "掌中剑诀"],
        )
        self.assertEqual(technique_look.find_names("他一剑劈下，以掌相迎，运起内功。"), [])


class LookTests(unittest.TestCase):
    def test_the_ending_sets_the_shape_and_the_words_set_colour_effect_and_scale(self):
        finger = technique_look.look("大荒囚天指", SCENE)
        self.assertTrue(finger.startswith("一指点出"))
        for word in ("苍茫古旧", "光牢", "从天穹压落"):
            self.assertIn(word, finger)
        devour = technique_look.look("吞天魔功", SCENE)
        for word in ("魔气", "漩涡或黑洞", "黑红"):
            self.assertIn(word, devour)
        self.assertIn("范围以百米计", devour, "the grade written beside it sets the scale")
        self.assertNotIn("从天穹压落", devour, "scale is said once")
        refine = technique_look.look("鸿蒙炼神引")
        self.assertIn("灰白混沌", refine)
        self.assertEqual(refine.count("元神"), 1, "one line per kind")

    def test_more_forms_and_names_that_start_with_nine(self):
        self.assertEqual(technique_look.find_names("他施展九天玄雷斩，魔修祭出九幽噬魂大法，又修炼紫霄引雷诀。"),
                         ["九天玄雷斩", "九幽噬魂大法", "紫霄引雷诀"])
        self.assertIn("边界内颜色和规则都变了", technique_look.look("太极八卦领域"))
        self.assertIn("黑白双鱼", technique_look.look("太极八卦领域"))
        self.assertIn("遁光", technique_look.look("缩地成寸遁术"))
        self.assertIn("巨大法相", technique_look.look("山河法相"))
        self.assertIn("幽冥", technique_look.look("九幽噬魂大法"))

    def test_formations_and_talismans_are_named_and_read(self):
        text = "长老催动九宫锁灵阵，又布下诛仙剑阵。她祭出替身符，再贴上定身符。弟子以神行符遁走。"
        self.assertEqual(technique_look.find_names(text), ["九宫锁灵阵", "诛仙剑阵", "替身符", "定身符", "神行符"])
        self.assertIn("符纸碎裂", technique_look.look("替身符"))
        self.assertIn("刀光剑气纵横", technique_look.look("诛仙剑阵"))

    def test_the_brief_lists_each_named_technique_within_budget(self):
        brief = technique_look.technique_brief(SCENE)
        self.assertTrue(brief.startswith("【术法外观】"))
        self.assertIn("「大荒囚天指」", brief)
        self.assertLessEqual(brief.count("\n- 「"), 4)
        self.assertEqual(technique_look.technique_brief("两人对坐喝茶。"), "")


class PowerSystemTests(unittest.TestCase):
    def test_xianxia_and_wuxia_scripts_carry_the_power_system(self):
        self.assertIn("炼气 → 筑基 → 金丹", load_section("xianxia-power-system", budget=0))
        cultivation = writer_system_prompt("编剧", config={"title_suggestion": "废材修仙：我在宗门签到万年"}, stage="write")
        romance = writer_system_prompt("编剧", config={"title_suggestion": "霸总的契约甜妻"}, stage="write")
        self.assertIn("功法品级与画面尺度", cultivation)
        self.assertNotIn("功法品级与画面尺度", romance)
        self.assertTrue(technique_look.power_system_applies("wuxia"))

    def test_the_director_and_the_storyboard_read_them(self):
        source = inspect.getsource(drama_service)
        self.assertIn('load_section("xianxia-power-system"', source)
        self.assertIn("technique_look.technique_brief(scene_content)", source)


if __name__ == "__main__":
    unittest.main()

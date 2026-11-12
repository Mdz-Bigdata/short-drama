"""修仙设定参照：特殊体质、法宝、宗门势力，只给仙侠玄幻修真项目。"""

import inspect
import unittest

from app.core import xianxia_lore as physiques
from app.core.screenwriting import prompts
from tests.test_production_gates import _outline_arguments

TEN = ("荒骨圣体", "斗战圣体", "混沌道体", "天生剑体", "不灭剑体", "轮回圣体", "先天道胎", "纯阳圣体", "五行灵体", "无极道体", "厄难毒体", "至尊骨", "重瞳")


class PhysiqueReferenceTests(unittest.TestCase):
    def test_only_cultivation_stories_get_it(self):
        self.assertTrue(physiques.applies("修仙逆袭"))
        self.assertTrue(physiques.applies("玄幻"))
        self.assertTrue(physiques.applies("", text="少年测出杂灵根，被逐出宗门"))
        self.assertFalse(physiques.applies("都市甜宠"))
        self.assertFalse(physiques.applies("古装武侠"))
        self.assertEqual(physiques.block("都市甜宠"), "")

    def test_every_physique_with_power_cost_hook_and_look(self):
        names = physiques.names()
        self.assertEqual(tuple(names[:len(TEN)]), TEN, "the producer's picks come first")
        for name in ("绝灵体", "天生魔体", "道胎魔种", "仙骨", "纯阴之体", "天生媚骨", "炉鼎体质", "万毒之体", "金刚不坏之体", "天眷之体", "天厌之体"):
            self.assertIn(name, names)
        self.assertEqual(len(names), len(set(names)))
        text = physiques.reference()
        for name in names:
            line = next(row for row in text.splitlines() if row.startswith(f"- {name}"))
            for part in ("代价：", "戏点：", "画面："):
                self.assertIn(part, line, name)
        self.assertIn("荒骨圣体（又名荒古圣体）", text)
        self.assertIn("每种体质都要有代价或瓶颈", text)
        self.assertIn("弱小时藏住体质", text)

    def test_the_episode_outline_of_a_cultivation_story_carries_it(self):
        made = prompts.build_outline_plan_prompt(
            **_outline_arguments(prompts.build_outline_plan_prompt, {"genre": "修仙逆袭", "synopsis": "杂灵根少年被逐出宗门"}),
        )
        self.assertIn("修仙设定参照", made)
        self.assertIn("荒骨圣体", made)
        urban = prompts.build_outline_plan_prompt(**_outline_arguments(prompts.build_outline_plan_prompt, {"genre": "都市甜宠"}))
        self.assertNotIn("修仙设定参照", urban)

    def test_the_banner_and_the_sects_are_in_it(self):
        text = physiques.reference()
        self.assertEqual(physiques.artifact_names(), ["人皇幡"])
        banner = next(row for row in text.splitlines() if row.startswith("- 人皇幡"))
        self.assertIn("人皇帆", banner, "the spelling the producer used still finds it")
        for part in ("代价：", "戏点：", "画面："):
            self.assertIn(part, banner)
        for line in ("宗门层级", "杂役弟子", "宗主", "势力类型", "魔道宗门", "宗门大比", "外门灰衣"):
            self.assertIn(line, text)

    def test_the_scene_plan_block_reads_the_story_not_only_the_genre_word(self):
        self.assertIn("无极道体", prompts._physique_block({"genre": "古装", "synopsis": "他在宗门外门测出灵根，一路修仙"}))
        self.assertEqual(prompts._physique_block({"genre": "古装", "synopsis": "宅门里的姐妹争宠"}), "")

    def test_the_director_plan_of_a_cultivation_story_carries_it(self):
        from app.service import drama_service

        self.assertIn("xianxia_lore.block(", inspect.getsource(drama_service))


if __name__ == "__main__":
    unittest.main()

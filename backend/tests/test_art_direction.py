# -*- coding: utf-8 -*-
"""美术指导与武术指导：策划里定下的美术设定卡、打法卡，后面的环节读得到、照着做。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import art_direction, fight_design
from app.core.screenwriting import prompts
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.service.drama_service import DramaService

WORLD = "明末江南水乡，梅雨季；白墙黛瓦、蓝印花布、桐油灯；乌篷船代步，檐下晾腌菜。"
OVERVIEW = {"synopsis": "绣娘查父亲旧案。", "genre": "古装悬疑", "theme": "真相有价", "world_setting": WORLD}


class WorldCardTests(unittest.TestCase):
    def test_the_director_is_asked_for_a_card_that_grows_the_picture_out_of_the_place(self):
        card = art_direction.world_card()
        self.assertTrue(card.startswith("【美术设定卡】"))
        for line in ("时代与地域", "物产与材质", "生活习惯", "民俗细节", "阶层差别", "贯穿小物件", "奇幻落地"):
            self.assertIn(f"- {line}", card)
        self.assertIn("不靠堆风格词", card)
        self.assertIn("照原文", card, "an adapted or uploaded story keeps its own era and place")
        self.assertIn("现实的基底越扎实，奇幻越可信", card)

    def test_the_overview_carries_the_card_so_the_writer_and_the_asset_list_read_it(self):
        ask = prompts.build_overview_prompt("策划方案正文", source_kind="outline")
        self.assertIn("世界观一栏照策划方案或原文里的「美术设定卡」写成一段", ask)
        self.assertIn("原文没写的不编", ask)
        inventory = prompts.build_asset_inventory_prompt("第一集……", source_kind="novel", overview=OVERVIEW)
        self.assertIn(f"世界观：{WORLD}", inventory)

    def test_scenes_and_props_are_asked_for_the_place_the_household_and_the_owner(self):
        inventory = prompts.build_asset_inventory_prompt("第一集……", source_kind="novel", overview=OVERVIEW)
        self.assertIn("有人过日子的痕迹", inventory)
        self.assertIn("应季应地的民俗细节", inventory)
        self.assertIn("它是谁的、用成了什么样", inventory)
        # 作者的成品剧本照作者写的，不替他补世界。
        authored = prompts.build_asset_inventory_prompt("第一集……", source_kind="screenplay", overview=OVERVIEW)
        self.assertNotIn("有人过日子的痕迹", authored)
        self.assertNotIn("它是谁的、用成了什么样", authored)

    def test_the_catalogue_pass_gets_the_rules_and_the_world_only_for_scenes_and_props(self):
        self.assertEqual(art_direction.CATALOG_KINDS, ("scenes", "props"))
        rules = art_direction.catalog_rules(["scenes", "costumes", "props"])
        self.assertEqual(rules.count("\n"), 2)
        self.assertIn("场景（scenes）", rules)
        self.assertIn("道具（props）", rules)
        self.assertEqual(art_direction.catalog_rules(["costumes", "makeup"]), "")
        self.assertEqual(art_direction.catalog_world(WORLD, ["scenes"]), f"【世界观与美术设定】：\n{WORLD}\n\n")
        self.assertEqual(art_direction.catalog_world(WORLD, ["costumes"]), "")
        self.assertEqual(art_direction.catalog_world("  ", ["scenes"]), "")
        self.assertEqual(art_direction.catalog_world(None, ["props"]), "")

    def test_a_costume_says_who_they_are_how_they_are_doing_and_how_they_wear_it_without_feeling_words(self):
        rule = art_direction.costume_rule()
        for part in ("1. 身份", "2. 处境", "3. 性格"):
            self.assertIn(part, rule)
        self.assertIn("不写心理词", rule)
        self.assertIn("美术设定卡", rule)
        self.assertIn("全剧不换", rule)


class FightCardTests(unittest.TestCase):
    def test_a_story_with_fighting_gets_a_card_per_fighter_and_other_stories_none(self):
        card = fight_design.director_card("wuxia", "")
        self.assertTrue(card.startswith("【打法卡】"))
        for line in ("打法从人来", "破绽", "情绪怎么进招", "代价"):
            self.assertIn(f"- {line}", card)
        strong = next(iter(fight_design.STRONG_SIGNALS))
        self.assertTrue(fight_design.director_card("urban", f"两人在码头{strong}"))
        self.assertEqual(fight_design.director_card("romance", "总裁与小助理的误会"), "")
        self.assertEqual(fight_design.director_card("", ""), "")

    def test_the_fight_plan_follows_the_card_and_shows_feeling_as_a_change_in_how_someone_fights(self):
        self.assertIn("13. **打法跟人走**", fight_design.PLAN_RULES)
        self.assertIn("情绪不写成表情，写成这一场打法的变化", fight_design.PLAN_RULES)
        self.assertIn("没有打法卡时按第 2 条现定，定了全剧不换", fight_design.PLAN_RULES)
        self.assertIn("12. **强者有固定标志**", fight_design.PLAN_RULES, "the twelve rules before it are untouched")


class DirectorWiringTests(unittest.TestCase):
    """The cards are in the request the stage-1 director actually gets."""

    @staticmethod
    def _director_system(title: str) -> str:
        systems: list[str] = []

        def model(model_name, system_prompt, user_prompt, *args, **kwargs):
            systems.append(str(system_prompt))
            return ""

        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"HARNESS_EVOLUTION": "off"}):
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            service.gateway.call_llm = model
            task = service.create_task(DramaCreateRequest(titleSuggestion=title, episodeCount=3), owner_user_id="u1")
            try:
                service._execute_stage_blocking(task["task_id"], 1)
            except Exception:  # noqa: BLE001 - an empty plan fails the stage; the request is what is checked
                pass
        return next(system for system in systems if "【立意卡】" in system)

    def test_every_plan_is_asked_for_the_art_card_and_a_fight_story_for_the_fight_card_too(self):
        quiet = self._director_system("总裁与小助理的误会")
        self.assertIn("【美术设定卡】", quiet)
        self.assertLess(quiet.index("【立意卡】"), quiet.index("【美术设定卡】"))
        self.assertNotIn("【打法卡】", quiet)
        strong = next(iter(fight_design.STRONG_SIGNALS))
        fighting = self._director_system(f"两个镖师在渡口{strong}")
        self.assertIn("【美术设定卡】", fighting)
        self.assertIn("【打法卡】", fighting)


if __name__ == "__main__":
    unittest.main()

"""The five rules for writing a character's block reach every prompt that writes one."""

import json
import unittest
from pathlib import Path

from app.core import character_block
from app.core.screenwriting.prompts import build_asset_inventory_prompt

DATA = Path(__file__).resolve().parents[1] / "app" / "data" / "prompt"


class CharacterBlockTests(unittest.TestCase):
    def test_the_inventory_of_a_novel_or_outline_carries_all_five_rules(self):
        for kind in ("novel", "outline"):
            line = next(row for row in build_asset_inventory_prompt("原文", source_kind=kind, overview=None).splitlines() if "角色块写法" in row)
            for phrase in ("只写不可变特征", "疤痕与痣的位置", "越靠前权重越高", "那件褪色的橄榄绿棉工装", "每个角色单独一块", "一个角色一个音色，全剧不变"):
                self.assertIn(phrase, line, (kind, phrase))
            self.assertIn("（5）", line)

    def test_a_finished_screenplay_keeps_the_authors_descriptions(self):
        line = next(row for row in build_asset_inventory_prompt("原文", source_kind="screenplay", overview=None).splitlines() if "角色块写法" in row)
        self.assertIn("每个角色单独一块", line)
        self.assertIn("一个角色一个音色", line)
        # The author's look is copied as written: no rewriting it into fixed features or a reordered list.
        self.assertNotIn("只写不可变特征", line)
        self.assertNotIn("越靠前权重越高", line)

    def test_the_character_designer_reads_the_same_rules(self):
        rules = character_block.designer_rules()
        self.assertTrue(rules.startswith("【角色块写法"))
        self.assertEqual(rules.count("\n1. "), 1)
        self.assertIn("5. 一个角色一个音色，全剧不变", rules)
        source = (Path(__file__).resolve().parents[1] / "app" / "service" / "drama_service.py").read_text("utf-8")
        self.assertIn('prompt_data.text("agent_prompts", "character_designer")\n                + character_block.designer_rules()', source)

    def test_the_name_segment_stays_first_for_face_sculpt(self):
        ordering = json.loads((DATA / "character_block.json").read_text("utf-8"))["rules"][1]
        self.assertIn("称呼与身份那一小段照旧写在最前", ordering)

    def test_the_dna_keeps_one_voice_per_character(self):
        structurer = json.loads((DATA / "agent_prompts.json").read_text("utf-8"))["dna_structurer"]
        self.assertIn("一个角色一个音色、全剧不变", structurer)
        self.assertIn("不随 states 变化", structurer)


if __name__ == "__main__":
    unittest.main()

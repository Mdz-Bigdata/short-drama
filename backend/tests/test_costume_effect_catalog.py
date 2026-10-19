"""Costumes and effects come out of the screenplay: the writer lists them, and a project whose writer did not is backfilled."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.production_asset_extractor import extract_production_assets
from app.core.screenwriting.models import AssetInventory
from app.core.screenwriting.prompts import build_asset_inventory_prompt
from app.core.screenwriting.renderer import render_breakdown
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from app.service.screenwriting_service import ENGINE_NAME

SCRIPT = "第1集 雨夜\n场景1：靖安侯府正堂 夜 内景\n暴雨砸在槛窗上。沈知微一身素白医官袍，指间金针泛着冷光。\n沈知微：松手。"


def _task() -> dict:
    return {
        "task_id": "catalog-task",
        "config": {"title_suggestion": "金针", "llm_model": "test-model"},
        "assets": {
            "2": SCRIPT,
            "2_breakdown": {
                "production_assets": {
                    "scenes": [{"name": "靖安侯府正堂", "description": "夜，内景"}],
                    "props": [{"name": "金针", "description": "九枚"}],
                    "costumes": [],
                    "effects": [],
                },
            },
            "2_screenwriting": {
                "engine": ENGINE_NAME,
                "inventory": {"characters": {"沈知微": {"description": "二十岁上下女子，穿素白交领窄袖医官袍，外罩青灰比甲"}}},
            },
        },
    }


ANSWER = json.dumps({
    "costumes": [{"name": "沈知微·素白医官袍", "character": "沈知微", "description": "素白交领窄袖，外罩青灰比甲"}],
    "effects": [{"name": "雨夜雨幕", "description": "暴雨斜打槛窗，窗纸水痕"}],
}, ensure_ascii=False)


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("catalog-task", _task())
        self.service = DramaService()
        self.service.repo = self.repo

    def test_only_the_missing_lists_are_asked_for_and_scenes_and_props_are_kept(self):
        with patch.object(self.service.gateway, "call_llm", return_value=ANSWER) as call:
            catalog = self.service.ensure_production_asset_catalog("catalog-task")
        system_prompt, user_prompt = call.call_args.args[1], call.call_args.args[2]
        self.assertIn('"costumes"', system_prompt)
        self.assertIn('"effects"', system_prompt)
        self.assertNotIn('"scenes"', system_prompt)
        self.assertIn("素白交领窄袖医官袍", user_prompt, "the cast's look is handed over so costumes match the actor sheets")
        self.assertEqual(catalog["scenes"][0]["name"], "靖安侯府正堂")
        self.assertEqual(catalog["costumes"][0]["character"], "沈知微")
        self.assertTrue(catalog["costumes"][0]["description"].startswith("沈知微穿着"))

        task = self.repo.get_task("catalog-task")
        self.assertEqual(task["assets"]["2_breakdown"]["production_assets"], catalog)
        self.assertEqual([item["name"] for item in extract_production_assets(task, "costume")], ["沈知微·素白医官袍"])
        self.assertEqual([item["name"] for item in extract_production_assets(task, "effect")], ["雨夜雨幕"])

    def test_a_script_without_effects_is_asked_once_until_the_script_changes(self):
        empty = json.dumps({"costumes": [{"name": "沈知微·素白医官袍", "character": "沈知微", "description": "素白"}], "effects": []})
        with patch.object(self.service.gateway, "call_llm", return_value=empty) as call:
            self.service.ensure_production_asset_catalog("catalog-task")
            self.service.ensure_production_asset_catalog("catalog-task")
        self.assertEqual(call.call_count, 1, "an honest empty answer is not re-asked on every page open")

        self.repo.mutate_task("catalog-task", lambda task: task["assets"].__setitem__("2", SCRIPT + "\n第2集 火场\n大火吞没药庐。"))
        with patch.object(self.service.gateway, "call_llm", return_value=ANSWER) as call:
            catalog = self.service.ensure_production_asset_catalog("catalog-task")
        self.assertEqual(call.call_count, 1)
        self.assertNotIn('"costumes"', call.call_args.args[1], "costumes are already listed")
        self.assertEqual([item["name"] for item in catalog["effects"]], ["雨夜雨幕"])

    def test_a_complete_catalog_costs_no_call(self):
        task = _task()
        task["assets"]["2_breakdown"]["production_assets"].update(json.loads(ANSWER))
        self.repo.save_task("catalog-task", task)
        with patch.object(self.service.gateway, "call_llm") as call:
            self.service.ensure_production_asset_catalog("catalog-task")
        call.assert_not_called()

    def test_stage_three_fills_the_task_it_holds(self):
        task = _task()
        with patch.object(self.service.gateway, "call_llm", return_value=ANSWER):
            self.assertEqual(self.service._catalog_kinds_to_fill(task), ["costumes", "effects"])
            _, changed = self.service._fill_production_catalog(task)
        self.assertTrue(changed)
        self.assertEqual(self.service._catalog_kinds_to_fill(task), [])
        self.assertEqual(len(task["assets"]["2_breakdown"]["production_assets"]["effects"]), 1)


class WriterInventoryTests(unittest.TestCase):
    def test_the_inventory_prompt_asks_for_costumes_and_effects_in_both_modes(self):
        for kind in ("novel", "screenplay"):
            prompt = build_asset_inventory_prompt("原文", source_kind=kind, overview={})
            self.assertIn("服装（costumes）", prompt)
            self.assertIn("特效（effects）", prompt)
            self.assertIn("角色名·造型名", prompt)

    def test_the_inventory_accepts_lists_and_the_breakdown_carries_them(self):
        inventory = AssetInventory.model_validate({
            "characters": [{"name": "沈知微", "description": "素白医官袍"}],
            "costumes": [{"name": "沈知微·素白医官袍", "character": "沈知微", "description": "素白交领窄袖"}],
            "effects": [{"name": "雨夜雨幕", "description": "暴雨斜打"}],
        }).model_dump(mode="json")
        catalog = render_breakdown({"inventory": inventory})["production_assets"]
        self.assertEqual(catalog["costumes"], [{"name": "沈知微·素白医官袍", "description": "沈知微穿着；素白交领窄袖", "character": "沈知微"}])
        self.assertEqual(catalog["effects"], [{"name": "雨夜雨幕", "description": "暴雨斜打"}])


if __name__ == "__main__":
    unittest.main()

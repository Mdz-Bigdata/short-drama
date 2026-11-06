"""The recipe catalog: data that is checked on load, rendering that treats typed text as text, and the agent's tools."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import recipe_api
from app.api.auth_api import get_current_user
from app.core import recipe_catalog
from app.core.agent_tools import catalog as tool_catalog
from app.core.recipe_catalog import RecipeCatalogError, RecipeInputError, load_catalog, render

USER = {"user_id": "u-1", "role": "user"}


def _write(folder, name, recipes, category="general_image"):
    (Path(folder) / name).write_text(json.dumps({"category": category, "label": "测试", "recipes": recipes}, ensure_ascii=False), encoding="utf-8")


def _recipe(**changes):
    return {
        "id": "a-recipe", "name": "配方", "description": "说明", "output_type": "image",
        "inputs": [{"name": "place", "label": "地点", "required": True}],
        "prompt": "这是一条足够长的提示词，地点是 {{place}}。", **changes,
    }


class ShippedCatalogTests(unittest.TestCase):
    def test_the_shipped_catalog_loads_and_covers_every_category(self):
        shipped = load_catalog()
        self.assertGreaterEqual(len(shipped.recipes), 20)
        self.assertEqual(
            set(shipped.labels),
            {"short_drama", "ecommerce_image", "social_image", "general_image", "general_video", "general_audio"},
        )
        self.assertEqual({recipe.category for recipe in shipped.recipes}, set(shipped.labels))
        self.assertEqual({recipe.output_type for recipe in shipped.recipes}, {"image", "video", "audio"})

    def test_every_recipe_renders_from_its_required_inputs_alone(self):
        for recipe in load_catalog().recipes:
            inputs = {
                item.name: (item.choices[0] if item.choices else "测试内容")
                for item in recipe.inputs if item.required and not item.default
            }
            rendered = render(recipe.id, inputs)
            self.assertNotIn("{{", rendered["prompt"], recipe.id)
            self.assertNotIn("[[", rendered["prompt"], recipe.id)
            self.assertGreater(len(rendered["prompt"]), 40, recipe.id)

    def test_every_recipe_renders_with_all_inputs_filled(self):
        for recipe in load_catalog().recipes:
            inputs = {
                item.name: (item.choices[-1] if item.choices else str(int(item.minimum or 10)) if item.type == "number" else "填写值")
                for item in recipe.inputs
            }
            rendered = render(recipe.id, inputs)
            self.assertNotIn("{{", rendered["prompt"], recipe.id)
            for value in inputs.values():
                self.assertIn(value, rendered["prompt"], recipe.id)

    def test_video_recipes_keep_the_project_rule_about_music(self):
        for recipe in load_catalog().recipes:
            if recipe.output_type == "video":
                self.assertIn("不生成音乐", recipe.prompt, recipe.id)


class RenderTests(unittest.TestCase):
    def test_substitutes_and_applies_defaults(self):
        rendered = render("image-cinematic-still", {"scene": "雨夜客厅"})
        self.assertIn("雨夜客厅", rendered["prompt"])
        self.assertIn("35mm 环境人像", rendered["prompt"])
        self.assertEqual(rendered["output_type"], "image")
        self.assertEqual(rendered["params"]["aspect_ratio"], "16:9")
        self.assertTrue(rendered["negative"])

    def test_an_optional_block_goes_when_its_input_is_empty(self):
        base = {"protagonist": "林夏", "opponent": "周牧", "place": "宴会厅", "reveal": "遗嘱"}
        self.assertNotIn("平静地说出", render("drama-public-reversal", base)["prompt"])
        with_line = render("drama-public-reversal", {**base, "line": "这家公司是我的。"})["prompt"]
        self.assertIn("平静地说出：「这家公司是我的。」", with_line)

    def test_typed_text_is_never_read_as_syntax(self):
        rendered = render("image-cinematic-still", {"scene": "{{lens}} [[偷渡]] {{nothing}}"})
        self.assertIn("{{lens}} [[偷渡]] {{nothing}}", rendered["prompt"])

    def test_refusals_name_the_input(self):
        for inputs, message in (
            ({}, "缺少"),
            ({"scene": "x", "nope": "y"}, "没有这些输入"),
            ({"scene": "x" * 301}, "最长"),
            ({"scene": "x", "lens": "IMAX"}, "只能是"),
        ):
            with self.assertRaisesRegex(RecipeInputError, message):
                render("image-cinematic-still", inputs)
        with self.assertRaises(LookupError):
            render("no-such-recipe", {})

    def test_number_inputs_respect_their_range(self):
        base = {"moment": "告别"}
        self.assertIn("约 60 秒", render("audio-score-brief", {**base, "seconds": 60})["prompt"])
        for value in ("abc", "1", "9999", "nan"):
            with self.assertRaises(RecipeInputError, msg=value):
                render("audio-score-brief", {**base, "seconds": value})


class SchemaValidationTests(unittest.TestCase):
    def _load(self, recipes, name="x.json"):
        with tempfile.TemporaryDirectory() as folder:
            _write(folder, name, recipes)
            return load_catalog(Path(folder))

    def test_a_good_file_loads(self):
        self.assertEqual(self._load([_recipe()]).get("a-recipe").category, "general_image")

    def test_broken_recipes_fail_naming_the_file(self):
        cases = {
            "未声明": _recipe(prompt="这是一条足够长的提示词，用了 {{place}} 和 {{other}}。"),
            "没用": _recipe(inputs=[{"name": "place", "label": "地点", "required": True}, {"name": "extra", "label": "多余"}]),
            "默认值": _recipe(inputs=[{"name": "place", "label": "地点"}]),
            "写坏": _recipe(prompt="这是一条足够长的提示词，地点是 {{place}} {oops}。"),
            "Field required": {"id": "a-recipe", "name": "配方"},
            "输入名重复": _recipe(inputs=[{"name": "place", "label": "甲", "required": True}, {"name": "place", "label": "乙", "required": True}]),
            "output_type": _recipe(output_type="hologram"),
            "choices": _recipe(inputs=[{"name": "place", "label": "地点", "type": "choice", "required": True}]),
            "不在 choices": _recipe(inputs=[{"name": "place", "label": "地点", "type": "choice", "required": True, "choices": ["甲"], "default": "乙"}]),
        }
        for message, recipe in cases.items():
            with self.assertRaisesRegex(RecipeCatalogError, f"bad.json.*{message}|bad.json[\\s\\S]*{message}", msg=message):
                self._load([recipe], "bad.json")

    def test_an_optional_input_must_sit_in_a_block_to_go_missing(self):
        fine = _recipe(inputs=[{"name": "place", "label": "地点", "required": True}, {"name": "mood", "label": "氛围"}],
                       prompt="这是一条足够长的提示词，地点是 {{place}}。[[氛围：{{mood}}。]]")
        self.assertTrue(self._load([fine]).recipes)

    def test_duplicate_ids_and_categories_across_files_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            _write(folder, "a.json", [_recipe()], category="general_image")
            _write(folder, "b.json", [_recipe()], category="general_video")
            with self.assertRaisesRegex(RecipeCatalogError, "重复"):
                load_catalog(Path(folder))
        with tempfile.TemporaryDirectory() as folder:
            _write(folder, "a.json", [_recipe()])
            _write(folder, "b.json", [_recipe(id="b-recipe")])
            with self.assertRaisesRegex(RecipeCatalogError, "已在别的文件"):
                load_catalog(Path(folder))

    def test_bad_json_and_an_empty_folder_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RecipeCatalogError, "没有配方文件"):
                load_catalog(Path(folder))
            (Path(folder) / "broken.json").write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(RecipeCatalogError, "broken.json"):
                load_catalog(Path(folder))


class RecipeRouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(recipe_api.router)
        app.dependency_overrides[get_current_user] = lambda: USER
        self.client = TestClient(app)

    def test_lists_and_filters(self):
        body = self.client.get("/api/recipes").json()
        self.assertEqual(body["total"], len(recipe_catalog.catalog().recipes))
        self.assertEqual(len(body["categories"]), 6)
        videos = self.client.get("/api/recipes", params={"output_type": "video"}).json()
        self.assertTrue(videos["recipes"])
        self.assertTrue(all(item["output_type"] == "video" for item in videos["recipes"]))
        ecommerce = self.client.get("/api/recipes", params={"category": "ecommerce_image"}).json()
        self.assertEqual({item["category"] for item in ecommerce["recipes"]}, {"ecommerce_image"})
        self.assertEqual(self.client.get("/api/recipes", params={"q": "白底"}).json()["recipes"][0]["id"], "ecom-white-background")
        self.assertNotIn("prompt", body["recipes"][0])

    def test_gets_one_and_renders(self):
        self.assertEqual(self.client.get("/api/recipes/ecom-white-background").json()["output_type"], "image")
        self.assertEqual(self.client.get("/api/recipes/none").status_code, 404)
        rendered = self.client.post("/api/recipes/ecom-white-background/render", json={"inputs": {"product": "保温杯", "material": "哑光不锈钢"}})
        self.assertEqual(rendered.status_code, 200, rendered.text)
        self.assertIn("保温杯", rendered.json()["prompt"])
        self.assertEqual(self.client.post("/api/recipes/ecom-white-background/render", json={"inputs": {}}).status_code, 422)
        self.assertEqual(self.client.post("/api/recipes/none/render", json={}).status_code, 404)

    def test_needs_a_signed_in_person(self):
        app = FastAPI()
        app.include_router(recipe_api.router)
        self.assertEqual(TestClient(app).get("/api/recipes").status_code, 401)


class RecipeToolTests(unittest.TestCase):
    def test_both_tools_are_free_reads_with_no_project(self):
        tools = {tool.name: tool for tool in tool_catalog.list()}
        for name in ("list_recipes", "render_recipe"):
            self.assertEqual(tools[name].effect, "read")
            self.assertFalse(tools[name].needs_task)
        self.assertEqual(tools["render_recipe"].input_schema["required"], ["recipe_id"])

    def test_the_agent_can_list_and_render(self):
        service = MagicMock()
        listed = tool_catalog.call("list_recipes", {"category": "short_drama"}, service=service, user=USER)
        self.assertTrue(listed["ok"])
        self.assertTrue(all(item["category"] == "short_drama" for item in listed["result"]["recipes"]))
        rendered = tool_catalog.call("render_recipe", {"recipe_id": "video-opening-hook", "inputs": {"event": "杯子摔碎", "person": "林夏"}}, service=service, user=USER)
        self.assertTrue(rendered["ok"])
        self.assertIn("杯子摔碎", rendered["result"]["prompt"])
        self.assertEqual(service.method_calls, [])

    def test_a_bad_call_answers_without_raising(self):
        missing = tool_catalog.call("render_recipe", {"recipe_id": "video-opening-hook", "inputs": {}}, service=MagicMock(), user=USER)
        self.assertFalse(missing["ok"])
        self.assertIn("缺少", missing["error"])
        self.assertFalse(tool_catalog.call("render_recipe", {"recipe_id": "nope"}, service=MagicMock(), user=USER)["ok"])


if __name__ == "__main__":
    unittest.main()

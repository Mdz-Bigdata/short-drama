"""Derived looks dress their character where the story calls for them; products are bound and, for an ad, required."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.auth_api import auth_service
from app.core import character_variants as cv
from app.core.production_asset_extractor import extract_production_assets
from app.core.production_asset_readiness import evaluate_asset_readiness, readiness_reasons
from app.core.storyboard_scene_context import compile_scene_context, merge_video_references, panel_context
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from main import app

BASE = {"id": "a-base", "kind": "actor", "name": "林夏", "description": "黑色短发，白大褂", "metadata": {}, "image_url": "data:base"}
YOUNG = {"id": "a-young", "kind": "actor", "name": "少年林夏", "description": "十五岁，校服马尾", "image_url": "data:young",
         "metadata": {"variant": {"of": "林夏", "label": "少年", "triggers": ["少年", "校服"], "episodes": None}}}
BRIDE = {"id": "a-bride", "kind": "actor", "name": "婚纱林夏", "description": "白色婚纱，盘发", "image_url": "data:bride",
         "metadata": {"variant": {"of": "林夏", "label": "婚纱", "triggers": ["婚纱"], "episodes": [3, 3]}}}
DRYER = {"id": "p-1", "kind": "product", "name": "静音吹风机", "description": "哑光白机身，银色风嘴", "metadata": {}, "image_url": "data:dryer"}


def _task(**config):
    return {"task_id": "vp-1", "config": config, "assets": {
        "3_characters": [{"name": "林夏", "desc": "调查记者"}], "3_sheets": {"林夏": "https://cdn/base-sheet.png"},
    }}


class VariantRulesTests(unittest.TestCase):
    def test_a_variant_needs_a_base_and_a_way_to_be_called_for(self):
        facts = cv.clean_variant({"of": "林夏", "label": "少年", "triggers": "校服、少年"}, element_name="少年林夏")
        self.assertEqual(facts, {"of": "林夏", "label": "少年", "triggers": ["校服", "少年"], "episodes": None})
        self.assertEqual(cv.clean_variant({"of": "林夏", "label": "少年", "triggers": ["校服"]})["triggers"], ["少年", "校服"])
        self.assertEqual(cv.clean_variant({"of": "林夏", "episode_from": 3})["episodes"], [3, 3])
        for bad, message in (({"of": ""}, "来源角色"), ({"of": "林夏"}, "触发词"), ({"of": "林夏", "episode_from": 4, "episode_to": 2}, "集数范围无效")):
            with self.assertRaisesRegex(cv.VariantError, message):
                cv.clean_variant(bad)
        with self.assertRaisesRegex(cv.VariantError, "自己"):
            cv.clean_variant({"of": "林夏", "label": "x"}, element_name="林夏")

    def test_a_mentioned_trigger_wins_over_an_episode_range_and_the_longest_trigger_wins(self):
        _, variants = cv.split([BASE, YOUNG, BRIDE])
        options = variants["林夏"]
        self.assertEqual(cv.pick(options, text="少年林夏奔跑", episode=3)["id"], "a-young")
        self.assertEqual(cv.pick(options, text="林夏走进教堂", episode=3)["id"], "a-bride")
        self.assertIsNone(cv.pick(options, text="林夏走进教堂", episode=2))
        self.assertIsNone(cv.triggered(options, "林夏走进教堂"))
        self.assertEqual(cv.episode_of("E12S03"), 12)


class SceneBindingTests(unittest.TestCase):
    def test_a_scene_that_calls_for_a_variant_dresses_the_character_without_adding_a_character(self):
        context = compile_scene_context(_task(), {"scene_id": "E1S01", "content": "少年林夏在雨里奔跑，校服湿透。", "characters": ["林夏"]}, [BASE, YOUNG, BRIDE])
        self.assertEqual(context["characters"], ["林夏"])
        self.assertNotIn("少年林夏", context["all_character_names"])
        actor = context["actors"][0]
        self.assertEqual((actor["image_url"], actor["variant"], actor["description"]), ("data:young", "少年", "十五岁，校服马尾"))
        self.assertIn("十五岁，校服马尾", context["prompt"])

        by_episode = compile_scene_context(_task(), {"scene_id": "E3S02", "content": "林夏走进教堂。", "characters": ["林夏"]}, [BASE, YOUNG, BRIDE])
        self.assertEqual(by_episode["actors"][0]["variant"], "婚纱")
        plain = compile_scene_context(_task(), {"scene_id": "E2S01", "content": "林夏推门。", "characters": ["林夏"]}, [BASE, YOUNG, BRIDE])
        self.assertEqual(plain["actors"][0]["image_url"], "data:base")
        self.assertNotIn("variant", plain["actors"][0])

    def test_a_shot_can_call_for_another_look_than_its_scene_and_the_base_sheet_steps_aside(self):
        context = compile_scene_context(_task(), {"scene_id": "E3S01", "content": "林夏在教堂里回忆往事。", "characters": ["林夏"]}, [BASE, YOUNG, BRIDE])
        self.assertEqual(context["actors"][0]["variant"], "婚纱")
        flashback = panel_context(context, {"desc": "闪回：少年林夏在操场上奔跑", "characters": ["林夏"]})
        actor_refs = [r for r in flashback["references"] if r["kind"] == "actor"]
        self.assertEqual(actor_refs, [{"kind": "actor", "name": "林夏", "image_url": "data:young", "variant": "少年"}])

        images, notes = merge_video_references([("林夏", "https://cdn/base-sheet.png")], flashback["references"])
        self.assertNotIn("https://cdn/base-sheet.png", images, "the dressed character is locked by its variant, not the base sheet")
        self.assertIn("data:young", images)
        plain, _ = merge_video_references([("林夏", "https://cdn/base-sheet.png")], [{"kind": "actor", "name": "林夏", "image_url": "data:base"}])
        self.assertEqual(plain, ["https://cdn/base-sheet.png", "data:base"])

    def test_a_product_is_bound_where_a_shot_mentions_it(self):
        context = compile_scene_context(_task(), {"scene_id": "E1S01", "content": "林夏拿起静音吹风机，三分钟吹干头发。", "characters": ["林夏"]}, [BASE, DRYER])
        self.assertEqual([p["name"] for p in context["products"]], ["静音吹风机"])
        self.assertIn("【商品】", context["prompt"])
        shot = panel_context(context, {"desc": "特写：林夏按下静音吹风机的开关", "characters": ["林夏"]})
        self.assertIn({"kind": "product", "name": "静音吹风机", "image_url": "data:dryer"}, shot["references"])
        quiet = panel_context(context, {"desc": "林夏看向镜子", "characters": ["林夏"]})
        self.assertNotIn("product", [r["kind"] for r in quiet["references"]])


class ProductReadinessTests(unittest.TestCase):
    AD = {"creation_mode": "ad", "ad_brief": {"product": "静音吹风机", "selling_points": "三分钟速干", "call_to_action": "立即下单"}}

    def test_an_ad_needs_a_photo_of_the_product_its_brief_names(self):
        task = {"task_id": "vp-1", "config": self.AD, "assets": {}}
        missing = evaluate_asset_readiness(task, [])
        self.assertEqual(missing["kinds"]["product"]["missing"], ["静音吹风机"])
        self.assertIn("3.商品缺少参考图（1项）：静音吹风机", readiness_reasons(missing))
        no_photo = evaluate_asset_readiness(task, [{"kind": "product", "name": "静音吹风机", "metadata": {}, "has_image": False}])
        self.assertEqual(no_photo["kinds"]["product"]["missing"], ["静音吹风机"])
        ready = evaluate_asset_readiness(task, [{"kind": "product", "name": "静音吹风机", "metadata": {}, "has_image": True}])
        self.assertEqual(ready["kinds"]["product"]["missing"], [])

    def test_a_drama_never_asks_for_a_product_and_extraction_takes_it_from_the_brief(self):
        drama = evaluate_asset_readiness({"task_id": "vp-1", "config": {}, "assets": {}}, [])
        self.assertFalse(drama["kinds"]["product"]["enforced"])
        self.assertFalse(any("商品" in reason for reason in readiness_reasons(drama)))
        self.assertEqual(extract_production_assets({"config": self.AD, "assets": {}}, "product"),
                         [{"name": "静音吹风机", "description": "三分钟速干", "image_url": ""}])
        self.assertEqual(extract_production_assets({"config": {}, "assets": {}}, "product"), [])


class VariantApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'p.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            self.user, _ = await self.store.create_user(email="variant@example.com", phone=None, password="variant-user-password")
            self.base = await self.store.create_element(owner_id=self.user.id, kind="actor", name="林夏", metadata={"task_id": "vp-1"})
            self.young = await self.store.create_element(owner_id=self.user.id, kind="actor", name="少年林夏", metadata={"task_id": "vp-1"})
            self.product = await self.store.create_element(owner_id=self.user.id, kind="product", name="静音吹风机", metadata={"task_id": "vp-1"})

        asyncio.run(prepare())
        self.addCleanup(lambda: asyncio.run(self.store.close()))
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.cookies = {"auth_token": auth_service.generate_token(self.user.id)}

    def test_an_actor_is_made_a_variant_keeps_its_project_scope_and_can_be_cleared(self):
        made = self.client.put(f"/api/elements/{self.young.id}/variant", cookies=self.cookies,
                               json={"of": "林夏", "label": "少年", "triggers": ["校服"], "episode_from": 1, "episode_to": 2})
        self.assertEqual(made.status_code, 200, made.text)
        metadata = made.json()["metadata"]
        self.assertEqual(metadata["variant"], {"of": "林夏", "label": "少年", "triggers": ["少年", "校服"], "episodes": [1, 2]})
        self.assertEqual(metadata["task_id"], "vp-1", "the project scope is untouched")

        self.assertEqual(self.client.put(f"/api/elements/{self.young.id}/variant", cookies=self.cookies, json={"of": "林夏"}).status_code, 422)
        self.assertEqual(self.client.put(f"/api/elements/{self.product.id}/variant", cookies=self.cookies, json={"of": "林夏", "label": "x"}).status_code, 422)
        cleared = self.client.delete(f"/api/elements/{self.young.id}/variant", cookies=self.cookies)
        self.assertEqual(cleared.status_code, 200)
        self.assertNotIn("variant", cleared.json()["metadata"])

    def test_products_are_a_library_kind(self):
        listed = self.client.get("/api/elements?kind=product", cookies=self.cookies)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["name"] for item in listed.json()["items"]], ["静音吹风机"])


if __name__ == "__main__":
    unittest.main()

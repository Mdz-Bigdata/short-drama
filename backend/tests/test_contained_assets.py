# -*- coding: utf-8 -*-
"""被包含的资产条目不单独出图：「香头」之于「偏殿香头」。第 3 步补图、资产库补齐图片和就绪检查都认这一条。"""

import unittest

from app.core import contained_assets
from app.core.character_variants import LOOK_SOURCE
from app.core.production_asset_readiness import evaluate_asset_readiness
from tests.test_production_asset_readiness import _summary, _task


def _look(name: str, of: str, has_image: bool = False) -> dict:
    return {"id": f"look-{name}", "kind": "actor", "name": name, "has_image": has_image,
            "metadata": {"task_id": "task-gate", "variant": {"of": of, "label": name.split("·", 1)[-1], "source": LOOK_SOURCE}}}


class ContainedAssetTests(unittest.TestCase):
    def test_a_name_inside_a_longer_one_of_the_same_kind_gets_no_image_of_its_own(self):
        rows = [
            _summary("set_dressing", "香头", False), _summary("set_dressing", "偏殿香头", False),
            _summary("set_dressing", "偏殿木门", False), _summary("set_dressing", "偏殿木门与门槛", False),
            _summary("set_dressing", "偏殿 门槛", False),  # 「偏殿门槛」不在「偏殿木门与门槛」里：照常出图
            _summary("prop", "香头", False),               # 别的类不比
        ]
        skipped = contained_assets.skip_ids(rows)
        self.assertEqual(skipped, {"set_dressing-香头", "set_dressing-偏殿木门"})

    def test_actors_and_looks_are_left_to_the_look_planner(self):
        """受伤前穿的「麻灰拭剑奴衣」被「麻灰拭剑奴衣·左颊剑伤」包含，但前几集要穿：定妆图由时间线定，这里不管。"""
        rows = [
            {"id": "actor-陈三", "kind": "actor", "name": "陈三", "has_image": True, "metadata": {"task_id": "task-gate"}},
            _look("沈无咎·麻灰拭剑奴衣", "沈无咎"),
            _look("沈无咎·麻灰拭剑奴衣·左颊剑伤", "沈无咎"),
        ]
        self.assertEqual(contained_assets.skip_ids(rows), set())

    def test_every_name_inside_another_of_its_kind_is_drawn_into_that_picture(self):
        """同一样东西的更全叫法(「牌位一排」⊂「偏殿牌位一排」)和配套的另一样东西(「长剑」⊂「长剑剑鞘」)都不单独出图；
        字面不包含的(「演武台掷接剑」与「演武台掷剑接剑」)照常各出一张。"""
        rows = [_summary(kind, name, False) for kind, name in [
            ("set_dressing", "牌位一排"), ("set_dressing", "偏殿牌位一排"), ("set_dressing", "偏殿供桌"), ("set_dressing", "偏殿供桌与牌位"),
            ("prop", "长剑"), ("prop", "长剑剑鞘"), ("prop", "刀"), ("prop", "刀鞘"), ("set_dressing", "门"), ("set_dressing", "偏殿门"),
            ("stunt", "演武台掷接剑"), ("stunt", "演武台掷剑接剑"),
        ]]
        skipped = {row["name"] for row in rows if row["id"] in contained_assets.skip_ids(rows)}
        self.assertEqual(skipped, {"牌位一排", "偏殿供桌", "长剑", "刀", "门"})

    def test_of_identical_names_only_one_is_drawn_preferring_the_one_with_an_image(self):
        rows = [
            {"id": "a", "kind": "effect", "name": "剑刃冷白光", "has_image": False, "metadata": {}},
            {"id": "b", "kind": "effect", "name": "剑刃 冷白光", "has_image": True, "metadata": {}},
            {"id": "c", "kind": "effect", "name": "剑刃冷白光。", "has_image": False, "metadata": {}},
        ]
        self.assertEqual(contained_assets.skip_ids(rows), {"a", "c"})

    def test_a_crowd_of_the_same_scene_is_drawn_once(self):
        """截图里的四条群演：山门那两拨是同一拨人(只差叫法)，只画一张；演武台、偏殿门槛外是别的场景，各画一张。"""
        rows = [_summary("extra", name, False) for name in ["演武台围观人群", "偏殿门槛外人群", "山门围观百姓", "山门围观人群"]]
        self.assertEqual(contained_assets.skip_ids(rows), {"extra-山门围观人群"})
        rows[3]["has_image"] = True  # 已有图的那条留着，另一条不再出
        self.assertEqual(contained_assets.skip_ids(rows), {"extra-山门围观百姓"})
        self.assertEqual(contained_assets.crowd_key("山门外围观的百姓"), "山门外围观")
        self.assertEqual(contained_assets.crowd_key("人群"), "人群", "去掉后不剩场景就按原名比")
        # 只有群演这样比：置景里「山门人群」「山门百姓」不是一回事。
        props = [_summary("set_dressing", "山门石狮人群", False), _summary("set_dressing", "山门石狮百姓", False)]
        self.assertEqual(contained_assets.skip_ids(props), set())
        self.assertTrue(contained_assets.contained_in("山门围观百姓", ["山门围观人群"], "extra"))
        self.assertFalse(contained_assets.contained_in("山门围观百姓", ["山门围观人群"]))
        self.assertFalse(contained_assets.contained_in("演武台围观人群", ["山门围观人群"], "extra"))

    def test_duplicates_are_same_names_and_same_crowds_not_contained_ones(self):
        rows = [
            _summary("extra", "山门围观百姓", False), _summary("extra", "山门围观人群", False), _summary("extra", "演武台围观人群", False),
            {"id": "a", "kind": "effect", "name": "剑刃冷白光", "has_image": False, "metadata": {}},
            {"id": "b", "kind": "effect", "name": "剑刃 冷白光", "has_image": True, "metadata": {}},
            _summary("set_dressing", "香头", False), _summary("set_dressing", "偏殿香头", False),
        ]
        groups = {keeper["id"]: [item["id"] for item in losers] for keeper, losers in contained_assets.duplicate_groups(rows)}
        self.assertEqual(groups, {"extra-山门围观百姓": ["extra-山门围观人群"], "b": ["a"]})

    def test_literal_containment_and_same_names(self):
        self.assertTrue(contained_assets.contained_in("香头", ["偏殿 香头"]))
        self.assertTrue(contained_assets.contained_in("灯", ["灯笼"]), "配套的也画进长的那张")
        self.assertFalse(contained_assets.covered_by("长剑", ["长剑剑鞘"][0]), "字面包含但是另一样东西：不算同一样东西的更全叫法")
        self.assertFalse(contained_assets.contained_in("偏殿香头", ["偏殿香头"]), "同名不算被包含")

    def test_readiness_counts_a_contained_name_as_ready_when_the_longer_one_has_an_image(self):
        task = _task()
        task["assets"]["2_breakdown"]["production_assets"]["props"] = [{"name": "长剑", "description": "剑"}]
        summaries = [
            _summary("scene", "长安城门", True), _summary("scene", "含元殿", True),
            _summary("prop", "带鞘长剑", True), _summary("effect", "火药爆炸", True),
        ]
        readiness = evaluate_asset_readiness(task, summaries)
        self.assertEqual(readiness["kinds"]["prop"]["missing"], [])
        self.assertTrue(readiness["complete"])
        summaries[2]["has_image"] = False
        self.assertEqual(evaluate_asset_readiness(task, summaries)["kinds"]["prop"]["missing"], ["长剑"])


if __name__ == "__main__":
    unittest.main()


class RelatedPairTests(unittest.TestCase):
    """字面包含却是另一样东西、两者相关的：画在一张图里，不分别出图；两条都用这张图。"""

    ROWS = [_summary(kind, name, False) for kind, name in [
        ("prop", "长剑"), ("prop", "长剑剑鞘"), ("prop", "刀"), ("prop", "刀鞘"),
        ("set_dressing", "门"), ("set_dressing", "偏殿门"),
        ("set_dressing", "香头"), ("set_dressing", "偏殿香头"), ("prop", "小锤"), ("prop", "陈三小锤"),
    ]]

    def _row(self, kind, name):
        return next(item for item in self.ROWS if item["kind"] == kind and item["name"] == name)

    def test_the_contained_one_is_not_drawn_on_its_own(self):
        skipped = {item["name"] for item in self.ROWS if item["id"] in contained_assets.skip_ids(self.ROWS)}
        self.assertEqual(skipped, {"长剑", "刀", "门", "香头", "小锤"})

    def test_the_fuller_one_draws_its_companions_into_the_same_picture(self):
        names = lambda kind, name: [row["name"] for row in contained_assets.companions(self._row(kind, name), self.ROWS)]
        self.assertEqual(names("prop", "长剑剑鞘"), ["长剑"])
        self.assertEqual(names("prop", "刀鞘"), ["刀"])
        self.assertEqual(names("set_dressing", "偏殿门"), ["门"])
        self.assertEqual(names("set_dressing", "偏殿香头"), [], "同一样东西的更全叫法不另画")
        self.assertEqual(names("prop", "陈三小锤"), [])

    def test_a_companion_that_already_has_a_picture_is_the_reference(self):
        rows = [dict(row, has_image=row["name"] == "长剑") for row in self.ROWS]
        sheath = next(row for row in rows if row["name"] == "长剑剑鞘")
        self.assertEqual(contained_assets.related_partner(sheath, rows)["name"], "长剑")
        self.assertIsNone(contained_assets.related_partner(self._row("prop", "长剑剑鞘"), self.ROWS))

    def test_readiness_counts_the_companion_once_the_shared_picture_exists(self):
        self.assertTrue(contained_assets.contained_in("刀", ["刀鞘"]))
        self.assertTrue(contained_assets.contained_in("长剑", ["长剑剑鞘"]))


class RelatedReferenceGenerationTests(unittest.TestCase):
    def _run(self, has_sword_image):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        from app.api import element_api

        def element(element_id, name, has_image):
            files = [SimpleNamespace(mime_type="image/png")] if has_image else []
            return SimpleNamespace(id=element_id, kind="set_dressing", name=name, files=files, owner_id="o",
                                   description="", metadata_json={"task_id": "t1", "task_ids": ["t1"]})

        sword, sheath, other = element("e1", "长剑", has_sword_image), element("e2", "长剑剑鞘", False), element("e3", "供桌", False)
        store = SimpleNamespace(list_all_elements=AsyncMock(return_value=[sword, sheath, other]),
                                merge_element_metadata=AsyncMock(return_value=None))
        calls, saved = [], []

        def generate(model, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return "https://img.test/x.png", "fake"

        async def persist(**kwargs):
            saved.append(kwargs["element_id"])
            return {"ok": True}

        with patch.object(element_api, "_element_generation_context", AsyncMock(return_value=("img-model", ""))), \
                patch.object(element_api, "_first_image_bytes", return_value=b"sword-bytes"), \
                patch.object(element_api, "_validated_generated_image", return_value=(".png", "image/png")), \
                patch.object(element_api, "_load_generated_image_bytes", return_value=b"new"), \
                patch.object(element_api, "_persist_element_file", side_effect=persist), \
                patch.object(element_api.element_image_gateway, "generate_image", side_effect=generate):
            asyncio.run(element_api._generate_non_actor_reference(item=sheath, owner_id="o", store=store))
            asyncio.run(element_api._generate_non_actor_reference(item=other, owner_id="o", store=store))
        return calls, saved, store

    def test_the_sheath_and_the_sword_are_one_picture_shared_by_both(self):
        calls, saved, store = self._run(has_sword_image=False)
        prompt, kwargs = calls[0]
        self.assertIn("本图把「长剑」和「长剑剑鞘」画在同一张图里", prompt)
        self.assertNotIn("ref_images", kwargs, "长剑还没图：照文字一起画")
        self.assertEqual(saved[:2], ["e1", "e2"], "长剑也存上这张图，再存剑鞘自己的")
        store.merge_element_metadata.assert_any_await("e2", "o", {"drawn_together": ["长剑"]})
        store.merge_element_metadata.assert_any_await("e1", "o", {"drawn_with": "长剑剑鞘"})
        self.assertNotIn("ref_images", calls[1][1], "没有配套的照旧")
        self.assertNotIn("同一张图", calls[1][0])

    def test_an_earlier_picture_of_the_sword_is_reference_one(self):
        calls, saved, _store = self._run(has_sword_image=True)
        prompt, kwargs = calls[0]
        self.assertTrue(prompt.startswith("参考图1是已经画好的「长剑」"), prompt[:40])
        self.assertEqual(len(kwargs["ref_images"]), 1)
        self.assertEqual(saved[0], "e2", "长剑已有图：不覆盖")

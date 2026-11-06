"""拆解补充类别：群演、车辆、特技、置景、化妆从剧本里提得出、绑得上分镜、进得了资产库，但不拦分镜。"""

import unittest

from app.core import breakdown_kinds, production_asset_readiness as readiness
from app.core.production_asset_extractor import extract_production_assets
from app.core.screenwriting.models import AssetInventory
from app.core.screenwriting.prompts import build_asset_inventory_prompt
from app.core.screenwriting.renderer import render_breakdown
from app.core.storyboard_scene_context import LABELS, compile_scene_context, panel_context, reference_note
from app.platform.store import ELEMENT_KINDS
from app.schema.platform import ElementKind
from app.service.drama_service import DramaService

SCRIPT = """第1集
【场景一：码头】夜
码头苦力搬着麻袋来来往往。沈砚从一辆黑色马车上跳下来，右手攥着玉牌。

- 群演：码头苦力（十来个短打搬麻袋）
- 车辆：黑色马车（双驾旧车厢）
- 特技：沈砚跳车（从行进的马车上跃下滚地卸力）
- 置景：码头灯笼（竹骨红纸挂在桩上）
- 化妆：沈砚·额角刀伤（三寸结痂从第1集起）
"""


class ListTests(unittest.TestCase):
    def test_the_five_kinds_are_known_everywhere(self):
        for kind in breakdown_kinds.KINDS:
            self.assertIn(kind, ELEMENT_KINDS)
            self.assertIn(kind, ElementKind.__args__)
            self.assertIn(kind, LABELS)
            self.assertIn(kind, readiness.LIBRARY_KINDS)
            self.assertIn(kind, readiness.KIND_LABELS)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.task = {"task_id": "t", "config": {}, "assets": {"2": SCRIPT, "2_breakdown": {"scenes": []}}}

    def test_each_kind_is_read_from_its_section(self):
        names = {kind: [item["name"] for item in extract_production_assets(self.task, kind)] for kind in breakdown_kinds.KINDS}
        self.assertEqual(names["extra"], ["码头苦力"])
        self.assertEqual(names["vehicle"], ["黑色马车"])
        self.assertEqual(names["stunt"], ["沈砚跳车"])
        self.assertEqual(names["set_dressing"], ["码头灯笼"])
        self.assertEqual(names["makeup"], ["沈砚·额角刀伤"])

    def test_a_stunt_may_be_named_by_its_action(self):
        self.task["assets"]["2"] = "- 特技：主角撞破窗户甩出\n"
        self.assertEqual([item["name"] for item in extract_production_assets(self.task, "stunt")], ["主角撞破窗户甩出"])
        self.task["assets"]["2"] = "- 道具：主角撞破窗户甩出\n"
        self.assertEqual(extract_production_assets(self.task, "prop"), [])

    def test_the_writer_catalog_wins_when_it_lists_them(self):
        self.task["assets"]["2_breakdown"]["production_assets"] = {"vehicles": [{"name": "青篷马车", "description": "x"}]}
        self.assertEqual([item["name"] for item in extract_production_assets(self.task, "vehicle")], ["青篷马车"])


class BindingTests(unittest.TestCase):
    def _context(self):
        task = {"task_id": "t", "assets": {"3_characters": [{"name": "沈砚", "desc": "青衫"}]}, "config": {}}
        scene = {"scene_id": "E1S01", "content": "码头，桩上挂着码头灯笼。沈砚额角刀伤未愈，从黑色马车上跳下来，码头苦力让开。", "characters": ["沈砚"], "location": "码头"}
        elements = [
            {"id": "1", "kind": "actor", "name": "沈砚", "description": "青衫", "metadata": {}, "image_url": "data:a"},
            {"id": "2", "kind": "vehicle", "name": "黑色马车", "description": "双驾", "metadata": {}, "image_url": "data:v"},
            {"id": "3", "kind": "extra", "name": "码头苦力", "description": "短打", "metadata": {}, "image_url": "data:e"},
            {"id": "4", "kind": "makeup", "name": "沈砚·额角刀伤", "description": "沈砚，三寸结痂", "metadata": {}, "image_url": "data:m"},
            {"id": "5", "kind": "set_dressing", "name": "码头灯笼", "description": "竹骨红纸", "metadata": {}, "image_url": "data:s"},
            {"id": "6", "kind": "stunt", "name": "沈砚跳车", "description": "跃下滚地", "metadata": {}, "image_url": "data:t"},
        ]
        return compile_scene_context(task, scene, elements)

    def test_named_things_and_the_makeup_of_the_cast_are_bound_and_the_rest_are_not(self):
        binding = panel_context(self._context(), {"desc": "沈砚从黑色马车上跳下来，码头苦力让开", "characters": ["沈砚"]})
        kinds = [(item["kind"], item["name"]) for item in binding["references"]]
        self.assertIn(("vehicle", "黑色马车"), kinds)
        self.assertIn(("extra", "码头苦力"), kinds)
        self.assertIn(("makeup", "沈砚·额角刀伤"), kinds, "a wound travels with its face")
        self.assertNotIn(("set_dressing", "码头灯笼"), kinds, "not in this panel's action")
        self.assertNotIn(("stunt", "沈砚跳车"), kinds)
        quiet = panel_context(self._context(), {"desc": "沈砚抬头看码头灯笼", "characters": ["沈砚"]})
        self.assertIn(("set_dressing", "码头灯笼"), [(item["kind"], item["name"]) for item in quiet["references"]])

    def test_a_wound_is_not_drawn_in_a_scene_that_does_not_mention_it(self):
        task = {"task_id": "t", "assets": {"3_characters": [{"name": "沈砚", "desc": "青衫"}]}, "config": {}}
        scene = {"scene_id": "E1S01", "content": "沈砚在码头散步。", "characters": ["沈砚"], "location": "码头"}
        elements = [
            {"id": "1", "kind": "actor", "name": "沈砚", "description": "青衫", "metadata": {}, "image_url": "data:a"},
            {"id": "4", "kind": "makeup", "name": "沈砚·额角刀伤", "description": "沈砚，三寸结痂", "metadata": {}, "image_url": "data:m"},
        ]
        binding = panel_context(compile_scene_context(task, scene, elements), {"desc": "沈砚散步", "characters": ["沈砚"]})
        self.assertNotIn("makeup", [item["kind"] for item in binding["references"]])

    def test_each_kind_has_its_own_reference_sentence(self):
        self.assertIn("人群疏密", reference_note(2, {"kind": "extra", "name": "码头苦力"}))
        self.assertIn("不采用图中脸型、五官", reference_note(3, {"kind": "makeup", "name": "沈砚·额角刀伤"}))
        self.assertIn("接触点", reference_note(4, {"kind": "stunt", "name": "沈砚跳车"}))
        for kind in ("vehicle", "set_dressing"):
            note = reference_note(5, {"kind": kind, "name": "x"})
            self.assertIn(breakdown_kinds.LABELS[kind], note)
            self.assertNotIn("；", note)


class ReadinessTests(unittest.TestCase):
    def test_missing_pictures_are_counted_but_never_block(self):
        task = {"task_id": "t", "owner_user_id": "u", "config": {}, "assets": {"2": SCRIPT, "2_breakdown": {"scenes": []}, "3_characters": []}}
        result = readiness.evaluate_asset_readiness(task, [])
        self.assertEqual(result["kinds"]["vehicle"]["missing"], ["黑色马车"])
        self.assertFalse(result["kinds"]["vehicle"]["enforced"])
        blocking = [kind for kind, info in result["kinds"].items() if info["missing"] and info["enforced"]]
        self.assertNotIn("vehicle", blocking)
        self.assertNotIn("extra", blocking)


class WriterTests(unittest.TestCase):
    def test_the_inventory_accepts_the_new_lists_and_renders_them(self):
        inventory = AssetInventory.model_validate({"characters": {}, "vehicles": [{"name": "黑色马车", "description": "双驾"}], "makeup": {"沈砚·刀伤": {"description": "三寸"}}})
        self.assertEqual(list(inventory.vehicles), ["黑色马车"])
        rendered = render_breakdown({"inventory": inventory.model_dump(), "overview": {}})
        self.assertEqual(rendered["production_assets"]["vehicles"], [{"name": "黑色马车", "description": "双驾"}])
        self.assertEqual(rendered["production_assets"]["makeup"], [{"name": "沈砚·刀伤", "description": "三寸"}])
        self.assertEqual(rendered["production_assets"]["extras"], [])

    def test_the_writer_is_told_what_each_kind_is(self):
        prompt = build_asset_inventory_prompt("沈砚跳车。", source_kind="novel", overview={}, existing={"vehicles": ["黑色马车"]})
        for word in ("群演（extras）", "车辆（vehicles）", "特技（stunts）", "置景（set_dressing）", "化妆（makeup）", "已登记车辆：黑色马车"):
            self.assertIn(word, prompt)

    def test_an_older_catalog_is_not_sent_back_to_the_model_for_them(self):
        service = DramaService.__new__(DramaService)
        task = {"assets": {"2": "剧本", "2_breakdown": {"production_assets": {"scenes": [{"name": "码头"}], "props": [], "costumes": [{"name": "x"}], "effects": [{"name": "y"}]}}}, "config": {}}
        self.assertEqual(service._catalog_kinds_to_fill(task), [])
        catalog, changed = service._fill_production_catalog(task)
        self.assertFalse(changed)
        for key in breakdown_kinds.CATALOG_KEYS.values():
            self.assertEqual(catalog[key], [])

if __name__ == "__main__":
    unittest.main()

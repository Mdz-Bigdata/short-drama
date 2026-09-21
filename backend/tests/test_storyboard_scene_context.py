import unittest

from app.core.storyboard_scene_context import compile_scene_context, panel_context


class SceneContextTests(unittest.TestCase):
    def test_effect_label_word_order_and_guard_uniform_do_not_break_binding(self):
        self.task["assets"]["2_breakdown"]["production_assets"]["effects"] = [
            {"name": "血痕三道", "description": "指尖划出的暗红血痕"}
        ]
        self.task["assets"]["2_breakdown"]["production_assets"]["costumes"] = [
            {"name": "贺兰霆官袍", "description": "贺兰霆，玄黑官袍"},
            {"name": "墨羽卫甲胄", "description": "贺兰霆亲卫，黑甲"},
        ]
        context = compile_scene_context(self.task, self.scene)
        self.assertEqual([item["name"] for item in context["costumes"]], ["贺兰霆官袍"])
        panel = panel_context(context, {"desc": "沈砚指尖划出三道血痕"})
        self.assertEqual(panel["effects"], ["血痕三道"])

    def setUp(self):
        self.scene = {
            "scene_id": "E2S03",
            "characters": ["沈砚", "贺兰霆"],
            "content": "太常寺天文台夜内景，沈砚跪在青石阶上，指尖划出三道血痕。贺兰霆的玄色官靴踏出阴影。",
            "dialogue": "贺兰霆：十年前，你爹也这样跪着死。",
        }
        self.task = {
            "assets": {
                "2": "整部剧本包括谢云遥、太后与金銮殿大战。",
                "3_characters": [
                    {"name": "沈砚", "desc": "墨青长袍，左眉旧疤"},
                    {"name": "贺兰霆", "desc": "玄黑官袍"},
                    {"name": "谢云遥", "desc": "月白长裙"},
                ],
                "3_sheets": {
                    "沈砚": "https://img.test/shen.png",
                    "谢云遥": "https://img.test/xie.png",
                },
                "2_breakdown": {
                    "production_assets": {
                        "scenes": [
                            {
                                "name": "太常寺天文台",
                                "description": "青石阶、星盘；蓝色月光",
                            },
                            {"name": "金銮殿", "description": "龙椅"},
                        ],
                        "props": [{"name": "铜针", "description": "下一场偷袭用"}],
                        "costumes": [
                            {"name": "沈砚常服", "description": "沈砚的墨青长袍"},
                            {"name": "谢云遥长裙", "description": "谢云遥的月白长裙"},
                        ],
                        "effects": [
                            {"name": "血痕", "description": "三道暗红痕迹渗入石纹"},
                            {"name": "爆炸", "description": "火光冲天"},
                        ],
                    }
                },
            }
        }

    def test_only_current_scene_actors_and_five_asset_categories(self):
        context = compile_scene_context(self.task, self.scene)
        self.assertEqual(context["characters"], ["沈砚", "贺兰霆"])
        self.assertIn("十年前", context["script"])
        self.assertIn("青石阶、星盘", context["prompt"])
        self.assertIn("沈砚常服", context["prompt"])
        self.assertIn("暗红痕迹", context["prompt"])
        for unrelated in ("谢云遥", "金銮殿", "铜针", "爆炸", "整部剧本"):
            self.assertNotIn(unrelated, context["prompt"])

    def test_local_library_overrides_catalog_and_keeps_reference_labels(self):
        context = compile_scene_context(
            self.task,
            self.scene,
            elements=[
                {
                    "kind": "scene",
                    "id": "observatory",
                    "name": "太常寺天文台",
                    "description": "批准布局：石阶向北",
                    "image_url": "data:image/png;base64,AAAA",
                },
                {
                    "kind": "effect",
                    "name": "血痕",
                    "description": "另一场血痕",
                    "metadata": {"scene_ids": ["E2S04"]},
                },
            ],
        )
        panel = panel_context(
            context,
            {
                "desc": "沈砚指尖划出三道血痕",
                "characters": ["沈砚"],
                "characters_explicit": True,
            },
        )
        self.assertIn("批准布局：石阶向北", panel["prompt"])
        self.assertNotIn("另一场", panel["prompt"])
        self.assertEqual(
            [ref["name"] for ref in panel["references"]], ["沈砚", "太常寺天文台"]
        )

    def test_empty_shot_does_not_bind_arbitrary_character_references(self):
        context = compile_scene_context(self.task, self.scene)
        panel = panel_context(
            context,
            {
                "desc": "青石阶上三道血痕",
                "characters": ["无"],
                "characters_explicit": True,
            },
        )
        self.assertEqual(panel["characters"], ["空镜（无人物）"])
        self.assertFalse(any(ref["kind"] == "actor" for ref in panel["references"]))
        self.assertNotIn("墨青长袍", panel["prompt"])

    def test_out_of_scene_actor_and_generic_filler_are_rejected(self):
        context = compile_scene_context(self.task, self.scene)
        for shot in (
            {"desc": "谢云遥走进来", "characters": ["谢云遥"]},
            {"desc": "主角与反派在cyberpunk下的剧情推进分镜9"},
        ):
            with self.assertRaises(ValueError):
                panel_context(context, shot)

    def test_visible_actor_cannot_be_omitted_from_explicit_cast(self):
        context = compile_scene_context(self.task, self.scene)
        for shot in (
            {"desc": "沈砚低头", "characters": ["无"], "characters_explicit": True},
            {
                "desc": "沈砚低头，贺兰霆的手按住他的肩膀",
                "characters": ["沈砚"],
                "characters_explicit": True,
            },
        ):
            with self.assertRaisesRegex(ValueError, "入镜角色列不一致"):
                panel_context(context, shot)

    def test_ambiguous_costume_states_are_not_selected_by_actor_alone(self):
        self.task["assets"]["2_breakdown"]["production_assets"]["costumes"].append(
            {"name": "沈砚朝服", "description": "沈砚次日上朝穿着"}
        )
        context = compile_scene_context(self.task, self.scene)
        self.assertEqual(context["costumes"], [])


if __name__ == "__main__":
    unittest.main()

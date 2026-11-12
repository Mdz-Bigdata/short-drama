import unittest

from app.core.storyboard_scene_context import bind_scene_frames, compile_scene_context, crowd_on_set, merge_video_references, panel_context
from app.core.video_references import VideoReferencePlan, renumber_reference_mentions


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
        written = " ".join(item["description"] for item in panel["assets"])
        self.assertIn("批准布局：石阶向北", written)
        self.assertNotIn("另一场", written)
        self.assertEqual(
            [ref["name"] for ref in panel["references"]], ["沈砚", "太常寺天文台"]
        )

    def test_only_the_view_that_frames_the_shot_is_sent(self):
        views = {slot: f"data:image/png;base64,{slot}" for slot in ("scene_45", "scene_depth", "scene_detail", "scene_reverse")}
        context = compile_scene_context(
            self.task,
            self.scene,
            elements=[{
                "kind": "scene", "id": "observatory", "name": "太常寺天文台", "description": "石阶向北",
                "image_url": "data:image/png;base64,AAAA", "views": views,
            }],
        )
        shot = {"desc": "沈砚抬头", "characters": ["沈砚"], "characters_explicit": True}

        def sent(**framing):
            panel = panel_context(context, {**shot, **framing})
            return [(ref.get("view") or "scene_main", ref.get("frame")) for ref in panel["references"] if ref["kind"] == "scene"]

        self.assertEqual(sent(size="全景"), [("scene_main", None)])
        self.assertEqual(sent(size="中景", angle="过肩"), [("scene_main", "space_only"), ("scene_45", "composition")])
        self.assertEqual(sent(size="近景", angle="反打"), [("scene_main", "space_only"), ("scene_reverse", "composition")])

    def test_a_crowd_stays_on_set_between_the_shots_that_name_it(self):
        # 文章里的 bug：第一镜教室空着、下一镜突然坐满。剧本里在场的群演每一镜都在背景里。
        self.scene["content"] += "殿下宫女若干垂首侍立。"
        catalog = self.task["assets"]["2_breakdown"]["production_assets"]
        catalog["extras"] = [{"name": "宫女", "description": "六名，青衣，垂首侍立"}, {"name": "禁军", "description": "十名甲士"}]
        self.scene["content"] += "禁军涌入。"
        context = compile_scene_context(self.task, self.scene)
        shots = [
            {"desc": "沈砚跪在青石阶上", "characters": ["沈砚"]},
            {"desc": "宫女垂首，贺兰霆踏出阴影", "characters": ["贺兰霆"]},
            {"desc": "禁军涌入殿门，沈砚抬头", "characters": ["沈砚"]},
            {"desc": "宫女退下，殿内只剩两人", "characters": ["沈砚", "贺兰霆"]},
            {"desc": "贺兰霆俯身逼近沈砚", "characters": ["沈砚", "贺兰霆"]},
        ]
        on_set = crowd_on_set(context, shots)
        self.assertEqual([sorted(names) for names in on_set], [
            ["宫女"], ["宫女"], ["宫女", "禁军"], ["宫女", "禁军"], ["禁军"],
        ])
        # 第一镜没点名宫女，绑定里照样有她们。
        panel = panel_context(context, shots[0], crowd=on_set[0])
        self.assertIn("宫女", [item["name"] for item in panel["assets"]])
        self.assertNotIn("宫女", [item["name"] for item in panel_context(context, shots[4], crowd=on_set[4])["assets"]])
        # 视频提示词：没点名的那一镜补一句；点了名的不重复。
        from app.core.storyboard_scene_context import crowd_lines
        lines = crowd_lines(context, shots[0], on_set[0])
        self.assertEqual(len(lines), 1)
        self.assertIn("背景里照常有本场在场的宫女（六名，青衣，垂首侍立）", lines[0])
        self.assertEqual(crowd_lines(context, shots[1], on_set[1]), [])

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
        self.assertFalse(any(item["kind"] == "actor" for item in panel["assets"]))

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


class SceneFrameTests(unittest.TestCase):
    """几张场地视角图一起发：一张是本镜唯一的场景构图来源，其余只核对陈设。"""

    @staticmethod
    def _references(actor=True):
        cast = [{"kind": "actor", "name": "赵光义", "image_url": "a"}] if actor else []
        views = [{"kind": "scene", "name": "大殿", "image_url": view, "view": view} for view in ("scene_45", "scene_depth", "scene_detail")]
        return cast + [{"kind": "scene", "name": "大殿", "image_url": "main"}] + views

    def _frames(self, shot, actor=True):
        references = self._references(actor)
        bind_scene_frames(references, shot, empty_shot=not actor)
        return {item.get("view") or "scene_main": item["frame"] for item in references if item["kind"] == "scene"}

    def test_one_view_is_the_composition_source(self):
        self.assertEqual(self._frames({"size": "全景", "angle": "平视"})["scene_main"], "composition")
        frames = self._frames({"size": "中景", "angle": "侧面过肩"})
        self.assertEqual(frames["scene_45"], "composition")
        self.assertEqual(list(frames.values()).count("composition"), 1)

    def test_detail_view_only_frames_an_empty_insert(self):
        self.assertEqual(self._frames({"size": "特写"})["scene_main"], "composition")
        self.assertEqual(self._frames({"size": "特写"}, actor=False)["scene_detail"], "composition")

    def test_reverse_shot_has_no_composition_source(self):
        self.assertEqual(set(self._frames({"size": "近景", "angle": "反打"}).values()), {"reverse"})

    def test_reverse_plate_frames_a_reverse_shot(self):
        references = self._references() + [{"kind": "scene", "name": "大殿", "image_url": "rev", "view": "scene_reverse"}]
        bind_scene_frames(references, {"angle": "反打"}, empty_shot=False)
        frames = {item.get("view") or "scene_main": item["frame"] for item in references if item["kind"] == "scene"}
        self.assertEqual(frames["scene_reverse"], "composition")
        self.assertEqual(list(frames.values()).count("composition"), 1)

    def test_an_actor_is_sent_as_front_full_body_then_front_headshot(self):
        from app.core.storyboard_scene_context import reference_note
        from app.service.drama_service import with_sheet_faces
        note = reference_note(2, {"kind": "actor", "name": "断水", "image_url": "face", "view": "face"}, label="数字演员")
        self.assertIn("参考图2仅锁定数字演员「断水」正面大头照里的脸型骨相", note)
        self.assertIn("发型、头饰与服装以这个人的正面全身照为准", note)
        self.assertNotIn("；", note)
        # 设定集兜底的人也配上大头照；已经发了的图不重复。
        references = with_sheet_faces([("断水", "body"), ("沈砚", "s-body")], [], {"断水": "face", "沈砚": "s-body"})
        self.assertEqual(references, [{"kind": "actor", "name": "断水", "image_url": "face", "view": "face"}])
        _, notes = merge_video_references([("断水", "body")], references)
        self.assertIn("参考图1仅锁定数字演员设定集「断水」的脸型", notes)
        self.assertIn("参考图2仅锁定数字演员设定集「断水」正面大头照", notes)

    def test_a_look_brings_its_own_bust_but_a_real_person_keeps_the_photo(self):
        from app.core import character_variants
        look = {"id": "look", "image_url": "look-body", "face_url": "look-bust", "variant": {"label": "残衣"}}
        self.assertEqual(character_variants.apply({"name": "断水", "image_url": "b", "face_url": "f"}, look)["face_url"], "look-bust")
        real = {"name": "沈砚", "image_url": "b", "face_url": "photo", "real_person": True}
        self.assertEqual(character_variants.apply(real, look)["face_url"], "photo")
        self.assertEqual(character_variants.apply({"name": "断水", "face_url": "f"}, {"id": "old", "image_url": "board"})["face_url"], "f")

    def test_single_scene_image_gets_no_frame(self):
        references = [{"kind": "scene", "name": "大殿", "image_url": "main"}]
        bind_scene_frames(references, {"size": "全景"}, empty_shot=True)
        self.assertNotIn("frame", references[0])

    def test_notes_survive_renumbering_and_yield_to_the_opening_frame(self):
        references = self._references()
        bind_scene_frames(references, {"size": "全景"}, empty_shot=False)
        images, notes = merge_video_references([], references)
        self.assertIn("是本镜唯一的场景构图来源", notes)
        self.assertNotIn("用于走位与转身时的透视", notes)
        prompt = "【参考素材职责】\n" + notes + "。"
        plain = VideoReferencePlan(mode="multi_reference", provider_family="seedance", provider_status="x", reference_images=images)
        self.assertEqual(renumber_reference_mentions(prompt, images, plain).count("唯一的场景构图来源"), 1)
        opened = plain.model_copy(update={"reference_images": ["frame", *images]})
        text = renumber_reference_mentions(prompt, images, opened)
        self.assertNotIn("唯一的场景构图来源", text)
        self.assertIn("开场构图以开场画面为准", text)


if __name__ == "__main__":
    unittest.main()

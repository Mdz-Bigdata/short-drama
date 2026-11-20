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
        # 过肩是正反打里的一镜：场地有反打视角时成对发正面与反打(没有反打视角时照旧挑 45°，见 test_reference_numbering)。
        self.assertEqual(sent(size="中景", angle="过肩"), [("scene_main", "composition"), ("scene_reverse", "reverse_space")])
        self.assertEqual(sent(size="中景", angle="侧面"), [("scene_main", "space_only"), ("scene_45", "composition")])
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


class ShotReversePairTests(unittest.TestCase):
    """一组正反打里的一镜：场地有反打视角时，正面(主场景全景)与反打成对发出，各自写明方向。"""

    FRONT = "参考图{}仅锁定拍摄场地「磨刀铺内」正面的空间布局"
    BACK = "参考图{}仅锁定拍摄场地「磨刀铺内」反打（与正面相对）的空间布局"
    PAIR = "正面与反打是同一场地、同一画风，左右按机位方向互换"

    def _context(self, reverse=True, props=0):
        slots = ("scene_45", "scene_depth", "scene_detail", *(("scene_reverse",) if reverse else ()))
        views = {slot: f"data:{slot}" for slot in slots}
        names = [f"刀{i}" for i in range(props)]
        task = {"assets": {
            "3_characters": [{"name": "沈砚", "desc": "墨青长袍"}, {"name": "贺兰霆", "desc": "玄黑官袍"}],
            "3_sheets": {"沈砚": "data:shen", "贺兰霆": "data:he"},
        }}
        scene = {"scene_id": "E1S02", "characters": ["沈砚", "贺兰霆"], "content": "磨刀铺内，沈砚与贺兰霆对坐。" + "".join(names)}
        elements = [{"kind": "scene", "id": "shop", "name": "磨刀铺内", "description": "", "image_url": "data:main", "views": views}]
        elements += [{"kind": "prop", "name": name, "image_url": f"data:{name}"} for name in names]
        return compile_scene_context(task, scene, elements), names

    def _send(self, shot, **kwargs):
        context, names = self._context(**kwargs)
        shot = {"desc": "、".join(shot["characters"]) + "在铺里" + "".join(names), **shot}
        references = panel_context(context, shot, layout="磨刀石在画面左侧")["references"]
        scenes = [(ref.get("view") or "scene_main", ref.get("frame")) for ref in references if ref["kind"] == "scene"]
        images, notes = merge_video_references([], references)
        return references, scenes, images, notes

    def _number(self, references, view):
        return next(number for number, ref in enumerate(references, 1) if ref["kind"] == "scene" and (ref.get("view") or "scene_main") == view)

    def test_a_dialogue_two_shot_sends_front_and_reverse_with_their_duties(self):
        references, scenes, _, notes = self._send({"characters": ["沈砚", "贺兰霆"], "size": "中景", "dialogue": "沈砚：刀磨好了。"})
        self.assertEqual(scenes, [("scene_main", "composition"), ("scene_reverse", "reverse_space")])
        front, back = self._number(references, "scene_main"), self._number(references, "scene_reverse")
        self.assertIn(self.FRONT.format(front) + "，光线与天色以本场为准、不照搬此图（磨刀石在画面左侧），是本镜唯一的场景构图来源", notes)
        self.assertIn(self.BACK.format(back) + "，光线与天色以本场为准、不照搬此图，是反打方向（机位身后一侧），只核对那一侧的陈设，本镜不拍这一侧", notes)
        self.assertEqual(notes.count(self.PAIR), 1)
        self.assertNotIn("；", notes.split(self.BACK.format(back))[1].split("不是额外剧情或额外人物")[0], "the pair note stays inside its line")
        self.assertNotIn("反打视角，用于", notes)

    def test_a_reverse_shot_frames_on_the_reverse_plate_and_still_sends_the_front(self):
        references, scenes, _, notes = self._send({"characters": ["贺兰霆"], "size": "近景", "angle": "反打"})
        self.assertEqual(scenes, [("scene_main", "space_only"), ("scene_reverse", "composition")])
        self.assertIn(self.BACK.format(self._number(references, "scene_reverse")) + "，光线与天色以本场为准、不照搬此图，是本镜唯一的场景构图来源", notes)
        self.assertIn(self.FRONT.format(self._number(references, "scene_main")), notes)
        self.assertEqual(notes.count(self.PAIR), 1)

    def test_over_the_shoulder_framing_alone_makes_an_exchange(self):
        _, scenes, _, notes = self._send({"characters": ["沈砚"], "size": "中近景", "framing": "正反打"})
        self.assertEqual(scenes, [("scene_main", "composition"), ("scene_reverse", "reverse_space")])
        self.assertIn(self.PAIR, notes)
        # 「正反打」不说这一镜是反打那一侧；写了「过肩反打」才是。
        _, scenes, _, _ = self._send({"characters": ["沈砚"], "angle": "过肩反打"})
        self.assertEqual(scenes, [("scene_main", "space_only"), ("scene_reverse", "composition")])

    def test_a_lone_close_up_sends_only_the_front_as_before(self):
        references, scenes, _, notes = self._send({"characters": ["沈砚"], "size": "特写", "dialogue": "沈砚：刀磨好了。"})
        self.assertEqual(scenes, [("scene_main", None)])
        self.assertIn(self.FRONT.format(self._number(references, "scene_main")) + "，光线与天色以本场为准、不照搬此图（磨刀石在画面左侧），图中人物不作参考", notes)
        self.assertNotIn("反打", notes)
        # 两人同框却没有台词：不算正反打。
        _, scenes, _, _ = self._send({"characters": ["沈砚", "贺兰霆"], "size": "全景"})
        self.assertEqual(scenes, [("scene_main", None)])

    def test_without_a_reverse_plate_the_views_are_sent_as_before(self):
        dialogue = {"characters": ["沈砚", "贺兰霆"], "size": "中景", "dialogue": "沈砚：刀磨好了。"}
        _, scenes, _, notes = self._send(dialogue, reverse=False)
        self.assertEqual(scenes, [("scene_main", None)])
        self.assertNotIn(self.PAIR, notes)
        _, scenes, _, _ = self._send({**dialogue, "angle": "过肩"}, reverse=False)
        self.assertEqual(scenes, [("scene_main", "space_only"), ("scene_45", "composition")])
        _, scenes, _, _ = self._send({"characters": ["贺兰霆"], "angle": "反打"}, reverse=False)
        self.assertEqual(scenes, [("scene_main", "reverse")])

    def test_the_cast_and_props_keep_their_places_within_nine(self):
        dialogue = {"characters": ["沈砚", "贺兰霆"], "size": "中景", "dialogue": "沈砚：刀磨好了。"}
        # 两位演员 + 主场景 + 5 件道具 = 8：反打视角坐第 9 张。
        references, scenes, _, notes = self._send(dialogue, props=5)
        self.assertEqual(len(references), 9)
        self.assertEqual(references[-1].get("view"), "scene_reverse")
        self.assertIn(self.PAIR, notes)
        # 再多一件道具就满了：道具优先，反打视角不发，也不说成对。
        references, scenes, _, notes = self._send(dialogue, props=6)
        self.assertEqual(len(references), 9)
        self.assertEqual(sum(1 for ref in references if ref["kind"] == "prop"), 6)
        self.assertEqual(scenes, [("scene_main", None)])
        self.assertNotIn(self.PAIR, notes)

    def test_the_pair_note_leaves_with_the_reverse_plate(self):
        references, _, images, notes = self._send({"characters": ["沈砚", "贺兰霆"], "size": "中景", "dialogue": "沈砚：刀磨好了。"})
        prompt = "【参考素材职责】\n" + notes + "。"
        both = VideoReferencePlan(mode="multi_reference", provider_family="seedance", provider_status="x", reference_images=images)
        self.assertEqual(renumber_reference_mentions(prompt, images, both).count(self.PAIR), 1)
        reverse = images[self._number(references, "scene_reverse") - 1]
        front_only = both.model_copy(update={"reference_images": [url for url in images if url != reverse]})
        text = renumber_reference_mentions(prompt, images, front_only)
        self.assertNotIn(self.PAIR, text)
        self.assertNotIn("反打（与正面相对）", text)
        self.assertIn("「磨刀铺内」正面的空间布局", text)


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

    def test_front_and_reverse_split_the_duties_by_the_shot_direction(self):
        pair = [{"kind": "scene", "name": "大殿", "image_url": "main"}, {"kind": "scene", "name": "大殿", "image_url": "rev", "view": "scene_reverse"}]
        bind_scene_frames(pair, {"size": "中景"}, empty_shot=False)
        self.assertEqual([(item["frame"], item.get("pair")) for item in pair], [("composition", None), ("reverse_space", True)])
        bind_scene_frames(pair, {"angle": "反打"}, empty_shot=False)
        self.assertEqual([(item["frame"], item.get("pair")) for item in pair], [("space_only", None), ("composition", True)])

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

    def _profile_context(self, cast=("沈砚",), **extra):
        task = {"assets": {"3_characters": [{"name": name, "desc": "墨青长袍"} for name in cast], "3_sheets": {}}}
        scene = {"scene_id": "E1S02", "characters": list(cast), "content": "磨刀铺内。"}
        elements = [
            {"kind": "actor", "id": f"a{index}", "name": name, "description": "", "image_url": f"data:body{index}",
             "face_url": f"data:face{index}", "side_face_url": f"data:side{index}", **extra}
            for index, name in enumerate(cast)
        ]
        return compile_scene_context(task, scene, elements)

    def test_a_shot_with_a_head_turn_brings_the_side_face_after_the_front_pair(self):
        from app.core.storyboard_scene_context import reference_note, side_view
        self.assertTrue(side_view("沈砚回头看向门口"))
        self.assertFalse(side_view("沈砚抬刀"))
        context = self._profile_context()
        turned = panel_context(context, {"desc": "沈砚回头看向门口，侧脸被炉火照亮"})["references"]
        self.assertEqual([(item["image_url"], item.get("view"), item.get("angle")) for item in turned if item["kind"] == "actor"],
                         [("data:body0", None, None), ("data:face0", "face", None), ("data:side0", "face", "side")])
        note = reference_note(3, turned[2], label="数字演员")
        self.assertIn("参考图3仅锁定数字演员「沈砚」转头和侧脸时的侧面轮廓", note)
        self.assertIn("正面相貌仍以这个人的正面大头照为准", note)
        self.assertNotIn("；", note)
        self.assertNotIn("。", note)
        # 没有转头和侧脸的镜头照旧只发两张。
        plain = panel_context(context, {"desc": "沈砚抬刀"})["references"]
        self.assertEqual([item["image_url"] for item in plain if item["kind"] == "actor"], ["data:body0", "data:face0"])

    def test_the_side_face_is_left_out_of_crowded_shots_and_for_real_people(self):
        crowded = self._profile_context(cast=("沈砚", "贺兰霆", "断水"))
        references = panel_context(crowded, {"desc": "沈砚、贺兰霆、断水同时回头"})["references"]
        self.assertFalse([item for item in references if item.get("angle") == "side"])
        real = self._profile_context(real_person=True)
        references = panel_context(real, {"desc": "沈砚回头"})["references"]
        self.assertFalse([item for item in references if item.get("angle") == "side"])

    def test_a_look_without_its_own_side_face_takes_the_one_cut_from_the_stage_three_sheet(self):
        from unittest.mock import patch
        from app.core import media_compositor
        from app.core.storyboard_scene_context import side_view
        # The side of a thing is not a face turned away.
        self.assertFalse(side_view("他走到丹炉侧面的进气口前蹲下"))
        task = {"assets": {"3_sheets": {}, "3_characters": [{
            "name": "沈砚", "desc": "墨青长袍",
            "views": [{"view": "face_three_quarter", "image_url": "/media/character_views/a/15_face_three_quarter.png"}],
        }, {"name": "贺兰霆", "desc": "玄黑官袍", "sheet_cells": [{"cell": "face_three_quarter", "image_url": "/media/gone.png"}]}]}}
        scene = {"scene_id": "E1S02", "characters": ["沈砚", "贺兰霆"], "content": "磨刀铺内。"}
        elements = [
            {"kind": "actor", "id": "a", "name": "沈砚", "description": "", "image_url": "data:body", "face_url": "data:face"},
            {"kind": "actor", "id": "b", "name": "贺兰霆", "description": "", "image_url": "data:body2", "face_url": "data:face2"},
        ]
        with patch.object(media_compositor, "local_media_path", lambda url: "/x" if "character_views" in url else None):
            context = compile_scene_context(task, scene, elements)
        references = panel_context(context, {"desc": "沈砚回头看向贺兰霆"})["references"]
        self.assertEqual([(item["name"], item["image_url"]) for item in references if item.get("angle") == "side"],
                         [("沈砚", "/media/character_views/a/15_face_three_quarter.png")])
        # A character wearing a look never borrows the sheet's side face (its hair is the base sheet's, not the look's):
        # a board drawn before the side-face panel sends none, a board with one sends its own.
        look = {"kind": "actor", "id": "look", "name": "沈砚·染血残衣", "description": "染血残衣", "image_url": "data:look", "face_url": "data:bust",
                "metadata": {"variant": {"of": "沈砚", "source": "costume", "label": "染血残衣"}}}
        for own_side, expected in (("", []), ("data:look-side", [("沈砚", "data:look-side")])):
            dressed_look = {**look, **({"side_face_url": own_side} if own_side else {})}
            with patch.object(media_compositor, "local_media_path", lambda url: "/x" if "character_views" in url else None):
                dressed = compile_scene_context(task, scene, [*elements, dressed_look])
            worn = next(actor for actor in dressed["actors"] if actor["name"] == "沈砚")
            self.assertEqual(worn.get("variant"), "染血残衣")
            references = panel_context(dressed, {"desc": "沈砚回头看向贺兰霆"})["references"]
            self.assertEqual([(item["name"], item["image_url"]) for item in references if item.get("angle") == "side"], expected)

    def test_the_still_prompt_names_the_side_face_for_what_it_is(self):
        from app.core.panel_still_prompt import _reference_line
        line = _reference_line([
            {"kind": "actor", "name": "沈砚", "image_url": "b"}, {"kind": "actor", "name": "沈砚", "image_url": "f", "view": "face"},
            {"kind": "actor", "name": "沈砚", "image_url": "s", "view": "face", "angle": "side"},
        ])
        self.assertIn("图2 「沈砚」正面大头照", line)
        self.assertIn("图3 「沈砚」侧脸照", line)

    def test_a_look_brings_its_own_bust_but_a_real_person_keeps_the_photo(self):
        from app.core import character_variants
        look = {"id": "look", "image_url": "look-body", "face_url": "look-bust", "variant": {"label": "残衣"}}
        self.assertEqual(character_variants.apply({"name": "断水", "image_url": "b", "face_url": "f"}, look)["face_url"], "look-bust")
        real = {"name": "沈砚", "image_url": "b", "face_url": "photo", "real_person": True}
        self.assertEqual(character_variants.apply(real, look)["face_url"], "photo")
        self.assertEqual(character_variants.apply({"name": "断水", "face_url": "f"}, {"id": "old", "image_url": "board"})["face_url"], "f")
        # The side face is the look's own or none: the character's own (another hairstyle) is not carried into the look.
        self.assertEqual(character_variants.apply({"name": "断水", "side_face_url": "sheet"}, look)["side_face_url"], "")
        self.assertEqual(character_variants.apply({"name": "断水", "side_face_url": "sheet"}, {**look, "side_face_url": "look-side"})["side_face_url"], "look-side")
        self.assertEqual(character_variants.apply({**real, "side_face_url": "x"}, {**look, "side_face_url": "look-side"})["side_face_url"], "")
        self.assertEqual(character_variants.apply({"name": "断水", "side_face_url": "sheet"}, None)["side_face_url"], "sheet")

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

# -*- coding: utf-8 -*-
"""剧本只叫称呼(侯府嫡女)、设定集有名有姓(陆婉)：参考图与视频准入都认设定集那个人。"""

import unittest

from app.core.storyboard_scene_context import (
    cast_aliases, compile_scene_context, costume_wearers, identity_sheets, is_uncast, panel_context,
)
from app.core.video_admission import assess_video_batch


def _project(**assets):
    return {"task_id": "cast-1", "config": {"video_model": "seedance2.0"}, "assets": {
        "3_characters": [
            {"name": "沈知微", "desc": "女主角"},
            {"name": "陆婉", "desc": "侯府嫡女／女配角（第 1 集被替命对象）；圆鹅蛋脸，下颌软"},
        ],
        "3_sheets": {"沈知微": "https://cdn/shen.png", "陆婉": "https://cdn/luwan.png"},
        **assets,
    }}


def _shot(shot_id, scene_id, characters):
    return {"shot_id": shot_id, "scene_id": scene_id, "desc": "帘缝里红缎绣花鞋尖与鹅黄披帛静止" * 2, "characters": characters, "duration": "5s"}


class CastAliasTests(unittest.TestCase):
    def test_the_title_at_the_head_of_a_sheet_names_that_actor(self):
        self.assertEqual(cast_aliases(_project()), {"侯府嫡女": "陆婉"})

    def test_billing_shared_titles_and_actor_names_are_never_aliases(self):
        task = _project()
        task["assets"]["3_characters"].append({"name": "陆夫人", "desc": "侯府嫡女／反派；冷面"})   # 两人共用的称呼
        task["assets"]["3_characters"].append({"name": "裴崇", "desc": "沈知微／反派"})          # 称呼正是别人的名字
        self.assertEqual(cast_aliases(task), {})

    def test_empty_shots_and_unnamed_extras_are_not_cast(self):
        for name in ("空镜（无人物）", "空镜", "无", "管事", "仆妇甲", "画外声音", "玄黑人影", "黑衣人", "阶下众人", "举火的人"):
            self.assertTrue(is_uncast(name), name)
        for name in ("李管事", "沈影", "裴仲玄"):
            self.assertFalse(is_uncast(name), name)


class AdmissionTests(unittest.TestCase):
    def test_a_title_an_empty_shot_and_an_extra_do_not_block_video(self):
        task = _project(**{"4": [
            _shot(1, "E1S03", ["沈知微", "侯府嫡女"]), _shot(1, "E1S08", ["空镜（无人物）"]), _shot(2, "E1S08", ["沈知微", "管事"]),
        ], "5": []})
        admission = assess_video_batch(task, provider_ready=lambda *_: True)
        self.assertNotEqual(admission.decision, "blocked", admission.summary())

    def test_an_unknown_person_is_still_blocked_and_named_with_the_scene(self):
        task = _project(**{"4": [_shot(1, "E1S03", ["神秘人"])], "5": []})
        admission = assess_video_batch(task, provider_ready=lambda *_: True)
        self.assertEqual(admission.decision, "blocked")
        self.assertIn("E1S03 镜头 1：出场角色尚无身份视图：神秘人", admission.summary())

    def test_a_clip_is_reused_only_by_the_shot_it_was_made_for(self):
        task = _project(**{"4": [_shot(1, "E1S01", ["沈知微"]), _shot(1, "E1S02", ["沈知微"])],
                           "5": [{"scene_id": "E1S01", "shot_id": 1, "shot_uids": [100101], "video_url": "https://cdn/c.mp4", "slice": {"beats": []}}]})
        admission = assess_video_batch(task, provider_ready=lambda *_: True)
        self.assertEqual([shot.quote for shot in admission.shots], ["reuse", "generate"])


class ReferenceTests(unittest.TestCase):
    def test_the_named_actor_stands_in_for_a_stale_library_entry_under_the_title(self):
        task = _project()
        elements = [
            {"kind": "actor", "name": "侯府嫡女", "description": "女配角", "image_url": "https://cdn/stale.png"},
            {"kind": "actor", "name": "陆婉", "description": "侯府嫡女／女配角", "image_url": "https://cdn/luwan-lib.png"},
            {"kind": "actor", "name": "沈知微", "description": "女主角", "image_url": "https://cdn/shen-lib.png"},
        ]
        scene = {"scene_id": "E1S03", "content": "侯府嫡女在珠帘后站着，沈知微跪在堂下。", "characters": ["沈知微", "侯府嫡女"]}
        context = compile_scene_context(task, scene, elements)
        self.assertEqual(context["characters"], ["沈知微", "陆婉"])
        refs = panel_context(context, _shot(3, "E1S03", ["侯府嫡女", "沈知微"]))["references"]
        actors = [(ref["name"], ref["image_url"]) for ref in refs if ref["kind"] == "actor"]
        self.assertEqual(sorted(actors), [("沈知微", "https://cdn/shen-lib.png"), ("陆婉", "https://cdn/luwan-lib.png")])

    def test_her_one_costume_named_with_the_title_still_dresses_her(self):
        elements = [
            {"kind": "costume", "name": "陆婉（侯府嫡女）·石榴红齐胸襦裙", "description": "第1集珠帘后露面", "image_url": "https://cdn/red.png"},
            {"kind": "costume", "name": "陆婉·素白囚衣", "description": "第6集", "image_url": "https://cdn/white.png"},
        ]
        context = compile_scene_context(_project(), {"scene_id": "E1S03", "content": "珠帘后鞋尖一闪。", "characters": ["侯府嫡女"]}, elements)
        self.assertEqual([item["name"] for item in context["costumes"]], ["陆婉（侯府嫡女）·石榴红齐胸襦裙"])

    def test_a_scene_that_only_uses_the_title_still_finds_the_actor(self):
        context = compile_scene_context(_project(), {"scene_id": "E1S03", "content": "侯府嫡女端着茶盘进来。"}, [])
        self.assertEqual(context["characters"], ["陆婉"])
        self.assertEqual(context["actors"][0]["image_url"], "https://cdn/luwan.png")


class IdentitySheetTests(unittest.TestCase):
    SHEETS = {"沈知微": "https://expired/shen.png", "陆昀": "https://expired/lu.png", "陆婉": "https://expired/luwan.png"}
    LEADS = [("沈知微", "https://expired/shen.png"), ("陆昀", "https://expired/lu.png")]

    def test_library_images_win_and_sheets_only_fill_gaps_in_this_shot(self):
        refs = [{"kind": "actor", "name": "沈知微", "image_url": "data:image/png;base64,AAA"}, {"kind": "scene", "name": "正堂", "image_url": "data:x"}]
        shot = {"characters": ["沈知微", "侯府嫡女"]}
        self.assertEqual(identity_sheets(self.SHEETS, self.LEADS, refs, shot, {"侯府嫡女": "陆婉"}), [("陆婉", "https://expired/luwan.png")])

    def test_an_empty_shot_gets_no_faces(self):
        refs = [{"kind": "scene", "name": "旧库", "image_url": "data:x"}]
        self.assertEqual(identity_sheets(self.SHEETS, self.LEADS, refs, {"characters": ["空镜（无人物）"]}, {}), [])

    def test_projects_without_a_library_keep_the_old_choice(self):
        self.assertEqual(identity_sheets(self.SHEETS, self.LEADS, [], {"characters": []}, {}), self.LEADS)


if __name__ == "__main__":
    unittest.main()


class CostumeWearerTests(unittest.TestCase):
    """服装参考图绑定到穿它的人：名字写在造型名或描述开头，称呼也算。"""

    def test_each_costume_goes_to_the_person_it_is_named_for(self):
        references = [
            {"kind": "costume", "name": "沈知微·素白中衣", "image_url": "https://cdn/c1.png"},
            {"kind": "costume", "name": "石榴红襦裙", "description": "侯府嫡女，喜服", "image_url": "https://cdn/c2.png"},
            {"kind": "costume", "name": "夜行衣", "description": "黑衣人统一制式", "image_url": "https://cdn/c3.png"},
            {"kind": "prop", "name": "沈知微·玉佩", "image_url": "https://cdn/p1.png"},
        ]
        wearers = costume_wearers(references, ["沈知微", "陆婉", "贺兰霆"], {"侯府嫡女": "陆婉"})
        self.assertEqual(wearers, [("沈知微", "沈知微·素白中衣"), ("陆婉", "石榴红襦裙")])

    def test_a_costume_of_someone_not_in_the_shot_is_not_bound(self):
        references = [{"kind": "costume", "name": "沈知微·素白中衣", "image_url": "https://cdn/c1.png"}]
        self.assertEqual(costume_wearers(references, ["陆婉"]), [])


# -*- coding: utf-8 -*-
"""武侠与修仙的特效写法：哪场戏用哪一套、分镜和视频提示词里特效写得出形状、颜色和光。"""

import unittest
from types import SimpleNamespace

from app.core import seedance_video_director as director
from app.core import style_packs, wuxia_vfx
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt
from tests.test_panel_still_prompt import _contract, _prompt

THUNDER = {"name": "九霄雷劫", "description": "紫金色雷柱垂直劈落，白芯外裹分叉电弧；落点焦黑龟裂。第3集渡劫"}


def _task(*effects):
    return {"assets": {"2_breakdown": {"production_assets": {"effects": list(effects)}}}}


class KindTests(unittest.TestCase):
    def test_the_genre_sets_the_tone_and_words_decide_without_one(self):
        self.assertEqual(wuxia_vfx.kind_of("他运起内力，一掌拍出，掌风扫落竹叶", "wuxia"), wuxia_vfx.WUXIA)
        self.assertEqual(wuxia_vfx.kind_of("两人剑气纵横", "xianxia"), wuxia_vfx.XIANXIA)
        self.assertEqual(wuxia_vfx.kind_of("天雷滚滚，她要渡劫", "wuxia"), wuxia_vfx.XIANXIA, "武侠剧里写到天劫，照修仙写")
        self.assertEqual(wuxia_vfx.kind_of("他御剑而起"), wuxia_vfx.XIANXIA)
        self.assertEqual(wuxia_vfx.kind_of("剑气划破竹林"), wuxia_vfx.WUXIA)

    def test_a_dialogue_scene_of_either_genre_gets_nothing(self):
        for genre in ("wuxia", "xianxia", ""):
            self.assertEqual(wuxia_vfx.kind_of("两人在亭中对坐饮茶，谈起旧事", genre), "", genre)
            self.assertEqual(wuxia_vfx.vfx_brief("两人在亭中对坐饮茶，谈起旧事", genre), "", genre)


class BriefTests(unittest.TestCase):
    @staticmethod
    def _headings(brief: str) -> list[str]:
        return [line for line in brief.splitlines() if line.startswith("## ")]

    def test_a_tribulation_gets_the_spectacle_rules_with_timing_and_light(self):
        brief = wuxia_vfx.vfx_brief("云层压低，第一道雷劫劈下，苏问剑祭出法宝硬扛", "xianxia")
        headings = "".join(self._headings(brief))
        for part in ("能量四态", "尺度四件套", "特效镜头", "非打斗奇观"):
            self.assertIn(part, headings)
        self.assertIn("蓄力 → 释放 → 作用 → 余波", brief)
        self.assertIn("渡劫雷劫", brief)
        self.assertNotIn("Seedance 2.5 写法", brief)
        self.assertLessEqual(len(brief), 5600)

    def test_an_alchemy_scene_gets_the_pill_thunder(self):
        brief = wuxia_vfx.vfx_brief("丹炉嗡鸣，丹雷落下，丹成出炉", "xianxia")
        self.assertIn("丹雷与出炉异象", brief)

    def test_a_xianxia_fight_gets_form_scale_and_shot_rules_but_not_the_spectacle_list(self):
        headings = "".join(self._headings(wuxia_vfx.vfx_brief("剑气纵横，两人斗法，光刃对撞", "xianxia", fight=True)))
        self.assertIn("特效镜头", headings)
        self.assertNotIn("非打斗奇观", headings)

    def test_an_effect_is_written_by_its_texture_and_the_one_it_hits_reacts(self):
        brief = wuxia_vfx.vfx_brief("剑气纵横，两人斗法，光刃对撞", "xianxia", fight=True)
        for texture in ("流体", "几何", "动能", "碎块"):
            self.assertIn(texture, brief)
        self.assertIn("受击的人另写一句", brief)
        self.assertLessEqual(len(brief), 5200 + 400, "the brief stays inside its budget")

    def test_a_wuxia_fight_shows_force_through_the_world_not_glow(self):
        brief = wuxia_vfx.vfx_brief("沈无咎一掌拍出，掌风震碎茶盏", "wuxia", fight=True)
        self.assertIn("内力外放", brief)
        self.assertIn("不画成发光的能量体", brief)
        self.assertNotIn("能量四态", brief)


class EffectLineTests(unittest.TestCase):
    def test_the_video_line_carries_what_the_effect_looks_like(self):
        lines = wuxia_vfx.effect_lines(["九霄雷劫", "本格无额外特效", "无相剑气", "无"], _task(THUNDER))
        self.assertEqual(lines[0], "九霄雷劫（紫金色雷柱垂直劈落，白芯外裹分叉电弧，落点焦黑龟裂，第3集渡劫；声音：炸雷的闷响和电弧噼啪声）")
        self.assertEqual(lines[1:], ["无相剑气（声音：尖锐的破空声）"], "名字以「无」开头的特效不是占位词")

    def test_an_effect_nobody_can_hear_is_just_named(self):
        self.assertEqual(wuxia_vfx.effect_lines(["定身术"], _task()), ["定身术"])

    def test_the_video_prompt_has_the_effects_section(self):
        shot = ShotPromptInput(
            shot_index=1, duration_seconds=6, shot_size="全景", camera_movement="缓推", subject_action="苏问剑仰头扛住雷劫",
            scene="剑冢", blocking="", start_state="", end_state="", effects=wuxia_vfx.effect_lines(["九霄雷劫"], _task(THUNDER)),
        )
        compiled = compile_shot_prompt(style_packs.FILM_35MM, shot, model="seedance2.5")
        self.assertIn("特效：九霄雷劫（紫金色雷柱垂直劈落", compiled.text)


class BindingTests(unittest.TestCase):
    EFFECTS = [{"kind": "effect", "name": "九霄雷劫", "image_url": "data:thunder"},
               {"kind": "effect", "name": "沈无咎紫电剑气"}, {"kind": "effect", "name": "裴仲玄赤焰剑气"}]

    def test_a_core_term_owned_by_one_effect_binds_it(self):
        bound = wuxia_vfx.bound_by_term(self.EFFECTS, "雷劫劈下，两人的剑气纵横交错")
        self.assertEqual([item["name"] for item in bound], ["九霄雷劫"], "两个特效都叫…剑气：谁也不认")

    def test_an_effect_already_named_is_not_bound_twice(self):
        self.assertEqual(wuxia_vfx.bound_by_term(self.EFFECTS, "九霄雷劫劈下", ["九霄雷劫"]), [])

    def test_the_panel_binds_it_and_puts_the_effect_ahead_of_old_costumes(self):
        from app.core.storyboard_scene_context import panel_context

        context = {
            "scene_id": "E3S01", "characters": ["苏问剑"], "all_character_names": ["苏问剑"], "actors": [], "scenes": [], "props": [], "products": [],
            "costumes": [{"kind": "costume", "name": "苏问剑·素白丧服", "description": "苏问剑穿着", "image_url": "data:robe"}],
            "effects": self.EFFECTS, "makeup": [],
        }
        panel = panel_context(context, {"characters": ["苏问剑"], "desc": "苏问剑仰头，雷劫劈下"})
        self.assertIn("九霄雷劫", panel["effects"])
        urls = [item["image_url"] for item in panel["references"]]
        self.assertLess(urls.index("data:thunder"), urls.index("data:robe"))


class EffectReferenceNoteTests(unittest.TestCase):
    def test_an_effect_picture_is_told_when_it_happens_and_survives_renumbering(self):
        from app.core.storyboard_scene_context import reference_note
        from app.core.video_references import _REFERENCE_NOTE

        note = reference_note(3, {"kind": "effect", "name": "九霄雷劫"})
        self.assertIn("先蓄力，再放出、作用，最后留下余波", note)
        self.assertNotIn("；", note)
        self.assertTrue(_REFERENCE_NOTE.search(note))
        self.assertNotIn("蓄力", reference_note(3, {"kind": "prop", "name": "玉牌"}))


class PanelTests(unittest.TestCase):
    def test_a_drawn_effect_keeps_its_description_and_lights_the_people(self):
        references = [{"kind": "actor", "name": "沈砚"}, {"kind": "effect", "name": "九霄雷劫"}]
        assets = [{"kind": "actor", "name": "沈砚", "description": "圆脸"}, {"kind": "effect", **THUNDER}]
        prompt = _prompt(_contract(effects=["九霄雷劫"]), references=references, assets=assets)
        self.assertIn("「九霄雷劫」特效按设定：紫金色雷柱垂直劈落", prompt)
        self.assertIn("特效光：「九霄雷劫」是这一格的临时光源", prompt)

    def test_no_effect_no_effect_light(self):
        self.assertNotIn("特效光", _prompt())
        self.assertNotIn("特效时刻", _prompt())

    def test_the_first_frame_holds_the_charge_and_the_last_the_aftermath(self):
        contract = _contract(effects=["九霄雷劫"])
        self.assertIn("特效时刻：特效此刻在蓄力", _prompt(contract))
        self.assertIn("特效时刻：特效此刻在余波", _prompt(contract, frame_state="end"))


class ReferenceImageTests(unittest.TestCase):
    def test_an_effect_reference_is_designed_by_form_layers_and_colour(self):
        from app.api.element_api import _element_reference_prompt

        xianxia = _element_reference_prompt(SimpleNamespace(kind="effect", name="九霄雷劫", description=THUNDER["description"]), "", "")
        self.assertIn("硬质能量体、写意层", xianxia)
        wuxia = _element_reference_prompt(SimpleNamespace(kind="effect", name="掌风", description="一掌推出，掌风吹灭烛火"), "", "")
        self.assertIn("不画成发光的能量体", wuxia)
        prop = _element_reference_prompt(SimpleNamespace(kind="scene", name="剑冢", description="夜"), "", "")
        self.assertNotIn("特效设计要求", prop)
        self.assertNotIn("术法外观", xianxia, "雷劫不是一门术法的名字")

    def test_a_named_technique_gets_its_shape_from_its_name(self):
        from app.api.element_api import _element_reference_prompt

        prompt = _element_reference_prompt(SimpleNamespace(kind="effect", name="大荒囚天指", description="一指点出"), "", "")
        self.assertIn("术法外观(按名字定形", prompt)
        self.assertIn("光束或指印", prompt)


class WriterAndColourTests(unittest.TestCase):
    TASK = {"assets": {
        "3_characters": [{"name": "沈无咎"}, {"name": "裴仲玄"}],
        "2_breakdown": {"production_assets": {"effects": [
            {"name": "沈无咎·紫电剑气", "description": "沈无咎剑上的紫色电弧"},
            {"name": "裴仲玄·赤焰刀气", "description": "赤红火焰沿刀身翻卷"},
            {"name": "九霄雷劫", "description": "紫金雷柱"},
        ]}},
    }}

    def test_each_fighter_keeps_one_effect_colour(self):
        line = wuxia_vfx.color_line(self.TASK, ["沈无咎", "裴仲玄"])
        self.assertIn("沈无咎的「沈无咎·紫电剑气」是紫色", line)
        self.assertIn("裴仲玄的「裴仲玄·赤焰刀气」是赤红色", line)
        self.assertNotIn("九霄雷劫", line, "不归谁的特效不算谁的主色")
        self.assertNotIn("裴仲玄", wuxia_vfx.color_line(self.TASK, ["沈无咎"]))

    def test_the_writer_gets_spectacle_rules_only_for_a_spectacle_episode(self):
        from tests.test_fight_design import _plan

        self.assertIn("奇观设计", _plan("第三日，苏问剑在剑冢渡劫，雷劫九道，一道比一道粗。"))
        self.assertNotIn("奇观设计", _plan("沈知微与陆昀在正堂对坐饮茶，说起旧事。"))
        fight = _plan("雨夜屋顶，沈知微拔剑，与陆昀交手三合，刀剑相接，她被击退半步又反击。")
        self.assertNotIn("奇观设计", fight, "打戏集走打戏规则")


class DirectorLayerTests(unittest.TestCase):
    def setUp(self):
        if not director.skill_installed():
            self.skipTest("seedance-2-5-video-director 未安装")

    def _sections(self, prompt: str) -> list[str]:
        director.reset_seedance_director_cache()
        return list(director.build_director_layer(video_model="doubao-seedance-2-5-260128", duration=8, prompt=prompt).sections)

    def test_a_tribulation_without_a_fight_still_gets_the_vfx_rules(self):
        sections = self._sections("乌云旋成漩涡，雷劫劈落，苏问剑盘坐硬扛，衣袍焦破")
        self.assertIn("xianxia/特效镜头", sections)
        self.assertIn("xianxia/非打斗奇观", sections)

    def test_a_tea_scene_gets_none(self):
        self.assertFalse(any(name.startswith("xianxia/") for name in self._sections("两人在亭中对坐饮茶，谈起旧事")))


if __name__ == "__main__":
    unittest.main()

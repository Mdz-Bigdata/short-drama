# -*- coding: utf-8 -*-
"""修仙道具：丹药、飞剑、符箓、法宝按类画，按品阶加光；寻常器物不加；尺寸有据；宗门场地有尺寸。"""

import unittest

from app.core import scene_scale, xianxia_props
from app.core.prop_turnaround import plan_prop
from app.core.production_knowledge import load_section
from app.service.screenwriting_service import writer_system_prompt


class LookTests(unittest.TestCase):
    def test_xianxia_items_get_their_look_and_grade(self):
        pill = xianxia_props.prop_rules("九转还魂丹", "八阶丹药，能护住元神")
        self.assertIn("丹纹", pill)
        self.assertIn("高阶丹", pill)
        self.assertIn("剑脊铭刻符纹", xianxia_props.prop_rules("青锋飞剑"))
        self.assertIn("朱砂符文", xianxia_props.prop_rules("雷符"))
        mirror = xianxia_props.prop_rules("照妖镜", "仙器，能照出原形")
        self.assertIn("铭刻符纹", mirror)
        self.assertIn("器灵成形", mirror)

    def test_beast_cores_herbs_eggs_and_sect_tokens(self):
        self.assertIn("妖丹是一枚浑圆晶珠", xianxia_props.prop_rules("三阶火狼妖丹"), "the longest ending wins over 丹")
        self.assertIn("丹纹", xianxia_props.prop_rules("九转还魂丹"))
        self.assertIn("柔光", xianxia_props.prop_rules("千年朱果"))
        self.assertIn("宗门图腾", xianxia_props.prop_rules("青云宗身份玉牌"))
        self.assertIn("宗门图腾", xianxia_props.prop_rules("掌门令牌", "宗门掌门信物"))
        self.assertEqual(xianxia_props.prop_rules("县衙令牌", "捕快所用"), "")
        self.assertEqual(plan_prop("三阶火狼妖丹").longest_cm, 3.5)
        self.assertEqual(plan_prop("千年朱果").longest_cm, 6.0)

    def test_beast_materials_and_inheritance_items(self):
        self.assertIn("暗红色", xianxia_props.prop_rules("金翅大鹏精血"))
        self.assertIn("金属般的光泽", xianxia_props.prop_rules("九阶蛟龙龙鳞"))
        self.assertIn("像有人在里面低语", xianxia_props.prop_rules("太古传承玉简"), "an inheritance slip beats a plain 玉简")
        self.assertIn("古篆", xianxia_props.prop_rules("荒古传承石碑"))
        self.assertEqual(xianxia_props.prop_rules("路边石碑"), "")
        self.assertIn("石台或蒲团", xianxia_props.place_rules("剑帝传承之地"))
        self.assertEqual(scene_scale.plan("后山碑林").kind, "悟道崖碑林")

    def test_ordinary_objects_stay_ordinary(self):
        self.assertEqual(xianxia_props.prop_rules("铜镜", "皇后梳妆用"), "")
        self.assertEqual(xianxia_props.prop_rules("长剑", "江湖剑客的佩剑"), "")
        self.assertEqual(xianxia_props.prop_rules("一枝牡丹"), "")


class PlaceTests(unittest.TestCase):
    def test_xianxia_places_get_their_look_and_shared_names_need_a_cultivation_word(self):
        self.assertIn("灵泉", xianxia_props.place_rules("太上长老洞府"))
        self.assertIn("漂浮着山石", xianxia_props.place_rules("上古秘境"))
        self.assertIn("石牌坊", xianxia_props.place_rules("青云宗山门"))
        self.assertIn("禁制光幕", xianxia_props.place_rules("宗门藏经阁"))
        self.assertEqual(xianxia_props.place_rules("少林寺山门", "江湖"), "")
        self.assertEqual(xianxia_props.place_rules("皇宫藏书阁", "后宫"), "")
        self.assertEqual(xianxia_props.place_rules("客栈暗室"), "")
        self.assertIn("禁止斗法的石碑", xianxia_props.place_rules("天南坊市"))
        self.assertIn("雷击裂纹", xianxia_props.place_rules("渡劫台"))
        self.assertEqual(xianxia_props.place_rules("万宝拍卖场"), "", "an auction hall needs a cultivation word")
        self.assertEqual(scene_scale.plan("十万妖兽山脉").kind, "妖兽山脉")
        for place in ("太上长老洞府", "上古秘境", "宗门藏经阁"):
            self.assertNotRegex(xianxia_props.place_rules(place), "人物|弟子|修士", "a location plate stays empty")


class SizeTests(unittest.TestCase):
    def test_xianxia_items_have_real_sizes(self):
        self.assertEqual((plan_prop("青锋飞剑").longest_cm, plan_prop("青锋飞剑").size_source), (100.0, "table"))
        self.assertEqual(plan_prop("紫金丹炉").longest_cm, 120.0)
        self.assertEqual(plan_prop("储物戒").longest_cm, 2.2)
        self.assertEqual(plan_prop("九转还魂丹").longest_cm, 1.5, "a pill is a pill, not a 30 cm object")
        self.assertEqual(plan_prop("一枝牡丹").longest_cm, 15.0)

    def test_sect_locations_have_sizes(self):
        self.assertEqual(scene_scale.plan("青云宗山门").kind, "宗门山门")
        self.assertEqual(scene_scale.plan("太上长老洞府").kind, "洞府")
        self.assertEqual(scene_scale.plan("外门演武场").kind, "演武场")
        self.assertEqual(scene_scale.plan("客栈暗室").kind, "暗室牢房", "older types still match")
        self.assertEqual(scene_scale.plan("上古秘境").kind, "秘境")
        self.assertEqual(scene_scale.plan("万剑剑冢").kind, "剑冢")


class CatalogTests(unittest.TestCase):
    def test_the_catalog_reaches_the_writer_for_cultivation_stories_only(self):
        catalog = load_section("xianxia-catalog", budget=0)
        for heading in ("功法谱", "丹药谱", "宗门", "法宝、兵器与道具", "秘境", "符箓", "阵法", "传承"):
            self.assertIn(heading, catalog)
        cultivation = writer_system_prompt("编剧", config={"title_suggestion": "废材修仙：我在宗门签到万年"}, stage="write")
        self.assertIn("修仙设定谱", cultivation)
        self.assertNotIn("修仙设定谱", writer_system_prompt("编剧", config={"title_suggestion": "霸总的契约甜妻"}, stage="write"))
        self.assertNotIn("修仙设定谱", writer_system_prompt("编剧", config={"title_suggestion": "废材修仙"}, stage="visual"))

    def test_the_world_page_is_for_cultivation_stories_not_wuxia(self):
        world = load_section("xianxia-world", budget=0)
        for heading in ("妖兽与灵兽", "妖兽材料", "吸收精血", "称谓与礼数", "宗门服饰按身份", "坊市、拍卖与灵石"):
            self.assertIn(heading, world)
        self.assertIn("人情物理", writer_system_prompt("编剧", config={"title_suggestion": "废材修仙：我在宗门签到万年"}, stage="write"))
        self.assertNotIn("人情物理", writer_system_prompt("编剧", config={"title_suggestion": "江湖夜雨十年灯 武侠"}, stage="write"))


if __name__ == "__main__":
    unittest.main()

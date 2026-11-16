# -*- coding: utf-8 -*-
"""短剧常见道具的尺寸补充表(app/data/props/everyday_items.json)：真实项目里的道具名都查得到，单字表名只认结尾，同名以参照表为准。"""

import json
import unittest

from app.core import prop_scale
from app.core.prop_turnaround import _FAMILIES, plan_prop

SUPPLEMENT = prop_scale.TABLE.with_name("everyday_items.json")


class EverydayTableTests(unittest.TestCase):
    def test_the_props_of_real_projects_are_found(self):
        # 本地五个项目第 2 阶段拆出来的道具名，补表之前一个都查不到。「未开刃的刀」「拭剑布」结尾是单字的刀、布，
        # 不收进表，按物件类别估(见下一条)。
        found = {
            "七缺口钝刀": "钝刀", "凹坑磨石": "磨石", "粗陶油灯": "油灯", "马蹄金与钱袋": "钱袋",
            "铜镖铃": "镖铃", "腰间三块磨刀石": "磨刀石", "九剑名册": "名册", "九剑盟主佩剑": "佩剑",
            "玉扳指": "扳指", "半块铜牌": "铜牌", "断手木砧与刑刀": "刑刀", "旧铜钥匙串": "钥匙串", "演武场旗杆": "旗杆",
            "钉石长剑": "长剑", "长布包": "长布包", "半截断剑尖": "剑尖", "木供桌": "供桌", "马车": "马车", "茶杯": "茶杯",
            "铁链": "铁链", "黑色轿车": "轿车",
        }
        for name, entry in found.items():
            with self.subTest(name):
                self.assertEqual(prop_scale.lookup(name).name, entry)

    def test_a_one_character_thing_is_left_to_the_estimate(self):
        """单字的器物名不收：「秘书」不是书，「拭剑布」不是剑；这些按物件类别估最长边。"""
        self.assertIsNone(prop_scale.lookup("秘书"))
        self.assertIsNone(prop_scale.lookup("拭剑布"))
        self.assertIsNone(prop_scale.lookup("保镖"))
        self.assertEqual(plan_prop("拭剑布").size_source, "estimate")
        self.assertEqual(prop_scale.lookup("剪刀").name, "剪刀", "scissors are not an 80 cm sabre")
        self.assertEqual(prop_scale.lookup("牛").name, "牛", "a one-character animal counts as the whole name")
        self.assertIsNone(prop_scale.lookup("蜗牛"))

    def test_the_official_table_wins_a_shared_name(self):
        official = {entry["name"] for entry in json.loads(prop_scale.TABLE.read_text(encoding="utf-8"))["entries"]}
        supplement = json.loads(SUPPLEMENT.read_text(encoding="utf-8"))
        for entry in supplement["entries"]:
            if entry["name"] in official:
                self.assertEqual(prop_scale.lookup(entry["name"]).dims_cm, tuple(
                    next(item for item in json.loads(prop_scale.TABLE.read_text(encoding="utf-8"))["entries"] if item["name"] == entry["name"])["dims_cm"]
                ))

    def test_every_entry_is_well_formed(self):
        data = json.loads(SUPPLEMENT.read_text(encoding="utf-8"))
        names = [entry["name"] for entry in data["entries"]]
        self.assertEqual(len(names), len(set(names)))
        for entry in data["entries"]:
            with self.subTest(entry["name"]):
                self.assertIn(entry["category"], data["category_family"])
                self.assertTrue(entry["dims_cm"] and all(value > 0 for value in entry["dims_cm"]))
        for family in data["category_family"].values():
            self.assertTrue(family == "default" or family in _FAMILIES, family)

    def test_the_prop_sheet_is_drawn_at_the_table_size(self):
        plan = plan_prop("粗陶油灯", "豆大的灯火")
        self.assertEqual((plan.size_source, plan.longest_cm), ("table", 12.0))
        self.assertIn("长12", plan.size_text)


if __name__ == "__main__":
    unittest.main()

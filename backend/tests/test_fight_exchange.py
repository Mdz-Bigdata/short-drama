# -*- coding: utf-8 -*-
"""打戏招招写实、按回合打：谁出手、从哪发力、怎么走、打在谁身上哪里、结果与力；多人不站着不排队；回合只进不退。"""

import unittest

from app.core import fight_design, fight_exchange
from app.core.shot_table_rules import audit_shot_table

FULL = ("U1（0.8–2.4秒）甲右脚蹬地拧腰，右手长剑自右上向左下斜劈，砍向乙的左肩；乙横刀上架，刀剑相撞火星四溅，乙被震得退半步。"
        "U2（2.4–3.6秒）乙借势转腰，刀锋贴地横扫甲的脚踝；甲跃起闪过，落地踉跄。")
THREE = ("U1（0.8–2.6秒）甲与乙同时出手，甲右拳直击丙的胸口，乙左脚踹向丙的膝窝；丙双臂格开两拳，被震得滑退撞上木桌。"
         "U2（2.6–4秒）丙借势旋身，右肘横扫甲的下颌；甲偏头躲过，乙从背后抡棍砸向丙的后背，丙闷哼跪地。")


class BriefTest(unittest.TestCase):
    def test_the_writer_is_told_the_five_things_and_the_rounds(self):
        two = fight_exchange.brief(2)
        for words in ("谁出手", "从哪发力起手", "怎么走", "打在谁身上哪里", "结果与力", "试探 → 交锋 → 升级 → 反转 → 决胜"):
            self.assertIn(words, two)
        self.assertNotIn("多人（本场", two)
        self.assertIn("多人（本场 4 人）", fight_exchange.brief(4))

    def test_the_scriptwriter_plans_rounds_too(self):
        self.assertIn(fight_exchange.writer_rule(), fight_design.plan_rules_for("两人拔剑对打，刀光剑影"))
        self.assertEqual(fight_design.plan_rules_for("两人在茶馆喝茶"), "")


class ShotTest(unittest.TestCase):
    def test_a_fully_written_exchange_passes(self):
        self.assertEqual(fight_exchange.audit_shot(FULL, ["甲", "乙"]), [])
        self.assertEqual(fight_exchange.audit_shot(THREE, ["甲", "乙", "丙"]), [])

    def test_a_vague_unit_is_named_with_what_it_lacks(self):
        issues = fight_exchange.audit_shot("U1（0–2秒）甲出招。U2（2–4秒）乙右脚蹬地，刀锋横扫甲的脚踝，甲踉跄。", ["甲", "乙"])
        rules = {issue.rule: issue.detail for issue in issues}
        self.assertIn("招式没写清", rules)
        self.assertTrue(rules["招式没写清"].startswith("U1 缺："))
        self.assertIn("招式没有落点", rules)
        self.assertIn("U1", rules["招式没有落点"])

    def test_force_is_written_from_the_feet_up(self):
        backwards = "U1（0–2秒）甲一拳砸向乙的胸口，右脚蹬地拧腰；乙胸口一凹，踉跄后退。"
        rules = [issue.rule for issue in fight_exchange.audit_shot(backwards, ["甲", "乙"])]
        self.assertEqual(rules, ["发力链倒序"])
        # 挨打的一方在分号之后蹬地后撤，不算出手的人倒序。
        self.assertEqual(fight_exchange.audit_shot(FULL, ["甲", "乙"]), [])

    def test_the_brief_asks_for_the_struck_side_the_cut_and_the_ground(self):
        text = fight_exchange.brief(2)
        for words in ("句子的顺序就是力的顺序", "形变", "偏移", "离地", "镜头切点", "脚下有东西", "伤会变"):
            self.assertIn(words, text)

    def test_nobody_stands_and_watches_and_nobody_queues(self):
        issues = fight_exchange.audit_shot(FULL, ["甲", "乙", "丙"])
        rules = {issue.rule: issue.detail for issue in issues}
        self.assertIn("丙", rules["多人打戏有人站着"])
        self.assertIn("围攻排队", rules)

    def test_a_shot_without_units_is_left_to_the_unit_count_check(self):
        self.assertEqual(fight_exchange.audit_shot("两人打成一团", ["甲", "乙"]), [])


class ClipCheckTest(unittest.TestCase):
    def test_the_finished_clip_is_judged_on_the_same_rules(self):
        from app.core import prompt_data

        prompt = prompt_data.text("fight_scene", "clip_check_prompt")
        for words in ("全身发力", "木偶互推", "整段站着看", "排着队", "落点", "左右位置前后对得上", "脱手或折断的兵器"):
            self.assertIn(words, prompt)
        self.assertIn("在场的人都在打", prompt_data.text("fight_scene", "clip_fix_lead"))


class RoundTest(unittest.TestCase):
    def test_round_labels_read_numbers_either_way(self):
        self.assertEqual(fight_exchange.round_of("【第三回合·反转】U1…"), (3, "反转"))
        self.assertEqual(fight_exchange.round_of("【第12回合 决胜】"), (12, "决胜"))
        self.assertEqual(fight_exchange.round_of("【第十一回合·升级】")[0], 11)
        self.assertIsNone(fight_exchange.round_of("U1（0–2秒）"))

    def test_a_fight_in_escalating_rounds_with_a_finish_passes(self):
        shots = [(1, "【第1回合·试探】x"), (2, "【第2回合·升级】x"), (3, "【第3回合·决胜】x")]
        self.assertEqual(fight_exchange.audit_rounds(shots), [])

    def test_round_problems_are_reported(self):
        rules = [issue.rule for _, issue in fight_exchange.audit_rounds([(1, "【第1回合·交锋】x"), (2, "x"), (3, "【第2回合·试探】x")])]
        self.assertEqual(sorted(rules), sorted(["打戏没标回合", "回合倒退", "打戏没有决胜"]))
        one = fight_exchange.audit_rounds([(1, "【第1回合·交锋】x"), (2, "【第1回合·交锋】x")])
        self.assertIn("打戏只有一个回合", [issue.rule for _, issue in one])


class TableTest(unittest.TestCase):
    def test_the_revision_round_reads_one_line_per_problem(self):
        shots = [
            {"shot_id": 1, "desc": "【第1回合·试探】" + FULL, "characters": "甲、乙"},
            {"shot_id": 2, "desc": "【第2回合·决胜】U1（0–2秒）甲出招。", "characters": ["甲", "乙"]},
            {"shot_id": 3, "desc": "沈砚独自饮茶", "characters": "沈砚"},
        ]
        lines = fight_exchange.table_issues(shots)
        self.assertTrue(lines)
        self.assertTrue(all(line.startswith("镜2 ") for line in lines), lines)

    def test_the_shot_table_audit_reports_them_for_a_fight_scene(self):
        shots = [{"shot_id": 1, "desc": "【第1回合·试探】U1（0–2秒）甲出招。", "size": "中景", "duration": "4秒", "characters": "甲、乙"}]
        audit = audit_shot_table(shots, scene_kind="fight", repair=False)
        self.assertIn("招式没写清", [issue.rule for issue in audit.issues])


if __name__ == "__main__":
    unittest.main()

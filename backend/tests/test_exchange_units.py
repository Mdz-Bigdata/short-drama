import inspect
import unittest
from unittest.mock import patch

from app.core import exchange_units as eu
from app.core.shot_table_rules import audit_shot_table


MASTERS = {"甲": "武林高手，一流剑客", "乙": "江湖大侠"}
ELDERS = {"爷爷": "白发苍苍的老人", "奶奶": "年迈的老太太"}


def _fight(text="两人在擂台上散打，鞭腿与直拳交换", profiles=None):
    return eu.scene_plan(text, profiles=profiles if profiles is not None else MASTERS, fight=True)


class TablesTests(unittest.TestCase):
    def test_the_skill_tables_load_with_the_spec_multipliers(self):
        data = eu.tables()

        self.assertIsNotNone(data)
        self.assertEqual(sorted(data.styles), sorted(f"MS{n}" for n in range(1, 11)))
        self.assertEqual(sorted(data.powers), [f"IP{n}" for n in range(1, 8)])
        self.assertEqual(sorted(data.dialogue), [f"DT{n}" for n in range(1, 7)])
        self.assertEqual(
            data.multipliers, {"IP7": 0.85, "IP6": 1.0, "IP5": 1.1, "IP4": 1.35, "IP3": 1.5, "IP2": 2.0},
        )
        self.assertEqual((data.crowd, data.min_half), (1.2, 0.6))
        self.assertEqual(data.styles["MS1"].half, 0.75)
        self.assertEqual(data.styles["MS6"].pause, 0.0, "tai chi flows on without breaks")

    def test_without_the_skill_nothing_is_planned_or_checked(self):
        eu.tables.cache_clear()
        try:
            with patch.object(eu.knowledge_registry, "section", return_value=None):
                self.assertIsNone(eu.scene_plan("两人散打", fight=True))
                self.assertEqual(eu.audit_shot(None, seconds=9, characters=["甲"], dialogue="", desc="", fight_shot=True), [])
        finally:
            eu.tables.cache_clear()


class JudgingTests(unittest.TestCase):
    def test_power_goes_health_then_skill_then_age(self):
        self.assertEqual(eu.judge_power("病入膏肓的掌门"), "IP1")
        self.assertEqual(eu.judge_power("年迈的掌门，武林高手"), "IP6", "skill beats age")
        self.assertEqual(eu.judge_power("白发苍苍的老人"), "IP2")
        self.assertEqual(eu.judge_power("十岁的小男孩"), "IP4")
        self.assertEqual(eu.judge_power("一代宗师"), "IP7")
        self.assertEqual(eu.judge_power("公司职员"), "", "no clue is left to the caller")

    def test_states_drop_a_fighter_but_drunken_fist_is_a_skill(self):
        self.assertEqual(eu.judge_power("负伤的大侠"), "IP5")
        self.assertEqual(eu.judge_power("醉拳高手"), "IP6")

    def test_style_is_read_from_its_words_and_a_brow_is_not_a_sword(self):
        self.assertEqual(eu.judge_style("截拳道寸拳快打"), "MS1")
        self.assertEqual(eu.judge_style("太极推手，四两拨千斤"), "MS6")
        self.assertEqual(eu.judge_style("剑眉星目的拳手在擂台上散打"), "MS3")
        self.assertEqual(eu.judge_style("两人扭打在一起"), "")

    def test_dialogue_tempo_is_read_from_its_words(self):
        self.assertEqual(eu.judge_dialogue("夫妻吵架，她拍桌怒斥"), "DT1")
        self.assertEqual(eu.judge_dialogue("临终遗言"), "DT5")
        self.assertEqual(eu.judge_dialogue("两人站着"), "")


class FightTempoTests(unittest.TestCase):
    """出品人：两个老人 9 秒两个单元合理，两个武林高手 9 秒只两个就太慢。"""

    def test_two_masters_trade_at_least_four_units_in_nine_seconds(self):
        plan = _fight()

        self.assertEqual(plan.fight.style, "MS3")
        self.assertEqual(plan.fight.half, 1.5)
        self.assertGreaterEqual(plan.fight.halves_for(9) - 1, 4)

    def test_frail_elders_move_far_slower_than_masters(self):
        elders = _fight("太极推手", ELDERS).fight
        masters = _fight("太极推手").fight

        self.assertEqual(elders.style, "MS6")
        self.assertEqual(elders.half, 5.0)
        self.assertLess(elders.halves_for(9), masters.halves_for(9))

    def test_jeet_kune_do_masters_trade_about_twelve_half_units_in_twelve_seconds(self):
        plan = _fight("截拳道过招", {"甲": "顶尖高手", "乙": "顶尖高手"})

        self.assertEqual(plan.fight.style, "MS1")
        self.assertGreaterEqual(plan.fight.halves_for(12), 12)

    def test_tiers_far_apart_go_by_the_stronger_and_close_ones_average(self):
        one_sided = _fight(profiles={"大侠": "江湖大侠", "醉汉": "醉醺醺的醉汉"}).fight
        close = _fight(profiles={"甲": "武林高手", "乙": "习武的镖师"}).fight

        self.assertIn("一边倒", one_sided.rule)
        self.assertEqual(one_sided.multiplier, 1.0)
        self.assertEqual(close.rule, "对抗取平均")
        self.assertEqual(close.multiplier, 1.05)

    def test_three_fighters_slow_down_and_the_gravely_ill_stay_out(self):
        crowd = _fight(profiles={"甲": "高手", "乙": "高手", "丙": "高手"}).fight
        plan = _fight(profiles={"甲": "高手", "老人": "病入膏肓"})

        self.assertTrue(crowd.crowd)
        self.assertAlmostEqual(crowd.half, 1.8)
        self.assertEqual(plan.fight.multiplier, 1.0, "the IP1 person does not set the pace")
        self.assertTrue(any("不进武打交锋" in note for note in plan.notes))

    def test_an_unnamed_style_falls_back_to_sanda_and_says_so(self):
        brief = _fight("两人扭打在一起").brief()

        self.assertIn("剧本没写流派，按散打", brief)
        self.assertIn("一个半单元约 1.5 秒", brief)
        self.assertIn("U1＝起手＋对方第一次接化发", brief)
        self.assertIn("9 秒只过两招就是太慢", brief)


class DialogueTests(unittest.TestCase):
    def test_a_quarrel_brief_sets_turn_length_budget_and_the_exchange_floor(self):
        plan = eu.scene_plan("妻：你到底瞒了我多久？\n夫：我瞒你什么了！", profiles={"妻": "", "夫": ""})
        brief = plan.brief()

        self.assertEqual(plan.dialogue.code, "DT3", "no quarrel word: everyday talk")
        self.assertIn("一格至少两个话轮", brief)
        self.assertIn("同一时刻只有一人开口", brief)
        self.assertIn("不空叹", brief)
        self.assertIn("起承转合", brief)

    def test_a_scene_without_lines_gets_no_dialogue_block(self):
        plan = eu.scene_plan("爷爷牵着孙子慢慢走过石桥", profiles={"爷爷": "白发苍苍的老人", "孙子": "五岁的小孩"})

        self.assertIsNone(plan.dialogue)
        self.assertEqual(plan.calm_unit, 5.0, "outside a fight the slower person sets the pace")
        self.assertIn("约 5 秒", plan.brief())

    def test_turns_merge_one_speakers_lines_and_ignore_a_quoted_colon(self):
        turns = eu.split_turns("林夏：你说啊。林夏：说话！ 周教授：他说：走。", ["林夏", "周教授"])

        self.assertEqual([turn.speaker for turn in turns], ["林夏", "周教授"])
        self.assertEqual(turns[0].text, "你说啊。说话！")
        self.assertEqual(turns[0].chars, 5, "punctuation is not spoken")


class ShotAuditTests(unittest.TestCase):
    def rules(self, plan, **shot):
        values = {"seconds": 10, "characters": ["甲", "乙"], "dialogue": "", "desc": "", "fight_shot": False}
        values.update(shot)
        return [issue.rule for issue in eu.audit_shot(plan, **values)]

    def test_a_fight_shot_must_be_written_in_units_and_not_too_few(self):
        plan = _fight()

        self.assertIn("打斗未按单元环扣写", self.rules(plan, seconds=9, desc="甲出拳，乙格挡", fight_shot=True))
        self.assertIn("打斗单元过少", self.rules(plan, seconds=12, desc="U1（0.8–3.8秒）甲出拳；乙格挡", fight_shot=True))
        dense = "；".join(f"U{n}" for n in range(1, 17))
        self.assertIn("打斗单元过密", self.rules(plan, seconds=12, desc=dense, fight_shot=True))
        enough = "U1（0.8–3.8秒）… U2 … U3–U4 … U5 …"
        self.assertEqual(eu.count_units(enough), 5)
        self.assertEqual(self.rules(plan, seconds=9, desc=enough, fight_shot=True), [])

    def test_a_line_inside_a_fight_is_short(self):
        rules = self.rules(_fight(), seconds=9, desc="U1 U2 U3 U4", fight_shot=True, dialogue="甲：你今天休想从这里活着走出去！")

        self.assertIn("打斗台词过长", rules)

    def test_half_an_exchange_three_in_a_row_long_turns_and_empty_tails(self):
        plan = eu.scene_plan("甲：你好。", profiles={"甲": "", "乙": ""})

        self.assertIn("对话少于一个来回", self.rules(plan, dialogue="甲：你今天回来得真早。"))
        self.assertIn("一人连说三句", self.rules(plan, dialogue="甲：一。甲：二。甲：三。乙：嗯。"))
        self.assertIn("话轮台词超字数", self.rules(plan, dialogue="甲：" + "我" * 40 + "。乙：好。"))
        self.assertIn("格尾空叹", self.rules(
            plan, seconds=12, desc="说完两人对视，叹气", dialogue="甲：你来了。乙：嗯，来了。",
        ))
        self.assertEqual(self.rules(
            plan, seconds=9, dialogue="甲：那封信你到底看过没有？乙：看过了，就在昨晚，我一个字都没漏。",
        ), [])

    def test_the_table_audit_runs_the_unit_checks(self):
        shot = {
            "shot_id": 1, "size": "中景", "duration": "10s", "characters": ["林夏", "周教授"],
            "desc": "林夏站在画面左侧三分之一的中景，朝向画面右侧，指节扣紧信封，肩背绷直，眼神压着火。",
            "dialogue": "林夏：那封信到底是谁写的？",
        }

        audit = audit_shot_table([shot, {**shot, "shot_id": 2, "size": "全景"}], video_model="seedance2.5")

        self.assertIn("对话少于一个来回", {issue.rule for issue in audit.issues})


class StageFourWiringTests(unittest.TestCase):
    def test_the_scene_board_briefs_the_writer_and_audits_with_the_same_plan(self):
        from app.service.drama_service import DramaService

        source = inspect.getsource(DramaService._generate_scene_board)

        self.assertIn("exchange_units.scene_plan(", source)
        self.assertIn("exchange.brief()", source)
        self.assertIn("exchange=exchange", source)

    def test_stage_five_hands_a_fight_shot_the_previous_landing_unless_it_shares_a_video(self):
        from app.service.drama_service import DramaService

        source = inspect.getsource(DramaService._execute_stage_blocking)

        self.assertIn('prompt_data.text("clip_prompt", "fight_carry").format(landing=', source)
        self.assertIn("in fight_scenes and episode_cycle.shot_uid(shot) not in sliced_uids", source)
        self.assertIn("carry_in=fight_carry", source)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""打戏补充：兵器谱、过审改写(力道不减)、伤势与兵器跨镜承接。"""

import unittest

from app.core import fight_safety, fight_state, weapon_moves
from app.core.model_gateway import ModelGateway
from tests.test_clip_route_stage5 import SENSITIVE, ClipRouteStageFiveTests
from tests.test_stage_five_queue import _task

FIGHT = "沈无咎挥拳重击，裴仲玄被震飞撞碎木桌，骨裂声响起；沈无咎一脚踹在他胸口，撕开他的衣襟，扫腿将他放倒"


class WeaponMovesTests(unittest.TestCase):
    def test_only_the_weapons_in_the_scene_are_sent(self):
        brief = weapon_moves.weapon_brief("沈无咎拔剑，裴仲玄挥刀劈下")
        self.assertIn("- 剑：", brief)
        self.assertIn("- 刀：", brief)
        self.assertNotIn("- 枪：", brief)
        self.assertIn("格挡", brief)

    def test_a_place_named_after_a_sword_is_not_a_sword(self):
        self.assertEqual(weapon_moves.weapons_in("剑冢里，两人对坐不语"), [])
        self.assertEqual(weapon_moves.weapon_brief("剑冢里，两人对坐不语"), "")

    def test_the_brief_stays_inside_its_budget(self):
        everything = "长剑 长刀 长枪 长棍 长鞭 折扇 匕首 战斧 飞刀 弯弓 挥拳 飞剑 金钟 法印 紫金葫芦 魂幡 符箓 捆仙索"
        self.assertEqual(len(weapon_moves.weapons_in(everything)), 18)
        brief = weapon_moves.weapon_brief(everything)
        self.assertLessEqual(len(brief), 1900)
        self.assertNotIn("…", brief, "装不下的兵器整条不发，不截半句")

    def test_treasures_fight_their_own_way(self):
        brief = weapon_moves.weapon_brief("他并指一引，祭出飞剑；对手抛出金钟罩下，又掷出雷符")
        for name in ("- 飞剑：", "- 钟罩鼎：", "- 符箓："):
            self.assertIn(name, brief)
        self.assertEqual(weapon_moves.weapons_in("醉汉解下腰间的酒葫芦"), [], "酒葫芦不是收人的葫芦")


class FightSafetyTests(unittest.TestCase):
    def test_a_fight_with_no_blocked_words_is_left_alone(self):
        self.assertEqual(fight_safety.clean_gore(FIGHT), FIGHT)
        self.assertEqual(fight_safety.soften(FIGHT), FIGHT)

    def test_force_words_survive_both_tables(self):
        for word in fight_safety.force_words():
            self.assertIn(word, fight_safety.soften(f"他{word}了一下，嘴角渗血"), word)

    def test_gore_is_rewritten_up_front_and_blood_only_on_the_retry(self):
        text = "一刀斩首，鲜血喷涌，他嘴角渗血"
        upfront = fight_safety.clean_gore(text)
        self.assertNotIn("斩首", upfront)
        self.assertNotIn("鲜血喷涌", upfront)
        self.assertIn("渗血", upfront, "血字只在被拦之后才换")
        self.assertNotIn("血", fight_safety.soften(text))

    def test_the_agnes_cleaner_keeps_punches_and_tearing(self):
        cleaned = ModelGateway._sanitize_prompt_for_agnes(FIGHT + "，眼中杀意，嘴角渗血，死死盯着；折扇一合")
        for word in ("挥拳", "踹", "撕开", "折扇", "震飞"):
            self.assertIn(word, cleaned)
        for word in ("杀", "血", "死"):
            self.assertNotIn(word, cleaned)
        self.assertIn("紧紧盯着", cleaned)


def _shot(shot_id, desc, people=("沈无咎", "裴仲玄"), scene="E1S02"):
    return {"shot_id": shot_id, "scene_id": scene, "desc": desc, "motion_contract": {"characters": list(people)}}


class FightStateTests(unittest.TestCase):
    def test_wounds_and_broken_weapons_carry_to_later_shots_of_the_scene(self):
        carried = fight_state.scene_carry([
            _shot(1, "裴仲玄一刀劈下，沈无咎左臂被划开一道口子"),
            _shot(2, "两刃相交，沈无咎的长剑断成两截，裴仲玄的刀被挑飞"),
            _shot(3, "裴仲玄捡起长刀，再次扑上"),
            _shot(4, "两人对峙"),
            _shot(5, "苏问剑独坐", people=("苏问剑",), scene="E1S03"),
        ])
        self.assertNotIn("E1S02:1", carried)
        self.assertIn("沈无咎：左臂被划开一道口子", carried["E1S02:2"])
        self.assertIn("裴仲玄：刀被挑飞", carried["E1S02:3"])
        # 捡回刀之后「被挑飞」不再带；断掉的剑照样是断的。
        self.assertNotIn("挑飞", carried["E1S02:4"])
        self.assertIn("长剑断成两截", carried["E1S02:4"])
        self.assertNotIn("E1S03:5", carried, "换场清零")

    def test_a_wrecked_set_stays_wrecked(self):
        carried = fight_state.scene_carry([
            _shot(1, "雷柱砸落，地面龟裂"),
            _shot(2, "沈无咎一掌把石桌劈成两半"),
            _shot(3, "两人对峙"),
        ])
        self.assertIn("场景：地面龟裂", carried["E1S02:2"])
        self.assertIn("沈无咎一掌把石桌劈成两半", carried["E1S02:3"])
        self.assertNotIn("沈无咎：", carried["E1S02:3"], "打坏的东西记在场景名下，不记在人身上")

    def test_a_breakthrough_follows_the_person_into_later_scenes_until_it_fades(self):
        def solo(shot_id, desc, scene):
            return _shot(shot_id, desc, people=("苏问剑",), scene=scene)

        carried = fight_state.scene_carry([
            solo(1, "雷劫散去，苏问剑突破至元婴，周身泛起淡金光", "E3S01"),
            solo(2, "苏问剑走出剑冢", "E3S02"),
            solo(3, "苏问剑周身金光褪去", "E4S01"),
            solo(4, "苏问剑坐下", "E4S01"),
        ])
        self.assertIn("苏问剑：突破至元婴，周身泛起淡金光(此后一直如此)", carried["E3S02:2"])
        self.assertIn("不出现半变半不变的中间态", carried["E3S02:2"])
        self.assertIn("E4S01:3", carried)
        # 褪去之后不再带「此后一直如此」，改成写明已恢复常态、不残留。
        self.assertNotIn("此后一直如此", carried["E4S01:4"])
        self.assertIn("苏问剑：已恢复常态", carried["E4S01:4"])

    def test_every_scene_numbers_from_one_so_the_carry_is_keyed_by_scene(self):
        # 第 1 场第 2 镜受的伤，不能出现在第 2 场的第 2 镜。
        carried = fight_state.scene_carry([
            _shot(1, "沈无咎左臂被划开一道口子", scene="E1S01"), _shot(2, "两人对峙", scene="E1S01"),
            _shot(1, "苏问剑独坐", people=("苏问剑",), scene="E1S02"), _shot(2, "苏问剑起身", people=("苏问剑",), scene="E1S02"),
        ])
        self.assertIn("左臂被划开", carried["E1S01:2"])
        self.assertNotIn("E1S02:2", carried)

    def test_an_unnamed_clause_counts_only_when_one_person_is_in_the_shot(self):
        alone = fight_state.scene_carry([_shot(1, "右肩中了一箭", people=("沈无咎",)), _shot(2, "他咬牙站起", people=("沈无咎",))])
        self.assertIn("沈无咎：右肩中了一箭", alone["E1S02:2"])
        two = fight_state.scene_carry([_shot(1, "右肩中了一箭"), _shot(2, "两人对峙")])
        self.assertEqual(two, {})


def _desc(task, index, text):
    shot = task["assets"]["4"][index]
    shot["desc"] = text
    shot["motion_contract"]["subject_action"] = text
    shot.pop("contract_fingerprint", None)


class StageFiveTests(ClipRouteStageFiveTests):
    def test_each_clip_keeps_what_earlier_shots_left(self):
        task = _task(2)
        _desc(task, 0, "沈砚左臂被划开一道口子")
        self._run_routes(task)
        self.assertNotIn("伤势与兵器承接", self.calls[0]["prompt"])
        self.assertIn("沈砚：左臂被划开一道口子", self.calls[1]["prompt"])

    def test_a_refused_clip_is_retried_once_with_safe_words_and_full_force(self):
        task = _task(1)
        _desc(task, 0, "沈砚一拳重击，对方嘴角渗血，眼中杀意")
        stored = self._run_routes(task, video=lambda count: None if count == 1 else f"https://cdn/{count}.mp4", failure=SENSITIVE)
        first, retry = self.calls[0]["prompt"], self.calls[1]["prompt"]
        self.assertIn("渗血", first)
        self.assertNotIn("血", retry)
        self.assertIn("重击", retry)
        self.assertEqual(stored["assets"]["5"][0]["moderation_fallback"]["softened_prompt"], True)


# 父类的测试在本类里不重复跑。
for _inherited in [name for name in vars(ClipRouteStageFiveTests) if name.startswith("test_")]:
    setattr(StageFiveTests, _inherited, None)

if __name__ == "__main__":
    unittest.main()

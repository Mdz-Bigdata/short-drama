# -*- coding: utf-8 -*-
"""无缝连镜：镜间衔接账本(道具状态、人物姿态)、首帧不提前画结果、跑动接停下、交付前验收的四项新检查。"""

import unittest

from app.core import delivery_check, shot_ledger
from app.core import shot_transitions as cuts
from app.core.panel_still_prompt import compile_panel_still
from tests.test_delivery_check import _clip, _task, _timeline
from tests.test_panel_still_prompt import _REFERENCES, _ASSETS, _contract

CAST = ["林夏", "周烈"]


def _shot(shot_id, desc, *, props=("文件夹",), cast=("林夏",), scene="S1", start="", end=""):
    return {"scene_id": scene, "shot_id": shot_id, "desc": desc, "props": list(props), "characters": list(cast),
            "motion_contract": {"start_state": start, "end_state": end}}


OFFICE = [
    _shot(1, "林夏站在办公桌左侧，右手拿着文件夹，看向门口的周烈。", cast=("林夏", "周烈")),
    _shot(2, "林夏把文件夹放在桌面中央。"),
    _shot(3, "周烈双手拿着文件夹，翻开。", cast=("周烈",)),
    _shot(4, "林夏坐在椅子上，看着周烈。", props=(), cast=("林夏", "周烈")),
    _shot(5, "林夏站起身，接过周烈递来的文件夹，合上。", cast=("林夏", "周烈")),
]


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = shot_ledger.walk(OFFICE, CAST)

    def entry(self, shot_id):
        return self.ledger[shot_ledger.key("S1", shot_id)]

    def test_props_carry_holder_hand_place_and_state(self):
        self.assertEqual(shot_ledger.end_props(self.entry(1)), {"文件夹": "文件夹在林夏右手"})
        self.assertEqual(shot_ledger.end_props(self.entry(2)), {"文件夹": "文件夹在桌面中央"})
        self.assertEqual(shot_ledger.end_props(self.entry(3)), {"文件夹": "文件夹在周烈双手（打开）"})
        self.assertEqual(shot_ledger.end_props(self.entry(5)), {"文件夹": "文件夹在林夏手里（合上）"})

    def test_the_next_shot_starts_from_where_the_last_one_ended(self):
        self.assertEqual(shot_ledger.handoff_line(self.entry(1)), "", "a scene's first shot has nothing to carry")
        self.assertIn("林夏站着，右手持文件夹", shot_ledger.handoff_line(self.entry(2), ["林夏"], ["文件夹"]))
        self.assertEqual(shot_ledger.handoff_items(self.entry(3), ["周烈"], ["文件夹"]), "文件夹在桌面中央")

    def test_a_change_without_an_action_is_a_continuity_error(self):
        self.assertEqual([issue["rule"] for issue in self.entry(3).issues], ["prop_jump"], "on the desk, then in 周烈's hands with nobody picking it up")
        self.assertEqual([issue["rule"] for issue in self.entry(4).issues], ["posture_jump"], "standing, then sitting with no 坐下")
        self.assertEqual(self.entry(2).issues + self.entry(5).issues, [], "放在 and 站起身 / 接过 explain the changes")

    def test_a_new_scene_starts_a_new_ledger(self):
        ledger = shot_ledger.walk([*OFFICE[:2], _shot(1, "周烈双手拿着文件夹。", scene="S2", cast=("周烈",))], CAST)
        self.assertEqual(ledger[shot_ledger.key("S2", 1)].issues, [])


class StagePlanContactTests(unittest.TestCase):
    """有空间方案的场次：方案里的握持、搁置接触先记，和文字对不上又没动作就是穿帮。"""

    def setUp(self):
        from app.core.spatial_stage import build_plan
        from app.core.spatial_stage.operations import apply_operations
        from tests.test_stage_contacts import _study

        self.plan = apply_operations(build_plan(_study()), [
            {"op": "set_contact", "kind": "hold", "actor": "林夏", "target": "录音笔", "hand": "right", "shot_ids": [2]},
            {"op": "set_contact", "kind": "hold", "actor": "周教授", "target": "录音笔", "shot_ids": [3]},
        ])

    def test_contacts_are_read_and_a_handover_without_an_action_is_flagged(self):
        facts = shot_ledger.staged_facts(self.plan, 2)
        self.assertEqual(facts.props["录音笔"]["holder"], "林夏")
        self.assertEqual(facts.props["录音笔"]["hand"], "右手")
        shots = [
            {"scene_id": "E3S01", "shot_id": 2, "desc": "林夏看着周教授", "characters": ["林夏"], "props": []},
            {"scene_id": "E3S01", "shot_id": 3, "desc": "周教授坐在扶手椅上", "characters": ["周教授"], "props": []},
        ]
        ledger = shot_ledger.walk(shots, ["林夏", "周教授"], plans=lambda _scene: self.plan)
        self.assertEqual(shot_ledger.end_props(ledger["E3S01:2"])["录音笔"], "录音笔在林夏右手")
        self.assertEqual([issue["rule"] for issue in ledger["E3S01:3"].issues], ["prop_jump"])
        handed = [dict(shots[0]), {**shots[1], "desc": "周教授接过林夏递来的录音笔"}]
        self.assertEqual(shot_ledger.walk(handed, ["林夏", "周教授"], plans=lambda _scene: self.plan)["E3S01:3"].issues, [])

    def test_a_missing_or_broken_plan_falls_back_to_the_text(self):
        def broken(_scene):
            raise ValueError("unreadable")

        ledger = shot_ledger.walk(OFFICE, CAST, plans=broken)
        self.assertEqual([issue["rule"] for issue in ledger["S1:3"].issues], ["prop_jump"])


class FrozenKeyframeTests(unittest.TestCase):
    def test_a_single_beat_with_a_result_is_drawn_before_the_result(self):
        contract = _contract(subject_action="沈砚把玉牌放到案上")
        start = compile_panel_still(contract, references=_REFERENCES, assets=_ASSETS).prompt
        end = compile_panel_still(contract, references=_REFERENCES, assets=_ASSETS, frame_state="end").prompt
        self.assertIn("首帧停在动作开始的那一瞬", start)
        self.assertNotIn("首帧停在动作开始的那一瞬", end)
        plain = compile_panel_still(_contract(subject_action="沈砚抬眼看向林晚"), references=_REFERENCES, assets=_ASSETS).prompt
        self.assertNotIn("首帧停在动作开始的那一瞬", plain)


class ArrivalTests(unittest.TestCase):
    def _shot(self, shot_id, desc):
        return {"shot_id": shot_id, "scene_id": "E1S01", "scene": "街口", "size": "全景", "motion": "固定", "desc": desc,
                "duration": "3s", "characters": ["沈砚"], "shot_purpose": "information"}

    def test_a_run_into_a_stop_ends_on_the_slowdown(self):
        plan = cuts.plan_transitions([self._shot(1, "沈砚从画面右侧奔跑向左侧"), self._shot(2, "沈砚停在巷口，双手撑膝喘气")])
        self.assertTrue(plan.cuts[1].arrival)
        self.assertIn("减速收步", cuts.panel_fields(plan, 1, total=2)["end_state"])
        still = cuts.plan_transitions([self._shot(1, "沈砚从画面右侧奔跑向左侧"), self._shot(2, "沈砚继续奔跑，冲进巷子")])
        self.assertFalse(still.cuts[1].arrival)


class DeliveryTests(unittest.TestCase):
    def test_props_postures_gaze_and_tone_are_checked(self):
        clips = [_clip("S1", uid, size) for uid, size in zip(range(1, 7), ("全景", "中景", "近景", "中景", "近景", "特写"))]
        boards = [
            {**OFFICE[0], "lighting": "暖黄烛光"},
            {**OFFICE[1]},
            {**OFFICE[2]},
            {**OFFICE[3], "lighting": "冷蓝月光"},
            {"scene_id": "S1", "shot_id": 5, "characters": ["林夏"], "desc": "林夏看向画面右侧"},
            {"scene_id": "S1", "shot_id": 6, "characters": ["周烈"], "desc": "周烈看向画面右侧"},
        ]
        issues = delivery_check.check(_task(clips, boards), _timeline(clips))
        found = {(issue["shot_uid"], issue["rule"]) for issue in issues}
        self.assertIn((3, "prop_jump"), found)
        self.assertIn((4, "posture_jump"), found)
        self.assertIn((4, "tone_flip"), found)
        self.assertIn((6, "gaze_mismatch"), found)
        self.assertEqual(delivery_check.tone("主光 3200K"), "warm")
        self.assertEqual(delivery_check.tone("月光 6500K"), "cool")


if __name__ == "__main__":
    unittest.main()

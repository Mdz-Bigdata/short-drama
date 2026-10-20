# -*- coding: utf-8 -*-
"""The cut plan: how each storyboard shot hands over to the next, and the checks on it.

Six relations are exercised: logic (time, space, cause), picture (size steps, the 30-degree
rule, eyelines, action matching), motion, matching (shape, light), rhythm and the device
chosen for each cut. No model and no network; the spatial plans are built by the real planner.
"""

import unittest

from app.core import shot_transitions as cuts
from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan
from app.core.spatial_stage.coverage import canonical_size, repeats_the_angle
from app.core.spatial_stage.operations import apply_operations


def _shot(shot_id, desc, cast=("沈砚",), size="中景", motion="固定", scene_id="E1S01", location="书房",
          duration="3s", purpose="information"):
    return {
        "shot_id": shot_id, "scene_id": scene_id, "scene": location, "size": size, "motion": motion,
        "desc": desc, "duration": duration, "characters": list(cast), "shot_purpose": purpose,
    }


def _check(plan, code):
    return next(item for item in plan.checks if item.code == code)


def _pair(first, second, **kwargs):
    return cuts.plan_transitions([first, second], **kwargs).cuts[1]


class CutDecisionTests(unittest.TestCase):
    def test_a_scene_opens_with_a_fade_only_at_the_top_of_an_episode(self):
        opening = cuts.plan_transitions([_shot(1, "沈砚立于窗前", size="全景")], first_of_episode=True).cuts[0]
        self.assertEqual((opening.from_shot, opening.kind, opening.technique), (0, "fade", "opening"))
        self.assertEqual(opening.label, "淡入淡出·开场")
        self.assertEqual(opening.duration_seconds, 0.8)
        self.assertIn("渐显进入", opening.edit_in)

        later = cuts.plan_transitions([_shot(1, "沈砚立于窗前", size="全景")]).cuts[0]
        self.assertEqual((later.kind, later.technique), ("cut", "opening"))

    def test_inside_a_scene_a_look_is_answered_and_then_the_reaction_follows(self):
        plan = cuts.plan_transitions([
            _shot(1, "沈砚看向窗外", size="近景"),
            _shot(2, "窗外一道黑影掠过", cast=(), size="特写"),
            _shot(3, "沈砚脸色一变", size="近景"),
        ])
        look, reaction = plan.cuts[1], plan.cuts[2]
        self.assertEqual((look.kind, look.technique), ("cut", "eyeline_match"))
        self.assertEqual(look.carries, "沈砚投向画外的视线")
        self.assertIn("停在沈砚视线投向画外的瞬间切出", look.edit_out)
        self.assertEqual(reaction.technique, "reaction")
        self.assertIn("切回沈砚的反应", reaction.edit_in)
        self.assertTrue(_check(plan, "transition_eyeline_answered").passed)

    def test_one_action_is_cut_in_the_middle_and_picked_up_in_the_middle(self):
        cut = _pair(_shot(1, "沈砚伸手去拿剑"), _shot(2, "沈砚握住剑柄", size="特写"))
        self.assertEqual((cut.kind, cut.technique), ("cut", "action_match"))
        self.assertEqual(cut.carries, "「伸手」这一个动作")
        self.assertIn("进行到一半时切出", cut.edit_out)
        self.assertIn("同一动作的后半段", cut.edit_in)
        self.assertEqual(cut.size_step, 3)

        # Two different people doing the same kind of thing is not one action.
        other = _pair(_shot(1, "沈砚伸手去拿剑", cast=("沈砚",)), _shot(2, "黄琰握住茶杯", cast=("黄琰",)))
        self.assertEqual(other.technique, "shot_reverse")

    def test_two_singles_of_different_people_are_shot_and_reverse_shot(self):
        cut = _pair(_shot(1, "沈砚沉声开口", cast=("沈砚",)), _shot(2, "黄琰冷笑", cast=("黄琰",)))
        self.assertEqual((cut.kind, cut.technique, cut.label), ("cut", "shot_reverse", "硬切·正反打"))
        self.assertIn("机位留在轴线同一侧", cut.edit_in)

        plain = _pair(_shot(1, "两人对视", cast=("沈砚", "黄琰")), _shot(2, "两人僵持", cast=("沈砚", "黄琰")))
        self.assertEqual(plain.technique, "plain")

    def test_time_passing_and_memory_dissolve_and_a_big_jump_fades(self):
        passage = _pair(_shot(1, "沈砚伏案疾书"), _shot(2, "次日，沈砚仍伏在案上"))
        self.assertEqual((passage.kind, passage.technique, passage.duration_seconds), ("dissolve", "time_passage", 0.5))
        self.assertIn("叠化淡入", passage.edit_in)

        light = _pair(_shot(1, "深夜，烛火下沈砚伏案"), _shot(2, "清晨阳光照进书房"))
        self.assertEqual(light.technique, "time_passage")
        # Candlelight alone is not a time of day.
        self.assertEqual(_pair(_shot(1, "烛火下沈砚伏案"), _shot(2, "阳光照进书房")).kind, "cut")

        memory = _pair(_shot(1, "沈砚闭上眼"), _shot(2, "回忆中少年沈砚在雪地里练剑"))
        self.assertEqual((memory.kind, memory.technique), ("dissolve", "flashback"))

        chapter = _pair(_shot(1, "沈砚转身离去"), _shot(2, "三年后，沈砚鬓角已白"))
        self.assertEqual((chapter.kind, chapter.technique, chapter.duration_seconds), ("fade", "chapter", 0.8))
        self.assertIn("自黑渐显", chapter.edit_in)

    def test_an_optical_transition_settles_both_pictures_whatever_the_cameras_do(self):
        cut = _pair(_shot(1, "沈砚伏案疾书", motion="缓推"), _shot(2, "次日，沈砚仍伏在案上", motion="横移"))
        self.assertEqual(cut.motion_join, "moving_to_moving")
        self.assertIn("画面稳住后再转场", cut.edit_out)
        self.assertIn("画面稳住后再开始运动", cut.edit_in)

        hard = _pair(_shot(1, "沈砚沉声开口", motion="缓推"), _shot(2, "黄琰冷笑", cast=("黄琰",)))
        self.assertEqual(hard.motion_join, "moving_to_static")
        self.assertIn("落幅稳住再切", hard.edit_out)

    def test_a_change_of_scene_rides_a_shared_shape_an_exit_or_a_change_of_colour(self):
        graphic = _pair(
            _shot(1, "沈砚的瞳孔骤然收缩", size="大特写"),
            _shot(2, "一轮圆月悬在城楼上", cast=(), size="大远景", scene_id="E1S02", location="城楼"),
        )
        self.assertEqual((graphic.kind, graphic.technique), ("match_cut", "graphic_match"))
        self.assertEqual(graphic.carries, "瞳孔与圆月同为圆形")

        exit_cut = _pair(
            _shot(1, "沈砚推门而出"),
            _shot(2, "沈砚踏上长街", scene_id="E1S02", location="长街"),
        )
        self.assertEqual((exit_cut.kind, exit_cut.technique), ("cut", "action_match"))

        tone = _pair(
            _shot(1, "烛火映着沈砚的脸"),
            _shot(2, "冷雨打在青石板上", cast=(), scene_id="E1S02", location="长街"),
        )
        self.assertEqual((tone.kind, tone.technique), ("dissolve", "scene_change"))

        plain = _pair(_shot(1, "沈砚合上书卷"), _shot(2, "黄琰在院中踱步", cast=("黄琰",), scene_id="E1S02", location="庭院"))
        self.assertEqual((plain.kind, plain.technique), ("cut", "scene_change"))

    def test_the_first_shot_of_a_scene_cuts_from_the_last_shot_of_the_one_before(self):
        lead_in = _shot(9, "沈砚推门而出", scene_id="E1S01")
        plan = cuts.plan_transitions([_shot(1, "沈砚走进长街", scene_id="E1S02", location="长街")], previous_shot=lead_in)
        self.assertEqual((plan.cuts[0].from_shot, plan.cuts[0].technique), (0, "action_match"))
        self.assertTrue(plan.summary.startswith("入场→1 硬切·动作匹配"))


class CutCheckTests(unittest.TestCase):
    def test_sizes_step_rather_than_leap_unless_the_leap_is_the_point(self):
        leap = cuts.plan_transitions([_shot(1, "沈砚立于庭中", size="大远景"), _shot(2, "沈砚眼神一凛", size="大特写")])
        check = _check(leap, "transition_shot_size_step")
        self.assertFalse(check.passed)
        self.assertEqual(check.shot_ids, [2])
        self.assertIn("「大远景」直接跳到第2镜「大特写」", check.detail)

        shock = cuts.plan_transitions([
            _shot(1, "沈砚立于庭中", size="大远景"), _shot(2, "沈砚眼神一凛", size="大特写", purpose="shock"),
        ])
        self.assertTrue(_check(shock, "transition_shot_size_step").passed)
        insert = cuts.plan_transitions([_shot(1, "沈砚立于庭中", size="大远景"), _shot(2, "剑穗轻晃", cast=(), size="大特写")])
        self.assertTrue(_check(insert, "transition_shot_size_step").passed)

    def test_a_look_into_an_insert_must_come_back_to_whoever_looked(self):
        orphan = cuts.plan_transitions([
            _shot(1, "沈砚看向窗外", size="近景"),
            _shot(2, "窗外一道黑影掠过", cast=(), size="特写"),
            _shot(3, "黄琰端起茶盏", cast=("黄琰",), size="近景"),
        ])
        check = _check(orphan, "transition_eyeline_answered")
        self.assertFalse(check.passed)
        self.assertEqual(check.shot_ids, [3])

        pov = cuts.plan_transitions([_shot(1, "主观镜头：长街尽头的灯火", cast=())])
        self.assertIn("主观镜头", _check(pov, "transition_eyeline_answered").detail)

    def test_opposite_moves_back_to_back_are_flagged(self):
        plan = cuts.plan_transitions([_shot(1, "沈砚沉默", motion="缓推"), _shot(2, "沈砚闭眼", size="近景", motion="拉远")])
        check = _check(plan, "transition_motion_direction")
        self.assertFalse(check.passed)
        self.assertEqual(check.shot_ids, [2])
        same = cuts.plan_transitions([_shot(1, "沈砚沉默", motion="缓推"), _shot(2, "沈砚闭眼", size="近景", motion="推近")])
        self.assertTrue(_check(same, "transition_motion_direction").passed)

    def test_an_effect_before_its_cause_is_flagged_unless_withheld_on_purpose(self):
        rows = [_shot(1, "黄琰中箭倒地", cast=("黄琰",)), _shot(2, "沈砚放箭", cast=("沈砚",))]
        check = _check(cuts.plan_transitions(rows), "transition_cause_before_effect")
        self.assertFalse(check.passed)
        self.assertIn("「中箭」", check.detail)
        rows[0]["shot_purpose"] = "suspense"
        self.assertTrue(_check(cuts.plan_transitions(rows), "transition_cause_before_effect").passed)

    def test_light_and_colour_do_not_flip_across_a_hard_cut_inside_a_scene(self):
        plan = cuts.plan_transitions([_shot(1, "烛火映着沈砚的脸", size="近景"), _shot(2, "冷色的光落在黄琰肩头", cast=("黄琰",), size="近景")])
        self.assertEqual(plan.cuts[1].kind, "cut")
        check = _check(plan, "transition_light_continuity")
        self.assertFalse(check.passed)
        self.assertIn("第1镜暖色、第2镜冷色", check.detail)

        # A change of time of day is dissolved, so the check has nothing to flag.
        dissolved = cuts.plan_transitions([_shot(1, "月光下沈砚伏案"), _shot(2, "清晨阳光照进书房")])
        self.assertEqual(dissolved.cuts[1].kind, "dissolve")
        self.assertTrue(_check(dissolved, "transition_light_continuity").passed)

    def test_rhythm_wants_varied_durations_and_short_action(self):
        even = cuts.plan_transitions([_shot(index, f"沈砚第{index}次落笔") for index in range(1, 6)])
        check = _check(even, "transition_rhythm")
        self.assertFalse(check.passed)
        self.assertIn("全部镜头都是3秒", check.detail)

        rows = [_shot(1, "沈砚落笔", duration="3s"), _shot(2, "沈砚抬头", duration="4s"),
                _shot(3, "沈砚挥剑劈向来人", duration="12s"), _shot(4, "沈砚收剑", duration="2s")]
        slow = _check(cuts.plan_transitions(rows), "transition_rhythm")
        self.assertFalse(slow.passed)
        self.assertEqual(slow.shot_ids, [3])

        varied = [_shot(1, "沈砚落笔", duration="3s"), _shot(2, "沈砚抬头", duration="5s"), _shot(3, "沈砚收笔", duration="2s")]
        self.assertTrue(_check(cuts.plan_transitions(varied), "transition_rhythm").passed)

    def test_grief_does_not_cut_straight_into_comedy(self):
        plan = cuts.plan_transitions([_shot(1, "沈砚痛哭失声"), _shot(2, "黄琰做了个鬼脸", cast=("黄琰",))])
        check = _check(plan, "transition_emotion_bridge")
        self.assertFalse(check.passed)
        self.assertIn("缓冲镜头", check.detail)

    def test_checks_that_measure_the_stage_only_run_with_a_spatial_plan(self):
        codes = {item.code for item in cuts.plan_transitions([_shot(1, "沈砚落笔"), _shot(2, "沈砚抬头")]).checks}
        self.assertNotIn("transition_thirty_degree", codes)
        self.assertNotIn("transition_state_continuous", codes)
        self.assertEqual(len(codes), 7)


def _brief(shots, **overrides):
    values = dict(
        scene_id="E1S01", location="书房", text="沈砚与黄琰隔着书案对峙",
        characters=["沈砚", "黄琰"], props=["书案"], shots=shots,
    )
    values.update(overrides)
    return SceneBrief(**values)


def _rows(specs, scene_id="E1S01"):
    return [
        _shot(spec.shot_id, spec.desc, cast=spec.subjects, size=spec.size, motion=spec.motion, scene_id=scene_id)
        for spec in specs
    ]


class StagedCutTests(unittest.TestCase):
    def test_a_walk_up_is_staged_from_where_the_person_has_been_standing(self):
        specs = [
            ShotSpec(1, ["沈砚", "黄琰"], "", "全景", "平视", "固定", "沈砚与黄琰对峙"),
            ShotSpec(2, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "两人对视"),
            ShotSpec(3, ["黄琰"], "黄琰", "近景", "平视", "固定", "黄琰走近一步"),
            ShotSpec(4, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "黄琰再走近一步"),
        ]
        plan = build_plan(_brief(specs))
        walk = next(item for item in plan.shot(3).overrides if item.name == "黄琰")
        self.assertFalse(walk.hold)
        for shot_id in (1, 2):
            held = next(item for item in plan.shot(shot_id).overrides if item.name == "黄琰")
            self.assertTrue(held.hold)
            self.assertEqual(held.position, walk.position)
            self.assertIn("尚未走近", plan.shot(shot_id).text.blocking)
            # Held for the whole shot: still there when it ends.
            ending = {actor.name: actor for actor in plan.actors_in(plan.shot(shot_id), at_end=True)}
            self.assertEqual(ending["黄琰"].position, walk.position)
        # One mark, one move: the second walk is not staged, so nobody jumps into shot 4.
        self.assertFalse(any(item.position for item in plan.shot(4).overrides))

        transitions = cuts.plan_transitions(_rows(specs), stage_plan=plan)
        self.assertTrue(_check(transitions, "transition_state_continuous").passed)
        self.assertTrue(all(check.passed for check in plan.checks if check.severity == "error"))

    def test_an_edit_that_moves_someone_between_two_hard_cuts_is_a_jump(self):
        specs = [
            ShotSpec(1, ["沈砚", "黄琰"], "", "全景", "平视", "固定", "沈砚与黄琰对峙"),
            ShotSpec(2, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "两人对视"),
        ]
        plan = build_plan(_brief(specs))
        mark = next(actor for actor in plan.actors if actor.name == "黄琰").position
        edited = apply_operations(plan, [{
            "op": "set_shot_override", "shot_id": 2, "name": "黄琰",
            "position": [mark[0] + 2.0, mark[1]], "reason": "挪到门边",
        }])
        check = _check(cuts.plan_transitions(_rows(specs), stage_plan=edited), "transition_state_continuous")
        self.assertFalse(check.passed)
        self.assertEqual(check.shot_ids, [2])
        self.assertIn("黄琰从第1镜结束到第2镜开始，位置相差2.0米", check.detail)

        # Holding them there through the shot before closes the gap.
        held = apply_operations(edited, [{
            "op": "set_shot_override", "shot_id": 1, "name": "黄琰",
            "position": [mark[0] + 2.0, mark[1]], "hold": True, "reason": "一直站在门边",
        }])
        self.assertTrue(next(item for item in held.shot(1).overrides if item.name == "黄琰").hold)
        self.assertTrue(_check(cuts.plan_transitions(_rows(specs), stage_plan=held), "transition_state_continuous").passed)

        # The same change behind a dissolve is time passing, not a jump.
        rows = _rows(specs)
        rows[1]["desc"] = "次日，两人对视"
        self.assertTrue(_check(cuts.plan_transitions(rows, stage_plan=edited), "transition_state_continuous").passed)

    def test_two_people_backing_off_from_an_embrace_never_start_past_each_other(self):
        specs = [
            ShotSpec(1, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "二人相拥"),
            ShotSpec(2, ["沈砚"], "", "近景", "平视", "固定", "沈砚后退一步"),
            ShotSpec(3, ["黄琰"], "", "近景", "平视", "固定", "黄琰后退一步"),
            ShotSpec(4, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "两人对视"),
        ]
        plan = build_plan(_brief(specs, text="二人相拥"))
        marks = {actor.name: actor.position for actor in plan.actors}
        for shot in plan.shots:
            staged = {actor.name: actor.position for actor in plan.actors_in(shot)}
            left = "沈砚" if marks["沈砚"][0] < marks["黄琰"][0] else "黄琰"
            right = "黄琰" if left == "沈砚" else "沈砚"
            self.assertLess(staged[left][0], staged[right][0], f"shot {shot.shot_id} crossed")
        self.assertTrue(all(check.passed for check in plan.checks if check.severity == "error"))

    def test_the_planner_moves_a_lens_that_would_repeat_the_last_angle_and_the_cut_plan_agrees(self):
        specs = [
            ShotSpec(1, ["沈砚"], "", "中近景", "平视", "固定", "沈砚凝视书案"),
            ShotSpec(2, ["沈砚"], "", "MS", "平视", "固定", "沈砚垂下眼"),
            ShotSpec(3, ["沈砚"], "", "CU", "平视", "固定", "沈砚握紧笔杆"),
        ]
        plan = build_plan(_brief(specs, characters=["沈砚"], text="沈砚独坐书案前"))
        cameras = [plan.camera(shot.camera_id) for shot in plan.shots]
        self.assertFalse(repeats_the_angle(cameras[0], cameras[1]))
        transitions = cuts.plan_transitions(_rows(specs), stage_plan=plan)
        self.assertGreaterEqual(transitions.cuts[1].lens_change_deg, 30)
        self.assertTrue(_check(transitions, "transition_thirty_degree").passed)

    def test_shot_list_shorthand_reads_as_the_size_it_names(self):
        self.assertEqual(
            [canonical_size(value) for value in ("CU", "ECU", "MCU", "MS", "MLS", "FS", "LS", "近景 CU", "focus 近景")],
            ["特写", "大特写", "中近景", "中景", "中全景", "全景", "远景", "近景", "近景"],
        )


class PanelTextTests(unittest.TestCase):
    def setUp(self):
        self.plan = cuts.plan_transitions([
            _shot(1, "沈砚立于庭中", size="全景"),
            _shot(2, "沈砚伸手去拿剑"),
            _shot(3, "沈砚握住剑柄", size="特写", motion="缓推"),
        ], first_of_episode=True)

    def test_the_first_panel_establishes_and_the_last_hands_over_to_the_next_scene(self):
        first = cuts.panel_fields(self.plan, 1, total=3)
        self.assertEqual(first["continuity_in"], "建立空间与人物关系")
        self.assertIn("渐显进入", first["edit_in"])
        self.assertIn("向第2镜交付", first["continuity_out"])

        last = cuts.panel_fields(self.plan, 3, total=3)
        self.assertIn("本场最后一镜", last["edit_out"])
        self.assertNotIn("continuity_out", last)

    def test_an_action_match_leaves_the_action_unfinished_on_one_side_and_resumes_it_on_the_other(self):
        before = cuts.panel_fields(self.plan, 2, total=3)
        after = cuts.panel_fields(self.plan, 3, total=3)
        self.assertEqual(before["end_state"], "动作停在进行中，留给下一镜完成")
        self.assertEqual(after["start_state"], "同一动作已进行到一半，从这里继续")
        self.assertIn("承接第2镜（硬切·动作匹配）", after["continuity_in"])
        self.assertIn("景别推近3级", after["continuity_in"])
        self.assertIn("先以起幅稳住约半秒再开始运动", after["edit_in"])

    def test_a_shot_records_the_cut_into_it_in_the_compositor_s_terms(self):
        self.assertEqual(cuts.shot_summary(self.plan, 1)["compositor"], "dip_to_black")
        self.assertEqual(cuts.shot_summary(self.plan, 3), {
            "from_shot": 2, "kind": "cut", "technique": "action_match", "label": "硬切·动作匹配",
            "duration_seconds": 0.0, "motion_join": "static_to_moving", "compositor": "hard_cut",
        })
        self.assertEqual(cuts.shot_summary(self.plan, 99), {})
        self.assertEqual(set(cuts.COMPOSITOR_TRANSITIONS.values()), {"hard_cut", "match_cut", "crossfade", "dip_to_black"})

    def test_a_scene_follows_the_last_shot_of_the_nearest_earlier_scene_that_has_shots(self):
        flat = [
            {"scene_id": "E1S01", "shot_id": 1}, {"scene_id": "E1S01", "shot_id": 9}, {"scene_id": "E1S01", "shot_id": 4},
            {"scene_id": "E1S03", "shot_id": 1},
        ]
        order = ["E1S01", "E1S02", "E1S03"]
        self.assertEqual(cuts.scene_lead_in(flat, order, "E1S03")["shot_id"], 9)
        self.assertEqual(cuts.scene_lead_in(flat, order, "E1S02")["shot_id"], 9)
        self.assertIsNone(cuts.scene_lead_in(flat, order, "E1S01"))
        self.assertIsNone(cuts.scene_lead_in(flat, order, "E9S01"))

    def test_nothing_to_plan_gives_an_empty_plan(self):
        empty = cuts.plan_transitions([])
        self.assertEqual((empty.cuts, empty.checks, empty.summary), ([], [], ""))
        self.assertIn("【镜头衔接】", cuts.TABLE_BRIEF)


if __name__ == "__main__":
    unittest.main()

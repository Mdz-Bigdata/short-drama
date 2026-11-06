# -*- coding: utf-8 -*-
"""The cut plan: how each storyboard shot hands over to the next, and the checks on it.

Six relations are exercised: logic (time, space, cause), picture (size steps, the 30-degree
rule, eyelines, action matching), motion, matching (shape, light), rhythm and the device
chosen for each cut. No model and no network; the spatial plans are built by the real planner.
"""

import unittest
from types import SimpleNamespace

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
        self.assertEqual((later.kind, later.technique), ("dissolve", "opening"))

    def test_inside_a_scene_a_look_is_answered_and_then_the_reaction_follows(self):
        plan = cuts.plan_transitions([
            _shot(1, "沈砚看向窗外", size="近景"),
            _shot(2, "窗外一道黑影掠过", cast=(), size="特写"),
            _shot(3, "沈砚脸色一变", size="近景"),
        ])
        look, reaction = plan.cuts[1], plan.cuts[2]
        self.assertEqual((look.kind, look.technique), ("match_cut", "eyeline_match"))
        self.assertEqual(look.carries, "沈砚投向画外的视线")
        self.assertIn("在沈砚视线投向画外时，镜头顺视线方向带向所见之物", look.edit_out)
        self.assertEqual(reaction.technique, "reaction")
        self.assertIn("回到沈砚的反应", reaction.edit_in)
        self.assertTrue(_check(plan, "transition_eyeline_answered").passed)

    def test_one_action_is_cut_in_the_middle_and_picked_up_in_the_middle(self):
        cut = _pair(_shot(1, "沈砚伸手去拿剑"), _shot(2, "沈砚握住剑柄", size="特写"))
        self.assertEqual((cut.kind, cut.technique), ("match_cut", "action_match"))
        self.assertEqual(cut.carries, "「伸手」这一个动作")
        self.assertIn("进行到一半时顺势衔接到下一镜", cut.edit_out)
        self.assertIn("同一动作的后半段", cut.edit_in)
        self.assertEqual(cut.size_step, 3)

        # Two different people doing the same kind of thing is not one action.
        other = _pair(_shot(1, "沈砚伸手去拿剑", cast=("沈砚",)), _shot(2, "黄琰握住茶杯", cast=("黄琰",)))
        self.assertEqual(other.technique, "shot_reverse")

    def test_two_singles_of_different_people_are_shot_and_reverse_shot(self):
        cut = _pair(_shot(1, "沈砚沉声开口", cast=("沈砚",)), _shot(2, "黄琰冷笑", cast=("黄琰",)))
        self.assertEqual((cut.kind, cut.technique, cut.label), ("match_cut", "shot_reverse", "匹配剪辑·正反打"))
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
        self.assertEqual(_pair(_shot(1, "烛火下沈砚伏案"), _shot(2, "阳光照进书房")).kind, "match_cut")

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
        self.assertIn("落幅稳住再过渡", hard.edit_out)

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
        self.assertEqual((exit_cut.kind, exit_cut.technique), ("match_cut", "action_match"))

        tone = _pair(
            _shot(1, "烛火映着沈砚的脸"),
            _shot(2, "冷雨打在青石板上", cast=(), scene_id="E1S02", location="长街"),
        )
        self.assertEqual((tone.kind, tone.technique), ("dissolve", "scene_change"))

        plain = _pair(_shot(1, "沈砚合上书卷"), _shot(2, "黄琰在院中踱步", cast=("黄琰",), scene_id="E1S02", location="庭院"))
        self.assertEqual((plain.kind, plain.technique), ("push_pull", "scene_change"))
        self.assertIn("前景遮挡物掠过或镜头推进", plain.edit_out)

    def test_the_first_shot_of_a_scene_cuts_from_the_last_shot_of_the_one_before(self):
        lead_in = _shot(9, "沈砚推门而出", scene_id="E1S01")
        plan = cuts.plan_transitions([_shot(1, "沈砚走进长街", scene_id="E1S02", location="长街")], previous_shot=lead_in)
        self.assertEqual((plan.cuts[0].from_shot, plan.cuts[0].technique), (0, "action_match"))
        self.assertTrue(plan.summary.startswith("入场→1 匹配剪辑·动作匹配"))


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

    def test_light_and_colour_do_not_flip_across_a_join_inside_a_scene(self):
        plan = cuts.plan_transitions([_shot(1, "烛火映着沈砚的脸", size="近景"), _shot(2, "冷色的光落在黄琰肩头", cast=("黄琰",), size="近景")])
        self.assertEqual(plan.cuts[1].kind, "match_cut")
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
        self.assertEqual(len(codes), 12)
        self.assertNotIn("transition_attention_jump", codes)


class ConnectionIdeaTests(unittest.TestCase):
    def test_a_similar_movement_links_two_scenes_without_saying_they_are_one(self):
        cut = _pair(_shot(1, "画师的笔向下落笔", cast=("画师",)), _shot(2, "鼓手落槌", cast=("鼓手",), scene_id="E1S02", location="河岸"))
        self.assertEqual((cut.kind, cut.technique), ("match_cut", "action_rhyme"))
        self.assertEqual(cut.carries, "落笔与落槌的相似运动")
        self.assertIn("不表示人物到了对方那里", cut.reasons[0])

    def test_the_same_object_carries_a_change_of_place(self):
        cut = _pair(_shot(1, "书桌上放着六角铜牌"), _shot(2, "铜牌躺在码头石面上", cast=(), scene_id="E1S02", location="码头"))
        self.assertEqual(cut.technique, "object_carry")
        self.assertIn("同一个铜牌", cut.edit_in)

    def test_a_named_occluder_makes_an_occlusion_cut_and_says_cover_it_all(self):
        cut = _pair(_shot(1, "衣袖贴近镜头遮满画面"), _shot(2, "码头清晨", cast=(), scene_id="E1S02", location="码头"))
        self.assertEqual((cut.kind, cut.technique), ("push_pull", "occlusion"))
        self.assertIn("遮满画面", cut.edit_out)
        self.assertIn("前景滑动方向与摄影机运动方向分开写", cut.edit_in)

    def test_leaning_on_a_wall_is_not_an_occlusion(self):
        cut = _pair(_shot(1, "他手撑着墙喘气"), _shot(2, "码头清晨", cast=(), scene_id="E1S02", location="码头"))
        self.assertEqual(cut.technique, "scene_change")

    def test_a_diagonal_can_match_a_diagonal(self):
        cut = _pair(_shot(1, "石阶由左下伸向右上", cast=()), _shot(2, "山脊沿同一方向展开", cast=(), scene_id="E1S02", location="山"))
        self.assertEqual(cut.technique, "graphic_match")
        self.assertIn("斜线", cut.carries)

    def test_the_same_room_keeps_the_lens_when_time_passes(self):
        cut = _pair(_shot(1, "午后日光里他作画", location="画室"), _shot(2, "雨暮时分他仍在作画，次日", location="画室"))
        self.assertEqual(cut.technique, "time_passage")
        self.assertIn("机位与陈设不变", cut.edit_in)

    def test_a_line_runs_past_the_cut_into_a_shot_without_lines(self):
        first = {**_shot(1, "送信人开口"), "dialogue": "他不会来了"}
        cut = _pair(first, _shot(2, "空码头", cast=(), scene_id="E1S02", location="码头"))
        self.assertEqual(cut.sound_join, "l_cut")

    def test_the_next_scene_is_heard_first(self):
        cut = _pair(_shot(1, "他收起画笔"), _shot(2, "鼓手站上高台", cast=("鼓手",), scene_id="E1S02", location="河岸"))
        self.assertEqual(cut.sound_join, "j_cut")

    def test_a_sound_offset_stays_out_of_the_words_sent_to_the_video_model(self):
        first = {**_shot(1, "送信人开口"), "dialogue": "他不会来了"}
        plan = cuts.plan_transitions([first, _shot(2, "空码头", cast=(), scene_id="E1S02", location="码头")])
        self.assertEqual(plan.cuts[1].sound_join, "l_cut")
        for text in cuts.panel_fields(plan, 2, total=2).values():
            self.assertNotIn("L-cut", text)
        self.assertEqual(cuts.shot_summary(plan, 2)["sound_join"], "l_cut")

    def test_a_chapter_fade_does_not_offset_sound(self):
        cut = _pair(_shot(1, "他收起画笔"), _shot(2, "三年后，他回到河岸", location="河岸", scene_id="E1S02"))
        self.assertEqual((cut.kind, cut.sound_join), ("fade", ""))


class CutDiagnosisTests(unittest.TestCase):
    def test_a_cut_that_brings_nothing_new_is_named(self):
        plan = cuts.plan_transitions([_shot(1, "沈砚坐在桌边说话"), _shot(2, "沈砚坐在桌边说话。")])
        check = _check(plan, "transition_new_information")
        self.assertFalse(check.passed)
        self.assertEqual(check.shot_ids, [2])

    def test_a_new_line_is_new_information(self):
        plan = cuts.plan_transitions([_shot(1, "沈砚坐在桌边说话"), {**_shot(2, "沈砚坐在桌边说话。"), "dialogue": "走吧"}])
        self.assertTrue(_check(plan, "transition_new_information").passed)

    def test_an_action_already_finished_is_not_started_again(self):
        plan = cuts.plan_transitions([_shot(1, "沈砚起身，站稳"), _shot(2, "沈砚从椅子上起身", size="近景")])
        self.assertFalse(_check(plan, "transition_action_replay").passed)
        picked_up = cuts.plan_transitions([_shot(1, "沈砚起身，站稳"), _shot(2, "沈砚起身的余势未尽，抬眼", size="近景")])
        self.assertTrue(_check(picked_up, "transition_action_replay").passed)

    def test_walking_the_other_way_needs_a_reason(self):
        plan = cuts.plan_transitions([_shot(1, "沈砚向右走"), _shot(2, "沈砚向左走", size="近景")])
        self.assertFalse(_check(plan, "transition_screen_direction").passed)
        turned = cuts.plan_transitions([_shot(1, "沈砚向右走"), _shot(2, "沈砚转身向左走", size="近景")])
        self.assertTrue(_check(turned, "transition_screen_direction").passed)

    def test_a_fast_move_needs_a_reason_and_a_match(self):
        burst = cuts.plan_transitions([_shot(1, "沈砚慢慢说话"), _shot(2, "沈砚站着", motion="快速左摇", size="近景")])
        self.assertFalse(_check(burst, "transition_motion_energy").passed)
        heard = cuts.plan_transitions([_shot(1, "门外玻璃碎裂声"), _shot(2, "沈砚站着", motion="快速左摇", size="近景")])
        self.assertTrue(_check(heard, "transition_motion_energy").passed)
        brakes = cuts.plan_transitions([_shot(1, "沈砚奔", motion="快速左摇"), _shot(2, "沈砚站定", motion="缓慢左摇", size="近景")])
        self.assertIn("减速带", _check(brakes, "transition_motion_energy").detail)

    def test_a_scene_locked_off_throughout_reads_as_slides(self):
        shots = [_shot(index, f"第{index}个动作", size=size) for index, size in enumerate(("全景", "中景", "近景", "特写"), start=1)]
        self.assertIn("幻灯片", _check(cuts.plan_transitions(shots), "transition_camera_breath").detail)
        shots[2]["motion"] = "缓推"
        self.assertTrue(_check(cuts.plan_transitions(shots), "transition_camera_breath").passed)

    def test_the_eye_is_not_sent_across_the_frame_at_a_similar_size(self):
        def staged(x):
            return SimpleNamespace(screen=[SimpleNamespace(name="沈砚", visible=True, x=x)])

        def check(second_x, second_size="中景"):
            shots = {1: staged(-30), 2: staged(second_x)}
            views = [cuts._view(_shot(1, "他站着"), 1, None), cuts._view(_shot(2, "他抬头", size=second_size), 2, None)]
            found = cuts._diagnosis_checks(list(zip(views, views[1:])), views, SimpleNamespace(shot=shots.get))
            return next(item for item in found if item.code == "transition_attention_jump")

        self.assertFalse(check(30).passed)
        self.assertTrue(check(5).passed)
        self.assertTrue(check(30, second_size="大特写").passed)

    def test_a_violent_move_on_a_person_is_named_but_not_on_an_empty_shot(self):
        person = cuts.plan_transitions([_shot(1, "他站着", motion="剧烈晃动")])
        self.assertFalse(_check(person, "transition_camera_breath").passed)
        empty = cuts.plan_transitions([_shot(1, "空街", cast=(), motion="剧烈晃动")])
        self.assertTrue(_check(empty, "transition_camera_breath").passed)


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
        self.assertIn("承接第2镜（匹配剪辑·动作匹配）", after["continuity_in"])
        self.assertIn("景别推近3级", after["continuity_in"])
        self.assertIn("先以起幅稳住约半秒再开始运动", after["edit_in"])

    def test_a_shot_records_the_cut_into_it_in_the_compositor_s_terms(self):
        self.assertEqual(cuts.shot_summary(self.plan, 1)["compositor"], "dip_to_black")
        self.assertEqual(cuts.shot_summary(self.plan, 3), {
            "from_shot": 2, "kind": "match_cut", "technique": "action_match", "label": "匹配剪辑·动作匹配",
            "duration_seconds": 0.0, "motion_join": "static_to_moving", "compositor": "match_cut",
            "sound_join": "", "sound_note": "", "watch": cuts._WATCH["action_match"],
        })
        self.assertEqual(cuts.shot_summary(self.plan, 99), {})
        self.assertEqual(set(cuts.COMPOSITOR_TRANSITIONS.values()), {"match_cut", "crossfade", "dip_to_black"})

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

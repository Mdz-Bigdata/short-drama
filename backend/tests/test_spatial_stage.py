# -*- coding: utf-8 -*-
"""The spatial stage: marks, axis, solved cameras, screen measurements, checks and edits.

No model, no network: every assertion is geometry. The scene used throughout is a
two-hander with a third person upstage, which is the smallest cast that exercises
the axis, shot / reverse-shot, the inverted triangle and occlusion.
"""

import math
import unittest

from app.core.frame_position import facing_side
from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan
from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage import interchange, language
from app.core.spatial_stage.coverage import canonical_size, move_kind
from app.core.spatial_stage.models import StagePlan
from app.core.spatial_stage.operations import StageEditError, apply_operations
from app.core.spatial_stage.planner import cast_fingerprint, location_key, speaker_of
from app.core.spatial_stage.projection import CameraView, classify_shot_size, screen_states
from app.core.spatial_stage.prompting import bearing_from, landmark_relative_position, table_brief
from app.core.storyboard_director import landmark_is_anchored


def _brief(**overrides) -> SceneBrief:
    values = dict(
        scene_id="E1S02",
        location="文思阁 / 夜 / 内景",
        text="沈砚与黄琰隔着书案对峙，内侍站在后面。炭盆里烧着黄绫。",
        characters=["沈砚", "黄琰", "内侍"],
        props=["黄绫", "炭盆"],
        shots=[
            ShotSpec(1, ["沈砚", "黄琰", "内侍"], "", "全景", "平视", "固定", "三人在文思阁内"),
            ShotSpec(2, ["沈砚"], "沈砚", "近景", "过肩", "固定", "沈砚盯着对面"),
            ShotSpec(3, ["黄琰"], "黄琰", "近景", "过肩", "缓推", "黄琰抬头"),
            ShotSpec(4, ["沈砚"], "黄琰", "特写", "平视", "固定", "沈砚咬牙"),
            ShotSpec(5, [], "", "特写", "俯拍", "固定", "炭盆里的黄绫卷起火舌"),
            ShotSpec(6, ["沈砚", "黄琰"], "", "中景", "平视", "环绕", "两人对视"),
        ],
    )
    values.update(overrides)
    return SceneBrief(**values)


def _states(plan: StagePlan, shot_id: int) -> dict:
    return {state.name: state for state in plan.shot(shot_id).screen}


class GeometryTests(unittest.TestCase):
    def test_yaw_forward_and_right_agree_with_a_three_js_object(self):
        self.assertAlmostEqual(geo.forward_of(0)[1], 1.0)
        self.assertAlmostEqual(geo.forward_of(90)[0], 1.0)
        # Facing +Z, a person's right hand points to -X.
        self.assertEqual(geo.right_of((0.0, 1.0)), (-1.0, 0.0))
        self.assertAlmostEqual(geo.yaw_toward((0, 0), (1, 0)), 90.0)
        self.assertAlmostEqual(geo.yaw_toward((0, 0), (0, -1)), 180.0)
        rotated = geo.rotate(geo.forward_of(30), 45)
        self.assertAlmostEqual(rotated[0], geo.forward_of(75)[0])
        self.assertAlmostEqual(rotated[1], geo.forward_of(75)[1])

    def test_a_portrait_frame_puts_the_long_side_of_the_sensor_upright(self):
        self.assertAlmostEqual(geo.vertical_fov(50, 9 / 16), 39.6, places=1)
        self.assertAlmostEqual(geo.vertical_fov(50, 16 / 9), 22.9, places=1)
        self.assertAlmostEqual(geo.horizontal_fov(geo.vertical_fov(50, 16 / 9), 16 / 9), 39.6, places=1)

    def test_framing_distance_inverts_visible_height(self):
        fov = geo.vertical_fov(65, 9 / 16)
        reach = geo.framing_distance(0.72, fov)
        self.assertAlmostEqual(geo.visible_height(reach, fov), 0.72)
        self.assertEqual(classify_shot_size(0.4), "特写")
        self.assertEqual(classify_shot_size(2.2), "全景")

    def test_formations_are_centred_and_separate_pushes_overlaps_apart(self):
        line = geo.line_positions(3, (0, 0), (1, 0), 1.2)
        self.assertEqual([round(p[0], 2) for p in line], [-1.2, 0.0, 1.2])
        grid = geo.grid_positions(5, (0, 0), (1, 0), 1.0, 3)
        self.assertEqual(sorted(round(p[0], 2) for p in grid[3:]), [-0.5, 0.5])  # short last row stays centred
        circle = geo.circle_positions(4, (0, 0), (0, 1), 2.0)
        self.assertTrue(all(abs(geo.length(p) - 2.0) < 1e-9 for p in circle))
        apart = geo.separate([(0.0, 0.0), (0.1, 0.0)], 0.6)
        self.assertGreaterEqual(geo.distance(apart[0], apart[1]), 0.6 - 1e-6)


class VocabularyTests(unittest.TestCase):
    def test_sizes_moves_and_speakers_are_read_from_storyboard_wording(self):
        self.assertEqual(canonical_size("中近景"), "中近景")
        self.assertEqual(canonical_size("Medium Close-up"), "中近景")
        self.assertEqual(canonical_size("过肩镜头"), "近景")
        self.assertEqual(canonical_size("MS"), "中景")
        self.assertEqual(move_kind("缓推"), "push")
        self.assertEqual(move_kind("Orbit"), "orbit")
        self.assertEqual(move_kind("固定"), "static")
        self.assertEqual(speaker_of("黄琰（惨叫）：抓住他！", ["沈砚", "黄琰"]), "黄琰")
        self.assertEqual(speaker_of("远处的钟声", ["沈砚"]), "")

    def test_a_verb_belongs_to_the_clause_that_names_the_character(self):
        text = "沈砚后退一步，黄琰上前逼近"
        self.assertEqual(language.travel_in("沈砚", text), "retreat")
        self.assertEqual(language.travel_in("黄琰", text), "approach")
        self.assertEqual(language.posture_in("黄琰", "黄琰与内侍对峙，沈砚跪倒在地"), "stand")
        self.assertEqual(language.posture_in("沈砚", "黄琰与内侍对峙，沈砚跪倒在地"), "kneel")
        self.assertTrue(language.enters_in("沈砚", "沈砚推门冲进来"))
        self.assertFalse(language.enters_in("黄琰", "沈砚推门冲进来，黄琰抬头"))

    def test_two_scenes_share_a_set_when_only_the_time_of_day_differs(self):
        self.assertEqual(location_key("文思阁 / 夜 / 内景"), location_key("文思阁 日"))
        self.assertNotEqual(location_key("文思阁"), location_key("太史局"))
        self.assertEqual(cast_fingerprint(["沈砚", "黄琰"], "文思阁 夜"), cast_fingerprint(["黄琰", "沈砚", "无"], "文思阁 日"))


class PlanningTests(unittest.TestCase):
    def test_principals_play_across_one_axis_and_a_third_person_closes_the_triangle(self):
        plan = build_plan(_brief())

        left, right, third = plan.actor("沈砚"), plan.actor("黄琰"), plan.actor("内侍")
        self.assertEqual((left.role, left.screen_side), ("principal", "left"))
        self.assertEqual((right.role, right.screen_side), ("principal", "right"))
        self.assertAlmostEqual(geo.distance(tuple(left.position), tuple(right.position)), 2.6)  # 对峙
        self.assertAlmostEqual(left.yaw_deg, 90.0)   # faces +X, toward his partner
        self.assertAlmostEqual(right.yaw_deg, -90.0)
        self.assertEqual(third.role, "supporting")
        self.assertLess(third.position[1], 0)        # upstage, away from the camera side
        self.assertEqual((plan.axis.kind, plan.axis.from_name, plan.axis.to_name, plan.axis.camera_side), ("dialogue", "沈砚", "黄琰", 1))
        self.assertIn("面对面", plan.formation)
        self.assertIn("倒三角", plan.formation)
        self.assertEqual(plan.coverage, "storyboard")

    def test_the_same_brief_always_gives_the_same_stage(self):
        first, second = build_plan(_brief()), build_plan(_brief())
        drop = {"updated_at"}
        self.assertEqual(first.model_dump(exclude=drop), second.model_dump(exclude=drop))

    def test_every_camera_lives_on_one_side_and_the_pair_never_swaps(self):
        plan = build_plan(_brief())

        self.assertTrue(all(shot.axis_side in {0, 1} for shot in plan.shots))
        for shot_id in (1, 6):
            states = _states(plan, shot_id)
            self.assertLess(states["沈砚"].x, states["黄琰"].x)
            self.assertEqual(facing_side(states["沈砚"].facing), "right")
            self.assertEqual(facing_side(states["黄琰"].facing), "left")
        # Shot / reverse-shot: each single keeps the screen direction the master established.
        self.assertEqual(facing_side(_states(plan, 2)["沈砚"].facing), "right")
        self.assertEqual(facing_side(_states(plan, 3)["黄琰"].facing), "left")
        self.assertEqual(facing_side(_states(plan, 4)["沈砚"].facing), "right")
        self.assertTrue(all(check.passed for check in plan.checks if check.severity == "error"), [c.code for c in plan.checks if not c.passed])

    def test_an_over_the_shoulder_really_holds_the_shoulder_in_a_portrait_frame(self):
        plan = build_plan(_brief())
        camera = plan.camera("cam-02")
        states = _states(plan, 2)

        self.assertEqual(camera.function, "over_shoulder")
        self.assertTrue(states["沈砚"].visible)
        self.assertTrue(states["黄琰"].visible)                  # the foreground shoulder is in frame
        self.assertGreater(states["黄琰"].x, states["沈砚"].x)     # and on the partner's side of it
        self.assertLess(states["黄琰"].depth_m, states["沈砚"].depth_m)
        self.assertIn("近前景", states["黄琰"].depth_layer)
        text = plan.shot(2).text
        self.assertIn("肩背虚化，遮挡画面右侧约四分之一", text.composition)
        self.assertIn("保留沈砚的完整面部", text.composition)
        self.assertIn("沈砚恒在画左、黄琰恒在画右", text.action_axis)
        self.assertIn("不越轴", text.action_axis)

    def test_shot_sizes_become_lens_and_distance(self):
        plan = build_plan(_brief())
        close, wide = plan.camera("cam-04"), plan.camera("cam-01")

        self.assertEqual(close.lens_mm, 85)
        reach = math.dist(close.position, close.target)
        self.assertAlmostEqual(geo.visible_height(reach, close.fov_deg), 0.38, places=2)
        self.assertLess(wide.lens_mm, 40)
        self.assertGreater(math.dist(wide.position, wide.target), reach * 3)
        self.assertEqual(plan.camera("cam-03").move.kind, "push")
        self.assertLess(
            math.dist(plan.camera("cam-03").move.end_position, plan.camera("cam-03").target),
            math.dist(plan.camera("cam-03").position, plan.camera("cam-03").target),
        )

    def test_a_shot_of_nobody_that_names_a_set_piece_is_an_insert_of_it(self):
        plan = build_plan(_brief())
        camera, shot = plan.camera("cam-05"), plan.shot(5)
        brazier = next(item for item in plan.landmarks if item.name == "炭盆")

        self.assertEqual(camera.function, "detail")
        self.assertEqual(camera.target[0], brazier.position[0])
        self.assertEqual(camera.target[2], brazier.position[1])
        self.assertIn("空镜，不出现人物", shot.text.composition)
        self.assertIn("炭盆位于画面中央", shot.text.composition)

    def test_set_pieces_come_from_props_and_whole_phrases_never_from_a_stray_character(self):
        plan = build_plan(_brief(text="沈砚翻开方案，几个门派的人盯着黄琰。两人隔着书案对峙。", props=["黄绫"]))
        names = [item.name for item in plan.landmarks]

        self.assertIn("黄绫", names)
        self.assertIn("书案", names)
        self.assertNotIn("门", names)   # 门派
        self.assertNotIn("案", names)   # 方案
        for landmark in plan.landmarks:
            self.assertTrue(landmark_is_anchored(landmark_relative_position(plan, landmark)), landmark.name)
            self.assertTrue(all(
                geo.distance(tuple(landmark.position), tuple(actor.position)) >= 0.5 for actor in plan.actors
            ))

    def test_a_character_who_enters_is_offstage_before_and_walks_to_the_mark(self):
        brief = _brief(shots=[
            ShotSpec(1, ["黄琰", "内侍"], "", "全景", "平视", "固定", "黄琰把黄绫抖开"),
            ShotSpec(2, ["沈砚"], "", "中景", "平视", "跟拍", "沈砚推门冲进来"),
            ShotSpec(3, ["沈砚", "黄琰"], "黄琰", "中景", "平视", "固定", "两人对峙，黄琰跪倒在地"),
            ShotSpec(4, ["黄琰"], "黄琰", "近景", "平视", "固定", "黄琰惨叫"),
        ])
        plan = build_plan(brief)

        self.assertEqual([actor.name for actor in plan.actors_in(plan.shot(1))], ["黄琰", "内侍"])
        entering = next(item for item in plan.shot(2).overrides if item.name == "沈砚")
        mark = plan.actor("沈砚").position
        self.assertGreater(geo.distance(tuple(entering.position), tuple(mark)), 2.0)
        self.assertEqual(entering.posture, "walk")
        ended = next(actor for actor in plan.actors_in(plan.shot(2), at_end=True) if actor.name == "沈砚")
        self.assertEqual(ended.position, mark)
        # The follow lands on the mark with him, so he is still in frame when the move ends.
        camera = plan.camera("cam-02")
        ending = {state.name: state for state in screen_states(plan.actors_in(plan.shot(2), at_end=True), camera, end=True)}
        self.assertTrue(ending["沈砚"].visible)
        # A posture a shot gives someone holds in the shots after it.
        for shot_id in (3, 4):
            kneeling = next(actor for actor in plan.actors_in(plan.shot(shot_id)) if actor.name == "黄琰")
            self.assertEqual(kneeling.posture, "kneel")
        self.assertIn("跪地", plan.shot(4).text.blocking)
        self.assertTrue(all(check.passed for check in plan.checks), [c.code for c in plan.checks if not c.passed])

    def test_a_scene_without_shots_gets_standard_coverage(self):
        plan = build_plan(_brief(shots=[]))

        self.assertEqual(plan.coverage, "template")
        functions = [camera.function for camera in plan.cameras]
        self.assertEqual(functions[0], "establish")
        self.assertEqual(functions.count("over_shoulder"), 2)
        self.assertTrue(all(check.passed for check in plan.checks if check.severity == "error"))

    def test_solo_empty_and_crowd_scenes_plan_without_an_error(self):
        solo = build_plan(_brief(characters=["沈砚"], text="沈砚伏案书写", shots=[ShotSpec(1, ["沈砚"], "", "中景")]))
        self.assertEqual(solo.axis.kind, "gaze")
        self.assertEqual(solo.axis.from_name, "沈砚")
        # He stands screen left of what he plays to, looking right at it.
        focus = next(item for item in solo.landmarks if item.name == solo.axis.to_name)
        view = CameraView.of(solo.camera("cam-01"))
        self.assertLess(_states(solo, 1)["沈砚"].x, view.project((focus.position[0], 0.4, focus.position[1]))[0] + 1e-6)
        self.assertEqual(facing_side(_states(solo, 1)["沈砚"].facing), "right")

        empty = build_plan(_brief(characters=[], props=[], text="空荡的大殿", shots=[ShotSpec(1, [], "", "远景")]))
        self.assertEqual(empty.actors, [])
        self.assertEqual(empty.cameras[0].function, "empty")

        crowd = build_plan(_brief(characters=["沈砚", "黄琰", "禁军们"], shots=[ShotSpec(1, ["沈砚", "黄琰", "禁军们"], "", "全景")]))
        self.assertEqual(crowd.actor("禁军们").role, "crowd")
        for plan in (solo, empty, crowd):
            self.assertTrue(all(check.passed for check in plan.checks if check.severity == "error"))

    def test_the_side_a_character_was_promised_survives_into_the_next_scene(self):
        default = build_plan(_brief(characters=["黄琰", "沈砚"], shots=[]))
        self.assertEqual(default.actor("黄琰").screen_side, "left")

        remembered = build_plan(_brief(characters=["黄琰", "沈砚"], shots=[]), side_memory={"沈砚": "left", "黄琰": "right"})
        self.assertEqual(remembered.actor("沈砚").screen_side, "left")
        self.assertLess(remembered.actor("沈砚").position[0], remembered.actor("黄琰").position[0])

    def test_a_location_keeps_its_set_pieces_where_an_earlier_scene_put_them(self):
        first = build_plan(_brief())
        moved = [item.model_copy(update={"position": [3.3, -2.2]}) if item.name == "炭盆" else item for item in first.landmarks]

        second = build_plan(_brief(scene_id="E2S05", props=["炭盆", "铜管"]), location_landmarks=moved)

        brazier = next(item for item in second.landmarks if item.name == "炭盆")
        self.assertEqual(brazier.position, [3.3, -2.2])
        self.assertIn("铜管", [item.name for item in second.landmarks])

    def test_blocking_is_kept_and_only_cameras_are_solved_again(self):
        preview = build_plan(_brief(shots=[]))
        edited = apply_operations(preview, [{"op": "face_pair", "first": "沈砚", "second": "黄琰", "distance": 1.0}])

        replanned = build_plan(_brief(), blocking_from=edited)

        self.assertEqual(replanned.source, "edited")
        self.assertEqual(replanned.actor("沈砚").position, edited.actor("沈砚").position)
        self.assertEqual(len(replanned.cameras), 6)
        self.assertEqual(replanned.coverage, "storyboard")
        self.assertGreater(replanned.revision, edited.revision)


class ProjectionTests(unittest.TestCase):
    def test_screen_right_is_the_cross_of_forward_and_up(self):
        plan = build_plan(_brief())
        view = CameraView.of(plan.camera("cam-01"))

        self.assertAlmostEqual(view.ground_forward()[1], -1.0, places=2)   # looking from +Z toward the pair
        self.assertAlmostEqual(view.ground_right()[0], 1.0, places=2)
        x, _, depth = view.project((1.0, 1.0, 0.0))
        self.assertGreater(x, 0)
        self.assertGreater(depth, 0)
        self.assertEqual(view.offscreen_side((-50.0, 0.0)), "left")

    def test_an_overhead_lens_is_neutral_and_keeps_left_and_right(self):
        plan = build_plan(_brief(shots=[
            ShotSpec(1, ["沈砚", "黄琰"], "", "全景", "平视", "固定", ""),
            ShotSpec(2, ["沈砚", "黄琰"], "", "全景", "顶拍", "固定", ""),
        ]))
        shot = plan.shot(2)

        self.assertTrue(axis_rules.is_overhead(plan.camera("cam-02")))
        self.assertEqual((shot.axis_side, shot.crossing), (0, "neutral"))
        states = _states(plan, 2)
        self.assertTrue(states["沈砚"].visible and states["黄琰"].visible)
        self.assertLess(states["沈砚"].x, states["黄琰"].x)
        self.assertIn("中性镜头", shot.text.action_axis)

    def test_bearings_are_said_from_the_character(self):
        plan = build_plan(_brief())
        shen = plan.actor("沈砚")   # at -X, facing +X

        self.assertEqual(bearing_from(shen, (5.0, 0.0))[0], "前方")
        self.assertEqual(bearing_from(shen, (-5.0, 0.0))[0], "后方")
        self.assertEqual(bearing_from(shen, (shen.position[0], -3.0))[0], "左侧")   # upstage is on his left hand
        self.assertEqual(bearing_from(shen, (shen.position[0], 3.0))[0], "右侧")


class ValidationTests(unittest.TestCase):
    def _codes(self, plan: StagePlan) -> dict:
        return {check.code: check for check in plan.checks}

    def test_a_cut_across_the_axis_needs_a_bridge(self):
        plan = build_plan(_brief())
        camera = plan.camera("cam-04")
        mirrored = [camera.position[0], camera.position[1], -camera.position[2]]

        jumped = apply_operations(plan, [{"op": "move_camera", "camera_id": "cam-04", "position": mirrored}])

        check = self._codes(jumped)["spatial_axis_consistent"]
        self.assertFalse(check.passed)
        self.assertEqual(check.severity, "error")
        self.assertEqual(check.shot_ids, [4, 5])   # into the crossed shot, and back out of it
        self.assertIn("第3镜→第4镜越轴", check.detail)
        self.assertEqual(jumped.shot(4).axis_side, -1)
        # From the far side he looks the other way: exactly the flip the rule exists to prevent.
        self.assertEqual(facing_side(_states(jumped, 4)["沈砚"].facing), "left")

    def test_a_neutral_shot_before_it_makes_the_crossing_legal(self):
        plan = build_plan(_brief())
        camera = plan.camera("cam-04")
        mirrored = [camera.position[0], camera.position[1], -camera.position[2]]
        on_axis = [plan.actor("黄琰").position[0] + 1.2, 1.5, 0.0]

        bridged = apply_operations(plan, [
            {"op": "move_camera", "camera_id": "cam-03", "position": on_axis, "target": [plan.actor("沈砚").position[0], 1.5, 0.0]},
            {"op": "move_camera", "camera_id": "cam-04", "position": mirrored},
        ])

        self.assertEqual(bridged.shot(3).crossing, "neutral")
        check = self._codes(bridged)["spatial_axis_consistent"]
        self.assertNotIn("第3镜→第4镜", check.detail)

    def test_a_subject_outside_the_frame_is_an_error(self):
        plan = build_plan(_brief())
        away = apply_operations(plan, [{"op": "move_camera", "camera_id": "cam-04", "target": [30.0, 1.5, 30.0]}])

        check = self._codes(away)["spatial_subjects_in_frame"]
        self.assertFalse(check.passed)
        self.assertEqual(check.shot_ids, [4])
        self.assertIn("第4镜的沈砚", check.detail)

    def test_overlapping_marks_and_a_hidden_subject_are_reported(self):
        plan = build_plan(_brief())
        shen = plan.actor("沈砚").position
        stacked = apply_operations(plan, [{"op": "move_actor", "name": "内侍", "position": [shen[0] + 0.1, shen[1]]}])
        self.assertFalse(self._codes(stacked)["spatial_actor_spacing"].passed)

        camera = plan.camera("cam-01")
        toward_lens = [shen[0] + (camera.position[0] - shen[0]) * 0.4, shen[1] + (camera.position[2] - shen[1]) * 0.4]
        blocked = apply_operations(plan, [{"op": "move_actor", "name": "内侍", "position": toward_lens}])
        hidden = self._codes(blocked)["spatial_subject_occlusion"]
        self.assertFalse(hidden.passed)
        self.assertEqual(hidden.severity, "warning")
        self.assertIn("沈砚被内侍挡住", hidden.detail)

    def test_swapping_the_marks_breaks_the_promised_sides(self):
        plan = build_plan(_brief())
        left, right = plan.actor("沈砚").position, plan.actor("黄琰").position

        swapped = apply_operations(plan, [
            {"op": "move_actor", "name": "沈砚", "position": right, "yaw_deg": -90},
            {"op": "move_actor", "name": "黄琰", "position": left, "yaw_deg": 90},
        ])

        check = self._codes(swapped)["spatial_screen_sides_stable"]
        self.assertFalse(check.passed)
        self.assertIn(1, check.shot_ids)

    def test_a_flattened_move_and_an_averted_partner_are_warnings(self):
        brief = _brief(shots=[
            ShotSpec(1, ["沈砚", "黄琰"], "", "全景", "平视", "固定", ""),
            ShotSpec(2, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "沈砚走向黄琰"),
        ])
        plan = build_plan(brief)
        self.assertTrue(self._codes(plan)["spatial_action_changes_state"].passed)
        self.assertTrue(any(item.position for item in plan.shot(2).overrides))

        flattened = apply_operations(plan, [
            {"op": "clear_shot_override", "shot_id": 2, "name": "沈砚"},
            {"op": "move_actor", "name": "黄琰", "yaw_deg": 0},
        ])
        codes = self._codes(flattened)
        self.assertFalse(codes["spatial_action_changes_state"].passed)
        self.assertIn("第2镜沈砚写了走位", codes["spatial_action_changes_state"].detail)
        self.assertFalse(codes["spatial_facing_partner"].passed)
        self.assertTrue(all(codes[code].severity == "warning" for code in ("spatial_action_changes_state", "spatial_facing_partner")))


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())

    def test_left_means_the_anchors_left_or_the_cameras_left_depending_on_the_reference(self):
        shen = self.plan.actor("沈砚")   # faces +X, so his left hand is -Z (upstage)

        by_actor = apply_operations(self.plan, [{
            "op": "place_relative", "name": "内侍", "anchor": "沈砚", "relation": "left", "distance": 1.5,
        }])
        placed = by_actor.actor("内侍")
        self.assertAlmostEqual(placed.position[0], shen.position[0], places=2)
        self.assertAlmostEqual(placed.position[1], shen.position[1] - 1.5, places=2)
        self.assertAlmostEqual(placed.yaw_deg, 0.0)   # turned to face the anchor

        by_camera = apply_operations(self.plan, [{
            "op": "place_relative", "name": "内侍", "anchor": "沈砚", "reference": "camera", "camera_id": "cam-01",
            "relation": "left", "distance": 1.5, "orient": "none",
        }])
        self.assertLess(by_camera.actor("内侍").position[0], shen.position[0] - 1.4)   # screen left of the master
        self.assertLess(_states(by_camera, 1)["内侍"].x, _states(by_camera, 1)["沈砚"].x)

        nearer = apply_operations(self.plan, [{
            "op": "place_relative", "name": "内侍", "anchor": "沈砚", "reference": "camera", "camera_id": "cam-01",
            "relation": "foreground", "distance": 1.0,
        }])
        self.assertGreater(nearer.actor("内侍").position[1], shen.position[1])          # toward the lens

    def test_foreground_needs_a_camera_and_errors_name_the_operation(self):
        with self.assertRaises(StageEditError) as raised:
            apply_operations(self.plan, [
                {"op": "move_actor", "name": "沈砚", "yaw_deg": 10},
                {"op": "place_relative", "name": "内侍", "anchor": "沈砚", "relation": "foreground"},
            ])
        self.assertIn("operations[1] place_relative", str(raised.exception))
        self.assertIn("以机位为参照", str(raised.exception))
        for bad in (
            [{"op": "teleport"}],
            [{"op": "move_actor", "name": "无名氏", "position": [0, 0]}],
            [{"op": "move_actor", "name": "沈砚", "position": [9999, 0]}],
            [{"op": "move_actor", "name": "沈砚", "posture": "flying"}],
            [{"op": "move_camera", "camera_id": "cam-01", "position": [0, 1, 0], "target": [0, 1, 0]}],
            [],
        ):
            with self.assertRaises(StageEditError):
                apply_operations(self.plan, bad)
        self.assertEqual(self.plan.actor("沈砚").yaw_deg, 90.0)   # all or nothing: the input is untouched

    def test_face_pair_and_formations(self):
        paired = apply_operations(self.plan, [{"op": "face_pair", "first": "沈砚", "second": "黄琰", "distance": 1.2}])
        a, b = paired.actor("沈砚"), paired.actor("黄琰")
        self.assertAlmostEqual(geo.distance(tuple(a.position), tuple(b.position)), 1.2)
        self.assertGreater(geo.dot(geo.forward_of(a.yaw_deg), geo.unit(geo.sub(tuple(b.position), tuple(a.position)))), 0.999)
        self.assertEqual(paired.axis.start, a.position)   # the axis follows the people it joins

        ring = apply_operations(self.plan, [{
            "op": "arrange_group", "names": ["沈砚", "黄琰", "内侍"], "layout": "circle", "radius": 2.0, "center": [0, 0],
        }])
        for name in ("沈砚", "黄琰", "内侍"):
            actor = ring.actor(name)
            self.assertAlmostEqual(geo.length(tuple(actor.position)), 2.0, places=2)
            self.assertGreater(geo.dot(geo.forward_of(actor.yaw_deg), geo.unit(geo.scale(tuple(actor.position), -1))), 0.999)

    def test_flipping_the_side_reissues_the_promise_and_resolving_moves_every_camera(self):
        flipped = apply_operations(self.plan, [{"op": "flip_camera_side"}, {"op": "solve_camera"}])

        self.assertEqual(flipped.axis.camera_side, -1)
        self.assertEqual((flipped.actor("沈砚").screen_side, flipped.actor("黄琰").screen_side), ("right", "left"))
        self.assertTrue(all(shot.axis_side in {0, -1} for shot in flipped.shots))
        self.assertGreater(_states(flipped, 1)["沈砚"].x, _states(flipped, 1)["黄琰"].x)
        self.assertTrue(all(check.passed for check in flipped.checks if check.severity == "error"))
        self.assertEqual((flipped.source, flipped.revision), ("edited", self.plan.revision + 1))

    def test_one_shot_can_be_resolved_with_a_different_intent(self):
        resolved = apply_operations(self.plan, [{"op": "solve_camera", "shot_id": 4, "size": "中景", "over_shoulder": True}])

        camera = resolved.camera("cam-04")
        self.assertEqual(camera.function, "over_shoulder")
        self.assertEqual(resolved.camera("cam-02").position, self.plan.camera("cam-02").position)

    def test_per_shot_changes_and_set_pieces(self):
        edited = apply_operations(self.plan, [
            {"op": "set_shot_override", "shot_id": 6, "name": "内侍", "offstage": True, "reason": "已退下"},
            {"op": "add_landmark", "name": "屏风", "kind": "furniture", "position": [0, -3.5]},
            {"op": "move_landmark", "name": "炭盆", "position": [-2.5, -1.0]},
        ])
        self.assertNotIn("内侍", [actor.name for actor in edited.actors_in(edited.shot(6))])
        self.assertIn("屏风", [item.name for item in edited.landmarks])
        self.assertIn("屏风", edited.scene_bible)

        cleared = apply_operations(edited, [
            {"op": "clear_shot_override", "shot_id": 6, "name": "内侍"}, {"op": "remove_landmark", "name": "屏风"},
        ])
        self.assertIn("内侍", [actor.name for actor in cleared.actors_in(cleared.shot(6))])
        with self.assertRaises(StageEditError):
            apply_operations(cleared, [{"op": "add_landmark", "name": "沈砚"}])


class InterchangeTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())

    def test_a_director_desk_project_round_trips_positions_and_lenses(self):
        document = interchange.to_director_desk(self.plan)

        self.assertEqual(document["version"], 1)
        kinds = [item["kind"] for item in document["objects"]]
        self.assertEqual(kinds.count("character"), 3)
        self.assertEqual(kinds.count("camera"), len(self.plan.cameras))
        # The desk stores the rig body, 1.82 m behind the lens along the look direction.
        camera = self.plan.camera("cam-01")
        rig = next(item for item in document["cameras"] if item["id"] == "cam-01")["transform"]["position"]
        self.assertAlmostEqual(math.dist(rig, camera.position), interchange.DESK_RIG_OFFSET_M, places=2)

        for item in document["objects"]:
            if item["name"] == "沈砚":
                item["transform"]["position"] = [-2.0, 0.0, 0.5]
                item["transform"]["rotation"] = [0.0, math.radians(45), 0.0]
        operations = interchange.import_operations(self.plan, document)
        imported = apply_operations(self.plan, operations)

        self.assertEqual(imported.actor("沈砚").position, [-2.0, 0.5])
        self.assertAlmostEqual(imported.actor("沈砚").yaw_deg, 45.0, places=3)
        for untouched in self.plan.cameras:
            for got, want in zip(imported.camera(untouched.id).position, untouched.position):
                self.assertAlmostEqual(got, want, places=2)

    def test_a_costage_document_round_trips_with_its_plus_x_forward(self):
        document = interchange.to_costage(self.plan)

        self.assertEqual(document["version"], 2)
        shen = next(item for item in document["scenes"][0]["scene"]["characters"] if item["label"] == "沈砚")
        self.assertAlmostEqual(shen["rotation"][1], 0.0, places=6)   # plan yaw 90° is CoStage's +X rest facing
        document["scenes"][0]["scene"]["cameras"][0]["fov"] = 30.0
        operations = interchange.import_operations(self.plan, document)
        imported = apply_operations(self.plan, operations)

        self.assertAlmostEqual(imported.actor("沈砚").yaw_deg, 90.0, places=3)
        self.assertAlmostEqual(imported.camera("cam-01").fov_deg, 30.0, places=0)

    def test_unknown_documents_are_refused(self):
        for document in ({}, {"version": 3}, {"version": 1, "objects": "x"}, {"version": 2, "scenes": []}):
            with self.assertRaises(interchange.InterchangeError):
                interchange.import_operations(self.plan, document)
        stranger = {"version": 1, "objects": [{"kind": "character", "name": "路人", "transform": {"position": [0, 0, 0]}}], "cameras": []}
        with self.assertRaises(interchange.InterchangeError):
            interchange.import_operations(self.plan, stranger)


class ProseTests(unittest.TestCase):
    def test_the_table_brief_states_what_the_table_must_not_contradict(self):
        brief = table_brief(build_plan(_brief(shots=[])))

        self.assertIn("沈砚恒在画左、黄琰恒在画右", brief)
        self.assertIn("相距约2.6米", brief)
        self.assertIn("内侍在两人后方", brief)
        self.assertLessEqual(len(brief), 600)
        self.assertEqual(table_brief(build_plan(_brief(characters=[], props=[], text="空殿", shots=[]))), "")

    def test_every_sentence_fits_the_panel_contract(self):
        plan = build_plan(_brief(characters=["沈砚", "黄琰", "内侍", "魏渊", "裴相", "禁军们"], props=["黄绫", "炭盆", "铜管", "书案"]))
        for shot in plan.shots:
            self.assertLessEqual(len(shot.text.composition), 1000)
            self.assertLessEqual(len(shot.text.action_axis), 500)
            self.assertLessEqual(len(shot.text.eyeline), 500)
            self.assertLessEqual(len(shot.text.blocking), 800)
            self.assertGreaterEqual(len(shot.text.blocking), 2)
        self.assertIn("【空间圣经】", plan.scene_bible)
        self.assertEqual(StagePlan.model_validate(plan.model_dump(mode="json")).scene_id, "E1S02")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""A hall: the crowd is an audience in two seated blocks either side of a centre aisle, and three lenses know where it sits.

No model, no network. The audience sits on the camera side of the stage, so the aisle is the lane a wide
looks down; a lens may stand behind the last row, in a gap among the seats, or behind the stage looking
back. Sizes and trigger words are ``stage_planner.json``'s venue table and ``stage_vocabulary.json``'s
crowd lenses — the tests read them from there.
"""

import unittest

from app.core import prompt_data
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.coverage import ShotSpec, crowd_lens, crowd_lens_names
from app.core.spatial_stage.planner import SceneBrief, build_plan
from app.core.spatial_stage.prompting import table_brief

VENUE = prompt_data.load("stage_planner")["venue"]
LENSES = dict(prompt_data.value("stage_vocabulary", "angles")["crowd_lenses"])
HALL = "集团发布会现场 日 内景"


def _plan(text="沈砚走上讲台，台下记者们举起相机。", cast=("沈砚", "记者们"), shots=(), location=HALL, **more):
    return build_plan(SceneBrief(scene_id="E1S01", location=location, text=text, characters=list(cast), shots=list(shots), **more))


def _shot(shot_id, subjects, angle, size="全景", desc="会场", motion="固定"):
    return ShotSpec(shot_id, list(subjects), "", size, angle, motion, desc)


def _members(plan):
    return [actor for actor in plan.actors if actor.crowd_id]


def _failed(plan, severity="error"):
    return [check.code for check in plan.checks if not check.passed and check.severity == severity]


class AudienceTests(unittest.TestCase):
    def test_the_crowd_of_a_hall_sits_in_two_blocks_with_an_aisle_facing_the_front(self):
        plan = _plan()
        self.assertEqual([(crowd.label, crowd.rows, crowd.columns, crowd.spacing) for crowd in plan.crowds], [
            ("记者们左区", VENUE["rows"], VENUE["columns"], VENUE["spacing_m"]),
            ("记者们右区", VENUE["rows"], VENUE["columns"], VENUE["spacing_m"]),
        ])
        members = _members(plan)
        self.assertEqual(len(members), 2 * VENUE["rows"] * VENUE["columns"])
        left = [actor for actor in members if actor.crowd_id == plan.crowds[0].id]
        right = [actor for actor in members if actor.crowd_id == plan.crowds[1].id]
        # The blocks mirror each other about the aisle, on the camera side of the stage.
        self.assertAlmostEqual(plan.crowds[0].center[0], -plan.crowds[1].center[0])
        self.assertLess(max(actor.position[0] for actor in left), 0)
        self.assertGreater(min(actor.position[0] for actor in right), 0)
        self.assertGreater(min(actor.position[1] for actor in members), VENUE["front_m"] - VENUE["spacing_m"] / 2)
        # A lane stays open down the middle even after each seat's own small shift.
        self.assertGreater(min(abs(actor.position[0]) for actor in members), 0.45)
        for actor in members:
            turned = geo.dot(geo.forward_of(actor.yaw_deg), geo.unit(geo.sub((0.0, 0.0), (actor.position[0], actor.position[1]))))
            with self.subTest(member=actor.name):
                self.assertGreater(turned, 0.95, "everyone looks at the 主位")
                self.assertEqual((actor.role, actor.posture), ("crowd", "sit"))
        self.assertEqual(_failed(plan), [])

    def test_the_cast_name_of_the_crowd_is_someone_in_the_front_row(self):
        plan = _plan()
        named = plan.actor("记者们")
        self.assertTrue(named.crowd_id)
        nearest = min(geo.distance((actor.position[0], actor.position[1]), (0.0, 0.0)) for actor in _members(plan))
        self.assertAlmostEqual(geo.distance((named.position[0], named.position[1]), (0.0, 0.0)), nearest)
        self.assertEqual(len({actor.name for actor in plan.actors}), len(plan.actors))
        # A shot that names the crowd is a shot of that person, taken from the stage side.
        shot = _plan(shots=[_shot(1, ["记者们"], "平视", "近景", "记者们举起相机")])
        self.assertEqual(shot.cameras[0].subjects, ["记者们"])
        self.assertLess(shot.cameras[0].position[2], named.position[1])

    def test_a_lone_lead_stands_at_the_front_and_faces_the_hall(self):
        plan = _plan(props=["话筒"])
        lead = plan.actor("沈砚")
        self.assertEqual((lead.position, lead.yaw_deg, lead.screen_side), ([0.0, 0.0], 0.0, "center"))
        self.assertEqual(plan.axis.kind, "none", "the lead plays to the hall, not to a prop")
        self.assertTrue(plan.formation.startswith(prompt_data.load("stage_planner")["formations"]["venue_single"]))
        self.assertIn("每侧4排4列、相隔1.2米", plan.formation)
        self.assertIn("沈砚居中", table_brief(plan))

    def test_a_pair_keeps_its_axis_and_the_hall_watches_from_the_camera_side(self):
        plan = _plan("颁奖典礼上，沈砚与柳烟在台上对峙，宾客哗然。", ["沈砚", "柳烟", "宾客"], location="酒店礼堂 夜")
        self.assertEqual((plan.axis.kind, plan.axis.from_name, plan.axis.to_name), ("dialogue", "沈砚", "柳烟"))
        self.assertAlmostEqual(geo.distance(tuple(plan.actor("沈砚").position), tuple(plan.actor("柳烟").position)), 2.6)
        self.assertEqual(len(plan.crowds), 2)
        self.assertEqual(_failed(plan), [])

    def test_the_scene_bible_and_the_shot_say_the_blocks_not_the_seats(self):
        plan = _plan(shots=[_shot(1, ["沈砚"], "平视", "近景")])
        self.assertIn("记者们左区：4排×4列共16人", plan.scene_bible)
        self.assertIn("记者们右区16人列阵于沈砚", plan.shot(1).text.blocking)
        self.assertNotIn("记者们左区-01", plan.scene_bible + plan.shot(1).text.blocking)

    def test_a_crowd_outside_a_hall_stays_a_mark_in_the_background(self):
        plan = _plan("长街上，沈砚与柳烟对峙，路人围观。", ["沈砚", "柳烟", "路人"], location="长街 夜")
        self.assertEqual(plan.crowds, [])
        self.assertLess(plan.actor("路人").position[1], 0)
        self.assertNotIn("机位角度还可以写", table_brief(plan))

    def test_a_hall_with_no_crowd_in_the_cast_invents_nobody(self):
        plan = _plan("沈砚独自站在空荡荡的会场里。", ["沈砚"])
        self.assertEqual((plan.crowds, [actor.name for actor in plan.actors]), ([], ["沈砚"]))
        self.assertEqual(plan.actor("沈砚").yaw_deg, 90.0)

    def test_the_same_brief_gives_the_same_hall(self):
        first, second = _plan(), _plan()
        self.assertEqual(
            [(actor.name, actor.position, actor.yaw_deg) for actor in first.actors],
            [(actor.name, actor.position, actor.yaw_deg) for actor in second.actors],
        )

    def test_a_replan_keeps_the_hall_it_was_given(self):
        first = _plan()
        again = build_plan(
            SceneBrief(scene_id="E1S01", location=HALL, text="沈砚走上讲台。", characters=["沈砚", "记者们"],
                       shots=[_shot(1, ["沈砚"], "观众席后方")]),
            blocking_from=first,
        )
        self.assertEqual([crowd.id for crowd in again.crowds], [crowd.id for crowd in first.crowds])
        self.assertEqual(len(_members(again)), len(_members(first)))


class CrowdLensTests(unittest.TestCase):
    def setUp(self):
        self.shots = [
            _shot(1, ["沈砚"], "观众席后方平视"),
            _shot(2, ["沈砚"], "观众席后方俯拍", "远景"),
            _shot(3, ["沈砚"], "人群缝隙侧拍", "中景"),
            _shot(4, ["沈砚"], "主位后方反拍"),
            _shot(5, ["沈砚"], "平视", "近景"),
        ]
        self.plan = _plan(shots=self.shots)
        self.depths = [actor.position[1] for actor in _members(self.plan)]

    def _state(self, shot_id, name="沈砚"):
        return next(state for state in self.plan.shot(shot_id).screen if state.name == name)

    def test_every_lens_word_in_the_table_is_read_only_with_a_crowd_array_on_the_stage(self):
        for kind, words in LENSES.items():
            for word in words:
                spec = _shot(1, ["沈砚"], word)
                self.assertEqual(crowd_lens(spec, self.plan.actors), kind, word)
                self.assertEqual(crowd_lens(spec, [self.plan.actor("沈砚")]), "", word)
        self.assertEqual(crowd_lens(_shot(1, ["沈砚"], "平视", desc="镜头从人群缝隙里看过去"), self.plan.actors), "through_crowd")
        self.assertEqual(crowd_lens(_shot(1, ["沈砚"], "平视"), self.plan.actors), "")
        self.assertEqual(crowd_lens_names(), [words[0] for words in LENSES.values()])

    def test_from_behind_the_audience_the_lens_looks_down_the_aisle_over_the_heads(self):
        camera = self.plan.cameras[0]
        self.assertGreater(camera.position[2], max(self.depths) + 1.0)
        self.assertLess(abs(camera.position[0]), 0.3, "in the aisle")
        self.assertGreater(camera.position[1], 1.7 * 0.74 + 0.5, "above the seated heads")
        state = self._state(1)
        self.assertTrue(state.visible and not state.occluded_by)
        self.assertEqual(state.facing, "面向镜头")
        self.assertGreater(sum(1 for item in self.plan.shot(1).screen if item.visible), 5, "the audience fills the foreground")

    def test_asking_to_look_down_raises_that_lens(self):
        level, high = self.plan.cameras[0], self.plan.cameras[1]
        self.assertEqual((high.position[0], high.position[2]), (level.position[0], level.position[2]))
        self.assertGreater(high.position[1], level.position[1] + 2.0)
        self.assertLessEqual(high.position[1], 6.0)
        self.assertGreater(
            sum(1 for item in self.plan.shot(2).screen if item.visible), sum(1 for item in self.plan.shot(1).screen if item.visible),
        )

    def test_in_the_crowd_the_lens_stands_among_the_seats_and_still_sees_the_stage(self):
        camera = self.plan.cameras[2]
        self.assertGreater(camera.position[2], min(self.depths))
        self.assertLess(camera.position[2], max(self.depths))
        block = [actor.position[0] for actor in _members(self.plan) if actor.position[0] * camera.position[0] > 0]
        self.assertTrue(min(map(abs, block)) <= abs(camera.position[0]) <= max(map(abs, block)), "inside a block, not in the aisle")
        # The line to the stage passes between the heads ahead, not through one.
        spot, sight = (camera.position[0], camera.position[2]), geo.unit(geo.sub((0.0, 0.0), (camera.position[0], camera.position[2])))
        for actor in _members(self.plan):
            offset = geo.sub((actor.position[0], actor.position[1]), spot)
            if geo.dot(offset, sight) > 0.3:
                self.assertGreater(abs(geo.dot(offset, geo.right_of(sight))) / geo.dot(offset, sight), 0.1, actor.name)
        nearest = min(geo.distance((camera.position[0], camera.position[2]), (a.position[0], a.position[1])) for a in _members(self.plan))
        self.assertGreater(nearest, 0.4, "in a gap, not on a seat")
        state = self._state(3)
        self.assertTrue(state.visible and not state.occluded_by)

    def test_from_behind_the_stage_the_lens_sees_the_lead_from_the_back_and_the_hall_beyond(self):
        camera = self.plan.cameras[3]
        self.assertLess(camera.position[2], 0)
        self.assertEqual(self._state(4).facing, "背对镜头")
        self.assertGreater(sum(1 for item in self.plan.shot(4).screen if item.visible and item.name != "沈砚"), 12)

    def test_an_ordinary_shot_is_solved_as_before(self):
        plain = _plan(shots=[_shot(5, ["沈砚"], "平视", "近景")], cast=["沈砚"], text="沈砚独自站在空荡荡的会场里。")
        hall = self.plan.cameras[4]
        self.assertLess(hall.position[2], min(self.depths), "a close single stays between the stage and the first row")
        self.assertEqual((plain.cameras[0].lens_mm, plain.cameras[0].shot_size), (hall.lens_mm, hall.shot_size))

    def test_no_shot_of_the_hall_fails_a_check(self):
        self.assertEqual(_failed(self.plan), [])
        self.assertEqual(_failed(self.plan, "warning"), [])

    def test_a_pair_seen_from_behind_the_stage_is_a_legal_crossing_and_said_so(self):
        plan = _plan("颁奖典礼上，沈砚与柳烟在台上对峙，宾客哗然。", ["沈砚", "柳烟", "宾客"], location="酒店礼堂 夜", shots=[
            _shot(1, ["沈砚", "柳烟"], "观众席后方"), _shot(2, ["沈砚", "柳烟"], "主位后方反拍"), _shot(3, ["柳烟"], "人群缝隙侧拍", "中景"),
        ])
        self.assertEqual([shot.axis_side for shot in plan.shots], [1, -1, 1])
        self.assertEqual(plan.shot(2).crossing, "reestablish")
        self.assertEqual(_failed(plan), [])
        self.assertEqual(_failed(plan, "warning"), ["spatial_screen_sides_stable"])
        for shot, camera in zip(plan.shots, plan.cameras):
            for state in shot.screen:
                if state.name in camera.subjects:
                    self.assertTrue(state.visible and not state.occluded_by, (shot.shot_id, state.name))

    def test_the_storyboard_writer_is_told_the_words_the_solver_reads(self):
        brief = table_brief(self.plan)
        for name in crowd_lens_names():
            self.assertIn(name, brief)
        self.assertIn("记者们左区、记者们右区", brief)


if __name__ == "__main__":
    unittest.main()

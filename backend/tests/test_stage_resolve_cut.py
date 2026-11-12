# -*- coding: utf-8 -*-
"""Re-solving lenses on a stage that already exists keeps what the plan gave the cut.

The auto plan varies the angle between consecutive shots of the same people (the 30-degree
rule) and sends a moving camera along with a subject who walks to their mark. The
``solve_camera`` operation has to leave both in place, and a sweep over every shot must not
replace a lens someone keyed or one that several shots look through.
"""

import unittest

from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan
from app.core.spatial_stage.coverage import repeats_the_angle
from app.core.spatial_stage.cutting import carry_camera, vary_angle
from app.core.spatial_stage.models import StagePlan
from app.core.spatial_stage.operations import apply_operations


def _plan() -> StagePlan:
    return build_plan(SceneBrief(
        scene_id="E1S01", location="茶馆 / 日 / 内景", text="林夏与周教授对坐谈话。",
        characters=["林夏", "周教授"], props=[],
        shots=[
            ShotSpec(1, ["林夏", "周教授"], "", "中景", "平视", "固定", "两人对坐"),
            ShotSpec(2, ["林夏", "周教授"], "林夏", "中景", "平视", "固定", "林夏开口"),
            ShotSpec(3, ["林夏", "周教授"], "周教授", "中景", "平视", "固定", "周教授回答"),
            ShotSpec(4, ["林夏"], "林夏", "近景", "平视", "跟拍", "林夏走到窗前"),
        ],
    ))


def _cameras(plan: StagePlan) -> list[dict]:
    return [camera.model_dump() for camera in plan.cameras]


class ResolveKeepsTheCutTests(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()

    def test_the_fixture_has_a_varied_angle_and_a_carried_move(self):
        first, second, _third, follow = self.plan.cameras
        self.assertNotEqual(first.position, second.position)
        self.assertFalse(repeats_the_angle(first, second))
        self.assertEqual(follow.move.kind, "follow")
        self.assertIsNotNone(follow.move.end_position)

    def test_a_sweep_gives_back_the_lenses_the_plan_had(self):
        self.assertEqual(_cameras(apply_operations(self.plan, [{"op": "solve_camera"}])), _cameras(self.plan))
        self.assertEqual(_cameras(apply_operations(self.plan, [{"op": "flip_camera_side"}, {"op": "flip_camera_side"}], solve=True)), _cameras(self.plan))

    def test_a_sweep_gives_back_a_shot_of_nobody_as_the_plan_solved_it(self):
        # An insert with no angle written looks down at its piece, and an empty frame takes the room at eye level.
        plan = build_plan(SceneBrief(
            scene_id="E1S02", location="书房 / 夜 / 内景", text="沈砚与黄琰在书房对坐。",
            characters=["沈砚", "黄琰"], props=["书案", "茶杯", "炭盆"],
            shots=[
                ShotSpec(1, ["沈砚", "黄琰"], "", "全景", "平视", "固定", "两人对坐"),
                ShotSpec(2, [], "", "特写", "", "固定", "茶杯特写"),
                ShotSpec(3, [], "", "中景", "", "环绕", "炭盆里的火"),
                ShotSpec(4, [], "", "全景", "", "固定", "夜色"),
            ],
        ))
        self.assertEqual([camera.function for camera in plan.cameras], ["establish", "detail", "detail", "empty"])
        self.assertEqual([camera.angle for camera in plan.cameras[1:]], ["俯拍", "俯拍", "平视"])
        self.assertEqual(_cameras(apply_operations(plan, [{"op": "solve_camera"}])), _cameras(plan))
        for shot in plan.shots:
            with self.subTest(shot=shot.shot_id):
                named = apply_operations(plan, [{"op": "solve_camera", "shot_id": shot.shot_id}])
                self.assertEqual(_cameras(named), _cameras(plan))

    def test_a_sweep_after_an_edit_repeats_no_angle(self):
        moved = apply_operations(self.plan, [{"op": "move_actor", "name": "周教授", "position": [1.4, 0.3]}], solve=True)
        for previous, current in zip(moved.cameras, moved.cameras[1:]):
            self.assertFalse(repeats_the_angle(previous, current), (previous.id, current.id))

    def test_naming_one_shot_still_turns_it_away_from_the_shot_before(self):
        # Shot 3 on its own solves to shot 1's lens; put shot 2 there and re-solve shot 3 alone.
        first = self.plan.camera("cam-01")
        same = apply_operations(self.plan, [{
            "op": "move_camera", "camera_id": "cam-02", "position": first.position, "target": first.target, "lens_mm": first.lens_mm,
        }], solve=False)
        self.assertTrue(repeats_the_angle(same.camera("cam-02"), same.camera("cam-03")))

        solved = apply_operations(same, [{"op": "solve_camera", "shot_id": 3}], solve=False)

        self.assertFalse(repeats_the_angle(solved.camera("cam-02"), solved.camera("cam-03")))
        self.assertEqual(solved.camera("cam-02").position, same.camera("cam-02").position)

    def test_a_follow_shot_keeps_the_end_of_its_move(self):
        before = self.plan.camera("cam-04")
        after = apply_operations(self.plan, [{"op": "solve_camera", "shot_id": 4}], solve=False).camera("cam-04")
        self.assertEqual(after.move.model_dump(), before.move.model_dump())
        # The move ends on the mark the subject walks to, not where they started.
        mark = self.plan.actor("林夏").position
        self.assertAlmostEqual(after.move.end_target[0], mark[0], delta=0.6)

    def test_a_sweep_leaves_a_keyed_lens_where_someone_put_it(self):
        keyed = apply_operations(self.plan, [
            {"op": "move_camera", "camera_id": "cam-02", "position": [2.0, 1.6, 3.0], "target": [0.0, 1.2, 0.0]},
            {"op": "apply_camera_move", "shot_id": 2, "preset": "push"},
        ], solve=False)

        swept = apply_operations(keyed, [{"op": "solve_camera"}])
        self.assertEqual(swept.camera("cam-02").model_dump(), keyed.camera("cam-02").model_dump())
        self.assertEqual(swept.timelines["2"].camera, keyed.timelines["2"].camera)

        named = apply_operations(keyed, [{"op": "solve_camera", "shot_id": 2}])
        self.assertNotEqual(named.camera("cam-02").position, keyed.camera("cam-02").position)

    def test_a_sweep_leaves_a_lens_several_shots_share(self):
        stored = self.plan.model_dump()
        stored["shots"][2]["camera_id"] = "cam-01"
        stored["cameras"] = [camera for camera in stored["cameras"] if camera["id"] != "cam-03"]
        shared = StagePlan.model_validate(stored)
        placed = apply_operations(shared, [{
            "op": "move_camera", "camera_id": "cam-01", "position": [0.5, 1.5, 5.0], "target": [0.0, 1.1, 0.0],
        }], solve=False)

        swept = apply_operations(placed, [{"op": "solve_camera"}])
        self.assertEqual(swept.camera("cam-01").position, placed.camera("cam-01").position)

        named = apply_operations(placed, [{"op": "solve_camera", "shot_id": 1}])
        self.assertNotEqual(named.camera("cam-01").position, placed.camera("cam-01").position)


class CuttingHelperTests(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()

    def test_vary_angle_solves_again_only_for_a_repeat(self):
        first, second = self.plan.camera("cam-01"), self.plan.camera("cam-02")
        asked: list[object] = []

        def solve(avoid=None):
            asked.append(avoid)
            return second

        self.assertIs(vary_angle(None, first, solve), first)
        self.assertIs(vary_angle(first, second, solve), second)
        self.assertEqual(asked, [])
        self.assertIs(vary_angle(first, first, solve), second)
        self.assertEqual(len(asked), 1)
        self.assertIsNotNone(asked[0])

    def test_carry_camera_leaves_a_still_lens_and_a_subject_on_their_mark_alone(self):
        still = self.plan.camera("cam-01")
        self.assertIs(carry_camera(still, self.plan.shots[0], self.plan), still)
        follow = self.plan.camera("cam-04")
        on_mark = self.plan.shots[3].model_copy(update={"overrides": []})
        self.assertIs(carry_camera(follow, on_mark, self.plan), follow)


if __name__ == "__main__":
    unittest.main()

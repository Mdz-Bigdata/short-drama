# -*- coding: utf-8 -*-
"""Automatic repair of failing spatial checks, drawn routes as keys, set-piece arrays and
alignment, and the depth capture hand-off."""

import unittest

from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan, paths, repair
from app.core.spatial_stage.models import StagePlan
from app.core.spatial_stage.operations import OPERATIONS, StageEditError, apply_operations
from app.service import director_desk_service as desk
from tests.test_director_desk import PNG, _mp4, _task


def _brief() -> SceneBrief:
    return SceneBrief(
        scene_id="E1S02", location="文思阁 / 夜 / 内景",
        text="沈砚与黄琰隔着书案对峙，内侍站在后面。",
        characters=["沈砚", "黄琰", "内侍"], props=["炭盆", "书案"],
        shots=[
            ShotSpec(1, ["沈砚", "黄琰", "内侍"], "", "全景", "平视", "固定", "三人在文思阁内"),
            ShotSpec(2, ["沈砚"], "沈砚", "近景", "过肩", "固定", "沈砚盯着对面"),
            ShotSpec(3, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "两人对视"),
        ],
    )


def _failing(plan: StagePlan) -> list[str]:
    return repair.failing(plan.checks)


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())
        self.assertEqual(_failing(self.plan), [])

    def _broken(self) -> StagePlan:
        a = self.plan.actor("沈砚")
        return apply_operations(self.plan, [
            {"op": "move_actor", "name": "黄琰", "position": [a.position[0] + 0.1, a.position[1]], "yaw_deg": a.yaw_deg},
            {"op": "move_camera", "camera_id": self.plan.shots[2].camera_id, "position": [a.position[0], 1.5, a.position[1] + 0.1]},
        ], solve=False)

    def test_every_failing_check_gets_a_proposal_made_of_ordinary_operations(self):
        broken = self._broken()
        codes = _failing(broken)
        self.assertIn("spatial_actor_spacing", codes)
        self.assertIn("spatial_facing_partner", codes)
        self.assertIn("spatial_camera_clearance", codes)

        proposals = repair.propose(broken)
        self.assertEqual([item.code for item in proposals], codes)
        self.assertTrue(all(item.automatic for item in proposals), [item.manual for item in proposals])
        for item in proposals:
            for operation in item.operations:
                self.assertIn(operation["op"], OPERATIONS)
        spacing = next(item for item in proposals if item.code == "spatial_actor_spacing")
        self.assertEqual({op["name"] for op in spacing.operations}, {"沈砚", "黄琰"})
        # Two lens checks on the same shot ask for one solve.
        combined = repair.combined_operations(proposals)
        self.assertEqual(sum(1 for op in combined if op["op"] == "solve_camera"), 1)

    def test_applying_the_proposals_clears_the_checks(self):
        broken = self._broken()
        fixed = apply_operations(broken, repair.combined_operations(repair.propose(broken)), solve=False)
        self.assertEqual(_failing(fixed), [])
        a, b = fixed.actor("沈砚"), fixed.actor("黄琰")
        self.assertGreaterEqual(((a.position[0] - b.position[0]) ** 2 + (a.position[1] - b.position[1]) ** 2) ** 0.5, repair.SPACING_TARGET_M - 1e-6)

    def test_repair_checks_operation_does_the_same_in_one_edit_and_can_be_narrowed(self):
        broken = self._broken()
        fixed = apply_operations(broken, [{"op": "repair_checks"}], solve=False)
        self.assertEqual(_failing(fixed), [])
        self.assertEqual(fixed.revision, broken.revision + 1)

        only_spacing = apply_operations(broken, [{"op": "repair_checks", "codes": ["spatial_actor_spacing"]}], solve=False)
        self.assertNotIn("spatial_actor_spacing", _failing(only_spacing))
        self.assertIn("spatial_camera_clearance", _failing(only_spacing))

        with self.assertRaises(StageEditError) as refused:
            apply_operations(self.plan, [{"op": "repair_checks"}], solve=False)
        self.assertIn("没有可以自动修正", str(refused.exception))
        with self.assertRaises(StageEditError):
            apply_operations(broken, [{"op": "repair_checks", "codes": "spatial_actor_spacing"}], solve=False)

    def test_a_scene_that_opens_mirrored_swaps_the_pair_back(self):
        a, b = self.plan.actor("沈砚"), self.plan.actor("黄琰")
        mirrored = apply_operations(self.plan, [
            {"op": "move_actor", "name": "沈砚", "position": list(b.position), "yaw_deg": b.yaw_deg},
            {"op": "move_actor", "name": "黄琰", "position": list(a.position), "yaw_deg": a.yaw_deg},
        ], solve=False)
        self.assertIn("spatial_screen_sides_stable", _failing(mirrored))
        proposal = next(item for item in repair.propose(mirrored) if item.code == "spatial_screen_sides_stable")
        self.assertTrue(proposal.automatic)
        fixed = apply_operations(mirrored, proposal.operations, solve=False)
        self.assertNotIn("spatial_screen_sides_stable", _failing(fixed))
        self.assertEqual(fixed.actor("沈砚").position, a.position)

    def test_a_posture_the_storyboard_names_is_written_as_that_shots_override(self):
        plan = build_plan(_brief())
        shots = [shot.model_copy(update={"action": "沈砚跪倒在地" if shot.shot_id == 2 else shot.action, "overrides": []}) for shot in plan.shots]
        from app.core.spatial_stage.planner import refresh

        plan = refresh(plan.model_copy(update={"shots": shots}))
        self.assertIn("spatial_action_changes_state", _failing(plan))
        proposal = next(item for item in repair.propose(plan) if item.code == "spatial_action_changes_state")
        self.assertEqual(proposal.operations, [{
            "op": "set_shot_override", "shot_id": 2, "name": "沈砚", "posture": "kneel", "reason": "分镜写明「kneel」",
        }])
        fixed = apply_operations(plan, proposal.operations, solve=False)
        self.assertNotIn("spatial_action_changes_state", _failing(fixed))

    def test_a_walk_the_storyboard_names_is_left_to_a_person(self):
        plan = build_plan(_brief())
        shots = [shot.model_copy(update={"action": "黄琰走向沈砚" if shot.shot_id == 3 else shot.action, "overrides": []}) for shot in plan.shots]
        from app.core.spatial_stage.planner import refresh

        plan = refresh(plan.model_copy(update={"shots": shots}))
        proposal = next(item for item in repair.propose(plan) if item.code == "spatial_action_changes_state")
        self.assertFalse(proposal.automatic)
        self.assertIn("画一条路径", proposal.manual)


class PathTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())
        self.shot = self.plan.shots[0]

    def test_a_drawn_walk_becomes_evenly_spaced_keys_that_face_along_the_route(self):
        route = [[0, 0], [0, 1], [0.05, 2], [0, 3], [2, 3]]
        edited = apply_operations(self.plan, [
            {"op": "set_path", "shot_id": 1, "target": "沈砚", "points": route, "start_s": 0.5, "end_s": 4.5, "easing": "smooth"},
        ], solve=False)
        keys = edited.timelines["1"].actors["沈砚"]
        self.assertGreaterEqual(len(keys), 4)
        self.assertEqual((keys[0].time, keys[0].position, keys[-1].time, keys[-1].position), (0.5, [0.0, 0.0], 4.5, [2.0, 3.0]))
        # Even spacing along the route, and the walker turns to where they are going.
        gaps = [((a.position[0] - b.position[0]) ** 2 + (a.position[1] - b.position[1]) ** 2) ** 0.5 for a, b in zip(keys, keys[1:])]
        self.assertLess(max(gaps) - min(gaps), 0.2)
        self.assertAlmostEqual(abs(keys[1].yaw_deg) % 180, 0, delta=12)   # heading north first
        self.assertAlmostEqual(keys[-1].yaw_deg % 360, 90, delta=20)       # arriving heading east
        self.assertTrue(all(key.easing == "linear" for key in keys))
        # Keys sit at even distances, so where a smooth move is slow (both ends) they are far apart in time.
        times = [key.time for key in keys]
        self.assertGreater(times[1] - times[0], times[len(times) // 2] - times[len(times) // 2 - 1])
        linear = apply_operations(self.plan, [{"op": "set_path", "shot_id": 1, "target": "沈砚", "points": route, "end_s": 4}], solve=False)
        steps = [b.time - a.time for a, b in zip(linear.timelines["1"].actors["沈砚"], linear.timelines["1"].actors["沈砚"][1:])]
        self.assertLess(max(steps) - min(steps), 0.01)
        # The other tracks of the timeline are untouched by a second route for someone else.
        again = apply_operations(edited, [{"op": "set_path", "shot_id": 1, "target": "黄琰", "points": [[1, 1], [1, 2]]}], solve=False)
        self.assertEqual(set(again.timelines["1"].actors), {"沈砚", "黄琰"})

    def test_facing_can_hold_or_watch_a_point_while_walking(self):
        held = apply_operations(self.plan, [{"op": "set_path", "shot_id": 1, "target": "沈砚", "points": [[0, 0], [0, 2]], "face": "hold"}], solve=False)
        self.assertTrue(all(key.yaw_deg is None for key in held.timelines["1"].actors["沈砚"]))
        watching = apply_operations(self.plan, [
            {"op": "set_path", "shot_id": 1, "target": "沈砚", "points": [[-2, 0], [2, 0]], "face": "point", "face_target": "黄琰"},
        ], solve=False)
        partner = watching.actor("黄琰")
        for key in watching.timelines["1"].actors["沈砚"]:
            expected = paths.heading_deg((key.position[0], 0, key.position[1]), (partner.position[0], 0, partner.position[1]), 0)
            self.assertAlmostEqual(key.yaw_deg, expected, delta=0.5)
        with self.assertRaises(StageEditError):
            apply_operations(self.plan, [{"op": "set_path", "shot_id": 1, "target": "沈砚", "points": [[0, 0], [0, 2]], "face": "point"}], solve=False)

    def test_a_camera_route_keeps_the_lens_on_its_subject(self):
        edited = apply_operations(self.plan, [
            {"op": "set_path", "shot_id": 1, "target": "camera", "points": [[-3, -3], [0, -4], [3, -3]], "height_m": 1.4, "look_at": "沈砚", "end_s": 3},
        ], solve=False)
        keys = edited.timelines["1"].camera
        subject = edited.actor("沈砚")
        self.assertTrue(all(key.position[1] == 1.4 for key in keys))
        self.assertTrue(all((key.target[0], key.target[2]) == (subject.position[0], subject.position[1]) for key in keys))
        self.assertEqual(keys[0].lens_mm, edited.camera(self.shot.camera_id).lens_mm)
        ahead = apply_operations(self.plan, [{"op": "set_path", "shot_id": 1, "target": "camera", "points": [[0, 1.2, -3], [0, 1.2, 3]]}], solve=False)
        first = ahead.timelines["1"].camera[0]
        self.assertGreater(first.target[2], first.position[2])

    def test_a_route_past_the_end_lengthens_the_shot_unless_the_length_was_stated(self):
        edited = apply_operations(self.plan, [{"op": "set_path", "shot_id": 1, "target": "沈砚", "points": [[0, 0], [0, 2]], "end_s": 8}], solve=False)
        self.assertEqual(edited.timelines["1"].duration_s, 8)
        with self.assertRaises(StageEditError) as refused:
            apply_operations(self.plan, [{"op": "set_path", "shot_id": 1, "target": "沈砚", "points": [[0, 0], [0, 2]], "end_s": 8, "duration_s": 5}], solve=False)
        self.assertIn("超过了时间线时长", str(refused.exception))

    def test_bad_routes_are_refused_in_words(self):
        for operation, needle in (
            ({"op": "set_path", "shot_id": 1, "target": "沈砚", "points": [[0, 0]]}, "2 到 400 个点"),
            ({"op": "set_path", "shot_id": 1, "target": "沈砚", "points": [[0, 0], [0, 0]]}, "起点和终点不能重合"),
            ({"op": "set_path", "shot_id": 1, "target": "沈砚", "points": [[0, 0], [0, "a"]]}, "有限数字"),
            ({"op": "set_path", "shot_id": 1, "target": "沈砚", "points": [[0, 0], [0, 2]], "easing": "hold"}, "easing"),
            ({"op": "set_path", "shot_id": 1, "target": "无名", "points": [[0, 0], [0, 2]]}, "场上没有人物"),
            ({"op": "set_path", "shot_id": 1, "points": [[0, 0], [0, 2]]}, "target"),
            ({"op": "set_path", "shot_id": 1, "target": "camera", "points": [[0, 0], [0, 2]], "look_at": 5}, "look_at"),
        ):
            with self.assertRaises(StageEditError, msg=operation) as refused:
                apply_operations(self.plan, [operation], solve=False)
            self.assertIn(needle, str(refused.exception))
        many = [[i * 0.01, 0] for i in range(401)]
        with self.assertRaises(StageEditError):
            apply_operations(self.plan, [{"op": "set_path", "shot_id": 1, "target": "沈砚", "points": many}], solve=False)
        long = [[i * 0.1, 0] for i in range(400)]
        keys = apply_operations(self.plan, [{"op": "set_path", "shot_id": 1, "target": "沈砚", "points": long}], solve=False).timelines["1"].actors["沈砚"]
        self.assertLessEqual(len(keys), paths.MAX_PATH_KEYS)

    def test_smoothing_cuts_corners_but_keeps_the_ends(self):
        route = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)]
        cut = paths.chaikin(route)
        self.assertEqual((cut[0], cut[-1]), (route[0], route[-1]))
        self.assertNotIn((1.0, 0.0, 0.0), cut)
        self.assertEqual(paths.chaikin(route, 0), route)


class SetPieceTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())
        self.name = self.plan.landmarks[0].name

    def test_a_line_array_keeps_the_original_in_place_and_names_the_copies(self):
        edited = apply_operations(self.plan, [{"op": "array_landmark", "name": self.name, "layout": "line", "count": 4, "spacing": 1.0, "direction_deg": 0}], solve=False)
        pieces = [item for item in edited.landmarks if item.name == self.name or item.name.startswith(f"{self.name} ")]
        self.assertEqual([item.name for item in pieces], [self.name, f"{self.name} 2", f"{self.name} 3", f"{self.name} 4"])
        original = self.plan.landmarks[0]
        self.assertEqual(pieces[0].position, original.position)
        # direction_deg is the yaw the row runs along: one metre per piece that way.
        from app.core.spatial_stage import geometry as geo

        along = geo.forward_of(0)
        for index, item in enumerate(pieces):
            self.assertAlmostEqual(item.position[0] - original.position[0], along[0] * index, places=3)
            self.assertAlmostEqual(item.position[1] - original.position[1], along[1] * index, places=3)
        self.assertEqual(len({item.id for item in edited.landmarks}), len(edited.landmarks))
        self.assertTrue(all(item.shape == original.shape and item.size == original.size for item in pieces))

    def test_grid_and_ring_arrays(self):
        grid = apply_operations(self.plan, [{"op": "array_landmark", "name": self.name, "layout": "grid", "count": 6, "columns": 3, "spacing": 1.0}], solve=False)
        self.assertEqual(len(grid.landmarks), len(self.plan.landmarks) + 5)
        ring = apply_operations(self.plan, [{"op": "array_landmark", "name": self.name, "layout": "ring", "count": 6, "radius": 2.0}], solve=False)
        pieces = [item for item in ring.landmarks if item.name == self.name or item.name.startswith(f"{self.name} ")]
        xs = [item.position[0] for item in pieces]
        zs = [item.position[1] for item in pieces]
        centre = (sum(xs) / 6, sum(zs) / 6)
        for item in pieces:
            self.assertAlmostEqual(((item.position[0] - centre[0]) ** 2 + (item.position[1] - centre[1]) ** 2) ** 0.5, 2.0, delta=0.05)
        self.assertEqual(pieces[0].position, self.plan.landmarks[0].position)

    def test_arrays_are_bounded(self):
        for operation, needle in (
            ({"op": "array_landmark", "name": self.name, "count": 1}, "count"),
            ({"op": "array_landmark", "name": self.name, "count": 41}, "count"),
            ({"op": "array_landmark", "name": "无", "count": 2}, "场上没有地标"),
            ({"op": "array_landmark", "name": self.name, "layout": "spiral"}, "layout"),
        ):
            with self.assertRaises(StageEditError, msg=operation) as refused:
                apply_operations(self.plan, [operation], solve=False)
            self.assertIn(needle, str(refused.exception))
        big = apply_operations(self.plan, [{"op": "array_landmark", "name": self.name, "count": 40}] * 2, solve=False)
        self.assertEqual(len(big.landmarks), len(self.plan.landmarks) + 78)
        self.assertEqual(len({item.name for item in big.landmarks}), len(big.landmarks))
        with self.assertRaises(StageEditError) as refused:
            apply_operations(big, [{"op": "array_landmark", "name": self.name, "count": 3}], solve=False)
        self.assertIn("上限 80", str(refused.exception))

    def test_align_and_distribute(self):
        names = [item.name for item in self.plan.landmarks[:2]]
        self.assertEqual(len(names), 2)
        aligned = apply_operations(self.plan, [{"op": "align_landmarks", "names": names, "axis": "z", "mode": "center"}], solve=False)
        zs = {item.position[1] for item in aligned.landmarks if item.name in names}
        self.assertEqual(len(zs), 1)
        spread = apply_operations(self.plan, [
            {"op": "array_landmark", "name": names[0], "count": 3, "spacing": 1.0, "direction_deg": 0},
            {"op": "transform_landmark", "name": f"{names[0]} 2", "position": [self.plan.landmarks[0].position[0] + 0.2, self.plan.landmarks[0].position[1]]},
            {"op": "align_landmarks", "names": [names[0], f"{names[0]} 2", f"{names[0]} 3"], "axis": "x", "mode": "distribute"},
        ], solve=False)
        xs = sorted(item.position[0] for item in spread.landmarks if item.name in {names[0], f"{names[0]} 2", f"{names[0]} 3"})
        self.assertAlmostEqual(xs[1] - xs[0], xs[2] - xs[1], places=3)
        with self.assertRaises(StageEditError):
            apply_operations(self.plan, [{"op": "align_landmarks", "names": names[:1]}], solve=False)
        with self.assertRaises(StageEditError):
            apply_operations(self.plan, [{"op": "align_landmarks", "names": names, "mode": "spiral"}], solve=False)


class DepthCaptureTests(unittest.TestCase):
    BLOCKING = "林夏（站立）与周教授（站立）相距2.6米面对面；机位距林夏5.1米、机高1.4米"
    PROMPT = f"镜头1。调度：{BLOCKING}；动作：对峙。相机以“固定”运动。"

    def setUp(self):
        self.task = _task("depth")
        self.shot = self.task["assets"]["4"][0]

    def test_a_depth_still_is_kept_but_never_applied_as_a_first_frame(self):
        still = desk.add_capture(self.task, "E1S01", desk.CaptureUpload(content=PNG, kind="still", shot_id=1, depth=True), "https://cdn.test/media/d.png")
        self.assertTrue(still["depth"])
        self.assertEqual(still["warning"], desk.DEPTH_WARNING)
        with self.assertRaises(desk.CaptureError) as refused:
            desk.apply_capture(self.task, "E1S01", still["id"])
        self.assertIn("深度静帧不能作为首帧", str(refused.exception))
        with self.assertRaises(desk.CaptureError):
            desk.validate_upload(desk.CaptureUpload(content=PNG, kind="backdrop", shot_id=0, depth=True))

    def test_an_applied_depth_clip_tells_stage_five_what_it_may_copy(self):
        clip = desk.add_capture(self.task, "E1S01", desk.CaptureUpload(content=_mp4(4), kind="clip", shot_id=1, duration_s=4, depth=True), "https://cdn.test/media/d.mp4")
        desk.apply_capture(self.task, "E1S01", clip["id"])
        inputs = desk.motion_inputs(self.task, self.shot, list(self.shot.get("reference_videos") or []), self.BLOCKING, self.PROMPT)
        self.assertTrue(inputs.blockout.depth and inputs.blockout.owns_camera)
        self.assertIn(desk.DEPTH_REQUIREMENT, inputs.motion_prompt)
        self.assertNotIn("机位距", inputs.motion_prompt)
        self.assertEqual(inputs.motion_prompt.count(desk.DEPTH_REQUIREMENT), 1)
        # A plain clip says nothing about depth.
        plain = desk.add_capture(self.task, "E1S01", desk.CaptureUpload(content=_mp4(4), kind="clip", shot_id=1, duration_s=4), "https://cdn.test/media/p.mp4")
        desk.apply_capture(self.task, "E1S01", plain["id"])
        inputs = desk.motion_inputs(self.task, self.shot, list(self.shot.get("reference_videos") or []), self.BLOCKING, self.PROMPT)
        self.assertNotIn(desk.DEPTH_REQUIREMENT, inputs.motion_prompt)


if __name__ == "__main__":
    unittest.main()

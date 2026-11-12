# -*- coding: utf-8 -*-
"""Set pieces as the lenses see them: a piece is placed on screen at the height it really is, and an insert
of a small prop upstage of the axis still frames it at the size the shot asks for.

No model, no network.
"""

import math
import unittest

from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan
from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import StageCamera, StageLandmark, StagePlan
from app.core.spatial_stage.projection import SHOT_SIZE_HEIGHTS
from app.core.spatial_stage.prompting import landmark_relative_position, layout_facts

CLOSE_UP_M = dict(SHOT_SIZE_HEIGHTS)["特写"]


class MasterSideTests(unittest.TestCase):
    def _plan(self, elevation: float) -> StagePlan:
        # A high master looking down into the room, and a lantern hung on a beam just in front of it.
        master = StageCamera(
            id="cam-01", label="主机位", position=[0.0, 1.6, 4.0], target=[0.0, 0.8, 0.0], fov_deg=40, aspect="9:16",
            function="establish",
        )
        lantern = StageLandmark(
            id="mark-01", name="宫灯", kind="light", position=[0.0, 3.8], size=[0.4, 0.4, 0.4], elevation_m=elevation,
        )
        return StagePlan(scene_id="E1S04", cameras=[master], landmarks=[lantern])

    def test_a_piece_is_placed_on_screen_where_it_hangs_not_where_it_would_stand(self):
        # On the floor it is in the middle of the master frame; hung 2 m up it is above and behind the lens.
        self.assertEqual(layout_facts(self._plan(0.0)), "宫灯在画面中央")
        self.assertEqual(layout_facts(self._plan(2.0)), "")
        self.assertNotIn("主机位画面", landmark_relative_position(self._plan(2.0), self._plan(2.0).landmarks[0]))


class UpstageInsertTests(unittest.TestCase):
    def _plan(self, angle: str) -> StagePlan:
        return build_plan(SceneBrief(
            scene_id="E1S05", location="书房 / 夜 / 内景", text="沈砚与黄琰对峙。", characters=["沈砚", "黄琰"],
            props=["书案", "录音笔"],
            shots=[
                ShotSpec(1, ["沈砚", "黄琰"], "", "全景", "平视", "固定", "两人对峙"),
                ShotSpec(2, [], "", "特写", angle, "固定", "录音笔特写"),
            ],
        ))

    def test_a_small_prop_on_an_upstage_table_fills_a_close_up(self):
        for angle in ("", "俯拍", "平视"):
            with self.subTest(angle=angle):
                plan = self._plan(angle)
                pieces = {piece.name: piece for piece in plan.landmarks}
                desk, recorder = pieces["书案"], pieces["录音笔"]
                self.assertEqual(recorder.size, [0.14, 0.03, 0.03])
                self.assertAlmostEqual(recorder.elevation_m, desk.size[2])
                # The table stands upstage of the pair, so the lens is kept back on the camera side.
                self.assertEqual(axis_rules.side_of(plan.axis, (desk.position[0], desk.position[1])), -plan.axis.camera_side)
                camera = plan.camera(plan.shot(2).camera_id)
                self.assertEqual(axis_rules.side_of(plan.axis, (camera.position[0], camera.position[2])), plan.axis.camera_side)
                # The longer lens makes up for it: the frame covers a close-up's height, not a near shot's.
                covered = geo.visible_height(math.dist(camera.position, camera.target), camera.fov_deg)
                self.assertAlmostEqual(covered, CLOSE_UP_M, delta=0.02)
                self.assertGreater(camera.lens_mm, 85.0)
                self.assertIn("录音笔位于画面中央", plan.shot(2).text.composition)
                for code in ("spatial_camera_clearance", "spatial_set_clearance", "spatial_axis_consistent"):
                    check = next(item for item in plan.checks if item.code == code)
                    self.assertTrue(check.passed, check.detail)

    def test_an_overhead_insert_keeps_the_height_that_fits_the_piece_across_the_frame(self):
        # Straight down on a portrait frame, the lens rises until the piece fits across the narrow side. That height
        # is framing, so the lens is not lengthened over it; only the 2.2 m floor a small prop is held at is slack.
        for props, desc, piece in ((["屏风"], "屏风特写", "屏风"), (["书案", "录音笔"], "录音笔特写", "录音笔")):
            with self.subTest(piece=piece):
                plan = build_plan(SceneBrief(
                    scene_id="E1S05", location="书房 / 夜 / 内景", text="沈砚与黄琰对峙。", characters=["沈砚", "黄琰"],
                    props=props,
                    shots=[
                        ShotSpec(1, ["沈砚", "黄琰"], "", "全景", "平视", "固定", "两人对峙"),
                        ShotSpec(2, [], "", "特写", "顶拍", "固定", desc),
                    ],
                ))
                item = next(landmark for landmark in plan.landmarks if landmark.name == piece)
                camera = plan.camera(plan.shot(2).camera_id)
                across = geo.visible_height(math.dist(camera.position, camera.target), camera.fov_deg) * geo.parse_aspect(camera.aspect)
                self.assertGreaterEqual(across, max(CLOSE_UP_M, item.size[2] * 1.2) - 0.02)
        self.assertGreater(camera.lens_mm, 85.0)


if __name__ == "__main__":
    unittest.main()

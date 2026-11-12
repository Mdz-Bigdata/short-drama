# -*- coding: utf-8 -*-
"""Which desk captures an edit of the stage dates.

A capture is a picture of one shot. An edit dates it when the edit could show in it: the cast's
marks or the set changed, or its own shot, timeline or lens did. Framing the next shot does not.
"""

import unittest
from typing import Any

from app.core.spatial_stage.models import StagePlan, StageShot
from app.service import director_desk_service as desk
from app.service import spatial_stage_service as spatial

SCENE = "E1S01"
CAM_2_ELSEWHERE = {"op": "move_camera", "camera_id": "cam-02", "position": [2.0, 1.6, 3.0], "target": [0.0, 1.2, 0.0]}


def _task() -> dict[str, Any]:
    return {
        "task_id": "dated", "current_stage": 5, "status": "idle",
        "assets": {
            "2_breakdown": {"scenes": [{"scene_id": SCENE, "content": "林夏在办公室与周教授对峙", "characters": ["林夏", "周教授"]}]},
            "4": [
                {"shot_id": 1, "scene_id": SCENE, "size": "全景", "angle": "平视", "motion": "固定", "desc": "两人对峙", "characters": ["林夏", "周教授"],
                 "reference_videos": ["http://v.test/library.mp4"]},
                {"shot_id": 2, "scene_id": SCENE, "size": "近景", "angle": "平视", "motion": "固定", "desc": "林夏盯着对面", "characters": ["林夏"]},
                {"shot_id": 3, "scene_id": SCENE, "size": "近景", "angle": "平视", "motion": "固定", "desc": "周教授没有回答", "characters": ["周教授"]},
            ],
        },
    }


class CaptureStalenessTests(unittest.TestCase):
    def setUp(self):
        self.task = _task()
        plan = spatial.ensure_plan(self.task, SCENE)
        self.assertEqual([(shot.shot_id, shot.camera_id) for shot in plan.shots], [(1, "cam-01"), (2, "cam-02"), (3, "cam-03")])
        self.made = 0

    def _capture(self, shot_id: int, camera_id: str = "", kind: str = "still") -> dict[str, Any]:
        self.made += 1
        upload = desk.CaptureUpload(content=b"x", kind=kind, shot_id=shot_id, camera_id=camera_id, duration_s=6.0 if kind == "clip" else 0.0)
        return desk.add_capture(self.task, SCENE, upload, f"https://cdn.test/media/desk_{self.made}.bin")

    def _edit(self, *operations: dict[str, Any], solve: bool | None = False) -> StagePlan:
        revision = spatial.load_plan(self.task, SCENE).revision
        return spatial.edit_plan(self.task, SCENE, base_revision=revision, operations=list(operations), solve=solve)

    def test_framing_another_shot_leaves_this_shots_pictures_good(self):
        first, second, third = self._capture(1, "cam-01"), self._capture(2, "cam-02"), self._capture(3, "cam-03")

        self._edit(CAM_2_ELSEWHERE)

        self.assertEqual((first["stale"], second["stale"], third["stale"]), (False, True, False))

    def test_a_picture_taken_through_the_lens_that_moved_is_dated_whatever_its_shot(self):
        borrowed, free, own = self._capture(1, "cam-02"), self._capture(1), self._capture(2)

        self._edit(CAM_2_ELSEWHERE)

        self.assertEqual((borrowed["stale"], free["stale"], own["stale"]), (True, False, True))

    def test_what_another_shot_does_with_its_cast_and_its_timeline_stays_in_that_shot(self):
        for operation in (
            {"op": "set_shot_override", "shot_id": 2, "name": "林夏", "position": [-1.0, 0.8]},
            {"op": "set_pose", "name": "林夏", "preset": "sit", "shot_id": 2},
            {"op": "apply_camera_move", "shot_id": 2, "preset": "push"},
        ):
            with self.subTest(op=operation["op"]):
                self.setUp()
                first, second = self._capture(1, "cam-01"), self._capture(2, "cam-02")
                self._edit(operation)
                self.assertEqual((first["stale"], second["stale"]), (False, True))

    def test_the_marks_and_the_set_are_in_every_picture(self):
        for operation in (
            {"op": "move_actor", "name": "周教授", "position": [1.8, 0.4]},
            {"op": "set_pose", "name": "林夏", "preset": "sit"},
            {"op": "add_landmark", "name": "书架", "position": [3.0, 2.0]},
        ):
            with self.subTest(op=operation["op"]):
                self.setUp()
                # Shot 2 is 林夏 alone: 周教授 and the shelf are still on the stage behind her.
                captures = [self._capture(1, "cam-01"), self._capture(2, "cam-02"), self._capture(3)]
                self._edit(operation)
                self.assertEqual([item["stale"] for item in captures], [True, True, True])

    def test_an_edit_that_changes_nothing_dates_nothing(self):
        camera = spatial.load_plan(self.task, SCENE).camera("cam-02")
        capture = self._capture(2, "cam-02")

        edited = self._edit({"op": "move_camera", "camera_id": "cam-02", "position": list(camera.position), "target": list(camera.target)})

        self.assertEqual(edited.camera("cam-02").position, camera.position)
        self.assertFalse(capture["stale"])

    def test_a_dated_picture_stays_dated_and_a_backdrop_is_never_dated(self):
        second, backdrop = self._capture(2, "cam-02"), self._capture(0, kind="backdrop")
        self._edit(CAM_2_ELSEWHERE)
        self._edit({"op": "move_camera", "camera_id": "cam-03", "position": [-2.0, 1.6, 3.0], "target": [0.0, 1.2, 0.0]})
        self.assertTrue(second["stale"])

        self._edit({"op": "move_actor", "name": "林夏", "position": [-2.0, 0.5]})
        self.assertFalse(backdrop["stale"])

    def test_a_rebuild_dates_the_whole_scene(self):
        captures = [self._capture(1, "cam-01"), self._capture(2, "cam-02")]
        spatial.rebuild_plan(self.task, SCENE)
        self.assertEqual([item["stale"] for item in captures], [True, True])

    def test_a_replan_for_a_rewritten_storyboard_dates_the_shots_it_solved_differently(self):
        first, second = self._capture(1, "cam-01"), self._capture(2, "cam-02")
        before = spatial.load_plan(self.task, SCENE)
        self.task["assets"]["4"][1].update(size="全景", characters=["林夏", "周教授"])

        after = spatial.plan_scene(self.task, spatial.scene_record(self.task, SCENE), spatial.scene_shots(self.task, SCENE))

        self.assertEqual(after.camera("cam-01").position, before.camera("cam-01").position)
        self.assertNotEqual(after.camera("cam-02").position, before.camera("cam-02").position)
        self.assertEqual((first["stale"], second["stale"]), (False, True))

    def test_a_picture_of_a_shot_the_stage_does_not_have_is_dated(self):
        orphan = self._capture(9)
        self._edit(CAM_2_ELSEWHERE)
        self.assertTrue(orphan["stale"])

    def test_the_applied_clip_of_an_untouched_shot_still_reaches_stage_five(self):
        clip = self._capture(1, "cam-01", kind="clip")
        desk.apply_capture(self.task, SCENE, clip["id"])

        self._edit(CAM_2_ELSEWHERE)

        shot = self.task["assets"]["4"][0]
        inputs = desk.motion_inputs(self.task, shot, list(shot["reference_videos"]), "机位距林夏5.1米、机高1.4米", "p")
        self.assertEqual((inputs.refused, inputs.blockout.owns_camera), ([], True))
        # A still taken of the same shot afterwards can be applied too; the edited shot's cannot.
        desk.apply_capture(self.task, SCENE, self._capture(1, "cam-01")["id"])
        dated = self._capture(2, "cam-02")
        self._edit({"op": "move_camera", "camera_id": "cam-02", "position": [2.4, 1.6, 3.0], "target": [0.0, 1.2, 0.0]})
        with self.assertRaises(desk.CaptureError):
            desk.apply_capture(self.task, SCENE, dated["id"])


class ExclusionTests(unittest.TestCase):
    """A picture stays good only when the whole difference is known not to show in it."""

    def setUp(self):
        self.task = _task()
        self.plan = spatial.ensure_plan(self.task, SCENE)
        upload = desk.CaptureUpload(content=b"x", kind="still", shot_id=1, camera_id="cam-01")
        self.capture = desk.add_capture(self.task, SCENE, upload, "https://cdn.test/media/desk_1.png")

    def _dated_by(self, after: StagePlan) -> bool:
        self.capture["stale"] = False
        desk.mark_captures_stale(self.task, SCENE, before=self.plan, after=after)
        return self.capture["stale"]

    def test_the_fields_left_out_are_real_and_change_no_picture(self):
        self.assertLessEqual(desk._PLAN_BOOKKEEPING, set(StagePlan.model_fields))
        self.assertLessEqual(desk._SHOT_DERIVED, set(StageShot.model_fields))
        self.assertFalse(self._dated_by(self.plan.model_copy(update={"revision": self.plan.revision + 1, "source": "edited", "updated_at": "later"})))

    def test_any_other_field_of_the_plan_dates_the_scene(self):
        tried = set()
        for field in sorted(set(StagePlan.model_fields) - desk._PLAN_BOOKKEEPING - {"shots", "cameras", "timelines"}):
            value = getattr(self.plan, field)
            if isinstance(value, str):
                changed: Any = value + "x"
            elif isinstance(value, list) and value:
                changed = value[:-1]
            else:
                continue
            tried.add(field)
            with self.subTest(field=field):
                # Not validated on purpose: all that matters is that the two plans disagree there.
                self.assertTrue(self._dated_by(self.plan.model_copy(update={field: changed})))
        self.assertLessEqual({"actors", "aspect_ratio", "location"}, tried)
        self.assertTrue(self._dated_by(self.plan.model_copy(update={"axis": self.plan.axis.model_copy(update={"from_name": "别人"})})))

    def test_without_both_plans_everything_is_dated(self):
        self.capture["stale"] = False
        desk.mark_captures_stale(self.task, SCENE, before=self.plan)
        self.assertTrue(self.capture["stale"])

    def test_two_records_under_one_id_date_everything(self):
        doubled = self.plan.model_copy(update={"cameras": [*self.plan.cameras, self.plan.cameras[-1]]})
        self.assertTrue(self._dated_by(doubled))


if __name__ == "__main__":
    unittest.main()

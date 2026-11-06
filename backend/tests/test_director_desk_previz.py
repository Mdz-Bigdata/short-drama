# -*- coding: utf-8 -*-
"""Previz on the 3D director desk: a blockout read off a reference image, sensor sizes, block tracks on the timeline."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import drama_api
from app.api.auth_api import auth_service, get_current_user
from app.core import studio_canvas
from app.core.spatial_stage import SceneBrief, ShotSpec, blockout, build_plan
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import MAX_LANDMARKS, ActionClip, FollowClip, ShotTimeline, StagePlan
from app.core.spatial_stage.operations import OPERATIONS, StageEditError, apply_operations
from app.core.spatial_stage.prompting import prompt_landmarks
from app.repository.task_repo import TaskRepository
from app.service import director_desk_service as desk
from app.service.drama_service import DramaService
from main import app


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), "gray").save(buffer, format="PNG")
    return buffer.getvalue()


def _plan() -> StagePlan:
    return build_plan(
        SceneBrief(scene_id="S01", location="庭院", characters=["林晚", "陆沉"], shots=[
            ShotSpec(shot_id=1, subjects=["林晚", "陆沉"], speaker="林晚", size="中景", angle="平视", motion="固定", desc="两人对话"),
            ShotSpec(shot_id=2, subjects=["林晚"], speaker="林晚", size="近景", angle="平视", motion="固定", desc="林晚回答"),
        ]),
    )


def _piece(name="外墙", **changes):
    return {"name": name, "kind": "architecture", "shape": "box", "center": [1.0, 2.0], "size": [4.0, 0.4, 3.0], **changes}


class ParseBlockoutTests(unittest.TestCase):
    def test_reads_a_reply_inside_a_code_fence(self):
        reply = "```json\n" + json.dumps({
            "summary": "庭院", "extent_m": [20, 16],
            "reference_camera": {"position": [0, 12, 18], "target": [0, 0, 0], "lens_mm": 28},
            "pieces": [_piece()],
        }, ensure_ascii=False) + "\n```"
        parsed = blockout.parse_blockout(reply)
        self.assertEqual(parsed.summary, "庭院")
        self.assertEqual(parsed.extent_m, (20.0, 16.0))
        self.assertEqual(parsed.reference_camera.lens_mm, 28)
        self.assertEqual(parsed.pieces[0].size, (4.0, 0.4, 3.0))

    def test_one_bad_row_costs_that_row(self):
        parsed = blockout.parse_blockout(json.dumps({"pieces": [_piece(), {"name": "没有尺寸", "center": [0, 0]}, _piece("负尺寸", size=[-1, 1, 1])]}, ensure_ascii=False))
        self.assertEqual([piece.name for piece in parsed.pieces], ["外墙"])
        self.assertEqual(parsed.dropped, 2)

    def test_reply_cut_off_at_the_token_limit_keeps_finished_pieces(self):
        whole = json.dumps({"summary": "广场", "pieces": [_piece("甲"), _piece("乙"), _piece("丙")]}, ensure_ascii=False)
        cut = whole[: whole.rindex('"丙"') + 2]
        parsed = blockout.parse_blockout(cut)
        self.assertEqual([piece.name for piece in parsed.pieces], ["甲", "乙"])

    def test_a_quote_or_brace_inside_a_name_does_not_fool_the_salvage(self):
        whole = json.dumps({"pieces": [_piece('门"洞}'), _piece("乙")]}, ensure_ascii=False)
        cut = whole[: whole.rindex('"乙"')]
        parsed = blockout.parse_blockout(cut)
        self.assertEqual([piece.name for piece in parsed.pieces], ['门"洞}'])

    def test_array_rows_expand_along_their_step(self):
        parsed = blockout.parse_blockout(json.dumps({"pieces": [_piece("廊柱", shape="cylinder", center=[0, 0], array={"count": 4, "dx": 3, "dz": 1})]}, ensure_ascii=False))
        self.assertEqual([piece.name for piece in parsed.pieces], ["廊柱 1", "廊柱 2", "廊柱 3", "廊柱 4"])
        self.assertEqual(parsed.pieces[3].center, (9.0, 3.0))

    def test_repeated_names_are_numbered_not_lost(self):
        parsed = blockout.parse_blockout(json.dumps({"pieces": [_piece("墙"), _piece("墙")]}, ensure_ascii=False))
        self.assertEqual([piece.name for piece in parsed.pieces], ["墙", "墙 2"])

    def test_unusable_replies_are_refused_with_a_reason(self):
        for reply in ("我看不懂这张图", '{"summary": "x"}', '{"pieces": []}', '{"pieces": [{"name": "没有尺寸"}]}'):
            with self.assertRaises(blockout.BlockoutError, msg=reply):
                blockout.parse_blockout(reply)

    def test_a_camera_looking_at_itself_is_dropped_not_fatal(self):
        parsed = blockout.parse_blockout(json.dumps({"reference_camera": {"position": [1, 1, 1], "target": [1, 1, 1]}, "pieces": [_piece()]}, ensure_ascii=False))
        self.assertIsNone(parsed.reference_camera)
        self.assertEqual(len(parsed.pieces), 1)

    def test_size_is_clamped_to_what_a_set_piece_can_be(self):
        parsed = blockout.parse_blockout(json.dumps({"pieces": [_piece(size=[1000, 0.001, 3])]}, ensure_ascii=False))
        self.assertEqual(parsed.pieces[0].size, (200.0, 0.02, 3.0))

    def test_prompt_carries_the_operators_width_and_hint(self):
        _, prompt = blockout.analysis_prompt("俯拍庭院", 24)
        self.assertIn("24", prompt)
        self.assertIn("俯拍庭院", prompt)


class ApplyBlockoutTests(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()

    def test_registered(self):
        self.assertIn("apply_blockout", OPERATIONS)
        self.assertIn("clear_blockout", OPERATIONS)

    def test_pieces_become_ordinary_set_pieces_marked_as_blockout(self):
        plan = apply_operations(self.plan, [{"op": "apply_blockout", "pieces": [_piece(elevation_m=3, yaw_deg=30, color="#112233")]}], solve=False)
        built = next(item for item in plan.landmarks if item.origin == "blockout")
        self.assertEqual((built.name, built.position, built.size, built.elevation_m, built.yaw_deg, built.color), ("外墙", [1.0, 2.0], [4.0, 0.4, 3.0], 3.0, 30.0, "#112233"))

    def test_applying_again_replaces_the_blockout_but_not_hand_placed_pieces(self):
        plan = apply_operations(self.plan, [
            {"op": "add_landmark", "name": "桌子", "position": [0, 0]},
            {"op": "apply_blockout", "pieces": [_piece("旧墙")]},
            {"op": "apply_blockout", "pieces": [_piece("新墙")]},
        ], solve=False)
        names = {item.name for item in plan.landmarks}
        self.assertIn("桌子", names)
        self.assertIn("新墙", names)
        self.assertNotIn("旧墙", names)

    def test_clear_takes_only_the_blockout(self):
        plan = apply_operations(self.plan, [
            {"op": "add_landmark", "name": "桌子", "position": [0, 0]},
            {"op": "apply_blockout", "pieces": [_piece()]},
            {"op": "clear_blockout"},
        ], solve=False)
        self.assertEqual([item.name for item in plan.landmarks if item.origin == "blockout"], [])
        self.assertIn("桌子", {item.name for item in plan.landmarks})

    def test_a_name_already_on_the_stage_is_numbered(self):
        plan = apply_operations(self.plan, [{"op": "apply_blockout", "pieces": [_piece("林晚")]}], solve=False)
        self.assertIn("林晚 2", {item.name for item in plan.landmarks})

    def test_capacity_is_refused_up_front(self):
        pieces = [_piece(f"块{index}") for index in range(MAX_LANDMARKS + 1)]
        with self.assertRaises(StageEditError):
            apply_operations(self.plan, [{"op": "apply_blockout", "pieces": pieces}], solve=False)

    def test_a_bad_submitted_row_refuses_the_whole_operation(self):
        with self.assertRaises(StageEditError) as refused:
            apply_operations(self.plan, [{"op": "apply_blockout", "pieces": [_piece(), {"name": "坏"}]}], solve=False)
        self.assertIn("不合法", str(refused.exception))

    def test_reference_camera_is_a_candidate_and_replaces_the_last_one(self):
        lens = {"position": [0, 10, 14], "target": [0, 0, 0], "lens_mm": 28}
        plan = apply_operations(self.plan, [
            {"op": "apply_blockout", "pieces": [_piece()], "shot_id": 1, "reference_camera": lens},
            {"op": "apply_blockout", "pieces": [_piece()], "shot_id": 1, "reference_camera": {**lens, "lens_mm": 35}},
        ], solve=False)
        references = [camera for camera in plan.cameras if camera.label == blockout.REFERENCE_CAMERA_LABEL]
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0].lens_mm, 35)
        self.assertIn(references[0].id, plan.shot(1).alt_camera_ids)
        self.assertNotEqual(plan.shot(1).camera_id, references[0].id)

    def test_a_big_blockout_does_not_flood_the_prompts(self):
        pieces = [_piece(f"墙段{index}", center=[index * 0.5, 3.0]) for index in range(150)]
        plan = apply_operations(self.plan, [{"op": "apply_blockout", "pieces": pieces}], solve=False)
        self.assertEqual(sum(item.origin == "blockout" for item in prompt_landmarks(plan)), 6)
        # What comes after the set pieces in the bible has to survive its length limit.
        self.assertIn("轴线", plan.scene_bible)
        self.assertLess(len(plan.shots[0].text.blocking), 801)


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()
        self.camera = self.plan.shots[0].camera_id

    def test_field_of_view_follows_the_film_back_equation(self):
        aspect = geo.parse_aspect(self.plan.aspect_ratio)
        self.assertLess(aspect, 1)  # the long side of a vertical frame is its height
        plan = apply_operations(self.plan, [{"op": "move_camera", "camera_id": self.camera, "lens_mm": 50, "sensor_mm": 24.89}], solve=False)
        camera = plan.camera(self.camera)
        self.assertAlmostEqual(camera.fov_deg, math.degrees(2 * math.atan(24.89 / (2 * 50))), places=1)

    def test_a_smaller_sensor_crops_in(self):
        wide = apply_operations(self.plan, [{"op": "move_camera", "camera_id": self.camera, "lens_mm": 35}], solve=False).camera(self.camera)
        tight = apply_operations(self.plan, [{"op": "move_camera", "camera_id": self.camera, "lens_mm": 35, "sensor_mm": 17.3}], solve=False).camera(self.camera)
        self.assertLess(tight.fov_deg, wide.fov_deg)

    def test_prompt_millimetres_are_full_frame_equivalent(self):
        plan = apply_operations(self.plan, [{"op": "move_camera", "camera_id": self.camera, "lens_mm": 35, "sensor_mm": 18}], solve=False)
        self.assertEqual(plan.camera(self.camera).equivalent_lens_mm, 70.0)
        self.assertIn("70mm", plan.shots[0].text.composition)

    def test_re_solving_keeps_the_sensor_and_the_field_of_view(self):
        plan = apply_operations(self.plan, [{"op": "move_camera", "camera_id": self.camera, "sensor_mm": 18}], solve=False)
        solved = apply_operations(plan, [{"op": "solve_camera", "shot_id": 1}], solve=False).camera(self.camera)
        self.assertEqual(solved.sensor_mm, 18)
        self.assertAlmostEqual(solved.fov_deg, geo.vertical_fov(solved.lens_mm, geo.parse_aspect(solved.aspect), 18), delta=1.0)

    def test_old_plans_read_as_full_frame(self):
        stored = self.plan.model_dump(mode="json")
        for camera in stored["cameras"]:
            camera.pop("sensor_mm", None)
        self.assertEqual(StagePlan.model_validate(stored).cameras[0].sensor_mm, 36.0)


class BlockTrackTests(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()

    def _set(self, **fields):
        return apply_operations(self.plan, [{"op": "set_timeline", "shot_id": 1, **fields}], solve=False)

    def test_clips_are_stored(self):
        plan = self._set(clips={"林晚": [{"id": "clip-01", "clip": "human-walk-v1", "start": 0, "end": 2}]})
        self.assertEqual(plan.timelines["1"].clips["林晚"][0].clip, "human-walk-v1")

    def test_an_emptied_track_is_not_kept(self):
        plan = self._set(clips={"林晚": []})
        self.assertNotIn("林晚", plan.timelines["1"].clips)

    def test_overlap_and_overrun_are_refused_in_words(self):
        for clips, needle in (
            ([{"id": "a", "clip": "x", "start": 0, "end": 3}, {"id": "b", "clip": "x", "start": 2, "end": 4}], "不能重叠"),
            ([{"id": "a", "clip": "x", "start": 0, "end": 9}], "片段不能超过时间线时长"),
            ([{"id": "a", "clip": "x", "start": 2, "end": 1}], "晚于"),
        ):
            with self.assertRaises(StageEditError) as refused:
                self._set(clips={"林晚": clips})
            self.assertIn(needle, str(refused.exception))

    def test_touching_blocks_do_not_overlap(self):
        plan = self._set(clips={"林晚": [{"id": "a", "clip": "x", "start": 0, "end": 2}, {"id": "b", "clip": "x", "start": 2, "end": 4}]})
        self.assertEqual(len(plan.timelines["1"].clips["林晚"]), 2)

    def test_a_shorter_shot_cannot_cut_a_block(self):
        plan = self._set(follow=[{"id": "f", "actor": "林晚", "start": 0, "end": 5}])
        with self.assertRaises(StageEditError) as refused:
            apply_operations(plan, [{"op": "set_timeline", "shot_id": 1, "duration_s": 3}], solve=False)
        self.assertIn("跟拍", str(refused.exception))

    def test_blocks_must_name_someone_on_the_stage(self):
        with self.assertRaises(StageEditError):
            self._set(follow=[{"id": "f", "actor": "路人", "start": 0, "end": 1}])
        with self.assertRaises(StageEditError):
            self._set(clips={"路人": [{"id": "a", "clip": "x", "start": 0, "end": 1}]})

    def test_old_timelines_read_without_blocks(self):
        timeline = ShotTimeline.model_validate({"duration_s": 5, "fps": 24, "camera": [], "actors": {}})
        self.assertEqual((timeline.clips, timeline.follow), ({}, []))

    def test_clip_models_refuse_a_backwards_block(self):
        with self.assertRaises(ValidationError):
            ActionClip(id="a", clip="x", start=2, end=1)
        with self.assertRaises(ValidationError):
            FollowClip(id="a", actor="林晚", start=2, end=2)

    def test_removing_someone_takes_their_blocks_with_them(self):
        plan = apply_operations(self.plan, [
            {"op": "add_crowd", "label": "路人", "rows": 1, "columns": 2, "center": [8, 8]},
        ], solve=False)
        member = next(actor.name for actor in plan.actors if actor.crowd_id)
        crowd = next(actor.crowd_id for actor in plan.actors if actor.crowd_id)
        plan = apply_operations(plan, [{
            "op": "set_timeline", "shot_id": 1,
            "clips": {member: [{"id": "a", "clip": "x", "start": 0, "end": 1}]},
            "follow": [{"id": "f", "actor": member, "start": 0, "end": 1}],
        }], solve=False)
        plan = apply_operations(plan, [{"op": "remove_crowd", "crowd_id": crowd}], solve=False)
        self.assertEqual(plan.timelines["1"].clips, {})
        self.assertEqual(plan.timelines["1"].follow, [])


class CameraCutTests(unittest.TestCase):
    def setUp(self):
        self.plan = apply_operations(_plan(), [{"op": "add_camera", "shot_id": 1, "label": "反打"}], solve=False)
        self.shot = self.plan.shot(1)
        self.alt = self.shot.alt_camera_ids[0]

    def cuts(self, cuts, plan=None):
        return apply_operations(plan or self.plan, [{"op": "set_timeline", "shot_id": 1, "cuts": cuts}], solve=False)

    def test_a_cut_to_a_candidate_is_stored(self):
        plan = self.cuts([{"id": "cut-01", "camera_id": self.alt, "start": 1, "end": 3}])
        self.assertEqual(plan.timelines["1"].cuts[0].camera_id, self.alt)

    def test_a_cut_may_also_go_back_to_the_shots_own_lens(self):
        plan = self.cuts([{"id": "a", "camera_id": self.alt, "start": 0, "end": 2}, {"id": "b", "camera_id": self.shot.camera_id, "start": 2, "end": 3}])
        self.assertEqual(len(plan.timelines["1"].cuts), 2)

    def test_a_lens_of_another_shot_is_refused_in_words(self):
        other = self.plan.shot(2).camera_id
        with self.assertRaises(StageEditError) as refused:
            self.cuts([{"id": "a", "camera_id": other, "start": 0, "end": 1}])
        self.assertIn("候选机位", str(refused.exception))

    def test_overlap_and_overrun_are_refused(self):
        with self.assertRaises(StageEditError):
            self.cuts([{"id": "a", "camera_id": self.alt, "start": 0, "end": 3}, {"id": "b", "camera_id": self.alt, "start": 2, "end": 4}])
        with self.assertRaises(StageEditError) as refused:
            self.cuts([{"id": "a", "camera_id": self.alt, "start": 0, "end": 9}])
        self.assertIn("切机位", str(refused.exception))

    def test_removing_the_lens_takes_its_cuts_with_it(self):
        plan = self.cuts([{"id": "a", "camera_id": self.alt, "start": 0, "end": 2}])
        plan = apply_operations(plan, [{"op": "remove_camera", "camera_id": self.alt}], solve=False)
        self.assertEqual(plan.timelines["1"].cuts, [])

    def test_promoting_the_candidate_keeps_the_cuts_valid(self):
        plan = self.cuts([{"id": "a", "camera_id": self.alt, "start": 0, "end": 2}])
        plan = apply_operations(plan, [{"op": "use_camera", "shot_id": 1, "camera_id": self.alt}], solve=False)
        self.assertEqual(plan.shot(1).camera_id, self.alt)
        self.assertEqual(plan.timelines["1"].cuts[0].camera_id, self.alt)

    def test_old_timelines_read_without_cuts(self):
        self.assertEqual(ShotTimeline.model_validate({"duration_s": 5, "fps": 24, "camera": [], "actors": {}}).cuts, [])


class PacedPathTests(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()

    def test_speed_sets_how_long_the_walk_takes(self):
        plan = apply_operations(self.plan, [{
            "op": "set_path", "shot_id": 1, "target": "林晚", "points": [[0, 0], [2.8, 0]], "speed_mps": 1.4, "clip": "human-walk-v1",
        }], solve=False)
        timeline = plan.timelines["1"]
        self.assertAlmostEqual(timeline.actors["林晚"][-1].time, 2.0, places=2)
        clip = timeline.clips["林晚"][0]
        self.assertEqual((clip.clip, clip.start, clip.end), ("human-walk-v1", 0.0, 2.0))

    def test_a_long_route_lengthens_the_shot(self):
        plan = apply_operations(self.plan, [{"op": "set_path", "shot_id": 1, "target": "林晚", "points": [[0, 0], [14, 0]], "speed_mps": 1.4}], solve=False)
        self.assertAlmostEqual(plan.timelines["1"].duration_s, 10.0, places=2)

    def test_a_route_longer_than_any_shot_is_refused_in_words(self):
        with self.assertRaises(StageEditError) as refused:
            apply_operations(self.plan, [{"op": "set_path", "shot_id": 1, "target": "林晚", "points": [[0, 0], [100, 0]], "speed_mps": 1}], solve=False)
        self.assertIn("超过了 30 秒", str(refused.exception))

    def test_the_motion_replaces_what_was_on_that_stretch_only(self):
        plan = apply_operations(self.plan, [{"op": "set_timeline", "shot_id": 1, "duration_s": 10, "clips": {"林晚": [
            {"id": "clip-01", "clip": "human-talk-v1", "start": 0, "end": 1},
            {"id": "clip-02", "clip": "human-idle-v1", "start": 6, "end": 8},
        ]}}], solve=False)
        plan = apply_operations(plan, [{
            "op": "set_path", "shot_id": 1, "target": "林晚", "points": [[0, 0], [2.8, 0]], "start_s": 1, "speed_mps": 1.4, "clip": "human-walk-v1",
        }], solve=False)
        self.assertEqual([clip.clip for clip in plan.timelines["1"].clips["林晚"]], ["human-talk-v1", "human-walk-v1", "human-idle-v1"])


class ControlFrameTests(unittest.TestCase):
    def setUp(self):
        self.task = {"assets": {"4": [{"shot_id": 1, "scene_id": "S01", "desc": "x"}]}}

    def upload(self, **changes):
        fields = {"content": b"", "kind": "still", "shot_id": 1, "camera_id": "c", "width": 10, "height": 10, "layer": "", **changes}
        return desk.CaptureUpload(**fields)

    def test_a_mask_is_kept_but_cannot_become_a_first_frame(self):
        capture = desk.add_capture(self.task, "S01", self.upload(layer="mask"), "/media/a.png")
        self.assertEqual(capture["layer"], "mask")
        with self.assertRaises(desk.CaptureError) as refused:
            desk.apply_capture(self.task, "S01", capture["id"])
        self.assertIn("遮罩", str(refused.exception))

    def test_an_empty_set_can(self):
        capture = desk.add_capture(self.task, "S01", self.upload(layer="background"), "/media/b.png")
        desk.apply_capture(self.task, "S01", capture["id"])
        self.assertIn("/media/b.png", self.task["assets"]["4"][0]["sequence_images"])

    def test_nonsense_is_refused_before_it_is_stored(self):
        png = _png_bytes()
        for changes, needle in (({"layer": "xray"}, "控制帧类型"), ({"layer": "mask", "kind": "clip"}, "只能是静帧"), ({"layer": "mask", "depth": True}, "不能同时")):
            with self.assertRaises(desk.CaptureError) as refused:
                desk.validate_upload(self.upload(content=png, **changes))
            self.assertIn(needle, str(refused.exception))

    def test_a_mask_reaching_a_canvas_node_is_refused_in_words(self):
        resolved = studio_canvas.Inputs()
        studio_canvas._take_capture(resolved, {"kind": "still", "layer": "mask", "url": "/media/a.png"}, "s", {"kind": "image_gen"})
        self.assertIn("遮罩", resolved.problems[0])
        self.assertEqual(resolved.ref_images, [])


class BlockoutEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.task_id = "task-previz"
        self.service.repo.save_task(self.task_id, {"task_id": self.task_id, "user_id": "u-1", "assets": {}, "config": {}})
        patcher = patch.object(drama_api, "service", self.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        app.dependency_overrides[drama_api.require_owned_drama_task] = lambda: {"user_id": "u-1", "role": "user"}
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-1", "role": "user"}
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app, cookies={"auth_token": auth_service.generate_token("u-1")})

    def _post(self, content=b"", filename="ref.png", content_type="image/png"):
        return self.client.post(
            f"/api/drama/{self.task_id}/director-desk/scenes/S01/blockout/analyze",
            files={"file": (filename, content, content_type)}, data={"hint": "庭院"},
        )

    def _png(self):
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (32, 24), "gray").save(buffer, format="PNG")
        return buffer.getvalue()

    def test_a_scene_that_does_not_exist_is_a_404_not_a_model_call(self):
        with patch.object(self.service.gateway, "describe_image") as call:
            response = self._post(self._png())
        self.assertEqual(response.status_code, 404)
        call.assert_not_called()

    def test_the_proposal_comes_back_and_nothing_is_stored(self):
        reply = json.dumps({"summary": "庭院", "pieces": [_piece()]}, ensure_ascii=False)
        before = self.service.repo.get_task(self.task_id)
        with patch("app.service.spatial_stage_service.scene_record", return_value={"scene_id": "S01"}), \
             patch.object(self.service.gateway, "describe_image", return_value=(reply, "vision-1")) as call:
            response = self._post(self._png())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["model"], "vision-1")
        self.assertEqual(body["pieces"][0]["name"], "外墙")
        self.assertEqual(call.call_args.kwargs["max_tokens"], blockout.BLOCKOUT_MAX_TOKENS)
        self.assertEqual(self.service.repo.get_task(self.task_id).get("assets"), before.get("assets"))

    def test_no_vision_model_is_a_readable_422(self):
        with patch("app.service.spatial_stage_service.scene_record", return_value={"scene_id": "S01"}), \
             patch.object(self.service.gateway, "describe_image", return_value=(None, "")):
            response = self._post(self._png())
        self.assertEqual(response.status_code, 422)
        self.assertIn("多模态", response.json()["detail"])

    def test_something_that_is_not_a_picture_is_a_422(self):
        with patch("app.service.spatial_stage_service.scene_record", return_value={"scene_id": "S01"}):
            response = self._post(b"not an image", "ref.png", "image/png")
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

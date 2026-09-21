# -*- coding: utf-8 -*-
"""The 3D director desk's backend: the additive stage model, the desk operations, camera move
presets, desk interchange, and the capture hand-off to stage 5.

Geometry is asserted against calculations written out here, not against the code under test.
"""

import math
import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import drama_api
from app.api.auth_api import auth_service, get_current_user
from app.core import media_compositor
from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan, camera_moves, crowds, interchange
from app.core.spatial_stage import axis as axis_rules
from app.core.spatial_stage.models import (
    ActorKey,
    CameraKey,
    ShotTimeline,
    StageActor,
    StagePlan,
    StagePose,
)
from app.core.spatial_stage.operations import OPERATIONS, StageEditError, apply_operations
from app.core.spatial_stage.planner import refresh
from app.core.spatial_stage.projection import SHOT_SIZE_HEIGHTS, posture_height, screen_states
from app.core.spatial_stage.prompting import without_camera_pose
from app.repository.task_repo import TaskRepository
from app.service import director_desk_service as desk
from app.service import spatial_stage_service as spatial_stage
from app.service.drama_service import DramaService
from main import app

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x40\x00\x00\x00WEBPVP8 " + b"\x00" * 64
WEBM = b"\x1a\x45\xdf\xa3\x9fB\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x84webm" + b"\x00" * 64


def _mp4(seconds: float, timescale: int = 1000) -> bytes:
    ftyp = struct.pack(">I4s4sI4s", 20, b"ftyp", b"isom", 0x200, b"isom")
    mvhd_body = struct.pack(">IIIII", 0, 0, 0, timescale, int(seconds * timescale)) + b"\x00" * 80
    mvhd = struct.pack(">I4s", 8 + len(mvhd_body), b"mvhd") + mvhd_body
    return ftyp + struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd


def _brief() -> SceneBrief:
    return SceneBrief(
        scene_id="E1S02", location="文思阁 / 夜 / 内景",
        text="沈砚与黄琰隔着书案对峙，内侍站在后面。炭盆里烧着黄绫。",
        characters=["沈砚", "黄琰", "内侍"], props=["黄绫", "炭盆"],
        shots=[
            ShotSpec(1, ["沈砚", "黄琰", "内侍"], "", "全景", "平视", "固定", "三人在文思阁内"),
            ShotSpec(2, ["沈砚"], "沈砚", "近景", "过肩", "固定", "沈砚盯着对面"),
            ShotSpec(3, ["黄琰"], "黄琰", "近景", "过肩", "缓推", "黄琰抬头"),
            ShotSpec(4, ["沈砚"], "黄琰", "特写", "平视", "固定", "沈砚咬牙"),
            ShotSpec(5, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "两人对视"),
        ],
    )


def _rejects(test: unittest.TestCase, plan: StagePlan, operation: dict, *needles: str) -> None:
    with test.assertRaises(StageEditError, msg=operation) as raised:
        apply_operations(plan, [operation])
    for needle in needles:
        test.assertIn(needle, str(raised.exception))


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())

    def test_a_plan_stored_before_the_desk_existed_loads_unchanged(self):
        stored = self.plan.model_dump(mode="json")
        for key in ("timelines", "crowds"):
            stored.pop(key)
        for actor in stored["actors"]:
            for key in ("figure", "body_type", "color", "crowd_id", "pose"):
                actor.pop(key)
        for landmark in stored["landmarks"]:
            for key in ("yaw_deg", "shape", "color", "element_id"):
                landmark.pop(key)
        for shot in stored["shots"]:
            shot.pop("alt_camera_ids")
            for change in shot["overrides"]:
                change.pop("pose")

        loaded = StagePlan.model_validate(stored)

        self.assertEqual(loaded.version, 1)
        self.assertEqual(loaded.actors[0].figure, "standin")
        self.assertEqual((loaded.landmarks[0].shape, loaded.landmarks[0].yaw_deg), ("box", 0.0))
        self.assertEqual((loaded.timelines, loaded.shots[0].alt_camera_ids), ({}, []))

    def test_a_pose_holds_at_most_120_joints_within_half_a_turn(self):
        StagePose(joints={"spine.x": 180, "armL.z": -180})
        with self.assertRaises(ValidationError):
            StagePose(joints={"spine.x": 180.5})
        with self.assertRaises(ValidationError):
            StagePose(joints={f"j{index}": 1.0 for index in range(121)})
        with self.assertRaises(ValidationError):
            StagePose(joints={"9 bad key": 1.0})
        with self.assertRaises(ValidationError):
            StagePose(clip_phase=1.2)

    def test_timeline_keys_increase_strictly_and_stay_inside_the_duration(self):
        def key(time: float) -> dict:
            return {"time": time, "position": [0, 1.5, 4], "target": [0, 1.2, 0]}

        ShotTimeline(duration_s=4, camera=[key(0), key(2), key(4)], actors={"沈砚": [{"time": 1, "yaw_deg": 30}]})
        for bad in (
            {"camera": [key(0), key(2), key(2)]},
            {"camera": [key(2), key(1)]},
            {"duration_s": 3, "camera": [key(0), key(3.5)]},
            {"actors": {"沈砚": [{"time": 2, "yaw_deg": 1}, {"time": 1, "yaw_deg": 2}]}},
            {"actors": {"沈砚": [{"time": 9, "position": [0, 0]}]}},
            {"camera": [key(index * 0.01) for index in range(121)]},
            {"fps": 60},
            {"duration_s": 31},
            {"duration_s": 0.5},
        ):
            with self.assertRaises(ValidationError, msg=bad):
                ShotTimeline(**bad)
        with self.assertRaises(ValidationError):
            CameraKey(time=0, position=[1, 1, 1], target=[1, 1, 1])
        with self.assertRaises(ValidationError):
            ActorKey(time=0)
        with self.assertRaises(ValidationError):
            CameraKey(time=0, position=[0, 1, 4], target=[0, 1, 0], easing="bounce")

    def test_candidate_lenses_and_timelines_must_point_at_things_on_the_stage(self):
        raw = self.plan.model_dump(mode="json")

        def broken(change) -> dict:
            copy = StagePlan.model_validate(raw).model_dump(mode="json")
            change(copy)
            return copy

        for change in (
            lambda plan: plan["shots"][0].update(alt_camera_ids=["cam-99"]),
            lambda plan: plan["shots"][0].update(alt_camera_ids=[plan["shots"][0]["camera_id"]]),
            lambda plan: plan["shots"][0].update(alt_camera_ids=["cam-02", "cam-02"]),
            lambda plan: plan.update(timelines={"77": {"duration_s": 3}}),
            lambda plan: plan["actors"][0].update(crowd_id="crowd-09"),
        ):
            with self.assertRaises(ValidationError):
                StagePlan.model_validate(broken(change))
        StagePlan.model_validate(broken(lambda plan: plan.update(timelines={"2": {"duration_s": 3}})))

    def test_a_pose_preset_that_implies_a_posture_sets_the_height(self):
        actor = StageActor(id="a", name="甲", position=[0, 0], height_m=1.8)

        self.assertAlmostEqual(posture_height(actor), 1.8)
        self.assertAlmostEqual(posture_height(actor.model_copy(update={"pose": StagePose(preset="sit")})), 1.8 * 0.74)
        self.assertAlmostEqual(posture_height(actor.model_copy(update={"pose": StagePose(preset="kneel-one")})), 1.8 * 0.68)
        # A free pose implies nothing: the posture still decides.
        free = actor.model_copy(update={"posture": "crouch", "pose": StagePose(joints={"spine.x": 20})})
        self.assertAlmostEqual(posture_height(free), 1.8 * 0.6)
        self.assertAlmostEqual(posture_height(actor.model_copy(update={"pose": StagePose(preset="wave-hello")})), 1.8)


class LandmarkAndFigureOperationTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())
        self.piece = self.plan.landmarks[0].name

    def test_every_desk_operation_is_registered(self):
        for name in (
            "transform_landmark", "bind_landmark_model", "set_backdrop", "add_crowd", "remove_crowd", "transform_crowd",
            "add_extra", "remove_extra", "set_figure", "set_pose", "add_camera", "remove_camera", "use_camera",
            "frame_shot", "set_timeline", "clear_timeline", "apply_camera_move",
        ):
            self.assertIn(name, OPERATIONS)

    def test_a_landmark_is_transformed_bound_and_added_with_its_shape(self):
        edited = apply_operations(self.plan, [
            {"op": "transform_landmark", "name": self.piece, "position": [1, -2], "size": [2, 0.5, 1.1], "yaw_deg": 270,
             "shape": "cylinder", "color": "#AABBCC", "kind": "furniture"},
            {"op": "bind_landmark_model", "name": self.piece, "element_id": "el_123"},
            {"op": "add_landmark", "name": "屏风", "position": [0, -3], "size": [3, 0.1, 2], "yaw_deg": 15, "shape": "plane", "color": "#112233"},
        ])
        piece = next(item for item in edited.landmarks if item.name == self.piece)
        screen = next(item for item in edited.landmarks if item.name == "屏风")

        self.assertEqual((piece.position, piece.size, piece.yaw_deg), ([1.0, -2.0], [2.0, 0.5, 1.1], -90.0))
        self.assertEqual((piece.shape, piece.color, piece.kind, piece.element_id), ("cylinder", "#aabbcc", "furniture", "el_123"))
        self.assertEqual((screen.size, screen.yaw_deg, screen.shape, screen.color), ([3.0, 0.1, 2.0], 15.0, "plane", "#112233"))
        unbound = apply_operations(edited, [{"op": "bind_landmark_model", "name": self.piece, "element_id": ""}])
        self.assertEqual(next(item for item in unbound.landmarks if item.name == self.piece).element_id, "")
        self.assertEqual(edited.revision, self.plan.revision + 1)

    def test_landmark_operations_refuse_bad_values(self):
        _rejects(self, self.plan, {"op": "transform_landmark", "name": "不存在", "yaw_deg": 1}, "不存在")
        _rejects(self, self.plan, {"op": "transform_landmark", "name": self.piece}, "需要")
        _rejects(self, self.plan, {"op": "transform_landmark", "name": self.piece, "shape": "torus"}, "shape")
        _rejects(self, self.plan, {"op": "transform_landmark", "name": self.piece, "color": "red"}, "#rrggbb")
        _rejects(self, self.plan, {"op": "transform_landmark", "name": self.piece, "size": [1, 1]}, "size")
        _rejects(self, self.plan, {"op": "transform_landmark", "name": self.piece, "size": [1, 1, 0]}, "size")
        _rejects(self, self.plan, {"op": "transform_landmark", "name": self.piece, "kind": "vehicle"}, "kind")
        _rejects(self, self.plan, {"op": "transform_landmark", "name": self.piece, "yaw_deg": 999}, "yaw_deg")
        _rejects(self, self.plan, {"op": "bind_landmark_model", "name": "不存在", "element_id": "x"}, "不存在")
        _rejects(self, self.plan, {"op": "bind_landmark_model", "name": self.piece, "element_id": "x" * 121}, "element_id")
        _rejects(self, self.plan, {"op": "add_landmark", "name": "屏风", "shape": "torus"}, "shape")

    def test_figures_extras_and_poses(self):
        edited = apply_operations(self.plan, [
            {"op": "set_figure", "name": "沈砚", "figure": "mannequin", "body_type": "broad", "color": "#336699"},
            {"op": "add_extra", "name": "茶童", "position": [2, -1], "yaw_deg": 90, "figure": "humanoid"},
            {"op": "set_pose", "name": "沈砚", "preset": "sit", "joints": {"spine.x": 12.5, "armL.z": -40}},
            {"op": "set_pose", "name": "黄琰", "shot_id": 3, "clip": "idle", "clip_phase": 0.25},
        ])
        shen, boy = edited.actor("沈砚"), edited.actor("茶童")

        self.assertEqual((shen.figure, shen.body_type, shen.color), ("mannequin", "broad", "#336699"))
        self.assertEqual((boy.id, boy.role, boy.figure, boy.position), ("extra-01", "supporting", "humanoid", [2.0, -1.0]))
        self.assertEqual(shen.pose, StagePose(preset="sit", joints={"spine.x": 12.5, "armL.z": -40.0}))
        self.assertIsNone(edited.actor("黄琰").pose)
        change = next(item for item in edited.shot(3).overrides if item.name == "黄琰")
        self.assertEqual(change.pose, StagePose(clip="idle", clip_phase=0.25))
        self.assertEqual(next(a for a in edited.actors_in(edited.shot(3)) if a.name == "黄琰").pose.clip, "idle")
        self.assertIsNone(next(a for a in edited.actors_in(edited.shot(4)) if a.name == "黄琰").pose)
        # The seated figure is measured seated.
        self.assertLess(
            next(s for s in edited.shot(1).screen if s.name == "沈砚").height_fraction,
            next(s for s in self.plan.shot(1).screen if s.name == "沈砚").height_fraction,
        )

        # Restaging keeps the per-shot pose; an empty set_pose takes a pose off; an empty override disappears.
        restaged = apply_operations(edited, [{"op": "set_shot_override", "shot_id": 3, "name": "黄琰", "posture": "sit"}])
        self.assertEqual(next(i for i in restaged.shot(3).overrides if i.name == "黄琰").pose.clip, "idle")
        cleared = apply_operations(edited, [{"op": "set_pose", "name": "沈砚"}, {"op": "set_pose", "name": "黄琰", "shot_id": 3}])
        self.assertIsNone(cleared.actor("沈砚").pose)
        self.assertFalse([item for item in cleared.shot(3).overrides if item.name == "黄琰"])

        gone = apply_operations(edited, [
            {"op": "set_timeline", "shot_id": 1, "actors": {"茶童": [{"time": 0, "position": [2, -1]}]}},
            {"op": "remove_extra", "name": "茶童"},
        ])
        self.assertIsNone(gone.actor("茶童"))
        self.assertEqual(gone.timelines["1"].actors, {})

    def test_figure_extra_and_pose_operations_refuse_bad_values(self):
        _rejects(self, self.plan, {"op": "set_figure", "name": "沈砚"}, "需要")
        _rejects(self, self.plan, {"op": "set_figure", "name": "沈砚", "figure": "robot"}, "figure")
        _rejects(self, self.plan, {"op": "set_figure", "name": "沈砚", "color": "#12"}, "#rrggbb")
        _rejects(self, self.plan, {"op": "set_figure", "name": "无名氏", "figure": "standin"}, "无名氏")
        _rejects(self, self.plan, {"op": "set_figure", "crowd_id": "crowd-01", "figure": "standin"}, "crowd-01")
        _rejects(self, self.plan, {"op": "add_extra", "name": "沈砚"}, "已有")
        _rejects(self, self.plan, {"op": "add_extra", "name": ""}, "name")
        _rejects(self, self.plan, {"op": "add_extra", "name": "茶童", "posture": "flying"})
        _rejects(self, self.plan, {"op": "remove_extra", "name": "沈砚"}, "剧本里的人物")
        _rejects(self, self.plan, {"op": "remove_extra", "name": "无名氏"}, "无名氏")
        _rejects(self, self.plan, {"op": "set_pose", "name": "沈砚", "joints": {"spine.x": 181}}, "spine.x")
        _rejects(self, self.plan, {"op": "set_pose", "name": "沈砚", "joints": {"9x": 1}}, "关节名")
        _rejects(self, self.plan, {"op": "set_pose", "name": "沈砚", "joints": [1, 2]}, "joints")
        _rejects(self, self.plan, {"op": "set_pose", "name": "沈砚", "joints": {f"j{i}": 1 for i in range(121)}}, "120")
        _rejects(self, self.plan, {"op": "set_pose", "name": "沈砚", "preset": "sit", "clip_phase": 2}, "clip_phase")
        _rejects(self, self.plan, {"op": "set_pose", "name": "沈砚", "preset": "sit", "shot_id": 99}, "99")
        _rejects(self, self.plan, {"op": "set_pose", "name": "无名氏", "preset": "sit"}, "无名氏")


class BackdropTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())

    def test_a_stage_starts_without_a_backdrop_and_takes_one_field_at_a_time(self):
        self.assertEqual(
            self.plan.backdrop.model_dump(),
            {"kind": "none", "color": "", "url": "", "yaw_deg": 0.0, "opacity": 1.0},
        )
        coloured = apply_operations(self.plan, [{"op": "set_backdrop", "kind": "color", "color": "#101820"}])
        self.assertEqual((coloured.backdrop.kind, coloured.backdrop.color), ("color", "#101820"))

        panorama = apply_operations(coloured, [
            {"op": "set_backdrop", "kind": "panorama", "url": "https://cdn.test/media/desk_x.png", "yaw_deg": -330, "opacity": 0.4},
        ])
        self.assertEqual(
            (panorama.backdrop.kind, panorama.backdrop.url, panorama.backdrop.yaw_deg, panorama.backdrop.opacity),
            ("panorama", "https://cdn.test/media/desk_x.png", 30.0, 0.4),
        )
        # The colour is kept while another kind is showing, so switching back needs no re-pick.
        self.assertEqual(panorama.backdrop.color, "#101820")
        off = apply_operations(panorama, [{"op": "set_backdrop", "kind": "none"}])
        self.assertEqual((off.backdrop.kind, off.backdrop.url), ("none", "https://cdn.test/media/desk_x.png"))

    def test_the_backdrop_refuses_what_it_cannot_draw(self):
        _rejects(self, self.plan, {"op": "set_backdrop"}, "需要")
        _rejects(self, self.plan, {"op": "set_backdrop", "kind": "video"}, "kind")
        _rejects(self, self.plan, {"op": "set_backdrop", "kind": "image"}, "url")
        _rejects(self, self.plan, {"op": "set_backdrop", "url": "javascript:alert(1)"}, "http(s)")
        _rejects(self, self.plan, {"op": "set_backdrop", "url": "/media/relative.png"}, "http(s)")
        _rejects(self, self.plan, {"op": "set_backdrop", "opacity": 2}, "opacity")
        _rejects(self, self.plan, {"op": "set_backdrop", "color": "blue"}, "#rrggbb")
        with self.assertRaises(ValidationError):
            StagePlan.model_validate({**self.plan.model_dump(), "backdrop": {"kind": "image", "url": "ftp://x/y.png"}})

    def test_a_re_plan_keeps_the_backdrop_and_the_crowd_its_members_belong_to(self):
        edited = apply_operations(self.plan, [
            {"op": "add_crowd", "label": "旁观", "rows": 1, "columns": 3, "spacing": 1.0, "center": [4, 4]},
            {"op": "set_backdrop", "kind": "image", "url": "https://cdn.test/media/desk_bg.png", "opacity": 0.5},
        ])
        again = build_plan(_brief(), blocking_from=edited)

        self.assertEqual([crowd.label for crowd in again.crowds], ["旁观"])
        self.assertEqual(len([actor for actor in again.actors if actor.crowd_id]), 3)
        self.assertEqual((again.backdrop.kind, again.backdrop.opacity), ("image", 0.5))


class CrowdTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())
        self.op = {"op": "add_crowd", "label": "禁军", "rows": 3, "columns": 4, "spacing": 1.5, "center": [0, -6], "yaw_deg": 0, "body_type": "broad", "seed": 42}

    def test_a_crowd_is_a_centred_grid_with_repeatable_variation(self):
        first, again = apply_operations(self.plan, [self.op]), apply_operations(self.plan, [self.op])
        other = apply_operations(self.plan, [{**self.op, "seed": 43}])
        members = [actor for actor in first.actors if actor.crowd_id]

        self.assertEqual([actor.name for actor in members], [f"禁军-{index:02d}" for index in range(1, 13)])
        self.assertEqual({(actor.role, actor.crowd_id, actor.body_type, actor.figure) for actor in members}, {("crowd", "crowd-01", "broad", "standin")})
        self.assertEqual([a.model_dump() for a in members], [a.model_dump() for a in again.actors if a.crowd_id])
        self.assertNotEqual([a.position for a in members], [a.position for a in other.actors if a.crowd_id])
        self.assertEqual(first.crowds[0].model_dump(), {
            "id": "crowd-01", "label": "禁军", "rows": 3, "columns": 4, "spacing": 1.5, "center": [0.0, -6.0],
            "yaw_deg": 0.0, "body_type": "broad", "seed": 42,
        })
        # Facing +Z: columns run along the array's right (-X … +X is right-to-left here, right = (-1, 0)),
        # rows go back along -Z; every member is within the jitter of its grid cell.
        for index, actor in enumerate(members):
            row, column = divmod(index, 4)
            cell = (-(column - 1.5) * 1.5, -6 - (row - 1) * 1.5)
            self.assertLessEqual(abs(actor.position[0] - cell[0]), 0.18 * 1.5 + 1e-6)
            self.assertLessEqual(abs(actor.position[1] - cell[1]), 0.18 * 1.5 + 1e-6)
            self.assertLessEqual(abs(actor.yaw_deg), 12.0)
            self.assertLessEqual(abs(actor.height_m - 1.7), 1.7 * 0.04 + 1e-3)
        self.assertGreater(len({actor.yaw_deg for actor in members}), 6)

    def test_the_generator_is_the_browsers_mulberry32(self):
        draw = crowds.mulberry32(1)
        self.assertAlmostEqual(draw(), 0.6270739405881613, places=15)
        self.assertAlmostEqual(draw(), 0.002735721180215478, places=15)

    def test_a_crowd_moves_turns_and_respaces_as_one_piece_and_leaves_as_one(self):
        placed = apply_operations(self.plan, [self.op, {"op": "move_actor", "name": "禁军-01", "position": [9, -9]}])
        moved = apply_operations(placed, [{"op": "transform_crowd", "crowd_id": "crowd-01", "center": [4, -6], "yaw_deg": 90, "spacing": 3.0}])

        for before, after in zip((a for a in placed.actors if a.crowd_id), (a for a in moved.actors if a.crowd_id)):
            dx, dz = (before.position[0] - 0) * 2, (before.position[1] + 6) * 2
            # +90° of yaw takes (x, z) to (z, -x).
            self.assertAlmostEqual(after.position[0], 4 + dz, places=2)
            self.assertAlmostEqual(after.position[1], -6 - dx, places=2)
            self.assertAlmostEqual(math.sin(math.radians(after.yaw_deg - before.yaw_deg - 90)), 0, places=4)
        self.assertEqual((moved.crowds[0].center, moved.crowds[0].yaw_deg, moved.crowds[0].spacing), ([4.0, -6.0], 90.0, 3.0))

        tinted = apply_operations(placed, [{"op": "set_figure", "crowd_id": "crowd-01", "color": "#445566", "body_type": "slim"}])
        self.assertEqual({(a.color, a.body_type) for a in tinted.actors if a.crowd_id}, {("#445566", "slim")})
        self.assertEqual(tinted.crowds[0].body_type, "slim")

        staged = apply_operations(placed, [{"op": "set_shot_override", "shot_id": 1, "name": "禁军-02", "posture": "kneel"}])
        emptied = apply_operations(staged, [{"op": "remove_crowd", "crowd_id": "crowd-01"}])
        self.assertEqual([a.name for a in emptied.actors], ["沈砚", "黄琰", "内侍"])
        self.assertEqual((emptied.crowds, emptied.shot(1).overrides), ([], self.plan.shot(1).overrides))

    def test_crowd_operations_refuse_bad_values_and_respect_the_caps(self):
        _rejects(self, self.plan, {**self.op, "label": ""}, "label")
        _rejects(self, self.plan, {**self.op, "rows": 0}, "rows")
        _rejects(self, self.plan, {**self.op, "columns": 2.5}, "整数")
        _rejects(self, self.plan, {**self.op, "rows": 20, "columns": 20}, "最多 150 人")
        _rejects(self, self.plan, {**self.op, "spacing": 0.1}, "spacing")
        _rejects(self, self.plan, {**self.op, "seed": -1}, "seed")
        _rejects(self, self.plan, {**self.op, "center": [0]}, "center")
        _rejects(self, self.plan, {"op": "remove_crowd", "crowd_id": "crowd-07"}, "crowd-07")
        _rejects(self, self.plan, {"op": "transform_crowd", "crowd_id": "crowd-07", "yaw_deg": 1}, "crowd-07")
        placed = apply_operations(self.plan, [self.op])
        _rejects(self, placed, self.op, "已有名为")
        _rejects(self, placed, {"op": "transform_crowd", "crowd_id": "crowd-01"}, "需要")
        named = apply_operations(self.plan, [{"op": "add_extra", "name": "卫兵-01"}])
        _rejects(self, named, {**self.op, "label": "卫兵"}, "卫兵-01")
        full = apply_operations(self.plan, [{**self.op, "rows": 10, "columns": 15}])
        _rejects(self, full, {**self.op, "label": "宫女", "rows": 6, "columns": 8}, "不能超过 200")

    def test_a_full_stage_stays_fast_and_its_crowd_is_never_checked_for_cover(self):
        import time

        full = apply_operations(self.plan, [
            {**self.op, "rows": 10, "columns": 15, "spacing": 0.6, "center": [0, -2]},
            {**self.op, "label": "宫女", "rows": 4, "columns": 11, "spacing": 0.6, "center": [0, 1]},
        ])
        self.assertEqual(len(full.actors), 197)
        started = time.perf_counter()
        refreshed = refresh(full)
        self.assertLess(time.perf_counter() - started, 1.5)
        # Members stand shoulder to shoulder and in front of each other: neither is a finding.
        self.assertTrue(next(c for c in refreshed.checks if c.code == "spatial_actor_spacing").passed)
        self.assertFalse(any(state.occluded_by for state in refreshed.shot(1).screen if state.name.startswith(("禁军", "宫女"))))
        self.assertEqual(len(refreshed.shot(1).screen), 197)
        self.assertIn("禁军150人列阵", refreshed.shot(1).text.blocking)
        self.assertNotIn("禁军-01", refreshed.scene_bible)


class CameraOperationTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())

    def test_move_camera_keeps_the_move_unless_told_to_reset_it(self):
        moving = self.plan.camera("cam-03")
        self.assertEqual(moving.move.kind, "push")
        nudged = [moving.position[0], moving.position[1] + 0.2, moving.position[2]]

        kept = apply_operations(self.plan, [{"op": "move_camera", "camera_id": "cam-03", "position": nudged}]).camera("cam-03")
        reset = apply_operations(self.plan, [{"op": "move_camera", "camera_id": "cam-03", "position": nudged, "reset_move": True}]).camera("cam-03")

        self.assertEqual(kept.move, moving.move)
        self.assertEqual((reset.move.kind, reset.move.end_position), ("static", None))

    def test_solve_false_moves_no_lens_and_solve_true_solves_them_all(self):
        edit = [{"op": "move_actor", "name": "沈砚", "position": [-3.5, 0.4]}]

        held = apply_operations(self.plan, edit, solve=False)
        default = apply_operations(self.plan, edit)
        solved = apply_operations(self.plan, edit, solve=True)

        self.assertEqual([c.model_dump() for c in held.cameras], [c.model_dump() for c in self.plan.cameras])
        self.assertEqual([c.model_dump() for c in default.cameras], [c.model_dump() for c in self.plan.cameras])
        self.assertNotEqual(solved.camera("cam-04").position, self.plan.camera("cam-04").position)
        self.assertEqual(
            [c.model_dump() for c in solved.cameras],
            [c.model_dump() for c in apply_operations(self.plan, [*edit, {"op": "solve_camera"}]).cameras],
        )

    def test_candidate_lenses_are_added_promoted_and_removed(self):
        added = apply_operations(self.plan, [
            {"op": "add_camera", "shot_id": 2},
            {"op": "add_camera", "shot_id": 2, "position": [3, 1.6, 3], "target": [-1, 1.5, 0], "lens_mm": 35, "label": "侧机位"},
        ])
        filming, copy, side = added.camera("cam-02"), added.camera("alt-02-01"), added.camera("alt-02-02")

        self.assertEqual(added.shot(2).alt_camera_ids, ["alt-02-01", "alt-02-02"])
        self.assertEqual((copy.position, copy.target, copy.subjects, copy.move.kind), (filming.position, filming.target, filming.subjects, "static"))
        self.assertEqual((side.position, side.lens_mm, side.label), ([3.0, 1.6, 3.0], 35.0, "侧机位"))
        self.assertEqual(added.shot(2).camera_id, "cam-02")

        keyed = apply_operations(added, [{"op": "apply_camera_move", "shot_id": 2, "preset": "push"}])
        promoted = apply_operations(keyed, [{"op": "use_camera", "shot_id": 2, "camera_id": "alt-02-02"}])
        self.assertEqual((promoted.shot(2).camera_id, promoted.shot(2).alt_camera_ids), ("alt-02-02", ["alt-02-01", "cam-02"]))
        self.assertEqual(promoted.timelines["2"].camera, [])       # the keys belonged to the old lens
        self.assertEqual(promoted.shot(2).text.camera_start, refresh(promoted).shot(2).text.camera_start)

        _rejects(self, promoted, {"op": "remove_camera", "camera_id": "alt-02-02"}, "正在拍摄第 2 镜")
        trimmed = apply_operations(promoted, [{"op": "remove_camera", "camera_id": "cam-02"}])
        self.assertEqual(trimmed.shot(2).alt_camera_ids, ["alt-02-01"])
        self.assertIsNone(trimmed.camera("cam-02"))

    def test_candidate_lens_operations_refuse_bad_values(self):
        _rejects(self, self.plan, {"op": "add_camera", "shot_id": 99}, "99")
        _rejects(self, self.plan, {"op": "add_camera", "shot_id": 2, "position": [0, 1, 0], "target": [0, 1, 0]}, "不能重合")
        _rejects(self, self.plan, {"op": "remove_camera", "camera_id": "cam-77"}, "cam-77")
        _rejects(self, self.plan, {"op": "remove_camera", "camera_id": "cam-01"}, "正在拍摄")
        _rejects(self, self.plan, {"op": "use_camera", "shot_id": 2, "camera_id": "cam-03"}, "不是第 2 镜的候选机位")
        _rejects(self, self.plan, {"op": "use_camera", "shot_id": 2, "camera_id": "nope"}, "nope")
        crowded = apply_operations(self.plan, [{"op": "add_camera", "shot_id": 2}] * 8)
        _rejects(self, crowded, {"op": "add_camera", "shot_id": 2}, "最多 8 个候选机位")

    def test_frame_shot_solves_the_distance_from_the_film_back(self):
        heights = dict(SHOT_SIZE_HEIGHTS)
        for aspect_ratio, size, alias in (("9:16", "全景", "全景"), ("9:16", "中景", "MS"), ("9:16", "近景", "近景"), ("16:9", "特写", "close-up"), ("16:9", "中近景", "中近景")):
            brief = _brief()
            brief.aspect_ratio = aspect_ratio
            plan = build_plan(brief)
            before = plan.camera("cam-04")
            framed = apply_operations(plan, [{"op": "frame_shot", "shot_id": 4, "size": alias}]).camera("cam-04")

            # Independent of the code: a 36 mm long side, so a portrait frame is 36 mm tall and a
            # landscape one 36 / aspect; similar triangles give distance = covered height × focal / sensor height.
            sensor_height = 36.0 if aspect_ratio == "9:16" else 36.0 * 9 / 16
            expected = heights[size] * before.lens_mm / sensor_height
            self.assertAlmostEqual(math.dist(framed.position, framed.target), expected, delta=expected * 0.004 + 0.002)
            look_before = [(before.target[i] - before.position[i]) / math.dist(before.position, before.target) for i in range(3)]
            look_after = [(framed.target[i] - framed.position[i]) / math.dist(framed.position, framed.target) for i in range(3)]
            for a, b in zip(look_before, look_after):
                self.assertAlmostEqual(a, b, places=2)
            self.assertEqual((framed.target, framed.lens_mm, framed.shot_size), (before.target, before.lens_mm, size))

    def test_frame_shot_carries_a_move_and_refuses_what_it_cannot_frame(self):
        before = self.plan.camera("cam-03")
        framed = apply_operations(self.plan, [{"op": "frame_shot", "shot_id": 3, "size": "中景"}]).camera("cam-03")
        shift = [framed.position[i] - before.position[i] for i in range(3)]
        self.assertEqual(framed.move.kind, "push")
        for i in range(3):
            self.assertAlmostEqual(framed.move.end_position[i], before.move.end_position[i] + shift[i], places=2)

        _rejects(self, self.plan, {"op": "frame_shot", "shot_id": 3, "size": "随便"}, "景别")
        _rejects(self, self.plan, {"op": "frame_shot", "shot_id": 3}, "景别")
        _rejects(self, self.plan, {"op": "frame_shot", "shot_id": 42, "size": "中景"}, "42")
        low = apply_operations(self.plan, [{"op": "move_camera", "camera_id": "cam-04", "position": [0.5, 0.3, 1.5], "target": [-1.3, 1.6, 0]}])
        _rejects(self, low, {"op": "frame_shot", "shot_id": 4, "size": "大远景"}, "地面以下")

    def test_timelines_are_set_merged_and_cleared(self):
        camera = self.plan.camera("cam-02")
        keys = [
            {"time": 0, "position": camera.position, "target": camera.target, "lens_mm": 50},
            {"time": 3, "position": [camera.position[0], camera.position[1] + 0.5, camera.position[2]], "target": camera.target, "easing": "smooth"},
        ]
        walk = {"沈砚": [{"time": 0, "position": [-1.3, 0]}, {"time": 3, "position": [-0.8, 0.2], "yaw_deg": 80, "pose": {"preset": "walk"}, "easing": "ease-out"}]}

        timed = apply_operations(self.plan, [{"op": "set_timeline", "shot_id": 2, "duration_s": 4, "fps": 30, "camera": keys, "actors": walk}])
        timeline = timed.timelines["2"]
        self.assertEqual((timeline.duration_s, timeline.fps, len(timeline.camera), timeline.camera[1].easing), (4.0, 30, 2, "smooth"))
        self.assertEqual(timeline.actors["沈砚"][1].pose.preset, "walk")

        longer = apply_operations(timed, [{"op": "set_timeline", "shot_id": 2, "duration_s": 6}])
        self.assertEqual((longer.timelines["2"].duration_s, longer.timelines["2"].fps, len(longer.timelines["2"].camera)), (6.0, 30, 2))
        cleared = apply_operations(longer, [{"op": "clear_timeline", "shot_id": 2}, {"op": "clear_timeline", "shot_id": 3}])
        self.assertEqual(cleared.timelines, {})
        # Stored and loaded like the rest of the plan.
        self.assertEqual(StagePlan.model_validate(timed.model_dump(mode="json")).timelines["2"], timeline)

        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2}, "需要")
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 77, "duration_s": 3}, "77")
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "fps": 60}, "fps")
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "duration_s": 45}, "duration_s")
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "camera": [keys[1], keys[0]]}, "严格递增")
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "duration_s": 2, "camera": keys}, "不能超过时间线时长")
        _rejects(self, timed, {"op": "set_timeline", "shot_id": 2, "duration_s": 2}, "不能超过时间线时长")
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "actors": {"无名氏": [{"time": 0, "yaw_deg": 1}]}}, "无名氏")
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "actors": {"沈砚": [{"time": 0}]}}, "position / yaw_deg / pose")
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "camera": "keys"}, "camera")
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "actors": []}, "actors")
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "camera": [{**keys[0], "target": keys[0]["position"]}]}, "不能重合")
        _rejects(self, self.plan, {"op": "clear_timeline", "shot_id": 77}, "77")

    def test_a_shorter_duration_names_the_key_it_would_cut_off(self):
        walk = {"沈砚": [{"time": 0, "position": [-1.3, 0]}, {"time": 3.5, "position": [-0.8, 0.2]}]}
        timed = apply_operations(self.plan, [{"op": "set_timeline", "shot_id": 2, "duration_s": 4, "actors": walk}])
        _rejects(self, timed, {"op": "set_timeline", "shot_id": 2, "duration_s": 3}, "「沈砚」轨最后一个关键帧在 3.5 秒")
        camera = self.plan.camera("cam-02")
        late = [{"time": 2.5, "position": camera.position, "target": camera.target}]
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "duration_s": 2, "camera": late}, "机位轨最后一个关键帧在 2.5 秒")

    def test_a_whole_pose_key_round_trips(self):
        pose = {"preset": "", "joints": {"leftShoulder.pitch": 42.5, "rightHand.index.curl": 30}, "clip": "human-walk-v1", "clip_phase": 0.25}
        keys = {"沈砚": [{"time": 0, "position": [-1.3, 0], "yaw_deg": 90, "pose": {"preset": "walk"}}, {"time": 2, "pose": pose, "easing": "hold"}]}
        timed = apply_operations(self.plan, [{"op": "set_timeline", "shot_id": 2, "actors": keys}])
        stored = StagePlan.model_validate(timed.model_dump(mode="json")).timelines["2"].actors["沈砚"]
        self.assertEqual(stored[1].pose.model_dump(), pose)
        self.assertEqual((stored[1].position, stored[1].yaw_deg, stored[1].easing), (None, None, "hold"))
        # A later edit of another field leaves the pose keys alone.
        again = apply_operations(timed, [{"op": "set_timeline", "shot_id": 2, "fps": 25}])
        self.assertEqual(again.timelines["2"].actors["沈砚"][1].pose.model_dump(), pose)
        _rejects(self, self.plan, {"op": "set_timeline", "shot_id": 2, "actors": {"沈砚": [{"time": 0, "pose": {"joints": {"leftElbow.bend": 999}}}]}}, "时间线不合法")


class CameraMoveTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())

    def _visible(self, plan: StagePlan, shot_id: int, key: CameraKey) -> bool:
        camera = plan.camera(plan.shot(shot_id).camera_id)
        aspect = 9 / 16
        fov = math.degrees(2 * math.atan(36.0 / (2 * key.lens_mm))) if aspect < 1 else 0
        probe = camera.model_copy(update={"position": key.position, "target": key.target, "fov_deg": fov})
        states = {s.name: s for s in screen_states(plan.actors_in(plan.shot(shot_id)), probe)}
        return all(states[name].visible for name in camera.subjects)

    def test_every_preset_writes_ordinary_keys_that_hold_the_subjects_on_the_cameras_side(self):
        self.assertEqual(len(camera_moves.PRESETS), 14)
        for preset in camera_moves.PRESETS:
            for shot_id in (1, 2, 4, 5):
                moved = apply_operations(self.plan, [{"op": "apply_camera_move", "shot_id": shot_id, "preset": preset, "duration_s": 6}])
                timeline = moved.timelines[str(shot_id)]
                keys = timeline.camera
                label = f"{preset} on shot {shot_id}"

                self.assertGreaterEqual(len(keys), 2, label)
                self.assertEqual((keys[0].time, keys[-1].time, timeline.duration_s), (0.0, 6.0, 6.0), label)
                self.assertTrue(all(b.time > a.time for a, b in zip(keys, keys[1:])), label)
                self.assertEqual({key.easing for key in keys}, {"linear"}, label)   # the easing lives in the times
                self.assertEqual({axis_rules.side_of(moved.axis, (k.position[0], k.position[2])) for k in keys}, {moved.axis.camera_side}, label)
                checked = keys[-1:] if preset == "whip-pan" else keys
                self.assertTrue(all(self._visible(moved, shot_id, key) for key in checked), label)
                # Nothing but the timeline changed: the solved lens is still where it was.
                self.assertEqual(moved.camera(f"cam-{shot_id:02d}"), self.plan.camera(f"cam-{shot_id:02d}"), label)

    def test_each_preset_does_what_its_name_says(self):
        camera = self.plan.camera("cam-04")
        reach = math.dist(camera.position, camera.target)

        def keys(preset: str, **options) -> list[CameraKey]:
            return apply_operations(self.plan, [{"op": "apply_camera_move", "shot_id": 4, "preset": preset, **options}]).timelines["4"].camera

        def reach_of(key: CameraKey) -> float:
            return math.dist(key.position, key.target)

        self.assertLess(reach_of(keys("push")[-1]), reach * 0.9)
        self.assertGreater(reach_of(keys("pull")[-1]), reach * 1.1)
        self.assertGreater(keys("rise")[-1].position[1], camera.position[1] + 0.3)
        self.assertLess(keys("descend")[-1].position[1], camera.position[1])
        self.assertGreater(math.dist(keys("truck")[-1].position, camera.position), 0.1)
        self.assertEqual(keys("truck")[-1].target, camera.target)

        arc = keys("arc", angle=40)
        self.assertEqual(len(arc), camera_moves.ARC_SAMPLES + 1)
        radius = math.hypot(camera.position[0] - camera.target[0], camera.position[2] - camera.target[2])
        for key in arc:
            self.assertAlmostEqual(math.hypot(key.position[0] - key.target[0], key.position[2] - key.target[2]), radius, delta=0.02)
        a = (arc[0].position[0] - camera.target[0], arc[0].position[2] - camera.target[2])
        b = (arc[-1].position[0] - camera.target[0], arc[-1].position[2] - camera.target[2])
        swept = math.degrees(math.acos((a[0] * b[0] + a[1] * b[1]) / (math.hypot(*a) * math.hypot(*b))))
        self.assertAlmostEqual(swept, 40, delta=1.0)
        self.assertLess(reach_of(keys("arc-push")[-1]), reach * 0.85)

        crane = keys("crane-reveal")[-1]
        self.assertTrue(crane.position[1] > camera.position[1] + 0.5 and reach_of(crane) > reach)
        ground = keys("ground-rise")
        self.assertAlmostEqual(ground[0].position[1], 0.3, places=2)
        self.assertEqual(ground[-1].position, camera.position)

        whip = keys("whip-pan")
        self.assertEqual({tuple(key.position) for key in whip}, {tuple(camera.position)})
        self.assertEqual(whip[-1].target, camera.target)
        self.assertGreater(math.dist(whip[0].target, camera.target), 0.5)

        pause = keys("push-pause", duration_s=10)
        self.assertEqual((pause[-2].time, pause[-1].time), (6.0, 10.0))
        self.assertEqual((pause[-2].position, pause[-2].target), (pause[-1].position, pause[-1].target))

        zoom = keys("dolly-zoom")
        for key in zoom:   # subject size ∝ focal / distance stays put while the lens and the distance both change
            self.assertAlmostEqual(key.lens_mm / reach_of(key), camera.lens_mm / reach, delta=camera.lens_mm / reach * 0.02)
        self.assertLess(zoom[-1].lens_mm, camera.lens_mm * 0.8)

        settle = keys("roll-recover")
        self.assertEqual((settle[-1].position, settle[-1].target), (camera.position, camera.target))
        self.assertLess(math.dist(settle[0].position, camera.position), 0.6)
        self.assertGreater(math.dist(settle[0].position, camera.position), 0.01)

        off = apply_operations(self.plan, [{"op": "move_camera", "camera_id": "cam-04", "target": [camera.target[0] + 0.25, camera.target[1], camera.target[2]]}])
        reframed = apply_operations(off, [{"op": "apply_camera_move", "shot_id": 4, "preset": "reframe"}]).timelines["4"].camera
        shen = self.plan.actor("沈砚")
        self.assertAlmostEqual(reframed[-1].target[0], shen.position[0], places=2)
        self.assertAlmostEqual(reframed[-1].target[2], shen.position[1], places=2)
        self.assertEqual({tuple(key.position) for key in reframed}, {tuple(camera.position)})

    def test_easing_redistributes_the_times_and_linear_needs_two_keys(self):
        def keys(easing: str) -> list[CameraKey]:
            return apply_operations(self.plan, [
                {"op": "apply_camera_move", "shot_id": 4, "preset": "push", "easing": easing, "duration_s": 8},
            ]).timelines["4"].camera

        self.assertEqual([key.time for key in keys("linear")], [0.0, 8.0])
        smooth, ease_in, ease_out, whip = keys("smooth"), keys("ease-in"), keys("ease-out"), keys("whip")
        # The samples are evenly spaced along the path, so the time of the middle one is where the move is half done.
        middle = len(smooth) // 2
        self.assertAlmostEqual(smooth[middle].time, 4.0, places=2)
        self.assertAlmostEqual(ease_in[middle].time, 8 * math.sqrt(0.5), places=2)
        self.assertAlmostEqual(ease_out[middle].time, 8 * (1 - math.sqrt(0.5)), places=2)
        # Smoothstep covers 1/8 of the path by t where 3t² − 2t³ = 1/8.
        t = smooth[1].time / 8
        self.assertAlmostEqual(3 * t * t - 2 * t ** 3, 1 / 8, places=3)
        self.assertGreater(whip[1].time, smooth[1].time)             # a whip waits longer, then snaps
        self.assertLess(whip[middle + 1].time - whip[middle].time, smooth[middle + 1].time - smooth[middle].time)
        for a, b in zip(smooth, smooth[1:]):                          # evenly spaced along the path
            self.assertAlmostEqual(math.dist(a.position, b.position), math.dist(smooth[0].position, smooth[1].position), places=2)

    def test_side_amplitude_and_the_axis(self):
        def end(**options) -> CameraKey:
            return apply_operations(self.plan, [{"op": "apply_camera_move", "shot_id": 1, "preset": "truck", **options}]).timelines["1"].camera[-1]

        camera = self.plan.camera("cam-01")
        left, right = end(side="left"), end(side="right")
        self.assertLess(left.position[0], camera.position[0])        # the master looks down -Z: screen left is -X
        self.assertGreater(right.position[0], camera.position[0])
        self.assertLess(math.dist(end(side="right", amplitude=0.3).position, camera.position), math.dist(right.position, camera.position))

        # A half-turn arc would cross the line; it is shortened until it stays on the side it started on.
        wide = apply_operations(self.plan, [{"op": "apply_camera_move", "shot_id": 5, "preset": "arc", "angle": 170, "side": "left"}])
        self.assertEqual({axis_rules.side_of(wide.axis, (k.position[0], k.position[2])) for k in wide.timelines["5"].camera}, {wide.axis.camera_side})

    def test_apply_camera_move_refuses_bad_values(self):
        _rejects(self, self.plan, {"op": "apply_camera_move", "shot_id": 4, "preset": "barrel-roll"}, "preset")
        _rejects(self, self.plan, {"op": "apply_camera_move", "shot_id": 4}, "preset")
        _rejects(self, self.plan, {"op": "apply_camera_move", "shot_id": 99, "preset": "push"}, "99")
        _rejects(self, self.plan, {"op": "apply_camera_move", "shot_id": 4, "preset": "push", "easing": "hold"}, "easing")
        _rejects(self, self.plan, {"op": "apply_camera_move", "shot_id": 4, "preset": "push", "side": "up"}, "side")
        _rejects(self, self.plan, {"op": "apply_camera_move", "shot_id": 4, "preset": "push", "amplitude": 0}, "amplitude")
        _rejects(self, self.plan, {"op": "apply_camera_move", "shot_id": 4, "preset": "arc", "angle": 270}, "angle")
        _rejects(self, self.plan, {"op": "apply_camera_move", "shot_id": 4, "preset": "push", "duration_s": 0.2}, "duration_s")
        self.assertEqual(self.plan.timelines, {})


class InterchangeTests(unittest.TestCase):
    def setUp(self):
        self.plan = apply_operations(build_plan(_brief()), [
            {"op": "transform_landmark", "name": build_plan(_brief()).landmarks[0].name, "yaw_deg": 30, "shape": "cone", "color": "#223344", "size": [1.2, 0.8, 0.5]},
            {"op": "set_figure", "name": "沈砚", "body_type": "heavy", "color": "#aa5500"},
            {"op": "set_pose", "name": "沈砚", "preset": "sit", "joints": {"spine.x": 10, "legL.x": -85}},
            {"op": "add_camera", "shot_id": 2},
        ])
        self.piece = self.plan.landmarks[0]

    def test_a_still_stage_is_a_version_one_project_that_carries_the_desk_fields(self):
        document = interchange.to_director_desk(self.plan)
        shen = next(item for item in document["objects"] if item["name"] == "沈砚")
        prop = next(item for item in document["objects"] if item["name"] == self.piece.name)
        alt = next(item for item in document["cameras"] if item["id"] == "alt-02-01")

        self.assertEqual(document["version"], 1)
        self.assertNotIn("timeline", document)
        self.assertEqual((shen["bodyType"], shen["color"]), ("heavy", "#aa5500"))
        self.assertEqual(shen["characterRig"]["posePresetId"], "sit")
        self.assertEqual(shen["characterRig"]["controls"], {"spine.x": 10.0, "legL.x": -85.0})
        self.assertAlmostEqual(prop["transform"]["rotation"][1], math.radians(30), places=5)
        self.assertEqual((prop["geometryType"], prop["color"], prop["transform"]["scale"]), ("cone", "#223344", [1.2, 0.5, 0.8]))
        self.assertEqual(alt["alternateOfShot"], 2)
        self.assertNotIn("alternateOfShot", next(item for item in document["cameras"] if item["id"] == "cam-02"))
        self.assertEqual(interchange.to_costage(self.plan)["version"], 2)   # CoStage still exports

    def test_an_animated_stage_is_version_two_with_camera_tracks_laid_end_to_end(self):
        animated = apply_operations(self.plan, [
            {"op": "apply_camera_move", "shot_id": 2, "preset": "push", "easing": "linear", "duration_s": 4},
            {"op": "apply_camera_move", "shot_id": 4, "preset": "rise", "easing": "linear", "duration_s": 3},
        ])
        document = interchange.to_director_desk(animated)
        timeline = document["timeline"]

        self.assertEqual(document["version"], 2)
        self.assertEqual((timeline["duration"], timeline["tracks"]), (7.0, []))
        self.assertEqual([track["cameraId"] for track in timeline["cameraTracks"]], ["cam-02", "cam-04"])
        first, second = timeline["cameraTracks"]
        self.assertEqual([key["time"] for key in first["keyframes"]], [0.0, 4.0])
        self.assertEqual([key["time"] for key in second["keyframes"]], [4.0, 7.0])
        self.assertEqual(len({key["id"] for track in timeline["cameraTracks"] for key in track["keyframes"]}), 4)
        key, source = first["keyframes"][0], animated.timelines["2"].camera[0]
        self.assertEqual(set(key["value"]), {"position", "target", "fov"})
        self.assertEqual(key["value"]["target"], source.target)
        # The rig body sits 1.82 m behind the lens, as in the camera records of the same document.
        self.assertAlmostEqual(math.dist(key["value"]["position"], source.position), interchange.DESK_RIG_OFFSET_M, places=3)
        self.assertAlmostEqual(key["value"]["fov"], math.degrees(2 * math.atan(36 / (2 * source.lens_mm))), places=1)
        # A version 2 desk project is read back like a version 1 one.
        self.assertTrue(interchange.import_operations(animated, document))

    def test_a_backdrop_and_an_element_binding_travel_as_notes_and_come_back_as_nothing(self):
        local = apply_operations(self.plan, [
            {"op": "set_backdrop", "kind": "panorama", "url": "https://cdn.test/media/desk_bg.png", "yaw_deg": 25, "opacity": 0.6},
            {"op": "bind_landmark_model", "name": self.piece.name, "element_id": "el_desk_42"},
        ])
        document = interchange.to_director_desk(local)

        self.assertEqual(document["scene"]["panoramaYaw"], 25.0)
        self.assertTrue(any("全景图" in note and "0.6" in note for note in document["notes"]), document["notes"])
        self.assertTrue(any("el_desk_42" in note for note in document["notes"]), document["notes"])
        self.assertTrue(any("el_desk_42" in note for note in interchange.to_costage(local)["notes"]))
        # A flat colour reaches the field the other desk actually reads.
        self.assertEqual(
            interchange.to_director_desk(apply_operations(local, [{"op": "set_backdrop", "kind": "color", "color": "#223344"}]))["scene"]["backgroundColor"],
            "#223344",
        )

        # Reading its own document back changes neither of them, and neither does a foreign one.
        restored = apply_operations(local, interchange.import_operations(local, document))
        self.assertEqual(restored.backdrop, local.backdrop)
        self.assertEqual(restored.landmarks[0].element_id, "el_desk_42")
        foreign = {**document, "scene": {**document["scene"], "backgroundColor": "#ff0000", "panoramaYaw": 180}, "notes": ["别人的说明"]}
        self.assertEqual(apply_operations(local, interchange.import_operations(local, foreign)).backdrop, local.backdrop)

    def test_rotation_scale_and_pose_controls_come_back(self):
        document = interchange.to_director_desk(self.plan)
        for item in document["objects"]:
            if item["name"] == self.piece.name:
                item["transform"]["rotation"] = [0.0, math.radians(-45), 0.0]
                item["transform"]["scale"] = [2.0, 0.9, 1.5]
            if item["name"] == "沈砚":
                item["characterRig"] = {"posePresetId": "kneel-one", "controls": {"spine.x": 25, "armR.z": 60}}

        imported = apply_operations(self.plan, interchange.import_operations(self.plan, document))
        piece = next(item for item in imported.landmarks if item.name == self.piece.name)

        self.assertEqual((piece.yaw_deg, piece.size, piece.shape), (-45.0, [2.0, 1.5, 0.9], "cone"))
        self.assertEqual(imported.actor("沈砚").pose, StagePose(preset="kneel-one", joints={"spine.x": 25.0, "armR.z": 60.0}))
        self.assertIsNone(imported.actor("黄琰").pose)
        self.assertEqual(imported.actor("黄琰").position, self.plan.actor("黄琰").position)

        # A mannequin posed on the desk survives export → import onto a fresh plan, finger keys included.
        joints = {"leftKnee.bend": 86.0, "body.offsetY": 0.12, "rightHand.index.curl": 70.0, "rightHand.thumb.spread": -12.5}
        posed = apply_operations(self.plan, [
            {"op": "set_figure", "name": "黄琰", "figure": "mannequin", "body_type": "slim"},
            {"op": "set_pose", "name": "黄琰", "preset": "kneel-one", "joints": joints},
        ])
        exported = interchange.to_director_desk(posed)
        rig = next(item for item in exported["objects"] if item["name"] == "黄琰")["characterRig"]
        self.assertEqual((rig["posePresetId"], rig["controls"]), ("kneel-one", joints))
        back = apply_operations(self.plan, interchange.import_operations(self.plan, exported))
        self.assertEqual(back.actor("黄琰").pose, StagePose(preset="kneel-one", joints=joints))

        for item in document["objects"]:
            if item["name"] == "沈砚":
                item["characterRig"]["controls"] = {"spine.x": 720}
        with self.assertRaises(StageEditError):
            apply_operations(self.plan, interchange.import_operations(self.plan, document))


class CaptureValidationTests(unittest.TestCase):
    def _upload(self, content: bytes, kind: str = "still", **values) -> desk.CaptureUpload:
        return desk.CaptureUpload(content=content, kind=kind, shot_id=values.pop("shot_id", 1), **values)

    def test_the_bytes_decide_what_a_file_is(self):
        self.assertEqual(desk.sniff_media(PNG), "image/png")
        self.assertEqual(desk.sniff_media(JPEG), "image/jpeg")
        self.assertEqual(desk.sniff_media(WEBP), "image/webp")
        self.assertEqual(desk.sniff_media(_mp4(5)), "video/mp4")
        self.assertEqual(desk.sniff_media(WEBM), "video/webm")
        self.assertIsNone(desk.sniff_media(b"RIFF\x00\x00\x00\x00WAVEfmt "))
        self.assertIsNone(desk.sniff_media(b"<html><script>alert(1)</script>"))
        self.assertIsNone(desk.sniff_media(b"\x1a\x45\xdf\xa3" + b"\x00" * 20 + b"matroska"))
        self.assertAlmostEqual(desk.mp4_duration(_mp4(7.5)), 7.5)
        self.assertIsNone(desk.mp4_duration(b"\x00\x00\x00\x08ftyp"))

    def test_acceptable_uploads(self):
        self.assertEqual(desk.validate_upload(self._upload(PNG)), "image/png")
        self.assertEqual(desk.validate_upload(self._upload(WEBP, width=1080, height=1920)), "image/webp")
        self.assertEqual(desk.validate_upload(self._upload(_mp4(8), "clip", duration_s=8, fps=24)), "video/mp4")
        self.assertEqual(desk.validate_upload(self._upload(WEBM, "clip", duration_s=30, fps=30)), "video/webm")

    def test_refused_uploads_say_why(self):
        for upload, needle in (
            (self._upload(b""), "空"),
            (self._upload(PNG, "gif"), "still、clip 或 backdrop"),
            (self._upload(b"GIF89a" + b"\x00" * 32), "PNG、JPEG、WebP"),
            (self._upload(_mp4(3)), "PNG、JPEG、WebP"),                       # a clip sent as a still
            (self._upload(PNG + b"\x00" * desk.MAX_STILL_BYTES), "10 MB"),
            (self._upload(PNG, "clip", duration_s=5), "MP4、WebM"),           # a picture sent as a clip
            (self._upload(b"#!/bin/sh\nrm -rf /" + b"\x00" * 32, "clip", duration_s=5), "MP4、WebM"),
            (self._upload(_mp4(5) + b"\x00" * desk.MAX_CLIP_BYTES, "clip", duration_s=5), "60 MB"),
            (self._upload(_mp4(5), "clip", duration_s=31), "30 秒"),
            (self._upload(_mp4(5), "clip", duration_s=0), "30 秒"),
            (self._upload(_mp4(5), "clip", duration_s=float("nan")), "30 秒"),
            (self._upload(_mp4(95), "clip", duration_s=10), "实际时长 95.0 秒"),   # the container disagrees with the form
            (self._upload(PNG, shot_id=0), "shot_id"),
            (self._upload(PNG, width=99999), "width"),
            (self._upload(_mp4(5), "clip", duration_s=5, fps=12), "fps"),
            (self._upload(_mp4(5), "clip", duration_s=5, fps=60), "与时间线的帧率一致"),   # a timeline is never 60 fps
            (self._upload(PNG, plan_revision=-1), "plan_revision"),
        ):
            with self.assertRaises(desk.CaptureError, msg=needle) as raised:
                desk.validate_upload(upload)
            self.assertIn(needle, str(raised.exception))


def _task(task_id: str) -> Dict[str, Any]:
    return {
        "task_id": task_id, "owner_user_id": "director-user", "current_stage": 5, "status": "idle",
        "config": {"llm_model": "m", "image_model": "img", "video_model": "v"},
        "assets": {
            "2_breakdown": {"scenes": [
                {"scene_id": "E1S01", "content": "林夏在办公室与周教授对峙", "characters": ["林夏", "周教授"]},
                {"scene_id": "E1S02", "content": "周教授独自站在走廊", "characters": ["周教授"]},
            ]},
            "4": [
                {"shot_id": 1, "scene_id": "E1S01", "size": "全景", "angle": "平视", "motion": "固定", "desc": "两人对峙", "characters": ["林夏", "周教授"],
                 "sequence_images": ["http://img.test/old-still.png"], "reference_videos": ["http://v.test/library.mp4"]},
                {"shot_id": 2, "scene_id": "E1S01", "size": "近景", "angle": "平视", "motion": "固定", "desc": "林夏盯着对面", "characters": ["林夏"]},
                {"shot_id": 3, "scene_id": "E1S02", "size": "中景", "angle": "平视", "motion": "固定", "desc": "周教授站着", "characters": ["周教授"]},
            ],
            "4_scene_boards": {"E1S01": {"status": "done"}},
        },
        "logs": {}, "episodes": [],
    }


class DirectorDeskApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.media = Path(self.temp.name) / "media"
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        self.repo.save_task("desk-api", _task("desk-api"))
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "director-user", "role": "user"}
        self.client = TestClient(app, cookies={"auth_token": auth_service.generate_token("director-user")})
        self.patches = [
            patch.object(drama_api, "service", self.service),
            patch.object(media_compositor, "MEDIA_DIR", str(self.media)),
            patch.object(media_compositor, "PUBLIC_BASE_URL", "https://cdn.test/media/"),
        ]
        for item in self.patches:
            item.start()
        self.base = "/api/drama/desk-api/director-desk"

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.client.close()
        app.dependency_overrides.pop(get_current_user, None)
        self.temp.cleanup()

    def _upload(self, content: bytes, scene: str = "E1S01", name: str = "capture.bin", mime: str = "application/octet-stream", **form):
        data = {"shot_id": "1", "kind": "still", **{key: str(value) for key, value in form.items()}}
        return self.client.post(f"{self.base}/scenes/{scene}/captures", files={"file": (name, content, mime)}, data=data)

    def _shot(self, shot_id: int) -> Dict[str, Any]:
        return next(shot for shot in self.repo.get_task("desk-api")["assets"]["4"] if shot["shot_id"] == shot_id)

    def _revision(self) -> int:
        return self.client.get("/api/drama/desk-api/spatial/scenes/E1S01").json()["plan"]["revision"]

    def test_an_upload_is_stored_under_a_server_made_name_and_listed(self):
        response = self._upload(
            PNG, name="../../etc/passwd.png", mime="text/html", shot_id=2, camera_id="cam-02", plan_revision=4,
            shows_limbs="true", monochrome="true", labelled="false", width=1080, height=1920,
        )

        self.assertEqual(response.status_code, 200, response.text)
        capture = response.json()
        self.assertEqual(
            (capture["kind"], capture["shotId"], capture["cameraId"], capture["planRevision"], capture["showsLimbs"], capture["monochrome"], capture["labelled"], capture["stale"]),
            ("still", 2, "cam-02", 4, True, True, False, False),
        )
        self.assertRegex(capture["url"], r"^https://cdn\.test/media/desk_desk-api_E1S01_[0-9a-f]{32}\.png$")
        stored = list(self.media.iterdir())
        self.assertEqual([path.name for path in stored], [capture["url"].rsplit("/", 1)[1]])
        self.assertEqual(stored[0].read_bytes(), PNG)

        listing = self.client.get(f"{self.base}/scenes/E1S01/captures").json()
        self.assertEqual((listing["schemaVersion"], [item["id"] for item in listing["captures"]], listing["applied"]), ("director-desk.v1", [capture["id"]], {}))
        self.assertEqual(self.client.get(f"{self.base}/scenes/E1S02/captures").json()["captures"], [])

    def test_uploads_are_refused_by_content_size_length_scene_and_count(self):
        disguised = self._upload(b"<html>" + b"\x00" * 40, name="frame.png", mime="image/png")
        as_clip = self._upload(PNG, name="clip.mp4", mime="video/mp4", kind="clip", duration_s=5)
        too_long = self._upload(_mp4(5), kind="clip", duration_s=31)
        lying = self._upload(_mp4(64), kind="clip", duration_s=6)
        big = self._upload(PNG + b"\x00" * desk.MAX_STILL_BYTES)
        nowhere = self._upload(PNG, scene="E9S99")

        self.assertEqual([r.status_code for r in (disguised, as_clip, too_long, lying, big, nowhere)], [422, 422, 422, 422, 422, 404])
        self.assertIn("PNG、JPEG、WebP", disguised.json()["detail"])
        self.assertIn("MP4、WebM", as_clip.json()["detail"])
        self.assertIn("30 秒", too_long.json()["detail"])
        self.assertIn("10 MB", big.json()["detail"])
        self.assertFalse(self.media.exists() and list(self.media.iterdir()))

        task = self.repo.get_task("desk-api")
        desk.store_of(task)["scenes"]["E1S01"] = {"captures": [{"id": f"c{i}", "kind": "still", "shot_id": 1, "url": f"http://x/{i}.png"} for i in range(60)], "applied": {}}
        self.repo.save_task("desk-api", task)
        full = self._upload(PNG)
        self.assertEqual(full.status_code, 422)
        self.assertIn("60 条", full.json()["detail"])
        self.assertFalse(self.media.exists() and list(self.media.iterdir()))
        self.assertEqual(self._upload(PNG, scene="E1S02", shot_id=3).status_code, 200)   # the cap is per scene

    def test_apply_and_unapply_write_exactly_the_two_slots_stage_five_reads(self):
        still = self._upload(PNG).json()
        newer = self._upload(JPEG).json()
        clip = self._upload(_mp4(6), kind="clip", duration_s=6, fps=24, shows_limbs="true").json()

        applied = self.client.post(f"{self.base}/scenes/E1S01/captures/{still['id']}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()["applied"], {"1": {"still": still["id"], "clip": None}})
        self.assertEqual(self._shot(1)["sequence_images"], [still["url"], "http://img.test/old-still.png"])
        self.assertEqual(self._shot(1)["reference_videos"], ["http://v.test/library.mp4"])

        # Applying it twice changes nothing; a newer still takes its place rather than piling up.
        self.client.post(f"{self.base}/scenes/E1S01/captures/{still['id']}/apply")
        self.assertEqual(self._shot(1)["sequence_images"], [still["url"], "http://img.test/old-still.png"])
        self.client.post(f"{self.base}/scenes/E1S01/captures/{newer['id']}/apply")
        self.assertEqual(self._shot(1)["sequence_images"], [newer["url"], "http://img.test/old-still.png"])

        both = self.client.post(f"{self.base}/scenes/E1S01/captures/{clip['id']}/apply").json()
        self.assertEqual(both["applied"], {"1": {"still": newer["id"], "clip": clip["id"]}})
        self.assertEqual(self._shot(1)["reference_videos"], [clip["url"], "http://v.test/library.mp4"])
        self.assertNotIn("reference_videos", self._shot(2))

        back = self.client.post(f"{self.base}/scenes/E1S01/captures/{clip['id']}/unapply").json()
        self.assertEqual(back["applied"], {"1": {"still": newer["id"], "clip": None}})
        self.assertEqual(self._shot(1)["reference_videos"], ["http://v.test/library.mp4"])
        # Unapplying the still that is no longer the applied one leaves the applied one alone
        # (DELETE …/apply is the same request as POST …/unapply).
        self.assertEqual(self.client.delete(f"{self.base}/scenes/E1S01/captures/{still['id']}/apply").status_code, 200)
        self.assertEqual(self._shot(1)["sequence_images"], [newer["url"], "http://img.test/old-still.png"])

        removed = self.client.delete(f"{self.base}/scenes/E1S01/captures/{newer['id']}")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(([item["id"] for item in removed.json()["captures"]], removed.json()["applied"]), ([still["id"], clip["id"]], {}))
        self.assertEqual(self._shot(1)["sequence_images"], ["http://img.test/old-still.png"])
        self.assertEqual(sorted(path.suffix for path in self.media.iterdir()), [".mp4", ".png"])

    def test_apply_refuses_what_it_cannot_honour(self):
        orphan = self._upload(PNG, shot_id=7).json()
        still = self._upload(PNG).json()

        self.assertEqual(self.client.post(f"{self.base}/scenes/E1S01/captures/nope/apply").status_code, 404)
        self.assertEqual(self.client.delete(f"{self.base}/scenes/E1S01/captures/nope").status_code, 404)
        missing_shot = self.client.post(f"{self.base}/scenes/E1S01/captures/{orphan['id']}/apply")
        self.assertEqual(missing_shot.status_code, 422)
        self.assertIn("第 7 镜", missing_shot.json()["detail"])

        task = self.repo.get_task("desk-api")
        task["status"] = "running"
        self.repo.save_task("desk-api", task)
        self.assertEqual(self.client.post(f"{self.base}/scenes/E1S01/captures/{still['id']}/apply").status_code, 409)
        self.assertEqual(self._upload(PNG).status_code, 409)
        self.assertEqual(len(list(self.media.iterdir())), 2)   # the refused upload left no file behind

        app.dependency_overrides[get_current_user] = lambda: {"user_id": "someone-else", "role": "user"}
        self.assertEqual(self.client.get(f"{self.base}/scenes/E1S01/captures").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/poses").status_code, 404)

    def test_a_blocking_edit_a_rebuild_and_an_import_each_mark_the_scenes_captures_stale(self):
        def stale_flags() -> list[bool]:
            return [item["stale"] for item in self.client.get(f"{self.base}/scenes/E1S01/captures").json()["captures"]]

        def fresh() -> None:
            task = self.repo.get_task("desk-api")
            for item in task["assets"][desk.ASSET_KEY]["scenes"]["E1S01"]["captures"]:
                item["stale"] = False
            self.repo.save_task("desk-api", task)

        clip = self._upload(_mp4(6), kind="clip", duration_s=6).json()
        elsewhere = self._upload(PNG, scene="E1S02", shot_id=3).json()
        self.client.post(f"{self.base}/scenes/E1S01/captures/{clip['id']}/apply")

        refused = self.client.patch("/api/drama/desk-api/spatial/scenes/E1S01", json={"baseRevision": self._revision(), "operations": [{"op": "move_actor", "name": "无名氏", "position": [0, 0]}]})
        self.assertEqual((refused.status_code, stale_flags()), (422, [False]))

        patched = self.client.patch("/api/drama/desk-api/spatial/scenes/E1S01", json={
            "baseRevision": self._revision(), "solve": False, "operations": [{"op": "move_actor", "name": "林夏", "position": [-2.0, 0.5]}],
        })
        self.assertEqual((patched.status_code, stale_flags()), (200, [True]))
        self.assertFalse(self.client.get(f"{self.base}/scenes/E1S02/captures").json()["captures"][0]["stale"], elsewhere)
        # A stale capture cannot be applied afresh, but it can still be taken out.
        again = self.client.post(f"{self.base}/scenes/E1S01/captures/{clip['id']}/apply")
        self.assertEqual(again.status_code, 422)
        self.assertIn("旧站位", again.json()["detail"])

        fresh()
        rebuilt = self.client.post("/api/drama/desk-api/spatial/scenes/E1S01/rebuild", json={"baseRevision": self._revision()})
        self.assertEqual((rebuilt.status_code, stale_flags()), (200, [True]))

        fresh()
        document = self.client.get("/api/drama/desk-api/spatial/scenes/E1S01/export?format=director-desk").json()["document"]
        imported = self.client.post("/api/drama/desk-api/spatial/scenes/E1S01/import", json={"baseRevision": self._revision(), "document": document})
        self.assertEqual((imported.status_code, stale_flags()), (200, [True]))
        self.assertEqual(self.client.post(f"{self.base}/scenes/E1S01/captures/{clip['id']}/unapply").status_code, 200)

    def test_a_backdrop_upload_is_a_scene_reference_that_never_reaches_a_shot(self):
        backdrop = self._upload(JPEG, name="wall.jpg", mime="image/jpeg", kind="backdrop", shot_id=0, width=2048, height=1024)
        self.assertEqual(backdrop.status_code, 200, backdrop.text)
        record = backdrop.json()
        self.assertEqual((record["kind"], record["shotId"], record["durationS"], record["fps"]), ("backdrop", 0, 0.0, 0))

        applied = self.client.post(f"{self.base}/scenes/E1S01/captures/{record['id']}/apply")
        self.assertEqual(applied.status_code, 422)
        self.assertIn("不能应用到分镜", applied.json()["detail"])
        self.assertNotIn(record["url"], self._shot(1).get("sequence_images") or [])

        # A blocking edit dates the stills of the scene; the backdrop is not a picture of the blocking.
        still = self._upload(PNG).json()
        self.client.patch("/api/drama/desk-api/spatial/scenes/E1S01", json={
            "baseRevision": self._revision(), "solve": False, "operations": [{"op": "move_actor", "name": "林夏", "position": [-2.0, 0.5]}],
        })
        flags = {item["kind"]: item["stale"] for item in self.client.get(f"{self.base}/scenes/E1S01/captures").json()["captures"]}
        self.assertEqual(flags, {"backdrop": False, "still": True}, still)

        refused = self._upload(_mp4(4), name="wall.mp4", mime="video/mp4", kind="backdrop", shot_id=0)
        self.assertEqual((refused.status_code, "PNG、JPEG、WebP" in refused.json()["detail"]), (422, True))
        # Backdrops have their own room, so they never use up one of the scene's sixty captures.
        task = self.repo.get_task("desk-api")
        entry = task["assets"][desk.ASSET_KEY]["scenes"]["E1S01"]
        padding = next(item for item in entry["captures"] if item["kind"] == "still")
        entry["captures"].extend([{**dict(padding), "id": f"pad{index}"} for index in range(desk.MAX_CAPTURES_PER_SCENE)])
        self.repo.save_task("desk-api", task)
        self.assertEqual(self._upload(PNG).status_code, 422)
        self.assertEqual(self._upload(JPEG, kind="backdrop", shot_id=0).status_code, 200)

    def test_the_patch_route_carries_the_solve_flag(self):
        cameras = self.client.get("/api/drama/desk-api/spatial/scenes/E1S01").json()["plan"]["cameras"]
        edit = [{"op": "move_actor", "name": "林夏", "position": [-3.0, 0.6]}]

        held = self.client.patch("/api/drama/desk-api/spatial/scenes/E1S01", json={"baseRevision": self._revision(), "solve": False, "operations": edit}).json()
        solved = self.client.patch("/api/drama/desk-api/spatial/scenes/E1S01", json={"baseRevision": self._revision(), "solve": True, "operations": [{"op": "orient_toward", "name": "林夏", "target": "周教授"}]}).json()

        self.assertEqual(held["plan"]["cameras"], cameras)
        self.assertNotEqual(solved["plan"]["cameras"], cameras)

    def test_saved_poses_are_kept_replaced_by_name_capped_and_deleted(self):
        pose = {"preset": "sit", "joints": {"spine.x": 12}, "clip": "", "clip_phase": 0}

        saved = self.client.post(f"{self.base}/poses", json={"name": "沉思", "pose": pose})
        self.assertEqual(saved.status_code, 200, saved.text)
        record = saved.json()["poses"][0]
        self.assertEqual((record["name"], record["pose"]), ("沉思", {"preset": "sit", "joints": {"spine.x": 12.0}, "clip": "", "clip_phase": 0.0}))

        replaced = self.client.post(f"{self.base}/poses", json={"name": "沉思", "pose": {"joints": {"spine.x": 30}}}).json()["poses"]
        self.assertEqual([(item["id"], item["pose"]["joints"]) for item in replaced], [(record["id"], {"spine.x": 30.0})])
        self.client.post(f"{self.base}/poses", json={"name": "拔剑", "pose": {"preset": "fight"}})
        self.assertEqual([item["name"] for item in self.client.get(f"{self.base}/poses").json()["poses"]], ["沉思", "拔剑"])

        for bad in ({"name": "", "pose": pose}, {"name": "坏", "pose": {"joints": {"spine.x": 400}}}, {"name": "坏", "pose": {"limbs": 4}}, {"name": "坏"}):
            self.assertEqual(self.client.post(f"{self.base}/poses", json=bad).status_code, 422, bad)

        removed = self.client.delete(f"{self.base}/poses/{record['id']}")
        self.assertEqual([item["name"] for item in removed.json()["poses"]], ["拔剑"])
        self.assertEqual(self.client.delete(f"{self.base}/poses/{record['id']}").status_code, 404)

        task = self.repo.get_task("desk-api")
        desk.store_of(task)["poses"] = [{"id": f"p{i}", "name": f"姿态{i}", "pose": {}, "created_at": ""} for i in range(200)]
        self.repo.save_task("desk-api", task)
        full = self.client.post(f"{self.base}/poses", json={"name": "第201个", "pose": pose})
        self.assertEqual(full.status_code, 422)
        self.assertIn("200", full.json()["detail"])
        self.assertEqual(self.client.post(f"{self.base}/poses", json={"name": "姿态7", "pose": pose}).status_code, 200)   # replacing is not adding


class StageFiveGateTests(unittest.TestCase):
    BLOCKING = "林夏（站立）与周教授（站立）相距2.6米面对面；机位距林夏5.1米、机高1.4米；录音笔位于林夏前方约1.3米"
    PROMPT = f"镜头1，严格依据对应分镜契约生成连续运镜视频。调度：{BLOCKING}；动作：对峙。相机以“固定”运动。"

    def setUp(self):
        self.task = _task("gate")
        self.shot = self.task["assets"]["4"][0]
        upload = desk.CaptureUpload(content=_mp4(6), kind="clip", shot_id=1, duration_s=6, shows_limbs=True)
        self.clip = desk.add_capture(self.task, "E1S01", upload, "https://cdn.test/media/desk_gate_E1S01_a.mp4")

    def _inputs(self) -> desk.MotionInputs:
        return desk.motion_inputs(self.task, self.shot, list(self.shot.get("reference_videos") or []), self.BLOCKING, self.PROMPT)

    def test_the_measured_lens_clause_is_the_only_thing_withheld(self):
        self.assertEqual(without_camera_pose(self.BLOCKING), "林夏（站立）与周教授（站立）相距2.6米面对面；录音笔位于林夏前方约1.3米")
        self.assertEqual(without_camera_pose("机位距林夏5.1米、机高1.4米"), "")
        self.assertEqual(without_camera_pose("空镜：按场景圣经保持地标位置"), "空镜：按场景圣经保持地标位置")
        # It is the clause the stage itself writes.
        plan = build_plan(_brief())
        self.assertIn("机位距", plan.shot(1).text.blocking)
        self.assertNotIn("机位距", without_camera_pose(plan.shot(1).text.blocking))
        self.assertNotIn("机高", without_camera_pose(plan.shot(1).text.blocking))

    def test_without_an_applied_clip_stage_five_is_untouched(self):
        inputs = self._inputs()
        self.assertEqual((inputs.reference_videos, inputs.blocking, inputs.motion_prompt, inputs.refused), (["http://v.test/library.mp4"], self.BLOCKING, self.PROMPT, []))
        self.assertFalse(inputs.blockout.owns_camera)
        self.assertEqual(desk.motion_inputs({"assets": {}}, self.shot, ["u"], "b", "p").reference_videos, ["u"])

    def test_a_fresh_applied_clip_owns_the_camera(self):
        desk.apply_capture(self.task, "E1S01", self.clip["id"])
        inputs = self._inputs()

        self.assertEqual(inputs.reference_videos, [self.clip["url"], "http://v.test/library.mp4"])
        self.assertTrue(inputs.blockout.owns_camera and inputs.blockout.shows_limbs)
        self.assertNotIn("机位距", inputs.blocking + inputs.motion_prompt)
        self.assertIn("相距2.6米面对面；录音笔", inputs.blocking)
        self.assertIn("相机以“固定”运动", inputs.motion_prompt)
        # A blocking sentence that was nothing but the lens pose stays: the field is required downstream.
        only = desk.motion_inputs(self.task, self.shot, [], "机位距林夏5.1米、机高1.4米", "p")
        self.assertEqual(only.blocking, "机位距林夏5.1米、机高1.4米")
        # Another shot of the scene is not affected.
        other = desk.motion_inputs(self.task, self.task["assets"]["4"][1], [], self.BLOCKING, self.PROMPT)
        self.assertEqual((other.blocking, other.blockout.owns_camera), (self.BLOCKING, False))

    def test_a_stale_applied_clip_is_refused_and_the_camera_sentences_come_back(self):
        desk.apply_capture(self.task, "E1S01", self.clip["id"])
        spatial_stage.edit_plan(self.task, "E1S01", base_revision=spatial_stage.ensure_plan(self.task, "E1S01").revision, operations=[
            {"op": "move_actor", "name": "林夏", "position": [-2.2, 0.4]},
        ])
        inputs = self._inputs()

        self.assertEqual(inputs.refused, [self.clip["url"]])
        self.assertEqual(inputs.reference_videos, ["http://v.test/library.mp4"])
        self.assertEqual((inputs.blocking, inputs.motion_prompt), (self.BLOCKING, self.PROMPT))
        self.assertFalse(inputs.blockout.owns_camera)

    def test_a_limbed_clip_asks_for_the_limb_sequence_only_while_it_is_applied(self):
        self.assertEqual(self.clip["warning"], desk.LIMBS_WARNING)
        self.assertNotIn(desk.LIMBS_REQUIREMENT, self._inputs().motion_prompt)

        desk.apply_capture(self.task, "E1S01", self.clip["id"])
        prompt = self._inputs().motion_prompt
        self.assertTrue(prompt.endswith(f"。{desk.LIMBS_REQUIREMENT}。"))
        self.assertEqual(prompt.count(desk.LIMBS_REQUIREMENT), 1)
        self.assertNotIn("。。", prompt)
        for word in ("前倾角度", "步幅", "重心", "手臂与布料动态"):
            self.assertIn(word, desk.LIMBS_REQUIREMENT)
        # Feeding the result back in does not say it twice.
        again = desk.motion_inputs(self.task, self.shot, [self.clip["url"]], self.BLOCKING, prompt)
        self.assertEqual(again.motion_prompt.count(desk.LIMBS_REQUIREMENT), 1)

        desk.unapply_capture(self.task, "E1S01", self.clip["id"])
        self.assertNotIn(desk.LIMBS_REQUIREMENT, self._inputs().motion_prompt)

    def test_a_limbless_clip_and_a_stale_limbed_one_add_nothing(self):
        plain = desk.add_capture(
            self.task, "E1S01", desk.CaptureUpload(content=_mp4(6), kind="clip", shot_id=1, duration_s=6),
            "https://cdn.test/media/desk_gate_E1S01_b.mp4",
        )
        self.assertEqual(plain["warning"], "")
        desk.apply_capture(self.task, "E1S01", plain["id"])
        inputs = self._inputs()
        self.assertTrue(inputs.blockout.owns_camera)
        self.assertNotIn(desk.LIMBS_REQUIREMENT, inputs.motion_prompt)

        desk.apply_capture(self.task, "E1S01", self.clip["id"])
        desk.mark_captures_stale(self.task, "E1S01")
        self.assertEqual(self._inputs().motion_prompt, self.PROMPT)

    def test_stage_five_calls_the_gate(self):
        source = Path(drama_api.__file__).parents[1].joinpath("service", "drama_service.py").read_text(encoding="utf-8")
        self.assertIn("director_desk.motion_inputs(task, shot, motion_refs, contract.blocking, compiled_motion.prompt)", source)
        self.assertIn("blocking=desk.blocking", source)
        self.assertIn('motion_prompt=f"{carry_lead}{desk.motion_prompt}"', source)


if __name__ == "__main__":
    unittest.main()

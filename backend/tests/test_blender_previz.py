# -*- coding: utf-8 -*-
"""Blender 3D 预演台：方案→规格的换算、规格规则、服务(渲染/缓存/手持/空段/交付分镜)、实时桥接与对话工具。

真 Blender 渲染只在本机装了 Blender 时跑(其余用替身)，ffmpeg 缺失时跳过切片相关用例。
"""

import json
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.core import media_compositor
from app.core.agent_tools import catalog
from app.core.blender_previz import build_spec, live, operations_from_snapshot, runner
from app.core.blender_previz.from_plan import EXTRA_COLOR, from_blender, ground_to_blender, to_blender
from app.core.blender_previz.spec import BlockingSpec
from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan
from app.core.spatial_stage.operations import apply_operations
from app.repository.task_repo import TaskRepository
from app.service import blender_previz_service as previz
from app.service import spatial_stage_service as spatial_stage
from app.service.drama_service import DramaService

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _plan():
    return build_plan(SceneBrief(
        scene_id="E1S01", location="九霄殿外验魂台 / 夜 / 外景",
        text="殷无咎与陆昭在验魂台上对峙，玄铁令落在石台上。",
        characters=["殷无咎", "陆昭"], props=["玄铁令"],
        shots=[
            ShotSpec(1, ["殷无咎", "陆昭"], "", "全景", "平视", "固定", "两人在台上对峙"),
            ShotSpec(2, ["陆昭"], "陆昭", "近景", "过肩", "缓推", "陆昭抬手"),
            ShotSpec(3, ["殷无咎"], "殷无咎", "特写", "平视", "固定", "殷无咎眯眼"),
        ],
    ))


def _mp4(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s=320x568:d={seconds}:r=24",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


class CoordinateTests(unittest.TestCase):
    def test_three_and_blender_axes_round_trip(self):
        self.assertEqual(to_blender([1.0, 2.0, 3.0]), (1.0, -3.0, 2.0))
        self.assertEqual(ground_to_blender([1.5, -2.0]), (1.5, 2.0, 0.0))
        self.assertEqual(from_blender(to_blender([0.3, 1.6, -4.2])), [0.3, 1.6, -4.2])


class BuildSpecTests(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()

    def test_every_shot_becomes_one_segment_with_a_hard_cut_on_its_first_frame(self):
        spec, segments = build_spec(self.plan, durations={1: 3, 2: 2.5}, fps=24)
        self.assertEqual([s["shot_id"] for s in segments], [1, 2, 3])
        self.assertEqual([(s["start"], s["end"]) for s in segments], [(1, 72), (73, 132), (133, 228)])
        self.assertEqual([c.frame for c in spec.cuts], [1, 73, 133])
        self.assertEqual(spec.frames, 228)
        self.assertEqual(len({c.camera for c in spec.cuts}), 3)  # 一镜一台 Blender 摄影机
        self.assertEqual(spec.resolution, (1080, 1920))           # 方案 9:16 → 竖画幅

    def test_actors_bind_their_names_and_principals_never_share_a_colour(self):
        spec, _ = build_spec(self.plan)
        actors = [p for p in spec.proxies if p.binds.kind == "actor"]
        self.assertEqual({p.binds.name for p in actors}, {"殷无咎", "陆昭"})
        self.assertEqual(len({p.color for p in actors}), len(actors))
        self.assertTrue(all(p.shape == "capsule" for p in actors))
        self.assertIn("玄铁令", {b.name for b in spec.set.blocks})

    def test_an_offstage_character_is_hidden_for_that_shot_only(self):
        plan = apply_operations(self.plan, [{"op": "set_shot_override", "shot_id": 3, "name": "陆昭", "offstage": True}])
        spec, segments = build_spec(plan)
        lu = next(p for p in spec.proxies if p.binds.name == "陆昭")
        third = segments[2]
        self.assertEqual(lu.hidden, [(third["start"], third["end"])])

    def test_crowd_members_are_grey_extras(self):
        plan = apply_operations(self.plan, [{"op": "add_crowd", "label": "仙卫", "rows": 2, "columns": 3, "center": [0, 6]}])
        spec, _ = build_spec(plan)
        extras = [p for p in spec.proxies if p.binds.kind == "extra"]
        self.assertEqual(len(extras), 6)
        self.assertTrue(all(p.color == EXTRA_COLOR for p in extras))

    def test_a_timeline_drives_camera_and_target_keys_separately(self):
        plan = apply_operations(self.plan, [{"op": "apply_camera_move", "shot_id": 2, "preset": "push"}])
        spec, segments = build_spec(plan)
        camera = next(c for c in spec.cameras if c.id == "shot-002")
        self.assertGreaterEqual(len(camera.keys), 2)
        self.assertTrue(camera.target.keys)        # 目标有自己的路径，不是跟着摄影机转
        frames = [k.frame for k in camera.keys]
        self.assertTrue(all(segments[1]["start"] <= f <= segments[1]["end"] for f in frames))

    def test_handheld_and_reserved_slots_come_from_the_options(self):
        spec, segments = build_spec(self.plan, options={
            "handheld_shots": [2], "reserved": [{"shot_id": 3, "from_s": 1, "to_s": 2, "label": "雷柱"}]})
        handheld = {c.id for c in spec.cameras if c.handheld}
        self.assertEqual(handheld, {"shot-002"})
        slot = spec.reserved[0]
        self.assertEqual((slot.label, slot.start, slot.end), ("雷柱", segments[2]["start"] + 24, segments[2]["start"] + 47))

    def test_a_scene_without_shots_cannot_be_previzd(self):
        with self.assertRaises(ValueError):
            build_spec(self.plan, shot_ids=[99])


class SnapshotTests(unittest.TestCase):
    def test_what_was_dragged_in_blender_comes_back_as_plan_operations(self):
        plan = _plan()
        spec, segments = build_spec(plan)
        lu_index = next(i for i, a in enumerate(plan.actors) if a.name == "陆昭")
        lu = plan.actors[lu_index]
        moved = list(ground_to_blender([lu.position[0] + 1.0, lu.position[1]]))
        camera = next(c for c in plan.cameras if c.id == plan.shot(1).camera_id)
        snapshot = {
            "proxies": [{"id": f"actor-{lu_index + 1:02d}", "position": moved, "yaw_deg": lu.yaw_deg + 30}],
            "blocks": [],
            "cameras": [{"id": "shot-001", "position": list(to_blender([v + (0.5 if i == 0 else 0) for i, v in enumerate(camera.position)])),
                         "target": list(to_blender(camera.target)), "lens_mm": camera.lens_mm}],
        }
        ops = operations_from_snapshot(plan, snapshot, segments)
        move = next(op for op in ops if op["op"] == "move_actor")
        self.assertEqual(move["name"], "陆昭")
        self.assertAlmostEqual(move["position"][0], lu.position[0] + 1.0, places=2)
        self.assertEqual(next(op for op in ops if op["op"] == "move_camera")["camera_id"], camera.id)
        # 写回方案也成立
        apply_operations(plan, ops)

    def test_nothing_moved_means_no_operations(self):
        plan = _plan()
        spec, segments = build_spec(plan)
        snapshot = {"proxies": [{"id": p.id, "position": list(p.keys[0].position), "yaw_deg": p.keys[0].yaw_deg} for p in spec.proxies],
                    "blocks": [], "cameras": []}
        self.assertEqual(operations_from_snapshot(plan, snapshot, segments), [])


class SpecRuleTests(unittest.TestCase):
    def _spec(self, **changes):
        base = {
            "frames": 48,
            "proxies": [
                {"id": "a", "binds": {"kind": "actor", "name": "甲"}, "size": [0.5, 0.5, 1.7], "color": "#112233", "keys": [{"frame": 1, "position": [0, 0, 0]}]},
                {"id": "b", "binds": {"kind": "actor", "name": "乙"}, "size": [0.5, 0.5, 1.7], "color": "#445566", "keys": [{"frame": 1, "position": [1, 0, 0]}]},
            ],
            "cameras": [{"id": "c1", "keys": [{"frame": 1, "position": [0, -5, 1.6]}], "target": {"proxy": "a"}}],
            "cuts": [{"frame": 1, "camera": "c1"}],
        }
        base.update(changes)
        return BlockingSpec.model_validate(base)

    def test_a_valid_spec_passes(self):
        self.assertEqual(self._spec().segments()[0]["end"], 48)

    def test_two_principals_may_not_share_a_colour(self):
        with self.assertRaises(ValidationError):
            self._spec(proxies=[
                {"id": "a", "binds": {"kind": "actor", "name": "甲"}, "size": [0.5, 0.5, 1.7], "color": "#112233", "keys": [{"frame": 1, "position": [0, 0, 0]}]},
                {"id": "b", "binds": {"kind": "actor", "name": "乙"}, "size": [0.5, 0.5, 1.7], "color": "#112233", "keys": [{"frame": 1, "position": [1, 0, 0]}]},
            ])

    def test_the_first_cut_must_open_the_film_and_cameras_must_exist(self):
        with self.assertRaises(ValidationError):
            self._spec(cuts=[{"frame": 5, "camera": "c1"}])
        with self.assertRaises(ValidationError):
            self._spec(cuts=[{"frame": 1, "camera": "nope"}])

    def test_a_target_is_either_a_proxy_or_a_path(self):
        with self.assertRaises(ValidationError):
            self._spec(cameras=[{"id": "c1", "keys": [{"frame": 1, "position": [0, -5, 1.6]}], "target": {}}])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "media"
        self.media.mkdir()
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(self.media))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        task = {
            "task_id": "previz-1", "owner_user_id": "u1", "status": "idle", "current_stage": 4, "config": {}, "logs": {},
            "assets": {
                "2_breakdown": {"scenes": [{"scene_id": "E1S01", "content": "验魂台对峙", "characters": ["殷无咎", "陆昭"]}]},
                "4": [{"scene_id": "E1S01", "shot_id": i, "duration": 2} for i in (1, 2, 3)],
            },
        }
        spatial_stage.save_plan(task, _plan())
        self.service.repo.save_task("previz-1", task)
        self.renders = 0

    def _fake_render(self, spec, out_dir):
        self.renders += 1
        out_dir.mkdir(parents=True, exist_ok=True)
        video = _mp4(out_dir / "previz.mp4", spec.frames / spec.fps) if HAS_FFMPEG else (out_dir / "previz.mp4")
        if not HAS_FFMPEG:
            video.write_bytes(b"")
        stills = []
        for index, cut in enumerate(spec.cuts, start=1):
            path = out_dir / f"cut_{index:02d}.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
            stills.append({"index": index, "frame": cut.frame, "camera": cut.camera, "path": str(path)})
        (out_dir / "previz.blend").write_bytes(b"BLENDER")
        (out_dir / "manifest.json").write_text(json.dumps({"video": str(video), "stills": stills, "blend": str(out_dir / "previz.blend"), "blender": "test"}), encoding="utf-8")
        return runner.RenderResult(out_dir=out_dir, video=video, stills=stills, blend=out_dir / "previz.blend", blender_version="test")

    def test_render_records_the_result_and_reuses_an_identical_spec(self):
        with patch.object(runner, "render", side_effect=self._fake_render), patch.object(previz.live, "push", return_value=None):
            first = previz.render_scene(self.service, "previz-1", "E1S01", long_edge=960)
            second = previz.render_scene(self.service, "previz-1", "E1S01", long_edge=960)
        self.assertEqual(self.renders, 1)
        self.assertTrue(second["reused"])
        self.assertEqual([s["shot_id"] for s in first["segments"]], [1, 2, 3])
        self.assertEqual(len(first["stills"]), 3)
        self.assertTrue(first["video_url"].endswith("previz.mp4"))
        view = previz.get_previz(self.service.repo.get_task("previz-1"), "E1S01")
        self.assertFalse(view["stale"])

    def test_editing_the_blocking_makes_the_previz_stale(self):
        with patch.object(runner, "render", side_effect=self._fake_render), patch.object(previz.live, "push", return_value=None):
            previz.render_scene(self.service, "previz-1", "E1S01", long_edge=960)
        plan = spatial_stage.load_plan(self.service.repo.get_task("previz-1"), "E1S01")
        self.service.patch_spatial_plan("previz-1", "E1S01", base_revision=plan.revision,
                                        operations=[{"op": "move_actor", "name": "陆昭", "position": [2.0, 1.0]}])
        self.assertTrue(previz.get_previz(self.service.repo.get_task("previz-1"), "E1S01")["stale"])
        with self.assertRaises(previz.PrevizError):
            previz.attach_to_shots(self.service, "previz-1", "E1S01")

    def test_options_are_validated_and_stored(self):
        view = previz.set_options(self.service, "previz-1", "E1S01", handheld_shots=[2, 2, 3],
                                  reserved=[{"shot_id": 3, "from_s": 0.5, "to_s": 1.5, "label": "雷柱"}])
        self.assertEqual(view["options"]["handheld_shots"], [2, 3])
        with self.assertRaises(previz.PrevizError):
            previz.set_options(self.service, "previz-1", "E1S01", reserved=[{"shot_id": 3, "from_s": 2, "to_s": 1}])

    @unittest.skipUnless(HAS_FFMPEG, "需要 ffmpeg 切片")
    def test_attaching_puts_one_clip_per_shot_into_the_motion_reference_slot(self):
        with patch.object(runner, "render", side_effect=self._fake_render), patch.object(previz.live, "push", return_value=None):
            previz.render_scene(self.service, "previz-1", "E1S01", long_edge=960)
        result = previz.attach_to_shots(self.service, "previz-1", "E1S01", shot_ids=[1, 3])
        self.assertEqual(result["failed"], [])
        self.assertEqual([item["shot_id"] for item in result["attached"]], [1, 3])
        shots = {s["shot_id"]: s for s in self.service.repo.get_task("previz-1")["assets"]["4"]}
        self.assertEqual(shots[1]["reference_videos"][0], result["attached"][0]["url"])
        self.assertFalse(shots[2].get("reference_videos"))

    def test_blender_missing_is_a_clear_error(self):
        with patch.object(runner, "find_blender", return_value=None), patch.object(previz.live, "push", return_value=None):
            with self.assertRaisesRegex(previz.PrevizError, "没有找到 Blender"):
                previz.render_scene(self.service, "previz-1", "E1S01")


class LiveTests(unittest.TestCase):
    def test_no_blender_listening_is_quiet(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        with patch.object(live, "PORT", free):
            self.assertIsNone(live.ping())
            self.assertIsNone(live.snapshot())


class AgentToolTests(unittest.TestCase):
    def test_the_previz_tools_are_in_the_catalog_with_the_right_effects(self):
        effects = {tool.name: tool.effect for tool in catalog.list()}
        for name, effect in {"describe_stage": "read", "blender_status": "read", "get_blender_previz": "read",
                             "render_blender_previz": "write", "set_previz_options": "write", "attach_previz_to_shots": "write",
                             "push_to_blender": "write", "pull_from_blender": "write"}.items():
            self.assertEqual(effects.get(name), effect, name)

    def test_describe_stage_gives_names_cameras_and_the_operation_cheatsheet(self):
        service = DramaService()
        with tempfile.TemporaryDirectory() as tmp:
            service.repo = TaskRepository(str(Path(tmp) / "tasks.json"))
            task = {"task_id": "t", "owner_user_id": "u", "assets": {}, "config": {}, "logs": {}}
            spatial_stage.save_plan(task, _plan())
            service.repo.save_task("t", task)
            result = catalog.call("describe_stage", {"task_id": "t", "scene_id": "E1S01"}, service=service, user={"user_id": "u"})
        self.assertTrue(result["ok"])
        body = result["result"]
        self.assertEqual({a["name"] for a in body["actors"]}, {"殷无咎", "陆昭"})
        self.assertTrue(body["cameras"])
        self.assertIn("move_actor", body["operations"])


@unittest.skipUnless(runner.find_blender() and HAS_FFMPEG, "本机没有 Blender 或 ffmpeg")
class RealBlenderTests(unittest.TestCase):
    def test_blender_renders_every_frame_and_a_still_per_cut(self):
        spec, segments = build_spec(_plan(), durations={1: 1, 2: 1, 3: 1}, long_edge=480)
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.render(spec, Path(tmp))
            frames = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                     "stream=nb_read_frames,width,height", "-of", "json", str(result.video)],
                                    capture_output=True, text=True, check=True)
            stream = json.loads(frames.stdout)["streams"][0]
            self.assertEqual(int(stream["nb_read_frames"]), spec.frames)
            self.assertEqual((stream["width"], stream["height"]), spec.resolution)
            self.assertEqual(len(result.stills), len(segments))
            self.assertTrue(result.blend.is_file())


if __name__ == "__main__":
    unittest.main()

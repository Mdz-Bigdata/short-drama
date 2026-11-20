# -*- coding: utf-8 -*-
"""White-model blocking diagrams read from a staged scene."""

from __future__ import annotations

import unittest

from app.core import prompt_data
from app.core.spatial_stage import blocking_diagram
from app.core.spatial_stage.models import (
    ActorKey, ActorOverride, CameraMove, ShotTimeline, StageActor, StageCamera, StageLandmark, StagePlan, StageShot,
)


def _camera(camera_id: str, position, target, **extra) -> StageCamera:
    return StageCamera(id=camera_id, label=camera_id, position=position, target=target, aspect="16:9", **extra)


def _plan(**changes) -> StagePlan:
    base = dict(
        scene_id="E1S01", location="旧仓库 夜", aspect_ratio="16:9", revision=7,
        actors=[
            StageActor(id="a1", name="陆沉", position=[1.5, 1.0], yaw_deg=-90, role="principal"),
            StageActor(id="a2", name="苏晚", position=[-1.0, -1.0], yaw_deg=51, role="principal", posture="sit"),
            StageActor(id="a3", name="老周", position=[3.0, -2.0], yaw_deg=180, role="supporting"),
        ],
        landmarks=[
            StageLandmark(id="l1", name="木箱", position=[-1.6, -1.2], size=[0.8, 0.8, 0.6]),
            StageLandmark(id="l2", name="铁门", position=[-4.0, 1.0], size=[0.2, 2.4, 2.6], kind="architecture"),
        ],
        cameras=[
            _camera("c1", [0.2, 1.5, 5.0], [0.2, 1.2, 0.0], lens_mm=40, subjects=["陆沉", "苏晚"]),
            _camera("c2", [2.5, 1.5, 2.5], [-1.0, 1.1, -1.0], lens_mm=85, subjects=["苏晚"]),
            _camera("c3", [0.0, 1.6, 4.0], [0.0, 1.2, 0.0], lens_mm=35, subjects=["陆沉"],
                    move=CameraMove(kind="push", end_position=[0.0, 1.6, 2.0], end_target=[0.0, 1.2, 0.0])),
        ],
        shots=[
            StageShot(shot_id=1, camera_id="c1", subjects=["陆沉", "苏晚"]),
            StageShot(shot_id=2, camera_id="c2", subjects=["苏晚"]),
            StageShot(shot_id=3, camera_id="c1", subjects=["陆沉"],
                      overrides=[ActorOverride(name="陆沉", position=[3.5, 2.0], yaw_deg=-90)]),
            StageShot(shot_id=4, camera_id="c3", subjects=["陆沉"]),
        ],
    )
    base.update(changes)
    return StagePlan(**base)


class ColourTests(unittest.TestCase):
    def test_every_named_character_gets_a_colour_far_from_the_others(self):
        colors = blocking_diagram.assign_colors(_plan().actors)
        hues = [blocking_diagram._hue(colors[name]["hex"]) for name in ("陆沉", "苏晚", "老周")]
        gap = prompt_data.load("blocking_diagram")["min_hue_gap_deg"]
        for index, first in enumerate(hues):
            for second in hues[index + 1:]:
                self.assertGreaterEqual(blocking_diagram._hue_gap(first, second), gap)

    def test_a_hand_set_colour_is_kept_unless_it_is_grey_or_too_close_to_one_taken(self):
        actors = [
            StageActor(id="a1", name="甲", position=[0, 0], role="principal", color="#1e8449"),
            StageActor(id="a2", name="乙", position=[1, 0], role="principal", color="#1f8a4c"),
            StageActor(id="a3", name="丙", position=[2, 0], role="supporting", color="#777777"),
        ]
        colors = blocking_diagram.assign_colors(actors)
        self.assertEqual(colors["甲"], {"hex": "#1E8449", "name": "绿"})
        self.assertNotEqual(colors["乙"]["hex"].lower(), "#1f8a4c")
        self.assertNotEqual(colors["丙"]["hex"].lower(), "#777777")
        palette = {item["hex"] for item in prompt_data.load("blocking_diagram")["palette"]}
        self.assertIn(colors["乙"]["hex"], palette)

    def test_crowd_members_share_the_neutral_grey(self):
        actors = [
            StageActor(id="a1", name="甲", position=[0, 0], role="principal"),
            StageActor(id="a2", name="群演1", position=[1, 0], role="crowd", crowd_id="crowd-1"),
        ]
        colors = blocking_diagram.assign_colors(actors)
        self.assertEqual(colors["群演1"]["hex"], prompt_data.load("blocking_diagram")["extra_color"]["hex"])


class SeriesTests(unittest.TestCase):
    def test_still_shots_share_one_diagram_and_a_walk_or_a_travelling_lens_gets_its_own(self):
        series = blocking_diagram.build(_plan())
        self.assertEqual([item["shot_ids"] for item in series["diagrams"]], [[1, 2], [3], [4]])
        first, walk, push = series["diagrams"]
        self.assertEqual([camera["label"] for camera in first["cameras"]], ["CAM 1", "CAM 2"])
        self.assertEqual(first["routes"], [])
        self.assertIn("站位图 1/3", first["title"])
        self.assertIn("开场站位", first["title"])
        self.assertEqual(walk["routes"][0]["name"], "陆沉")
        self.assertEqual(walk["routes"][0]["order"], 1)
        self.assertEqual(walk["routes"][0]["points"], [[3.5, 2.0], [1.5, 1.0]])
        self.assertIn("走位", walk["title"])
        self.assertEqual(push["cameras"][0]["label"], "CAM 3")
        self.assertEqual(push["cameras"][0]["end_position"], [0.0, 2.0])

    def test_a_lens_keeps_its_number_wherever_it_films_again(self):
        series = blocking_diagram.build(_plan())
        self.assertEqual(series["diagrams"][1]["cameras"][0]["label"], "CAM 1")
        self.assertEqual(series["diagrams"][1]["cameras"][0]["shot_ids"], [3])

    def test_the_cone_is_the_lens_real_horizontal_view_and_takes_a_single_subjects_colour(self):
        series = blocking_diagram.build(_plan())
        wide, tight = series["diagrams"][0]["cameras"]
        # 40 mm on a 36 mm-wide frame sees 48.5 degrees across; 85 mm sees 23.9.
        self.assertAlmostEqual(wide["fov_deg"], 48.5, delta=0.2)
        self.assertAlmostEqual(tight["fov_deg"], 23.9, delta=0.2)
        colour_of = {item["name"]: item["hex"] for item in series["colors"]}
        self.assertEqual(wide["color"], "")
        self.assertEqual(tight["color"], colour_of["苏晚"])

    def test_a_timeline_route_keeps_its_bends_and_routes_are_numbered_by_who_moves_first(self):
        timeline = ShotTimeline(duration_s=6, actors={
            "陆沉": [ActorKey(time=2, position=[1.5, 1.0]), ActorKey(time=4, position=[0.5, 2.0]), ActorKey(time=6, position=[-0.5, 1.0])],
            "老周": [ActorKey(time=0, position=[3.0, -2.0]), ActorKey(time=1, position=[2.0, -2.0])],
        })
        plan = _plan(shots=[StageShot(shot_id=1, camera_id="c1")], timelines={"1": timeline})
        diagram = blocking_diagram.build(plan)["diagrams"][0]
        self.assertEqual([(route["name"], route["order"]) for route in diagram["routes"]], [("老周", 1), ("陆沉", 2)])
        self.assertEqual(len(diagram["routes"][1]["points"]), 3)
        self.assertIn("途中拐 1 次", diagram["prompt"])

    def test_someone_off_stage_is_not_drawn(self):
        plan = _plan(shots=[StageShot(shot_id=1, camera_id="c1", overrides=[ActorOverride(name="老周", offstage=True)])])
        diagram = blocking_diagram.build(plan)["diagrams"][0]
        self.assertEqual([figure["name"] for figure in diagram["figures"]], ["陆沉", "苏晚"])

    def test_a_far_lens_is_drawn_at_the_edge_and_says_how_far_it_really_is(self):
        plan = _plan(cameras=[_camera("c1", [0.0, 1.5, 60.0], [0.0, 1.2, 0.0], lens_mm=200)],
                     shots=[StageShot(shot_id=1, camera_id="c1")])
        camera = blocking_diagram.build(plan)["diagrams"][0]["cameras"][0]
        self.assertGreater(camera["far_m"], 50)
        self.assertLess(camera["position"][1], 20)
        self.assertEqual(camera["true_position"], [0.0, 60.0])

    def test_the_floor_is_whole_metres_and_holds_everything_drawn(self):
        for diagram in blocking_diagram.build(_plan())["diagrams"]:
            low_x, low_z, high_x, high_z = diagram["bounds"]
            self.assertTrue(all(float(value).is_integer() for value in diagram["bounds"]))
            points = [figure["position"] for figure in diagram["figures"]] + [camera["position"] for camera in diagram["cameras"]]
            for x, z in points:
                self.assertTrue(low_x <= x <= high_x and low_z <= z <= high_z)

    def test_a_scene_without_shots_and_an_unknown_view_are_refused_in_words(self):
        with self.assertRaises(blocking_diagram.BlockingDiagramError) as raised:
            blocking_diagram.build(_plan(shots=[]))
        self.assertIn("还没有镜头", str(raised.exception))
        with self.assertRaises(blocking_diagram.BlockingDiagramError):
            blocking_diagram.build(_plan(), view="fisheye")


class PromptTests(unittest.TestCase):
    def test_the_prompt_says_who_stands_where_in_metres_facing_whom_and_what_each_lens_sees(self):
        diagram = blocking_diagram.build(_plan())["diagrams"][0]
        prompt = diagram["prompt"]
        for head in ("■ 画面视角", "■ 场景空间", "■ 人物站位与姿态", "■ 摄影机标记", "■ 角色名牌", "■ 光影与质感", "■ 不要出现"):
            self.assertIn(head, prompt)
        self.assertNotIn("■ 走位路径", prompt)
        self.assertIn("陆沉【", prompt)
        self.assertIn("苏晚【", prompt)
        self.assertIn("坐着", prompt)
        self.assertIn("面向陆沉", prompt)
        self.assertIn("面向画面左侧", prompt)
        self.assertRegex(prompt, r"与苏晚相距约 3 米")
        self.assertIn("CAM 1", prompt)
        self.assertIn("等效 40 毫米", prompt)
        self.assertIn("木箱", prompt)
        self.assertIn("旧仓库 夜", prompt)

    def test_a_walk_is_written_with_its_start_end_length_and_number(self):
        prompt = blocking_diagram.build(_plan())["diagrams"][1]["prompt"]
        self.assertIn("■ 走位路径", prompt)
        self.assertRegex(prompt, r"1\. 陆沉（.色虚线）：从.+走到.+，约 2 米")
        self.assertIn("本镜开始时在", prompt)

    def test_the_view_changes_the_first_line_only(self):
        oblique = blocking_diagram.build(_plan())["diagrams"][0]["prompt"]
        top = blocking_diagram.build(_plan(), view="top")["diagrams"][0]["prompt"]
        self.assertIn("45 度", oblique)
        self.assertIn("正上方", top)
        self.assertEqual(oblique.split("■ 场景空间")[1], top.split("■ 场景空间")[1])

    def test_a_crowded_set_is_trimmed_to_the_cap_and_keeps_the_people_and_lenses(self):
        landmarks = [StageLandmark(id=f"l{i}", name=f"陈设{i}", position=[i % 9 - 4, i // 9 - 4]) for i in range(60)]
        actors = [StageActor(id=f"a{i}", name=f"角色{i}", position=[i - 10, 0.5 * i], role="principal" if i < 2 else "supporting")
                  for i in range(24)]
        plan = _plan(actors=actors, landmarks=landmarks, cameras=[_camera("c1", [0, 1.5, 9], [0, 1.2, 0], subjects=["角色0"])],
                     shots=[StageShot(shot_id=1, camera_id="c1")])
        prompt = blocking_diagram.build(plan)["diagrams"][0]["prompt"]
        self.assertLessEqual(len(prompt), prompt_data.load("blocking_diagram")["limits"]["prompt_chars"])
        self.assertIn("角色0【", prompt)
        self.assertIn("CAM 1", prompt)
        self.assertIn("另有", prompt)

    def test_no_wording_asks_for_a_real_face_or_names_an_image_tool(self):
        prompt = blocking_diagram.build(_plan())["diagrams"][0]["prompt"]
        for word in ("--ar", "--v", "Midjourney", "8K"):
            self.assertNotIn(word, prompt)


if __name__ == "__main__":
    unittest.main()

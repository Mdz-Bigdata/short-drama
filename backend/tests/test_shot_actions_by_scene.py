"""Shot actions find the right board clip: every scene numbers its shots from 1, so a bare shot_id is ambiguous."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core.agent_tools import catalog
from app.repository.task_repo import TaskRepository
from app.schema.shot_visual import ShotVisualSettings
from app.service.drama_service import DramaService
from main import app


def _board_clip(scene: str, uids: list[int], url: str) -> dict:
    return {
        "scene_id": scene, "episode": 1, "shot_id": 1, "shot_uid": uids[0], "shot_ids": [uid % 100 for uid in uids],
        "shot_uids": uids, "video_url": url, "candidates": [url, url.replace(".mp4", "-b.mp4")],
        "contract_fingerprint": f"slice:{scene}", "motion_prompt": f"{scene} 片段", "duration": 10,
        "slice": {"scene_id": scene, "part": 1, "parts": 1, "beats": [{"shot_id": uid % 100, "shot_uid": uid} for uid in uids]},
    }


def _task() -> dict:
    return {
        "task_id": "boards", "owner_user_id": "u1", "status": "completed", "current_stage": 5,
        "config": {"video_model": "seedance2.0"},
        "assets": {
            "4": [
                {"shot_id": 1, "scene_id": "E1S01", "desc": "沈砚推门而入", "scene": "天牢", "duration": "5秒"},
                {"shot_id": 2, "scene_id": "E1S01", "desc": "狱卒抬头", "scene": "天牢", "duration": "5秒"},
                {"shot_id": 1, "scene_id": "E1S02", "desc": "苏晚在雨中回头", "scene": "长街", "duration": "5秒"},
                {"shot_id": 2, "scene_id": "E1S02", "desc": "伞落在地上", "scene": "长街", "duration": "5秒"},
            ],
            "5": [
                _board_clip("E1S01", [100101, 100102], "https://cdn/s01.mp4"),
                _board_clip("E1S02", [100201, 100202], "https://cdn/s02.mp4"),
            ],
            "5_jobs": {
                "100101:0": {"key": "100101:0", "status": "downloaded", "video_url": "https://cdn/s01.mp4"},
                "100201:0": {"key": "100201:0", "status": "downloaded", "video_url": "https://cdn/s02.mp4"},
                "100201:1": {"key": "100201:1", "status": "submitted"},
                # 旧的按镜号记的任务：不属于任何分镜片段，重做别的片段时不能顺手删掉。
                "1:0": {"key": "1:0", "status": "downloaded"},
            },
        },
    }


class ShotActionsByScene(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("boards", _task())
        self.service = DramaService()
        self.service.repo = self.repo
        workspace = patch.object(self.service, "get_shot_visual_workspace", return_value={"ok": True})
        workspace.start()
        self.addCleanup(workspace.stop)

    def _clips(self) -> dict:
        return {clip["scene_id"]: clip for clip in self.repo.get_task("boards")["assets"]["5"]}

    def test_regenerating_a_moment_marks_its_whole_board_stale_and_drops_that_clips_jobs(self):
        self.service.regenerate_shot("boards", 2, reason="伞的位置不对", scene_id="E1S02")

        clips = self._clips()
        self.assertTrue(clips["E1S02"]["stale"])
        self.assertIn("伞的位置不对", clips["E1S02"]["stale_reason"])
        self.assertIn("E1S02 这段片段视频", clips["E1S02"]["stale_reason"])
        self.assertNotIn("stale", clips["E1S01"])
        self.assertEqual(sorted(self.repo.get_task("boards")["assets"]["5_jobs"]), ["100101:0", "1:0"])

    def test_the_project_unique_shot_uid_finds_the_board_too(self):
        self.service.regenerate_shot("boards", 2, shot_uid=100102)

        clips = self._clips()
        self.assertTrue(clips["E1S01"]["stale"])
        self.assertNotIn("stale", clips["E1S02"])
        self.assertEqual(sorted(self.repo.get_task("boards")["assets"]["5_jobs"]), ["100201:0", "100201:1", "1:0"])

    def test_a_bare_shot_id_shared_by_two_scenes_is_refused_instead_of_guessed(self):
        for call in (
            lambda: self.service.regenerate_shot("boards", 1),
            lambda: self.service.select_shot_candidate("boards", 1, "https://cdn/s02-b.mp4"),
            lambda: self.service.set_shot_video_prompt("boards", 1, "新的提示词"),
            lambda: self.service.compose_shot_recipe("boards", 1, "psychology", "strong"),
        ):
            with self.assertRaisesRegex(ValueError, "请指明 scene_id"):
                call()
        self.assertEqual(self.repo.get_task("boards"), _task())

    def test_selecting_a_candidate_changes_only_that_scenes_clip(self):
        self.service.select_shot_candidate("boards", 1, "https://cdn/s02-b.mp4", scene_id="E1S02")

        clips = self._clips()
        self.assertEqual(clips["E1S02"]["video_url"], "https://cdn/s02-b.mp4")
        self.assertEqual(clips["E1S01"]["video_url"], "https://cdn/s01.mp4")
        with self.assertRaisesRegex(ValueError, "不在该镜头的候选列表"):
            self.service.select_shot_candidate("boards", 1, "https://cdn/s02-b.mp4", scene_id="E1S01")

    def test_a_hand_written_prompt_lands_on_that_scenes_shot_and_stales_its_board(self):
        self.service.set_shot_video_prompt("boards", 1, "苏晚缓缓回头", scene_id="E1S02")

        shots = self.repo.get_task("boards")["assets"]["4"]
        self.assertNotIn("video_prompt_override", shots[0])
        self.assertEqual(shots[2]["video_prompt_override"], "苏晚缓缓回头")
        clips = self._clips()
        self.assertTrue(clips["E1S02"]["stale"])
        self.assertNotIn("stale", clips["E1S01"])

    def test_camera_settings_land_on_that_scenes_shot_and_stale_its_board(self):
        settings = ShotVisualSettings(camera_motion="环绕", shot_type="特写", duration_seconds=6)
        self.service.update_shot_visual("boards", 2, settings, scene_id="E1S01")

        shots = self.repo.get_task("boards")["assets"]["4"]
        self.assertEqual(shots[1]["visual"]["camera_motion"], "Orbit")
        self.assertNotIn("visual", shots[3])
        clips = self._clips()
        self.assertTrue(clips["E1S01"]["stale"])
        self.assertNotIn("stale", clips["E1S02"])

    def test_a_recipe_is_filled_from_that_scenes_shot(self):
        recipe = self.service.compose_shot_recipe("boards", 1, "psychology", "strong", scene_id="E1S02")
        self.assertIn("苏晚在雨中回头", recipe["prompt_zh"])
        with self.assertRaisesRegex(ValueError, "镜头不存在"):
            self.service.compose_shot_recipe("boards", 3, "psychology", "strong", scene_id="E1S02")


class LegacyClipsWithoutScenes(unittest.TestCase):
    """旧项目的片段没有场号、镜号全剧唯一：只给 shot_id 照旧能用。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("legacy", {
            "task_id": "legacy", "status": "completed", "config": {"video_model": "seedance2.0"},
            "assets": {
                "4": [{"shot_id": 1, "scene_id": "E1S01", "desc": "a"}, {"shot_id": 2, "scene_id": "E1S02", "desc": "b"}],
                "5": [
                    {"shot_id": 1, "video_url": "https://cdn/1.mp4", "candidates": ["https://cdn/1.mp4", "https://cdn/1b.mp4"]},
                    {"shot_id": 2, "video_url": "https://cdn/2.mp4", "candidates": ["https://cdn/2.mp4"]},
                ],
                "5_jobs": {"2:0": {"key": "2:0", "status": "downloaded"}, "1:0": {"key": "1:0", "status": "downloaded"}},
            },
        })
        self.service = DramaService()
        self.service.repo = self.repo
        workspace = patch.object(self.service, "get_shot_visual_workspace", return_value={"ok": True})
        workspace.start()
        self.addCleanup(workspace.stop)

    def test_bare_shot_ids_still_find_their_clips(self):
        self.service.select_shot_candidate("legacy", 1, "https://cdn/1b.mp4")
        self.service.regenerate_shot("legacy", 2)
        self.service.set_shot_video_prompt("legacy", 1, "改写")

        assets = self.repo.get_task("legacy")["assets"]
        first, second = assets["5"]
        self.assertEqual(first["video_url"], "https://cdn/1b.mp4")
        self.assertTrue(first["stale"])
        self.assertTrue(second["stale"])
        self.assertIn("只重做本镜", second["stale_reason"])
        self.assertEqual(list(assets["5_jobs"]), ["1:0"])
        self.assertEqual(assets["4"][0]["video_prompt_override"], "改写")


class ShotRoutesAndTools(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("boards", _task())
        self.service = DramaService()
        self.service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        self.addCleanup(lambda: app.dependency_overrides.pop(get_current_user, None))
        self.client = TestClient(app)

    def test_routes_take_the_scene_as_a_query_parameter(self):
        with patch.object(drama_api, "service", self.service):
            workspace = self.client.get("/api/drama/boards/shots/visual").json()
            ambiguous = self.client.post("/api/drama/boards/shots/1/regenerate", json={"reason": ""})
            regenerated = self.client.post("/api/drama/boards/shots/1/regenerate?scene_id=E1S02", json={"reason": "重来"})
            picked = self.client.put(
                "/api/drama/boards/shots/2/visual/select?scene_id=E1S01", json={"video_url": "https://cdn/s01-b.mp4"},
            )
            recipe = self.client.post(
                "/api/drama/boards/shots/1/visual/recipe?shot_uid=100201", json={"category": "psychology", "intensity": "soft"},
            )
            prompt = self.client.put("/api/drama/boards/shots/2/video-prompt?scene_id=E1S02", json={"prompt": "伞落地"})
            visual = self.client.put("/api/drama/boards/shots/1/visual?scene_id=E1S01", json={
                "camera_motion": "Orbit", "shot_type": "Close-up", "duration_seconds": 6,
            })

        self.assertEqual(
            [(shot["scene_id"], shot["shot_id"], shot["shot_uid"]) for shot in workspace["shots"]],
            [("E1S01", 1, 100101), ("E1S01", 2, 100102), ("E1S02", 1, 100201), ("E1S02", 2, 100202)],
        )
        self.assertEqual(ambiguous.status_code, 422)
        self.assertIn("scene_id", ambiguous.json()["detail"])
        for response in (regenerated, picked, recipe, prompt, visual):
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([shot["stale"] for shot in regenerated.json()["shots"]], [False, False, True, True])
        self.assertEqual([shot["video_url"] for shot in picked.json()["shots"]][:2], ["https://cdn/s01-b.mp4"] * 2)
        self.assertIn("苏晚在雨中回头", recipe.json()["prompt_zh"])
        self.assertEqual(self.repo.get_task("boards")["assets"]["4"][3]["video_prompt_override"], "伞落地")
        self.assertEqual(visual.json()["shots"][0]["settings"]["camera_motion"], "Orbit")
        self.assertEqual(visual.json()["shots"][2]["settings_source"], "derived")

    def test_the_agent_tool_passes_the_scene_through(self):
        schema = catalog.get("regenerate_shot").input_schema["properties"]
        self.assertTrue({"scene_id", "shot_uid"} <= set(schema))
        user = {"user_id": "u1", "role": "user"}
        with patch.object(self.service, "get_shot_visual_workspace", return_value={"ok": True}):
            ambiguous = catalog.call("regenerate_shot", {"task_id": "boards", "shot_id": 1}, service=self.service, user=user)
            result = catalog.call(
                "regenerate_shot", {"task_id": "boards", "shot_id": 1, "scene_id": "E1S01"}, service=self.service, user=user,
            )
        self.assertFalse(ambiguous["ok"])
        self.assertIn("scene_id", ambiguous["error"])
        self.assertEqual(result["result"], {"shot_id": 1, "scene_id": "E1S01", "stale": True})
        clips = {clip["scene_id"]: clip for clip in self.repo.get_task("boards")["assets"]["5"]}
        self.assertTrue(clips["E1S01"]["stale"])
        self.assertNotIn("stale", clips["E1S02"])


if __name__ == "__main__":
    unittest.main()

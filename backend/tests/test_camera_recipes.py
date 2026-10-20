import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core.camera_recipes import RECIPE_CATEGORIES, compose_recipe, recipe_catalog, repeated_move_signature
from app.core.shot_table_rules import audit_shot_table
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from main import app


class CameraRecipeTests(unittest.TestCase):
    def test_every_category_composes_all_three_intensities_from_provider_primitives(self):
        self.assertEqual(len(recipe_catalog()), len(RECIPE_CATEGORIES))
        for category in RECIPE_CATEGORIES:
            for intensity in ("strong", "medium", "soft"):
                recipe = compose_recipe(category, intensity, provider_family="minimax_h3")
                self.assertEqual(recipe.intensity, intensity)
                self.assertTrue(recipe.prompt_zh and recipe.prompt_en and recipe.negative)
                self.assertTrue(recipe.prompt_zh.startswith(recipe.provider_phrase))

    def test_recipe_is_filled_with_the_shot_and_uses_the_provider_phrasing(self):
        recipe = compose_recipe(
            "fight_climax", "strong", subject_action="沈砚挥剑劈向门柱", environment="天牢", lighting="冷白月光",
            provider_family="minimax_h3",
        )
        self.assertEqual(recipe.camera_motion, "Orbit")
        self.assertIn("沈砚挥剑劈向门柱", recipe.prompt_zh)
        self.assertIn("天牢", recipe.prompt_zh)
        self.assertIn("低位贴地机位", recipe.prompt_zh)
        self.assertIn("蓄力后短促爆发", recipe.prompt_zh)
        pushed = compose_recipe("entrance", "strong", provider_family="minimax_h3")
        self.assertTrue(pushed.provider_phrase.startswith("[Push in]"))
        self.assertEqual(compose_recipe("entrance", "nonsense").intensity, "medium")
        with self.assertRaises(ValueError):
            compose_recipe("unknown-category")

    def test_adjacent_shots_sharing_move_angle_and_rhythm_are_flagged(self):
        same = repeated_move_signature(
            {"motion": "推镜", "angle": "平视", "_seconds": 2}, {"motion": "Dolly In", "angle": "eye-level", "_seconds": 3},
        )
        self.assertEqual(same, "推镜 / 平视 / 快节奏")
        self.assertEqual(repeated_move_signature({"motion": "推镜", "angle": "平视", "_seconds": 2}, {"motion": "推镜", "angle": "仰拍", "_seconds": 2}), "")
        self.assertEqual(repeated_move_signature({"motion": "固定", "angle": "平视", "_seconds": 2}, {"motion": "固定", "angle": "平视", "_seconds": 2}), "")

        desc = "陈九站在祭坛边，火把照亮他的侧脸，指节扣紧火把木柄，肩背绷直，袍角垂落没有一丝晃动，眼神冷得没有波澜。"
        audit = audit_shot_table([
            {"shot_id": 1, "size": "全景", "duration": "2s", "motion": "推镜", "angle": "平视", "desc": desc},
            {"shot_id": 2, "size": "中景", "duration": "3s", "motion": "缓慢推进", "angle": "平视", "desc": desc},
            {"shot_id": 3, "size": "特写", "duration": "3s", "motion": "推镜", "angle": "仰拍", "desc": desc},
        ], video_model="seedance2.0")
        flagged = {issue.shot_id for issue in audit.issues if issue.rule == "相邻镜运镜撞款"}
        self.assertEqual(flagged, {2})


class ShotRecipeApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("recipe-task", {
            "task_id": "recipe-task", "owner_user_id": "u1", "current_stage": 5, "status": "completed",
            "config": {"video_model": "MiniMax-H3"},
            "assets": {"4": [{"shot_id": 1, "scene_id": "E1S01", "size": "MS", "motion": "Dolly In", "desc": "沈砚推门而入", "scene": "天牢"}]},
        })
        self.service = DramaService()
        self.service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        self.addCleanup(lambda: app.dependency_overrides.pop(get_current_user, None))
        self.client = TestClient(app)

    def test_workspace_lists_recipe_categories_and_composes_one_for_a_shot(self):
        with patch.object(drama_api, "service", self.service):
            workspace = self.client.get("/api/drama/recipe-task/shots/visual").json()
            composed = self.client.post("/api/drama/recipe-task/shots/1/visual/recipe", json={"category": "psychology", "intensity": "strong"})
            missing = self.client.post("/api/drama/recipe-task/shots/9/visual/recipe", json={"category": "psychology"})
            unknown = self.client.post("/api/drama/recipe-task/shots/1/visual/recipe", json={"category": "nope"})

        self.assertEqual([item["value"] for item in workspace["recipe_categories"]][:2], ["entrance", "tracking"])
        self.assertEqual(composed.status_code, 200, composed.text)
        body = composed.json()
        self.assertEqual((body["camera_motion"], body["intensity"]), ("Zoom In", "strong"))
        self.assertTrue(body["provider_phrase"].startswith("[Zoom in]"))
        self.assertIn("沈砚推门而入", body["prompt_zh"])
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(unknown.status_code, 422)
        # Composing never persists anything.
        self.assertNotIn("visual", self.repo.get_task("recipe-task")["assets"]["4"][0])


if __name__ == "__main__":
    unittest.main()

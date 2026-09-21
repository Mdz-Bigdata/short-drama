import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core.shot_seeds import assign_scene_seeds, candidate_seed, scene_seed_base
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from main import app


class ShotSeedTests(unittest.TestCase):
    def test_same_scene_shots_get_consecutive_seeds_and_candidates_offset(self):
        shots = [
            {"shot_id": 1, "scene_id": "E1S01"}, {"shot_id": 2, "scene_id": "E1S01"},
            {"shot_id": 3, "scene_id": "E1S02"}, {"shot_id": 4, "scene_id": "E1S01"},
        ]
        seeds = assign_scene_seeds(shots)
        base = scene_seed_base("E1S01")
        self.assertEqual((seeds[1], seeds[2], seeds[4]), (base + 1, base + 2, base + 3))
        self.assertEqual(seeds[3], scene_seed_base("E1S02") + 1)
        self.assertNotEqual(base, scene_seed_base("E1S02"))
        self.assertEqual(assign_scene_seeds(shots), seeds)
        self.assertEqual(candidate_seed(100, 2), 114)
        self.assertIsNone(candidate_seed(None, 1))


class ShotSeedApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("seed-task", {
            "task_id": "seed-task", "owner_user_id": "u1", "current_stage": 5, "status": "completed",
            "config": {"video_model": "MiniMax-H3"},
            "assets": {
                "4": [
                    {"shot_id": 1, "scene_id": "E1S01", "size": "MS", "motion": "推镜", "desc": "沈砚推门而入", "duration": "5"},
                    {"shot_id": 2, "scene_id": "E1S01", "size": "CU", "motion": "固定", "desc": "沈砚抬眼", "duration": "4"},
                ],
                "5": [{
                    "shot_id": 1, "video_url": "/media/a.mp4", "candidates": ["/media/a.mp4", "/media/b.mp4"], "seed": None,
                }],
            },
        })
        self.service = DramaService()
        self.service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        self.addCleanup(lambda: app.dependency_overrides.pop(get_current_user, None))
        self.client = TestClient(app)

    def test_assign_seeds_and_select_a_candidate(self):
        with patch.object(drama_api, "service", self.service):
            assigned = self.client.post("/api/drama/seed-task/shots/seeds/assign")
            self.assertEqual(assigned.status_code, 200, assigned.text)
            body = assigned.json()
            seeds = [shot["settings"]["seed"] for shot in body["shots"]]
            self.assertEqual(seeds[1], seeds[0] + 1)
            self.assertTrue(body["shots"][0]["stale"])
            self.assertEqual(body["shots"][0]["candidate_urls"], ["/media/a.mp4", "/media/b.mp4"])

            selected = self.client.put("/api/drama/seed-task/shots/1/visual/select", json={"video_url": "/media/b.mp4"})
            self.assertEqual(selected.status_code, 200, selected.text)
            self.assertEqual(selected.json()["shots"][0]["video_url"], "/media/b.mp4")
            rejected = self.client.put("/api/drama/seed-task/shots/1/visual/select", json={"video_url": "/media/zzz.mp4"})
            self.assertEqual(rejected.status_code, 422)
            no_clip = self.client.put("/api/drama/seed-task/shots/2/visual/select", json={"video_url": "/media/b.mp4"})
            self.assertEqual(no_clip.status_code, 422)

        stored = self.repo.get_task("seed-task")
        self.assertEqual(stored["assets"]["5"][0]["selected_candidate"], "/media/b.mp4")
        self.assertEqual(stored["assets"]["4"][0]["visual"]["seed"], seeds[0])
        self.assertEqual(stored["current_stage"], 5)


if __name__ == "__main__":
    unittest.main()

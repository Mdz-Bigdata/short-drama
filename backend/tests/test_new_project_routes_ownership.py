"""The project routes added for tasks, voices, the image pool and panoramas answer only their owner."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import drama_api, image_pool_api, panorama_api, task_center_api, voice_asset_api
from app.api.auth_api import get_current_user
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService

ROUTES = (
    ("get", "/tasks"), ("post", "/tasks/video%3A1/retry"),
    ("get", "/voices"), ("post", "/voices/narrator/audition"), ("post", "/voices/narrator/cast"), ("put", "/voices/narrator"), ("delete", "/voices/narrator"),
    ("get", "/image-pool"), ("post", "/image-pool/rebuild"), ("post", "/image-pool/split"), ("post", "/image-pool/assign"),
    ("get", "/panoramas/scenes/E1S01"), ("post", "/panoramas/scenes/E1S01"),
)


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service.repo.save_task("mine", {"task_id": "mine", "owner_user_id": "owner", "assets": {}, "config": {}})
        patcher = patch.object(drama_api, "service", self.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = FastAPI()
        for module in (task_center_api, voice_asset_api, image_pool_api, panorama_api):
            self.app.include_router(module.router)

    def _as(self, user_id):
        self.app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "role": "user"}
        return TestClient(self.app)

    def test_someone_else_gets_a_404_and_nothing_runs(self):
        client = self._as("stranger")
        with patch.object(self.service.gateway, "generate_image") as image, \
             patch.object(self.service, "execute_stage", new=AsyncMock()) as stage:
            for method, path in ROUTES:
                response = getattr(client, method)(f"/api/drama/mine{path}")
                self.assertEqual(response.status_code, 404, f"{method} {path}: {response.text}")
                self.assertEqual(response.json()["detail"], "任务不存在", path)
        image.assert_not_called()
        stage.assert_not_called()

    def test_no_session_gets_a_401(self):
        client = TestClient(self.app)
        for method, path in ROUTES:
            self.assertEqual(getattr(client, method)(f"/api/drama/mine{path}").status_code, 401, path)

    def test_the_owner_gets_through(self):
        client = self._as("owner")
        for path in ("/tasks", "/voices", "/image-pool"):
            self.assertEqual(client.get(f"/api/drama/mine{path}").status_code, 200, path)

    def test_routes_do_not_clash_with_the_existing_drama_router(self):
        existing = {(method, route.path) for route in drama_api.router.routes for method in getattr(route, "methods", [])}
        added = {
            (method, route.path)
            for module in (task_center_api, voice_asset_api, image_pool_api, panorama_api)
            for route in module.router.routes for method in getattr(route, "methods", [])
        }
        self.assertEqual(existing & added, set())


if __name__ == "__main__":
    unittest.main()

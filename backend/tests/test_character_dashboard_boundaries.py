import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core.character_dashboard import compile_character_dashboard
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.service.drama_service import DramaService
from main import app


class CharacterDashboardRawRecoveryTests(unittest.TestCase):
    def test_structured_roster_is_not_expanded_by_metadata_headings(self):
        dashboard = compile_character_dashboard({
            "task_id": "structured-character-task",
            "config": {"title_suggestion": "渡口"},
            "assets": {
                "3": (
                    "## 角色设计规范：五视图一致性角色卡\n"
                    "### 角色 UID 总表\n"
                    "## 主角：沈知微\n十九岁，深蓝校服。\n"
                    "## 反派：陆行远\n二十八岁，黑色风衣。"
                ),
                "3_dna": {
                    "characters": [{"name": "沈知微"}],
                },
            },
        })

        self.assertEqual([character.name for character in dashboard.characters], ["沈知微"])
        self.assertIn("深蓝校服", dashboard.characters[0].description)

    def test_raw_only_recovery_requires_an_explicit_markdown_role_card(self):
        dashboard = compile_character_dashboard({
            "task_id": "raw-character-task",
            "config": {},
            "assets": {
                "3": (
                    "角色设计规范：五视图一致性角卡\n"
                    "### 角色 UID 总表\n"
                    "**主角：顾言**\n二十八岁，灰色西装。"
                ),
            },
        })

        self.assertEqual([character.name for character in dashboard.characters], ["顾言"])


class DramaTaskOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.request = DramaCreateRequest(title_suggestion="任务归属测试")

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)
        self.temp.cleanup()

    @staticmethod
    def _set_user(user_id: str, role: str = "user") -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": user_id,
            "role": role,
        }

    def test_create_persists_owner_and_list_is_scoped_to_current_user(self):
        self._set_user("user-a")
        with patch.object(drama_api, "service", self.service):
            client = TestClient(app)
            created = client.post("/api/drama/create", json={"titleSuggestion": "用户 A 的项目"})
            other = self.service.create_task(self.request, owner_user_id="user-b")
            listed = client.get("/api/drama/list")

        self.assertEqual(created.status_code, 200, created.text)
        created_id = created.json()["taskId"]
        self.assertEqual(self.service.repo.get_task(created_id)["owner_user_id"], "user-a")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["taskId"] for item in listed.json()], [created_id])
        self.assertNotEqual(other["task_id"], created_id)

    def test_non_owner_cannot_probe_any_task_route(self):
        task = self.service.create_task(self.request, owner_user_id="user-a")
        self._set_user("user-b")

        with patch.object(drama_api, "service", self.service):
            client = TestClient(app)
            status = client.get(f"/api/drama/{task['task_id']}/status")
            dashboard = client.get(f"/api/drama/{task['task_id']}/character-dashboard")

        self.assertEqual(status.status_code, 404)
        self.assertEqual(dashboard.status_code, 404)

    def test_authorization_repository_miss_fails_closed_without_handler_retry(self):
        task = self.service.create_task(self.request, owner_user_id="user-a")
        self._set_user("user-b")

        with (
            patch.object(drama_api, "service", self.service),
            patch.object(
                self.service.repo,
                "get_task",
                side_effect=[None, task],
            ) as get_task,
        ):
            response = TestClient(app).get(
                f"/api/drama/{task['task_id']}/character-dashboard"
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(get_task.call_count, 1)

    def test_admin_can_open_legacy_ownerless_tasks(self):
        legacy = self.service.create_task(self.request)
        self._set_user("admin-a", role="admin")

        with patch.object(drama_api, "service", self.service):
            response = TestClient(app).get(f"/api/drama/{legacy['task_id']}/character-dashboard")

        self.assertEqual(response.status_code, 200, response.text)


if __name__ == "__main__":
    unittest.main()

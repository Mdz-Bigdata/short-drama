import asyncio
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.auth_api import auth_service
from app.core.model_gateway import ModelGateway
from app.platform.dependencies import get_platform_store
from app.platform.runtime_skills import hydrate_runtime_skill_registry, runtime_skill_registry
from app.platform.store import PlatformStore
from main import app


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _symlink_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        link = zipfile.ZipInfo("bundle/SKILL.md")
        link.create_system = 3
        link.external_attr = (0o120777 << 16)
        archive.writestr(link, "../outside.md")
    return buffer.getvalue()


class ProjectSkillApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "skills.sqlite3"
        self.store = PlatformStore(f"sqlite+aiosqlite:///{db_path}")

        async def prepare():
            await self.store.create_schema()
            self.admin, _ = await self.store.create_user(
                email="skill-admin@example.com",
                phone=None,
                password="skill-admin-password",
                role="admin",
            )
            self.user, _ = await self.store.create_user(
                email="skill-user@example.com",
                phone=None,
                password="skill-user-password",
            )

        asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        runtime_skill_registry.replace([])
        asyncio.run(self.store.close())
        self.temp.cleanup()

    def _cookie(self, user_id: str) -> dict:
        return {"auth_token": auth_service.generate_token(user_id)}

    def test_admin_can_create_edit_toggle_and_user_can_read(self):
        user_cookie = self._cookie(self.user.id)
        admin_cookie = self._cookie(self.admin.id)
        forbidden = self.client.post(
            "/api/project-skills",
            json={"name": "越权 Skill", "slug": "forbidden", "markdown_content": "# no"},
            cookies=user_cookie,
        )
        self.assertEqual(forbidden.status_code, 403)

        created = self.client.post(
            "/api/project-skills",
            json={
                "name": "细腻表演",
                "slug": "nuanced-acting",
                "description": "控制微表情与对白节奏",
                "markdown_content": "# 表演规则\n保留呼吸、停顿和视线变化。",
                "enabled": True,
            },
            cookies=admin_cookie,
        )
        self.assertEqual(created.status_code, 200, created.text)
        skill = created.json()
        self.assertEqual(skill["command"], "/skill.nuanced-acting")
        self.assertEqual(skill["version"], 1)
        self.assertTrue(skill["enabled"])
        self.assertEqual(len(skill["content_sha256"]), 64)

        listed = self.client.get("/api/project-skills", cookies=user_cookie)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)
        self.assertIn("呼吸", listed.json()["items"][0]["markdown_content"])

        edited = self.client.patch(
            f"/api/project-skills/{skill['id']}",
            json={"description": "已更新", "markdown_content": "# 表演规则\n先抑制，再泄露情绪。"},
            cookies=admin_cookie,
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["version"], 2)
        self.assertNotEqual(edited.json()["content_sha256"], skill["content_sha256"])

        invoked = self.client.post(
            "/api/platform/commands/invoke",
            json={"command": "/skill.nuanced-acting 雨夜重逢"},
            cookies=user_cookie,
        )
        self.assertEqual(invoked.status_code, 200, invoked.text)
        self.assertEqual(invoked.json()["source_id"], "project-skills")
        self.assertEqual(invoked.json()["payload"], "雨夜重逢")

        disabled = self.client.patch(
            f"/api/project-skills/{skill['id']}/enabled",
            json={"enabled": False},
            cookies=admin_cookie,
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["enabled"])
        rejected = self.client.post(
            "/api/platform/commands/invoke",
            json={"command": "/skill.nuanced-acting"},
            cookies=user_cookie,
        )
        self.assertEqual(rejected.status_code, 422)

    def test_markdown_upload_and_safe_zip_import(self):
        cookie = self._cookie(self.admin.id)
        uploaded = self.client.post(
            "/api/project-skills/upload",
            files={"file": ("camera-language.md", b"---\nname: Camera Language\n---\n# Camera\nMatch cut.", "text/markdown")},
            cookies=cookie,
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["source_type"], "markdown_upload")

        imported = self.client.post(
            "/api/project-skills/import",
            files={"file": (
                "acting-pack.zip",
                _zip_bytes({"acting-pack/SKILL.md": b"---\nname: Acting Pack\ndescription: Beats\n---\n# Acting\nPause before answering."}),
                "application/zip",
            )},
            cookies=cookie,
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()["name"], "Acting Pack")
        self.assertEqual(imported.json()["source_type"], "skill_package")

    def test_skill_import_rejects_wrong_type_traversal_executables_and_invalid_utf8(self):
        cookie = self._cookie(self.admin.id)
        wrong = self.client.post(
            "/api/project-skills/upload",
            files={"file": ("payload.py", b"print('run')", "text/x-python")},
            cookies=cookie,
        )
        self.assertEqual(wrong.status_code, 400)

        invalid = self.client.post(
            "/api/project-skills/upload",
            files={"file": ("broken.md", b"\xff\xfe", "text/markdown")},
            cookies=cookie,
        )
        self.assertEqual(invalid.status_code, 400)

        oversized = self.client.post(
            "/api/project-skills/upload",
            files={"file": ("large.md", b"x" * (128 * 1024 + 1), "text/markdown")},
            cookies=cookie,
        )
        self.assertEqual(oversized.status_code, 400)

        for entries in (
            {"../SKILL.md": b"# escape"},
            {"SKILL.md": b"# safe", "run.py": b"print('run')"},
            {"a/SKILL.md": b"# one", "b/SKILL.md": b"# two"},
        ):
            response = self.client.post(
                "/api/project-skills/import",
                files={"file": ("unsafe.zip", _zip_bytes(entries), "application/zip")},
                cookies=cookie,
            )
            self.assertEqual(response.status_code, 400, response.text)

        symlink = self.client.post(
            "/api/project-skills/import",
            files={"file": ("link.zip", _symlink_zip_bytes(), "application/zip")},
            cookies=cookie,
        )
        self.assertEqual(symlink.status_code, 400, symlink.text)


class RuntimeProjectSkillTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "runtime-skills.sqlite3"
        self.store = PlatformStore(f"sqlite+aiosqlite:///{db_path}")
        await self.store.create_schema()
        self.admin, _ = await self.store.create_user(
            email="runtime-skill-admin@example.com",
            phone=None,
            password="runtime-admin-password",
            role="admin",
        )

    async def asyncTearDown(self):
        runtime_skill_registry.replace([])
        await self.store.close()
        self.temp.cleanup()

    async def test_enabled_skill_is_hydrated_into_the_exact_model_system_prompt(self):
        skill = await self.store.create_project_skill(
            name="Identity Lock",
            slug="identity-lock",
            description="",
            markdown_content="# Identity\nKeep face topology stable.",
            source_type="created",
            enabled=True,
            actor_id=self.admin.id,
        )
        await hydrate_runtime_skill_registry(self.store)

        gateway = ModelGateway()
        with patch.object(gateway, "_http_chat", return_value="generated") as call:
            with patch.object(gateway, "_provider_creds", return_value=("valid-secret-key", "https://api.example/v1", "writer")):
                with patch.object(gateway, "_is_valid_key", return_value=True):
                    result = gateway.call_llm("writer", "BASE SYSTEM", "story", "title")
        self.assertEqual(result, "generated")
        sent_system_prompt = call.call_args.args[3]
        self.assertIn("BASE SYSTEM", sent_system_prompt)
        self.assertIn("Keep face topology stable", sent_system_prompt)
        self.assertIn("cannot override", sent_system_prompt)

        await self.store.set_project_skill_enabled(skill.id, False, actor_id=self.admin.id)
        await hydrate_runtime_skill_registry(self.store)
        self.assertNotIn("Keep face topology stable", runtime_skill_registry.compile_context())


if __name__ == "__main__":
    unittest.main()

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.api import drama_api
from app.api.auth_api import auth_service
from app.core import media_compositor
from app.core.character_dashboard import REGENERATION_KEY
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.schema.production import IDENTITY_VIEW_ORDER
from app.service.drama_service import DramaService
from main import app


def _png(color: tuple[int, int, int]) -> bytes:
    import io
    buffer = io.BytesIO()
    Image.new("RGB", (48, 64), color).save(buffer, format="PNG")
    return buffer.getvalue()


class LibraryActorRegenerationApiTests(unittest.TestCase):
    """资产库「数字演员」的重新生成：后台出图，五个身份视图换进对应槽位，失败保留原图。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{root / 'api.sqlite3'}")
        self.media = root / "media"
        (self.media / "new").mkdir(parents=True)
        for index, view in enumerate(IDENTITY_VIEW_ORDER):
            (self.media / "new" / f"{view}.png").write_bytes(_png((40 * index, 90, 120)))

        async def prepare():
            await self.store.create_schema()
            user, _ = await self.store.create_user(email="actor-regen@example.com", phone=None, password="user-password-strong")
            actor = await self.store.create_element(
                owner_id=user.id, kind="actor", name="陆昀", description="青衫书生，眉间一道浅疤",
                metadata={"task_id": "task-gone"},
            )
            return user, actor

        self.user, self.actor = asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        self.addCleanup(lambda: asyncio.run(self.store.close()))
        self.client = TestClient(app)
        self.cookie = {"auth_token": auth_service.generate_token(self.user.id)}
        for target, value in (
            ("app.api.element_api.ELEMENT_MEDIA_ROOT", root / "elements"),
            ("app.api.element_api.MEDIA_DIR", str(self.media)),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        uploaded = self.client.post(
            f"/api/elements/{self.actor.id}/files", data={"slot": "front"},
            files={"file": ("front.png", _png((200, 160, 140)), "image/png")}, cookies=self.cookie,
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.original_front = uploaded.json()["files"][0]["sha256"]

    def _result(self):
        return {
            "views": [{"view": view, "image_url": f"/media/new/{view}.png"} for view in IDENTITY_VIEW_ORDER],
            "sheet": "/media/new/sheet.png", "quality": {"passed": True}, "task_id": "",
        }

    def test_regenerates_in_the_background_and_files_all_five_identity_views(self):
        with patch.object(drama_api.service, "regenerate_library_actor", return_value=self._result()) as regenerate:
            response = self.client.post(f"/api/elements/{self.actor.id}/regenerate", json={"prompt": ""}, cookies=self.cookie)

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["metadata"]["regeneration"]["status"], "running")
        kwargs = regenerate.call_args.kwargs
        self.assertEqual(kwargs["name"], "陆昀")
        self.assertEqual(kwargs["task_ids"], ("task-gone",))
        self.assertIn("陆昀", kwargs["name_keys"])
        self.assertTrue(kwargs["reference"].startswith(b"\x89PNG"))

        element = self.client.get(f"/api/elements/{self.actor.id}", cookies=self.cookie).json()
        self.assertEqual({file["slot"] for file in element["files"]}, set(IDENTITY_VIEW_ORDER))
        front = next(file for file in element["files"] if file["slot"] == "front")
        self.assertNotEqual(front["sha256"], self.original_front)
        self.assertEqual(element["metadata"]["regeneration"]["status"], "done")
        self.assertTrue(element["metadata"]["five_view_passed"])
        self.assertEqual([view["view"] for view in element["metadata"]["views"]], list(IDENTITY_VIEW_ORDER))
        self.assertEqual(element["metadata"]["sheet_url"], "/media/new/sheet.png")

    def test_a_failed_regeneration_keeps_the_old_images_and_records_why(self):
        with patch.object(drama_api.service, "regenerate_library_actor", side_effect=RuntimeError("角色「陆昀」设定集重新生成未通过质检")):
            response = self.client.post(f"/api/elements/{self.actor.id}/regenerate", json={"prompt": ""}, cookies=self.cookie)

        self.assertEqual(response.status_code, 202, response.text)
        element = self.client.get(f"/api/elements/{self.actor.id}", cookies=self.cookie).json()
        self.assertEqual([file["sha256"] for file in element["files"]], [self.original_front])
        self.assertEqual(element["metadata"]["regeneration"]["status"], "failed")
        self.assertIn("未通过质检", element["metadata"]["regeneration"]["error"])
        self.assertNotIn("five_view_passed", element["metadata"])

    def test_missing_identity_views_replace_nothing(self):
        partial = self._result()
        partial["views"] = partial["views"][:3]
        with patch.object(drama_api.service, "regenerate_library_actor", return_value=partial):
            self.client.post(f"/api/elements/{self.actor.id}/regenerate", json={"prompt": ""}, cookies=self.cookie)

        element = self.client.get(f"/api/elements/{self.actor.id}", cookies=self.cookie).json()
        self.assertEqual(len(element["files"]), 1)
        self.assertIn("缺少身份视图", element["metadata"]["regeneration"]["error"])

    def test_a_running_regeneration_is_not_started_twice_but_a_stale_one_is(self):
        asyncio.run(self.store.merge_element_metadata(
            self.actor.id, self.user.id, {"regeneration": {"status": "running", "started_epoch": time.time()}},
        ))
        with patch.object(drama_api.service, "regenerate_library_actor", return_value=self._result()) as regenerate:
            busy = self.client.post(f"/api/elements/{self.actor.id}/regenerate", json={"prompt": ""}, cookies=self.cookie)
            self.assertEqual(busy.status_code, 409, busy.text)
            regenerate.assert_not_called()

            asyncio.run(self.store.merge_element_metadata(
                self.actor.id, self.user.id, {"regeneration": {"status": "running", "started_epoch": time.time() - 3600}},
            ))
            stale = self.client.post(f"/api/elements/{self.actor.id}/regenerate", json={"prompt": ""}, cookies=self.cookie)
            self.assertEqual(stale.status_code, 202, stale.text)
            regenerate.assert_called_once()


class LibraryActorRegenerationServiceTests(unittest.TestCase):
    """资产库演员挂在本人项目里就走项目的单角色重生成；项目没了就按资产库描述独立出图。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "media"
        (self.media / "old").mkdir(parents=True)
        Image.new("RGB", (64, 80), (200, 160, 140)).save(self.media / "old" / "portrait.png")
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(self.media))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        created = self.service.create_task(DramaCreateRequest(title_suggestion="渡口", llm_model="m", image_model="img-model"))
        self.task_id = created["task_id"]
        task = self.service.repo.get_task(self.task_id)
        task["owner_user_id"] = "owner-1"
        task["assets"]["3_characters"] = [{
            "name": "陆 昀", "role": "男主", "desc": "青衫书生",
            "sheet": "https://cdn.test/old/sheet.png",
            "views": [{"view": view, "image_url": f"/media/old/{view}.png"} for view in IDENTITY_VIEW_ORDER],
            "sheet_cells": [{"cell": "portrait", "image_url": "/media/old/portrait.png"}],
            "five_view_quality": {"passed": True, "issues": []},
        }]
        self.service.repo.save_task(self.task_id, task)

    def _render(self, *, passed=True, error=None):
        return {
            "sheet": "/media/new/sheet.png",
            "views": [{"view": view, "image_url": f"/media/new/{view}.png"} for view in IDENTITY_VIEW_ORDER],
            "cells": [{"cell": "portrait", "image_url": "/media/new/portrait.png"}],
            "quality": {"passed": passed, "issues": []}, "phase": "quality_error", "error": error,
        }

    def test_a_linked_project_character_is_regenerated_in_its_project(self):
        with (
            patch.object(self.service, "_render_actor_sheet", return_value=self._render()) as render,
            patch.object(self.service.gateway, "resolve_authorized_face", return_value=None),
        ):
            result = self.service.regenerate_library_actor(
                owner_id="owner-1", name="陆昀", name_keys={"陆昀"}, desc="",
                task_ids=("missing-task", self.task_id), reference=None,
            )

        self.assertEqual(result["task_id"], self.task_id)
        self.assertEqual(result["sheet"], "/media/new/sheet.png")
        self.assertEqual(render.call_args.kwargs["image_model"], "img-model")
        task = self.service.repo.get_task(self.task_id)
        self.assertEqual(task["assets"]["3_characters"][0]["sheet"], "/media/new/sheet.png")
        self.assertEqual(task["assets"][REGENERATION_KEY]["陆 昀"]["status"], "done")

    def test_another_owners_project_is_never_touched(self):
        with patch.object(self.service, "_render_actor_sheet", return_value=self._render()) as render:
            result = self.service.regenerate_library_actor(
                owner_id="someone-else", name="陆昀", name_keys={"陆昀"}, desc="青衫书生",
                task_ids=(self.task_id,), reference=b"\x89PNG-not-really",
            )

        self.assertEqual(result["task_id"], "")
        self.assertEqual(render.call_args.kwargs["name"], "陆昀")
        self.assertIsNone(render.call_args.kwargs["ref_images"])  # 读不出的旧图不挡出图
        task = self.service.repo.get_task(self.task_id)
        self.assertEqual(task["assets"]["3_characters"][0]["sheet"], "https://cdn.test/old/sheet.png")

    def test_an_orphan_actor_uses_its_existing_image_as_reference_and_fails_loudly(self):
        reference = (self.media / "old" / "portrait.png").read_bytes()
        with patch.object(self.service, "_render_actor_sheet", return_value=self._render()) as render:
            self.service.regenerate_library_actor(
                owner_id="owner-1", name="白小七", name_keys={"白小七"}, desc="红衣少女",
                task_ids=(), reference=reference,
            )
        self.assertTrue(render.call_args.kwargs["ref_images"][0].startswith("data:image/"))
        self.assertEqual(render.call_args.kwargs["desc"], "红衣少女")

        with patch.object(self.service, "_render_actor_sheet", return_value=self._render(passed=False)):
            with self.assertRaisesRegex(RuntimeError, "未通过质检"):
                self.service.regenerate_library_actor(
                    owner_id="owner-1", name="白小七", name_keys={"白小七"}, desc="", task_ids=(), reference=None,
                )

    def test_a_failed_project_regeneration_is_reported(self):
        with (
            patch.object(self.service, "_render_actor_sheet", return_value=self._render(passed=False)),
            patch.object(self.service.gateway, "resolve_authorized_face", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "未通过质检"):
                self.service.regenerate_library_actor(
                    owner_id="owner-1", name="陆昀", name_keys={"陆昀"}, desc="", task_ids=(self.task_id,),
                )


if __name__ == "__main__":
    unittest.main()

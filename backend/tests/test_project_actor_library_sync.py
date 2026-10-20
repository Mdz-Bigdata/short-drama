import asyncio
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.api import element_api
from app.core import media_compositor
from app.platform.store import PlatformStore
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.schema.production import IDENTITY_VIEW_ORDER
from app.service.drama_service import DramaService


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 64), color).save(buffer, format="PNG")
    return buffer.getvalue()


class ProjectActorLibrarySyncTests(unittest.TestCase):
    """项目里重新生成成功后，新身份视图同步到资产库里挂在该项目的同名数字演员。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db_url = f"sqlite+aiosqlite:///{root / 'library.sqlite3'}"
        self.media = root / "media"
        (self.media / "new").mkdir(parents=True)
        for index, view in enumerate(IDENTITY_VIEW_ORDER):
            (self.media / "new" / f"{view}.png").write_bytes(_png((30 * index, 80, 140)))
        for target, value in (
            ("app.api.element_api.ELEMENT_MEDIA_ROOT", root / "elements"),
            ("app.api.element_api.MEDIA_DIR", str(self.media)),
            ("app.api.element_api.settings.database_url", lambda: self.db_url),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        async def prepare():
            store = PlatformStore(self.db_url)
            try:
                await store.create_schema()
                user, _ = await store.create_user(email="sync@example.com", phone=None, password="user-password-strong")
                linked = await store.create_element(owner_id=user.id, kind="actor", name="侯府 嫡女", metadata={"task_id": "task-1"})
                other_project = await store.create_element(owner_id=user.id, kind="actor", name="侯府嫡女", metadata={"task_id": "task-2"})
                other_name = await store.create_element(owner_id=user.id, kind="actor", name="裴崇", metadata={"task_id": "task-1"})
                return user.id, linked.id, other_project.id, other_name.id
            finally:
                await store.close()

        self.owner, self.linked, self.other_project, self.other_name = asyncio.run(prepare())

    def _task(self, name="侯府嫡女", views=None):
        return {
            "task_id": "task-1", "owner_user_id": self.owner,
            "assets": {"3_characters": [{
                "name": name, "sheet": "/media/new/sheet.png",
                "views": views if views is not None else [
                    {"view": view, "image_url": f"/media/new/{view}.png"} for view in IDENTITY_VIEW_ORDER
                ],
            }]},
        }

    def _element(self, element_id):
        async def read():
            store = PlatformStore(self.db_url)
            try:
                return await store.get_element(element_id, self.owner)
            finally:
                await store.close()
        return asyncio.run(read())

    def test_files_the_new_views_only_into_the_same_named_actor_linked_to_that_project(self):
        self.assertEqual(element_api.sync_project_actor_to_library(self._task(), "侯府嫡女"), 1)

        linked = self._element(self.linked)
        self.assertEqual({file.slot for file in linked.files}, set(IDENTITY_VIEW_ORDER))
        self.assertTrue(linked.metadata_json["five_view_passed"])
        self.assertEqual(linked.metadata_json["sheet_url"], "/media/new/sheet.png")
        self.assertEqual(linked.metadata_json["synced_from_task"], "task-1")
        self.assertEqual(self._element(self.other_project).files, [])
        self.assertEqual(self._element(self.other_name).files, [])

    def test_an_incomplete_view_set_replaces_nothing(self):
        views = [{"view": "front", "image_url": "/media/new/front.png"}]
        self.assertEqual(element_api.sync_project_actor_to_library(self._task(views=views), "侯府嫡女"), 0)
        self.assertEqual(self._element(self.linked).files, [])

    def test_a_library_run_in_progress_files_its_own_result(self):
        async def mark():
            store = PlatformStore(self.db_url)
            try:
                await store.merge_element_metadata(
                    self.linked, self.owner, {"regeneration": {"status": "running", "started_epoch": time.time()}},
                )
            finally:
                await store.close()
        asyncio.run(mark())
        self.assertEqual(element_api.sync_project_actor_to_library(self._task(), "侯府嫡女"), 0)
        self.assertEqual(self._element(self.linked).files, [])

    def test_no_owner_or_unknown_character_is_a_no_op(self):
        task = self._task()
        task["owner_user_id"] = ""
        self.assertEqual(element_api.sync_project_actor_to_library(task, "侯府嫡女"), 0)
        self.assertEqual(element_api.sync_project_actor_to_library(self._task(), "不存在"), 0)


class RegenerationHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        media = Path(self.temp.name) / "media"
        (media / "old").mkdir(parents=True)
        Image.new("RGB", (64, 80), (200, 160, 140)).save(media / "old" / "portrait.png")
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(media))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.task_id = self.service.create_task(DramaCreateRequest(title_suggestion="渡口", llm_model="m", image_model="img"))["task_id"]
        task = self.service.repo.get_task(self.task_id)
        task["assets"]["3_characters"] = [{
            "name": "沈知微", "desc": "", "sheet": "old", "sheet_cells": [{"cell": "portrait", "image_url": "/media/old/portrait.png"}],
            "views": [{"view": view, "image_url": f"/media/old/{view}.png"} for view in IDENTITY_VIEW_ORDER],
        }]
        self.service.repo.save_task(self.task_id, task)

    def _render(self, passed=True):
        return {
            "sheet": "new", "views": [{"view": view, "image_url": f"/media/new/{view}.png"} for view in IDENTITY_VIEW_ORDER],
            "cells": [], "quality": {"passed": passed, "issues": []}, "phase": "quality_error", "error": None,
        }

    def test_the_hook_runs_with_the_updated_task_only_after_success(self):
        calls = []
        self.service.character_regenerated_hook = lambda task, name: calls.append((task["assets"]["3_characters"][0]["sheet"], name))
        with (
            patch.object(self.service, "_render_actor_sheet", return_value=self._render()),
            patch.object(self.service.gateway, "resolve_authorized_face", return_value=None),
        ):
            self.service.regenerate_character(self.task_id, "沈知微", background=False)
        self.assertEqual(calls, [("new", "沈知微")])

        with (
            patch.object(self.service, "_render_actor_sheet", return_value=self._render(passed=False)),
            patch.object(self.service.gateway, "resolve_authorized_face", return_value=None),
        ):
            self.service.regenerate_character(self.task_id, "沈知微", background=False)
        self.assertEqual(len(calls), 1)

    def test_a_failing_hook_never_undoes_the_project_result(self):
        def boom(task, name):
            raise RuntimeError("library down")
        self.service.character_regenerated_hook = boom
        with (
            patch.object(self.service, "_render_actor_sheet", return_value=self._render()),
            patch.object(self.service.gateway, "resolve_authorized_face", return_value=None),
        ):
            self.service.regenerate_character(self.task_id, "沈知微", background=False)
        task = self.service.repo.get_task(self.task_id)
        self.assertEqual(task["assets"]["3_characters"][0]["sheet"], "new")

    def test_the_api_service_is_wired_to_the_library(self):
        from app.api import drama_api
        self.assertIs(drama_api.service.character_regenerated_hook, element_api.sync_project_actor_to_library)


if __name__ == "__main__":
    unittest.main()

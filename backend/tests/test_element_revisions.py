# -*- coding: utf-8 -*-
"""资产库的版本历史：每次改动前记一版，可以回到旧版本；被引用的旧文件不删，配额连历史一起算。"""
import asyncio
import hashlib
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.api.auth_api import auth_service
from app.platform.dependencies import get_platform_store
from app.platform.models import ElementRevision
from app.platform.store import PlatformStore
from main import app


def _png(label: str) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + label.encode()


class ElementRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "revisions.sqlite3"
        self.store = PlatformStore(f"sqlite+aiosqlite:///{self.database}")
        self.image_root = Path(self.temp.name) / "private" / "elements"

        async def prepare():
            await self.store.create_schema()
            self.user, _ = await self.store.create_user(email="rev@example.com", phone=None, password="user-password-strong")
            self.other, _ = await self.store.create_user(email="rev-other@example.com", phone=None, password="user-password-strong")
            self.prop = await self.store.create_element(owner_id=self.user.id, kind="prop", name="旧名", description="旧描述", metadata={})

        asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        media = patch("app.api.element_api.ELEMENT_MEDIA_ROOT", self.image_root)
        media.start()
        self.addCleanup(media.stop)
        # 项目一侧的同步换成假的，测试不碰真实的项目库；要看调用的测试自己再套一层。
        sync = patch("app.service.asset_sync.element_changed", return_value={"tasks": [], "renamed": False})
        sync.start()
        self.addCleanup(sync.stop)
        # 上传按来源地址限流；这组测试上传得多，用自己的地址，不占其他测试的额度。
        self.client = TestClient(
            app, cookies={"auth_token": auth_service.generate_token(self.user.id)}, client=(f"revisions-{uuid.uuid4().hex}", 50000),
        )
        self.stranger = {"auth_token": auth_service.generate_token(self.other.id)}

    def tearDown(self):
        app.dependency_overrides.clear()
        asyncio.run(self.store.close())
        self.temp.cleanup()

    def _upload(self, label: str, slot: str = "reference", element_id: str | None = None):
        response = self.client.post(
            f"/api/elements/{element_id or self.prop.id}/files",
            data={"slot": slot},
            files={"file": (f"{label}.png", _png(label), "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _revisions(self, element_id: str | None = None) -> list[dict]:
        response = self.client.get(f"/api/elements/{element_id or self.prop.id}/revisions")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"]

    def _on_disk(self) -> set[bytes]:
        return {path.read_bytes() for path in self.image_root.rglob("*.png")}

    def test_each_change_writes_a_revision_listed_newest_first(self):
        self._upload("a")
        self.assertEqual(self.client.patch(f"/api/elements/{self.prop.id}", json={"name": "新名"}).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/elements/{self.prop.id}", json={"description": "新描述"}).status_code, 200)
        replaced = self._upload("b")
        deleted = self.client.delete(f"/api/elements/{self.prop.id}/files/{replaced['files'][0]['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)

        items = self._revisions()
        self.assertEqual([item["revision"] for item in items], [5, 4, 3, 2, 1])
        self.assertEqual([item["reason"] for item in items], ["file_delete", "file", "edit", "rename", "file"])
        # 每一版是改动前的样子。
        self.assertEqual((items[3]["name"], items[3]["description"]), ("旧名", "旧描述"))
        self.assertEqual((items[2]["name"], items[2]["description"]), ("新名", "旧描述"))
        self.assertEqual(items[4]["files"], [])
        self.assertEqual([entry["slot"] for entry in items[0]["files"]], ["reference"])
        self.assertEqual([item["version"] for item in items], sorted((item["version"] for item in items), reverse=True))
        datetime.fromisoformat(items[0]["created_at"])
        # 删掉、换掉的图都还在磁盘上，供恢复。
        self.assertEqual(self._on_disk(), {_png("a"), _png("b")})

    def test_an_unchanged_save_bumps_the_version_without_a_revision(self):
        before = self.client.get(f"/api/elements/{self.prop.id}").json()
        same = self.client.patch(f"/api/elements/{self.prop.id}", json={"name": "旧名"})
        self.assertEqual(same.status_code, 200, same.text)
        self.assertEqual(same.json()["version"], before["version"] + 1)
        self.assertEqual(self._revisions(), [])

    def test_restore_brings_back_the_old_name_description_and_image(self):
        self._upload("a")
        self.client.patch(f"/api/elements/{self.prop.id}", json={"name": "新名", "description": "新描述"})
        self._upload("b")
        old = next(item for item in self._revisions() if item["reason"] == "rename")
        self.assertEqual(old["name"], "旧名")
        old_file = self.client.get(old["files"][0]["url"])
        self.assertEqual(old_file.status_code, 200, old_file.text)
        self.assertEqual(old_file.content, _png("a"))
        self.assertEqual(old_file.headers["cache-control"], "private, no-store")

        restored = self.client.post(f"/api/elements/{self.prop.id}/revisions/{old['revision']}/restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        body = restored.json()
        self.assertEqual((body["name"], body["description"]), ("旧名", "旧描述"))
        self.assertIn("folder_id", body)
        self.assertIn("sync", body)
        self.assertEqual(self.client.get(body["files"][0]["url"]).content, _png("a"))
        detail = self.client.get(f"/api/elements/{self.prop.id}").json()
        self.assertEqual({key: detail[key] for key in ("name", "description", "version")},
                         {key: body[key] for key in ("name", "description", "version")})

        # 恢复前的那一版也记下了，恢复本身可以撤回。
        latest = self._revisions()[0]
        self.assertEqual((latest["reason"], latest["name"]), ("restore", "新名"))
        self.assertEqual(self.client.get(latest["files"][0]["url"]).content, _png("b"))
        again = self.client.post(f"/api/elements/{self.prop.id}/revisions/{latest['revision']}/restore")
        self.assertEqual(again.json()["name"], "新名")
        self.assertEqual(self.client.get(again.json()["files"][0]["url"]).content, _png("b"))

    def test_restore_drops_slots_that_did_not_exist_then(self):
        self._upload("a")
        self._upload("detail", slot="detail")
        first = next(item for item in self._revisions() if item["revision"] == 2)
        self.assertEqual([entry["slot"] for entry in first["files"]], ["reference"])
        restored = self.client.post(f"/api/elements/{self.prop.id}/revisions/2/restore").json()
        self.assertEqual([item["slot"] for item in restored["files"]], ["reference"])
        empty = self.client.post(f"/api/elements/{self.prop.id}/revisions/1/restore").json()
        self.assertEqual((empty["files"], empty["status"]), ([], "draft"))

    def test_history_is_owner_only_and_a_missing_revision_is_404(self):
        self._upload("a")
        self._upload("b")
        url = self._revisions()[0]["files"][0]["url"]
        self.assertEqual(self.client.get(url, cookies=self.stranger).status_code, 404)
        self.assertEqual(self.client.get(f"/api/elements/{self.prop.id}/revisions", cookies=self.stranger).status_code, 404)
        self.assertEqual(self.client.post(f"/api/elements/{self.prop.id}/revisions/1/restore", cookies=self.stranger).status_code, 404)
        self.assertEqual(self.client.post(f"/api/elements/{self.prop.id}/revisions/99/restore").status_code, 404)
        self.assertEqual(self.client.get(f"/api/elements/{self.prop.id}/revisions/2/files/nope/content").status_code, 404)

    def test_trimming_beyond_the_limit_deletes_only_files_nobody_references(self):
        with patch("app.platform.store.REVISION_LIMIT", 3):
            self._upload("x", slot="detail")  # 一直在用，不能删
            for label in ("a", "b", "c", "d"):
                self._upload(label)
            self.assertEqual(len(self._revisions()), 3)
            # 裁掉的两版只引用了 x，x 还在用。
            self.assertEqual(self._on_disk(), {_png(label) for label in ("x", "a", "b", "c", "d")})
            self._upload("e")
        items = self._revisions()
        self.assertEqual([item["revision"] for item in items], [6, 5, 4])
        # 引用 a 的那一版被裁，a 没人再用了才删。
        self.assertEqual(self._on_disk(), {_png(label) for label in ("x", "b", "c", "d", "e")})

    def test_without_a_cleanup_hook_trimming_never_strands_a_file(self):
        async def run():
            with patch("app.platform.store.REVISION_LIMIT", 1):
                for index in range(3):
                    await self.store.add_element_file(
                        element_id=self.prop.id, owner_id=self.user.id, slot="reference",
                        storage_path=f"{self.user.id}/{self.prop.id}/{index}.png", mime_type="image/png",
                        size_bytes=1, sha256=str(index),
                    )
            return await self.store.list_element_revisions(self.user.id, self.prop.id)

        revisions = asyncio.run(run())
        # 没法删文件时只裁掉不独占文件的那一版(空的第一版)，引用 0.png、1.png 的都留着。
        self.assertEqual([item.revision for item in revisions], [3, 2])

    def test_quota_counts_files_kept_in_history(self):
        size = len(_png("a"))
        with patch("app.platform.store.MAX_ELEMENT_STORAGE_BYTES", size * 2 + 1):
            self._upload("a")
            self._upload("b")
            refused = self.client.post(
                f"/api/elements/{self.prop.id}/files",
                data={"slot": "reference"},
                files={"file": ("c.png", _png("c"), "image/png")},
            )
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertIn("存储空间", refused.json()["detail"])
        self.assertEqual(self._on_disk(), {_png("a"), _png("b")})
        live = self.client.get(f"/api/elements/{self.prop.id}").json()["files"][0]
        self.assertEqual(live["sha256"], hashlib.sha256(_png("b")).hexdigest())

    def test_deleting_the_element_removes_its_history_files(self):
        self._upload("a")
        uploaded = self._upload("b")
        self.client.delete(f"/api/elements/{self.prop.id}/files/{uploaded['files'][0]['id']}")
        self.assertEqual(self._on_disk(), {_png("a"), _png("b")})
        self.assertEqual(self.client.delete(f"/api/elements/{self.prop.id}").status_code, 200)
        self.assertEqual(self._on_disk(), set())

        async def remaining():
            async with self.store.sessions() as session:
                return await session.scalar(select(func.count()).select_from(ElementRevision))

        self.assertEqual(asyncio.run(remaining()), 0)

    def test_element_detail_says_which_folder_it_is_in(self):
        self.assertIsNone(self.client.get(f"/api/elements/{self.prop.id}").json()["folder_id"])
        folder = self.client.post("/api/elements/folders", json={"name": "道具组"}).json()["id"]
        self.client.post("/api/elements/folders/move", json={"element_ids": [self.prop.id], "folder_id": folder})
        self.assertEqual(self.client.get(f"/api/elements/{self.prop.id}").json()["folder_id"], folder)

    def test_mutations_tell_the_projects_and_report_the_sync(self):
        calls = []

        def fake(element, *, reason, old_name=None):
            calls.append((dict(element), reason, old_name))
            return {"tasks": [{"task_id": "t1", "shots_marked": 1}], "renamed": old_name is not None}

        actor = asyncio.run(self.store.create_element(owner_id=self.user.id, kind="actor", name="少年林夏", metadata={}))
        with patch("app.service.asset_sync.element_changed", side_effect=fake):
            renamed = self.client.patch(f"/api/elements/{self.prop.id}", json={"name": "新名"}).json()
            edited = self.client.patch(f"/api/elements/{self.prop.id}", json={"description": "新描述"}).json()
            uploaded = self._upload("a")
            deleted = self.client.delete(f"/api/elements/{self.prop.id}/files/{uploaded['files'][0]['id']}").json()
            sized = self.client.put(f"/api/elements/{self.prop.id}/prop-size", json={"length_cm": 30}).json()
            restored = self.client.post(f"/api/elements/{self.prop.id}/revisions/1/restore").json()
            varied = self.client.put(f"/api/elements/{actor.id}/variant", json={"of": "林夏", "label": "少年"}).json()
            cleared = self.client.delete(f"/api/elements/{actor.id}/variant").json()

        self.assertEqual(renamed["sync"], {"tasks": [{"task_id": "t1", "shots_marked": 1}], "renamed": True})
        self.assertEqual(renamed["name"], "新名")
        for body in (edited, uploaded, deleted, sized, restored, varied, cleared):
            self.assertIn("sync", body)
        self.assertEqual(
            [(reason, old_name) for _element, reason, old_name in calls],
            [("rename", "旧名"), ("edit", None), ("file", None), ("file_delete", None), ("prop_size", None),
             ("restore", "新名"), ("variant", None), ("variant", None)],
        )
        snapshot = calls[0][0]
        self.assertEqual(set(snapshot), {"id", "owner_id", "kind", "name", "description", "version", "metadata"})
        self.assertEqual((snapshot["id"], snapshot["owner_id"], snapshot["name"]), (self.prop.id, self.user.id, "新名"))
        self.assertEqual(restored["name"], "旧名")
        reasons = [item["reason"] for item in self._revisions()]
        self.assertEqual(reasons, ["restore", "prop_size", "file_delete", "file", "edit", "rename"])

    def test_a_failed_sync_never_fails_the_request(self):
        with patch("app.service.asset_sync.element_changed", side_effect=RuntimeError("projects down")):
            response = self.client.patch(f"/api/elements/{self.prop.id}", json={"name": "新名"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sync"], {"error": "projects down"})
        self.assertEqual(response.json()["name"], "新名")

    def test_usages_come_from_asset_sync(self):
        found = [{"task_id": "t1", "title": "第一集", "scene_id": "s1", "shot_id": "1", "shot_uid": "u1",
                  "in_storyboard": True, "in_video": False}]
        with patch("app.service.asset_sync.usages", return_value=found) as usages:
            response = self.client.get(f"/api/elements/{self.prop.id}/usages")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"items": found})
        snapshot = usages.call_args.args[0]
        self.assertEqual((snapshot["id"], snapshot["kind"], snapshot["name"]), (self.prop.id, "prop", "旧名"))
        self.assertEqual(self.client.get(f"/api/elements/{self.prop.id}/usages", cookies=self.stranger).status_code, 404)

    def test_paging_order_is_stable_when_updated_at_ties(self):
        async def tie():
            for name in ("甲", "乙", "丙"):
                await self.store.create_element(owner_id=self.user.id, kind="prop", name=name)
            async with self.store.engine.begin() as connection:
                await connection.execute(
                    text("UPDATE element_assets SET updated_at = :moment"), {"moment": datetime(2026, 1, 1, tzinfo=timezone.utc)},
                )

        asyncio.run(tie())
        pages = [
            self.client.get("/api/elements", params={"kind": "prop", "page": page, "page_size": 1}).json()["items"][0]["id"]
            for page in (1, 2, 3, 4)
        ]
        self.assertEqual(pages, sorted(pages))
        self.assertEqual(len(set(pages)), 4)

    def test_a_database_from_before_history_gets_the_table_on_startup(self):
        async def downgrade_and_restart():
            async with self.store.engine.begin() as connection:
                await connection.execute(text("DROP TABLE element_revisions"))
                await connection.execute(text("UPDATE alembic_version SET version_num = '0004_refund_approvals'"))
            await self.store.create_schema()
            async with self.store.engine.connect() as connection:
                return (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()

        self.assertEqual(asyncio.run(downgrade_and_restart()), "0005_element_revisions")
        self._upload("a")
        self.assertEqual(len(self._revisions()), 1)


if __name__ == "__main__":
    unittest.main()

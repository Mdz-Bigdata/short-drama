# -*- coding: utf-8 -*-
"""Element library folders: an optional, separate layer that existing elements never need."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.auth_api import auth_service
from app.platform.dependencies import get_platform_store
from app.platform.store import MAX_ELEMENT_FOLDERS_PER_OWNER, PlatformStore
from main import app


class ElementFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "library.sqlite3"
        self.store = PlatformStore(f"sqlite+aiosqlite:///{self.database}")

        async def prepare():
            await self.store.create_schema()
            self.user, _ = await self.store.create_user(email="lib@example.com", phone=None, password="user-password-strong")
            self.other, _ = await self.store.create_user(email="other@example.com", phone=None, password="user-password-strong")
            self.a = await self.store.create_element(owner_id=self.user.id, kind="prop", name="信封", description="", metadata={})
            self.b = await self.store.create_element(owner_id=self.user.id, kind="prop", name="雨伞", description="", metadata={})
            self.c = await self.store.create_element(owner_id=self.user.id, kind="scene", name="客厅", description="", metadata={})
            self.foreign = await self.store.create_element(owner_id=self.other.id, kind="prop", name="别人的", description="", metadata={})

        asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.client = TestClient(app, cookies={"auth_token": auth_service.generate_token(self.user.id)})

    def tearDown(self):
        app.dependency_overrides.clear()
        asyncio.run(self.store.close())
        self.temp.cleanup()

    def _folder(self, name="道具组", **body):
        response = self.client.post("/api/elements/folders", json={"name": name, **body})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _move(self, ids, folder_id):
        return self.client.post("/api/elements/folders/move", json={"element_ids": ids, "folder_id": folder_id})

    def _names(self, **params):
        response = self.client.get("/api/elements", params={"kind": "prop", **params})
        self.assertEqual(response.status_code, 200, response.text)
        return {item["name"] for item in response.json()["items"]}, response.json()

    def test_existing_elements_keep_working_without_any_folder(self):
        names, body = self._names()
        self.assertEqual(names, {"信封", "雨伞"})
        self.assertEqual(body["total"], 2)
        self.assertTrue(all(item["folder_id"] is None for item in body["items"]))
        self.assertEqual(self.client.get(f"/api/elements/{self.a.id}").status_code, 200)
        listing = self.client.get("/api/elements/folders", params={"kind": "prop"}).json()
        self.assertEqual(listing, {"folders": [], "total": 2, "unfiled": 2})

    def test_a_database_from_before_folders_gets_the_tables_on_startup(self):
        async def drop_and_restart():
            async with self.store.engine.begin() as connection:
                await connection.execute(text("DROP TABLE element_folder_members"))
                await connection.execute(text("DROP TABLE element_folders"))
            await self.store.create_schema()

        asyncio.run(drop_and_restart())
        self.assertEqual(self._names()[0], {"信封", "雨伞"})
        self._folder()

    def test_all_folder_and_unfiled_views(self):
        folder = self._folder()
        self.assertEqual(self._move([self.a.id], folder).status_code, 200)
        self.assertEqual(self._names()[0], {"信封", "雨伞"})
        names, body = self._names(folder=folder)
        self.assertEqual(names, {"信封"})
        self.assertEqual(body["items"][0]["folder_id"], folder)
        self.assertEqual(self._names(folder="unfiled")[0], {"雨伞"})
        listing = self.client.get("/api/elements/folders", params={"kind": "prop"}).json()
        self.assertEqual(listing["folders"][0]["count"], 1)
        self.assertEqual((listing["total"], listing["unfiled"]), (2, 1))

    def test_moving_in_out_and_between_folders_keeps_one_place(self):
        first, second = self._folder("甲"), self._folder("乙")
        self._move([self.a.id], first)
        self._move([self.a.id], second)
        self.assertEqual(self._names(folder=first)[0], set())
        self.assertEqual(self._names(folder=second)[0], {"信封"})
        self.assertEqual(self._move([self.a.id], None).json()["folder_id"], None)
        self.assertEqual(self._names(folder=second)[0], set())
        self.assertIn("信封", self._names(folder="unfiled")[0])

    def test_counts_cover_each_kind_separately(self):
        folder = self._folder()
        self._move([self.a.id, self.c.id], folder)
        self.assertEqual(self.client.get("/api/elements/folders", params={"kind": "scene"}).json()["folders"][0]["count"], 1)
        self.assertEqual(self.client.get("/api/elements/folders").json()["folders"][0]["count"], 2)

    def test_deleting_a_folder_keeps_its_elements(self):
        folder = self._folder()
        self._move([self.a.id], folder)
        self.assertEqual(self.client.delete(f"/api/elements/folders/{folder}").status_code, 200)
        self.assertEqual(self._names(folder="unfiled")[0], {"信封", "雨伞"})
        self.assertEqual(self.client.delete(f"/api/elements/folders/{folder}").status_code, 404)

    def test_deleting_an_element_leaves_no_ghost_count_or_cover(self):
        folder = self._folder(cover_element_id=self.a.id)
        self._move([self.a.id, self.b.id], folder)
        self.assertEqual(self.client.delete(f"/api/elements/{self.a.id}").status_code, 200)
        [entry] = self.client.get("/api/elements/folders").json()["folders"]
        self.assertEqual(entry["count"], 1)
        self.assertIsNone(entry["cover_element_id"])

    def test_cover_is_optional_settable_and_clearable(self):
        folder = self._folder()
        listing = self.client.get("/api/elements/folders").json()["folders"][0]
        self.assertIsNone(listing["cover_element_id"])
        self.assertIsNone(listing["cover_url"])
        updated = self.client.patch(f"/api/elements/folders/{folder}", json={"cover_element_id": self.a.id})
        self.assertEqual(updated.json()["cover_element_id"], self.a.id)
        renamed = self.client.patch(f"/api/elements/folders/{folder}", json={"name": "新名"}).json()
        self.assertEqual((renamed["name"], renamed["cover_element_id"]), ("新名", self.a.id))
        cleared = self.client.patch(f"/api/elements/folders/{folder}", json={"cover_element_id": None})
        self.assertIsNone(cleared.json()["cover_element_id"])
        refused = self.client.patch(f"/api/elements/folders/{folder}", json={"cover_element_id": self.foreign.id})
        self.assertEqual(refused.status_code, 422)

    def test_names_are_validated_per_owner(self):
        self._folder("甲")
        self.assertEqual(self.client.post("/api/elements/folders", json={"name": "甲"}).status_code, 422)
        self.assertEqual(self.client.post("/api/elements/folders", json={"name": "   "}).status_code, 422)
        other = TestClient(app, cookies={"auth_token": auth_service.generate_token(self.other.id)})
        self.assertEqual(other.post("/api/elements/folders", json={"name": "甲"}).status_code, 201)

    def test_folder_quota(self):
        async def fill():
            for index in range(MAX_ELEMENT_FOLDERS_PER_OWNER):
                await self.store.create_element_folder(self.user.id, f"f{index}")
        asyncio.run(fill())
        refused = self.client.post("/api/elements/folders", json={"name": "再来一个"})
        self.assertEqual(refused.status_code, 422)

    def test_other_peoples_folders_and_elements_stay_out_of_reach(self):
        folder = self._folder()
        self._move([self.a.id], folder)
        other = TestClient(app, cookies={"auth_token": auth_service.generate_token(self.other.id)})
        self.assertEqual(other.get("/api/elements/folders").json()["folders"], [])
        self.assertEqual(other.patch(f"/api/elements/folders/{folder}", json={"name": "x"}).status_code, 404)
        self.assertEqual(other.delete(f"/api/elements/folders/{folder}").status_code, 404)
        self.assertEqual(other.post("/api/elements/folders/move", json={"element_ids": [self.foreign.id], "folder_id": folder}).status_code, 404)
        self.assertEqual(self._move([self.foreign.id], folder).status_code, 404)
        self.assertEqual(self._move([self.a.id, self.foreign.id], None).status_code, 404)
        self.assertEqual(self._names(folder=folder)[0], {"信封"})
        self.assertEqual(self.client.get("/api/elements/folders").status_code, 200)

    def test_needs_a_signed_in_person(self):
        self.assertEqual(TestClient(app).get("/api/elements/folders").status_code, 401)


if __name__ == "__main__":
    unittest.main()

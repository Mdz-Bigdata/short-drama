"""The account's asset library against its limits: what the storage meter is drawn from."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import element_api
from app.api.auth_api import auth_service
from app.platform import store as store_module
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from main import app


class StorageUsageViewTests(unittest.TestCase):
    def view(self, used: int, count: int = 0) -> dict:
        return element_api.storage_usage_view({"used_bytes": used, "quota_bytes": 1000, "asset_count": count, "asset_quota": 100})

    def test_the_fuller_of_bytes_and_asset_count_sets_the_level(self):
        self.assertEqual(self.view(100)["level"], "ok")
        self.assertEqual(self.view(700)["level"], "warning")
        self.assertEqual(self.view(899)["level"], "warning")
        self.assertEqual(self.view(900)["level"], "danger")
        self.assertEqual(self.view(100, count=95)["level"], "danger", "few bytes, but the asset count is nearly spent")
        self.assertEqual(self.view(100, count=95)["share"], 0.95)

    def test_what_is_left_never_goes_below_nothing(self):
        over = self.view(1500, count=130)
        self.assertEqual((over["remaining_bytes"], over["remaining_assets"], over["share"], over["level"]), (0, 0, 1.0, "danger"))


class StorageUsageApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'api.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            self.user, _ = await self.store.create_user(email="meter@example.com", phone=None, password="user-password-strong")
            self.other, _ = await self.store.create_user(email="other@example.com", phone=None, password="user-password-strong")
            for owner, name, size in ((self.user, "磨刀石", 300), (self.user, "油灯", 450), (self.other, "别人的", 9999)):
                element = await self.store.create_element(owner_id=owner.id, kind="prop", name=name)
                await self.store.add_element_file(
                    element_id=element.id, owner_id=owner.id, slot="reference", storage_path=f"{element.id}/a.png",
                    mime_type="image/png", size_bytes=size, sha256="0" * 64,
                )

        asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        asyncio.run(self.store.close())
        self.temp.cleanup()

    def test_the_meter_counts_the_caller_s_own_files_against_the_limits(self):
        self.assertEqual(self.client.get("/api/elements/storage-usage").status_code, 401, "the meter is the signed-in account's own")
        cookie = {"auth_token": auth_service.generate_token(self.user.id)}
        with patch.object(store_module, "MAX_ELEMENT_STORAGE_BYTES", 1000), patch.object(store_module, "MAX_ELEMENT_ASSETS_PER_OWNER", 10):
            answer = self.client.get("/api/elements/storage-usage", cookies=cookie)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json(), {
            "used_bytes": 750, "quota_bytes": 1000, "remaining_bytes": 250, "asset_count": 2, "asset_quota": 10, "remaining_assets": 8,
            "share": 0.75, "level": "warning",
        })


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""拍摄道具页签把车辆、商品一起列出：类型本身不变(剧本车辆清单、带货商品检查照旧)，只是同一页里看。"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.api.auth_api import auth_service
from main import app


class PropTabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'p.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            self.user, _ = await self.store.create_user(email="props@example.com", phone=None, password="prop-tab-password")
            for kind, name, task in (("prop", "断水刀", "t1"), ("vehicle", "黑色轿车", "t1"), ("product", "静音吹风机", "t1"),
                                     ("scene", "磨刀铺", "t1"), ("vehicle", "别的项目的车", "t2")):
                await self.store.create_element(owner_id=self.user.id, kind=kind, name=name, metadata={"task_id": task})

        asyncio.run(prepare())
        self.addCleanup(lambda: asyncio.run(self.store.close()))
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.cookies = {"auth_token": auth_service.generate_token(self.user.id)}

    def _names(self, query: str) -> tuple[set[str], int]:
        response = self.client.get(f"/api/elements?{query}", cookies=self.cookies)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        return {item["name"] for item in body["items"]}, body["total"]

    def test_the_prop_tab_lists_vehicles_and_products_too_and_kinds_are_unchanged(self):
        names, total = self._names("kind=prop&include=vehicle,product&task_id=t1")
        self.assertEqual(names, {"断水刀", "黑色轿车", "静音吹风机"})
        self.assertEqual(total, 3)
        everything, _ = self._names("kind=prop&include=vehicle,product&page_size=100")
        self.assertIn("别的项目的车", everything, "without a project every library item of those kinds is listed")
        self.assertEqual(self._names("kind=prop&task_id=t1")[0], {"断水刀"}, "without include only props, as before")
        kinds = {item["name"]: item["kind"] for item in self.client.get("/api/elements?kind=prop&include=vehicle,product&task_id=t1", cookies=self.cookies).json()["items"]}
        self.assertEqual(kinds["黑色轿车"], "vehicle", "the stored kind is not rewritten")

    def test_folder_counts_follow_the_tab_too(self):
        response = self.client.get("/api/elements/folders?kind=prop&include=vehicle,product", cookies=self.cookies)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 4, "prop + two vehicles + product, the whole library")
        self.assertEqual(self.client.get("/api/elements/folders?kind=prop", cookies=self.cookies).json()["total"], 1)

    def test_an_unknown_kind_is_refused(self):
        self.assertEqual(self.client.get("/api/elements?kind=prop&include=spaceship", cookies=self.cookies).status_code, 422)


if __name__ == "__main__":
    unittest.main()

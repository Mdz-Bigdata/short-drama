import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.api.drama_api import _import_production_asset_candidates
from app.core.element_library_reuse import find_library_characters
from app.core.production_asset_extractor import extract_production_assets
from app.platform.store import PlatformStore


def _five_views(prefix: str) -> list[dict[str, str]]:
    return [
        {"view": view, "image_url": f"/media/{prefix}/{view}.png"}
        for view in ("front", "front_three_quarter", "profile", "rear_three_quarter", "back")
    ]


class ProductionAssetLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'library.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            user, _ = await self.store.create_user(
                email="library@example.com", phone=None, password="library-password-strong"
            )
            return user.id

        self.owner = asyncio.run(prepare())
        self.addCleanup(lambda: asyncio.run(self.store.close()))

    def _import(self, task_id: str, kind: str, candidates: list[dict]) -> dict:
        return asyncio.run(_import_production_asset_candidates(
            task_id=task_id, kind=kind, candidates=candidates, owner_id=self.owner, store=self.store,
        ))

    def test_import_links_same_name_assets_from_other_projects_instead_of_recreating(self):
        old = asyncio.run(self.store.create_element(
            owner_id=self.owner, kind="prop", name="青铜剑", description="旧项目的剑",
            metadata={"task_id": "task-old", "task_ids": ["task-old"]},
        ))
        candidates = [
            {"name": "青铜 剑", "description": "新项目也用这把剑", "image_url": ""},
            {"name": "玉佩", "description": "新道具", "image_url": ""},
        ]

        first = self._import("task-new", "prop", candidates)
        again = self._import("task-new", "prop", candidates)

        self.assertEqual((first["created"], first["reused"], first["skipped"]), (1, 1, 0))
        self.assertEqual(first["reused_items"][0]["id"], old.id)
        self.assertEqual((again["created"], again["reused"], again["skipped"]), (0, 0, 2))
        linked = asyncio.run(self.store.get_element(old.id, self.owner))
        self.assertEqual(linked.metadata_json["task_id"], "task-old")
        self.assertEqual(linked.metadata_json["task_ids"], ["task-old", "task-new"])
        self.assertEqual(linked.description, "旧项目的剑")

        new_scope, new_total = asyncio.run(self.store.list_elements(self.owner, "prop", 1, 50, task_id="task-new"))
        old_scope, old_total = asyncio.run(self.store.list_elements(self.owner, "prop", 1, 50, task_id="task-old"))
        everything, total = asyncio.run(self.store.list_elements(self.owner, "prop", 1, 50))
        self.assertEqual(({item.name for item in new_scope}, new_total), ({"青铜剑", "玉佩"}, 2))
        self.assertEqual(({item.name for item in old_scope}, old_total), ({"青铜剑"}, 1))
        self.assertEqual(total, 2)

    def test_actor_import_records_approved_views_and_a_later_project_reuses_them(self):
        task = {
            "task_id": "task-old",
            "owner_user_id": self.owner,
            "assets": {"3_characters": [{
                "name": "沈砚", "role": "主角", "desc": "长发束起的青年",
                "sheet": "/media/sheets/shen.png", "views": _five_views("shen"),
                "five_view_quality": {"passed": True},
            }, {
                "name": "无名侍卫", "role": "配角", "desc": "未通过质检",
                "sheet": "/media/sheets/guard.png", "views": _five_views("guard"),
                "five_view_quality": {"passed": False},
            }]},
        }
        candidates = extract_production_assets(task, "actor")
        result = self._import("task-old", "actor", candidates)
        self.assertEqual(result["created"], 2)

        approved, rejected = [
            next(item for item in asyncio.run(self.store.list_all_elements(self.owner, "actor")) if item.name == name)
            for name in ("沈砚", "无名侍卫")
        ]
        self.assertTrue(approved.metadata_json["five_view_passed"])
        self.assertEqual(len(approved.metadata_json["views"]), 5)
        self.assertEqual(approved.metadata_json["sheet_url"], "/media/sheets/shen.png")
        self.assertNotIn("views", rejected.metadata_json)
        self.assertEqual(self._import("task-old", "actor", candidates)["skipped"], 2)

        with patch("app.core.element_library_reuse.PlatformStore", return_value=self.store), \
                patch.object(self.store, "close", return_value=asyncio.sleep(0)), \
                patch("app.core.element_library_reuse._local_media_exists", return_value=True):
            records = find_library_characters(
                {"task_id": "task-new", "owner_user_id": self.owner}, ["沈砚", "无名侍卫", "陌生人"],
            )
        self.assertEqual(set(records), {"沈砚"})
        record = records["沈砚"]
        self.assertTrue(record["five_view_quality"]["passed"])
        self.assertEqual(record["five_view_quality"]["reused_from_library"], approved.id)
        self.assertEqual([view["view"] for view in record["views"]], [view["view"] for view in _five_views("x")])
        self.assertEqual(record["sheet"], "/media/sheets/shen.png")
        relinked = asyncio.run(self.store.get_element(approved.id, self.owner))
        self.assertEqual(relinked.metadata_json["task_ids"], ["task-old", "task-new"])

    def test_library_reuse_never_blocks_generation(self):
        self.assertEqual(find_library_characters({"task_id": "t"}, ["沈砚"]), {})
        broken = SimpleNamespace(
            list_all_elements=lambda *_: (_ for _ in ()).throw(RuntimeError("db down")),
        )
        with patch("app.core.element_library_reuse.PlatformStore", return_value=broken):
            self.assertEqual(
                find_library_characters({"task_id": "t", "owner_user_id": self.owner}, ["沈砚"]), {},
            )


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""捏脸写回元素库：只认本项目绑定的同名数字演员，元素库出错不打断保存。"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core import face_sculpt_sync as sync


def element(element_id, name, *, task_id="t1", owner_id="u1", kind="actor", aliases=None, description="旧描述"):
    metadata = {"task_id": task_id}
    if aliases:
        metadata["aliases"] = aliases
    return SimpleNamespace(id=element_id, owner_id=owner_id, kind=kind, name=name, description=description, metadata_json=metadata)


class FakeStore:
    """只记调用的元素库：``fail`` 设了异常就在读的时候抛。"""

    def __init__(self, elements=(), page_size=None):
        self.elements = list(elements)
        self.page_size = page_size
        self.listed = []
        self.updates = []
        self.fail = None
        self.closed = False

    async def list_elements(self, owner_id, kind, page, size):
        if self.fail is not None:
            raise self.fail
        self.listed.append((owner_id, kind, page, size))
        size = self.page_size or size
        mine = [item for item in self.elements if item.owner_id == owner_id and item.kind == kind]
        return mine[(page - 1) * size:page * size], len(mine)

    async def update_element(self, element_id, owner_id, *, name, description):
        self.updates.append({"element_id": element_id, "owner_id": owner_id, "name": name, "description": description})
        item = next(item for item in self.elements if item.id == element_id and item.owner_id == owner_id)
        item.description = description
        return item

    async def close(self):
        self.closed = True


def _task(**extra):
    return {
        "task_id": "t1", "owner_user_id": "u1",
        "assets": {"3_characters": [{"name": "林婉", "desc": "女主角；鹅蛋脸", **extra}]},
    }


class AsyncSyncTests(unittest.TestCase):
    def run_sync(self, store, task, name="林婉", description="新描述"):
        return asyncio.run(sync.sync_actor_description_async(store, task, name, description))

    def test_updates_the_bound_actor_whose_name_matches_loosely(self):
        store = FakeStore([element("other", "沈砚"), element("e1", " 林 婉 ")])
        self.assertEqual(self.run_sync(store, _task()), {"updated": True, "element_id": "e1"})
        self.assertEqual(store.updates, [{"element_id": "e1", "owner_id": "u1", "name": None, "description": "新描述"}])
        self.assertEqual(store.listed[0][:2], ("u1", "actor"))

    def test_name_mismatch_or_other_project_means_no_update(self):
        for item in (element("e1", "林婉婉"), element("e1", "林婉", task_id="t2"), element("e1", "林婉", owner_id="u2")):
            with self.subTest(item.name, task=item.metadata_json, owner=item.owner_id):
                store = FakeStore([item])
                self.assertEqual(self.run_sync(store, _task()), {"updated": False, "element_id": ""})
                self.assertEqual(store.updates, [])

    def test_the_first_alias_counts_on_either_side(self):
        store = FakeStore([element("e1", "小婉")])
        self.assertTrue(self.run_sync(store, _task(aliases=["小婉", "婉儿"]))["updated"])
        store = FakeStore([element("e1", "婉儿")])
        self.assertFalse(self.run_sync(store, _task(aliases=["小婉", "婉儿"]))["updated"], "只认第一个别名")
        store = FakeStore([element("e1", "女一号", aliases=["林婉"])])
        self.assertTrue(self.run_sync(store, _task())["updated"], "元素自己记的别名也算")

    def test_pages_through_a_big_library(self):
        store = FakeStore([element(f"e{i}", f"演员{i}") for i in range(250)] + [element("hit", "林婉")], page_size=100)
        self.assertEqual(self.run_sync(store, _task())["element_id"], "hit")
        self.assertEqual([call[2] for call in store.listed], [1, 2, 3])

    def test_store_failure_is_captured_not_raised(self):
        store = FakeStore([element("e1", "林婉")])
        store.fail = RuntimeError("connection refused")
        result = self.run_sync(store, _task())
        self.assertFalse(result["updated"])
        self.assertIn("connection refused", result["error"])

    def test_nothing_to_do_without_owner_or_project(self):
        store = FakeStore([element("e1", "林婉")])
        self.assertFalse(self.run_sync(store, {"task_id": "t1", "assets": {}})["updated"])
        self.assertFalse(self.run_sync(store, {"owner_user_id": "u1", "assets": {}})["updated"])
        self.assertEqual(store.listed, [])


class SyncVariantTests(unittest.TestCase):
    def test_opens_its_own_store_and_closes_it(self):
        store = FakeStore([element("e1", "林婉")])
        with patch("app.platform.store.PlatformStore", return_value=store) as factory:
            result = sync.sync_actor_description(_task(), "林婉", "新描述")
        self.assertEqual(result, {"updated": True, "element_id": "e1"})
        self.assertEqual(factory.call_count, 1)
        self.assertTrue(store.closed)
        self.assertEqual(store.updates[0]["description"], "新描述")

    def test_refuses_to_run_inside_an_event_loop(self):
        async def inside():
            return sync.sync_actor_description(_task(), "林婉", "新描述")

        with self.assertRaisesRegex(RuntimeError, "sync_actor_description_async"):
            asyncio.run(inside())

    def test_a_store_that_cannot_even_open_is_reported(self):
        with patch("app.platform.store.PlatformStore", side_effect=OSError("no database")):
            result = sync.sync_actor_description(_task(), "林婉", "新描述")
        self.assertFalse(result["updated"])
        self.assertIn("no database", result["error"])


if __name__ == "__main__":
    unittest.main()

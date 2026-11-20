# -*- coding: utf-8 -*-
"""第 3 步把重复的条目并成一条：被并掉的名字记进留下那条的别名，只在本项目的删掉，别的项目也用的只拿出本项目。"""

import asyncio
import unittest
from unittest import mock

from app.core import project_asset_completion as pac


class _Store:
    def __init__(self, rows):
        self.rows = rows
        self.metadata, self.deleted, self.unlinked = {}, [], []

    async def merge_element_metadata(self, element_id, owner_id, patch):
        self.metadata[element_id] = patch

    async def unlink_element_from_task(self, element_id, owner_id, task_id):
        self.unlinked.append(element_id)


def _row(id_, name, has_image=False, task_ids=("t1",), aliases=None):
    metadata = {"task_id": task_ids[0], "task_ids": list(task_ids)}
    if aliases:
        metadata["aliases"] = aliases
    return {"id": id_, "kind": "extra", "name": name, "has_image": has_image, "metadata": metadata}


class MergeDuplicateTests(unittest.TestCase):
    def _merge(self, rows, task=None):
        store = _Store(rows)

        async def summaries(*_args):
            return rows

        async def delete(element_id, owner_id, store_):
            store.deleted.append(element_id)

        with mock.patch.object(pac, "project_element_summaries", summaries), \
                mock.patch("app.api.element_api.delete_element_and_files", delete):
            merged = asyncio.run(pac.merge_duplicate_elements(store, "u1", "t1", task or {}))
        return store, merged

    def test_the_same_crowd_is_merged_into_one_entry_and_its_name_kept_as_an_alias(self):
        rows = [_row("keep", "山门围观百姓"), _row("dup", "山门围观人群", aliases=["山门看客"]), _row("other", "演武台围观人群")]
        store, merged = self._merge(rows)
        self.assertEqual(merged, ["山门围观人群"])
        self.assertEqual(store.deleted, ["dup"])
        self.assertEqual(store.metadata, {"keep": {"aliases": ["山门围观人群", "山门看客"]}})

    def test_the_one_with_an_image_stays_and_a_shared_duplicate_only_leaves_this_project(self):
        rows = [_row("dup", "山门围观人群", task_ids=("t1", "t2")), _row("keep", "山门围观百姓", has_image=True)]
        store, merged = self._merge(rows)
        self.assertEqual((store.deleted, store.unlinked, merged), ([], ["dup"], ["山门围观人群"]))
        self.assertEqual(store.metadata, {"keep": {"aliases": ["山门围观人群"]}})

    def test_an_entry_a_shot_already_binds_is_left_alone(self):
        rows = [_row("keep", "山门围观百姓"), _row("dup", "山门围观人群")]
        task = {"assets": {}}
        with mock.patch("app.core.asset_dependents.shots_using", lambda task, element_id, kind, names: [{}] if element_id == "dup" else []):
            store, merged = self._merge(rows, task)
        self.assertEqual((store.deleted, store.metadata, merged), ([], {}, []))


if __name__ == "__main__":
    unittest.main()

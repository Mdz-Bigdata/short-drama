"""@ 候选：项目角色、挂在本项目的资产库元素和分镜里的场。"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.core import mention_catalog


def _element(element_id, kind, name, *, task_ids=("t1",), owner="u1", aliases=None, description="", files=()):
    metadata = {"task_id": task_ids[0], "task_ids": list(task_ids)} if task_ids else {}
    if aliases is not None:
        metadata["aliases"] = aliases
    return SimpleNamespace(
        id=element_id, kind=kind, name=name, owner_id=owner, description=description, version=3,
        metadata_json=metadata, files=list(files),
    )


class FakeStore:
    """list_elements(owner_id, kind, page, page_size) over a fixed list, with real paging."""

    def __init__(self, elements):
        self.elements = elements
        self.calls = []
        self.closed = False

    async def list_elements(self, owner_id, kind, page, page_size, task_id=None, folder=None):
        self.calls.append((owner_id, kind, page, page_size))
        mine = [item for item in self.elements if item.owner_id == owner_id and item.kind == kind]
        start = (page - 1) * page_size
        return mine[start:start + page_size], len(mine)

    async def close(self):
        self.closed = True


def _task():
    return {
        "task_id": "t1", "owner_user_id": "u1",
        "assets": {
            "3_characters": [
                {"name": "林夏", "aliases": ["夏夏"], "desc": "女主，" + "冷" * 100},
                {"name": "陆昭", "aliases": [], "desc": "男主"},
                {"name": "名" * 41, "desc": "太长"},
                "bad",
            ],
            "2_breakdown": {"scenes": [
                {"scene_id": "E1S01", "label": "办公室 / 日", "characters": ["林夏"]},
                {"scene_id": "E1S02", "label": "天台 / 夜"},
            ]},
        },
    }


def _library():
    image = SimpleNamespace(id="f-img", mime_type="image/png")
    model = SimpleNamespace(id="f-glb", mime_type="model/gltf-binary")
    return [
        _element("a1", "actor", "林夏", description="资产库里的林夏", files=[model, image]),
        _element("a2", "actor", "赵总", task_ids=("other",)),
        _element("a3", "actor", "沈总", aliases=["陆昭"]),
        _element("s1", "scene", "天台 / 夜", description="楼顶"),
        _element("p1", "prop", "玉佩", aliases="玉坠、佩"),
        _element("v1", "vehicle", "黑色轿车"),
        _element("x1", "prop", "其他人的道具", owner="u2"),
        _element("l1", "prop", "长" * 41),
    ]


def run(store, task=None, **kwargs):
    return asyncio.run(mention_catalog.mentionable_async(store, task or _task(), **kwargs))


class MentionCatalogTests(unittest.TestCase):
    def test_union_is_ordered_actor_scene_prop_then_others(self):
        items = run(FakeStore(_library()))
        self.assertEqual(
            [(item["kind"], item["name"]) for item in items],
            [("actor", "林夏"), ("actor", "沈总"), ("scene", "天台 / 夜"), ("scene", "办公室 / 日"),
             ("prop", "玉佩"), ("vehicle", "黑色轿车")],
        )
        # 同类里按先出现的顺序：项目角色、资产库、分场。
        self.assertEqual(set(items[0]), {"name", "kind", "element_id", "aliases", "description", "thumb_url"})

    def test_library_entries_win_the_dedupe_and_keep_the_project_aliases(self):
        items = {(item["kind"], item["name"]): item for item in run(FakeStore(_library()))}
        lin = items[("actor", "林夏")]
        self.assertEqual(lin["element_id"], "a1")
        self.assertEqual(lin["description"], "资产库里的林夏")
        self.assertEqual(lin["aliases"], ["夏夏"])
        self.assertEqual(lin["thumb_url"], "/api/elements/a1/files/f-img/content?v=3", "first image file, never the model")
        # 项目里的陆昭是资产库里别名为陆昭的沈总：合成一条，名字用资产库的。
        shen = items[("actor", "沈总")]
        self.assertEqual((shen["element_id"], shen["description"]), ("a3", "男主"))
        self.assertIn("陆昭", shen["aliases"])
        roof = items[("scene", "天台 / 夜")]
        self.assertEqual((roof["element_id"], roof["description"], roof["aliases"]), ("s1", "楼顶", ["E1S02"]))
        self.assertEqual(items[("scene", "办公室 / 日")]["element_id"], "")
        self.assertEqual(items[("prop", "玉佩")]["aliases"], ["玉坠", "佩"])

    def test_without_a_library_project_characters_and_scenes_still_list(self):
        items = run(None)
        lin = items[0]
        self.assertEqual((lin["name"], lin["element_id"], lin["aliases"]), ("林夏", "", ["夏夏"]))
        self.assertEqual(len(lin["description"]), 80)
        self.assertEqual([item["name"] for item in items], ["林夏", "陆昭", "办公室 / 日", "天台 / 夜"])

    def test_only_this_task_and_owner_and_names_that_fit_a_mention(self):
        names = {item["name"] for item in run(FakeStore(_library()))}
        self.assertNotIn("赵总", names, "linked to another project")
        self.assertNotIn("其他人的道具", names, "another owner's library")
        self.assertFalse(any(len(name) > 40 for name in names))

    def test_every_page_of_every_kind_is_read(self):
        props = [_element(f"p{n}", "prop", f"道具{n}") for n in range(230)]
        store = FakeStore(props)
        items = run(store, limit=1000)
        self.assertEqual(sum(item["kind"] == "prop" for item in items), 230)
        self.assertEqual([call[2] for call in store.calls if call[1] == "prop"], [1, 2, 3])
        self.assertEqual({call[1] for call in store.calls}, set(mention_catalog.LIBRARY_KINDS))

    def test_query_matches_name_and_aliases_ignoring_case_and_spaces(self):
        store = FakeStore(_library() + [_element("e1", "effect", "Blue Fire")])
        self.assertEqual([item["name"] for item in run(store, query="夏")], ["林夏"])
        self.assertEqual([item["name"] for item in run(store, query="陆 昭")], ["沈总"])
        self.assertEqual([item["name"] for item in run(store, query="bluefire")], ["Blue Fire"])
        self.assertEqual([item["name"] for item in run(store, query="E1S01")], ["办公室 / 日"])
        self.assertEqual(len(run(store, limit=2)), 2)

    def test_a_failing_library_falls_back_to_the_project(self):
        class Broken(FakeStore):
            async def list_elements(self, *args, **kwargs):
                raise RuntimeError("db down")

        self.assertEqual([item["name"] for item in run(Broken([]))], ["林夏", "陆昭", "办公室 / 日", "天台 / 夜"])

    def test_the_sync_helper_opens_and_closes_its_own_store(self):
        store = FakeStore(_library())
        with patch.object(mention_catalog, "_fresh_store", return_value=store):
            items = mention_catalog.mentionable(_task(), query="玉")
        self.assertEqual([item["element_id"] for item in items], ["p1"])
        self.assertTrue(store.closed)
        with patch.object(mention_catalog, "_fresh_store") as fresh:
            ownerless = {**_task(), "owner_user_id": ""}
            self.assertEqual(mention_catalog.mentionable(ownerless)[0]["name"], "林夏")
        fresh.assert_not_called()


class MentionableEndpointTests(unittest.TestCase):
    def test_the_endpoint_lists_the_task_candidates_with_the_request_store(self):
        from app.api import drama_api

        repo = SimpleNamespace(get_task=lambda task_id: _task() if task_id == "t1" else None)
        with patch.object(drama_api.service, "repo", repo):
            body = asyncio.run(drama_api.list_mentionable("t1", q="林", limit=10, store=FakeStore(_library())))
            self.assertEqual([(item["name"], item["element_id"]) for item in body["items"]], [("林夏", "a1")])
            with self.assertRaises(HTTPException) as missing:
                asyncio.run(drama_api.list_mentionable("nope", q="", limit=10, store=FakeStore([])))
        self.assertEqual(missing.exception.status_code, 404)

    def test_the_route_is_registered(self):
        from app.api import drama_api

        routes = {(route.path, tuple(sorted(route.methods))) for route in drama_api.router.routes}
        self.assertIn(("/api/drama/{task_id}/mentionable", ("GET",)), routes)


if __name__ == "__main__":
    unittest.main()

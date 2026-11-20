# -*- coding: utf-8 -*-
"""换了说法的同一样东西按描述并成一条：模型分组、留哪条、别名、从本项目摘掉，以及剧本写旧名字照样认到留下的那条。

不调模型：``ask`` 换成固定回答。
"""

import asyncio
import json
import unittest

from app.core import asset_dedupe
from app.core.storyboard_scene_context import compile_scene_context, panel_context


def _row(id_, kind, name, description="", *, image=False, **metadata):
    return {"id": id_, "kind": kind, "name": name, "description": description, "has_image": image, "metadata": dict(metadata)}


SWORDS = [
    _row("p1", "prop", "带鞘长剑（裴照的剑）", "裴照随身的乌鞘长剑", image=True),
    _row("p2", "prop", "裴照的带鞘长剑", "乌木鞘长剑"),
    _row("p3", "prop", "裴照腰佩长剑", "挂在裴照左腰的长剑"),
    _row("p4", "prop", "小锤", "陈三打铁的小锤"),
]


class _Store:
    def __init__(self):
        self.metadata = {}
        self.unlinked = []

    async def merge_element_metadata(self, element_id, owner_id, values):
        self.metadata.setdefault(element_id, {}).update(values)

    async def unlink_element_from_task(self, element_id, owner_id, task_id):
        self.unlinked.append((element_id, task_id))


class GroupingTests(unittest.TestCase):
    def test_the_prompt_lists_every_item_with_its_description(self):
        system, user = asset_dedupe.prompt("prop", SWORDS)
        self.assertIn("剑和剑鞘", system)
        self.assertIn("1. 带鞘长剑（裴照的剑）：裴照随身的乌鞘长剑", user)
        self.assertIn("拍摄道具", user)

    def test_only_valid_disjoint_groups_of_two_or_more_survive(self):
        answer = "好的：" + json.dumps({"groups": [[1, 2, 3], [3, 4], [9, 1], [4], ["2", 4]]})
        self.assertEqual(asset_dedupe.parse_groups(answer, 4), [[0, 1, 2]])
        self.assertEqual(asset_dedupe.parse_groups("没有 JSON", 4), [])
        self.assertEqual(asset_dedupe.parse_groups(None, 4), [])

    def test_the_kept_one_is_the_drawn_set_then_the_one_with_a_picture_then_the_longest_name(self):
        self.assertEqual(asset_dedupe.keeper(SWORDS[:3])["id"], "p1")
        drawn = _row("p9", "prop", "剑", drawn_together=["剑穗"])
        self.assertEqual(asset_dedupe.keeper([*SWORDS[:3], drawn])["id"], "p9")
        self.assertEqual(asset_dedupe.keeper([SWORDS[1], SWORDS[2]])["id"], "p2", "same length: the earlier one")

    def test_each_kind_is_asked_on_its_own_and_actors_are_left_alone(self):
        asked = []

        def ask(system, user):
            asked.append(user)
            return json.dumps({"groups": [[1, 2, 3]]}) if "拍摄道具" in user else '{"groups": []}'

        rows = [*SWORDS, _row("a1", "actor", "裴照"), _row("a2", "actor", "裴照·玄黑锦袍"),
                _row("e1", "effect", "剑身人脸倒影"), _row("e2", "effect", "剑身围观人脸倒影"),
                _row("x1", "prop", "早就并掉的", merged_into="p1")]
        groups = asset_dedupe.ask_groups(rows, ask)
        self.assertEqual(len(asked), 2, "props and effects; actors are not asked, a kind with one item is not asked")
        self.assertNotIn("早就并掉的", asked[0])
        self.assertEqual([(kept["id"], [item["id"] for item in losers]) for kept, losers in groups], [("p1", ["p2", "p3"])])


class MergeTests(unittest.TestCase):
    def test_merged_names_become_aliases_and_the_rest_leave_the_project(self):
        store = _Store()
        task = {"assets": {}}
        done = asyncio.run(asset_dedupe.merge(store, "owner", "t1", task, [(SWORDS[0], [SWORDS[1], SWORDS[2]])]))
        self.assertEqual(done, [{"kept": "带鞘长剑（裴照的剑）", "kind": "prop", "merged": ["裴照的带鞘长剑", "裴照腰佩长剑"]}])
        self.assertEqual(store.metadata["p1"]["aliases"], ["裴照的带鞘长剑", "裴照腰佩长剑"])
        self.assertEqual(store.metadata["p2"][asset_dedupe.MERGED_INTO], "p1")
        self.assertEqual(store.unlinked, [("p2", "t1"), ("p3", "t1")], "taken out of the project, not deleted")

    def test_one_a_storyboard_already_uses_stays(self):
        store = _Store()
        task = {"assets": {"4": [{"shot_id": 1, "scene_id": "E1S01", "props": ["裴照腰佩长剑"],
                                  "asset_bindings": [{"kind": "prop", "element_id": "p3", "name": "裴照腰佩长剑"}]}]}}
        done = asyncio.run(asset_dedupe.merge(store, "owner", "t1", task, [(SWORDS[0], [SWORDS[1], SWORDS[2]])]))
        self.assertEqual(done[0]["merged"], ["裴照的带鞘长剑"])
        self.assertNotIn(("p3", "t1"), store.unlinked)


class RebindTests(unittest.TestCase):
    def _task(self):
        return {"assets": {"4": [
            {"shot_id": 1, "props": ["裴照腰佩长剑"], "asset_bindings": [
                {"kind": "prop", "name": "裴照腰佩长剑", "element_id": "p3", "element_version": 2},
                {"kind": "actor", "name": "裴照", "element_id": "a1", "element_version": 1},
            ]},
            {"shot_id": 2, "asset_bindings": [
                {"kind": "prop", "name": "带鞘长剑（裴照的剑）", "element_id": "p1", "element_version": 4},
                {"kind": "prop", "name": "裴照的带鞘长剑", "element_id": "p2", "element_version": 1},
            ]},
            {"shot_id": 3, "asset_bindings": [{"kind": "prop", "name": "陈三小锤", "element_id": "p5", "element_version": 1}]},
        ]}}

    def test_shots_bound_to_merged_items_point_at_the_kept_one(self):
        task = self._task()
        changed = asset_dedupe.rebind_shots(task, SWORDS[0], [SWORDS[1], SWORDS[2]], version=4)
        self.assertEqual(changed, 2)
        first, second, third = task["assets"]["4"]
        self.assertEqual(first["asset_bindings"][0], {"kind": "prop", "name": "带鞘长剑（裴照的剑）", "element_id": "p1", "element_version": 4})
        self.assertEqual(first["asset_bindings"][1]["name"], "裴照", "other assets untouched")
        self.assertEqual(first["props"], ["裴照腰佩长剑"], "the shot's own list is not rewritten: its clip is still reused")
        self.assertEqual([item["element_id"] for item in second["asset_bindings"]], ["p1"], "already bound to the kept one: the merged binding just goes")
        self.assertEqual(third["asset_bindings"][0]["element_id"], "p5")

    def test_after_rebinding_the_merge_takes_them_out(self):
        store = _Store()
        task = self._task()
        asset_dedupe.rebind_shots(task, SWORDS[0], [SWORDS[1], SWORDS[2]], version=4)
        done = asyncio.run(asset_dedupe.merge(store, "owner", "t1", task, [(SWORDS[0], [SWORDS[1], SWORDS[2]])]))
        self.assertEqual(done[0]["merged"], ["裴照的带鞘长剑", "裴照腰佩长剑"])


class FinishedClipTests(unittest.TestCase):
    def test_finished_clips_record_the_kept_one_so_they_are_still_reused(self):
        from app.core import asset_dependents

        task = {"assets": {"5": [
            {"shot_uid": 1, "asset_versions": {"a1": 1, "p3": 2}},
            {"shot_uid": 2, "asset_versions": {"p1": 4, "p2": 1}},
            {"shot_uid": 3, "asset_versions": {"a1": 1}},
            {"shot_uid": 4},
        ]}}
        self.assertEqual(asset_dedupe.remap_clip_versions(task, SWORDS[0], [SWORDS[1], SWORDS[2]], version=4), 2)
        clips = task["assets"]["5"]
        self.assertEqual(clips[0]["asset_versions"], {"a1": 1, "p1": 4})
        self.assertEqual(clips[1]["asset_versions"], {"p1": 4})
        self.assertEqual(clips[2]["asset_versions"], {"a1": 1})
        self.assertNotIn("asset_versions", clips[3])
        # 下次第 5 阶段按名字认到留下那条：{a1, p1} 和记录一致，片子照旧复用。
        self.assertTrue(asset_dependents.versions_match(clips[0], {"a1": 1, "p1": 4}))


class OldNameTests(unittest.TestCase):
    def test_a_script_using_a_merged_name_finds_the_kept_one_and_lists_it_once(self):
        kept = {"id": "p1", "kind": "prop", "name": "带鞘长剑（裴照的剑）", "description": "", "image_url": "data:sword",
                "metadata": {"aliases": ["裴照腰佩长剑"]}}
        actor = {"id": "a1", "kind": "actor", "name": "裴照", "description": "", "metadata": {}, "image_url": "data:actor"}
        task = {"task_id": "t1", "config": {}, "assets": {
            "3_characters": [{"name": "裴照", "desc": ""}],
            "2_breakdown": {"production_assets": {"props": [{"name": "裴照腰佩长剑", "description": "挂在左腰"}]}},
        }}
        context = compile_scene_context(task, {"scene_id": "E1S01", "content": "裴照按住裴照腰佩长剑。", "characters": ["裴照"]}, [actor, kept])
        self.assertEqual([item["name"] for item in context["props"]], ["带鞘长剑（裴照的剑）"])
        panel = panel_context(context, {"desc": "裴照按住裴照腰佩长剑", "characters": ["裴照"]})
        self.assertIn("data:sword", [item["image_url"] for item in panel["references"]])


if __name__ == "__main__":
    unittest.main()

"""A name is an asset's identity: renaming and merging follow every reference."""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from app.core import asset_identity
from app.core.screenwriting.engine import ENGINE_NAME
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService


def _task() -> dict:
    scenes = [
        {
            "scene_id": "E1S01", "duration_seconds": 8, "characters_in_scene": ["林夏", "周教授"], "scenes": ["地下实验室"], "props": ["录音笔"],
            "utterances": [{"kind": "dialogue", "speaker": "林夏", "text": "你瞒了什么？"}, {"kind": "voiceover", "text": "夜深了。"}],
        },
        {"scene_id": "E1S02", "duration_seconds": 8, "characters_in_scene": ["周教授"], "scenes": ["走廊"], "props": [], "utterances": []},
    ]
    return {
        "task_id": "id-1", "status": "idle", "config": {"title_suggestion": "暗室回声", "episode_count": 1},
        "assets": {
            "1": "方案",
            "2": "第1集 对峙\n\n“你瞒了什么？”林夏问。",
            "2_screenwriting": {
                "engine": ENGINE_NAME, "version": 1, "source_kind": "outline", "title": "暗室回声", "episode_count": 1,
                "inventory": {
                    "characters": {"林夏": {"description": "黑色短发", "aliases": []}, "周教授": {"description": "金丝眼镜", "aliases": ["老周"]}},
                    "scenes": {"地下实验室": {"description": "冷白灯"}, "走廊": {"description": ""}},
                    "props": {"录音笔": {"description": "银色"}},
                },
                "ledger": [{"episode": 1, "title": "对峙", "hook": "", "story_beats": [], "source_origin": "none"}],
                "episodes": {"1": {"episode": 1, "plan": {"title": "对峙", "scenes": deepcopy(scenes)}, "script": {"episode": 1, "title": "对峙", "scenes": deepcopy(scenes)}, "prose": "“你瞒了什么？”林夏问。周教授没有回答。", "violations": [], "needs_replan": []}},
                "warnings": [], "durations": {"supported": [4, 5, 6, 7, 8], "video_model": "seedance2.0"}, "language": "zh",
            },
            "2_breakdown": {
                "overview": {"synopsis": "林夏追查真相。", "genre": "悬疑", "theme": "代价"},
                "scenes": [{"scene_id": "E1S01", "duration": "8s", "content": "对峙", "characters": ["林夏", "周教授"]}],
                "roles": [{"name": "林夏", "position": "女主角"}, {"name": "周教授", "position": "反派"}],
                "relationships": [{"from": "林夏", "to": "周教授", "relation": "师生对立"}],
                "production_assets": {"scenes": [{"name": "地下实验室", "description": "冷白灯"}], "props": [{"name": "录音笔", "description": "银色"}], "costumes": [], "effects": []},
                "timeline": [],
            },
            "3_sheets": {"林夏": "https://cdn/linxia.png", "周教授": "https://cdn/zhou.png"},
            "3_characters": [{"name": "林夏", "role": "主角"}, {"name": "周教授", "role": "反派"}],
            "4": [{"shot_id": 1, "scene_id": "E1S01", "characters": ["林夏", "周教授"], "desc": "对峙"}, {"shot_id": 2, "scene_id": "E1S02", "characters": ["周教授"], "desc": "走廊"}],
            "5": [{"shot_id": 1, "video_url": "https://cdn/1.mp4"}, {"shot_id": 2, "video_url": "https://cdn/2.mp4"}],
        },
        "logs": {},
    }


class RenameTests(unittest.TestCase):
    def test_preview_counts_every_reference_without_changing_anything(self):
        task = _task()
        before = deepcopy(task)

        impact = asset_identity.preview_rename(task, "character", "林夏", "沈知微")

        self.assertEqual(task, before)
        self.assertEqual(impact.references["inventory"], 1)
        self.assertEqual(impact.references["plan.characters_in_scene"], 1)
        self.assertEqual(impact.references["script.speaker"], 1)
        self.assertEqual(impact.references["breakdown.roles"], 1)
        self.assertEqual(impact.references["breakdown.relationships"], 1)
        self.assertEqual(impact.references["sheets"], 1)
        self.assertEqual(impact.references["shots"], 1)
        self.assertEqual(impact.episodes, [1])
        self.assertEqual(impact.stale_shots, [1])

    def test_rename_cascades_everywhere_and_keeps_the_old_name_as_an_alias(self):
        task = _task()

        impact = asset_identity.rename_asset(task, "character", "林夏", "沈知微")

        state = task["assets"]["2_screenwriting"]
        self.assertNotIn("林夏", state["inventory"]["characters"])
        self.assertEqual(state["inventory"]["characters"]["沈知微"]["aliases"], ["林夏"])
        self.assertEqual(impact.aliases, ["林夏"])
        scene = state["episodes"]["1"]["script"]["scenes"][0]
        self.assertEqual(scene["characters_in_scene"], ["沈知微", "周教授"])
        self.assertEqual(scene["utterances"][0]["speaker"], "沈知微")
        self.assertIn("沈知微问", state["episodes"]["1"]["prose"])
        breakdown = task["assets"]["2_breakdown"]
        self.assertEqual(breakdown["roles"][0]["name"], "沈知微")
        self.assertEqual(breakdown["relationships"][0]["from"], "沈知微")
        self.assertEqual(breakdown["scenes"][0]["characters"], ["沈知微", "周教授"])
        self.assertEqual(task["assets"]["3_sheets"], {"沈知微": "https://cdn/linxia.png", "周教授": "https://cdn/zhou.png"})
        self.assertEqual(task["assets"]["3_characters"][0]["name"], "沈知微")
        self.assertEqual(task["assets"]["4"][0]["characters"], ["沈知微", "周教授"])
        # The clip filmed under the old name stays, flagged for a rerun; the other shot is untouched.
        self.assertTrue(task["assets"]["5"][0]["stale"])
        self.assertNotIn("stale", task["assets"]["5"][1])

    def test_scenes_and_props_rename_through_their_own_references(self):
        task = _task()
        impact = asset_identity.rename_asset(task, "scene", "地下实验室", "地下档案室")
        self.assertEqual(task["assets"]["2_screenwriting"]["episodes"]["1"]["plan"]["scenes"][0]["scenes"], ["地下档案室"])
        self.assertEqual(task["assets"]["2_breakdown"]["production_assets"]["scenes"][0]["name"], "地下档案室")
        self.assertIn("地下档案室", task["assets"]["2_screenwriting"]["inventory"]["scenes"])
        self.assertEqual(impact.references["breakdown.production_assets"], 1)

        asset_identity.rename_asset(task, "prop", "录音笔", "录音机")
        self.assertEqual(task["assets"]["2_screenwriting"]["episodes"]["1"]["script"]["scenes"][0]["props"], ["录音机"])

    def test_a_rename_to_an_existing_name_is_refused_and_an_unknown_name_too(self):
        task = _task()
        with self.assertRaisesRegex(asset_identity.AssetIdentityError, "合并"):
            asset_identity.rename_asset(task, "character", "林夏", "周教授")
        with self.assertRaisesRegex(asset_identity.AssetIdentityError, "没有叫"):
            asset_identity.rename_asset(task, "character", "不存在", "谁")
        with self.assertRaisesRegex(asset_identity.AssetIdentityError, "相同"):
            asset_identity.rename_asset(task, "character", "林夏", " 林夏 ")
        with self.assertRaisesRegex(asset_identity.AssetIdentityError, "类型"):
            asset_identity.rename_asset(task, "costume", "x", "y")

    def test_names_compare_after_trimming_and_unicode_normalisation(self):
        task = _task()
        task["assets"]["2_breakdown"]["roles"][0]["name"] = " 林夏 "
        self.assertIn("林夏", asset_identity.known_names(task, "character"))
        asset_identity.rename_asset(task, "character", "林夏", "沈知微")
        self.assertEqual(task["assets"]["2_breakdown"]["roles"][0]["name"], "沈知微")


class MergeTests(unittest.TestCase):
    def test_merge_points_every_reference_at_the_survivor_and_keeps_the_loser_as_an_alias(self):
        task = _task()

        impact = asset_identity.merge_assets(task, "character", "周教授", "林夏")

        state = task["assets"]["2_screenwriting"]
        self.assertNotIn("周教授", state["inventory"]["characters"])
        self.assertEqual(state["inventory"]["characters"]["林夏"]["aliases"], ["周教授"])
        # A scene that listed both now lists the survivor once; the second scene keeps one cast member.
        scenes = state["episodes"]["1"]["script"]["scenes"]
        self.assertEqual(scenes[0]["characters_in_scene"], ["林夏"])
        self.assertEqual(scenes[1]["characters_in_scene"], ["林夏"])
        self.assertEqual([role["name"] for role in task["assets"]["2_breakdown"]["roles"]], ["林夏"])
        self.assertEqual(task["assets"]["2_breakdown"]["relationships"][0], {"from": "林夏", "to": "林夏", "relation": "师生对立"})
        self.assertEqual(task["assets"]["3_sheets"], {"林夏": "https://cdn/linxia.png"})
        self.assertEqual(impact.stale_shots, [1, 2])

    def test_merging_into_an_unknown_survivor_is_refused(self):
        with self.assertRaisesRegex(asset_identity.AssetIdentityError, "保留方"):
            asset_identity.merge_assets(_task(), "character", "林夏", "不存在")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("id-1", _task())
        self.service = DramaService()
        self.service.repo = self.repo

    def test_a_dry_run_changes_nothing_and_a_real_run_reprojects_the_dashboards(self):
        preview = self.service.change_asset_identity("id-1", operation="rename", kind="character", name="林夏", new_name="沈知微", dry_run=True)
        self.assertEqual(preview["total_references"], asset_identity.preview_rename(_task(), "character", "林夏", "沈知微").total())
        self.assertIn("林夏", self.repo.get_task("id-1")["assets"]["3_sheets"])

        result = self.service.change_asset_identity("id-1", operation="rename", kind="character", name="林夏", new_name="沈知微", dry_run=False)

        stored = self.repo.get_task("id-1")
        self.assertEqual(result["new_name"], "沈知微")
        self.assertIn("沈知微", stored["assets"]["2"])
        self.assertNotIn("林夏", stored["assets"]["2"])
        # The breakdown is re-projected from the structured state, so its role order follows the inventory.
        self.assertEqual({role["name"] for role in stored["assets"]["2_breakdown"]["roles"]}, {"沈知微", "周教授"})
        self.assertTrue(any(role["name"] == "沈知微" for role in stored["assets"]["2_writer_dashboard"]["roles"]))
        self.assertTrue(stored["assets"]["5"][0]["stale"])


if __name__ == "__main__":
    unittest.main()

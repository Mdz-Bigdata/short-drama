"""Legacy outlines must not hide episodes that exist in the screenplay."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from app.core import writer_dashboard


def _episode(index: int) -> str:
    return (
        f"第{index}集 副标题{index}\n"
        f"场景1：档案室 夜 内景\n林夏：第{index}集原文。\n"
        f"场景2：长街 日 外景\n周教授：第{index}集第二场。\n"
    )


def _legacy_task() -> dict:
    covered = [*range(1, 9), *range(13, 16), *range(25, 29)]
    scenes = [
        {
            "scene_id": f"E{episode}S{shot:02d}",
            "duration": "15s",
            "content": f"已有第{episode}集第{shot}镜",
            "characters": ["林夏"],
            "image_url": f"https://example.test/E{episode}S{shot:02d}.png",
        }
        for episode in covered
        for shot in range(1, 8)
    ]
    return {
        "task_id": "legacy-outline",
        "config": {"episode_count": 30, "title_suggestion": "档案追踪"},
        "assets": {
            "2": "\n".join(_episode(index) for index in range(1, 31)),
            "2_breakdown": {
                "scenes": scenes,
                "production_assets": {"props": [{"name": "密函"}]},
                "roles": [{"name": "林夏", "position": "女主角"}],
            },
        },
    }


class OutlineReconciliationTests(unittest.TestCase):
    def test_internal_source_gaps_survive_stale_or_missing_configured_count(self):
        script = "\n".join(_episode(index) for index in [*range(1, 16), 25])
        for configured in (15, 0, None, "15"):
            with self.subTest(configured=configured):
                self.assertEqual(
                    writer_dashboard.script_episode_gaps(script, configured),
                    list(range(16, 25)),
                )

    def test_source_gap_audit_keeps_unheaded_upload_compatibility(self):
        self.assertEqual(writer_dashboard.script_episode_gaps("林夏：出发。", 30), [])

    def test_stage_two_cannot_advance_past_an_internal_gap_with_stale_config(self):
        from app.service.drama_service import DramaService

        task = _legacy_task()
        task["config"]["episode_count"] = 15
        task["assets"]["2"] = "\n".join(_episode(index) for index in [*range(1, 16), 25])
        missing = DramaService._missing_stage_outputs(task, 2)
        self.assertTrue(any("16、17、18、19、20、21、22、23、24" in reason for reason in missing))

    def test_effective_target_preserves_larger_plan_and_handles_legacy_counts(self):
        for configured, expected in ((30, 30), (15, 25), (None, 25), ("15", 25)):
            with self.subTest(configured=configured):
                self.assertEqual(writer_dashboard.episode_target([1, 15, 25], configured), expected)

    def test_dashboard_total_includes_source_heading_even_when_outline_has_no_rows_for_it(self):
        task = _legacy_task()
        task["config"]["episode_count"] = 15
        task["assets"]["2"] = "\n".join(_episode(index) for index in range(1, 16)) + "\n第25集\n"
        task["assets"]["2_breakdown"]["scenes"] = [
            {"scene_id": "E15S06", "content": "原有镜头", "characters": ["林夏"]},
        ]
        dashboard = writer_dashboard.compile_writer_dashboard(task)
        self.assertEqual(dashboard.stats.total_episodes, 25)
        self.assertEqual(dashboard.stats.missing_episodes, list(range(16, 25)))
        self.assertEqual(dashboard.state, "INCOMPLETE")

    def test_complete_script_repairs_nonempty_105_scene_legacy_outline(self):
        task = _legacy_task()
        self.assertEqual(len(task["assets"]["2_breakdown"]["scenes"]), 105)

        dashboard = writer_dashboard.compile_writer_dashboard(task)

        self.assertEqual(sorted({scene.episode_index for scene in dashboard.scenes}), list(range(1, 31)))
        self.assertEqual(dashboard.stats.scene_count, 135)
        self.assertEqual(dashboard.stats.missing_episodes, [])
        self.assertTrue(all(episode.scene_count for episode in dashboard.episodes))
        self.assertEqual(dashboard.state, "READY")
        added = next(scene for scene in dashboard.scenes if scene.scene_id == "E16S01")
        self.assertIn("第16集原文", added.content)

    def test_preserves_existing_ids_content_durations_and_assets_without_mutation(self):
        task = _legacy_task()
        before = deepcopy(task)
        original = task["assets"]["2_breakdown"]["scenes"]

        repaired = writer_dashboard.reconcile_breakdown_scenes(original, task["assets"]["2"])

        by_id = {scene["scene_id"]: scene for scene in repaired}
        self.assertTrue(all(by_id[scene["scene_id"]] == scene for scene in original))
        self.assertEqual(task, before)
        self.assertEqual(by_id["E25S01"]["content"], "已有第25集第1镜")

    def test_reconciliation_is_idempotent(self):
        task = _legacy_task()
        repaired = writer_dashboard.reconcile_breakdown_scenes(
            task["assets"]["2_breakdown"]["scenes"], task["assets"]["2"],
        )

        self.assertEqual(writer_dashboard.reconcile_breakdown_scenes(repaired, task["assets"]["2"]), repaired)
        self.assertEqual(len({scene["scene_id"] for scene in repaired}), len(repaired))

    def test_natural_order_keeps_original_scene_numbers(self):
        scenes = [
            {"scene_id": name, "content": name}
            for name in ("E10S01", "E2S10", "E2S02", "E1S06")
        ]

        repaired = writer_dashboard.reconcile_breakdown_scenes(scenes, "")

        self.assertEqual([scene["scene_id"] for scene in repaired], ["E1S06", "E2S02", "E2S10", "E10S01"])

    def test_missing_screenplay_episodes_are_not_fabricated_or_marked_ready(self):
        task = _legacy_task()
        written = [*range(1, 16), *range(25, 31)]
        task["assets"]["2"] = "\n".join(_episode(index) for index in written)

        dashboard = writer_dashboard.compile_writer_dashboard(task)

        self.assertEqual(sorted({scene.episode_index for scene in dashboard.scenes}), written)
        self.assertEqual(dashboard.stats.missing_episodes, list(range(16, 25)))
        self.assertEqual(dashboard.state, "INCOMPLETE")

    def test_unheaded_upload_does_not_fabricate_requested_episodes(self):
        task = _legacy_task()
        task["assets"]["2"] = "场景1：长街 日 外景\n林夏：出发。"
        task["assets"]["2_breakdown"]["scenes"] = [{"scene_id": "E1S01", "content": "已编辑内容"}]

        dashboard = writer_dashboard.compile_writer_dashboard(task)

        self.assertEqual([scene.scene_id for scene in dashboard.scenes], ["E1S01"])
        self.assertEqual(dashboard.stats.missing_episodes, [])

    def test_empty_or_invalid_outline_uses_source_without_network(self):
        script = _episode(16)
        with patch("socket.socket.connect", side_effect=AssertionError("repair must remain offline")):
            for source in (None, [], "invalid", [None, "invalid"]):
                with self.subTest(source=source):
                    repaired = writer_dashboard.reconcile_breakdown_scenes(source, script)
                    self.assertEqual([scene["scene_id"] for scene in repaired], ["E16S01", "E16S02"])


if __name__ == "__main__":
    unittest.main()

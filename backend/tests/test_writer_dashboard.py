import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core.writer_dashboard import compile_writer_dashboard, parse_duration_seconds
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from main import app


def _task() -> dict:
    return {
        "task_id": "writer-task-1",
        "owner_user_id": "writer-user",
        "status": "idle",
        "config": {"title_suggestion": "十二小时", "episode_count": 2},
        "assets": {
            "2": "第1集 匿名录音\n场景1：雨夜办公室\n林夏：你隐瞒了什么？\n第2集 实验室\n场景1：地下实验室\n周教授：现在回头还来得及。",
            "2_breakdown": {
                "overview": {"synopsis": "林夏追查失踪案。", "genre": "都市悬疑", "theme": "真相需要代价"},
                "scenes": [
                    {"scene_id": "E1S01", "duration": "1m 5s", "content": "林夏收到匿名录音。", "characters": ["林夏"]},
                    {"scene_id": "E2S01", "duration": "45秒", "content": "林夏闯入地下实验室。", "characters": ["林夏", "周教授"]},
                ],
                "timeline": [
                    {"phase": "故事开始", "title": "匿名录音", "desc": "倒计时开始。", "points": ["建立目标"]},
                    {"phase": "高潮", "title": "实验室对峙", "desc": "真相揭晓。", "points": ["关系反转"]},
                ],
                "roles": [{"name": "林夏", "position": "女主角"}, {"name": "周教授", "position": "反派"}],
                "relationships": [{"from": "林夏", "to": "周教授", "relation": "师生对立"}],
            },
        },
        "episodes": [
            {"index": 1, "title": "匿名录音", "status": "completed", "video_url": "https://cdn.example/ep1.mp4"},
            {"index": 2, "title": "地下实验室", "status": "idle", "video_url": None},
        ],
        "total_episodes": 2,
    }


class WriterDashboardCompilerTests(unittest.TestCase):
    def test_compiles_timed_scenes_events_relationships_and_episode_status(self):
        dashboard = compile_writer_dashboard(_task())

        self.assertEqual(dashboard.state, "READY")
        self.assertEqual(dashboard.stats.total_duration_seconds, 110)
        self.assertEqual(dashboard.scenes[0].start_seconds, 0)
        self.assertEqual(dashboard.scenes[1].start_seconds, 65)
        self.assertEqual(dashboard.timeline[1].scene_id, "E2S01")
        self.assertEqual(dashboard.timeline[1].start_seconds, 65)
        self.assertEqual(
            [(edge.from_, edge.to, edge.relation) for edge in dashboard.relationships],
            [("林夏", "周教授", "师生对立")],
        )
        self.assertEqual(dashboard.episodes[0].status, "completed")
        self.assertEqual(dashboard.model_dump(by_alias=True)["relationships"][0]["from"], "林夏")
        self.assertEqual(len(dashboard.source_hash), 64)

    def test_falls_back_to_script_when_llm_breakdown_is_missing(self):
        task = _task()
        task["assets"].pop("2_breakdown")
        dashboard = compile_writer_dashboard(task)

        self.assertEqual(dashboard.state, "READY")
        self.assertEqual(dashboard.stats.total_episodes, 2)
        self.assertGreaterEqual(dashboard.stats.scene_count, 2)
        self.assertIn("林夏", [role.name for role in dashboard.roles])
        self.assertTrue(dashboard.timeline)

    def test_infers_labeled_character_relationships_from_scene_cooccurrence(self):
        task = _task()
        task["assets"].pop("2_breakdown")
        task["assets"]["2"] = (
            "第1集 对峙\n"
            "场景1：地下实验室\n"
            "林夏：你隐瞒了什么？\n"
            "周教授：现在回头还来得及。\n"
            "陈警官：所有人都别动。\n"
            "场景2：实验室走廊\n"
            "陈警官：出口已经封锁。\n"
            "周教授：你们没有证据。\n"
            "林夏：录音就是证据。\n"
        )

        dashboard = compile_writer_dashboard(task)

        edges = {(edge.from_, edge.to): edge.relation for edge in dashboard.relationships}
        self.assertEqual(dashboard.stats.relationship_count, 3)
        self.assertEqual(edges[("林夏", "周教授")], "同场互动 · 2 场")
        self.assertEqual(edges[("林夏", "陈警官")], "同场互动 · 2 场")
        self.assertEqual(edges[("周教授", "陈警官")], "同场互动 · 2 场")

    def test_speaker_extraction_does_not_merge_an_action_line_into_the_next_role(self):
        task = _task()
        task["assets"].pop("2_breakdown")
        task["assets"]["2"] = (
            "第1集 追踪\n"
            "场景1：档案室\n"
            "林夏走进房间\n"
            "周教授：你不该来这里。\n"
        )

        dashboard = compile_writer_dashboard(task)

        names = [role.name for role in dashboard.roles]
        self.assertIn("周教授", names)
        self.assertNotIn("林夏走进房间 周教授", names)

    def test_relationship_inference_bounds_the_global_role_universe(self):
        task = _task()
        task["assets"]["2_breakdown"]["relationships"] = []
        task["assets"]["2_breakdown"]["scenes"] = [
            {"scene_id": "E1S01", "content": "开场", "characters": ["甲", "乙"]},
            {
                "scene_id": "E1S02",
                "content": "群像一",
                "characters": [f"第一组{index:03d}" for index in range(100)],
            },
            {
                "scene_id": "E1S03",
                "content": "群像二",
                "characters": [f"第二组{index:03d}" for index in range(100)],
            },
        ]

        dashboard = compile_writer_dashboard(task)

        inferred_names = {
            name
            for edge in dashboard.relationships
            for name in (edge.from_, edge.to)
        }
        self.assertLessEqual(len(inferred_names), 100)
        self.assertLessEqual(len(dashboard.relationships), 5000)

    def test_duration_parser_supports_dashboard_input_formats(self):
        self.assertEqual(parse_duration_seconds("01:30"), 90)
        self.assertEqual(parse_duration_seconds("2分钟15秒"), 135)
        self.assertEqual(parse_duration_seconds("8s"), 8)

    def test_malformed_legacy_episode_counts_do_not_break_the_dashboard(self):
        task = _task()
        task["config"]["episode_count"] = "invalid"
        task["total_episodes"] = None

        dashboard = compile_writer_dashboard(task)

        self.assertEqual(dashboard.stats.total_episodes, 2)

    def test_excessive_scene_durations_are_bounded_to_the_contract(self):
        task = _task()
        task["assets"]["2_breakdown"]["scenes"] = [
            {"scene_id": f"E1S{index:02d}", "duration": "86400s", "content": f"场景 {index}"}
            for index in range(1, 10)
        ]

        dashboard = compile_writer_dashboard(task)

        self.assertEqual(dashboard.stats.total_duration_seconds, 604800)
        self.assertEqual(dashboard.episodes[0].duration_seconds, 604800)
        self.assertLessEqual(dashboard.scenes[-1].start_seconds, 604800)


class WriterDashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("writer-task-1", _task())
        self.service = DramaService()
        self.service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "writer-user",
            "role": "user",
        }

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)
        self.temp.cleanup()

    def test_dashboard_and_export_endpoints_share_the_versioned_contract(self):
        with patch.object(drama_api, "service", self.service):
            client = TestClient(app)
            response = client.get("/api/drama/writer-task-1/writer-dashboard")
            exported = client.get("/api/drama/writer-task-1/writer-dashboard/export")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["schemaVersion"], "writer-dashboard.v1")
        self.assertEqual(response.json()["stats"]["totalDurationSeconds"], 110)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("attachment", exported.headers["content-disposition"])
        self.assertEqual(exported.json()["sourceHash"], response.json()["sourceHash"])

    def test_missing_task_returns_not_found(self):
        with patch.object(drama_api, "service", self.service):
            response = TestClient(app).get("/api/drama/missing/writer-dashboard")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

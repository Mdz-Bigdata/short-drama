import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import auth_service, get_current_user
from app.core.writer_dashboard import compile_writer_dashboard, parse_duration_seconds
from app.repository.task_repo import TaskRepository
from app.repository.task_repo import StaleTaskWriteError
from app.platform.request_limits import SCRIPT_UPDATE_REQUEST_MAX_BYTES
from app.platform.dependencies import get_platform_store
from app.schema.drama import ScriptUpdateRequest
from app.service.drama_service import DramaService, StagePrerequisiteError
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
    def test_preserves_the_full_script_accepted_by_the_update_contract(self):
        suffix = "FULL-SCRIPT-END"
        script = "a" * (2 * 1024 * 1024 - len(suffix)) + suffix
        accepted = ScriptUpdateRequest(
            content=script,
            file_name="large-script.txt",
            expected_source_hash="0" * 64,
        )
        task = _task()
        task["assets"]["2"] = accepted.content
        task["assets"].pop("2_breakdown")

        dashboard = compile_writer_dashboard(task)

        self.assertEqual(dashboard.script, script)
        self.assertTrue(dashboard.script.endswith("FULL-SCRIPT-END"))

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


class _ClientAddressApp:
    """Pin a distinct ASGI client address per test.

    Older starlette TestClient builds accepted a ``client=`` keyword; the
    pinned 0.41 line does not, so rewrite the scope ourselves to keep the
    per-client request limits isolated between test methods.
    """

    def __init__(self, app, address):
        self._app = app
        self._address = address

    async def __call__(self, scope, receive, send):
        if scope.get("type") in {"http", "websocket"}:
            scope = dict(scope)
            scope["client"] = self._address
        await self._app(scope, receive, send)


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
        self.client = TestClient(
            _ClientAddressApp(app, (f"writer-{self._testMethodName}", 50000)),
            cookies={"auth_token": auth_service.generate_token("writer-user")},
        )

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_current_user, None)
        self.temp.cleanup()

    def test_relationship_update_replaces_persists_and_recompiles_the_dashboard(self):
        with patch.object(drama_api, "service", self.service):
            response = self.client.put(
                "/api/drama/writer-task-1/relationships",
                json={"relationships": [
                    {"from": "林夏", "to": "周教授", "relation": "亦敌亦友", "bidirectional": True},
                    {"from": "林夏", "to": "林夏", "relation": "自环必须被丢弃"},
                    {"from": "周教授", "to": "助手", "relation": "上下级"},
                ]},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(
            {(edge["from"], edge["to"], edge["relation"], edge["bidirectional"]) for edge in payload["relationships"]},
            {("林夏", "周教授", "亦敌亦友", True), ("周教授", "助手", "上下级", False)},
        )
        stored = self.repo.get_task("writer-task-1")["assets"]["2_breakdown"]["relationships"]
        self.assertEqual(len(stored), 2)
        self.assertTrue(stored[0]["bidirectional"])
        # The rest of the breakdown must survive a relationship-only edit.
        self.assertEqual(payload["stats"]["sceneCount"], 2)

    def test_stage_five_is_rejected_before_claim_when_stage_four_contract_is_incomplete(self):
        task = self.repo.get_task("writer-task-1")
        task["current_stage"] = 4
        task["status"] = "idle"
        task["assets"]["4"] = [{
            "shot_id": 1,
            "size": "MS",
            "motion": "Dolly In",
            "desc": "雨夜对峙",
        }]
        task["assets"].pop("4_storyboard", None)
        self.repo.save_task("writer-task-1", task)

        with patch.object(drama_api, "service", self.service):
            response = self.client.post(
                "/api/drama/writer-task-1/next?current_stage=5",
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("第4阶段尚未完整完成", response.json()["detail"])
        self.assertIn("4_storyboard", response.json()["detail"])
        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(stored["current_stage"], 4)
        self.assertEqual(stored["status"], "idle")
        self.assertNotEqual((stored.get("stage_progress") or {}).get("stage"), 5)

    def test_every_downstream_stage_requires_the_previous_stage_output(self):
        for stage in range(2, 9):
            with self.subTest(stage=stage):
                with self.assertRaisesRegex(StagePrerequisiteError, f"第{stage - 1}阶段尚未完整完成"):
                    self.service._assert_stage_prerequisites({"assets": {}}, stage)

    def test_assistant_does_not_announce_or_mark_a_blocked_next_stage_as_started(self):
        task = self.repo.get_task("writer-task-1")
        task["current_stage"] = 4
        task["status"] = "idle"
        task["assets"]["4"] = [{"shot_id": 1, "desc": "雨夜对峙"}]
        task["assets"].pop("4_storyboard", None)
        self.repo.save_task("writer-task-1", task)

        with self.assertRaises(StagePrerequisiteError):
            asyncio.run(self.service.assistant_message("writer-task-1", "继续"))

        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(stored["current_stage"], 4)
        self.assertEqual(stored["status"], "idle")
        self.assertNotEqual((stored.get("stage_progress") or {}).get("stage"), 5)

    def test_claiming_a_stage_discards_orphaned_outputs_from_later_stages(self):
        task = self.repo.get_task("writer-task-1")
        task["current_stage"] = 6
        task["status"] = "interrupted"
        task["fail_reason"] = "服务重启导致后台任务中断"
        task["assets"].update({
            "3": "角色锁定包",
            "3_sheets": {"林夏": "sheet.png"},
            "3_character_dashboard": {"state": "READY"},
            "5": [{"video_url": "stale-shot.mp4"}],
            "6": {"audio_url": "stale-audio.mp3"},
        })
        task["logs"] = {"5": "STALE", "6": "STALE"}
        task["video_url"] = "stale-final.mp4"
        task["short_link"] = "https://stale.invalid"
        task["pr_content"] = "过期宣发"
        task["stage_completions"] = {
            "3": {"status": "success"},
            "5": {"status": "success"},
            "6": {"status": "success"},
        }
        self.repo.save_task("writer-task-1", task)

        claimed = self.service._claim_stage_task("writer-task-1", 4)

        self.assertEqual(claimed["current_stage"], 4)
        self.assertIsNone(claimed["fail_reason"])
        self.assertNotIn("5", claimed["assets"])
        self.assertNotIn("6", claimed["assets"])
        self.assertNotIn("5", claimed["logs"])
        self.assertNotIn("6", claimed["logs"])
        self.assertEqual(set(claimed["stage_completions"]), {"3"})
        self.assertIsNone(claimed["video_url"])
        self.assertIsNone(claimed["short_link"])
        self.assertIsNone(claimed["pr_content"])

    def test_relationship_update_rejects_invalid_payloads(self):
        with patch.object(drama_api, "service", self.service):
            blank = self.client.put(
                "/api/drama/writer-task-1/relationships",
                json={"relationships": [{"from": "", "to": "周教授"}]},
            )
            oversized = self.client.put(
                "/api/drama/writer-task-1/relationships",
                json={"relationships": [
                    {"from": f"角色{index}", "to": f"角色{index + 1}"} for index in range(501)
                ]},
            )

        self.assertEqual(blank.status_code, 422)
        self.assertEqual(oversized.status_code, 422)

    def test_dashboard_and_export_endpoints_share_the_versioned_contract(self):
        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/writer-task-1/writer-dashboard")
            exported = self.client.get("/api/drama/writer-task-1/writer-dashboard/export")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["schemaVersion"], "writer-dashboard.v1")
        self.assertEqual(response.json()["stats"]["totalDurationSeconds"], 110)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("attachment", exported.headers["content-disposition"])
        self.assertEqual(exported.json()["sourceHash"], response.json()["sourceHash"])

    def test_episode_list_source_hash_tracks_the_same_script_snapshot(self):
        initial_task = self.repo.get_task("writer-task-1")
        expected_initial_hash = compile_writer_dashboard(initial_task).source_hash

        with patch.object(drama_api, "service", self.service):
            initial = self.client.get("/api/drama/writer-task-1/episodes")
            updated = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={
                    "content": "第1集 新剧本\n场景1：港口\n林夏：启程。",
                    "fileName": "new-script.md",
                    "expectedSourceHash": expected_initial_hash,
                    "confirmInvalidate": True,
                },
            )
            refreshed = self.client.get("/api/drama/writer-task-1/episodes")

        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertRegex(initial.json()["sourceHash"], r"^[0-9a-f]{64}$")
        self.assertEqual(initial.json()["sourceHash"], expected_initial_hash)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(refreshed.status_code, 200, refreshed.text)

        stored = self.repo.get_task("writer-task-1")
        expected_updated_hash = compile_writer_dashboard(stored).source_hash
        payload = refreshed.json()
        self.assertRegex(payload["sourceHash"], r"^[0-9a-f]{64}$")
        self.assertNotEqual(payload["sourceHash"], initial.json()["sourceHash"])
        self.assertEqual(payload["sourceHash"], expected_updated_hash)
        self.assertEqual(payload["sourceHash"], updated.json()["sourceHash"])
        self.assertEqual(payload["totalEpisodes"], stored["total_episodes"])
        self.assertEqual(payload["episodes"][0]["title"], stored["episodes"][0]["title"])

    def test_episode_plan_returns_the_source_hash_of_its_returned_snapshot(self):
        with patch.object(drama_api, "service", self.service):
            response = self.client.post("/api/drama/writer-task-1/episodes/plan")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertRegex(payload["sourceHash"], r"^[0-9a-f]{64}$")
        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(payload["sourceHash"], compile_writer_dashboard(stored).source_hash)
        self.assertEqual(payload["totalEpisodes"], len(payload["episodes"]))
        self.assertEqual(
            [episode["title"] for episode in payload["episodes"]],
            [episode["title"] for episode in stored["episodes"]],
        )

    def test_patch_script_persists_md_without_llm_and_rebuilds_derived_dashboard(self):
        revised_script = (
            "# 第1集 新的开始\n"
            "场景1：清晨车站\n"
            "苏遥：我们现在就出发。\n"
        )
        mature_task = self.repo.get_task("writer-task-1")
        mature_task.update({
            "current_stage": 8,
            "stage_name": "宣发Agent引流",
            "status": "completed",
            "video_url": "https://cdn.example/final.mp4",
            "short_link": "https://short.example/old",
            "pr_content": "旧宣发文案",
        })
        mature_task["assets"]["3_characters"] = [{"name": "林夏"}]
        mature_task["assets"]["4_storyboard"] = {"panels": ["旧分镜"]}
        mature_task.setdefault("logs", {})["4"] = "旧分镜日志"
        self.repo.save_task("writer-task-1", mature_task)
        source_hash = compile_writer_dashboard(self.repo.get_task("writer-task-1")).source_hash
        with (
            patch.object(drama_api, "service", self.service),
            patch.object(
                self.service.gateway,
                "call_llm",
                side_effect=AssertionError("手动保存剧本不得调用外部 LLM"),
            ),
            patch.object(
                self.service,
                "_extract_script_breakdown",
                side_effect=AssertionError("手动保存剧本不得调用 LLM 结构化分析"),
            ),
        ):
            requires_confirmation = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={
                    "content": revised_script,
                    "fileName": "revised-script.md",
                    "expectedSourceHash": source_hash,
                },
            )
            response = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={
                    "content": revised_script,
                    "fileName": "revised-script.md",
                    "expectedSourceHash": source_hash,
                    "confirmInvalidate": True,
                },
            )

        self.assertEqual(requires_confirmation.status_code, 409, requires_confirmation.text)
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["script"], revised_script)
        self.assertEqual(payload["scriptFileName"], "revised-script.md")
        self.assertEqual(payload["episodes"][0]["title"], "新的开始")
        self.assertEqual(payload["episodes"][0]["status"], "idle")
        self.assertIsNone(payload["episodes"][0]["videoUrl"])
        self.assertIn("苏遥", [role["name"] for role in payload["roles"]])
        self.assertNotIn("林夏", [role["name"] for role in payload["roles"]])

        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(stored["assets"]["2"], revised_script)
        self.assertEqual(stored["config"]["script_content"], revised_script)
        self.assertEqual(stored["config"]["script_name"], "revised-script.md")
        self.assertEqual(stored["config"]["episode_count"], 1)
        self.assertEqual(stored["total_episodes"], 1)
        self.assertEqual(stored["episodes"][0]["title"], "新的开始")
        self.assertNotIn("2_breakdown", stored["assets"])
        self.assertEqual(
            stored["assets"]["2_writer_dashboard"]["sourceHash"],
            payload["sourceHash"],
        )
        self.assertEqual(stored["current_stage"], 2)
        self.assertEqual(stored["status"], "idle")
        self.assertNotIn("3_characters", stored["assets"])
        self.assertNotIn("4_storyboard", stored["assets"])
        self.assertNotIn("4", stored["logs"])
        self.assertIsNone(stored["video_url"])
        self.assertIsNone(stored["short_link"])
        self.assertIsNone(stored["pr_content"])
        self.assertEqual(len(stored["script_archives"]), 1)
        self.assertEqual(
            stored["script_archives"][0]["episodes"][0]["video_url"],
            "https://cdn.example/ep1.mp4",
        )
        self.assertEqual(
            stored["script_archives"][0]["assets"]["3_characters"][0]["name"],
            "林夏",
        )

    def test_patch_script_accepts_txt_and_rejects_unsupported_or_unsafe_inputs(self):
        original = self.repo.get_task("writer-task-1")["assets"]["2"]
        source_hash = compile_writer_dashboard(self.repo.get_task("writer-task-1")).source_hash
        with patch.object(drama_api, "service", self.service):
            accepted = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={
                    "content": "场景1：码头\n赵宁：收到。",
                    "fileName": "draft.TXT",
                    "expectedSourceHash": source_hash,
                    "confirmInvalidate": True,
                },
            )
            unsupported = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={"content": "不会保存", "fileName": "draft.pdf"},
            )
            traversing = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={"content": "不会保存", "fileName": "../draft.md"},
            )
            null_byte = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={"content": "场景\x00内容", "fileName": "draft.md"},
            )

        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["script"], "场景1：码头\n赵宁：收到。")
        self.assertEqual(unsupported.status_code, 422, unsupported.text)
        self.assertEqual(traversing.status_code, 422, traversing.text)
        self.assertEqual(null_byte.status_code, 422, null_byte.text)
        stored_content = self.repo.get_task("writer-task-1")["assets"]["2"]
        self.assertNotEqual(stored_content, original)
        self.assertEqual(stored_content, "场景1：码头\n赵宁：收到。")

    def test_patch_script_rejects_blank_oversized_and_stale_edits(self):
        source_hash = compile_writer_dashboard(self.repo.get_task("writer-task-1")).source_hash
        with patch.object(drama_api, "service", self.service):
            blank = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={"content": " \n\t ", "fileName": "draft.md", "expectedSourceHash": source_hash},
            )
            oversized = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={"content": "剧" * 700_000, "fileName": "draft.md", "expectedSourceHash": source_hash},
            )
            stale = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={
                    "content": "第1集 不应保存",
                    "fileName": "draft.md",
                    "expectedSourceHash": "0" * 64,
                    "confirmInvalidate": True,
                },
            )
            oversized_body = self.client.patch(
                "/api/drama/writer-task-1/script",
                content=b"{}",
                headers={"Content-Length": str(SCRIPT_UPDATE_REQUEST_MAX_BYTES + 1)},
            )

        self.assertEqual(blank.status_code, 422, blank.text)
        self.assertEqual(oversized.status_code, 422, oversized.text)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(oversized_body.status_code, 413, oversized_body.text)
        self.assertEqual(self.repo.get_task("writer-task-1")["assets"]["2"], _task()["assets"]["2"])

    def test_patch_script_noop_preserves_completed_media_and_running_edits_conflict(self):
        task = self.repo.get_task("writer-task-1")
        source_hash = compile_writer_dashboard(task).source_hash
        with patch.object(drama_api, "service", self.service):
            noop = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={"content": task["assets"]["2"], "expectedSourceHash": source_hash},
            )

            running = self.repo.get_task("writer-task-1")
            running["stage_progress"] = {"status": "running", "stage": 4}
            self.repo.save_task("writer-task-1", running)
            running_hash = compile_writer_dashboard(running).source_hash
            conflict = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={
                    "content": "第1集 运行中不应覆盖",
                    "fileName": "draft.md",
                    "expectedSourceHash": running_hash,
                    "confirmInvalidate": True,
                },
            )

        self.assertEqual(noop.status_code, 200, noop.text)
        preserved = self.repo.get_task("writer-task-1")
        self.assertEqual(preserved["episodes"][0]["status"], "completed")
        self.assertEqual(preserved["episodes"][0]["video_url"], "https://cdn.example/ep1.mp4")
        self.assertEqual(conflict.status_code, 409, conflict.text)

    def test_patch_script_rejects_top_level_running_task_even_without_running_progress(self):
        task = self.repo.get_task("writer-task-1")
        task["status"] = "running"
        task["stage_progress"] = {"status": "success", "stage": 3}
        self.repo.save_task("writer-task-1", task)
        source_hash = compile_writer_dashboard(task).source_hash

        with patch.object(drama_api, "service", self.service):
            response = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={
                    "content": "第1集 运行中不得覆盖",
                    "expectedSourceHash": source_hash,
                    "confirmInvalidate": True,
                },
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("等待当前生成结束", response.json()["detail"])
        self.assertEqual(
            self.repo.get_task("writer-task-1")["assets"]["2"],
            task["assets"]["2"],
        )

    def test_stale_stage_failure_does_not_mark_the_new_script_revision_failed(self):
        task = self.repo.get_task("writer-task-1")
        task["script_revision"] = 1
        task["status"] = "running"
        self.repo.save_task("writer-task-1", task)

        def superseded_stage(*_args, **_kwargs):
            def advance_revision(current):
                current["script_revision"] = 2
                current["status"] = "idle"
                current["assets"]["2"] = "第1集 新版本"
                current["fail_reason"] = None

            self.repo.mutate_task("writer-task-1", advance_revision)
            raise RuntimeError("旧版本调用失败")

        with patch.object(self.service, "_execute_stage_blocking", side_effect=superseded_stage):
            with self.assertRaises(StaleTaskWriteError):
                asyncio.run(self.service.execute_stage("writer-task-1", 3))

        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(stored["script_revision"], 2)
        self.assertEqual(stored["status"], "idle")
        self.assertEqual(stored["assets"]["2"], "第1集 新版本")
        self.assertIsNone(stored["fail_reason"])

    def test_stage_failure_marks_the_revision_claimed_after_a_preclaim_script_update(self):
        task = self.repo.get_task("writer-task-1")
        task["script_revision"] = 1
        task["status"] = "idle"
        self.repo.save_task("writer-task-1", task)
        source_hash = compile_writer_dashboard(task).source_hash
        claim_entered = threading.Event()
        allow_claim = threading.Event()
        claimed_revisions: list[int] = []
        original_claim = self.service._claim_stage_task

        def delayed_claim(task_id: str, stage: int):
            claim_entered.set()
            if not allow_claim.wait(timeout=2):
                raise TimeoutError("测试未释放阶段 claim")
            return original_claim(task_id, stage)

        def fail_claimed_revision(*_args, **kwargs):
            claimed_revisions.append(int(kwargs["_claimed_task"]["script_revision"]))
            raise RuntimeError("新版本 provider 失败")

        async def run_race():
            with (
                patch.object(self.service, "_claim_stage_task", side_effect=delayed_claim),
                patch.object(
                    self.service,
                    "_execute_stage_blocking",
                    side_effect=fail_claimed_revision,
                ),
            ):
                execution = asyncio.create_task(self.service.execute_stage("writer-task-1", 3))
                try:
                    entered = await asyncio.wait_for(
                        asyncio.to_thread(claim_entered.wait, 1),
                        timeout=2,
                    )
                    self.assertTrue(entered)
                    self.service.update_script(
                        "writer-task-1",
                        content="第1集 在线程 claim 前保存的新版本",
                        expected_source_hash=source_hash,
                        confirm_invalidate=True,
                        owner_user_id="writer-user",
                    )
                finally:
                    allow_claim.set()
                with self.assertRaisesRegex(RuntimeError, "新版本 provider 失败"):
                    await execution

        asyncio.run(run_race())

        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(claimed_revisions, [2])
        self.assertEqual(stored["script_revision"], 2)
        self.assertEqual(stored["assets"]["2"], "第1集 在线程 claim 前保存的新版本")
        self.assertEqual(stored["status"], "failed")
        self.assertIn("新版本 provider 失败", stored["fail_reason"])

    def test_stage_claimed_by_old_revision_cannot_fail_a_newer_script(self):
        task = self.repo.get_task("writer-task-1")
        task["script_revision"] = 1
        task["status"] = "idle"
        self.repo.save_task("writer-task-1", task)
        worker_claimed = threading.Event()
        allow_failure = threading.Event()

        def fail_after_claim(*_args, **kwargs):
            self.assertEqual(kwargs["_claimed_task"]["script_revision"], 1)
            worker_claimed.set()
            if not allow_failure.wait(timeout=2):
                raise TimeoutError("测试未释放 provider 失败")
            raise RuntimeError("旧版本 provider 失败")

        async def run_race():
            with patch.object(
                self.service,
                "_execute_stage_blocking",
                side_effect=fail_after_claim,
            ):
                execution = asyncio.create_task(self.service.execute_stage("writer-task-1", 3))
                try:
                    claimed = await asyncio.wait_for(
                        asyncio.to_thread(worker_claimed.wait, 1),
                        timeout=2,
                    )
                    self.assertTrue(claimed)

                    def install_new_revision(current):
                        current["script_revision"] = 2
                        current["status"] = "idle"
                        current["assets"]["2"] = "第1集 claim 后的新版本"
                        current["stage_progress"] = None
                        current["fail_reason"] = None

                    self.repo.mutate_task("writer-task-1", install_new_revision)
                finally:
                    allow_failure.set()
                with self.assertRaises(StaleTaskWriteError):
                    await execution

        asyncio.run(run_race())

        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(stored["script_revision"], 2)
        self.assertEqual(stored["status"], "idle")
        self.assertEqual(stored["assets"]["2"], "第1集 claim 后的新版本")
        self.assertIsNone(stored["fail_reason"])

    def test_execute_all_stages_treats_stale_revision_as_superseded(self):
        task = self.repo.get_task("writer-task-1")
        task["script_revision"] = 1
        task["current_stage"] = 2
        task["status"] = "idle"
        self.repo.save_task("writer-task-1", task)

        async def superseded_stage(*_args, **_kwargs):
            def advance_revision(current):
                current["script_revision"] = 2
                current["status"] = "idle"
                current["assets"]["2"] = "第1集 新版本"
                current["fail_reason"] = None

            self.repo.mutate_task("writer-task-1", advance_revision)
            raise StaleTaskWriteError("旧版本已被替换")

        with patch.object(self.service, "execute_stage", side_effect=superseded_stage):
            asyncio.run(self.service.execute_all_stages("writer-task-1"))

        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(stored["script_revision"], 2)
        self.assertEqual(stored["status"], "idle")
        self.assertEqual(stored["assets"]["2"], "第1集 新版本")
        self.assertIsNone(stored["fail_reason"])

    def test_confirmed_script_update_keeps_the_twenty_first_archive(self):
        task = self.repo.get_task("writer-task-1")
        task["current_stage"] = 3
        task["assets"]["3_characters"] = [{"name": "旧角色"}]
        task["script_archives"] = [
            {"source_hash": f"archive-{index}", "sentinel": index}
            for index in range(20)
        ]
        self.repo.save_task("writer-task-1", task)
        source_hash = compile_writer_dashboard(task).source_hash

        self.service.update_script(
            "writer-task-1",
            content="第1集 新版本",
            expected_source_hash=source_hash,
            confirm_invalidate=True,
            owner_user_id="writer-user",
        )

        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(len(stored["script_archives"]), 21)
        self.assertEqual(stored["script_archives"][0]["sentinel"], 0)
        retention = stored["script_archive_retention"]
        self.assertEqual(retention["policy"], "bounded_reject_before_write")
        self.assertEqual(retention["current_entries"], 21)
        self.assertLessEqual(retention["current_total_bytes"], retention["max_total_bytes"])

    def test_archive_quota_returns_409_without_changing_script_or_assets(self):
        task = self.repo.get_task("writer-task-1")
        task["current_stage"] = 3
        task["assets"]["3_characters"] = [{"name": "必须保留的旧角色"}]
        self.repo.save_task("writer-task-1", task)
        source_hash = compile_writer_dashboard(task).source_hash
        self.service.script_archive_max_total_bytes = 256

        with patch.object(drama_api, "service", self.service):
            response = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={
                    "content": "第1集 容量超限的新版本",
                    "expectedSourceHash": source_hash,
                    "confirmInvalidate": True,
                },
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("归档容量上限", response.json()["detail"])
        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(stored["assets"]["2"], task["assets"]["2"])
        self.assertEqual(
            stored["assets"]["3_characters"],
            [{"name": "必须保留的旧角色"}],
        )
        self.assertNotIn("script_archives", stored)

    def test_archive_entry_limit_rejects_before_mutating_the_active_version(self):
        task = self.repo.get_task("writer-task-1")
        task["current_stage"] = 3
        task["assets"]["3_characters"] = [{"name": "必须保留的旧角色"}]
        task["script_archives"] = [
            {"source_hash": f"archive-{index}", "sentinel": index}
            for index in range(21)
        ]
        self.repo.save_task("writer-task-1", task)
        source_hash = compile_writer_dashboard(task).source_hash
        self.service.script_archive_max_entries = 21

        with patch.object(drama_api, "service", self.service):
            response = self.client.patch(
                "/api/drama/writer-task-1/script",
                json={
                    "content": "第1集 不应越过归档条目上限",
                    "expectedSourceHash": source_hash,
                    "confirmInvalidate": True,
                },
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("归档容量上限", response.json()["detail"])
        stored = self.repo.get_task("writer-task-1")
        self.assertEqual(stored["assets"]["2"], task["assets"]["2"])
        self.assertEqual(stored["assets"]["3_characters"], [{"name": "必须保留的旧角色"}])
        self.assertEqual(len(stored["script_archives"]), 21)
        self.assertEqual(stored["script_archives"][-1]["sentinel"], 20)

    def test_repository_rejects_a_snapshot_older_than_the_script_revision(self):
        stale = self.repo.get_task("writer-task-1")

        def advance(task):
            task["script_revision"] = 1

        self.repo.mutate_task("writer-task-1", advance)

        with self.assertRaises(StaleTaskWriteError):
            self.repo.save_task("writer-task-1", stale)

    def test_patch_script_reuses_task_ownership_boundary(self):
        source_hash = compile_writer_dashboard(self.repo.get_task("writer-task-1")).source_hash
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "another-user",
            "role": "user",
        }
        try:
            with patch.object(drama_api, "service", self.service):
                response = self.client.patch(
                    "/api/drama/writer-task-1/script",
                    json={
                        "content": "场景1：不会保存",
                        "fileName": "draft.md",
                        "expectedSourceHash": source_hash,
                    },
                )
        finally:
            app.dependency_overrides[get_current_user] = lambda: {
                "user_id": "writer-user",
                "role": "user",
            }

        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.repo.get_task("writer-task-1")["assets"]["2"], _task()["assets"]["2"])

    def test_missing_task_returns_not_found(self):
        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/missing/writer-dashboard")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()


class ScriptLibraryApiTests(unittest.TestCase):
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
        self.client = TestClient(
            _ClientAddressApp(app, (f"library-{self._testMethodName}", 50000)),
            cookies={"auth_token": auth_service.generate_token("writer-user")},
        )

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_current_user, None)
        self.temp.cleanup()

    def test_script_documents_support_full_crud(self):
        with patch.object(drama_api, "service", self.service):
            empty = self.client.get("/api/drama/writer-task-1/script-documents")
            created = self.client.post(
                "/api/drama/writer-task-1/script-documents",
                json={"name": "story.txt", "content": "第一章 一场车祸"},
            )
            document_id = created.json()["id"]
            listed = self.client.get("/api/drama/writer-task-1/script-documents")
            read = self.client.get(f"/api/drama/writer-task-1/script-documents/{document_id}")
            renamed = self.client.patch(
                f"/api/drama/writer-task-1/script-documents/{document_id}",
                json={"name": "episode_6.txt", "content": "第六章 西门庆下赌局"},
            )
            removed = self.client.delete(f"/api/drama/writer-task-1/script-documents/{document_id}")
            after = self.client.get("/api/drama/writer-task-1/script-documents")

        self.assertEqual(empty.json()["total"], 0)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(listed.json()["total"], 1)
        self.assertEqual(read.json()["content"], "第一章 一场车祸")
        self.assertEqual(read.json()["sizeBytes"], len("第一章 一场车祸".encode("utf-8")))
        self.assertEqual(renamed.json()["name"], "episode_6.txt")
        self.assertEqual(renamed.json()["content"], "第六章 西门庆下赌局")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(after.json()["total"], 0)

    def test_script_document_names_are_sanitized_and_missing_ids_404(self):
        with patch.object(drama_api, "service", self.service):
            traversal = self.client.post(
                "/api/drama/writer-task-1/script-documents",
                json={"name": "../../etc/passwd", "content": "x"},
            )
            extensionless = self.client.post(
                "/api/drama/writer-task-1/script-documents",
                json={"name": "剧本", "content": "x"},
            )
            missing = self.client.get("/api/drama/writer-task-1/script-documents/does-not-exist")
            empty_patch = self.client.patch(
                f"/api/drama/writer-task-1/script-documents/{traversal.json()['id']}",
                json={},
            )

        self.assertEqual(traversal.json()["name"], "passwd.txt")
        self.assertEqual(extensionless.json()["name"], "剧本.txt")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(empty_patch.status_code, 422)


class ProductionAssetExtractionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        task = _task()
        task["assets"]["2"] = (
            "**【场景1：建康城外乱葬岗 / 夜 / 暴雨初歇】**\n"
            "**关键道具**：金属钢笔（伪装铜簪）、烂布条\n"
            "**服装**：粗麻短褐\n"
            "**特效**：泥浆飞溅\n"
        )
        self.repo.save_task("writer-task-1", task)
        self.service = DramaService()
        self.service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "writer-user",
            "role": "user",
        }
        self.client = TestClient(
            _ClientAddressApp(app, (f"extract-{self._testMethodName}", 50000)),
            cookies={"auth_token": auth_service.generate_token("writer-user")},
        )

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_current_user, None)
        self.temp.cleanup()

    def test_preview_reports_only_assets_the_screenplay_names(self):
        with patch.object(drama_api, "service", self.service):
            scenes = self.client.get("/api/drama/writer-task-1/production-assets/scene")
            props = self.client.get("/api/drama/writer-task-1/production-assets/prop")
            costumes = self.client.get("/api/drama/writer-task-1/production-assets/costume")
            effects = self.client.get("/api/drama/writer-task-1/production-assets/effect")
            unsupported = self.client.get("/api/drama/writer-task-1/production-assets/music")

        self.assertIn("建康城外乱葬岗", [item["name"] for item in scenes.json()["items"]])
        self.assertIn("金属钢笔", [item["name"] for item in props.json()["items"]])
        self.assertIn("粗麻短褐", [item["name"] for item in costumes.json()["items"]])
        self.assertIn("泥浆飞溅", [item["name"] for item in effects.json()["items"]])
        self.assertEqual(unsupported.status_code, 404)

    def test_preview_prefers_the_structured_production_asset_catalog(self):
        task = _task()
        task["assets"]["2_breakdown"]["production_assets"] = {
            "scenes": [
                {"name": "祭坛边柴堆引火区", "description": "深夜，雪中祭火"},
                {"name": "含元殿", "description": "清晨朝会内景"},
            ],
            "props": [
                {"name": "火把", "description": "裴无咎持有的木柄火把"},
                {"name": "浇满灯油的干柴", "description": "沿祭坛码放"},
            ],
            "costumes": [{"name": "玄黑官袍", "description": "主体1夜戏服装"}],
            "effects": [
                {"name": "祭火蔓延", "description": "火舌沿柴枝爬向主体2"},
                {"name": "雪落火焰白汽", "description": "雪片落火后形成白汽与火星"},
            ],
        }
        self.repo.save_task("writer-task-1", task)

        with patch.object(drama_api, "service", self.service):
            scenes = self.client.get("/api/drama/writer-task-1/production-assets/scene").json()["items"]
            props = self.client.get("/api/drama/writer-task-1/production-assets/prop").json()["items"]
            costumes = self.client.get("/api/drama/writer-task-1/production-assets/costume").json()["items"]
            effects = self.client.get("/api/drama/writer-task-1/production-assets/effect").json()["items"]

        self.assertEqual([item["name"] for item in scenes], ["祭坛边柴堆引火区", "含元殿"])
        self.assertEqual([item["name"] for item in props], ["火把", "浇满灯油的干柴"])
        self.assertEqual([item["name"] for item in costumes], ["玄黑官袍"])
        self.assertEqual([item["name"] for item in effects], ["祭火蔓延", "雪落火焰白汽"])

    def test_preview_recognizes_plain_stage_two_scene_headings(self):
        task = _task()
        task["assets"].pop("2_breakdown", None)
        task["assets"]["2"] = (
            "第1集 血碑\n\n"
            "场景1：太常寺天文台 夜 内景\n"
            "镜头：中近景 缓推\n沈砚跪在青石阶上。\n\n"
            "场景2：含元殿 晨 内景\n"
            "镜头：中景 固定\n群臣立于丹墀两侧。\n"
        )
        self.repo.save_task("writer-task-1", task)

        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/writer-task-1/production-assets/scene")

        self.assertEqual(
            [item["name"] for item in response.json()["items"]],
            ["太常寺天文台", "含元殿"],
        )

    def test_legacy_project_gets_a_persisted_complete_production_catalog(self):
        response = """{
          "scenes": [{"name": "雨夜办公室", "description": "夜，内景"}],
          "props": [{"name": "匿名录音带", "description": "林夏收到的证物"}],
          "costumes": [{"name": "深色风衣", "description": "林夏雨夜造型"}],
          "effects": [{"name": "窗外暴雨", "description": "雨线与玻璃水痕"}]
        }"""

        with patch.object(self.service.gateway, "call_llm", return_value=response):
            catalog = self.service.ensure_production_asset_catalog("writer-task-1")

        self.assertEqual([item["name"] for item in catalog["props"]], ["匿名录音带"])
        persisted = self.repo.get_task("writer-task-1")
        self.assertEqual(
            persisted["assets"]["2_breakdown"]["production_assets"],
            catalog,
        )

    def test_stage_two_breakdown_contract_requires_every_production_asset_category(self):
        contract = self.service._breakdown_contract(15, "test-video")

        for field in ('"scenes"', '"props"', '"costumes"', '"effects"'):
            self.assertIn(field, contract)
        self.assertIn("production_assets", contract)

    def test_bulk_sync_imports_all_non_actor_categories_idempotently(self):
        task = _task()
        task["assets"]["2_breakdown"]["production_assets"] = {
            "scenes": [{"name": "祭坛边柴堆引火区", "description": "雪夜外景"}],
            "props": [
                {"name": "火把", "description": "木柄火把"},
                {"name": "灯油干柴", "description": "祭坛边码放"},
            ],
            "costumes": [{"name": "玄黑官袍", "description": "裴无咎造型"}],
            "effects": [{"name": "祭火蔓延", "description": "火舌与雪汽"}],
        }
        self.repo.save_task("writer-task-1", task)

        class MemoryElementStore:
            def __init__(self):
                self.items = []

            async def list_elements(self, owner_id, kind, page, page_size):
                found = [item for item in self.items if item.kind == kind]
                return found, len(found)

            async def create_element(self, *, owner_id, kind, name, description, metadata):
                item = SimpleNamespace(
                    id=f"{kind}-{len(self.items) + 1}", kind=kind, name=name,
                    description=description, metadata_json=metadata,
                )
                self.items.append(item)
                return item

        store = MemoryElementStore()
        app.dependency_overrides[get_platform_store] = lambda: store
        try:
            with patch.object(drama_api, "service", self.service):
                first = self.client.post("/api/drama/writer-task-1/production-assets/sync")
                second = self.client.post("/api/drama/writer-task-1/production-assets/sync")
        finally:
            app.dependency_overrides.pop(get_platform_store, None)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["created"], 5)
        self.assertEqual(first.json()["kinds"], {
            "scene": 1, "prop": 2, "costume": 1, "effect": 1,
        })
        self.assertEqual(second.json()["created"], 0)
        self.assertEqual(second.json()["skipped"], 5)

    def test_actor_extraction_includes_descriptions_and_reference_images(self):
        task = _task()
        task["assets"]["3_characters"] = [
            {
                "name": "沈砚之",
                "role": "男主角",
                "desc": "28岁男性，椭圆脸，戴银丝半框眼镜。",
                "sheet": "https://cdn.example/sheet.png",
                "views": [
                    {"view": "front", "image_url": "http://localhost:8000/media/character_views/x/1_front.png"},
                ],
            },
            {"name": "王景略", "role": "权臣", "desc": "45-50岁男性，方颌长脸。", "views": []},
        ]
        self.repo.save_task("writer-task-1", task)

        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/writer-task-1/production-assets/actor")

        items = {item["name"]: item for item in response.json()["items"]}
        self.assertIn("沈砚之", items)
        self.assertIn("银丝半框眼镜", items["沈砚之"]["description"])
        self.assertTrue(items["沈砚之"]["image_url"].endswith("1_front.png"))
        # A character without any render still imports, just without an image.
        self.assertEqual(items["王景略"]["image_url"], "")
        # Roles named only by the writer breakdown are still offered.
        self.assertIn("周教授", items)

    def test_actor_extraction_falls_back_to_breakdown_roles_and_scene_cast(self):
        task = _task()
        task["assets"].pop("3_characters", None)
        self.repo.save_task("writer-task-1", task)

        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/writer-task-1/production-assets/actor")

        names = [item["name"] for item in response.json()["items"]]
        self.assertIn("林夏", names)
        self.assertIn("周教授", names)


class TaskListingCostTests(unittest.TestCase):
    """The lobby polls the task list every 1.5s; it must not re-read per task."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        for index in range(1, 7):
            task = _task()
            task["task_id"] = f"writer-task-{index}"
            # The listing endpoint serializes through DramaTaskResponse.
            task["current_stage"] = 2
            task["stage_name"] = "专业编剧剧本创作"
            task["logs"] = {"2": "剧本已生成"}
            self.repo.save_task(f"writer-task-{index}", task)
        self.service = DramaService()
        self.service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "writer-user",
            "role": "admin",
        }
        self.client = TestClient(
            _ClientAddressApp(app, (f"listing-{self._testMethodName}", 50000)),
            cookies={"auth_token": auth_service.generate_token("writer-user")},
        )

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_current_user, None)
        self.temp.cleanup()

    def test_listing_issues_no_per_task_fetches(self):
        list_calls = []
        get_calls = []
        original_list = TaskRepository.list_all_tasks
        original_get = TaskRepository.get_task

        def counting_list(repo_self):
            list_calls.append(1)
            return original_list(repo_self)

        def counting_get(repo_self, task_id):
            get_calls.append(task_id)
            return original_get(repo_self, task_id)

        with patch.object(drama_api, "service", self.service), \
             patch.object(TaskRepository, "list_all_tasks", counting_list), \
             patch.object(TaskRepository, "get_task", counting_get):
            response = self.client.get("/api/drama/list")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 6)
        # One bulk listing; hydration must not go back to the store per task.
        self.assertEqual(len(list_calls), 1)
        self.assertEqual(get_calls, [], f"unexpected per-task fetches: {get_calls}")

    def test_listing_returns_summaries_and_leaves_assets_to_the_status_route(self):
        with patch.object(drama_api, "service", self.service):
            listed = self.client.get("/api/drama/list").json()
            single = self.client.get("/api/drama/writer-task-1/status").json()

        by_id = {item["taskId"]: item for item in listed}
        self.assertIn("writer-task-1", by_id)
        summary = by_id["writer-task-1"]
        # Everything the lobby renders is present...
        for field in ("taskId", "currentStage", "stageName", "status", "config"):
            self.assertIn(field, summary)
        self.assertEqual(summary["config"]["titleSuggestion"], "十二小时")
        # ...but the bulky generated assets are not shipped on every poll.
        self.assertNotIn("assets", summary)
        self.assertNotIn("logs", summary)
        # They remain available per project through the status route.
        self.assertIn("2_breakdown", single["assets"])


class TaskStatusRevalidationTests(unittest.TestCase):
    """The workbench polls /status every 1.5s; unchanged polls must be free."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        task = _task()
        task["current_stage"] = 2
        task["stage_name"] = "专业编剧剧本创作"
        task["logs"] = {"2": "剧本已生成"}
        self.repo.save_task("writer-task-1", task)
        self.service = DramaService()
        self.service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "writer-user",
            "role": "admin",
        }
        self.client = TestClient(
            _ClientAddressApp(app, (f"etag-{self._testMethodName}", 50000)),
            cookies={"auth_token": auth_service.generate_token("writer-user")},
        )

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_current_user, None)
        self.temp.cleanup()

    def test_an_unchanged_task_revalidates_to_an_empty_304(self):
        with patch.object(drama_api, "service", self.service):
            first = self.client.get("/api/drama/writer-task-1/status")
            etag = first.headers["etag"]
            repeat = self.client.get(
                "/api/drama/writer-task-1/status",
                headers={"If-None-Match": etag},
            )

        self.assertEqual(first.status_code, 200)
        self.assertIn("2_breakdown", first.json()["assets"])
        self.assertEqual(first.headers["cache-control"], "private, no-cache")
        self.assertEqual(repeat.status_code, 304)
        self.assertEqual(repeat.content, b"")
        self.assertEqual(repeat.headers["etag"], etag)

    def test_a_changed_task_gets_a_new_etag_and_the_full_body(self):
        with patch.object(drama_api, "service", self.service):
            first = self.client.get("/api/drama/writer-task-1/status")
            stale_etag = first.headers["etag"]

            changed = self.repo.get_task("writer-task-1")
            changed["status"] = "running"
            self.repo.save_task("writer-task-1", changed)

            after = self.client.get(
                "/api/drama/writer-task-1/status",
                headers={"If-None-Match": stale_etag},
            )

        # A stale validator must never be answered with 304.
        self.assertEqual(after.status_code, 200)
        self.assertNotEqual(after.headers["etag"], stale_etag)
        self.assertEqual(after.json()["status"], "running")

    def test_the_response_is_not_cached_across_accounts(self):
        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/writer-task-1/status")

        # A shared cache must not replay one account's project to another.
        self.assertIn("private", response.headers["cache-control"])
        self.assertEqual(response.headers["vary"], "Cookie")


class CharacterExtractionTests(unittest.TestCase):
    """Production labels share the "名称：内容" shape with dialogue lines."""

    def test_structural_labels_never_become_characters(self):
        task = _task()
        # A screenplay written to the house format carries these label rows.
        task["assets"]["2"] = (
            "第1集 匿名录音\n"
            "场景1：雨夜办公室\n"
            "双轨节奏：情节推进 / 情感压抑\n"
            "时长预估：90 秒\n"
            "陈九：你隐瞒了什么？\n"
            "小六：我什么都没说。\n"
        )
        task["assets"].pop("2_breakdown")

        dashboard = compile_writer_dashboard(task)
        names = {role.name for role in dashboard.roles}

        self.assertIn("陈九", names)
        self.assertIn("小六", names)
        self.assertNotIn("双轨节奏", names)
        self.assertNotIn("时长预估", names)
        for edge in dashboard.relationships:
            self.assertNotIn("双轨节奏", (edge.from_, edge.to))

    def test_a_label_supplied_by_the_model_is_dropped_too(self):
        task = _task()
        task["assets"]["2_breakdown"]["scenes"][0]["characters"] = ["陈九", "双轨节奏"]
        task["assets"]["2_breakdown"]["roles"] = [{"name": "情绪钩子", "position": "反派"}]
        task["assets"]["2_breakdown"]["relationships"] = [
            {"from": "陈九", "to": "双轨节奏", "relation": "对峙"},
            {"from": "陈九", "to": "小六", "relation": "主仆"},
        ]

        dashboard = compile_writer_dashboard(task)

        self.assertNotIn("情绪钩子", {role.name for role in dashboard.roles})
        self.assertEqual(
            [(edge.from_, edge.to, edge.relation) for edge in dashboard.relationships],
            [("陈九", "小六", "主仆")],
        )

    def test_a_co_occurrence_graph_is_flagged_as_inferred(self):
        task = _task()
        task["assets"]["2_breakdown"].pop("relationships")

        dashboard = compile_writer_dashboard(task)

        self.assertTrue(dashboard.relationships_inferred)
        self.assertTrue(all("同场互动" in edge.relation for edge in dashboard.relationships))

    def test_analysed_relations_are_not_flagged(self):
        self.assertFalse(compile_writer_dashboard(_task()).relationships_inferred)


class StorySynopsisFallbackTests(unittest.TestCase):
    """Without a breakdown the brief used to show the raw file head."""

    def test_the_metadata_banner_is_not_used_as_the_synopsis(self):
        task = _task()
        task["assets"].pop("2_breakdown")
        task["assets"]["2"] = (
            "《流氓天子》分集剧本\n"
            "【series_bible / 世界观与人物档案】\n"
            "输入来源：总导演策划大纲 (director_constitution / highlight_map)\n"
            "- 全剧30集，首季试水；每集90-150秒。\n"
            "核心角色：陈九、小六、沈崇\n"
            "陈九本是市井混混，一夜之间被认作失落的皇子，被迫在朝堂与街市之间求生。\n"
        )

        synopsis = compile_writer_dashboard(task).overview.synopsis

        self.assertIn("陈九本是市井混混", synopsis)
        self.assertNotIn("series_bible", synopsis)
        self.assertNotIn("输入来源", synopsis)
        self.assertNotIn("director_constitution", synopsis)

    def test_a_declared_synopsis_line_wins(self):
        task = _task()
        task["assets"].pop("2_breakdown")
        task["assets"]["2"] = "【档案】\n故事梗概：陈九在一夜之间从混混变成皇子。\n场景1：市井长街\n"

        self.assertEqual(
            compile_writer_dashboard(task).overview.synopsis,
            "陈九在一夜之间从混混变成皇子。",
        )


class RelationshipAnalysisTests(unittest.TestCase):
    """Repairing a co-occurrence graph must yield real dramatic relations."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        task = _task()
        task["assets"]["2_breakdown"].pop("relationships")
        task["assets"]["2_breakdown"].pop("roles")
        self.repo.save_task("writer-task-1", task)
        self.service = DramaService()
        self.service.repo = self.repo

    def tearDown(self):
        self.temp.cleanup()

    def _stub_gateway(self, response: str):
        class _Gateway:
            def __init__(self):
                self.calls = []

            def call_llm(self, *args, **kwargs):
                self.calls.append(args)
                return response

        gateway = _Gateway()
        self.service.gateway = gateway
        return gateway

    def test_analysis_replaces_the_inferred_edges_and_persists(self):
        self._stub_gateway(
            '{"roles": [{"name": "林夏", "position": "女主角"}],'
            ' "relationships": [{"from": "林夏", "to": "周教授", "relation": "师徒反目",'
            ' "bidirectional": false}]}'
        )

        dashboard = self.service.analyze_relationships("writer-task-1")

        self.assertFalse(dashboard.relationships_inferred)
        self.assertEqual(
            [(edge.from_, edge.to, edge.relation) for edge in dashboard.relationships],
            [("林夏", "周教授", "师徒反目")],
        )
        stored = self.repo.get_task("writer-task-1")["assets"]["2_breakdown"]
        self.assertEqual(stored["relationships"][0]["relation"], "师徒反目")
        self.assertEqual(stored["roles"][0]["position"], "女主角")

    def test_richer_stage_two_casting_is_never_overwritten(self):
        task = self.repo.get_task("writer-task-1")
        task["assets"]["2_breakdown"]["roles"] = [{"name": "林夏", "position": "女主角"}]
        self.repo.save_task("writer-task-1", task)
        self._stub_gateway(
            '{"roles": [{"name": "林夏", "position": "其它角色"}],'
            ' "relationships": [{"from": "林夏", "to": "周教授", "relation": "师徒反目"}]}'
        )

        self.service.analyze_relationships("writer-task-1")

        stored = self.repo.get_task("writer-task-1")["assets"]["2_breakdown"]
        self.assertEqual(stored["roles"], [{"name": "林夏", "position": "女主角"}])

    def test_an_unusable_model_reply_is_reported_not_persisted(self):
        self._stub_gateway("模型今天不想输出 JSON")

        with self.assertRaises(ValueError):
            self.service.analyze_relationships("writer-task-1")

        self.assertNotIn("relationships", self.repo.get_task("writer-task-1")["assets"]["2_breakdown"])

    def test_a_project_without_a_script_is_rejected(self):
        task = self.repo.get_task("writer-task-1")
        task["assets"]["2"] = ""
        task["config"]["script_content"] = ""
        self.repo.save_task("writer-task-1", task)
        self._stub_gateway("{}")

        with self.assertRaises(ValueError):
            self.service.analyze_relationships("writer-task-1")

    def test_a_missing_task_is_not_an_error(self):
        self._stub_gateway("{}")
        self.assertIsNone(self.service.analyze_relationships("no-such-task"))


class DramaTitleResolutionTests(unittest.TestCase):
    """A project is created from a chat prompt; the prompt is not the drama's name."""

    def test_a_creation_request_is_never_shown_as_a_title(self):
        from app.core.writer_dashboard import is_instruction_like

        for prompt in (
            "请帮我生成一个古装权谋短剧",
            "帮我写一部甜宠短剧",
            "我想要一个悬疑短剧",
            "给我来一部战神归来",
            "生成一个都市爽剧剧本",
        ):
            self.assertTrue(is_instruction_like(prompt), prompt)

    def test_a_real_drama_name_is_not_mistaken_for_a_request(self):
        from app.core.writer_dashboard import is_instruction_like

        for name in ("流氓天子", "乱葬坑里有人醒", "十二小时", "赘婿归来", "长安一片月"):
            self.assertFalse(is_instruction_like(name), name)

    def test_the_screenplay_headline_supplies_the_name(self):
        from app.core.writer_dashboard import script_title

        self.assertEqual(script_title("《流氓天子》分集剧本\n【series_bible】\n第1集 市井"), "流氓天子")
        self.assertEqual(script_title("剧名：乱葬坑里有人醒\n第1集"), "乱葬坑里有人醒")
        self.assertEqual(script_title("**片名：长安一片月**\n第1集"), "长安一片月")

    def test_a_guideline_reference_is_not_taken_as_the_name(self):
        from app.core.writer_dashboard import script_title

        script = "参考《AI漫剧短剧剧本黄金叙事结构》撰写\n《流氓天子》分集剧本\n第1集 市井"
        self.assertEqual(script_title(script), "流氓天子")

    def test_the_dashboard_prefers_the_analysed_title_over_the_prompt(self):
        task = _task()
        task["config"]["title_suggestion"] = "请帮我生成一个古装权谋短剧"
        task["assets"]["2_breakdown"]["overview"]["title"] = "流氓天子"

        dashboard = compile_writer_dashboard(task)

        self.assertEqual(dashboard.title, "流氓天子")
        self.assertEqual(dashboard.overview.title, "流氓天子")

    def test_the_screenplay_is_used_when_the_analysis_has_no_title(self):
        task = _task()
        task["config"]["title_suggestion"] = "请帮我生成一个古装权谋短剧"
        task["assets"]["2"] = "《流氓天子》分集剧本\n第1集 市井无赖\n陈九：台词。"

        self.assertEqual(compile_writer_dashboard(task).title, "流氓天子")

    def test_a_prompt_with_no_other_source_falls_back_to_a_placeholder(self):
        task = _task()
        task["config"]["title_suggestion"] = "请帮我生成一个古装权谋短剧"
        task["assets"]["2"] = "第1集 市井无赖\n陈九：台词。"
        task["assets"]["2_breakdown"]["overview"].pop("title", None)

        # Better an honest placeholder than the user's own request as a title.
        self.assertEqual(compile_writer_dashboard(task).title, "未命名短剧")

    def test_a_deliberate_project_name_is_still_respected(self):
        task = _task()
        task["config"]["title_suggestion"] = "乱葬坑里有人醒"
        task["assets"]["2"] = "第1集 苏醒\n沈砚之：台词。"
        task["assets"]["2_breakdown"]["overview"].pop("title", None)

        self.assertEqual(compile_writer_dashboard(task).title, "乱葬坑里有人醒")

    def test_an_analysed_title_that_is_itself_a_request_is_rejected(self):
        task = _task()
        task["config"]["title_suggestion"] = "乱葬坑里有人醒"
        task["assets"]["2_breakdown"]["overview"]["title"] = "请帮我生成一个古装权谋短剧"

        self.assertEqual(compile_writer_dashboard(task).title, "乱葬坑里有人醒")

    def test_book_title_marks_are_stripped_from_the_analysed_name(self):
        task = _task()
        task["assets"]["2_breakdown"]["overview"]["title"] = "《流氓天子》"

        self.assertEqual(compile_writer_dashboard(task).title, "流氓天子")

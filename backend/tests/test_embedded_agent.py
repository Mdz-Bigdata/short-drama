"""The embedded tool assistant asks before it spends, and the MCP server exposes the same tools behind a token."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import auth_service, get_current_user
from app.core import embedded_agent
from app.core.agent_tools import ToolError, catalog
from app.core.model_configuration import ModelSecretCipher
from app.platform.dependencies import get_model_secret_cipher, get_platform_store
from app.platform.store import PlatformStore
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from main import app


def _task(task_id="ag-1", owner="u1") -> dict:
    return {
        "task_id": task_id, "owner_user_id": owner, "status": "idle", "current_stage": 1, "stage_name": "总导演策划",
        "config": {"title_suggestion": "暗室回声", "episode_count": 2, "llm_model": "deepseek", "video_model": "seedance2.0"},
        "assets": {"1": "方案"}, "logs": {}, "chat_history": [],
    }


class ToolCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        self.repo.save_task("ag-1", _task())
        self.repo.save_task("ag-2", _task("ag-2", owner="someone-else"))
        self.user = {"user_id": "u1", "role": "user"}

    def test_the_catalog_describes_every_tool_with_a_schema_and_an_effect(self):
        names = {t["name"] for t in catalog.describe()}
        self.assertTrue({"list_projects", "get_project", "get_screenplay", "review_episode", "edit_timeline", "run_stage", "run_all", "render_timeline"} <= names)
        run_stage = catalog.get("run_stage")
        self.assertEqual(run_stage.effect, "paid")
        self.assertIn("confirm", run_stage.input_schema["properties"])
        self.assertEqual(run_stage.input_schema["required"], ["task_id", "stage"])

    def test_read_tools_answer_for_the_owner_and_refuse_someone_elses_project(self):
        listed = catalog.call("list_projects", {}, service=self.service, user=self.user)
        self.assertEqual([p["task_id"] for p in listed["result"]["projects"]], ["ag-1"])
        project = catalog.call("get_project", {"task_id": "ag-1"}, service=self.service, user=self.user)
        self.assertTrue(project["ok"])
        self.assertEqual(project["result"]["next_stage"], 2)
        with self.assertRaisesRegex(ToolError, "不属于当前用户"):
            catalog.call("get_project", {"task_id": "ag-2"}, service=self.service, user=self.user)
        with self.assertRaisesRegex(ToolError, "不存在"):
            catalog.call("get_project", {"task_id": "nope"}, service=self.service, user=self.user)
        with self.assertRaisesRegex(ToolError, "没有叫"):
            catalog.call("explode", {"task_id": "ag-1"}, service=self.service, user=self.user)
        admin = catalog.call("get_project", {"task_id": "ag-2"}, service=self.service, user={"user_id": "x", "role": "admin"})
        self.assertTrue(admin["ok"])

    def test_a_paid_tool_waits_for_confirmation_and_a_tool_error_is_a_result_not_a_crash(self):
        pending = catalog.call("run_stage", {"task_id": "ag-1", "stage": 2}, service=self.service, user=self.user)
        self.assertEqual((pending["ok"], pending["needs_confirmation"], pending["arguments"]), (False, True, {"task_id": "ag-1", "stage": 2}))
        with patch.object(DramaService, "_claim_stage_task", return_value={"task_id": "ag-1"}) as claim, \
             patch("app.core.agent_tools._start_background") as start:
            done = catalog.call("run_stage", {"task_id": "ag-1", "stage": 2, "confirm": True}, service=self.service, user=self.user)
        self.assertEqual(done["result"], {"started": True, "stage": 2})
        claim.assert_called_once_with("ag-1", 2)
        start.assert_called_once()
        failed = catalog.call("pause_project", {"task_id": "ag-1", "stop": False}, service=self.service, user=self.user)
        self.assertTrue(failed["ok"])
        no_review = catalog.call("review_episode", {"task_id": "ag-1", "episode": 1, "action": "confirm"}, service=self.service, user=self.user)
        self.assertFalse(no_review["ok"])
        self.assertIn("结构化", no_review["error"])


class EmbeddedAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        self.repo.save_task("ag-1", _task())
        self.answers: list[str] = []
        self.prompts: list[str] = []

        def call_llm(model, system_prompt, user_prompt, *args, **kwargs):
            self.prompts.append(user_prompt)
            return self.answers.pop(0) if self.answers else '{"reply": "好的。"}'

        patcher = patch.object(self.service.gateway, "call_llm", side_effect=call_llm)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_model_reads_with_a_tool_then_answers(self):
        self.answers = [json.dumps({"thought": "先看状态", "tool": "get_project", "arguments": {}}), json.dumps({"reply": "项目在第 1 阶段，下一步是编剧。"})]
        result = asyncio.run(self.service.assistant_message("ag-1", "/agent 现在到哪一步了？", user={"user_id": "u1", "role": "user"}))
        self.assertEqual(result["action"], "agent")
        self.assertEqual(result["reply"], "项目在第 1 阶段，下一步是编剧。")
        self.assertEqual([c["tool"] for c in result["tool_calls"]], ["get_project"])
        self.assertTrue(result["tool_calls"][0]["result"]["ok"])
        self.assertIn("[工具 get_project 返回]", self.prompts[1], "the tool's answer is fed back to the model")
        stored = self.repo.get_task("ag-1")
        self.assertEqual(stored["chat_history"][-1]["content"], "项目在第 1 阶段，下一步是编剧。")
        self.assertEqual([h["role"] for h in stored[embedded_agent.HISTORY_KEY]], ["user", "tool", "assistant"])

    def test_a_paid_tool_becomes_a_proposal_that_confirm_runs_and_cancel_drops(self):
        self.answers = [json.dumps({"tool": "run_stage", "arguments": {"stage": 2, "confirm": True}})]
        proposed = asyncio.run(self.service.assistant_message("ag-1", "/agent 开始写剧本", user={"user_id": "u1", "role": "user"}))
        self.assertEqual(proposed["proposal"], {"tool": "run_stage", "arguments": {"task_id": "ag-1", "stage": 2}, "message": "「执行一个阶段」会调用付费模型；确认后再执行（confirm=true）"})
        self.assertIn("/confirm", proposed["reply"])
        self.assertIn(embedded_agent.PENDING_KEY, self.repo.get_task("ag-1"))

        with patch.object(DramaService, "_claim_stage_task", return_value={"task_id": "ag-1"}), patch("app.core.agent_tools._start_background"):
            confirmed = asyncio.run(self.service.assistant_message("ag-1", "/confirm", user={"user_id": "u1", "role": "user"}))
        self.assertIn("已执行「run_stage」", confirmed["reply"])
        self.assertNotIn(embedded_agent.PENDING_KEY, self.repo.get_task("ag-1"))

        nothing = asyncio.run(self.service.assistant_message("ag-1", "/cancel", user={"user_id": "u1", "role": "user"}))
        self.assertEqual(nothing["reply"], "没有待确认的操作。")

    def test_a_plain_answer_is_taken_as_the_reply_and_other_messages_still_reach_the_workflow_assistant(self):
        self.answers = ["我直接说：先完成编剧。"]
        result = asyncio.run(self.service.assistant_message("ag-1", "/agent 建议？", user={"user_id": "u1", "role": "user"}))
        self.assertEqual(result["reply"], "我直接说：先完成编剧。")
        status = asyncio.run(self.service.assistant_message("ag-1", "/status", user={"user_id": "u1", "role": "user"}))
        self.assertEqual(status["action"], "none")


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'platform.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            self.user, _ = await self.store.create_user(email="mcp@example.com", phone=None, password="mcp-user-password")

        asyncio.run(prepare())
        self.addCleanup(lambda: asyncio.run(self.store.close()))
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        self.repo.save_task("ag-1", _task(owner=self.user.id))
        app.dependency_overrides[get_platform_store] = lambda: self.store
        app.dependency_overrides[get_model_secret_cipher] = lambda: ModelSecretCipher(Fernet.generate_key())
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.cookies = {"auth_token": auth_service.generate_token(self.user.id)}

    def _rpc(self, token: str, method: str, params=None, request_id=1):
        return self.client.post("/mcp", headers={"Authorization": f"Bearer {token}"}, json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})

    def test_tokens_are_issued_once_listed_masked_and_revoked(self):
        app.dependency_overrides[get_current_user] = lambda: {"user_id": self.user.id, "role": "user"}
        created = self.client.post("/api/mcp/tokens", cookies=self.cookies, json={"label": "Claude Code"})
        self.assertEqual(created.status_code, 200, created.text)
        token = created.json()["token"]
        self.assertTrue(token.startswith("mcp_"))
        listed = self.client.get("/api/mcp/tokens", cookies=self.cookies).json()
        self.assertEqual([t["label"] for t in listed["items"]], ["Claude Code"])
        self.assertNotIn(token, json.dumps(listed))
        self.assertEqual(listed["endpoint"], "/mcp")
        revoked = self.client.delete(f"/api/mcp/tokens/{created.json()['id']}", cookies=self.cookies)
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(self.client.get("/api/mcp/tokens", cookies=self.cookies).json()["items"], [])
        self.assertEqual(self._rpc(token, "ping").status_code, 401, "a revoked token no longer opens the server")

    def test_the_server_initializes_lists_tools_and_calls_them_as_the_token_owner(self):
        token = asyncio.run(self.store.create_mcp_token(self.user.id, label="agent"))[1]
        with patch.object(drama_api, "service", self.service):
            init = self._rpc(token, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}})
            self.assertEqual(init.json()["result"]["serverInfo"]["name"], "short-drama")
            self.assertEqual(self.client.post("/mcp", headers={"Authorization": f"Bearer {token}"}, json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code, 202)
            tools = self._rpc(token, "tools/list").json()["result"]["tools"]
            by_name = {t["name"]: t for t in tools}
            self.assertTrue(by_name["get_project"]["annotations"]["readOnlyHint"])
            self.assertIn("[paid]", by_name["run_stage"]["description"])
            called = self._rpc(token, "tools/call", {"name": "get_project", "arguments": {"task_id": "ag-1"}}).json()["result"]
            self.assertFalse(called["isError"])
            self.assertEqual(called["structuredContent"]["result"]["title"], "暗室回声")
            paid = self._rpc(token, "tools/call", {"name": "run_stage", "arguments": {"task_id": "ag-1", "stage": 2}}).json()["result"]
            self.assertFalse(paid["isError"])
            self.assertTrue(paid["structuredContent"]["needs_confirmation"])
            foreign = self._rpc(token, "tools/call", {"name": "get_project", "arguments": {"task_id": "missing"}}).json()["result"]
            self.assertTrue(foreign["isError"])
            unknown = self._rpc(token, "no/such").json()
            self.assertEqual(unknown["error"]["code"], -32601)
        self.assertEqual(self.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code, 401)
        self.assertEqual(self.client.get("/mcp", headers={"Authorization": f"Bearer {token}"}).status_code, 405)




class StageToolTests(unittest.TestCase):
    """The desk's checks, edits and repairs are reachable by the tool assistant and MCP."""

    def setUp(self):
        from tests.test_director_desk import _task as desk_task

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        self.repo.save_task("desk-tools", {**desk_task("desk-tools"), "owner_user_id": "u1"})
        self.user = {"user_id": "u1", "role": "user"}

    def _call(self, name, **arguments):
        return catalog.call(name, arguments, service=self.service, user=self.user)

    def test_checks_edits_and_repairs_round_trip(self):
        checks = self._call("get_stage_checks", task_id="desk-tools", scene_id="E1S01")
        self.assertTrue(checks["ok"], checks)
        self.assertTrue(all(c["passed"] for c in checks["result"]["checks"]))
        self.assertEqual(checks["result"]["repairs"], [])
        names = [a["name"] for a in self.service.get_spatial_plan("desk-tools", "E1S01")["plan"]["actors"]]
        first, second = names[0], names[1]
        plan = self.service.get_spatial_plan("desk-tools", "E1S01")["plan"]
        spot = next(a for a in plan["actors"] if a["name"] == first)["position"]

        edited = self._call("edit_stage", task_id="desk-tools", scene_id="E1S01", operations=[
            {"op": "move_actor", "name": second, "position": [spot[0] + 0.1, spot[1]]},
        ])
        self.assertTrue(edited["ok"], edited)
        self.assertIn("spatial_actor_spacing", edited["result"]["failing_checks"])

        repaired = self._call("repair_stage", task_id="desk-tools", scene_id="E1S01")
        self.assertTrue(repaired["ok"], repaired)
        self.assertNotIn("spatial_actor_spacing", repaired["result"]["failing_checks"])
        self.assertEqual(repaired["result"]["revision"], edited["result"]["revision"] + 1)

        stale = self._call("edit_stage", task_id="desk-tools", scene_id="E1S01", base_revision=1, operations=[{"op": "move_actor", "name": second, "position": [0, 0]}])
        self.assertFalse(stale["ok"])
        self.assertIn("刷新", stale["error"])
        bad = self._call("edit_stage", task_id="desk-tools", scene_id="E1S01", operations=[{"op": "teleport"}])
        self.assertFalse(bad["ok"])
        self.assertIn("未知操作", bad["error"])
        nothing = self._call("repair_stage", task_id="desk-tools", scene_id="E1S01")
        self.assertFalse(nothing["ok"])
        self.assertIn("没有可以自动修正", nothing["error"])
        self.assertEqual(catalog.get("edit_stage").effect, "write")
        self.assertEqual(catalog.get("get_stage_checks").effect, "read")


class AssistantStageAndFaceTests(unittest.TestCase):
    """侧栏助手的舞台与捏脸工具：场景可以说第几场，每一步都可撤销，界面收到刷新动作。"""

    def setUp(self):
        from tests.test_director_desk import _task as desk_task
        from tests.test_face_sculpt import _task as face_task

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        task = {**desk_task("desk-tools"), "owner_user_id": "u1"}
        task["assets"].update(face_task()["assets"])
        # 第 5 阶段已出的片段：E1S01 两镜各一段，E1S02 一段。改舞台、捏脸后它们该被标为待重做。
        task["assets"]["5"] = [
            {"shot_id": 1, "scene_id": "E1S01", "video_url": "https://cdn.test/1.mp4"},
            {"shot_id": 2, "scene_id": "E1S01", "video_url": "https://cdn.test/2.mp4"},
            {"shot_id": 3, "scene_id": "E1S02", "video_url": "https://cdn.test/3.mp4"},
        ]
        self.repo.save_task("desk-tools", task)
        self.user = {"user_id": "u1", "role": "user"}
        # 元素库写回走假的：记下参数，不开数据库。
        self.synced = []
        synced = patch("app.core.face_sculpt_sync.sync_actor_description", side_effect=self._sync)
        synced.start()
        self.addCleanup(synced.stop)

    def _sync(self, task, name, description):
        self.synced.append((task.get("task_id"), name, description))
        return {"updated": True, "element_id": "el-1"}

    def _call(self, tool_name, **arguments):
        return catalog.call(tool_name, {"task_id": "desk-tools", **arguments}, service=self.service, user=self.user)

    def _clips(self):
        return [(clip["scene_id"], bool(clip.get("stale")), clip.get("stale_reason", "")) for clip in self.repo.get_task("desk-tools")["assets"]["5"]]

    def _actor(self, who):
        plan = self.service.get_spatial_plan("desk-tools", "E1S01")["plan"]
        return next(a for a in plan["actors"] if a["name"] == who)

    def _desc(self):
        return self.repo.get_task("desk-tools")["assets"]["3_characters"][0]["desc"]

    def test_scenes_are_listed_and_an_edit_named_by_scene_number_is_one_undoable_step(self):
        listed = self._call("list_stage_scenes")["result"]
        self.assertEqual([s["scene_id"] for s in listed["scenes"]], ["E1S01", "E1S02"])
        self.assertEqual(listed["scenes"][0]["characters"], ["林夏", "周教授"])
        self.assertEqual([s["shot_id"] for s in listed["scenes"][0]["shots"]], [1, 2])

        spot = self._actor("周教授")["position"]
        edited = self._call("edit_stage", scene_id="第1场", label="周教授退后",
                            operations=[{"op": "move_actor", "name": "周教授", "position": [spot[0], spot[1] + 1.0]}])
        self.assertTrue(edited["ok"], edited)
        result = edited["result"]
        self.assertTrue(result["snapshot_id"])
        self.assertEqual(result["changed"]["actors"], ["周教授"])
        action = result["ui_action"]
        self.assertEqual((action["type"], action["scene_id"], action["revision"], action["snapshot_id"]),
                         ("stage_changed", "E1S01", result["revision"], result["snapshot_id"]))
        self.assertEqual(action["summary"], "助手：周教授退后")
        self.assertEqual(action["failing_checks"], result["failing_checks"])
        self.assertEqual((result["stale_clips"], action["stale_clips"]), (2, 2), "both E1S01 clips now need the stage-5 rerun")
        from app.service.stage_director_ops import STALE_CLIP_REASON

        self.assertEqual(self._clips(), [("E1S01", True, STALE_CLIP_REASON), ("E1S01", True, STALE_CLIP_REASON), ("E1S02", False, "")])

        desk = self._call("get_stage_director", scene_id="林夏")   # 只在一场里出现的人物也能指到那一场
        self.assertTrue(desk["ok"], desk)
        self.assertEqual([row["id"] for row in desk["result"]["snapshots"]], [result["snapshot_id"]])
        self.assertEqual(desk["result"]["chat"][-1], {"role": "assistant", "text": "助手：周教授退后"})
        self.assertIn("score", desk["result"]["measured"])

        described = self._call("describe_stage", scene_id="E1S01")["result"]
        for op in ("place_relative", "solve_camera", "set_backdrop", "apply_blockout", "bind_landmark_model", "array_landmark", "flip_camera_side"):
            self.assertIn(op, described["operations"])
        self.assertEqual(described["operations"].count("set_backdrop {"), 1, "every operation is documented once")
        self.assertEqual([row["id"] for row in described["snapshots"]], [result["snapshot_id"]])
        self.assertIn("score", described["measured"])

        unknown = self._call("describe_stage", scene_id="第9场")
        self.assertFalse(unknown["ok"])
        self.assertIn("E1S01", unknown["error"])
        same = self._call("edit_stage", scene_id="E1S01", operations=[{"op": "move_actor", "name": "周教授", "position": [spot[0], spot[1] + 1.0]}])
        self.assertTrue(same["ok"], same)
        self.assertEqual((same["result"]["changed"], same["result"]["snapshot_id"], same["result"]["stale_clips"]), (False, None, 0), "an edit that changes nothing writes nothing")
        self.assertNotIn("ui_action", same["result"], "nothing changed, so the desk is not asked to refresh")

    def test_the_ai_director_changes_the_stage_through_a_fake_model_and_the_step_can_be_taken_back(self):
        spot = self._actor("周教授")["position"]
        reply = json.dumps({"reply": "周教授退后了一步", "done": True,
                            "operations": [{"op": "move_actor", "name": "周教授", "position": [spot[0], spot[1] + 1.0]}]})
        proposed = self._call("direct_stage", scene_id="第1场", message="周教授退后一点")
        self.assertTrue(proposed.get("needs_confirmation"), "the AI director spends text-model calls, so it waits for a confirm like any paid tool")
        self.assertIn("E1S01", proposed["message"], "the proposal names the scene the money goes on")
        self.assertIn("1–3 次文本模型调用", proposed["message"])
        with patch.object(self.service.gateway, "call_llm", return_value=reply) as llm, \
             patch.object(self.service.gateway, "last_answer_was_offline", return_value=False):
            directed = self._call("direct_stage", scene_id="第1场", message="周教授退后一点", confirm=True)
        self.assertTrue(directed["ok"], directed)
        self.assertEqual(llm.call_count, 1)
        result = directed["result"]
        self.assertEqual(result["reply"], "周教授退后了一步")
        self.assertEqual(result["changed"]["actors"], ["周教授"])
        self.assertEqual(result["ui_action"]["type"], "stage_changed")
        self.assertEqual(result["ui_action"]["snapshot_id"], result["snapshot_id"])
        self.assertAlmostEqual(self._actor("周教授")["position"][1], spot[1] + 1.0, places=3)
        self.assertEqual((result["stale_clips"], result["ui_action"]["stale_clips"]), (2, 2), "the AI director's change also makes the scene's clips stale")
        self.assertEqual([stale for _scene, stale, _reason in self._clips()], [True, True, False])
        self.repo.mutate_task("desk-tools", lambda task: [clip.pop("stale", None) for clip in task["assets"]["5"]])

        reverted = self._call("revert_stage_step", scene_id="E1S01")
        self.assertTrue(reverted["ok"], reverted)
        self.assertAlmostEqual(self._actor("周教授")["position"][1], spot[1], places=3)
        self.assertEqual(reverted["result"]["ui_action"]["summary"], "已撤销「周教授退后一点」")
        self.assertEqual((reverted["result"]["stale_clips"], reverted["result"]["ui_action"]["stale_clips"]), (2, 2), "an undo moves people too")
        self.assertEqual([stale for _scene, stale, _reason in self._clips()], [True, True, False])
        self.assertEqual(reverted["result"]["revision"], result["revision"] + 1)
        self.assertTrue(reverted["result"]["kept_snapshot_id"], "the undo itself can be taken back")
        self.assertEqual((catalog.get("direct_stage").effect, catalog.get("optimize_stage").effect), ("paid", "paid"),
                         "both spend text-model calls, so neither runs without a confirm")
        self.assertEqual(catalog.get("optimize_scenes").effect, "paid")
        proposed = self._call("optimize_scenes", episode=1)
        self.assertTrue(proposed.get("needs_confirmation"))
        self.assertIn("共 2 场", proposed["message"], "the proposal states the scope being confirmed")
        self.assertIn("E1S01", proposed["message"])
        self.assertEqual(proposed["arguments"], {"task_id": "desk-tools", "episode": 1})
        blind = self._call("optimize_scenes")
        self.assertFalse(blind["ok"])
        self.assertFalse(blind.get("needs_confirmation"), "a batch with no scope is refused before any confirmation")
        self.assertIn("scene_ids", blind["error"])
        self.assertIn("episode", blind["error"])
        with patch.object(self.service, "_has_running_generation", return_value=True), \
             patch.object(self.service.gateway, "call_llm", return_value=reply) as llm:
            busy = self._call("direct_stage", scene_id="E1S01", message="再退一点", confirm=True)
            self.assertFalse(busy["ok"])
            self.assertIn("正在执行阶段", busy["error"])
            self.assertFalse(self._call("optimize_stage", scene_id="E1S01", confirm=True)["ok"])
            self.assertFalse(self._call("optimize_scenes", episode=1, confirm=True)["ok"])
        self.assertEqual(llm.call_count, 0, "no paid call while the task is running")

    def test_face_sculpt_round_trip_returns_ui_actions_and_undoes(self):
        from tests.test_face_sculpt import REAL

        seen = self._call("get_face_sculpt", name="林婉")["result"]
        self.assertEqual(seen["revision"], 0)
        self.assertIn("nose_bridge", seen["catalog"]["controls"])
        self.assertIn("phoenix=丹凤眼", seen["catalog"]["controls"]["eye_shape"])
        self.assertEqual(list(seen)[0], "catalog", "the control table comes first so a truncated transcript keeps it")
        self.assertLess(len(json.dumps(seen["catalog"], ensure_ascii=False, separators=(",", ":"))), 3500)
        self.assertNotIn("words", json.dumps(seen["catalog"]["expressions"]))
        # The transcript shows the model the whole table: this read tool raises its own result limit.
        shown = embedded_agent._history_text([{"role": "tool", "tool": "get_face_sculpt", "result": seen}])
        self.assertNotIn("已截断", shown)
        self.assertIn("nose_bridge", shown)
        self.assertGreater(catalog.get("describe_stage").result_chars, embedded_agent.TOOL_RESULT_CHARS)
        self.assertEqual(embedded_agent._result_limit("get_project"), embedded_agent.TOOL_RESULT_CHARS)

        sculpted = self._call("sculpt_face", name=" 林婉 ", face={"nose_bridge": 1, "eye_shape": "丹凤眼"})
        self.assertTrue(sculpted["ok"], sculpted)
        result = sculpted["result"]
        self.assertEqual((result["name"], result["revision"], result["changed"]), ("林婉", 1, True))
        self.assertIn("丹凤眼", result["description"])
        self.assertEqual(result["sculpt"]["face"], {"nose_bridge": 1, "eye_shape": "phoenix"}, "option labels are accepted as values")
        action = result["ui_action"]
        self.assertEqual((action["type"], action["name"], action["revision"]), ("face_sculpt_changed", "林婉", 1))
        self.assertEqual((action["before"], action["after"]), (REAL, result["description"]))
        self.assertEqual(action["snapshot_id"], result["history"][0]["id"])
        self.assertEqual(result["history"][0]["label"], "捏脸前")
        stored = self.repo.get_task("desk-tools")
        self.assertIn("丹凤眼", stored["assets"]["3_characters"][0]["desc"])
        self.assertIn("3_character_dashboard", stored["assets"], "the dashboard is recomputed on the same write path as the API")

        second = self._call("sculpt_face", name="林婉", face={"nose_bridge": 2}, label="鼻梁再高")["result"]
        self.assertEqual(second["sculpt"]["face"], {"nose_bridge": 2, "eye_shape": "phoenix"}, "merge keeps what was sculpted before")
        self.assertEqual(second["label"], "助手：鼻梁再高")
        back = self._call("revert_face_sculpt", name="林婉")["result"]
        self.assertEqual(back["sculpt"]["face"]["nose_bridge"], 1)
        self.assertEqual(back["ui_action"]["type"], "face_sculpt_changed")
        self.assertTrue(back["changed"])
        reset = self._call("reset_face_sculpt", name="林婉")["result"]
        self.assertEqual((reset["revision"], reset["history"]), (0, []))
        self.assertEqual(self._desc(), REAL)

    def test_a_face_change_reports_the_clips_it_made_stale_and_the_library_write_back(self):
        from app.api import face_sculpt_api
        from app.core import face_sculpt

        def cast(task):
            # 林婉 appears in E1S02's shot 3, whose clip is the third one.
            task["assets"]["4"][2]["characters"] = ["周教授", "林婉"]
            return True

        self.repo.mutate_task("desk-tools", cast)
        sculpted = self._call("sculpt_face", name="林婉", face={"nose_bridge": 1, "eye_shape": "丹凤眼"})
        self.assertTrue(sculpted["ok"], sculpted)
        result = sculpted["result"]
        self.assertEqual(result["downstream"], {"stale_clips": 1, "sheet_stale": True})
        self.assertEqual(result["library"], {"library_updated": True, "element_id": "el-1"})
        self.assertEqual(result["ui_action"]["downstream"], result["downstream"])
        self.assertEqual(result["ui_action"]["library"], result["library"])
        self.assertEqual(self.synced, [("desk-tools", "林婉", result["description"])], "the library gets the new description after the write")
        self.assertIn("丹凤眼", self.synced[0][2])
        scenes = self._clips()
        self.assertEqual([stale for _scene, stale, _reason in scenes], [False, False, True], "only the clip 林婉 appears in is stale")
        self.assertIn("第 5 阶段", scenes[2][2])

        # The sheet prompt the tool shows is the one the endpoint builds, with the sculpted face in it.
        prompt = self._call("get_sheet_prompt", name="林 婉")
        self.assertTrue(prompt["ok"], prompt)
        task = self.repo.get_task("desk-tools")
        expected = face_sculpt_api._sheet_prompt(task, face_sculpt.record_of(task, "林婉"))
        self.assertEqual(prompt["result"]["prompt"], expected)
        self.assertIn("丹凤眼", prompt["result"]["prompt"])
        self.assertEqual((prompt["result"]["name"], prompt["result"]["revision"], prompt["result"]["sheet_stale"]), ("林婉", 1, True))
        self.assertEqual(catalog.get("get_sheet_prompt").effect, "read")

        # A library that cannot be reached is reported, never raised, and the sculpt stays saved.
        with patch("app.core.face_sculpt_sync.sync_actor_description", return_value={"updated": False, "element_id": "", "error": "OSError: down"}):
            reset = self._call("reset_face_sculpt", name="林婉")
        self.assertTrue(reset["ok"], reset)
        self.assertEqual(reset["result"]["library"], {"library_updated": False, "element_id": "", "error": "OSError: down"})
        self.assertEqual(reset["result"]["downstream"]["stale_clips"], 1)
        self.assertEqual(reset["result"]["revision"], 0)

    def test_face_sculpt_rejects_unknown_controls_and_characters_helpfully(self):
        from tests.test_face_sculpt import REAL

        bad = self._call("sculpt_face", name="林婉", face={"nose_height": 1, "nose_bridge": 1})
        self.assertFalse(bad["ok"])
        self.assertIn("nose_height", bad["error"])
        self.assertEqual(self._desc(), REAL, "nothing is written when part of the change is unknown")
        nothing = self._call("sculpt_face", name="林婉")
        self.assertFalse(nothing["ok"])
        who = self._call("get_face_sculpt", name="无名氏")
        self.assertFalse(who["ok"])
        self.assertIn("林婉", who["error"])
        self.assertIn("沈砚", who["error"])
        preview = self._call("preview_face_sculpt", name="林 婉", face={"nose_bridge": 2})
        self.assertTrue(preview["ok"], preview)
        self.assertIn("鼻梁高挺", preview["result"]["description"])
        self.assertNotIn("face_sculpt", self.repo.get_task("desk-tools")["assets"]["3_characters"][0], "preview writes nothing")
        empty = self._call("revert_face_sculpt", name="沈砚")
        self.assertFalse(empty["ok"])
        self.assertIn("可撤销", empty["error"])

    def test_the_system_prompt_carries_the_new_guides_and_the_mcp_listing_the_new_tools(self):
        from app.api.mcp_api import _tool_listing

        prompt = embedded_agent.system_prompt()
        for needle in ("get_face_sculpt", "sculpt_face", "nose_bridge", "direct_stage", "edit_stage（不花钱", "revert_stage_step", "optimize_scenes", "第3场",
                       "stale_clips", "付费步骤"):
            self.assertIn(needle, prompt)
        self.assertIn("不要出现工具名", prompt)
        self.assertIn("Blender 3D 预演：改站位或机位前先 describe_stage", prompt, "the existing guidance stays word for word")
        names = {t["name"] for t in _tool_listing()}
        self.assertTrue({"list_stage_scenes", "direct_stage", "optimize_stage", "optimize_scenes", "revert_stage_step", "get_stage_director",
                         "pin_stage_snapshot", "get_face_sculpt", "preview_face_sculpt", "sculpt_face", "revert_face_sculpt", "reset_face_sculpt",
                         "get_sheet_prompt"} <= names)
        self.assertIn("场景：E1S02、第3场 或场名", catalog.get("get_scene_board").input_schema["properties"]["scene_id"]["description"])


if __name__ == "__main__":
    unittest.main()

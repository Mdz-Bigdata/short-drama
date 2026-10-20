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


if __name__ == "__main__":
    unittest.main()

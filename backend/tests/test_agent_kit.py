# -*- coding: utf-8 -*-
"""The Agent Kit bridge, against a real local HTTP server and as a real subprocess."""

import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "agent-kit" / "short_drama_mcp.py"
SKILL = Path(__file__).resolve().parents[2] / "agent-kit" / "skills" / "short-drama-canvas" / "SKILL.md"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/mcp":
            self.send_response(404)
            self.end_headers()
            return
        if self.headers.get("Authorization") != "Bearer good":
            payload, status = {"detail": "MCP 令牌无效或已撤销"}, 401
        elif body.get("id") is None:
            payload, status = None, 202
        elif body.get("method") == "tools/list":
            payload, status = {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [{"name": "a"}, {"name": "b"}]}}, 200
        else:
            payload, status = {"jsonrpc": "2.0", "id": body["id"], "result": {"echo": body["method"]}}, 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())


class AgentKitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def run_kit(self, *args, url=None, token="good", stdin=None):
        env = {"PATH": "/usr/bin:/bin", "SHORT_DRAMA_URL": url or self.url, "SHORT_DRAMA_TOKEN": token}
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, input=stdin, env=env, timeout=30, check=False)

    def test_doctor_counts_the_tools(self):
        done = self.run_kit("doctor")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("2 个", done.stdout)

    def test_doctor_tells_a_bad_token_from_a_bad_address(self):
        bad_token = self.run_kit("doctor", token="bad")
        self.assertEqual(bad_token.returncode, 1)
        self.assertIn("令牌", bad_token.stdout)
        bad_address = self.run_kit("doctor", url="http://127.0.0.1:9")
        self.assertEqual(bad_address.returncode, 1)
        self.assertIn("连不上", bad_address.stdout)

    def test_a_missing_token_is_said_up_front(self):
        done = self.run_kit("doctor", token="")
        self.assertEqual(done.returncode, 2)
        self.assertIn("SHORT_DRAMA_TOKEN", done.stderr)

    def test_the_bridge_forwards_requests_and_stays_up_through_bad_input(self):
        lines = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            "not json",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]) + "\n"
        done = self.run_kit("serve", stdin=lines)
        self.assertEqual(done.returncode, 0, done.stderr)
        replies = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([reply.get("id") for reply in replies], [1, None, 2])
        self.assertEqual(replies[0]["result"], {"echo": "ping"})
        self.assertEqual(replies[1]["error"]["code"], -32700)
        self.assertEqual(len(replies[2]["result"]["tools"]), 2)

    def test_a_refused_request_is_an_rpc_error_not_a_dead_bridge(self):
        done = self.run_kit("serve", token="bad", stdin=json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}) + "\n")
        reply = json.loads(done.stdout)
        self.assertEqual(reply["id"], 7)
        self.assertIn("401", reply["error"]["message"])

    def test_config_for_each_client(self):
        claude = self.run_kit("config", "claude-code", url="https://host/").stdout
        self.assertIn("https://host/mcp", claude)
        self.assertIn("Bearer good", claude)
        self.assertIn("serve", self.run_kit("config", "codex").stdout)
        self.assertEqual(json.loads(self.run_kit("config", "json", url="https://host/mcp").stdout)["mcpServers"]["short-drama"]["url"], "https://host/mcp")

    def test_the_skill_names_tools_that_exist(self):
        from app.core.agent_tools import catalog

        known = {item["name"] for item in catalog.describe()}
        text = SKILL.read_text(encoding="utf-8")
        for name in ("list_projects", "plan_canvas_workflow", "apply_canvas_workflow", "canvas_workflow_status", "quote_canvas_run", "run_canvas_nodes", "list_canvas_tools", "get_canvas", "edit_canvas"):
            self.assertIn(name, text)
            self.assertIn(name, known)


if __name__ == "__main__":
    unittest.main()

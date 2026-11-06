#!/usr/bin/env python3
"""Connect an MCP client to this app: a stdio bridge for clients that only speak stdio, a check, and config snippets.

Standard library only, so it runs from anywhere without the backend's environment. It holds no
logic of its own: every tool lives on the server, and the token decides what it may touch.

    SHORT_DRAMA_URL=https://your-host SHORT_DRAMA_TOKEN=... python short_drama_mcp.py doctor
    python short_drama_mcp.py config claude-code
    python short_drama_mcp.py serve
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT_S = 600
CLIENTS = ("claude-code", "codex", "json")


def endpoint(base: str) -> str:
    return base.rstrip("/").removesuffix("/mcp") + "/mcp"


def post(url: str, token: str, message: dict) -> tuple[int, dict | None]:
    request = urllib.request.Request(
        url, data=json.dumps(message, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            body = response.read()
            return response.status, json.loads(body) if body and body != b"null" else None
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            return error.code, json.loads(body)
        except ValueError:
            return error.code, {"detail": body.decode("utf-8", "replace")[:300]}


def rpc_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve(url: str, token: str, stdin=None, stdout=None) -> None:
    """One JSON-RPC message per line in, one per line out. A failed request answers the client; it never ends the bridge."""
    for line in stdin or sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply = rpc_error(None, -32700, "parse error")
        else:
            request_id = message.get("id") if isinstance(message, dict) else None
            try:
                status, reply = post(url, token, message)
                if request_id is None:
                    continue  # a notification has no answer
                if reply is None or "jsonrpc" not in reply:
                    detail = (reply or {}).get("detail") if isinstance(reply, dict) else None
                    reply = rpc_error(request_id, -32000, f"服务器返回 {status}：{detail or '没有内容'}")
            except (urllib.error.URLError, OSError, ValueError) as error:
                reply = rpc_error(request_id, -32000, f"连不上服务器：{error}")
        print(json.dumps(reply, ensure_ascii=False), file=stdout or sys.stdout, flush=True)


def doctor(url: str, token: str) -> int:
    """Says which step fails, so a wrong address and a revoked token do not look the same."""
    try:
        status, reply = post(url, token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    except (urllib.error.URLError, OSError) as error:
        print(f"连不上 {url}：{error}")
        return 1
    if status == 401:
        print("令牌无效或已撤销：到用户中心重新生成一个。")
        return 1
    tools = ((reply or {}).get("result") or {}).get("tools") if isinstance(reply, dict) else None
    if status != 200 or not isinstance(tools, list):
        print(f"{url} 没有按 MCP 回答（HTTP {status}），地址对吗？")
        return 1
    print(f"连接正常：{url}，可用工具 {len(tools)} 个。")
    return 0


def config(client: str, url: str, token: str) -> str:
    if client == "claude-code":
        return f'claude mcp add --transport http short-drama {url} --header "Authorization: Bearer {token}"'
    if client == "codex":
        script = os.path.abspath(__file__)
        return (
            "[mcp_servers.short-drama]\n"
            f'command = "python3"\nargs = ["{script}", "serve"]\n'
            f'env = {{ SHORT_DRAMA_URL = "{url}", SHORT_DRAMA_TOKEN = "{token}" }}\n'
        )
    return json.dumps({"mcpServers": {"short-drama": {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {token}"}}}}, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("serve", "doctor", "config"))
    parser.add_argument("client", nargs="?", choices=CLIENTS, default="json")
    args = parser.parse_args(argv)
    base = os.environ.get("SHORT_DRAMA_URL", "http://localhost:8000")
    token = os.environ.get("SHORT_DRAMA_TOKEN", "")
    url = endpoint(base)
    if args.command == "config":
        print(config(args.client, url, token or "<你的令牌>"))
        return 0
    if not token:
        print("缺少 SHORT_DRAMA_TOKEN：到用户中心的 MCP 令牌处生成一个。", file=sys.stderr)
        return 2
    if args.command == "doctor":
        return doctor(url, token)
    serve(url, token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

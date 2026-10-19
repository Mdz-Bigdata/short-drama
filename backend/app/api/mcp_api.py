"""The project as an MCP server: external agents reach the same tool catalog the embedded assistant uses.

Transport is MCP's Streamable HTTP in its simplest form — JSON-RPC 2.0 over
``POST /mcp`` — with a bearer token the person issued in the user centre. The
token stands for the person, so every tool call is checked against project
ownership exactly as in the UI, and paid tools still wait for ``confirm``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.auth_api import get_current_user
from app.core.agent_tools import ToolError, catalog
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore

router = APIRouter(tags=["MCP"])
PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "short-drama", "version": "1.0"}


class McpTokenCreateRequest(BaseModel):
    label: str = Field(default="", max_length=80)


def _token_row(token) -> dict[str, Any]:
    return {
        "id": token.id, "label": token.label or f"****{token.token_hint}", "hint": f"****{token.token_hint}",
        "created_at": token.created_at.isoformat() if token.created_at else None,
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
    }


@router.get("/api/mcp/tokens")
async def list_mcp_tokens(current_user: dict = Depends(get_current_user), store: PlatformStore = Depends(get_platform_store)):
    return {"items": [_token_row(t) for t in await store.list_mcp_tokens(current_user["user_id"])], "endpoint": "/mcp", "protocol_version": PROTOCOL_VERSION}


@router.post("/api/mcp/tokens")
async def create_mcp_token(request: McpTokenCreateRequest, current_user: dict = Depends(get_current_user), store: PlatformStore = Depends(get_platform_store)):
    """The clear token is in this response and nowhere else."""
    token, clear = await store.create_mcp_token(current_user["user_id"], label=request.label.strip())
    return {**_token_row(token), "token": clear}


@router.delete("/api/mcp/tokens/{token_id}")
async def revoke_mcp_token(token_id: str, current_user: dict = Depends(get_current_user), store: PlatformStore = Depends(get_platform_store)):
    if not await store.revoke_mcp_token(current_user["user_id"], token_id):
        raise HTTPException(status_code=404, detail="令牌不存在或已撤销")
    return {"id": token_id, "revoked": True}


def _rpc_error(request_id: Any, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, status_code=status)


async def _mcp_user(authorization: str | None, store: PlatformStore) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 MCP 令牌")
    user = await store.verify_mcp_token(authorization.removeprefix("Bearer ").strip())
    if user is None:
        raise HTTPException(status_code=401, detail="MCP 令牌无效或已撤销")
    return {"user_id": user.id, "role": user.role, "username": user.username}


def _tool_listing() -> list[dict[str, Any]]:
    return [
        {"name": t["name"], "title": t["title"], "description": f"[{t['effect']}] {t['description']}", "inputSchema": t["input_schema"],
         "annotations": {"readOnlyHint": t["effect"] == "read", "destructiveHint": False, "openWorldHint": False}}
        for t in catalog.describe()
    ]


@router.post("/mcp")
async def mcp_endpoint(request: Request, authorization: str | None = Header(None), store: PlatformStore = Depends(get_platform_store)):
    """JSON-RPC 2.0 over HTTP: initialize, ping, tools/list, tools/call; notifications are acknowledged with 202."""
    from app.api.drama_api import service

    user = await _mcp_user(authorization, store)
    try:
        body = await request.json()
    except ValueError:
        return _rpc_error(None, -32700, "parse error", status=400)
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return _rpc_error(body.get("id") if isinstance(body, dict) else None, -32600, "invalid request", status=400)
    method = str(body.get("method") or "")
    request_id = body.get("id")
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    if request_id is None:
        return JSONResponse(None, status_code=202)  # a notification
    if method == "initialize":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
            "instructions": "付费工具（run_stage / run_all / repair_episode / render_timeline）必须显式传 confirm=true 才会执行。",
        }})
    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {}})
    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tool_listing()}})
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            result = await run_in_threadpool(catalog.call, name, arguments, service=service, user=user)
        except ToolError as exc:
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True}})
        except Exception as exc:  # noqa: BLE001 - the tool's failure is the call's result, never a crashed transport
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": f"{type(exc).__name__}: {str(exc)[:300]}"}], "isError": True}})
        import json

        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
            "structuredContent": result if isinstance(result, dict) else None,
            "isError": not result.get("ok", True) and not result.get("needs_confirmation", False),
        }})
    return _rpc_error(request_id, -32601, f"method not found: {method}")


@router.get("/mcp")
async def mcp_stream_unsupported():
    raise HTTPException(status_code=405, detail="此 MCP 服务只接受 POST（Streamable HTTP，无服务端推流）")

# -*- coding: utf-8 -*-
"""和你打开的 Blender 里的实时桥接插件说话(127.0.0.1，一行 JSON 一问一答)。

插件没开或没点「开始连接」时，所有调用都安静地返回 ``None``——实时同步是锦上添花，渲染与对话不依赖它。
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any

from .spec import BlockingSpec

HOST = "127.0.0.1"
PORT = int(os.getenv("BLENDER_LIVE_PORT", "9877"))


def _ask(message: dict, *, timeout: float = 60.0) -> dict | None:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.5) as conn:
            conn.settimeout(timeout)
            conn.sendall((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
    except OSError:
        return None
    try:
        return json.loads(data.decode("utf-8") or "null")
    except ValueError:
        return None


def ping() -> dict | None:
    """插件在线就回 {ok, blender, scene}。"""
    return _ask({"op": "ping"}, timeout=5)


def push(spec: BlockingSpec) -> dict | None:
    """在打开的 Blender 里按规格重建预演(只动插件自己的集合)。"""
    return _ask({"op": "build", "spec": json.loads(spec.model_dump_json())})


def snapshot() -> dict[str, Any] | None:
    """读回 Blender 里代理、布景与摄影机的当前位置。"""
    return _ask({"op": "snapshot"}, timeout=20)

# -*- coding: utf-8 -*-
"""短剧预演实时桥接：让对话里的改动直接出现在你打开的 Blender 里。

安装：Blender → 编辑 → 偏好设置 → 插件 → 从磁盘安装，选后端下载的 short_drama_previz.zip，勾选启用。
启用后在 3D 视口右侧 N 面板「短剧预演」里点「开始连接」。插件只在本机 127.0.0.1 上监听，只接受三种消息：

- ``{"op": "ping"}``                → 回报 Blender 版本与场景名；
- ``{"op": "build", "spec": {...}}`` → 按预演规格重建「ShortDramaPreviz」集合(不动你自己建的其它东西)；
- ``{"op": "snapshot"}``            → 读回代理、布景与摄影机的位置，供后端同步回导演台。

不执行任何外部传入的 Python，不读写磁盘上的其它文件。每条消息一行 JSON，回复也是一行 JSON。
"""

bl_info = {
    "name": "Short Drama Previz Bridge",
    "author": "short-drama",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D 视口 › N 面板 › 短剧预演",
    "description": "把短剧项目的 3D 预演(站位、机位、硬切)实时同步到 Blender",
    "category": "Animation",
}

import json
import queue
import socket
import threading

import bpy

from . import previz_scene

DEFAULT_PORT = 9877
MAX_MESSAGE_BYTES = 8 * 1024 * 1024

_server = {"thread": None, "socket": None, "running": False, "port": DEFAULT_PORT, "last": "未连接"}
_inbox: "queue.Queue[tuple[dict, queue.Queue]]" = queue.Queue()


def _handle(message: dict) -> dict:
    op = message.get("op")
    if op == "ping":
        return {"ok": True, "blender": bpy.app.version_string, "scene": bpy.context.scene.name}
    if op == "build":
        spec = message.get("spec")
        if not isinstance(spec, dict):
            return {"ok": False, "error": "build 需要 spec"}
        built = previz_scene.build(spec)
        _server["last"] = f"已同步：{len(built['proxies'])} 个代理、{len(built['cameras'])} 台摄影机"
        return {"ok": True, **built}
    if op == "snapshot":
        return {"ok": True, **previz_scene.snapshot()}
    return {"ok": False, "error": f"不支持的操作 {op}"}


def _drain() -> float:
    """在 Blender 主线程里处理收到的消息(bpy 只能在主线程改场景)。"""
    while True:
        try:
            message, reply = _inbox.get_nowait()
        except queue.Empty:
            break
        try:
            reply.put(_handle(message))
        except Exception as exc:  # noqa: BLE001 - 错误原样回给后端，插件不崩
            reply.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return 0.1 if _server["running"] else None


def _serve(sock: socket.socket) -> None:
    while _server["running"]:
        try:
            conn, _ = sock.accept()
        except OSError:
            break
        with conn:
            conn.settimeout(30)
            data = b""
            try:
                while not data.endswith(b"\n") and len(data) < MAX_MESSAGE_BYTES:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                message = json.loads(data.decode("utf-8") or "{}")
                reply: "queue.Queue[dict]" = queue.Queue()
                _inbox.put((message, reply))
                answer = reply.get(timeout=60)
            except Exception as exc:  # noqa: BLE001
                answer = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            try:
                conn.sendall((json.dumps(answer, ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                pass


def start(port: int = DEFAULT_PORT) -> None:
    if _server["running"]:
        return
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(4)
    _server.update(socket=sock, running=True, port=port, last=f"监听 127.0.0.1:{port}，等待后端推送")
    _server["thread"] = threading.Thread(target=_serve, args=(sock,), daemon=True)
    _server["thread"].start()
    bpy.app.timers.register(_drain, persistent=True)


def stop() -> None:
    _server["running"] = False
    if _server["socket"] is not None:
        try:
            _server["socket"].close()
        except OSError:
            pass
    _server.update(socket=None, last="未连接")


class SDP_OT_start(bpy.types.Operator):
    bl_idname = "short_drama_previz.start"
    bl_label = "开始连接"

    def execute(self, context):
        try:
            start(context.scene.short_drama_previz_port)
        except OSError as exc:
            self.report({"ERROR"}, f"端口被占用：{exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class SDP_OT_stop(bpy.types.Operator):
    bl_idname = "short_drama_previz.stop"
    bl_label = "断开"

    def execute(self, context):
        stop()
        return {"FINISHED"}


class SDP_PT_panel(bpy.types.Panel):
    bl_label = "短剧预演"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "短剧预演"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "short_drama_previz_port", text="端口")
        if _server["running"]:
            layout.operator("short_drama_previz.stop", icon="CANCEL")
        else:
            layout.operator("short_drama_previz.start", icon="LINKED")
        layout.label(text=_server["last"])


_CLASSES = (SDP_OT_start, SDP_OT_stop, SDP_PT_panel)


def register():
    bpy.types.Scene.short_drama_previz_port = bpy.props.IntProperty(default=DEFAULT_PORT, min=1024, max=65535)
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    stop()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.short_drama_previz_port

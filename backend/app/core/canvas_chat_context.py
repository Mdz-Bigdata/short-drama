"""What the canvas tells the assistant when someone talks to it from inside the canvas.

The chat panel on the canvas sends which board is open and which nodes are selected. That becomes
part of the one ``[界面]`` line the assistant already gets (see ``DramaService._interface_line``),
so "把这两个节点连起来" or "这张图换成夜景" has something to point at. Idea from AID Studio's
canvas side panel (MIT, © 光子讯息(杭州)科技有限公司), where the selected nodes ride along as chips.

The wording and the limits live in app/data/prompt/canvas_chat.json. Nothing here is trusted
further than as a hint: the assistant still reads the board with ``get_canvas`` before it edits.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.core import prompt_data

_FILE = "canvas_chat"
_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _limit(key: str) -> int:
    return prompt_data.number(_FILE, key)


def clean(raw: Any) -> dict[str, Any] | None:
    """The canvas part of a chat request, cut down to what may reach the prompt; None when there is none.

    Ids must look like ids (they are echoed to the model), titles are trimmed and flattened to one
    line, and only the first ``max_nodes`` selected nodes are kept; ``selected`` keeps the real count.
    """
    if not isinstance(raw, Mapping):
        return None
    canvas_id = str(raw.get("canvas_id") or "").strip()
    if not _ID.match(canvas_id):
        return None
    nodes: list[dict[str, str]] = []
    listed = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    for item in listed:
        if not isinstance(item, Mapping):
            continue
        node_id = str(item.get("id") or "").strip()
        if not _ID.match(node_id):
            continue
        title = " ".join(str(item.get("title") or "").split())[: _limit("max_title")]
        kind = str(item.get("kind") or "").strip()
        nodes.append({"id": node_id, "title": title, "kind": kind if _ID.match(kind) else ""})
    kept = nodes[: _limit("max_nodes")]
    return {"canvas_id": canvas_id, "nodes": kept, "selected": len(nodes)}


def line(canvas: Any) -> str:
    """The canvas part of the interface line, or "" when the chat did not come from a canvas."""
    if not isinstance(canvas, Mapping) or not canvas.get("canvas_id"):
        return ""
    wording = prompt_data.value(_FILE, "line")
    text = str(wording["open"]).format(canvas_id=canvas["canvas_id"])
    nodes = [node for node in (canvas.get("nodes") or []) if isinstance(node, Mapping) and node.get("id")]
    if not nodes:
        return text + str(wording["none"])
    named = str(wording["joiner"]).join(
        str(wording["node"] if node.get("title") else wording["node_untitled"]).format(id=node["id"], title=node.get("title") or "", kind=node.get("kind") or "")
        for node in nodes
    )
    total = max(len(nodes), int(canvas.get("selected") or 0))
    more = str(wording["more"]).format(rest=total - len(nodes)) if total > len(nodes) else ""
    return text + str(wording["selected"]).format(count=total, nodes=named) + more + str(wording["hint"])

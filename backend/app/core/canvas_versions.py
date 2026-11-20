"""Several results from one run of a canvas node.

A picture or clip node may ask for more than one result (``params.count``). Each is a run record
of its own in the same batch, so every result lands in the node's history, can be restored, and is
billed as the separate call it is. Idea from AID Studio's composer (MIT, © 光子讯息(杭州)科技有限公司),
where the count sits beside the other parameters; written for this project's run records.

The ceiling and the label live in app/data/prompt/canvas_versions.json.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.core import prompt_data

_FILE = "canvas_versions"

#: Node kinds whose run may be asked for several times over.
VERSIONED_KINDS = frozenset(prompt_data.words(_FILE, "kinds"))
MAX_VERSIONS = prompt_data.number(_FILE, "max")

_WAITING = ("running", "queued")


def versions_of(node: Mapping[str, Any]) -> int:
    """How many results one run of this node makes: 1 unless a picture or clip node asks for more, never above the ceiling."""
    if str(node.get("kind")) not in VERSIONED_KINDS:
        return 1
    payload = node.get("payload") if isinstance(node.get("payload"), Mapping) else {}
    params = payload.get("params") if isinstance(payload.get("params"), Mapping) else {}
    try:
        asked = int(params.get("count") or 1)
    except (TypeError, ValueError):
        return 1
    return max(1, min(MAX_VERSIONS, asked))


def share_of(estimate: Mapping[str, Any], versions: int) -> dict[str, Any]:
    """One result's part of an estimate made for all of them; an unpriced estimate stays unpriced."""
    shared = dict(estimate)
    if versions > 1 and shared.get("priced") and shared.get("cost") is not None:
        shared["cost"] = round(float(shared["cost"]) / versions, 6)
    return shared


def label_of(label: str, index: int, total: int) -> str:
    """The queue's name for one result: the node's own name, numbered when there are several."""
    if total <= 1:
        return label
    return prompt_data.text(_FILE, "label").format(label=label, index=index, total=total)


def latest_of(runs: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """How each node's last order stands, from its runs newest first.

    One order may hold several runs of a node. The node is still working while any of them is, and it
    is done once one of them is; ``versions`` then says how many were asked for and how they ended.
    """
    grouped: dict[str, list[Any]] = {}
    for run in runs:
        siblings = grouped.setdefault(run.node_id, [])
        if not siblings or siblings[0].batch_id == run.batch_id:
            siblings.append(run)
    latest: dict[str, dict[str, Any]] = {}
    for node_id, siblings in grouped.items():
        shown = siblings[0]
        for status in (*_WAITING, "done"):
            match = next((run for run in siblings if run.status == status), None)
            if match is not None:
                shown = match
                break
        entry = {"run_id": shown.id, "status": shown.status, "error": shown.error, "batch_id": shown.batch_id}
        if len(siblings) > 1:
            entry["versions"] = {
                "total": len(siblings),
                "done": sum(1 for run in siblings if run.status == "done"),
                "failed": sum(1 for run in siblings if run.status == "failed"),
            }
        latest[node_id] = entry
    return latest

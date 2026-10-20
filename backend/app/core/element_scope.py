"""Project scoping for the shared element library.

Every element is created by one project (``metadata.task_id``) and may later be
reused by others (``metadata.task_ids``). The library keeps everything the owner
ever produced; a project only sees what it created or explicitly linked, and a
new project links a same-name asset instead of generating it again.
"""

from __future__ import annotations

import re
from typing import Any

_NAME_NOISE = re.compile(
    r"[\s　·•・\-—–_/\\()（）\[\]【】《》「」『』\"'“”‘’,，。.:：;；!！?？]+"
)


def normalized_asset_name(value: Any) -> str:
    """Collapse spacing and punctuation so 《长安城门》 and 长安 城门 match."""
    return _NAME_NOISE.sub("", str(value or "")).casefold()


def element_task_ids(metadata: Any) -> tuple[str, ...]:
    """Origin project first, then every project that linked the element."""
    if not isinstance(metadata, dict):
        return ()
    ordered: list[str] = []
    origin = str(metadata.get("task_id") or "").strip()
    if origin:
        ordered.append(origin)
    raw = metadata.get("task_ids")
    for item in raw if isinstance(raw, list) else ():
        text = str(item or "").strip()
        if text and text not in ordered:
            ordered.append(text)
    return tuple(ordered)


def element_in_task(metadata: Any, task_id: Any) -> bool:
    task = str(task_id or "").strip()
    return bool(task) and task in element_task_ids(metadata)


def link_task(metadata: Any, task_id: Any) -> dict:
    """Return metadata with ``task_id`` linked; the origin ``task_id`` is preserved."""
    base = dict(metadata) if isinstance(metadata, dict) else {}
    task = str(task_id or "").strip()
    if not task:
        return base
    ids = list(element_task_ids(base))
    if task not in ids:
        ids.append(task)
    if not str(base.get("task_id") or "").strip():
        base["task_id"] = task
    base["task_ids"] = ids
    return base


def element_name_keys(name: Any, metadata: Any = None) -> set[str]:
    """Normalized lookup keys: the element name plus any recorded aliases."""
    keys = {normalized_asset_name(name)}
    aliases = metadata.get("aliases") if isinstance(metadata, dict) else None
    if isinstance(aliases, str):
        aliases = re.split(r"[、，,/]", aliases)
    for alias in aliases if isinstance(aliases, list) else ():
        keys.add(normalized_asset_name(alias))
    keys.discard("")
    return keys

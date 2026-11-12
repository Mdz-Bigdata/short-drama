# -*- coding: utf-8 -*-
"""资产库里的一个资产变了(改名、改描述、换图、恢复旧版本)，挂着它的每个项目跟着知道。

元素库(PlatformStore，异步)和项目(TaskRepository，同步、按行加锁)不在同一个事务里：
先提交资产的修改，再在线程池里调这里，逐个项目幂等地把引用它的镜头和片段标成过期。
这里只标记、不重画：重画是付费操作，由用户在界面上点。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping

from app.core import asset_dependents, asset_identity, episode_cycle
from app.core.element_scope import element_task_ids, normalized_asset_name

logger = logging.getLogger(__name__)

SKIPPED_RUNNING = "running"
SKIPPED_MISSING = "missing"
SKIPPED_OWNER = "owner"


def _repo() -> Any:
    """全局服务的项目仓库；导入时不碰 drama_api(它会把整个服务拉起来)。"""
    from app.api.drama_api import service

    return service.repo


def _running(task: Mapping[str, Any]) -> bool:
    from app.service.drama_service import DramaService

    return bool(DramaService._has_running_generation(dict(task)))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _aliases(metadata: Any) -> list[str]:
    raw = metadata.get("aliases") if isinstance(metadata, Mapping) else None
    if isinstance(raw, str):
        raw = re.split(r"[、，,/]", raw)
    return [_text(item) for item in raw if _text(item)] if isinstance(raw, list) else []


def _names(element: Mapping[str, Any], old_name: str | None = None) -> list[str]:
    names = [_text(element.get("name")), _text(old_name), *_aliases(element.get("metadata"))]
    return [name for name in dict.fromkeys(names) if name]


def _reason(element: Mapping[str, Any], reason: str) -> str:
    """``reason`` 是写到镜头和片段上的过期原因；可带 {name}，空着用默认那句。"""
    name = _text(element.get("name"))
    text = _text(reason)
    if not text:
        return asset_dependents.STALE_REASON.format(name=name)
    return text.replace("{name}", name)


def _owned(task: Mapping[str, Any], owner_id: str) -> bool:
    return bool(owner_id) and _text(task.get("owner_user_id")) == owner_id


def _rename_in_project(task: dict[str, Any], kind: str, old_name: str, new_name: str) -> tuple[bool, str]:
    """项目里还用旧名字叫这个资产时，按项目内改名的同一套逻辑改过去(旧名留作别名)。返回 (改了没有, 失败原因)。"""
    identity_kind = next((key for key, value in asset_dependents.IDENTITY_KINDS.items() if value == kind), None)
    old, new = asset_identity.canonical_name(old_name), asset_identity.canonical_name(new_name)
    if identity_kind is None or not old or not new or old == new:
        return False, ""
    if old not in asset_identity.known_names(task, identity_kind):
        return False, ""
    try:
        asset_identity.rename_asset(task, identity_kind, old, new)
    except asset_identity.AssetIdentityError as exc:
        return False, str(exc)
    from app.service.drama_service import DramaService

    DramaService._reproject_after_identity(task)
    return True, ""


def sync_element(
    element: Mapping[str, Any], *, reason: str, old_name: str | None = None, repo: Any = None,
) -> dict[str, Any]:
    """``element_changed`` 的实现；``repo`` 留给测试和已经拿着仓库的调用方。"""
    repo = repo if repo is not None else _repo()
    owner_id = _text(element.get("owner_id"))
    element_id = _text(element.get("id"))
    kind = _text(element.get("kind"))
    name = _text(element.get("name"))
    names = _names(element, old_name)
    text = _reason(element, reason)
    rows: list[dict[str, Any]] = []
    renamed_any = False
    for task_id in element_task_ids(element.get("metadata")):
        row: dict[str, Any] = {"task_id": task_id, "shots_marked": 0, "clips_marked": 0, "boards_marked": 0}

        def mutation(task: dict[str, Any]) -> dict[str, Any]:
            if not _owned(task, owner_id):
                return {"skipped": SKIPPED_OWNER}
            if _running(task):
                return {"skipped": SKIPPED_RUNNING}
            outcome: dict[str, Any] = {}
            if old_name and name:
                renamed, error = _rename_in_project(task, kind, old_name, name)
                outcome["renamed"] = renamed
                if error:
                    outcome["rename_error"] = error
            # 改名在前：改名会把片段的过期原因写成它自己的那句，标记在后，第二次通知时什么都不再计数。
            outcome.update(asset_dependents.mark_dependents_stale(task, element_id=element_id, kind=kind, names=names, reason=text))
            return outcome

        try:
            outcome = repo.mutate_task(task_id, mutation)
        except Exception as exc:  # noqa: BLE001 - 一个项目失败只记在它自己那一行
            logger.warning("资产 %s 同步到项目 %s 失败: %s", element_id, task_id, type(exc).__name__)
            row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            rows.append(row)
            continue
        if outcome is None:
            outcome = {"skipped": SKIPPED_MISSING}
        row.update(outcome)
        renamed_any = renamed_any or bool(outcome.get("renamed"))
        rows.append(row)
    return {"tasks": rows, "renamed": renamed_any}


def element_changed(element: Mapping[str, Any], *, reason: str, old_name: str | None = None) -> dict[str, Any]:
    """``element``: {id, owner_id, kind, name, description, version, metadata}。

    返回 {"tasks": [{"task_id", "shots_marked", "clips_marked", "boards_marked", "skipped"?}], "renamed": bool}。
    不抛异常：一个项目失败只记进它自己那一行。
    """
    try:
        return sync_element(element, reason=reason, old_name=old_name)
    except Exception as exc:  # noqa: BLE001 - 资产已经改好了，通知失败不能让它回滚
        logger.warning("资产 %s 同步失败: %s", _text(element.get("id")), type(exc).__name__)
        return {"tasks": [], "renamed": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def element_usages(element: Mapping[str, Any], *, repo: Any = None) -> list[dict[str, Any]]:
    """``usages`` 的实现；``repo`` 留给测试和已经拿着仓库的调用方。"""
    repo = repo if repo is not None else _repo()
    owner_id = _text(element.get("owner_id"))
    element_id = _text(element.get("id"))
    kind = _text(element.get("kind"))
    names = _names(element)
    keys = {normalized_asset_name(item) for item in names} - {""}
    rows: list[dict[str, Any]] = []
    for task_id in element_task_ids(element.get("metadata")):
        task = repo.get_task(task_id)
        if not isinstance(task, dict) or not _owned(task, owner_id):
            continue
        config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
        title = _text(config.get("title_suggestion"))
        for shot in asset_dependents.shots_using(task, element_id=element_id, kind=kind, names=names):
            entries = [
                entry for entry in asset_dependents.shot_assets(task, shot)
                if (element_id and entry["element_id"] == element_id)
                or (entry["kind"] in (kind, "") and normalized_asset_name(entry["name"]) in keys)
            ]
            rows.append({
                "task_id": task_id,
                "title": title,
                "scene_id": _text(shot.get("scene_id")),
                "shot_id": shot.get("shot_id"),
                "shot_uid": episode_cycle.shot_uid(shot),
                # 绑定里只记了定妆造型 id 的镜头对不上条目，但它就是画在分镜里的。
                "in_storyboard": any(entry["in_storyboard"] for entry in entries) or not entries,
                "in_video": any(entry["in_video"] for entry in entries),
            })
    return rows


def usages(element: Mapping[str, Any]) -> list[dict[str, Any]]:
    """引用这个资产的镜头：[{task_id, title, scene_id, shot_id, shot_uid, in_storyboard, in_video}]。"""
    return element_usages(element)


__all__ = ["SKIPPED_MISSING", "SKIPPED_OWNER", "SKIPPED_RUNNING", "element_changed", "element_usages", "sync_element", "usages"]

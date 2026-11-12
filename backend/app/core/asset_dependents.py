# -*- coding: utf-8 -*-
"""一个资产被哪些镜头用着，改了它之后哪些镜头、场景板和片段要跟着过期。

镜头用资产有三条线索：第 4 阶段画图时绑上的参考(``shot["asset_bindings"]``，带素材库 id 和版本)，
分镜表里点到的名字(入镜角色、道具、特效、场景)，以及第 5 阶段片段上的参考图序号(``reference_numbers`` /
``mention_kinds`` / ``asset_versions``)。这里全是纯函数：只读写传进来的任务字典，不碰数据库，不调模型。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

from app.core import episode_cycle
from app.core.element_scope import normalized_asset_name

# 资产在素材库里的种类 → 分镜表镜头上点名它的字段。
SHOT_FIELDS: dict[str, str] = {"actor": "characters", "prop": "props", "effect": "effects", "scene": "scene"}
# 项目内资产身份(asset_identity)的种类 → 素材库 / 分镜绑定的种类。
IDENTITY_KINDS: dict[str, str] = {"character": "actor", "scene": "scene", "prop": "prop"}
# 分镜表的场景字段是「；」连起来的场景名；没有场景资产时它退成一段剧情原文，那不是名字。
_SCENE_SEPARATOR = re.compile(r"[；;]")
_MAX_NAME_LENGTH = 40
# 分镜表里「本格无额外道具」「空镜（无人物）」这类占位不是资产。
_PLACEHOLDER = re.compile(r"^(?:本格无|空镜|无$|无人|无出场|[—\-]$)")

STALE_REASON = "资产「{name}」已修改，需重画本场分镜、重跑第 5 阶段后生效"
MERGED_REASON = "资产「{name}」已并入「{survivor}」，需重画本场分镜、重跑第 5 阶段后生效"


def _key(value: Any) -> str:
    return normalized_asset_name(value)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _version(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _assets(task: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = task.get("assets")
    return assets if isinstance(assets, Mapping) else {}


def _shots(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    shots = _assets(task).get("4")
    return [shot for shot in shots if isinstance(shot, dict)] if isinstance(shots, list) else []


def _clips(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    clips = _assets(task).get("5")
    return [clip for clip in clips if isinstance(clip, dict)] if isinstance(clips, list) else []


def _field_names(shot: Mapping[str, Any], kind: str) -> list[str]:
    """镜头上点名 ``kind`` 资产的名字(去掉占位)。"""
    field = SHOT_FIELDS.get(kind)
    if not field:
        return []
    value = shot.get(field)
    if kind == "scene":
        parts = _SCENE_SEPARATOR.split(value) if isinstance(value, str) else []
        parts = [part for part in parts if len(part.strip()) <= _MAX_NAME_LENGTH]
    elif isinstance(value, str):
        parts = re.split(r"[、，,/]", value)
    elif isinstance(value, list):
        parts = [str(item) for item in value if isinstance(item, (str, int))]
    else:
        parts = []
    names: list[str] = []
    for part in parts:
        name = _text(part)
        if name and not _PLACEHOLDER.match(name) and name not in names:
            names.append(name)
    return names


def _bindings(shot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = shot.get("asset_bindings")
    return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []


def binding_entries(references: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """第 4 阶段画这一格时绑上的参考 → 写进 ``shot["asset_bindings"]`` 的样子。

    同一个资产发了几张图(全身 + 大头照、场地多视角)只记一条；只在项目里、不在素材库的资产 element_id 为空。
    """
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for reference in references:
        if not isinstance(reference, Mapping):
            continue
        kind, name = _text(reference.get("kind")), _text(reference.get("name"))
        marker = (kind, _key(name))
        if not kind or not name or marker in seen:
            continue
        seen.add(marker)
        entry: dict[str, Any] = {
            "kind": kind, "name": name,
            "element_id": _text(reference.get("id")),
            "element_version": _version(reference.get("version")),
        }
        if _text(reference.get("variant_element_id")):
            entry["variant_element_id"] = _text(reference.get("variant_element_id"))
            entry["variant_element_version"] = _version(reference.get("variant_version"))
        entries.append(entry)
    return entries


def reference_versions(references: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """发给视频模型的参考里每个素材库资产的版本：{element_id: version}；定妆造型按它自己的元素记。"""
    versions: dict[str, int] = {}
    for reference in references:
        if not isinstance(reference, Mapping):
            continue
        for id_key, version_key in (("id", "version"), ("variant_element_id", "variant_version")):
            element_id = _text(reference.get(id_key))
            if element_id:
                versions[element_id] = max(versions.get(element_id, 0), _version(reference.get(version_key)))
    return versions


def request_asset_versions(request: Mapping[str, Any]) -> dict[str, int]:
    """第 5 阶段一个视频请求用到的素材库资产版本：分镜片段请求合并了各瞬间的参考，单镜请求看它自己的参考。"""
    versions = request.get("asset_versions")
    if isinstance(versions, Mapping):
        return {str(key): _version(value) for key, value in versions.items()}
    return reference_versions(request.get("library_references") or [])


def versions_match(earlier: Mapping[str, Any], current: Mapping[str, int]) -> bool:
    """上一轮的片子是不是按同样版本的资产出的。

    没记版本的旧片(这项功能上线前做的)算一样：否则下次跑第 5 阶段会把所有旧片整批重新生成，
    那是一大笔没人要的花费。旧片之后要是改了资产，资产改动本身会把它标成过期，照样会重做。
    """
    recorded = earlier.get("asset_versions")
    if not isinstance(recorded, Mapping):
        return True
    return {str(key): _version(value) for key, value in recorded.items()} == {str(key): _version(value) for key, value in current.items()}


def board_asset_stale(board: Any) -> bool:
    """场景板因为资产改过而过期；标记之后已经重画过(九宫格换了)的不算。"""
    if not isinstance(board, Mapping) or not board.get("asset_stale"):
        return False
    marked_grid = board.get("asset_stale_grid_url")
    return marked_grid is None or marked_grid == (board.get("grid_url") or "")


def _board(task: Mapping[str, Any], scene_id: str) -> Any:
    boards = _assets(task).get("4_scene_boards")
    return boards.get(scene_id) if isinstance(boards, Mapping) else None


def shot_assets(task: Mapping[str, Any], shot: Mapping[str, Any]) -> list[dict[str, Any]]:
    """这一镜用到的每个资产：{kind, name, element_id, element_version, image_number, in_storyboard, in_video, stale}。

    分镜绑定、分镜表点名和片段参考三处合并，按(类型, 规范化名字)去重。
    """
    clip = episode_cycle.clip_for(shot, _clips(task)) or {}
    stale = bool(clip.get("stale")) or bool(shot.get("asset_stale")) or board_asset_stale(_board(task, _text(shot.get("scene_id"))))
    entries: list[dict[str, Any]] = []
    index: dict[tuple[str, str], dict[str, Any]] = {}

    def add(kind: str, name: str, **fields: Any) -> dict[str, Any] | None:
        kind, name = _text(kind), _text(name)
        if not name:
            return None
        marker = (kind, _key(name))
        entry = index.get(marker)
        if entry is None and not kind:
            # 片段只记了序号、没记类型的名字：按名字认已有的那一条。
            entry = next((item for (_, key), item in index.items() if key == marker[1]), None)
        if entry is None:
            entry = {
                "kind": kind, "name": name, "element_id": "", "element_version": 0, "image_number": None,
                "in_storyboard": False, "in_video": False, "stale": stale,
            }
            index[marker] = entry
            entries.append(entry)
        for key, value in fields.items():
            if key in ("element_id", "element_version") and entry.get(key):
                continue
            if key in ("in_storyboard", "in_video"):
                entry[key] = entry[key] or bool(value)
            elif value not in (None, ""):
                entry[key] = value
        return entry

    for binding in _bindings(shot):
        add(
            _text(binding.get("kind")), _text(binding.get("name")), in_storyboard=True,
            element_id=_text(binding.get("element_id")), element_version=_version(binding.get("element_version")),
        )
    for kind in SHOT_FIELDS:
        for name in _field_names(shot, kind):
            add(kind, name, in_storyboard=True)
    if clip:
        kinds = clip.get("mention_kinds") if isinstance(clip.get("mention_kinds"), Mapping) else {}
        numbers = clip.get("reference_numbers") if isinstance(clip.get("reference_numbers"), Mapping) else {}
        for name in dict.fromkeys([*numbers, *kinds]):
            number = numbers.get(name)
            add(_text(kinds.get(name)), _text(name), in_video=True, image_number=number if isinstance(number, int) else None)
        versions = clip.get("asset_versions") if isinstance(clip.get("asset_versions"), Mapping) else {}
        for entry in entries:
            if entry["element_id"] and entry["element_id"] in versions:
                entry["in_video"] = True
    return entries


def _binding_hits(shot: Mapping[str, Any], element_id: str, kind: str, keys: set[str]) -> str:
    """'id'：绑定里就是这个元素；'other'：同名同类型绑的是另一个素材库元素；'name'：按名字对上；''：没用。"""
    named_other = False
    named = False
    for binding in _bindings(shot):
        bound_ids = {_text(binding.get("element_id")), _text(binding.get("variant_element_id"))} - {""}
        if element_id and element_id in bound_ids:
            return "id"
        if _text(binding.get("kind")) == kind and _key(binding.get("name")) in keys:
            if bound_ids and element_id:
                named_other = True
            else:
                named = True
    if named_other:
        return "other"
    return "name" if named else ""


def shots_using(task: Mapping[str, Any], *, element_id: str = "", kind: str, names: Iterable[Any]) -> list[dict[str, Any]]:
    """引用这个资产的镜头：先按分镜绑定里的素材库 id 认；没绑 id 的按类型 + 名字(含别名)对分镜表的字段。"""
    element_id = _text(element_id)
    keys = {_key(name) for name in names} - {""}
    used: list[dict[str, Any]] = []
    for shot in _shots(task):
        hit = _binding_hits(shot, element_id, kind, keys)
        if hit == "other":
            continue
        if hit or (keys and any(_key(name) in keys for name in _field_names(shot, kind))):
            used.append(shot)
    return used


def mark_dependents_stale(
    task: MutableMapping[str, Any], *, element_id: str = "", kind: str, names: Iterable[Any], reason: str,
) -> dict[str, int]:
    """把用到这个资产的镜头、它们所在的场景板和覆盖它们的第 5 阶段片段标成过期。

    片段按覆盖的镜头编号对(各场镜号都从 1 起，只看镜号会串场)，没有场号的旧片段按镜号对。
    已经标过的不再计数：同一次修改通知两遍，第二遍返回全 0。
    """
    shots = shots_using(task, element_id=element_id, kind=kind, names=list(names))
    counts = {"shots_marked": 0, "clips_marked": 0, "boards_marked": 0}
    if not shots:
        return counts
    for shot in shots:
        if not (shot.get("asset_stale") and shot.get("asset_stale_reason") == reason):
            counts["shots_marked"] += 1
        shot["asset_stale"] = True
        shot["asset_stale_reason"] = reason
    uids = {episode_cycle.shot_uid(shot) for shot in shots}
    legacy_ids = {str(shot.get("shot_id")) for shot in shots if shot.get("shot_id") not in (None, "")}
    for clip in _clips(task):
        if clip.get("scene_id") or clip.get("shot_uids"):
            hit = not uids.isdisjoint(episode_cycle.covered_uids(clip))
        else:
            hit = str(clip.get("shot_id")) in legacy_ids
        if not hit:
            continue
        if not (clip.get("stale") and clip.get("stale_reason") == reason):
            counts["clips_marked"] += 1
        clip["stale"] = True
        clip["stale_reason"] = reason
    assets = task.get("assets")
    boards = assets.get("4_scene_boards") if isinstance(assets, MutableMapping) else None
    if isinstance(boards, MutableMapping):
        for scene_id in dict.fromkeys(_text(shot.get("scene_id")) for shot in shots):
            board = boards.get(scene_id)
            if not scene_id or not isinstance(board, MutableMapping):
                continue
            if not (board_asset_stale(board) and board.get("asset_stale_reason") == reason):
                counts["boards_marked"] += 1
            board["asset_stale"] = True
            board["asset_stale_reason"] = reason
            # 记下标记时的九宫格：重画之后换了图，这个标记自然失效。
            board["asset_stale_grid_url"] = board.get("grid_url") or ""
    return counts


__all__ = [
    "IDENTITY_KINDS",
    "MERGED_REASON",
    "SHOT_FIELDS",
    "STALE_REASON",
    "binding_entries",
    "board_asset_stale",
    "mark_dependents_stale",
    "reference_versions",
    "request_asset_versions",
    "shot_assets",
    "shots_using",
    "versions_match",
]

"""Scene-scoped production references; no provider calls or persistence."""

from __future__ import annotations

import re
from typing import Any

KINDS = {"scene": "scenes", "prop": "props", "costume": "costumes", "effect": "effects"}
LABELS = {
    "actor": "数字演员",
    "scene": "拍摄场地",
    "prop": "拍摄道具",
    "costume": "服装",
    "effect": "特效",
}
EMPTY_ACTOR = "空镜（无人物）"
_EMPTY_NAMES = {"无", "无人", "无人物", "空镜", "—", "-", "无出场角色", EMPTY_ACTOR}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[、，,/]", value)
    return (
        list(dict.fromkeys(_text(name) for name in (value or []) if _text(name)))
        if isinstance(value, list)
        else []
    )


def _scoped(item: dict, scene_id: str) -> bool:
    metadata = item.get("metadata") or {}
    scope = (
        item.get("scene_ids")
        or item.get("scene_id")
        or metadata.get("scene_ids")
        or metadata.get("scene_id")
    )
    return not scope or scene_id in _names(scope)


def _mentioned(item: dict, text: str) -> bool:
    name = _text(item.get("name"))
    aliases = _names(item.get("aliases")) + _names(name)
    # Catalog labels commonly append staging annotations to the actual name.
    stem = re.split(r"[（(]", name)[0]
    stem = re.sub(r"(?:夜景|日景|内景|外景|全景|场景|效果|特效)$", "", stem)
    # A label such as 血痕三道 names the same effect as 三道血痕.
    stem = re.sub(r"[一二三四五六七八九十百\d]+(?:道|条|滴|束)", "", stem)
    return any(len(alias) >= 2 and alias in text for alias in [name, stem, *aliases])


def _line(item: dict) -> str:
    return f"{item['name']}：{item.get('description') or '沿用已确认造型与状态'}"


def _costume_owner(item: dict, name: str) -> bool:
    # '贺兰霆亲卫' and '贺兰霆手下' describe other actors, not his outfit.
    return name in item["name"] or bool(
        re.match(
            rf"^{re.escape(name)}(?:[，,：:；;\s]|$)", _text(item.get("description"))
        )
    )


def compile_scene_context(
    task: dict, scene: dict, elements: list[dict] | None = None
) -> dict:
    """Bind only source-backed assets, never use the first two global actors."""
    assets = task.get("assets") or {}
    scene_id = _text(scene.get("scene_id")) or "E1S01"
    content = _text(scene.get("content"))
    dialogue = _text(scene.get("dialogue"))
    script = content + (
        f"\n对白：{dialogue}" if dialogue and dialogue not in {"-", "—", "无"} else ""
    )
    profiles = {
        item["name"]: _text(item.get("desc"))
        for item in assets.get("3_characters", [])
        if isinstance(item, dict) and _text(item.get("name"))
    }
    actor_elements: dict[str, dict[str, Any]] = {}
    for item in elements or []:
        if item.get("kind") == "actor" and _scoped(item, scene_id):
            actor_elements.setdefault(item["name"], item)
    all_names = list(dict.fromkeys([*profiles, *actor_elements]))
    characters = _names(scene.get("characters")) or [
        name for name in all_names if name in script
    ]
    characters = [name for name in characters if name not in _EMPTY_NAMES]
    sheets = assets.get("3_sheets") or {}
    actors: list[dict[str, Any]] = []
    for name in characters:
        library_actor = actor_elements.get(name, {})
        description = _text(library_actor.get("description")) or profiles.get(name, "")
        profiles[name] = description
        actors.append(
            {
                **library_actor,
                "kind": "actor",
                "name": name,
                "description": description,
                "image_url": library_actor.get("image_url") or sheets.get(name) or "",
            }
        )

    catalog = (assets.get("2_breakdown") or {}).get("production_assets") or {}
    context: dict[str, Any] = {
        "scene_id": scene_id,
        "script": script,
        "characters": characters,
        "profiles": {name: profiles.get(name, "") for name in characters},
        "all_character_names": all_names,
        "actors": actors,
    }
    for kind, key in KINDS.items():
        candidates = {}
        for value in catalog.get(key) or []:
            item = value if isinstance(value, dict) else {"name": value}
            if _text(item.get("name")) and _scoped(item, scene_id):
                candidates[item["name"]] = {**item, "kind": kind}
        library_names = set()
        for item in elements or []:
            if item.get("kind") == kind and _scoped(item, scene_id):
                if item["name"] not in library_names:
                    candidates[item["name"]] = item
                    library_names.add(item["name"])
        selected = []
        for item in candidates.values():
            explicit_scope = (
                item.get("scene_ids")
                or item.get("scene_id")
                or (item.get("metadata") or {}).get("scene_ids")
                or (item.get("metadata") or {}).get("scene_id")
            )
            matched = bool(explicit_scope) or _mentioned(item, script)
            if kind == "costume" and not matched:
                owners = [name for name in characters if _costume_owner(item, name)]
                # A single character's alternate outfits must not all appear in
                # one shot. Without a scene/explicit name, use only a unique look.
                matched = any(
                    sum(_costume_owner(other, name) for other in candidates.values())
                    == 1
                    for name in owners
                )
            if matched:
                selected.append(item)
        context[key] = selected
    lines = [
        f"【当前剧情 {scene_id}】\n{script}",
        "以下资料只用于锁定外观；不得把资产背景故事或其他场次事件画进本场。",
    ]
    for kind, items in [
        ("actor", actors),
        *((kind, context[key]) for kind, key in KINDS.items()),
    ]:
        lines.append(
            f"【{LABELS[kind]}】\n"
            + (
                "\n".join(_line(item) for item in items)
                or "无已匹配资产；仅依据当前剧情，不添加无关内容"
            )
        )
    context["prompt"] = "\n".join(lines)
    return context


def merge_video_references(
    sheets: list[tuple[str, str]], references: list[dict], *, limit: int = 9
) -> tuple[list[str], str]:
    """Five-view sheets first, then the shot's library references; deduplicated.

    Returns the image list for the video provider plus the role lines the prompt
    needs so each reference locks exactly one asset and nothing else.
    """
    ordered: list[tuple[str, str, str]] = [("actor", name, url) for name, url in sheets if url]
    ordered += [
        (str(item.get("kind") or ""), str(item.get("name") or ""), str(item.get("image_url") or ""))
        for item in references
        if item.get("image_url")
    ]
    images: list[str] = []
    notes: list[str] = []
    for kind, name, url in ordered:
        if url in images or len(images) >= limit:
            continue
        images.append(url)
        label = "数字演员五视图" if kind == "actor" else LABELS.get(kind, kind)
        notes.append(f"参考图{len(images)}仅锁定{label}「{name}」，不是额外剧情或额外人物")
    return images, "；".join(notes)


def panel_context(context: dict, shot: dict) -> dict:
    """Respect the shot's cast column and bind references with type/name labels."""
    action = _text(shot.get("desc"))
    if len(action) < 2 or re.search(
        r"剧情推进分镜\s*\d+|第\d+个因果/情绪信息单元", action
    ):
        raise ValueError("分镜画面仍为通用占位内容，请重新拆解当前剧情")
    declared = _names(shot.get("characters"))
    unknown = [
        name
        for name in declared
        if name not in context["characters"] and name not in _EMPTY_NAMES
    ]
    unrelated = [
        name
        for name in context["all_character_names"]
        if name not in context["characters"] and name in action
    ]
    if unknown or unrelated:
        raise ValueError(
            "分镜包含当前剧情未出场角色：" + "、".join(unknown or unrelated)
        )
    if declared or shot.get("characters_explicit"):
        characters = [name for name in declared if name in context["characters"]]
        missing = [
            name
            for name in context["characters"]
            if name in action and name not in characters
        ]
        if missing:
            raise ValueError("分镜画面与入镜角色列不一致，缺少：" + "、".join(missing))
    else:
        characters = [
            name for name in context["characters"] if name in action
        ] or context["characters"]
    selected = [item for item in context["actors"] if item["name"] in characters]
    selected += context["scenes"]
    props = [item for item in context["props"] if _mentioned(item, action)]
    effects = [item for item in context["effects"] if _mentioned(item, action)]
    costumes = [
        item
        for item in context["costumes"]
        if any(_costume_owner(item, name) for name in characters)
        or _mentioned(item, action)
    ]
    selected += props + costumes + effects
    references: list[dict[str, str]] = []
    seen_urls = set()
    for item in selected:
        url = item.get("image_url")
        if url and url not in seen_urls and len(references) < 9:
            references.append(
                {"kind": item["kind"], "name": item["name"], "image_url": url}
            )
            seen_urls.add(url)
    lines = [
        f"【本格剧情动作】{action}",
        f"【本格入镜人物】{'、'.join(characters) or '空镜，无人物'}",
    ]
    lines.extend(f"【{LABELS[item['kind']]}】{_line(item)}" for item in selected)
    lines.extend(
        f"参考图{index}仅锁定{LABELS[item['kind']]}「{item['name']}」，不是额外剧情或额外人物。"
        for index, item in enumerate(references, 1)
    )
    lines.append(
        "严格以本格动作决定可见内容；其他镜头的动作、未出场角色、未触发特效不得提前出现。画风不得改变剧本时代、场地或服装。"
    )
    return {
        "characters": characters or [EMPTY_ACTOR],
        "props": [item["name"] for item in props] or ["本格无额外道具"],
        "effects": [item["name"] for item in effects] or ["本格无额外特效"],
        "references": references,
        "prompt": "\n".join(lines),
    }

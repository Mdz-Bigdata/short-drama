# -*- coding: utf-8 -*-
"""武侠与修仙的特效写法：哪场戏用哪一套，分镜和视频提示词里特效怎么写。

- 修仙(仙侠、玄幻)：法术、法宝、阵法、天劫这类特效先定形再有光，按蓄力 → 释放 → 作用 → 余波走，
  特效照亮朝向它的人，环境跟着受力。打戏和非打斗的奇观(渡劫、突破、御剑、阵法……)都适用，
  非打斗奇观另有各自的写法。
- 武侠：内力、掌风、剑气靠物理反应显力，不画成发光的能量体。

写法本身在特效指南 ``xianxia-combat-vfx``(shot-design-master)里，按小节标题挑，那份文件是唯一出处；
哪场戏算哪一套、挑哪几节、提示词里的几句措辞在 ``app/data/prompt/wuxia_vfx.json``。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from typing import Any

from app.core import knowledge_registry, prompt_data, technique_look

_WORDING = "wuxia_vfx"
_GUIDE = "xianxia-combat-vfx"
_NO_EFFECT = ("本格无额外", "本场无额外")

XIANXIA = "xianxia"
WUXIA = "wuxia"


def _words(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING, key)


def _has_any(text: str, words: Iterable[str]) -> bool:
    return any(word and word in text for word in words)


def kind_of(text: str, genre: str = "") -> str:
    """这场戏要哪一套特效写法："xianxia"、"wuxia"，都不要时是空串。

    题材定基调：修仙剧里的剑气也是能量体，武侠剧里的剑气只是一线寒光；题材不明时看词，
    修仙才有的词(灵力、法阵、雷劫……)优先。只有题材、没有特效词的场次(文戏)不要。
    """
    text = str(text or "")
    genre = str(genre or "").strip().lower()
    xianxia = _has_any(text, _words("xianxia_markers"))
    wuxia = _has_any(text, _words("wuxia_markers"))
    if genre in _words("xianxia_genres"):
        return XIANXIA if xianxia or wuxia else ""
    if genre in _words("wuxia_genres"):
        # 武侠剧里写到了法阵、雷劫，那一场照修仙的写。
        return XIANXIA if _has_any(text, _words("spectacle_markers")) else (WUXIA if wuxia else "")
    if xianxia:
        return XIANXIA
    return WUXIA if wuxia else ""


def is_spectacle(text: str) -> bool:
    """有渡劫、突破、御剑、阵法、法宝、结界、召唤、炼丹这类非打斗奇观。"""
    return _has_any(str(text or ""), _words("spectacle_markers"))


@lru_cache(maxsize=1)
def _guide() -> str:
    item = knowledge_registry.section(_GUIDE)
    if item is None:
        return ""
    try:
        return item.path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _sections(keywords: Iterable[str]) -> list[str]:
    """标题里含 ``keywords`` 之一的 ``## `` 小节，按关键词的顺序；给视频模型的语法行不要。"""
    blocks = [block for block in re.split(r"(?m)^(?=## )", _guide()) if block.startswith("## ")]
    picked: list[str] = []
    for keyword in keywords:
        for block in blocks:
            heading = block.splitlines()[0]
            if keyword in heading and block not in picked:
                picked.append(block)
    return [
        "\n".join(line for line in block.splitlines() if not line.startswith("Seedance")).strip()
        for block in picked
    ]


def _fit(parts: list[str], budget: int) -> str:
    """整节装，装不下的节从后往前按行丢。"""
    text = "\n\n".join(parts)
    if len(text) <= budget:
        return text
    lines = text.splitlines()
    while lines and len("\n".join(lines)) > budget:
        lines.pop()
    return "\n".join(lines).rstrip()


def vfx_brief(scene_text: str, genre: str = "", *, fight: bool = False) -> str:
    """一场戏追加给分镜师的特效写法；没有特效的场次是空串。

    修仙打戏：能量四态、尺度四件套、特效镜头规格；修仙的非打斗奇观再加各自的写法；武侠：内力外放。
    """
    kind = kind_of(scene_text, genre)
    if not kind:
        return ""
    if kind == WUXIA:
        keys, lead = _words("wuxia_sections"), prompt_data.text(_WORDING, "wuxia_lead")
    elif fight or not is_spectacle(scene_text):
        keys, lead = _words("fight_sections"), prompt_data.text(_WORDING, "xianxia_lead")
    else:
        keys, lead = _words("spectacle_sections"), prompt_data.text(_WORDING, "xianxia_lead")
    guide = _fit(_sections(keys), prompt_data.number(_WORDING, "budget"))
    return f"{lead}\n\n{guide}" if guide else lead


def named_effects(names: Iterable[Any]) -> list[str]:
    """镜头里真有的特效名，占位词(「本格无额外特效」)不算。"""
    return [
        str(name).strip() for name in names or []
        if str(name).strip() not in ("", "无") and not str(name).strip().startswith(_NO_EFFECT)
    ]


def _catalog(task: Mapping[str, Any]) -> dict[str, str]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), Mapping) else {}
    catalog = breakdown.get("production_assets") if isinstance(breakdown.get("production_assets"), Mapping) else {}
    return {
        str(item.get("name") or "").strip(): str(item.get("description") or "").strip()
        for item in catalog.get("effects") or [] if isinstance(item, Mapping) and str(item.get("name") or "").strip()
    }


def _short(text: str, limit: int) -> str:
    text = re.sub(r"\s+", "", re.sub(r"[；;。]+", "，", str(text or ""))).strip("，")
    return text if len(text) <= limit else text[:limit].rstrip("，、") + "…"


def effect_sound(name: str, description: str = "") -> str:
    """特效的声音(雷→炸雷闷响、剑气→破空声)：先看名字再看描述，表里靠前的先认；认不出是空串。"""
    for text in (str(name or ""), str(description or "")):
        for word, sound in prompt_data.pairs(_WORDING, "effect_sounds"):
            if word in text:
                return sound
    return ""


def effect_lines(names: Iterable[Any], task: Mapping[str, Any]) -> list[str]:
    """视频提示词「特效：」那一节：特效名带上拆解目录里它长什么样和它的声音，都没有时就写名字。"""
    described = _catalog(task)
    limit = prompt_data.number(_WORDING, "effect_limit")
    lines: list[str] = []
    for name in named_effects(names):
        looks, sound = _short(described.get(name, ""), limit), effect_sound(name, described.get(name, ""))
        if looks and sound:
            lines.append(prompt_data.text(_WORDING, "effect_line_with_sound").format(name, looks, sound))
        elif looks:
            lines.append(prompt_data.text(_WORDING, "effect_line").format(name, looks))
        elif sound:
            lines.append(prompt_data.text(_WORDING, "effect_line_sound_only").format(name, sound))
        else:
            lines.append(name)
    return lines


def bound_by_term(effects: Sequence[Mapping[str, Any]], text: str, already: Iterable[str] = ()) -> list[Mapping[str, Any]]:
    """名字没原样出现、但这一镜写了它的核心词(「雷劫劈下」之于「九霄雷劫」)的特效。

    核心词只认特效词表里的词，而且本场只有这一个特效带这个词：两个特效都叫「…剑气」时谁也不认，免得绑错人。
    """
    text = str(text or "")
    taken = set(already)
    terms = [term for term in _words("effect_terms") if term in text]
    if not terms:
        return []
    owners: dict[str, list[Mapping[str, Any]]] = {}
    for item in effects:
        for term in terms:
            if term in str(item.get("name") or ""):
                owners.setdefault(term, []).append(item)
    picked: list[Mapping[str, Any]] = []
    for term in terms:
        items = owners.get(term) or []
        if len(items) == 1 and str(items[0].get("name")) not in taken and items[0] not in picked:
            picked.append(items[0])
    return picked


def panel_effect_note(name: str, description: str) -> str:
    """分镜单帧里特效的那一句：有参考图也写，图只给一个瞬间，文字说清它长什么样。"""
    text = _short(description, prompt_data.number(_WORDING, "panel_effect_limit"))
    return prompt_data.text(_WORDING, "panel_effect").format(name, text) if text else ""


def panel_effect_light(names: Iterable[Any]) -> str:
    """分镜单帧里特效当光源的那一句；没有特效时是空串。"""
    effects = named_effects(names)
    return prompt_data.text(_WORDING, "panel_effect_light").format("、".join(f"「{name}」" for name in effects)) if effects else ""


def reference_rules(name: str, description: str) -> str:
    """特效参考图的设计要求：修仙的定形、三层与配色；武侠的画受力不画发光体。题材看不出来时按修仙写。

    特效名就是一门术法(「大荒囚天指」「护山大阵」)时，再加上术法按名字定的形(technique_look)。
    """
    kind = kind_of(f"{name} {description}")
    rules = prompt_data.text(_WORDING, "reference_wuxia" if kind == WUXIA else "reference_xianxia")
    if technique_look.find_names(f"「{name}」"):
        rules += prompt_data.text(_WORDING, "reference_technique").format(technique_look.look(name, description))
    return rules


def panel_effect_beat(names: Iterable[Any], frame_state: str = "start") -> str:
    """分镜单帧里特效画在哪一拍：首帧画蓄力(放出之前)，尾帧画余波；没有特效时是空串。"""
    if not named_effects(names):
        return ""
    return prompt_data.text(_WORDING, "panel_effect_end" if frame_state == "end" else "panel_effect_start")


def plan_rules_for(*texts: str, genre: str = "") -> str:
    """编剧写本集时的奇观设计规则：本集有渡劫、突破、御剑这类修仙奇观时才给，其余是空串。"""
    text = "\n".join(str(item or "") for item in texts)
    if not is_spectacle(text) or kind_of(text, genre) != XIANXIA:
        return ""
    return prompt_data.text(_WORDING, "plan_rules")


def _color_of(text: str) -> str:
    color = next((word for word in _words("owner_colors") if word in text), "")
    return color[:-1] if color.endswith("色") else ("紫" if color == "紫电" else color)


def signature_colors(task: Mapping[str, Any], people: Iterable[str] = ()) -> list[tuple[str, str, str]]:
    """拆解目录里写了归谁、写了颜色的特效：(角色, 特效名, 颜色)。``people`` 给了就只留这几个人的。

    特效名或描述里出现角色名(「沈无咎·紫电剑气」「沈无咎的剑气，紫色」)才算他的；一个人只取第一个有颜色的特效。
    """
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    cast = [str(item.get("name") or "").strip() for item in assets.get("3_characters") or [] if isinstance(item, Mapping)]
    wanted = {str(name) for name in people} if people else None
    seen: dict[str, tuple[str, str, str]] = {}
    for name, description in _catalog(task).items():
        owner = next((person for person in cast if person and (person in name or description.startswith(person))), "")
        if not owner or owner in seen or (wanted is not None and owner not in wanted):
            continue
        color = _color_of(name) or _color_of(description)
        if color:
            seen[owner] = (owner, name, color)
    return list(seen.values())


def color_line(task: Mapping[str, Any], people: Iterable[str] = ()) -> str:
    """本场各人的特效主色写成一句；没人有带颜色的特效时是空串。"""
    colors = signature_colors(task, people)
    if not colors:
        return ""
    template = prompt_data.text(_WORDING, "color_item")
    return prompt_data.text(_WORDING, "color_line").format("；".join(template.format(*item) for item in colors))


__all__ = [
    "WUXIA", "XIANXIA", "bound_by_term", "color_line", "effect_lines", "effect_sound", "is_spectacle", "kind_of", "named_effects", "panel_effect_beat", "panel_effect_light", "panel_effect_note", "plan_rules_for", "reference_rules", "signature_colors", "vfx_brief",
]

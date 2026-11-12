# -*- coding: utf-8 -*-
"""打戏场次给分镜师的那几样东西，按戏挑，不按文件头截。

- 武打指南(martial-arts)按小节抽：力学、运镜、出招-受击、轴线、五镜动作链、音效、冲击帧。整篇从头截只到得了
  「实战模板」，真正让打戏有力量、接得顺的几节反而进不了提示词。
- 专项打戏骨架(performance-action §3.16)六种里只挑和这场戏对得上的一种：六种一起装不下，也用不上。
- 三人以上同场时的多人编排：每一拍写清每个人在哪、在做什么，配上多人交锋模式表(结构与怎么环扣两列)。

挑哪一节、认哪种戏、几人算多人，都在 app/data/prompt/fight_scene.json。
"""

from __future__ import annotations

import csv
import io
import re
from functools import lru_cache

from app.core import knowledge_registry, prompt_data

_WORDING = "fight_scene"
_SKELETON_SECTION = "performance-action"
_MARTIAL_SECTION = "martial-arts"


def _read(key: str) -> str:
    item = knowledge_registry.section(key)
    if item is None:
        return ""
    try:
        return item.path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


@lru_cache(maxsize=1)
def martial_guide() -> str:
    """武打指南里打戏真正要用的几节，按 ``martial_sections`` 的顺序；超出预算从尾部按行丢。"""
    text = _read(_MARTIAL_SECTION)
    if not text:
        return ""
    blocks = re.split(r"(?m)^(?=## )", text)
    picked = [
        block.strip() for anchor in prompt_data.words(_WORDING, "martial_sections")
        for block in blocks if block.startswith("## ") and anchor in block.splitlines()[0]
    ]
    joined = "\n\n".join(dict.fromkeys(picked))
    budget = prompt_data.number(_WORDING, "martial_budget")
    if len(joined) <= budget:
        return joined
    cut = joined[:budget]
    return cut[: cut.rfind("\n")] if "\n" in cut else cut


@lru_cache(maxsize=1)
def _skeletons() -> dict[str, str]:
    """§3.16 的六种骨架：{标题里的名字: 整段}。"""
    text = _read(_SKELETON_SECTION)
    start = text.find("### 3.16")
    if start < 0:
        return {}
    end = text.find("\n### ", start + 8)
    section = text[start:end if end > 0 else len(text)]
    found: dict[str, str] = {}
    for block in re.split(r"(?m)^(?=#### )", section):
        if block.startswith("#### "):
            title = re.sub(r"^#### [A-Z]\.\s*", "", block.splitlines()[0]).strip()
            found[title] = block.strip()
    return found


def skeleton_for(scene_text: str) -> str:
    """和这场戏对得上的那一种专项骨架(按 ``skeletons`` 的先后认)；一种都对不上是空串。"""
    text = str(scene_text or "")
    skeletons = _skeletons()
    for name, words in prompt_data.value(_WORDING, "skeletons"):
        if any(word in text for word in words):
            body = next((block for title, block in skeletons.items() if title.startswith(str(name))), "")
            if body:
                return f"{prompt_data.text(_WORDING, 'skeleton_lead')}\n{body}"
    return ""


@lru_cache(maxsize=1)
def _modes() -> str:
    """多人交锋模式表的结构与环扣两列(写法列里的逐镜上限不带)。"""
    text = _read(prompt_data.text(_WORDING, "multi_fighter_modes_file"))
    rows = list(csv.DictReader(io.StringIO(text)))
    return "\n".join(
        f"- {row.get('码', '')} {row.get('名称', '')}（{row.get('结构', '')}）：{row.get('怎么环扣', '')}" for row in rows if row.get("码")
    )


def multi_fighter_brief(fighters: int) -> str:
    """三人以上同场交手时的编排要求；人少时是空串。"""
    if fighters < prompt_data.number(_WORDING, "multi_fighter_min"):
        return ""
    modes = _modes()
    return prompt_data.text(_WORDING, "multi_fighter_rule").format(fighters) + (f"\n{modes}" if modes else "")


def scene_brief(scene_text: str, fighters: int) -> str:
    """一场打戏追加给分镜师的说明：对得上的骨架 + 多人编排。"""
    return "\n\n".join(part for part in (skeleton_for(scene_text), multi_fighter_brief(fighters)) if part)


__all__ = ["martial_guide", "multi_fighter_brief", "scene_brief", "skeleton_for"]

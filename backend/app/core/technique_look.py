# -*- coding: utf-8 -*-
"""术法长什么样，按名字定。

「大荒囚天指」：结尾「指」定形(一指点出、力量收成一束)，「囚」定它对人做什么(光牢合拢)，
「大荒」定颜色质感(苍茫古旧、土黄古铜)，「天」定尺度(从天穹压落)。名字就是视觉说明书，
分镜师照着画，同一门术法全剧长一个样。

只认点了名的术法：书名号、引号里的，或者跟在「施展、使出、祭出、运起、修炼……」后面、以招式字
(指、掌、拳、印、剑、魔功、神通、引……)结尾的名字。「使出全力一剑」「以手指」这类不算。
表和措辞在 app/data/prompt/technique_look.json。
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.core import prompt_data

_WORDING = "technique_look"
#: 数量、程度开头的不是术法名：「全力一剑」「三分力」。
# 「九」不在里面：「九天玄雷斩」「九幽噬魂大法」是常见的术法名。
_NOT_A_NAME_START = tuple("一二三四五六七八十半两全几数每这那")


def _forms() -> list[tuple[str, str]]:
    return [(str(suffix), str(text)) for suffix, text in prompt_data.value(_WORDING, "forms")]


@lru_cache(maxsize=1)
def _cue_pattern() -> re.Pattern[str]:
    """动词后面最短的、以招式字结尾的一串：「施展大荒囚天指一掌拍下」取「大荒囚天指」。"""
    cues = sorted(prompt_data.words(_WORDING, "cue_verbs"), key=len, reverse=True)
    suffixes = sorted({suffix for suffix, _ in _forms()}, key=len, reverse=True)
    high = prompt_data.number(_WORDING, "name_max")
    chars = prompt_data.text(_WORDING, "name_chars")
    # 前瞻：每个位置都试一次，「运起天级功法吞天魔功」里「天级功」不算，后面的「吞天魔功」照样认得到。
    return re.compile(
        f"(?=(?:{'|'.join(map(re.escape, cues))})({chars}{{1,{high - 1}}}?(?:{'|'.join(map(re.escape, suffixes))})))"
    )


def _extend(name: str, after: str) -> str:
    """最短匹配会截短：「掌中剑诀」截成「掌中剑」，「紫霄引雷诀」截成「紫霄引」。
    后面一两个字凑得成招式字结尾、又不是「一掌」这种数量开头的，就带上。"""
    high = prompt_data.number(_WORDING, "name_max")
    chars = prompt_data.text(_WORDING, "name_chars")
    for extra in (after[:2], after[:1]):
        longer = name + extra
        if not extra or extra.startswith(_NOT_A_NAME_START) or len(longer) > high or not re.fullmatch(chars + "+", extra):
            continue
        # 补一个字只为凑齐更长的结尾(剑 → 剑诀)；「神行符」后面的「遁走」是动作，不并进名字。
        ending = next((suffix for suffix, _ in _forms() if longer.endswith(suffix)), "")
        if ending and (len(extra) == 2 or len(ending) > 1):
            return longer
    return name


def _form_of(name: str) -> str:
    return next((text for suffix, text in _forms() if name.endswith(suffix)), "")


def _is_name(name: str) -> bool:
    low, high = prompt_data.number(_WORDING, "name_min"), prompt_data.number(_WORDING, "name_max")
    return (
        low <= len(name) <= high and not name.startswith(_NOT_A_NAME_START)
        and not any(word in name for word in prompt_data.words(_WORDING, "not_in_name")) and bool(_form_of(name))
    )


def find_names(text: str) -> list[str]:
    """场景文字里点了名的术法，按出现先后，不重复。"""
    text = str(text or "")
    found: list[tuple[int, str]] = []
    for match in re.finditer(prompt_data.text(_WORDING, "bracketed"), text):
        if _is_name(match.group(1)):
            found.append((match.start(), match.group(1)))
    for match in _cue_pattern().finditer(text):
        name = _extend(match.group(1), text[match.end(1):])
        if _is_name(name):
            found.append((match.start(1), name))
    names: list[str] = []
    for _, name in sorted(found):
        # 「吞天魔功」认过了，「天魔功」就不再算一门。
        if not any(name in known or known in name for known in names):
            names.append(name)
    return names


def _kind(line: str) -> str:
    """「颜色质感：…」「作用：…」「尺度：…」「形：…」的那个类别。"""
    return line.split("：", 1)[0] if "：" in line else line


def _themes(name: str) -> list[str]:
    """名字里的字说的颜色质感、作用、尺度：长的先认(「大荒」先于「荒」)，认过的字不再算，每类只取名字里最先说到的一条。"""
    rows = [(str(key), str(text)) for key, text in prompt_data.value(_WORDING, "themes")]
    rest, hits = name, []
    for key, text in sorted(rows, key=lambda row: len(row[0]), reverse=True):
        at = rest.find(key)
        if at >= 0:
            rest = rest[:at] + "\0" * len(key) + rest[at + len(key):]
            hits.append((at, text))
    picked: dict[str, str] = {}
    for _, text in sorted(hits):
        picked.setdefault(_kind(text), text)
    return list(picked.values())


def _grade(name: str, text: str) -> str:
    """和名字同一小句里写了品级(「运起天级功法吞天魔功」)，按品级给尺度。"""
    for clause in re.split(r"[，。；！？\n]", text):
        if name not in clause:
            continue
        for grade, scale in prompt_data.value(_WORDING, "grades"):
            if grade in clause:
                return str(scale)
    return ""


def look(name: str, text: str = "") -> str:
    """一门术法在画面上长什么样。"""
    themes = _themes(name)
    grade = _grade(name, str(text or ""))
    if grade:
        # 写明的品级比名字里的「天」更准：尺度只说一次。
        themes = [line for line in themes if _kind(line) != _kind(grade)] + [grade]
    parts = [_form_of(name) or prompt_data.text(_WORDING, "fallback"), *themes]
    return "；".join(parts)


def technique_brief(scene_text: str) -> str:
    """本场点了名的术法各长什么样，给分镜师；没有点名的术法是空串。"""
    names = find_names(scene_text)[: prompt_data.number(_WORDING, "max_items")]
    if not names:
        return ""
    budget = prompt_data.number(_WORDING, "budget")
    lines = [prompt_data.text(_WORDING, "lead")]
    for name in names:
        line = prompt_data.text(_WORDING, "item").format(name, look(name, scene_text))
        if sum(len(item) + 1 for item in lines) + len(line) > budget:
            break
        lines.append(line)
    return "\n".join(lines) if len(lines) > 1 else ""


def power_system_applies(genre: str = "", text: str = "") -> bool:
    """修仙、武侠题材(或故事里写到灵根、筑基、江湖这类词)：编剧和总导演要带上力量体系底板。"""
    if str(genre or "").strip().lower() in prompt_data.words(_WORDING, "power_system_genres"):
        return True
    text = str(text or "")
    return any(word in text for word in prompt_data.words(_WORDING, "power_system_words"))


def world_applies(genre: str = "", text: str = "") -> bool:
    """修仙世界(不含武侠)：妖兽、称谓、宗门服饰、坊市这一页只给修仙题材。"""
    if str(genre or "").strip().lower() == "xianxia":
        return True
    text = str(text or "")
    return any(word in text for word in prompt_data.words(_WORDING, "world_words"))


__all__ = ["find_names", "look", "power_system_applies", "technique_brief", "world_applies"]

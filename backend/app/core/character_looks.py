# -*- coding: utf-8 -*-
"""表演妆造：剧本里的每套戏服和妆效，都提前出一张「这个人化好妆、穿好它」的定妆图。

服装和化妆不再是单独的资产。剧本拆解目录(``production_assets`` 的 ``costumes``、``makeup``)仍是清单，
这里按它给每个人登记衍生形象(见 ``character_variants``)：描述只留穿戴和妆效，什么时候(第几集、剧情名)
变成换装依据，分镜和视频按这个依据给角色换上对应的定妆图。写了集数的妆效和当时穿的那身合成一张。
认不出是谁的条目(禁军甲胄这类成片的)归到群演，画在群演参考图上。定不下时间的妆效不出图，镜头提到时
按文字画在当时那身上。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.core import prompt_data
from app.core.character_variants import LOOK_SOURCE, VariantError, clean_variant, episode_of, scene_of
from app.core.storyboard_scene_context import cast_aliases, costume_owner, mentioned

# 16:9 且不超过 Seedream 单张约 462 万像素的上限。
LOOK_BOARD_SIZE = "2848x1600"
# 出图、核对和改正的措辞在 app/data/prompt/character_looks.json。
_WORDING = "character_looks"


def _say(key: str) -> str:
    return prompt_data.text(_WORDING, key)


LOOK_BOARD_INSTRUCTION = _say("board_instruction_head") + _say("board_closeups_plain") + _say("board_instruction_tail")
# 有妆效时右边第三格改拍妆效所在的部位：手上的伤只在全身格里，小到看不清，也核对不出来。
LOOK_BOARD_INSTRUCTION_MAKEUP = _say("board_instruction_head") + _say("board_closeups_makeup") + _say("board_instruction_tail")
# 模型爱给伤口加戏：多画几道划痕、血色画得新鲜。有妆效时把字面要求说死。
LOOK_MAKEUP_RULE = _say("makeup_rule")
# 「右手」是人物自己的右手；模型常按画面左右画反，核对也是按人物自己的左右判的。
LOOK_SIDE_RULE = _say("side_rule")
LOOK_BOARD_CLOSING = _say("board_closing")
_NUMBER = r"[\d一二两三四五六七八九十百]{1,5}"
_RANGE = re.compile(rf"第\s*({_NUMBER})\s*(?:集)?\s*(?:[-–—~～至到]\s*第?\s*({_NUMBER})\s*)?集\s*(起|开始|之后|以后|至剧终|到剧终|至结局|到结局)?")
_SCENE_REF = re.compile(
    rf"(?P<from>从)?\s*(?:第\s*(?P<episode>{_NUMBER})\s*集\s*)?第\s*(?P<scene>{_NUMBER})\s*场\s*(?P<onward>起|开始|之后|以后)?"
    r"|E(?P<id_episode>\d+)S(?P<id_scene>\d+)"
)
_DIGITS = dict(zip("一二两三四五六七八九", (1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
# 变体的集数上限(见 schema ElementVariantRequest)：「第11集起」一直穿到剧终。
_OPEN_END = 500
#: 「第1集演武场受辱」这样讲剧情的分句，以及开头的「某某穿着」，都不是穿戴，不进定妆图。
_WEARER_LEAD = re.compile(r"^\s*(?P<name>[^；;，,：:。\s]{1,20}?)(?:穿着|身穿|所穿)\s*[；;，,：:]?\s*")


def _merged(spans: list[list[int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for first, last in sorted(spans):
        if merged and first <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], last)
        else:
            merged.append([first, last])
    return merged


def _episode_number(text: str) -> int:
    """「12」「十二」「二十三」「一百零五」→ 整数；认不出是 0。"""
    if text.isdigit():
        return int(text)
    total, current = 0, 0
    for char in text:
        if char == "百":
            total += (current or 1) * 100
            current = 0
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char in _DIGITS:
            current = _DIGITS[char]
        else:
            return 0
    return total + current


def episode_spans(text: str) -> list[list[int]]:
    """描述里写明的集数：「第1集…第2-8集…第11集起」→ [[1, 8], [11, 500]]。相邻和重叠的合并。"""
    spans: list[list[int]] = []
    for match in _RANGE.finditer(str(text or "")):
        first = _episode_number(match.group(1))
        last = _episode_number(match.group(2)) if match.group(2) else (_OPEN_END if match.group(3) else first)
        if first >= 1 and last >= first:
            spans.append([first, last])
    return _merged(spans)


def wardrobe_text(description: str, wearer: str = "") -> str:
    """只留穿戴和妆效：去掉开头的穿着者和讲第几集的分句，定妆图里不该出现剧情。"""
    text = str(description or "").strip()
    lead = _WEARER_LEAD.match(text)
    if lead and (not wearer or lead.group("name") == wearer):
        text = text[lead.end():]
    clauses = []
    for clause in re.split(r"[。；;]", text):
        kept = "，".join(
            fragment.strip() for fragment in re.split(r"[，,]", clause) if fragment.strip() and not _RANGE.search(fragment) and not _SCENE_REF.search(fragment)
        )
        if kept:
            clauses.append(kept)
    return "；".join(clauses)


def _wearer(entry: Mapping[str, Any], cast: Sequence[str], aliases: Mapping[str, str]) -> str:
    stated = str(entry.get("character") or "").strip()
    stated = aliases.get(stated, stated)
    if stated in cast:
        return stated
    item = {"name": str(entry.get("name") or ""), "description": str(entry.get("description") or "")}
    description = item["description"]
    for label, owner in [*((name, name) for name in cast), *aliases.items()]:
        if owner in cast and (costume_owner(item, label) or description.startswith((f"{label}穿着", f"{label}身穿"))):
            return owner
    return ""


def _label(name: str, wearer: str, aliases: Mapping[str, str]) -> str:
    """「沈无咎·染血残衣」的造型名是「染血残衣」；名字里没写人就是它自己。"""
    label = name
    for title in (wearer, *(title for title, owner in aliases.items() if owner == wearer)):
        label = label.replace(title, "")
    label = re.sub(r"[（(][^）)]*[）)]", "", label).strip(" ·•・-—:：")
    return label or name


def _catalog(task: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), Mapping) else {}
    catalog = breakdown.get("production_assets")
    return catalog if isinstance(catalog, Mapping) else {}


def _story_scenes(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    """分场大纲：``{episode, scene, text, people}``，读不出第几集的不要。"""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), Mapping) else {}
    scenes: list[dict[str, Any]] = []
    for raw in breakdown.get("scenes") or []:
        if not isinstance(raw, Mapping):
            continue
        episode, scene = episode_of(raw.get("scene_id")), scene_of(raw.get("scene_id"))
        if episode is None or scene is None:
            continue
        people = raw.get("characters")
        scenes.append({
            "episode": episode, "scene": scene,
            "text": " ".join(str(raw.get(key) or "") for key in ("label", "content", "description", "summary")),
            "people": {str(name).strip() for name in people} if isinstance(people, (list, tuple)) else set(),
        })
    return sorted(scenes, key=lambda item: (item["episode"], item["scene"]))


def _scene_timing(text: str, scenes: Sequence[Mapping[str, Any]]) -> tuple[list[list[int]], list[int] | None]:
    """描述里按场说的时间：「第2集第3场起」「E2S03」「从第3场开始」。没写集的「第3场」取全剧最早的那一场。"""
    match = _SCENE_REF.search(text)
    if not match:
        return [], None
    if match.group("id_episode"):
        episode, scene = int(match.group("id_episode")), int(match.group("id_scene"))
    else:
        scene = _episode_number(match.group("scene"))
        if match.group("episode"):
            episode = _episode_number(match.group("episode"))
        else:
            hit = next((item for item in scenes if item["scene"] == scene), None)
            if hit is None:
                return [], None
            episode = int(hit["episode"])
    if episode < 1 or scene < 1:
        return [], None
    is_open = bool(match.group("from") or match.group("onward"))
    return [[episode, _OPEN_END if is_open else episode]], [episode, scene]


def _mention_timing(name: str, wearer: str, aliases: Mapping[str, str], scenes: Sequence[Mapping[str, Any]]) -> tuple[list[list[int]], list[int] | None]:
    """剧本哪几场写到了它，并且这个人在场：从第一场到最后一场。"""
    titles = {wearer, *(title for title, owner in aliases.items() if owner == wearer)}
    hits = [
        item for item in scenes
        if mentioned({"name": name}, item["text"]) and (titles & item["people"] or any(title in item["text"] for title in titles))
    ]
    if not hits:
        return [], None
    return [[int(hits[0]["episode"]), int(hits[-1]["episode"])]], [int(hits[0]["episode"]), int(hits[0]["scene"])]


def _timing(entry: Mapping[str, Any], wearer: str, aliases: Mapping[str, str], scenes: Sequence[Mapping[str, Any]]) -> tuple[list[list[int]], list[int] | None]:
    """什么时候穿戴：描述写的集数 > 描述写的场 > 模型读剧本定的(``timing``) > 剧本提到它的那几场。"""
    for text in (str(entry.get("description") or ""), str(entry.get("timing") or "")):
        scene_spans, starts = _scene_timing(text, scenes)
        if scene_spans:
            return scene_spans, starts
        spans = episode_spans(text)
        if spans:
            return spans, None
    return _mention_timing(str(entry.get("name") or ""), wearer, aliases, scenes)


def _holds(piece: Mapping[str, Any], episode: int) -> int | None:
    """这件在这一集穿着/带着时返回所在区间的宽度，不在就是 None。"""
    widths = [last - first for first, last in piece["spans"] if first <= episode <= last]
    return min(widths) if widths else None


def _look(
    wearer: str, outfit: Mapping[str, Any] | None, makeups: list[Mapping[str, Any]], spans: list[list[int]], starts: list[int] | None = None,
) -> dict[str, Any] | None:
    pieces = [*([outfit] if outfit else []), *makeups]
    name = "·".join([pieces[0]["name"], *(piece["label"] for piece in pieces[1:])])
    label = "·".join(piece["label"] for piece in pieces)
    worn = "；".join(piece["text"] for piece in makeups)
    description = "；".join(part for part in (outfit["text"] if outfit else "", f"妆效：{worn}" if makeups else "") if part)
    triggers = list(dict.fromkeys(word for piece in pieces for word in (piece["name"], piece["label"])))
    try:
        facts = clean_variant(
            {
                "of": wearer, "label": label, "triggers": triggers, "spans": _merged(spans), "source": LOOK_SOURCE,
                "outfit": outfit["name"] if outfit else "", "makeups": [piece["name"] for piece in makeups], "starts": starts,
            },
            element_name=name,
        )
    except VariantError:
        return None
    return {"name": name, "of": wearer, "label": label, "description": description, "facts": facts}


def _wearer_looks(wearer: str, outfits: list[dict[str, Any]], makeups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """这个人要出的定妆图。妆效按时间线和当时穿的那身合成一张，受伤之前的戏不带伤。"""
    # 「第9集起」只算到戏服写到的最后一集：再往后没有戏可穿，不为它多付一次出图。
    horizon = max((last for piece in outfits for _first, last in piece["spans"]), default=0)
    timed = [
        {**piece, "spans": [[first, horizon if last >= _OPEN_END and first <= horizon else last] for first, last in piece["spans"]]}
        for piece in makeups if piece["spans"]
    ]
    plain_spans = {piece["name"]: piece["spans"] for piece in outfits}
    combined: dict[tuple[str, tuple[str, ...]], list[list[int]]] = {}
    combined_starts: dict[tuple[str, tuple[str, ...]], list[int]] = {}
    if timed:
        untimed_outfits = [piece for piece in outfits if not piece["spans"]]
        default = untimed_outfits[0] if len(untimed_outfits) == 1 else None
        marks = sorted({edge for piece in [*outfits, *timed] for first, last in piece["spans"] for edge in (first, last + 1)})
        plain_spans = {piece["name"]: [] for piece in outfits}
        for first, after in zip(marks, marks[1:]):
            covering = [(piece, _holds(piece, first)) for piece in outfits]
            covering = [pair for pair in covering if pair[1] is not None]
            outfit = min(covering, key=lambda pair: pair[1])[0] if covering else default
            active = [piece for piece in timed if _holds(piece, first) is not None]
            if active:
                key = (outfit["name"] if outfit else "", tuple(piece["name"] for piece in active))
                combined.setdefault(key, []).append([first, after - 1])
                begun = [piece["starts"] for piece in active if piece.get("starts") and piece["starts"][0] == first]
                if begun:
                    combined_starts.setdefault(key, max(begun))
                    # 这一集前半场还没受伤，那身不带伤的这一集也要穿。
                    if outfit and outfit["spans"]:
                        plain_spans[outfit["name"]].append([first, first])
            elif outfit and outfit["spans"]:
                plain_spans[outfit["name"]].append([first, after - 1])
    by_name = {piece["name"]: piece for piece in [*outfits, *timed]}
    looks = [
        _look(wearer, piece, [], plain_spans[piece["name"]], piece.get("starts")) for piece in outfits
        # 写了集数、但每一集都带着妆效的那身，单独画没人穿。
        if not piece["spans"] or plain_spans[piece["name"]]
    ]
    looks += [
        _look(wearer, by_name.get(outfit), [by_name[name] for name in active], spans, combined_starts.get((outfit, active)))
        for (outfit, active), spans in combined.items()
    ]
    return [look for look in looks if look]


def _appearances(cast: Sequence[str], aliases: Mapping[str, str], scenes: Sequence[Mapping[str, Any]]) -> dict[str, set[int]]:
    """每个人实际出场的集。"""
    seen: dict[str, set[int]] = {name: set() for name in cast}
    for scene in scenes:
        for name in cast:
            titles = {name, *(title for title, owner in aliases.items() if owner == name)}
            if titles & scene["people"] or any(title in scene["text"] for title in titles):
                seen[name].add(int(scene["episode"]))
    return seen


def _cast_of(task: Mapping[str, Any]) -> list[str]:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    return [
        str(item.get("name") or "").strip() for item in assets.get("3_characters") or []
        if isinstance(item, Mapping) and str(item.get("name") or "").strip()
    ]


def _pieces(task: Mapping[str, Any], cast: Sequence[str]) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], list[Mapping[str, Any]]]:
    """(每个人的戏服和妆效, 认不出是谁的条目)。"""
    catalog, aliases, scenes = _catalog(task), cast_aliases(dict(task)), _story_scenes(task)
    pieces: dict[str, dict[str, list[dict[str, Any]]]] = {}
    unowned: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for key in ("costumes", "makeup"):
        for entry in catalog.get(key) or []:
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            wearer = _wearer(entry, cast, aliases)
            if not wearer:
                unowned.append({**entry, "_catalog": key})
            elif name != wearer:
                spans, starts = _timing(entry, wearer, aliases, scenes)
                pieces.setdefault(wearer, {"costumes": [], "makeup": []})[key].append({
                    "name": name, "label": _label(name, wearer, aliases), "spans": spans, "starts": starts,
                    "text": wardrobe_text(str(entry.get("description") or ""), wearer) or _label(name, wearer, aliases),
                })
    return pieces, unowned


def plan_looks(task: Mapping[str, Any], *, cast: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """本剧要出的每一张定妆图：``{name, of, label, description, facts}``，按角色，顺序同拆解目录。

    分场大纲写了谁在哪集出场时，只留用得上的：这个人一场都没有的那几集，不为它出图。``cast`` 默认是第 3 步的角色。
    """
    names = list(cast) if cast is not None else _cast_of(task)
    pieces, _unowned = _pieces(task, names)
    scenes = _story_scenes(task)
    seen = _appearances(names, cast_aliases(dict(task)), scenes) if scenes else None
    looks: list[dict[str, Any]] = []
    for wearer, worn in pieces.items():
        for look in _wearer_looks(wearer, worn["costumes"], worn["makeup"]):
            spans = look["facts"].get("spans") or []
            if seen is None or (seen[wearer] and not spans) or any(first <= episode <= last for first, last in spans for episode in seen[wearer]):
                looks.append(look)
    return looks


def untimed_makeup(task: Mapping[str, Any], *, cast: Sequence[str] | None = None) -> list[dict[str, str]]:
    """定不下时间的妆效：不出图，也不等它定下来。``{of, name, label, text}``，镜头提到时按文字画在当时那身上。"""
    names = list(cast) if cast is not None else _cast_of(task)
    pieces, _unowned = _pieces(task, names)
    return [
        {"of": wearer, "name": piece["name"], "label": piece["label"], "text": piece["text"]}
        for wearer, worn in pieces.items() for piece in worn["makeup"] if not piece["spans"]
    ]


def timing_is_readable(text: str) -> bool:
    """人填的时间读得出来吗：第9集起、第9-12集、第2集第3场起、E2S03。没写集的「第3场」要靠分场大纲，这里也算。"""
    return bool(episode_spans(text) or _SCENE_REF.search(text))


def undated(task: Mapping[str, Any]) -> list[str]:
    """值得问模型的条目：定不下时间的妆效，和同一个人好几身都定不下时间的戏服。只有一身的那身就是默认，不用问。"""
    pieces, _unowned = _pieces(task, _cast_of(task))
    names: list[str] = []
    for worn in pieces.values():
        names += [piece["name"] for piece in worn["makeup"] if not piece["spans"]]
        loose = [piece["name"] for piece in worn["costumes"] if not piece["spans"]]
        if len(loose) > 1:
            names += loose
    return names


def _crowd_name(name: str, script: str) -> str:
    """「溃兵血污」「禁军甲胄」穿在谁身上：名字开头在剧本里出现过的最短一段(溃兵、禁军)，「王二·囚衣」就是王二。"""
    if "·" in name:
        return name.split("·", 1)[0].strip() or name
    for end in range(2, len(name)):
        if name[:end] in script:
            return name[:end]
    return name


def crowd_wardrobe(task: Mapping[str, Any], *, cast: Sequence[str] | None = None) -> list[dict[str, str]]:
    """认不出是谁的戏服和妆效归到群演：写进已有的同名群演，没有就按人群登记一条，让群演参考图把它画出来。"""
    names = list(cast) if cast is not None else _cast_of(task)
    if not names:
        return []
    _pieces_by_wearer, unowned = _pieces(task, names)
    if not unowned:
        return []
    catalog = _catalog(task)
    listed = {
        str(item.get("name") or "").strip(): str(item.get("description") or "")
        for item in catalog.get("extras") or [] if isinstance(item, Mapping) and str(item.get("name") or "").strip()
    }
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    script = str(assets.get("2") or "")
    crowds: dict[str, list[str]] = {}
    for entry in unowned:
        name = str(entry.get("name") or "").strip()
        crowd = next((known for known in listed if known in name or name in known), "") or _crowd_name(name, script)
        text = wardrobe_text(str(entry.get("description") or "")) or name
        crowds.setdefault(crowd, []).append(f"妆效：{text}" if entry["_catalog"] == "makeup" else f"服装：{text}")
    return [
        {"name": crowd, "description": "；".join(part for part in (listed.get(crowd, ""), *parts) if part), "parts": parts}
        for crowd, parts in crowds.items()
    ]


# 画完再看一眼：模型常把伤口画错数量、画到另一侧，或在某一格漏掉。不合格的照问题重画一次。
LOOK_CHECK_SYSTEM = _say("check_system")


def wears_makeup(wardrobe: str) -> bool:
    """这身妆造写了妆效：出图要守妆效规则，画完要核对。"""
    return "妆效：" in wardrobe


def names_a_side(wardrobe: str) -> bool:
    """文字写了左或右：出图时说清是人物自己的左右。"""
    return any(word in wardrobe for word in prompt_data.words(_WORDING, "side_words"))


def look_check_prompt(wardrobe: str) -> str:
    """让看图模型核对妆效的提示词；答案用 ``parse_look_check`` 读。"""
    return f"{_say('check_wardrobe_label')}{wardrobe.strip()}\n{_say('check_steps')}{_say('check_output')}"


def parse_look_check(answer: str | None) -> dict[str, Any] | None:
    """``{passed, problems}``；读不出结论时返回 None，当作没检查过。"""
    match = re.search(r"\{.*\}", str(answer or ""), re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("passed"), bool):
        return None
    # 每条自己带的句末标点去掉，拼起来才不会出现「。；」。
    problems = [str(item).strip().rstrip("。；;.，, ")[:120] for item in data.get("problems") or []]
    problems = [item for item in problems if item][:6]
    passed = data["passed"] and not problems
    return {"passed": passed, "problems": [] if passed else problems or [_say("check_unclear_problem")]}


def look_fix_prompt(problems: list[str], wardrobe: str = "") -> str:
    """重画时补在提示词后面的改正要求；``wardrobe`` 写了左右时，再提醒一次左右的算法。"""
    fix = _say("fix_lead") + "；".join(problems)
    return f"{fix}\n{_say('fix_side_reminder')}" if names_a_side(wardrobe) else fix


def look_prompt(name: str, wardrobe: str, project_style: str = "", extra_prompt: str = "", *, earlier_designs: int = 0) -> str:
    """一张定妆图的提示词；描述已是只留穿戴的文字。``earlier_designs`` 是身份参考之后另附的旧服装图、旧妆效图张数。"""
    makeup = wears_makeup(wardrobe)
    prompt = (
        f"{LOOK_BOARD_INSTRUCTION_MAKEUP if makeup else LOOK_BOARD_INSTRUCTION}\n"
        f"{_say('look_name_label')}{name.strip()}\n{_say('wardrobe_label')}{wardrobe.strip() or name.strip()}\n"
    )
    if makeup:
        prompt += LOOK_MAKEUP_RULE
    if names_a_side(wardrobe):
        prompt += LOOK_SIDE_RULE
    if earlier_designs:
        prompt += _say("earlier_designs_note")
    if project_style:
        prompt += f"{_say('project_style_label')}{project_style}\n"
    if extra_prompt.strip():
        prompt += f"{_say('extra_prompt_label')}{extra_prompt.strip()}\n"
    return prompt + LOOK_BOARD_CLOSING


__all__ = [
    "LOOK_BOARD_CLOSING", "LOOK_BOARD_INSTRUCTION", "LOOK_BOARD_INSTRUCTION_MAKEUP", "LOOK_BOARD_SIZE", "LOOK_CHECK_SYSTEM", "LOOK_MAKEUP_RULE",
    "LOOK_SIDE_RULE", "crowd_wardrobe", "episode_spans", "look_check_prompt", "look_fix_prompt", "look_prompt", "names_a_side",
    "parse_look_check", "plan_looks", "timing_is_readable", "undated", "untimed_makeup", "wardrobe_text", "wears_makeup",
]

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

from app.core.character_variants import LOOK_SOURCE, VariantError, clean_variant, episode_of, scene_of
from app.core.storyboard_scene_context import cast_aliases, costume_owner, mentioned

# 16:9 且不超过 Seedream 单张约 462 万像素的上限。
LOOK_BOARD_SIZE = "2848x1600"
LOOK_BOARD_INSTRUCTION = (
    "生成一张影视角色定妆照展示板：16:9 横向画布，浅灰到中灰的影棚无缝背景，同一中性柔光。"
    "严格参考所给参考图里的同一个人：脸型、五官比例、痣与疤的位置、肤色和体型完全一致，只按下面这身妆造换装，"
    "发型、头饰、妆面和伤口血迹按它的写法画在写明的位置，没写的保持参考图原样；服装呈现真实穿着体积、肩线与自然垂坠，人物端正站立；围巾、面巾、披风等搭在颈肩的东西不挡住领口的形制。"
    "画面左侧约四分之三宽度横排四格全身视图，格与格之间一条纯白细缝，依次为正面、左侧90度侧面、背面、"
    "右前方45度三分之四侧面；四格同一比例尺，脚底在同一条基线上，头顶到双脚完整入画，表情平静。"
    "画面右侧约四分之一宽度竖排三格特写：正脸胸像(看得清五官、领口与发型)、腰带系结与配饰、袖口或下摆的面料纹理与磨损。"
    "完整呈现领口、上装、下装、袖口、下摆、鞋履、材质、纹样、配饰、妆效及剧情状态。"
)
# 模型爱给伤口加戏：多画几道划痕、血色画得新鲜。有妆效时把字面要求说死。
LOOK_MAKEUP_RULE = (
    "妆效严格照字面：写几道伤就只画几道，长度、走向和位置照写；不加文字没写的划痕、爪痕、擦伤或飞溅血点；"
    "写了半干、结痂或旧伤，血色画成暗红到褐色，不画鲜红的湿血。"
    "伤在哪一侧，每个看得到那一侧脸或身体的视图和特写都要画上，各格里形状、长度、血量和颜色完全一样，不在某一格加重或省掉。\n"
)
LOOK_BOARD_CLOSING = (
    "统一要求：四个视图和三格特写是同一个人、同一套服装、同一配色与磨损状态，人物完整位于各自格内安全区，"
    "高清写实影棚摄影质感；严禁任何文字、标签、编号、字幕、水印、Logo；不出现其他人物、道具陈列和剧情场景，不用人台或假人。"
)

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
LOOK_CHECK_SYSTEM = (
    "你是影视剧组的化妆指导，核对一张角色定妆照展示板上的妆效是否和文字一致。"
    "展示板左边四格全身：正面、左侧面、背面、右前方三分之四侧面；右边三格特写：正脸胸像、腰带、袖口或下摆。"
    "左右一律指人物自己的左右：正面和正脸特写里，人物的左脸在画面右侧。"
    "只看妆效，不评价服装、构图和画风。"
)


def wears_makeup(wardrobe: str) -> bool:
    """这身妆造写了妆效：出图要守妆效规则，画完要核对。"""
    return "妆效：" in wardrobe


def look_check_prompt(wardrobe: str) -> str:
    """让看图模型核对妆效的提示词；答案用 ``parse_look_check`` 读。"""
    return (
        f"这身妆造的文字：{wardrobe.strip()}\n"
        "逐格核对：1. 伤口或妆效的数量、长度、走向和位置是否和文字一致；"
        "2. 是否只在写明的一侧，另一侧和其他部位干净；"
        "3. 每个看得到那一侧的格子是否都画了，各格形状、血量和颜色是否一致；"
        "4. 文字写了半干、结痂或旧伤时，血色是否是暗红到褐色。\n"
        '只输出一行 JSON：{"passed": true 或 false, "problems": ["哪一格、哪里不对，一句话一条"]}。都对时 problems 为空。'
    )


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
    problems = [str(item).strip()[:120] for item in data.get("problems") or [] if str(item).strip()][:6]
    passed = data["passed"] and not problems
    return {"passed": passed, "problems": [] if passed else problems or ["妆效和文字对不上"]}


def look_fix_prompt(problems: list[str]) -> str:
    """重画时补在提示词后面的改正要求。"""
    return "上一张的妆效有这些问题，这次务必改正：" + "；".join(problems)


def look_prompt(name: str, wardrobe: str, project_style: str = "", extra_prompt: str = "", *, earlier_designs: int = 0) -> str:
    """一张定妆图的提示词；描述已是只留穿戴的文字。``earlier_designs`` 是身份参考之后另附的旧服装图、旧妆效图张数。"""
    prompt = f"{LOOK_BOARD_INSTRUCTION}\n造型名称：{name.strip()}\n这身妆造：{wardrobe.strip() or name.strip()}\n"
    if wears_makeup(wardrobe):
        prompt += LOOK_MAKEUP_RULE
    if earlier_designs:
        prompt += "第1张参考图是这个人；后面的参考图是已确认的服装或妆效设计，只取款式、颜色、材质和伤口的位置形态，不取其中的人台和人脸。\n"
    if project_style:
        prompt += f"项目视觉基准：{project_style}\n"
    if extra_prompt.strip():
        prompt += f"本次补充要求：{extra_prompt.strip()}\n"
    return prompt + LOOK_BOARD_CLOSING


__all__ = [
    "LOOK_BOARD_CLOSING", "LOOK_BOARD_INSTRUCTION", "LOOK_BOARD_SIZE", "LOOK_CHECK_SYSTEM", "LOOK_MAKEUP_RULE", "crowd_wardrobe", "episode_spans",
    "look_check_prompt", "look_fix_prompt", "look_prompt", "parse_look_check", "plan_looks", "timing_is_readable", "undated",
    "untimed_makeup", "wardrobe_text", "wears_makeup",
]

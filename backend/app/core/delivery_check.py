# -*- coding: utf-8 -*-
"""成片交付前验收：合成前把要进成片的镜头过一遍，列出哪一镜有问题，不拦合成。

只做能机器判定的几条，都按剪辑台上真正要用的那一段算(修剪后的入出点)：

* 镜头太短，观众看不清；
* 台词按情绪语速连同留白放不下(字幕读不完、台词被切)；
* 连着几镜同一景别；整条成片景别不到三档；
* 同一场戏里主光换了边、色温冷暖跳了(没有开灯、天黑这类变化)；
* 相邻两镜道具凭空换手变样、人物姿态无因跳变(镜间衔接账本 :mod:`app.core.shot_ledger`)；
* 正反打的两个单人镜头里，两人都看向画面同一侧；
* 原片自带开口说话的口型，却换成了配音(嘴型可能对不上)。

每条问题标上它属于哪一层(内容、连续性、表演、阅读、技术、包装、授权)、哪一档(必须修复 / 建议优化 /
需人工确认)；:func:`report` 再把机器没查的层列成「未验证」，不让一张空清单看起来像全部通过。

措辞和阈值在 data/prompt/delivery_check.json。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.core import edit_timeline, prompt_data, shot_ledger
from app.core.shot_table_rules import dialogue_seconds

_DATA = "delivery_check"


def _say(key: str, **values: Any) -> str:
    return prompt_data.value(_DATA, "messages")[key].format(**values)


def opening_size(size: Any) -> str:
    """一镜的起幅景别：「中景起幅→近景落幅」读作中景；认不出时是空串。"""
    text = str(size or "")
    found = [(text.find(word), word) for word in prompt_data.words(_DATA, "sizes") if word in text]
    if not found:
        return ""
    first = min(position for position, _word in found)
    # 同一位置上长的词优先(中近景先于近景)。
    return max((word for position, word in found if position == first), key=len)


def light_side(*texts: Any) -> str:
    """主光从画面哪一侧来(左 / 右)；文字里没写就是空串。"""
    pattern = re.compile(prompt_data.text(_DATA, "light_side"))
    for text in texts:
        match = pattern.search(str(text or ""))
        if match:
            return match.group(1)
    return ""


def gaze_side(*texts: Any) -> str:
    """人物看向画面哪一侧(左 / 右)；没写就是空串。"""
    pattern = re.compile(prompt_data.text(_DATA, "gaze_side"))
    for text in texts:
        match = pattern.search(str(text or ""))
        if match:
            return match.group(1)
    return ""


def tone(*texts: Any) -> str:
    """画面色调冷暖(warm / cool)：先看写明的色温 K 值，再看冷暖词；两样都有或都没有时是空串。"""
    text = " ".join(str(item or "") for item in texts)
    kelvin = re.search(prompt_data.text(_DATA, "kelvin"), text)
    if kelvin:
        value = int(kelvin.group(1))
        if value < float(prompt_data.value(_DATA, "kelvin_warm_below")):
            return "warm"
        if value > float(prompt_data.value(_DATA, "kelvin_cool_above")):
            return "cool"
    warm = any(word in text for word in prompt_data.words(_DATA, "warm_words"))
    cool = any(word in text for word in prompt_data.words(_DATA, "cool_words"))
    return "warm" if warm and not cool else "cool" if cool and not warm else ""


def _cast(task: Mapping[str, Any]) -> list[str]:
    """项目里有名有姓的角色(第 3 阶段的角色卡和角色 DNA)。"""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    dna = assets.get("3_dna") if isinstance(assets.get("3_dna"), Mapping) else {}
    rows = [*(assets.get("3_characters") or []), *(dna.get("characters") or [])]
    return list(dict.fromkeys(str(row.get("name") or "").strip() for row in rows if isinstance(row, Mapping) and str(row.get("name") or "").strip()))


def _shot_facts(task: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    """全剧镜头编号 → 这一镜的景别、表情、光向(取第 4 阶段分镜和第 5 阶段片段里写的)。"""
    from app.core import episode_cycle

    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    boards = {
        (str(shot.get("scene_id") or ""), str(shot.get("shot_id"))): shot
        for shot in assets.get("4") or [] if isinstance(shot, Mapping)
    }
    facts: dict[int, dict[str, Any]] = {}
    for clip in assets.get("5") or []:
        if not isinstance(clip, Mapping):
            continue
        board = boards.get((str(clip.get("scene_id") or ""), str(clip.get("shot_id")))) or {}
        contract = board.get("motion_contract") if isinstance(board.get("motion_contract"), Mapping) else {}
        light_text = (board.get("lighting"), contract.get("lighting"), board.get("storyboard_prompt"), board.get("desc"))
        facts[episode_cycle.shot_uid(clip)] = {
            "board": board or clip,
            "people": [str(name) for name in (board.get("characters") or contract.get("characters") or []) if str(name).strip()],
            "gaze": gaze_side(contract.get("eyeline"), board.get("eyeline"), board.get("desc")),
            "tone": tone(*light_text),
            "light_change": bool(re.search(prompt_data.text(_DATA, "light_change"), str(board.get("desc") or ""))),
            "size": opening_size(clip.get("size") or board.get("size")),
            "expression": str(board.get("expression") or ""),
            # 原始台词按说话人分行、带括注(「（哽咽）」)，逐句按情绪算；没有时用字幕。
            "dialogue": str(clip.get("dialogue") or board.get("dialogue") or ""),
            "light": light_side(board.get("storyboard_prompt"), board.get("desc"), clip.get("motion_prompt")),
        }
    return facts


def check(task: Mapping[str, Any], timeline: Mapping[str, Any], *, plans: Any = None) -> list[dict[str, Any]]:
    """剪辑台上要进成片的镜头逐条验收；每条问题写明是哪一镜、哪一条、为什么。

    ``plans(scene_id)`` 给场次的空间方案：镜间衔接账本先读方案里的接触，和提示词用的是同一本账。
    """
    clips = edit_timeline._cut_clips(timeline)
    facts = _shot_facts(task)
    issues: list[dict[str, Any]] = []

    def flag(clip: Mapping[str, Any], rule: str, detail: str) -> None:
        issues.append({
            "shot_uid": clip.get("shot_uid"), "scene_id": str(clip.get("scene_id") or ""), "shot_id": clip.get("shot_id"),
            "rule": rule, "detail": detail, **_grade(rule),
        })

    minimum = float(prompt_data.value(_DATA, "min_shot_seconds"))
    slack = float(prompt_data.value(_DATA, "dialogue_slack_seconds"))
    run_limit = int(prompt_data.value(_DATA, "max_same_size_run"))
    groups = prompt_data.value(_DATA, "size_groups")
    run_size, run_count = "", 0
    last_light: dict[str, str] = {}
    last_tone: dict[str, str] = {}
    # 镜间衔接账本按剪辑台上的顺序记：剪掉的镜头不算，挪了位置的按新位置接。
    ordered = [(facts.get(int(clip.get("shot_uid") or 0)) or {}) for clip in clips]
    ledger = shot_ledger.walk([{**fact.get("board", {}), "scene_id": str(clip.get("scene_id") or "")} for fact, clip in zip(ordered, clips)], _cast(task), plans=plans)
    previous_clip: Mapping[str, Any] | None = None
    sizes_used: list[str] = []
    for clip in clips:
        fact = facts.get(int(clip.get("shot_uid") or 0)) or {}
        seconds = round(edit_timeline.clip_seconds(clip), 1)
        if seconds and seconds < minimum:
            flag(clip, "too_short", _say("too_short", seconds=seconds))
        spoken = fact.get("dialogue") or str(clip.get("subtitle") or "")
        need = dialogue_seconds(spoken, fact.get("expression") or "") if clip.get("subtitle") else 0.0
        if need and seconds and need > seconds + slack:
            flag(clip, "dialogue", _say("dialogue", need=round(need, 1), seconds=seconds))
        size = fact.get("size") or ""
        if size:
            sizes_used.append(size)
            group = groups.get(size, size)
            run_count = run_count + 1 if group == run_size else 1
            run_size = group
            if run_count == run_limit + 1:
                flag(clip, "same_size", _say("same_size", count=run_count, size=size))
        side, scene = fact.get("light") or "", str(clip.get("scene_id") or "")
        if side:
            before = last_light.get(scene)
            if before and before != side:
                flag(clip, "light_flip", _say("light_flip", before=before, after=side))
            last_light[scene] = side
        shade = fact.get("tone") or ""
        if shade:
            before = last_tone.get(scene)
            if before and before != shade and not fact.get("light_change"):
                names = prompt_data.value(_DATA, "tone_names")
                flag(clip, "tone_flip", _say("tone_flip", before=names[before], after=names[shade]))
            last_tone[scene] = shade
        entry = ledger.get(shot_ledger.key(scene, (fact.get("board") or {}).get("shot_id")))
        for problem in (entry.issues if entry is not None else []):
            flag(clip, problem["rule"], _say(problem["rule"], detail=problem["detail"]))
        if previous_clip is not None and str(previous_clip.get("scene_id") or "") == scene:
            before_fact = facts.get(int(previous_clip.get("shot_uid") or 0)) or {}
            first, second = before_fact.get("people") or [], fact.get("people") or []
            # 正反打：两个单人镜头，一人一镜；两人都看向画面同一侧就没对上。
            if len(first) == 1 and len(second) == 1 and first != second and before_fact.get("gaze") and before_fact.get("gaze") == fact.get("gaze"):
                flag(clip, "gaze_mismatch", _say("gaze_mismatch", first=first[0], second=second[0], side=fact["gaze"]))
        # 原片自带开口说话的口型，却换成了配音：嘴型、镜头长度可能和配音对不上。
        if edit_timeline.audio_source(clip) == "tts" and clip.get("native_available") and str(clip.get("subtitle") or "").strip():
            flag(clip, "dub_over_face", _say("dub_over_face"))
        previous_clip = clip
    distinct = list(dict.fromkeys(groups.get(size, size) for size in sizes_used))
    if clips and sizes_used and len(distinct) < int(prompt_data.value(_DATA, "min_sizes_in_cut")):
        issues.append({"shot_uid": None, "scene_id": "", "shot_id": None, "rule": "few_sizes",
                       "detail": _say("few_sizes", sizes="、".join(dict.fromkeys(sizes_used))), **_grade("few_sizes")})
    return issues


def _grade(rule: str) -> dict[str, str]:
    """一条规则属于哪一层、哪一档：{layer, tier, tier_label}。"""
    layer, tier = prompt_data.value(_DATA, "rule_layers").get(rule, ("", "manual"))
    return {"layer": layer, "tier": tier, "tier_label": prompt_data.value(_DATA, "tiers")[tier]}


def report(task: Mapping[str, Any], timeline: Mapping[str, Any], *, plans: Any = None) -> list[dict[str, Any]]:
    """验收单：逐镜的问题(按层的顺序、同层里必须修复在前)，再加机器没查的层(「未验证」，需人工确认)，
    最后一行是可用镜头单价(:mod:`app.core.unit_cost`)。"""
    layers = list(prompt_data.value(_DATA, "layers"))
    order = list(prompt_data.value(_DATA, "tiers"))
    issues = sorted(
        check(task, timeline, plans=plans),
        key=lambda issue: (layers.index(issue["layer"]) if issue.get("layer") in layers else len(layers), order.index(issue["tier"])),
    )
    # 授权层：成片里每样素材的来源记录(rights_ledger)；说不清使用范围的列出来要人记下授权说明。查过了就不再算「未验证」。
    from app.core import rights_ledger

    rights = [
        {"shot_uid": None, "scene_id": "", "shot_id": None, "rule": "rights", "detail": item["detail"], "rights_key": item["key"], **_grade("rights")}
        for item in rights_ledger.items(task, timeline) if item["status"] == "confirm"
    ]
    issues = [*issues, *rights]
    unverified = [
        {"shot_uid": None, "scene_id": "", "shot_id": None, "rule": "unverified", "detail": detail,
         "layer": layer, "tier": "manual", "tier_label": prompt_data.value(_DATA, "tiers")["manual"]}
        for layer, detail in prompt_data.value(_DATA, "unverified") if layer != "授权"
    ]
    # 可用镜头单价：不是问题，是这一轮的账，放在最后一行。
    from app.core import unit_cost

    cost = unit_cost.summary(task)
    money = {"shot_uid": None, "scene_id": "", "shot_id": None, "rule": "unit_cost", "detail": cost["line"],
             "layer": "", "tier": "info", "tier_label": "", "per_usable": cost["per_usable"], "usable": cost["usable"]}
    return [*issues, *unverified, money]


def counts(issues: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {rule: sum(1 for issue in issues if issue.get("rule") == rule) for rule in dict.fromkeys(issue.get("rule") for issue in issues)}


__all__ = ["check", "counts", "gaze_side", "light_side", "opening_size", "report", "tone"]

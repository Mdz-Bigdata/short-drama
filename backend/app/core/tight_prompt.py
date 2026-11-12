# -*- coding: utf-8 -*-
"""整条提示词硬上限紧的视频模型(Seedance 2.0：含负面词 2000 字)，发出前把提示词去重、合并约束。

为什么在这里而不是裁正文：第 5 阶段一条 Seedance 2.0 提示词实测 6000–7700 字，分镜与运镜正文只占约 2000，
其余是每条重申的固定层——同一个人的名字每次都带「（参考图N）」、锚型定义 / 人物锚点 / 服装绑定 / 参考素材职责 /
人物外貌把参考图已经给出的外貌和服装说了四五遍、站位在空间锚与导演台里各写一遍、【关键约束】里十几条铁律和负面清单。
用户的规矩是分镜与运镜内容一个字都不删(prompt_budget.fit_hard_limit 超了也原样发)，所以这里只去重：

1. 名字只在开头一行参考图绑定里带一次参考图号，外貌、服装、场景交给参考图；没有参考图的人照留外貌文字。
2. 同一件事写了几遍的锚点、站位行只留一遍(有导演台的「空间：」就不再写「[空间锚]」…)。
3. 【关键约束】里的各条铁律、跨镜连贯常量、负面清单合成一行精简约束。

只对 hard_limit 不超过 ``max_limit`` 的模型、且这条提示词加上网关要追加的负面词会超上限时才动；不超就一字不改。
人工改过的提示词不进这里(调用方判断)。去重后仍超就照原样发，回执里带 ``over_note``。
剪法全在 ``app/data/prompt/tight_prompt.json``，这里只有逻辑。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.core import prompt_budget, prompt_data

_DATA = "tight_prompt"


@dataclass
class Fit:
    """一次去重的回执：前后长度、上限、做了哪几步、去重后是否仍超。"""

    model: str
    limit: int | None
    before: int
    after: int
    steps: list[str] = field(default_factory=list)
    over: bool = False
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"model": self.model, "limit": self.limit, "before": self.before, "after": self.after,
                "steps": list(self.steps), "over": self.over, "note": self.note}


@lru_cache(maxsize=1)
def _rules() -> dict[str, Any]:
    data = prompt_data.load(_DATA)
    anchor = prompt_data.load("clip_skeleton")["anchor_types"]
    return {
        **data,
        "mention_re": re.compile(data["mention"]),
        "anchor_re": re.compile(data["anchor_row"]),
        "costume_re": re.compile(data["costume"]),
        "drop_res": [re.compile(item) for item in data["drop_lines"]],
        "drop_when_res": [(re.compile(line), re.compile(needs)) for line, needs in data["drop_when"]],
        "keep_mentions_res": [re.compile(item) for item in data["keep_mentions_in"]],
        "inline_res": [re.compile(item) for item in data["inline_drop"]],
        "constraint_res": [re.compile(item) for item in data["constraint_lines"]],
        "term_res": [re.compile(item) for item in data["term_lines"]],
        # 锚型 → 它给什么(clip_skeleton 的锚型定义表)，绑定行照它写。
        "gives": {kind: gives for kind, gives in anchor["definitions"]},
    }


@lru_cache(maxsize=1)
def _generic_terms() -> frozenset[str]:
    """每条都带的通用负面词：连续性负面词和各内置画风包的基础负面词(不含场景专属、本片自定义的)。"""
    from app.core import style_packs

    terms = set(prompt_data.words("iron_rules", "continuity_negatives"))
    for pack in style_packs.list_packs():
        terms.update(pack.negatives)
    return frozenset(str(term).strip() for term in terms)


def tight_limit(model: str) -> int | None:
    """这个模型的整条硬上限，只在它算「紧」(不超过 max_limit)时给出。"""
    limit = prompt_budget.hard_limit(model)
    return limit if limit is not None and limit <= int(_rules()["max_limit"]) else None


def _token(name: str, n: str) -> str:
    return prompt_data.text("asset_mentions", "replace.text").format(name, n)


def _bindings(lines: list[str]) -> dict[str, dict[str, str]]:
    """名字 → {n, kind, costume}，按首次出现的顺序。

    正文里「名字（参考图N）」前面常连着别的字(「看向画内的谢九（参考图4）」)，名字取同一个号各处写法的共同结尾。
    锚型(身份服装锚 / 场景锚…)和服装名从紧跟在这个名字后面的写法认。
    """
    rules = _rules()
    seen: dict[str, list[str]] = {}
    for line in lines:
        for match in rules["mention_re"].finditer(line):
            seen.setdefault(match.group("n"), []).append(match.group("name"))
    found: dict[str, dict[str, str]] = {}
    for n, names in seen.items():
        name = os.path.commonprefix([item[::-1] for item in names])[::-1]
        if name:
            found[name] = {"n": n, "kind": "", "costume": ""}
    for name, item in found.items():
        token = _token(name, item["n"])
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(token) and (row := rules["anchor_re"].match(stripped[len(token):])):
                item["kind"] = row.group("kind")
            for piece in line.split(token)[1:]:
                if not item["costume"] and (match := rules["costume_re"].match(piece)):
                    item["costume"] = match.group("costume").strip()
    return found


def _desk_marker() -> str:
    """场景图让位给导演台白模时，它的职责句里带的固定短语(scene_views.json；没有这个键时不生效)。"""
    return str(prompt_data.load("scene_views").get("desk_demoted_marker") or "")


def _demoted(lines: list[str]) -> set[str]:
    """职责句里写明「站位与家具位置以导演台白模为准」的参考图号。

    各张图的职责常并在一行里(「参考图3仅…；参考图5仅…」)：按每张图自己那一段认，不按行首的号。
    【场景锚点】行里带这句时，这一行点到的场景图也算。
    """
    marker = _desk_marker()
    if not marker:
        return set()
    rules = _rules()
    starts_re = re.compile(rules["duty_start"])
    demoted: set[str] = set()
    for line in lines:
        if marker not in line:
            continue
        starts = list(starts_re.finditer(line))
        for index, start in enumerate(starts):
            end = starts[index + 1].start() if index + 1 < len(starts) else len(line)
            if marker in line[start.start():end]:
                demoted.add(start.group(1))
        if line.strip().startswith(rules["scene_anchor_head"]):
            demoted.update(match.group("n") for match in rules["mention_re"].finditer(line))
    return demoted


def _binding_line(found: dict[str, dict[str, str]], demoted: set[str] = frozenset()) -> str:
    rules = _rules()
    words = rules["binding"]
    rows = []
    for name, item in found.items():
        gives = rules["gives"].get(item["kind"]) or (words["gives_scene"] if item["kind"].startswith("场景") else words["gives_default"])
        gives = words["gives_desk_demoted"] if item["n"] in demoted else "、".join(gives.split())
        template = words["row_costume"] if item["costume"] else words["row"]
        rows.append(template.format(name=name, n=item["n"], gives=gives, costume=item["costume"]))
    return words["head"] + words["joiner"].join(rows) + words["tail"] if rows else ""


def _appearance(line: str, found: dict[str, dict[str, str]]) -> str:
    """人物外貌一行：有参考图的人那一截交给参考图，没有参考图的人照留。"""
    rules = _rules()
    head = rules["appearance_head"]
    body = line.strip()[len(head):]
    kept: list[str] = []
    keep = True
    starts = {_token(name, item["n"]) + "：" for name, item in found.items()}
    for chunk in re.split(r"(?<=。)", body):
        if not chunk.strip():
            continue
        # 一截以「名字：」或「名字（参考图N）：」开头就是换了一个人；只有带参考图的人那截交给参考图。
        if _PERSON.match(chunk.strip()):
            keep = not any(chunk.strip().startswith(token) for token in starts)
        if keep:
            kept.append(chunk)
    return head + "".join(kept) if kept else ""


_CLAUSE = re.compile(r"([；。])")
_PERSON = re.compile(r"^[^：，、。；\s]{1,24}：")
_LABEL = re.compile(r"^[^：:，,。；]{1,6}[：:]")


def _drop_repeats(lines: list[str]) -> tuple[list[str], bool]:
    """前文已经一字不差写过的句子，后面那次删掉；台词行、时间轴固定句不动。"""
    rules = _rules()
    least = int(rules["repeat_min_chars"])
    skip = [re.compile(item) for item in rules["repeat_skip_lines"]]
    seen = ""
    out: list[str] = []
    dropped = False
    for line in lines:
        if any(pattern.search(line) for pattern in skip):
            out.append(line)
            seen += "\n" + line
            continue
        parts = _CLAUSE.split(line)
        kept: list[str] = []
        for index in range(0, len(parts), 2):
            clause = parts[index]
            mark = parts[index + 1] if index + 1 < len(parts) else ""
            core = _LABEL.sub("", clause.strip())
            if len(core) >= least and core in seen:
                dropped = True
                continue
            kept.append(clause + mark)
            seen += clause + mark
        line = "".join(kept)
        if line.strip() or not parts[0].strip():
            out.append(line)
    return out, dropped


def compact(text: str, model: str) -> tuple[str, Fit]:
    """发给 ``model`` 前的去重；不需要时原样返回(steps 为空)。"""
    text = str(text or "")
    limit = tight_limit(model)
    fit = Fit(model=model, limit=limit, before=len(text), after=len(text))
    rules = _rules()
    if limit is None or len(text) + int(rules["reserve"]) <= limit:
        return text, fit
    for pattern in rules["inline_res"]:
        shorter = pattern.sub("", text)
        if shorter != text:
            text = shorter
            fit.steps.append("inline")
    lines = text.split("\n")
    found = _bindings(lines)
    demoted = _demoted(lines)
    present = [line.strip() for line in lines]
    out: list[str] = []
    in_constraints = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(rules["constraints_head"]):
            in_constraints = True
        elif in_constraints and any(pattern.search(stripped) for pattern in rules["constraint_res"]):
            fit.steps.append("constraints")
            continue
        elif in_constraints and any(pattern.search(stripped) for pattern in rules["term_res"]):
            # 负面词表：通用词已由合成的约束行概括；打戏这类场景专属的、本片自定义的照留。
            joiner = rules["term_joiner"]
            fit.steps.append("constraints")
            terms = [term.strip() for term in stripped.split(joiner.strip())]
            line = joiner.join(term for term in terms if term and term not in _generic_terms())
            if not line:
                continue
        if any(pattern.search(stripped) for pattern in rules["drop_res"]):
            fit.steps.append("anchors")
            continue
        if any(pattern.search(stripped) and any(needs.search(other) for other in present) for pattern, needs in rules["drop_when_res"]):
            fit.steps.append("duplicate")
            continue
        if stripped.startswith(rules["appearance_head"]):
            line = _appearance(line, found)
            fit.steps.append("appearance")
            if not line:
                continue
        out.append(line)
    if "constraints" in fit.steps:
        # 合成的那一行放在【关键约束】标题下(没有标题就放最后)。
        head = next((index for index, line in enumerate(out) if line.strip().startswith(rules["constraints_head"])), None)
        out.insert(len(out) if head is None else head + 1, rules["constraints"])
    # 名字只在绑定行里带参考图号；「参考图1是开场画面…」这类讲图本身的行照旧。
    if found:
        binding = _binding_line(found, demoted)
        tokens = re.compile("|".join(re.escape(_token(name, item["n"])) for name, item in found.items()))
        names = {_token(name, item["n"]): name for name, item in found.items()}
        out = [
            line if any(pattern.search(line.strip()) for pattern in rules["keep_mentions_res"])
            else tokens.sub(lambda match: names[match.group(0)], line)
            for line in out
        ]
        # 绑定行放在讲参考图的开头几行之后、正文之前。
        at = 0
        while at < len(out) and any(pattern.search(out[at].strip()) for pattern in rules["keep_mentions_res"]):
            at += 1
        out.insert(at, binding)
        fit.steps.append("names")
    out, repeated = _drop_repeats(out)
    if repeated:
        fit.steps.append("repeats")
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    fit.steps = list(dict.fromkeys(fit.steps))
    fit.after = len(text)
    if len(text) + int(rules["reserve"]) > limit:
        fit.over = True
        fit.note = rules["over_note"].format(length=len(text), model=model, limit=limit)
    return text, fit


__all__ = ["Fit", "compact", "tight_limit"]

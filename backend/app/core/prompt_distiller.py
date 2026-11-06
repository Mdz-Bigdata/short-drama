# -*- coding: utf-8 -*-
"""视频提示词精炼：内容一个不丢，字数尽量少。

两步：
1. :func:`dedupe` ——不花钱的去重：运镜契约整段把画面、景别、构图、表情、落幅再抄一遍，铁律与负向词
   互相重复，中文规则后面还跟着同义的英文括注；完全重复的分句删掉，信息不变。
2. 仍超出预算时请文本模型把正文压短(:data:`SYSTEM_PROMPT`)；``@[名字]`` 标记与带单位的数字必须一个
   不少、而且要明显变短才采用(:func:`check`)，否则用去重后的版本。

风格锁、锚点、空间锁、景别运镜行、台词原文不进第 2 步。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from app.core.prompt_budget import FIXED_SECTIONS, prompt_length
from app.core.spoken_lines import dialogue_segments

#: 进精炼的正文小节(按提示词顺序)。
DISTILLABLE: tuple[str, ...] = (
    "subject", "motion", "expression", "composition", "environment", "colour", "effects",
    "contact", "handoff", "dialogue_notes", "sound_layers", "sound", "end_state",
)
#: 正文目标字数低于此值就不精炼(锁定行已占满预算，再压也写不下事实)。
MIN_TARGET = 120
#: 精炼结果至少要短到原文的这个比例才采用(超出目标不算失败：内容优先，宁长勿丢)。
MIN_SAVING = 0.85

SYSTEM_PROMPT = (
    "你是视频提示词精炼师。把用户给的视频提示词正文压缩到不超过 {target} 个汉字(不计空格与换行)。\n"
    "硬规则：\n"
    "1. 事实一个不丢：出场人物、动作及其先后顺序、站位与朝向、景别/机位/焦段/运镜、光线方向与色温、"
    "道具及其状态、表情与眼神、起幅与落幅、镜头衔接、声音与台词表达方式，全部保留。\n"
    "2. 原文里形如 @[名字] 的标记、所有数字及其单位(mm、米、°、度、秒等)原样保留，不改写、不换算；"
    "这些必须原样出现：{keep}。\n"
    "3. 只删重复、套话、修饰性空话和解释；不加新内容，不评价，不解释。\n"
    "4. 用短句，分号分隔，小节标题可省略；如有【镜头k/n｜…】镜头块，逐块保留开头标记与顺序，只压缩块内文字，"
    "各块重复的套话只写一次。\n"
    "5. 只输出压缩后的正文本身，不要标题、不要引号、不要代码块、不要说明。"
)

_MENTION = re.compile(r"@\[[^\]]+\]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?\s*(?:mm|cm|米|m\b|°|度|秒|s\b|级|%|％|分之[一二三四五六七八九十])")


@dataclass
class Plan:
    body: str
    target: int
    kept: dict[str, str]
    mentions: set[str]
    numbers: set[str]
    # 必须原样出现的字面量(如多镜头片段的「【镜头2/3」块标记)。
    required: set[str] = field(default_factory=set)
    distillable: tuple[str, ...] = DISTILLABLE


def _normalize(token: str) -> str:
    return re.sub(r"\s+", "", token)


def invariants(text: str) -> tuple[set[str], set[str]]:
    """正文里必须原样保留的东西：@[名字] 标记，和带单位的数字。"""
    mentions = set(_MENTION.findall(text or ""))
    numbers = {_normalize(match.group(0)) for match in _NUMBER.finditer(text or "")}
    return mentions, numbers


def keep_list(plan_: Plan) -> str:
    """系统提示词里那句「这些必须原样出现」。"""
    items = sorted(plan_.required) + sorted(plan_.mentions) + sorted(plan_.numbers)
    return "、".join(items) if items else "无"


# 表格没写内容时填的占位话：模型读不出任何画面信息，它也不知道什么是「场景圣经」「分镜契约」。
_PLACEHOLDER_LINES = ("[道具锁]本格无额外道具", "[光影锁]继承场景圣经的主光方向、色温、时间和天气，人物脸部保持自然层次")
_PLACEHOLDER_SECTIONS = {
    "expression": ("表演：与本镜触发事件对应的可观察微表情与呼吸变化",),
    "effects": ("特效：本格无额外特效",),
    "end_state": (
        "落幅：人物姿态、视线与道具停在下一镜可以直接承接的状态",
        "落幅：人物姿态、视线与道具停在下一镜可以直接承接的状态。",
        "落幅：锁定人物朝向、道具归属、情绪强度、光向与色温",
        "落幅：锁定人物朝向、道具归属、情绪强度、光向与色温。",
    ),
}
_PLACEHOLDER_CLAUSES = frozenset({
    "本格无额外道具", "本格无额外特效", "与本镜触发事件对应的可观察微表情与呼吸变化",
    "继承场景圣经的主光方向、色温、时间和天气，人物脸部保持自然层次",
    "建立空间与人物关系", "人物姿态、视线与道具停在下一镜可以直接承接的状态", "锁定人物朝向、道具归属、情绪强度、光向与色温",
})
_PLACEHOLDER_PHRASES = ("：建立空间与人物关系；", "：建立空间与人物关系")
_NO_LINE = re.compile(r"^(?:无|没有|-+|—+|n/?a)?(?:[（(][^）)]*[）)])?$", re.I)
_REFERENCE_SUFFIXES = ("，图中人物不作参考", "，不是额外剧情或额外人物")

_DIALOGUE_COPY = re.compile(r"[。．.]?\s*原文台词保持不变[：:].*?(。?)\s*$", re.S)
_CLAUSE = re.compile(r"[^；;。\n]+[；;。]?")
_LABEL = re.compile(r"^\s*[\w\u4e00-\u9fff·]{1,8}[：:]")
_ASCII_GLOSS = re.compile(r"\s*[（(][A-Za-z][A-Za-z0-9 ,.'\-/&]*[)）]")


def _core(clause: str) -> str:
    """分句去掉「标签：」和标点后的正文，用来判断是否与别处重复。"""
    return re.sub(r"[\s。；;，,]", "", _LABEL.sub("", clause))


def is_no_line(dialogue: object) -> bool:
    """台词栏其实没有台词：「无」「无；无」「—（承接上一格，本格不出新台词）」都不是要念的话。"""
    return all(_NO_LINE.match(part) for part in dialogue_segments(dialogue))


def _is_placeholder(clause: str) -> bool:
    return _LABEL.sub("", clause).strip(" ；;。") in _PLACEHOLDER_CLAUSES


def _drop_placeholders(sections: dict[str, str]) -> None:
    for key, placeholders in _PLACEHOLDER_SECTIONS.items():
        if sections.get(key, "").strip() in placeholders:
            sections[key] = ""
    if sections.get("expression"):
        sections["expression"] = "".join(
            clause for clause in _CLAUSE.findall(sections["expression"]) if not _is_placeholder(clause)
        ).strip()
    locks = sections.get("locks", "")
    if locks:
        lines = [line for line in locks.splitlines() if line.strip() not in _PLACEHOLDER_LINES]
        text = "\n".join(lines)
        for phrase in _PLACEHOLDER_PHRASES:
            text = text.replace(phrase, "：")
        # 状态只是占位时，「人物：视线：人物视线朝向…」只留视线那句。
        text = re.sub(r"^(\[状态锁\])[^\n：]*：+(?=视线：)", r"\1", text, flags=re.M)
        sections["locks"] = re.sub(r"^(?!\[状态锁\]视线)(.*?)：+\s*$", r"\1", text, flags=re.M)


def repeated_clauses_out(text: str) -> str:
    """同一段里再次出现的分句删掉，只留第一次。"""
    seen: set[str] = set()
    kept = []
    for clause in re.findall(r"[^；;。\n]+[；;。]?|\n", text):
        core = _core(clause)
        if len(core) >= 6 and core in seen:
            continue
        seen.add(core)
        kept.append(clause)
    return "".join(kept)


def _negatives_out_of(negatives: str, *written: str) -> str:
    """负向词里已经写过的条目去掉：整条的(NOT CGI、无水印)和括号英文清单里的单词。"""
    source = " ".join(written)
    lowered = source.lower()
    items = [item.strip() for item in negatives.split(" + ") if item.strip()]
    kept = []
    for item in items:
        if item in source:
            continue
        listed = re.fullmatch(r"\(([^：:]{1,8}[：:])(.*)\)", item)
        if listed:
            terms = [term.strip() for term in listed.group(2).split(",") if term.strip()]
            terms = [term for term in terms if not re.search(rf"(?<![a-z]){re.escape(term.lower())}(?![a-z])", lowered)]
            if not terms:
                continue
            item = f"({listed.group(1)}{', '.join(terms)})"
        kept.append(item)
    return " + ".join(kept)


def dedupe_blocks(blocks: list[str]) -> list[str]:
    """多镜头片段的镜头块：后面的块不再重复前面写过的分句，块头和带台词的分句不动。"""
    seen: set[str] = set()
    result = []
    for block in blocks:
        head, closing, body = block.partition("】")
        if not closing:
            head, closing, body = "", "", block
        kept = []
        for clause in _CLAUSE.findall(body):
            core = _core(clause)
            # 台词和镜头之间的衔接每块都有自己的位置，字面相同也不是重复。
            spoken = "{" in clause or "}" in clause  # 台词可能被句号断开，后半截同样动不得
            if len(core) >= 6 and not spoken and not clause.startswith("衔接：") and core in seen:
                continue
            seen.add(core)
            kept.append(clause)
        result.append(f"{head}{closing}{''.join(kept)}")
    return result


def collapse_reference_notes(prompt: str) -> str:
    """每张参考图都重复的两句，只说一次。在参考图改完号之后调用：改号靠句尾那句定位。"""
    if prompt.count(_REFERENCE_SUFFIXES[1]) < 2:
        return prompt
    closing = ""
    if prompt.count(_REFERENCE_SUFFIXES[0]):
        closing += "；场地图中的人物都不作参考"
    closing += "；以上参考图都不是额外剧情或额外人物"
    for suffix in _REFERENCE_SUFFIXES:
        prompt = prompt.replace(suffix, "")
    head, marker, tail = prompt.partition("【参考素材职责】\n")
    if not marker:
        return prompt + closing
    line, newline, rest = tail.partition("\n")
    return f"{head}{marker}{line.rstrip('。')}{closing}。{newline}{rest}"


def dedupe(sections: Mapping[str, str]) -> dict[str, str]:
    """删掉重复和没有信息的内容，画面信息不变。

    - 运镜契约(motion)里与画面、景别运镜、构图、表演、空间锁、落幅逐字相同的分句；
    - 负向词里已经写在铁律、收尾句里的条目；铁律里重复的分句；
    - 中文规则后面同义的纯英文括注(如「同一人物同一张脸……(same character, same outfit, …)」)；
    - 表格没写内容时填的占位话。
    """
    out = {key: str(value or "") for key, value in sections.items()}
    _drop_placeholders(out)
    # 画面正文里抄的台词原文：台词栏已经逐字写了，这里再写一遍只会被当成画面。
    out["subject"] = _DIALOGUE_COPY.sub(lambda match: match.group(1), out.get("subject", ""))
    others = "".join(_core(out.get(key, "")) for key in ("subject", "camera", "composition", "expression", "locks", "end_state", "dialogue"))
    motion = out.get("motion", "")
    if motion:
        kept = []
        for clause in _CLAUSE.findall(motion):
            core = _core(clause)
            if (len(core) >= 6 and core in others) or _is_placeholder(clause):
                continue
            kept.append(clause)
        out["motion"] = "".join(kept).strip()
    rules = out.get("rules", "")
    if rules:
        rules = out["rules"] = repeated_clauses_out(_ASCII_GLOSS.sub("", rules))
    negatives = out.get("negatives", "")
    if negatives:
        out["negatives"] = _negatives_out_of(negatives, rules, out.get("closing", ""))
    return {key: value for key, value in out.items() if value}


def plan(
    sections: Mapping[str, str], budget: int | None, *, fixed: frozenset[str] = FIXED_SECTIONS,
    distillable: tuple[str, ...] = DISTILLABLE, required: set[str] | tuple[str, ...] = (),
) -> Plan | None:
    """要不要精炼、压到多少字：正文超出预算减去锁定行之后的余量才精炼。"""
    if not budget:
        return None
    kept = {key: str(value or "") for key, value in sections.items() if key not in distillable and str(value or "")}
    body = "\n".join(str(sections[key]) for key in distillable if str(sections.get(key) or "").strip())
    if not body.strip():
        return None
    locked = sum(prompt_length(value) for key, value in kept.items() if key not in fixed)
    target = budget - locked
    if prompt_length(body) <= target or target < MIN_TARGET:
        return None
    mentions, numbers = invariants(body)
    return Plan(
        body=body, target=target, kept=kept, mentions=mentions, numbers=numbers,
        required={token for token in required if token in body}, distillable=tuple(distillable),
    )


def check(plan_: Plan, output: str) -> str:
    """精炼结果为什么不能用；能用返回空串。"""
    text = str(output or "").strip()
    if not text:
        return "没有输出"
    if "```" in text or text.startswith(("#", "{", "[")):
        return "输出不是正文"
    length = prompt_length(text)
    if length > prompt_length(plan_.body) * MIN_SAVING:
        return f"没有明显变短({length}/{prompt_length(plan_.body)})"
    lost_blocks = sorted(token for token in plan_.required if token not in text)
    if lost_blocks:
        return "丢了镜头块：" + "、".join(lost_blocks[:5])
    mentions, numbers = invariants(text)
    missing = sorted(plan_.mentions - mentions)
    if missing:
        return "丢了标记：" + "、".join(missing[:5])
    lost = sorted(plan_.numbers - numbers)
    if lost:
        return "丢了数字：" + "、".join(lost[:5])
    return ""


def apply(plan_: Plan, output: str) -> dict[str, str] | None:
    """校验通过就把精炼正文装回 ``subject``，其余锁定小节原样；不通过返回 None。"""
    if check(plan_, output):
        return None
    sections = dict(plan_.kept)
    sections["subject"] = str(output).strip()
    return sections


def distill_sections(
    sections: Mapping[str, str], budget: int | None, *, rewrite: Callable[[str, int], str], fixed: frozenset[str] = FIXED_SECTIONS,
) -> tuple[dict[str, str] | None, str]:
    """一步到位：规划 → 改写 → 校验；返回 (新小节或 None, 未采用的原因)。"""
    plan_ = plan(sections, budget, fixed=fixed)
    if plan_ is None:
        return None, "不需要精炼"
    try:
        output = rewrite(plan_.body, plan_.target)
    except Exception as exc:  # noqa: BLE001 - 精炼失败就退回裁剪，原因记下来
        return None, f"改写失败：{type(exc).__name__}"
    reason = check(plan_, output)
    return (None, reason) if reason else (apply(plan_, output), "")


__all__ = [
    "DISTILLABLE", "MIN_SAVING", "MIN_TARGET", "SYSTEM_PROMPT", "Plan", "apply", "check", "dedupe", "distill_sections",
    "invariants", "keep_list", "plan",
]

# -*- coding: utf-8 -*-
"""MiniMax H3 原生提示词：把分镜片段的中文提示词改写成 H3 官方 Ref2VA 六段式英文提示词。

H3 官方提示词契约(skills/shot-design-master/references/h3-native-contract.md)要求多参考请求写成六个固定
段落：subject_definitions / summary / retention_analysis / detailed_description / overall_soundscape /
non_diegetic_music；画面描述用英文，台词与画面文字保留原文；多镜头用 ``[Shot k] At 00:SS.mmm`` 递增时间码；
不另附一段并列的负面提示词；全文不超过 7000 字符。

做法：每个分镜片段请文本模型改写一次(并行、结果缓存)，改写结果必须通过 :func:`check`——六段齐全且有序、
每个镜头块与给定时间码都在、每个 ``@[名字]`` 与 ``<Frame k>`` 标记都在、每句台词逐字保留、长度在上限内——
才采用；不通过就照旧发中文提示词。标记在发送那一刻才换成真实的 ``<Picture N>`` 编号(:func:`resolve`)：
只有路由完成后才知道每张图排在第几位。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.core.prompt_distiller import is_no_line
from app.core.spoken_lines import plain as _plain, spoken_lines

logger = logging.getLogger(__name__)

SECTIONS: tuple[str, ...] = (
    "subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music",
)
#: H3 官方提示词上限(字符)。改写结果留出标记展开的余量。
MAX_CHARS = 7000
MAX_DRAFT_CHARS = 6400
_MENTION = re.compile(r"@\[([^\]]+)\]")
_FRAME = re.compile(r"<Frame (\d+)>")
_REF = re.compile(r"<Ref (\d+)>")
_SOURCE_REF = re.compile(r"参考图(\d+)")
_DIALOGUE = re.compile(r"[{｛]([^{}｛｝]+)[}｝]")
_NO_DIALOGUE = frozenset({"无", "无台词", "-", "—", "（无）", "(无)"})
#: 目标长度：英文比中文占字符，官方上限 7000，正文尽量控制在这里。
TARGET_CHARS = 4500
#: 不交给改写的中文分节：铁律与负面词按官方契约改成 retention_analysis 里的正面约束，收尾句是中文画面要求。
SKIP_SECTIONS = frozenset({"rules", "negatives", "closing"})

SYSTEM_PROMPT = (
    "你是 MiniMax H3 视频提示词导演。把用户给的「分镜片段中文提示词」改写成 H3 官方 Ref2VA 六段式英文提示词，"
    "只输出提示词本身。\n"
    "格式(六段，顺序固定，每段以字段名加冒号开头，段与段之间空一行)：\n"
    "subject_definitions: …\nsummary: …\nretention_analysis: …\ndetailed_description: …\noverall_soundscape: …\nnon_diegetic_music: …\n"
    "硬规则：\n"
    "1. 画面、动作、运镜、光线、表演用英文写；台词逐字保留中文原文，写成 (S1) says: <d>[Chinese] 原文</d>，"
    "同一说话人全片同一个 (S编号)；画外音写 says in an off-screen voiceover，并写明画面人物嘴唇闭合；画面里真实可见的文字用英文双引号逐字保留。\n"
    "2. 原文里的 @[名字] 标记原样保留(不翻译、不加空格)；原文的「参考图k」一律写成 <Ref k>，每个 <Ref k> 都在 subject_definitions 里"
    "写清它锁定什么(人物身份、服装、场地的哪个视角、道具)；分镜画面用 <Frame k> 指代，每个 <Frame k> 都要在 subject_definitions 里写一句"
    "「<Frame k> is the storyboard reference for [Shot k], defining viewpoint, subject placement and composition.」。\n"
    "3. subject_definitions：每个人物、场地、关键道具一条 <Subject N> 定义，写明它来自哪个 @[名字]，例如 "
    "<Subject 1> is @[沈无咎], a young swordsman whose face, hair and wardrobe come from his reference picture.\n"
    "4. summary 以 [reference generation] 开头，一两句说明这段视频讲什么、参考图各管什么。\n"
    "5. retention_analysis：逐个 <Subject N> 与 <Frame k> 写 fully_preserved / partially_preserved / weak_reference，"
    "并把一致性要求写成正面约束(同一张脸、同一服装、同一空间方向与主光方向、道具不换手不消失)，不要单列负面词。\n"
    "6. detailed_description：按镜头顺序写 [Shot 1] …，从第二个镜头起必须逐字使用给定的时间码开头，如 "
    "[Shot 2] At 00:05.000, the shot transitions to …；不要写硬切(hard cut)，镜头之间写清动作或视线如何顺接。"
    "每个镜头写清主体与站位、动作因果(准备→发力→受力→收势)、表情与视线目标、一个主运镜(类型+幅度+速度+目的)、"
    "光线(主光方向、光源、色温、光比)。\n"
    "7. overall_soundscape：1–4 句英文写环境声、动作声与非语言人声，不重复台词；non_diegetic_music：1–3 句英文写配乐，没有就写 N/A。\n"
    "8. 不丢任何事实(人物、动作先后、站位朝向、景别机位焦段、光线色温、道具状态、起幅落幅、台词)；"
    "删掉重复、套话和形容词堆砌；不写「8K」「超清」之类空洞画质词；全文尽量控制在 {target} 个字符以内，绝不超过 {limit} 个字符。\n"
    "9. 只输出六段正文，不要标题、解释、Markdown 或代码块。"
)


@dataclass
class Request:
    """一个分镜片段的改写任务。"""

    board_text: str                       # 中文提示词(带 @[名字] 标记)
    shot_starts: list[str]                # 每个镜头的起始时间码，第 1 镜为空串
    seconds: int
    frames: int = 0                       # 分镜画面张数(<Frame 1> … <Frame n>)
    mentions: set[str] = field(default_factory=set)
    dialogue: list[str] = field(default_factory=list)
    refs: list[int] = field(default_factory=list)          # 原文「参考图k」的 k(身份参考图的序号)

    @property
    def shots(self) -> int:
        return len(self.shot_starts)


def timecode(seconds: float) -> str:
    whole = max(0.0, float(seconds))
    minutes, rest = divmod(whole, 60)
    return f"{int(minutes):02d}:{rest:06.3f}"


def shot_starts(beat_seconds: Sequence[float], total: float) -> list[str]:
    """每个镜头的起始时间码：按计划秒数等比缩放到片段时长，第 1 镜不写时间码。"""
    planned = [max(0.1, float(value)) for value in beat_seconds] or [float(total or 1)]
    scale = float(total or sum(planned)) / sum(planned)
    starts, cursor = [""], 0.0
    for value in planned[:-1]:
        cursor += value * scale
        starts.append(timecode(cursor))
    return starts


def request(
    board_text: str, *, beat_seconds: Sequence[float], seconds: int, frames: int, dialogue: Sequence[str] = (),
) -> Request:
    """``dialogue`` 是各镜头台词栏的原文；没给时从提示词里 ``{…}`` 取。"""
    text = str(board_text or "")
    # 「{无}」是无台词镜头的占位，不是要逐字保留的台词。
    dialogue = [line for line in dialogue if not is_no_line(line)]
    lines = spoken_lines(dialogue) if dialogue else [
        line.strip() for line in _DIALOGUE.findall(text) if line.strip() and line.strip() not in _NO_DIALOGUE
    ]
    return Request(
        board_text=text, shot_starts=shot_starts(beat_seconds, seconds), seconds=int(seconds), frames=int(frames),
        mentions={f"@[{name}]" for name in _MENTION.findall(text)}, dialogue=list(dict.fromkeys(lines)),
        refs=sorted({int(k) for k in _SOURCE_REF.findall(text)}),
    )


def system_prompt() -> str:
    return SYSTEM_PROMPT.format(limit=MAX_DRAFT_CHARS, target=TARGET_CHARS)


def board_text(sections: Mapping[str, str]) -> str:
    """交给改写的中文提示词：去掉铁律、负面词与收尾句，其余分节按原顺序。"""
    from app.core.video_prompt_engine import _render

    return _render({key: value for key, value in sections.items() if key not in SKIP_SECTIONS})


def user_prompt(req: Request) -> str:
    """给文本模型的输入：中文提示词 + 必须遵守的镜头时间码、分镜画面数与台词清单。"""
    stamps = "；".join(
        f"[Shot {number}]" + (f" At {start}" if start else "（不写时间码）") for number, start in enumerate(req.shot_starts, start=1)
    )
    frames = "、".join(f"<Frame {k}>" for k in range(1, req.frames + 1)) or "无"
    refs = "、".join(f"参考图{k} → <Ref {k}>" for k in req.refs) or "无"
    lines = "\n".join(f"- {line}" for line in req.dialogue) or "- 无台词"
    return (
        f"片段总时长 {req.seconds} 秒，共 {req.shots} 个镜头。镜头时间码：{stamps}。\n"
        f"分镜画面：{frames}（按镜头顺序，<Frame k> 对应 [Shot k]）。\n"
        f"参考图标记：{refs}。\n"
        f"必须逐字保留的台词：\n{lines}\n\n"
        f"【分镜片段中文提示词】\n{req.board_text}"
    )


_SENTENCE_END = re.compile(r"[。！？.!?\n]")


def fit(prompt: str, *, plain: str = "") -> str:
    """发给 H3 的正文不超过官方 7000 字符：先去掉追加的增强词与负面词(``plain`` 是追加前的原文)，
    还是太长就在最后一个句末截断。宁可少一句，不能整段被 400 拒单。"""
    if len(prompt) <= MAX_CHARS:
        return prompt
    text = plain if plain and len(plain) < len(prompt) else prompt
    if len(text) > MAX_CHARS:
        head = text[:MAX_CHARS]
        ends = [match.end() for match in _SENTENCE_END.finditer(head)]
        text = head[: ends[-1]] if ends and ends[-1] > MAX_CHARS // 2 else head
    logger.warning("[H3] 提示词 %s 字符超出官方上限 %s，发 %s 字符的版本", len(prompt), MAX_CHARS, len(text))
    return text.strip()


def is_native(prompt: str) -> bool:
    """这条提示词已是 H3 六段式(网关据此不再追加中文增强词与负面词)。"""
    return str(prompt or "").lstrip().startswith(("subject_definitions:", "For the target video", "How the reference pictures"))


def check(req: Request, output: str) -> str:
    """改写结果为什么不能用；能用返回空串。"""
    text = str(output or "").strip()
    if not text:
        return "没有输出"
    if "```" in text:
        return "输出带了代码块"
    if len(text) > MAX_DRAFT_CHARS:
        return f"超出长度上限({len(text)}/{MAX_DRAFT_CHARS})"
    positions = []
    for name in SECTIONS:
        found = re.search(rf"(?m)^{name}:", text)
        if not found:
            return f"缺少段落 {name}"
        positions.append(found.start())
    if positions != sorted(positions):
        return "六个段落顺序不对"
    if re.search(r"\(S\d+\)", text[positions[2]:positions[3]]):
        return "retention_analysis 里不能出现说话人编号"
    detail = text[positions[3]:positions[4]]
    for number, start in enumerate(req.shot_starts, start=1):
        if f"[Shot {number}]" not in detail:
            return f"缺少镜头 [Shot {number}]"
        if start and f"[Shot {number}] At {start}" not in detail:
            return f"[Shot {number}] 没有用给定时间码 {start}"
    if f"[Shot {req.shots + 1}]" in detail:
        return "多出了镜头"
    missing = sorted(mention for mention in req.mentions if mention not in text)
    if missing:
        return "丢了标记：" + "、".join(missing[:5])
    refs = [k for k in req.refs if f"<Ref {k}>" not in text]
    if refs:
        return "丢了参考图：" + "、".join(f"<Ref {k}>" for k in refs)
    frames = [k for k in range(1, req.frames + 1) if f"<Frame {k}>" not in text]
    if frames:
        return "丢了分镜画面：" + "、".join(f"<Frame {k}>" for k in frames)
    plain = _plain(text)
    lost = [line for line in req.dialogue if _plain(line) not in plain]
    if lost:
        return "台词没有逐字保留：" + lost[0][:20]
    if re.search(r"(?i)hard cut", text):
        return "写了硬切"
    return ""


def _drop_sentences(text: str, token: re.Pattern[str]) -> str:
    """去掉含未落地标记的句子(那张图这次没有发出去)。"""
    lines = []
    for line in text.splitlines():
        if token.search(line):
            parts = re.split(r"(?<=[.;])\s+", line)
            kept = [part for part in parts if not token.search(part)]
            line = " ".join(kept)
            if re.fullmatch(r"\s*\w+:\s*", line):
                line = line.rstrip() + " N/A"
        lines.append(line)
    return "\n".join(lines)


def resolve(
    text: str, *, sent: Sequence[str], identity_images: Sequence[str], numbers: Mapping[str, int],
    frames: Sequence[str], handoff: str | None = None,
) -> str:
    """发送前把标记换成这次请求里真实的图片编号：``@[名字]`` → ``名字 (<Picture N>)``，``<Frame k>`` → ``<Picture N>``。

    没发出去的图(内容审核后去掉的分镜画面)对应的句子删掉；以上一段尾帧开场时补一句说明。
    """
    position = {url: index for index, url in enumerate(sent, start=1)}

    def picture_of(url: str | None) -> int | None:
        return position.get(url) if url else None

    def mention(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        number = numbers.get(name)
        url = identity_images[number - 1] if number and 0 < number <= len(identity_images) else None
        index = picture_of(url)
        return f"{name} (<Picture {index}>)" if index else name

    def ref(match: re.Match[str]) -> str:
        k = int(match.group(1))
        index = picture_of(identity_images[k - 1]) if 0 < k <= len(identity_images) else None
        return f"<Picture {index}>" if index else match.group(0)

    def frame(match: re.Match[str]) -> str:
        k = int(match.group(1))
        index = picture_of(frames[k - 1]) if 0 < k <= len(frames) else None
        return f"<Picture {index}>" if index else match.group(0)

    out = _REF.sub(ref, _FRAME.sub(frame, _MENTION.sub(mention, str(text or ""))))
    out = _drop_sentences(_drop_sentences(out, _FRAME), _REF)
    index = picture_of(handoff)
    if index:
        out = re.sub(
            r"(?m)^subject_definitions:\s*",
            f"subject_definitions: <Picture {index}> is the last frame of the previous part and the opening frame of [Shot 1]. ",
            out, count=1,
        )
    return out.strip()


__all__ = [
    "MAX_CHARS", "MAX_DRAFT_CHARS", "fit", "SECTIONS", "SKIP_SECTIONS", "SYSTEM_PROMPT", "TARGET_CHARS", "Request", "board_text", "check",
    "is_native", "request", "resolve", "spoken_lines",
    "shot_starts", "system_prompt", "timecode", "user_prompt",
]

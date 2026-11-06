# -*- coding: utf-8 -*-
"""镜头台词栏里真正说出口的话。

第 4 阶段写的台词栏常夹着别的东西：说话人标签、括注的语气与音色说明(有时被截断、没有收口)、
花括号、引号、括号外的舞台说明(「停顿一拍」)、表示无台词的「无」。字幕、配音核对和 H3 台词校验
都只要说出口的那几句。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_DIALOGUE = re.compile(r"[{｛]([^{}｛｝]+)[}｝]")
NO_DIALOGUE = frozenset({"无", "无台词", "-", "—", "（无）", "(无)"})
_SPEAKER = re.compile(r"^[^：:「“\"]{1,12}?(?:[（(][^）)]*[）)])?\s*[：:]\s*")
_NOTE = re.compile(r"[（(][^）)]*[）)]")
_NEXT_SPEAKER = re.compile(r"([。！？!?…」”])\s*([\u4e00-\u9fff]{1,6}[：:])")
#: 台词里夹的舞台说明(没有用括号括起来)：不是说出口的话，按它拆开。
_STAGE_DIRECTION = re.compile(r"[，,]?\s*(?:停顿一拍|停顿片刻|停了一拍|顿了顿|停顿|沉默片刻|沉默)\s*[，,]?")
_QUOTES = re.compile(r"[「」『』“”\"'‘’{}｛｝\s]")


def spoken_lines(dialogue: Sequence[str]) -> list[str]:
    """镜头台词栏里真正说出口的话：去掉说话人、括注的语气说明和引号；「无」不算。"""
    lines: list[str] = []
    for block in dialogue:
        # 括注的音色说明常用分号断句(「沙哑；起音猛、尾音发颤」)：先整段去掉括注，再按分号拆句，
        # 不然说明的后半截会被当成一句台词。
        text = re.sub(r"[（(][^）)]*$", "", _NOTE.sub("", str(block or "")))
        # 同一行里接着写下一个人的台词(「握着。沈无咎：握了。」)：在说话人标签前断开；
        # 括注去掉之后再断，说话人后面带语气说明的也认得出来。
        text = _NEXT_SPEAKER.sub(lambda match: match.group(1) + "\n" + match.group(2), text)
        for raw in re.split(r"[\n／/；;]", text):
            # 有花括号时只有括号里的是说出口的话，括号之间是舞台说明(「{谁？}停顿一拍{谁动的剑？}」)。
            parts = _DIALOGUE.findall(raw) or _STAGE_DIRECTION.split(_SPEAKER.sub("", raw.strip(), count=1))
            for part in parts:
                line = _NOTE.sub("", part)
                line = re.sub(r"[（(][^）)]*$", "", line)          # 被截断、没有收口的语气说明
                line = _QUOTES.sub("", line).strip("；;，, ")
                if line and line not in NO_DIALOGUE and not re.fullmatch(r"无+", line) and line not in lines:
                    lines.append(line)
    return lines




_OPENERS, _CLOSERS = "（({｛「『“", "）)}｝」』”"
_SEPARATORS = "\n／/；;"
_NEXT_LABEL = re.compile(r"\s*[\u4e00-\u9fff]{1,6}(?:[（(][^）)]*[）)])?\s*[：:]")
_AFTER_A_LINE = "。！？!?…」”}｝）)"
_TOP_NOTE = re.compile(r"[（(]([^（）()]*)[）)]")


def dialogue_segments(dialogue: object) -> list[str]:
    """台词栏按说话人拆开：换行、斜杠、分号，或上一句收尾后紧跟下一个「名字：」。

    括号、花括号和引号里面的不算：语气说明常带分号，台词里也可能有斜杠。
    """
    text = str(dialogue or "")
    segments: list[str] = []
    current: list[str] = []
    depth = 0

    def flush() -> None:
        segment = "".join(current).strip()
        if segment:
            segments.append(segment)
        current.clear()

    for index, char in enumerate(text):
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth = max(0, depth - 1)
        if depth == 0 and char in _SEPARATORS:
            flush()
            continue
        current.append(char)
        if depth == 0 and char in _AFTER_A_LINE and _NEXT_LABEL.match(text, index + 1):
            flush()
    flush()
    return segments


_LABEL = re.compile(r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z·]{0,7})\s*(?:[（(]([^（）()]*)[）)])?\s*[：:]\s*")
_CLOSED = re.compile(r"[（(「『“{｛][^）)」』”}｝]*[）)」』”}｝]")
_NOTE_TEXT = re.compile(r"[（(]([^）)]*)[）)]")


def labelled_lines(dialogue: object) -> list[tuple[str, str, str]]:
    """台词栏里带说话人的每一句：(名字, 语气说明, 说出口的话)。没有说话人标签时为空。

    标签可以带括注(「裴仲玄（语速缓）：落。」)；括号、引号里面的冒号不是标签。
    """
    text = str(dialogue or "")
    closed = [match.span() for match in _CLOSED.finditer(text)]
    labels = [match for match in _LABEL.finditer(text) if not any(start <= match.start() < end for start, end in closed)]
    found: list[tuple[str, str, str]] = []
    for label, following in zip(labels, [*labels[1:], None]):
        body = text[label.end():following.start() if following else len(text)]
        notes = "；".join(note for note in (label.group(2), *_NOTE_TEXT.findall(body)) if note)
        found.extend((label.group(1), notes, line) for line in spoken_lines([body]))
    return found


def split_speech(body: object) -> tuple[list[str], str]:
    """一句台词的(语气说明们, 说出口的部分)。说出口的部分已写成 ``{台词}``，不会多套一层。

    模型的写法有 ``{落。}（低沉）``、``「落。」（低沉）``、``（低沉）「落。」``，也有不带引号的；
    花括号之间的舞台说明(``{谁？} 停顿一拍 {谁动的剑？}``)留在括号外。
    """
    text = str(body or "").strip()
    depth = 0
    notes: list[str] = []
    kept: list[str] = []
    position = 0
    for match in _TOP_NOTE.finditer(text):
        before = text[position:match.start()]
        depth += sum(before.count(mark) for mark in "{｛「『“") - sum(before.count(mark) for mark in "}｝」』”")
        kept.append(before)
        if depth > 0:  # 台词里面的括号属于台词
            kept.append(match.group(0))
        else:
            notes.append(match.group(1).strip())
        position = match.end()
    kept.append(text[position:])
    spoken = "".join(kept).strip()
    spoken = re.sub(r"[「『“]([^」』”]*)[」』”]", r"{\1}", spoken) if not re.search(r"[{｛]", spoken) else spoken
    spoken = spoken.replace("｛", "{").replace("｝", "}")
    if "{" not in spoken:
        spoken = f"{{{spoken}}}" if spoken else ""
    return [note for note in notes if note], re.sub(r"\s*([{}])\s*", r"\1", spoken)


def plain(text: str) -> str:
    """去掉引号、花括号与空白后的文字，用来判断台词有没有逐字保留。"""
    return _QUOTES.sub("", str(text or ""))


__all__ = ["NO_DIALOGUE", "dialogue_segments", "labelled_lines", "plain", "split_speech", "spoken_lines"]

# -*- coding: utf-8 -*-
"""配音的表演标注：把台词旁写下的语气说明翻成配音模型认的表演标签。

AI 配音不是把字念出来，是把情绪演出来。台词栏里的（低声）（嘶吼）（停顿）（哽咽）、剧本 delivery 的
「停顿与重音」，以前只被读成一个情绪词；这里把它们按 data/prompt/voice_delivery.json 的词表翻成
ElevenLabs v3 的方括号标签，放在这句台词前面。台词原文不改，「……」「——」留在台词里由模型自己停。
"""

from __future__ import annotations

import re

from collections.abc import Mapping
from typing import Any

from app.core import prompt_data

_DATA = "voice_delivery"


def _pause_after(notes: str) -> bool:
    """「说完停半拍」：停顿在这句之后，不在开口之前。"""
    found = re.search(prompt_data.text(_DATA, "pause_words"), notes)
    if not found:
        return False
    clause = re.split(r"[，,；;。]", notes[:found.start()])[-1]
    return bool(re.search(prompt_data.text(_DATA, "pause_after_words"), clause))


def delivery_tags(notes: str, emotion: str = "neutral") -> list[str]:
    """这句该怎么演：语气说明里认出的标签在前(按词表顺序)，情绪标签补在后，开口前的停顿最后；最多 max_tags 个。

    情绪标签只在写了语气说明时加：没写说明时情绪是按台词关键词猜的，只信 trusted_guesses 里的。
    """
    notes = str(notes or "")
    tags: list[str] = []
    for words, tag in prompt_data.pairs(_DATA, "note_tags"):
        if tag not in tags and re.search(words, notes):
            tags.append(tag)
    emotion = str(emotion or "").strip()
    emotion_tag = prompt_data.value(_DATA, "emotion_tags").get(emotion)
    if emotion_tag and emotion_tag not in tags and (notes.strip() or emotion in prompt_data.words(_DATA, "trusted_guesses")):
        tags.append(emotion_tag)
    limit = prompt_data.number(_DATA, "max_tags")
    tags = tags[:limit]
    if re.search(prompt_data.text(_DATA, "pause_words"), notes) and not _pause_after(notes):
        tags = [*tags[:limit - 1], prompt_data.text(_DATA, "pause_tag")]
    return tags


def performed_text(text: str, emotion: str = "neutral", notes: str = "") -> str:
    """送给配音模型的一句：表演标签 + 台词原文(+ 说完才停的停顿)，如「[whispers] 那就三天。[short pause]」。"""
    line = " ".join(str(text or "").split())
    if not line:
        return line
    tags = delivery_tags(notes, emotion)
    before = ("".join(f"[{tag}]" for tag in tags) + " ") if tags else ""
    after = f"[{prompt_data.text(_DATA, 'pause_tag')}]" if _pause_after(str(notes or "")) else ""
    return before + line + after


def _integer(text: str) -> str:
    """整数的中文读法：105 → 一百零五，10 → 十，20000 → 两万。"""
    table = prompt_data.value(_DATA, "numbers")
    digits, units, big = table["digits"], table["units"], table["big_units"]
    value = int(text)
    if value == 0:
        return digits[0]

    def four(group: int) -> str:
        out, zero = "", False
        for position in range(3, -1, -1):
            digit = group // (10 ** position) % 10
            if digit == 0:
                zero = bool(out)
                continue
            if zero:
                out += digits[0]
                zero = False
            out += digits[digit] + units[position]
        return out

    parts: list[str] = []
    groups = []
    while value:
        groups.append(value % 10000)
        value //= 10000
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if not group:
            continue
        if parts and group < 1000:
            parts.append(digits[0])
        parts.append(four(group) + big[index] if index < len(big) else four(group))
    spoken = "".join(parts)
    # 十几只念「十」开头，不念「一十」。
    return spoken[1:] if spoken.startswith(digits[1] + units[1]) else spoken


def _spell(text: str) -> str:
    digits = prompt_data.value(_DATA, "numbers")["digits"]
    return "".join(digits[int(char)] for char in text if char.isdigit())


def _number(match: re.Match[str]) -> str:
    table = prompt_data.value(_DATA, "numbers")
    whole, fraction, after = match.group(1), match.group(2), match.group(3) or ""
    counted = bool(after) and after[0] in table["measure_words"]
    # 长串号码(电话、编号)逐位念；后面跟着量词的是数量(20000块 → 两万块)。
    if len(whole) >= int(table["spell_out_from"]) and not fraction and not counted:
        return _spell(whole) + after
    spoken = _integer(whole)
    if len(spoken) > 1 and spoken[0] == table["digits"][2] and spoken[1] in table["two_before"]:
        spoken = table["two"] + spoken[1:]
    if fraction:
        spoken += table["point"] + _spell(fraction)
    elif whole == "2" and counted:
        spoken = table["two"]
    return spoken + after


def spoken_form(text: str, readings: Any = None) -> str:
    """送去配音的那一句：数字按中文读法写出来，项目读音表里的词换成登记的念法。字幕不用这个。

    百分数(50% → 百分之五十)、时刻(7:30 → 七点三十)、年份(2026年 → 二零二六年)、小数(3.5 → 三点五)、
    五位以上的号码逐位念，量词前的 2 念「两」(2个 → 两个)。``readings`` 是 [{word, say}] 或 {word: say}。
    """
    table = prompt_data.value(_DATA, "numbers")
    line = str(text or "")
    pairs = readings.items() if isinstance(readings, Mapping) else (
        (str(item.get("word") or ""), str(item.get("say") or "")) for item in readings or [] if isinstance(item, Mapping)
    )
    for word, say in sorted(((str(w).strip(), str(v).strip()) for w, v in pairs), key=lambda item: len(item[0]), reverse=True):
        if word and say:
            line = line.replace(word, say)
    line = re.sub(r"(\d+(?:\.\d+)?)\s*[%％]", lambda m: table["percent"].format(n=_number(re.match(r"(\d+)(?:\.(\d+))?()", m.group(1)))), line)

    def clock(match: re.Match[str]) -> str:
        hour, minute = int(match.group(1)), int(match.group(2))
        minutes = "" if minute == 0 else _integer(str(minute)) if minute >= 10 else table["digits"][0] + _integer(str(minute))
        return table["time"].format(h=_integer(str(hour)), m=minutes)

    line = re.sub(r"(?<!\d)(\d{1,2})[:：](\d{2})(?!\d)", clock, line)
    line = re.sub(r"(?<!\d)(\d{4})(?=年)", lambda m: _spell(m.group(1)), line)
    return re.sub(r"(\d+)(?:\.(\d+))?(\D)?", _number, line)


def clean_readings(readings: Any) -> list[dict[str, str]]:
    """读音表：去空、去重(同一个词以后写的为准)，每条 {word, say}，最多 max_readings 条。"""
    rows: dict[str, str] = {}
    for item in readings if isinstance(readings, list) else []:
        if not isinstance(item, Mapping):
            continue
        word, say = str(item.get("word") or "").strip()[:20], str(item.get("say") or "").strip()[:20]
        if word and say and word != say:
            rows[word] = say
    return [{"word": word, "say": say} for word, say in list(rows.items())[: prompt_data.number(_DATA, "max_readings")]]


def age_bucket(description: str) -> str:
    """声音设计里的年龄(「38岁男声」「老年」)落在音色库的哪个年龄段：young / middle_aged / old；看不出是空串。"""
    ages = prompt_data.value(_DATA, "voice_ages")
    text = str(description or "")
    years = re.search(r"(\d{1,3})\s*岁", text)
    if years:
        age = int(years.group(1))
        return next((bucket for low, high, bucket in ages["buckets"] if low <= age <= high), "")
    return next((bucket for words, bucket in ages["words"] if re.search(words, text)), "")


def age_distance(wanted: str, offered: str) -> int:
    order = prompt_data.value(_DATA, "voice_ages")["order"]
    if wanted not in order or offered not in order:
        return 1
    return abs(order.index(wanted) - order.index(offered))


__all__ = ["age_bucket", "age_distance", "clean_readings", "delivery_tags", "performed_text", "spoken_form"]

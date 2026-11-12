# -*- coding: utf-8 -*-
"""配音的表演标注：把台词旁写下的语气说明翻成配音模型认的表演标签。

AI 配音不是把字念出来，是把情绪演出来。台词栏里的（低声）（嘶吼）（停顿）（哽咽）、剧本 delivery 的
「停顿与重音」，以前只被读成一个情绪词；这里把它们按 data/prompt/voice_delivery.json 的词表翻成
ElevenLabs v3 的方括号标签，放在这句台词前面。台词原文不改，「……」「——」留在台词里由模型自己停。
"""

from __future__ import annotations

import re

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


__all__ = ["age_bucket", "age_distance", "delivery_tags", "performed_text"]

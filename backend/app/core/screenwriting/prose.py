# -*- coding: utf-8 -*-
"""The reading form of an episode: 小说体正文.

The script plan stays the content truth source (shot boundaries, cast, verbatim
utterances). The prose is what a person reads in ``assets["2"]``: narration
paragraphs separated by one blank line, dialogue inside “” with the speaker's
action woven around it, and none of the production labels (``场景N：`` /
``镜头：`` / ``角色：台词``) the shot list needs.

Everything here is pure text work: normalising a model's draft, checking it
against the plan it was written from, and synthesising a plain prose body when
no authored one exists.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.writer_dashboard import EPISODE_HEADING, episode_label_number

# Lines that belong to a shot list, not to prose.
_LABEL_LINE = re.compile(
    r"^(?:【[^】]*】\s*$"
    r"|(?:场景|镜头|画面|分镜画面|分镜|动作|环境音|音效|音乐|配乐|旁白|画外音|字幕|时长|景别|运镜|转场|"
    r"台词提示|备注|集尾钩子|下集悬念钩子|下集预告|本集钩子|SCENE|INT\.|EXT\.|BGM)\s*[0-9]{0,4}\s*[：:]"
    r"|(?:内景|外景)[：:\s])",
    re.IGNORECASE,
)
_SCENE_ID = re.compile(r"(?<![A-Za-z0-9])E\d+S\d{2,}(?:_\d+)?(?![A-Za-z0-9])")
# What a chat model wraps around the body: "以下是第1集正文：" before it, "（本集完）" after it.
_PREFACE_LINE = re.compile(r"^(?:以下|下面|好的|这是|正文如下).{0,40}[：:]$")
_CLOSING_LINE = re.compile(r"^[（(【\-—\s]*(?:全文完|本集完|全剧终|未完待续|待续|完)[）)】\-—\s]*$")
_FENCE_LINE = re.compile(r"^\s*```")
_RULE_LINE = re.compile(r"^\s*(?:[-*_=]\s*){3,}$")
_MARKDOWN_PREFIX = re.compile(r"^(?:#{1,6}\s+|>\s*|[-*+]\s+(?=\S))")
_STAGE_PAREN = re.compile(r"[（(][^（()）\n]{1,40}[)）]")
_QUOTED = re.compile(r"“([^“”\n]{1,600})”")
_ASCII_QUOTED = re.compile(r'"([^"\n]{1,600})"')
_CORNER_QUOTED = re.compile(r"「([^「」\n]{1,600})」")
# Where a line of dialogue may be interrupted by the speaker's action without
# changing a single spoken character: “你听好，”她把信纸按在桌上，“这不是我写的。”
_FRAGMENT_SPLIT = re.compile(r"[\s，。！？；：、…—,.!?;:~～\-“”\"'‘’「」『』（）()《》〈〉【】·]+")
# Delivery marks a line may carry ([停顿2秒] / （冷笑）) are performed, not spoken, so prose never shows them.
_DELIVERY_MARK = re.compile(r"\[[^\[\]\n]{0,30}\]|[（(][^（()）\n]{0,30}[)）]")
_SPOKEN_TAIL = re.compile(r"[。！？…，—～!?]$")
_MIN_CHARS_PER_SHOT = 30
_MIN_CHARS = 60
_MAX_REPORTED = 6


@dataclass
class ProseCheck:
    """``errors`` make a draft unusable; ``warnings`` are worth a retry but may be kept."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [*self.errors, *self.warnings]


def _fold(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text or ""))


def _fragments(text: str) -> list[str]:
    spoken = _DELIVERY_MARK.sub(" ", unicodedata.normalize("NFC", text or ""))
    return [part for part in _FRAGMENT_SPLIT.split(spoken) if part]


def normalize_prose(text: str) -> str:
    """One paragraph per block, exactly one blank line between blocks, Chinese quotes, no markdown."""
    raw = unicodedata.normalize("NFC", text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    paragraphs: list[str] = []
    for line in raw.split("\n"):
        if _FENCE_LINE.match(line) or _RULE_LINE.match(line):
            continue
        paragraph = _MARKDOWN_PREFIX.sub("", line.strip().strip("　")).replace("**", "").replace("__", "").strip()
        if not paragraph:
            continue
        paragraph = _CORNER_QUOTED.sub(r"“\1”", paragraph)
        paragraphs.append(_ASCII_QUOTED.sub(r"“\1”", paragraph))
    if paragraphs and _PREFACE_LINE.match(paragraphs[0]):
        paragraphs = paragraphs[1:]
    # The renderer owns the 第N集 line; a draft that opens with its own would double it.
    if paragraphs and EPISODE_HEADING.match(paragraphs[0]):
        paragraphs = paragraphs[1:]
    if paragraphs and _CLOSING_LINE.match(paragraphs[-1]):
        paragraphs = paragraphs[:-1]
    return "\n\n".join(paragraphs)


def utterances_of(scenes: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    spoken: list[dict[str, str]] = []
    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        for utterance in scene.get("utterances") or []:
            if not isinstance(utterance, Mapping):
                continue
            text = str(utterance.get("text") or "").strip()
            if text:
                spoken.append({
                    "scene_id": str(scene.get("scene_id") or ""),
                    "kind": str(utterance.get("kind") or "dialogue"),
                    "speaker": str(utterance.get("speaker") or "").strip(),
                    "text": text,
                })
    return spoken


def _find_in_order(haystack: str, fragments: Sequence[str], start: int) -> int:
    """End offset after matching every fragment in order from ``start``; -1 when one is missing."""
    cursor = start
    for fragment in fragments:
        found = haystack.find(fragment, cursor)
        if found == -1:
            return -1
        cursor = found + len(fragment)
    return cursor


def spoken_verbatim_in(source: str, line: str, *, max_gap: int = 120) -> bool:
    """Is ``line`` spoken word for word in ``source``, allowing action beats between its clauses?

    A prose script splits one spoken line around what the speaker does, so the line is
    not a substring of the source even though not a character of it was changed. Each
    clause must follow the previous one within ``max_gap`` characters, which is an
    action beat, not another part of the story.
    """
    fragments = [_fold(part) for part in _fragments(line)]
    if not fragments:
        return True
    folded = _fold(source)
    start = folded.find(fragments[0])
    while start != -1:
        cursor = start + len(fragments[0])
        for fragment in fragments[1:]:
            found = folded.find(fragment, cursor, cursor + max_gap + len(fragment))
            if found == -1:
                break
            cursor = found + len(fragment)
        else:
            return True
        start = folded.find(fragments[0], start + 1)
    return False


def missing_utterances(prose: str, scenes: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Plan utterances whose words do not all appear, in order, in ``prose``.

    A line may be split around an action beat at its own punctuation, so the
    match is on the punctuation-free fragments of the line, not on the whole string.
    """
    folded = _fold(prose)
    cursor = 0
    missing: list[dict[str, str]] = []
    for utterance in utterances_of(scenes):
        fragments = [_fold(part) for part in _fragments(utterance["text"])]
        if not fragments:
            continue
        end = _find_in_order(folded, fragments, cursor)
        if end == -1:
            # Prose may tell two beats in a different order than the shot list.
            end = _find_in_order(folded, fragments, 0)
            if end == -1:
                missing.append(utterance)
                continue
        else:
            cursor = end
    return missing


def invented_dialogue(prose: str, scenes: Sequence[Mapping[str, Any]]) -> list[str]:
    """Quoted speech in ``prose`` that no plan utterance contains.

    Only quotes that read as spoken lines count: 那个“死”字 is emphasis, not dialogue.
    """
    corpus = _fold("\n".join(utterance["text"] for utterance in utterances_of(scenes)))
    invented: list[str] = []
    for quoted in _QUOTED.findall(prose):
        content = quoted.strip()
        if len(_fold(content)) < 4 or not _SPOKEN_TAIL.search(content):
            continue
        fragments = [_fold(part) for part in _fragments(content)]
        if any(len(fragment) >= 2 and fragment not in corpus for fragment in fragments):
            invented.append(content)
    return invented


def check_prose(prose: str, scenes: Sequence[Mapping[str, Any]], *, character_names: Sequence[str] = ()) -> ProseCheck:
    """Does ``prose`` read as prose, and does it say exactly what the plan says?"""
    result = ProseCheck()
    shots = [scene for scene in scenes if isinstance(scene, Mapping)]
    minimum = max(_MIN_CHARS, _MIN_CHARS_PER_SHOT * len(shots))
    if len(_fold(prose)) < minimum:
        result.errors.append(f"正文过短（不足 {minimum} 字）：请把每个分镜的画面、动作与台词都写成完整的叙事段落")
        return result

    names = sorted({str(name).strip() for name in character_names if str(name).strip()}, key=len, reverse=True)
    speaker_line = (
        re.compile(r"^(?:" + "|".join(re.escape(name) for name in names) + r")\s*(?:[（(][^（()）]*[)）])?\s*[：:]")
        if names else None
    )
    labelled: list[str] = []
    scripted: list[str] = []
    headings: list[str] = []
    for line in prose.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if EPISODE_HEADING.match(stripped):
            headings.append(stripped[:24])
        elif _LABEL_LINE.match(stripped) or _SCENE_ID.search(stripped):
            labelled.append(stripped[:24])
        elif speaker_line is not None and speaker_line.match(stripped):
            scripted.append(stripped[:24])
    if headings:
        result.errors.append("正文里不要出现「第N集」标题行（系统会自动加上）：" + " / ".join(headings[:_MAX_REPORTED]))
    if labelled:
        result.errors.append(
            "正文出现了分镜表的标签行或分镜编号（场景 / 镜头 / 画面 / 旁白 / E1S01 等），请改写为叙事句：" + " / ".join(labelled[:_MAX_REPORTED])
        )
    if scripted:
        result.errors.append(
            "正文出现了「角色名：台词」的剧本体对白，请改为小说体——台词放进中文引号“”，说话人与动作写在引号前后：" + " / ".join(scripted[:_MAX_REPORTED])
        )

    missing = missing_utterances(prose, shots)
    if missing:
        listed = "；".join(
            f"{item['speaker'] or '旁白'}「{item['text'][:40]}」" for item in missing[:_MAX_REPORTED]
        )
        result.errors.append(
            f"有 {len(missing)} 句已定稿的口播没有逐字出现在正文里（不得改字、删字、换说法，只允许在原有标点处被动作隔开）：{listed}"
        )

    invented = invented_dialogue(prose, shots)
    if invented:
        result.warnings.append(
            "正文出现了分镜里没有的台词，请删除或改为叙述：" + "；".join(f"「{item[:30]}」" for item in invented[:_MAX_REPORTED])
        )
    parens = _STAGE_PAREN.findall(prose)
    if parens:
        result.warnings.append("正文不要用括号写舞台提示或心理暗示，请改为叙述动作：" + " ".join(parens[:_MAX_REPORTED]))
    return result


# --------------------------------------------------------------------------- synthesis


def _sentence(text: str) -> str:
    cleaned = " ".join(str(text or "").replace("\x00", "").split())
    if not cleaned:
        return ""
    return cleaned if re.search(r"[。！？…—”!?]$", cleaned) else cleaned + "。"


def prose_from_scenes(scenes: Sequence[Mapping[str, Any]]) -> str:
    """Plain prose assembled from the plan itself, for an episode that has no authored body.

    Every spoken line leads its own paragraph inside “” with the speaker after it,
    so the text never takes the ``角色：台词`` shape the dashboard reads as a script.
    """
    paragraphs: list[str] = []
    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        description = _sentence(scene.get("scene_description") or "")
        if description:
            # 第N集 opens an episode everywhere downstream; a body paragraph must never read as one.
            paragraphs.append(f"画面里，{description}" if EPISODE_HEADING.match(description) else description)
        for utterance in scene.get("utterances") or []:
            if not isinstance(utterance, Mapping):
                continue
            text = " ".join(str(utterance.get("text") or "").split())
            if not text:
                continue
            speaker = " ".join(str(utterance.get("speaker") or "").split())
            if utterance.get("kind") == "dialogue" and speaker:
                paragraphs.append(f"“{text}”{speaker}说。")
            else:
                paragraphs.append(_sentence(text))
    return "\n\n".join(paragraphs)


def prose_revision_source(scenes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The plan fields a prose body is written from; an edit elsewhere leaves the prose valid."""
    projected: list[dict[str, Any]] = []
    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        projected.append({
            "scene_id": str(scene.get("scene_id") or ""),
            "setting": scene.get("setting"),
            "scene_description": scene.get("scene_description"),
            "utterances": [
                {"kind": item.get("kind"), "speaker": item.get("speaker"), "text": item.get("text")}
                for item in (scene.get("utterances") or []) if isinstance(item, Mapping)
            ],
        })
    return projected


def has_episode_heading(text: str, episode: int) -> bool:
    """Does ``text`` already carry its own 第N集 heading for ``episode``?"""
    return any(episode_label_number(match.group(1)) == int(episode) for match in EPISODE_HEADING.finditer(text or ""))


__all__ = [
    "ProseCheck",
    "check_prose",
    "has_episode_heading",
    "invented_dialogue",
    "missing_utterances",
    "normalize_prose",
    "prose_from_scenes",
    "prose_revision_source",
    "spoken_verbatim_in",
    "utterances_of",
]

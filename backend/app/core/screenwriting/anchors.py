# -*- coding: utf-8 -*-
"""Resolve ``end_anchor`` snippets into episode boundaries inside a source window.

An episode is "everything after the previous episode's end up to and including
its own anchor". Anchors are first matched byte-for-byte; when that fails they
are matched on a punctuation/whitespace-folded copy of the window (full-width
vs. half-width punctuation, any whitespace as one space). The fold is strictly
one character to one character so offsets on the folded copy are offsets on the
normalized source.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

_PUNCT_FOLD: dict[str, str] = {
    "。": ".", "．": ".", "，": ",", "！": "!", "？": "?", "：": ":", "；": ";",
    "（": "(", "）": ")", "～": "~", "〜": "~",
    "“": '"', "”": '"', "‘": "'", "’": "'", "＂": '"', "＇": "'",
}
assert all(len(value) == 1 for value in _PUNCT_FOLD.values())


class AnchorRejected(ValueError):
    """The drafted anchors cannot be resolved; ``reasons`` go back to the model verbatim."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def normalize_source_text(text: str) -> str:
    """NFC + unified newlines: the coordinate system every ledger offset lives in."""
    return unicodedata.normalize("NFC", text or "").replace("\r\n", "\n").replace("\r", "\n")


def fold_for_match(text: str) -> str:
    out: list[str] = []
    for char in text:
        folded = _PUNCT_FOLD.get(char)
        if folded is not None:
            out.append(folded)
        elif char.isspace():
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


def find_all_overlapping(haystack: str, needle: str) -> list[int]:
    if not needle:
        return []
    starts: list[int] = []
    found = haystack.find(needle)
    while found != -1:
        starts.append(found)
        found = haystack.find(needle, found + 1)
    return starts


def resolve_boundaries(window: str, anchors: Sequence[str], *, snap_whitespace_tail: bool) -> list[int]:
    """Relative end offsets for each anchor; validates existence, uniqueness and ordering."""
    reasons: list[str] = []
    ends: list[int] = []
    pos = 0
    ordering_valid = True
    folded_window: str | None = None
    for index, anchor in enumerate(anchors, start=1):
        match_len = len(anchor)
        starts = find_all_overlapping(window, anchor)
        matched_by_fold = False
        if not starts:
            if folded_window is None:
                folded_window = fold_for_match(window)
            normalized = normalize_source_text(anchor)
            starts = find_all_overlapping(folded_window, fold_for_match(normalized))
            if starts:
                matched_by_fold = True
                match_len = len(normalized)
        if not starts:
            reasons.append(f"第 {index} 条的 end_anchor 在原文窗口中不存在（必须逐字摘抄，含标点）: {anchor!r}")
            ordering_valid = False
            continue
        if len(starts) > 1:
            if matched_by_fold:
                reasons.append(
                    f"第 {index} 条的 end_anchor 在标点全/半角与空白折叠后出现 {len(starts)} 次，无法唯一定位，"
                    f"请改用更长、更独特且与原文逐字一致的片段: {anchor!r}"
                )
            else:
                reasons.append(
                    f"第 {index} 条的 end_anchor 在原文窗口中出现 {len(starts)} 次，无法唯一定位，请改用更长或更独特的片段: {anchor!r}"
                )
            ordering_valid = False
            continue
        end = starts[0] + match_len
        if ordering_valid and end <= pos:
            reasons.append(f"第 {index} 条的 end_anchor 位置不在上一集结尾之后（各集范围必须连续推进、不重叠）: {anchor!r}")
            ordering_valid = False
            continue
        ends.append(end)
        pos = end
    if reasons:
        raise AnchorRejected(reasons)
    if snap_whitespace_tail and ends and ends[-1] < len(window) and not window[ends[-1]:].strip():
        ends[-1] = len(window)
    return ends


__all__ = ["AnchorRejected", "find_all_overlapping", "fold_for_match", "normalize_source_text", "resolve_boundaries"]

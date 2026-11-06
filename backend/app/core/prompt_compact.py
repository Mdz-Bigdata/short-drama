# -*- coding: utf-8 -*-
"""A prompt without what only a reader's eye needs.

The skills and guides a system prompt is assembled from are Markdown written for people: rules of box-drawing
characters, table padding, blank lines, the same sentence in two guides. A model pays for all of that by the token and
reads the same meaning without it. Nothing here shortens a sentence or drops a rule that appears once; what cuts
content is the choice of which guides to load, and that belongs to the caller.

Only system prompts come through here. A user prompt carries the person's script, which is kept exactly as written.
"""

from __future__ import annotations

import re
from functools import lru_cache

_RULE_LINE = re.compile(r"^[\s─-╿]+$")
_BOX_SIDES = re.compile(r"[│┃║]")
_BOX_RUN = re.compile(r"[─━═]{2,}")
_INNER_SPACES = re.compile(r"(?<=\S)[ \t]{2,}")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_FRONTMATTER = re.compile(r"^---\nname:.*?\n---$", re.M | re.S)
# Two sentences this long being identical is a repeat; a short one may be a list item that means something in each place.
_MIN_REPEAT_CHARS = 30
_CJK = re.compile(r"[⺀-鿿가-힯＀-￯]")


def estimate_tokens(text: str) -> int:
    """A rough count for comparing prompts: about one token per CJK character, about four other characters to a token."""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    return cjk + (len(text) - cjk + 3) // 4


@lru_cache(maxsize=128)
def compact_system(text: str) -> str:
    """The same instructions in fewer tokens. Same input, same output, so a provider's prefix cache still matches."""
    if not text:
        return text
    body = _FRONTMATTER.sub("", text.replace("\r\n", "\n"))
    out: list[str] = []
    seen: set[str] = set()
    fenced = False
    for raw in body.split("\n"):
        line = raw.rstrip()
        marker = line.lstrip().startswith("```")
        if marker:
            fenced = not fenced
        if not line.strip() or _RULE_LINE.match(line):
            continue
        # Inside a code block the layout can be the template the model is told to fill in.
        if fenced or marker:
            out.append(line)
            continue
        line = _BOX_RUN.sub("─", _BOX_SIDES.sub(" ", line))
        line = _INNER_SPACES.sub(" ", line).rstrip()
        if not line.strip():
            continue
        if _TABLE_RULE.match(line):
            line = "|" + "-|" * max(1, line.count("|") - 1)
        elif len(line.strip()) >= _MIN_REPEAT_CHARS:
            key = line.strip()
            if key in seen:
                continue
            seen.add(key)
        out.append(line)
    return "\n".join(out)


__all__ = ["compact_system", "estimate_tokens"]

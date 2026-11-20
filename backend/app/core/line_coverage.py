"""Every scripted line of a scene is in the storyboard table: once, in the script's order.

The table's dialogue column is the only place stage 5 reads lines from (subtitles, dubbing, the H3 verbatim
check, the clip's length), so a line the table leaves out is gone from the film, and a line written twice is
said twice. Nothing checked this: the stage prompt only asks for the whole scene to be covered.

What is compared is what is spoken: the script's ``dialogue`` entries of the configured kinds, and the table's
lines as :func:`spoken_lines` reads them, both without punctuation and spacing. A line split over two
moments, or two lines written in one cell, still match. A line is *missing* when it is nowhere in the table,
*out of order* when it is only found before the previous line's place, and written too often when whole table
lines equal to it outnumber the script's own repeats (so a short line inside a longer one is not counted).

Kinds and sentences are in ``app/data/prompt/line_coverage.json``.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from app.core import prompt_data
from app.core.spoken_lines import spoken_lines

_DATA = "line_coverage"
_NOISE = re.compile(r"[\s\W_]+")


def _says(key: str, **values: object) -> str:
    return prompt_data.text(_DATA, key).format(**values)


def _key(text: object) -> str:
    return _NOISE.sub("", str(text or ""))


def scripted_lines(scene: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(speaker, text) of the scene's lines that belong in the dialogue column, in the script's order."""
    raw = scene.get("dialogue")
    if isinstance(raw, str):
        try:
            raw = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return []
    kinds = set(prompt_data.words(_DATA, "kinds"))
    found: list[tuple[str, str]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, Mapping) or str(entry.get("kind") or "dialogue") not in kinds:
            continue
        text = str(entry.get("text") or "").strip()
        if _key(text):
            found.append((str(entry.get("speaker") or "").strip() or prompt_data.text(_DATA, "unnamed_speaker"), text))
    return found


def table_issues(shots: Sequence[Mapping[str, Any]], scene: Mapping[str, Any]) -> list[str]:
    """One sentence per scripted line the table leaves out, puts out of order, or writes too often."""
    script = scripted_lines(scene)
    if not script:
        return []
    table = [_key(line) for shot in shots for line in spoken_lines([str(shot.get("dialogue") or "")])]
    stream = "".join(table)
    issues: list[str] = []
    position, previous = 0, ""
    for speaker, text in script:
        key = _key(text)
        at = stream.find(key, position)
        if at >= 0:
            position, previous = at + len(key), text
        elif key in stream:
            issues.append(_says("out_of_order", line=text, before=previous))
        else:
            issues.append(_says("missing", speaker=speaker, line=text))
    wanted = Counter(_key(text) for _, text in script)
    written = Counter(table)
    shown = {_key(text): text for _, text in script}
    for key, expected in wanted.items():
        if written[key] > expected:
            issues.append(_says("extra", line=shown[key], count=written[key], expected=expected))
    return issues


def film_missing(scenes: Sequence[Mapping[str, Any]], subtitles: Sequence[str]) -> list[tuple[str, str]]:
    """(speaker, line) of each scripted line that no subtitle of the cut carries: the last look before delivery.

    The table can hold every line and the film still lose one: a subtitle edited by hand, or a shot cut from the
    timeline. Compared without punctuation, so a line split over two shots or two lines in one subtitle still match.
    """
    stream = "".join(_key(text) for text in subtitles)
    return [(speaker, text) for scene in scenes for speaker, text in scripted_lines(scene) if _key(text) not in stream]

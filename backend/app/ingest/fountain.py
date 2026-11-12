"""Fountain (.fountain / .spmd) to the plain script text every later stage reads.

The result is deliberately not Fountain any more: the screenplay parser and the
story graph recognise ``NAME：dialogue``, ``INT. X - NIGHT`` and ``内景：X - 夜``,
so each element is written in the form they already understand. Episodes,
characters and scenes then come out exactly as they do for any other upload.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from app.core import prompt_data


_WORDING_FILE = "fountain"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/fountain.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

_REMOVED = "\x01"
_BONEYARD = re.compile(r"/\*.*?\*/", re.S)
_NOTE = re.compile(r"\[\[.*?\]\]", re.S)

_TITLE_KEYS = {
    "title", "credit", "author", "authors", "source", "draft date", "date", "contact", "copyright",
    "notes", "revision", _text_of("module.title_keys"), _text_of("module.title_keys.2"), _text_of("module.title_keys.3"), _text_of("module.title_keys.4"), _text_of("module.title_keys.5"), _text_of("module.title_keys.6"), _text_of("module.title_keys.7"), _text_of("module.title_keys.8"), _text_of("module.title_keys.9"), _text_of("module.title_keys.10"),
}
_TITLE_LINE = re.compile(r"^([^\s:：][^:：]{0,30})[:：]\s*(.*)$")
_TITLE_NAMES = _words_of("module.title_names")

_EN_HEADING = re.compile(r"^(INT\./EXT|INT/EXT|I/E|INT|EXT|EST)(?:\.|\s)\s*(.*)$", re.I)
_SCENE_NUMBER = re.compile(r"\s*#[\w.\-]+#\s*$")
_CN_INT_EXT = re.compile(_text_of("module.cn_int_ext"))
_CN_NUMBERED = re.compile(_text_of("module.cn_numbered"))
_CN_LEADING_NUMBER = re.compile(r"^\d+(?:\s*[-－—.]\s*\d+)?[\s、.．]+(.+)$")
_CN_SEPARATOR = re.compile(r"[\s·,，、/\-–—]+")
_CN_TIMES = {
    _text_of("module.cn_times"), _text_of("module.cn_times.2"), _text_of("module.cn_times.3"), _text_of("module.cn_times.4"), _text_of("module.cn_times.5"), _text_of("module.cn_times.6"), _text_of("module.cn_times.7"), _text_of("module.cn_times.8"), _text_of("module.cn_times.9"), _text_of("module.cn_times.10"), _text_of("module.cn_times.11"), _text_of("module.cn_times.12"), _text_of("module.cn_times.13"), _text_of("module.cn_times.14"), _text_of("module.cn_times.15"), _text_of("module.cn_times.16"),
    _text_of("module.cn_times.17"), _text_of("module.cn_times.18"), _text_of("module.cn_times.19"), _text_of("module.cn_times.20"), _text_of("module.cn_times.21"), _text_of("module.cn_times.22"), _text_of("module.cn_times.23"), _text_of("module.cn_times.24"),
}
_CN_SIDES = {_text_of("module.cn_sides"): _text_of("module.cn_sides.2"), _text_of("module.cn_sides.3"): _text_of("module.cn_sides.4"), _text_of("module.cn_sides.5"): _text_of("module.cn_sides.6"), _text_of("module.cn_sides.7"): _text_of("module.cn_sides.8"), _text_of("module.cn_sides.9"): _text_of("module.cn_sides.10"), _text_of("module.cn_sides.11"): _text_of("module.cn_sides.12")}

_SECTION = re.compile(r"^#{1,6}\s*(.*)$")
_EPISODE_CN = re.compile(_text_of("module.episode_cn"))
_EPISODE_EN = re.compile(r"^(?:episode|ep\.?)\s*(\d{1,3})\b[\s:：.\-–—]*(.*)$", re.I)
_PAGE_BREAK = re.compile(r"^={3,}\s*$")

_TRANSITION_EN = re.compile(r"^[^a-z]*\bTO:$")
_TRANSITION_CN = re.compile(_text_of("module.transition_cn"))
# What the screenplay parser recognises as a transition; anything else gets the 转场 label it also recognises.
_TRANSITION_KNOWN = re.compile(
    _text_of("module.transition_known"),
    re.I,
)

_PARENTHETICAL = re.compile(r"^[（(](.+)[）)]$")
_CUE_EXTENSION = re.compile(r"\s*[（(]([^）)]*)[）)]\s*$")
_CJK_NAME = re.compile(_text_of("module.cjk_name"))
_NOT_A_NAME_START = _text_of("module.not_a_name_start")
_CONTINUED = re.compile(_text_of("module.continued"), re.I)
# Names the parser can read as ``NAME: text``; others need the cue on its own line.
_INLINE_NAME = re.compile(_text_of("module.inline_name"))
# Action the parser would otherwise take for a cue, a heading or a parenthetical.
_MISREAD_ACTION = re.compile(
    _text_of("module.misread_action"),
    re.I,
)
_ACTION_LABEL = _text_of("module.action_label")

_EMPHASIS = (
    (re.compile(r"(?<!\\)\*\*\*(?=\S)(.+?)(?<=\S)(?<!\\)\*\*\*"), r"\1"),
    (re.compile(r"(?<!\\)\*\*(?=\S)(.+?)(?<=\S)(?<!\\)\*\*"), r"\1"),
    (re.compile(r"(?<!\\)\*(?=\S)(.+?)(?<=\S)(?<!\\)\*"), r"\1"),
    (re.compile(r"(?<![A-Za-z0-9\\])_(?=\S)(.+?)(?<=\S)(?<!\\)_(?![A-Za-z0-9])"), r"\1"),
)


@dataclass
class FountainScript:
    text: str
    title: str | None = None
    title_page: dict[str, str] = field(default_factory=dict)


def _plain(value: str) -> str:
    for pattern, replacement in _EMPHASIS:
        value = pattern.sub(replacement, value)
    return re.sub(r"\\([*_\\])", r"\1", value).strip()


def _strip_hidden(text: str) -> str:
    """Remove boneyard and notes; a line holding nothing else goes too, so it cannot end a dialogue block."""
    marked = _NOTE.sub(_REMOVED, _BONEYARD.sub(_REMOVED, text))
    kept: list[str] = []
    for line in marked.split("\n"):
        if _REMOVED in line:
            line = line.replace(_REMOVED, "")
            if not line.strip():
                continue
        kept.append(line)
    return "\n".join(kept)


def _take_title_page(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return {}, lines
    match = _TITLE_LINE.match(lines[first].strip())
    if not match or match.group(1).strip().lower() not in _TITLE_KEYS:
        return {}, lines
    page: dict[str, str] = {}
    key = ""
    index = first
    while index < len(lines) and lines[index].strip():
        line = lines[index]
        match = _TITLE_LINE.match(line.strip()) if not line[:1].isspace() else None
        if match:
            key = match.group(1).strip().lower()
            page[key] = _plain(match.group(2))
        elif key:
            page[key] = " ".join(part for part in (page[key], _plain(line)) if part)
        index += 1
    return page, lines[index:]


def _cn_heading_parts(tokens: list[str]) -> tuple[str, str, str] | None:
    side = next((token for token in tokens if token in _CN_SIDES), "")
    time = next((token for token in tokens if token in _CN_TIMES), "")
    location = " ".join(token for token in tokens if token not in {side, time})
    return (_CN_SIDES.get(side, ""), location, time) if location else None


def _cn_side_line(side: str, location: str, time: str) -> str:
    return f"{side}：{location} - {time}" if time else f"{side}：{location}"


def _chinese_heading(line: str) -> str | None:
    side = _CN_INT_EXT.match(line)
    if side and side.group(2).strip():
        tokens = [token for token in _CN_SEPARATOR.split(side.group(2).strip()) if token]
        parts = _cn_heading_parts(tokens)
        if parts:
            return _cn_side_line(side.group(1), parts[1], parts[2])
    numbered = _CN_NUMBERED.match(line)
    if numbered:
        tokens = [token for token in _CN_SEPARATOR.split(numbered.group(2).strip()) if token]
        parts = _cn_heading_parts(tokens)
        if parts:
            if parts[0]:
                return _cn_side_line(parts[0], parts[1], parts[2])
            label = re.sub(r"\s+", "", numbered.group(1))
            return f"{label} {parts[1]} - {parts[2]}" if parts[2] else f"{label} {parts[1]}"
    # "1-1 日 内 办公室", "办公室 夜 内": a time and a side are what make these headings, not prose.
    leading = _CN_LEADING_NUMBER.match(line)
    body = leading.group(1) if leading else line
    tokens = [token for token in _CN_SEPARATOR.split(body.strip()) if token]
    if len(tokens) >= 2 and not re.search(r"[。！？!?，,：:；;“”\"]", body):
        parts = _cn_heading_parts(tokens)
        if parts and parts[2] and parts[0]:
            return _cn_side_line(parts[0], parts[1], parts[2])
    return None


def _english_heading(line: str) -> str | None:
    match = _EN_HEADING.match(line)
    if not match or not match.group(2).strip():
        return None
    kind = match.group(1).upper()
    if kind == "EST":
        kind = "EXT"
    elif kind in {"INT./EXT", "INT/EXT", "I/E"}:
        kind = "INT/EXT"
    return f"{kind}. {match.group(2).strip()}"


def _heading(line: str, *, forced: bool, scene_number: int) -> str | None:
    bare = _SCENE_NUMBER.sub("", line).strip()
    heading = _english_heading(bare) or _chinese_heading(bare)
    if heading or not forced:
        return heading
    # A forced heading with no interior/exterior ("雨夜客厅") still has to open a scene downstream.
    tokens = [token for token in _CN_SEPARATOR.split(bare) if token]
    time = tokens[-1] if len(tokens) > 1 and tokens[-1] in _CN_TIMES else ""
    location = " ".join(tokens[:-1]) if time else bare
    return _text_of("_heading.text").format(scene_number, location, time) if time else _text_of("_heading.text.2").format(scene_number, location)


def _cue(line: str, *, previous_blank: bool, next_blank: bool) -> tuple[str, str] | None:
    """(name, direction) when the line starts a dialogue block."""
    forced = line.startswith("@")
    if not previous_blank or next_blank:
        return None
    body = line[1:].strip() if forced else line.rstrip("^").strip()
    if forced:
        body = body.rstrip("^").strip()
    directions: list[str] = []
    while True:
        extension = _CUE_EXTENSION.search(body)
        if not extension:
            break
        if not _CONTINUED.match(extension.group(1).strip()):
            directions.insert(0, extension.group(1).strip())
        body = body[:extension.start()].strip()
    if not body:
        return None
    if not forced:
        letters = re.sub(r"[^A-Za-z]", "", body)
        if letters:
            if letters != letters.upper() or re.search(_text_of("_cue.text"), body) or body.endswith("TO:"):
                return None
        elif not _CJK_NAME.match(body) or body[0] in _NOT_A_NAME_START:
            # Chinese has no capitals to mark a cue, so only a bare name-sized line qualifies.
            return None
    return body, "，".join(item for item in directions if item)


def _dialogue_rows(name: str, direction: str, lines: list[str]) -> list[str]:
    rows: list[tuple[str, list[str]]] = [(direction, [])]
    for raw in lines:
        line = raw.strip()
        parenthetical = _PARENTHETICAL.match(line)
        if parenthetical:
            if rows[-1][1] or rows[-1][0]:
                rows.append((_plain(parenthetical.group(1)), []))
            else:
                rows[-1] = (_plain(parenthetical.group(1)), [])
            continue
        if line:
            rows[-1][1].append(_plain(line.lstrip("~").strip()))
    rendered: list[str] = []
    for lead, parts in rows:
        spoken = ""
        for part in parts:
            # Latin words need a space when joined; Chinese must not get one.
            gap = " " if spoken and spoken[-1].isascii() and part[:1].isascii() else ""
            spoken += gap + part
        lead_text = f"（{lead}）" if lead else ""
        if not (lead_text or spoken):
            continue
        if _INLINE_NAME.match(name):
            separator = ": " if name.isascii() else "："
            rendered.append(f"{name}{separator}{lead_text}{spoken}")
        else:
            rendered.append(f"{name}\n{lead_text}{spoken}" if spoken or lead_text else name)
    return rendered


def _guarded(action: str) -> str:
    return f"{_ACTION_LABEL}{action}" if _MISREAD_ACTION.match(action) else action


def _transition_line(value: str) -> str:
    value = _plain(value)
    return value if _TRANSITION_KNOWN.match(value) else _text_of("_transition_line.text").format(value)


def parse_fountain(source: str) -> FountainScript:
    text = source.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    text = _strip_hidden(text)
    title_page, lines = _take_title_page(text.split("\n"))

    blocks: list[str] = []
    action: list[str] = []
    scene_number = 0
    index = 0

    def flush_action() -> None:
        if action:
            blocks.append("\n".join(action))
            action.clear()

    while index < len(lines):
        raw = lines[index]
        line = raw.strip()
        previous_blank = index == 0 or not lines[index - 1].strip()
        next_blank = index + 1 >= len(lines) or not lines[index + 1].strip()
        index += 1

        if not line:
            flush_action()
            continue
        if _PAGE_BREAK.match(line) or (line.startswith("=") and not line.startswith("==")):
            continue  # page breaks and synopses do not print
        section = _SECTION.match(line)
        if section:
            flush_action()
            heading = _plain(section.group(1))
            episode = _EPISODE_EN.match(heading)
            if episode:
                blocks.append(_text_of("parse_fountain.text").format(int(episode.group(1)), episode.group(2).strip()).rstrip())
            elif _EPISODE_CN.search(heading):
                blocks.append(heading)
            continue

        if line.startswith("!"):
            forced_action = _plain(line[1:])
            action.append(f"{_ACTION_LABEL}{forced_action}" if forced_action else "")
            continue

        forced_heading = line.startswith(".") and len(line) > 1 and (line[1].isalnum() or _text_of("parse_fountain.forced_heading") <= line[1] <= _text_of("parse_fountain.forced_heading.2"))
        heading = None
        if forced_heading:
            heading = _heading(_plain(line[1:]), forced=True, scene_number=scene_number + 1)
        elif previous_blank:
            heading = _heading(_plain(line), forced=False, scene_number=scene_number + 1)
        if heading:
            flush_action()
            scene_number += 1
            blocks.append(heading)
            continue

        if line.startswith(">") and line.endswith("<"):
            action.append(_guarded(_plain(line[1:-1])))  # centred text
            continue
        if line.startswith(">"):
            flush_action()
            blocks.append(_transition_line(line[1:]))
            continue
        if previous_blank and next_blank and (_TRANSITION_EN.match(line) or _TRANSITION_CN.match(line)):
            flush_action()
            blocks.append(_transition_line(line))
            continue

        cue = _cue(line, previous_blank=previous_blank, next_blank=next_blank)
        if cue:
            flush_action()
            spoken: list[str] = []
            while index < len(lines):
                following = lines[index]
                # Two spaces on an otherwise empty line keep the speech going.
                if not following.strip() and len(following) < 2:
                    break
                spoken.append(following)
                index += 1
            blocks.append("\n".join(_dialogue_rows(cue[0], cue[1], spoken)))
            continue

        if line.startswith("~"):
            action.append(f"♪ {_plain(line[1:])}")
            continue
        plain = _plain(line)
        # A bare "林夏：…" line stays: it is how Chinese scripts write dialogue, and the parser reads it so.
        action.append(_guarded(plain))
    flush_action()

    title = next((title_page[key] for key in _TITLE_NAMES if title_page.get(key)), None)
    return FountainScript(text="\n\n".join(block for block in blocks if block), title=title, title_page=title_page)

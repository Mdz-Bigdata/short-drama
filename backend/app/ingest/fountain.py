"""Fountain (.fountain / .spmd) to the plain script text every later stage reads.

The result is deliberately not Fountain any more: the screenplay parser and the
story graph recognise ``NAME：dialogue``, ``INT. X - NIGHT`` and ``内景：X - 夜``,
so each element is written in the form they already understand. Episodes,
characters and scenes then come out exactly as they do for any other upload.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_REMOVED = "\x01"
_BONEYARD = re.compile(r"/\*.*?\*/", re.S)
_NOTE = re.compile(r"\[\[.*?\]\]", re.S)

_TITLE_KEYS = {
    "title", "credit", "author", "authors", "source", "draft date", "date", "contact", "copyright",
    "notes", "revision", "标题", "片名", "剧名", "作者", "编剧", "来源", "日期", "联系方式", "版权", "备注",
}
_TITLE_LINE = re.compile(r"^([^\s:：][^:：]{0,30})[:：]\s*(.*)$")
_TITLE_NAMES = ("title", "标题", "片名", "剧名")

_EN_HEADING = re.compile(r"^(INT\./EXT|INT/EXT|I/E|INT|EXT|EST)(?:\.|\s)\s*(.*)$", re.I)
_SCENE_NUMBER = re.compile(r"\s*#[\w.\-]+#\s*$")
_CN_INT_EXT = re.compile(r"^(内外景|内景|外景)(?:[\s:：.。·,，、/\-–—]+)?(.*)$")
_CN_NUMBERED = re.compile(r"^(第\s*[零〇一二三四五六七八九十百千万两\d]+\s*[场幕]|场景\s*[零〇一二三四五六七八九十百千万两\d]*)\s*[:：]?\s*(.+)$")
_CN_LEADING_NUMBER = re.compile(r"^\d+(?:\s*[-－—.]\s*\d+)?[\s、.．]+(.+)$")
_CN_SEPARATOR = re.compile(r"[\s·,，、/\-–—]+")
_CN_TIMES = {
    "日", "夜", "晨", "昏", "晚", "早", "午", "白天", "夜晚", "日间", "夜间", "清晨", "早晨", "上午", "中午", "下午",
    "傍晚", "黄昏", "黎明", "凌晨", "深夜", "午夜", "夜里", "白日",
}
_CN_SIDES = {"内": "内景", "外": "外景", "内景": "内景", "外景": "外景", "内外": "内外景", "内外景": "内外景"}

_SECTION = re.compile(r"^#{1,6}\s*(.*)$")
_EPISODE_CN = re.compile(r"第\s*(?:[0-9]{1,3}|[一二三四五六七八九十]{1,4})\s*集")
_EPISODE_EN = re.compile(r"^(?:episode|ep\.?)\s*(\d{1,3})\b[\s:：.\-–—]*(.*)$", re.I)
_PAGE_BREAK = re.compile(r"^={3,}\s*$")

_TRANSITION_EN = re.compile(r"^[^a-z]*\bTO:$")
_TRANSITION_CN = re.compile(r"^(?:淡入|淡出|切至|转场|叠化|闪回)(?:[:：].*)?$")
# What the screenplay parser recognises as a transition; anything else gets the 转场 label it also recognises.
_TRANSITION_KNOWN = re.compile(
    r"^(?:FADE\s+IN:|FADE\s+OUT\.?|CUT\s+TO:|DISSOLVE\s+TO:|SMASH\s+CUT(?:\s+TO)?:|MATCH\s+CUT(?:\s+TO)?:|淡入|淡出|切至|转场)",
    re.I,
)

_PARENTHETICAL = re.compile(r"^[（(](.+)[）)]$")
_CUE_EXTENSION = re.compile(r"\s*[（(]([^）)]*)[）)]\s*$")
_CJK_NAME = re.compile(r"^[一-鿿·]{2,4}$")
_NOT_A_NAME_START = "他她它我你这那有在是把从向"
_CONTINUED = re.compile(r"^(?:cont'?d|continued|续)\.?$", re.I)
# Names the parser can read as ``NAME: text``; others need the cue on its own line.
_INLINE_NAME = re.compile(r"^[A-Za-z一-鿿][A-Za-z0-9一-鿿· ._-]{0,40}$")
# Action the parser would otherwise take for a cue, a heading or a parenthetical.
_MISREAD_ACTION = re.compile(
    r"^(?:[A-Z][A-Z0-9 ._'’-]{0,50}(?:\s*\([^)]*\))?$|(?:INT|EXT|I/E)|[（(].*[）)]$"
    r"|(?:内景|外景|内外景)\s*[：:]|(?:场景\s*[零〇一二三四五六七八九十百千万两\d]+|第\s*[零〇一二三四五六七八九十百千万两\d]+\s*[场幕]))",
    re.I,
)
_ACTION_LABEL = "动作："

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
    return f"第{scene_number}场 {location} - {time}" if time else f"第{scene_number}场 {location}"


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
            if letters != letters.upper() or re.search(r"[一-鿿]", body) or body.endswith("TO:"):
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
    return value if _TRANSITION_KNOWN.match(value) else f"转场：{value}"


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
                blocks.append(f"第{int(episode.group(1))}集 {episode.group(2).strip()}".rstrip())
            elif _EPISODE_CN.search(heading):
                blocks.append(heading)
            continue

        if line.startswith("!"):
            forced_action = _plain(line[1:])
            action.append(f"{_ACTION_LABEL}{forced_action}" if forced_action else "")
            continue

        forced_heading = line.startswith(".") and len(line) > 1 and (line[1].isalnum() or "一" <= line[1] <= "鿿")
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

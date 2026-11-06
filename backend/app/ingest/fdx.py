# -*- coding: utf-8 -*-
"""Final Draft (.fdx) to the plain script text every later stage reads.

An .fdx file already says what each paragraph is (``<Paragraph Type="Character">``), so the
elements are written out by type instead of being guessed again from bare text: a scene heading
becomes ``INT. X - NIGHT`` or ``内景：X - 夜``, a character and its speech ``NAME：台词``, a
transition ``切至：``. The screenplay parser and the story graph read those forms already, so an
.fdx upload comes out with the same episodes, characters and scenes as a Fountain one.

Only the parts a shooting script prints are kept: the cast list (sitcom), synopses, outline
elements, tag data and revision marks are left out.
"""

from __future__ import annotations

import re

from lxml import etree

from app.ingest.fountain import (
    _CONTINUED,
    _CUE_EXTENSION,
    _TITLE_KEYS,
    _TITLE_LINE,
    _TITLE_NAMES,
    FountainScript,
    _dialogue_rows,
    _guarded,
    _heading,
    _transition_line,
)

#: Paragraph types that start or belong to a speech, in the order Final Draft writes them.
_SPEECH = {"Character", "Parenthetical", "Dialogue"}
#: Printed as action: shots and custom elements have no form of their own downstream.
_AS_ACTION = {"Action", "General", "Shot"}
#: Never printed in a shooting script.
_SKIPPED = {"Cast List", "Synopsis", "Outline", "Act Break", "New Act", "End of Act"}
_SPACES = re.compile(r"[ \t ]+")


class FdxError(ValueError):
    pass


def _text(element: etree._Element) -> str:
    """The words of one paragraph: every ``<Text>`` run joined, styling dropped, breaks kept."""
    parts: list[str] = []
    for node in element.iter():
        if node.tag == "Text" and node.text:
            parts.append(node.text)
        elif node.tag == "LineBreak":
            parts.append("\n")
    lines = [_SPACES.sub(" ", line).strip() for line in "".join(parts).split("\n")]
    return "\n".join(line for line in lines if line)


def _paragraphs(content: etree._Element | None) -> list[etree._Element]:
    """Paragraphs in reading order, including the ones wrapped in ``<DualDialogue>``."""
    if content is None:
        return []
    return [node for node in content.iter("Paragraph")]


def _title(root: etree._Element) -> tuple[str | None, dict[str, str]]:
    """The title page: ``Title: X`` lines when the writer labelled them, else its first line."""
    page: dict[str, str] = {}
    first = ""
    for paragraph in _paragraphs(root.find("TitlePage/Content")):
        for line in _text(paragraph).split("\n"):
            match = _TITLE_LINE.match(line)
            if match and match.group(1).strip().lower() in _TITLE_KEYS:
                page[match.group(1).strip().lower()] = match.group(2).strip()
            elif not first and not page:
                first = line
    title = next((page[key] for key in _TITLE_NAMES if page.get(key)), None) or (first or None)
    return title, page


def _split_cue(text: str) -> tuple[str, str]:
    """``STEEL (V.O.) (CONT'D)`` → (``STEEL``, ``V.O.``); the continued marker is not a direction."""
    body = text.replace("\n", " ").rstrip("^").strip()
    directions: list[str] = []
    while True:
        extension = _CUE_EXTENSION.search(body)
        if not extension:
            break
        direction = extension.group(1).strip()
        if direction and not _CONTINUED.match(direction):
            directions.insert(0, direction)
        body = body[: extension.start()].strip()
    return body, "，".join(directions)


def render_fdx(root: etree._Element) -> FountainScript:
    """The script text of a parsed .fdx document."""
    blocks: list[str] = []
    action: list[str] = []
    scene_number = 0

    def flush_action() -> None:
        if action:
            blocks.append("\n".join(action))
            action.clear()

    paragraphs = _paragraphs(root.find("Content"))
    index = 0
    while index < len(paragraphs):
        paragraph = paragraphs[index]
        kind = str(paragraph.get("Type") or "Action").strip()
        text = _text(paragraph)
        index += 1
        if not text or kind in _SKIPPED:
            continue
        if kind == "Scene Heading":
            flush_action()
            scene_number += 1
            blocks.append(_heading(text.replace("\n", " "), forced=True, scene_number=scene_number) or text)
        elif kind == "Transition":
            flush_action()
            blocks.append(_transition_line(text.replace("\n", " ")))
        elif kind == "Character":
            flush_action()
            name, direction = _split_cue(text)
            if not name:
                continue
            spoken: list[str] = []
            while index < len(paragraphs):
                following = paragraphs[index]
                following_kind = str(following.get("Type") or "").strip()
                if following_kind not in _SPEECH - {"Character"}:
                    break
                words = _text(following)
                index += 1
                if not words:
                    continue
                if following_kind == "Parenthetical":
                    words = words.replace("\n", " ")
                    spoken.append(words if words.startswith(("(", "（")) else f"({words})")
                else:
                    spoken.extend(words.split("\n"))
            blocks.append("\n".join(_dialogue_rows(name, direction, spoken)))
        elif kind in _SPEECH:
            # Dialogue without a character above it: keep the words, as action.
            action.extend(_guarded(line) for line in text.split("\n"))
        else:
            # Action, General, Shot and any custom element.
            action.extend(_guarded(line) for line in text.split("\n"))
    flush_action()

    title, page = _title(root)
    return FountainScript(text="\n\n".join(block for block in blocks if block), title=title, title_page=page)


def parse_fdx(content: bytes) -> FountainScript:
    """Parse an .fdx upload safely (no entities, no network) and render it by element."""
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise FdxError("FDX external entities are forbidden")
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False, huge_tree=False)
        root = etree.fromstring(content, parser=parser)
    except Exception as exc:  # noqa: BLE001 - every lxml failure means the same thing to the caller
        raise FdxError("FDX could not be parsed safely") from exc
    script = render_fdx(root)
    if script.text.strip():
        return script
    # Not a Final Draft layout (no typed paragraphs): fall back to every <Text> run in order.
    text = "\n".join(node.text.strip() for node in root.iter("Text") if node.text and node.text.strip())
    return FountainScript(text=text, title=script.title, title_page=script.title_page)


__all__ = ["FdxError", "parse_fdx", "render_fdx"]

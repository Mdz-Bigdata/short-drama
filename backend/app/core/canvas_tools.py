# -*- coding: utf-8 -*-
"""The canvas's one-step tools: redraw a picture, cut a grid, read a video's shots.

Each tool is a row of data: what it takes, what it hands on, and which engine does the work.
That engine is what a person is told before running it, so it is never blurred: ``image`` calls
the image model and is paid, ``vision`` and ``text`` call a text model and are paid, ``audio``
calls ElevenLabs and is paid, ``local`` runs PIL or ffmpeg on this machine for free. Upscaling and erasing here are therefore honest
signal processing, not generative repair: the labels say so, and ``enhance`` is the model route.

Nothing here touches the disk or a model; see ``app.service.canvas_tool_ops`` for that.

Behavioural reference: the tool lists in DramaClaw's README (Elastic License 2.0). The prompts,
parameters and style looks are this project's own; see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field
from app.core import prompt_data


_WORDING_FILE = "canvas_tools"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/canvas_tools.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

_STYLE_WALL = Path(__file__).resolve().parents[1] / "data" / "style_wall.json"

ENGINES = ("image", "vision", "text", "audio", "local")
IMAGE_INPUT = {"image": ("reference", "ref_image"), "style": ("reference", "style"), "text": ("dependency", "prompt"), "capture": ("reference", "ref_capture")}
VIDEO_INPUT = {"video": ("reference", "ref_video")}
TEXT_INPUT = {"text": ("dependency", "prompt"), "image": ("reference", "ref_image")}


class CanvasToolError(ValueError):
    """A tool cannot run on what it was given; the message says what to change."""


@dataclass(frozen=True)
class CanvasTool:
    id: str
    label: str
    group: str
    engine: str
    output: str
    # Output type of the upstream node -> (edge kind, role): the same shape as studio_canvas's table.
    inputs: Mapping[str, tuple[str, str]] = field(default_factory=lambda: IMAGE_INPUT)
    # At least this many pictures / clips have to arrive.
    images: int = 0
    videos: int = 0
    needs_prompt: bool = False


TOOLS: tuple[CanvasTool, ...] = (
    CanvasTool("redraw", _text_of("module.tools"), "image", "image", "image", images=1, needs_prompt=True),
    CanvasTool("outpaint", _text_of("module.tools.2"), "image", "image", "image", images=1),
    CanvasTool("relight", _text_of("module.tools.3"), "image", "image", "image", images=1),
    CanvasTool("multi_view", _text_of("module.tools.4"), "image", "image", "image", images=1),
    CanvasTool("style_transfer", _text_of("module.tools.5"), "image", "image", "image", images=1),
    CanvasTool("template_edit", _text_of("module.tools.6"), "image", "image", "image", images=1),
    CanvasTool("enhance", _text_of("module.tools.7"), "image", "image", "image", images=1),
    CanvasTool("upscale_image", _text_of("module.tools.8"), "image", "local", "image", images=1),
    CanvasTool("grid_cell", _text_of("module.tools.9"), "image", "local", "image", images=1),
    CanvasTool("composite", _text_of("module.tools.10"), "image", "local", "image", images=3),
    CanvasTool("reverse_prompt", _text_of("module.tools.11"), "image", "vision", "text", images=1),
    CanvasTool("mark_detect", _text_of("module.tools.12"), "image", "vision", "text", images=1),
    CanvasTool("video_upscale", _text_of("module.tools.13"), "video", "local", "video", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("video_erase", _text_of("module.tools.14"), "video", "local", "video", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("audio_extract", _text_of("module.tools.15"), "video", "local", "audio", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("voice_isolate", _text_of("module.tools.16"), "video", "audio", "audio", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("frame_extract", _text_of("module.tools.17"), "video", "local", "image", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("to_gif", _text_of("module.tools.18"), "video", "local", "image", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("shot_analysis", _text_of("module.tools.19"), "video", "vision", "text", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("sketch", _text_of("module.tools.20"), "skill", "image", "image", images=1),
    CanvasTool("action_breakdown", _text_of("module.tools.21"), "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("link_design", _text_of("module.tools.22"), "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("frame_bridge", _text_of("module.tools.23"), "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("script_write", _text_of("module.tools.24"), "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("shot_table", _text_of("module.tools.25"), "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("svg_art", _text_of("module.tools.26"), "skill", "text", "image", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("html_page", _text_of("module.tools.27"), "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("frame_from_context", _text_of("module.tools.28"), "skill", "image", "image", needs_prompt=True),
    CanvasTool("set_background", _text_of("module.tools.29"), "skill", "image", "image", images=2),
    CanvasTool("scene_360", _text_of("module.tools.30"), "skill", "image", "image", needs_prompt=True),
    CanvasTool("frame_review", _text_of("module.tools.31"), "skill", "vision", "text", images=1),
    CanvasTool("beat_plan", _text_of("module.tools.32"), "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
)
_BY_ID = {tool.id: tool for tool in TOOLS}
DEFAULT_TOOL = "redraw"

# Names shown in a <select> and in prompts, per parameter value.
OUTPAINT_RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4, "1:1": 1.0, "21:9": 21 / 9, "2:3": 2 / 3}
_LIGHTS = {
    "golden": _text_of("module.lights.golden"), "noon": _text_of("module.lights.noon"), "overcast": _text_of("module.lights.overcast"),
    "night": _text_of("module.lights.night"), "neon": _text_of("module.lights.neon"), "rembrandt": _text_of("module.lights.rembrandt"),
    "backlit": _text_of("module.lights.backlit"), "candle": _text_of("module.lights.candle"),
}
_VIEWS = {
    "front": _text_of("module.views.front"), "left": _text_of("module.views.left"), "right": _text_of("module.views.right"), "back": _text_of("module.views.back"), "three_quarter": _text_of("module.views.three_quarter"),
    "top": _text_of("module.views.top"), "low": _text_of("module.views.low"),
}
_TEMPLATES = {
    "remove_people": _text_of("module.templates.remove_people"),
    "change_outfit": _text_of("module.templates.change_outfit"),
    "change_expression": _text_of("module.templates.change_expression"),
    "change_weather": _text_of("module.templates.change_weather"),
    "add_prop": _text_of("module.templates.add_prop"),
    "remove_text": _text_of("module.templates.remove_text"),
}
_TEMPLATES_NEED_TEXT = frozenset({"change_outfit", "change_expression", "change_weather", "add_prop"})
_KEEP = _text_of("module.keep")
_NO_TEXT = _text_of("module.no_text")

BEAT_SYSTEM = (
    _text_of("module.beat_system")
)
BEAT_FORMAT = (
    _text_of("module.beat_format")
)
REVERSE_SYSTEM = _text_of("module.reverse_system")
REVERSE_PROMPT = (
    _text_of("module.reverse_prompt")
)
MARK_SYSTEM = _text_of("module.mark_system")
MARK_PROMPT = (
    _text_of("module.mark_prompt")
)
REVIEW_SYSTEM = _text_of("module.review_system")
REVIEW_PROMPT = (
    _text_of("module.review_prompt")
)
SHOT_SYSTEM = _text_of("module.shot_system")
SHOT_PROMPT = (
    _text_of("module.shot_prompt")
)
SCRIPT_SYSTEM = _text_of("module.script_system")
SCRIPT_PROMPT = (
    _text_of("module.script_prompt")
)
LINK_SYSTEM = _text_of("module.link_system")
LINK_PROMPT = (
    _text_of("module.link_prompt")
)

FRAME_BRIDGE_SYSTEM = _text_of("module.frame_bridge_system")
FRAME_BRIDGE_PROMPT = (
    _text_of("module.frame_bridge_prompt")
)

SHOT_TABLE_SYSTEM = _text_of("module.shot_table_system")
SHOT_TABLE_PROMPT = (
    _text_of("module.shot_table_prompt")
)
SVG_SYSTEM = _text_of("module.svg_system")
SVG_PROMPT = _text_of("module.svg_prompt")
HTML_SYSTEM = _text_of("module.html_system")
HTML_PROMPT = _text_of("module.html_prompt")
OUTPAINT_INSTRUCTION = _text_of("module.outpaint_instruction")


class StyleLook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    group: str = Field(min_length=1, max_length=20)
    names: dict[str, str]
    prompt: str = Field(min_length=10, max_length=400)
    swatch: tuple[str, str]


@lru_cache(maxsize=1)
def style_wall() -> tuple[StyleLook, ...]:
    return tuple(StyleLook.model_validate(item) for item in json.loads(_STYLE_WALL.read_text(encoding="utf-8")))


def style_look(style_id: str) -> StyleLook | None:
    return next((look for look in style_wall() if look.id == style_id), None)


def tool_of(node: Mapping[str, Any]) -> CanvasTool:
    """The tool a canvas node is set to; an unknown id (an older client, an edited file) is refused rather than guessed."""
    payload = node.get("payload") if isinstance(node.get("payload"), Mapping) else {}
    params = payload.get("params") if isinstance(payload.get("params"), Mapping) else {}
    tool = _BY_ID.get(str(params.get("tool") or DEFAULT_TOOL))
    if tool is None:
        raise CanvasToolError(_text_of("tool_of.text").format(params.get('tool')))
    return tool


def get_tool(tool_id: str) -> CanvasTool | None:
    return _BY_ID.get(tool_id)


def number(params: Mapping[str, Any], key: str, default: float, low: float, high: float) -> float:
    try:
        value = float(params.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def image_prompt(tool: CanvasTool, params: Mapping[str, Any], text: str) -> str:
    """What the image model is asked; ``text`` is what the person wrote or wired in. Refuses what could not produce a result."""
    extra = " ".join(str(text or "").split())
    if tool.id == "redraw":
        if not extra:
            raise CanvasToolError(_text_of("image_prompt.text"))
        return _text_of("image_prompt.text.2").format(extra, _NO_TEXT)
    if tool.id == "outpaint":
        return OUTPAINT_INSTRUCTION.format(ratio=outpaint_ratio(params)) + (_text_of("image_prompt.text.3").format(extra) if extra else "") + _NO_TEXT
    if tool.id == "relight":
        light = _LIGHTS.get(str(params.get("light") or "golden"), _LIGHTS["golden"])
        return _text_of("image_prompt.text.4").format(light, _KEEP, extra, _NO_TEXT)
    if tool.id == "multi_view":
        view = _VIEWS.get(str(params.get("view") or "three_quarter"), _VIEWS["three_quarter"])
        return _text_of("image_prompt.text.5").format(view, extra, _NO_TEXT)
    if tool.id == "style_transfer":
        look = style_look(str(params.get("style") or ""))
        if look is None:
            raise CanvasToolError(_text_of("image_prompt.text.6"))
        return _text_of("image_prompt.text.7").format(look.prompt, _KEEP, extra, _NO_TEXT)
    if tool.id == "template_edit":
        key = str(params.get("template") or "remove_people")
        template = _TEMPLATES.get(key)
        if template is None:
            raise CanvasToolError(_text_of("image_prompt.text.8").format(key))
        if key in _TEMPLATES_NEED_TEXT and not extra:
            raise CanvasToolError(_text_of("image_prompt.text.9"))
        return template.format(extra=extra) + (f"。{extra}" if extra and "{extra}" not in template else "。") + _NO_TEXT
    if tool.id == "enhance":
        return _text_of("image_prompt.text.10").format(extra, _NO_TEXT)
    if tool.id == "sketch":
        return _text_of("image_prompt.text.11").format(extra)
    if tool.id == "frame_from_context":
        if not extra:
            raise CanvasToolError(_text_of("image_prompt.text.12"))
        return _text_of("image_prompt.text.13").format(extra, _NO_TEXT)
    if tool.id == "set_background":
        return _text_of("image_prompt.text.14").format(extra, _NO_TEXT)
    raise CanvasToolError(_text_of("image_prompt.text.15").format(tool.label))


def outpaint_ratio(params: Mapping[str, Any]) -> str:
    ratio = str(params.get("ratio") or "16:9")
    return ratio if ratio in OUTPAINT_RATIOS else "16:9"


def beat_prompt(text: str) -> str:
    story = " ".join(str(text or "").split())
    if not story:
        raise CanvasToolError(_text_of("beat_prompt.text"))
    return _text_of("beat_prompt.text.2").format(story, BEAT_FORMAT)


def parse_beats(answer: str) -> list[dict[str, str]]:
    """The beats of a model's reply; a reply with none is a failed run, not an empty plan."""
    from app.core.screenwriting.structured_llm import extract_json_object

    data = extract_json_object(str(answer or ""))
    rows = data.get("beats") if isinstance(data, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise CanvasToolError(_text_of("parse_beats.text"))
    beats = [
        {"title": str(row.get("title") or "").strip()[:40], "prompt": str(row.get("prompt") or "").strip()[:800]}
        for row in rows if isinstance(row, Mapping) and str(row.get("prompt") or "").strip()
    ][:40]
    if not beats:
        raise CanvasToolError(_text_of("parse_beats.text.2"))
    return beats


def parse_shots(answer: str) -> list[dict[str, Any]]:
    """The rows of a shot table; a reply with none is a failed run, not an empty table."""
    from app.core.screenwriting.structured_llm import extract_json_object

    data = extract_json_object(str(answer or ""))
    rows = data.get("shots") if isinstance(data, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise CanvasToolError(_text_of("parse_shots.text"))
    shots: list[dict[str, Any]] = []
    for row in rows[:60]:
        if not isinstance(row, Mapping) or not str(row.get("desc") or "").strip():
            continue
        shots.append({
            "size": str(row.get("size") or "").strip()[:20], "motion": str(row.get("motion") or "").strip()[:20],
            "seconds": int(number(row, "seconds", 5, 2, 15)), "desc": str(row.get("desc")).strip()[:600],
            "dialogue": str(row.get("dialogue") or "").strip()[:300],
        })
    if not shots:
        raise CanvasToolError(_text_of("parse_shots.text.2"))
    return shots


def shots_text(shots: Sequence[Mapping[str, Any]]) -> str:
    lines = []
    for index, shot in enumerate(shots, 1):
        camera = "、".join(part for part in (shot["size"], shot["motion"]) if part)
        line = _text_of("shots_text.line").format(index, camera + '｜' if camera else '', shot['seconds'], shot['desc'])
        lines.append(f"{line}｜「{shot['dialogue']}」" if shot["dialogue"] else line)
    return "\n".join(lines)


def shots_as_beats(shots: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """A shot table in the shape 铺成节点 takes: one first frame to draw per shot."""
    beats = []
    for index, shot in enumerate(shots, 1):
        camera = "，".join(part for part in (shot["size"], shot["motion"]) if part)
        beats.append({"title": _text_of("shots_as_beats.title").format(index), "prompt": f"{shot['desc']}{'，' + camera if camera else ''}"[:800]})
    return beats


# What an SVG may hold: shapes and paint. It is served from this origin, so anything that can run or reach out stays out.
_SVG_TAGS = frozenset({
    "svg", "g", "defs", "title", "desc", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan",
    "lineargradient", "radialgradient", "stop", "clippath", "mask", "pattern", "symbol",
})
_SVG_ATTRIBUTES = frozenset({
    "viewbox", "xmlns", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "d", "points", "fill", "fill-opacity", "fill-rule",
    "stroke", "stroke-width", "stroke-opacity", "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "opacity", "transform", "id", "offset", "stop-color",
    "stop-opacity", "gradientunits", "gradienttransform", "fx", "fy", "font-size", "font-family", "font-weight", "text-anchor", "dx", "dy", "clip-path", "clip-rule",
    "preserveaspectratio", "patternunits", "patterntransform", "maskunits",
})
_SVG_SAFE_URL = re.compile(r"url\(\s*#[\w.-]+\s*\)")


def clean_svg(answer: str) -> str:
    """The first <svg> in a reply, keeping only the elements and attributes above. Refuses what is not an SVG."""
    match = re.search(r"<svg\b.*?</svg\s*>", str(answer or ""), flags=re.S | re.I)
    if not match or "<!" in match.group(0):
        raise CanvasToolError(_text_of("clean_svg.text"))
    try:
        root = ElementTree.fromstring(match.group(0))
    except ElementTree.ParseError as error:
        raise CanvasToolError(_text_of("clean_svg.text.2")) from error

    def local(name: str) -> str:
        return name.rsplit("}", 1)[-1].lower()

    def clean(element: ElementTree.Element) -> None:
        for child in list(element):
            if local(child.tag) in _SVG_TAGS:
                clean(child)
            else:
                element.remove(child)
        for name, value in list(element.attrib.items()):
            url = "url(" in value.lower()
            if local(name) not in _SVG_ATTRIBUTES or (url and not _SVG_SAFE_URL.fullmatch(value.strip())):
                del element.attrib[name]

    if local(root.tag) != "svg":
        raise CanvasToolError(_text_of("clean_svg.text.3"))
    clean(root)
    ElementTree.register_namespace("", "http://www.w3.org/2000/svg")
    return ElementTree.tostring(root, encoding="unicode")


def clean_html(answer: str) -> str:
    """The document from a reply, code fence or chatter around it removed. It is only ever shown in a sandboxed frame."""
    text = str(answer or "").strip()
    match = re.search(r"<!doctype html.*?</html\s*>|<html\b.*?</html\s*>", text, flags=re.S | re.I)
    if not match:
        raise CanvasToolError(_text_of("clean_html.text"))
    return match.group(0)


def beats_text(beats: Sequence[Mapping[str, str]]) -> str:
    return "\n".join(f"{index}. {beat['title'] or _text_of('beats_text.text') % index}：{beat['prompt']}" for index, beat in enumerate(beats, 1))


def looks_like_mask(histogram: Sequence[int]) -> bool:
    """A greyscale histogram that is almost all black or white is a mask, not a picture."""
    total = sum(histogram) or 1
    return (sum(histogram[:16]) + sum(histogram[240:])) / total >= 0.98


def grid_box(width: int, height: int, rows: int, columns: int, index: int) -> tuple[int, int, int, int]:
    """Pixel box of cell ``index`` (0-based, left to right, top to bottom)."""
    if not (1 <= rows <= 12 and 1 <= columns <= 12):
        raise CanvasToolError(_text_of("grid_box.text"))
    if not 0 <= index < rows * columns:
        raise CanvasToolError(_text_of("grid_box.text.2").format(rows * columns, index + 1))
    row, column = divmod(index, columns)
    return (width * column // columns, height * row // rows, width * (column + 1) // columns, height * (row + 1) // rows)


def erase_box(params: Mapping[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    """The box to erase, in pixels, kept a pixel inside the frame: ffmpeg's delogo refuses anything touching the edge."""
    if width < 8 or height < 8:
        raise CanvasToolError(_text_of("erase_box.text"))
    box_w = max(2, round(width * number(params, "w", 20, 0.5, 100) / 100))
    box_h = max(2, round(height * number(params, "h", 10, 0.5, 100) / 100))
    x = max(1, round(width * number(params, "x", 0, 0, 100) / 100))
    y = max(1, round(height * number(params, "y", 0, 0, 100) / 100))
    return (min(x, width - 3), min(y, height - 3), min(box_w, width - 2 - min(x, width - 3)), min(box_h, height - 2 - min(y, height - 3)))


def scene_cuts(lines: Sequence[str], duration: float) -> list[float]:
    """Cut times from ffmpeg ``showinfo`` output, with a cut closer than half a second to the last dropped as a flash."""
    times: list[float] = []
    for line in lines:
        marker = line.find("pts_time:")
        if marker < 0:
            continue
        try:
            value = float(line[marker + len("pts_time:"):].split()[0])
        except (IndexError, ValueError):
            continue
        if 0.5 <= value <= max(0.0, duration - 0.2) and (not times or value - times[-1] >= 0.5):
            times.append(round(value, 2))
    return times


def describe_catalog() -> list[dict[str, Any]]:
    return [{
        "id": tool.id, "label": tool.label, "group": tool.group, "engine": tool.engine, "output": tool.output,
        "inputs": sorted(tool.inputs), "images": tool.images, "videos": tool.videos, "needs_prompt": tool.needs_prompt,
    } for tool in TOOLS]


__all__ = [
    "BEAT_SYSTEM", "CanvasTool", "CanvasToolError", "DEFAULT_TOOL", "ENGINES", "MARK_PROMPT", "MARK_SYSTEM", "OUTPAINT_RATIOS",
    "REVERSE_PROMPT", "REVERSE_SYSTEM", "REVIEW_PROMPT", "REVIEW_SYSTEM", "SHOT_PROMPT", "SHOT_SYSTEM", "TOOLS", "StyleLook",
    "beat_prompt", "beats_text", "describe_catalog", "erase_box", "get_tool", "grid_box", "image_prompt", "number",
    "outpaint_ratio", "parse_beats", "scene_cuts", "style_look", "style_wall", "tool_of",
]

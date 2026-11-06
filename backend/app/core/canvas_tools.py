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
    CanvasTool("redraw", "重绘", "image", "image", "image", images=1, needs_prompt=True),
    CanvasTool("outpaint", "扩图", "image", "image", "image", images=1),
    CanvasTool("relight", "打光", "image", "image", "image", images=1),
    CanvasTool("multi_view", "多视角", "image", "image", "image", images=1),
    CanvasTool("style_transfer", "风格转绘", "image", "image", "image", images=1),
    CanvasTool("template_edit", "模板改图", "image", "image", "image", images=1),
    CanvasTool("enhance", "高清修复", "image", "image", "image", images=1),
    CanvasTool("upscale_image", "放大（本地）", "image", "local", "image", images=1),
    CanvasTool("grid_cell", "取宫格", "image", "local", "image", images=1),
    CanvasTool("composite", "贴回人物", "image", "local", "image", images=3),
    CanvasTool("reverse_prompt", "反推提示词", "image", "vision", "text", images=1),
    CanvasTool("mark_detect", "水印字幕检测", "image", "vision", "text", images=1),
    CanvasTool("video_upscale", "放大（本地）", "video", "local", "video", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("video_erase", "区域擦除", "video", "local", "video", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("audio_extract", "提取音轨", "video", "local", "audio", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("voice_isolate", "人声分离", "video", "audio", "audio", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("frame_extract", "抽帧", "video", "local", "image", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("to_gif", "转动图", "video", "local", "image", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("shot_analysis", "镜头分析", "video", "vision", "text", inputs=VIDEO_INPUT, videos=1),
    CanvasTool("sketch", "转线稿", "skill", "image", "image", images=1),
    CanvasTool("action_breakdown", "拆动作", "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("link_design", "设计接镜", "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("frame_bridge", "写首尾帧过渡", "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("script_write", "写剧本", "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("shot_table", "拆镜头表", "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("svg_art", "生成矢量图", "skill", "text", "image", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("html_page", "生成网页", "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
    CanvasTool("frame_from_context", "按上下文出首帧", "skill", "image", "image", needs_prompt=True),
    CanvasTool("set_background", "换背景", "skill", "image", "image", images=2),
    CanvasTool("scene_360", "生成 360° 场景", "skill", "image", "image", needs_prompt=True),
    CanvasTool("frame_review", "画面审查", "skill", "vision", "text", images=1),
    CanvasTool("beat_plan", "拍点规划", "skill", "text", "text", inputs=TEXT_INPUT, needs_prompt=True),
)
_BY_ID = {tool.id: tool for tool in TOOLS}
DEFAULT_TOOL = "redraw"

# Names shown in a <select> and in prompts, per parameter value.
OUTPAINT_RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4, "1:1": 1.0, "21:9": 21 / 9, "2:3": 2 / 3}
_LIGHTS = {
    "golden": "黄昏金色低角度暖光，长影子", "noon": "正午顶光，硬朗的短影子", "overcast": "阴天柔光，几乎没有阴影",
    "night": "夜晚冷色月光，暗部保留细节", "neon": "霓虹灯的品红与青色混合光", "rembrandt": "伦勃朗布光，暗侧脸颊有三角形亮区",
    "backlit": "强逆光，轮廓发亮，正面略暗", "candle": "烛光，暖色小光源，周围迅速衰减",
}
_VIEWS = {
    "front": "正面平视", "left": "左侧面", "right": "右侧面", "back": "正背面", "three_quarter": "四分之三侧面",
    "top": "俯视", "low": "低角度仰视",
}
_TEMPLATES = {
    "remove_people": "去掉画面里的路人，只留主体，被遮挡的背景按周围环境自然补全",
    "change_outfit": "只换主体的服装为：{extra}。脸、发型、姿势、光线和背景不变",
    "change_expression": "只改主体的表情为：{extra}。五官比例和身份不变，其余不变",
    "change_weather": "把天气和时间改为：{extra}。人物和建筑的位置与形状不变",
    "add_prop": "在主体手中或身旁加入：{extra}。接触关系、比例和光影要和画面一致",
    "remove_text": "去掉画面中的文字、水印和字幕，被覆盖处按周围内容补全，其余不变",
}
_TEMPLATES_NEED_TEXT = frozenset({"change_outfit", "change_expression", "change_weather", "add_prop"})
_KEEP = "构图、机位、人物身份、位置关系都保持和参考图一致。"
_NO_TEXT = "画面中不要出现文字、水印或边框。"

BEAT_SYSTEM = (
    "你是短剧分镜导演。把一段故事拆成一拍一拍的画面，每拍是一个能单独生成的镜头。只输出一个 JSON 对象，不要解释或代码块标记。"
)
BEAT_FORMAT = (
    '输出：{"beats": [{"title": "这一拍在讲什么（十字以内）", "prompt": "能直接生成首帧的画面描述：人物、动作、景别、机位、光线"}]}。'
    "拍数按内容定，一般 4 到 12 拍；每拍只写一个动作；前一拍的结果要能接到后一拍。"
)
REVERSE_SYSTEM = "你是图像提示词工程师。看图，写出能生成同一张图的提示词。只输出提示词正文，不要解释。"
REVERSE_PROMPT = (
    "按这个顺序写一段中文：主体与动作、景别与机位、场景、光线、色彩、质感或画风、镜头参数。只写看得到的东西，不猜画面外的剧情。"
)
MARK_SYSTEM = "你检查画面里不该留到成片的文字和标记。只报告看得到的，没有就直说没有。"
MARK_PROMPT = (
    "逐项列出画面中的水印、台标、字幕、签名和其他文字。每项一行：类型｜文字内容｜位置，"
    "位置用「左 x%，上 y%，宽 w%，高 h%」表示，都是相对画面的百分比（可以直接填进区域擦除工具）。"
    "最后一行写结论：可以直接用，或需要先处理。"
)
REVIEW_SYSTEM = "你是短剧监制，审查一张分镜首帧能不能拿去做视频。说话直接，只说看得到的问题。"
REVIEW_PROMPT = (
    "按这几项各用一两句话评价：构图与主体、人物手部和面部有没有畸变、物体接触和比例、光线是否一致、"
    "画面里有没有多余的文字或水印。{extra}最后一行给结论：通过，或要改什么。"
)
SHOT_SYSTEM = "你是剪辑师，看一张按时间排列的联系表，每格是视频的一个镜头。只说看得到的内容。"
SHOT_PROMPT = (
    "这个视频有 {count} 个镜头，联系表从左到右、从上到下排列，切点时间依次是：{cuts}。"
    "逐个镜头写一行：序号｜时间段｜景别｜机位或运镜｜画面内容。最后用一句话说整段的节奏。"
)
SCRIPT_SYSTEM = "你是短剧编剧。按要求写一场能直接拍的戏：冲突清楚，对白短，每句都推动情节。只输出剧本正文。"
SCRIPT_PROMPT = (
    "按这个格式写：\n场景标题（地点，日或夜）\n动作描写\n人物名：对白\n\n"
    "只写画面里看得到、听得到的东西，不写心理活动和镜头术语。\n\n要求：{story}"
)
LINK_SYSTEM = "你是剪辑指导。先想清这一切要让观众跟住什么，再决定在哪一刻切。接不上就直说换成别的接法，不硬凑花哨转场。"
LINK_PROMPT = (
    "两个镜头要接在一起：{story}\n\n"
    "从这六类关系里选最合适的一种：接动作（同一动作换景别 / 相似动作连两场戏）、接图形（形状或主线条呼应）、"
    "借遮挡（近处物体遮满画面 / 摄影机掠过墙面）、留参照（同物换境 / 同景换时）、错开声画（下一场声音先到 / 上一场声音留下）、"
    "顺着看与走（视线引导 / 方向延续）。\n\n"
    "只输出这几行：\n接法：选了哪一种，为什么，这一切给观众新增了什么信息\n"
    "镜头A：切出时的状态——主体位置与大小、运动方向、动作进行到哪一步、道具状态\n"
    "镜头B：接入时的状态——同样几项，后镜不重演前镜做过的部分\n"
    "剪辑备注：在哪一刻试切，前后留多少余量；声音和画面是否错开\n"
    "检查：回看时核对哪几项\n"
    "切出和接入的状态可以在片段中间，不一定是文件的最后一帧和第一帧。"
)

FRAME_BRIDGE_SYSTEM = "你写首尾帧视频的过渡提示词。只输出一段可以直接发给视频模型的中文，不解释、不加标题。"
FRAME_BRIDGE_PROMPT = (
    "首帧和尾帧分别是：{story}\n\n"
    "挑一种最合适的方式让首帧走到尾帧，写清镜头怎么动、画面怎么变，一到两句：运镜走过去（推拉摇移）、景别递进（特写到全景或反过来）、"
    "光影渐变（强弱、冷暖）、主体动作延续、艺术风格演变（同一构图）、时间流逝（固定机位，季节昼夜变化）、色彩渐变、"
    "空间穿越（隧道、门、窗）。只写首尾之间发生的变化，不重复描述两张图。"
)

SHOT_TABLE_SYSTEM = "你是分镜师。把一段剧本拆成镜头表，每个镜头是一个能单独生成的画面。只输出一个 JSON 对象，不要解释或代码块标记。"
SHOT_TABLE_PROMPT = (
    '输出：{{"shots": [{{"size": "景别", "motion": "运镜", "seconds": 秒数, "desc": "画面内容", "dialogue": "这一镜的对白，没有就留空"}}]}}。'
    "一个镜头只写一个动作；秒数是 2 到 15 的整数。\n\n剧本：\n{story}"
)
SVG_SYSTEM = "你生成干净的 SVG 矢量图。只输出一个完整的 <svg> 元素，不要解释或代码块标记；只用基本图形和路径，不要脚本、外链、内嵌图片或 foreignObject。"
SVG_PROMPT = "画这个：{story}。用 viewBox，不写死宽高；形状简洁、配色统一。"
HTML_SYSTEM = "你写单文件静态网页。只输出一个完整的 HTML 文档，不要解释或代码块标记；样式写在页面内，不引用任何外部资源。"
HTML_PROMPT = "做这个页面：{story}。手机和电脑都要能看，正文可读，不用占位文字。"
OUTPAINT_INSTRUCTION = "把这张图向四周扩展到完整的 {ratio} 画幅：原图内容保持原样，只补全它周围缺的部分，透视、光线和质感要接得上。"


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
        raise CanvasToolError(f"不认识的工具 {params.get('tool')}")
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
            raise CanvasToolError("写一下要改成什么样")
        return f"以参考图为基础重绘：{extra}。没有提到的部分保持不变。{_NO_TEXT}"
    if tool.id == "outpaint":
        return OUTPAINT_INSTRUCTION.format(ratio=outpaint_ratio(params)) + (f"补全的内容：{extra}。" if extra else "") + _NO_TEXT
    if tool.id == "relight":
        light = _LIGHTS.get(str(params.get("light") or "golden"), _LIGHTS["golden"])
        return f"只改变这张图的光线：{light}。{_KEEP}{extra}{_NO_TEXT}"
    if tool.id == "multi_view":
        view = _VIEWS.get(str(params.get("view") or "three_quarter"), _VIEWS["three_quarter"])
        return f"画出参考图中同一主体的{view}。身份、服装、配色和体型都不变，背景保持简洁。{extra}{_NO_TEXT}"
    if tool.id == "style_transfer":
        look = style_look(str(params.get("style") or ""))
        if look is None:
            raise CanvasToolError("先在风格墙里选一种风格")
        return f"把参考图转绘为这种风格：{look.prompt}。{_KEEP}{extra}{_NO_TEXT}"
    if tool.id == "template_edit":
        key = str(params.get("template") or "remove_people")
        template = _TEMPLATES.get(key)
        if template is None:
            raise CanvasToolError(f"不认识的改图模板 {key}")
        if key in _TEMPLATES_NEED_TEXT and not extra:
            raise CanvasToolError("这个模板要写明改成什么")
        return template.format(extra=extra) + (f"。{extra}" if extra and "{extra}" not in template else "。") + _NO_TEXT
    if tool.id == "enhance":
        return f"高清修复这张图：提高清晰度和细节，去掉噪点和压缩痕迹，不改变任何内容、构图和人物长相。{extra}{_NO_TEXT}"
    if tool.id == "sketch":
        return f"把参考图转成干净的黑白线稿：单色线条、白底、无阴影和上色，人物和物体的位置与轮廓不变。{extra}"
    if tool.id == "frame_from_context":
        if not extra:
            raise CanvasToolError("连一段文本或写一下这一镜要拍什么")
        return f"生成这一镜的首帧：{extra}。如果有参考图，人物长相、服装和场景都以参考图为准。{_NO_TEXT}"
    if tool.id == "set_background":
        return f"第一张参考图里的主体放进第二张参考图的场景：主体的长相、服装、姿势不变，比例、透视和光线与场景一致。{extra}{_NO_TEXT}"
    raise CanvasToolError(f"{tool.label} 不走图像模型")


def outpaint_ratio(params: Mapping[str, Any]) -> str:
    ratio = str(params.get("ratio") or "16:9")
    return ratio if ratio in OUTPAINT_RATIOS else "16:9"


def beat_prompt(text: str) -> str:
    story = " ".join(str(text or "").split())
    if not story:
        raise CanvasToolError("连一段文本或写一下这段故事")
    return f"故事：{story}\n\n{BEAT_FORMAT}"


def parse_beats(answer: str) -> list[dict[str, str]]:
    """The beats of a model's reply; a reply with none is a failed run, not an empty plan."""
    from app.core.screenwriting.structured_llm import extract_json_object

    data = extract_json_object(str(answer or ""))
    rows = data.get("beats") if isinstance(data, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise CanvasToolError("模型没有返回可解析的拍点，请重试")
    beats = [
        {"title": str(row.get("title") or "").strip()[:40], "prompt": str(row.get("prompt") or "").strip()[:800]}
        for row in rows if isinstance(row, Mapping) and str(row.get("prompt") or "").strip()
    ][:40]
    if not beats:
        raise CanvasToolError("模型没有给出可用的拍点，请把故事写具体一些后重试")
    return beats


def parse_shots(answer: str) -> list[dict[str, Any]]:
    """The rows of a shot table; a reply with none is a failed run, not an empty table."""
    from app.core.screenwriting.structured_llm import extract_json_object

    data = extract_json_object(str(answer or ""))
    rows = data.get("shots") if isinstance(data, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise CanvasToolError("模型没有返回可解析的镜头表，请重试")
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
        raise CanvasToolError("模型没有给出可用的镜头，请把剧本写具体一些后重试")
    return shots


def shots_text(shots: Sequence[Mapping[str, Any]]) -> str:
    lines = []
    for index, shot in enumerate(shots, 1):
        camera = "、".join(part for part in (shot["size"], shot["motion"]) if part)
        line = f"{index}. {camera + '｜' if camera else ''}{shot['seconds']} 秒｜{shot['desc']}"
        lines.append(f"{line}｜「{shot['dialogue']}」" if shot["dialogue"] else line)
    return "\n".join(lines)


def shots_as_beats(shots: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """A shot table in the shape 铺成节点 takes: one first frame to draw per shot."""
    beats = []
    for index, shot in enumerate(shots, 1):
        camera = "，".join(part for part in (shot["size"], shot["motion"]) if part)
        beats.append({"title": f"第 {index} 镜", "prompt": f"{shot['desc']}{'，' + camera if camera else ''}"[:800]})
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
        raise CanvasToolError("模型没有返回可用的 SVG，请重试")
    try:
        root = ElementTree.fromstring(match.group(0))
    except ElementTree.ParseError as error:
        raise CanvasToolError("模型返回的 SVG 不完整，请重试") from error

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
        raise CanvasToolError("模型没有返回可用的 SVG，请重试")
    clean(root)
    ElementTree.register_namespace("", "http://www.w3.org/2000/svg")
    return ElementTree.tostring(root, encoding="unicode")


def clean_html(answer: str) -> str:
    """The document from a reply, code fence or chatter around it removed. It is only ever shown in a sandboxed frame."""
    text = str(answer or "").strip()
    match = re.search(r"<!doctype html.*?</html\s*>|<html\b.*?</html\s*>", text, flags=re.S | re.I)
    if not match:
        raise CanvasToolError("模型没有返回完整的网页，请重试")
    return match.group(0)


def beats_text(beats: Sequence[Mapping[str, str]]) -> str:
    return "\n".join(f"{index}. {beat['title'] or '第 %d 拍' % index}：{beat['prompt']}" for index, beat in enumerate(beats, 1))


def looks_like_mask(histogram: Sequence[int]) -> bool:
    """A greyscale histogram that is almost all black or white is a mask, not a picture."""
    total = sum(histogram) or 1
    return (sum(histogram[:16]) + sum(histogram[240:])) / total >= 0.98


def grid_box(width: int, height: int, rows: int, columns: int, index: int) -> tuple[int, int, int, int]:
    """Pixel box of cell ``index`` (0-based, left to right, top to bottom)."""
    if not (1 <= rows <= 12 and 1 <= columns <= 12):
        raise CanvasToolError("行数和列数都要在 1 到 12 之间")
    if not 0 <= index < rows * columns:
        raise CanvasToolError(f"这张表只有 {rows * columns} 格，没有第 {index + 1} 格")
    row, column = divmod(index, columns)
    return (width * column // columns, height * row // rows, width * (column + 1) // columns, height * (row + 1) // rows)


def erase_box(params: Mapping[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    """The box to erase, in pixels, kept a pixel inside the frame: ffmpeg's delogo refuses anything touching the edge."""
    if width < 8 or height < 8:
        raise CanvasToolError("视频尺寸太小，无法擦除")
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

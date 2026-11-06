# -*- coding: utf-8 -*-
"""A grey-box set read off a reference image.

A person shows the place — a concept painting, a location photo, an aerial view — and a model
that can see lists it as simple volumes on the floor plan: boxes, cylinders, wedges with a name,
a footprint and a height. The result is a proposal; ``apply_blockout`` (operations.py) puts it on
the stage as ordinary set pieces a person can then move, scale or delete one by one.

Nothing here calls a model; ``analysis_prompt`` is what to send and ``parse_blockout`` reads what
came back. A reply is taken apart piece by piece so one malformed row costs that row, not the
whole set: models write these lists long and a reply can be cut off at the token limit.

Behavioural reference: the 3D director stage shown in DramaClaw's README (Elastic License 2.0,
implementation not published). Nothing of DramaClaw's is used; see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.spatial_stage.model_kit import catalog_text, find_kit
from app.core.spatial_stage.models import LandmarkKind, LandmarkShape, MAX_LANDMARKS, SpacePoint

REFERENCE_CAMERA_LABEL = "参考机位"
# Enough for a whole street; the rest of the stage's capacity stays for what a person adds by hand.
MAX_BLOCKOUT_PIECES = 200
MAX_ARRAY_COUNT = 40
BLOCKOUT_MAX_TOKENS = 8000
_MAX_HINT = 300
MAX_DESCRIPTION = 2000
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_SIZE_RANGE = (0.02, 200.0)

_SYSTEM = (
    "你是电影美术的白模师。你看一张场景参考图，把它拆成可以在 3D 软件里搭出来的简单体块，"
    "用来做机位和走位预演，不追求细节，追求空间关系和比例准确。只输出一个 JSON 对象，不要任何解释或代码块标记。"
)

_INSTRUCTIONS = """把这张参考图还原成一张俯视平面图上的体块清单。

坐标约定（米，真实世界比例）：
- 地面是 XZ 平面，场地中心在原点。
- 站在拍摄这张图的位置看过去：+X 是画面右侧，-X 是画面左侧，+Z 朝向拍摄者（画面近处），-Z 是画面深处。
- 用画面里的常见物体估算比例：门高约 2.1 米，一层楼约 3 米，人高约 1.7 米，树高 4 到 8 米。

输出这个 JSON：
{
  "summary": "一句话说明这是什么地方",
  "extent_m": [场地宽, 场地深],
  "reference_camera": {"position": [x, y, z], "target": [x, y, z], "lens_mm": 35},
  "pieces": [
    {"name": "北侧外墙", "kind": "architecture", "shape": "box", "center": [x, z], "size": [宽, 进深, 高], "yaw_deg": 0, "elevation_m": 0},
    {"name": "廊柱", "kind": "architecture", "shape": "cylinder", "center": [x, z], "size": [0.6, 0.6, 4], "array": {"count": 6, "dx": 3, "dz": 0}}
  ]
}

字段说明：
- name：中文名，说清它是什么、在哪一侧，同类用「段 1」「段 2」区分，不要重复。
- kind：architecture（墙、楼、地台、台阶）、furniture（桌椅、柜台、车辆）、prop（小物件、盆栽、箱子）、light（灯具）。
- shape：box、cylinder、sphere、cone、wedge（斜坡或单坡屋顶，高的一边在 -Z）。
- center 是体块底面中心；size 是 [X 向宽度, Z 向进深, 高度]；yaw_deg 绕竖直轴转，0 表示不转。
- elevation_m：体块底面离地高度，屋顶、二层、架在别的东西上的才填，贴地可省略。
- array：可选，一排重复的东西（柱子、窗、树、座位）写一条再加 array，不要逐个罗列；count 是总数，dx / dz 是相邻两个的间距。
- reference_camera：估算拍摄这张图的机位、看向的点和等效全画幅焦距；y 是离地高度，航拍可以很高。

拆分要求：
- 先铺地面：用一块很薄的 box（高 0.05 米）表示主要地面或广场；地面只占一块，别的体块都站在它上面。
- 再放决定空间结构的大件（外墙、建筑体量、通道两侧的墙），它们围出人能走的路；墙要有真实的厚度（0.2 到 1 米），不要让体块互相穿插。
- 长墙有门洞或转折就拆成几段，留出缺口，这样人物走位才走得通。
- 最后放能遮挡视线或被人物利用的中小件。画面看不到的地方不要编造。
- 总数控制在 """ + str(MAX_BLOCKOUT_PIECES) + """ 块以内：宁可合并远处的小东西，也不要漏掉近处的结构。"""


class BlockoutError(ValueError):
    """The reply could not be read as a blockout, or a submitted one is not usable."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class BlockoutPiece(_Model):
    name: str = Field(min_length=1, max_length=120)
    kind: LandmarkKind = "architecture"
    shape: LandmarkShape = "box"
    center: tuple[float, float]
    size: tuple[float, float, float]
    yaw_deg: float = Field(0.0, ge=-360, le=360)
    elevation_m: float = Field(0.0, ge=0, le=100)
    color: str = ""
    # A built-in model or a list of volumes, drawn inside the piece's size instead of one plain volume.
    kit: str = ""
    parts: list[Any] = Field(default_factory=list, max_length=64)
    # Without a size of its own a kit piece comes out at the size that kind of thing really is.
    size_given: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def trimmed(cls, value: Any) -> Any:
        return value.strip()[:120] if isinstance(value, str) else value

    @field_validator("center")
    @classmethod
    def on_the_stage(cls, value: tuple[float, float]) -> tuple[float, float]:
        if any(not math.isfinite(item) or abs(item) > 500 for item in value):
            raise ValueError("a piece must stand within ±500 metres")
        return (round(value[0], 3), round(value[1], 3))

    @field_validator("size")
    @classmethod
    def real_volume(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if any(not math.isfinite(item) or item <= 0 for item in value):
            raise ValueError("a piece needs a positive size")
        low, high = _SIZE_RANGE
        return tuple(round(max(low, min(high, item)), 3) for item in value)  # type: ignore[return-value]

    @field_validator("color", mode="before")
    @classmethod
    def colour_or_nothing(cls, value: Any) -> str:
        text = str(value or "").strip()
        return text if _HEX.match(text) else ""


class BlockoutCamera(_Model):
    position: SpacePoint
    target: SpacePoint
    lens_mm: float = Field(35.0, ge=8, le=600)

    @field_validator("position")
    @classmethod
    def above_the_floor(cls, value: list[float]) -> list[float]:
        return [value[0], max(0.05, value[1]), value[2]]


class Blockout(_Model):
    summary: str = Field("", max_length=300)
    extent_m: tuple[float, float] | None = None
    reference_camera: BlockoutCamera | None = None
    pieces: list[BlockoutPiece]
    # Rows of the reply that could not be used; surfaced so a person knows the set is incomplete.
    dropped: int = 0

    @field_validator("summary", mode="before")
    @classmethod
    def short(cls, value: Any) -> str:
        return str(value or "")[:300]


_TEXT_SYSTEM = (
    "你是电影美术的白模师。你读一段场景描述，把它搭成可以在 3D 软件里摆出来的简单体块，"
    "用来做机位和走位预演，不追求细节，追求空间关系和比例准确。只输出一个 JSON 对象，不要任何解释或代码块标记。"
)

_TEXT_NOTES = """这次没有参考图：按描述想象这个地方，把它搭出来；描述没写的只补这类地方必需的东西（一间屋子要有墙和门），不要加戏。
- 把上面说的「站在拍摄位置看过去」理解成：站在场地南侧（+Z）朝北（-Z）看，reference_camera 就给一个能看清全场的机位。
- 优先用模型库：一件东西在下面的库里有，就写 "kit": "库里的 id"，并给 center；只有实际尺寸和库里明显不同才写 size。墙、地面、大体块仍可以用 shape + size。

模型库（id（名称 宽×深×高，米））：
"""


def text_prompt(description: str, width_m: float | None = None) -> tuple[str, str]:
    """The same floor-plan contract as a reference image, from words, with the model library on offer."""
    prompt = _INSTRUCTIONS + "\n\n" + _TEXT_NOTES + catalog_text()
    if width_m:
        prompt += f"\n\n操作者已知这个场地宽约 {width_m:g} 米：以此为准定比例。"
    return _TEXT_SYSTEM, f"{prompt}\n\n场景描述：\n{description.strip()[:MAX_DESCRIPTION]}"


def analysis_prompt(hint: str = "", width_m: float | None = None) -> tuple[str, str]:
    prompt = _INSTRUCTIONS
    if width_m:
        prompt += f"\n\n操作者已知这个场地宽约 {width_m:g} 米：以此为准定比例。"
    if hint.strip():
        prompt += f"\n\n操作者的补充说明（只用来判断画面内容）：{hint.strip()[:_MAX_HINT]}"
    return _SYSTEM, prompt


def _json_of(text: str) -> Mapping[str, Any]:
    """The reply as an object; a reply cut off inside the list keeps every piece it finished."""
    body = re.sub(r"^```(?:json)?|```$", "", str(text or "").strip(), flags=re.MULTILINE).strip()
    start = body.find("{")
    if start < 0:
        raise BlockoutError("模型没有返回可解析的白模清单，请重试或换一个多模态模型")
    body = body[start:]
    try:
        parsed = json.JSONDecoder().raw_decode(body)[0]
    except json.JSONDecodeError:
        parsed = _salvage(body)
    if not isinstance(parsed, Mapping):
        raise BlockoutError("模型没有返回可解析的白模清单，请重试或换一个多模态模型")
    return parsed


def _salvage(body: str) -> Mapping[str, Any]:
    """Cut a truncated reply back to its last complete piece and close what is still open."""
    opening = body.find('"pieces"')
    bracket = body.find("[", opening) if opening >= 0 else -1
    if bracket < 0:
        raise BlockoutError("模型的回答被截断，没有读到任何体块，请重试")
    depth, in_string, escaped, last = 0, False, False, -1
    for index in range(bracket + 1, len(body)):
        char = body[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                last = index
    if last < 0:
        raise BlockoutError("模型的回答被截断，没有读到任何体块，请重试")
    try:
        return json.loads(body[: last + 1] + "]}")
    except json.JSONDecodeError as error:
        raise BlockoutError("模型的回答被截断且无法修复，请重试") from error


def _expand(rows: Sequence[Any]) -> list[Any]:
    """A row with an ``array`` becomes that many pieces, numbered and stepped along it."""
    expanded: list[Any] = []
    for row in rows:
        spec = row.get("array") if isinstance(row, Mapping) else None
        if not isinstance(spec, Mapping):
            expanded.append(row)
            continue
        try:
            count = max(1, min(MAX_ARRAY_COUNT, int(spec.get("count", 1))))
            dx, dz = float(spec.get("dx", 0)), float(spec.get("dz", 0))
            x, z = float(row["center"][0]), float(row["center"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            expanded.append(row)  # let validation say what is wrong with it
            continue
        for index in range(count):
            expanded.append({
                **{key: value for key, value in row.items() if key != "array"},
                "name": f"{str(row.get('name') or '').strip()[:112]} {index + 1}" if count > 1 else row.get("name"),
                "center": [x + dx * index, z + dz * index],
            })
    return expanded


def _kit_defaults(row: Any) -> Any:
    """A row that only names a library model takes its size and kind from there; an unknown name is a plain volume."""
    if isinstance(row, Mapping) and row.get("parts") and not row.get("size"):
        return {**row, "size_given": False, "size": [1.0, 1.0, 1.0]}
    if not isinstance(row, Mapping) or not row.get("kit"):
        return row
    kit = find_kit(row["kit"])
    if kit is None:
        return {**row, "kit": ""} if row.get("size") else row
    has_size = isinstance(row.get("size"), Sequence) and not isinstance(row.get("size"), (str, bytes))
    return {
        "kind": kit.kind, **row, "kit": kit.id, "size_given": has_size,
        "size": row["size"] if has_size else list(kit.size),
    }


def _read_rows(rows: Sequence[Any]) -> tuple[list[BlockoutPiece], int]:
    pieces: list[BlockoutPiece] = []
    dropped = 0
    names: set[str] = set()
    for row in _expand(rows):
        try:
            piece = BlockoutPiece.model_validate(_kit_defaults(row))
        except ValidationError:
            dropped += 1
            continue
        # Names are how the stage addresses a piece, so a repeat gets a number rather than losing the piece.
        name, suffix = piece.name, 2
        while name in names:
            name, suffix = f"{piece.name[:112]} {suffix}", suffix + 1
        names.add(name)
        pieces.append(piece.model_copy(update={"name": name}))
    overflow = max(0, len(pieces) - MAX_BLOCKOUT_PIECES)
    return pieces[:MAX_BLOCKOUT_PIECES], dropped + overflow


def parse_blockout(text: str) -> Blockout:
    """What the model said, with the unusable rows counted and left out."""
    data = _json_of(text)
    rows = data.get("pieces")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise BlockoutError("模型的回答里没有体块清单，请重试")
    pieces, dropped = _read_rows(rows)
    if not pieces:
        raise BlockoutError("模型没有给出可用的体块，请换一张空间关系更清楚的参考图，或补充说明后重试")
    camera = None
    try:
        camera = BlockoutCamera.model_validate(data["reference_camera"]) if data.get("reference_camera") else None
        if camera is not None and sum((camera.position[i] - camera.target[i]) ** 2 for i in range(3)) < 1e-4:
            camera = None
    except ValidationError:
        camera = None
    extent = data.get("extent_m")
    try:
        extent_m = (float(extent[0]), float(extent[1])) if isinstance(extent, Sequence) and len(extent) == 2 else None
    except (TypeError, ValueError):
        extent_m = None
    return Blockout(summary=data.get("summary") or "", extent_m=extent_m, reference_camera=camera, pieces=pieces, dropped=dropped)


def read_pieces(rows: Any) -> list[BlockoutPiece]:
    """The pieces of an ``apply_blockout`` operation; unlike a model's reply, a submitted row must be right."""
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise BlockoutError("pieces 必须是非空的体块列表")
    if len(rows) > MAX_LANDMARKS:
        raise BlockoutError(f"一份白模最多 {MAX_LANDMARKS} 块")
    pieces, dropped = _read_rows(rows)
    if dropped:
        raise BlockoutError(f"有 {dropped} 个体块的字段不合法（需要 name、center:[x,z]、size:[宽,进深,高]）")
    return pieces


__all__ = [
    "BLOCKOUT_MAX_TOKENS", "Blockout", "BlockoutCamera", "BlockoutError", "BlockoutPiece", "MAX_BLOCKOUT_PIECES",
    "REFERENCE_CAMERA_LABEL", "analysis_prompt", "parse_blockout", "read_pieces", "text_prompt",
]

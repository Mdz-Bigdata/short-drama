"""Physical actor-sheet and exact 3x3 storyboard image operations."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps

from app import settings
from app.core.actor_sheet_cutter import _SeparatorMap, detect_actor_sheet_cell_boxes
from app.core.actor_sheet_layout import (
    ACTOR_SHEET_CELL_ORDER,
    ACTOR_SHEET_LAYOUT,
    DERIVED_CELL_SOURCES,
    MIRRORED_CELL_SOURCES,
    actor_sheet_cell_paths,
)


Image.MAX_IMAGE_PIXELS = 60_000_000
MAX_REMOTE_IMAGE_BYTES = 30 * 1024 * 1024


def _validate_remote_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("image URL must use HTTP(S)")
    if parsed.scheme == "http" and os.getenv("ALLOW_INSECURE_MEDIA_HTTP", "0") != "1":
        raise ValueError("remote image URL must use HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("credentials in media URLs are not allowed")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    for address in addresses:
        if not settings.is_public_address(address[4][0]):
            raise ValueError("private or local media hosts are not allowed")


def _download_image(url: str) -> bytes:
    current = url
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for _ in range(4):
            _validate_remote_url(current)
            with client.stream("GET", current, headers={"Accept": "image/*"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("image redirect has no location")
                    current = str(response.url.join(location))
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                if content_type and not content_type.startswith("image/"):
                    raise ValueError("remote resource is not an image")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_REMOTE_IMAGE_BYTES:
                        raise ValueError("remote image exceeds 30 MB")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise ValueError("too many image redirects")


def fetch_remote_image_bytes(url: str) -> bytes:
    """Download a validated remote storyboard image for re-serving to the user."""
    return _download_image(url)


def _open_image(source: str | Path) -> Image.Image:
    value = str(source)
    if value.startswith("data:image/"):
        try:
            payload = value.split(",", 1)[1]
            data = base64.b64decode(payload, validate=True)
        except (IndexError, ValueError) as exc:
            raise ValueError("invalid image data URI") from exc
        if len(data) > MAX_REMOTE_IMAGE_BYTES:
            raise ValueError("image data URI exceeds 30 MB")
        image = Image.open(io.BytesIO(data))
    elif value.startswith(("https://", "http://")):
        image = Image.open(io.BytesIO(_download_image(value)))
    else:
        image = Image.open(Path(value).expanduser().resolve())
    image.load()
    return image.convert("RGB")


def compose_nine_grid(
    sources: list[str | Path],
    output: str | Path,
    *,
    cell_size: tuple[int, int] = (356, 636),
    gutter: int = 6,
) -> Path:
    """Create one 3x3 board; unused cells stay blank instead of duplicating beats."""
    if not 1 <= len(sources) <= 9:
        raise ValueError("a nine-grid page requires between one and nine real images")
    cell_width, cell_height = cell_size
    if cell_width <= 0 or cell_height <= 0 or not 0 <= gutter <= 32:
        raise ValueError("invalid grid geometry")
    canvas = Image.new(
        "RGB",
        (cell_width * 3 + gutter * 2, cell_height * 3 + gutter * 2),
        "white",
    )
    for index, source in enumerate(sources):
        image = _open_image(source)
        fitted = ImageOps.fit(image, cell_size, method=Image.Resampling.LANCZOS)
        row, column = divmod(index, 3)
        canvas.paste(
            fitted,
            (column * (cell_width + gutter), row * (cell_height + gutter)),
        )
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format="PNG", optimize=True)
    return target


def split_actor_sheet(source: str | Path, output_directory: str | Path) -> list[Path]:
    """把一张 21:9 数字演员设定集裁成独立格子资产(最多 25 个)。

    每一格的边界由 ``detect_actor_sheet_cell_boxes`` 从画面里的分隔线找出来并收紧到
    面板本身，所以标题字不会混进格子，脸和全身也不会被切掉一半。模型没画的元素/细节格
    不会凭空切出来；七个身份必需格(REQUIRED_CELLS)一定都在。

    返回的路径按 ACTOR_SHEET_CELL_ORDER 排序，文件名为 ``NN_<key>-<内容哈希>.png``，NN 是该格在
    版面表里的固定序号(缺格时序号不连续)；下游用 ``actor_sheet_cell_key`` 从文件名认格子。

    宽高比不在 2.0–2.6 之间说明模型压根没按超宽横版出图，这时候按固定比例裁只会
    切出一堆垃圾并把它们当成合格资产存进库里——所以直接拒绝，交给上层重试整张图。
    """
    image = _open_image(source)
    layout = ACTOR_SHEET_LAYOUT
    aspect = image.width / image.height
    if not layout.min_aspect_ratio <= aspect <= layout.max_aspect_ratio:
        raise ValueError(
            f"数字演员设定集必须是 {layout.aspect_ratio_label} 超宽横版"
            f"（宽高比需在 {layout.min_aspect_ratio:g}–{layout.max_aspect_ratio:g} 之间），"
            f"当前为 {aspect:.2f}，不予拆分。"
        )
    if image.width < 200 or image.height < 100:
        raise ValueError("数字演员设定集分辨率过低，无法拆出各个格子。")
    target_dir = Path(output_directory).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for cell, box in detect_actor_sheet_cell_boxes(image):
        paths.append(_save_cell(image.crop(box), target_dir, cell))
    return paths


def _save_cell(image: Image.Image, directory: Path, cell: str) -> Path:
    """存成 ``NN_<key>-<内容哈希>.png``：内容变了文件名就变，浏览器不会拿缓存的旧裁切冒充新图。"""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    payload = buffer.getvalue()
    digest = hashlib.sha1(payload).hexdigest()[:8]
    path = directory / f"{ACTOR_SHEET_CELL_ORDER.index(cell) + 1:02d}_{cell}-{digest}.png"
    if not path.exists():
        path.write_bytes(payload)
    return path


# 补位裁切的最短边：太小的部位放大到这个尺寸，单看时不糊成一团，也过得了逐格质检的 64px 下限。
DERIVED_CELL_MIN_SIDE = 256


# 补位来源本身切坏了(全身立绘只切到人物边上一条窄条)时，换同一部位更可靠的身份格来裁。
DERIVED_SOURCE_FALLBACKS: dict[str, tuple[str, ...]] = {
    "full_body": ("front",),
    "portrait": ("face_front",),
}
# 全身类来源宽高比低于这个值就是切坏的窄条(正常的全身格连留白约 0.35–0.6)。
FULL_BODY_MIN_ASPECT = 0.28


def _usable_source(cell: str, size: tuple[int, int]) -> bool:
    width, height = size
    if min(width, height) < 32:
        return False
    if cell in {"full_body", "front", "back"}:
        return width / height >= FULL_BODY_MIN_ASPECT
    return True


def _derived_crop(image: Image.Image, fractions: tuple[float, float, float, float]) -> Image.Image | None:
    """按部位比例从身份面板里裁一块补位，保证裁出来的不是一片空白。

    比例按人物本身(去掉四周留白后的外框)算，不按整格算：全身立绘左右常有大片留白，
    按整格比例裁「面料」「手部」会落在背景上。仍然空白就放宽到同一高度的整条人物带，
    再不行就用整个人物外框——宁可补位画面大一些，也不留空白格。
    """
    from app.core.actor_detail_fill import is_blank

    width, height = image.size
    figure = _SeparatorMap(image).trim((0, 0, width, height)) or (0, 0, width, height)
    fig_left, fig_top, fig_right, fig_bottom = figure
    fig_width, fig_height = fig_right - fig_left, fig_bottom - fig_top
    left, top, right, bottom = fractions
    band_top, band_bottom = fig_top + round(fig_height * top), fig_top + round(fig_height * bottom)
    candidates = (
        (fig_left + round(fig_width * left), band_top, fig_left + round(fig_width * right), band_bottom),
        (fig_left, band_top, fig_right, band_bottom),
        figure,
    )
    usable = [box for box in candidates if box[2] - box[0] >= 4 and box[3] - box[1] >= 4]
    for box in usable:
        crop = image.crop(box)
        if not is_blank(crop):
            return crop
    # 来源面板本身就是一片底色(只在切图失败的极端情况)：照常给出部位裁切，25 格一张不缺。
    return image.crop(usable[0]) if usable else None


def complete_actor_sheet_cells(paths: list[Path]) -> tuple[list[Path], dict[str, str]]:
    """把模型没画的元素/细节格补齐成完整的 25 格。

    每个缺格按 ``DERIVED_CELL_SOURCES`` 从已画出的身份面板(全身立绘、主肖像、背面)里按部位裁一块，
    存成同样的 ``NN_<key>.png``。返回 (按 ACTOR_SHEET_CELL_ORDER 排好的全部路径, {补位格: 来源格})。
    来源格本身缺失时(只会发生在切图失败的极端情况)跳过该格，不编造图片。
    """
    by_cell = actor_sheet_cell_paths(list(paths))
    derived: dict[str, str] = {}
    for cell, source_cell in MIRRORED_CELL_SOURCES.items():
        source = by_cell.get(source_cell)
        if cell in by_cell or source is None:
            continue
        with Image.open(source) as image:
            mirrored = ImageOps.mirror(image.convert("RGB"))
        by_cell[cell] = _save_cell(mirrored, Path(source).parent, cell)
        derived[cell] = source_cell
    for cell in ACTOR_SHEET_CELL_ORDER:
        if cell in by_cell or cell not in DERIVED_CELL_SOURCES:
            continue
        source_cell, fractions = DERIVED_CELL_SOURCES[cell]
        crop, source = None, None
        for candidate in (source_cell, *DERIVED_SOURCE_FALLBACKS.get(source_cell, ())):
            path = by_cell.get(candidate)
            if path is None:
                continue
            with Image.open(path) as image:
                if not _usable_source(candidate, image.size):
                    continue
                crop = _derived_crop(image.convert("RGB"), fractions)
            if crop is not None:
                source_cell, source = candidate, path
                break
        if crop is None:
            continue
        shortest = min(crop.size)
        if shortest < DERIVED_CELL_MIN_SIDE:
            scale = DERIVED_CELL_MIN_SIDE / shortest
            crop = crop.resize(
                (round(crop.width * scale), round(crop.height * scale)), Image.Resampling.LANCZOS,
            )
        by_cell[cell] = _save_cell(crop, Path(source).parent, cell)
        derived[cell] = source_cell
    ordered = [Path(by_cell[cell]) for cell in ACTOR_SHEET_CELL_ORDER if cell in by_cell]
    return ordered, derived


def split_five_view_sheet(source: str | Path, output_directory: str | Path) -> list[Path]:
    """Materialize five stable view assets from an ordered horizontal sheet.

    旧版五视图等宽五栏排版。新流水线走 ``split_actor_sheet``；这个函数只为
    已经存在磁盘上的旧整板保留，删掉的话历史任务重开就拆不出图了。
    """
    image = _open_image(source)
    if image.width < 5 or image.height < 1:
        raise ValueError("five-view sheet is too small")
    target_dir = Path(output_directory).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    names = ["front", "front_three_quarter", "profile", "rear_three_quarter", "back"]
    boundaries = [round(image.width * index / 5) for index in range(6)]
    paths: list[Path] = []
    for index, name in enumerate(names):
        crop = image.crop((boundaries[index], 0, boundaries[index + 1], image.height))
        path = target_dir / f"{index + 1}_{name}.png"
        crop.save(path, format="PNG", optimize=True)
        paths.append(path)
    return paths

# -*- coding: utf-8 -*-
"""参考图送给视频模型之前，先放进供应商写明的尺寸范围。

Seedance 2.0(火山 Ark)与 MiniMax 的图生视频都只收宽高比在 2:5 到 5:2(0.4–2.5)之间、短边不小于
300 像素的图。数字演员的身份视图是从设定集里裁出来的竖条(如 804×2048，宽高比 0.39)，原样发过去
整条请求就被拒，网关只能降级成不带任何参考的文生视频——人物和分镜画面全丢。

这里只补边、不裁剪：竖条左右补黑边、横条上下补黑边，画面里的人一像素不少；太小的等比放大，
太大的等比缩小。只处理内嵌的 data URI(本机产出的图)；远程 URL 由供应商自己取，不在这里下载。
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import math
import re

from app import settings

logger = logging.getLogger("app.core.reference_fit")

MIN_RATIO = 0.4
MAX_RATIO = 2.5
MIN_SIDE = 300
MAX_SIDE = 6000
COMPACT_MAX_SIDE = 2048
COMPACT_JPEG_QUALITY = 90
_DATA_URI = re.compile(r"data:image/(png|jpeg|jpg|webp);base64,(.+)", re.DOTALL)


def compact_image_reference(value: object) -> object:
    """生图参考图的内嵌 data URI 重新编码成 JPEG，长边不超过 COMPACT_MAX_SIDE；变小才替换。

    一格分镜要带 5–7 张内嵌 PNG，请求体中位数约 8.7 MB：参考图只用来认人认景，不需要无损。
    带透明通道的图(元素抠图)和读不了的图原样返回。IMAGE_REFERENCE_COMPACT=0 关闭。
    """
    if not isinstance(value, str) or not value.startswith("data:image/") or not settings.env_flag("IMAGE_REFERENCE_COMPACT", True):
        return value
    match = _DATA_URI.fullmatch(value)
    if match is None:
        return value
    try:
        from PIL import Image

        with Image.open(io.BytesIO(base64.b64decode(match.group(2)))) as image:
            if "A" in image.getbands() and image.getchannel("A").getextrema()[0] < 255:
                return value
            picture = image.convert("RGB")
        if max(picture.size) > COMPACT_MAX_SIDE:
            picture.thumbnail((COMPACT_MAX_SIDE, COMPACT_MAX_SIDE), Image.LANCZOS)
        buffer = io.BytesIO()
        # 不做色度抽样：人脸和服饰边缘的颜色是参考图要传达的东西。
        picture.save(buffer, format="JPEG", quality=COMPACT_JPEG_QUALITY, subsampling=0, optimize=True)
    except (OSError, ValueError, binascii.Error) as error:
        logger.debug("参考图未压缩，按原图发送: %s", type(error).__name__)
        return value
    compact = f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"
    return compact if len(compact) < len(value) else value


def _target_size(width: int, height: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """(缩放后的图尺寸, 补边后的画布尺寸)：先压到长边上限，再补边到宽高比范围，最后补足短边。"""
    scale = min(1.0, MAX_SIDE / max(width, height))
    image_w, image_h = max(1, round(width * scale)), max(1, round(height * scale))
    canvas_w, canvas_h = image_w, image_h
    if canvas_w / canvas_h < MIN_RATIO:
        canvas_w = math.ceil(canvas_h * MIN_RATIO)
    elif canvas_w / canvas_h > MAX_RATIO:
        canvas_h = math.ceil(canvas_w / MAX_RATIO)
    if min(canvas_w, canvas_h) < MIN_SIDE:
        # 画布已在比例范围内，短边不足 300 时长边至多 750：整体等比放大不会越过长边上限。
        up = MIN_SIDE / min(canvas_w, canvas_h)
        image_w, image_h = max(1, round(image_w * up)), max(1, round(image_h * up))
        canvas_w, canvas_h = max(image_w, math.ceil(canvas_w * up)), max(image_h, math.ceil(canvas_h * up))
    return (image_w, image_h), (canvas_w, canvas_h)


def within_limits(width: int, height: int) -> bool:
    return MIN_RATIO <= width / height <= MAX_RATIO and min(width, height) >= MIN_SIDE and max(width, height) <= MAX_SIDE


def fit_image(value: str | None) -> str | None:
    """超出范围的内嵌图补边/缩放后返回新的 data URI；范围内的、远程 URL、读不出的图原样返回。"""
    if not isinstance(value, str) or not value.startswith("data:image/"):
        return value
    match = _DATA_URI.fullmatch(value)
    if not match:
        return value
    try:
        raw = base64.b64decode(match[2], validate=True)
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            width, height = source.size
            if not width or not height or within_limits(width, height):
                return value
            image_size, canvas_size = _target_size(width, height)
            fmt = "PNG" if match[1] == "png" else "JPEG"
            picture = source.convert("RGBA" if fmt == "PNG" else "RGB")
            if picture.size != image_size:
                picture = picture.resize(image_size, Image.LANCZOS)
            background = (0, 0, 0, 255) if fmt == "PNG" else (0, 0, 0)
            canvas = Image.new(picture.mode, canvas_size, background)
            canvas.paste(picture, ((canvas_size[0] - image_size[0]) // 2, (canvas_size[1] - image_size[1]) // 2))
            buffer = io.BytesIO()
            canvas.save(buffer, format=fmt, **({"quality": 92} if fmt == "JPEG" else {}))
    except (ValueError, binascii.Error, OSError) as exc:
        logger.warning("[ReferenceFit] 参考图无法读取，原样发送: %s", type(exc).__name__)
        return value
    logger.info("[ReferenceFit] 参考图 %sx%s 超出供应商范围，已补边为 %sx%s", width, height, *canvas_size)
    mime = "png" if fmt == "PNG" else "jpeg"
    return f"data:image/{mime};base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def fit_images(values: list | None) -> list | None:
    return [fit_image(value) for value in values] if values else values


__all__ = ["MAX_RATIO", "MAX_SIDE", "MIN_RATIO", "MIN_SIDE", "fit_image", "fit_images", "within_limits"]

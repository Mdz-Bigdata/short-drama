"""A scene's 360° backdrop: the prompt that asks for one, and making what comes back fit for wrapping.

An equirectangular picture wraps a sphere, so it must be exactly 2:1 and its left and right
edges must meet. A model does not guarantee either, so both are put right here; how far apart
the edges were is kept, because a large gap means the seam may still show.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageChops, ImageOps, ImageStat

# 2:1, staying under the roughly 4.6-megapixel ceiling of a single image from the image models.
PANORAMA_SIZE = "3024x1512"
MAX_WIDTH = 4096
MIN_WIDTH = 256
_SEAM_BAND = 0.015
# Mean edge difference (0-255) above which the seam is worth warning about.
SEAM_WARNING = 28.0
MAX_DESCRIPTION = 1500

_FORMAT_TEXT = (
    "生成一张 360° 全景环境图：等距圆柱投影（equirectangular），画幅严格 2:1。"
    "地平线水平穿过画面正中；画面左右两端在环绕时无缝相接，左边缘与右边缘的景物、光线和颜色完全连续，不留接缝。"
    "画面顶部是天空或天花板、底部是地面，靠近上下两极的景物按全景投影自然拉伸。"
    "这是一个空场景：全场没有人，不出现人物、人影、剪影、倒影里的人或人体局部。"
    "写实电影质感，同一时段、同一光向与色温贯穿全景。"
    "画面里不出现文字、字幕、标签、水印和 Logo。"
)
_REFERENCE_TEXT = "参考所给图片的地点、陈设、材质、色调与光线，把它扩展成环绕一周的完整空间；图中的人物一律不要。"


@dataclass(frozen=True)
class Panorama:
    content: bytes
    width: int
    height: int
    seam_delta: float


def scene_brief(scene: Mapping[str, Any] | None) -> str:
    """What the screenplay says about the place, in a line, so an empty description still names the scene."""
    if not scene:
        return ""
    parts = [
        str(scene.get(key) or "").strip()
        for key in ("location", "scene_name", "name", "time_of_day", "time", "atmosphere", "summary")
    ]
    return "，".join(dict.fromkeys(part for part in parts if part))[:400]


def panorama_prompt(description: str, *, scene: Mapping[str, Any] | None = None, has_reference: bool = False) -> str:
    place = " ".join(str(description or "").split())[:MAX_DESCRIPTION] or scene_brief(scene)
    if not place and not has_reference:
        raise ValueError("请描述这个全景的地点，或给一张参考图")
    pieces = [_FORMAT_TEXT]
    if place:
        pieces.append(f"场景：{place}。")
    if has_reference:
        pieces.append(_REFERENCE_TEXT)
    return "".join(pieces)


def _blend_edges(image: Image.Image) -> Image.Image:
    """Cross-fade a thin band on each side so the two edges carry the same colours where they meet."""
    width, height = image.size
    band = max(2, round(width * _SEAM_BAND))
    left = image.crop((0, 0, band, height))
    right = image.crop((width - band, 0, width, height))
    # Half of the other side at the very edge, fading to none at the inside of the band.
    fade = ImageOps.mirror(Image.linear_gradient("L").rotate(90, expand=True).resize((band, height)))
    fade = fade.point(lambda value: value // 2)
    new_left = Image.composite(ImageOps.mirror(right), left, fade)
    new_right = Image.composite(ImageOps.mirror(left), right, ImageOps.mirror(fade))
    result = image.copy()
    result.paste(new_left, (0, 0))
    result.paste(new_right, (width - band, 0))
    return result


def _edge_delta(image: Image.Image) -> float:
    width, height = image.size
    left = image.crop((0, 0, 1, height))
    right = image.crop((width - 1, 0, width, height))
    return round(float(sum(ImageStat.Stat(ImageChops.difference(left, right)).mean) / 3), 2)


def fit_panorama(content: bytes) -> Panorama:
    """Exactly 2:1, edges blended, as a JPEG small enough to be a desk backdrop."""
    try:
        with Image.open(io.BytesIO(content)) as opened:
            image = opened.convert("RGB")
    except OSError as exc:
        raise ValueError("图像模型返回的不是可用的图片") from exc
    width, height = image.size
    if width < MIN_WIDTH:
        raise ValueError(f"生成的图片太小（{width}×{height}），不能作全景")
    target_width = min(width, MAX_WIDTH)
    target = (target_width - target_width % 2, (target_width - target_width % 2) // 2)
    # Keep the middle: the horizon is asked for there, and the poles are the part that matters least.
    fitted = ImageOps.fit(image, target, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    seam_delta = _edge_delta(fitted)
    blended = _blend_edges(fitted)
    buffer = io.BytesIO()
    blended.save(buffer, format="JPEG", quality=90, optimize=True)
    return Panorama(content=buffer.getvalue(), width=target[0], height=target[1], seam_delta=seam_delta)

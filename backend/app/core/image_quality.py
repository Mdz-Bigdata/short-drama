"""Deterministic preflight checks for actor sheets (and legacy five-view sheets)."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image
from pydantic import BaseModel

from app.core.actor_sheet_layout import (
    ACTOR_SHEET_CELL_ORDER,
    FULL_BODY_CELLS,
)
from app.schema.production import IDENTITY_VIEW_ORDER


class ImageQualityIssue(BaseModel):
    code: str
    message: str
    view_index: int | None = None


class FiveViewQualityReport(BaseModel):
    """两代质检共用的报告。

    ``entropy`` 每个被检查的格子一项（旧五视图 5 项、设定集 25 项），
    ``unique_view_hashes`` 是五个身份锚点里互不相同的角度数。
    形状保持不变，drama_service 落库、看板编译、资产库复用都不用改读法。
    """

    passed: bool
    entropy: list[float]
    palette_similarity: float
    unique_view_hashes: int
    issues: list[ImageQualityIssue]


def _entropy(image: Image.Image) -> float:
    histogram = image.convert("L").histogram()
    total = sum(histogram) or 1
    return -sum(
        (count / total) * math.log2(count / total)
        for count in histogram
        if count
    )


def _palette_histogram(image: Image.Image) -> list[float]:
    image = image.resize((64, 64), Image.Resampling.BILINEAR).convert("RGB")
    buckets = [0.0] * 48
    pixel_data = image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()
    for red, green, blue in pixel_data:
        buckets[min(red // 16, 15)] += 1
        buckets[16 + min(green // 16, 15)] += 1
        buckets[32 + min(blue // 16, 15)] += 1
    norm = math.sqrt(sum(value * value for value in buckets)) or 1
    return [value / norm for value in buckets]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _difference_hash(image: Image.Image) -> int:
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixel_data = gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata()
    pixels = list(pixel_data)
    bits = 0
    for row in range(8):
        for column in range(8):
            left = pixels[row * 9 + column]
            right = pixels[row * 9 + column + 1]
            bits = (bits << 1) | int(left > right)
    return bits


def _hash_variety(image: Image.Image) -> int:
    """差分哈希里少数位的个数（0–32）：0 表示整格没有任何局部明暗变化。

    纯色块、纯渐变底的差分哈希要么全 0 要么全 1，真实照片内容一定是混的。
    复用 _difference_hash，不另造一套图像度量。
    """
    bits = _difference_hash(image)
    ones = bin(bits).count("1")
    return min(ones, 64 - ones)


def _is_near_uniform(image: Image.Image) -> bool:
    """空白格/纯色格：熵极低，或差分哈希毫无局部结构。"""
    return _entropy(image) < 1.2 or _hash_variety(image) < 3


def validate_actor_sheet_images(paths: list[str | Path]) -> FiveViewQualityReport:
    """数字演员设定集 25 格的逐格质检。

    ``paths`` 必须是 ``split_actor_sheet`` 的返回值，顺序即 ACTOR_SHEET_CELL_ORDER。

    四道闸：
    1. 逐格空白/纯色检查——模型没画满网格时，裁出来的就是一片底色；
    2. 五个身份锚点至少三个角度互不相同（沿用旧的重复角度检查）；
    3. 正面/侧面/背面三张全身必须两两不同，否则根本没转面；
    4. 左区大正面与正脸特写不能是同一张裁切，否则细节矩阵没真的画出来。
    """
    expected = len(ACTOR_SHEET_CELL_ORDER)
    if len(paths) != expected:
        return FiveViewQualityReport(
            passed=False,
            entropy=[],
            palette_similarity=0,
            unique_view_hashes=0,
            issues=[ImageQualityIssue(
                code="cell_count", message=f"设定集必须恰好提供{expected}个格子。",
            )],
        )
    images: dict[str, Image.Image] = {}
    issues: list[ImageQualityIssue] = []
    entropies: list[float] = []
    for index, (cell, path) in enumerate(zip(ACTOR_SHEET_CELL_ORDER, paths), start=1):
        try:
            image = Image.open(Path(path)).convert("RGB")
            image.load()
        except Exception as exc:
            issues.append(ImageQualityIssue(
                code="unreadable", message=f"格子无法读取：{type(exc).__name__}", view_index=index,
            ))
            continue
        images[cell] = image
        entropies.append(round(_entropy(image), 4))
        if image.width < 64 or image.height < 64:
            issues.append(ImageQualityIssue(
                code="low_resolution", message="格子分辨率低于64×64。", view_index=index,
            ))
        if _is_near_uniform(image):
            issues.append(ImageQualityIssue(
                code="blank_cell", message="格子疑似空白或纯色，模型未在该格作画。", view_index=index,
            ))
    if len(images) != expected:
        return FiveViewQualityReport(
            passed=False, entropy=entropies, palette_similarity=0,
            unique_view_hashes=0, issues=issues,
        )

    identity_hashes = {_difference_hash(images[view]) for view in IDENTITY_VIEW_ORDER}
    if len(identity_hashes) < 3:
        issues.append(ImageQualityIssue(
            code="duplicate_views",
            message="五个身份锚点中至少三个疑似重复，未形成有效转面。",
        ))
    full_body_hashes = [_difference_hash(images[view]) for view in FULL_BODY_CELLS]
    if len(set(full_body_hashes)) < len(FULL_BODY_CELLS):
        issues.append(ImageQualityIssue(
            code="duplicate_full_body",
            message="正面/侧面/背面三张全身视图中存在重复，三视图未真正转面。",
        ))
    if _difference_hash(images["portrait"]) == _difference_hash(images["face_front"]):
        issues.append(ImageQualityIssue(
            code="portrait_matches_face",
            message="左区大正面与细节矩阵正脸特写是同一张裁切，细节矩阵未按版面作画。",
        ))
    # 色彩漂移只在三张全身之间比——头部特写和全身的配色天然不同，
    # 混在一起比只会让每张合格的设定集都被判服装漂移。
    full_body_palettes = [_palette_histogram(images[view]) for view in FULL_BODY_CELLS]
    palette_similarity = min(
        _cosine(full_body_palettes[index], full_body_palettes[index + 1])
        for index in range(len(full_body_palettes) - 1)
    )
    if palette_similarity < 0.65:
        issues.append(ImageQualityIssue(
            code="palette_drift",
            message="三张全身视图之间色彩/服装调色差异过大，疑似人物或服装漂移。",
        ))
    return FiveViewQualityReport(
        passed=not issues,
        entropy=entropies,
        palette_similarity=round(palette_similarity, 4),
        unique_view_hashes=len(identity_hashes),
        issues=issues,
    )


def validate_five_view_images(paths: list[str | Path]) -> FiveViewQualityReport:
    """旧版五视图整板的五张等宽裁切质检。

    新流水线走 ``validate_actor_sheet_images``；这个函数只服务磁盘上已有的旧资产。
    """
    if len(paths) != 5:
        return FiveViewQualityReport(
            passed=False,
            entropy=[],
            palette_similarity=0,
            unique_view_hashes=0,
            issues=[ImageQualityIssue(code="view_count", message="必须恰好提供5个视图。")],
        )
    images: list[Image.Image] = []
    issues: list[ImageQualityIssue] = []
    entropies: list[float] = []
    for index, path in enumerate(paths, start=1):
        try:
            image = Image.open(Path(path)).convert("RGB")
            image.load()
        except Exception as exc:
            issues.append(ImageQualityIssue(
                code="unreadable", message=f"视图无法读取：{type(exc).__name__}", view_index=index,
            ))
            continue
        images.append(image)
        if image.width < 128 or image.height < 256:
            issues.append(ImageQualityIssue(
                code="low_resolution", message="视图分辨率低于128×256。", view_index=index,
            ))
        entropy = _entropy(image)
        entropies.append(round(entropy, 4))
        if entropy < 1.2:
            issues.append(ImageQualityIssue(
                code="low_entropy", message="视图疑似空白或细节严重不足。", view_index=index,
            ))
    if len(images) != 5:
        return FiveViewQualityReport(
            passed=False, entropy=entropies, palette_similarity=0,
            unique_view_hashes=0, issues=issues,
        )
    histograms = [_palette_histogram(image) for image in images]
    similarities = [
        _cosine(histograms[index], histograms[index + 1])
        for index in range(4)
    ]
    palette_similarity = min(similarities)
    if palette_similarity < 0.65:
        issues.append(ImageQualityIssue(
            code="palette_drift",
            message="相邻视图色彩/服装调色差异过大，疑似人物或服装漂移。",
        ))
    unique_hashes = len({_difference_hash(image) for image in images})
    if unique_hashes < 3:
        issues.append(ImageQualityIssue(
            code="duplicate_views",
            message="五视图中至少三个角度疑似重复，未形成有效转面。",
        ))
    return FiveViewQualityReport(
        passed=not issues,
        entropy=entropies,
        palette_similarity=round(palette_similarity, 4),
        unique_view_hashes=unique_hashes,
        issues=issues,
    )

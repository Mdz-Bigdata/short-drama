"""Deterministic preflight checks for five-view character sheets."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image
from pydantic import BaseModel


class ImageQualityIssue(BaseModel):
    code: str
    message: str
    view_index: int | None = None


class FiveViewQualityReport(BaseModel):
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


def validate_five_view_images(paths: list[str | Path]) -> FiveViewQualityReport:
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

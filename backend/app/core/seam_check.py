# -*- coding: utf-8 -*-
"""接缝质检：前一段的末帧和后一段的首帧到底接没接上。

同一个连续镜头切成几段生成，后一段按前一段的末帧开场，但模型不保证照着画：机位挪了、人物换了姿势、
色调变了，接缝处就会跳。这里把两张图放在一起量三样东西：

* **结构**：缩到 32×18 的灰度图逐像素比，看构图和人物位置有没有变；
* **明暗分布**：灰度直方图的差，看光比和曝光有没有变；
* **色调**：RGB 三通道的均值差，看冷暖有没有变。

三项合成一个 0…1 的差异分，再给一个结论：接上了 / 可疑 / 跳了。它只量画面，不懂剧情：
一个有意的大动作也会被记成可疑，结论是给人看的提示，不是自动拒收。只用 PIL。
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps

_THUMB = (32, 18)
#: 缩略图上一个像素灰度变了这么多才算「变了」(0…255)。
_CHANGED = 32
#: 差异分到这里算可疑，到这里算跳了。小于 SUSPECT 的接缝人眼一般看不出来。
SUSPECT = 0.15
JUMP = 0.35
VERDICT_ZH = {"good": "接上了", "suspect": "接缝可疑", "jump": "接缝跳了"}


@dataclass(frozen=True)
class SeamReport:
    score: float
    verdict: str
    structure: float
    exposure: float
    tone: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score, "verdict": self.verdict, "label": VERDICT_ZH[self.verdict],
            "structure": self.structure, "exposure": self.exposure, "tone": self.tone, "detail": self.detail,
        }

    @property
    def detail(self) -> str:
        worst = max(("构图或人物位置", self.structure), ("明暗", self.exposure), ("色调", self.tone), key=lambda item: item[1])
        if self.verdict == "good":
            return f"前后两帧基本一致（差异 {self.score:.2f}）"
        return f"差异 {self.score:.2f}，主要在{worst[0]}；看一眼接缝，不对就重跑后一段"


def _open(picture: bytes | str) -> Image.Image:
    if isinstance(picture, str):
        if picture.startswith("data:"):
            picture = base64.b64decode(picture.split(",", 1)[1])
        else:
            with open(picture, "rb") as handle:
                picture = handle.read()
    return ImageOps.exif_transpose(Image.open(io.BytesIO(picture))).convert("RGB")


def _structure(a: Image.Image, b: Image.Image) -> float:
    """构图差：先拉平明暗(曝光的差归「明暗」管)，再看平均像素差和「明显变了的像素占比」，取大的。

    平均差对一个人物从画左挪到画右不敏感(大部分像素没变)，占比对它敏感；两者取大，哪种跳都漏不掉。
    """
    small_a = list(ImageOps.autocontrast(a.convert("L").resize(_THUMB, Image.Resampling.BOX)).getdata())
    small_b = list(ImageOps.autocontrast(b.convert("L").resize(_THUMB, Image.Resampling.BOX)).getdata())
    diffs = [abs(x - y) for x, y in zip(small_a, small_b)]
    mean = sum(diffs) / (255 * len(diffs))
    changed = sum(1 for d in diffs if d > _CHANGED) / len(diffs)
    return max(mean, changed)


def _exposure(a: Image.Image, b: Image.Image) -> float:
    """两张图灰度直方图的差，归一到 0…1（两张互不重叠的直方图为 1）。"""
    ha, hb = a.convert("L").histogram(), b.convert("L").histogram()
    na, nb = sum(ha) or 1, sum(hb) or 1
    # 16 级分桶，免得同一张图轻微的噪声也算差异。
    bins_a = [sum(ha[i:i + 16]) / na for i in range(0, 256, 16)]
    bins_b = [sum(hb[i:i + 16]) / nb for i in range(0, 256, 16)]
    return sum(abs(x - y) for x, y in zip(bins_a, bins_b)) / 2


def _tone(a: Image.Image, b: Image.Image) -> float:
    def mean(image: Image.Image) -> tuple[float, float, float]:
        pixels = image.resize(_THUMB, Image.Resampling.BOX).getdata()
        total = [0.0, 0.0, 0.0]
        count = 0
        for r, g, b in pixels:
            total[0] += r
            total[1] += g
            total[2] += b
            count += 1
        return tuple(value / max(1, count) for value in total)  # type: ignore[return-value]

    ma, mb = mean(a), mean(b)
    return sum(abs(x - y) for x, y in zip(ma, mb)) / (3 * 255)


def compare(before: bytes | str, after: bytes | str) -> SeamReport:
    """``before`` 是前一段的末帧，``after`` 是后一段的首帧：文件内容、文件路径或 data URI 都行。"""
    a, b = _open(before), _open(after)
    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.LANCZOS)
    structure, exposure, tone = _structure(a, b), _exposure(a, b), _tone(a, b)
    # 结构权重最大：人物挪了位置观众一眼就看见；色调差一点往往是压缩和调色的正常波动。
    score = round(min(1.0, 0.7 * structure + 0.2 * exposure + 0.1 * tone), 3)
    verdict = "jump" if score >= JUMP else "suspect" if score >= SUSPECT else "good"
    return SeamReport(score=score, verdict=verdict, structure=round(structure, 3), exposure=round(exposure, 3), tone=round(tone, 3))


__all__ = ["JUMP", "SUSPECT", "SeamReport", "VERDICT_ZH", "compare"]

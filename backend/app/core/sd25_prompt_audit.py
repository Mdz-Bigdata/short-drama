"""Read-only structural audit for the project's five-part Seedance 2.5 prompts.

Independently authored for this project. The checks are derived from the
project's own reference notes under ``backend/skills/sd-2-5-prompt/references``
and from the ``sd25-pe`` contract; no upstream implementation is copied,
translated or executed here. See that skill's ``SOURCE.json`` for provenance.

The auditor never mutates the prompt, never interprets it as instructions, and
never contacts a model or generation provider. It reads text and returns
findings plus a digest of exactly what it read.
"""

from __future__ import annotations

import hashlib
import re

from app.schema.production import (
    Sd25PromptAuditFinding,
    Sd25PromptAuditRequest,
    Sd25PromptAuditResult,
)

# Timeline spans are written either bare ("0—2秒") or wrapped in the delivery
# brackets ("【0—2秒】"). Compose the pattern from named fragments so the
# accepted separators can be widened without rewriting the whole expression.
_DECIMAL = r"\d+(?:\.\d+)?"
_SEPARATOR = r"[-—–~～]"
_SPAN_PATTERN = re.compile(
    rf"(?P<lo>{_DECIMAL})\s*秒?\s*{_SEPARATOR}\s*(?P<hi>{_DECIMAL})\s*秒"
)

# Tolerances: spans are compared in seconds, so a hundredth of a second absorbs
# float noise while a twentieth is the largest drift we accept against a
# caller-declared total duration.
_EDGE_TOLERANCE = 0.01
_DURATION_TOLERANCE = 0.05

# The five delivery headings, in the order they must appear in the body.
_REQUIRED_HEADINGS: tuple[tuple[str, str], ...] = (
    ("subject.missing", "【主体】"),
    ("style.missing", "【风格】"),
    ("timeline.section_missing", "【时间线】"),
    ("bgm.missing", "【BGM】"),
    ("constraints.missing", "【限制】"),
)

# Reference-asset markers the project emits, and the responsibility verbs that
# make a marker accountable. Stored as frozensets: membership is what matters,
# order carries no meaning.
_ASSET_MARKERS = frozenset(
    {"@图", "@图片", "@Image", "@视频", "@Video", "@音频", "@Audio"}
)
_RESPONSIBILITY_MARKERS = frozenset(
    {"用于", "只采用", "只参考", "负责", "锁定", "不采用", "不参考", "不复制", "不迁移"}
)

# Action vocabulary drawn from this project's own storyboard and fight-scene
# guides: any of these implies a spatial chain the timeline has to close.
_ACTION_MARKERS = frozenset(
    {
        "打斗", "格挡", "闪避", "扑倒", "推搡", "拉扯", "挥拳", "踢击",
        "追逐", "换位", "抛接", "投掷", "飞向", "坠落", "撞击",
        "射流", "喷溅", "攻击",
    }
)
# Words that actually establish that chain: an origin, a route, a bearing, or a
# terminus. Written this loosely on purpose — the check flags silence, not style.
_CAUSAL_MARKERS = frozenset(
    {
        "起点", "终点", "落点", "路径", "轨迹", "来向", "去向", "朝向",
        "发力", "受力", "作用于", "经过", "从", "向", "沿",
    }
)

# Brand names this project screens for in unbranded deliveries. A finite,
# project-maintained list: passing it is not proof that a prompt is unbranded.
_SCREENED_BRANDS = frozenset(
    {
        "可口可乐", "coca-cola", "coca cola", "百事", "pepsi", "雪碧", "sprite",
        "芬达", "fanta", "红牛", "red bull", "农夫山泉", "元气森林",
        "麦当劳", "mcdonald", "肯德基", "kfc", "星巴克", "starbucks",
        "耐克", "nike", "阿迪达斯", "adidas", "苹果手机", "iphone",
        "华为", "huawei", "小米手机", "罗技", "logitech",
    }
)
# Phrases that count as an explicit brand boundary in the constraints section.
_BRAND_BOUNDARY_MARKERS = frozenset(
    {"无品牌", "无商标", "不出现现实品牌", "不出现任何文字", "不出现商标", "不出现水印"}
)


class Sd25PromptAuditor:
    """Inspect prompt text without rewriting it or calling any provider."""

    @staticmethod
    def _report(level: str, code: str, message: str) -> Sd25PromptAuditFinding:
        return Sd25PromptAuditFinding(level=level, code=code, message=message)

    @staticmethod
    def _mentions_any(text: str, markers: frozenset[str]) -> bool:
        return any(marker in text for marker in markers)

    def audit(self, request: Sd25PromptAuditRequest) -> Sd25PromptAuditResult:
        text = request.prompt
        findings: list[Sd25PromptAuditFinding] = []

        self._check_headings(text, findings)
        timeline_end = self._check_timeline(text, request.duration_seconds, findings)
        self._check_asset_scope(text, findings)
        self._check_action_chain(text, findings)
        if request.unbranded:
            self._check_brand_boundary(text, findings)

        return Sd25PromptAuditResult(
            ok=not findings,
            errors=sum(item.level == "error" for item in findings),
            warnings=sum(item.level == "warning" for item in findings),
            findings=findings,
            timeline_end_seconds=timeline_end,
            prompt_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

    def _check_headings(self, text: str, findings: list[Sd25PromptAuditFinding]) -> None:
        for code, heading in _REQUIRED_HEADINGS:
            if heading not in text:
                findings.append(self._report(
                    "error", code, f"正文里找不到 {heading} 这一段，五段结构不成立。"
                ))

    def _check_timeline(
        self,
        text: str,
        declared_duration: float | None,
        findings: list[Sd25PromptAuditFinding],
    ) -> float | None:
        spans = [
            (float(match.group("lo")), float(match.group("hi")))
            for match in _SPAN_PATTERN.finditer(text)
        ]
        if not spans:
            findings.append(self._report(
                "error", "timeline.missing", "正文里没有可解析的秒数区间，时间轴无法校验。"
            ))
            return None

        for low, high in spans:
            if high <= low:
                findings.append(self._report(
                    "error",
                    "timeline.invalid",
                    f"区间 {low:g}—{high:g} 秒的终点没有落在起点之后。",
                ))

        if spans != sorted(spans):
            findings.append(self._report(
                "error", "timeline.order", "各区间的起点没有一路递增，事件顺序被打乱。"
            ))

        if abs(spans[0][0]) > _EDGE_TOLERANCE:
            findings.append(self._report(
                "error",
                "timeline.start",
                f"第一个区间从 {spans[0][0]:g} 秒起步，时间轴必须由 0 秒接起。",
            ))

        for (_, earlier_end), (later_start, _) in zip(spans, spans[1:]):
            drift = later_start - earlier_end
            if drift > _EDGE_TOLERANCE:
                findings.append(self._report(
                    "error",
                    "timeline.gap",
                    f"{earlier_end:g} 秒到 {later_start:g} 秒之间没有任何段落覆盖。",
                ))
            elif drift < -_EDGE_TOLERANCE:
                findings.append(self._report(
                    "error",
                    "timeline.overlap",
                    f"两个区间在 {later_start:g} 秒处彼此压盖。",
                ))

        timeline_end = max(high for _, high in spans)
        if (
            declared_duration is not None
            and abs(timeline_end - declared_duration) > _DURATION_TOLERANCE
        ):
            findings.append(self._report(
                "error",
                "timeline.duration",
                f"时间轴收在 {timeline_end:g} 秒，与传入的 {declared_duration:g} 秒不符。",
            ))
        return timeline_end

    def _check_asset_scope(self, text: str, findings: list[Sd25PromptAuditFinding]) -> None:
        if self._mentions_any(text, _ASSET_MARKERS) and not self._mentions_any(
            text, _RESPONSIBILITY_MARKERS
        ):
            findings.append(self._report(
                "warning",
                "reference.scope",
                "引用了参考素材，却没有写清每份素材负责什么、不负责什么。",
            ))

    def _check_action_chain(self, text: str, findings: list[Sd25PromptAuditFinding]) -> None:
        if self._mentions_any(text, _ACTION_MARKERS) and not self._mentions_any(
            text, _CAUSAL_MARKERS
        ):
            findings.append(self._report(
                "warning",
                "action.causality",
                "写到了复杂动作，但没有交代它从哪里发起、怎么走、最后停在哪里。",
            ))

    def _check_brand_boundary(self, text: str, findings: list[Sd25PromptAuditFinding]) -> None:
        lowered = text.lower()
        hits = sorted(brand for brand in _SCREENED_BRANDS if brand.lower() in lowered)
        if hits:
            findings.append(self._report(
                "error",
                "brand.detected",
                "无品牌交付里出现了受检品牌名：" + "、".join(hits),
            ))
        if not self._mentions_any(text, _BRAND_BOUNDARY_MARKERS):
            findings.append(self._report(
                "warning",
                "brand.lock",
                "选了无品牌模式，限制段却没有写明品牌、商标或水印的边界。",
            ))

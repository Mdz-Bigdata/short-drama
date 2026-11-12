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

from app.core import prompt_data
from app.schema.production import (
    Sd25PromptAuditFinding,
    Sd25PromptAuditRequest,
    Sd25PromptAuditResult,
)

# The headings, marker words, patterns, tolerances and finding messages the audit reads:
# app/data/prompt/sd25_prompt_audit.json.
_WORDING = "sd25_prompt_audit"


def _says(key: str, /, **values: object) -> str:
    """A finding message of the audit's wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _markers(key: str) -> frozenset[str]:
    return frozenset(prompt_data.words(_WORDING, key))


# Timeline spans are written either bare ("0—2秒") or wrapped in the delivery
# brackets ("【0—2秒】"). Compose the pattern from named fragments so the
# accepted separators can be widened without rewriting the whole expression.
_DECIMAL = prompt_data.text(_WORDING, "decimal")
_SEPARATOR = prompt_data.text(_WORDING, "separator")
_SPAN_PATTERN = re.compile(
    prompt_data.text(_WORDING, "span_pattern").format(decimal=_DECIMAL, separator=_SEPARATOR)
)

# Tolerances: spans are compared in seconds, so a hundredth of a second absorbs
# float noise while a twentieth is the largest drift we accept against a
# caller-declared total duration.
_EDGE_TOLERANCE = float(prompt_data.value(_WORDING, "edge_tolerance"))
_DURATION_TOLERANCE = float(prompt_data.value(_WORDING, "duration_tolerance"))

# The five delivery headings, in the order they must appear in the body, each under the
# finding code it raises when missing.
_HEADING_CODES = (
    "subject.missing",
    "style.missing",
    "timeline.section_missing",
    "bgm.missing",
    "constraints.missing",
)
_REQUIRED_HEADINGS: tuple[tuple[str, str], ...] = tuple(
    (code, str(prompt_data.load(_WORDING)["headings"][code])) for code in _HEADING_CODES
)

# Reference-asset markers the project emits, and the responsibility verbs that
# make a marker accountable. Stored as frozensets: membership is what matters,
# order carries no meaning.
_ASSET_MARKERS = _markers("asset_markers")
_RESPONSIBILITY_MARKERS = _markers("responsibility_markers")

# Action vocabulary drawn from this project's own storyboard and fight-scene
# guides: any of these implies a spatial chain the timeline has to close.
_ACTION_MARKERS = _markers("action_markers")
# Words that actually establish that chain: an origin, a route, a bearing, or a
# terminus. Written this loosely on purpose — the check flags silence, not style.
_CAUSAL_MARKERS = _markers("causal_markers")

# Brand names this project screens for in unbranded deliveries. A finite,
# project-maintained list: passing it is not proof that a prompt is unbranded.
_SCREENED_BRANDS = _markers("screened_brands")
# Phrases that count as an explicit brand boundary in the constraints section.
_BRAND_BOUNDARY_MARKERS = _markers("brand_boundary_markers")


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
                    "error", code, _says("heading_missing", heading=heading)
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
                "error", "timeline.missing", _says("timeline_missing")
            ))
            return None

        for low, high in spans:
            if high <= low:
                findings.append(self._report(
                    "error",
                    "timeline.invalid",
                    _says("timeline_invalid", low=low, high=high),
                ))

        if spans != sorted(spans):
            findings.append(self._report(
                "error", "timeline.order", _says("timeline_order")
            ))

        if abs(spans[0][0]) > _EDGE_TOLERANCE:
            findings.append(self._report(
                "error",
                "timeline.start",
                _says("timeline_start", start=spans[0][0]),
            ))

        for (_, earlier_end), (later_start, _) in zip(spans, spans[1:]):
            drift = later_start - earlier_end
            if drift > _EDGE_TOLERANCE:
                findings.append(self._report(
                    "error",
                    "timeline.gap",
                    _says("timeline_gap", earlier_end=earlier_end, later_start=later_start),
                ))
            elif drift < -_EDGE_TOLERANCE:
                findings.append(self._report(
                    "error",
                    "timeline.overlap",
                    _says("timeline_overlap", later_start=later_start),
                ))

        timeline_end = max(high for _, high in spans)
        if (
            declared_duration is not None
            and abs(timeline_end - declared_duration) > _DURATION_TOLERANCE
        ):
            findings.append(self._report(
                "error",
                "timeline.duration",
                _says("timeline_duration", timeline_end=timeline_end, declared_duration=declared_duration),
            ))
        return timeline_end

    def _check_asset_scope(self, text: str, findings: list[Sd25PromptAuditFinding]) -> None:
        if self._mentions_any(text, _ASSET_MARKERS) and not self._mentions_any(
            text, _RESPONSIBILITY_MARKERS
        ):
            findings.append(self._report(
                "warning",
                "reference.scope",
                _says("reference_scope"),
            ))

    def _check_action_chain(self, text: str, findings: list[Sd25PromptAuditFinding]) -> None:
        if self._mentions_any(text, _ACTION_MARKERS) and not self._mentions_any(
            text, _CAUSAL_MARKERS
        ):
            findings.append(self._report(
                "warning",
                "action.causality",
                _says("action_causality"),
            ))

    def _check_brand_boundary(self, text: str, findings: list[Sd25PromptAuditFinding]) -> None:
        lowered = text.lower()
        hits = sorted(brand for brand in _SCREENED_BRANDS if brand.lower() in lowered)
        if hits:
            findings.append(self._report(
                "error",
                "brand.detected",
                _says("brand_detected", brands=prompt_data.text(_WORDING, "brand_separator").join(hits)),
            ))
        if not self._mentions_any(text, _BRAND_BOUNDARY_MARKERS):
            findings.append(self._report(
                "warning",
                "brand.lock",
                _says("brand_lock"),
            ))

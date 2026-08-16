"""Fail-closed production readiness and deterministic outcome analytics."""

from __future__ import annotations

import hashlib
import json
import re

from app.core.providers.capabilities import ProviderCapabilityRegistry
from app.schema.evidence import (
    FailureEvidence,
    GenerationOutcome,
    ProductionAnalyticsSummary,
    ProductionReadinessReport,
    ProductionReadinessRequest,
    ReadinessCheck,
)


_SECRET = re.compile(
    r"(?i)\b(xi-api-key|authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+"
)
_BARE_SECRET = re.compile(r"(?i)\b(?:sk|ark)_[A-Za-z0-9_-]{20,}\b")


class ProductionEvidenceService:
    def __init__(self) -> None:
        self.providers = ProviderCapabilityRegistry()

    @staticmethod
    def _fingerprint(request: ProductionReadinessRequest) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def evaluate_readiness(self, request: ProductionReadinessRequest) -> ProductionReadinessReport:
        checks: list[ReadinessCheck] = []

        asset_report = request.assets.readiness()
        checks.append(ReadinessCheck(
            code="assets.complete" if asset_report.ready else "assets.incomplete",
            passed=asset_report.ready,
            detail=(
                "all role, scene, prop and effect assets are approved"
                if asset_report.ready
                else f"missing={asset_report.missing_categories}; unapproved={asset_report.unapproved_ids}"
            ),
        ))
        checks.append(ReadinessCheck(
            code="storyboard.exact_nine_grid" if request.storyboard is not None else "storyboard.missing",
            passed=request.storyboard is not None,
            detail="exact 3x3 board is present" if request.storyboard else "an exact 3x3 board is required",
        ))
        checks.append(ReadinessCheck(
            code="storyboard.approved" if request.storyboard_approved else "storyboard.not_approved",
            passed=request.storyboard_approved,
            detail="storyboard approval is current" if request.storyboard_approved else "storyboard requires current approval",
        ))

        provider = self.providers.list().get(request.provider)
        checks.append(ReadinessCheck(
            code="provider.known" if provider else "provider.unsupported",
            passed=provider is not None,
            detail=f"provider={request.provider}",
        ))
        if provider:
            operation_ok = request.operation in provider.operations
            mode_ok = request.generation_mode in provider.modes
            checks.extend([
                ReadinessCheck(
                    code="provider.operation_supported" if operation_ok else "provider.operation_unsupported",
                    passed=operation_ok,
                    detail=f"operation={request.operation}",
                ),
                ReadinessCheck(
                    code="provider.mode_supported" if mode_ok else "provider.mode_unsupported",
                    passed=mode_ok,
                    detail=f"mode={request.generation_mode}",
                ),
            ])
            limits = provider.limits
            references = {
                "images": request.reference_images,
                "videos": request.reference_videos,
                "audios": request.reference_audios,
            }
            for key, count in references.items():
                maximum = int(limits.get(key, 0))
                passed = count <= maximum
                checks.append(ReadinessCheck(
                    code=f"references.{key}_within_limit" if passed else f"references.{key}_exceeds_limit",
                    passed=passed,
                    detail=f"{count}/{maximum}",
                ))
            mixed = sum(references.values())
            mixed_maximum = int(limits.get("mixed_files", 0))
            mixed_ok = mixed <= mixed_maximum
            checks.append(ReadinessCheck(
                code="references.mixed_within_limit" if mixed_ok else "references.mixed_exceeds_limit",
                passed=mixed_ok,
                detail=f"{mixed}/{mixed_maximum}",
            ))
            duration_ok = (
                float(limits.get("min_duration_seconds", 0))
                <= request.duration_seconds
                <= float(limits.get("max_duration_seconds", request.duration_seconds))
            )
            checks.append(ReadinessCheck(
                code="duration.supported" if duration_ok else "duration.unsupported",
                passed=duration_ok,
                detail=f"duration={request.duration_seconds}",
            ))
            audio_reference_ok = not request.reference_audios or bool(
                request.reference_images or request.reference_videos
            )
            checks.append(ReadinessCheck(
                code="references.audio_context_present" if audio_reference_ok else "references.audio_only_unsupported",
                passed=audio_reference_ok,
                detail="reference audio is paired with visual context" if audio_reference_ok else "reference audio requires image or video context",
            ))

        blocking = [check.code for check in checks if check.severity == "blocking" and not check.passed]
        return ProductionReadinessReport(
            ready=not blocking,
            checks=checks,
            blocking_codes=blocking,
            fingerprint=self._fingerprint(request),
        )

    @staticmethod
    def normalize_failure(evidence: FailureEvidence) -> FailureEvidence:
        message = _SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", evidence.provider_message)
        message = _BARE_SECRET.sub("[REDACTED]", message)
        retry_scope = list(dict.fromkeys(evidence.failed_dimensions)) if evidence.retryable else []
        return evidence.model_copy(update={
            "provider_message": message[:2000],
            "retry_scope": retry_scope,
        })

    @staticmethod
    def summarize(outcomes: list[GenerationOutcome]) -> ProductionAnalyticsSummary:
        if not outcomes:
            return ProductionAnalyticsSummary(
                total=0, accepted=0, rejected=0, acceptance_rate=0, retry_rate=0,
                average_attempts=0, average_latency_ms=0, cost_by_currency={}, failures_by_category={},
            )
        accepted = sum(1 for item in outcomes if item.accepted)
        retried = sum(1 for item in outcomes if item.attempts > 1)
        costs: dict[str, float] = {}
        failures: dict[str, int] = {}
        for item in outcomes:
            costs[item.currency] = round(costs.get(item.currency, 0) + item.cost_amount, 6)
            if item.failure_category:
                failures[item.failure_category] = failures.get(item.failure_category, 0) + 1
        total = len(outcomes)
        return ProductionAnalyticsSummary(
            total=total,
            accepted=accepted,
            rejected=total - accepted,
            acceptance_rate=round(accepted / total, 6),
            retry_rate=round(retried / total, 6),
            average_attempts=round(sum(item.attempts for item in outcomes) / total, 4),
            average_latency_ms=round(sum(item.latency_ms for item in outcomes) / total),
            cost_by_currency=costs,
            failures_by_category=failures,
        )

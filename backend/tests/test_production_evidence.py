import unittest

from app.core.production_evidence import ProductionEvidenceService
from app.schema.evidence import (
    FailureEvidence,
    GenerationOutcome,
    ProductionReadinessRequest,
)
from app.schema.studio import AssetReadinessRequest


class ProductionEvidenceTests(unittest.TestCase):
    def test_readiness_fails_closed_before_paid_submission(self):
        report = ProductionEvidenceService().evaluate_readiness(ProductionReadinessRequest(
            assets=AssetReadinessRequest(),
            storyboard_approved=False,
            provider="minimax_h3",
            operation="video_generation",
            generation_mode="reference",
            reference_images=2,
            reference_videos=1,
            reference_audios=1,
            duration_seconds=8,
        ))

        self.assertFalse(report.ready)
        self.assertIn("assets.incomplete", report.blocking_codes)
        self.assertIn("storyboard.not_approved", report.blocking_codes)
        self.assertEqual(len(report.fingerprint), 64)

    def test_failure_evidence_redacts_provider_message_and_groups_dimensions(self):
        evidence = FailureEvidence(
            stage="video_generation",
            entity_id="shot-1",
            attempt=2,
            category="semantic_quality",
            failed_dimensions=["identity_consistency", "temporal_continuity"],
            request_fingerprint="f" * 64,
            provider_code="content_quality",
            provider_message=(
                "request failed with xi-api-key=secret-value and "
                "sk_abcdefghijklmnopqrstuvwxyz"
            ),
            retryable=True,
            evidence_urls=["https://cdn.example/review.json"],
        )
        normalized = ProductionEvidenceService().normalize_failure(evidence)

        self.assertNotIn("secret-value", normalized.provider_message)
        self.assertNotIn("sk_", normalized.provider_message)
        self.assertIn("[REDACTED]", normalized.provider_message)
        self.assertEqual(normalized.retry_scope, ["identity_consistency", "temporal_continuity"])

    def test_analytics_reports_acceptance_retry_cost_and_latency(self):
        outcomes = [
            GenerationOutcome(
                provider="minimax_h3", operation="video_generation", mode="reference",
                accepted=True, attempts=1, latency_ms=1200, cost_amount=0.20, currency="USD",
            ),
            GenerationOutcome(
                provider="minimax_h3", operation="video_generation", mode="reference",
                accepted=False, attempts=3, latency_ms=2400, cost_amount=0.50, currency="USD",
                failure_category="semantic_quality",
            ),
        ]
        summary = ProductionEvidenceService().summarize(outcomes)

        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.accepted, 1)
        self.assertEqual(summary.acceptance_rate, 0.5)
        self.assertEqual(summary.retry_rate, 0.5)
        self.assertEqual(summary.cost_by_currency["USD"], 0.7)
        self.assertEqual(summary.average_latency_ms, 1800)


if __name__ == "__main__":
    unittest.main()

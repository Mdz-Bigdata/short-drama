import unittest

from app.core.video_quality import VideoQualityMeasurements, evaluate_video_quality
from app.service.drama_service import DramaService


class _TaskRepo:
    def __init__(self):
        self.task = {"assets": {"7": {"final_video_url": "https://cdn.example/final.mp4"}}, "status": "awaiting_quality_review"}

    def get_task(self, task_id):
        return self.task if task_id == "task-1" else None

    def save_task(self, task_id, task):
        self.task = task


class VideoQualityGateTests(unittest.TestCase):
    def test_high_quality_measurements_pass(self):
        report = evaluate_video_quality(VideoQualityMeasurements(
            identity_consistency=0.96,
            anatomy_integrity=0.94,
            expression_fidelity=0.91,
            photorealism=0.93,
            temporal_continuity=0.92,
            dialogue_emotion_timing=0.90,
            lip_sync=0.91,
        ))
        self.assertTrue(report.passed)
        self.assertEqual(report.retry_actions, [])

    def test_expression_and_dialogue_failures_produce_targeted_retry(self):
        report = evaluate_video_quality(VideoQualityMeasurements(
            identity_consistency=0.95,
            anatomy_integrity=0.92,
            expression_fidelity=0.61,
            photorealism=0.90,
            temporal_continuity=0.93,
            dialogue_emotion_timing=0.55,
            lip_sync=0.58,
        ))
        self.assertFalse(report.passed)
        self.assertIn("expression_fidelity", report.failed_dimensions)
        self.assertIn("dialogue_emotion_timing", report.failed_dimensions)
        self.assertTrue(any("微表情" in action for action in report.retry_actions))
        self.assertTrue(any("对白" in action for action in report.retry_actions))

    def test_hard_visual_defect_always_rejects(self):
        report = evaluate_video_quality(VideoQualityMeasurements(
            identity_consistency=0.99,
            anatomy_integrity=0.99,
            expression_fidelity=0.99,
            photorealism=0.99,
            temporal_continuity=0.99,
            dialogue_emotion_timing=0.99,
            lip_sync=0.99,
            hard_defects=["extra_fingers"],
        ))
        self.assertFalse(report.passed)
        self.assertIn("hard_defects", report.failed_dimensions)

    def test_task_cannot_complete_until_evidence_backed_gate_passes(self):
        service = DramaService.__new__(DramaService)
        service.repo = _TaskRepo()
        failed = service.submit_video_quality("task-1", VideoQualityMeasurements(
            identity_consistency=0.50, anatomy_integrity=0.95, expression_fidelity=0.95,
            photorealism=0.95, temporal_continuity=0.95,
            dialogue_emotion_timing=0.95, lip_sync=0.95, assessor="human-director",
        ))
        self.assertEqual(failed["status"], "quality_failed")
        passed = service.submit_video_quality("task-1", VideoQualityMeasurements(
            identity_consistency=0.95, anatomy_integrity=0.95, expression_fidelity=0.95,
            photorealism=0.95, temporal_continuity=0.95,
            dialogue_emotion_timing=0.95, lip_sync=0.95, assessor="human-director",
        ))
        self.assertEqual(passed["status"], "completed")


if __name__ == "__main__":
    unittest.main()

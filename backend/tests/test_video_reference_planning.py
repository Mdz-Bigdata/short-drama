import unittest

from app.core.video_references import VideoGenerationIntent, plan_video_references


class VideoReferencePlanningTests(unittest.TestCase):
    def test_first_last_frame_mode_keeps_exact_anchors_separate_from_refs(self):
        plan = plan_video_references(
            "first_last_frame",
            first_frame="first.png",
            last_frame="last.png",
            reference_images=["character.png"],
            reference_videos=["motion.mp4"],
        )
        self.assertEqual(plan.first_frame, "first.png")
        self.assertEqual(plan.last_frame, "last.png")
        self.assertEqual(plan.reference_images, [])
        self.assertEqual(plan.reference_videos, [])

    def test_multimodal_mode_uses_images_video_audio_without_frame_claim(self):
        plan = plan_video_references(
            "multimodal",
            first_frame="panel.png",
            reference_images=["character.png", "panel.png"],
            reference_videos=["previous.mp4"],
            reference_audios=["voice.wav"],
        )
        self.assertIsNone(plan.first_frame)
        self.assertEqual(plan.reference_images, ["panel.png", "character.png"])
        self.assertEqual(plan.reference_videos, ["previous.mp4"])
        self.assertEqual(plan.reference_audios, ["voice.wav"])

    def test_auto_prioritizes_exact_end_frame_over_identity_images(self):
        plan = plan_video_references(
            "auto",
            first_frame="panel.png",
            last_frame="next.png",
            reference_images=["character.png"],
            intent=VideoGenerationIntent(exact_end_frame_required=True),
        )
        self.assertEqual(plan.mode, "first_last_frame")
        self.assertEqual(plan.first_frame, "panel.png")
        self.assertEqual(plan.last_frame, "next.png")
        self.assertIn("reference_images:1", plan.unused_assets)

    def test_auto_selects_multi_reference_for_storyboard_and_identity_images(self):
        plan = plan_video_references(
            "auto",
            first_frame="panel.png",
            reference_images=["character.png"],
            model="Seedance 2.0",
        )
        self.assertEqual(plan.mode, "multi_reference")
        self.assertEqual(plan.reference_images, ["panel.png", "character.png"])

    def test_gork_alias_falls_back_to_visual_refs_and_reports_unused_video(self):
        plan = plan_video_references(
            "auto",
            model="Gork Imagine Video",
            first_frame="panel.png",
            reference_images=["character.png"],
            reference_videos=["camera.mp4"],
        )
        self.assertEqual(plan.provider_family, "grok")
        self.assertEqual(plan.provider_status, "adapter_required")
        self.assertEqual(plan.mode, "multi_reference")
        self.assertIn("reference_videos:1", plan.unused_assets)
        self.assertTrue(plan.fallbacks)

    def test_required_motion_reference_fails_closed_for_grok(self):
        with self.assertRaises(ValueError):
            plan_video_references(
                "auto",
                model="Grok Imagine Video",
                first_frame="panel.png",
                reference_images=["character.png"],
                reference_videos=["camera.mp4"],
                intent=VideoGenerationIntent(motion_reference_required=True),
            )


if __name__ == "__main__":
    unittest.main()

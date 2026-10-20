import unittest

from pydantic import ValidationError

from app.core.preproduction import PreproductionPlanner
from app.schema.intelligence import (
    EpisodeBoundary,
    EpisodeIntakeRequest,
    NovelAnalyzeRequest,
    VoiceDirectionRequest,
    VoiceReferenceBinding,
)


class NovelAnalysisTests(unittest.TestCase):
    def test_index_is_hash_bound_and_sampling_is_reproducible(self):
        text = "第1章 雨夜\n门响了。\n第2章 来信\n她拆开信封。\n第3章 决定\n她转身离开。\n"
        planner = PreproductionPlanner()
        first = planner.analyze_novel(NovelAnalyzeRequest(source_id="novel-1", text=text, sample_count=2))
        second = planner.analyze_novel(NovelAnalyzeRequest(source_id="novel-1", text=text, sample_count=2))

        self.assertEqual(len(first.chapters), 3)
        self.assertEqual(first.content_sha256, second.content_sha256)
        self.assertEqual(first.sampled_chapter_indices, [1, 3])
        self.assertGreater(first.coverage_ratio, 0)
        self.assertEqual(first.chapters[0].start_byte, 0)
        self.assertTrue(all(len(chapter.sha256) == 64 for chapter in first.chapters))

    def test_episode_intake_supports_explicit_boundaries_and_resume(self):
        text = "序言\n第一场\n冲突\n第二场\n反转\n尾声\n"
        report = PreproductionPlanner().index_episodes(EpisodeIntakeRequest(
            source_id="script-1",
            text=text,
            boundaries=[
                EpisodeBoundary(episode_index=1, title="第一集", start_line=1, end_line=3),
                EpisodeBoundary(episode_index=2, title="第二集", start_line=4, end_line=6),
            ],
            resume_after_episode=1,
            output_language="zh-CN",
            prompt_language="en",
        ))

        self.assertEqual(len(report.episodes), 2)
        self.assertEqual(report.pending_episode_indices, [2])
        self.assertEqual(report.output_language, "zh-CN")
        self.assertEqual(report.prompt_language, "en")
        self.assertEqual(report.episodes[0].text, "序言\n第一场\n冲突\n")


class VoiceDirectionTests(unittest.TestCase):
    def test_approved_voice_reference_requires_consent_and_keeps_noise_out_of_identity(self):
        binding = VoiceReferenceBinding(
            uri="https://cdn.example/authorized-voice.wav",
            content_sha256="a" * 64,
            authorization="consented_clone",
            consent_record="consent-2026-08-15",
            admission_status="approved",
            may_control=["timbre", "pronunciation"],
            must_not_control=["emotion", "recording_room", "background_content"],
        )
        plan = PreproductionPlanner().plan_voice(VoiceDirectionRequest(
            character_id="char-1",
            character_name="林夏",
            language="zh-CN",
            reference=binding,
            selection_criteria=["低动态时仍保持清晰齿音"],
            rejection_criteria=["哭腔成为固定身份特征"],
            pronunciations={"林夏": "lin2 xia4"},
        ))

        self.assertEqual(plan.status, "ready")
        self.assertIn("emotion", plan.reference.must_not_control)

        with self.assertRaises(ValidationError):
            VoiceReferenceBinding(
                uri="https://cdn.example/unproven.wav",
                content_sha256="b" * 64,
                authorization="consented_clone",
                admission_status="approved",
                may_control=["timbre"],
                must_not_control=["emotion"],
            )


if __name__ == "__main__":
    unittest.main()

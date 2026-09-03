# -*- coding: utf-8 -*-
"""No shot may be longer than the selected video model can render in one call.

The dashboard used to carry a single 110s "shot" per episode. That is both a
storyboard with no camera language and a clip no provider can generate: MiniMax
H3 and Seedance 2.0 top out at 15s, Seedance 2.5 at 30s.
"""
import unittest
from typing import Any, Dict, List

from app.core.video_references import (
    DEFAULT_MAX_SHOT_SECONDS,
    max_shot_seconds,
    normalize_video_provider,
    split_shot_seconds,
)
from app.service.drama_service import DramaService


class MaxShotSecondsTests(unittest.TestCase):
    def test_seedance_versions_resolve_separately_despite_sharing_a_family(self):
        # The routing profile cannot tell them apart...
        self.assertEqual(normalize_video_provider("seedance2.0").family, "seedance")
        self.assertEqual(normalize_video_provider("seedance2.5").family, "seedance")
        # ...but the clip budget must.
        self.assertEqual(max_shot_seconds("seedance2.0"), 15)
        self.assertEqual(max_shot_seconds("seedance2.5"), 30)

    def test_separator_and_case_variants_resolve_the_same(self):
        for value in ("seedance2.5", "seedance-2.5", "Seedance 2.5", "SEEDANCE_2.5", "ark/seedance2.5"):
            self.assertEqual(max_shot_seconds(value), 30, value)
        for value in ("MiniMax-H3", "minimax_h3", "minimax h3", "MiniMax-Hailuo-2.3"):
            self.assertEqual(max_shot_seconds(value), 15, value)

    def test_an_unknown_or_missing_model_falls_back_conservatively(self):
        for value in ("", "   ", "some-new-model", "kling-o1"):
            self.assertEqual(max_shot_seconds(value), DEFAULT_MAX_SHOT_SECONDS, value)
        # Conservative means short enough for anything, never longer than the shortest known cap.
        self.assertLess(DEFAULT_MAX_SHOT_SECONDS, 15)

    def test_the_minimax_cap_matches_the_provider_capability_registry(self):
        from app.core.providers.capabilities import ProviderCapabilityRegistry

        limits = ProviderCapabilityRegistry()._providers["minimax_h3"].limits
        self.assertEqual(max_shot_seconds("minimax-h3"), limits["max_duration_seconds"])

    def test_the_shot_floor_matches_what_a_video_request_will_accept(self):
        from app.core.providers.capabilities import ProviderCapabilityRegistry
        from app.core.video_references import MIN_SHOT_SECONDS
        from app.schema.production import H3VideoRequest

        limits = ProviderCapabilityRegistry()._providers["minimax_h3"].limits
        bounds = {type(item).__name__: item for item in H3VideoRequest.model_fields["duration_seconds"].metadata}
        # A shot shorter than the floor would be rejected at submission time.
        self.assertEqual(MIN_SHOT_SECONDS, limits["min_duration_seconds"])
        self.assertEqual(MIN_SHOT_SECONDS, bounds["Ge"].ge)
        self.assertEqual(max_shot_seconds("minimax-h3"), bounds["Le"].le)


class SplitShotSecondsTests(unittest.TestCase):
    def test_an_over_long_shot_is_divided_without_losing_runtime(self):
        for model in ("seedance2.0", "seedance2.5", "unknown-model"):
            parts = split_shot_seconds(110, model)
            self.assertEqual(sum(parts), 110, model)
            self.assertTrue(all(part <= max_shot_seconds(model) for part in parts), model)

    def test_a_shot_within_budget_is_left_alone(self):
        self.assertEqual(split_shot_seconds(12, "seedance2.0"), [12])
        self.assertEqual(split_shot_seconds(30, "seedance2.5"), [30])

    def test_the_split_uses_the_fewest_clips_that_fit(self):
        self.assertEqual(len(split_shot_seconds(30, "seedance2.0")), 2)
        self.assertEqual(len(split_shot_seconds(31, "seedance2.0")), 3)
        self.assertEqual(len(split_shot_seconds(110, "seedance2.5")), 4)

    def test_a_zero_duration_shot_produces_no_clips(self):
        self.assertEqual(split_shot_seconds(0, "seedance2.0"), [])


class EnforceShotDurationsTests(unittest.TestCase):
    @staticmethod
    def _scenes() -> List[Dict[str, Any]]:
        return [
            {"scene_id": "E1S01", "duration": "110s", "content": "整集一镜到底", "characters": ["陈九"]},
            {"scene_id": "E2S01", "duration": "12s", "content": "短镜头", "characters": ["小六"]},
        ]

    def test_a_whole_episode_shot_becomes_several_renderable_shots(self):
        result = DramaService._enforce_shot_durations(self._scenes(), "seedance2.0")

        episode_one = [scene for scene in result if scene["scene_id"].startswith("E1S")]
        self.assertEqual(len(episode_one), 8)
        self.assertEqual(sum(int(scene["duration"].rstrip("s")) for scene in episode_one), 110)
        self.assertTrue(all(int(scene["duration"].rstrip("s")) <= 15 for scene in episode_one))

    def test_shot_ids_stay_sequential_within_each_episode(self):
        result = DramaService._enforce_shot_durations(self._scenes(), "seedance2.0")

        self.assertEqual(
            [scene["scene_id"] for scene in result if scene["scene_id"].startswith("E1S")],
            [f"E1S{index:02d}" for index in range(1, 9)],
        )
        # An untouched episode keeps its single shot at index 01.
        self.assertEqual([scene["scene_id"] for scene in result if scene["scene_id"].startswith("E2S")], ["E2S01"])

    def test_a_split_shot_says_which_segment_it_is(self):
        result = DramaService._enforce_shot_durations(self._scenes(), "seedance2.0")

        self.assertIn("（分段 1/8）", result[0]["content"])
        self.assertIn("（分段 8/8）", result[7]["content"])
        self.assertNotIn("分段", result[-1]["content"])

    def test_a_longer_capable_model_needs_fewer_splits(self):
        result = DramaService._enforce_shot_durations(self._scenes(), "seedance2.5")

        self.assertEqual(len([scene for scene in result if scene["scene_id"].startswith("E1S")]), 4)

    def test_characters_and_other_fields_survive_the_split(self):
        result = DramaService._enforce_shot_durations(self._scenes(), "seedance2.0")

        self.assertTrue(all(scene["characters"] == ["陈九"] for scene in result if scene["scene_id"].startswith("E1S")))

    def test_an_episode_that_reappears_later_does_not_interleave_the_shot_list(self):
        # A re-analysed batch (or a relabelled answer) can put E1 shots after E2's.
        # Shots are renumbered per episode, so leaving that order would produce
        # E1S01, E2S01, E1S02 - a shot list that jumps backwards mid-episode.
        scenes = [
            {"scene_id": "E1S01", "duration": "40s", "content": "一"},
            {"scene_id": "E2S01", "duration": "12s", "content": "二"},
            {"scene_id": "E1S02", "duration": "12s", "content": "三"},
            {"scene_id": "E3S01", "duration": "12s", "content": "四"},
            {"scene_id": "E2S02", "duration": "12s", "content": "五"},
        ]

        result = DramaService._enforce_shot_durations(scenes, "seedance2.0")
        ids = [scene["scene_id"] for scene in result]

        self.assertEqual(ids, ["E1S01", "E1S02", "E1S03", "E1S04", "E2S01", "E2S02", "E3S01"])
        # Story order inside an episode is preserved by the stable sort.
        self.assertEqual(result[3]["content"], "三")
        self.assertEqual(result[5]["content"], "五")

    def test_malformed_entries_are_dropped_not_crashed_on(self):
        result = DramaService._enforce_shot_durations(["not a dict", None, {"scene_id": "E1S01"}], "seedance2.0")

        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()

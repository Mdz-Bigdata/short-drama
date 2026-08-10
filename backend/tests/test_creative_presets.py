import unittest

from app.core.creative_presets import CreativePresetRegistry
from app.core.capability_manifest import UPSTREAM_CAPABILITIES


class CreativePresetRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = CreativePresetRegistry()

    def test_all_audited_creative_modes_are_callable(self):
        expected = {
            "h3-prompt-writing",
            "3d-animation-short",
            "brand-promo",
            "co-op-game-intro",
            "handdrawn-live",
            "minimalist-product-ad",
            "music-video-subtitle",
            "paper-collage-explainer",
            "papercraft-stop-motion",
            "narrative-breakdown",
            "deep-emotion",
            "detailed-action",
            "episode-continuity",
            "single-video-polish",
            "high-impact-drama",
            "slow-cinematic",
            "sd25-pe-production",
        }
        self.assertTrue(expected.issubset({preset.id for preset in self.registry.list()}))

    def test_manifest_contains_all_thirteen_requested_sources(self):
        self.assertEqual(len(UPSTREAM_CAPABILITIES), 13)
        self.assertIn("short-drama-skills", {source["id"] for source in UPSTREAM_CAPABILITIES})

    def test_compiler_injects_non_optional_production_contracts(self):
        compiled = self.registry.compile(
            "deep-emotion",
            "林夏发现丈夫隐瞒了信件。",
            asset_context="角色林夏；场景客厅；道具信封；特效雨丝。",
        )
        self.assertIn("角色五视图", compiled.prompt)
        self.assertIn("3×3 九宫格", compiled.prompt)
        self.assertIn("角色、场景、道具、特效", compiled.prompt)
        self.assertIn("首帧", compiled.prompt)
        self.assertIn("尾帧", compiled.prompt)
        self.assertIn("微表情", compiled.prompt)
        self.assertEqual(compiled.source_id, "short-drama-skills")

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(KeyError):
            self.registry.compile("../../unknown", "内容")


if __name__ == "__main__":
    unittest.main()

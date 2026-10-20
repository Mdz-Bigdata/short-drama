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

    def test_manifest_contains_every_requested_source(self):
        self.assertEqual(len(UPSTREAM_CAPABILITIES), 20)
        ids = {source["id"] for source in UPSTREAM_CAPABILITIES}
        self.assertIn("short-drama-skills", ids)
        self.assertIn("fight-prompt-director", ids)

    def test_compiler_injects_non_optional_production_contracts(self):
        compiled = self.registry.compile(
            "deep-emotion",
            "林夏发现丈夫隐瞒了信件。",
            asset_context="角色林夏；场景客厅；道具信封；特效雨丝。",
        )
        self.assertIn("数字演员设定集", compiled.prompt)
        self.assertIn("3×3 九宫格", compiled.prompt)
        self.assertIn("角色、场景、道具、特效", compiled.prompt)
        self.assertIn("首帧", compiled.prompt)
        self.assertIn("尾帧", compiled.prompt)
        self.assertIn("微表情", compiled.prompt)
        self.assertEqual(compiled.source_id, "short-drama-skills")

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(KeyError):
            self.registry.compile("../../unknown", "内容")



class TensionLockPresetTests(unittest.TestCase):
    def test_tension_lock_preset_compiles_the_restraint_rules(self):
        from app.core.creative_presets import CreativePresetRegistry

        compiled = CreativePresetRegistry().compile("tension-lock", "深夜工业区，两人对峙。")
        self.assertEqual(compiled.source_id, "first-party")
        self.assertIn("镜头默认静止锁帧", compiled.prompt)
        self.assertIn("暗部占七成以上", compiled.prompt)
        self.assertIn("写指节发白", compiled.prompt)


if __name__ == "__main__":
    unittest.main()

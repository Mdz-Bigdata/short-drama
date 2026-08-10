import json
import tempfile
import unittest
from pathlib import Path

from app.core.shotcraft_catalog import (
    ShotcraftCatalogError,
    ShotcraftCatalogLoader,
    ShotcraftSelectionRequest,
)


class ShotcraftCatalogTests(unittest.TestCase):
    def test_locked_catalog_covers_every_reviewed_card_style_and_audio_stat(self):
        catalog = ShotcraftCatalogLoader.locked()
        self.assertEqual(len(catalog.cards), 152)
        self.assertEqual(sum(len(card.styles) for card in catalog.cards), 209)
        self.assertEqual(catalog.stats.sfx_count, 149)
        self.assertEqual(catalog.stats.sfx_category_count, 16)
        self.assertEqual(len(catalog.categories), 10)

    def test_selection_compiles_to_provider_neutral_shot_plan(self):
        loader = ShotcraftCatalogLoader()
        plan = loader.compile_selection(
            ShotcraftSelectionRequest(
                card="tension-camera-moves",
                style="slow-push-in",
                purpose="林夏意识到信件是伪造的",
                duration_seconds=4.5,
                asset_ids=["char-linxia", "prop-letter"],
            )
        )
        self.assertEqual(plan.category, "camera")
        self.assertEqual(plan.renderer_contract, "canonical-shot-plan-v1")
        self.assertIn("slow-push-in", plan.motion_tags)
        with self.assertRaises(ShotcraftCatalogError):
            loader.compile_selection(
                ShotcraftSelectionRequest(
                    card="tension-camera-moves",
                    style="nonexistent-style",
                    purpose="错误样式",
                    duration_seconds=4,
                )
            )

    def test_checkout_loader_requires_apache_license_and_validated_library(self):
        locked_path = Path(__file__).resolve().parents[1] / "app" / "data" / "video_shotcraft_catalog.json"
        locked = json.loads(locked_path.read_text(encoding="utf-8"))
        upstream_shape = {
            "revision": locked["library_revision"],
            "stats": {
                "cardCount": locked["stats"]["cardCount"],
                "styleCount": locked["stats"]["styleCount"],
                "previewCount": locked["stats"]["previewCount"],
                "mediaCount": locked["stats"]["mediaCount"],
                "newest": locked["stats"]["newest"],
            },
            "categories": locked["categories"],
            "cards": [
                {
                    "name": card["name"],
                    "category": card["category"],
                    "styles": [{"key": style} for style in card["styles"]],
                }
                for card in locked["cards"]
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "gallery" / "api"
            library.mkdir(parents=True)
            (library / "library.json").write_text(
                json.dumps(upstream_shape), encoding="utf-8"
            )
            with self.assertRaises(ShotcraftCatalogError):
                ShotcraftCatalogLoader.from_checkout(root)
            (root / "LICENSE").write_text(
                "Apache License\nVersion 2.0, January 2004", encoding="utf-8"
            )
            catalog = ShotcraftCatalogLoader.from_checkout(root)
            self.assertEqual(len(catalog.cards), 152)
            self.assertEqual(catalog.reviewed_commit, "external-checkout")


if __name__ == "__main__":
    unittest.main()

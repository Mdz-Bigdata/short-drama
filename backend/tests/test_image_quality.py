import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from app.core.image_quality import validate_five_view_images


class ImageQualityTests(unittest.TestCase):
    def test_five_view_quality_rejects_blank_duplicate_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = []
            for index in range(5):
                path = root / f"blank-{index}.png"
                Image.new("RGB", (200, 400), "white").save(path)
                paths.append(path)
            report = validate_five_view_images(paths)
            self.assertFalse(report.passed)
            self.assertIn("low_entropy", {issue.code for issue in report.issues})

    def test_five_view_quality_accepts_detailed_consistent_palette(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = []
            for index in range(5):
                image = Image.new("RGB", (200, 400), (225, 220, 210))
                draw = ImageDraw.Draw(image)
                draw.rectangle((55 + index * 2, 50, 145 + index * 2, 350), fill=(40, 65, 90))
                draw.ellipse((72 + index, 20, 128 + index, 90), fill=(190, 140, 105))
                for line in range(15):
                    draw.line((60, 100 + line * 12, 140, 105 + line * 12), fill=(50 + line * 3, 70, 95))
                path = root / f"view-{index}.png"
                image.save(path)
                paths.append(path)
            report = validate_five_view_images(paths)
            self.assertTrue(report.passed, report.model_dump())


if __name__ == "__main__":
    unittest.main()

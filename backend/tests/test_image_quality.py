import random
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from app.core.actor_sheet_layout import ACTOR_SHEET_CELL_ORDER
from app.core.image_quality import validate_actor_sheet_images, validate_five_view_images


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


def _textured_cell(root: Path, name: str, seed: int, *, size=(220, 220)) -> Path:
    """一张有明确局部结构、彼此可区分的合成格子。

    用固定种子的伪随机块填充：熵足够高（不会被空白检查误伤），
    每个 seed 的块分布不同（差分哈希互不相同）。
    """
    generator = random.Random(seed)
    image = Image.new("RGB", size, (225, 220, 210))
    draw = ImageDraw.Draw(image)
    step = 20
    for top in range(0, size[1], step):
        for left in range(0, size[0], step):
            draw.rectangle(
                (left, top, left + step - 1, top + step - 1),
                fill=(
                    generator.randrange(30, 230),
                    generator.randrange(30, 230),
                    generator.randrange(30, 230),
                ),
            )
    path = root / f"{name}.png"
    image.save(path)
    return path


def _actor_sheet_cells(root: Path) -> list[Path]:
    return [
        _textured_cell(root, f"{index:02d}_{cell}", index)
        for index, cell in enumerate(ACTOR_SHEET_CELL_ORDER, start=1)
    ]


class ActorSheetQualityTests(unittest.TestCase):
    def test_actor_sheet_quality_accepts_twenty_five_distinct_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_actor_sheet_images(_actor_sheet_cells(Path(tmp)))
            self.assertTrue(report.passed, report.model_dump())
            self.assertEqual(len(report.entropy), 25)
            self.assertEqual(report.unique_view_hashes, 5)

    def test_actor_sheet_quality_rejects_a_wrong_cell_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _actor_sheet_cells(Path(tmp))[:5]
            report = validate_actor_sheet_images(paths)
            self.assertFalse(report.passed)
            self.assertEqual({issue.code for issue in report.issues}, {"cell_count"})

    def test_a_blank_cell_fails_that_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _actor_sheet_cells(root)
            blank_index = ACTOR_SHEET_CELL_ORDER.index("detail_texture")
            Image.new("RGB", (220, 220), (248, 248, 248)).save(paths[blank_index])

            report = validate_actor_sheet_images(paths)

            self.assertFalse(report.passed)
            blank = [issue for issue in report.issues if issue.code == "blank_cell"]
            self.assertEqual([issue.view_index for issue in blank], [blank_index + 1])

    def test_repeated_full_body_views_and_a_portrait_clone_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _actor_sheet_cells(root)
            order = list(ACTOR_SHEET_CELL_ORDER)
            # 背面照抄正面：没转面。
            Image.open(paths[order.index("front")]).save(paths[order.index("back")])
            # 正脸特写照抄左区大正面：细节矩阵没画。
            Image.open(paths[order.index("portrait")]).save(paths[order.index("face_front")])

            report = validate_actor_sheet_images(paths)

            self.assertFalse(report.passed)
            codes = {issue.code for issue in report.issues}
            self.assertIn("duplicate_full_body", codes)
            self.assertIn("portrait_matches_face", codes)

    def test_identical_identity_anchors_report_duplicate_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _actor_sheet_cells(root)
            order = list(ACTOR_SHEET_CELL_ORDER)
            source = paths[order.index("front")]
            for anchor in ("profile", "back", "face_front", "face_three_quarter"):
                Image.open(source).save(paths[order.index(anchor)])

            report = validate_actor_sheet_images(paths)

            self.assertFalse(report.passed)
            self.assertIn("duplicate_views", {issue.code for issue in report.issues})
            self.assertEqual(report.unique_view_hashes, 1)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.core.actor_sheet_layout import ACTOR_SHEET_CELL_ORDER, actor_sheet_cell_boxes
from app.core.storyboard_assets import compose_nine_grid, split_actor_sheet, split_five_view_sheet


class StoryboardAssetTests(unittest.TestCase):
    def test_compose_nine_grid_is_exact_vertical_three_by_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for index in range(9):
                path = root / f"panel-{index}.png"
                Image.new("RGB", (180, 320), (index * 20, 50, 100)).save(path)
                sources.append(str(path))
            output = root / "board.png"
            compose_nine_grid(sources, output, cell_size=(180, 320), gutter=4)
            with Image.open(output) as board:
                self.assertEqual(board.size, (548, 968))

    def test_compose_nine_grid_leaves_unused_cells_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = []
            for index in range(3):
                path = root / f"panel-{index}.png"
                Image.new("RGB", (60, 100), (20, 40, 60)).save(path)
                sources.append(str(path))
            output = root / "partial-board.png"
            compose_nine_grid(sources, output, cell_size=(60, 100), gutter=2)
            with Image.open(output) as board:
                self.assertEqual(board.size, (184, 304))
                self.assertEqual(board.getpixel((30, 250)), (255, 255, 255))

    def test_split_actor_sheet_returns_twenty_five_ordered_crops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "actor-sheet.png"
            Image.new("RGB", (3360, 1440), (120, 120, 120)).save(sheet)

            paths = split_actor_sheet(sheet, root / "cells")

            self.assertEqual(len(paths), 25)
            self.assertEqual(
                [path.name for path in paths],
                [f"{index:02d}_{cell}.png" for index, cell in enumerate(ACTOR_SHEET_CELL_ORDER, start=1)],
            )
            expected = actor_sheet_cell_boxes(3360, 1440)
            for path, (_cell, (left, top, right, bottom)) in zip(paths, expected):
                with Image.open(path) as crop:
                    self.assertEqual(crop.size, (right - left, bottom - top))

    def test_split_actor_sheet_refuses_a_sixteen_by_nine_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "wrong-aspect.png"
            Image.new("RGB", (2560, 1440), (120, 120, 120)).save(sheet)

            with self.assertRaises(ValueError) as caught:
                split_actor_sheet(sheet, root / "cells")

            self.assertIn("21:9", str(caught.exception))
            self.assertIn("1.78", str(caught.exception))

    def test_split_five_view_sheet_returns_five_equal_crops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "sheet.png"
            Image.new("RGB", (1000, 400), (120, 120, 120)).save(sheet)
            paths = split_five_view_sheet(sheet, root / "views")
            self.assertEqual(len(paths), 5)
            for path in paths:
                with Image.open(path) as view:
                    self.assertEqual(view.size, (200, 400))


if __name__ == "__main__":
    unittest.main()

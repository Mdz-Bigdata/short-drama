import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.core.storyboard_assets import compose_nine_grid, split_five_view_sheet


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

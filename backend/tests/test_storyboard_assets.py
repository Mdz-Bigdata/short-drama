import random
import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from app.core.actor_sheet_cutter import detect_actor_sheet_cell_boxes
from app.core.actor_sheet_layout import (
    ACTOR_SHEET_CELL_ORDER,
    REQUIRED_CELLS,
    actor_sheet_cell_boxes,
    actor_sheet_cell_key,
)
from app.core.storyboard_assets import (
    complete_actor_sheet_cells,
    compose_nine_grid,
    split_actor_sheet,
    split_five_view_sheet,
)


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

    def test_split_actor_sheet_always_returns_the_required_cells(self):
        """一张没有任何面板结构的图：只产出七个身份必需格，元素和细节不凭空切出来。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "actor-sheet.png"
            Image.new("RGB", (3360, 1440), (120, 120, 120)).save(sheet)

            paths = split_actor_sheet(sheet, root / "cells")

            self.assertEqual({actor_sheet_cell_key(path) for path in paths}, set(REQUIRED_CELLS))
            expected = [
                (f"{index:02d}", cell)
                for index, cell in enumerate(ACTOR_SHEET_CELL_ORDER, start=1)
                if cell in REQUIRED_CELLS
            ]
            self.assertEqual([_name_parts(path) for path in paths], expected)

    def test_missing_cells_are_cropped_from_the_identity_panels(self):
        """模型只画出七个必需格：其余 18 格从全身立绘、主肖像、背面按部位补裁，凑满 25 张。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "actor-sheet.png"
            Image.new("RGB", (3360, 1440), (120, 120, 120)).save(sheet)
            found = split_actor_sheet(sheet, root / "cells")
            self.assertEqual(len(found), len(REQUIRED_CELLS))

            paths, derived = complete_actor_sheet_cells(found)

            self.assertEqual([actor_sheet_cell_key(path) for path in paths], list(ACTOR_SHEET_CELL_ORDER))
            self.assertEqual(set(derived), set(ACTOR_SHEET_CELL_ORDER) - set(REQUIRED_CELLS))
            self.assertEqual(derived["detail_eye"], "portrait")
            self.assertEqual(derived["element_shoe"], "full_body")
            self.assertEqual(derived["face_back_hair"], "back")
            # 右侧 45° 侧脸没画时由左侧 45° 水平翻转补上
            self.assertEqual(derived["face_three_quarter_right"], "face_three_quarter")
            by_cell = {actor_sheet_cell_key(path): path for path in paths}
            with Image.open(by_cell["face_three_quarter"]) as left, Image.open(by_cell["face_three_quarter_right"]) as right:
                self.assertEqual(ImageOps.mirror(left.convert("RGB")).tobytes(), right.convert("RGB").tobytes())
            for path in paths:
                self.assertTrue(path.is_file(), path)
                with Image.open(path) as image:
                    self.assertGreaterEqual(min(image.size), 64, path.name)

    def test_drawn_cells_are_never_replaced_by_a_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet, _panels = _drawn_actor_sheet()
            sheet.save(root / "sheet.png")
            found = split_actor_sheet(root / "sheet.png", root / "cells")
            paths, derived = complete_actor_sheet_cells(found)
            self.assertEqual(derived, {})
            self.assertEqual(paths, found)

    def test_a_resplit_with_new_content_gets_a_new_file_name(self):
        """文件名带内容哈希：重新切出不同的图，URL 就变，浏览器不会拿缓存的旧图冒充。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (3360, 1440), (120, 120, 120)).save(root / "a.png")
            Image.new("RGB", (3360, 1440), (90, 140, 120)).save(root / "b.png")
            first = {actor_sheet_cell_key(path): path.name for path in split_actor_sheet(root / "a.png", root / "cells")}
            second = {actor_sheet_cell_key(path): path.name for path in split_actor_sheet(root / "b.png", root / "cells")}
            self.assertNotEqual(first["front"], second["front"])
            self.assertTrue(re.fullmatch(r"03_front-[0-9a-f]{8}\.png", second["front"]))

    def test_split_actor_sheet_names_every_drawn_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet, _panels = _drawn_actor_sheet()
            sheet.save(root / "sheet.png")
            paths = split_actor_sheet(root / "sheet.png", root / "cells")
            self.assertEqual(
                [_name_parts(path) for path in paths],
                [(f"{index:02d}", cell) for index, cell in enumerate(ACTOR_SHEET_CELL_ORDER, start=1)],
            )

    def test_split_actor_sheet_follows_the_drawn_panels_not_the_ratios(self):
        """模型画偏了的设定集：每格都要切到真实面板上，标题带和栏间细线都不能混进来。"""
        sheet, panels = _drawn_actor_sheet()
        detected = dict(detect_actor_sheet_cell_boxes(sheet))
        self.assertEqual(list(detected), list(ACTOR_SHEET_CELL_ORDER))
        for cell, (left, top, right, bottom) in panels.items():
            got = detected[cell]
            for actual, wanted in zip(got, (left, top, right, bottom)):
                self.assertLessEqual(abs(actual - wanted), 16, (cell, got, (left, top, right, bottom)))
            # 每一格都在标题带以下：标题字不会出现在任何格子里。
            self.assertGreater(got[1], 120, cell)

        # 版面比例给出的预期框和真实面板差得很远——证明结果来自画面而不是比例。
        ratio = dict(actor_sheet_cell_boxes(3360, 1440))
        self.assertGreater(abs(ratio["full_body"][2] - panels["full_body"][2]), 40)
        self.assertGreater(abs(ratio["portrait"][2] - panels["portrait"][2]), 40)
        self.assertGreater(abs(ratio["face_front"][0] - panels["face_front"][0]), 40)

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




def _grid_panels(box, rows, columns, gap, keys):
    left, top, right, bottom = box
    cell_w = (right - left - gap * (columns - 1)) / columns
    cell_h = (bottom - top - gap * (rows - 1)) / rows
    panels = {}
    for index, key in enumerate(keys):
        row, column = divmod(index, columns)
        x0 = round(left + column * (cell_w + gap))
        y0 = round(top + row * (cell_h + gap))
        panels[key] = (x0, y0, round(x0 + cell_w), round(y0 + cell_h))
    return panels


def _draw_face(draw, box):
    """一块"像脸"的面板：上部深色头发，下部肤色，都带细密的随机纹理(和真照片一样处处有跳变)。"""
    generator = random.Random(box[0] * 7 + box[1])
    left, top, right, bottom = box
    hair = top + round((bottom - top) * 0.45)
    for y in range(top, bottom + 1, 4):
        for x in range(left, right + 1, 4):
            jitter = generator.randint(-30, 30)
            if y < hair:
                fill = (max(0, 24 + jitter // 3), max(0, 20 + jitter // 3), max(0, 22 + jitter // 3))
            else:
                fill = (226 + jitter // 3, 176 + jitter // 2, 150 + jitter // 2)
            draw.rectangle((x, y, min(x + 3, right), min(y + 3, bottom)), fill=fill)


def _name_parts(path):
    """``NN_<key>-<哈希>.png`` → (NN, key)。"""
    match = re.fullmatch(r"(\d{2})_([a-z_]+)-[0-9a-f]{8}\.png", path.name)
    assert match, path.name
    return match.group(1), match.group(2)


def _drawn_actor_sheet():
    """画一张"像真出图"的设定集：栏宽不是版面比例、标题带有字块和贯穿全宽的细线、栏间有灰色细线、
    面板之间只有 6px 白缝，面板内部是细密的棋盘格内容。返回 (图, 每格真实面板框)。"""
    image = Image.new("RGB", (3360, 1440), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    # 标题带：各栏居中的深灰字块 + 一条贯穿全宽的细线
    for x0 in (250, 1150, 2500):
        draw.rectangle((x0, 40, x0 + 360, 100), fill=(70, 70, 80))
    draw.rectangle((0, 128, 3360, 130), fill=(200, 200, 200))
    # 栏间灰色细竖线(栏宽故意不等于 20% / 40% / 40%)
    for x in (788, 2238):
        draw.rectangle((x, 0, x + 2, 1440), fill=(160, 160, 160))
    gap = 6
    panels = {"portrait": (30, 150, 760, 1410)}
    panels["full_body"] = (820, 150, 1300, 1410)
    right_part = (1306, 150, 2210, 1410)
    split = 950
    panels.update(_grid_panels((right_part[0], 150, right_part[2], split), 1, 3, gap,
                               ("front", "profile", "back")))
    panels.update(_grid_panels((right_part[0], split + gap, right_part[2], 1410), 2, 4, gap,
                               ("element_shoe", "element_waist", "element_wrist", "element_collar",
                                "element_fabric", "element_hair", "element_hand", "element_hem")))
    panels.update(_grid_panels((2270, 150, 3330, 1410), 4, 3, gap,
                               ("face_front", "face_three_quarter", "face_three_quarter_right",
                                "face_back_hair", "detail_collar", "detail_chest",
                                "detail_waist_knot", "detail_cuff", "detail_texture",
                                "detail_shoe", "detail_eye", "detail_accessory")))
    # 面板内容是细密的棋盘格：和真实画面一样，任何穿过面板的线都会碰上一串边缘。
    for index, (key, box) in enumerate(panels.items()):
        shade = 60 + (index * 37) % 120
        left, top, right, bottom = box
        if key.startswith("face_") and key != "face_back_hair":
            _draw_face(draw, box)
            continue
        draw.rectangle(box, fill=(shade, shade, shade))
        for y in range(top, bottom + 1, 8):
            for x in range(left + ((y - top) // 8 % 2) * 8, right + 1, 16):
                draw.rectangle((x, y, min(x + 7, right), min(y + 7, bottom)), fill=(20, 20, 30))
    # 面板框是包含端点的；换成切图用的右开区间。
    return image, {key: (l, t, r + 1, b + 1) for key, (l, t, r, b) in panels.items()}


if __name__ == "__main__":
    unittest.main()

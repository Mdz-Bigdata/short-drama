import io
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.core import media_compositor
from app.core.actor_detail_fill import (
    DETAIL_FILL_SUBJECTS,
    board_shape,
    board_size,
    boards,
    detail_fill_prompt,
    generate_detail_cells,
    is_blank,
    padded,
    split_board,
)
from app.core.storyboard_assets import _derived_crop, _save_cell
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.schema.production import IDENTITY_VIEW_ORDER
from app.service.drama_service import DramaService


def _texture(draw, box, seed):
    generator = random.Random(seed)
    left, top, right, bottom = box
    for y in range(top, bottom, 6):
        for x in range(left, right, 6):
            value = 40 + generator.randint(0, 150)
            draw.rectangle((x, y, x + 5, y + 5), fill=(value, value - 20, value - 30))


def _board(columns, rows, *, side=256, blank=()):
    """columns × rows 拼板：格间白缝，每格中间一块纹理；blank 里的序号只留底色。"""
    image = Image.new("RGB", (side * columns, side * rows), (244, 244, 244))
    draw = ImageDraw.Draw(image)
    for c in range(1, columns):
        draw.rectangle((c * side - 3, 0, c * side + 3, side * rows), fill=(255, 255, 255))
    for r in range(1, rows):
        draw.rectangle((0, r * side - 3, side * columns, r * side + 3), fill=(255, 255, 255))
    for index in range(columns * rows):
        if index in blank:
            continue
        r, c = divmod(index, columns)
        _texture(draw, (c * side + side // 6, r * side + side // 6, (c + 1) * side - side // 6, (r + 1) * side - side // 6), index)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class BoardLayoutTests(unittest.TestCase):
    def test_missing_cells_are_grouped_into_boards_of_at_most_eight(self):
        self.assertEqual(boards(["face_three_quarter_right", "element_fabric", "element_hand"]), [["element_fabric", "element_hand"]])
        many = boards(["element_shoe", "element_waist", "element_wrist", "element_collar", "element_fabric",
                       "element_hair", "element_hand", "element_hem", "detail_eye", "detail_shoe"])
        self.assertEqual([len(board) for board in many], [8, 2])

    def test_square_grids_always_keep_the_last_slot_spare(self):
        """方格网模型画得最稳；最后一格永远是空位，供应商盖在右下角的水印只会落在空位上。"""
        self.assertEqual(board_shape(2), (2, 2))
        self.assertEqual(board_shape(5), (3, 2))
        self.assertEqual(board_shape(8), (3, 3))
        self.assertEqual(board_size(3, 3), "3072x3072")
        self.assertEqual(board_size(2, 2), "3072x3072")
        for count in (1, 3, 5, 8):
            cells = list(DETAIL_FILL_SUBJECTS)[:count]
            layout = padded(cells)
            columns, rows = board_shape(count)
            self.assertEqual(len(layout), columns * rows)
            self.assertEqual(layout[:count], cells)
            self.assertNotIn(layout[-1], cells)
            self.assertEqual(len(set(layout)), len(layout))

    def test_prompt_names_every_panel_in_order_and_forbids_text(self):
        prompt = detail_fill_prompt(padded(["element_fabric", "element_hand"]), columns=2, rows=2, name="沈知微", desc="青色襦裙", style="写实")
        self.assertIn("第1格：主服装面料微距", prompt)
        self.assertIn("第2格：手部姿态特写", prompt)
        self.assertIn("2 行、每行 2 格", prompt)
        self.assertIn("第4格", prompt)
        self.assertIn("不多不少", prompt)
        self.assertIn("禁止出现文字", prompt)


class SplitBoardTests(unittest.TestCase):
    def test_a_board_is_cut_in_reading_order(self):
        crops = split_board(_board(3, 2), 3, 2)
        self.assertEqual(len(crops), 6)
        for crop in crops:
            self.assertFalse(is_blank(crop))
            self.assertLess(crop.width, 256)

    def test_blank_panels_are_detected(self):
        crops = split_board(_board(2, 1, blank={1}), 2, 1)
        self.assertEqual(len(crops), 2)
        self.assertFalse(is_blank(crops[0]))
        self.assertTrue(is_blank(crops[1]))


class GenerateDetailCellsTests(unittest.TestCase):
    def test_only_requested_non_blank_cells_come_back(self):
        calls = []

        def generate(prompt, references, size):
            calls.append((prompt, references, size))
            return "board://1"

        # 3 个缺格 → 2×2 (最后一格空位)；第 2 格画成空白，不能采用。
        filled = generate_detail_cells(
            generate=generate, load=lambda url: _board(2, 2, blank={1}),
            cells=["element_fabric", "element_hand", "detail_eye"],
            name="沈知微", desc="", style="写实", references=["ref"],
        )
        self.assertEqual(set(filled), {"element_fabric", "detail_eye"})
        self.assertEqual(calls[0][1], ["ref"])
        self.assertEqual(calls[0][2], "3072x3072")

    def test_a_failed_or_misshapen_board_fills_nothing(self):
        self.assertEqual(generate_detail_cells(
            generate=lambda *_: None, load=lambda url: b"", cells=["element_fabric"],
            name="x", desc="", style="", references=[],
        ), {})
        # 要 2×2 却只画出 1 格：整板不采用，免得张冠李戴。
        self.assertEqual(generate_detail_cells(
            generate=lambda *_: "u", load=lambda url: _board(1, 1, side=512), cells=["element_fabric", "element_hand"],
            name="x", desc="", style="", references=[],
        ), {})

    def test_a_board_with_an_extra_column_is_rejected_instead_of_mislabelled(self):
        """沈知微那次：要 3×3，模型画成 4×3 多塞了一列人物——按 3 列硬切会把格子错位，整板不采用。"""
        self.assertEqual(split_board(_board(4, 3), 3, 3), [])
        self.assertEqual(split_board(_board(3, 2), 3, 3), [])
        self.assertEqual(generate_detail_cells(
            generate=lambda *_: "u", load=lambda url: _board(4, 3), cells=list(DETAIL_FILL_SUBJECTS)[:8],
            name="x", desc="", style="", references=[],
        ), {})

    def test_the_spare_last_cell_is_dropped_even_when_it_is_drawn(self):
        filled = generate_detail_cells(
            generate=lambda *_: "u", load=lambda url: _board(3, 3), cells=list(DETAIL_FILL_SUBJECTS)[:8],
            name="x", desc="", style="", references=[],
        )
        self.assertEqual(set(filled), set(list(DETAIL_FILL_SUBJECTS)[:8]))


class DerivedCropTests(unittest.TestCase):
    def test_crops_follow_the_figure_not_the_white_margins(self):
        """全身立绘左右大片留白：「面料」按整格比例会裁到空白，按人物外框裁就落在衣服上。"""
        image = Image.new("RGB", (600, 1200), (250, 250, 250))
        draw = ImageDraw.Draw(image)
        _texture(draw, (270, 80, 330, 1150), 3)
        # 按整格比例，左 0–20% 宽是纯留白；按人物外框算就落在人物身上。
        self.assertTrue(is_blank(image.crop((0, 672, 120, 888))))
        crop = _derived_crop(image, (0.0, 0.56, 0.2, 0.74))
        self.assertIsNotNone(crop)
        self.assertFalse(is_blank(crop))

    def test_a_sliver_full_body_falls_back_to_the_front_view(self):
        """全身立绘被切成人物边上一条窄条：补位改从正面全身裁，标明来源。"""
        from app.core.storyboard_assets import complete_actor_sheet_cells

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            sliver = Image.new("RGB", (150, 1000), (250, 250, 250))
            _texture(ImageDraw.Draw(sliver), (0, 0, 20, 1000), 1)
            front = Image.new("RGB", (500, 1000), (250, 250, 250))
            _texture(ImageDraw.Draw(front), (150, 40, 350, 980), 2)
            paths = [_save_cell(sliver, directory, "full_body"), _save_cell(front, directory, "front")]
            _, derived = complete_actor_sheet_cells(paths)
        self.assertEqual(derived["element_fabric"], "front")
        self.assertEqual(derived["element_hand"], "front")

    def test_a_blank_source_still_yields_a_cell(self):
        crop = _derived_crop(Image.new("RGB", (400, 800), (120, 120, 120)), (0.25, 0.56, 0.75, 0.74))
        self.assertIsNotNone(crop)


class DetailsModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "media"
        cells_dir = self.media / "character_views" / "abc"
        cells_dir.mkdir(parents=True)
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(self.media))
        patcher.start()
        self.addCleanup(patcher.stop)

        def textured(seed):
            image = Image.new("RGB", (200, 300), (240, 240, 240))
            _texture(ImageDraw.Draw(image), (20, 20, 180, 280), seed)
            return image

        cells = []
        keys = ["portrait", "full_body", *IDENTITY_VIEW_ORDER, "element_fabric", "element_hand"]
        for index, key in enumerate(dict.fromkeys(keys)):
            path = _save_cell(textured(index), cells_dir, key)
            cells.append({
                "cell": key, "image_url": f"/media/{path.relative_to(self.media).as_posix()}",
                **({"derived_from": "full_body"} if key.startswith("element_") else {}),
            })
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.task_id = self.service.create_task(DramaCreateRequest(title_suggestion="渡口", llm_model="m", image_model="img"))["task_id"]
        task = self.service.repo.get_task(self.task_id)
        task["assets"]["3_characters"] = [{
            "name": "沈知微", "desc": "青色襦裙", "sheet": "/media/sheet.png", "sheet_cells": cells,
            "views": [item for item in cells if item["cell"] in IDENTITY_VIEW_ORDER],
            "five_view_quality": {"passed": True, "issues": []},
        }]
        self.service.repo.save_task(self.task_id, task)

    def test_details_mode_replaces_only_the_filled_cells_and_clears_their_fill_tag(self):
        fill = Image.new("RGB", (300, 300), (240, 240, 240))
        _texture(ImageDraw.Draw(fill), (20, 20, 280, 280), 99)
        with (
            patch("app.service.drama_service.generate_detail_cells", return_value={"element_fabric": fill}) as generate,
            patch("app.service.drama_service.validate_actor_sheet_images") as validate,
        ):
            validate.return_value.passed = True
            validate.return_value.model_dump.return_value = {"passed": True, "issues": []}
            self.service.regenerate_character(self.task_id, "沈知微", mode="details", background=False)

        self.assertEqual(generate.call_args.kwargs["cells"], ["element_fabric", "element_hand"])
        self.assertEqual(len(generate.call_args.kwargs["references"]), 3)
        task = self.service.repo.get_task(self.task_id)
        record = task["assets"]["3_characters"][0]
        by_cell = {item["cell"]: item for item in record["sheet_cells"]}
        self.assertNotIn("derived_from", by_cell["element_fabric"])
        self.assertEqual(by_cell["element_hand"]["derived_from"], "full_body")
        self.assertEqual(task["assets"]["3_character_regeneration"]["沈知微"]["status"], "done")

    def test_nothing_to_fill_is_reported_and_keeps_the_images(self):
        with patch("app.service.drama_service.generate_detail_cells", return_value={}):
            self.service.regenerate_character(self.task_id, "沈知微", mode="details", background=False)
        task = self.service.repo.get_task(self.task_id)
        state = task["assets"]["3_character_regeneration"]["沈知微"]
        self.assertEqual(state["status"], "failed")
        self.assertIn("补画", state["error"])

    def test_an_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.regenerate_character(self.task_id, "沈知微", mode="everything", background=False)


if __name__ == "__main__":
    unittest.main()

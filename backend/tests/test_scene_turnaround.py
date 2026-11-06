# -*- coding: utf-8 -*-
"""The scene's four views: one 2×2 board, cut along its white seams into four full-bleed views."""

import io
import random
import unittest

from PIL import Image, ImageDraw

from app.core.asset_sheets import EMPTY_SCENE_PREFIX, EMPTY_SCENE_SUFFIX
from app.core.scene_turnaround import (
    SCENE_TURNAROUND_CLOSING,
    SCENE_TURNAROUND_INSTRUCTION,
    SCENE_TURNAROUND_SIZE,
    SCENE_VIEW_SLOTS,
    split_scene_turnaround,
)


def _board(width=1424, height=800, seam=(706, 718, 394, 406)) -> bytes:
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    left, right, top, bottom = seam
    generator = random.Random(7)
    for x0, y0, x1, y1 in ((0, 0, left, top), (right, 0, width, top), (0, bottom, left, height), (right, bottom, width, height)):
        for y in range(y0, y1, 5):
            for x in range(x0, x1, 5):
                value = 30 + generator.randint(0, 150)
                draw.rectangle((x, y, min(x + 4, x1 - 1), min(y + 4, y1 - 1)), fill=(value, value, value - 20))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class SceneTurnaroundTests(unittest.TestCase):
    def test_the_board_is_cut_on_its_seams_into_four_full_views(self):
        views = split_scene_turnaround(_board())
        self.assertEqual(tuple(views), SCENE_VIEW_SLOTS)
        for slot, content in views.items():
            with Image.open(io.BytesIO(content)) as view:
                width, height = view.size
                # The whole cell, minus the white seam: a scene is never trimmed to a subject.
                self.assertTrue(700 <= width <= 712 and 388 <= height <= 400, (slot, view.size))
                column = [view.getpixel((width - 1, y)) for y in range(0, height, 7)]
                self.assertFalse(all(pixel == (255, 255, 255) for pixel in column), slot)

    def test_a_seam_off_the_middle_is_still_found(self):
        views = split_scene_turnaround(_board(seam=(760, 770, 360, 372)))
        with Image.open(io.BytesIO(views["scene_main"])) as main:
            self.assertTrue(abs(main.size[0] - 760) <= 6 and abs(main.size[1] - 360) <= 6, main.size)

    def test_a_board_too_small_to_cut_is_refused(self):
        buffer = io.BytesIO()
        Image.new("RGB", (1, 1), (10, 10, 10)).save(buffer, format="PNG")
        with self.assertRaises(ValueError):
            split_scene_turnaround(buffer.getvalue())

    def test_the_prompt_is_an_empty_plate_with_layout_light_materials_and_scale(self):
        prompt = SCENE_TURNAROUND_INSTRUCTION + SCENE_TURNAROUND_CLOSING
        self.assertTrue(prompt.startswith(EMPTY_SCENE_PREFIX))
        self.assertTrue(prompt.endswith(EMPTY_SCENE_SUFFIX))
        for phrase in ("全场无人", "左上格：主场景全景", "右上格：45°斜角", "左下格：纵深视角", "右下格：关键细节",
                       "画面左侧是什么、右侧是什么", "主光从画面哪一侧来、色温与时段", "颜色与材质", "门高约2米"):
            self.assertIn(phrase, prompt)
        width, height = (int(value) for value in SCENE_TURNAROUND_SIZE.split("x"))
        self.assertLessEqual(width * height, 4_620_000)
        self.assertAlmostEqual(width / height, 16 / 9, places=2)


if __name__ == "__main__":
    unittest.main()

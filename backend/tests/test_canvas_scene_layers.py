# -*- coding: utf-8 -*-
"""逆向拆解一张剧照：空间基底、配色卡、氛围建立三个画布工具。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.core import canvas_tools, canvas_workflow, prompt_data
from app.service import canvas_tool_ops


def _still(path: Path) -> str:
    """A night street: a dark sky, a warm lit wall, a pale road, with a soft gradient so it is not flat."""
    image = Image.new("RGB", (320, 180))
    for x in range(320):
        for y in range(180):
            if y < 70:
                image.putpixel((x, y), (12 + y // 6, 18 + y // 5, 40 + y // 3))
            elif x < 160:
                image.putpixel((x, y), (200 - y // 4, 120 - y // 6, 50))
            else:
                image.putpixel((x, y), (150 + x // 8, 150 + x // 8, 140 + y // 6))
    image.save(path)
    return str(path)


class ColourCardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.still = _still(self.folder / "still.png")

    def test_the_card_is_flat_blocks_of_the_stills_own_colours_from_dark_to_light(self):
        out = str(self.folder / "card.png")
        canvas_tool_ops.color_card([self.still], 8, out)
        with Image.open(out) as card:
            self.assertEqual(card.size, canvas_tool_ops.CARD_SIZE)
            colours = canvas_tool_ops.card_colours([self.still], 8)
            self.assertGreaterEqual(len(colours), canvas_tool_ops.CARD_MIN_BLOCKS, "a still with few colours still fills six blocks")
            self.assertLessEqual(len(colours), 8)
            step = card.width // len(colours)
            shown = [card.getpixel((index * step + step // 2, card.height // 2)) for index in range(len(colours))]
            self.assertEqual(shown, colours)
            # Flat: a block is one colour from top to bottom and edge to edge.
            self.assertEqual(card.getpixel((3, 3)), card.getpixel((step - 3, card.height - 3)))
        light = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in colours]
        self.assertEqual(light, sorted(light))
        self.assertLess(light[0], 60, "the night sky is on the card")
        self.assertGreater(light[-1], 140, "and so is the pale road")

    def test_a_small_warm_accent_and_the_highlight_keep_a_block_in_a_cold_picture(self):
        cold = Image.new("RGB", (400, 240))
        for x in range(400):
            for y in range(240):
                cold.putpixel((x, y), (10 + x // 20, 40 + x // 8 + y // 12, 60 + x // 6 + y // 10))
        cold.paste((190, 120, 60), (30, 30, 60, 60))       # a lantern: under 1% of the frame
        cold.paste((235, 240, 238), (340, 20, 370, 40))    # a lit window pane
        path = str(self.folder / "cold.png")
        cold.save(path)
        colours = canvas_tool_ops.card_colours([path], 8)
        self.assertTrue(any(red > blue + 60 for red, _, blue in colours), f"the lantern's warmth is on the card: {colours}")
        self.assertGreater(max(sum(colour) for colour in colours), 600, "and the brightest pane")
        self.assertLessEqual(len(colours), 8)

    def test_a_palette_strip_somebody_brought_goes_onto_the_card(self):
        strip = Image.new("RGB", (300, 40))
        for index, colour in enumerate([(230, 20, 160), (20, 220, 210), (250, 240, 30)]):
            strip.paste(colour, (index * 100, 0, (index + 1) * 100, 40))
        path = str(self.folder / "strip.png")
        strip.save(path)
        colours = canvas_tool_ops.card_colours([self.still, path], 8)
        self.assertLessEqual(len(colours), 8)
        for wanted in ((230, 20, 160), (20, 220, 210), (250, 240, 30)):
            self.assertTrue(any(sum(abs(a - b) for a, b in zip(wanted, colour)) < 30 for colour in colours), wanted)

    def test_a_card_is_recognised_by_what_it_is_and_a_photograph_is_not(self):
        out = str(self.folder / "card.png")
        canvas_tool_ops.color_card([self.still], 8, out)
        self.assertTrue(canvas_tool_ops.is_color_card(out))
        self.assertFalse(canvas_tool_ops.is_color_card(self.still))
        self.assertFalse(canvas_tool_ops.is_color_card(str(self.folder / "missing.png")))
        # A sideways gradient is uniform top to bottom too, but it never holds a colour: not a card.
        ramp = Image.new("RGB", (256, 40))
        for x in range(256):
            ramp.paste((x, x, x), (x, 0, x + 1, 40))
        ramp.save(self.folder / "ramp.png")
        self.assertFalse(canvas_tool_ops.is_color_card(str(self.folder / "ramp.png")))
        # One flat frame (a blackout) is not a card either: a card has blocks.
        Image.new("RGB", (200, 100), (8, 8, 10)).save(self.folder / "black.png")
        self.assertFalse(canvas_tool_ops.is_color_card(str(self.folder / "black.png")))

    def test_the_mood_frame_gets_base_still_card_in_that_order_wherever_the_card_was_wired(self):
        card = str(self.folder / "card.png")
        canvas_tool_ops.color_card([self.still], 8, card)
        base = _still(self.folder / "base.png")
        with patch.object(canvas_tool_ops, "_materialize", side_effect=lambda url, suffix, scratch: url):
            self.assertEqual(canvas_tool_ops.mood_references([card, base, self.still], ""), [base, self.still, card])
            self.assertEqual(canvas_tool_ops.mood_references([base, card, self.still], ""), [base, self.still, card])
            self.assertEqual(canvas_tool_ops.mood_references([base, self.still, card], ""), [base, self.still, card])
            # No card among them (or two): nothing is guessed, the order stays as wired.
            self.assertEqual(canvas_tool_ops.mood_references([base, self.still, base], ""), [base, self.still, base])
            self.assertEqual(canvas_tool_ops.mood_references([card, card, base], ""), [card, card, base])


class CatalogTests(unittest.TestCase):
    def test_the_three_tools_are_skills_and_the_card_needs_no_model(self):
        tools = {tool.id: tool for tool in canvas_tools.TOOLS}
        self.assertEqual((tools["space_base"].engine, tools["space_base"].images, tools["space_base"].output), ("image", 1, "image"))
        self.assertEqual((tools["color_card"].engine, tools["color_card"].images, tools["color_card"].output), ("local", 1, "image"))
        self.assertEqual((tools["mood_frame"].engine, tools["mood_frame"].images, tools["mood_frame"].output), ("image", 3, "image"))
        self.assertEqual({tools[key].group for key in ("space_base", "color_card", "mood_frame")}, {"skill"})

    def test_the_space_base_is_asked_to_rebuild_the_place_before_the_story_not_to_blank_the_still(self):
        prompt = canvas_tools.image_prompt(canvas_tools.get_tool("space_base"), {}, "保留远处的塔")
        for words in ("机位、画幅、透视", "去掉剧情人物", "平常的自然光", "不沿用原图为主体服务的浅景深", "不凭空补出", "保留远处的塔"):
            self.assertIn(words, prompt)
        self.assertTrue(prompt.endswith(prompt_data.text("canvas_tools", "module.no_text")))

    def test_the_mood_frame_gives_each_reference_one_job(self):
        prompt = canvas_tools.image_prompt(canvas_tools.get_tool("mood_frame"), {}, "")
        self.assertLess(prompt.index("图1是空间基底"), prompt.index("图2是原始剧照"))
        self.assertLess(prompt.index("图2是原始剧照"), prompt.index("图3是配色卡"))
        for words in ("以图1为准", "以图2为准", "严格以图3为准", "色块本身不出现在画面里", "不增加、不移除、不移动、不替换任何实体"):
            self.assertIn(words, prompt)

    def test_the_workflow_planner_is_told_how_the_three_are_wired(self):
        rules = prompt_data.text("canvas_workflow", "module.rules")
        self.assertIn("把 space_base、原图、color_card 按这个顺序连到 mood_frame", rules)
        described = canvas_workflow.planning_prompt("逆向拆解这张剧照")
        for label in ("空间基底", "配色卡", "氛围建立"):
            self.assertIn(label, described)


if __name__ == "__main__":
    unittest.main()

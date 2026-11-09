# -*- coding: utf-8 -*-
"""Prop sheets: how many views an object needs, how big it is, and a board whose numbers can be trusted."""

import io
import unittest

from PIL import Image, ImageChops, ImageDraw

from app.core.prop_board import _hand, _object_box, _on_white, compose_prop_board
from app.core.prop_turnaround import (
    PROP_DISPLAY_ONLY_SLOTS,
    SQUARE_SIZE,
    WIDE_SIZE,
    nice_step,
    plan_prop,
    prop_instruction,
    split_prop_sheet,
    stated_length_cm,
)


def _sheet(plan, *, object_size=(60, 400), size=(2848, 1600)) -> bytes:
    """A grid as the image model would draw it: a dark object in each cell on white, with white seams."""
    image = Image.new("RGB", size, (250, 250, 250))
    draw = ImageDraw.Draw(image)
    width, height = size
    cell_w, cell_h = width / plan.columns, height / plan.rows
    for row in range(plan.rows):
        for column in range(plan.columns):
            left, top = column * cell_w, row * cell_h
            center = (left + cell_w / 2, top + cell_h / 2)
            draw.rectangle((center[0] - object_size[0] / 2, center[1] - object_size[1] / 2,
                            center[0] + object_size[0] / 2, center[1] + object_size[1] / 2), fill=(40, 30, 30))
    for column in range(1, plan.columns):
        draw.rectangle((column * cell_w - 6, 0, column * cell_w + 6, height), fill=(255, 255, 255))
    for row in range(1, plan.rows):
        draw.rectangle((0, row * cell_h - 6, width, row * cell_h + 6), fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class PlanTest(unittest.TestCase):
    def test_the_number_of_views_depends_on_the_object(self):
        self.assertEqual(plan_prop("长剑").views, ("prop_front", "prop_side", "prop_back"))
        self.assertEqual(plan_prop("青铜令牌").views, ("prop_front", "prop_back", "prop_side"))
        self.assertEqual(plan_prop("茶碗").views, ("prop_front", "prop_top", "prop_left_45"))
        self.assertEqual(len(plan_prop("雕花木桌").views), 5)
        self.assertEqual(len(plan_prop("不知道是什么").views), 5)

    def test_what_the_name_ends_in_says_what_it_is(self):
        self.assertEqual(plan_prop("拭剑旧布").longest_cm, 40)
        self.assertEqual(plan_prop("拭剑旧布").views[1], "prop_back")
        self.assertEqual(plan_prop("剑鞘").longest_cm, 85)
        self.assertEqual(plan_prop("青白玉扳指").longest_cm, 3)
        self.assertEqual(plan_prop("长剑（断裂）").longest_cm, 100)

    def test_long_objects_are_one_row_and_compact_ones_a_square_grid(self):
        sword, token = plan_prop("长剑"), plan_prop("令牌")
        self.assertEqual((sword.rows, sword.columns, sword.size), (1, 4, WIDE_SIZE))
        self.assertEqual((token.rows, token.columns, token.size), (2, 2, SQUARE_SIZE))

    def test_hand_for_what_a_hand_can_measure_and_figure_for_the_rest(self):
        self.assertFalse(plan_prop("长剑").figure)
        self.assertTrue(plan_prop("长枪").figure)
        self.assertTrue(plan_prop("凳").figure, "furniture is sized against a person even when low")
        self.assertTrue(plan_prop("令牌", "高两米的巨型令牌").figure)

    def test_a_stated_size_wins_and_is_not_marked_as_an_estimate(self):
        plan = plan_prop("长剑", "全长 120cm，古朴")
        self.assertEqual((plan.longest_cm, plan.size_stated), (120, True))
        self.assertFalse(plan_prop("长剑").size_stated)

    def test_a_size_set_by_hand_wins_over_the_description_and_the_estimate(self):
        plan = plan_prop("长剑", "全长 120cm", length_cm=64)
        self.assertEqual((plan.longest_cm, plan.size_stated), (64, True))
        self.assertTrue(plan_prop("长剑", length_cm=200).figure)
        self.assertFalse(plan_prop("长枪", length_cm=90).figure)

    def test_prompt_asks_for_pictures_not_writing(self):
        text = prop_instruction(plan_prop("长枪"))
        self.assertIn("1 行 × 4 列", text)
        self.assertIn("人台", text)
        self.assertIn("220 厘米", text)
        self.assertNotIn("真人面孔", text)
        self.assertIn("手长约", prop_instruction(plan_prop("长剑")))

    def test_prompt_states_the_ratio_and_a_clean_background(self):
        sword = prop_instruction(plan_prop("长剑"))
        self.assertIn("手长的 5.6 倍", sword)
        self.assertIn("纯白背景", sword)
        self.assertIn("没有投影", sword)
        self.assertIn("人台身高的 1.3 倍", prop_instruction(plan_prop("长枪")))


class StatedLengthTest(unittest.TestCase):
    def test_units_and_chinese_numbers(self):
        for text, expected in (("长约80厘米", 80), ("全长1.2米", 120), ("高两米", 200), ("三尺长", 99), ("七寸", 23.1),
                               ("直径 30 mm", 3), ("长二十五厘米", 25), ("宽5cm，全长100cm", 100)):
            self.assertAlmostEqual(stated_length_cm(text), expected, places=1, msg=text)

    def test_size_words(self):
        self.assertEqual(stated_length_cm("掌心大小"), 8)
        self.assertEqual(stated_length_cm("巴掌大的铜镜"), 15)

    def test_a_distance_is_not_a_size(self):
        self.assertIsNone(stated_length_cm("放在三米外的桌上"))
        self.assertIsNone(stated_length_cm("古朴，刻虎纹"))


class SplitTest(unittest.TestCase):
    def test_every_cell_lands_in_its_own_slot(self):
        for name, size in (("长剑", (2848, 1600)), ("令牌", (2048, 2048)), ("雕花木桌", (2848, 1600))):
            plan = plan_prop(name)
            views = split_prop_sheet(_sheet(plan, size=size), plan)
            self.assertEqual(tuple(views), plan.slots, name)
            for slot, content in views.items():
                with Image.open(io.BytesIO(content)) as image:
                    self.assertLess(image.width, size[0] / plan.columns + 2, f"{name} {slot} crossed a seam")
                    self.assertLess(image.height, size[1] / plan.rows + 2, f"{name} {slot} crossed a seam")

    def test_no_cell_carries_a_piece_of_the_seam(self):
        plan = plan_prop("令牌")
        image = Image.new("RGB", (1000, 1000), (30, 30, 30))  # a picture that fills every cell
        draw = ImageDraw.Draw(image)
        draw.rectangle((492, 0, 508, 1000), fill=(255, 255, 255))
        draw.rectangle((0, 492, 1000, 508), fill=(255, 255, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        for slot, content in split_prop_sheet(buffer.getvalue(), plan).items():
            with Image.open(io.BytesIO(content)) as view:
                self.assertLess(view.convert("L").getextrema()[1], 60, f"{slot} has white in it")

    def test_the_reference_for_a_video_model_is_never_a_display_only_view(self):
        for name in ("长剑", "令牌", "茶碗", "雕花木桌", "别的"):
            self.assertNotIn(plan_prop(name).views[0], PROP_DISPLAY_ONLY_SLOTS)


class BoardTest(unittest.TestCase):
    def _board(self, name, description="", object_size=(60, 400), size=(2848, 1600)):
        plan = plan_prop(name, description)
        views = split_prop_sheet(_sheet(plan, object_size=object_size, size=size), plan)
        with Image.open(io.BytesIO(compose_prop_board(plan, views))) as image:
            return plan, image.convert("RGB")

    def test_every_kind_of_object_makes_a_board(self):
        for name, object_size, size in (
            ("长剑", (60, 900), (2848, 1600)), ("青铜令牌", (200, 320), (2048, 2048)), ("青白玉扳指", (300, 300), (2048, 2048)),
            ("长枪", (30, 1200), (2848, 1600)), ("马车", (500, 300), (2848, 1600)), ("雕花木桌", (500, 200), (2848, 1600)),
        ):
            _plan, board = self._board(name, object_size=object_size, size=size)
            self.assertEqual(board.width, 2400, name)
            self.assertGreater(board.height, 800, name)

    def test_the_object_in_the_strip_is_to_scale_with_the_hand(self):
        plan, board = self._board("长剑", object_size=(60, 900))
        # The band just above the ruler, below both labels.
        band = board.crop((0, board.height - 470 + 215, board.width, board.height - 470 + 352)).convert("L")
        sword = band.point(lambda value: 255 if value < 70 else 0).getbbox()
        rest = band.crop((sword[2] + 4, 0, band.width, band.height))
        hand = rest.point(lambda value: 255 if 185 <= value <= 200 else 0).getbbox()
        self.assertAlmostEqual((sword[2] - sword[0]) / (hand[2] - hand[0]), plan.longest_cm / 18, delta=0.15)

    def test_measured_views_share_one_scale(self):
        plan = plan_prop("长剑")
        views = split_prop_sheet(_sheet(plan, object_size=(60, 900)), plan)
        with Image.open(io.BytesIO(compose_prop_board(plan, views))) as opened:
            board = opened.convert("L")
        cell = (2400 - 28 * 5) // 4
        heights = []
        for index in range(3):
            x = 28 + index * (cell + 28)
            dark = board.crop((x + 60, 30, x + cell, 28 + round(cell * 2.1) - 70)).point(lambda value: 255 if value < 70 else 0)
            box = dark.getbbox()
            heights.append(box[3] - box[1])
        self.assertLessEqual(max(heights) - min(heights), 2)

    def test_the_ruler_stays_on_the_board(self):
        for name, object_size, size in (("长剑", (60, 900), (2848, 1600)), ("青白玉扳指", (300, 300), (2048, 2048))):
            _plan, board = self._board(name, object_size=object_size, size=size)
            edge = board.crop((board.width - 30, board.height - 470, board.width, board.height)).convert("L")
            self.assertGreater(edge.getextrema()[0], 200, f"{name}: something runs off the right edge")

    def test_views_drawn_at_different_zooms_come_back_to_one_scale(self):
        plan = plan_prop("雕花木桌")
        def view(width, height):
            image = Image.new("RGB", (900, 900), (250, 250, 250))
            ImageDraw.Draw(image).rectangle((100, 100, 100 + width, 100 + height), fill=(210, 30, 30))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
        # front 400×200; the side was drawn twice as big as it should be, the top half as big.
        views = {slot: view(400, 200) for slot in plan.slots}
        views["prop_side"] = view(320, 400)
        views["prop_top"] = view(200, 120)
        with Image.open(io.BytesIO(compose_prop_board(plan, views))) as opened:
            green = opened.convert("RGB").split()[1]  # the red objects are dark here; the grey labels are not as dark
            red = opened.convert("RGB").split()[0]
        cell = (2400 - 28 * 7) // 6
        def extent(index):
            x = 28 + index * (cell + 28)
            area = (x + 4, 32, x + cell - 4, 28 + cell)
            only_red = ImageChops.subtract(red.crop(area), green.crop(area)).point(lambda value: 255 if value > 100 else 0)
            box = only_red.getbbox()
            return box[2] - box[0], box[3] - box[1]
        front, side, top = extent(0), extent(1), extent(3)
        self.assertAlmostEqual(front[1], side[1], delta=3)
        self.assertAlmostEqual(front[0], top[0], delta=3)

    def test_an_all_white_view_does_not_crash_it(self):
        plan = plan_prop("令牌")
        blank = io.BytesIO()
        Image.new("RGB", (400, 400), (255, 255, 255)).save(blank, format="PNG")
        views = {slot: blank.getvalue() for slot in plan.slots}
        self.assertTrue(compose_prop_board(plan, views))


class HelpersTest(unittest.TestCase):
    def test_a_grey_background_becomes_white_and_a_scene_stays(self):
        grey = Image.new("RGB", (40, 40), (230, 232, 228))
        self.assertEqual(_on_white(grey).getpixel((5, 5)), (255, 255, 255))
        dark = Image.new("RGB", (40, 40), (20, 60, 70))
        self.assertEqual(_on_white(dark).getpixel((5, 5)), (20, 60, 70))

    def test_ruler_steps(self):
        self.assertEqual(nice_step(100), 10)
        self.assertEqual(nice_step(24), 5)
        self.assertEqual(nice_step(170), 20)

    def test_object_box_finds_the_object(self):
        image = Image.new("RGB", (100, 100), (252, 252, 252))
        ImageDraw.Draw(image).rectangle((20, 30, 40, 80), fill=(10, 10, 10))
        self.assertEqual(_object_box(image), (20, 30, 41, 81))

    def test_hand_keeps_its_proportions(self):
        hand = _hand(200)
        self.assertEqual(hand.width, 200)
        self.assertEqual(hand.height, 94)


if __name__ == "__main__":
    unittest.main()


class ScaleReferenceTableTests(unittest.TestCase):
    """道具标尺参照表(LF_D2P V1.12)：按名字查真实尺寸，比按名字结尾的字猜准得多。"""

    def test_props_the_noun_guess_got_wrong_get_their_real_size(self):
        from app.core.prop_turnaround import plan_prop

        pistol = plan_prop("半自动手枪")  # 以前按结尾的「枪」当成两米多的长枪
        self.assertEqual((pistol.longest_cm, pistol.figure, pistol.size_source), (20.0, False, "table"))
        self.assertIn("prop_left_45", pistol.views, "a pistol is not laid out like a spear")
        tank = plan_prop("主战坦克二型")
        self.assertEqual((tank.longest_cm, tank.figure), (950.0, True))
        self.assertEqual(plan_prop("马").longest_cm, 250.0)
        self.assertEqual(plan_prop("冰箱").longest_cm, 180.0)
        self.assertIn("长20×宽4×高14厘米", prop_instruction(pistol))

    def test_shape_and_what_a_person_wrote_still_win(self):
        from app.core.prop_turnaround import plan_prop

        self.assertEqual(plan_prop("盾牌").views, plan_prop("令牌").views, "a shield is still drawn flat")
        self.assertEqual(plan_prop("拭剑旧布").size_source, "estimate", "a cloth is not the sword it wipes")
        self.assertEqual(plan_prop("马车").size_source, "estimate", "a cart is not a horse")
        self.assertEqual(plan_prop("宝剑", "全长八十厘米").longest_cm, 80.0)
        self.assertEqual(plan_prop("宝剑", length_cm=90).size_source, "manual")

    def test_the_table_has_each_prop_once_with_its_typo_fixed(self):
        import json

        from app.core import prop_scale

        entries = json.loads(prop_scale.TABLE.read_text(encoding="utf-8"))["entries"]
        names = [entry["name"] for entry in entries]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(prop_scale.lookup("智能手机二型").dims_cm, (15.5, 7.5, 0.8))

    def test_a_shot_keeps_a_prop_to_scale_beside_people(self):
        from app.core.storyboard_scene_context import reference_note

        note = reference_note(3, {"kind": "prop", "name": "半自动手枪"})
        self.assertIn("真实尺寸约长20×宽4×高14厘米", note)
        self.assertNotIn("；", note)
        self.assertNotIn("真实尺寸", reference_note(5, {"kind": "prop", "name": "拭剑旧布"}))

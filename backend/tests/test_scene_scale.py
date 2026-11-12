# -*- coding: utf-8 -*-
"""拍摄场地的人物比例参照：尺寸从描述或场地类型来，全景下面接比例尺、人形和尺寸，只给人看。"""

import io
import unittest

from PIL import Image

from app.core import scene_scale, storyboard_element_context


def _png(width=1424, height=800) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (60, 40, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class PlanTests(unittest.TestCase):
    def test_sizes_written_in_the_description_win(self):
        plan = scene_scale.plan("密道", "密道宽约1.2米、高约1.8米，纵深约30米")
        self.assertEqual(plan.source, "description")
        self.assertEqual(plan.text(), "密道宽约1.2米、密道高约1.8米、密道纵深约30米")

    def test_old_units_and_square_rooms_are_read(self):
        self.assertEqual(scene_scale.plan("客栈暗室", "空间逼仄，约两丈见方").text(), "房间面宽约6.7米、房间进深约6.7米")
        self.assertEqual(scene_scale.plan("殿", "大殿高三丈、面阔十二丈").text(), "大殿高约10米、大殿面阔约40米")

    def test_the_kind_of_place_is_read_from_the_end_of_its_name(self):
        hidden_room = scene_scale.plan("客栈暗室")
        self.assertEqual((hidden_room.source, hidden_room.kind), ("table", "暗室牢房"), "a hidden room of an inn is not its hall")
        self.assertEqual(scene_scale.plan("紫禁城午门").kind, "城门宫门")
        self.assertEqual(scene_scale.plan("无名之地").source, "indoor")
        self.assertEqual(scene_scale.plan("荒郊野外").source, "outdoor")

    def test_the_scale_bar_spans_the_place_within_limits(self):
        self.assertEqual(scene_scale.plan("客栈暗室").bar_meters(), 5.0)
        self.assertEqual(scene_scale.plan("紫禁城午门").bar_meters(), 10.0)
        self.assertEqual(scene_scale.plan("马车").bar_meters(), 4.0)

    def test_the_prompt_line_carries_the_sizes_and_the_person(self):
        line = scene_scale.prompt_line(scene_scale.plan("客栈暗室"))
        self.assertIn("室内层高约2.6米", line)
        self.assertIn("1.75 米", line)


class ComposeTests(unittest.TestCase):
    def test_a_white_strip_is_added_under_the_panorama(self):
        board = Image.open(io.BytesIO(scene_scale.compose(_png(), scene_scale.plan("客栈暗室"))))
        self.assertEqual(board.width, 1600, "small panoramas are enlarged so the strip stays readable")
        self.assertGreater(board.height, round(800 * 1600 / 1424))
        strip = board.crop((0, board.height - 40, board.width, board.height)).convert("L")
        self.assertGreater(sum(strip.getdata()) / (strip.width * strip.height), 200, "the strip is white")


class ReferenceTests(unittest.TestCase):
    def test_the_board_never_becomes_a_reference_image(self):
        self.assertIn(scene_scale.SCENE_SCALE_SLOT, storyboard_element_context._DISPLAY_ONLY_SLOTS)


if __name__ == "__main__":
    unittest.main()

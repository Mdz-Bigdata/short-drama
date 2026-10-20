import io
import random
import unittest

from PIL import Image, ImageDraw

from app.core.actor_hd_views import HD_BODY_CELLS, HD_FACE_CELLS, generate_hd_views, split_triptych


def _triptych(width: int, height: int, *, seeds=(1, 2, 3), same=False) -> bytes:
    """横排三格：每格中间一块带纹理的人形，格间白缝；same=True 时三格一模一样(没转面)。"""
    image = Image.new("RGB", (width, height), (246, 246, 246))
    draw = ImageDraw.Draw(image)
    third = width // 3
    for gap in (third, 2 * third):
        draw.rectangle((gap - 4, 0, gap + 4, height), fill=(255, 255, 255))
    for index in range(3):
        generator = random.Random(seeds[0] if same else seeds[index])
        left = index * third + third // 4
        top = height // 8
        offset = 0 if same else index * third // 10
        for y in range(top, height - top, 6):
            for x in range(left + offset, left + offset + third // 2, 6):
                value = 50 + generator.randint(0, 120)
                draw.rectangle((x, y, x + 5, y + 5), fill=(value, value - 20, value - 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class SplitTests(unittest.TestCase):
    def test_a_triptych_is_cut_into_three_trimmed_views(self):
        crops = split_triptych(_triptych(1536, 512))
        self.assertEqual(len(crops), 3)
        for crop in crops:
            self.assertLess(crop.width, 512)          # 收紧到人物，不是整个三分之一
            self.assertGreater(crop.height, 300)


class UnevenSplitTests(unittest.TestCase):
    def test_uneven_panels_without_white_gutters_are_cut_at_their_real_edges(self):
        """三格不等宽、格间只有窄缝：按真实面板切，每张只有一个人物。"""
        image = Image.new("RGB", (1536, 512), (246, 246, 246))
        draw = ImageDraw.Draw(image)
        edges = [(0, 420), (424, 1080), (1084, 1536)]
        generator = random.Random(7)
        for left, right in edges:
            for y in range(40, 470, 6):
                for x in range(left + 30, right - 30, 6):
                    value = 50 + generator.randint(0, 120)
                    draw.rectangle((x, y, x + 5, y + 5), fill=(value, value - 20, value - 30))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        crops = split_triptych(buffer.getvalue())
        widths = [crop.width for crop in crops]
        self.assertLess(widths[0], 420)
        self.assertGreater(widths[1], 560)
        self.assertLess(widths[2], 452)


class GenerateTests(unittest.TestCase):
    def _run(self, payloads):
        calls = []

        def generate(prompt, references, size):
            calls.append((prompt, references, size))
            return f"https://img.test/{len(calls)}.png"

        views = generate_hd_views(
            generate=generate, load=lambda url: payloads[int(url.rsplit("/", 1)[1].split(".")[0]) - 1],
            name="陆昀", desc="男主角", style="真人电影写实", references=["data:image/png;base64,AAA"],
        )
        return views, calls

    def test_both_groups_replace_all_six_identity_views(self):
        views, calls = self._run([_triptych(1536, 512), _triptych(1536, 1024, seeds=(4, 5, 6))])
        self.assertEqual(set(views), set(HD_FACE_CELLS) | set(HD_BODY_CELLS))
        self.assertEqual([size for _, _, size in calls], ["3072x1024", "3072x2048"])
        self.assertIn("向画面左侧转 45°", calls[0][0])
        self.assertIn("90 度标准侧面全身", calls[1][0])
        self.assertEqual(calls[0][1], ["data:image/png;base64,AAA"])

    def test_faces_that_did_not_turn_are_not_used(self):
        views, _ = self._run([_triptych(1536, 512, same=True), _triptych(1536, 1024, seeds=(4, 5, 6))])
        self.assertEqual(set(views), set(HD_BODY_CELLS))

    def test_a_failed_call_keeps_the_sheet_crops(self):
        views = generate_hd_views(
            generate=lambda *args: None, load=lambda url: b"", name="陆昀", desc="", style="", references=[],
        )
        self.assertEqual(views, {})


if __name__ == "__main__":
    unittest.main()

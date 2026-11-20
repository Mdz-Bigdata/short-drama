import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.core import canvas_tools
from app.service import canvas_tool_ops

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class EraseRulesTest(unittest.TestCase):
    def test_a_preset_fills_the_whole_width_of_a_subtitle_band(self):
        x, y, w, h = canvas_tools.erase_box({"preset": "bottom_band", "x": 50, "w": 5}, 1280, 720)
        self.assertEqual((x, w), (1, 1277))
        self.assertGreater(y, 720 * 0.8)
        self.assertLessEqual(y + h, 720 - 1)
        self.assertEqual(canvas_tools.erase_box({"preset": "nonsense", "x": 10, "y": 10, "w": 20, "h": 10}, 1000, 1000), (100, 100, 200, 100))

    def test_the_mode_is_one_of_the_three_and_defaults_to_filling(self):
        self.assertEqual(canvas_tools.erase_mode({}), "delogo")
        self.assertEqual(canvas_tools.erase_mode({"mode": "mosaic"}), "mosaic")
        self.assertEqual(canvas_tools.erase_mode({"mode": "drop table"}), "delogo")


@unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
class EraseRunTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "in.mp4"
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "1", str(self.source),
        ], check=True, capture_output=True, timeout=60)

    def _region_changed(self, out: Path, box: tuple[int, int, int, int]) -> tuple[bool, bool]:
        from PIL import Image, ImageChops

        frames = []
        for path in (self.source, out):
            still = Path(self.temp.name) / f"{path.stem}.png"
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(path), "-frames:v", "1", str(still)], check=True, capture_output=True, timeout=60)
            frames.append(Image.open(still).convert("RGB"))
        diff = ImageChops.difference(*frames)
        x, y, w, h = box
        inside = diff.crop((x + 2, y + 2, x + w - 2, y + h - 2)).getbbox() is not None
        outside = diff.crop((0, 0, frames[0].width, max(1, y - 4))).getbbox()
        return inside, outside is None or max(diff.crop((0, 0, frames[0].width, max(1, y - 4))).getextrema()[c][1] for c in range(3)) < 40

    def test_each_mode_changes_the_box_keeps_the_rest_and_the_sound(self):
        for mode in ("delogo", "blur", "mosaic"):
            with self.subTest(mode=mode):
                out = Path(self.temp.name) / f"{mode}.mp4"
                params = {"mode": mode, "preset": "bottom_band"}
                canvas_tool_ops.erase_region(str(self.source), params, str(out))
                facts = canvas_tool_ops._probe(str(out))
                self.assertTrue(facts["has_audio"])
                inside, rest_kept = self._region_changed(out, canvas_tools.erase_box(params, 320, 180))
                self.assertTrue(inside, f"{mode} left the band as it was")
                self.assertTrue(rest_kept, f"{mode} changed the picture above the band")


if __name__ == "__main__":
    unittest.main()

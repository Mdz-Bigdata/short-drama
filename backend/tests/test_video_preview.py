import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import video_preview
from app.core.video_preview import VideoFacts

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _encoders() -> str:
    try:
        return subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def clip(folder: Path, name: str, codec: str, size: str = "320x180", audio: bool = True) -> Path:
    path = folder / name
    command = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=10:duration=1"]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac"]
    command += ["-c:v", codec, "-pix_fmt", "yuv420p", "-t", "1", str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return path


class RulesTest(unittest.TestCase):
    def test_what_a_browser_plays(self):
        h264 = VideoFacts("h264", "yuv420p", "High", 1920, 1080, True)
        self.assertTrue(video_preview.browser_plays(h264, ".mp4"))
        self.assertFalse(video_preview.browser_plays(h264, ".mov"))
        self.assertFalse(video_preview.browser_plays(VideoFacts("hevc", "yuv420p", "Main", 1920, 1080, True), ".mp4"))
        self.assertFalse(video_preview.browser_plays(VideoFacts("h264", "yuv420p10le", "High 10", 1920, 1080, True), ".mp4"))
        self.assertTrue(video_preview.browser_plays(VideoFacts("vp9", "yuv420p", "", 640, 360, False), ".webm"))

    def test_the_preview_keeps_the_long_side_within_the_limit_and_sizes_even(self):
        self.assertEqual(video_preview._scale(VideoFacts("hevc", "yuv420p", "", 3840, 2160, True)), "scale=1280:-2")
        self.assertEqual(video_preview._scale(VideoFacts("hevc", "yuv420p", "", 1080, 1920, True)), "scale=-2:1280")
        self.assertEqual(video_preview._scale(VideoFacts("hevc", "yuv420p", "", 641, 361, True)), "scale=trunc(iw/2)*2:trunc(ih/2)*2")
        self.assertEqual(video_preview.preview_name("canvas_up_ab12.mp4"), "canvas_up_ab12.preview.mp4")

    def test_a_video_that_cannot_be_read_gets_no_preview_and_raises_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "broken.mp4"
            broken.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
            with self.assertLogs("app.core.video_preview", level="WARNING"):
                self.assertIsNone(video_preview.preview_if_needed(broken))
            self.assertEqual(sorted(item.name for item in Path(folder).iterdir()), ["broken.mp4"])

    def test_without_ffmpeg_nothing_is_attempted(self):
        from app.core import media_compositor

        with mock.patch.object(media_compositor, "_ffmpeg", return_value=None), \
                self.assertLogs("app.core.video_preview", level="WARNING") as logs:
            self.assertIsNone(video_preview.preview_if_needed("/nonexistent.mp4"))
        self.assertIn("ffmpeg", logs.output[0])


@unittest.skipUnless(HAS_FFMPEG and "libx265" in _encoders(), "needs ffmpeg with libx265")
class TranscodeTest(unittest.TestCase):
    def test_an_hevc_upload_gets_a_playable_h264_copy_and_the_original_stays(self):
        with tempfile.TemporaryDirectory() as folder:
            source = clip(Path(folder), "canvas_up_x.mp4", "libx265")
            before = source.read_bytes()
            self.assertEqual(video_preview.probe(source).codec, "hevc")
            made = video_preview.preview_if_needed(source)
            self.assertEqual(made.name, "canvas_up_x.preview.mp4")
            facts = video_preview.probe(made)
            self.assertEqual((facts.codec, facts.pixel_format, facts.has_audio), ("h264", "yuv420p", True))
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse([item for item in Path(folder).iterdir() if ".part." in item.name])

    def test_an_h264_upload_gets_none(self):
        with tempfile.TemporaryDirectory() as folder:
            source = clip(Path(folder), "plain.mp4", "libx264", audio=False)
            self.assertIsNone(video_preview.preview_if_needed(source))
            self.assertEqual([item.name for item in Path(folder).iterdir()], ["plain.mp4"])

    def test_the_canvas_upload_answers_with_the_preview(self):
        from app.core import media_compositor
        from app.service.studio_service import StudioService

        with tempfile.TemporaryDirectory() as folder:
            content = clip(Path(folder), "phone.mp4", "libx265").read_bytes()
            service = StudioService.__new__(StudioService)
            service.repository = mock.Mock()
            media = Path(folder) / "media"
            with mock.patch.object(media_compositor, "MEDIA_DIR", str(media)):
                stored = service.store_canvas_upload("p1", "u1", "phone.mp4", "video/mp4", content)
            self.assertEqual(stored["medium"], "video")
            self.assertTrue(stored["preview_url"].endswith(".preview.mp4"))
            self.assertNotEqual(stored["preview_url"], stored["url"])
            names = sorted(item.name for item in media.iterdir())
            self.assertEqual(len(names), 2)
            self.assertTrue(any(name.endswith(".preview.mp4") for name in names))


if __name__ == "__main__":
    unittest.main()

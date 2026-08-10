import subprocess
import tempfile
import unittest
from pathlib import Path

from app.core import media_compositor


class MediaTransitionTests(unittest.TestCase):
    def test_xfade_join_overlaps_adjacent_clips(self):
        ffmpeg = media_compositor._ffmpeg()
        if not ffmpeg:
            self.skipTest("ffmpeg unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clips = []
            for index, color in enumerate(("red", "blue")):
                path = root / f"{index}.mp4"
                subprocess.run(
                    [ffmpeg, "-y", "-f", "lavfi", "-i", f"color={color}:s=160x240:d=1:r=30",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                clips.append(str(path))
            output = root / "joined.mp4"
            durations = media_compositor._join_video_segments(
                clips, str(output), transition_specs=[{"type": "crossfade", "duration": 0.25}]
            )
            self.assertEqual(durations, [0.25])
            joined_duration = media_compositor._probe_duration(str(output))
            self.assertIsNotNone(joined_duration)
            self.assertGreater(joined_duration, 1.6)
            self.assertLess(joined_duration, 1.9)


if __name__ == "__main__":
    unittest.main()

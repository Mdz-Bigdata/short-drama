"""Music under dubbed shots plays to the end of the film, even when the last shot has no lines.

The music is ducked under the voices with a sidechain compressor, and that filter stops at its shorter input:
the voices' track ended with the last line, so the music (and the film's whole sound) used to stop there, seconds
before the picture did. Real ffmpeg, tiny local clips; skipped where ffmpeg is missing.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import media_compositor

FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")


def _make(args: list[str], out: Path) -> None:
    subprocess.run([FFMPEG, "-v", "error", "-y", *args, str(out)], check=True)


def _seconds(path: str, stream: str) -> float:
    found = subprocess.run([FFPROBE, "-v", "error", "-select_streams", stream, "-show_entries", "stream=duration", "-of", "csv=p=0", path],
                           capture_output=True, text=True).stdout.strip()
    return float(found or 0)


@unittest.skipUnless(FFMPEG and FFPROBE, "needs ffmpeg and ffprobe")
class MusicLengthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "media"
        self.media.mkdir()
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(self.media))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clips = []
        for index, seconds in enumerate((2, 3, 3), start=1):
            name = f"clip{index}.mp4"
            _make(["-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24", "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p"], self.media / name)
            self.clips.append(media_compositor.public_url(name))
        self.line = Path(self.temp.name) / "line.mp3"
        _make(["-f", "lavfi", "-i", "sine=frequency=660:duration=1.2", "-ac", "2"], self.line)
        self.music = Path(self.temp.name) / "music.mp3"
        _make(["-f", "lavfi", "-i", "sine=frequency=220:duration=9", "-ac", "2"], self.music)

    def compose(self, voices):
        url = media_compositor.compose_film(
            self.clips, ["", "", ""], None, tag="music_length", title=None, bgm=False, native_audio=[False, False, False],
            shot_voices=voices, bgm_path=str(self.music),
        )
        self.assertTrue(url, "the film was not composed")
        path = media_compositor.local_media_path(url)
        self.assertTrue(path and os.path.exists(path))
        return path

    def test_the_sound_lasts_as_long_as_the_picture_when_the_last_shot_is_silent(self):
        path = self.compose([None, str(self.line), None])
        picture, sound = _seconds(path, "v"), _seconds(path, "a")
        self.assertGreater(picture, 7)
        self.assertGreaterEqual(sound, picture - 0.1, f"sound stops at {sound:.2f}s, picture runs {picture:.2f}s")

    def test_music_alone_still_matches_the_picture(self):
        path = self.compose(None)
        self.assertGreaterEqual(_seconds(path, "a"), _seconds(path, "v") - 0.1)


if __name__ == "__main__":
    unittest.main()

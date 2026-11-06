import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.core import media_compositor


class SoundJoinPlanTests(unittest.TestCase):
    def plan(self, clips, voices, join, **kwargs):
        return media_compositor.plan_sound_joins(clips, voices, [join], **kwargs)

    def test_an_l_cut_cuts_the_picture_early_so_the_line_runs_over(self):
        heads, tails, leads, report = self.plan([4.0, 3.0], [3.7, None], {"join": "l_cut"})
        self.assertEqual((heads, leads), ([0.0, 0.0], [0.0, 0.0]))
        self.assertAlmostEqual(tails[0], 0.8)
        self.assertTrue(report[0]["applied"])

    def test_a_line_already_longer_than_its_clip_costs_no_picture(self):
        _, tails, _, report = self.plan([3.0, 3.0], [3.9, None], {"join": "l_cut"})
        self.assertEqual(tails, [0.0, 0.0])
        self.assertTrue(report[0]["applied"])

    def test_a_line_that_ended_long_before_the_cut_is_not_stretched_over_it(self):
        _, tails, _, report = self.plan([8.0, 3.0], [1.0, None], {"join": "l_cut"})
        self.assertEqual(tails, [0.0, 0.0])
        self.assertFalse(report[0]["applied"])
        self.assertIn("7.0 秒就说完了", report[0]["reason"])

    def test_an_l_cut_does_not_talk_over_the_next_line(self):
        _, tails, _, report = self.plan([4.0, 3.0], [3.7, 2.0], {"join": "l_cut"})
        self.assertEqual(tails, [0.0, 0.0])
        self.assertIn("压住", report[0]["reason"])

    def test_a_j_cut_removes_the_head_and_starts_the_voice_before_the_picture(self):
        heads, tails, leads, report = self.plan([4.0, 3.0], [None, 2.0], {"join": "j_cut"})
        self.assertEqual(heads, [0.0, 0.4])
        self.assertEqual(leads, [0.0, 0.4])
        self.assertEqual(tails, [0.0, 0.0])
        self.assertTrue(report[0]["applied"])

    def test_a_j_cut_needs_something_to_hear_and_a_clear_gap(self):
        self.assertIn("没有配音", self.plan([4.0, 3.0], [None, None], {"join": "j_cut"})[3][0]["reason"])
        heads, _, leads, report = self.plan([4.0, 3.0], [3.9, 2.0], {"join": "j_cut"})
        self.assertEqual((heads, leads), ([0.0, 0.0], [0.0, 0.0]))
        self.assertIn("压在一起", report[0]["reason"])

    def test_a_short_clip_keeps_its_picture(self):
        self.assertIn("太短", self.plan([4.0, 1.2], [None, 1.0], {"join": "j_cut"})[3][0]["reason"])

    def test_a_dip_to_black_is_a_pause_not_an_offset(self):
        report = self.plan([4.0, 3.0], [None, 2.0], {"join": "j_cut"}, transitions=[{"type": "dip_to_black"}])[3]
        self.assertFalse(report[0]["applied"])

    def test_the_length_is_the_one_asked_for_within_limits(self):
        self.assertEqual(self.plan([4.0, 3.0], [None, 2.0], {"join": "j_cut", "seconds": 0.8})[0], [0.0, 0.8])
        self.assertEqual(media_compositor.sound_join_seconds({"join": "l_cut", "seconds": 9}), 1.5)

    def test_a_cut_with_no_offset_is_left_alone(self):
        self.assertEqual(self.plan([4.0, 3.0], [1.0, 1.0], None), ([0.0, 0.0], [0.0, 0.0], [0.0, 0.0], []))


class SoundJoinRenderTests(unittest.TestCase):
    # Real ffmpeg: where the voice stops or starts against where the picture changes.

    def setUp(self):
        self.ffmpeg = media_compositor._ffmpeg()
        if not self.ffmpeg:
            self.skipTest("ffmpeg unavailable")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_ffmpeg(self, *arguments):
        subprocess.run([self.ffmpeg, "-y", "-loglevel", "error", *arguments], check=True)

    def clip(self, name, colour, seconds):
        path = self.root / name
        self.run_ffmpeg("-f", "lavfi", "-i", f"color={colour}:s=160x284:d={seconds}:r=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))
        return path

    def voice(self, name, seconds):
        path = self.root / name
        self.run_ffmpeg("-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path))
        return str(path)

    def compose(self, clips, voices, join):
        sources = {f"http://clips.test/{path.name}": path for path in clips}
        report = []

        def fetch(url, target):
            shutil.copyfile(sources[url], target)
            return True

        with patch.object(media_compositor, "MEDIA_DIR", str(self.root)), patch.object(media_compositor, "_download", side_effect=fetch):
            url = media_compositor.compose_film(
                list(sources), ["", ""], None, tag="join", title=None, bgm=False, shot_voices=voices,
                transition_plans=[{"type": "match_cut", "duration": 0.08}], sound_joins=[join], sound_report=report,
            )
        self.assertTrue(url)
        return self.root / url.rsplit("/", 1)[-1], report

    def colour_at(self, film, seconds):
        frame = self.root / "frame.png"
        self.run_ffmpeg("-ss", f"{seconds}", "-i", str(film), "-frames:v", "1", str(frame))
        with Image.open(frame) as picture:
            red, _, blue = picture.convert("RGB").getpixel((80, 142))
        return "red" if red > blue else "blue"

    def silence_marks(self, film):
        output = subprocess.run(
            [self.ffmpeg, "-i", str(film), "-af", "silencedetect=noise=-40dB:d=0.1", "-f", "null", "-"],
            capture_output=True, text=True, check=True,
        ).stderr
        return [float(value) for value in re.findall(r"silence_end: ([0-9.]+)", output)]

    def test_an_l_cut_keeps_the_line_going_over_the_next_picture(self):
        film, report = self.compose(
            [self.clip("a.mp4", "red", 3), self.clip("b.mp4", "blue", 3)], [self.voice("a.wav", 2.6), None], {"join": "l_cut"},
        )
        self.assertTrue(report[0]["applied"], report)
        # The picture leaves at about 2.1s; the line it belongs to ends at about 2.6s.
        self.assertEqual(self.colour_at(film, 1.8), "red")
        self.assertEqual(self.colour_at(film, 2.4), "blue")
        # Nothing else is on the track, so it ends where the line does.
        sound = self.root / "sound.wav"
        self.run_ffmpeg("-i", str(film), "-vn", str(sound))
        self.assertAlmostEqual(media_compositor._probe_duration(str(sound)), 2.6, delta=0.25)

    def test_a_j_cut_is_heard_before_the_picture_arrives(self):
        film, report = self.compose(
            [self.clip("a.mp4", "red", 3), self.clip("b.mp4", "blue", 3)], [None, self.voice("b.wav", 1.5)], {"join": "j_cut", "seconds": 0.5},
        )
        self.assertTrue(report[0]["applied"], report)
        # The next picture arrives at about 2.9s; its line starts half a second sooner.
        self.assertEqual(self.colour_at(film, 2.7), "red")
        self.assertEqual(self.colour_at(film, 3.1), "blue")
        ends = self.silence_marks(film)
        self.assertTrue(ends, "there should be silence before the line")
        self.assertAlmostEqual(ends[0], 2.42, delta=0.25)

    def test_without_an_offset_the_picture_is_not_touched(self):
        film, report = self.compose(
            [self.clip("a.mp4", "red", 3), self.clip("b.mp4", "blue", 3)], [self.voice("a.wav", 2.6), None], None,
        )
        self.assertEqual(report, [])
        self.assertEqual(self.colour_at(film, 2.7), "red")


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

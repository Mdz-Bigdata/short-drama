"""Subtitles of a clip that keeps the video model's own voices follow what the clip says, and when.

Before, a native-sound clip's lines were spread across the clip by reading speed, so 「剑不挑人，挑输赢。」
could sit on screen while nobody spoke, or while someone said something else. Now stage 6 reads each such
clip's sound (a word-timed transcript when speech recognition is configured, the clip's voice activity
otherwise) and the film shows each line while it is spoken. No model is called here: transcripts are
written by hand and the clips are made with ffmpeg.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import edit_timeline, media_compositor, spoken_cues

FFMPEG = shutil.which("ffmpeg")
LINE = "杂役，也配大比？ 扫帚还我。 剑不挑人，挑输赢。"


def word(text, start, end, speaker="speaker_0"):
    return {"text": text, "start": start, "end": end, "type": "word", "speaker_id": speaker}


class TranscriptTest(unittest.TestCase):
    def test_each_line_shows_while_it_is_spoken_and_an_unsaid_line_not_at_all(self):
        words = [word("杂役", 2.0, 2.4), word("也配", 2.5, 2.8), word("大比？", 2.8, 3.3),
                 word("剑不挑人", 8.1, 8.9), word("挑输赢。", 9.0, 9.7)]
        cues = spoken_cues.from_transcript(LINE, words, 13.0)
        self.assertEqual([cue["text"] for cue in cues], ["杂役，也配大比？", "剑不挑人，挑输赢。"])
        self.assertLessEqual(cues[0]["start"], 2.0)
        self.assertGreaterEqual(cues[0]["end"], 3.3)
        self.assertLess(cues[0]["end"], 8.1, "the first line is gone before the next is spoken")
        self.assertTrue(7.9 <= cues[1]["start"] <= 8.1)

    def test_the_scripts_wording_is_kept_where_the_speech_says_it_and_an_ad_lib_is_shown_as_heard(self):
        # Recognition heard 扫州 for 扫帚 and a line that is not in the script.
        words = [word("杂役也配大比扫州还我", 1.0, 3.6), word("剑不挑人", 6.0, 6.8), word("挑输赢", 7.6, 8.3),
                 word("滚开", 11.0, 11.5, "speaker_1")]
        cues = spoken_cues.from_transcript(LINE, words, 13.0)
        self.assertEqual([cue["text"] for cue in cues], ["杂役，也配大比？", "扫帚还我。", "剑不挑人，挑输赢。", "滚开"])
        # Two lines said in one breath share that breath; a line said with a pause in it is one subtitle.
        self.assertAlmostEqual(cues[1]["start"], cues[0]["end"], places=2)
        self.assertLessEqual(cues[2]["start"], 6.0)
        self.assertGreaterEqual(cues[2]["end"], 8.3)

    def test_cues_never_overlap_and_stay_inside_the_clip(self):
        words = [word("杂役也配大比", 0.0, 0.5), word("扫帚还我", 0.6, 0.9), word("剑不挑人挑输赢", 1.0, 2.9)]
        cues = spoken_cues.from_transcript(LINE, words, 3.0)
        for before, after in zip(cues, cues[1:]):
            self.assertLessEqual(before["end"], after["start"])
        self.assertLessEqual(cues[-1]["end"], 3.0)
        self.assertGreaterEqual(cues[0]["start"], 0.0)


class RecognitionFailureTest(unittest.TestCase):
    def test_a_failed_transcription_is_booked_and_falls_back_instead_of_raising(self):
        booked = []
        with patch.object(spoken_cues, "recognition_available", return_value=True), \
                patch("app.core.providers.elevenlabs.ElevenLabsClient", side_effect=RuntimeError("no key")), \
                patch.object(spoken_cues.subprocess, "run"), \
                patch.object(spoken_cues.usage_ledger, "record", side_effect=lambda *a, **k: booked.append(k["status"])):
            self.assertIsNone(spoken_cues.transcribe("clip.mp4", "ffmpeg"))
        self.assertEqual(booked, ["failed"])


class VoiceActivityTest(unittest.TestCase):
    def test_lines_go_onto_the_stretches_where_someone_speaks(self):
        cues = spoken_cues.from_voice(LINE, [(1.9, 3.4), (5.0, 6.0), (8.0, 9.8)], 13.0)
        self.assertEqual([round(cue["start"], 1) for cue in cues], [1.8, 4.9, 7.9])
        self.assertTrue(all(cue["end"] <= 13.0 for cue in cues))

    def test_more_lines_than_stretches_are_spread_over_the_speaking_time_only(self):
        cues = spoken_cues.from_voice(LINE, [(2.0, 6.0), (9.0, 11.0)], 13.0)
        self.assertEqual(len(cues), 3)
        for cue in cues:
            self.assertFalse(6.5 < cue["start"] < 8.9, f"no line starts in the silence: {cue}")

    def test_a_trim_moves_the_cues_and_drops_what_it_cuts_away(self):
        cues = [{"text": "一", "start": 0.5, "end": 1.5}, {"text": "二", "start": 3.0, "end": 4.0}, {"text": "三", "start": 8.0, "end": 9.0}]
        self.assertEqual(spoken_cues.trimmed(cues, 2.0, 6.0), [("二", 1.0, 2.0)])


class TimelineTest(unittest.TestCase):
    def task(self, cues_url="http://x/clip.mp4"):
        shot = {"shot_id": 1, "scene_id": "E1S07", "video_url": "http://x/clip.mp4", "duration": 13, "dialogue": "聂昭：杂役，也配大比？ 石砚：扫帚还我。"}
        record = {"video_url": cues_url, "source": "transcript", "cues": [{"text": "杂役，也配大比？", "start": 1.9, "end": 3.6}]}
        return {"assets": {"5": [shot], "6": {"native_audio_shots": [True], "native_cues": [record], "shot_voices": [None]}}}

    def test_a_native_clip_hands_its_heard_cues_to_the_compositor(self):
        plan = edit_timeline.render_plan(edit_timeline.build(self.task()))
        self.assertEqual(plan["subtitle_timings"], [[{"text": "杂役，也配大比？", "start": 1.9, "end": 3.6}]])

    def test_stale_cues_an_edited_subtitle_or_a_dub_fall_back_to_the_estimate(self):
        self.assertEqual(edit_timeline.render_plan(edit_timeline.build(self.task("http://x/old.mp4")))["subtitle_timings"], [None])
        timeline = edit_timeline.set_subtitle(edit_timeline.build(self.task()), 1, "我自己写的字幕")
        self.assertEqual(edit_timeline.render_plan(timeline)["subtitle_timings"], [None])
        dubbed = self.task()
        dubbed["assets"]["6"]["native_audio_shots"] = [False]
        dubbed["assets"]["5"][0]["native_audio"] = False
        self.assertEqual(edit_timeline.render_plan(edit_timeline.build(dubbed))["subtitle_timings"], [None])

    def test_new_sound_brings_new_cues(self):
        task = self.task()
        timeline = edit_timeline.build(task)
        task["assets"]["6"]["native_cues"][0]["cues"] = [{"text": "扫帚还我。", "start": 5.0, "end": 6.0}]
        self.assertEqual(edit_timeline.with_new_sound(timeline, task)["clips"][0]["spoken_cues"]["cues"][0]["start"], 5.0)


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class RealClipTest(unittest.TestCase):
    """A 6-second clip that is silent except for a voice-band tone from 3 s to 5 s."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "media"
        self.media.mkdir()
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(self.media))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clip = self.media / "clip.mp4"
        subprocess.run([
            FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=400:duration=6",
            "-filter_complex", "[1:a]volume=enable='not(between(t,3,5))':volume=0[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(self.clip),
        ], check=True)

    def test_voice_activity_finds_the_spoken_stretch(self):
        spans = spoken_cues.voice_spans(str(self.clip), FFMPEG)
        self.assertEqual(len(spans), 1, spans)
        self.assertAlmostEqual(spans[0][0], 3.0, delta=0.15)
        self.assertAlmostEqual(spans[0][1], 5.0, delta=0.15)

    def test_without_recognition_the_line_is_timed_from_the_clips_voice(self):
        found = spoken_cues.for_clip(str(self.clip), "剑不挑人，挑输赢。", ffmpeg=FFMPEG, video_url="u", duration=6.0,
                                     listen=lambda *args, **kwargs: None)
        self.assertEqual(found["source"], "voice")
        self.assertAlmostEqual(found["cues"][0]["start"], 2.9, delta=0.2)

    def test_the_film_shows_the_line_only_while_it_is_spoken(self):
        commands = []
        real_run = subprocess.run

        def recording(cmd, *args, **kwargs):
            commands.append(" ".join(map(str, cmd)) if isinstance(cmd, (list, tuple)) else str(cmd))
            return real_run(cmd, *args, **kwargs)

        with patch.object(media_compositor.subprocess, "run", side_effect=recording):
            url = media_compositor.compose_film(
                [media_compositor.public_url("clip.mp4")], ["剑不挑人，挑输赢。"], None, tag="heard_cues", title=None, bgm=False,
                native_audio=[True], subtitle_timings=[[{"text": "剑不挑人，挑输赢。", "start": 2.9, "end": 5.35}]],
            )
        self.assertTrue(url and os.path.exists(media_compositor.local_media_path(url)))
        self.assertTrue(any("between(t,2.900,5.350)" in command for command in commands), "the single line is windowed to its speech")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""分镜写的「一帧黑」由剪辑做：发给视频模型前去掉那句，合成时在撞击那一下盖几帧黑。

也测「接上一段」：出品人标了的一镜跨场也接上一段的尾帧(重出姿态跳了的片段时用)。
"""

import array
import math
import os
import shutil
import subprocess
import tempfile
import unittest

from app.core import blackout, edit_timeline
from app.core import clip_route as cr
from app.core.clip_route import ClipFacts as C

STRIKE = "刀身砸在厚背刀中段的暗痕上。接触瞬间画面骤黑一帧。再亮时同一机位同一光向：半截刀尖扎进泥水里斜立。"


def _tone(seconds, rate=blackout.SAMPLE_RATE, *, level=200, burst_at=None, burst=12000, speech=()):
    """低底噪，``burst_at`` 秒处一下撞击声，``speech`` 里每段 (起, 止) 是中等响度的说话声。"""
    samples = array.array("h")
    for index in range(int(seconds * rate)):
        t = index / rate
        value = level * math.sin(2 * math.pi * 220 * t)
        if any(start <= t < end for start, end in speech):
            value = 3000 * math.sin(2 * math.pi * 180 * t)
        if burst_at is not None and burst_at <= t < burst_at + 0.15:
            value = burst * math.sin(2 * math.pi * 90 * t)
        samples.append(int(value))
    return samples


class PromptTests(unittest.TestCase):
    def test_the_black_frame_sentence_is_left_to_the_edit(self):
        self.assertTrue(blackout.asked(STRIKE))
        sent = blackout.for_video(STRIKE)
        self.assertNotIn("骤黑", sent)
        self.assertNotIn("再亮", sent)
        self.assertIn("刀身砸在厚背刀中段的暗痕上。", sent)
        self.assertIn("随后同一机位同一光向：半截刀尖扎进泥水里斜立。", sent)

    def test_text_without_it_is_untouched(self):
        for text in ("沈磨推刀。", "片尾黑屏。", "灯灭，再亮起时人已不见。"):
            self.assertFalse(blackout.asked(text))
            self.assertEqual(blackout.for_video(text), text)


class OnsetTests(unittest.TestCase):
    def test_the_strike_is_found_even_after_quieter_speech(self):
        samples = _tone(10, burst_at=4.5, speech=((1.0, 2.5), (8.2, 9.2)))
        self.assertAlmostEqual(blackout.onset(samples), 4.5, delta=0.05)

    def test_no_sudden_sound_means_no_time(self):
        self.assertIsNone(blackout.onset(_tone(6)))

    def test_the_edges_are_skipped(self):
        self.assertIsNone(blackout.onset(_tone(6, burst_at=0.1)))

    def test_the_plan_says_why_when_nothing_is_found(self):
        mark = blackout.plan(STRIKE, None)
        self.assertIsNone(mark["at"])
        self.assertTrue(mark["reason"])
        self.assertIsNone(blackout.plan("沈磨推刀。", None), "not asked: no plan at all")

    def test_the_window_follows_the_trim(self):
        self.assertEqual(blackout.window({"at": 4.5, "frames": 2}, fps=24), (4.5, 4.583))
        self.assertEqual(blackout.window({"at": 4.5, "frames": 2}, trim_start=1.5, fps=24), (3.0, 3.083))
        self.assertIsNone(blackout.window({"at": 1.0, "frames": 2}, trim_start=1.5), "trimmed away")
        self.assertIsNone(blackout.window({"at": None, "frames": 2}))
        self.assertIsNone(blackout.window(None))


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class FileTests(unittest.TestCase):
    def test_a_real_file_is_read_through_ffmpeg(self):
        with tempfile.TemporaryDirectory() as folder:
            wav = os.path.join(folder, "strike.wav")
            raw = os.path.join(folder, "strike.raw")
            with open(raw, "wb") as handle:
                handle.write(_tone(8, burst_at=3.2, speech=((0.8, 2.0),)).tobytes())
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(blackout.SAMPLE_RATE), "-ac", "1", "-i", raw, wav], check=True)
            self.assertAlmostEqual(blackout.onset_in_file(wav), 3.2, delta=0.05)
            self.assertEqual(blackout.plan(STRIKE, wav)["source"], "sound_onset")


class TimelineTests(unittest.TestCase):
    def test_the_mark_travels_from_the_clip_to_the_render_plan(self):
        task = {"assets": {"5": [
            {"shot_id": 1, "scene_id": "E1S06", "video_url": "http://localhost:8000/media/a.mp4", "duration": 10, "contract_fingerprint": "a"},
            {"shot_id": 1, "scene_id": "E1S07", "video_url": "http://localhost:8000/media/b.mp4", "duration": 12, "contract_fingerprint": "b",
             "blackout": {"at": 4.52, "frames": 2, "source": "sound_onset"}},
        ], "6": {}}}
        plan = edit_timeline.render_plan(edit_timeline.build(task))
        self.assertEqual(plan["blackouts"], [None, {"at": 4.52, "frames": 2, "source": "sound_onset"}])


class OwnSoundTests(unittest.TestCase):
    def test_without_a_stage_six_record_a_clip_with_sound_keeps_it(self):
        task = {"assets": {"5": [
            {"shot_id": 1, "scene_id": "E1S01", "video_url": "http://localhost:8000/media/a.mp4", "duration": 10, "native_audio": True},
            {"shot_id": 1, "scene_id": "E1S02", "video_url": "http://localhost:8000/media/b.mp4", "duration": 10, "native_audio": False},
        ], "6": {}}}
        timeline = edit_timeline.build(task)
        self.assertEqual([clip["audio_source"] for clip in timeline["clips"]], ["native", "none"])
        self.assertEqual(edit_timeline.render_plan(timeline)["native_audio"], [True, False])

    def test_a_stage_six_record_still_decides(self):
        task = {"assets": {"5": [
            {"shot_id": 1, "scene_id": "E1S01", "video_url": "http://localhost:8000/media/a.mp4", "duration": 10, "native_audio": True},
        ], "6": {"native_audio_shots": [False], "shot_voices": ["/tmp/v.mp3"]}}}
        self.assertEqual(edit_timeline.build(task)["clips"][0]["audio_source"], "tts")


class FollowPreviousTests(unittest.TestCase):
    def test_a_marked_clip_chains_across_a_scene_change(self):
        routes = cr.route_clips(
            [C(1, "E1S05", characters=("沈磨",), storyboards=1, subject_refs=True),
             C(2, "E1S06", characters=("沈磨",), storyboards=1, subject_refs=True, follows_previous=True),
             C(3, "E1S07", characters=("沈磨",), storyboards=1, subject_refs=True)],
            ("text", "first_frame", "first_last_frame", "multi_reference", "multimodal"),
        )
        self.assertEqual((routes[2].kind, routes[2].chain_from), (cr.TAILFRAME, 1))
        self.assertIsNone(routes[3].chain_from, "an unmarked new scene still starts on its own")

    def test_it_chains_even_when_scene_chaining_is_off(self):
        routes = cr.route_clips(
            [C(1, "E1S05", storyboards=1), C(2, "E1S06", storyboards=1, follows_previous=True)],
            ("text", "first_frame", "multi_reference"), scene_chain=False,
        )
        self.assertEqual(routes[2].chain_from, 1)


if __name__ == "__main__":
    unittest.main()

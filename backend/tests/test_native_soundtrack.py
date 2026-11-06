# -*- coding: utf-8 -*-
"""MiniMax H3 clips keep the sound the model made: no dubbing over it, from the clip to the finished film."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import edit_timeline, media_compositor
from app.core.video_references import uses_native_soundtrack
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from tests import test_stage_five_queue as queue_tests

FFMPEG = shutil.which("ffmpeg")


def _clip(path, seconds=4, tone=440, audio=True):
    command = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x568:rate=24:duration={seconds}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency={tone}:duration={seconds}", "-c:a", "aac"]
    subprocess.run([*command, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def _audio_seconds(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out) if out and out != "N/A" else 0.0


class ChoiceTest(unittest.TestCase):
    def test_h3_keeps_its_sound_and_a_project_can_go_back_to_dubbing(self):
        self.assertTrue(uses_native_soundtrack({"video_model": "MiniMax-H3"}))
        self.assertFalse(uses_native_soundtrack({"video_model": "MiniMax-H3", "native_audio": False}))

    def test_a_host_that_turned_h3_sound_off_is_dubbed(self):
        with patch.dict(os.environ, {"MINIMAX_H3_NATIVE_AUDIO": "0"}):
            self.assertFalse(uses_native_soundtrack({"video_model": "MiniMax-H3"}))

    def test_other_models_stay_as_they_were(self):
        for model in ("seedance2.0", "seedance-1-0", "kling3", ""):
            self.assertFalse(uses_native_soundtrack({"video_model": model}), model)


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class CompositionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name)
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(self.media))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _film(self, urls, **kwargs):
        result = media_compositor.compose_film(urls, [""] * len(urls), None, tag="film", title=None, bgm=False, **kwargs)
        self.assertTrue(result)
        return self.media / result.rsplit("/", 1)[-1]

    def test_a_clip_keeps_its_own_sound_for_its_whole_length(self):
        _clip(self.media / "a.mp4")
        film = self._film([media_compositor.public_url("a.mp4")], native_audio=[True])
        self.assertAlmostEqual(_audio_seconds(film), 4, delta=0.3)

    def test_without_the_flag_the_clips_sound_is_dropped_as_before(self):
        _clip(self.media / "a.mp4")
        film = self._film([media_compositor.public_url("a.mp4")])
        self.assertEqual(_audio_seconds(film), 0.0)

    def test_music_stays_audible_under_sound_that_never_goes_quiet(self):
        dubbed, native = [], []
        media_compositor._append_master_mix_filters(dubbed, ["[v]"], "[b]", None)
        media_compositor._append_master_mix_filters(native, ["[v]"], "[b]", None, voices_carry_ambience=True)
        self.assertIn("threshold=0.04:ratio=8", ";".join(dubbed))
        self.assertIn("threshold=0.25:ratio=3", ";".join(native))

    def test_a_trim_takes_the_same_part_of_the_sound_as_of_the_picture(self):
        _clip(self.media / "a.mp4")
        with tempfile.TemporaryDirectory() as work:
            track = media_compositor._clip_sound(FFMPEG, str(self.media / "a.mp4"), (1.0, 3.0), os.path.join(work, "t.m4a"))
            self.assertAlmostEqual(_audio_seconds(track), 2, delta=0.2)

    def test_a_clip_with_no_sound_is_not_an_error(self):
        _clip(self.media / "silent.mp4", audio=False)
        with tempfile.TemporaryDirectory() as work:
            self.assertIsNone(media_compositor._clip_sound(FFMPEG, str(self.media / "silent.mp4"), None, os.path.join(work, "t.m4a")))
        self.assertTrue(self._film([media_compositor.public_url("silent.mp4")], native_audio=[True]).exists())

    def test_keeping_a_clip_makes_a_local_copy_and_never_loses_the_link(self):
        _clip(self.media / "a.mp4")
        local = media_compositor.public_url("a.mp4")
        self.assertEqual(media_compositor.keep_clip(local), local, "already ours")
        with patch.object(media_compositor, "_download", return_value=False):
            self.assertEqual(media_compositor.keep_clip("https://cdn/x.mp4"), "https://cdn/x.mp4")
        with patch.object(media_compositor, "_download", return_value=True):
            self.assertTrue(media_compositor.keep_clip("https://cdn/x.mp4", tag="shotav").endswith(".mp4"))
        self.assertIsNone(media_compositor.keep_clip(None))


class TimelineTest(unittest.TestCase):
    def _task(self, native):
        return {"assets": {
            "5": [{"shot_id": 1, "video_url": "http://x/1.mp4", "duration": "8"}, {"shot_id": 2, "video_url": "http://x/2.mp4", "duration": "8"}],
            "6": {"shot_voices": [None, None], "native_audio_shots": native},
        }}

    def test_the_plan_carries_it_and_a_muted_clip_stays_silent(self):
        timeline = edit_timeline.build(self._task([True, True]))
        self.assertEqual(edit_timeline.render_plan(timeline)["native_audio"], [True, True])
        timeline["clips"][1]["muted"] = True
        self.assertEqual(edit_timeline.render_plan(timeline)["native_audio"], [True, False])

    def test_a_project_from_before_reads_as_dubbed(self):
        task = self._task([])
        del task["assets"]["6"]["native_audio_shots"]
        self.assertEqual(edit_timeline.render_plan(edit_timeline.build(task))["native_audio"], [False, False])


class StageFiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))

    def _h3_task(self):
        task = queue_tests._task(1)
        task["config"]["video_model"] = "MiniMax-H3"
        task["assets"]["4"][0]["dialogue"] = "沈砚：朕的江山。"
        return task

    def _run(self, task):
        """Stage 5 with every provider stubbed; returns the first clip and the three sound calls."""
        self.service.repo.save_task(task["task_id"], task)
        with patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)) as dub, \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url) as attach, \
             patch("app.service.drama_service.media_compositor.keep_clip", side_effect=lambda url, **k: url.replace("cdn", "kept")) as keep, \
             patch.object(self.service.gateway, "call_llm", return_value="沈砚抬眼，低声说：朕的江山。"), \
             patch.object(self.service.gateway, "_http_chat", side_effect=AssertionError("no real model in this test")), \
             patch.object(self.service.gateway, "generate_video", return_value="https://cdn/1.mp4"), \
             patch.object(self.service.gateway, "generate_image", return_value=("https://cdn/frame.png", {})), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        return self.service.repo.get_task(task["task_id"])["assets"]["5"][0], dub, attach, keep

    def test_h3_keeps_the_clip_and_never_dubs(self):
        clip, dub, attach, keep = self._run(self._h3_task())
        dub.assert_not_called()
        attach.assert_not_called()
        keep.assert_called_once()
        self.assertEqual(clip["video_url"], "https://kept/1.mp4")
        self.assertFalse(clip.get("voice_path"))

    def test_a_project_that_opted_out_is_dubbed_as_before(self):
        task = self._h3_task()
        task["config"]["native_audio"] = False
        _clip_out, _dub, attach, keep = self._run(task)
        keep.assert_not_called()
        attach.assert_called_once()


class StageSixTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))

    def _run(self, config, clips):
        task = queue_tests._task(len(clips))
        task["config"].update(config)
        task["current_stage"] = 5
        task["stage_progress"] = {"stage": 6, "status": "running", "calls": []}
        task["assets"]["5"] = clips
        self.service.repo.save_task(task["task_id"], task)
        with patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=("u", "/x/v.mp3")) as dub, \
             patch("app.service.drama_service.media_compositor.synthesize_elevenlabs_sfx", return_value=("s", "/x/s.mp3")) as sfx, \
             patch("app.service.drama_service.media_compositor.synthesize_elevenlabs_music", return_value=("b", "/x/b.mp3")), \
             patch.object(self.service.gateway, "call_llm", return_value="OK"), \
             patch.object(self.service.gateway, "_http_chat", side_effect=AssertionError("no real model in this test")), \
             patch.object(self.service.gateway, "generate_tts", return_value="https://cdn/tts.mp3") as tts, \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(task["task_id"], 6, _claimed_task=task)
        return self.service.repo.get_task(task["task_id"])["assets"]["6"], dub, sfx, tts

    def _clip(self, shot_id, **extra):
        return {"shot_id": shot_id, "video_url": f"https://kept/{shot_id}.mp4", "dialogue": "沈砚：朕的江山。", "duration": "8", **extra}

    def test_nothing_is_voiced_or_laid_over_a_clip_that_has_its_own_sound(self):
        audio, dub, sfx, tts = self._run({"video_model": "MiniMax-H3"}, [self._clip(1), self._clip(2)])
        self.assertEqual(audio["native_audio_shots"], [True, True])
        self.assertEqual(audio["shot_voices"], [None, None])
        dub.assert_not_called()
        tts.assert_not_called()
        sfx.assert_not_called()
        self.assertIn("视频原生声音 (2/2", audio["voice_profile"])

    def test_a_clip_that_was_already_dubbed_keeps_its_dub(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3") as voice:
            audio, dub, _sfx, _tts = self._run({"video_model": "MiniMax-H3"}, [self._clip(1, voice_path=voice.name), self._clip(2)])
            self.assertEqual(audio["native_audio_shots"], [False, True])
            self.assertEqual(audio["shot_voices"][1], None)
            self.assertTrue(audio["shot_voices"][0])
            dub.assert_not_called()

    def test_seedance_is_still_dubbed(self):
        audio, dub, _sfx, _tts = self._run({"video_model": "seedance2.0"}, [self._clip(1)])
        self.assertEqual(audio["native_audio_shots"], [False])
        dub.assert_called()


if __name__ == "__main__":
    unittest.main()

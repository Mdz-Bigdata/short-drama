# -*- coding: utf-8 -*-
"""剪辑合成师: one shot's voices from the model's own sound or a dub, the basic settings, music placement,
and what the page shows beside the timeline (tension, scene markers, music match, size, versions)."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import edit_timeline, media_compositor, post_production
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService

FFMPEG = shutil.which("ffmpeg")


def _task():
    return {
        "task_id": "post-1",
        "config": {"genre": "古装权谋", "title_suggestion": "雪夜", "tts_model": "macos-say"},
        "assets": {
            "5": [
                {"shot_id": 1, "shot_uid": 1, "scene_id": "S1", "video_url": "http://x/1.mp4", "duration": "4",
                 "dialogue": "沈砚：朕的江山。", "desc": "沈砚冷笑，拔刀逼近", "native_audio": True, "image_url": "/media/f1.png"},
                {"shot_id": 2, "shot_uid": 2, "scene_id": "S1", "video_url": "http://x/2.mp4", "duration": "4",
                 "dialogue": "苏晚：你敢？", "desc": "苏晚后退", "native_audio": False, "draft_resolution": "480p"},
                {"shot_id": 1, "shot_uid": 3, "scene_id": "S2", "video_url": "http://x/3.mp4", "duration": "4",
                 "dialogue": "", "desc": "雪落庭院", "native_audio": True},
            ],
            "6": {"shot_voices": [None, "/tmp/v2.mp3", None], "native_audio_shots": [True, False, True],
                  "bgm_path": "/tmp/bgm.mp3", "bgm_url": "/media/bgm.mp3"},
        },
    }


class AudioSourceTest(unittest.TestCase):
    def test_each_clip_starts_from_what_stage_six_chose(self):
        timeline = edit_timeline.build(_task())
        self.assertEqual([edit_timeline.audio_source(c) for c in timeline["clips"]], ["native", "tts", "native"])
        self.assertEqual([c["native_available"] for c in timeline["clips"]], [True, False, True])
        plan = edit_timeline.render_plan(timeline)
        self.assertEqual(plan["native_audio"], [True, False, True])
        self.assertEqual(plan["shot_voices"], [None, "/tmp/v2.mp3", None])

    def test_a_shot_can_go_to_a_dub_or_to_silence(self):
        timeline = edit_timeline.build(_task())
        timeline = edit_timeline.set_audio_source(timeline, None, "tts", shot_uid=1)
        timeline = edit_timeline.set_audio_source(timeline, None, "none", shot_uid=3)
        plan = edit_timeline.render_plan(timeline)
        self.assertEqual(plan["native_audio"], [False, False, False])
        self.assertEqual([c["shot_uid"] for c in edit_timeline.needs_voice(timeline)], [1], "shot 1 has no dub yet")

    def test_a_clip_without_its_own_sound_cannot_use_it(self):
        with self.assertRaises(edit_timeline.TimelineError):
            edit_timeline.set_audio_source(edit_timeline.build(_task()), None, "native", shot_uid=2)

    def test_a_timeline_from_before_reads_its_old_flags(self):
        timeline = edit_timeline.build(_task())
        for clip in timeline["clips"]:
            clip.pop("audio_source")
        self.assertEqual(edit_timeline.render_plan(timeline)["native_audio"], [True, False, True])

    def test_a_refresh_keeps_the_editors_choice(self):
        timeline = edit_timeline.set_audio_source(edit_timeline.build(_task()), None, "tts", shot_uid=1)
        task = _task()
        task["assets"]["5"][2]["video_url"] = "http://x/3b.mp4"
        refreshed = edit_timeline.refresh(timeline, task)
        self.assertEqual(edit_timeline.audio_source(refreshed["clips"][0]), "tts")


class SettingsTest(unittest.TestCase):
    def test_all_on_by_default(self):
        self.assertEqual(edit_timeline.settings_of(edit_timeline.build(_task(), title="雪夜")),
                         {"transitions": True, "dialogue": True, "subtitles": True, "title_card": True, "name_cards": True})

    def test_each_switch_reaches_the_render(self):
        timeline = edit_timeline.build(_task(), title="雪夜")
        timeline = edit_timeline.set_settings(timeline, {"transitions": False, "dialogue": False, "subtitles": False, "title_card": False})
        plan = edit_timeline.render_plan(timeline)
        self.assertTrue(all(spec["type"] == "hard_cut" for spec in plan["transition_plans"]))
        self.assertEqual(plan["native_audio"], [False, False, False])
        self.assertEqual(plan["shot_voices"], [None, None, None])
        self.assertEqual(plan["subtitles"], ["", "", ""])
        self.assertIsNone(plan["title"])
        self.assertFalse(plan["fade_edges"])

    def test_an_unknown_switch_is_refused(self):
        with self.assertRaises(edit_timeline.TimelineError):
            edit_timeline.set_settings(edit_timeline.build(_task()), {"colour": True})

    def test_music_placement_stays_inside_the_film(self):
        timeline = edit_timeline.build(_task())
        self.assertEqual(edit_timeline.set_bgm(timeline, source="generated", path="/tmp/bgm.mp3", start=5)["bgm"]["start"], 5)
        self.assertEqual(edit_timeline.set_bgm(timeline, source="generated", path="/tmp/bgm.mp3", start=999)["bgm"]["start"], 12)
        self.assertEqual(edit_timeline.render_plan(edit_timeline.set_bgm(timeline, source="generated", path="/tmp/b.mp3", start=3))["bgm_start"], 3)


class NewSoundTest(unittest.TestCase):
    def test_new_sound_replaces_voices_and_keeps_the_edits(self):
        timeline = edit_timeline.build(_task())
        timeline = edit_timeline.trim(timeline, None, start=1, end=3, shot_uid=2)
        timeline = edit_timeline.set_audio_source(timeline, None, "none", shot_uid=3)
        task = _task()
        task["assets"]["6"]["shot_voices"] = [None, "/tmp/v2-new.mp3", None]
        task["assets"]["6"]["bgm_path"] = "/tmp/bgm-new.mp3"
        renewed = edit_timeline.with_new_sound(timeline, task)
        self.assertEqual(renewed["clips"][1]["voice_path"], "/tmp/v2-new.mp3")
        self.assertEqual((renewed["clips"][1]["in"], renewed["clips"][1]["out"]), (1.0, 3.0))
        self.assertEqual(edit_timeline.audio_source(renewed["clips"][2]), "none")
        self.assertEqual(renewed["bgm"]["path"], "/tmp/bgm-new.mp3")
        self.assertEqual(renewed["revision"], timeline["revision"])

    def test_music_picked_from_the_library_stays(self):
        timeline = edit_timeline.set_bgm(edit_timeline.build(_task()), source="library", path="/lib/a.mp3", library_id="a", name="A")
        self.assertEqual(edit_timeline.with_new_sound(timeline, _task())["bgm"]["library_id"], "a")


class ViewTest(unittest.TestCase):
    def test_tension_follows_the_running_time(self):
        timeline = edit_timeline.build(_task(), title="雪夜")
        order = post_production.running_order(timeline, _task())
        self.assertEqual([row["t"] for row in order], [2.6, 6.6, 10.6])
        self.assertGreater(order[0]["tension"], order[2]["tension"], "a drawn blade is tenser than falling snow")
        self.assertEqual(post_production.scene_markers(order), [{"scene_id": "S1", "t": 2.6}, {"scene_id": "S2", "t": 10.6}])

    def test_without_a_title_card_the_film_starts_at_zero(self):
        timeline = edit_timeline.set_settings(edit_timeline.build(_task(), title="雪夜"), {"title_card": False})
        self.assertEqual(post_production.running_order(timeline, _task())[0]["t"], 0.0)

    def test_music_that_fits_the_drama_ranks_first(self):
        tracks = [{"id": "a", "name": "轻快日常", "mood": "欢快"}, {"id": "b", "name": "宫墙暗涌", "mood": "古风 紧张"}, {"id": "c", "name": "无名"}]
        timeline = edit_timeline.build(_task())
        ranked = post_production.ranked_library(tracks, post_production.film_mood(_task(), post_production.running_order(timeline, _task())))
        self.assertEqual(ranked[0]["id"], "b")
        self.assertTrue(all(0 < row["match"] < 1 for row in ranked))
        self.assertIn("古风", ranked[0]["tags"])
        self.assertEqual(ranked[1]["tags"], ["轻快"], "only the moods a track's words name")
        self.assertNotIn("path", ranked[0])

    def test_the_view_carries_what_the_page_needs(self):
        view = post_production.view(_task(), edit_timeline.build(_task()), [])
        self.assertEqual(view["shots"][1], {"shot_uid": 2, "image_url": None, "draft": True, "audio_source": "tts", "native_available": False})
        self.assertGreater(view["estimated_bytes"], 0)
        self.assertEqual(view["film_versions"], [])
        task = _task()
        task["assets"]["5"][1]["draft_upscaled"] = True
        self.assertFalse(post_production.view(task, edit_timeline.build(task), [])["shots"][1]["draft"], "upscaled is HD enough")

    def test_per_episode_work_shows_that_episodes_versions(self):
        task = _task()
        task["assets"]["film_versions"] = [{"url": "/e1.mp4", "episode": 1}, {"url": "/e2.mp4", "episode": 2}, {"url": "/old.mp4"}]
        timeline = edit_timeline.build(task)
        self.assertEqual(len(post_production.view(task, timeline, [])["film_versions"]), 3)
        timeline["episode"] = 2
        self.assertEqual([v["url"] for v in post_production.view(task, timeline, [])["film_versions"]], ["/e2.mp4", "/old.mp4"])

    def test_versions_keep_the_newest_first_and_no_duplicates(self):
        assets: dict = {}
        timeline = edit_timeline.build(_task())
        for url in ("/media/a.mp4", "/media/b.mp4", "/media/a.mp4"):
            post_production.remember_film(assets, post_production.film_record(url, timeline=timeline, compose_mode="m", rendered_at=url))
        self.assertEqual([v["url"] for v in assets["film_versions"]], ["/media/a.mp4", "/media/b.mp4"])


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service.repo.save_task("post-1", _task())

    def test_operations_reach_the_timeline(self):
        self.service.edit_timeline("post-1", "audio_source", {"shot_uid": 1, "audio_source": "none"})
        self.service.edit_timeline("post-1", "settings", {"settings": {"subtitles": False}})
        result = self.service.edit_timeline("post-1", "bgm", {"bgm_start": 4})
        self.assertEqual(edit_timeline.audio_source(result["timeline"]["clips"][0]), "none")
        self.assertFalse(result["post"]["settings"]["subtitles"])
        self.assertEqual(result["timeline"]["bgm"]["start"], 4)
        self.assertEqual(result["timeline"]["bgm"]["source"], "generated", "placing the music keeps the track")
        self.assertIn("tension", result["post"])

    def test_the_chat_assistant_reaches_the_same_edits(self):
        from app.core.agent_tools import catalog

        admin = {"user_id": "x", "role": "admin"}
        voice = catalog.call("edit_timeline", {"task_id": "post-1", "operation": "audio_source", "shot_uid": 1, "audio_source": "none"},
                             service=self.service, user=admin)
        self.assertEqual(voice["result"]["summary"]["audio_sources"]["none"], 1)
        switch = catalog.call("edit_timeline", {"task_id": "post-1", "operation": "settings", "settings": {"title_card": False}},
                              service=self.service, user=admin)
        self.assertFalse(switch["result"]["settings"]["title_card"])
        placed = catalog.call("edit_timeline", {"task_id": "post-1", "operation": "bgm", "bgm_start": 3}, service=self.service, user=admin)
        self.assertEqual(placed["result"]["bgm"]["start"], 3)
        refused = catalog.call("edit_timeline", {"task_id": "post-1", "operation": "audio_source", "shot_uid": 2, "audio_source": "native"},
                               service=self.service, user=admin)
        self.assertFalse(refused["ok"])
        self.assertIn("没有原声", refused["error"])

    def test_an_earlier_music_version_can_go_back_on(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3") as old:
            task = self.service.repo.get_task("post-1")
            post_production.remember_music(task["assets"], url="/media/old.mp3", path=old.name, prompt="p", created_at="t")
            self.service.repo.save_task("post-1", task)
            result = self.service.edit_timeline("post-1", "bgm", {"source": "generated", "music_version": "/media/old.mp3"})
            self.assertEqual(result["timeline"]["bgm"]["path"], old.name)
        with self.assertRaises(edit_timeline.TimelineError):
            self.service.edit_timeline("post-1", "bgm", {"source": "generated", "music_version": "/media/none.mp3"})

    def test_a_shot_switched_to_a_dub_is_dubbed_before_the_render(self):
        self.service.edit_timeline("post-1", "audio_source", {"shot_uid": 1, "audio_source": "tts"})
        with patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=("u", "/tmp/v1.mp3")) as dub, \
             patch("app.service.drama_service.media_compositor.compose_film", return_value="/media/film.mp4") as compose:
            self.service.render_timeline("post-1")
        dub.assert_called_once()
        self.assertEqual(compose.call_args.kwargs["shot_voices"][0], "/tmp/v1.mp3")
        self.assertTrue(compose.call_args.kwargs["fade_edges"])
        task = self.service.repo.get_task("post-1")
        self.assertEqual(task["assets"]["film_versions"][0]["url"], "/media/film.mp4")


class MusicTest(unittest.TestCase):
    def test_the_prompt_comes_from_data(self):
        text = post_production.music_prompt("写实", "古装权谋")
        self.assertTrue(text.startswith("写实 古装权谋 short drama"))
        self.assertNotIn("{", text)
        self.assertIn("no speech", post_production.ambience_prompt())

    def test_versions_keep_the_newest_first_and_hide_the_server_path(self):
        assets: dict = {}
        for name in ("a", "b", "a"):
            post_production.remember_music(assets, url=f"/media/{name}.mp3", path=f"/srv/{name}.mp3", prompt="p", created_at=name)
        post_production.remember_music(assets, url=None, path=None, prompt=None, created_at="none")
        self.assertEqual([v["path"] for v in assets["music_versions"]], ["/srv/a.mp3", "/srv/b.mp3"])
        listed = post_production.view({"assets": assets}, edit_timeline.build(_task()), [])["music_versions"]
        self.assertEqual([v["url"] for v in listed], ["/media/a.mp3", "/media/b.mp3"])
        self.assertTrue(all("path" not in v for v in listed))

    def test_dubs_duck_the_music_hard_and_native_sound_gently(self):
        filters: list = []
        out = media_compositor._append_master_mix_filters(filters, ["[v1]", "[v2]"], "[bgm]", None, voices_carry_ambience=True, native_labels=["[v2]"])
        graph = ";".join(filters)
        self.assertIn("[bgm][dubkey]sidechaincompress=threshold=0.04:ratio=8", graph)
        self.assertIn("[bgmdub][natkey]sidechaincompress=threshold=0.25:ratio=3", graph)
        self.assertEqual(out, "[aout]")
        # One kind only: the single setting, as before.
        single: list = []
        media_compositor._append_master_mix_filters(single, ["[v1]"], "[bgm]", None, native_labels=[])
        self.assertNotIn("bgmdub", ";".join(single))

    def test_music_comes_whenever_elevenlabs_is_the_audio_provider(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        service = DramaService()
        service.repo = TaskRepository(str(Path(temp.name) / "tasks.json"))
        from tests import test_stage_five_queue as queue_tests
        task = queue_tests._task(1)
        task["config"].update({"tts_model": "speech-2.6-hd", "video_model": "seedance2.0"})
        task["current_stage"] = 5
        task["stage_progress"] = {"stage": 6, "status": "running", "calls": []}
        task["assets"]["5"] = [{"shot_id": 1, "video_url": "https://kept/1.mp4", "dialogue": "", "duration": "8"}]
        service.repo.save_task(task["task_id"], task)
        with patch("app.service.drama_service.media_compositor.effective_audio_model", return_value=("elevenlabs", "eleven_v3")), \
             patch("app.service.drama_service.media_compositor.synthesize_elevenlabs_music", return_value=("/media/m.mp3", "/srv/m.mp3")) as music, \
             patch("app.service.drama_service.media_compositor.synthesize_elevenlabs_sfx", return_value=(None, None)), \
             patch.object(service.gateway, "call_llm", return_value="OK"), \
             patch.object(service.gateway, "_http_chat", side_effect=AssertionError("no real model in this test")), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            service._execute_stage_blocking(task["task_id"], 6, _claimed_task=task)
        music.assert_called_once()
        saved = service.repo.get_task(task["task_id"])["assets"]
        self.assertEqual(saved["music_versions"][0]["path"], "/srv/m.mp3")
        self.assertIn("short drama cinematic score", saved["6"]["music_prompt"])


class ChainTest(unittest.TestCase):
    """继续 to stage 6 makes the sound and the film in one run: 剪辑合成师 does both."""

    def _run(self, *, next_stage=7, status="idle", automatic=False):
        import asyncio
        service = DramaService()
        ran = []
        claimed = {"workflow_control": {"run_id": "r1"}}
        with patch.object(DramaService, "_execute_claimed_stage_blocking", lambda _s, _t, stage, _c: ran.append(stage) or {"stage": stage}), \
             patch.object(DramaService, "_claim_stage_task", lambda _s, _t, stage, **_k: {**claimed, "current_stage": stage}), \
             patch.object(DramaService, "_finish_workflow_run", lambda *_a: None), \
             patch.object(DramaService, "workflow_snapshot", lambda _s, _t: {"next_stage": next_stage}), \
             patch.object(service.repo, "get_task", return_value={"status": status, "workflow_control": {}}):
            result = asyncio.run(service.execute_stage("t", 6, _claimed_task=claimed, _automatic=automatic))
        return ran, result

    def test_stage_seven_follows_stage_six(self):
        ran, result = self._run()
        self.assertEqual(ran, [6, 7])
        self.assertEqual(result, {"stage": 7})

    def test_it_stops_when_the_sound_fell_short_or_the_run_was_paused(self):
        self.assertEqual(self._run(next_stage=6)[0], [6])
        self.assertEqual(self._run(status="paused")[0], [6])

    def test_compose_makes_the_sound_first_when_it_is_missing(self):
        import asyncio
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        service = DramaService()
        service.repo = TaskRepository(str(Path(temp.name) / "tasks.json"))
        service.repo.save_task("post-1", _task())
        claimed = []

        def claim(_self, task_id, stage, **_kwargs):
            claimed.append(stage)
            return {**service.repo.get_task(task_id), "workflow_control": {"run_id": "r"}}

        for next_stage, expected in ((6, 6), (7, 7)):
            claimed.clear()
            snapshot = {"mode": "ready", "next_stage": next_stage, "stages": [{"guidance": ""}] * 8, "hint": "", "actions": []}
            with patch.object(DramaService, "workflow_snapshot", lambda _s, _t, snap=snapshot: snap), \
                 patch.object(DramaService, "_claim_stage_task", claim), \
                 patch.object(DramaService, "execute_stage", lambda *a, **k: asyncio.sleep(0)):
                asyncio.run(service.assistant_message("post-1", "合成视频"))
            self.assertEqual(claimed, [expected], next_stage)

    def test_the_automatic_run_moves_on_by_itself(self):
        self.assertEqual(self._run(automatic=True)[0], [6])


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class RenderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name)
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(self.media))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _clip(self, name, seconds=4):
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x568:rate=24:duration={seconds}",
                        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.media / name)], check=True)
        return media_compositor.public_url(name)

    def _music(self):
        path = self.media / "bgm.wav"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=3", str(path)], check=True)
        return str(path)

    def _level(self, path, start, seconds):
        report = subprocess.run([FFMPEG, "-v", "info", "-ss", str(start), "-t", str(seconds), "-i", str(path), "-vn",
                                 "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
        line = [part for part in report.splitlines() if "mean_volume" in part]
        return float(line[0].split("mean_volume:")[1].split("dB")[0]) if line else -200.0

    def test_a_film_mixing_native_sound_and_a_dub_renders(self):
        native = self._clip("n.mp4")
        silent = self.media / "s.mp4"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=24:duration=4",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)], check=True)
        dub = self.media / "dub.m4a"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=700:duration=2", str(dub)], check=True)
        film = media_compositor.compose_film([native, media_compositor.public_url("s.mp4")], ["", ""], None, tag="mix", title=None, bgm=True,
                                             bgm_path=self._music(), shot_voices=[None, str(dub)], native_audio=[True, False])
        self.assertTrue(film)
        path = self.media / film.rsplit("/", 1)[-1]
        self.assertGreater(self._level(path, 0.5, 2), -40, "the clip's own sound")
        self.assertGreater(self._level(path, 4.5, 1.5), -40, "the dub")

    def test_ambience_plays_under_dubbed_shots_only(self):
        native = self._clip("n.mp4")
        silent = self.media / "s.mp4"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x568:rate=24:duration=4",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)], check=True)
        ambience = self.media / "amb.wav"
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1500:duration=3", str(ambience)], check=True)
        film = media_compositor.compose_film([native, media_compositor.public_url("s.mp4")], ["", ""], None, tag="amb", title=None, bgm=False,
                                             sfx_path=str(ambience), native_audio=[True, False])
        path = self.media / film.rsplit("/", 1)[-1]
        band = lambda start: self._band(path, start, 1.5, 1500)  # noqa: E731
        self.assertLess(band(1.0), band(5.0) - 20, "quiet under the native shot, audible under the other")

    def _band(self, path, start, seconds, frequency):
        report = subprocess.run([FFMPEG, "-v", "info", "-ss", str(start), "-t", str(seconds), "-i", str(path), "-vn",
                                 "-af", f"bandpass=f={frequency}:width_type=h:w=40,volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
        line = [part for part in report.splitlines() if "mean_volume" in part]
        return float(line[0].split("mean_volume:")[1].split("dB")[0]) if line else -200.0

    def test_music_comes_in_where_it_is_placed_and_the_edges_fade(self):
        url = self._clip("a.mp4", seconds=6)
        film = media_compositor.compose_film([url], [""], None, tag="f", title=None, bgm=True, bgm_path=self._music(),
                                             bgm_volume=0.8, bgm_start=3.0, fade_edges=True)
        path = self.media / film.rsplit("/", 1)[-1]
        self.assertLess(self._level(path, 0.5, 2), -60, "no music before its place")
        self.assertGreater(self._level(path, 3.5, 1.5), -40, "music after it")


if __name__ == "__main__":
    unittest.main()


def _episode_task():
    """Two episodes; episode 1 is finished with a film, episode 2 has clips and is being cut."""
    def shot(scene, sid, url):
        return {"shot_id": sid, "scene_id": scene, "video_url": url, "duration": "4", "dialogue": "", "native_audio": True}
    return {
        "task_id": "ep-1", "stage_name": "剪辑合成师·成片合成", "current_stage": 7, "status": "idle",
        "config": {"title_suggestion": "雪夜", "tts_model": "macos-say"},
        "assets": {
            "4_progress": {"current_episode": 2, "episodes": [{"number": n, "total": 1, "done": 1, "complete": True} for n in (1, 2)]},
            "4": [{"scene_id": f"E{n}S01", "shot_id": 1} for n in (1, 2)],
            "5": [shot("E1S01", 1, "http://x/e1.mp4"), shot("E2S01", 1, "http://x/e2.mp4")],
            "episode_cycle": {"episodes": {"1": {"film": {"final_video_url": "/media/e1_old.mp4"}, "audio": {"shot_voices": [None], "native_audio_shots": [True]},
                                                 "needs_render_for_voice": True}}},
        },
    }


class EpisodeTimelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service.repo.save_task("ep-1", _episode_task())

    def test_an_edit_in_per_episode_work_is_still_there_on_the_next_read(self):
        first = self.service.get_timeline("ep-1")
        self.assertEqual(first["timeline"]["episode"], 2)
        uid = first["timeline"]["clips"][0]["shot_uid"]
        self.service.edit_timeline("ep-1", "audio_source", {"shot_uid": uid, "audio_source": "none"})
        again = self.service.get_timeline("ep-1")
        self.assertEqual(edit_timeline.audio_source(again["timeline"]["clips"][0]), "none")
        saved = self.service.repo.get_task("ep-1")["assets"]["episode_cycle"]["episodes"]["2"]["timeline"]
        self.assertEqual(edit_timeline.audio_source(saved["clips"][0]), "none")

    def test_a_finished_episode_can_be_rendered_again_on_its_own(self):
        before = self.service.get_timeline("ep-1")
        with patch("app.service.drama_service.media_compositor.compose_film", return_value="/media/e1_new.mp4") as compose:
            result = self.service.render_timeline("ep-1", episode=1)
        self.assertEqual(result["episode"], 1)
        self.assertEqual(compose.call_args.args[0], ["http://x/e1.mp4"], "episode 1's clips only")
        self.assertTrue(compose.call_args.kwargs["title"].endswith("第1集"))
        task = self.service.repo.get_task("ep-1")
        record = task["assets"]["episode_cycle"]["episodes"]["1"]
        self.assertEqual(record["film"]["final_video_url"], "/media/e1_new.mp4")
        self.assertNotIn("needs_render_for_voice", record)
        self.assertEqual(record["timeline"]["episode"], 1)
        self.assertEqual(task["assets"]["7_timeline"]["episode"], before["timeline"]["episode"], "the live cut stays on episode 2")
        self.assertEqual(task["assets"]["film_versions"][0]["episode"], 1)

    def test_an_episode_that_does_not_exist_is_refused(self):
        with self.assertRaises(ValueError):
            self.service.render_timeline("ep-1", episode=9)

    def test_the_editor_lists_the_episodes_it_can_open(self):
        result = self.service.get_timeline("ep-1")
        self.assertEqual(result["live_episode"], 2)
        self.assertEqual(result["episodes"], [
            {"number": 1, "clips": 1, "film_url": "/media/e1_old.mp4"}, {"number": 2, "clips": 1, "film_url": None}])
        self.service.repo.save_task("post-1", _task())
        whole = self.service.get_timeline("post-1")                       # 不分集的项目没有可切的集
        self.assertEqual((whole["episodes"], whole["live_episode"]), ([], None))

    def test_a_finished_episode_can_be_opened_and_edited_without_touching_the_cut_in_progress(self):
        live = self.service.get_timeline("ep-1")["timeline"]
        first = self.service.get_timeline("ep-1", episode=1)
        self.assertEqual(first["timeline"]["episode"], 1)
        self.assertEqual([clip["scene_id"] for clip in first["timeline"]["clips"]], ["E1S01"])
        uid = first["timeline"]["clips"][0]["shot_uid"]

        result = self.service.edit_timeline("ep-1", "subtitle", {"shot_uid": uid, "text": "第一集改的字幕"}, episode=1)
        self.assertEqual(result["timeline"]["episode"], 1)
        self.assertEqual(result["timeline"]["clips"][0]["subtitle"], "第一集改的字幕")

        task = self.service.repo.get_task("ep-1")
        self.assertEqual(task["assets"]["episode_cycle"]["episodes"]["1"]["timeline"]["clips"][0]["subtitle"], "第一集改的字幕")
        self.assertEqual(task["assets"]["7_timeline"]["episode"], 2, "the cut in progress is still episode 2's")
        self.assertEqual(task["assets"]["7_timeline"]["clips"], live["clips"])
        self.assertEqual(self.service.get_timeline("ep-1", episode=1)["timeline"]["clips"][0]["subtitle"], "第一集改的字幕")
        self.assertEqual(self.service.get_timeline("ep-1")["timeline"]["clips"][0]["subtitle"], live["clips"][0]["subtitle"])

        with patch("app.service.drama_service.media_compositor.compose_film", return_value="/media/e1_new.mp4") as compose:
            self.service.render_timeline("ep-1", episode=1)
        self.assertEqual(compose.call_args.args[1], ["第一集改的字幕"], "the film is composed from the edited cut")

    def test_reading_an_episode_twice_writes_nothing_the_second_time(self):
        self.service.get_timeline("ep-1", episode=1)
        self.service.get_timeline("ep-1")
        with patch.object(self.service.repo, "mutate_task", wraps=self.service.repo.mutate_task) as write:
            self.service.get_timeline("ep-1", episode=1)
            self.service.get_timeline("ep-1")
        self.assertEqual(write.call_count, 0)

    def test_an_episode_that_is_not_there_cannot_be_opened_or_edited(self):
        with self.assertRaises(ValueError):
            self.service.get_timeline("ep-1", episode=9)
        with self.assertRaises(edit_timeline.TimelineError):
            self.service.edit_timeline("ep-1", "settings", {"settings": {"subtitles": False}}, episode=9)
        self.service.repo.save_task("post-1", _task())
        with self.assertRaises(ValueError):
            self.service.get_timeline("post-1", episode=1)                  # 不分集的项目没有「第 1 集」

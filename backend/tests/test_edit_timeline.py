"""The edit timeline drives the final cut and the JianYing draft; the music library holds the beds."""

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core import bgm_library, edit_timeline
from app.export import jianying
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from main import app


def _task(**overrides) -> dict:
    task = {
        "task_id": "tl-1", "owner_user_id": "u1", "status": "idle", "current_stage": 6,
        "config": {"title_suggestion": "请帮我生成一部暗室回声", "video_model": "seedance2.0", "llm_model": "m"},
        "assets": {
            "5": [
                {"shot_id": 1, "video_url": "http://localhost:8000/media/c1.mp4", "duration": 8, "dialogue": "林夏：你到底瞒了什么？", "desc": "林夏推门", "contract_fingerprint": "f1", "candidates": ["http://localhost:8000/media/c1.mp4", "http://localhost:8000/media/c1b.mp4"]},
                {"shot_id": 2, "video_url": None, "duration": 6, "dialogue": "", "desc": "空镜"},
                {"shot_id": 3, "video_url": "http://localhost:8000/media/c3.mp4", "duration": 6, "dialogue": "", "desc": "周教授站在她身后，声音低沉，现在回头还来得及", "contract_fingerprint": "f3"},
            ],
            "6": {"shot_voices": ["/tmp/v1.mp3", None, None], "bgm_path": "/tmp/bgm.mp3", "bgm_url": "http://localhost:8000/media/bgm.mp3", "sfx_path": None},
        },
        "logs": {}, "chat_history": [],
    }
    task.update(overrides)
    return task


class TimelineModelTests(unittest.TestCase):
    def test_a_timeline_is_built_from_the_clips_with_voices_subtitles_and_music(self):
        timeline = edit_timeline.build(_task(), transitions=[{"type": "dip_to_black", "duration": 0.4}], title="暗室回声")
        self.assertEqual([c["shot_id"] for c in timeline["clips"]], [1, 3], "a shot without a clip is not on the timeline")
        first, third = timeline["clips"]
        self.assertEqual(first["subtitle"], "你到底瞒了什么？")
        self.assertEqual(first["voice_path"], "/tmp/v1.mp3")
        self.assertIsNone(first["transition_in"])
        self.assertEqual(third["transition_in"], {"type": "dip_to_black", "duration": 0.4})
        self.assertEqual(third["subtitle"][:4], "周教授站")
        self.assertEqual(timeline["bgm"]["source"], "generated")
        self.assertEqual(timeline["title"], {"text": "暗室回声", "seconds": 2.6})
        self.assertEqual(edit_timeline.summary(timeline)["seconds"], 16.6)

    def test_edits_change_the_cut_and_a_rejected_clip_leaves_it(self):
        timeline = edit_timeline.build(_task(), title="暗室回声")
        timeline = edit_timeline.trim(timeline, 1, start=1.0, end=6.5)
        timeline = edit_timeline.set_transition(timeline, 3, kind="crossfade", duration=0.3)
        timeline = edit_timeline.set_subtitle(timeline, 3, "  现在   回头  ")
        timeline = edit_timeline.set_muted(timeline, 1, True)
        timeline = edit_timeline.choose_candidate(timeline, 1, "http://localhost:8000/media/c1b.mp4")
        timeline = edit_timeline.review(timeline, 3, decision="rejected", note="人物面部崩坏")
        timeline = edit_timeline.set_bgm(timeline, source="none")

        plan = edit_timeline.render_plan(timeline)
        self.assertEqual(plan["shot_video_urls"], ["http://localhost:8000/media/c1b.mp4"])
        self.assertEqual(plan["trims"], [(1.0, 6.5)])
        self.assertEqual(plan["shot_voices"], [None], "a muted clip keeps its voice out")
        self.assertFalse(plan["bgm"])
        self.assertEqual(plan["title"], "暗室回声")
        self.assertEqual(edit_timeline.summary(timeline)["review"], {"pending": 1, "approved": 0, "rejected": 1})
        self.assertEqual(edit_timeline.summary(timeline)["seconds"], 8.1)
        self.assertEqual(timeline["revision"], 7)

        with self.assertRaisesRegex(edit_timeline.TimelineError, "出点"):
            edit_timeline.trim(timeline, 1, start=1.0, end=1.2)
        with self.assertRaisesRegex(edit_timeline.TimelineError, "第一镜"):
            edit_timeline.set_transition(timeline, 1, kind="crossfade")
        with self.assertRaisesRegex(edit_timeline.TimelineError, "候选"):
            edit_timeline.choose_candidate(timeline, 1, "http://elsewhere/x.mp4")
        with self.assertRaisesRegex(edit_timeline.TimelineError, "没有镜头"):
            edit_timeline.review(timeline, 9, decision="approved")

    def test_a_refresh_after_new_footage_keeps_the_edits_of_unchanged_clips(self):
        task = _task()
        timeline = edit_timeline.review(edit_timeline.trim(edit_timeline.build(task, title="t"), 1, start=0.5, end=None), 3, decision="approved")
        self.assertTrue(edit_timeline.is_current(timeline, task))
        task["assets"]["5"][2] = {**task["assets"]["5"][2], "video_url": "http://localhost:8000/media/c3-new.mp4", "contract_fingerprint": "f3b"}
        self.assertFalse(edit_timeline.is_current(timeline, task))
        refreshed = edit_timeline.refresh(timeline, task, title="t")
        self.assertEqual(refreshed["clips"][0]["in"], 0.5, "the untouched clip keeps its trim")
        self.assertEqual(refreshed["clips"][1]["review"]["decision"], "pending", "the regenerated clip is reviewed again")
        self.assertEqual(refreshed["revision"], timeline["revision"] + 1)


class JianYingDraftTests(unittest.TestCase):
    def test_the_draft_lays_out_video_voice_music_and_subtitles_and_packs_the_media(self):
        with tempfile.TemporaryDirectory() as temp:
            media = {name: str(Path(temp) / name) for name in ("c1.mp4", "c3.mp4", "v1.mp3", "bgm.mp3")}
            for path in media.values():
                Path(path).write_bytes(b"x" * 16)
            task = _task()
            task["assets"]["6"]["shot_voices"] = [media["v1.mp3"], None, None]
            task["assets"]["6"]["bgm_path"] = media["bgm.mp3"]
            timeline = edit_timeline.trim(edit_timeline.build(task, transitions=[{"type": "crossfade", "duration": 0.3}], title="暗室回声"), 1, start=1.0, end=6.0)

            draft = jianying.build_draft(timeline, name="暗室回声", resolve_local=lambda url: media.get(url.rsplit("/", 1)[-1]))

            content = draft["draft_content"]
            video_track = next(t for t in content["tracks"] if t["type"] == "video")
            self.assertEqual(len(video_track["segments"]), 2)
            first, second = video_track["segments"]
            self.assertEqual(first["source_timerange"], {"start": 1_000_000, "duration": 5_000_000})
            self.assertEqual(first["target_timerange"]["start"], 2_600_000, "the title card comes first")
            self.assertEqual(second["target_timerange"]["start"], 7_600_000)
            self.assertEqual(second["transition"]["type"], "crossfade")
            self.assertEqual(content["duration"], 13_600_000)
            self.assertEqual(draft["duration_seconds"], 13.6)
            self.assertTrue(all(m["path"].startswith(jianying.DRAFT_PATH_MARKER + "/materials/") for m in content["materials"]["videos"]))
            audio_tracks = [t for t in content["tracks"] if t["type"] == "audio"]
            self.assertEqual(len(audio_tracks), 2, "voices and music are separate tracks")
            self.assertEqual(audio_tracks[0]["segments"][0]["target_timerange"]["start"], 2_600_000)
            self.assertEqual(audio_tracks[1]["segments"][0]["target_timerange"]["duration"], content["duration"])
            texts = next(t for t in content["tracks"] if t["type"] == "text")
            self.assertEqual(len(texts["segments"]), 3, "title line plus two subtitles")
            self.assertEqual(draft["draft_meta_info"]["tm_duration"], content["duration"])
            self.assertEqual(draft["skipped"], [])

            packed = jianying.pack(draft, folder_name="暗室回声")
            with zipfile.ZipFile(io.BytesIO(packed)) as archive:
                names = archive.namelist()
                self.assertIn("暗室回声/draft_content.json", names)
                self.assertIn("暗室回声/draft_meta_info.json", names)
                self.assertIn("暗室回声/materials/shot_1.mp4", names)
                self.assertIn("暗室回声/materials/bgm.mp3", names)
                loaded = json.loads(archive.read("暗室回声/draft_content.json"))
                self.assertEqual(loaded["version"], jianying.DRAFT_VERSION)

    def test_footage_that_is_not_on_this_machine_is_reported_not_faked(self):
        draft = jianying.build_draft(edit_timeline.build(_task(), title=None), name="x", resolve_local=lambda _url: None)
        self.assertEqual(len(draft["skipped"]), 2)
        self.assertEqual(draft["draft_content"]["duration"], 0)


class BgmLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(bgm_library.settings, "RUNTIME_DIR", Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_tracks_are_checked_by_their_bytes_listed_and_removed(self):
        with self.assertRaisesRegex(bgm_library.BgmUploadError, "不一致"):
            bgm_library.add_track(name="x", mood="", content=b"not-audio-at-all", filename="x.mp3", content_type="audio/mpeg")
        with self.assertRaisesRegex(bgm_library.BgmUploadError, "仅支持"):
            bgm_library.add_track(name="x", mood="", content=b"ID3" + b"\x00" * 10, filename="x.txt", content_type="text/plain")
        with patch.object(bgm_library, "_probe_seconds", return_value=42.0):
            track = bgm_library.add_track(name="  夜雨  紧张 ", mood="tense", content=b"ID3" + b"\x00" * 64, filename="night.mp3", content_type="audio/mpeg", owner_id="u1")
        self.assertEqual((track["name"], track["mood"], track["seconds"], track["source"]), ("夜雨 紧张", "tense", 42.0, "upload"))
        self.assertTrue(Path(track["path"]).is_file())
        self.assertEqual([t["id"] for t in bgm_library.list_tracks()], [track["id"]])
        self.assertEqual(bgm_library.get_track(track["id"])["name"], "夜雨 紧张")
        self.assertTrue(bgm_library.remove_track(track["id"]))
        self.assertEqual(bgm_library.list_tracks(), [])
        self.assertFalse(bgm_library.remove_track("nope"))

    def test_a_generated_bed_can_be_kept(self):
        source = Path(self.temp.name) / "gen.mp3"
        source.write_bytes(b"ID3" + b"\x00" * 32)
        with patch.object(bgm_library, "_probe_seconds", return_value=None):
            kept = bgm_library.keep_generated(name="第 6 阶段配乐", mood="", source_path=str(source))
        self.assertEqual(kept["source"], "generated")
        self.assertIn(kept["id"], [t["id"] for t in bgm_library.list_tracks()])


class TimelineServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        self.repo.save_task("tl-1", _task())
        patcher = patch.object(bgm_library.settings, "RUNTIME_DIR", Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        self.addCleanup(app.dependency_overrides.pop, get_current_user, None)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_the_timeline_is_built_on_first_read_edited_through_the_api_and_rendered_with_its_trims(self):
        with patch.object(drama_api, "service", self.service):
            first = self.client.get("/api/drama/tl-1/timeline")
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual([c["shot_id"] for c in first.json()["timeline"]["clips"]], [1, 3])
            self.assertEqual(first.json()["timeline"]["title"]["text"], "暗室回声")
            self.assertIn("crossfade", first.json()["transitions"])

            trimmed = self.client.post("/api/drama/tl-1/timeline/ops", json={"operation": "trim", "shot_id": 1, "start": 1, "end": 6})
            self.assertEqual(trimmed.status_code, 200, trimmed.text)
            rejected = self.client.post("/api/drama/tl-1/timeline/ops", json={"operation": "review", "shot_id": 3, "decision": "rejected", "note": "重做"})
            self.assertEqual(rejected.json()["summary"]["review"]["rejected"], 1)
            bad = self.client.post("/api/drama/tl-1/timeline/ops", json={"operation": "trim", "shot_id": 1, "start": 1, "end": 1.2})
            self.assertEqual(bad.status_code, 422)

            with patch("app.service.drama_service.media_compositor.compose_film", return_value="http://localhost:8000/media/film.mp4") as compose:
                rendered = self.client.post("/api/drama/tl-1/timeline/render")
            self.assertEqual(rendered.status_code, 200, rendered.text)
            kwargs = compose.call_args.kwargs
            self.assertEqual(compose.call_args.args[0], ["http://localhost:8000/media/c1.mp4"], "the rejected clip is out of the cut")
            self.assertEqual(kwargs["trims"], [(1.0, 6.0)])
            self.assertEqual(kwargs["title"], "暗室回声")
            self.assertEqual(kwargs["bgm_path"], "/tmp/bgm.mp3")

        stored = self.repo.get_task("tl-1")
        self.assertEqual(stored["assets"]["7"]["final_video_url"], "http://localhost:8000/media/film.mp4")
        self.assertEqual(stored["assets"]["7"]["timeline_summary"]["included"], 1)
        self.assertEqual(stored["video_url"], "http://localhost:8000/media/film.mp4")

    def test_music_from_the_library_is_picked_onto_the_timeline(self):
        with patch.object(bgm_library, "_probe_seconds", return_value=30.0):
            track = bgm_library.add_track(name="夜雨", mood="tense", content=b"ID3" + b"\x00" * 64, filename="night.mp3", content_type="audio/mpeg")
        with patch.object(drama_api, "service", self.service):
            listed = self.client.get("/api/library/bgm")
            self.assertEqual([t["name"] for t in listed.json()["items"]], ["夜雨"])
            picked = self.client.post("/api/drama/tl-1/timeline/ops", json={"operation": "bgm", "source": "library", "library_id": track["id"], "volume": 0.3})
            self.assertEqual(picked.status_code, 200, picked.text)
            bgm = picked.json()["timeline"]["bgm"]
            self.assertEqual((bgm["source"], bgm["name"], bgm["volume"], bgm["library_id"]), ("library", "夜雨", 0.3, track["id"]))
            self.assertEqual(bgm["path"], track["path"])
            missing = self.client.post("/api/drama/tl-1/timeline/ops", json={"operation": "bgm", "source": "library", "library_id": "nope"})
            self.assertEqual(missing.status_code, 422)
            audio = self.client.get(f"/api/library/bgm/{track['id']}/audio")
            self.assertEqual(audio.status_code, 200)

    def test_the_jianying_draft_downloads_as_a_zip_and_names_what_it_could_not_pack(self):
        with patch.object(drama_api, "service", self.service):
            response = self.client.get("/api/drama/tl-1/timeline/jianying.zip")
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertEqual(response.headers["x-draft-skipped"], "2", "the fixture's clips are not on disk")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertTrue(any(name.endswith("/draft_content.json") for name in archive.namelist()))

    def test_stage_seven_renders_from_the_timeline_it_persists(self):
        task = self.repo.get_task("tl-1")
        task["assets"].update({"1": "方案", "2": "剧本", "3": "角色", "4": [{"shot_id": 1}]})
        task["stage_progress"] = {"stage": 7, "status": "running", "calls": []}
        self.repo.save_task("tl-1", task)
        with patch("app.service.drama_service.media_compositor.compose_film", return_value="http://localhost:8000/media/film7.mp4") as compose, \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"), \
             patch.object(DramaService, "_ensure_agent_council", lambda _self, _task: {"delivery": {"aspect_ratio": "9:16"}, "negative_prompt_by_role": {}}), \
             patch.object(DramaService, "_agent_role_prompt", lambda _self, _task, _role: ""):
            self.service._execute_stage_blocking("tl-1", 7, _claimed_task=task)
        stored = self.repo.get_task("tl-1")
        self.assertEqual(compose.call_args.kwargs["trims"], [(0.0, None), (0.0, None)])
        self.assertEqual(stored["assets"][edit_timeline.TIMELINE_KEY]["revision"], 0)
        self.assertEqual(stored["assets"]["7"]["timeline_summary"]["clips"], 2)


if __name__ == "__main__":
    unittest.main()

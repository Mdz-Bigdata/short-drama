"""The edit timeline drives the final cut and the JianYing draft; the music library holds the beds."""

import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core import bgm_library, edit_timeline, media_compositor
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


def _two_scene_task() -> dict:
    """Two scenes that both start at shot 1, the way every multi-scene film is numbered."""
    task = _task()
    task["assets"]["5"] = [
        {"shot_id": 1, "scene_id": "E1S01", "video_url": "http://localhost:8000/media/s1c1.mp4", "duration": 8, "dialogue": "", "contract_fingerprint": "a1"},
        {"shot_id": 2, "scene_id": "E1S01", "video_url": "http://localhost:8000/media/s1c2.mp4", "duration": 6, "dialogue": "", "contract_fingerprint": "a2"},
        {"shot_id": 1, "scene_id": "E1S02", "video_url": "http://localhost:8000/media/s2c1.mp4", "duration": 5, "dialogue": "", "contract_fingerprint": "b1",
         "candidates": ["http://localhost:8000/media/s2c1.mp4", "http://localhost:8000/media/s2c1b.mp4"]},
    ]
    task["assets"]["6"] = {"shot_voices": [None, None, None], "bgm_path": None}
    return task


def _without_shot_uids(timeline: dict) -> dict:
    """The timeline as it was saved before clips carried ``shot_uid``."""
    return {**timeline, "clips": [{k: v for k, v in clip.items() if k not in {"shot_uid", "scene_id"}} for clip in timeline["clips"]]}


class SubtitleTextTests(unittest.TestCase):
    def test_only_the_spoken_words_reach_the_subtitle(self):
        cases = {
            "｛站住。｝——苏问剑，低沉偏冷、气声短促 ｛伸手。｝": "站住。 伸手。",
            "「贱籍碰剑，断手。」（音色偏低沉厚、冷得无情绪的中年男声，语速慢": "贱籍碰剑，断手。",
            "无 无 无": "",
            "裴仲玄：果然在这。停顿一拍，三年了。": "果然在这。 三年了。",
            "苏问剑：{爹！}（音色偏低、沙哑、被压住的女声；起音猛、尾音发颤，语速快）": "爹！",
            "沈无咎：剑不是我拿的（气声；喉头发紧，越说越低": "剑不是我拿的",
        }
        for dialogue, subtitle in cases.items():
            self.assertEqual(edit_timeline._subtitle_of({"dialogue": dialogue, "desc": "周教授站在门口"}), subtitle, dialogue)


class TimelineModelTests(unittest.TestCase):
    def test_a_timeline_is_built_from_the_clips_with_voices_subtitles_and_music(self):
        timeline = edit_timeline.build(_task(), transitions=[{"type": "dip_to_black", "duration": 0.4}], title="暗室回声")
        self.assertEqual([c["shot_id"] for c in timeline["clips"]], [1, 3], "a shot without a clip is not on the timeline")
        first, third = timeline["clips"]
        self.assertEqual(first["subtitle"], "你到底瞒了什么？")
        self.assertEqual(first["voice_path"], "/tmp/v1.mp3")
        self.assertIsNone(first["transition_in"])
        self.assertEqual(third["transition_in"], {"type": "dip_to_black", "duration": 0.4})
        self.assertEqual(third["subtitle"], "", "没有台词的镜头不出字幕(不再把画面描述烧进成片)")
        self.assertEqual(timeline["bgm"]["source"], "generated")
        self.assertEqual(timeline["title"], {"text": "暗室回声", "seconds": 2.6})
        self.assertEqual(edit_timeline.summary(timeline)["seconds"], 16.6)

    def test_a_planned_sound_offset_reaches_the_render_and_a_person_can_change_it(self):
        specs = [{"type": "crossfade", "duration": 0.22, "sound_join": "l_cut"}]
        timeline = edit_timeline.build(_task(), transitions=specs, title="t")
        self.assertIsNone(timeline["clips"][0]["sound_in"])
        self.assertEqual(edit_timeline.render_plan(timeline)["sound_joins"], [{"join": "l_cut"}])

        changed = edit_timeline.set_sound_join(timeline, 3, join="j_cut", seconds=0.8)
        self.assertEqual(edit_timeline.render_plan(changed)["sound_joins"], [{"join": "j_cut", "seconds": 0.8}])
        self.assertEqual(edit_timeline.render_plan(edit_timeline.set_sound_join(changed, 3, join=""))["sound_joins"], [{"join": ""}])
        with self.assertRaisesRegex(edit_timeline.TimelineError, "未知"):
            edit_timeline.set_sound_join(timeline, 3, join="x_cut")
        with self.assertRaisesRegex(edit_timeline.TimelineError, "第一镜"):
            edit_timeline.set_sound_join(timeline, 1, join="j_cut")

    def test_a_refresh_keeps_a_persons_sound_offset_and_follows_the_plan_otherwise(self):
        task = _task()
        planned = edit_timeline.build(task, transitions=[{"sound_join": "l_cut"}], title="t")
        self.assertEqual(edit_timeline.refresh(planned, task, transitions=[{"sound_join": "j_cut"}], title="t")["clips"][1]["sound_in"]["join"], "j_cut")
        edited = edit_timeline.set_sound_join(planned, 3, join="")
        self.assertEqual(edit_timeline.refresh(edited, task, transitions=[{"sound_join": "j_cut"}], title="t")["clips"][1]["sound_in"]["join"], "")

    def test_what_the_render_did_is_recorded_on_the_clip_without_counting_as_an_edit(self):
        timeline = edit_timeline.build(_task(), transitions=[{"sound_join": "j_cut"}], title="t")
        report = [{"index": 1, "join": "j_cut", "seconds": 0.4, "applied": False, "reason": "下一镜没有配音，没有声音可以提前"}]
        recorded = edit_timeline.record_sound_results(timeline, edit_timeline.render_plan(timeline)["shot_ids"], report)
        self.assertEqual(recorded["clips"][1]["sound_in"]["result"]["reason"], report[0]["reason"])
        self.assertEqual(recorded["revision"], timeline["revision"])
        cleared = edit_timeline.record_sound_results(recorded, [1, 3], [])
        self.assertNotIn("result", cleared["clips"][1]["sound_in"])

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

    def test_the_same_shot_number_in_two_scenes_is_two_clips(self):
        timeline = edit_timeline.build(_two_scene_task(), transitions=[{}, {"sound_join": "j_cut"}], title="t")
        self.assertEqual([(c["scene_id"], c["shot_id"], c["shot_uid"]) for c in timeline["clips"]], [("E1S01", 1, 100101), ("E1S01", 2, 100102), ("E1S02", 1, 100201)])

        timeline = edit_timeline.review(timeline, 1, decision="rejected", note="穿模", shot_uid=100201)
        timeline = edit_timeline.trim(timeline, 1, start=1.0, end=4.0, shot_uid=100201)
        timeline = edit_timeline.set_muted(timeline, 1, True, shot_uid=100201)
        timeline = edit_timeline.set_subtitle(timeline, 1, "回头", shot_uid=100201)
        timeline = edit_timeline.choose_candidate(timeline, 1, "http://localhost:8000/media/s2c1b.mp4", shot_uid=100201)
        timeline = edit_timeline.set_transition(timeline, 1, kind="dip_to_black", shot_uid=100201)
        timeline = edit_timeline.set_sound_join(timeline, 1, join="l_cut", shot_uid=100201)
        first, _, third = timeline["clips"]
        self.assertEqual((first["review"]["decision"], first["in"], first["muted"], first["subtitle"]), ("pending", 0.0, False, ""), "scene 1 的镜头 1 没被动过")
        self.assertEqual((third["review"]["decision"], third["in"], third["out"], third["muted"], third["subtitle"]), ("rejected", 1.0, 4.0, True, "回头"))
        self.assertEqual(third["video_url"], "http://localhost:8000/media/s2c1b.mp4")
        self.assertEqual((third["transition_in"]["type"], third["sound_in"]["join"]), ("dip_to_black", "l_cut"))

        with self.assertRaisesRegex(edit_timeline.TimelineError, "没有镜头"):
            edit_timeline.review(timeline, 1, decision="approved", shot_uid=100301)
        # 只给镜号的旧调用方还是落在第一段上。
        self.assertEqual(edit_timeline.review(timeline, 1, decision="approved")["clips"][0]["review"]["decision"], "approved")

    def test_a_timeline_saved_before_shot_uids_still_takes_edits_and_gets_its_ids_back(self):
        task = _two_scene_task()
        saved = _without_shot_uids(edit_timeline.build(task, title="t"))
        self.assertTrue(edit_timeline.is_current(saved, task))

        self.assertEqual(edit_timeline.set_muted(saved, 2, True)["clips"][1]["muted"], True)
        self.assertEqual(edit_timeline.set_muted(saved, 2, True, shot_uid=100102)["clips"][1]["muted"], True, "没有全剧编号的片段退回按镜号找")

        restored = edit_timeline.with_shot_uids(saved, task)
        self.assertEqual([(c["shot_uid"], c["scene_id"]) for c in restored["clips"]], [(100101, "E1S01"), (100102, "E1S01"), (100201, "E1S02")])
        self.assertNotIn("shot_uid", saved["clips"][0], "the stored timeline is not changed in place")
        self.assertEqual(restored["revision"], saved["revision"])
        self.assertIs(edit_timeline.with_shot_uids(restored, task), restored)

    def test_what_the_render_did_lands_on_the_clip_at_that_place_in_the_cut(self):
        timeline = edit_timeline.build(_two_scene_task(), transitions=[{}, {"sound_join": "j_cut"}], title="t")
        timeline = edit_timeline.set_sound_join(timeline, 1, join="l_cut", shot_uid=100201)
        report = [{"index": 2, "join": "l_cut", "seconds": 0.5, "applied": True, "reason": ""}]
        recorded = edit_timeline.record_sound_results(timeline, edit_timeline.render_plan(timeline)["shot_ids"], report)
        self.assertEqual(recorded["clips"][2]["sound_in"]["result"]["applied"], True)
        self.assertIsNone(recorded["clips"][0]["sound_in"])

        # 中间一段被打回后，成片里的第 2 段就是第二场的镜头 1。
        without = edit_timeline.review(timeline, 2, decision="rejected")
        recorded = edit_timeline.record_sound_results(without, edit_timeline.render_plan(without)["shot_ids"], [{**report[0], "index": 1}])
        self.assertEqual(recorded["clips"][2]["sound_in"]["result"]["applied"], True)

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
            self.assertEqual(len(texts["segments"]), 2, "title line plus the one spoken subtitle (the silent shot carries none)")
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

    def test_two_scenes_that_both_start_at_shot_one_keep_their_own_files(self):
        with tempfile.TemporaryDirectory() as temp:
            task = _two_scene_task()
            # Both scenes' shot 1 are on this machine, each with a voice; the shot between them is not.
            media = {name: str(Path(temp) / name) for name in ("s1c1.mp4", "s2c1.mp4", "v1.mp3", "v2.mp3")}
            for name, path in media.items():
                Path(path).write_bytes(name.encode())
            task["assets"]["6"] = {"shot_voices": [media["v1.mp3"], None, media["v2.mp3"]], "bgm_path": None}
            timeline = edit_timeline.build(task, title=None)

            draft = jianying.build_draft(timeline, name="x", resolve_local=lambda url: media.get(url.rsplit("/", 1)[-1]), probe=lambda _path: 1.0)

            packed = {kind: sorted(Path(local).name for rel, local in draft["files"].items() if rel.startswith(f"materials/{kind}_")) for kind in ("shot", "voice")}
            self.assertEqual(packed, {"shot": ["s1c1.mp4", "s2c1.mp4"], "voice": ["v1.mp3", "v2.mp3"]}, "no scene's file is written over another's")
            videos = [item["path"] for item in draft["draft_content"]["materials"]["videos"]]
            self.assertEqual(len(set(videos)), 2)
            # The clip that is missing is named with its scene, since its number alone repeats.
            self.assertEqual(draft["skipped"], ["E1S01 镜头 2：片段不在本机，未打包"])

    def offset_draft(self, joins, voices, *, probe=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        media = {name: str(Path(temp.name) / name) for name in ("c1.mp4", "c3.mp4", "v1.mp3", "v3.mp3")}
        for path in media.values():
            Path(path).write_bytes(b"x" * 16)
        task = _task()
        task["assets"]["6"]["shot_voices"] = [media.get(voices[0]), None, media.get(voices[1])]
        task["assets"]["6"]["bgm_path"] = None
        timeline = edit_timeline.build(task, transitions=[{"type": "crossfade", "duration": 0.22, **joins}], title=None)
        lengths = {media["v1.mp3"]: 7.5, media["v3.mp3"]: 2.0}
        draft = jianying.build_draft(timeline, name="x", resolve_local=lambda url: media.get(url.rsplit("/", 1)[-1]), probe=probe or lengths.get)
        tracks = draft["draft_content"]["tracks"]
        picture = next(t for t in tracks if t["type"] == "video")["segments"]
        sound = next((t for t in tracks if t["type"] == "audio"), {"segments": []})["segments"]
        return draft, picture, sound

    def test_an_l_cut_shortens_the_picture_and_lets_the_line_run_past_it(self):
        draft, picture, sound = self.offset_draft({"sound_join": "l_cut"}, ("v1.mp3", None))
        # An 8s clip with a 7.5s line: the picture leaves at 7s, half a second before the line ends.
        self.assertEqual(picture[0]["source_timerange"], {"start": 0, "duration": 7_000_000})
        self.assertEqual(picture[1]["target_timerange"]["start"], 7_000_000)
        self.assertEqual(sound[0]["target_timerange"], {"start": 0, "duration": 7_500_000})
        self.assertEqual(draft["sound_joins"][0]["shot_id"], 3)
        self.assertTrue(draft["sound_joins"][0]["applied"])

    def test_a_j_cut_starts_the_line_before_the_picture_and_drops_the_head(self):
        draft, picture, sound = self.offset_draft({"sound_join": "j_cut"}, (None, "v3.mp3"))
        self.assertEqual(picture[1]["source_timerange"], {"start": 400_000, "duration": 5_600_000})
        self.assertEqual(picture[1]["target_timerange"]["start"], 8_000_000)
        self.assertEqual(sound[0]["target_timerange"], {"start": 7_600_000, "duration": 2_000_000})
        self.assertEqual(draft["draft_content"]["duration"], 13_600_000)

    def test_a_cut_that_cannot_be_offset_says_why_and_stays_as_it_was(self):
        draft, picture, sound = self.offset_draft({"sound_join": "l_cut"}, ("v1.mp3", "v3.mp3"))
        self.assertFalse(draft["sound_joins"][0]["applied"])
        self.assertIn("压住", draft["sound_joins"][0]["reason"])
        self.assertEqual(picture[0]["source_timerange"]["duration"], 8_000_000)
        self.assertEqual(sound[1]["target_timerange"]["start"], 8_000_000)

    def test_a_long_line_stops_where_the_next_one_starts(self):
        lengths = lambda path: 9.5 if path.endswith("v1.mp3") else 2.0  # noqa: E731 - a stub
        _, _, sound = self.offset_draft({}, ("v1.mp3", "v3.mp3"), probe=lengths)
        self.assertEqual(sound[0]["target_timerange"], {"start": 0, "duration": 8_000_000})
        self.assertEqual(sound[0]["source_timerange"]["duration"], 8_000_000)

    def test_without_a_probe_nothing_is_offset(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        media = {name: str(Path(temp.name) / name) for name in ("c1.mp4", "c3.mp4", "v3.mp3")}
        for path in media.values():
            Path(path).write_bytes(b"x" * 16)
        task = _task()
        task["assets"]["6"]["shot_voices"] = [None, None, media["v3.mp3"]]
        timeline = edit_timeline.build(task, transitions=[{"sound_join": "j_cut"}], title=None)
        draft = jianying.build_draft(timeline, name="x", resolve_local=lambda url: media.get(url.rsplit("/", 1)[-1]))
        self.assertFalse(draft["sound_joins"][0]["applied"])
        picture = next(t for t in draft["draft_content"]["tracks"] if t["type"] == "video")["segments"]
        self.assertEqual(picture[1]["source_timerange"]["start"], 0)

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

    def test_the_downloaded_draft_offsets_the_cut_using_the_real_length_of_the_voice(self):
        ffmpeg = media_compositor._ffmpeg()
        if not ffmpeg:
            self.skipTest("ffmpeg unavailable")
        root = Path(self.temp.name)
        for name in ("c1.mp4", "c3.mp4"):
            (root / name).write_bytes(b"x" * 16)
        voice = root / "v1.wav"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=7.5", str(voice)], check=True)
        task = _task()
        task["assets"]["6"].update({"shot_voices": [str(voice), None, None], "bgm_path": None})
        task["assets"]["5"][2]["cut_in"] = {"from_shot": 2, "kind": "match_cut", "label": "同物换境", "compositor": "match_cut", "sound_join": "l_cut"}
        self.repo.save_task("tl-1", task)
        with patch.object(drama_api, "service", self.service), \
                patch("app.service.drama_service.media_compositor._local_media_source", side_effect=lambda url: str(root / str(url).rsplit("/", 1)[-1])):
            response = self.client.get("/api/drama/tl-1/timeline/jianying.zip")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["x-draft-sound-offsets"], "1")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            content = json.loads(archive.read(next(name for name in archive.namelist() if name.endswith("draft_content.json"))))
        picture = next(track for track in content["tracks"] if track["type"] == "video")["segments"]
        sound = next(track for track in content["tracks"] if track["type"] == "audio")["segments"]
        cut = picture[-1]["target_timerange"]["start"]
        ends = sound[0]["target_timerange"]["start"] + sound[0]["target_timerange"]["duration"]
        self.assertAlmostEqual((ends - cut) / 1_000_000, 0.5, delta=0.02)

    def test_the_timeline_is_built_on_first_read_edited_through_the_api_and_rendered_with_its_trims(self):
        with patch.object(drama_api, "service", self.service):
            first = self.client.get("/api/drama/tl-1/timeline")
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual([c["shot_id"] for c in first.json()["timeline"]["clips"]], [1, 3])
            self.assertEqual(first.json()["timeline"]["title"]["text"], "暗室回声")
            self.assertIn("crossfade", first.json()["transitions"])

            offset = self.client.post("/api/drama/tl-1/timeline/ops", json={"operation": "sound_join", "shot_id": 3, "join": "j_cut", "seconds": 0.8})
            self.assertEqual(offset.status_code, 200, offset.text)
            self.assertEqual(offset.json()["timeline"]["clips"][1]["sound_in"]["join"], "j_cut")

            def renders(*_args, **kwargs):
                self.assertEqual(kwargs["sound_joins"], [{"join": "j_cut", "seconds": 0.8}])
                kwargs["sound_report"].append({"index": 1, "join": "j_cut", "seconds": 0.8, "applied": False, "reason": "下一镜没有配音"})
                return "http://localhost:8000/media/film.mp4"

            with patch("app.service.drama_service.media_compositor.compose_film", side_effect=renders):
                joined = self.client.post("/api/drama/tl-1/timeline/render")
            self.assertEqual(joined.status_code, 200, joined.text)
            self.assertEqual(joined.json()["sound_joins"][0]["reason"], "下一镜没有配音")
            self.assertEqual(self.client.get("/api/drama/tl-1/timeline").json()["timeline"]["clips"][1]["sound_in"]["result"]["applied"], False)
            cleared = self.client.post("/api/drama/tl-1/timeline/ops", json={"operation": "sound_join", "shot_id": 3, "join": ""})
            self.assertEqual(cleared.json()["timeline"]["clips"][1]["sound_in"]["join"], "")

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

    def test_an_edit_names_its_clip_by_shot_uid_and_a_stored_timeline_without_ids_gets_them(self):
        task = _two_scene_task()
        task["assets"][edit_timeline.TIMELINE_KEY] = _without_shot_uids(edit_timeline.build(task, title="暗室回声"))
        self.repo.save_task("tl-1", task)
        with patch.object(drama_api, "service", self.service):
            read = self.client.get("/api/drama/tl-1/timeline")
            self.assertEqual(read.status_code, 200, read.text)
            self.assertEqual([c["shot_uid"] for c in read.json()["timeline"]["clips"]], [100101, 100102, 100201])
            self.assertEqual(self.repo.get_task("tl-1")["assets"][edit_timeline.TIMELINE_KEY]["clips"][2]["shot_uid"], 100201, "the ids are saved, not recomputed on every read")

            rejected = self.client.post("/api/drama/tl-1/timeline/ops", json={"operation": "review", "shot_id": 1, "shot_uid": 100201, "decision": "rejected", "note": "重做"})
            self.assertEqual(rejected.status_code, 200, rejected.text)
            self.assertEqual([c["review"]["decision"] for c in rejected.json()["timeline"]["clips"]], ["pending", "pending", "rejected"])

            # 只带镜号的旧请求照旧可用。
            muted = self.client.post("/api/drama/tl-1/timeline/ops", json={"operation": "mute", "shot_id": 2, "muted": True})
            self.assertEqual([c["muted"] for c in muted.json()["timeline"]["clips"]], [False, True, False])
            gone = self.client.post("/api/drama/tl-1/timeline/ops", json={"operation": "mute", "shot_id": 1, "shot_uid": 100901, "muted": True})
            self.assertEqual(gone.status_code, 422)

    def test_the_title_card_carries_the_screenplays_title_not_the_request(self):
        task = _task()
        task["config"]["title_suggestion"] = "请帮我生成一份武侠短剧"
        task["assets"]["2_screenwriting"] = {"overview": {"title": "拭剑奴"}}
        self.repo.save_task("tl-1", task)
        timeline = self.service.get_timeline("tl-1")["timeline"]
        self.assertEqual(timeline["title"]["text"], "拭剑奴")

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

    def test_stage_seven_refuses_to_cut_a_film_from_clips_it_cannot_fetch(self):
        task = self.repo.get_task("tl-1")
        task["assets"].update({"1": "方案", "2": "剧本", "3": "角色", "4": [{"shot_id": 1}]})
        task["stage_progress"] = {"stage": 7, "status": "running", "calls": []}
        self.repo.save_task("tl-1", task)
        with patch("app.service.drama_service.media_compositor.compose_film") as compose, \
             patch.object(DramaService, "_ensure_agent_council", lambda _self, _task: {"delivery": {"aspect_ratio": "9:16"}, "negative_prompt_by_role": {}}), \
             patch.object(DramaService, "_agent_role_prompt", lambda _self, _task, _role: ""), \
             self.assertRaisesRegex(RuntimeError, "已拿不到"):
            self.service._execute_stage_blocking("tl-1", 7, _claimed_task=task)
        compose.assert_not_called()

    def test_stage_seven_renders_from_the_timeline_it_persists(self):
        task = self.repo.get_task("tl-1")
        task["assets"].update({"1": "方案", "2": "剧本", "3": "角色", "4": [{"shot_id": 1}]})
        task["stage_progress"] = {"stage": 7, "status": "running", "calls": []}
        self.repo.save_task("tl-1", task)
        with patch("app.service.drama_service.media_compositor.compose_film", return_value="http://localhost:8000/media/film7.mp4") as compose, \
             patch("app.service.drama_service.media_compositor.media_available", return_value=True), \
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

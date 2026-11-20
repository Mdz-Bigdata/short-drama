# -*- coding: utf-8 -*-
"""A recast voice after dubbing: everything the character said is re-dubbed, every copy updated, films marked.

No provider is called: the dubbing call is patched to write nothing and record what it was asked,
and the voice studio is the casting tests' stand-in.
"""

import ast
import json
import re
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core import edit_timeline, episode_cycle, media_compositor, voice_casting
from app.repository.task_repo import TaskRepository
from app.service import voice_relink
from app.service.drama_service import DramaService, StagePrerequisiteError
from main import app
from tests.test_voice_casting import FakeStudio

TASK = "relink-task"
SHEN, LU = "沈知微", "陆行远"
VOICE_PROMPT = "民国女学生，18岁，女声，中高音，清亮略带气声，咬字干净，语速偏快；情绪中性；干声，无音乐无混响"


def _clip(scene, shot, dialogue, **extra):
    return {"shot_id": shot, "scene_id": scene, "episode": int(scene[1]), "video_url": f"http://localhost:8000/media/{scene}-{shot}.mp4",
            "duration": 6, "dialogue": dialogue, "contract_fingerprint": f"{scene}-{shot}", **extra}


def _task(task_id=TASK, owner="relink-user"):
    """Two episodes made one after another. Episode 1 has a film, episode 2 is dubbed and on the live timeline.

    E1: shot 1 both speak (dubbed), shot 2 only 陆行远 (dubbed), shot 3 沈知微 in the clip's own sound.
    E2: shot 1 沈知微 twice (dubbed), shot 2 陆行远 in the clip's own sound.
    """
    clips = [
        _clip("E1S01", 1, "沈知微：你来了。\n陆行远：我来了。", voice_path="/tmp/e1-1.mp3", voice_url="u-e1-1", native_audio=False),
        _clip("E1S01", 2, "陆行远：走吧。", voice_path="/tmp/e1-2.mp3", native_audio=False),
        _clip("E1S01", 3, "沈知微（低声）：别回头。", native_audio=True),
        _clip("E2S01", 1, "沈知微：第二集开始了。\n沈知微：还是我。", native_audio=False),
        _clip("E2S01", 2, "陆行远：好。", native_audio=True),
    ]
    task = {
        "task_id": task_id, "owner_user_id": owner, "status": "idle", "current_stage": 7,
        "config": {"title_suggestion": "暗室回声", "tts_model": "eleven_v3"},
        "assets": {
            "3_characters": [{"name": SHEN, "desc": "女性，18岁民国女学生", "role": "主角"}, {"name": LU, "desc": "男性，中年", "role": "反派"}],
            "3_dna": {"characters": [
                {"name": SHEN, "voice_id": "v-shen-old", "voice_prompt": VOICE_PROMPT},
                {"name": LU, "voice_id": "v-lu"},
            ]},
            "4_progress": {"episodes": [{"number": 1, "complete": True}, {"number": 2, "complete": True}]},
            "5": clips,
            episode_cycle.CYCLE_KEY: {"version": 1, "episodes": {
                "1": {"audio": {"shot_voices": ["/tmp/e1-1.mp3", "/tmp/e1-2.mp3", None], "native_audio_shots": [False, False, True], "episode": 1},
                      "film": {"final_video_url": "http://localhost:8000/media/film-e1.mp4"}},
                "2": {"audio": {"shot_voices": ["/tmp/e2-1.mp3", None], "native_audio_shots": [False, True], "episode": 2}},
            }},
            "7": {"final_video_url": "http://localhost:8000/media/film-e1.mp4", "episode": 1},
            "film_versions": [{"url": "http://localhost:8000/media/film-e1.mp4", "episode": 1}],
        },
        "logs": {}, "episodes": [],
    }
    task["assets"]["6"] = dict(task["assets"][episode_cycle.CYCLE_KEY]["episodes"]["2"]["audio"])
    for number in (1, 2):
        timeline = edit_timeline.build(episode_cycle.episode_view(task, number))
        timeline["episode"] = number
        if number == 1:
            task["assets"][episode_cycle.CYCLE_KEY]["episodes"]["1"]["timeline"] = timeline
        else:
            task["assets"][edit_timeline.TIMELINE_KEY] = timeline
    return task


def _whole_film_task():
    """One run for the whole film, no timeline yet: a native shot of 沈知微 and a dubbed one."""
    task = _task()
    assets = task["assets"]
    assets.pop(episode_cycle.CYCLE_KEY)
    assets.pop("4_progress")
    assets.pop(edit_timeline.TIMELINE_KEY)
    assets["5"] = [
        {"shot_id": 1, "video_url": "http://localhost:8000/media/w1.mp4", "duration": 6, "dialogue": "沈知微：开始。", "voice_path": "/tmp/w1.mp3"},
        {"shot_id": 2, "video_url": "http://localhost:8000/media/w2.mp4", "duration": 6, "dialogue": "沈知微：结束。", "native_audio": True},
    ]
    assets["6"] = {"shot_voices": ["/tmp/w1.mp3", None], "native_audio_shots": [False, True]}
    assets["7"] = {"final_video_url": "http://localhost:8000/media/film.mp4"}
    assets["film_versions"] = [{"url": "http://localhost:8000/media/film.mp4"}]
    return task


class FakeDub:
    """Stands in for the dubbing call: records the lines and the cast voices bound around it."""

    def __init__(self, fail_tags=()):
        self.calls = []
        self.fail_tags = tuple(fail_tags)

    def __call__(self, segments, *, tts_model, tag="voice"):
        self.calls.append({"segments": list(segments), "voices": dict(media_compositor._speaker_voices.get()), "tag": tag})
        if any(part in tag for part in self.fail_tags):
            return None, None
        return f"http://localhost:8000/media/{tag}.mp3", f"/tmp/{tag}.mp3"


def _forbidden(*args, **kwargs):
    raise AssertionError("a paid dubbing call was made")


class RelinkCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.studio = FakeStudio()
        self.service.voice_studio = self.studio
        self.service.voice_relink_background = False
        self.service.repo.save_task(TASK, _task())
        self.dub = FakeDub()
        self.attached = []
        for target, value in (
            ("synthesize_preferred_dialogue_track", self.dub),
            ("synthesize_elevenlabs_dialogue_track", _forbidden),
            ("synthesize_dialogue_track", _forbidden),
            ("effective_audio_model", lambda model: ("elevenlabs", "eleven_v3")),
            ("attach_audio_to_clip", self._attach),
        ):
            patcher = patch.object(media_compositor, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _attach(self, video_url, voice_path=None, bgm=True, tag="shotav"):
        self.attached.append({"video": video_url, "voice": voice_path, "bgm": bgm, "tag": tag})
        return f"http://localhost:8000/media/{tag}.mp4"

    def _assets(self):
        return self.service.repo.get_task(TASK)["assets"]

    def _recast(self, voice="v-shen-new"):
        task = self.service.repo.get_task(TASK)
        voice_casting.set_voice(task["assets"], SHEN, voice_id=voice)
        self.service.repo.save_task(TASK, task)


class PreviewTests(RelinkCase):
    def test_counts_dubbed_and_native_lines_per_episode_and_the_films_to_render(self):
        result = voice_relink.preview(self.service.repo.get_task(TASK), SHEN)

        self.assertEqual(result["lines"], 4)          # E1: one dubbed + one native, E2: two dubbed
        self.assertEqual(result["dubbed_shots"], 2)
        self.assertEqual(result["native_shots"], 1)
        self.assertEqual(result["episodes"], [1, 2])
        self.assertEqual(result["films_to_rerender"], [1])
        self.assertEqual((result["provider"], result["billed"]), ("elevenlabs", True))
        self.assertEqual(result["per_episode"][0], {
            "episode": 1, "dubbed_shots": 1, "dubbed_lines": 1, "native_shots": 1, "native_lines": 1, "film": True,
        })
        self.assertNotIn("taken_by", result)
        self.assertEqual(self.dub.calls, [])

    def test_the_other_character_and_the_local_voice(self):
        result = voice_relink.preview(self.service.repo.get_task(TASK), LU)
        self.assertEqual((result["lines"], result["dubbed_shots"], result["native_shots"]), (3, 2, 1))
        with patch.object(media_compositor, "effective_audio_model", lambda model: ("", "edge-tts")):
            local = voice_relink.preview(self.service.repo.get_task(TASK), LU)
        self.assertEqual((local["provider"], local["billed"]), ("local", False))

    def test_a_voice_someone_else_has_is_named_and_the_same_voice_changes_nothing(self):
        task = self.service.repo.get_task(TASK)
        self.assertEqual(voice_relink.preview(task, SHEN, voice="v-lu")["taken_by"], LU)
        same = voice_relink.preview(task, SHEN, voice="v-shen-old")
        self.assertTrue(same["unchanged"])
        self.assertEqual((same["lines"], same["episodes"], same["films_to_rerender"]), (0, [], []))


class RelinkTests(RelinkCase):
    def test_only_the_characters_shots_are_redubbed_and_every_copy_follows(self):
        self._recast()

        summary = voice_relink.relink(self.service, TASK, SHEN)

        self.assertTrue(summary["applied"])
        self.assertEqual((summary["shots_redubbed"], summary["lines_redubbed"], summary["native_switched"]), (2, 3, 1))
        self.assertEqual(summary["episodes"], [1, 2])
        self.assertEqual(summary["films_to_rerender"], [1])
        self.assertEqual(summary["failures"], [])
        # Two tracks made again, the whole mixed track each time, with the cast's current voices.
        self.assertEqual(len(self.dub.calls), 2)
        first = self.dub.calls[0]
        self.assertEqual([segment[3] for segment in first["segments"]], [SHEN, LU])
        self.assertEqual(first["voices"][SHEN], "v-shen-new")
        self.assertEqual(first["voices"][LU], "v-lu")
        self.assertRegex(first["tag"], r"^voice_relink-t_e1_s0_r[0-9a-f]{6}$")

        assets = self._assets()
        new_e1, new_e2 = (f"/tmp/{call['tag']}.mp3" for call in self.dub.calls)
        clips = assets["5"]
        self.assertEqual(clips[0]["voice_path"], new_e1)
        self.assertEqual(clips[0]["voice_url"], f"http://localhost:8000/media/{self.dub.calls[0]['tag']}.mp3")
        self.assertEqual(clips[1]["voice_path"], "/tmp/e1-2.mp3")      # only 陆行远 speaks there
        records = assets[episode_cycle.CYCLE_KEY]["episodes"]
        self.assertEqual(records["1"]["audio"]["shot_voices"], [new_e1, "/tmp/e1-2.mp3", None])
        self.assertEqual(records["2"]["audio"]["shot_voices"], [new_e2, None])
        self.assertEqual(assets["6"]["shot_voices"], [new_e2, None])

        # Episode 1's own timeline: the new voice laid in, the native shot set to a dub made at render.
        cut1 = {clip["shot_uid"]: clip for clip in records["1"]["timeline"]["clips"]}
        self.assertEqual(cut1[100101]["voice_path"], new_e1)
        self.assertEqual(cut1[100102]["voice_path"], "/tmp/e1-2.mp3")
        self.assertEqual(cut1[100103]["audio_source"], "tts")
        self.assertEqual([clip["shot_uid"] for clip in edit_timeline.needs_voice(records["1"]["timeline"])], [100103])
        # The live timeline (episode 2): new voice, and 陆行远's native shot stays native.
        live = {clip["shot_uid"]: clip for clip in assets[edit_timeline.TIMELINE_KEY]["clips"]}
        self.assertEqual(live[200101]["voice_path"], new_e2)
        self.assertEqual(live[200102]["audio_source"], "native")

        self.assertEqual(records["1"][voice_relink.MARK_KEY], [SHEN])
        self.assertEqual(assets["7"][voice_relink.MARK_KEY], [SHEN])
        self.assertNotIn(voice_relink.MARK_KEY, records["2"])
        self.assertEqual(voice_casting.dna_character(assets, LU)["voice_id"], "v-lu")
        self.assertEqual(assets[voice_relink.STATUS_KEY][SHEN]["status"], "done")

    def test_a_whole_film_run_gets_a_timeline_with_the_native_shot_dubbed(self):
        self.service.repo.save_task(TASK, _whole_film_task())
        self._recast()

        summary = voice_relink.relink(self.service, TASK, SHEN)

        self.assertEqual((summary["shots_redubbed"], summary["native_switched"], summary["films_to_rerender"]), (1, 1, [0]))
        assets = self._assets()
        new = f"/tmp/{self.dub.calls[0]['tag']}.mp3"
        self.assertEqual(assets["6"]["shot_voices"], [new, None])
        self.assertEqual(assets["5"][0]["voice_path"], new)
        clips = assets[edit_timeline.TIMELINE_KEY]["clips"]
        self.assertEqual([clip["audio_source"] for clip in clips], ["tts", "tts"])
        self.assertEqual(clips[0]["voice_path"], new)
        self.assertEqual(assets["7"][voice_relink.MARK_KEY], [SHEN])

    def test_a_failed_shot_leaves_every_track_and_timeline_as_it_was(self):
        self._recast()
        before = deepcopy(self._assets())
        self.dub.fail_tags = ("_e2_",)

        summary = voice_relink.relink(self.service, TASK, SHEN)

        self.assertFalse(summary["applied"])
        self.assertEqual(len(summary["failures"]), 1)
        self.assertEqual(summary["failures"][0]["episode"], 2)
        after = self._assets()
        status = after.pop(voice_relink.STATUS_KEY)
        self.assertEqual(status[SHEN]["status"], "failed")
        self.assertEqual(json.dumps(after, sort_keys=True, ensure_ascii=False), json.dumps(before, sort_keys=True, ensure_ascii=False))

    def test_refused_while_a_stage_runs_and_for_a_shared_voice(self):
        self._recast()
        task = self.service.repo.get_task(TASK)
        task["status"] = "running"
        self.service.repo.save_task(TASK, task)
        with self.assertRaisesRegex(ValueError, "正在执行"):
            voice_relink.relink(self.service, TASK, SHEN)

        task["status"] = "idle"
        voice_casting.dna_character(task["assets"], LU)["voice_id"] = "v-shen-new"
        self.service.repo.save_task(TASK, task)
        with self.assertRaisesRegex(ValueError, LU):
            voice_relink.relink(self.service, TASK, SHEN)
        self.assertEqual(self.dub.calls, [])

    def test_a_render_clears_the_mark(self):
        self._recast()
        voice_relink.relink(self.service, TASK, SHEN)
        task = self.service.repo.get_task(TASK)

        voice_relink.clear_render_marks(task, 1)

        self.assertNotIn(voice_relink.MARK_KEY, task["assets"]["7"])
        self.assertNotIn(voice_relink.MARK_KEY, task["assets"][episode_cycle.CYCLE_KEY]["episodes"]["1"])


class PreviewClipTests(RelinkCase):
    def test_the_workbench_preview_gets_the_new_voice_and_the_cut_keeps_its_clip(self):
        before = [clip.get("video_url") for clip in self._assets()["5"]]
        self._recast()
        voice_relink.relink(self.service, TASK, SHEN)
        clips = self._assets()["5"]
        # Re-dubbed shots get a fresh preview made from the clip plus the new dub only (no music bed).
        self.assertEqual(len(self.attached), 2)
        self.assertTrue(all(call["bgm"] is False and call["voice"] and call["tag"].startswith("shotav_relink-t_s") for call in self.attached))
        self.assertEqual(clips[0]["preview_url"], f"http://localhost:8000/media/{self.attached[0]['tag']}.mp4")
        self.assertNotIn("preview_url", clips[1])            # 沈 does not speak there
        self.assertEqual([clip.get("video_url") for clip in clips], before)

    def test_a_preview_that_cannot_be_made_does_not_stop_the_re_dub(self):
        self._attach = lambda video_url, voice_path=None, bgm=True, tag="shotav": video_url
        with patch.object(media_compositor, "attach_audio_to_clip", self._attach):
            self._recast()
            summary = voice_relink.relink(self.service, TASK, SHEN)
        self.assertTrue(summary["applied"])
        self.assertNotIn("preview_url", self._assets()["5"][0])


class CastRelinksTests(RelinkCase):
    def _cast_new_take(self):
        round_ = self.service.audition_character_voice(TASK, SHEN)
        return self.service.cast_character_voice(TASK, SHEN, round_["previews"][0]["generated_voice_id"])

    def test_casting_a_new_voice_relinks_and_reports_it(self):
        dashboard = self._cast_new_take()

        summary = dashboard.voice_relink
        self.assertEqual(summary["status"], "done")
        self.assertEqual((summary["shots_redubbed"], summary["native_switched"]), (2, 1))
        self.assertEqual(summary["films_to_rerender"], [1])
        self.assertIn("voiceRelink", dashboard.model_dump(mode="json", by_alias=True))
        self.assertEqual(self.dub.calls[0]["voices"][SHEN], "voice-for-gen-1-1")
        self.assertEqual(self._assets()["6"]["shot_voices"][0], f"/tmp/{self.dub.calls[1]['tag']}.mp3")

    def test_a_long_relink_runs_in_the_background_with_its_progress_on_the_task(self):
        self.service.voice_relink_background = True
        dashboard = self._cast_new_take()
        self.assertEqual(dashboard.voice_relink["status"], "queued")
        for thread in threading.enumerate():
            if thread.name.startswith("voice-relink-"):
                thread.join(timeout=10)

        status = self._assets()[voice_relink.STATUS_KEY][SHEN]
        self.assertEqual(status["status"], "done")
        self.assertEqual((status["total"], status["done"]), (2, 2))
        self.assertEqual(status["summary"]["shots_redubbed"], 2)

    def test_a_voice_another_character_has_is_refused_before_anything_is_dubbed(self):
        task = self.service.repo.get_task(TASK)
        voice_casting.dna_character(task["assets"], LU)["voice_id"] = "voice-for-gen-1-1"
        self.service.repo.save_task(TASK, task)
        self.service.audition_character_voice(TASK, SHEN)

        with self.assertRaisesRegex(ValueError, LU):
            self.service.cast_character_voice(TASK, SHEN, "gen-1-1")
        self.assertEqual(voice_casting.dna_character(self._assets(), SHEN)["voice_id"], "v-shen-old")
        self.assertEqual(self.dub.calls, [])

    def test_a_character_who_never_spoke_is_cast_without_a_relink(self):
        task = self.service.repo.get_task(TASK)
        task["assets"]["3_characters"].append({"name": "路人甲", "desc": "女性"})
        voice_casting.dna_character(task["assets"], SHEN)["voice_prompt"] = VOICE_PROMPT
        task["assets"]["3_dna"]["characters"].append({"name": "路人甲", "voice_prompt": VOICE_PROMPT})
        self.service.repo.save_task(TASK, task)
        round_ = self.service.audition_character_voice(TASK, "路人甲")

        dashboard = self.service.cast_character_voice(TASK, "路人甲", round_["previews"][0]["generated_voice_id"])

        self.assertIsNone(dashboard.voice_relink)
        self.assertEqual(self.dub.calls, [])


class PreviewApiTests(RelinkCase):
    def setUp(self):
        super().setUp()
        self.original = drama_api.service.repo
        self.addCleanup(lambda: setattr(drama_api.service, "repo", self.original))
        drama_api.service.repo = self.service.repo
        self.service.repo.save_task("someone-else", _task("someone-else", owner="other"))
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "relink-user", "role": "user"}
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_the_preview_contract(self):
        response = self.client.get(f"/api/drama/{TASK}/characters/{SHEN}/voice-relink-preview", params={"voice": "v-lu"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key, kind in (("name", str), ("lines", int), ("episodes", list), ("native_shots", int), ("billed", bool),
                          ("provider", str), ("films_to_rerender", list)):
            self.assertIsInstance(body[key], kind, key)
        self.assertEqual((body["lines"], body["episodes"], body["films_to_rerender"]), (4, [1, 2], [1]))
        self.assertEqual(body["taken_by"], LU)
        self.assertEqual(self.dub.calls, [])

    def test_unknown_names_tasks_and_other_owners_are_404(self):
        base = "/api/drama/{}/characters/{}/voice-relink-preview"
        self.assertEqual(self.client.get(base.format(TASK, "路人乙")).status_code, 404)
        self.assertEqual(self.client.get(base.format("no-such-task", SHEN)).status_code, 404)
        self.assertEqual(self.client.get(base.format("someone-else", SHEN)).status_code, 404)


class StageGuardTests(RelinkCase):
    def _mark(self, status, started=None):
        task = self.service.repo.get_task(TASK)
        task["assets"].setdefault(voice_relink.STATUS_KEY, {})[SHEN] = {
            "status": status, "started_epoch": started if started is not None else time.time(),
        }
        self.service.repo.save_task(TASK, task)

    def test_stages_five_to_seven_wait_for_a_running_re_dub(self):
        self._mark("running")
        for stage in (5, 6, 7):
            with self.assertRaisesRegex(StagePrerequisiteError, "正在重配"):
                self.service._claim_stage_task(TASK, stage)
        self.assertNotEqual(self.service.repo.get_task(TASK).get("status"), "running")

    def test_other_stages_finished_re_dubs_and_stale_ones_do_not_block(self):
        self._mark("running")
        self.assertEqual(voice_relink.stage_refusal(self.service.repo.get_task(TASK), 3), "")
        self._mark("done")
        self.assertEqual(voice_relink.stage_refusal(self.service.repo.get_task(TASK), 6), "")
        # Cut off by a restart long ago: reported as failed, so it no longer holds the project.
        self._mark("running", started=time.time() - 10 * 24 * 3600)
        self.assertEqual(voice_relink.stage_refusal(self.service.repo.get_task(TASK), 6), "")


class WordingTests(unittest.TestCase):
    def test_no_chinese_sentence_is_hard_coded_in_the_module(self):
        tree = ast.parse(Path(voice_relink.__file__).read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and ast.get_docstring(node, clean=False) is not None
        }
        left = [node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r"[一-鿿]", node.value)
                and id(node) not in docstrings]
        self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()

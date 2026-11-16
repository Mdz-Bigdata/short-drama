# -*- coding: utf-8 -*-
"""Every character keeps one voice: clips from a model that makes its own sound carry the cast voice sample.

The sample is the audition take chosen in stage 3. A dialogue shot sends the samples of the characters who speak,
after the shot's own reference audios and within the model's limit; the voice lock line names the audio by its real
position (参考音频N, <Audio N> in H3's six-part prompt) and says nothing when the request does not carry it. Shots
without dialogue, speakers without a sample, silent models and models that take no audio go out exactly as before.
"""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.core import h3_native, h3_sound_design, voice_casting, voice_reference
from app.core.video_references import plan_video_references, renumber_audio_mentions, voice_placeholder
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from tests.test_stage_five_queue import _task

SAMPLE = "https://media.example.com/voices/shenyan.mp3"
SAMPLE_LIN = "https://media.example.com/voices/linwan.mp3"
OWN_AUDIO = "https://cdn.example.com/beat.mp3"


def _cast(name: str, url: str, **extra) -> dict:
    return {"name": name, "voice_id": f"v-{name}", "voice_take": {"generated_voice_id": f"g-{name}", "url": url}, **extra}


def _assets(*characters: dict) -> dict:
    return {"3_dna": {"characters": list(characters)}}


class VoiceSampleTest(unittest.TestCase):
    def test_the_cast_take_is_the_sample(self):
        self.assertEqual(voice_reference.voice_sample(_assets(_cast("沈砚", SAMPLE)), "沈砚"), SAMPLE)
        self.assertEqual(voice_reference.voice_sample(_assets(_cast("沈砚", SAMPLE)), " 沈砚 "), SAMPLE)

    def test_no_sample_without_a_cast_take(self):
        self.assertEqual(voice_reference.voice_sample(_assets(_cast("沈砚", SAMPLE)), "林婉"), "")
        self.assertEqual(voice_reference.voice_sample({}, "沈砚"), "")
        no_take = {"name": "沈砚", "voice_id": "v-1"}
        self.assertEqual(voice_reference.voice_sample(_assets(no_take), "沈砚"), "")
        no_voice = {"name": "沈砚", "voice_take": {"url": SAMPLE}}
        self.assertEqual(voice_reference.voice_sample(_assets(no_voice), "沈砚"), "", "a take without a cast voice is not the voice")

    def test_an_auto_assigned_library_voice_has_no_sample(self):
        auto = _cast("沈砚", SAMPLE, voice_source="auto")
        self.assertEqual(voice_reference.voice_sample(_assets(auto), "沈砚"), "")
        assets = {"3_auto_voices": {"路人甲": {"voice_id": "lib-1", "gender": "male"}}}
        self.assertEqual(voice_reference.voice_sample(assets, "路人甲"), "")


class PublicSampleTest(unittest.TestCase):
    POOL = {
        "female": [{"voice_id": "f1", "age": "young", "preview_url": "https://cdn.test/f1.mp3"}, {"voice_id": "f2", "age": "old"}],
        "male": [{"voice_id": "m1", "age": "middle_aged", "preview_url": "https://cdn.test/m1.mp3"}],
    }

    def test_an_auto_voice_keeps_the_library_preview_as_its_sample(self):
        assets = {"3_dna": {"characters": [{"name": "林夏"}, {"name": "周烈"}]}}
        voice_casting.assign_missing_voices(assets, {"林夏": "female", "周烈": "male", "路人甲": "female"}, self.POOL)
        self.assertEqual(voice_reference.voice_sample(assets, "林夏"), "https://cdn.test/f1.mp3")
        self.assertEqual(voice_reference.voice_sample(assets, "周烈"), "https://cdn.test/m1.mp3")
        # A library voice listed without a preview has no sample; a bit part's sample lives in 3_auto_voices.
        self.assertEqual(assets[voice_casting.AUTO_VOICES_KEY]["路人甲"]["voice_id"], "f2")
        self.assertEqual(voice_reference.voice_sample(assets, "路人甲"), "")
        assets[voice_casting.AUTO_VOICES_KEY]["路人甲"]["sample_url"] = "https://cdn.test/f2.mp3"
        self.assertEqual(voice_reference.voice_sample(assets, "路人甲"), "https://cdn.test/f2.mp3")

    def test_a_cast_voice_prefers_its_public_preview_and_a_recast_drops_the_old_one(self):
        assets = {"3_dna": {"characters": [{"name": "林夏"}]}}
        voice_casting.set_voice(assets, "林夏", voice_id="v1", take={"generated_voice_id": "g1", "url": "http://localhost:8000/media/take.mp3"},
                                sample_url="https://cdn.test/v1.mp3")
        self.assertEqual(voice_reference.voice_sample(assets, "林夏"), "https://cdn.test/v1.mp3")
        voice_casting.set_voice(assets, "林夏", voice_id="v2", take={"generated_voice_id": "g2", "url": "https://media.test/take2.mp3"})
        # No preview came back for the new voice: the old voice's preview is not its sample.
        self.assertEqual(voice_reference.voice_sample(assets, "林夏"), "https://media.test/take2.mp3")


class FitSampleTest(unittest.TestCase):
    """A sample longer than the model takes is cut to fit; one that cannot be sent is dropped, never failing the clip."""

    def setUp(self):
        from app.core import media_compositor

        self.mc = media_compositor
        if not media_compositor._ffmpeg():
            self.skipTest("ffmpeg not installed")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(media_compositor, "MEDIA_DIR", self.temp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = Path(self.temp.name) / "take.mp3"
        import subprocess

        subprocess.run([media_compositor._ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=33",
                        "-c:a", "libmp3lame", str(self.source)], check=True)
        self.limits = {"min": 2, "max": 15, "total": 15, "inline": False}

    def _local(self, url):
        return str(self.source) if url == "https://media.test/take.mp3" else None

    def test_a_33_second_take_is_cut_to_its_share_and_sent_by_its_public_link(self):
        with patch.object(self.mc, "local_media_path", self._local), \
                patch.object(voice_reference, "reachable", lambda url: url.startswith("https://media.test/")), \
                patch.object(self.mc, "public_url", lambda name: f"https://media.test/{name}"):
            sent = voice_reference.fit_sample("https://media.test/take.mp3", 7.5, self.limits)
        self.assertRegex(sent, r"^https://media\.test/voice_ref_[0-9a-f]{20}\.mp3$")
        cut = Path(self.temp.name) / sent.rsplit("/", 1)[1]
        self.assertAlmostEqual(self.mc._probe_duration(str(cut)), 7.5, delta=0.15)

    def test_with_no_public_link_it_goes_inline_only_where_allowed(self):
        with patch.object(self.mc, "local_media_path", self._local), patch.object(voice_reference, "reachable", lambda url: False):
            self.assertEqual(voice_reference.fit_sample("https://media.test/take.mp3", 5, self.limits), "")
            inline = voice_reference.fit_sample("https://media.test/take.mp3", 5, {**self.limits, "inline": True})
        self.assertTrue(inline.startswith("data:audio/mpeg;base64,"))

    def test_a_sample_within_limits_goes_as_it_is_and_one_too_short_is_dropped(self):
        import subprocess

        short = Path(self.temp.name) / "short.mp3"
        subprocess.run([self.mc._ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=1",
                        "-c:a", "libmp3lame", str(short)], check=True)
        local = {"https://media.test/take.mp3": str(self.source), "https://media.test/short.mp3": str(short)}
        with patch.object(self.mc, "local_media_path", lambda url: local.get(url)), patch.object(voice_reference, "reachable", lambda url: True):
            self.assertEqual(voice_reference.fit_sample("https://media.test/take.mp3", 40, self.limits), "https://media.test/take.mp3")
            self.assertEqual(voice_reference.fit_sample("https://media.test/short.mp3", 5, self.limits), "")

    def test_the_share_is_the_total_over_the_audio_slots_so_merged_moments_stay_within_it(self):
        shares = []
        assets = {"3_dna": {"characters": [{"name": n, "voice_id": f"v-{n}", "voice_sample_url": f"https://cdn.test/{n}.mp3"} for n in ("甲", "乙")]}}
        with patch.object(voice_reference, "fit_sample", lambda url, seconds, limits: shares.append(seconds) or url):
            refs = voice_reference.shot_voice_refs(assets, ["甲", "乙"], [], 3, model="MiniMax-H3")
        self.assertEqual([name for name, _ in refs], ["甲", "乙"])
        self.assertEqual(shares, [5.0, 5.0])     # 15 s over 3 slots, though only two speak here


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.assets = _assets(_cast("沈砚", SAMPLE), _cast("林婉", SAMPLE_LIN), _cast("老者", "http://localhost:8000/media/old.mp3"))

    def test_speaking_order_within_the_limit(self):
        self.assertEqual(
            voice_reference.shot_voice_refs(self.assets, ["林婉", "沈砚"], [], 3), [("林婉", SAMPLE_LIN), ("沈砚", SAMPLE)],
        )
        self.assertEqual(voice_reference.shot_voice_refs(self.assets, ["林婉", "沈砚"], [], 1), [("林婉", SAMPLE_LIN)])
        self.assertEqual(voice_reference.shot_voice_refs(self.assets, ["林婉", "沈砚"], [], 0), [])

    def test_the_shots_own_audios_come_first_and_are_never_dropped(self):
        self.assertEqual(voice_reference.shot_voice_refs(self.assets, ["林婉", "沈砚"], [OWN_AUDIO], 2), [("林婉", SAMPLE_LIN)])
        own = [OWN_AUDIO, "https://cdn.example.com/b.mp3", "https://cdn.example.com/c.mp3"]
        self.assertEqual(voice_reference.shot_voice_refs(self.assets, ["林婉"], own, 3), [])
        self.assertEqual(voice_reference.shot_voice_refs(self.assets, ["林婉"], [SAMPLE_LIN], 3), [], "already attached by hand")

    def test_speakers_without_a_reachable_sample_are_skipped(self):
        self.assertEqual(voice_reference.shot_voice_refs(self.assets, ["无名", "老者", "沈砚"], [], 3), [("沈砚", SAMPLE)])

    def test_a_clip_of_several_moments_merges_in_order(self):
        merged = voice_reference.merge_refs([[("林婉", SAMPLE_LIN)], [("沈砚", SAMPLE), ("林婉", SAMPLE_LIN)]], [OWN_AUDIO], 3)
        self.assertEqual(merged, [("林婉", SAMPLE_LIN), ("沈砚", SAMPLE)])
        self.assertEqual(voice_reference.merge_refs([[("林婉", SAMPLE_LIN)], [("沈砚", SAMPLE)]], [OWN_AUDIO], 2), [("林婉", SAMPLE_LIN)])

    def test_the_model_decides_how_many(self):
        self.assertEqual(voice_reference.audio_limit("seedance2.0"), 3)
        self.assertEqual(voice_reference.audio_limit("MiniMax-H3"), 3)
        self.assertEqual(voice_reference.audio_limit("grok-imagine-video"), 0)
        self.assertEqual(voice_reference.audio_limit("ltx-2-3-pro"), 0)


class RoutingTest(unittest.TestCase):
    def _anchor(self):
        anchor = h3_sound_design.build_voice_anchor("沈砚", description="中年帝王", gender="male")
        return replace(anchor, ref_audio=voice_placeholder("沈砚"))

    def test_multi_reference_becomes_multimodal_and_the_line_names_the_audio(self):
        plan = plan_video_references("multi_reference", first_frame=None, reference_images=["https://x/a.png"], model="seedance2.0")
        carried = voice_reference.carry(plan, [("沈砚", SAMPLE)], model="seedance2.0")
        self.assertEqual((carried.mode, carried.reference_audios, carried.reference_images), ("multimodal", [SAMPLE], ["https://x/a.png"]))
        line = renumber_audio_mentions(self._anchor().lock_line(), [("沈砚", SAMPLE)], carried)
        self.assertIn("沈砚：音色照参考音频1（只取音色", line)
        self.assertNotIn("男声", line, "a carried sample is pointed at, not described beside")
        self.assertNotIn("〈", line)
        self.assertEqual(voice_reference.numbers(carried, [("沈砚", SAMPLE)]), {"沈砚": 1})
        self.assertTrue(voice_reference.voice_only(carried, [("沈砚", SAMPLE)]))

    def test_the_shots_own_audio_keeps_number_one(self):
        plan = plan_video_references(
            "multimodal", first_frame=None, reference_images=["https://x/a.png"], reference_audios=[OWN_AUDIO], model="seedance2.0",
        )
        carried = voice_reference.carry(plan, [("沈砚", SAMPLE)], model="seedance2.0")
        self.assertEqual(carried.reference_audios, [OWN_AUDIO, SAMPLE])
        self.assertIn("参考音频2", renumber_audio_mentions(self._anchor().lock_line(), [("沈砚", SAMPLE)], carried))
        self.assertFalse(voice_reference.voice_only(carried, [("沈砚", SAMPLE)]))

    def test_frame_requests_keep_their_route_and_lose_the_mention(self):
        plan = plan_video_references("first_last_frame", first_frame="https://x/a.png", last_frame="https://x/b.png", model="seedance2.0")
        self.assertIs(voice_reference.carry(plan, [("沈砚", SAMPLE)], model="seedance2.0"), plan)
        line = renumber_audio_mentions(self._anchor().lock_line(), [("沈砚", SAMPLE)], plan)
        self.assertNotIn("音色参考", line)
        self.assertEqual(line, replace(self._anchor(), ref_audio="").lock_line())

    def test_a_model_that_takes_no_audio_or_cannot_run_multimodal_is_unchanged(self):
        plan = plan_video_references("multi_reference", first_frame=None, reference_images=["https://x/a.png"], model="grok-imagine-video")
        self.assertIs(voice_reference.carry(plan, [("沈砚", SAMPLE)], model="grok-imagine-video"), plan)
        plan = plan_video_references("multi_reference", first_frame=None, reference_images=["https://x/a.png"], model="seedance2.0")
        self.assertIs(voice_reference.carry(plan, [("沈砚", SAMPLE)], model="seedance2.0", executable={"multi_reference"}), plan)

    def test_h3_names_the_audio_as_audio_n(self):
        text = (
            "subject_definitions: <Subject 1> is @[沈砚].\n\nsummary: [reference generation] He speaks.\n\n"
            "retention_analysis: <Subject 1>: fully_preserved - same face.\n\ndetailed_description: [Shot 1] (S1) says: <d>[Chinese] 朕的江山。</d>\n\n"
            "overall_soundscape: Chains clink.\n\nnon_diegetic_music: N/A"
        )
        out = h3_native.resolve(
            text, sent=["https://x/sheet.png", SAMPLE], identity_images=["https://x/sheet.png"], numbers={"沈砚": 1}, frames=[],
            audios={"沈砚": 1},
        )
        self.assertIn("沈砚 (<Picture 1>). <Audio 1> is the voice-timbre reference for 沈砚", out)
        self.assertIn("summary: [reference generation + audio reference] He speaks.", out)
        self.assertIn("<Audio 1>: reference - only the voice timbre of 沈砚", out)
        self.assertEqual(h3_native.resolve(text, sent=[], identity_images=[], numbers={}, frames=[]),
                         h3_native.resolve(text, sent=[], identity_images=[], numbers={}, frames=[], audios={}))


H3_SIX_PART = (
    "subject_definitions: <Subject 1> is @[沈砚], an emperor.\n\n"
    "summary: [reference generation] The emperor claims his realm.\n\n"
    "retention_analysis: <Subject 1>: fully_preserved - same face and robe.\n\n"
    "detailed_description: [Shot 1] The emperor looks up as (S1) says: <d>[Chinese] 朕的江山。</d>\n\n"
    "overall_soundscape: Chains clink softly.\n\n"
    "non_diegetic_music: N/A"
)


class StageFiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))

    def _task(self, *, model="seedance2.0", shots=1, dialogue="沈砚：朕的江山。", sample=SAMPLE):
        task = _task(shots)
        task["config"]["video_model"] = model
        task["assets"]["4"][0]["dialogue"] = dialogue
        task["assets"]["3_characters"] = [{"name": "沈砚", "desc": "四十岁男子，嗓音低沉"}]
        task["assets"]["3_dna"] = {"characters": [_cast("沈砚", sample) if sample else {"name": "沈砚", "voice_id": "v-1"}]}
        return task

    def _run(self, task, *, llm="沈砚抬眼，低声说：朕的江山。", accept_rewrite=False):
        """Stage 5 with every provider stubbed; returns (every video request, the stored clips)."""
        calls: list[dict] = []

        def generate_video(model, image_url, prompt, *args, **kwargs):
            calls.append({"first": image_url, "prompt": prompt, **kwargs})
            return f"https://cdn/{len(calls)}.mp4"

        self.service.repo.save_task(task["task_id"], task)
        with patch.object(self.service.gateway, "generate_video", side_effect=generate_video), \
             patch.object(self.service.gateway, "generate_image", return_value=("https://cdn/frame.png", {})), \
             patch.object(self.service.gateway, "call_llm", return_value=llm), \
             patch.object(self.service.gateway, "_http_chat", side_effect=AssertionError("no real model in this test")), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch.object(self.service.gateway, "last_video_failure", return_value=""), \
             patch("app.core.h3_native.check", return_value="") if accept_rewrite else patch("app.core.h3_native.MAX_CHARS", h3_native.MAX_CHARS), \
             patch("app.service.drama_service.media_compositor.extract_last_frame_b64", return_value="data:image/jpeg;base64,VEFJTA=="), \
             patch("app.service.drama_service.media_compositor.extract_first_frame_b64", return_value="data:image/jpeg;base64,VEFJTA=="), \
             patch("app.service.drama_service.seam_check.compare") as compare, \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch("app.service.drama_service.media_compositor.keep_clip", side_effect=lambda url, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            compare.return_value.as_dict.return_value = {"verdict": "good", "label": "接上了", "score": 0.01}
            self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        return calls, self.service.repo.get_task(task["task_id"])["assets"]["5"]

    def _same_as_without_a_sample(self, task_with, task_without):
        with_sample, _ = self._run(task_with)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        without, _ = self._run(task_without)
        self.assertTrue(with_sample, "the shot was sent")
        self.assertEqual(with_sample, without)
        for call in with_sample:
            self.assertFalse(call.get("ref_audios"))
            self.assertNotIn("音色参考", call["prompt"])
            self.assertNotIn("〈音频", call["prompt"])

    def test_a_seedance_dialogue_shot_carries_the_cast_voice(self):
        calls, clips = self._run(self._task())
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["ref_audios"], [SAMPLE])
        self.assertIn("沈砚", calls[0]["prompt"])
        self.assertIn("音色照参考音频1（只取音色，语速与情绪按本镜表达）；全片音色", calls[0]["prompt"])
        self.assertNotIn("〈音频", calls[0]["prompt"])
        decision = clips[0]["video_route_decision"]
        self.assertEqual((decision["mode"], decision["reference_audios"]), ("multimodal", [SAMPLE]))
        self.assertIn("参考音频1", clips[0]["sent_prompt"])

    def test_the_shots_own_reference_audio_stays_first(self):
        task = self._task()
        task["assets"]["4"][0]["reference_audios"] = [OWN_AUDIO]
        task["assets"]["4"][0].pop("contract_fingerprint", None)
        calls, _ = self._run(task)
        self.assertEqual(calls[0]["ref_audios"], [OWN_AUDIO, SAMPLE])
        self.assertIn("音色照参考音频2", calls[0]["prompt"])
        self.assertNotIn("参考音频1（只取音色", calls[0]["prompt"])

    def test_a_first_last_frame_shot_drops_the_audio_and_the_mention(self):
        task = self._task(shots=4)
        task["config"].pop("video_granularity", None)
        for shot in task["assets"]["4"]:
            shot["duration"] = "7"
        calls, clips = self._run(task)
        self.assertEqual([clip["clip_route"]["kind"] for clip in clips], ["first_last", "first_last"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0]["last_frame"])
        for call in calls:
            self.assertFalse(call.get("ref_audios"))
            self.assertNotIn("音色参考", call["prompt"])
            self.assertNotIn("〈音频", call["prompt"])
        self.assertIn("朕的江山", calls[0]["prompt"])
        self.assertIn("全片音色、音调与声线不变", calls[0]["prompt"], "the lock line stays, only its audio clause goes")

    def test_an_h3_shot_carries_the_voice_in_the_chinese_prompt(self):
        calls, clips = self._run(self._task(model="MiniMax-H3"))
        self.assertEqual(calls[0]["ref_audios"], [SAMPLE])
        self.assertIn("音色照参考音频1", calls[0]["prompt"])
        self.assertEqual(clips[0]["video_route_decision"]["mode"], "multimodal")

    def test_an_h3_six_part_prompt_names_it_audio_one(self):
        calls, _ = self._run(self._task(model="MiniMax-H3"), llm=H3_SIX_PART, accept_rewrite=True)
        prompt = calls[0]["prompt"]
        self.assertTrue(prompt.startswith("subject_definitions:"), prompt[:80])
        self.assertEqual(calls[0]["ref_audios"], [SAMPLE])
        self.assertIn("<Audio 1> is the voice-timbre reference for 沈砚", prompt)
        self.assertIn("summary: [reference generation + audio reference]", prompt)
        self.assertNotIn("参考音频", prompt)

    def test_a_model_that_takes_no_audio_is_untouched(self):
        self._same_as_without_a_sample(self._task(model="grok-imagine-video"), self._task(model="grok-imagine-video", sample=""))

    def test_a_project_that_dubs_is_untouched(self):
        dubbed, dubbed_without = self._task(), self._task(sample="")
        dubbed["config"]["native_audio"] = dubbed_without["config"]["native_audio"] = False
        self._same_as_without_a_sample(dubbed, dubbed_without)

    def test_a_speaker_without_a_sample_is_untouched(self):
        no_take, clips = self._run(self._task(sample=""))
        self.assertFalse(no_take[0].get("ref_audios"))
        self.assertNotIn("音色参考", no_take[0]["prompt"])
        self.assertNotIn("〈音频", no_take[0]["prompt"])
        self.assertIn("沈砚：", no_take[0]["prompt"], "the voice lock line itself is still written")
        self.assertEqual(clips[0]["video_route_decision"]["mode"], "multi_reference")
        local, _ = self._run(self._task(sample="http://localhost:8000/media/eleven_voice_preview_0_x.mp3"))
        self.assertEqual(local, no_take, "a sample on this machine cannot be fetched by the provider: not sent")

    def test_a_shot_without_dialogue_is_routed_as_before(self):
        self._same_as_without_a_sample(self._task(dialogue=""), self._task(dialogue="", sample=""))


if __name__ == "__main__":
    unittest.main()

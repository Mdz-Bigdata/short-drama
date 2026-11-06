# -*- coding: utf-8 -*-
"""Casting a voice: the designed voice prompt is auditioned, re-rolled, and one take is kept.

No provider is called: the voice studio is a stand-in that records what it was asked.
"""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core import voice_casting
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from main import app

VOICE_PROMPT = "民国女学生，18岁，女声，中高音，清亮略带气声，咬字干净，语速偏快；情绪中性；干声，无音乐无混响"


class FakeStudio:
    def __init__(self):
        self.designs = []
        self.created = []

    def design_voice(self, request):
        self.designs.append(request)
        round_no = len(self.designs)
        return {"text": request.text, "previews": [
            {"generated_voice_id": f"gen-{round_no}-{take}", "url": f"https://cdn.test/{round_no}-{take}.mp3",
             "path": f"/tmp/{round_no}-{take}.mp3", "duration_secs": 9.5}
            for take in (1, 2, 3)
        ]}

    def create_designed_voice(self, request):
        self.created.append(request)
        return {"voice_id": f"voice-for-{request.generated_voice_id}"}


def _task(task_id="cast-task", **extra):
    return {
        "task_id": task_id, "owner_user_id": "cast-user", "status": "idle", "current_stage": 3,
        "config": {"title_suggestion": "暗室回声"},
        "assets": {
            "3_characters": [{"name": "沈知微", "desc": "18岁民国女学生"}, {"name": "陆行远", "desc": "中年男人"}],
            "3_dna": {"characters": [
                {"name": "沈知微", "voice_id": "", "voice_prompt": VOICE_PROMPT, "voice_desc": "18岁女声，清亮带气声，语速偏快"},
                {"name": "陆行远", "voice_id": ""},
            ]},
        },
        "logs": {}, "episodes": [], **extra,
    }


class AuditionTextTests(unittest.TestCase):
    def test_the_test_line_is_neutral_declarative_and_long_enough(self):
        text = voice_casting.audition_text("沈知微")

        self.assertGreaterEqual(len(text), voice_casting.MIN_AUDITION_CHARS)
        self.assertTrue(text.startswith("我是沈知微。"))
        for mark in ("？", "！", "?", "!"):
            self.assertNotIn(mark, text)

    def test_a_missing_voice_prompt_is_refused_before_paying(self):
        with self.assertRaises(ValueError):
            voice_casting.audition_request("", "陆行远")


class CastingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.studio = FakeStudio()
        self.service.voice_studio = self.studio
        self.service.repo.save_task("cast-task", _task())

    def test_an_audition_uses_the_stored_voice_prompt_and_a_padded_neutral_line(self):
        result = self.service.audition_character_voice("cast-task", "沈知微")

        request = self.studio.designs[0]
        self.assertEqual(request.voice_description, VOICE_PROMPT)
        self.assertGreaterEqual(len(request.text), 100)
        self.assertEqual([p["generated_voice_id"] for p in result["previews"]], ["gen-1-1", "gen-1-2", "gen-1-3"])
        self.assertEqual(result["rounds"], 1)

    def test_calling_again_re_rolls_with_a_new_seed_and_keeps_both_rounds(self):
        first = self.service.audition_character_voice("cast-task", "沈知微", seed=11)
        second = self.service.audition_character_voice("cast-task", "沈知微", seed=12)

        self.assertNotEqual(first["seed"], second["seed"])
        self.assertEqual(second["rounds"], 2)
        stored = self.service.repo.get_task("cast-task")["assets"][voice_casting.AUDITIONS_KEY]["沈知微"]
        self.assertEqual(len(stored), 2)

    def test_a_character_without_a_voice_prompt_or_an_unknown_name_is_refused(self):
        with self.assertRaises(ValueError):
            self.service.audition_character_voice("cast-task", "陆行远")
        with self.assertRaises(ValueError):
            self.service.audition_character_voice("cast-task", "路人甲")
        self.assertEqual(self.studio.designs, [], "nothing was paid for")

    def test_an_edited_voice_prompt_is_auditioned_and_kept(self):
        edited = "中年男人，45岁，男声，低沉，略沙哑，咬字慢而重，语速偏慢；情绪中性；干声"
        self.service.audition_character_voice("cast-task", "陆行远", voice_prompt=edited)

        dna = voice_casting.dna_character(self.service.repo.get_task("cast-task")["assets"], "陆行远")
        self.assertEqual(dna["voice_prompt"], edited)

    def test_the_chosen_take_becomes_the_characters_voice_id(self):
        self.service.audition_character_voice("cast-task", "沈知微")

        dashboard = self.service.cast_character_voice("cast-task", "沈知微", "gen-1-2")

        created = self.studio.created[0]
        self.assertEqual(created.generated_voice_id, "gen-1-2")
        self.assertEqual(created.voice_description, VOICE_PROMPT)
        character = next(item for item in dashboard.characters if item.name == "沈知微")
        self.assertEqual(character.voice_id, "voice-for-gen-1-2")
        dna = voice_casting.dna_character(self.service.repo.get_task("cast-task")["assets"], "沈知微")
        self.assertEqual(dna["voice_take"]["generated_voice_id"], "gen-1-2")

    def test_a_take_that_was_never_auditioned_cannot_be_cast(self):
        with self.assertRaises(ValueError):
            self.service.cast_character_voice("cast-task", "沈知微", "gen-9-9")
        self.assertEqual(self.studio.created, [])

    def test_nothing_is_cast_while_a_stage_is_running(self):
        self.service.audition_character_voice("cast-task", "沈知微")
        task = self.service.repo.get_task("cast-task")
        task["status"] = "running"
        self.service.repo.save_task("cast-task", task)

        with self.assertRaises(ValueError):
            self.service.cast_character_voice("cast-task", "沈知微", "gen-1-1")
        with self.assertRaises(ValueError):
            self.service.audition_character_voice("cast-task", "沈知微")

    def test_stage_five_reads_the_designed_voice_descriptions(self):
        voices = DramaService._designed_voices(self.service.repo.get_task("cast-task"))

        self.assertEqual(voices, {"沈知微": "18岁女声，清亮带气声，语速偏快"})


class StageThreeVoiceDesignTests(unittest.TestCase):
    def test_the_dna_breakdown_asks_for_a_designed_dry_voice_per_character(self):
        captured = {}

        class Gateway:
            def call_llm(self, model, sys_prompt, user_prompt, *args, **kwargs):
                captured["sys"] = sys_prompt
                return '{"characters": []}'

        service = DramaService()
        service.gateway = Gateway()
        service._extract_character_dna_breakdown({"llm_model": "x"}, "暗室回声", "写实", "电影感", "## 沈知微")

        prompt = captured["sys"]
        self.assertIn('"voice_prompt"', prompt)
        self.assertIn('"voice_desc"', prompt)
        for part in ("身份", "性别", "年龄", "音高", "音色质感", "咬字", "语速", "情绪保持中性", "干声", "不含音乐、音效、环境声与混响"):
            self.assertIn(part, prompt)
        self.assertIn("40字以内", prompt)

    def test_a_silent_model_leaves_a_post_audio_plan(self):
        plan = DramaService._post_audio_plan("林夏：你来了。", "环境音：雨声；动作音：关门")

        self.assertEqual(plan, {
            "dialogue": "tts", "ambience": ["雨声"], "effects": ["关门"], "effects_pass_needed": True,
        })
        self.assertEqual(DramaService._post_audio_plan("", "")["effects_pass_needed"], False)


class CastingApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original = (drama_api.service.repo, drama_api.service.voice_studio)
        self.addCleanup(self._restore)
        drama_api.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.studio = FakeStudio()
        drama_api.service.voice_studio = self.studio
        drama_api.service.repo.save_task("cast-task", _task())
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "cast-user", "role": "user"}
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def _restore(self):
        drama_api.service.repo, drama_api.service.voice_studio = self.original

    def test_audition_then_cast(self):
        audition = self.client.post("/api/drama/cast-task/characters/voice/audition", json={"name": "沈知微"})
        self.assertEqual(audition.status_code, 200)
        take = audition.json()["previews"][0]["generated_voice_id"]

        cast = self.client.post(
            "/api/drama/cast-task/characters/voice/cast", json={"name": "沈知微", "generated_voice_id": take},
        )

        self.assertEqual(cast.status_code, 200)
        character = next(item for item in cast.json()["characters"] if item["name"] == "沈知微")
        self.assertEqual(character["voiceId"], f"voice-for-{take}")

    def test_refusals_and_other_owners(self):
        missing = self.client.post("/api/drama/cast-task/characters/voice/audition", json={"name": "陆行远"})
        self.assertEqual(missing.status_code, 422)
        unknown_take = self.client.post(
            "/api/drama/cast-task/characters/voice/cast", json={"name": "沈知微", "generated_voice_id": "nope"},
        )
        self.assertEqual(unknown_take.status_code, 422)
        drama_api.service.repo.save_task("someone-else", {**_task("someone-else"), "owner_user_id": "other"})
        hidden = self.client.post("/api/drama/someone-else/characters/voice/audition", json={"name": "沈知微"})
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(self.studio.designs, [])

    def test_a_provider_failure_is_a_502(self):
        def broken(request):
            raise RuntimeError("upstream down")

        self.studio.design_voice = broken
        response = self.client.post("/api/drama/cast-task/characters/voice/audition", json={"name": "沈知微"})

        self.assertEqual(response.status_code, 502)


if __name__ == "__main__":
    unittest.main()

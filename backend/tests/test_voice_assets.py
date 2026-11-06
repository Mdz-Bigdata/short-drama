"""Voices as a project asset: the narrator stays out of the cast, and cast voices actually reach the dubbing."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import drama_api, voice_asset_api
from app.api.auth_api import get_current_user
from app.core import media_compositor, voice_casting
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService

TAKE = {"generated_voice_id": "gen-1", "url": "/media/preview1.mp3", "duration_secs": 4.2, "audio_base_64": "never-stored"}


class VoiceAssetRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.task_id = "task-voice"
        self.service.repo.save_task(self.task_id, {
            "task_id": self.task_id, "owner_user_id": "u-1", "config": {"title_suggestion": "雨夜"},
            "assets": {"3_dna": {"characters": [{"name": "林夏", "voice_prompt": "二十八岁女声，音色清亮微冷，语速偏快，干声，情绪中性", "voice_desc": "清亮"}]},
                       "3_characters": [{"name": "周牧"}]},
        })
        patcher = patch.object(drama_api, "service", self.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.studio = MagicMock()
        self.studio.design_voice.return_value = {"previews": [TAKE]}
        self.studio.create_designed_voice.return_value = {"voice_id": "voice-narrator"}
        self.service.voice_studio = self.studio
        app = FastAPI()
        app.include_router(voice_asset_api.router)
        app.dependency_overrides[drama_api.require_owned_drama_task] = lambda: {"user_id": "u-1", "role": "user"}
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-1", "role": "user"}
        self.client = TestClient(app)
        self.base = f"/api/drama/{self.task_id}/voices"

    def _assets(self):
        return self.service.repo.get_task(self.task_id)["assets"]

    def test_lists_every_character_and_a_default_narrator(self):
        body = self.client.get(self.base).json()
        self.assertEqual([c["name"] for c in body["characters"]], ["林夏", "周牧"])
        self.assertEqual(body["characters"][0]["voice_desc"], "清亮")
        self.assertEqual(body["characters"][1]["voice_prompt"], "")
        self.assertEqual(body["narrator"]["voice_id"], "")
        self.assertGreaterEqual(len(body["narrator"]["voice_prompt"]), voice_casting.MIN_VOICE_PROMPT_CHARS)
        self.assertEqual(body["narration_delivery"], "use_tts")
        self.assertEqual(self.client.get("/api/drama/none/voices").status_code, 404)

    def test_narrator_audition_and_cast_stay_out_of_the_character_cast(self):
        auditioned = self.client.post(f"{self.base}/narrator/audition", json={})
        self.assertEqual(auditioned.status_code, 200, auditioned.text)
        take = auditioned.json()["narrator"]["rounds"][0]["previews"][0]
        self.assertEqual(take["generated_voice_id"], "gen-1")
        self.assertNotIn("audio_base_64", take)
        self.studio.design_voice.assert_called_once()

        cast = self.client.post(f"{self.base}/narrator/cast", json={"generated_voice_id": "gen-1"})
        self.assertEqual(cast.status_code, 200, cast.text)
        self.assertEqual(cast.json()["narrator"]["voice_id"], "voice-narrator")
        self.assertEqual(cast.json()["narrator"]["take"]["url"], "/media/preview1.mp3")
        self.assertEqual(self.studio.create_designed_voice.call_args.args[0].voice_name, "雨夜·旁白")
        self.assertNotIn("旁白", [c["name"] for c in self._assets()["3_dna"]["characters"]])

    def test_a_take_never_auditioned_cannot_be_cast(self):
        response = self.client.post(f"{self.base}/narrator/cast", json={"generated_voice_id": "made-up"})
        self.assertEqual(response.status_code, 422)
        self.studio.create_designed_voice.assert_not_called()

    def test_an_existing_voice_can_narrate_without_paying_and_be_cleared(self):
        chosen = self.client.put(f"{self.base}/narrator", json={"voice_id": "lib-7", "label": "Rachel"})
        self.assertEqual(chosen.status_code, 200, chosen.text)
        self.assertEqual((chosen.json()["narrator"]["voice_id"], chosen.json()["narrator"]["source"]), ("lib-7", "existing"))
        self.studio.design_voice.assert_not_called()
        self.assertEqual(self.client.delete(f"{self.base}/narrator").json()["narrator"]["voice_id"], "")
        self.assertNotIn(voice_casting.NARRATOR_KEY, self._assets())

    def test_nothing_changes_while_a_stage_runs(self):
        self.service.repo.mutate_task(self.task_id, lambda task: task.update(status="running"))
        for response in (
            self.client.post(f"{self.base}/narrator/audition", json={}),
            self.client.post(f"{self.base}/narrator/cast", json={"generated_voice_id": "gen-1"}),
            self.client.put(f"{self.base}/narrator", json={"voice_id": "x"}),
            self.client.delete(f"{self.base}/narrator"),
        ):
            self.assertEqual(response.status_code, 409)
        self.studio.design_voice.assert_not_called()

    def test_a_provider_failure_is_a_safe_502(self):
        self.studio.design_voice.side_effect = RuntimeError("secret key abc")
        response = self.client.post(f"{self.base}/narrator/audition", json={})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret", response.text)


class CastVoicesReachTheDubbingTests(unittest.TestCase):
    def _dub(self, voices, segments):
        client = MagicMock()
        client.create_dialogue.return_value = b"audio"
        with patch.object(media_compositor, "_elevenlabs_available", return_value=True), \
             patch.object(media_compositor, "_elevenlabs_voices", return_value=("default-f", "default-m")), \
             patch("app.core.providers.elevenlabs.ElevenLabsClient", return_value=client), \
             patch.object(media_compositor, "_save_provider_audio", return_value=("u", "/p.mp3")), \
             media_compositor.bind_speaker_voices(voices):
            media_compositor.synthesize_elevenlabs_dialogue_track(segments)
        return [line.voice_id for line in client.create_dialogue.call_args.args[0]]

    def test_cast_and_narrator_voices_are_used_and_others_keep_the_defaults(self):
        assets = {"3_dna": {"characters": [{"name": "林夏", "voice_id": "v-lin"}, {"name": "周牧"}]}}
        voice_casting.set_narrator_voice(assets, voice_id="v-narr", source="existing")
        voices = voice_casting.speaker_voice_map(assets)
        used = self._dub(voices, [
            ("你好", "female", "neutral", "林夏"), ("再见", "male", "neutral", "周牧"),
            ("那一夜", "female", "neutral", "旁白"), ("多年后", "female", "neutral", "画外音"),
        ])
        self.assertEqual(used, ["v-lin", "default-m", "v-narr", "v-narr"])

    def test_with_nothing_cast_dubbing_is_unchanged(self):
        self.assertEqual(self._dub({}, [("你好", "male", "neutral", "林夏")]), ["default-m"])

    def test_a_stage_runs_with_the_projects_voices_bound(self):
        service = DramaService()
        seen = {}

        def capture(*_args, **_kwargs):
            seen.update(media_compositor._speaker_voices.get())
            return {}

        claimed = {"task_id": "t", "assets": {"3_dna": {"characters": [{"name": "林夏", "voice_id": "v-lin"}]}}}
        with patch.object(service, "_execute_stage_blocking", side_effect=capture):
            service._execute_claimed_stage_blocking("t", 5, claimed)
        self.assertEqual(seen, {"林夏": "v-lin"})
        self.assertEqual(dict(media_compositor._speaker_voices.get()), {})


if __name__ == "__main__":
    unittest.main()

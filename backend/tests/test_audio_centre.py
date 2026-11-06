# -*- coding: utf-8 -*-
"""配音与文本、图像、视频同一口径：模型配置中心优先，中心没有音频模型时才用配置文件里的。"""

import unittest
from unittest.mock import patch

from app.core import media_compositor as mc
from app.platform.runtime_models import RuntimeModelConfiguration, runtime_model_registry


def _centre(*configs):
    previous = list(runtime_model_registry.list("text") + runtime_model_registry.list("image")
                    + runtime_model_registry.list("video") + runtime_model_registry.list("audio"))
    runtime_model_registry.replace(list(configs))
    return previous


def _audio(provider="elevenlabs", models=("eleven_multilingual_v2",)):
    return RuntimeModelConfiguration(configuration_id="a1", category="audio", provider=provider, base_url="https://api.test",
                                     api_key="k", model_ids=tuple(models))


class EffectiveAudioModelTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(runtime_model_registry.replace, _centre())

    def test_the_centre_model_wins_over_the_project_or_config_file(self):
        runtime_model_registry.replace([_audio()])
        self.assertEqual(mc.effective_audio_model("edge-tts"), ("elevenlabs", "eleven_multilingual_v2"))
        self.assertEqual(mc.effective_audio_model("eleven_multilingual_v2"), ("elevenlabs", "eleven_multilingual_v2"))

    def test_without_centre_audio_models_the_config_file_model_is_used(self):
        runtime_model_registry.replace([])
        self.assertEqual(mc.effective_audio_model("edge-tts"), ("", "edge-tts"))
        self.assertEqual(mc.effective_audio_model("eleven_v3"), ("elevenlabs", "eleven_v3"))

    def test_a_centre_elevenlabs_model_drives_the_dialogue_track(self):
        runtime_model_registry.replace([_audio()])
        with patch.object(mc, "synthesize_elevenlabs_dialogue_track", return_value=("u", "/p.mp3")) as eleven, \
             patch.object(mc, "synthesize_dialogue_track", return_value=("l", "/l.mp3")) as local:
            self.assertEqual(mc.synthesize_preferred_dialogue_track([("你好", "female")], tts_model="edge-tts"), ("u", "/p.mp3"))
        eleven.assert_called_once()
        local.assert_not_called()


class AccountVoiceTests(unittest.TestCase):
    def setUp(self):
        mc._ACCOUNT_VOICES.clear()
        self.addCleanup(mc._ACCOUNT_VOICES.clear)
        self.addCleanup(runtime_model_registry.replace, _centre(_audio()))

    def test_without_env_voice_ids_the_account_voice_library_is_used_once(self):
        voices = {"voices": [{"voice_id": "m1", "labels": {"gender": "male"}}, {"voice_id": "f1", "labels": {"gender": "female"}},
                             {"voice_id": "f2", "labels": {"gender": "female"}}]}
        with patch.dict("os.environ", {"ELEVENLABS_VOICE_FEMALE_ID": "", "ELEVENLABS_VOICE_MALE_ID": ""}), \
             patch("app.core.providers.elevenlabs.ElevenLabsClient.list_voices", return_value=voices) as listing:
            self.assertEqual(mc._elevenlabs_voices(), ("f1", "m1"))
            self.assertEqual(mc._elevenlabs_voices(), ("f1", "m1"))
        listing.assert_called_once()

    def test_env_voice_ids_still_win(self):
        with patch.dict("os.environ", {"ELEVENLABS_VOICE_FEMALE_ID": "F", "ELEVENLABS_VOICE_MALE_ID": "M"}):
            self.assertEqual(mc._elevenlabs_voices(), ("F", "M"))


if __name__ == "__main__":
    unittest.main()

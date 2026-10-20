import unittest

from pydantic import ValidationError

from app.schema.elevenlabs import (
    PronunciationDictionaryCreateRequest,
    PronunciationRule,
    SpeechEngineCreateRequest,
    VoiceCreateRequest,
    VoiceDesignRequest,
)
from app.schema.production import TTSRequest
from main import app


class ElevenLabsContractTests(unittest.TestCase):
    def test_voice_design_requires_text_or_explicit_auto_generation(self):
        with self.assertRaises(ValidationError):
            VoiceDesignRequest(
                voice_description="A calm cinematic narrator with a warm restrained delivery"
            )
        request = VoiceDesignRequest(
            voice_description="A calm cinematic narrator with a warm restrained delivery",
            auto_generate_text=True,
        )
        self.assertEqual(request.model_id, "eleven_ttv_v3")
        created = VoiceCreateRequest(
            voice_name="Drama narrator",
            voice_description="A restrained and cinematic dramatic narrator",
            generated_voice_id="generated-voice-1",
            labels={"use_case": "short drama"},
        )
        self.assertEqual(created.labels["use_case"], "short drama")

    def test_speech_engine_rejects_local_or_insecure_upstream(self):
        for ws_url in ("ws://agent.example/ws", "wss://127.0.0.1/ws"):
            with self.subTest(ws_url=ws_url), self.assertRaises(ValidationError):
                SpeechEngineCreateRequest(
                    ws_url=ws_url,
                    voice_id="voice-1",
                )

    def test_pronunciation_rules_are_strictly_discriminated(self):
        alias = PronunciationRule(
            type="alias", string_to_replace="林夏", alias="林霞"
        )
        phoneme = PronunciationRule(
            type="phoneme", string_to_replace="Drama", phoneme="ˈdrɑːmə",
            alphabet="ipa",
        )
        dictionary = PronunciationDictionaryCreateRequest(
            name="短剧角色名", rules=[alias, phoneme]
        )
        self.assertEqual(len(dictionary.rules), 2)
        with self.assertRaises(ValidationError):
            PronunciationRule(
                type="alias", string_to_replace="错误", phoneme="wrong", alphabet="ipa"
            )

    def test_tts_accepts_at_most_three_pronunciation_dictionaries(self):
        locator = {
            "pronunciation_dictionary_id": "dictionary-1",
            "version_id": "version-1",
        }
        request = TTSRequest(
            text="林夏走进雨夜。",
            voice_id="voice-1",
            pronunciation_dictionary_locators=[locator],
        )
        self.assertEqual(len(request.pronunciation_dictionary_locators), 1)
        with self.assertRaises(ValidationError):
            TTSRequest(
                text="林夏走进雨夜。",
                voice_id="voice-1",
                pronunciation_dictionary_locators=[locator] * 4,
            )

    def test_all_capability_routes_are_present_in_openapi(self):
        paths = app.openapi()["paths"]
        expected = {
            "/api/production/audio/capabilities",
            "/api/production/audio/voices",
            "/api/production/audio/speech-engines",
            "/api/production/audio/tts",
            "/api/production/audio/transcribe",
            "/api/production/audio/music",
            "/api/production/audio/dialogue",
            "/api/production/audio/voice-changer",
            "/api/production/audio/voice-design",
            "/api/production/audio/voice-design/voices",
            "/api/production/audio/sound-effect",
            "/api/production/audio/isolation",
            "/api/production/audio/dub",
            "/api/production/audio/forced-alignment",
            "/api/production/audio/pronunciation-dictionaries",
            "/api/production/audio/audio-native",
        }
        self.assertTrue(expected.issubset(paths))


if __name__ == "__main__":
    unittest.main()

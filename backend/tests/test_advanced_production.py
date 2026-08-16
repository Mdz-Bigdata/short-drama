import unittest

from pydantic import ValidationError

from app.audio.mix_plan import AudioMixPlanner
from app.core.capability_manifest import capability_implementation_report
from app.core.performance import PerformancePlanner
from app.core.providers.capabilities import ProviderCapabilityRegistry
from app.core.providers.elevenlabs_capabilities import ELEVENLABS_CAPABILITIES
from app.schema.advanced import (
    AudioMixRequest,
    AudioTrack,
    PerformancePlanRequest,
)
from app.schema.production import H3VideoRequest


class PerformancePlannerTests(unittest.TestCase):
    def test_builds_motivation_first_observable_acting_and_voice_beats(self):
        request = PerformancePlanRequest(
            character="林夏",
            duration_seconds=6,
            motivation="不让对方看出自己已经绝望",
            trigger="看到信封上的退回标记",
            start_emotion="克制的期待",
            end_emotion="失落后的强装平静",
            dialogue="我知道了。",
            power_shift="从等待答案转为主动结束谈话",
        )
        plan = PerformancePlanner().build(request)

        self.assertEqual(plan.character, "林夏")
        self.assertEqual(plan.beats[0].phase, "trigger")
        self.assertEqual(plan.beats[-1].phase, "release")
        self.assertTrue(all(beat.start_seconds < beat.end_seconds for beat in plan.beats))
        self.assertLessEqual(plan.beats[-1].end_seconds, 6)
        joined = " ".join(
            f"{beat.gaze} {beat.breath} {beat.face} {beat.body} {beat.voice}" for beat in plan.beats
        )
        self.assertIn("视线", joined)
        self.assertIn("呼吸", joined)
        self.assertIn("停顿", joined)
        self.assertIn("不改变身份", " ".join(plan.identity_constraints))

    def test_rejects_duration_too_short_for_dialogue_performance(self):
        with self.assertRaises(ValidationError):
            PerformancePlanRequest(
                character="林夏", duration_seconds=1,
                motivation="隐藏情绪", trigger="看到信封",
                start_emotion="期待", end_emotion="失落",
                dialogue="这一句对白不可能在一秒内完成且保留自然反应。",
            )


class ProviderNegotiationTests(unittest.TestCase):
    def test_registry_exposes_h3_and_all_elevenlabs_audio_capabilities(self):
        registry = ProviderCapabilityRegistry()
        capabilities = registry.list()
        self.assertIn("minimax_h3", capabilities)
        self.assertEqual(
            set(capabilities["minimax_audio"].operations),
            {"tts", "music_generation", "music_cover"},
        )
        for provider in ("seedance", "kling", "grok", "happyhorse", "ltx_2_3"):
            self.assertIn(provider, capabilities)
        self.assertEqual(
            set(capabilities["elevenlabs"].operations),
            {
                "tts", "tts_with_timestamps", "dialogue", "dialogue_with_timestamps",
                "sound_effect", "music", "video_to_music", "speech_to_text", "dubbing",
                "voices_list", "speech_engine_list", "speech_engine_create",
                "voice_changer", "voice_design", "audio_isolation", "forced_alignment",
                "pronunciation_dictionary_list", "pronunciation_dictionary_create",
                "audio_native",
            },
        )
        self.assertEqual(len(ELEVENLABS_CAPABILITIES), 14)
        self.assertEqual(
            {item.id for item in ELEVENLABS_CAPABILITIES},
            {
                "text_to_speech", "speech_to_text", "music", "speech_engine", "voices",
                "text_to_dialogue", "voice_changer", "voice_design", "sound_effects",
                "audio_isolation", "dubbing", "forced_alignment",
                "pronunciation_dictionaries", "audio_native",
            },
        )
        request = H3VideoRequest(
            prompt="角色沿动作轴线转身",
            first_frame="https://cdn.example/first.png",
            last_frame="https://cdn.example/last.png",
            duration_seconds=8,
        )
        decision = registry.negotiate_h3(request)
        self.assertTrue(decision.compatible)
        self.assertEqual(decision.mode, "first_last_frame")


class AudioMixPlannerTests(unittest.TestCase):
    def test_dialogue_ducks_bgm_and_final_mix_is_loudness_limited(self):
        request = AudioMixRequest(
            duration_ms=8000,
            tracks=[
                AudioTrack(id="dialogue-1", kind="dialogue", uri="dialogue.wav", start_ms=1000, duration_ms=3000),
                AudioTrack(id="bgm-1", kind="bgm", uri="music.wav", start_ms=0, duration_ms=8000),
                AudioTrack(id="sfx-1", kind="sfx", uri="rain.wav", start_ms=0, duration_ms=8000),
            ],
        )
        plan = AudioMixPlanner().plan(request)

        self.assertTrue(plan.dialogue_windows)
        self.assertIn("sidechaincompress", plan.ffmpeg_filter_complex)
        self.assertIn("loudnorm", plan.ffmpeg_filter_complex)
        self.assertIn("alimiter", plan.ffmpeg_filter_complex)
        self.assertEqual(plan.target_lufs, -16.0)
        self.assertEqual(len(plan.tracks), 3)


class CapabilityImplementationTests(unittest.TestCase):
    def test_every_requested_source_has_callable_implementation_entries(self):
        report = capability_implementation_report()
        self.assertEqual(len(report), 13)
        self.assertTrue(all(row["implementations"] for row in report))
        self.assertTrue(all(
            all(item["entrypoint"].startswith("/") or "." in item["entrypoint"] for item in row["implementations"])
            for row in report
        ))


class AdvancedApiContractTests(unittest.TestCase):
    def test_advanced_production_routes_are_registered(self):
        from app.api.production_api import router

        paths = {route.path for route in router.routes}
        self.assertTrue({
            "/api/production/providers",
            "/api/production/video/route",
            "/api/production/performance/plan",
            "/api/production/audio/mix/plan",
            "/api/production/capabilities/report",
            "/api/production/preproduction/novel-analyze",
            "/api/production/preproduction/episodes/index",
            "/api/production/preproduction/voice/plan",
            "/api/production/readiness/evaluate",
            "/api/production/failures/normalize",
            "/api/production/analytics/summarize",
            "/api/production/audio/minimax/tts",
            "/api/production/audio/minimax/music",
            "/api/production/audio/minimax/music-cover",
        }.issubset(paths))


if __name__ == "__main__":
    unittest.main()

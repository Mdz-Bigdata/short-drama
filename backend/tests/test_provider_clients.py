import io
import json
import os
import unittest
from unittest.mock import patch

import httpx

from app.core.providers.elevenlabs import DialogueLine, ElevenLabsClient
from app.core.providers.minimax_audio import MiniMaxAudioClient
from app.core.providers.minimax_h3 import MiniMaxH3Client
from app.schema.minimax_audio import (
    MiniMaxMusicCoverRequest,
    MiniMaxMusicRequest,
    MiniMaxTTSRequest,
)
from app.schema.production import H3ReferenceBinding, H3VideoRequest


class ProviderClientTests(unittest.TestCase):
    def test_elevenlabs_requires_server_side_environment_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                ElevenLabsClient()

    def test_minimax_audio_routes_tts_music_and_one_step_cover(self):
        captured: list[tuple[str, str | None, dict]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            captured.append((
                request.url.path,
                request.headers.get("authorization"),
                payload,
            ))
            if request.url.path == "/v1/t2a_v2":
                return httpx.Response(200, json={
                    "data": {"audio": b"speech-bytes".hex(), "status": 2},
                    "trace_id": "trace-tts",
                    "extra_info": {"audio_format": "mp3"},
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                })
            return httpx.Response(200, json={
                "data": {"audio": "https://cdn.example/generated.mp3", "status": 2},
                "trace_id": "trace-music",
                "extra_info": {"music_duration": 42000},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            })

        client = MiniMaxAudioClient(
            api_key="server-test-key",
            base_url="https://api.minimaxi.com/v1/music_generation",
            transport=httpx.MockTransport(handler),
        )
        try:
            speech = client.text_to_speech(MiniMaxTTSRequest(
                model="speech-2.8-hd",
                text="今天是不是很开心呀(laughs)，当然了！",
                voice_id="male-qn-qingse",
                emotion="happy",
                pronunciation_tones=["处理/(chu3)(li3)"],
            ))
            music = client.generate_music(MiniMaxMusicRequest(
                prompt="克制、悬疑、电影感弦乐",
                is_instrumental=True,
            ))
            cover = client.cover_music(MiniMaxMusicCoverRequest(
                audio_url="https://cdn.example/original.mp3",
                prompt="爵士风格，慵懒深夜酒吧，萨克斯",
            ))
        finally:
            client.close()

        self.assertEqual(speech.audio, b"speech-bytes")
        self.assertEqual(music.audio_url, "https://cdn.example/generated.mp3")
        self.assertEqual(cover.kind, "music_cover")
        self.assertEqual([path for path, _, _ in captured], [
            "/v1/t2a_v2", "/v1/music_generation", "/v1/music_generation",
        ])
        self.assertTrue(all(auth == "Bearer server-test-key" for _, auth, _ in captured))
        tts_payload, music_payload, cover_payload = [item[2] for item in captured]
        self.assertEqual(tts_payload["model"], "speech-2.8-hd")
        self.assertEqual(tts_payload["output_format"], "hex")
        self.assertEqual(tts_payload["pronunciation_dict"]["tone"], ["处理/(chu3)(li3)"])
        self.assertEqual(music_payload["model"], "music-3.0")
        self.assertTrue(music_payload["is_instrumental"])
        self.assertEqual(music_payload["output_format"], "url")
        self.assertEqual(cover_payload["model"], "music-cover")
        self.assertEqual(cover_payload["audio_url"], "https://cdn.example/original.mp3")
        self.assertNotIn("lyrics", cover_payload)

    def test_minimax_audio_provider_errors_do_not_leak_secrets(self):
        client = MiniMaxAudioClient(
            api_key="never-leak-this-key",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "base_resp": {"status_code": 1004, "status_msg": "bad key"},
                        "trace_id": "trace-safe",
                    },
                )
            ),
        )
        try:
            with self.assertRaises(RuntimeError) as raised:
                client.generate_music(MiniMaxMusicRequest(
                    prompt="低沉的悬疑弦乐",
                    is_instrumental=True,
                ))
        finally:
            client.close()
        self.assertNotIn("never-leak-this-key", str(raised.exception))
        self.assertNotIn("bad key", str(raised.exception))
        self.assertIn("trace-safe", str(raised.exception))

    def test_elevenlabs_routes_each_capability_to_official_endpoint(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path, request.headers.get("xi-api-key")))
            if request.url.path == "/v1/speech-to-text":
                return httpx.Response(200, json={"text": "你好", "words": []})
            if request.url.path == "/v1/dubbing":
                return httpx.Response(200, json={"dubbing_id": "dub-1", "expected_duration_sec": 10})
            return httpx.Response(200, content=b"audio-bytes", headers={"content-type": "audio/mpeg"})

        client = ElevenLabsClient(
            api_key="server-test-key",
            transport=httpx.MockTransport(handler),
        )
        client.text_to_speech("你好", "voice-1", emotion="克制悲伤", speed=0.9)
        client.create_dialogue([
            DialogueLine(voice_id="voice-1", text="你来了。", emotion="压抑"),
            DialogueLine(voice_id="voice-2", text="我一直在。", emotion="温柔"),
        ])
        client.sound_effect("雨夜远处雷声", duration_seconds=4)
        client.compose_music("克制悬疑的弦乐，无人声", duration_seconds=20)
        client.transcribe(io.BytesIO(b"fake-audio"), filename="dialogue.wav", diarize=True)
        client.create_dub(source_url="https://cdn.example/film.mp4", target_language="zh")

        self.assertEqual([path for _, path, _ in seen], [
            "/v1/text-to-speech/voice-1",
            "/v1/text-to-dialogue",
            "/v1/sound-generation",
            "/v1/music",
            "/v1/speech-to-text",
            "/v1/dubbing",
        ])
        self.assertTrue(all(key == "server-test-key" for _, _, key in seen))

    def test_elevenlabs_accepts_sound_generation_endpoint_as_configured_base_url(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, content=b"sfx", headers={"content-type": "audio/mpeg"})

        client = ElevenLabsClient(
            api_key="server-test-key",
            base_url="https://api.elevenlabs.io/v1/sound-generation",
            transport=httpx.MockTransport(handler),
        )
        client.sound_effect("雨夜脚步", duration_seconds=3)

        self.assertEqual(seen, ["https://api.elevenlabs.io/v1/sound-generation"])

        with self.assertRaisesRegex(ValueError, "cannot contain credentials"):
            ElevenLabsClient(
                api_key="server-test-key",
                base_url="https://user:password@api.elevenlabs.io/v1/sound-generation",
                transport=httpx.MockTransport(handler),
            )

    def test_elevenlabs_tts_forwards_pronunciation_dictionary_locators(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(200, content=b"speech")

        client = ElevenLabsClient(
            api_key="server-test-key",
            transport=httpx.MockTransport(handler),
        )
        locators = [{
            "pronunciation_dictionary_id": "dictionary-1",
            "version_id": "version-1",
        }]
        client.text_to_speech(
            "林夏走进雨夜。", "voice-1",
            pronunciation_dictionary_locators=locators,
        )

        self.assertEqual(captured["pronunciation_dictionary_locators"], locators)

    def test_elevenlabs_routes_resource_and_audio_utility_capabilities(self):
        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path))
            if request.url.path == "/v2/voices":
                return httpx.Response(200, json={"voices": [], "has_more": False})
            if request.url.path == "/v1/speech-engine":
                return httpx.Response(200, json={"speech_engines": [], "has_more": False})
            if request.url.path == "/v1/text-to-voice/design":
                return httpx.Response(200, json={"previews": [], "text": "preview"})
            if request.url.path == "/v1/text-to-voice":
                return httpx.Response(200, json={"voice_id": "voice-created"})
            if request.url.path == "/v1/forced-alignment":
                return httpx.Response(200, json={"characters": [], "words": [], "loss": 0})
            if request.url.path == "/v1/pronunciation-dictionaries":
                return httpx.Response(200, json={"pronunciation_dictionaries": [], "has_more": False})
            if request.url.path == "/v1/pronunciation-dictionaries/add-from-rules":
                return httpx.Response(200, json={"id": "dict-1", "version_id": "v1"})
            if request.url.path == "/v1/audio-native":
                return httpx.Response(200, json={"project_id": "project-1", "html_snippet": "<div></div>"})
            return httpx.Response(200, content=b"audio-bytes")

        client = ElevenLabsClient(
            api_key="server-test-key",
            transport=httpx.MockTransport(handler),
        )
        client.list_voices()
        client.list_speech_engines()
        client.create_speech_engine(
            name="Drama", ws_url="wss://agent.example/ws", voice_id="voice-1",
            model_id="eleven_flash_v2_5", language="zh", tags=["production"],
        )
        client.voice_change(
            io.BytesIO(b"input"), filename="voice.wav", voice_id="voice-1"
        )
        client.design_voice(
            voice_description="A restrained dramatic narrator voice",
            text="This is a sufficiently long preview text for the generated dramatic character voice.",
            auto_generate_text=False, model_id="eleven_ttv_v3", seed=7,
            guidance_scale=5, should_enhance=True,
        )
        client.create_designed_voice(
            voice_name="Drama narrator",
            voice_description="A restrained and cinematic dramatic narrator",
            generated_voice_id="generated-voice-1",
            labels={"use_case": "short drama"},
        )
        client.isolate_audio(io.BytesIO(b"input"), filename="noisy.wav")
        client.force_align(
            io.BytesIO(b"input"), filename="line.wav", text="你终于来了。"
        )
        client.list_pronunciation_dictionaries()
        client.create_pronunciation_dictionary(
            name="角色名", description="", rules=[{
                "type": "alias", "string_to_replace": "林夏", "alias": "林霞",
            }],
        )
        client.create_audio_native(name="Article")

        self.assertEqual([path for _, path in seen], [
            "/v2/voices",
            "/v1/speech-engine",
            "/v1/speech-engine",
            "/v1/speech-to-speech/voice-1",
            "/v1/text-to-voice/design",
            "/v1/text-to-voice",
            "/v1/audio-isolation",
            "/v1/forced-alignment",
            "/v1/pronunciation-dictionaries",
            "/v1/pronunciation-dictionaries/add-from-rules",
            "/v1/audio-native",
        ])

    def test_minimax_h3_serializes_multimodal_references_without_secret_leak(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["authorization"] = request.headers.get("authorization")
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"task_id": "h3-task-1", "status": "queued"})

        client = MiniMaxH3Client(
            api_key="server-test-key",
            transport=httpx.MockTransport(handler),
        )
        result = client.create_video(H3VideoRequest(
            prompt="按动作视频跟拍角色，保留声音节奏",
            reference_images=["https://cdn.example/character.png"],
            reference_videos=["https://cdn.example/action.mp4"],
            reference_audios=["https://cdn.example/voice.mp3"],
            duration_seconds=8,
        ))
        self.assertEqual(captured["path"], "/v2/video_generation")
        self.assertEqual(captured["authorization"], "Bearer server-test-key")
        self.assertEqual(result.task_id, "h3-task-1")
        self.assertNotIn("server-test-key", json.dumps(result.model_dump()))
        self.assertNotIn("media_inputs", captured["payload"])
        self.assertEqual(
            [item["type"] for item in captured["payload"]["content"]],
            ["text", "image_url", "video_url", "audio_url"],
        )
        self.assertEqual(
            [item.get("role") for item in captured["payload"]["content"][1:]],
            ["reference_image", "reference_video", "reference_audio"],
        )

    def test_minimax_h3_maps_structured_references_without_internal_lineage(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"task_id": "h3-structured-1", "status": "queued"})

        client = MiniMaxH3Client(api_key="server-test-key", transport=httpx.MockTransport(handler))
        client.create_video(H3VideoRequest(
            prompt="保持人物身份，复用动作方向",
            reference_bindings=[
                H3ReferenceBinding(
                    slot_id="identity-1", order=1, media_type="image",
                    uri="https://cdn.example/identity.png", role="identity", priority=100,
                    content_sha256="d" * 64, provenance="asset:character:v2",
                ),
                H3ReferenceBinding(
                    slot_id="motion-1", order=2, media_type="video",
                    uri="https://cdn.example/motion.mp4", role="motion", priority=70,
                    content_sha256="e" * 64, provenance="reference:motion:v1",
                ),
            ],
            duration_seconds=8,
        ))

        content = captured["payload"]["content"]
        self.assertEqual(content[1]["image_url"]["url"], "https://cdn.example/identity.png")
        self.assertEqual(content[1]["role"], "reference_image")
        self.assertEqual(content[2]["video_url"]["url"], "https://cdn.example/motion.mp4")
        self.assertEqual(content[2]["role"], "reference_video")
        self.assertNotIn("content_sha256", json.dumps(captured["payload"]))

    def test_minimax_h3_serializes_first_and_last_frames_as_content_roles(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"task_id": "h3-frame-task"})

        client = MiniMaxH3Client(api_key="server-test-key", transport=httpx.MockTransport(handler))
        client.create_video(H3VideoRequest(
            prompt="女孩从童年成长为成年",
            first_frame="https://cdn.example/first.png",
            last_frame="https://cdn.example/last.png",
            duration_seconds=5,
            resolution="2k",
        ))

        self.assertEqual(captured["payload"]["resolution"], "2K")
        self.assertNotIn("ratio", captured["payload"])
        self.assertEqual(
            [item.get("role") for item in captured["payload"]["content"][1:]],
            ["first_frame", "last_frame"],
        )

    def test_elevenlabs_timing_and_video_to_music_use_current_official_endpoints(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            if request.url.path.endswith("with-timestamps"):
                return httpx.Response(200, json={
                    "audio_base64": "YXVkaW8=",
                    "alignment": {
                        "characters": ["你"],
                        "character_start_times_seconds": [0],
                        "character_end_times_seconds": [0.2],
                    },
                    "voice_segments": [],
                })
            return httpx.Response(200, content=b"music", headers={"content-type": "audio/mpeg"})

        client = ElevenLabsClient(api_key="server-test-key", transport=httpx.MockTransport(handler))
        speech = client.text_to_speech_with_timestamps("你好", "voice-1")
        dialogue = client.create_dialogue_with_timestamps([
            DialogueLine(voice_id="voice-1", text="你好", emotion="克制")
        ])
        music = client.video_to_music(
            [("shot.mp4", io.BytesIO(b"fake-video"))],
            description="克制悬疑弦乐", tags=["cinematic", "restrained"],
        )

        self.assertEqual(speech["audio"], b"audio")
        self.assertIn("alignment", dialogue)
        self.assertEqual(music, b"music")
        self.assertEqual(seen, [
            "/v1/text-to-speech/voice-1/with-timestamps",
            "/v1/text-to-dialogue/with-timestamps",
            "/v1/music/video-to-music",
        ])

    def test_minimax_h3_does_not_treat_echoed_reference_as_output_video(self):
        result = MiniMaxH3Client._result({
            "task_id": "h3-task-2",
            "status": "queued",
            "request": {"media_inputs": [{"type": "video", "url": "https://cdn.example/reference.mp4"}]},
        })
        self.assertIsNone(result.video_url)

        completed = MiniMaxH3Client._result({
            "task_id": "h3-task-2",
            "status": "completed",
            "output": {"url": "https://cdn.example/generated.mp4"},
        })
        self.assertEqual(completed.video_url, "https://cdn.example/generated.mp4")

    def test_minimax_h3_uses_v2_task_path_and_reads_task_content_url(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, json={
                "task": {
                    "task_id": "h3-task-v2",
                    "status": "succeeded",
                    "content": {"url": "https://cdn.example/generated-v2.mp4"},
                },
            })

        client = MiniMaxH3Client(
            api_key="server-test-key",
            transport=httpx.MockTransport(handler),
        )
        result = client.get_task("h3-task-v2")

        self.assertEqual(seen, ["/v2/query/video_generation/h3-task-v2"])
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.video_url, "https://cdn.example/generated-v2.mp4")

    def test_minimax_h3_resolves_completed_file_id_to_download_url(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.url.path, request.url.params.get("task_id"), request.url.params.get("file_id")))
            if request.url.path == "/v1/query/video_generation":
                return httpx.Response(200, json={
                    "task_id": "h3-task-3", "status": "Success", "file_id": "file-3",
                })
            return httpx.Response(200, json={
                "file": {"download_url": "https://cdn.example/generated-3.mp4"},
            })

        client = MiniMaxH3Client(
            api_key="server-test-key",
            status_url_template="https://api.minimaxi.com/v1/query/video_generation?task_id={task_id}",
            files_url="https://api.minimaxi.com/v1/files/retrieve",
            transport=httpx.MockTransport(handler),
        )
        result = client.get_task("h3-task-3")

        self.assertEqual(result.video_url, "https://cdn.example/generated-3.mp4")
        self.assertEqual(seen, [
            ("/v1/query/video_generation", "h3-task-3", None),
            ("/v1/files/retrieve", None, "file-3"),
        ])


if __name__ == "__main__":
    unittest.main()

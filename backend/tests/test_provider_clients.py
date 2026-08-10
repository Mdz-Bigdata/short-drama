import io
import json
import os
import unittest
from unittest.mock import patch

import httpx

from app.core.providers.elevenlabs import DialogueLine, ElevenLabsClient
from app.core.providers.minimax_h3 import MiniMaxH3Client
from app.schema.production import H3VideoRequest


class ProviderClientTests(unittest.TestCase):
    def test_elevenlabs_requires_server_side_environment_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                ElevenLabsClient()

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
        self.assertEqual(len(captured["payload"]["media_inputs"]), 3)

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

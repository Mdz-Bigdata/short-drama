"""What the pipeline does when a script, a storyboard or a setting gives it nothing to work with."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import Response
from fastapi.testclient import TestClient

from app import settings
from app.api import auth_api
from app.core import media_compositor
from app.core.model_gateway import ModelGateway
from app.core.providers.minimax_h3 import MiniMaxH3Client
from app.core.writer_dashboard import compile_writer_dashboard
from app.ingest.parsers import SourceIngestError, SourceIngestor
from app.platform.runtime_models import (
    RuntimeModelConfiguration,
    provider_key_available,
    runtime_model_registry,
)
from app.repository.task_repo import TaskRepository
from app.schema.auth import SendCodeRequest
from app.schema.drama import EPISODE_COUNT_MAX
from app.service.drama_service import (
    SKIP_SPEAKERS,
    DramaService,
    extract_character_info,
    extract_speech,
    parse_shot_dialogue,
)
from main import app
from tests.test_writer_dashboard import _task


class InventedContentTests(unittest.TestCase):
    def test_a_character_the_outline_only_names_gets_no_invented_wardrobe(self):
        name, look, rival, rival_look = extract_character_info("核心角色：顾沉渊\n对手角色：林婉儿")

        self.assertEqual((name, rival), ("顾沉渊", "林婉儿"))
        self.assertEqual((look, rival_look), ("", ""))

    def test_a_described_character_keeps_the_outline_description(self):
        outline = "- **沈知微**：\n特征描述：素色襦裙，眉心一点朱砂\n\n- **萧景行**：\n特征描述：玄色劲装，左手缠布"

        name, look, rival, rival_look = extract_character_info(outline)

        self.assertEqual((name, look), ("沈知微", "素色襦裙，眉心一点朱砂"))
        self.assertEqual((rival, rival_look), ("萧景行", "玄色劲装，左手缠布"))

    def test_a_script_without_dialogue_yields_no_line_to_voice(self):
        self.assertEqual(extract_speech(""), "")
        self.assertEqual(extract_speech("空镜，雨落在石阶上"), "")
        self.assertEqual(extract_speech("林夏：你到底隐瞒了什么？"), "你到底隐瞒了什么？")

    def test_soundtrack_labels_are_never_voiced_as_a_character(self):
        self.assertIn("ost", SKIP_SPEAKERS)
        lines = parse_shot_dialogue("OST：主题曲渐起 林夏：别回头。", "林夏", "周教授", "female", "male")

        self.assertEqual([line[0] for line in lines], ["别回头。"])


class EpisodeProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("writer-task-1", _task())
        self.service = DramaService()
        self.service.repo = self.repo

    def test_saving_a_long_script_keeps_every_episode(self):
        episodes = 30
        script = "\n".join(f"第{index}集 标题{index}\n场景1：室内\n林夏：第{index}句。" for index in range(1, episodes + 1))
        source_hash = compile_writer_dashboard(self.repo.get_task("writer-task-1")).source_hash

        self.service.update_script(
            "writer-task-1", content=script, expected_source_hash=source_hash,
            confirm_invalidate=True, owner_user_id="writer-user",
        )

        stored = self.repo.get_task("writer-task-1")
        self.assertGreater(EPISODE_COUNT_MAX, episodes)
        self.assertEqual(stored["total_episodes"], episodes)
        self.assertEqual(stored["config"]["episode_count"], episodes)
        self.assertNotIn("第13集", stored["episodes"][11]["script"])

    def test_a_failed_episode_is_recorded_instead_of_running_forever(self):
        failure = RuntimeError("provider rejected the request api_key=sk-secret-value-123456")
        with patch.object(self.service, "_produce_episode_blocking", side_effect=failure):
            with self.assertRaises(RuntimeError):
                asyncio.run(self.service.produce_episode("writer-task-1", 2))

        episode = self.repo.get_task("writer-task-1")["episodes"][1]
        self.assertEqual(episode["status"], "failed")
        self.assertIn("provider rejected", episode["fail_reason"])
        self.assertNotIn("sk-secret-value-123456", episode["fail_reason"])

    def test_an_unparseable_storyboard_stops_before_any_paid_generation(self):
        task = self.repo.get_task("writer-task-1")
        task["episodes"][1]["script"] = "第2集 实验室\n周教授：现在回头还来得及。"
        task["config"]["llm_model"] = "deepseek"
        self.repo.save_task("writer-task-1", task)

        with (
            patch.object(self.service.gateway, "call_llm", return_value="模型没有给出表格"),
            patch.object(self.service.gateway, "generate_image") as image,
            patch.object(self.service.gateway, "generate_video") as video,
        ):
            with self.assertRaisesRegex(ValueError, "第2集分镜表未解析出镜头"):
                self.service._produce_episode_blocking("writer-task-1", 2)

        image.assert_not_called()
        video.assert_not_called()


class DeploymentKnobTests(unittest.TestCase):
    def test_integer_knobs_clamp_and_fall_back(self):
        with patch.dict(os.environ, {"KNOB": "7"}):
            self.assertEqual(settings.env_int("KNOB", 3, minimum=1, maximum=5), 5)
        with patch.dict(os.environ, {"KNOB": "0"}):
            self.assertEqual(settings.env_int("KNOB", 3, minimum=1), 1)
        with patch.dict(os.environ, {"KNOB": "four"}):
            self.assertEqual(settings.env_int("KNOB", 3, minimum=1), 3)
        with patch.dict(os.environ, {"KNOB": ""}):
            self.assertEqual(settings.env_int("KNOB", 3, minimum=1), 3)

    def test_switches_and_placeholders(self):
        for off in ("0", "false", "No", " OFF "):
            with patch.dict(os.environ, {"SWITCH": off}):
                self.assertFalse(settings.env_flag("SWITCH", True))
        with patch.dict(os.environ, {"SWITCH": ""}):
            self.assertTrue(settings.env_flag("SWITCH", True))
        self.assertFalse(settings.is_configured("YOUR_DEEPSEEK_API_KEY"))
        self.assertFalse(settings.is_configured("  "))
        self.assertFalse(settings.is_configured(None))
        self.assertTrue(settings.is_configured("sk-real"))

    def test_the_session_cookie_lives_as_long_as_the_token_it_carries(self):
        with patch.dict(os.environ, {"AUTH_SESSION_TTL_SECONDS": "7200"}):
            response = Response()
            auth_api._set_session(response, "user-1")
            cookie = response.headers["set-cookie"]

        self.assertIn(f"{settings.AUTH_COOKIE_NAME}=", cookie)
        self.assertIn("Max-Age=7200", cookie)

    def test_the_session_tells_the_browser_the_limits_the_server_enforces(self):
        with patch.dict(os.environ, {"AUTH_CODE_COOLDOWN_SECONDS": "90"}):
            payload = TestClient(app).get("/api/auth/session").json()

        self.assertFalse(payload["authenticated"])
        config = payload["client_config"]
        self.assertEqual(config["password_min_length"], settings.PASSWORD_MIN_LENGTH)
        self.assertEqual(config["verification_code"], {"length": settings.VERIFICATION_CODE_LENGTH, "cooldown_seconds": 90})
        self.assertEqual(config["episode_count"]["max"], EPISODE_COUNT_MAX)
        self.assertEqual(config["script_upload"]["max_bytes"], SourceIngestor.MAX_BYTES)
        self.assertIn(".fdx", config["script_upload"]["extensions"])

    def test_sending_a_code_reports_the_cooldown_it_starts(self):
        with (
            patch.dict(os.environ, {"AUTH_CODE_COOLDOWN_SECONDS": "45"}),
            patch.object(auth_api.auth_service, "send_verification_code", return_value=(True, "")),
        ):
            payload = auth_api.send_code(SendCodeRequest(login_id="writer@example.com"))

        self.assertEqual(payload["cooldown_seconds"], 45)

    def test_every_advertised_script_format_is_one_the_parser_accepts(self):
        ingestor = SourceIngestor()
        for extension in SourceIngestor.SUPPORTED_EXTENSIONS:
            try:
                ingestor.ingest(f"script.{extension}", "第1集 开场\n林夏：开始吧。".encode("utf-8"))
            except SourceIngestError as error:
                # Binary formats reject this plain text, but never as an unknown format.
                self.assertNotIn("supported source formats", str(error), extension)
        with self.assertRaisesRegex(SourceIngestError, "supported source formats"):
            ingestor.ingest("script.exe", b"x")


class ProviderAccessTests(unittest.TestCase):
    def setUp(self):
        snapshot = list(runtime_model_registry.list("audio")) + list(runtime_model_registry.list("video"))
        self.addCleanup(lambda: runtime_model_registry.replace(snapshot))
        runtime_model_registry.replace([])

    @staticmethod
    def _saved(provider: str, category: str, base_url: str) -> RuntimeModelConfiguration:
        return RuntimeModelConfiguration(
            configuration_id=f"cfg-{provider}", category=category, provider=provider,
            base_url=base_url, api_key="saved-key", model_ids=("model-1",),
        )

    def test_a_key_saved_in_the_configuration_centre_counts_as_available(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "YOUR_ELEVENLABS_API_KEY"}):
            self.assertFalse(provider_key_available("elevenlabs", "audio", "ELEVENLABS_API_KEY"))
            self.assertFalse(media_compositor._elevenlabs_available())
            runtime_model_registry.replace([self._saved("elevenlabs", "audio", "https://api.elevenlabs.io")])
            self.assertTrue(provider_key_available("elevenlabs", "audio", "ELEVENLABS_API_KEY"))
            self.assertTrue(media_compositor._elevenlabs_available())
        runtime_model_registry.replace([])
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "env-key"}):
            self.assertTrue(media_compositor._elevenlabs_available())

    def test_h3_uses_the_saved_minimax_key_and_address(self):
        runtime_model_registry.replace([self._saved("minimax", "video", "https://api.minimax.io")])
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "", "MINIMAX_H3_ENDPOINT": "", "MINIMAX_BASE_URL": ""}):
            client = MiniMaxH3Client()
            self.addCleanup(client.close)

        self.assertEqual(client.endpoint, "https://api.minimax.io/v2/video_generation")
        self.assertEqual(client._client.headers["Authorization"], "Bearer saved-key")

    def test_the_ark_proxy_reaches_ark_and_nothing_else(self):
        gateway = object.__new__(ModelGateway)
        environment = {"ARK_PROXY": "http://ark-proxy:3128", "SEEDANCE_PROXY": "", "HTTPS_PROXY": "", "https_proxy": "", "ALL_PROXY": "", "all_proxy": ""}
        with patch.dict(os.environ, environment):
            ark = gateway._proxies_for("https://ark.cn-beijing.volces.com/api/v3")
            other = gateway._proxies_for("https://api.deepseek.com/v1")
            lookalike = gateway._proxies_for("https://volces.com.example.org/v1")

        self.assertEqual(ark, {"http": "http://ark-proxy:3128", "https": "http://ark-proxy:3128"})
        self.assertEqual(other, {"http": None, "https": None})
        self.assertEqual(lookalike, {"http": None, "https": None})


class LocalToolingTests(unittest.TestCase):
    def test_binaries_and_the_subtitle_font_can_be_pointed_at_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "ffmpeg-custom"
            font = Path(directory) / "brand.ttc"
            binary.write_bytes(b"")
            font.write_bytes(b"")
            with patch.dict(os.environ, {"FFMPEG_PATH": str(binary), "SUBTITLE_FONT_PATH": str(font)}):
                self.assertEqual(media_compositor._ffmpeg(), str(binary))
                self.assertEqual(media_compositor._font_path(), str(font))
            with patch.dict(os.environ, {"FFMPEG_PATH": str(Path(directory) / "missing")}):
                self.assertIsNone(media_compositor._ffmpeg())

    def test_the_title_card_tagline_is_the_deployments_to_set(self):
        with patch.dict(os.environ, {"TITLE_CARD_TAGLINE": "山音出品"}):
            self.assertEqual(media_compositor._title_tagline(), "山音出品")
        with patch.dict(os.environ, {"TITLE_CARD_TAGLINE": ""}):
            self.assertEqual(media_compositor._title_tagline(), "")
        environment = dict(os.environ)
        environment.pop("TITLE_CARD_TAGLINE", None)
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(media_compositor._title_tagline(), media_compositor.DEFAULT_TITLE_TAGLINE)

    def test_the_local_voice_is_configurable(self):
        with patch.dict(os.environ, {"LOCAL_TTS_VOICE": "Meijia"}):
            self.assertEqual(media_compositor._local_tts_voice(), "Meijia")
        with patch.dict(os.environ, {"LOCAL_TTS_VOICE": ""}):
            self.assertEqual(media_compositor._local_tts_voice(), media_compositor.DEFAULT_LOCAL_TTS_VOICE)


if __name__ == "__main__":
    unittest.main()

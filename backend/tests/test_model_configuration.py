import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.auth_api import auth_service
from app.core.model_configuration import (
    DiscoveredModel,
    ModelDiscoveryClient,
    ModelSecretCipher,
    provider_options,
)
from app.core.providers.elevenlabs_capabilities import ELEVENLABS_CAPABILITIES
from app.core.model_gateway import ModelGateway
from app.platform.dependencies import (
    get_model_discovery_client,
    get_model_secret_cipher,
    get_platform_store,
)
from app.platform.store import PlatformStore
from app.platform.runtime_models import (
    RuntimeModelConfiguration,
    runtime_model_registry,
)
from app.schema.platform import ModelTestRequest
from main import app


class ModelDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_compatible_models_are_discovered_and_text_multimodal_is_grouped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["authorization"], "Bearer dynamic-secret")
            return httpx.Response(200, json={"data": [
                {"id": "writer-alpha", "owned_by": "fixture"},
                {"id": "vision-omni-beta", "owned_by": "fixture", "input_modalities": ["text", "image"]},
                {"id": "image-renderer", "owned_by": "fixture", "output_modalities": ["image"]},
            ]})

        discovery = ModelDiscoveryClient(transport=httpx.MockTransport(handler))
        result = await discovery.discover(
            category="text",
            provider="openai",
            base_url="https://api.openai.com/v1",
            api_key="dynamic-secret",
        )

        self.assertEqual([item.model_id for item in result.models], ["vision-omni-beta", "writer-alpha"])
        vision = next(item for item in result.models if item.model_id == "vision-omni-beta")
        self.assertIn("multimodal", vision.capabilities)
        self.assertNotIn("image-renderer", [item.model_id for item in result.models])

    async def test_provider_host_mismatch_and_non_https_url_are_rejected_before_network(self):
        discovery = ModelDiscoveryClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(500))
        )
        with self.assertRaisesRegex(ValueError, "官方域名"):
            await discovery.discover(
                category="text", provider="openai",
                base_url="https://internal.example/v1", api_key="secret-value",
            )
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            await discovery.discover(
                category="text", provider="openai",
                base_url="http://api.openai.com/v1", api_key="secret-value",
            )

    async def test_global_provider_catalog_does_not_relabel_plain_text_models_as_images(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [
                {"id": "plain-writer-model"},
                {"id": "image-renderer-model"},
            ]})

        discovery = ModelDiscoveryClient(transport=httpx.MockTransport(handler))
        result = await discovery.discover(
            category="image",
            provider="openai",
            base_url="https://api.openai.com/v1",
            api_key="dynamic-secret",
        )

        self.assertEqual([item.model_id for item in result.models], ["image-renderer-model"])

    async def test_audio_models_are_grouped_from_dynamic_elevenlabs_metadata(self):
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            self.assertEqual(request.url.path, "/v1/models")
            self.assertEqual(request.headers["xi-api-key"], "dynamic-secret")
            return httpx.Response(200, json=[
                {"model_id": "voice-dynamic", "name": "Voice", "can_do_text_to_speech": True},
                {"model_id": "voice-change-dynamic", "name": "Voice Changer", "can_do_voice_conversion": True},
                {"model_id": "eleven_multilingual_sts_v2", "name": "Multilingual STS v2"},
                {"model_id": "eleven_ttv_v3", "name": "Text to Voice Design"},
                {"model_id": "scribe-dynamic", "name": "Transcription model"},
                {"model_id": "sound-dynamic", "name": "BGM sound model"},
                {"model_id": "music-dynamic", "name": "Music composition"},
            ])

        discovery = ModelDiscoveryClient(transport=httpx.MockTransport(handler))
        result = await discovery.discover(
            category="audio", provider="elevenlabs",
            base_url="https://api.elevenlabs.io", api_key="dynamic-secret",
        )
        self.assertEqual(
            {item.subcategory for item in result.models},
            {"asr", "tts", "voice_conversion", "voice_design", "bgm", "music"},
        )
        model_ids = {item.model_id for item in result.models}
        self.assertTrue({
            "eleven_v3", "eleven_ttv_v3", "eleven_multilingual_v2",
            "eleven_flash_v2_5", "eleven_flash_v2",
            "eleven_multilingual_sts_v2", "eleven_multilingual_ttv_v2",
            "eleven_english_sts_v2", "scribe_v2_realtime", "scribe_v2",
            "eleven_text_to_sound_v2", "music_v2", "music_v1",
        }.issubset(model_ids))
        capability_model_ids = {
            model_id
            for capability in ELEVENLABS_CAPABILITIES
            for model_id in capability.model_ids
        }
        self.assertTrue(model_ids.intersection({
            "eleven_v3", "eleven_ttv_v3", "eleven_multilingual_v2",
            "eleven_flash_v2_5", "eleven_flash_v2",
            "eleven_multilingual_sts_v2", "eleven_multilingual_ttv_v2",
            "eleven_english_sts_v2", "scribe_v2_realtime", "scribe_v2",
            "eleven_text_to_sound_v2", "music_v2", "music_v1",
        }).issubset(capability_model_ids))
        self.assertIn("voice-dynamic", model_ids)
        self.assertTrue(result.credential_verified)
        self.assertEqual(result.warnings, ())
        self.assertEqual(requested_paths, ["/v1/models"])

    async def test_elevenlabs_sound_generation_base_still_discovers_from_official_models_endpoint(self):
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            return httpx.Response(200, json=[
                {"model_id": "eleven_v3", "name": "Eleven v3", "can_do_text_to_speech": True},
            ])

        discovery = ModelDiscoveryClient(transport=httpx.MockTransport(handler))
        result = await discovery.discover(
            category="audio", provider="elevenlabs",
            base_url="https://api.elevenlabs.io/v1/sound-generation", api_key="dynamic-secret",
        )

        self.assertIn("eleven_v3", [item.model_id for item in result.models])
        self.assertIn("scribe_v2", [item.model_id for item in result.models])
        self.assertEqual(requested_paths, ["/v1/models"])

    async def test_elevenlabs_catalog_loads_when_model_scope_is_restricted(self):
        discovery = ModelDiscoveryClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(403))
        )

        result = await discovery.discover(
            category="audio", provider="elevenlabs",
            base_url="https://api.elevenlabs.io", api_key="scope-limited-key",
            allow_catalog_fallback=True,
            allow_invalid_key_fallback=False,
        )

        self.assertFalse(result.credential_verified)
        self.assertEqual(len(result.models), 13)
        self.assertIn("scope", result.warnings[0].lower())

    async def test_elevenlabs_strict_validation_distinguishes_restricted_and_invalid_keys(self):
        restricted = ModelDiscoveryClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(403))
        )
        with self.assertRaisesRegex(ValueError, "scope 或 IP"):
            await restricted.discover(
                category="audio", provider="elevenlabs",
                base_url="https://api.elevenlabs.io", api_key="scope-limited-key",
            )

        invalid = ModelDiscoveryClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(401))
        )
        fallback = await invalid.discover(
            category="audio", provider="elevenlabs",
            base_url="https://api.elevenlabs.io", api_key="invalid-looking-key",
            allow_catalog_fallback=True,
        )
        self.assertFalse(fallback.credential_verified)
        self.assertIn("已撤销", fallback.warnings[0])

        with self.assertRaisesRegex(ValueError, "无效、已撤销或已过期"):
            await invalid.discover(
                category="audio", provider="elevenlabs",
                base_url="https://api.elevenlabs.io", api_key="invalid-looking-key",
            )

    async def test_minimax_video_discovery_ignores_text_catalog(self):
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            self.assertEqual(request.headers["authorization"], "Bearer dynamic-secret")
            return httpx.Response(200, json={"data": [
                {"id": "MiniMax-M2.7"},
                {"id": "MiniMax-M2.7-highspeed"},
            ]})

        discovery = ModelDiscoveryClient(transport=httpx.MockTransport(handler))
        result = await discovery.discover(
            category="video", provider="minimax",
            base_url="https://api.minimaxi.com", api_key="dynamic-secret",
        )

        self.assertTrue(requested_paths)
        self.assertEqual(
            [item.model_id for item in result.models],
            ["MiniMax-H3", "MiniMax-Hailuo-2.3", "MiniMax-Hailuo-2.3-Fast", "MiniMax-Hailuo-02"],
        )
        self.assertTrue(all(item.category == "video" for item in result.models))
        self.assertNotIn("MiniMax-M2.7", [item.model_id for item in result.models])
        h3 = next(item for item in result.models if item.model_id == "MiniMax-H3")
        self.assertTrue({
            "first-last-frame", "multi-reference", "multimodal-reference",
        }.issubset(h3.capabilities))

    async def test_minimax_audio_discovery_returns_all_speech_and_music_models(self):
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            self.assertEqual(request.headers["authorization"], "Bearer dynamic-secret")
            return httpx.Response(200, json={"data": [{"id": "MiniMax-M3"}]})

        discovery = ModelDiscoveryClient(transport=httpx.MockTransport(handler))
        result = await discovery.discover(
            category="audio",
            provider="minimax",
            base_url="https://api.minimaxi.com",
            api_key="dynamic-secret",
        )

        self.assertTrue(requested_paths)
        self.assertEqual(
            {item.model_id for item in result.models},
            {
                "speech-2.8-hd", "speech-2.8-turbo",
                "speech-2.6-hd", "speech-2.6-turbo",
                "speech-02-hd", "speech-02-turbo",
                "speech-01-hd", "speech-01-turbo",
                "music-3.0", "music-cover",
            },
        )
        self.assertEqual(len(result.models), 10)
        self.assertTrue(all(item.category == "audio" for item in result.models))
        by_id = {item.model_id: item for item in result.models}
        self.assertEqual(by_id["music-3.0"].subcategory, "music")
        self.assertEqual(by_id["music-cover"].subcategory, "music_cover")
        self.assertIn("automatic-asr", by_id["music-cover"].capabilities)
        self.assertNotIn("MiniMax-M3", by_id)

    async def test_minimax_catalog_requires_authenticated_model_rows(self):
        discovery = ModelDiscoveryClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"base_resp": {"status_code": 1004}})
            )
        )
        with self.assertRaisesRegex(ValueError, "未提供可枚举"):
            await discovery.discover(
                category="video", provider="minimax",
                base_url="https://api.minimaxi.com", api_key="invalid-looking-key",
            )

    def test_minimax_provider_label_is_canonical(self):
        video_group = next(item for item in provider_options() if item["category"] == "video")
        minimax = next(item for item in video_group["providers"] if item["id"] == "minimax")
        self.assertEqual(minimax["label"], "minimax")
        audio_group = next(item for item in provider_options() if item["category"] == "audio")
        audio_minimax = next(
            item for item in audio_group["providers"] if item["id"] == "minimax"
        )
        self.assertEqual(audio_minimax["label"], "minimax")
        self.assertEqual(audio_minimax["default_base_url"], "https://api.minimaxi.com")

    def test_api_key_ciphertext_never_contains_plaintext(self):
        cipher = ModelSecretCipher(Fernet.generate_key())
        token = cipher.encrypt("never-store-this-plaintext")
        self.assertNotIn("never-store-this-plaintext", token)
        self.assertEqual(cipher.decrypt(token), "never-store-this-plaintext")


class FakeDiscoveryClient:
    def __init__(self):
        self.catalog_fallback_calls: list[bool] = []

    async def discover(
        self, *, category: str, provider: str, base_url: str, api_key: str,
        allow_catalog_fallback: bool = False,
        allow_invalid_key_fallback: bool = True,
    ):
        self.catalog_fallback_calls.append(allow_catalog_fallback)
        if api_key != "api-key-from-form":
            raise ValueError("API Key 无效")
        return type("DiscoveryResult", (), {
            "models": [
                DiscoveredModel(
                    model_id="remote-vision-model",
                    display_name="Remote Vision Model",
                    description="Dynamically returned fixture",
                    category=category,
                    subcategory=None,
                    capabilities=["text", "multimodal"],
                ),
                DiscoveredModel(
                    model_id="remote-writing-model",
                    display_name="Remote Writing Model",
                    description="Second dynamically returned fixture",
                    category=category,
                    subcategory=None,
                    capabilities=["text"],
                ),
                *[
                    DiscoveredModel(
                        model_id=f"remote-extra-model-{index}",
                        display_name=f"Remote Extra Model {index}",
                        description="Additional unlimited-count fixture",
                        category=category,
                        subcategory=None,
                        capabilities=["text"],
                    )
                    for index in range(1, 7)
                ],
            ],
            "source_endpoint": base_url.rstrip("/") + "/models",
            "credential_verified": True,
            "warnings": (),
        })()


class ModelConfigurationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "models.sqlite3"
        self.store = PlatformStore(f"sqlite+aiosqlite:///{db_path}")

        async def prepare():
            await self.store.create_schema()
            self.admin, _ = await self.store.create_user(
                email="model-admin@example.com", phone=None,
                password="model-admin-password", role="admin",
            )
            self.user, _ = await self.store.create_user(
                email="model-user@example.com", phone=None,
                password="model-user-password",
            )

        asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.discovery = FakeDiscoveryClient()
        app.dependency_overrides[get_model_discovery_client] = lambda: self.discovery
        self.cipher = ModelSecretCipher(Fernet.generate_key())
        app.dependency_overrides[get_model_secret_cipher] = lambda: self.cipher
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        runtime_model_registry.replace([])
        asyncio.run(self.store.close())
        self.temp.cleanup()

    def _cookie(self, user_id: str) -> dict:
        return {"auth_token": auth_service.generate_token(user_id)}

    def test_admin_saves_multiple_models_then_deletes_each_saved_entry(self):
        cookies = self._cookie(self.admin.id)
        payload = {
            "category": "text",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "api-key-from-form",
        }
        providers = self.client.get("/api/model-configurations/providers", cookies=cookies)
        self.assertEqual(providers.status_code, 200)
        self.assertEqual({item["category"] for item in providers.json()["items"]}, {"text", "image", "video", "audio"})

        discovered = self.client.post("/api/model-configurations/discover", json=payload, cookies=cookies)
        self.assertEqual(discovered.status_code, 200, discovered.text)
        self.assertEqual(discovered.json()["items"][0]["model_id"], "remote-vision-model")
        self.assertTrue(discovered.json()["credential_verified"])

        tested = self.client.post(
            "/api/model-configurations/test",
            json={**payload, "selected_model_ids": [
                "remote-vision-model", "remote-writing-model",
            ]},
            cookies=cookies,
        )
        self.assertTrue(tested.json()["connected"])

        saved = self.client.post(
            "/api/model-configurations",
            json={**payload, "selected_model_ids": [
                "remote-vision-model", "remote-writing-model",
            ]},
            cookies=cookies,
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertNotIn("api-key-from-form", saved.text)
        self.assertTrue(body["has_api_key"])
        self.assertEqual(
            {item["model_id"] for item in body["models"]},
            {"remote-vision-model", "remote-writing-model"},
        )
        self.assertIsNotNone(runtime_model_registry.resolve("remote-writing-model", "text"))
        self.assertEqual(self.discovery.catalog_fallback_calls, [True, False, False])

        entry = next(item for item in body["models"] if item["model_id"] == "remote-vision-model")
        disabled = self.client.patch(
            f"/api/model-configurations/{body['id']}/models/{entry['id']}",
            json={"enabled": False}, cookies=cookies,
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["enabled"])

        deleted = self.client.delete(
            f"/api/model-configurations/{body['id']}/models/{entry['id']}",
            cookies=cookies,
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(deleted.json()["was_enabled"])
        self.assertFalse(deleted.json()["configuration_deleted"])
        remaining = self.client.get("/api/model-configurations", cookies=cookies).json()
        self.assertEqual(
            [item["model_id"] for item in remaining["items"][0]["models"]],
            ["remote-writing-model"],
        )

        final_entry = remaining["items"][0]["models"][0]
        deleted_final = self.client.delete(
            f"/api/model-configurations/{body['id']}/models/{final_entry['id']}",
            cookies=cookies,
        )
        self.assertEqual(deleted_final.status_code, 200, deleted_final.text)
        self.assertTrue(deleted_final.json()["was_enabled"])
        self.assertTrue(deleted_final.json()["configuration_deleted"])
        empty_state = self.client.get("/api/model-configurations", cookies=cookies).json()
        self.assertEqual(empty_state["items"], [])
        self.assertFalse(empty_state["global_status"]["configured"])
        self.assertEqual(empty_state["global_status"]["enabled_total"], 0)
        self.assertIsNone(runtime_model_registry.resolve("remote-writing-model", "text"))

    def test_model_selection_schema_has_no_business_count_limit(self):
        request = ModelTestRequest(
            category="text",
            provider="openai",
            base_url="https://api.openai.com/v1",
            api_key="fixture-key",
            selected_model_ids=[f"model-{index}" for index in range(125)],
        )
        self.assertEqual(len(request.selected_model_ids), 125)

    def test_api_persists_and_returns_more_than_five_saved_models(self):
        cookies = self._cookie(self.admin.id)
        selected_model_ids = [
            "remote-vision-model",
            "remote-writing-model",
            *[f"remote-extra-model-{index}" for index in range(1, 7)],
        ]
        saved = self.client.post(
            "/api/model-configurations",
            json={
                "category": "text",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "api-key-from-form",
                "selected_model_ids": selected_model_ids,
            },
            cookies=cookies,
        )

        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(len(saved.json()["models"]), 8)
        listed = self.client.get("/api/model-configurations", cookies=cookies)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["items"][0]["models"]), 8)
        self.assertEqual(listed.json()["summary"]["text"], 8)
        global_status = listed.json()["global_status"]
        self.assertTrue(global_status["configured"])
        self.assertEqual(global_status["enabled_total"], 8)
        self.assertEqual(
            set(global_status["enabled_model_ids"]["text"]),
            set(selected_model_ids),
        )
        self.assertIn(global_status["default_model_ids"]["text"], selected_model_ids)

    def test_elevenlabs_discovery_returns_all_service_capabilities_separately(self):
        response = self.client.post(
            "/api/model-configurations/discover",
            json={
                "category": "audio",
                "provider": "elevenlabs",
                "base_url": "https://api.elevenlabs.io",
                "api_key": "api-key-from-form",
            },
            cookies=self._cookie(self.admin.id),
        )

        self.assertEqual(response.status_code, 200, response.text)
        capabilities = response.json()["service_capabilities"]
        self.assertEqual(len(capabilities), 14)
        self.assertEqual(
            {item["id"] for item in capabilities},
            {item.id for item in ELEVENLABS_CAPABILITIES},
        )
        self.assertTrue(any(item["kind"] == "service" and not item["model_ids"] for item in capabilities))

    def test_scope_limited_elevenlabs_key_can_save_catalog_but_cannot_pass_strict_test(self):
        restricted = ModelDiscoveryClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(403))
        )
        app.dependency_overrides[get_model_discovery_client] = lambda: restricted
        payload = {
            "category": "audio",
            "provider": "elevenlabs",
            "base_url": "https://api.elevenlabs.io",
            "api_key": "scope-limited-key",
            "selected_model_ids": ["eleven_v3", "music_v2"],
        }
        cookies = self._cookie(self.admin.id)

        tested = self.client.post(
            "/api/model-configurations/test", json=payload, cookies=cookies
        )
        self.assertEqual(tested.status_code, 422)

        saved = self.client.post(
            "/api/model-configurations", json=payload, cookies=cookies
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertFalse(saved.json()["credential_verified"])
        self.assertEqual(
            {item["model_id"] for item in saved.json()["models"]},
            {"eleven_v3", "music_v2"},
        )
        self.assertTrue(saved.json()["warnings"])
        global_status = self.client.get(
            "/api/model-configurations", cookies=cookies
        ).json()["global_status"]
        self.assertTrue(global_status["configured"])
        self.assertEqual(global_status["default_model_ids"]["audio"], "eleven_v3")

    def test_non_admin_cannot_discover_or_save_provider_credentials(self):
        response = self.client.post(
            "/api/model-configurations/discover",
            json={
                "category": "text", "provider": "openai",
                "base_url": "https://api.openai.com/v1", "api_key": "api-key-from-form",
            },
            cookies=self._cookie(self.user.id),
        )
        self.assertEqual(response.status_code, 403)

        deleted = self.client.delete(
            "/api/model-configurations/missing-configuration/models/missing-model",
            cookies=self._cookie(self.user.id),
        )
        self.assertEqual(deleted.status_code, 403)


class RuntimeModelRoutingTests(unittest.TestCase):
    def tearDown(self):
        runtime_model_registry.replace([])

    def test_selected_dynamic_text_model_routes_to_its_saved_provider(self):
        runtime_model_registry.replace([RuntimeModelConfiguration(
            configuration_id="configuration-1",
            category="text",
            provider="openai",
            base_url="https://api.openai.com/v1",
            api_key="runtime-secret",
            model_ids=("remote-runtime-model",),
        )])
        gateway = ModelGateway.__new__(ModelGateway)
        gateway._http_chat = Mock(return_value="动态模型响应")

        result = gateway.call_llm(
            "remote-runtime-model",
            "system",
            "user",
            "title",
        )

        self.assertEqual(result, "动态模型响应")
        gateway._http_chat.assert_called_once_with(
            "runtime-secret",
            "https://api.openai.com/v1",
            "remote-runtime-model",
            "system",
            "user",
            max_tokens=None,
        )

    def test_empty_text_selection_uses_the_enabled_global_default(self):
        runtime_model_registry.replace([RuntimeModelConfiguration(
            configuration_id="configuration-default",
            category="text",
            provider="openai",
            base_url="https://api.openai.com/v1",
            api_key="runtime-secret",
            model_ids=("global-default-writer", "global-secondary-writer"),
        )])
        gateway = ModelGateway.__new__(ModelGateway)
        gateway._http_chat = Mock(return_value="全局默认模型响应")

        result = gateway.call_llm("", "system", "user", "title")

        self.assertEqual(result, "全局默认模型响应")
        gateway._http_chat.assert_called_once_with(
            "runtime-secret",
            "https://api.openai.com/v1",
            "global-default-writer",
            "system",
            "user",
            max_tokens=None,
        )


if __name__ == "__main__":
    unittest.main()

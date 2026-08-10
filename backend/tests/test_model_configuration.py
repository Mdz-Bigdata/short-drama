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
)
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
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[
                {"model_id": "voice-dynamic", "name": "Voice", "can_do_text_to_speech": True},
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
            {"asr", "tts", "bgm", "music"},
        )

    def test_api_key_ciphertext_never_contains_plaintext(self):
        cipher = ModelSecretCipher(Fernet.generate_key())
        token = cipher.encrypt("never-store-this-plaintext")
        self.assertNotIn("never-store-this-plaintext", token)
        self.assertEqual(cipher.decrypt(token), "never-store-this-plaintext")


class FakeDiscoveryClient:
    async def discover(self, *, category: str, provider: str, base_url: str, api_key: str):
        if api_key != "api-key-from-form":
            raise ValueError("API Key 无效")
        return type("DiscoveryResult", (), {
            "models": [DiscoveredModel(
                model_id="remote-vision-model",
                display_name="Remote Vision Model",
                description="Dynamically returned fixture",
                category=category,
                subcategory=None,
                capabilities=["text", "multimodal"],
            )],
            "source_endpoint": base_url.rstrip("/") + "/models",
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
        app.dependency_overrides[get_model_discovery_client] = lambda: FakeDiscoveryClient()
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

    def test_admin_discovers_tests_saves_and_globally_disables_dynamic_model(self):
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

        tested = self.client.post(
            "/api/model-configurations/test",
            json={**payload, "selected_model_ids": ["remote-vision-model"]},
            cookies=cookies,
        )
        self.assertTrue(tested.json()["connected"])

        saved = self.client.post(
            "/api/model-configurations",
            json={**payload, "selected_model_ids": ["remote-vision-model"]},
            cookies=cookies,
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertNotIn("api-key-from-form", saved.text)
        self.assertTrue(body["has_api_key"])
        self.assertEqual(body["models"][0]["model_id"], "remote-vision-model")

        entry = body["models"][0]
        disabled = self.client.patch(
            f"/api/model-configurations/{body['id']}/models/{entry['id']}",
            json={"enabled": False}, cookies=cookies,
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["enabled"])

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
        )


if __name__ == "__main__":
    unittest.main()

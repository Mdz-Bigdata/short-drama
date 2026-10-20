"""Several keys per provider, video providers declared in data, and a ComfyUI that needs a workflow."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.auth_api import auth_service
from app.core.credential_pool import Credential, CredentialPool
from app.core.model_configuration import ModelSecretCipher
from app.core.model_gateway import ModelGateway, _http_status_in
from app.core.providers import comfyui
from app.core.providers.declarative_video import DeclarativeVideoAdapter, VideoEndpointSpec, declared_video_endpoints
from app.core.providers.video_adapters import VideoJobRequest
from app.core.video_references import normalize_video_provider
from app.platform.dependencies import get_model_discovery_client, get_model_secret_cipher, get_platform_store
from app.platform.runtime_models import RuntimeModelConfiguration, hydrate_runtime_model_registry, runtime_model_registry
from app.platform.store import PlatformStore
from main import app
from tests.test_model_configuration import FakeDiscoveryClient


class CredentialPoolTests(unittest.TestCase):
    def setUp(self):
        self.pool = CredentialPool()
        self.keys = (
            Credential(id="a", api_key="ka"),
            Credential(id="b", api_key="kb", buckets=("video",)),
            Credential(id="c", api_key="kc", buckets=("text", "image")),
        )

    def test_keys_take_turns_within_their_bucket(self):
        first = [c.id for c in self.pool.candidates("cfg", self.keys, "text")]
        second = [c.id for c in self.pool.candidates("cfg", self.keys, "text")]
        self.assertEqual(sorted(first), ["a", "c"])
        self.assertNotEqual(first[0], second[0], "rotation moves the first choice")
        self.assertEqual([c.id for c in self.pool.candidates("cfg", self.keys, "video")][0] in {"a", "b"}, True)
        self.assertEqual(self.pool.candidates("cfg", (Credential(id="x", api_key="k", enabled=False),), "text"), [])

    def test_a_refused_key_sits_out_and_comes_back_after_the_cooldown(self):
        self.assertFalse(self.pool.note_rejected("cfg", "a", 500))
        self.assertTrue(self.pool.note_rejected("cfg", "a", 429, "rate limited"))
        ordered = [c.id for c in self.pool.candidates("cfg", self.keys, "text")]
        self.assertEqual(ordered[-1], "a", "a cooling key is tried last")
        self.assertTrue(self.pool.status("cfg", "a")["cooling"])
        self.assertIn("429", self.pool.status("cfg", "a")["last_error"])
        with patch.dict("os.environ", {"CREDENTIAL_COOLDOWN_SECONDS": "0"}):
            self.pool.note_rejected("cfg", "c", 401)
        self.assertFalse(self.pool.status("cfg", "c")["cooling"])
        self.pool.note_used("cfg", "a")
        self.assertFalse(self.pool.status("cfg", "a")["cooling"])
        self.assertEqual(self.pool.status("cfg", "a")["uses"], 1)


class GatewayRotationTests(unittest.TestCase):
    def setUp(self):
        self.gateway = ModelGateway()
        runtime_model_registry.replace([RuntimeModelConfiguration(
            configuration_id="cfg-text", category="text", provider="openai", base_url="https://api.openai.com/v1", api_key="k1",
            model_ids=("writer",), credentials=(Credential(id="primary", api_key="k1"), Credential(id="second", api_key="k2")),
        )])
        self.addCleanup(runtime_model_registry.replace, [])

    def test_a_rejected_key_is_followed_by_the_next_and_a_server_error_is_not(self):
        asked: list[str] = []

        def chat(api_key, base_url, api_model, system_prompt, user_content, timeout=180, max_tokens=None):
            asked.append(api_key)
            self.gateway._thread_state.last_status = 401 if api_key == "k1" else 200
            return None if api_key == "k1" else "answer"

        with patch.object(self.gateway, "_http_chat", side_effect=chat):
            self.assertEqual(self.gateway._call_llm_unmetered("writer", "sys", "user", "t"), "answer")
        self.assertEqual(asked, ["k1", "k2"])

        asked.clear()

        def broken(api_key, *args, **kwargs):
            asked.append(api_key)
            self.gateway._thread_state.last_status = 500
            return None

        with patch.object(self.gateway, "_http_chat", side_effect=broken), patch.object(self.gateway, "_provider_creds", return_value=("", "", "")):
            self.gateway._call_llm_unmetered("writer", "sys", "user", "t")
        self.assertEqual(len(asked), 1, "a server error does not burn the other key")

    def test_adapter_errors_name_their_status(self):
        self.assertEqual(_http_status_in("Kling request failed: HTTP 401, request_id=x"), 401)
        self.assertIsNone(_http_status_in("timed out"))


def _spec(**overrides) -> VideoEndpointSpec:
    """An "acme" provider declared in data: submit a job, read its id, poll until a clip URL appears."""
    values = {
        "family": "acme_video", "label": "Acme 视频", "base_url": "https://video.acme.test",
        "model_ids": ["acme-v1"], "modes": ["text", "first_frame"],
        "submit": {"path": "/v1/jobs", "body": {"model": "{{model}}", "input": {
            "prompt": "{{prompt}}", "image": "{{first_frame}}", "seconds": "{{duration}}",
        }}},
        "job_id_path": "data.id",
        "poll": {"path": "/v1/jobs/{{job_id}}", "status_path": "data.state", "video_url_path": "data.output.url"},
        **overrides,
    }
    spec = VideoEndpointSpec.model_validate(values)
    spec.check()
    return spec


class DeclarativeVideoTests(unittest.TestCase):
    def tearDown(self):
        declared_video_endpoints.replace([])

    def test_the_spec_fills_the_template_submits_polls_and_returns_the_clip(self):
        seen: list[tuple[str, dict | None]] = []
        polls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["authorization"], "Bearer acme-key")
            if request.method == "POST":
                seen.append((request.url.path, json.loads(request.content)))
                return httpx.Response(200, json={"data": {"id": "job-7"}})
            polls["n"] += 1
            seen.append((request.url.path, None))
            if polls["n"] == 1:
                return httpx.Response(200, json={"data": {"state": "running"}})
            return httpx.Response(200, json={"data": {"state": "done", "output": {"url": "https://cdn.acme.test/7.mp4"}}})

        adapter = DeclarativeVideoAdapter(_spec(), api_key="acme-key", transport=httpx.MockTransport(handler))
        result = adapter.create_video(VideoJobRequest(model="acme-v1", prompt="雨夜", first_frame="https://img/1.png", duration_seconds=8))
        self.assertEqual(result.task_id, "job-7")
        finished = adapter.wait_for_video("job-7", poll_interval_seconds=0)
        self.assertEqual(finished.video_url, "https://cdn.acme.test/7.mp4")
        self.assertEqual(seen[0], ("/v1/jobs", {"model": "acme-v1", "input": {"prompt": "雨夜", "image": "https://img/1.png", "seconds": 8}}))
        self.assertEqual(seen[1][0], "/v1/jobs/job-7")

        with self.assertRaisesRegex(RuntimeError, "cannot execute mode"):
            adapter.create_video(VideoJobRequest(prompt="x", first_frame="a", last_frame="b"))

    def test_a_spec_must_be_https_have_a_placeholder_and_a_way_to_read_the_result(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            _spec(base_url="http://video.acme.test")
        with self.assertRaisesRegex(ValueError, "占位符"):
            _spec(submit={"path": "/v1/jobs", "body": {"fixed": True}})
        with self.assertRaisesRegex(ValueError, "job_id_path 或 video_url_path"):
            _spec(job_id_path="", poll=None)

    def test_a_declared_family_is_routed_and_ready_only_with_a_key(self):
        declared_video_endpoints.replace([(_spec(), "")])
        profile = normalize_video_provider("acme-v1")
        self.assertEqual((profile.family, profile.modes, profile.verification_status), ("acme_video", ["text", "first_frame"], "runtime_configuration_required"))
        self.assertFalse(ModelGateway.video_family_ready("acme_video", "acme-v1"))
        declared_video_endpoints.replace([(_spec(), "acme-key")])
        self.assertTrue(ModelGateway.video_family_ready("acme_video", "acme-v1"))
        self.assertEqual(ModelGateway.video_family_modes("acme_video"), frozenset({"text", "first_frame"}))
        self.assertEqual(normalize_video_provider("seedance2.0").family, "seedance", "built-in families are untouched")


class ComfyUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workflow = Path(self.temp.name) / "flow.json"
        self.workflow.write_text(json.dumps({
            "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder"}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
        }), encoding="utf-8")

    def test_without_a_workflow_it_is_configurable_but_not_ready_and_nothing_is_sent(self):
        with patch.dict("os.environ", {"COMFYUI_BASE_URL": "http://127.0.0.1:8188", "COMFYUI_WORKFLOW_PATH": "", "COMFYUI_BINDINGS": ""}):
            view = comfyui.status()
            self.assertFalse(view["ready"])
            self.assertEqual(view["workflow"], "missing")
            self.assertTrue(any("未提供工作流" in p for p in view["problems"]))
            self.assertFalse(ModelGateway.video_family_ready("comfyui"))
            gateway = ModelGateway()
            with patch.object(comfyui.ComfyUIClient, "from_environment", side_effect=AssertionError("must not connect")):
                self.assertIsNone(gateway._comfyui_generate("p", image=None, want="image"))
        with patch.dict("os.environ", {"COMFYUI_BASE_URL": "", "COMFYUI_WORKFLOW_PATH": str(self.workflow)}):
            self.assertIn("未设置 COMFYUI_BASE_URL", comfyui.status()["problems"][0])

    def test_with_a_workflow_the_prompt_is_bound_queued_polled_and_served(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.path}")
            if request.url.path == "/prompt":
                graph = json.loads(request.content)["prompt"]
                self.assertEqual(graph["6"]["inputs"]["text"], "雨夜的实验室")
                self.assertEqual(graph["3"]["inputs"]["seed"], 42)
                return httpx.Response(200, json={"prompt_id": "p-1"})
            if request.url.path == "/history/p-1":
                if len(calls) < 3:
                    return httpx.Response(200, json={})
                return httpx.Response(200, json={"p-1": {"status": {"status_str": "success"}, "outputs": {"9": {"images": [{"filename": "out_00001_.png", "subfolder": "", "type": "output"}]}}}})
            return httpx.Response(404)

        env = {"COMFYUI_BASE_URL": "http://127.0.0.1:8188", "COMFYUI_WORKFLOW_PATH": str(self.workflow),
               "COMFYUI_BINDINGS": json.dumps({"prompt": "6.inputs.text", "seed": "3.inputs.seed"}), "COMFYUI_POLL_SECONDS": "0"}
        with patch.dict("os.environ", env):
            self.assertTrue(comfyui.status()["ready"])
            client = comfyui.ComfyUIClient.from_environment(transport=httpx.MockTransport(handler))
            url = client.generate(prompt="雨夜的实验室", seed=42, want="image")
        self.assertEqual(url, "http://127.0.0.1:8188/view?filename=out_00001_.png&subfolder=&type=output")
        self.assertEqual(calls[0], "POST /prompt")
        with self.assertRaisesRegex(ValueError, "不存在"):
            comfyui.bind(json.loads(self.workflow.read_text()), {"prompt": "99.inputs.text"}, {"prompt": "x"})


class ConfigurationCentreTests(unittest.TestCase):
    """Credentials and settings through the store, the API and the runtime registry."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'models.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            self.admin, _ = await self.store.create_user(email="pool-admin@example.com", phone=None, password="pool-admin-password", role="admin")

        asyncio.run(prepare())
        self.cipher = ModelSecretCipher(Fernet.generate_key())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        app.dependency_overrides[get_model_discovery_client] = lambda: FakeDiscoveryClient()
        app.dependency_overrides[get_model_secret_cipher] = lambda: self.cipher
        self.client = TestClient(app)
        self.cookies = {"auth_token": auth_service.generate_token(self.admin.id)}

    def tearDown(self):
        app.dependency_overrides.clear()
        runtime_model_registry.replace([])
        declared_video_endpoints.replace([])
        asyncio.run(self.store.close())
        self.temp.cleanup()

    def _save_text_configuration(self) -> str:
        saved = self.client.post("/api/model-configurations", cookies=self.cookies, json={
            "category": "text", "provider": "openai", "base_url": "https://api.openai.com/v1",
            "api_key": "api-key-from-form", "selected_model_ids": ["remote-writing-model"],
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        return saved.json()["id"]

    def test_extra_credentials_are_saved_encrypted_listed_masked_and_rotate_at_runtime(self):
        configuration_id = self._save_text_configuration()
        added = self.client.post(f"/api/model-configurations/{configuration_id}/credentials", cookies=self.cookies,
                                 json={"label": "备用", "api_key": "second-key-0002", "buckets": ["text"]})
        self.assertEqual(added.status_code, 200, added.text)
        self.assertEqual((added.json()["label"], added.json()["key_hint"], added.json()["buckets"]), ("备用", "****0002", ["text"]))
        bad = self.client.post(f"/api/model-configurations/{configuration_id}/credentials", cookies=self.cookies, json={"api_key": "k", "buckets": ["voice"]})
        self.assertEqual(bad.status_code, 422)

        listed = self.client.get("/api/model-configurations", cookies=self.cookies).json()
        row = next(item for item in listed["items"] if item["id"] == configuration_id)
        self.assertEqual([c["label"] for c in row["credentials"]], ["备用"])
        self.assertNotIn("second-key", json.dumps(listed))
        runtime = runtime_model_registry.resolve("remote-writing-model", "text")
        self.assertEqual([c.api_key for c in runtime.credentials], ["api-key-from-form", "second-key-0002"])
        self.assertEqual([c.id for c in runtime.credentials_for("video")], ["primary"], "a text-only key stays out of video")

        credential_id = added.json()["id"]
        off = self.client.patch(f"/api/model-configurations/{configuration_id}/credentials/{credential_id}", cookies=self.cookies, json={"enabled": False})
        self.assertEqual(off.status_code, 200)
        self.assertEqual(len(runtime_model_registry.resolve("remote-writing-model", "text").credentials), 1)
        gone = self.client.delete(f"/api/model-configurations/{configuration_id}/credentials/{credential_id}", cookies=self.cookies)
        self.assertEqual(gone.status_code, 200)
        self.assertEqual(self.client.get("/api/model-configurations", cookies=self.cookies).json()["items"][0]["credentials"], [])

    def test_declared_video_endpoints_are_saved_and_hydrated(self):
        spec = _spec().model_dump(mode="json")
        spec.pop("family")
        missing_key = self.client.put("/api/model-configurations/settings/video-endpoints/acme_video", cookies=self.cookies, json={"spec": spec})
        self.assertEqual(missing_key.status_code, 422)
        saved = self.client.put("/api/model-configurations/settings/video-endpoints/acme_video", cookies=self.cookies, json={"spec": spec, "api_key": "acme-secret-key"})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual((saved.json()["family"], saved.json()["ready"], saved.json()["key_hint"]), ("acme_video", True, "****-key"))
        self.assertEqual(declared_video_endpoints.api_key("acme_video"), "acme-secret-key")
        self.assertEqual(normalize_video_provider("acme-v1").family, "acme_video")
        settings_view = self.client.get("/api/model-configurations", cookies=self.cookies).json()["settings"]
        self.assertEqual(settings_view["video_endpoints"][0]["family"], "acme_video")
        self.assertNotIn("acme-secret-key", json.dumps(settings_view))
        self.assertIn("workflow", settings_view["comfyui"])
        self.assertIn("prompt", settings_view["video_endpoint_placeholders"])

        asyncio.run(hydrate_runtime_model_registry(self.store, self.cipher))
        self.assertTrue(declared_video_endpoints.ready("acme_video"))
        removed = self.client.delete("/api/model-configurations/settings/video-endpoints/acme_video", cookies=self.cookies)
        self.assertEqual(removed.status_code, 200)
        self.assertIsNone(declared_video_endpoints.spec("acme_video"))

    def test_the_provider_list_reports_the_self_hosted_comfyui_status(self):
        with patch.dict("os.environ", {"COMFYUI_BASE_URL": "", "COMFYUI_WORKFLOW_PATH": ""}):
            providers = self.client.get("/api/model-configurations/providers", cookies=self.cookies).json()
        self.assertEqual(providers["self_hosted"][0]["family"], "comfyui")
        self.assertFalse(providers["self_hosted"][0]["ready"])


if __name__ == "__main__":
    unittest.main()

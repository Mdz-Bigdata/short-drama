"""A selected image model either draws the panel or the panel fails: no slow double attempts, no hidden model swap."""

import unittest
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core.model_gateway import ModelGateway
from app.platform.runtime_models import RuntimeModelConfiguration, runtime_model_registry
from main import app


class SelectedImageModelTests(unittest.TestCase):
    def setUp(self):
        snapshot = runtime_model_registry.list("image")
        self.addCleanup(lambda: runtime_model_registry.replace(list(snapshot)))
        runtime_model_registry.replace([RuntimeModelConfiguration(
            configuration_id="cfg-ark", category="image", provider="volcengine",
            base_url="https://ark.example/api/v3", api_key="saved-key", model_ids=("doubao-seedream-5-0-pro-260628",),
        )])
        self.gateway = ModelGateway()

    def test_a_failed_centre_model_is_not_replaced_by_the_environment_model(self):
        self.gateway._http_image = Mock(return_value=None)
        self.gateway._provider_creds = Mock(side_effect=AssertionError("the .env image model must not be tried"))

        with self.assertLogs("app.core.model_gateway", level="ERROR") as logs:
            url, provider = self.gateway._generate_image_unmetered("doubao-seedream-5-0-pro-260628", "九宫格分镜", enhance_prompt=False)

        self.assertEqual((url, provider), (None, None))
        self.assertEqual(self.gateway._http_image.call_count, 1)
        self.assertIn("不改用其它图像模型", logs.output[0])

    def test_a_project_image_model_missing_from_the_centre_uses_the_centre_model(self):
        self.gateway._http_image = Mock(return_value="https://cdn/panel.jpeg")
        self.gateway._provider_creds = Mock(side_effect=AssertionError("the .env image model must not be used while the centre has one"))

        url, provider = self.gateway._generate_image_unmetered("doubao-seedream-4-0-250828", "九宫格分镜", enhance_prompt=False)

        self.assertEqual((url, provider), ("https://cdn/panel.jpeg", "volcengine"))
        self.assertEqual(self.gateway._http_image.call_args.args[2], "doubao-seedream-5-0-pro-260628")

    def test_with_no_centre_image_model_the_configuration_file_model_is_used(self):
        runtime_model_registry.replace([])
        self.gateway._provider_creds = Mock(return_value=("ark-key-0123456789abcdef", "https://ark.example/api/v3", None))
        self.gateway._is_valid_key = lambda key: True
        self.gateway._http_image = Mock(return_value="https://cdn/panel.jpeg")

        url, provider = self.gateway._generate_image_unmetered("doubao-seedream-4-0-250828", "九宫格分镜", enhance_prompt=False)

        self.assertEqual((url, provider), ("https://cdn/panel.jpeg", "seedance"))
        self.assertEqual(self.gateway._http_image.call_args.args[2], self.gateway.seedance_image_model)

    def test_a_read_timeout_is_reported_once_and_does_not_mark_the_host_broken(self):
        with patch("requests.post", side_effect=requests.exceptions.ReadTimeout("slow")) as post, \
                self.assertLogs("app.core.model_gateway", level="WARNING") as logs:
            url = self.gateway._http_image("key", "https://ark.example/api/v3", "doubao-seedream-5-0-pro-260628", "p", extra={"size": "2048x2048"}, timeout=60)

        self.assertIsNone(url)
        self.assertEqual(post.call_count, 1)
        self.assertIn("超过 60 秒未返回", logs.output[0])
        self.assertFalse(self.gateway._is_host_broken("https://ark.example/api/v3"))

    def test_the_default_timeout_leaves_room_for_large_storyboard_grids(self):
        response = Mock(status_code=200)
        response.json.return_value = {"data": [{"url": "https://cdn/grid.jpeg"}]}
        with patch("requests.post", return_value=response) as post:
            self.gateway._http_image("key", "https://ark.example/api/v3", "m", "p")
        self.assertGreaterEqual(post.call_args.kwargs["timeout"], 300)


class SeedanceEndpointTests(unittest.TestCase):
    def test_a_prompt_only_request_is_refused(self):
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        self.addCleanup(lambda: app.dependency_overrides.pop(get_current_user, None))
        service = Mock()
        with patch.object(drama_api, "service", service):
            response = TestClient(app).post("/api/drama/seedance2_video", json={"prompt": "雨夜长街"})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("禁止文生视频", response.json()["detail"])
        service.generate_seedance2_video.assert_not_called()


if __name__ == "__main__":
    unittest.main()

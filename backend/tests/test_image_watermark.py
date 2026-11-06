"""Seedream images carry no visible 「AI生成」 mark unless the deployment asks for one."""

import os
import unittest
from unittest.mock import patch

from app.core.model_gateway import ModelGateway
from app.platform.runtime_models import RuntimeModelConfiguration, runtime_model_registry


class SeedreamWatermarkTests(unittest.TestCase):
    def setUp(self):
        snapshot = runtime_model_registry.list("image")
        self.addCleanup(lambda: runtime_model_registry.replace(list(snapshot)))
        runtime_model_registry.replace([RuntimeModelConfiguration(
            configuration_id="cfg-ark", category="image", provider="volcengine",
            base_url="https://ark.example/api/v3", api_key="saved-key", model_ids=("doubao-seedream-5-0-pro-260628",),
        )])

    def _sent_extra(self, env: dict) -> dict:
        with patch.dict(os.environ, env):
            gateway = ModelGateway()
        sent = {}

        def http_image(key, base_url, model, prompt, extra=None, timeout=180):
            sent.update(extra or {})
            return "https://cdn/image.jpeg"

        gateway._http_image = http_image
        gateway.generate_image("doubao-seedream-5-0-pro-260628", "雨夜长街，油灯", enhance_prompt=False)
        return sent

    def test_no_visible_watermark_by_default(self):
        env = {key: value for key, value in os.environ.items() if key != "SEEDANCE_IMAGE_WATERMARK"}
        with patch.dict(os.environ, env, clear=True):
            self.assertIs(self._sent_extra({})["watermark"], False)

    def test_a_deployment_can_ask_for_the_mark(self):
        self.assertIs(self._sent_extra({"SEEDANCE_IMAGE_WATERMARK": "1"})["watermark"], True)


if __name__ == "__main__":
    unittest.main()

import base64
import io
import unittest
from unittest.mock import patch

from PIL import Image

from app.core.model_gateway import ModelGateway, _image_reference
from app.platform.runtime_models import RuntimeModelConfiguration


class StoryboardImageReferenceTests(unittest.TestCase):
    def setUp(self):
        output = io.BytesIO()
        Image.new("RGB", (2, 2), "navy").save(output, format="PNG")
        self.reference = (
            "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
        )
        self.gateway = ModelGateway()

    def test_valid_private_image_reference_is_sent_to_seedream(self):
        runtime = RuntimeModelConfiguration(
            "test",
            "image",
            "volcengine",
            "https://provider.test",
            "test-only",
            ("image-model",),
        )
        with patch(
            "app.core.model_gateway.runtime_model_registry.resolve",
            return_value=runtime,
        ), patch.object(
            self.gateway, "_http_image", return_value="https://img.test/result.png"
        ) as request:
            result = self.gateway.generate_image(
                "image-model", "拍摄场地", [self.reference]
            )
        self.assertEqual(result[1], "volcengine")
        self.assertEqual(request.call_args.kwargs["extra"]["image"], [self.reference])

    def test_unsupported_reference_adapter_fails_before_text_only_generation(self):
        runtime = RuntimeModelConfiguration(
            "test",
            "image",
            "openai",
            "https://provider.test",
            "test-only",
            ("image-model",),
        )
        with patch(
            "app.core.model_gateway.runtime_model_registry.resolve",
            return_value=runtime,
        ), patch.object(self.gateway, "_http_image") as request:
            with self.assertRaisesRegex(ValueError, "参考图"):
                self.gateway.generate_image(
                    "image-model",
                    "剧情",
                    [self.reference],
                    require_reference_support=True,
                )
        request.assert_not_called()

    def test_invalid_inline_references_are_not_accepted(self):
        for value in (
            "file:///private/image.png",
            "data:text/html;base64,AAAA",
            "data:image/png;base64,AAAA",
            "data:image/png;base64,%%%",
            None,
        ):
            self.assertFalse(_image_reference(value))
        self.assertTrue(_image_reference(self.reference))

    def test_compiled_storyboard_prompt_is_not_rewritten_by_keyword_enhancer(self):
        runtime = RuntimeModelConfiguration(
            "test",
            "image",
            "volcengine",
            "https://provider.test",
            "test-only",
            ("image-model",),
        )
        prompt = "沈砚剑眉，身旁是星盘；无飞剑，无额外特效。"
        with patch(
            "app.core.model_gateway.runtime_model_registry.resolve",
            return_value=runtime,
        ), patch.object(
            self.gateway, "_http_image", return_value="https://img.test/result.png"
        ) as request:
            self.gateway.generate_image("image-model", prompt, enhance_prompt=False)
        self.assertEqual(request.call_args.args[3], prompt)


if __name__ == "__main__":
    unittest.main()

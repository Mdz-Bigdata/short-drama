"""An image size the model refuses as too large is shrunk to the stated ceiling, retried once, and remembered."""

import unittest
from unittest.mock import patch

from app.core.model_gateway import ModelGateway, allowed_image_area, fit_image_size

REFUSAL = ('{"error":{"code":"InvalidParameter","message":"The parameter `size` specified in the request are not valid: '
           'image area must be at most 4624220 pixels. Request id: 0217"}}')


class _Response:
    def __init__(self, status: int, body: dict | None = None, text: str = ""):
        self.status_code = status
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


def _ok() -> _Response:
    return _Response(200, {"data": [{"url": "https://cdn.example/image.png"}]})


class FitTests(unittest.TestCase):
    def test_the_ceiling_is_read_from_the_refusal_only(self):
        self.assertEqual(allowed_image_area(400, REFUSAL), 4_624_220)
        self.assertIsNone(allowed_image_area(400, "invalid api key"))
        self.assertIsNone(allowed_image_area(500, REFUSAL))

    def test_a_size_is_shrunk_close_to_the_same_ratio_in_multiples_of_16(self):
        fitted = fit_image_size("3072x2048", 4_624_220)
        self.assertEqual(fitted, "2624x1744")
        width, height = map(int, fitted.split("x"))
        self.assertLessEqual(width * height, 4_624_220)
        self.assertEqual((width % 16, height % 16), (0, 0))
        self.assertAlmostEqual(width / height, 1.5, places=2)
        self.assertEqual(fit_image_size("5040x2160", 4_624_220), "3280x1408", "the 21:9 actor sheet stays within 0.2% of 21:9")
        self.assertEqual(fit_image_size("3360x1440", 4_624_220), "3280x1408")
        self.assertEqual(fit_image_size("4096x4096", 4_624_220), "2144x2144")
        self.assertIsNone(fit_image_size("2048x2048", 4_624_220), "a size that fits is left alone")
        self.assertIsNone(fit_image_size("2K", 4_624_220), "named sizes are the model's to interpret")


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.gateway = ModelGateway()
        self.sent: list[str] = []

    def _image(self, responses, size="3072x2048"):
        queue = list(responses)

        def post(url, json=None, **kwargs):
            self.sent.append(json["size"])
            return queue.pop(0)

        with patch("requests.post", side_effect=post), \
                patch.object(self.gateway, "_is_host_broken", return_value=False), \
                patch.object(self.gateway, "_proxies_for", return_value=None):
            return self.gateway._http_image("key", "https://ark.example/api/v3", "doubao-seedream-5-0-pro", "一张图", extra={"size": size})

    def test_a_refused_size_is_retried_at_the_ceiling_and_remembered(self):
        self.assertEqual(self._image([_Response(400, text=REFUSAL), _ok()]), "https://cdn.example/image.png")
        self.assertEqual(self.sent, ["3072x2048", "2624x1744"])
        self.assertEqual(self._image([_ok()]), "https://cdn.example/image.png")
        self.assertEqual(self.sent[-1], "2624x1744", "the next request goes straight to the ceiling")
        self._image([_ok()], size="1440x2560")
        self.assertEqual(self.sent[-1], "1440x2560")

    def test_it_shrinks_once_and_other_refusals_are_not_retried(self):
        self.assertIsNone(self._image([_Response(400, text=REFUSAL), _Response(400, text=REFUSAL)]))
        self.assertEqual(len(self.sent), 2)
        self.sent.clear()
        self.assertIsNone(self._image([_Response(400, text="invalid api key")], size="1024x1024"))
        self.assertEqual(self.sent, ["1024x1024"])


if __name__ == "__main__":
    unittest.main()

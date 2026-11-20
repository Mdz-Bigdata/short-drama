"""A picture refused by moderation for what the model drew is drawn once more; a request refused for what it sent is not.

Seen in the canvas film trial (2026-11-16): Seedream refused one first frame with OutputImageSensitiveContentDetected,
the batch skipped that shot's clip and the film, and the same request passed when it was simply sent again.
"""

import unittest
from unittest.mock import patch

from app.core.model_gateway import ModelGateway


def _reply(status, text="", url=None):
    class Reply:
        status_code = status
        headers = {}

        def __init__(self):
            self.text = text

        def json(self):
            return {"data": [{"url": url}]} if url else {}

    return Reply()


OUTPUT_REFUSED = '{"error":{"code":"OutputImageSensitiveContentDetected","message":"The request failed because the output image may contain sensitive information."}}'
INPUT_REFUSED = '{"error":{"code":"InputImageSensitiveContentDetected.PrivacyInformation","message":"may contain real person"}}'


class OutputRefusalTests(unittest.TestCase):
    def draw(self, replies):
        gateway = ModelGateway.__new__(ModelGateway)
        gateway.tls_verify = True
        with patch("requests.post", side_effect=replies) as post, patch("time.sleep"), \
                patch.object(gateway, "_is_host_broken", return_value=False, create=True), \
                patch.object(gateway, "_note_host_ok", create=True), patch.object(gateway, "_proxies_for", return_value=None):
            url = gateway._http_image("k", "http://img.test/v1", "seedream", "a prompt")
        return url, post.call_count

    def test_a_refused_picture_is_drawn_once_more(self):
        self.assertEqual(self.draw([_reply(400, OUTPUT_REFUSED), _reply(200, url="http://img.test/a.png")]), ("http://img.test/a.png", 2))

    def test_only_once(self):
        self.assertEqual(self.draw([_reply(400, OUTPUT_REFUSED), _reply(400, OUTPUT_REFUSED), _reply(200, url="http://img.test/a.png")]), (None, 2))

    def test_a_request_refused_for_what_it_sent_is_not_sent_again(self):
        self.assertEqual(self.draw([_reply(400, INPUT_REFUSED), _reply(200, url="http://img.test/a.png")]), (None, 1))

    def test_other_errors_are_not_retried(self):
        self.assertEqual(self.draw([_reply(500, "server error"), _reply(200, url="http://img.test/a.png")]), (None, 1))


if __name__ == "__main__":
    unittest.main()

"""A chat call that the server keeps alive with blank lines must still end at its total deadline."""

import json
import unittest
from unittest.mock import patch

from app.core import model_gateway
from app.core.model_gateway import ModelGateway


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _StreamingResponse:
    status_code = 200
    text = ""

    def __init__(self, chunks, clock, seconds_per_chunk):
        self._chunks, self._clock, self._step = chunks, clock, seconds_per_chunk
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for chunk in self._chunks:
            self._clock.now += self._step
            yield chunk

    def close(self):
        self.closed = True


class _Plain:
    """A refusal (or any non-streamed answer) with a status and headers."""

    text = ""

    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.closed = False

    def close(self):
        self.closed = True


class ChatDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.gateway = ModelGateway.__new__(ModelGateway)
        self.gateway._thread_state = type("S", (), {})()
        self.clock = _Clock()
        self.patches = [
            patch.object(self.gateway, "_is_host_broken", return_value=False),
            patch.object(self.gateway, "_proxies_for", return_value=None),
            patch.object(self.gateway, "_note_host_ok"),
            patch.object(self.gateway, "_remember_chat_usage"),
            patch.object(self.gateway, "_mark_host_broken"),
            patch("time.monotonic", self.clock),
        ]
        for item in self.patches:
            item.start()
        self.gateway.tls_verify = True
        self.addCleanup(lambda: [item.stop() for item in self.patches])

    def _chat(self, response, **kwargs):
        calls = []

        def post(url, **request):
            calls.append(request)
            return response

        with patch("requests.post", side_effect=post):
            result = self.gateway._http_chat("key", "https://api.deepseek.com", "deepseek-v4-pro", "S", "U", **kwargs)
        return result, calls

    def test_endless_keep_alive_lines_end_at_the_deadline_without_retry_or_breaker(self):
        response = _StreamingResponse([b"\n"] * 1000, self.clock, seconds_per_chunk=5)
        with self.assertLogs("app.core.model_gateway", level="WARNING") as logs:
            result, calls = self._chat(response, timeout=60)

        self.assertIsNone(result)
        self.assertEqual(len(calls), 1, "a slow model is not retried on the same host")
        self.assertTrue(calls[0]["stream"])
        self.assertTrue(response.closed)
        self.gateway._mark_host_broken.assert_not_called()
        # Default deadline is 30 minutes whatever the read timeout: 1800 s at 5 s a line is 360 lines, not 1000.
        self.assertGreaterEqual(self.clock.now - 1000.0, 1800)
        self.assertLessEqual(self.clock.now - 1000.0, 1810)
        self.assertIn("1800 秒", logs.output[0])

    def test_an_explicit_deadline_beats_the_default_and_the_environment(self):
        response = _StreamingResponse([b"\n"] * 1000, self.clock, seconds_per_chunk=5)
        with patch.dict("os.environ", {"LLM_CALL_DEADLINE_SECONDS": "3600"}), self.assertLogs("app.core.model_gateway", level="WARNING"):
            self.assertIsNone(self._chat(response, timeout=40, deadline=80)[0])
        self.assertLessEqual(self.clock.now - 1000.0, 90)

    def test_a_slow_complete_answer_behind_keep_alive_lines_is_read(self):
        body = json.dumps({"choices": [{"message": {"content": "三幕大纲"}}], "usage": {}}).encode()
        response = _StreamingResponse([b"\n", b"\n", body[:20], body[20:]], self.clock, seconds_per_chunk=10)
        result, _ = self._chat(response, timeout=60)
        self.assertEqual(result, "三幕大纲")

    def test_the_deadline_can_be_set_from_the_environment(self):
        response = _StreamingResponse([b"\n"] * 1000, self.clock, seconds_per_chunk=5)
        with patch.dict("os.environ", {"LLM_CALL_DEADLINE_SECONDS": "30"}), self.assertLogs("app.core.model_gateway", level="WARNING"):
            self.assertIsNone(self._chat(response, timeout=180)[0])
        self.assertLessEqual(self.clock.now - 1000.0, 40)

    def test_reads_may_stay_silent_for_ten_minutes_but_connecting_fails_fast(self):
        body = json.dumps({"choices": [{"message": {"content": "好"}}], "usage": {}}).encode()
        with patch.dict("os.environ", {}, clear=False):
            import os

            for name in ("LLM_READ_TIMEOUT_SECONDS", "LLM_CONNECT_TIMEOUT_SECONDS"):
                os.environ.pop(name, None)
            _, calls = self._chat(_StreamingResponse([body], self.clock, seconds_per_chunk=1))
        self.assertEqual(model_gateway.DEFAULT_LLM_READ_TIMEOUT_SECONDS, 600)
        self.assertEqual(calls[0]["timeout"], (30.0, 600.0))

    def test_the_read_timeout_can_be_set_from_the_environment_or_the_call(self):
        body = json.dumps({"choices": [{"message": {"content": "好"}}], "usage": {}}).encode()
        with patch.dict("os.environ", {"LLM_READ_TIMEOUT_SECONDS": "1200", "LLM_CONNECT_TIMEOUT_SECONDS": "15"}):
            _, from_env = self._chat(_StreamingResponse([body], self.clock, seconds_per_chunk=1))
            _, explicit = self._chat(_StreamingResponse([body], self.clock, seconds_per_chunk=1), timeout=40)
        self.assertEqual(from_env[0]["timeout"], (15.0, 1200.0))
        self.assertEqual(explicit[0]["timeout"], (15.0, 40.0))

    def _chat_sequence(self, responses, **kwargs):
        """Each call to the provider answers with the next response; the waits between retries are recorded."""
        calls, waits = [], []
        queue = list(responses)

        def post(url, **request):
            calls.append(request)
            return queue.pop(0)

        with patch("requests.post", side_effect=post), patch("time.sleep", side_effect=waits.append):
            result = self.gateway._http_chat("key", "https://api.deepseek.com", "deepseek-v4-pro", "S", "U", **kwargs)
        return result, calls, waits

    def test_a_rate_limited_call_waits_as_told_and_asks_the_same_credential_again(self):
        body = json.dumps({"choices": [{"message": {"content": "好"}}], "usage": {}}).encode()
        limited = _Plain(429, headers={"Retry-After": "1.5"})
        with self.assertLogs("app.core.model_gateway", level="WARNING"):
            result, calls, waits = self._chat_sequence([limited, _StreamingResponse([body], self.clock, seconds_per_chunk=1)])

        self.assertEqual(result, "好")
        self.assertEqual(len(calls), 2)
        self.assertEqual(waits, [1.5])
        self.assertTrue(limited.closed)
        self.gateway._mark_host_broken.assert_not_called()

    def test_rate_limiting_backs_off_a_few_times_then_gives_the_call_up_without_the_breaker(self):
        with self.assertLogs("app.core.model_gateway", level="WARNING"):
            result, calls, waits = self._chat_sequence([_Plain(429) for _ in range(model_gateway.RATE_LIMIT_RETRIES + 2)])

        self.assertIsNone(result)
        self.assertEqual(len(calls), model_gateway.RATE_LIMIT_RETRIES + 1)
        self.assertEqual(waits, [2.0, 4.0, 6.0])
        self.gateway._mark_host_broken.assert_not_called()

    def test_other_refusals_are_not_retried(self):
        with self.assertLogs("app.core.model_gateway", level="ERROR"):
            result, calls, waits = self._chat_sequence([_Plain(500), _Plain(500)])

        self.assertIsNone(result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(waits, [])

    def test_the_rate_limit_wait_reads_retry_after_and_is_capped(self):
        self.assertEqual(model_gateway.rate_limit_wait("3", 1), 3.0)
        self.assertEqual(model_gateway.rate_limit_wait(None, 2), 4.0)
        self.assertEqual(model_gateway.rate_limit_wait("Wed, 21 Oct 2026 07:28:00 GMT", 1), 2.0)
        self.assertEqual(model_gateway.rate_limit_wait("600", 1), model_gateway.RATE_LIMIT_WAIT_MAX)

    def test_a_response_without_a_stream_is_read_whole(self):
        class _Plain:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

        self.assertEqual(self._chat(_Plain())[0], "ok")
        self.assertTrue(hasattr(model_gateway, "LLMCallDeadlineExceeded"))


if __name__ == "__main__":
    unittest.main()

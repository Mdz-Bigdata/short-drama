"""Chat output defaults to a 1M limit; a provider that takes less is retried at its own ceiling, which is remembered."""

import unittest
from unittest.mock import patch

from app.core.model_gateway import DEFAULT_LLM_CALL_DEADLINE_SECONDS, DEFAULT_LLM_MAX_TOKENS, ModelGateway, allowed_max_tokens


class _Response:
    def __init__(self, status: int, body: dict | None = None, text: str = ""):
        self.status_code = status
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


def _ok(content: str = "好的") -> _Response:
    return _Response(200, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": {}})


class AllowedMaxTokensTests(unittest.TestCase):
    def test_the_figure_the_provider_gives_is_used(self):
        self.assertEqual(allowed_max_tokens(400, "Invalid max_tokens value, the valid range of max_tokens is [1, 65536]", 1_000_000), 65536)
        self.assertEqual(allowed_max_tokens(400, "max_tokens is too large: 1000000. This model supports at most 32768 completion tokens", 1_000_000), 32768)

    def test_a_context_length_refusal_leaves_room_for_the_prompt(self):
        message = ("This model's maximum context length is 131072 tokens. However, you requested 1003000 tokens "
                   "(3000 in the messages, 1000000 in the completion).")
        self.assertEqual(allowed_max_tokens(400, message, 1_000_000), 131072 - 3000 - 64)

    def test_without_a_figure_it_steps_down_and_other_errors_are_left_alone(self):
        self.assertEqual(allowed_max_tokens(400, "max_tokens exceeds the model limit", 1_000_000), 524_288)
        self.assertEqual(allowed_max_tokens(400, "max_tokens exceeds the model limit", 65_536), 32_768)
        self.assertIsNone(allowed_max_tokens(400, "invalid api key", 1_000_000))
        self.assertIsNone(allowed_max_tokens(500, "max_tokens too large", 1_000_000))
        self.assertIsNone(allowed_max_tokens(400, "max_tokens exceeds the model limit", 4_096))


class GatewayRetryTests(unittest.TestCase):
    def setUp(self):
        self.gateway = ModelGateway()
        self.sent: list[int] = []

    def _post(self, responses):
        queue = list(responses)

        def post(url, json=None, **kwargs):
            self.sent.append(json["max_tokens"])
            return queue.pop(0)

        return patch("requests.post", side_effect=post)

    def _chat(self, **kwargs):
        with patch.object(self.gateway, "_is_host_broken", return_value=False), patch.object(self.gateway, "_proxies_for", return_value=None):
            return self.gateway._http_chat("key", "https://api.deepseek.example/v1", "deepseek-flash", "S", "U", **kwargs)

    def test_by_default_the_call_asks_for_1m(self):
        self.assertEqual(DEFAULT_LLM_MAX_TOKENS, 1_000_000)
        with self._post([_ok()]), patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("LLM_MAX_TOKENS", None)
            self.assertEqual(self._chat(), "好的")
        self.assertEqual(self.sent, [1_000_000])

    def test_a_refused_limit_is_retried_at_the_providers_ceiling_and_remembered(self):
        refusal = _Response(400, text='{"error":{"message":"Invalid max_tokens value, the valid range of max_tokens is [1, 65536]"}}')
        with self._post([refusal, _ok("正文")]):
            self.assertEqual(self._chat(max_tokens=1_000_000), "正文")
        self.assertEqual(self.sent, [1_000_000, 65536])
        # The next call to the same model goes straight to the ceiling it learned.
        with self._post([_ok()]):
            self._chat(max_tokens=1_000_000)
        self.assertEqual(self.sent[-1], 65536)
        # A smaller request than the ceiling is left as it is.
        with self._post([_ok()]):
            self._chat(max_tokens=2000)
        self.assertEqual(self.sent[-1], 2000)

    def test_an_unrelated_refusal_is_not_retried(self):
        with self._post([_Response(400, text="invalid api key")]):
            self.assertIsNone(self._chat(max_tokens=1_000_000))
        self.assertEqual(self.sent, [1_000_000])

    def test_stepping_down_stops_after_a_few_tries(self):
        refusals = [_Response(400, text="max_tokens exceeds the model limit") for _ in range(6)]
        with self._post(refusals):
            self.assertIsNone(self._chat(max_tokens=1_000_000))
        self.assertEqual(self.sent, [1_000_000, 524_288, 262_144, 131_072, 65_536])


class CallDeadlineTests(unittest.TestCase):
    """A long reasoning call gets 30 minutes by default; the env and an explicit deadline override it."""

    def _deadline_seen(self, env: dict, **kwargs) -> float:
        gateway = ModelGateway()
        seen: list[float] = []

        def json_within(response, deadline):
            seen.append(deadline - started[0])
            return {"choices": [{"message": {"content": "好"}, "finish_reason": "stop"}], "usage": {}}

        started = [0.0]
        with patch.object(gateway, "_is_host_broken", return_value=False), patch.object(gateway, "_proxies_for", return_value=None), \
                patch.object(ModelGateway, "_json_within", side_effect=json_within), patch("time.monotonic", return_value=0.0), \
                patch("requests.post", return_value=_Response(200)), patch.dict("os.environ", env, clear=False):
            import os

            if "LLM_CALL_DEADLINE_SECONDS" not in env:
                os.environ.pop("LLM_CALL_DEADLINE_SECONDS", None)
            self.assertEqual(gateway._http_chat("key", "https://api.example/v1", "m", "S", "U", **kwargs), "好")
        return seen[0]

    def test_default_is_thirty_minutes_even_for_a_short_read_timeout(self):
        self.assertEqual(DEFAULT_LLM_CALL_DEADLINE_SECONDS, 1800)
        self.assertEqual(self._deadline_seen({}), 1800)
        self.assertEqual(self._deadline_seen({}, timeout=60), 1800)

    def test_env_and_an_explicit_deadline_override_it(self):
        self.assertEqual(self._deadline_seen({"LLM_CALL_DEADLINE_SECONDS": "3600"}), 3600)
        self.assertEqual(self._deadline_seen({"LLM_CALL_DEADLINE_SECONDS": "3600"}, deadline=80), 80)


if __name__ == "__main__":
    unittest.main()

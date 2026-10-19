"""A reasoning model that runs out of room mid-JSON gets a bigger budget, not the same request again."""

import json
import unittest
from unittest.mock import Mock, patch

from pydantic import BaseModel

from app.core.model_gateway import ModelGateway
from app.core.screenwriting.structured_llm import (
    DEFAULT_MAX_TOKENS_CAP,
    TRUNCATED_REASON,
    StructuredOutputError,
    call_structured,
    looks_truncated,
)
from app.platform.runtime_models import RuntimeModelConfiguration, runtime_model_registry


class _Plan(BaseModel):
    scenes: list[str]


class TruncationRetryTests(unittest.TestCase):
    def test_truncation_is_recognised(self):
        self.assertTrue(looks_truncated(""))
        self.assertTrue(looks_truncated('{"scenes": ["a", "b"'))
        self.assertTrue(looks_truncated('```json\n{"scenes": ['))
        self.assertFalse(looks_truncated('{"scenes": []}'))
        self.assertFalse(looks_truncated("抱歉，我无法完成"))

    def test_a_cut_off_answer_is_retried_with_twice_the_room_and_told_why(self):
        budgets, prompts = [], []

        def caller(system, user, max_tokens):
            budgets.append(max_tokens)
            prompts.append(user)
            return '{"scenes": ["a", "b"' if len(budgets) == 1 else json.dumps({"scenes": ["a", "b"]})

        result = call_structured(caller, system_prompt="s", user_prompt="u", schema=_Plan, max_tokens=8000, label="plan")
        self.assertEqual(result.data, {"scenes": ["a", "b"]})
        self.assertEqual(budgets, [8000, 16000])
        self.assertIn(TRUNCATED_REASON, prompts[1])

    def test_growth_stops_at_the_cap_and_ordinary_bad_json_keeps_the_budget(self):
        budgets = []

        def cut_off(system, user, max_tokens):
            budgets.append(max_tokens)
            return '{"scenes": ['

        with patch.dict("os.environ", {"SCREENWRITING_MAX_TOKENS_CAP": "32000"}), self.assertRaises(StructuredOutputError):
            call_structured(cut_off, system_prompt="s", user_prompt="u", schema=_Plan, max_tokens=20000, attempts=3)
        self.assertEqual(budgets, [20000, 32000, 32000])
        self.assertEqual(DEFAULT_MAX_TOKENS_CAP, 1_000_000)

        budgets.clear()
        with patch.dict("os.environ", {"SCREENWRITING_MAX_TOKENS_CAP": "12000"}), self.assertRaises(StructuredOutputError):
            call_structured(cut_off, system_prompt="s", user_prompt="u", schema=_Plan, max_tokens=8000, attempts=2)
        self.assertEqual(budgets, [8000, 12000])

        budgets.clear()

        def prose(system, user, max_tokens):
            budgets.append(max_tokens)
            return "这是一段说明文字，不是 JSON"

        with self.assertRaises(StructuredOutputError):
            call_structured(prose, system_prompt="s", user_prompt="u", schema=_Plan, max_tokens=8000, attempts=2)
        self.assertEqual(budgets, [8000, 8000])


class _Response:
    status_code = 200
    text = ""

    def __init__(self, content, finish):
        self._body = {"choices": [{"message": {"content": content}, "finish_reason": finish}],
                      "usage": {"completion_tokens": 7999, "completion_tokens_details": {"reasoning_tokens": 7999}}}

    def json(self):
        return self._body


class GatewayLengthTests(unittest.TestCase):
    def setUp(self):
        runtime_model_registry.replace([RuntimeModelConfiguration(
            configuration_id="deepseek", category="text", provider="deepseek", base_url="https://api.deepseek.com",
            api_key="k", model_ids=("deepseek-flash",),
        )])
        self.addCleanup(runtime_model_registry.replace, [])
        self.gateway = ModelGateway.__new__(ModelGateway)
        self.gateway.tls_verify = True

    def _call(self, response):
        with patch("requests.post", return_value=response), \
             patch.object(self.gateway, "_is_host_broken", return_value=False), \
             patch.object(self.gateway, "_proxies_for", return_value=None), \
             patch.object(self.gateway, "_note_host_ok"), \
             patch.object(self.gateway, "_provider_creds", side_effect=AssertionError("no legacy fallback after a cut-off reply")):
            return self.gateway.call_llm("deepseek-flash", "s", "u", "t", max_tokens=8000)

    def test_an_empty_reply_cut_off_while_thinking_is_returned_not_replaced_by_another_provider(self):
        with self.assertLogs("app.core.model_gateway", level="WARNING") as logs:
            self.assertEqual(self._call(_Response("", "length")), "")
        self.assertIn("max_tokens=8000", logs.output[0])
        self.assertIn("推理 7999", logs.output[0])

    def test_a_cut_off_answer_is_returned_as_is_for_the_caller_to_judge(self):
        with self.assertLogs("app.core.model_gateway", level="WARNING"):
            self.assertEqual(self._call(_Response('{"scenes": [', "length")), '{"scenes": [')

    def test_a_complete_answer_logs_nothing(self):
        with patch.object(ModelGateway, "_remember_chat_usage", Mock()):
            with self.assertNoLogs("app.core.model_gateway", level="WARNING"):
                self.assertEqual(self._call(_Response('{"scenes": []}', "stop")), '{"scenes": []}')


if __name__ == "__main__":
    unittest.main()

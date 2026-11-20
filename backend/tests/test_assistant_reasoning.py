"""A reasoning model's readable thinking is kept beside the assistant's reply, for a person to open, and nowhere else."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import embedded_agent, prompt_data
from app.core.model_gateway import ModelGateway
from app.platform.runtime_models import RuntimeModelConfiguration, runtime_model_registry
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService


class _Response:
    status_code = 200
    text = ""

    def __init__(self, message):
        self._body = {"choices": [{"message": message, "finish_reason": "stop"}], "usage": {"completion_tokens": 9}}

    def json(self):
        return self._body


class GatewayReasoningTest(unittest.TestCase):
    def setUp(self):
        runtime_model_registry.replace([RuntimeModelConfiguration(
            configuration_id="deepseek", category="text", provider="deepseek", base_url="https://api.deepseek.com",
            api_key="k", model_ids=("deepseek-flash",),
        )])
        self.addCleanup(runtime_model_registry.replace, [])
        self.gateway = ModelGateway.__new__(ModelGateway)
        self.gateway.tls_verify = True

    def _call(self, message):
        with patch("requests.post", return_value=_Response(message)), \
             patch.object(self.gateway, "_is_host_broken", return_value=False), \
             patch.object(self.gateway, "_proxies_for", return_value=None), \
             patch.object(self.gateway, "_note_host_ok"):
            return self.gateway.call_llm("deepseek-flash", "s", "u", "t", max_tokens=800)

    def test_the_thinking_is_taken_once_and_the_answer_is_unchanged(self):
        answer = self._call({"content": "好的", "reasoning_content": "  先看用户要什么。\n再回答。 "})
        self.assertEqual(answer, "好的")
        self.assertEqual(self.gateway.take_reasoning(), "先看用户要什么。\n再回答。")
        self.assertEqual(self.gateway.take_reasoning(), "")

    def test_the_other_field_name_is_read_too(self):
        self._call({"content": "好的", "reasoning": "想了一下"})
        self.assertEqual(self.gateway.take_reasoning(), "想了一下")

    def test_an_answer_without_thinking_leaves_none_from_an_earlier_call(self):
        self._call({"content": "一", "reasoning_content": "上一次的思考"})
        self._call({"content": "二"})
        self.assertEqual(self.gateway.take_reasoning(), "")
        self._call({"content": "三", "reasoning_content": "上一次的思考"})
        with patch.object(self.gateway, "_call_llm_unmetered", return_value="离线模板"):
            self.gateway.call_llm("deepseek-flash", "s", "u", "t")
        self.assertEqual(self.gateway.take_reasoning(), "")

    def test_a_thinking_field_that_is_not_text_is_ignored(self):
        self._call({"content": "好的", "reasoning_content": {"steps": [1, 2]}})
        self.assertEqual(self.gateway.take_reasoning(), "")


def _task():
    return {
        "task_id": "think-1", "status": "idle", "current_stage": 1, "stage_name": "",
        "config": {"title_suggestion": "雨夜", "llm_model": "deepseek-flash"}, "assets": {}, "logs": {}, "chat_history": [],
    }


class AgentReasoningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service.repo.save_task("think-1", _task())

    def _run(self, answers, thoughts):
        def llm(*args, **kwargs):
            self.service.gateway._thread_state.last_reasoning = thoughts.pop(0)
            return answers.pop(0)

        with patch.object(self.service.gateway, "call_llm", side_effect=llm):
            return self.service._agent_turn(
                "think-1", self.service.repo.get_task("think-1"), "/agent 看看", user={"user_id": "u1", "role": "user"},
            )

    def test_every_call_of_the_turn_is_kept_in_order_on_the_shown_reply_only(self):
        self._run(
            [json.dumps({"tool": "get_project", "arguments": {}}), json.dumps({"reply": "项目在第一步"})],
            ["先读项目状态", "状态读到了，回答"],
        )
        stored = self.service.repo.get_task("think-1")
        shown = stored["chat_history"][-1]
        separator = prompt_data.value("embedded_agent", "reasoning")["separator"]
        self.assertEqual(shown["content"], "项目在第一步")
        self.assertEqual(shown["reasoning"], f"先读项目状态{separator}状态读到了，回答")
        self.assertNotIn("先读项目状态", json.dumps(stored[embedded_agent.HISTORY_KEY], ensure_ascii=False))

    def test_a_reply_without_thinking_stores_no_field(self):
        self._run([json.dumps({"reply": "好"})], [""])
        self.assertNotIn("reasoning", self.service.repo.get_task("think-1")["chat_history"][-1])

    def test_long_thinking_is_cut_to_the_stored_limit(self):
        limit = int(prompt_data.value("embedded_agent", "reasoning")["max_chars"])
        self._run([json.dumps({"reply": "好"})], ["想" * (limit + 500)])
        kept = self.service.repo.get_task("think-1")["chat_history"][-1]["reasoning"]
        self.assertTrue(kept.endswith(prompt_data.value("embedded_agent", "reasoning")["cut"]))
        self.assertLessEqual(len(kept), limit + 20)

    def test_a_gateway_without_the_reader_gives_nothing(self):
        self.assertEqual(embedded_agent._reasoning_of(object()), "")


if __name__ == "__main__":
    unittest.main()

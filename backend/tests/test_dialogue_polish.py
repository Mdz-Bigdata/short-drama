"""润色台词：逐句对应、不增删、不换说话人；回答对不上就整段作废。"""

import unittest

from app.core.dialogue_polish import Line, PolishError, build_prompt, parse_answer, scene_plugin

LINES = [
    Line("1", "林夏", "我希望你以后不要再替我做决定，因为这会让我感到不被尊重。", "压着火"),
    Line("2", "顾言", "我只是出于好意，你没有必要这么激动。"),
]


class DialoguePolishTests(unittest.TestCase):
    def test_the_prompt_carries_rules_voices_scene_and_every_line(self):
        system, user = build_prompt(LINES, voices={"林夏": "嘴硬，句子短", "顾言": "表面平静"}, context="医院走廊，深夜", scene_kind="吵架戏", extra="再冷一点")
        self.assertIn("台词润色师", system)
        for phrase in ("保留原意", "接球", "林夏：嘴硬，句子短", "这场是吵架戏", "医院走廊", "再冷一点", "\"id\": \"2\"", "压着火"):
            self.assertIn(phrase, user)
        self.assertEqual(scene_plugin("家人对峙"), scene_plugin("家人"))
        with self.assertRaises(PolishError):
            build_prompt([])

    def test_each_line_comes_back_in_place_and_a_bad_answer_is_refused(self):
        answer = '好的```json\n{"lines": [{"id": "1", "text": "林夏：（冷笑）你以后别替我做主。"}, {"id": "2", "text": "我那是怕你吃亏。"}]}\n```'
        result = parse_answer(answer, LINES)
        self.assertEqual([item["after"] for item in result], ["你以后别替我做主。", "我那是怕你吃亏。"])
        self.assertEqual(result[0]["before"], LINES[0].text)
        self.assertEqual(result[1]["speaker"], "顾言")
        for bad in ('{"lines": [{"id": "1", "text": "别管我。"}]}', '{"lines": [{"id": "1", "text": "a"}, {"id": "2", "text": "b"}, {"id": "9", "text": "c"}]}',
                    '{"lines": [{"id": "1", "text": ""}, {"id": "2", "text": "b"}]}', "我改好了"):
            with self.assertRaises(PolishError, msg=bad):
                parse_answer(bad, LINES)


if __name__ == "__main__":
    unittest.main()


class ServiceTests(unittest.TestCase):
    """一次文本模型调用、逐句改前改后、不写回；题眼台词不动；离线模板不算润色。"""

    def setUp(self):
        from unittest.mock import MagicMock, patch
        from app.service.drama_service import DramaService
        self.service = DramaService.__new__(DramaService)
        self.service.gateway = MagicMock()
        self.service.gateway.last_answer_was_offline.return_value = False
        self.service.repo = MagicMock()
        self.service.repo.get_task.return_value = {"task_id": "t", "config": {"llm_model": "deepseek-chat"}}
        plan = {"scenes": [
            {"scene_id": "E1S01", "setting": "磨刀铺内", "scene_description": "雨夜", "key_line": "刀不认人，我认。", "utterances": [
                {"kind": "dialogue", "speaker": "裘三娘", "text": "我希望你在三天之内把这把刀磨好。"},
                {"kind": "voiceover", "speaker": None, "text": "雨一直下。"},
                {"kind": "dialogue", "speaker": "谢九", "text": "刀不认人，我认。"},
            ]},
            {"scene_id": "E1S02", "utterances": [{"kind": "dialogue", "speaker": "谢九", "text": "你要杀的人是谁呢？"}]},
        ]}
        episode = MagicMock(plan=plan, plan_revision="rev-123456789")
        patches = [
            patch("app.service.drama_service.screenwriting.episode_response", return_value=episode),
            patch("app.service.drama_service.screenwriting.state_of", return_value={"inventory": {"characters": {"谢九": {"voice_style": "句子极短"}}}}),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_one_scene_is_polished_line_by_line_and_the_key_line_is_left_alone(self):
        self.service.gateway.call_llm.return_value = '{"lines": [{"id": "E1S01#0", "text": "三天。磨快它。"}]}'
        result = self.service.polish_dialogue("t", 1, scene_ids=["E1S01"], scene_kind="对峙")
        self.assertEqual([(item["scene_id"], item["index"], item["after"]) for item in result["items"]], [("E1S01", 0, "三天。磨快它。")])
        self.assertEqual(result["plan_revision"], "rev-123456789")
        self.assertEqual(len(result["scenes"]["E1S01"]), 3, "the whole utterance list comes back so the apply step can replace texts")
        user_prompt = self.service.gateway.call_llm.call_args.args[2]
        self.assertNotIn("刀不认人，我认。", user_prompt.split("要润色的台词")[1], "the key line is not sent for polishing")
        self.assertNotIn("雨一直下", user_prompt, "voiceover is not dialogue")
        self.service.repo.mutate_task.assert_not_called()

    def test_an_offline_template_answer_is_not_a_polish(self):
        self.service.gateway.call_llm.return_value = '{"lines": []}'
        self.service.gateway.last_answer_was_offline.return_value = True
        with self.assertRaisesRegex(RuntimeError, "离线模板"):
            self.service.polish_dialogue("t", 1)

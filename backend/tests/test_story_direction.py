# -*- coding: utf-8 -*-
"""Story directions before a project is made, and the creator's no-go list."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import prompt_data, story_direction
from app.schema.drama import DramaCreateRequest

DIRECTION = {"title": "替父收煞", "logline": "纸人阿萤替亡女尽孝，夺阴火续纸骨", "conflict": "纸身怕水，镇上却连下秋雨",
             "hook": "头七夜，纸人睁眼叫了一声爹", "appeal": "惊悚里藏着尽孝的温情"}


def answer(count: int = 4, **changes) -> str:
    rows = [{**DIRECTION, "title": f"方向{index}", **changes} for index in range(count)]
    return json.dumps({"directions": rows}, ensure_ascii=False)


class NormalizeTests(unittest.TestCase):
    def test_a_direction_needs_a_title_and_a_story_and_every_field_is_one_short_line(self):
        self.assertEqual(story_direction.normalize_direction({"title": "只有名字"}), {})
        self.assertEqual(story_direction.normalize_direction("替父收煞"), {})
        long = story_direction.normalize_direction({**DIRECTION, "conflict": "冲突\n" * 200, "extra": "丢掉"})
        limits = prompt_data.load("story_direction")["limits"]
        self.assertLessEqual(len(long["conflict"]), limits["field_chars"])
        self.assertNotIn("\n", long["conflict"])
        self.assertNotIn("extra", long)
        self.assertEqual(set(long), set(story_direction.fields()))

    def test_no_go_lines_lose_their_list_marks_and_repeats_and_stop_at_the_limit(self):
        self.assertEqual(story_direction.normalize_no_go("1. 不要重生\n- 不要失忆梗\n\n• 不要重生"), ["不要重生", "不要失忆梗"])
        limits = prompt_data.load("story_direction")["limits"]
        many = story_direction.normalize_no_go([f"不要第{i}种桥段" for i in range(30)])
        self.assertEqual(len(many), limits["no_go_items"])
        self.assertEqual(story_direction.normalize_no_go(None), [])
        self.assertLessEqual(len(story_direction.normalize_no_go(["字" * 500])[0]), limits["no_go_chars"])


class PromptTests(unittest.TestCase):
    def test_the_request_carries_the_idea_the_mode_and_what_was_already_chosen(self):
        system, user, wanted = story_direction.prompts(
            idea="纸扎匠给早夭的女儿扎了纸人", count=3,
            config={"creation_mode": "drama", "episode_count": 3, "target_audience": {"lean": "female", "age": ""},
                    "script_structure": "three_act", "story_no_go": ["不要血腥"]},
        )
        self.assertEqual(wanted, 3)
        self.assertIn("提出 3 个", system)
        self.assertIn('"directions"', system)
        for piece in ("纸扎匠给早夭的女儿扎了纸人", "竖屏短剧", "【计划集数】3", "女频", "三幕式", "不要血腥"):
            self.assertIn(piece, user)

    def test_a_hot_topic_lends_its_feeling_and_never_its_real_people(self):
        config = {"creation_mode": "drama", "episode_count": 3}
        plain_system, plain_user, _ = story_direction.prompts(idea="外卖员替人顶罪", config=config)
        system, user, _ = story_direction.prompts(idea="外卖员替人顶罪", config=config, trend="  某综艺里素人一句话怼哭评委 \n ")
        self.assertTrue(user.startswith("【想借的热点】某综艺里素人一句话怼哭评委\n"))
        self.assertTrue(system.startswith(plain_system))
        for piece in ("只借这种情绪和结构", "不照搬真人真事", "不用真实的人名", "你没有热度数据"):
            self.assertIn(piece, system)
        # With nothing typed the request is what it always was.
        self.assertEqual(story_direction.prompts(idea="外卖员替人顶罪", config=config, trend="   ")[:2], (plain_system, plain_user))
        # It also works with no idea at all, and a long one is cut.
        open_system, open_user, _ = story_direction.prompts(idea="", config=config, trend="热" * 900)
        self.assertIn("补充要求", open_system)
        self.assertEqual(open_user.count("热"), prompt_data.load("story_direction")["limits"]["trend_chars"] + 1)

    def test_requests_that_make_no_sense_are_refused_in_words(self):
        for kwargs, said in (
            (dict(idea="想法", config={"creation_mode": "ad"}), "广告"),
            (dict(idea="想法", config={"creation_mode": "drama", "script_content": "正文"}), "上传的剧本"),
            (dict(idea="字" * 5000, config={"creation_mode": "drama"}), "最多"),
        ):
            with self.assertRaises(story_direction.StoryDirectionError) as refused:
                story_direction.prompts(**kwargs)
            self.assertIn(said, str(refused.exception))

    def test_no_idea_asks_for_recommendations_of_different_genres_instead_of_refusing(self):
        system, user, count = story_direction.prompts(idea="  ", config={
            "creation_mode": "drama", "episode_count": 30, "story_no_go": ["不要失忆梗"],
        })
        limits = prompt_data.load("story_direction")["limits"]
        self.assertEqual(count, limits["count_open"])
        for piece in ("创作者还没有想法", f"{count} 个方向各用一种不同的题材", "反过来用", "你没有数据"):
            self.assertIn(piece, system)
        for piece in ("竖屏短剧", "【计划集数】30", "不要失忆梗", "还没有，请直接推荐方向"):
            self.assertIn(piece, user)
        self.assertNotIn("{", user)

    def test_with_an_idea_one_direction_turns_the_usual_setup_around_without_touching_what_was_named(self):
        system, user, count = story_direction.prompts(idea="纸扎匠给早夭的女儿扎了纸人", config={"creation_mode": "drama"})
        self.assertEqual(count, prompt_data.load("story_direction")["limits"]["count_default"])
        self.assertIn("至少有一个方向把这类故事里观众最熟的那个设定反过来用", system)
        self.assertIn("创作者点名的人物和设定不动", system)
        self.assertIn("纸扎匠给早夭的女儿扎了纸人", user)

    def test_a_picked_direction_can_stand_in_for_the_idea(self):
        self.assertEqual(story_direction.idea_from({"title": "替父收煞", "logline": "纸人阿萤替亡女尽孝", "hook": "x"}), "替父收煞：纸人阿萤替亡女尽孝")
        self.assertEqual(story_direction.idea_from({"title": "只有名字"}), "")

    def test_the_count_stays_inside_its_limits(self):
        limits = prompt_data.load("story_direction")["limits"]
        self.assertEqual(story_direction.prompts(idea="想法", config={"creation_mode": "film"}, count=99)[2], limits["count_max"])
        self.assertEqual(story_direction.prompts(idea="想法", config={"creation_mode": "film"}, count=1)[2], limits["count_min"])
        self.assertEqual(story_direction.prompts(idea="想法", config={"creation_mode": "film"})[2], limits["count_default"])

    def test_an_answer_gives_distinct_usable_directions_or_says_why_not(self):
        self.assertEqual(len(story_direction.parse(f"好的：\n```json\n{answer(4)}\n```")), 4)
        same = json.dumps({"directions": [DIRECTION, DIRECTION, {**DIRECTION, "title": "另一个"}]}, ensure_ascii=False)
        self.assertEqual([item["title"] for item in story_direction.parse(same)], ["替父收煞", "另一个"])
        for bad, said in (("", "没有给出回答"), ("我想了四个方向", "不是要求的格式"), (answer(1), "只给出了 1 个")):
            with self.assertRaises(story_direction.StoryDirectionError) as refused:
                story_direction.parse(bad)
            self.assertIn(said, str(refused.exception))


class RuleTests(unittest.TestCase):
    def test_the_director_is_told_the_chosen_direction_and_the_no_go_list(self):
        rule = story_direction.director_rule({"creation_mode": "drama", "story_direction": DIRECTION, "story_no_go": ["不要失忆梗"]})
        self.assertIn("【已选故事方向】", rule)
        self.assertIn("替父收煞", rule)
        self.assertIn("头七夜，纸人睁眼叫了一声爹", rule)
        self.assertIn("【创作禁区】", rule)
        self.assertIn("- 不要失忆梗", rule)

    def test_nothing_chosen_says_nothing_and_an_advert_or_an_uploaded_script_gets_neither(self):
        self.assertEqual(story_direction.director_rule({"creation_mode": "drama"}), "")
        self.assertEqual(story_direction.outline_rules({"creation_mode": "drama"}), [])
        chosen = {"story_direction": DIRECTION, "story_no_go": ["不要失忆梗"]}
        self.assertEqual(story_direction.director_rule({"creation_mode": "ad", **chosen}), "")
        self.assertEqual(story_direction.director_rule({"creation_mode": "drama", "script_content": "正文", **chosen}), "")
        self.assertEqual(story_direction.outline_rules({"creation_mode": "ad", **chosen}), [])

    def test_every_episode_batch_gets_the_no_go_list_and_not_the_direction(self):
        rules = story_direction.outline_rules({"creation_mode": "narration", "story_direction": DIRECTION, "story_no_go": ["不要失忆梗", "不要重生"]})
        self.assertEqual(len(rules), 1)
        self.assertIn("不要失忆梗；不要重生", rules[0])
        self.assertNotIn("替父收煞", rules[0])

    def test_the_create_request_takes_both_in_camel_case(self):
        request = DramaCreateRequest.model_validate({
            "titleSuggestion": "纸女儿", "storyDirection": DIRECTION, "storyNoGo": ["不要失忆梗"],
        })
        self.assertEqual(request.story_direction["title"], "替父收煞")
        self.assertEqual(request.story_no_go, ["不要失忆梗"])
        self.assertEqual(DramaCreateRequest.model_validate({"titleSuggestion": "纸女儿"}).story_no_go, [])


class WiringTests(unittest.TestCase):
    def test_the_director_prompt_and_the_planner_read_the_same_module(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app"
        self.assertIn("story_direction.director_rule(config)", (root / "service" / "drama_service.py").read_text(encoding="utf-8"))
        self.assertIn("story_direction.outline_rules(self.creation)", (root / "core" / "screenwriting" / "engine.py").read_text(encoding="utf-8"))
        self.assertIn("story_direction.NO_GO_KEY: story_direction.no_go_of(config)",
                      (root / "service" / "screenwriting_service.py").read_text(encoding="utf-8"))


class RouteTests(unittest.TestCase):
    def setUp(self):
        from app.api import drama_api, story_direction_api
        from app.api.auth_api import get_current_user

        self.gateway = drama_api.service.gateway
        app = FastAPI()
        app.include_router(story_direction_api.router)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "username": "u1", "role": "user", "permissions": []}
        self.client = TestClient(app)

    def test_one_text_call_returns_the_directions_and_stores_nothing(self):
        with mock.patch.object(self.gateway, "call_llm", return_value=answer(4)) as called, \
                mock.patch.object(self.gateway, "last_answer_was_offline", return_value=False):
            done = self.client.post("/api/story-directions", json={
                "idea": "纸扎匠给早夭的女儿扎了纸人", "creationMode": "drama", "episodeCount": 3, "llmModel": "deepseek-flash",
                "storyNoGo": ["不要血腥"],
            })
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(len(done.json()["directions"]), 4)
        self.assertEqual(done.json()["model"], "deepseek-flash")
        self.assertEqual(called.call_count, 1)
        self.assertEqual(called.call_args.args[0], "deepseek-flash")
        self.assertIn("不要血腥", called.call_args.args[2])
        self.assertEqual(called.call_args.kwargs["max_tokens"], prompt_data.load("story_direction")["limits"]["max_tokens"])

    def test_the_hot_topic_typed_in_the_form_reaches_the_model(self):
        with mock.patch.object(self.gateway, "call_llm", return_value=answer(4)) as called, \
                mock.patch.object(self.gateway, "last_answer_was_offline", return_value=False):
            done = self.client.post("/api/story-directions", json={
                "idea": "外卖员替人顶罪", "creationMode": "drama", "episodeCount": 3, "llmModel": "deepseek-flash", "trend": "素人一句话怼哭评委",
            })
        self.assertEqual(done.status_code, 200, done.text)
        self.assertIn("不照搬真人真事", called.call_args.args[1])
        self.assertIn("【想借的热点】素人一句话怼哭评委", called.call_args.args[2])

    def test_an_offline_template_answer_is_not_passed_off_as_directions(self):
        with mock.patch.object(self.gateway, "call_llm", return_value=answer(4)), \
                mock.patch.object(self.gateway, "last_answer_was_offline", return_value=True):
            done = self.client.post("/api/story-directions", json={"idea": "想法", "llmModel": "deepseek-flash"})
        self.assertEqual(done.status_code, 422)
        self.assertIn("没有给出回答", done.json()["detail"])

    def test_an_advert_and_a_missing_model_are_refused_before_any_model_is_called(self):
        with mock.patch.object(self.gateway, "call_llm", side_effect=AssertionError("no model call")):
            advert = self.client.post("/api/story-directions", json={"idea": "卖茶", "creationMode": "ad", "llmModel": "m"})
            no_model = self.client.post("/api/story-directions", json={"idea": " ", "llmModel": " "})
        self.assertEqual((advert.status_code, no_model.status_code), (422, 422))
        self.assertIn("广告", advert.json()["detail"])

    def test_an_empty_idea_gets_recommendations_and_the_idea_each_would_stand_for(self):
        with mock.patch.object(self.gateway, "call_llm", return_value=answer(5)) as called, \
                mock.patch.object(self.gateway, "last_answer_was_offline", return_value=False):
            done = self.client.post("/api/story-directions", json={"idea": " ", "creationMode": "drama", "episodeCount": 20, "llmModel": "deepseek-flash"})
        self.assertEqual(done.status_code, 200, done.text)
        body = done.json()
        self.assertTrue(body["open"])
        self.assertEqual((body["asked"], len(body["directions"]), len(body["ideas"])), (5, 5, 5))
        first = body["directions"][0]
        self.assertEqual(body["ideas"][0], f"{first['title']}：{first['logline']}")
        self.assertIn("创作者还没有想法", called.call_args.args[1])
        self.assertTrue(called.call_args.args[3])

    def test_the_form_can_read_the_field_labels_and_limits(self):
        shown = self.client.get("/api/story-directions").json()
        self.assertEqual([item["key"] for item in shown["fields"]], list(story_direction.fields()))
        self.assertEqual(shown["count"], 4)


if __name__ == "__main__":
    unittest.main()

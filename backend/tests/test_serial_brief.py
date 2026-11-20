# -*- coding: utf-8 -*-
"""Genres, tone, ending and the overseas switch chosen for a serial, and the paywall plan worked out from its length."""

from __future__ import annotations

import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import paywall_plan, prompt_data, serial_brief
from app.schema.drama import DramaCreateRequest

FULL = {"creation_mode": "drama", "episode_count": 60, "story_genres": ["war_god", "baby"], "story_tone": "blazing",
        "ending_type": "twist", "overseas": True, "paywall_plan": True}


class CatalogueTests(unittest.TestCase):
    def test_every_genre_points_at_tables_that_exist(self):
        data = prompt_data.load("serial_brief")
        kinds = prompt_data.load("paywall_plan")["kinds"]
        self.assertEqual(len(data["genres"]), 13)
        self.assertEqual(len({row["id"] for row in data["genres"]}), 13)
        for row in data["genres"]:
            with self.subTest(genre=row["id"]):
                self.assertIn(row["opening"], data["openings"])
                self.assertEqual(len(row["payoffs"]), 2)
                self.assertTrue(all(key in data["payoffs"] for key in row["payoffs"]))
                self.assertTrue(row["hooks"] and all(key in data["hooks"] for key in row["hooks"]))
                self.assertIn(row["paywall"], kinds)
                self.assertTrue(row["hint"] and row["audience"] and row["payoff"] and row["villains"])
        for clash in data["clashes"]:
            self.assertTrue(set(clash["pair"]) <= {row["id"] for row in data["genres"]})

    def test_the_form_gets_labels_and_hints_and_no_writing_rules(self):
        shown = serial_brief.catalog()
        self.assertEqual(shown["max_genres"], 3)
        self.assertEqual(len(shown["genres"]), 13)
        self.assertEqual(set(shown["genres"][0]), {"id", "label", "hint", "audience", "payoff"})
        self.assertEqual([item["id"] for item in shown["tones"]], ["blazing", "bittersweet", "funny", "dark", "warm"])
        self.assertEqual([item["id"] for item in shown["endings"]], ["happy", "open", "twist", "tragic"])


class NormalizeTests(unittest.TestCase):
    def test_genres_keep_their_order_drop_unknowns_and_repeats_and_stop_at_three(self):
        self.assertEqual(serial_brief.normalize_genres(["baby", "nope", "war_god", "baby", "sweet", "ceo"]), ["baby", "war_god", "sweet"])
        self.assertEqual(serial_brief.normalize_genres("mystery"), ["mystery"])
        self.assertEqual(serial_brief.normalize_genres(None), [])
        self.assertEqual((serial_brief.normalize_tone("dark"), serial_brief.normalize_tone("loud")), ("dark", ""))
        self.assertEqual((serial_brief.normalize_ending("open"), serial_brief.normalize_ending("")), ("open", ""))

    def test_only_a_serial_written_by_the_pipeline_keeps_a_brief(self):
        for config in ({**FULL, "creation_mode": "ad"}, {**FULL, "creation_mode": "film"}, {**FULL, "script_content": "正文"}):
            with self.subTest(config=config.get("creation_mode")):
                self.assertFalse(serial_brief.chosen(config))
                self.assertEqual(serial_brief.director_rule(config), "")
                self.assertEqual(serial_brief.outline_rules(config, last=60, total=60), [])
                self.assertEqual(paywall_plan.of(config), [])
        self.assertTrue(serial_brief.chosen({"creation_mode": "narration", "story_tone": "warm"}))

    def test_the_create_request_takes_the_choices_in_camel_case(self):
        request = DramaCreateRequest.model_validate({
            "titleSuggestion": "战神奶爸", "storyGenres": ["war_god", "baby"], "storyTone": "blazing", "endingType": "happy",
            "overseas": True, "paywallPlan": True,
        })
        self.assertEqual((request.story_genres, request.story_tone, request.ending_type, request.overseas, request.paywall_plan),
                         (["war_god", "baby"], "blazing", "happy", True, True))
        bare = DramaCreateRequest.model_validate({"titleSuggestion": "战神奶爸"})
        self.assertEqual((bare.story_genres, bare.story_tone, bare.overseas, bare.paywall_plan), ([], "", False, False))


class BriefRuleTests(unittest.TestCase):
    def test_nothing_chosen_adds_nothing(self):
        bare = {"creation_mode": "drama", "episode_count": 60}
        self.assertEqual(serial_brief.director_rule(bare), "")
        self.assertEqual(serial_brief.outline_rules(bare, last=10, total=60), [])
        self.assertEqual(paywall_plan.director_rule(bare), "")
        self.assertEqual(paywall_plan.outline_rules(bare, first=1, last=10, total=60), [])

    def test_the_director_gets_the_lead_genres_way_of_playing_and_each_choice(self):
        rule = serial_brief.director_rule(FULL)
        for piece in ("【连载立项】", "题材：战神归来 + 萌宝。战神归来定基调", "- 萌宝：", "开场建议用「当场打脸」", "爽点以身份碾压",
                      "集尾钩子多用悬念", "反派配置：看不起人的亲戚", "故事基调：爽燃", "结局：反转式", "面向海外观众"):
            self.assertIn(piece, rule)
        only_tone = serial_brief.director_rule({"creation_mode": "drama", "story_tone": "warm"})
        self.assertIn("故事基调：温情", only_tone)
        self.assertNotIn("题材：", only_tone)
        self.assertNotIn("开场建议", only_tone)

    def test_a_clashing_pair_is_pointed_out_and_a_single_genre_has_no_lead_sentence(self):
        clash = serial_brief.director_rule({"creation_mode": "drama", "story_genres": ["sweet", "apocalypse"]})
        self.assertIn("甜宠和末日的气质相冲", clash)
        single = serial_brief.director_rule({"creation_mode": "drama", "story_genres": ["mystery"]})
        self.assertIn("题材：悬疑探案。", single)
        self.assertNotIn("定基调，其余", single)

    def test_each_batch_gets_one_line_and_the_last_batch_the_ending_rule(self):
        middle = serial_brief.outline_rules(FULL, last=20, total=60)
        self.assertEqual(len(middle), 1)
        self.assertIn("题材战神归来 + 萌宝", middle[0])
        self.assertIn("基调爽燃", middle[0])
        self.assertIn("结局反转式", middle[0])
        final = serial_brief.outline_rules(FULL, last=60, total=60)
        self.assertEqual(len(final), 2)
        self.assertIn("这一批写到全剧最后一集", final[1])


class PaywallPlanTests(unittest.TestCase):
    def test_positions_keep_the_spacing_the_first_window_and_the_run_in_to_the_end(self):
        data = prompt_data.load("paywall_plan")
        low, high = data["first_range"]
        for total in range(data["min_episodes"], 161):
            found = paywall_plan.positions(total)
            with self.subTest(total=total):
                self.assertEqual(found, sorted(set(found)))
                self.assertTrue(low <= found[0] <= high)
                self.assertEqual(found[-1], total - data["last_before_end"])
                self.assertTrue(all(later - earlier >= data["min_gap"] for earlier, later in zip(found, found[1:])))
                self.assertLessEqual(sum(1 for episode in found if episode <= 10), 2)
        self.assertEqual(paywall_plan.positions(29), [])
        self.assertEqual(paywall_plan.positions(60), [10, 18, 26, 34, 42, 56])
        self.assertEqual((len(paywall_plan.positions(55)), len(paywall_plan.positions(80)), len(paywall_plan.positions(100))), (6, 8, 11))

    def test_the_first_cliff_is_the_lead_genres_and_no_two_in_a_row_are_the_same(self):
        for genre in ("", "war_god", "sweet", "palace", "mystery"):
            rows = paywall_plan.plan(100, genre)
            with self.subTest(genre=genre):
                self.assertTrue(all(a["kind"] != b["kind"] for a, b in zip(rows, rows[1:])))
        self.assertEqual(paywall_plan.plan(60, "sweet")[0]["label"], "情感爆发中断")
        self.assertEqual(paywall_plan.plan(60, "palace")[0]["label"], "生死一线")

    def test_a_project_gets_a_plan_only_when_it_asked_for_one(self):
        self.assertEqual(paywall_plan.of({**FULL, "paywall_plan": False}), [])
        self.assertEqual(paywall_plan.of({**FULL, "episode_count": 12}), [])
        self.assertEqual([row["episode"] for row in paywall_plan.of(FULL)], [10, 18, 26, 34, 42, 56])

    def test_the_director_gets_the_episodes_and_the_rules_of_a_paywall_cliff(self):
        rule = paywall_plan.director_rule(FULL)
        self.assertIn("这部剧共 60 集，付费卡点放在这 6 集：第 10 集（身份即将揭露）", rule)
        self.assertIn("一个悬念只卡一次", rule)
        self.assertIn("一开头就兑现", rule)

    def test_the_director_is_told_not_to_answer_a_paywalls_question_earlier_in_the_plan(self):
        rule = paywall_plan.director_rule(FULL)
        self.assertIn("排在它之前的地方（前三集钩子阶梯、分段大纲、高光地图、伏笔台账）都只铺疑点，不先把答案给观众", rule)
        self.assertIn("卡点表里每个悬念的答案，没有在更早的集数出现过", rule)
        self.assertEqual(paywall_plan.director_rule({**FULL, "paywall_plan": False}), "")

    def test_a_batch_is_told_its_paywall_episodes_the_episode_after_one_and_the_free_run(self):
        opening = paywall_plan.outline_rules(FULL, first=1, last=10, total=60)
        self.assertEqual(len(opening), 3)
        self.assertIn("第 1–10 集在第一个付费卡点（第 10 集）之前", opening[0])
        self.assertIn("第 10 集是付费卡点集（身份即将揭露）", opening[1])
        following = paywall_plan.outline_rules(FULL, first=11, last=20, total=60)
        self.assertEqual(len(following), 4)
        for rule, head in zip(following, ("第 11 集紧接付费卡点", "第 18 集是付费卡点集", "第 19 集紧接付费卡点")):
            self.assertTrue(rule.startswith(head), rule)

    def test_a_batch_is_told_which_paywalls_lie_ahead_so_it_does_not_spend_their_suspense(self):
        opening = paywall_plan.outline_rules(FULL, first=1, last=10, total=60)[-1]
        self.assertTrue(opening.startswith("后面的付费卡点还有第 18 集（"), opening)
        for episode in (26, 34, 42, 56):
            self.assertIn(f"第 {episode} 集（", opening)
        self.assertNotIn("第 10 集", opening, "the batch's own paywall is not one that lies ahead")
        self.assertIn("只铺垫、不揭开", opening)
        between = paywall_plan.outline_rules(FULL, first=44, last=50, total=60)
        self.assertEqual(len(between), 1, "a batch with no paywall of its own still hears what is ahead")
        self.assertTrue(between[0].startswith("后面的付费卡点还有第 56 集（"), between[0])
        closing = paywall_plan.outline_rules(FULL, first=51, last=60, total=60)
        self.assertFalse(any("后面的付费卡点" in rule for rule in closing), "nothing lies ahead of the last batch")
        self.assertEqual(paywall_plan.outline_rules({**FULL, "paywall_plan": False}, first=1, last=10, total=60), [])

    def test_an_empty_hook_and_two_paywalls_that_stop_the_same_way_are_hinted_once(self):
        entries = [{"episode": 10, "hook": ""}, {"episode": 18, "hook": "【身份逼近】他抬起了证件"},
                   {"episode": 26, "hook": "【身份逼近】她喊出了半个名字"}, {"episode": 27, "hook": ""}]
        found = paywall_plan.warnings(entries, FULL, total=60)
        self.assertEqual(found, ["第 10 集是付费卡点集，结尾钩子是空的；卡点集要停在答案出来的前一刻。",
                                 "第 18 集和第 26 集两个付费卡点停的是同一种（身份逼近）；一个悬念只卡一次，换一种停法。"])
        self.assertEqual(paywall_plan.warnings(entries, FULL, total=60, fresh=[34]), [])
        self.assertEqual(paywall_plan.warnings(entries, {**FULL, "paywall_plan": False}, total=60), [])


class WiringTests(unittest.TestCase):
    def test_creation_the_director_prompt_and_the_planner_read_these_modules(self):
        root = Path(__file__).resolve().parents[1] / "app"
        service = (root / "service" / "drama_service.py").read_text(encoding="utf-8")
        for piece in ("serial_brief.GENRES_KEY: serial_brief.normalize_genres(", "paywall_plan.CONFIG_KEY: bool(",
                      "serial_brief.director_rule(config)", "paywall_plan.director_rule(config)"):
            self.assertIn(piece, service)
        engine = (root / "core" / "screenwriting" / "engine.py").read_text(encoding="utf-8")
        for piece in ("serial_brief.outline_rules(self.creation, last=last, total=total)",
                      "paywall_plan.outline_rules(self.creation, first=first, last=last, total=total)", "paywall_plan.warnings("):
            self.assertIn(piece, engine)
        self.assertIn("**serial_brief.of(config), paywall_plan.CONFIG_KEY: paywall_plan.applies(config)",
                      (root / "service" / "screenwriting_service.py").read_text(encoding="utf-8"))

    def test_the_engine_plans_a_batch_with_the_brief_and_its_paywall_episodes(self):
        from app.service import screenwriting_service

        prompts = []

        def model(*args, **kwargs):
            prompts.append("\n".join(str(part) for part in (*args, *kwargs.values())))
            return ""

        def planned(config):
            prompts.clear()
            engine = screenwriting_service.build_engine(model, config=config, title="t", system_prompt="S")
            try:
                engine._plan_outline_batch({"director_plan": "plan", "overview": {"synopsis": "s"}}, 1, 10, total=60, earlier=[])
            except Exception:  # noqa: BLE001 - an empty answer ends the batch; the prompt is what is checked
                pass
            return next(p for p in prompts if "# 总导演策划方案" in p)

        base = {"creation_mode": "drama", "llm_model": "m", "video_model": "seedance2.0", "episode_count": 60}
        plan = planned({**FULL, **base})
        for piece in ("题材战神归来 + 萌宝", "基调爽燃", "第 1–10 集在第一个付费卡点（第 10 集）之前", "第 10 集是付费卡点集（身份即将揭露）"):
            self.assertIn(piece, plan)
        bare = planned(base)
        for piece in ("付费卡点集", "题材战神归来", "基调爽燃"):
            self.assertNotIn(piece, bare)

    def test_a_project_stores_what_was_chosen_and_drops_what_it_does_not_know(self):
        import tempfile

        from app.repository.task_repo import TaskRepository
        from app.service.drama_service import DramaService

        with tempfile.TemporaryDirectory() as temp:
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            made = service.create_task(DramaCreateRequest(
                titleSuggestion="一部剧", episodeCount=60, storyGenres=["war_god", "nope", "baby"], storyTone="blazing",
                endingType="sideways", overseas=True, paywallPlan=True,
            ), owner_user_id="u1")
            config = service.repo.get_task(made["task_id"])["config"]
            self.assertEqual((config["story_genres"], config["story_tone"], config["ending_type"], config["overseas"], config["paywall_plan"]),
                             (["war_god", "baby"], "blazing", "", True, True))
            self.assertIn("付费卡点放在这 6 集", paywall_plan.director_rule(config))
            unset = service.repo.get_task(service.create_task(DramaCreateRequest(titleSuggestion="另一部剧"), owner_user_id="u1")["task_id"])["config"]
            self.assertEqual((unset["story_genres"], unset["story_tone"], unset["ending_type"], unset["overseas"], unset["paywall_plan"]),
                             ([], "", "", False, False))


class FormListTests(unittest.TestCase):
    """The new-project form keeps its own copy of the lists (it renders before any request); they must say the same."""

    def test_the_forms_ids_names_and_hints_are_the_ones_in_the_data(self):
        import re

        source = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "features" / "writer" / "serialBrief.ts").read_text(encoding="utf-8")
        rows = re.findall(r"\{ id: '([^']+)', label: '([^']+)'(?:, hint: '([^']+)')? \}", source)
        shown = serial_brief.catalog()
        expected = [(row["id"], row["label"], row["hint"]) for key in ("genres", "tones", "endings") for row in shown[key]]
        expected += [(key, row["label"], "") for key, row in prompt_data.load("paywall_plan")["kinds"].items()]
        self.assertEqual(rows, expected)
        clashes = re.findall(r"\{ pair: \['([^']+)', '([^']+)'\], say: '([^']+)' \}", source)
        self.assertEqual(clashes, [(*row["pair"], row["say"]) for row in shown["clashes"]])
        self.assertIn(f"MAX_GENRES = {shown['max_genres']};", source)


class RouteTests(unittest.TestCase):
    def setUp(self):
        from app.api import serial_brief_api
        from app.api.auth_api import get_current_user

        app = FastAPI()
        app.include_router(serial_brief_api.router)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "username": "u1", "role": "user", "permissions": []}
        self.client = TestClient(app)

    def test_the_form_reads_the_catalogue_and_the_plan_for_a_length(self):
        shown = self.client.get("/api/serial-brief").json()
        self.assertEqual((len(shown["genres"]), shown["max_genres"], shown["paywall_min_episodes"]), (13, 3, 30))
        plan = self.client.get("/api/serial-brief/paywall", params={"episodes": 60, "genre": "sweet"}).json()
        self.assertEqual([row["episode"] for row in plan["episodes"]], [10, 18, 26, 34, 42, 56])
        self.assertEqual(plan["episodes"][0]["label"], "情感爆发中断")
        short = self.client.get("/api/serial-brief/paywall", params={"episodes": 12}).json()
        self.assertEqual(short["episodes"], [])
        self.assertIn("不到 30 集", short["text"])
        self.assertEqual(self.client.get("/api/serial-brief/paywall", params={"episodes": 60, "genre": "nope"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()

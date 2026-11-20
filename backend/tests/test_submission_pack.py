# -*- coding: utf-8 -*-
"""The platform submission pack: the script body in the template's layout, the model items checked and kept,
and the two endpoints. No real model: answers are scripted."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import auth_service, get_current_user
from app.core import prompt_data, submission_pack
from app.repository.task_repo import TaskRepository
from main import app

from tests import test_screenwriting_pipeline as pipeline

WORDING = prompt_data.load("submission_pack")


def _shot(scene_id, heading, description, dialogue=(), characters=()):
    return {
        "scene_id": scene_id, "content": f"{heading} {description}", "description": description,
        "dialogue": list(dialogue), "characters": list(characters), "duration": "6s",
    }


SCENES = [
    _shot("E1S01", "实验室 夜 内景", "近景，冷白顶光。林夏推开实验室的门。镜头缓推。她在抽屉里找到了录音笔。",
          [{"kind": "dialogue", "speaker": "林夏", "text": "有人吗？", "delivery": "试探-压声 / 慢"}], ["林夏"]),
    _shot("E1S02", "实验室 夜 内景", "周教授从暗处走出，站在林夏身后。",
          [{"kind": "dialogue", "speaker": "周教授", "text": "回头还来得及。", "delivery": "OS / 冷"},
           {"kind": "voiceover", "speaker": "", "text": "那一夜，灯没有再亮。"}], ["林夏", "周教授"]),
    _shot("E2S01", "实验室 日 内景", "林夏攥着录音笔站在门口。",
          [{"kind": "dialogue", "speaker": "周教授", "text": "站住。", "delivery": "画外，冷"}], ["林夏"]),
]


def _task(episodes=2):
    return {
        "task_id": "pack-1",
        "config": {"title_suggestion": "请帮我写一部悬疑短剧", "episode_count": episodes},
        "assets": {
            "2_screenwriting": {
                "engine": "structured_screenwriting_v1", "source_kind": "outline", "episode_count": episodes,
                "overview": {"title": "暗室回声", "synopsis": "林夏追查实验室里的录音。", "genre": "悬疑", "world_setting": "现代都市"},
                "inventory": {
                    "characters": {"林夏": {"description": "二十六岁的实习研究员", "position": "女主角"},
                                   "周教授": {"description": "实验室主任", "position": "反派"}},
                    "relationships": [{"from_": "周教授", "to": "林夏", "relation": "导师", "bidirectional": False}],
                },
                "ledger": [
                    {"episode": number, "title": f"第{number}集标题", "hook": "门被反锁", "story_beats": ["林夏找到录音笔", "周教授出现"]}
                    for number in range(1, episodes + 1)
                ],
            },
        },
    }


def _details(**changes):
    answer = {
        "channel": "女频", "world": "现代", "category": "悬疑脑洞", "paywall_episode": 2,
        "paywall_reason": "第二集结尾周教授把门反锁，林夏手里的录音笔亮着红灯，观众想知道录下了什么。",
        "premiere_hook": "", "synopsis": "《暗室回声》讲述了" + "实习研究员林夏在实验室深夜加班时找到一支录音笔，" * 6,
        "characters": [
            {"name": "林夏", "gender": "女", "age": "二十六岁", "identity": "实习研究员", "personality": "执拗、细心",
             "intro": "实验室的实习研究员，深夜加班时找到一支来历不明的录音笔，从此一步步查到导师头上。她的目标是弄清录音里的人是谁。"},
        ],
    }
    answer.update(changes)
    return json.dumps(answer, ensure_ascii=False)


def _outline(text="林夏在实验室找到一支来历不明的录音笔，周教授深夜出现，两人第一次正面交锋；门被反锁，录音笔亮起红灯，"
                  "林夏发现录音里有一段被删掉的对话，而删掉它的人就在实验室里。阶段爽点是她当着周教授的面把录音备份发了出去，悬念压到下一段。"):
    return json.dumps({"outline": text}, ensure_ascii=False)


class Scripted:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, system, user, max_tokens):
        self.calls.append((system, user))
        return self.answers.pop(0) if self.answers else ""


class BodyTests(unittest.TestCase):
    def setUp(self):
        self.pack = submission_pack.compile_pack(_task(), SCENES)
        self.lines = submission_pack.body_lines(self.pack["body"])

    def test_the_body_is_laid_out_the_way_the_template_asks(self):
        lines = self.lines
        self.assertEqual(lines[0], "第一集")
        self.assertEqual(lines[1], "1-1 实验室 夜 内")
        self.assertEqual(lines[2], "出场人物：林夏，周教授")
        self.assertIn("第二集", lines)
        self.assertIn("2-1 实验室 日 内", lines)
        self.assertEqual(lines.count("（本集完）"), 2)

    def test_shooting_notes_are_taken_out_and_each_sentence_is_a_line(self):
        actions = [line for line in self.lines if line.startswith("△")]
        self.assertEqual(actions[0], "△林夏【字幕：林夏】推开实验室的门。")
        self.assertEqual(actions[1], "△她在抽屉里找到了录音笔。")
        for line in actions:
            for word in ("近景", "顶光", "镜头", "缓推"):
                self.assertNotIn(word, line)
        # A shot label in front of a long sentence goes too; the action behind it stays.
        self.assertEqual(submission_pack.action_sentences("特写：虎口上方三寸有一道浅白旧痕横过，掌心干净。"), ["虎口上方三寸有一道浅白旧痕横过，掌心干净。"])
        self.assertEqual(submission_pack.action_sentences("她低声说：别动。"), ["她低声说：别动。"])

    def test_people_and_places_get_a_caption_only_the_first_time(self):
        body = "\n".join(self.lines)
        self.assertEqual(body.count("【字幕：实验室】"), 1)
        self.assertEqual(body.count("【字幕：林夏"), 1)
        self.assertIn("周教授【字幕：周教授】从暗处走出", body)

    def test_lines_keep_a_short_delivery_and_inner_or_off_screen_voices_are_marked(self):
        self.assertIn("林夏（试探-压声）：有人吗？", self.lines)
        self.assertIn("周教授（冷OS）：回头还来得及。", self.lines)
        self.assertIn("【VO】旁白：那一夜，灯没有再亮。", self.lines)
        self.assertIn("【VO】周教授（冷）：站住。", self.lines)
        # Who speaks off screen still appears in the scene's cast line.
        self.assertIn("出场人物：林夏，周教授", self.lines[self.lines.index("2-1 实验室 日 内") + 1])

    def test_the_items_read_from_the_project_need_no_model(self):
        pack = self.pack
        self.assertEqual((pack["title"], pack["adapted_from"], pack["episodes"], pack["ready"], pack["serial"]), ("暗室回声", "", 2, False, False))
        markdown = submission_pack.render_markdown(pack)
        self.assertIn("1. 剧本名称：暗室回声", markdown)
        self.assertIn("2. 是否 IP 改编：否", markdown)
        self.assertIn("7. 预计创作集数：2 集", markdown)
        self.assertIn("4. 男女频：（待生成）", markdown)
        self.assertIn(WORDING["document"]["not_serial"], markdown)
        self.assertIn(WORDING["document"]["missing_note"], markdown)

    def test_episode_numbers_are_written_in_chinese(self):
        self.assertEqual([submission_pack.chinese_number(n) for n in (1, 10, 12, 20, 101, 110, 123)],
                         ["一", "十", "十二", "二十", "一百零一", "一百一十", "一百二十三"])


class WriteTests(unittest.TestCase):
    def test_answers_are_checked_and_sent_back_with_reasons(self):
        model = Scripted(_details(channel="男女通吃", synopsis="太短"), _details(), _outline())

        written = submission_pack.write(model, _task(), SCENES, max_tokens=4000)

        retry = model.calls[1][1]
        self.assertIn("channel 只能是 男频/女频 之一", retry)
        self.assertIn("synopsis 现在 2 字", retry)
        self.assertEqual(written["details"]["channel"], "女频")
        self.assertEqual(written["outline"], [{"first": 1, "last": 2, "text": json.loads(_outline())["outline"]}])
        self.assertEqual(written["fingerprint"], submission_pack.fingerprint(_task(), SCENES))
        # The model read the project: the title, the cast and the episodes.
        first = model.calls[0][1]
        for fact in ("《暗室回声》", "林夏（女主角）", "周教授—林夏：导师", "第1集《第1集标题》"):
            self.assertIn(fact, first)

    def test_the_audience_chosen_at_creation_is_the_one_the_pack_states(self):
        task = _task()
        task["config"]["target_audience"] = {"lean": "male", "age": ""}
        self.assertEqual(submission_pack.compile_pack(task, SCENES)["channel"], "男频", "shown before anything is written")
        model = Scripted(_details(channel="女频"), _outline())

        written = submission_pack.write(model, task, SCENES, max_tokens=4000)

        self.assertEqual(len(model.calls), 2, "a different answer is overridden, not sent back")
        self.assertIn("立项时定的目标用户是男频", model.calls[0][1])
        self.assertEqual(written["details"]["channel"], "男频")

    def test_a_person_not_in_the_cast_and_a_paywall_past_the_end_are_refused(self):
        stranger = json.loads(_details())["characters"][0] | {"name": "林小夏"}
        model = Scripted(_details(characters=[stranger], paywall_episode=9), _details(), _outline())

        submission_pack.write(model, _task(), SCENES, max_tokens=4000)

        retry = model.calls[1][1]
        self.assertIn("「林小夏」不在资料的人物表里", retry)
        self.assertIn("paywall_episode 必须在 1 到 2 之间", retry)

    def test_a_long_serial_gets_a_premiere_hook_and_one_outline_call_per_ten_episodes(self):
        task = _task(episodes=120)
        outlines = [_outline() for _ in range(12)]
        model = Scripted(_details(premiere_hook=""), _details(premiere_hook="主角在婚礼上当众撕开继母的账本，首发停在账本最后一页的名字上。"), *outlines)

        written = submission_pack.write(model, task, SCENES, max_tokens=4000)

        self.assertIn(WORDING["model"]["reasons"]["premiere"], model.calls[1][1])
        self.assertEqual([(block["first"], block["last"]) for block in written["outline"]][:2], [(1, 10), (11, 20)])
        self.assertEqual(len(written["outline"]), 12)
        self.assertIn("第 21–30 集", model.calls[4][1])
        self.assertNotIn("第1集《", model.calls[4][1])


class ApiTests(unittest.TestCase):
    """On a real structured task: write the items once, keep them, lay the pack out as JSON, Markdown and Word."""

    @classmethod
    def setUpClass(cls):
        pipeline.setUpModule()

    @classmethod
    def tearDownClass(cls):
        pipeline.tearDownModule()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("pack-api", pipeline._task("pack-api"))
        self.gateway = pipeline._Gateway()
        self.gateway.last_answer_was_offline = lambda: False
        self.service = pipeline._service(self.gateway, self.repo)
        pipeline._run_stage_two(self.service, "pack-api")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "writer-user", "role": "user"}
        self.client = TestClient(app, cookies={"auth_token": auth_service.generate_token("writer-user")})
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(app.dependency_overrides.pop, get_current_user, None)
        self.addCleanup(self.client.close)
        service_patch = patch.object(drama_api, "service", self.service)
        service_patch.start()
        self.addCleanup(service_patch.stop)
        self.calls = []
        real = self.gateway.call_llm
        task = self.repo.get_task("pack-api")
        names = list(submission_pack.roster(task))
        person = json.loads(_details())["characters"][0] | {"name": names[0]}

        def call_llm(model, system, user, title, *args, **kwargs):
            if system == WORDING["model"]["system"]:
                self.calls.append(user)
                return _outline() if "这一段的大纲" in user else _details(characters=[person], paywall_episode=1)
            return real(model, system, user, title, *args, **kwargs)

        self.gateway.call_llm = call_llm

    def test_items_are_written_once_kept_and_laid_out_as_markdown_and_word(self):
        before = self.client.get("/api/drama/pack-api/submission-pack").json()
        self.assertFalse(before["ready"])
        self.assertTrue(before["body"])

        built = self.client.post("/api/drama/pack-api/submission-pack", json={})
        self.assertEqual(built.status_code, 200, built.text)
        self.assertTrue(built.json()["ready"])
        self.assertEqual(len(self.calls), 2)
        self.assertIn(submission_pack.ASSET_KEY, self.repo.get_task("pack-api")["assets"])

        self.client.post("/api/drama/pack-api/submission-pack", json={})
        self.assertEqual(len(self.calls), 2, "the kept items still match the script: no second call")
        self.client.post("/api/drama/pack-api/submission-pack", json={"refresh": True})
        self.assertEqual(len(self.calls), 4)

        markdown = self.client.get("/api/drama/pack-api/submission-pack?format=md")
        self.assertEqual(markdown.status_code, 200)
        self.assertIn("4. 男女频：女频", markdown.text)
        self.assertIn("第一集", markdown.text)
        word = self.client.get("/api/drama/pack-api/submission-pack?format=docx")
        self.assertEqual(word.status_code, 200)
        self.assertTrue(word.content.startswith(b"PK"))

    def test_a_changed_script_shows_the_kept_items_as_stale(self):
        self.client.post("/api/drama/pack-api/submission-pack", json={})

        def retitle(task):
            task["assets"]["2_screenwriting"]["ledger"][0]["title"] = "改过的标题"
            return True

        self.repo.mutate_task("pack-api", retitle)
        pack = self.client.get("/api/drama/pack-api/submission-pack").json()
        self.assertTrue(pack["stale"])
        self.assertIn(WORDING["document"]["stale_note"], self.client.get("/api/drama/pack-api/submission-pack?format=md").text)

    def test_an_offline_model_is_reported_and_nothing_is_kept(self):
        self.gateway.last_answer_was_offline = lambda: True

        response = self.client.post("/api/drama/pack-api/submission-pack", json={})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], WORDING["model"]["offline"])
        self.assertNotIn(submission_pack.ASSET_KEY, self.repo.get_task("pack-api")["assets"])


if __name__ == "__main__":
    unittest.main()

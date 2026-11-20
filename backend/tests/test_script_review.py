# -*- coding: utf-8 -*-
"""The script review report: read in blocks, checked against the script, kept on the project, laid out for the page."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import auth_service, get_current_user
from app.core import prompt_data, script_review
from app.core.screenwriting.structured_llm import StructuredOutputError
from app.repository.task_repo import TaskRepository
from main import app

from tests import test_screenwriting_pipeline as pipeline
from tests.test_submission_pack import SCENES, Scripted, _task

WORDING = prompt_data.load("script_review")
KEYS = [item["key"] for item in WORDING["dimensions"]]


def _answer(findings=(), verdicts=None, summary="开场立得住，中段的因果有一处接不上。", strengths=("第一场用找录音笔立住了悬念",), dimensions=None):
    verdicts = verdicts or {}
    return json.dumps({
        "summary": summary,
        "dimensions": dimensions if dimensions is not None else [
            {"key": key, "verdict": verdicts.get(key, "pass"), "note": f"{key} 的说明"} for key in KEYS
        ],
        "findings": list(findings),
        "strengths": list(strengths),
    }, ensure_ascii=False)


def _finding(**changes):
    finding = {"dimension": "logic", "severity": "medium", "scene": "1-1", "quote": "有人吗？", "issue": "林夏为什么深夜来实验室没有交代", "fix": "在 1-1 开头让她看一眼手机上的匿名短信"}
    finding.update(changes)
    return finding


def _small_blocks(chars: int):
    real = script_review._limit
    return patch.object(script_review, "_limit", lambda key: chars if key == "block_chars" else real(key))


class ScriptTests(unittest.TestCase):
    def test_the_script_is_read_by_episode_with_its_scene_numbers(self):
        first, second = script_review.episodes_of(_task(), SCENES)
        self.assertEqual((first["episode"], second["episode"]), (1, 2))
        self.assertEqual(first["numbers"], ["1-1"])
        self.assertEqual(second["numbers"], ["2-1"])
        self.assertIn("有人吗？", first["text"])
        self.assertIn("站住。", second["text"])
        # The submission template's caption marks are layout, not script.
        self.assertNotIn("字幕", first["text"] + second["text"])
        self.assertIn("林夏推开实验室的门。", first["text"])

    def test_a_voice_with_no_name_keeps_what_the_script_says_about_it(self):
        voiced = [dict(SCENES[0]), dict(SCENES[1], dialogue=[
            {"kind": "voiceover", "speaker": "", "text": "谁动过炉子？", "delivery": "画外，年长男声，不高；问完屋里更静"},
            {"kind": "voiceover", "speaker": "", "text": "那一夜，灯没有再亮。"},
            {"kind": "voiceover", "speaker": "", "text": "谁动过炉子？", "delivery": "画外、阶顶长老的声音：低沉 / 慢"},
        ]), dict(SCENES[2])]
        text = script_review.episodes_of(_task(), voiced)[0]["text"]
        self.assertIn("【VO】旁白（画外，年长男声，不高）：谁动过炉子？", text)
        self.assertIn("【VO】旁白（画外、阶顶长老的声音）：谁动过炉子？", text)
        self.assertLess(text.index("年长男声"), text.index("阶顶长老"))
        self.assertIn("【VO】旁白：那一夜，灯没有再亮。", text)
        self.assertIn("括号里是剧本对这个声音的说明", script_review.block_prompts(script_review.episodes_of(_task(), voiced), total=2)[1])

    def test_whole_episodes_are_packed_into_blocks_and_one_call_reads_each(self):
        episodes = script_review.episodes_of(_task(), SCENES)
        self.assertEqual(len(script_review.blocks(episodes)), 1)
        self.assertEqual(script_review.calls_needed(_task(), SCENES), 1)
        with _small_blocks(10):
            packed = script_review.blocks(episodes)
            self.assertEqual([[episode["episode"] for episode in block] for block in packed], [[1], [2]])
            self.assertEqual(script_review.calls_needed(_task(), SCENES), 2)

    def test_the_facts_are_counted_from_the_script(self):
        facts = {item["key"]: item["value"] for item in script_review.facts(_task(), SCENES)}
        self.assertEqual((facts["episodes"], facts["scenes"], facts["places"], facts["speakers"], facts["lines"]), ("2", "2", "1", "2", "3"))
        self.assertTrue(facts["dialogue_share"].endswith("%"))
        self.assertEqual([item["label"] for item in script_review.facts(_task(), SCENES)], list(WORDING["facts"]["labels"].values()))

    def test_the_request_names_the_aspects_the_scene_numbers_and_carries_the_script(self):
        block = script_review.episodes_of(_task(), SCENES)
        system, user = script_review.block_prompts(block, total=2)
        self.assertIn("剧本医生", system)
        self.assertIn(str(WORDING["limits"]["max_findings"]), system)
        for item in WORDING["dimensions"]:
            self.assertIn(f"- {item['key']}（{item['label']}）", user)
        for piece in ("整部剧本，共 2 集", "【这一段里的场号】1-1 / 2-1", "pass（通过）", "high（硬伤）", "有人吗？"):
            self.assertIn(piece, user)
        self.assertNotIn("全剧梗概", user)
        self.assertIn("【排版说明】下面的剧本每一场先列这一场的全部动作描写", user)
        self.assertNotIn("{", system)


class WriteTests(unittest.TestCase):
    def test_an_answer_is_checked_and_sent_back_with_reasons(self):
        bad = _answer(findings=[_finding(scene="9-9")], dimensions=[{"key": "logic", "verdict": "fine", "note": ""}])
        good = _answer(
            findings=[_finding(), _finding(dimension="dialogue", severity="high", scene="2-1", quote="站住。", issue="周教授的话太短", fix="在 2-1 让他多说半句")],
            verdicts={"logic": "revise", "dialogue": "problem"},
        )
        model = Scripted(bad, good)
        written = script_review.write(model, _task(), SCENES, max_tokens=4000, model="m")
        self.assertEqual(len(model.calls), 2)
        retry = model.calls[1][1]
        for piece in ("dimensions 要七个方面各一条", "场号「9-9」不在这一段里"):
            self.assertIn(piece, retry)
        self.assertEqual((written["calls"], written["model"], written["quotes_dropped"]), (1, "m", 0))
        self.assertEqual(written["fingerprint"], script_review.fingerprint(_task(), SCENES))
        # The most serious finding comes first.
        self.assertEqual([item["severity"] for item in written["findings"]], ["high", "medium"])
        self.assertEqual({item["key"]: item["verdict"] for item in written["dimensions"]}["dialogue"], "problem")
        self.assertEqual([item["key"] for item in written["dimensions"]], KEYS)

    def test_a_verdict_is_never_milder_than_the_aspects_own_worst_finding(self):
        model = Scripted(_answer(findings=[
            _finding(dimension="reversal", severity="high"), _finding(dimension="emotion", severity="medium"), _finding(dimension="opening", severity="low"),
        ], verdicts={"reversal": "revise"}))
        verdicts = {item["key"]: item["verdict"] for item in script_review.write(model, _task(), SCENES, max_tokens=4000)["dimensions"]}
        self.assertEqual((verdicts["reversal"], verdicts["emotion"], verdicts["opening"], verdicts["logic"]), ("problem", "revise", "pass", "pass"))

    def test_a_quote_that_is_not_in_the_script_is_removed_and_counted(self):
        model = Scripted(_answer(findings=[
            _finding(quote="有 人吗？"), _finding(quote="她哭着跑了出去", scene="", issue="结尾没有落点", fix="在 2-1 末尾补一个动作"),
        ]))
        written = script_review.write(model, _task(), SCENES, max_tokens=4000)
        quotes = {item["issue"]: item["quote"] for item in written["findings"]}
        self.assertEqual(quotes["林夏为什么深夜来实验室没有交代"], "有 人吗？")
        self.assertEqual(quotes["结尾没有落点"], "")
        self.assertEqual(written["quotes_dropped"], 1)

    def test_more_findings_than_asked_for_are_cut_not_sent_back(self):
        limit = WORDING["limits"]["max_findings"]
        model = Scripted(_answer(findings=[_finding(issue=f"问题 {n}") for n in range(limit + 5)]))
        written = script_review.write(model, _task(), SCENES, max_tokens=4000)
        self.assertEqual((len(model.calls), len(written["findings"])), (1, limit))

    def test_a_long_script_is_read_block_by_block_with_the_series_digest_and_the_worst_verdict_wins(self):
        first = _answer(findings=[_finding()], verdicts={"logic": "revise"}, summary="第一集立住了。")
        second = _answer(findings=[_finding(scene="2-1", quote="站住。", severity="high")], verdicts={"logic": "problem", "opening": "revise"}, summary="第二集接不上。")
        model = Scripted(first, second)
        with _small_blocks(10):
            written = script_review.write(model, _task(), SCENES, max_tokens=4000)
            self.assertEqual(written["fingerprint"], script_review.fingerprint(_task(), SCENES))
        self.assertEqual((len(model.calls), written["calls"]), (2, 2))
        self.assertIn("第 1 集（全剧共 2 集", model.calls[0][1])
        self.assertIn("【这一段里的场号】2-1", model.calls[1][1])
        for _system, user in model.calls:
            self.assertIn("全剧梗概", user)
            self.assertIn("暗室回声", user)
        verdicts = {item["key"]: item["verdict"] for item in written["dimensions"]}
        self.assertEqual((verdicts["logic"], verdicts["opening"], verdicts["conflict"]), ("problem", "revise", "pass"))
        self.assertEqual(written["summary"], "第 1–1 集：第一集立住了。\n第 2–2 集：第二集接不上。")
        self.assertEqual([item["scene"] for item in written["findings"]], ["2-1", "1-1"])

    def test_a_scene_from_another_block_is_refused_in_that_block(self):
        model = Scripted(_answer(findings=[_finding(scene="2-1")]), _answer(), _answer())
        with _small_blocks(10):
            script_review.write(model, _task(), SCENES, max_tokens=4000)
        self.assertEqual(len(model.calls), 3)
        self.assertIn("只能用 1-1", model.calls[1][1])

    def test_no_script_too_long_a_script_and_a_model_that_never_answers(self):
        with self.assertRaises(script_review.ScriptReviewError) as empty:
            script_review.write(Scripted(), _task(), [], max_tokens=4000)
        self.assertIn("还没有剧本", str(empty.exception))
        real = script_review._limit
        with patch.object(script_review, "_limit", lambda key: {"block_chars": 10, "max_blocks": 1}.get(key, real(key))):
            with self.assertRaises(script_review.ScriptReviewError) as long:
                script_review.write(Scripted(), _task(), SCENES, max_tokens=4000)
        self.assertIn("要分 2 段", str(long.exception))
        with self.assertRaises(StructuredOutputError):
            script_review.write(Scripted(), _task(), SCENES, max_tokens=4000)


class ViewTests(unittest.TestCase):
    def _kept(self):
        task = _task()
        task["assets"][script_review.ASSET_KEY] = script_review.write(
            Scripted(_answer(findings=[_finding(), _finding(scene="", quote="", severity="low", issue="全剧缺一条感情线", fix="在 1-1 给林夏一个放不下的人")],
                             verdicts={"logic": "revise"})),
            task, SCENES, max_tokens=4000, model="deepseek-flash",
        )
        return task

    def test_before_a_report_the_page_gets_the_facts_and_what_a_run_takes(self):
        shown = script_review.view(_task(), SCENES, model="deepseek-flash")
        self.assertIsNone(shown["report"])
        self.assertEqual((shown["stale"], shown["calls_needed"], shown["model"], shown["title"]), (False, 1, "deepseek-flash", "暗室回声"))
        self.assertTrue(shown["facts"])

    def test_the_kept_report_carries_its_labels_and_goes_stale_when_the_script_changes(self):
        task = self._kept()
        shown = script_review.view(task, SCENES)
        report = shown["report"]
        self.assertFalse(shown["stale"])
        self.assertEqual((report["dimensions"][0]["label"], report["dimensions"][0]["verdict_label"]), ("故事逻辑", "建议修改"))
        first, second = report["findings"]
        self.assertEqual((first["dimension_label"], first["severity_label"], first["where"]), ("故事逻辑", "该改", "第 1-1 场"))
        self.assertEqual(second["where"], "全剧")
        changed = [dict(SCENES[0], description="林夏踹开实验室的门。"), *SCENES[1:]]
        self.assertTrue(script_review.view(task, changed)["stale"])

    def test_the_markdown_report_has_every_part(self):
        task = self._kept()
        text = script_review.render_markdown(script_review.view(task, SCENES))
        for piece in ("# 《暗室回声》剧本审核报告", "模型：deepseek-flash", "## 总体判断", "- **故事逻辑**：建议修改。", "### 1. 【故事逻辑·该改】第 1-1 场",
                      "> 有人吗？", "- 改法：在 1-1 开头让她看一眼手机上的匿名短信", "## 做得好的地方", "## 制作概况", "不会改动剧本"):
            self.assertIn(piece, text)
        self.assertNotIn("剧本在这份报告生成之后改过", text)

    def test_the_module_keeps_its_wording_in_the_data_file(self):
        source = Path(script_review.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search("[一-鿿]", source))


class ApiTests(unittest.TestCase):
    """On a real structured task: nothing is asked of the model until the creator asks for a report."""

    @classmethod
    def setUpClass(cls):
        pipeline.setUpModule()

    @classmethod
    def tearDownClass(cls):
        pipeline.tearDownModule()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("review-api", pipeline._task("review-api"))
        self.gateway = pipeline._Gateway()
        self.offline = False
        self.gateway.last_answer_was_offline = lambda: self.offline
        self.service = pipeline._service(self.gateway, self.repo)
        pipeline._run_stage_two(self.service, "review-api")
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
        task = self.repo.get_task("review-api")
        self.number = script_review.episodes_of(task, list(self.service._breakdown_scenes(task)))[0]["numbers"][0]

        def call_llm(model, system, user, title, *args, **kwargs):
            if "剧本医生" in system:
                self.calls.append(user)
                return "" if self.offline else _answer(findings=[_finding(scene=self.number, quote="")], verdicts={"logic": "revise"})
            return real(model, system, user, title, *args, **kwargs)

        self.gateway.call_llm = call_llm

    def test_a_report_is_written_on_request_kept_and_downloaded(self):
        before = self.client.get("/api/drama/review-api/script-review")
        self.assertEqual(before.status_code, 200, before.text)
        self.assertIsNone(before.json()["report"])
        self.assertEqual(before.json()["calls_needed"], 1)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.client.get("/api/drama/review-api/script-review?format=md").status_code, 404)

        done = self.client.post("/api/drama/review-api/script-review")
        self.assertEqual(done.status_code, 200, done.text)
        report = done.json()["report"]
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(report["findings"][0]["where"], f"第 {self.number} 场")
        self.assertEqual(report["dimensions"][0]["verdict_label"], "建议修改")
        self.assertFalse(done.json()["stale"])
        self.assertIn(script_review.ASSET_KEY, self.repo.get_task("review-api")["assets"])

        again = self.client.get("/api/drama/review-api/script-review")
        self.assertEqual(again.json()["report"]["built_at"], report["built_at"])
        self.assertEqual(len(self.calls), 1)
        markdown = self.client.get("/api/drama/review-api/script-review?format=md")
        self.assertEqual(markdown.status_code, 200)
        self.assertIn("剧本审核报告", markdown.text)
        self.assertIn("attachment", markdown.headers["content-disposition"])

    def test_a_focused_check_is_asked_for_by_name_and_an_unknown_one_is_refused(self):
        shown = self.client.get("/api/drama/review-api/script-review?focus=opening")
        self.assertEqual(shown.status_code, 200, shown.text)
        self.assertEqual((shown.json()["focus"], shown.json()["label"]), ("opening", "前三集主线体检"))
        self.assertEqual([item["key"] for item in shown.json()["focuses"]], ["", "opening", "voice"])
        self.assertEqual(self.client.get("/api/drama/review-api/script-review?focus=nope").status_code, 409)
        self.assertEqual(self.client.post("/api/drama/review-api/script-review?focus=nope").status_code, 409)
        self.assertEqual(self.calls, [])

    def test_an_offline_model_is_reported_and_nothing_is_kept(self):
        self.offline = True
        done = self.client.post("/api/drama/review-api/script-review")
        self.assertEqual(done.status_code, 502)
        self.assertIn("没有给出回答", done.json()["detail"])
        self.assertNotIn(script_review.ASSET_KEY, self.repo.get_task("review-api")["assets"])

    def test_a_project_without_a_script_is_told_so(self):
        with patch.object(self.service, "_breakdown_scenes", return_value=[]):
            read = self.client.get("/api/drama/review-api/script-review")
            asked = self.client.post("/api/drama/review-api/script-review")
        self.assertEqual((read.status_code, asked.status_code), (409, 409))
        self.assertIn("还没有剧本", read.json()["detail"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()

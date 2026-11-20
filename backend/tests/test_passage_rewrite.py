# -*- coding: utf-8 -*-
"""Rewriting a passage of an episode's plan, the check of what it breaks, and the sheet update."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import auth_service, get_current_user
from app.core.screenwriting import passage_rewrite
from app.core.screenwriting.passage_rewrite import PassageError
from app.repository.task_repo import TaskRepository
from app.service import screenwriting_service as screenwriting
from main import app

from tests import test_screenwriting_pipeline as pipeline

SCENES = [
    {"scene_id": "E2S01", "duration_seconds": 6, "setting": "当铺 夜 内景", "characters_in_scene": ["林夏"], "scene_description": "林夏推门进当铺。",
     "utterances": [{"kind": "dialogue", "speaker": "林夏", "text": "掌柜在吗？"}]},
    {"scene_id": "E2S02", "duration_seconds": 8, "setting": "当铺 夜 内景", "characters_in_scene": ["林夏", "掌柜"], "key_line": "这玉佩，是我娘的。",
     "scene_description": "掌柜从柜里取出玉佩。", "utterances": [{"kind": "dialogue", "speaker": "林夏", "text": "这玉佩，是我娘的。"}]},
    {"scene_id": "E2S03", "duration_seconds": 5, "setting": "当铺 夜 外景", "characters_in_scene": ["林夏"], "scene_description": "林夏攥着玉佩走进雨里。", "utterances": []},
    {"scene_id": "E2S04", "duration_seconds": 5, "setting": "长街 夜 外景", "characters_in_scene": ["林夏"], "scene_description": "雨巷尽头有人跟着。", "utterances": []},
]
LEDGER = [
    {"episode": 1, "title": "失物", "state_changes": ["【物件】玉佩被当进了城南当铺"]},
    {"episode": 2, "title": "赎回", "state_changes": ["【物件】林夏赎回了玉佩，贴身带着", "【伏笔】玉佩背面刻着一个「周」字"], "story_beats": ["赎回玉佩"]},
    {"episode": 3, "title": "认亲", "state_changes": ["【兑现】周教授认出玉佩背面的「周」字"], "story_beats": ["周教授看见玉佩", "认亲"]},
    {"episode": 4, "title": "追兵", "state_changes": [], "story_beats": ["雨夜追逐"]},
]


def _answer(scenes):
    return json.dumps({"scenes": scenes}, ensure_ascii=False)


class Scripted:
    """A text model that answers from a list, recording each (system, user)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, system, user, max_tokens):
        self.calls.append((system, user))
        return self.answers.pop(0) if self.answers else ""


class SelectionTests(unittest.TestCase):
    def test_consecutive_shots_come_with_the_shots_around_them(self):
        chosen, before, after = passage_rewrite.select(SCENES, ["E2S03", "E2S02"], episode=2)
        self.assertEqual([scene["scene_id"] for scene in chosen], ["E2S02", "E2S03"])
        self.assertEqual((before["scene_id"], after["scene_id"]), ("E2S01", "E2S04"))
        first, none_before, _ = passage_rewrite.select(SCENES, ["E2S01"], episode=2)
        self.assertIsNone(none_before)

    def test_a_gap_an_unknown_shot_and_too_many_are_refused(self):
        with self.assertRaisesRegex(PassageError, "连在一起"):
            passage_rewrite.select(SCENES, ["E2S01", "E2S03"], episode=2)
        with self.assertRaisesRegex(PassageError, "E9S01"):
            passage_rewrite.select(SCENES, ["E9S01"], episode=2)
        many = [{"scene_id": f"E1S{index:02d}"} for index in range(1, 12)]
        with self.assertRaisesRegex(PassageError, "最多"):
            passage_rewrite.select(many, [scene["scene_id"] for scene in many], episode=1)


class RewriteTests(unittest.TestCase):
    def _rewrite(self, model, **extra):
        chosen, before, after = passage_rewrite.select(SCENES, ["E2S02", "E2S03"], episode=2)
        return passage_rewrite.rewrite(
            model, episode=2, chosen=chosen, before=before, after=after, sheet=["第 1 集：", "- 【物件】玉佩被当进了城南当铺"],
            cast=["林夏", "掌柜", "周教授"], instruction="掌柜不肯给，林夏得抢", max_tokens=4000, **extra,
        )

    def test_the_prompt_carries_the_request_the_sheet_the_cast_and_the_shots_around(self):
        model = Scripted(_answer([
            {"scene_id": "E2S02", "setting": "当铺 夜 内景", "characters_in_scene": ["林夏", "掌柜"], "scene_description": "掌柜把玉佩压在掌下。",
             "utterances": [{"kind": "dialogue", "speaker": "林夏", "text": "这玉佩，是我娘的。"}]},
            {"scene_id": "E2S03", "setting": "当铺 夜 外景", "characters_in_scene": ["林夏"], "scene_description": "林夏夺过玉佩冲进雨里。", "utterances": []},
        ]))
        rows = self._rewrite(model, keep=["玉佩背面的「周」字要拍到"])
        user = model.calls[0][1]
        for expected in ("掌柜不肯给，林夏得抢", "玉佩被当进了城南当铺", "林夏、掌柜、周教授", "林夏推门进当铺", "雨巷尽头有人跟着", "玉佩背面的「周」字要拍到", "题眼台词（一字不改）：这玉佩，是我娘的。"):
            self.assertIn(expected, user)
        self.assertEqual([row["scene_id"] for row in rows], ["E2S02", "E2S03"])
        self.assertEqual(rows[1]["before"]["scene_description"], "林夏攥着玉佩走进雨里。")
        self.assertEqual(rows[1]["after"]["scene_description"], "林夏夺过玉佩冲进雨里。")
        self.assertEqual(set(rows[0]["after"]), set(passage_rewrite.EDITED_FIELDS))

    def test_a_dropped_key_line_a_stranger_or_a_wrong_shot_is_sent_back_once(self):
        bad = _answer([
            {"scene_id": "E2S02", "characters_in_scene": ["林夏", "路人甲"], "scene_description": "掌柜摇头。", "utterances": [{"kind": "dialogue", "speaker": "林夏", "text": "给我。"}]},
            {"scene_id": "E2S03", "characters_in_scene": ["林夏"], "scene_description": "林夏冲进雨里。", "utterances": []},
        ])
        good = _answer([
            {"scene_id": "E2S02", "characters_in_scene": ["林夏", "掌柜"], "scene_description": "掌柜摇头。", "utterances": [{"kind": "dialogue", "speaker": "林夏", "text": "这玉佩，是我娘的。"}]},
            {"scene_id": "E2S03", "characters_in_scene": ["林夏"], "scene_description": "林夏冲进雨里。", "utterances": []},
        ])
        model = Scripted(bad, good)
        rows = self._rewrite(model)
        self.assertEqual(len(model.calls), 2)
        self.assertIn("路人甲", model.calls[1][1])
        self.assertIn("这玉佩，是我娘的。", model.calls[1][1])
        self.assertEqual(rows[0]["after"]["utterances"][0]["text"], "这玉佩，是我娘的。")

        with self.assertRaisesRegex(RuntimeError, "不合要求"):
            self._rewrite(Scripted(_answer([{"scene_id": "E2S02", "scene_description": "只回了一格"}]), _answer([])))

    def test_no_instruction_is_refused_before_any_call(self):
        model = Scripted()
        with self.assertRaises(PassageError):
            chosen, before, after = passage_rewrite.select(SCENES, ["E2S01"], episode=2)
            passage_rewrite.rewrite(model, episode=2, chosen=chosen, before=before, after=after, sheet=[], cast=[], instruction="  ", max_tokens=100)
        self.assertEqual(model.calls, [])


class ImpactTests(unittest.TestCase):
    def test_later_episodes_are_read_nearest_first_with_their_sheet_and_beats(self):
        lines = passage_rewrite.later_lines(LEDGER, 2)
        self.assertEqual(lines[0], "第 3 集「认亲」")
        self.assertIn("  场记：【兑现】周教授认出玉佩背面的「周」字", lines)
        self.assertIn("  剧情点：雨夜追逐", lines)
        self.assertFalse(any("赎回" in line for line in lines), "this and earlier episodes are not 'later'")
        self.assertEqual(passage_rewrite.own_changes(LEDGER, 2)[1], "【伏笔】玉佩背面刻着一个「周」字")

    def test_findings_and_the_new_sheet_come_back_and_no_answer_keeps_the_sheet(self):
        answer = json.dumps({"findings": [
            {"episode": 3, "fact": "【兑现】周教授认出玉佩背面的「周」字", "quote": "林夏夺过玉佩冲进雨里", "fix": "在 E2S03 让刻字露一下"},
            {"episode": 0, "fact": "没有 fix 的不要", "quote": "", "fix": ""},
        ], "state_changes": ["【物件】林夏抢回了玉佩"]}, ensure_ascii=False)
        model = Scripted(answer)
        result = passage_rewrite.impact(model, episode=2, before=SCENES[1:3], after=SCENES[1:3], own=LEDGER[1]["state_changes"], later=passage_rewrite.later_lines(LEDGER, 2), max_tokens=4000)
        self.assertTrue(result["checked"])
        self.assertEqual([(item["episode"], item["fix"]) for item in result["findings"]], [(3, "在 E2S03 让刻字露一下")])
        self.assertEqual(result["state_changes"], ["【物件】林夏抢回了玉佩"])
        system, user = model.calls[0]
        self.assertIn("第 2 集", system)
        self.assertIn("【伏笔】玉佩背面刻着一个「周」字", user)
        self.assertIn("第 3 集「认亲」", user)

        silent = passage_rewrite.impact(Scripted("", ""), episode=2, before=SCENES[1:3], after=SCENES[1:3], own=["【物件】x"], later=[], max_tokens=100)
        self.assertEqual(silent, {"findings": [], "state_changes": ["【物件】x"], "checked": False})


class ApiTests(unittest.TestCase):
    """On a real structured task: propose (nothing written), adopt through the plan edit, update the sheet."""

    @classmethod
    def setUpClass(cls):
        pipeline.setUpModule()

    @classmethod
    def tearDownClass(cls):
        pipeline.tearDownModule()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("pr-1", pipeline._task("pr-1"))
        self.gateway = pipeline._Gateway()
        self.gateway.last_answer_was_offline = lambda: False
        self.service = pipeline._service(self.gateway, self.repo)
        pipeline._run_stage_two(self.service, "pr-1")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "writer-user", "role": "user"}
        self.client = TestClient(app, cookies={"auth_token": auth_service.generate_token("writer-user")})
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(app.dependency_overrides.pop, get_current_user, None)
        self.addCleanup(self.client.close)
        service_patch = patch.object(drama_api, "service", self.service)
        service_patch.start()
        self.addCleanup(service_patch.stop)

    def _episode(self):
        return self.client.get("/api/drama/pr-1/screenwriting/episodes/1").json()

    def _script(self, rewritten_description, findings=(), state_changes=None):
        real = self.gateway.call_llm
        episode = self._episode()
        target = episode["plan"]["scenes"][1]
        rewrite = _answer([{
            "scene_id": target["scene_id"], "setting": target.get("setting") or "", "characters_in_scene": target.get("characters_in_scene") or [],
            "scene_description": rewritten_description, "utterances": target.get("utterances") or [],
        }])
        impact = json.dumps({"findings": list(findings), "state_changes": state_changes or []}, ensure_ascii=False)
        calls = []

        def call_llm(model, system, user, title, *args, **kwargs):
            if "只改人选中的这几个分镜" in system:
                calls.append("rewrite")
                return rewrite
            if "剧组场记" in system and "改了" in system:
                calls.append("impact")
                return impact
            return real(model, system, user, title, *args, **kwargs)

        self.gateway.call_llm = call_llm
        return episode, target, calls

    def test_a_proposal_writes_nothing_and_adopting_it_goes_through_the_plan_edit(self):
        episode, target, calls = self._script("周教授把门反锁，灯一盏盏灭了。", findings=[{"episode": 2, "fact": "节点2A", "quote": "灯一盏盏灭了", "fix": "第 2 集开场补一句灯为什么灭"}], state_changes=["【时地】当夜，实验室"])
        before = json.dumps(self.repo.get_task("pr-1")["assets"][screenwriting.STATE_KEY], ensure_ascii=False, sort_keys=True)
        response = self.client.post("/api/drama/pr-1/screenwriting/episodes/1/rewrite-passage", json={"scene_ids": [target["scene_id"]], "instruction": "更压抑"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(calls, ["rewrite", "impact"])
        self.assertEqual(body["plan_revision"], episode["planRevision"])
        self.assertEqual(body["scenes"][0]["after"]["scene_description"], "周教授把门反锁，灯一盏盏灭了。")
        self.assertEqual(body["impact"]["findings"][0]["episode"], 2)
        self.assertEqual(body["impact"]["state_changes"]["after"], ["【时地】当夜，实验室"])
        self.assertTrue(body["impact"]["checked"])
        after = json.dumps(self.repo.get_task("pr-1")["assets"][screenwriting.STATE_KEY], ensure_ascii=False, sort_keys=True)
        self.assertEqual(before, after, "a proposal is only shown")

        adopted = self.client.patch("/api/drama/pr-1/screenwriting/episodes/1/plan", json={
            "baseRevision": body["plan_revision"],
            "operations": [{"op": "update", "id": row["scene_id"], "fields": row["after"]} for row in body["scenes"]],
            "confirmInvalidate": True,
        })
        self.assertEqual(adopted.status_code, 200, adopted.text)
        self.assertEqual(adopted.json()["rewrittenSceneIds"], [target["scene_id"]])
        self.assertIn("灯一盏盏灭了", self.repo.get_task("pr-1")["assets"]["2"])

    def test_the_sheet_of_an_episode_can_be_replaced_and_shows_in_the_ledger(self):
        response = self.client.put("/api/drama/pr-1/screenwriting/ledger/1/state-changes", json={"state_changes": ["【物件】钥匙在林夏手里", "  ", "【知情】周教授知道了"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state_changes"], ["【物件】钥匙在林夏手里", "【知情】周教授知道了"])
        ledger = self.client.get("/api/drama/pr-1/screenwriting").json()["ledger"]
        self.assertEqual(ledger[0]["stateChanges"], ["【物件】钥匙在林夏手里", "【知情】周教授知道了"])
        self.assertEqual(self.client.put("/api/drama/pr-1/screenwriting/ledger/9/state-changes", json={"state_changes": []}).status_code, 404)

    def test_bad_selections_and_an_offline_model_are_told_apart(self):
        episode = self._episode()
        ids = [scene["scene_id"] for scene in episode["plan"]["scenes"]]
        gap = self.client.post("/api/drama/pr-1/screenwriting/episodes/1/rewrite-passage", json={"scene_ids": ["E1S99"], "instruction": "改"})
        self.assertEqual(gap.status_code, 422)
        missing = self.client.post("/api/drama/pr-1/screenwriting/episodes/9/rewrite-passage", json={"scene_ids": ids[:1], "instruction": "改"})
        self.assertEqual(missing.status_code, 404)

        self.gateway.call_llm = lambda *args, **kwargs: "离线模板"
        self.gateway.last_answer_was_offline = lambda: True
        offline = self.client.post("/api/drama/pr-1/screenwriting/episodes/1/rewrite-passage", json={"scene_ids": ids[:1], "instruction": "改"})
        self.assertEqual(offline.status_code, 502)
        self.assertIn("离线模板", offline.json()["detail"])


if __name__ == "__main__":
    unittest.main()

"""The writer board edits the reference product shows: overview by hand or by the model, story
event nodes, the cast and its positions, saved versions, and a shot table with verbatim lines."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.auth_api import auth_service, get_current_user
from app.api.drama_api import service
from app.core.screenwriting.prompts import build_asset_inventory_prompt
from app.core.screenwriting.renderer import render_breakdown, render_relationships, scene_label
from app.core.writer_dashboard import compile_writer_dashboard
from app.repository.task_repo import TaskRepository
from app.service import screenwriting_service as screenwriting
from main import app
from tests.test_screenwriting_engine import FakeModel, _engine, _scene


def _state(episodes: int = 2):
    engine = _engine(FakeModel())
    return engine.write(title="暗室回声", director_plan="三幕大纲", episode_count=episodes)


class ShotTableTests(unittest.TestCase):
    def test_each_shot_carries_a_label_its_picture_text_and_its_lines(self):
        state = _state(1)
        breakdown = render_breakdown(state)
        shot = breakdown["scenes"][0]
        self.assertEqual(shot["label"], "地下实验室 夜")
        self.assertEqual(shot["description"], "第1集第1个画面：林夏握紧录音笔，指节发白。")
        self.assertEqual(shot["dialogue"], [{"kind": "dialogue", "speaker": "林夏", "text": "你到底瞒了什么？", "verbatim": False, "delivery": "压抑-克制 / 慢"}])
        self.assertEqual(scene_label({"setting": "九丝城 城墙 黄昏 外景"}), "九丝城 城墙")
        self.assertEqual(scene_label({"setting": ""}), "")

    def test_lines_cut_from_a_source_are_verbatim_and_the_dashboard_shows_the_storyboard_frame(self):
        scene = _scene(1, 1, source_text="原文：你到底瞒了什么？")
        state = {"engine": "screenwriting-master", "episodes": {"1": {"episode": 1, "script": {"episode": 1, "title": "t", "scenes": [scene]}}}, "ledger": [], "overview": {}, "inventory": {}}
        breakdown = render_breakdown(state)
        self.assertTrue(breakdown["scenes"][0]["dialogue"][0]["verbatim"])
        task = {"task_id": "t1", "config": {"creation_mode": "narration"}, "assets": {
            "2": "第1集 开端\n\n场景一\n你到底瞒了什么？", "2_breakdown": breakdown,
            "4": [{"scene_id": "E1S01", "image_url": "https://img.example/e1s01.jpg"}, {"scene_id": "E1S01", "image_url": "https://img.example/dup.jpg"}],
        }}
        dashboard = compile_writer_dashboard(task)
        self.assertEqual(dashboard.scenes[0].image_url, "https://img.example/e1s01.jpg")
        self.assertEqual(dashboard.scenes[0].label, "地下实验室 夜")
        self.assertTrue(dashboard.scenes[0].dialogue[0].verbatim)
        self.assertEqual(dashboard.creation_mode, "narration")


class NamedRelationshipsTests(unittest.TestCase):
    """The writing stage names how the characters relate, so the star map is not a co-occurrence count."""

    def test_the_inventory_prompt_asks_for_named_relations(self):
        prompt = build_asset_inventory_prompt("林夏与周教授的故事", source_kind="novel", overview={})
        for word in ("relationships", "君臣", "父子", "母子", "主仆", "背叛", "兄弟", "兄妹", "先祖与后裔", "祭司辅佐首领",
                     "托孤之臣", "辅政大臣", "宿敌", "亦师亦友", "惺惺相惜", "禁止写「同场互动」"):
            self.assertIn(word, prompt)

    def test_written_projects_carry_the_relations_the_inventory_named(self):
        state = _state(1)
        self.assertEqual(render_breakdown(state)["relationships"], [{"from": "周教授", "to": "林夏", "relation": "亦师亦友", "bidirectional": True}])
        dashboard = compile_writer_dashboard({"task_id": "r1", "config": {}, "assets": {"2": "第1集 开端\n林夏：你到底瞒了什么？", "2_breakdown": render_breakdown(state)}})
        self.assertFalse(dashboard.relationships_inferred)
        self.assertEqual([(e.from_, e.to, e.relation) for e in dashboard.relationships], [("周教授", "林夏", "亦师亦友")])

    def test_empty_words_unknown_names_and_duplicates_are_dropped(self):
        state = {"inventory": {"characters": {"林夏": {}, "周教授": {}}, "relationships": [
            {"from_": "林夏", "to": "周教授", "relation": "敌对", "bidirectional": False},
            {"from": "林夏", "to": "周教授", "relation": "敌对"},
            {"from": "林夏", "to": "周教授", "relation": "同场互动"},
            {"from": "林夏", "to": "路人", "relation": "邻居"},
            {"from": "林夏", "to": "林夏", "relation": "自恋"},
        ]}}
        self.assertEqual(render_relationships(state), [{"from": "林夏", "to": "周教授", "relation": "敌对", "bidirectional": False}])

    def test_a_relation_set_by_hand_outlives_a_new_inventory_but_an_old_projection_does_not(self):
        assets: dict = {}
        screenwriting.apply_state(assets, _state(1))
        self.assertEqual(assets["2_breakdown"]["relationships"][0]["relation"], "亦师亦友")
        newer = _state(1)
        newer["inventory"]["relationships"] = [{"from": "林夏", "to": "周教授", "relation": "宿敌", "bidirectional": True}]
        screenwriting.apply_state(assets, newer)
        self.assertEqual(assets["2_breakdown"]["relationships"][0]["relation"], "宿敌", "a newer inventory replaces an older projection")
        assets["2_breakdown"]["relationships"] = [{"from": "林夏", "to": "周教授", "relation": "夫妻", "bidirectional": True}]
        assets["2_breakdown"]["relationships_authored"] = True
        screenwriting.apply_state(assets, newer)
        self.assertEqual(assets["2_breakdown"]["relationships"][0]["relation"], "夫妻", "a hand-set relation wins")

    def test_renaming_a_character_renames_its_relation_ends(self):
        from app.core import asset_identity

        state = _state(1)
        assets: dict = {}
        screenwriting.apply_state(assets, state)
        task = {"task_id": "r2", "config": {}, "assets": assets}
        asset_identity.rename_asset(task, "character", "周教授", "周慎")
        relation = assets[screenwriting.STATE_KEY]["inventory"]["relationships"][0]
        self.assertEqual(relation.get("from_") or relation.get("from"), "周慎")
        self.assertEqual(assets["2_breakdown"]["relationships"][0]["from"], "周慎")


class RelationshipAnalyserTests(unittest.TestCase):
    def test_the_analyser_drops_same_scene_counts_and_keeps_named_relations(self):
        import tempfile as _tempfile
        from app.service.drama_service import DramaService

        with _tempfile.TemporaryDirectory() as temp:
            svc = DramaService()
            svc.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            svc.repo.save_task("rel-1", {"task_id": "rel-1", "config": {"title_suggestion": "九霄殿"}, "assets": {"2": "第1集\n陆昭：放开我！"}})
            answer = json.dumps({"relationships": [
                {"from": "陆昭", "to": "殷无咎", "relation": "宿敌", "bidirectional": True},
                {"from": "陆昭", "to": "苏挽", "relation": "同场互动 · 6 场", "bidirectional": True},
                {"from": "白小七", "to": "陆昭", "relation": "托孤之臣", "bidirectional": False},
            ]}, ensure_ascii=False)
            with patch.object(svc.gateway, "call_llm", return_value=answer):
                dashboard = svc.analyze_relationships("rel-1")
            self.assertEqual([(e.from_, e.relation) for e in dashboard.relationships], [("陆昭", "宿敌"), ("白小七", "托孤之臣")])
            self.assertFalse(dashboard.relationships_inferred)
            with patch.object(svc.gateway, "call_llm", return_value=json.dumps({"relationships": [{"from": "陆昭", "to": "苏挽", "relation": "同场互动 · 6 场"}]}, ensure_ascii=False)):
                with self.assertRaises(ValueError):
                    svc.analyze_relationships("rel-1")


class AuthoredEditsSurviveProjectionTests(unittest.TestCase):
    def test_relations_positions_hidden_names_and_an_authored_timeline_are_carried_over(self):
        state = _state(2)
        assets: dict = {}
        screenwriting.apply_state(assets, state)
        assets["2_breakdown"]["relationships"] = [{"from": "林夏", "to": "周教授", "relation": "师生", "bidirectional": False}]
        assets["2_breakdown"]["relationships_authored"] = True
        assets["2_breakdown"]["role_positions"] = {"周教授": "反派", "新人": "男配角"}
        assets["2_breakdown"]["hidden_roles"] = ["路人甲"]
        assets["2_breakdown"]["timeline"] = [{"phase": "故事开始", "title": "手工节点", "desc": "", "points": []}]
        assets["2_breakdown"]["timeline_authored"] = True

        screenwriting.apply_state(assets, _state(3))
        breakdown = assets["2_breakdown"]
        self.assertEqual(breakdown["relationships"][0]["relation"], "师生")
        self.assertEqual(breakdown["hidden_roles"], ["路人甲"])
        positions = {role["name"]: role["position"] for role in breakdown["roles"]}
        self.assertEqual((positions["周教授"], positions["新人"]), ("反派", "男配角"))
        self.assertEqual([event["title"] for event in breakdown["timeline"]], ["手工节点"])
        self.assertTrue(breakdown["timeline_authored"])
        fresh: dict = {}
        screenwriting.apply_state(fresh, _state(1))
        self.assertFalse(fresh["2_breakdown"].get("timeline_authored"))
        self.assertTrue(fresh["2_breakdown"]["timeline"], "an untouched timeline still comes from the ledger")


class WriterBoardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self._previous_repo = service.repo
        service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "admin"}
        self.addCleanup(app.dependency_overrides.pop, get_current_user, None)
        self.client = TestClient(app, cookies={"auth_token": auth_service.generate_token("u1")})
        state = _state(2)
        assets: dict = {"1": "三幕大纲：林夏追查实验室真相。"}
        screenwriting.apply_state(assets, state)
        self.task = {
            "task_id": "board-1", "owner_user_id": "u1", "status": "idle", "current_stage": 2, "stage_name": "编剧剧本创作",
            "config": {"title_suggestion": "暗室回声", "episode_count": 2, "creation_mode": "drama"},
            "assets": assets, "episodes": [], "logs": {},
        }
        self.repo.save_task("board-1", self.task)

    def tearDown(self):
        service.repo = self._previous_repo
        self.temp.cleanup()

    def _dashboard(self):
        response = self.client.get("/api/drama/board-1/writer-dashboard")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_the_overview_is_edited_by_hand_and_told_again_by_the_model(self):
        edited = self.client.patch("/api/drama/board-1/overview", json={"synopsis": "手写梗概。", "genre": "历史传奇", "world_setting": "四川群山"})
        self.assertEqual(edited.status_code, 200, edited.text)
        overview = edited.json()["overview"]
        self.assertEqual((overview["synopsis"], overview["genre"], overview["worldSetting"]), ("手写梗概。", "历史传奇", "四川群山"))
        stored = self.repo.get_task("board-1")["assets"][screenwriting.STATE_KEY]["overview"]
        self.assertEqual(stored["genre"], "历史传奇", "the structured state's overview follows the edit")

        class _Engine:
            def refresh_overview(self, *, source, kind, title_hint):
                assert kind == "outline" and "三幕大纲" in source, (kind, source[:40])
                return {"title": "暗室回声", "synopsis": "模型重写的梗概。", "genre": "悬疑", "theme": "真相", "world_setting": "近未来"}

        with patch.object(service, "_structured_writer_engine", return_value=_Engine()):
            told = self.client.post("/api/drama/board-1/overview/regenerate")
        self.assertEqual(told.status_code, 200, told.text)
        self.assertEqual(told.json()["overview"]["synopsis"], "模型重写的梗概。")
        self.assertEqual(self.repo.get_task("board-1")["assets"]["2_breakdown"]["overview"]["theme"], "真相")

    def test_story_event_nodes_are_arranged_by_hand_and_then_stop_following_the_ledger(self):
        before = self._dashboard()
        self.assertFalse(before["timelineAuthored"])
        self.assertTrue(before["timeline"], "the ledger renders events until someone edits them")
        events = [
            {"phase": "故事开始", "title": "僰人随周武王伐纣受封", "desc": "商末牧野之战", "points": ["牧野战场", "首领受封僰侯"]},
            {"phase": "进展纠葛", "title": "悬棺葬俗", "desc": "", "points": []},
        ]
        saved = self.client.put("/api/drama/board-1/timeline", json={"events": events})
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertTrue(body["timelineAuthored"])
        self.assertEqual([(e["phase"], e["title"], e["points"]) for e in body["timeline"]], [("故事开始", "僰人随周武王伐纣受封", ["牧野战场", "首领受封僰侯"]), ("进展纠葛", "悬棺葬俗", [])])
        self.assertEqual(body["stats"]["mainEventCount"], 2)
        rejected = self.client.put("/api/drama/board-1/timeline", json={"events": [{"phase": "x", "title": ""}]})
        self.assertEqual(rejected.status_code, 422)

    def test_the_cast_is_set_by_hand_with_positions_new_names_and_hidden_names(self):
        before = {role["name"]: role["position"] for role in self._dashboard()["roles"]}
        self.assertIn("林夏", before)
        saved = self.client.put("/api/drama/board-1/roles", json={
            "roles": [{"name": "林夏", "position": "女主角"}, {"name": "周教授", "position": "反派"}, {"name": "阿岚", "position": "男配角"}],
            "hidden": ["周教授"],
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        roles = {role["name"]: role["position"] for role in saved.json()["roles"]}
        self.assertEqual(roles["林夏"], "女主角")
        self.assertEqual(roles["阿岚"], "男配角", "a name added by hand joins the cast")
        self.assertEqual(roles["周教授"], "反派", "a name both listed and hidden stays listed")
        hidden = self.client.put("/api/drama/board-1/roles", json={"roles": [{"name": "林夏", "position": "女主角"}], "hidden": ["周教授", "阿岚"]})
        names = [role["name"] for role in hidden.json()["roles"]]
        self.assertNotIn("周教授", names, "a hidden name stays out although the scenes still mention it")
        self.assertNotIn("阿岚", names)
        characters = self.repo.get_task("board-1")["assets"][screenwriting.STATE_KEY]["inventory"]["characters"]
        self.assertEqual(characters["林夏"]["position"], "女主角")
        self.assertNotIn("周教授", characters)

    def test_versions_are_saved_listed_and_restored_with_their_edits(self):
        if True:
            first = self.client.post("/api/drama/board-1/script/versions", json={"label": "初稿"})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual([v["label"] for v in first.json()["versions"]], ["初稿"])
            first_hash = first.json()["sourceHash"]

            self.client.put("/api/drama/board-1/relationships", json={"relationships": [{"from": "林夏", "to": "周教授", "relation": "师生"}]})
            self.client.patch("/api/drama/board-1/overview", json={"synopsis": "第二稿梗概。"})
            second = self.client.post("/api/drama/board-1/script/versions", json={})
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual([v["label"] for v in second.json()["versions"]], ["版本 2", "初稿"], "newest first, unnamed ones numbered")
            listed = self.client.get("/api/drama/board-1/script/versions").json()["items"]
            self.assertEqual(len(listed), 2)
            self.assertNotIn("payload", json.dumps(listed))

            version_id = listed[1]["version_id"]
            current = self._dashboard()
            stale = self.client.post(f"/api/drama/board-1/script/versions/{version_id}/restore", json={"expected_source_hash": "0" * 64})
            self.assertEqual(stale.status_code, 409)
            restored = self.client.post(f"/api/drama/board-1/script/versions/{version_id}/restore", json={"expected_source_hash": current["sourceHash"]})
            self.assertEqual(restored.status_code, 200, restored.text)
            body = restored.json()
            self.assertEqual(body["sourceHash"], first_hash, "the first version is back, byte for byte")
            self.assertNotEqual(body["overview"]["synopsis"], "第二稿梗概。")
            self.assertEqual([e["relation"] for e in body["relationships"]], ["亦师亦友"], "the first version's relations came from the writing stage, not the later hand edit")
            missing = self.client.post("/api/drama/board-1/script/versions/nope/restore", json={"expected_source_hash": body["sourceHash"]})
            self.assertEqual(missing.status_code, 404)

    def test_saving_a_version_needs_a_screenplay(self):
        self.repo.save_task("empty-1", {"task_id": "empty-1", "owner_user_id": "u1", "config": {}, "assets": {}, "episodes": [], "logs": {}})
        if True:
            self.assertEqual(self.client.post("/api/drama/empty-1/script/versions", json={}).status_code, 409)


if __name__ == "__main__":
    unittest.main()

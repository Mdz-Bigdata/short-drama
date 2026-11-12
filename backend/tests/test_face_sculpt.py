# -*- coding: utf-8 -*-
"""捏脸 / 捏表情：控件表自洽，捏出的脸写进统一资产且不破坏原描述，表情按人、按情绪进镜头。"""

import copy
import unittest

from app.core import face_sculpt as fs, style_packs
from app.core.emotion_table import RULES
from app.core.face_card import parse_face_card, render_face_card
from app.core.storyboard_quality import build_actor_sheet_prompt
from app.core.storyboard_scene_context import cast_aliases
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt

REAL = (
    "女主角/佩剑者（右手按剑）；女性，视觉年龄22–26；脸宽/脸长0.78鹅蛋脸，下颌圆润，颈长10cm；"
    "平眉、杏眼、眼尾上挑2°；鼻梁秀挺、鼻头小；唇中等厚、唇色淡朱；肤色暖白，保留细腻纹理；"
    "右手虎口第一掌骨中点一点朱砂痣，直径2mm，痣面平；无疤、无纹身。；发际线圆润无美人尖；"
    "黑发中分垂练至锁骨下3cm，后挽低髻"
)


def _task():
    return {
        "assets": {
            "3_characters": [
                {"name": "林婉", "role": "主角", "desc": REAL, "sheet": "/media/sheets/linwan_v1.png"},
                {"name": "沈砚", "role": "反派", "desc": "权臣；长脸、颧骨高、薄唇"},
            ],
            "3_dna": {"characters": [{
                "name": "林婉",
                "states": [
                    {"state_id": "s1", "title": "宫装", "bone": "鹅蛋脸、下颌圆润", "features": "杏眼、平眉、朱砂痣",
                     "skin": "暖白", "hair": "黑发低髻", "body": "身形纤长", "clothing": "月白宫装"},
                    {"state_id": "s2", "title": "便装", "bone": "鹅蛋脸", "features": "杏眼", "clothing": "青布衣"},
                ],
            }]},
        },
    }


class CatalogTests(unittest.TestCase):
    def test_every_emotion_word_belongs_to_exactly_one_expression(self):
        owners = {}
        for key, _label, words in fs.catalog().expressions:
            for word in words:
                self.assertNotIn(word, owners, f"{word} 同时属于 {owners.get(word)} 和 {key}")
                owners[word] = key
        for rule in RULES:
            for word in rule.words:
                self.assertIn(word, owners, f"情绪表的「{word}」没有对应的表情，捏了也进不了镜头")

    def test_presets_and_controls_are_valid(self):
        cat = fs.catalog()
        for key in cat.presets:
            with self.subTest(key):
                sculpt = fs.preset_sculpt(key)
                self.assertTrue(fs.layer_fragments(sculpt))
        for control in cat.controls:
            with self.subTest(control.key):
                if control.kind == "scale":
                    self.assertEqual(control.steps[2], "", "刻度中间档不写词")
                else:
                    self.assertTrue(all(phrase for _value, _label, phrase in control.options))

    def test_bad_input_is_refused_not_dropped(self):
        for raw, needle in (
            ({"face": {"nope": "x"}}, "没有这个捏脸控件"),
            ({"face": {"eye_shape": "triangle"}}, "没有选项"),
            ({"face": {"eye_size": 3}}, "-2 到 2"),
            ({"notes": {"bone": "长" * 61}}, "最多"),
            ({"expressions": {"giggle": {}}}, "没有这个表情"),
            ({"expressions": {"smile": {"choices": {"mouth": "pout"}}}}, "没有选项"),
        ):
            with self.subTest(raw), self.assertRaisesRegex(fs.SculptError, needle):
                fs.validate(raw)

    def test_neutral_and_empty_values_are_not_stored(self):
        sculpt = fs.validate({"face": {"eye_size": 0, "eye_shape": ""}, "notes": {"bone": "  "}, "expressions": {"smile": {}}})
        self.assertTrue(sculpt.empty)


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.sculpt = fs.preset_sculpt("heroine_cool")
        self.merged = fs.merge_description(REAL, self.sculpt)

    def test_title_stays_first_so_aliases_still_resolve(self):
        self.assertTrue(self.merged.startswith("女主角/佩剑者（右手按剑）；身份锚点："))
        task = {"assets": {"3_characters": [{"name": "林婉", "desc": self.merged}]}}
        self.assertEqual(cast_aliases(task).get("佩剑者"), "林婉")

    def test_conflicting_fragments_are_replaced_and_the_rest_kept(self):
        for gone in ("鹅蛋脸", "下颌圆润", "平眉", "杏眼", "鼻梁秀挺", "唇中等厚", "肤色暖白", "视觉年龄22–26"):
            self.assertNotIn(gone, self.merged)
        for kept in ("朱砂痣", "直径2mm", "颈长10cm", "唇色淡朱", "后挽低髻", "无纹身"):
            self.assertIn(kept, self.merged)
        for new in ("丹凤眼", "远山眉", "冷白皮", "下颌线清晰流畅"):
            self.assertIn(new, self.merged)

    def test_layers_reach_every_prompt_through_the_face_card(self):
        card = parse_face_card(self.merged)
        self.assertIn("丹凤眼", card.features)
        self.assertIn("瓜子脸", card.bone)
        self.assertIn("丹凤眼", render_face_card(card, "close"))
        self.assertIn("丹凤眼", build_actor_sheet_prompt("林婉", self.merged, "真人电影写实"))

    def test_negative_notes_go_to_the_avoid_list(self):
        sculpt = fs.validate({"face": {"eye_shape": "almond"}, "notes": {"skin": "不要磨皮，保留细纹"}})
        merged = fs.merge_description("林婉；鹅蛋脸", sculpt)
        card = parse_face_card(merged)
        self.assertIn("磨皮", card.negatives)
        self.assertIn("保留细纹", card.skin)
        self.assertNotIn("不要磨皮", render_face_card(card))

    def test_notes_cannot_open_a_new_layer(self):
        sculpt = fs.validate({"notes": {"features": "骨相：方脸；眉心一点花钿"}})
        self.assertEqual(sculpt.notes["features"], "骨相，方脸，眉心一点花钿")

    def test_an_empty_sculpt_leaves_the_description_alone(self):
        self.assertEqual(fs.merge_description(REAL, fs.validate({})), REAL)


class TaskEditTests(unittest.TestCase):
    def test_save_writes_the_unified_asset_and_reset_restores_it(self):
        task = _task()
        original = copy.deepcopy(task)
        sculpt = fs.preset_sculpt("heroine_cool")
        result = fs.save(task, "林婉", sculpt)
        record = task["assets"]["3_characters"][0]
        self.assertIn("丹凤眼", record["desc"])
        self.assertEqual(result["revision"], 1)
        states = task["assets"]["3_dna"]["characters"][0]["states"]
        self.assertTrue(states[0]["features"].startswith("丹凤眼"))
        self.assertIn("朱砂痣", states[0]["features"])
        self.assertNotIn("杏眼", states[0]["features"])
        self.assertEqual(states[0]["clothing"], "月白宫装")
        self.assertIn("丹凤眼", states[1]["features"])

        fs.save(task, "林婉", sculpt)  # same again: nothing piles up, the face did not change
        self.assertEqual(record["desc"].count("丹凤眼"), 1)
        self.assertEqual(record[fs.RECORD_KEY]["revision"], 1)

        fs.reset(task, "林婉")
        # 只多了一笔「现有设定集画的是哪段描述」：它说的是设定集，不是捏脸，重置不抹掉它。
        self.assertEqual(record.pop(fs.SHEET_KEY), {"sheet": "/media/sheets/linwan_v1.png", "desc_hash": fs._desc_hash(REAL)})
        self.assertEqual(task, original)

    def test_the_sheet_is_stale_only_until_it_is_redrawn(self):
        task = _task()
        record = task["assets"]["3_characters"][0]
        fs.save(task, "林婉", fs.validate({"expressions": {"smile": {"choices": {"eyes": "crescent"}}}}))
        self.assertFalse(fs.sheet_is_stale(record), "只改表情，设定集不用重出")
        fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}}))
        self.assertTrue(fs.sheet_is_stale(record))
        self.assertTrue(fs.current(task, "林婉")["preview"]["stale_note"])
        record["sheet"] = "/media/sheets/linwan_v2.png"
        self.assertFalse(fs.sheet_is_stale(record))

    def test_unknown_character(self):
        with self.assertRaises(LookupError):
            fs.save(_task(), "无名", fs.preset_sculpt("scholar"))


class ShotExpressionTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "林婉", fs.RECORD_KEY: {"expressions": {
                "smile": {"choices": {"eyes": "crescent", "mouth": "soft_smile", "side": "right"}, "tell": "左颊梨涡"},
                "cry": {"choices": {"eyes": "tears"}, "habit": "哭时先咬住下唇"},
            }}},
            {"name": "沈砚", fs.RECORD_KEY: {"expressions": {"sneer": {"choices": {"mouth": "one_corner"}}}}},
        ]

    def test_each_person_gets_their_own_way_of_showing_their_own_emotion(self):
        lines = fs.shot_expression_lines(
            self.records, ["林婉", "沈砚"], [("林婉", "微笑着说"), ("沈砚", "冷笑")],
        )
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("林婉笑时："), lines[0])
        self.assertIn("左颊梨涡", lines[0])
        self.assertIn("沈砚冷笑时：", lines[1])

    def test_a_lone_character_takes_the_shot_emotion_but_two_do_not(self):
        alone = fs.shot_expression_lines(self.records, ["林婉"], [], shot_word="哽咽")
        self.assertEqual(alone, ["林婉哭时：泪水无声滑落，哭时先咬住下唇"])
        self.assertEqual(fs.shot_expression_lines(self.records, ["林婉", "沈砚"], [], shot_word="哽咽"), [])

    def test_titles_resolve_to_the_actor(self):
        lines = fs.shot_expression_lines(self.records, ["佩剑者"], [("佩剑者", "微笑")], aliases={"佩剑者": "林婉"})
        self.assertEqual(len(lines), 1)

    def test_the_note_reaches_the_video_prompt_and_points_at_the_actor(self):
        note = fs.shot_expression_note(fs.shot_expression_lines(self.records, ["林婉"], [("林婉", "微笑")]))
        shot = ShotPromptInput(
            shot_index=1, duration_seconds=6, shot_size="近景", camera_movement="固定机位",
            subject_action="林婉回头", scene="书房", blocking="林婉居中", start_state="林婉背对镜头", end_state="林婉回头看向镜头", characters=["林婉"], cast_refs=["林婉"],
            expression=f"微笑；{note}",
        )
        text = compile_shot_prompt(style_packs.FILM_35MM, shot, model="jimeng").text
        self.assertIn("@[林婉]笑时：", text)
        self.assertIn("左颊梨涡", text)

    def test_stage_five_adds_the_note_to_the_expression(self):
        import inspect
        from app.service import drama_service

        source = inspect.getsource(drama_service)
        self.assertIn("face_sculpt.shot_expression_lines(", source)
        self.assertIn("personal_expression,", source)

    def test_broken_stored_data_never_breaks_a_shot(self):
        records = [{"name": "林婉", fs.RECORD_KEY: {"face": {"eye_shape": "removed-option"}}}]
        self.assertEqual(fs.shot_expression_lines(records, ["林婉"], [], shot_word="笑"), [])
        self.assertEqual(fs.shot_expression_note([]), "")


if __name__ == "__main__":
    unittest.main()


class ApiTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api import drama_api, face_sculpt_api
        from app.api.auth_api import get_current_user
        from app.repository.task_repo import TaskRepository

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous = drama_api.service.repo
        drama_api.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.addCleanup(setattr, drama_api.service, "repo", previous)
        self.repo = drama_api.service.repo
        self.repo.save_task("t1", {"task_id": "t1", "owner_user_id": "u1", **_task()})
        app = FastAPI()
        app.include_router(face_sculpt_api.catalog_router)
        app.include_router(face_sculpt_api.router)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "role": "user"}
        app.dependency_overrides[drama_api.require_owned_drama_task] = lambda: {"user_id": "u1", "role": "user"}
        # 元素库换成假的：本项目绑着一位同名数字演员，写回时能找到它。
        from app.platform.dependencies import get_platform_store
        from tests.test_face_sculpt_sync import FakeStore, element

        self.store = FakeStore([element("e1", "林婉", task_id="t1")])
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.client = TestClient(app)
        self.base = "/api/drama/t1/characters/林婉/face-sculpt"

    def test_catalog(self):
        data = self.client.get("/api/face-sculpt/catalog").json()
        self.assertEqual([layer["key"] for layer in data["layers"]], ["identity", "bone", "features", "skin", "hair", "physique"])
        self.assertTrue(any(control["type"] == "scale" for control in data["controls"]))
        self.assertEqual(len(data["expressions"]), len(fs.catalog().expressions))

    def test_preview_save_and_reset_round_trip(self):
        body = {"face": {"eye_shape": "phoenix", "nose_bridge": 1}, "expressions": {"smile": {"choices": {"eyes": "crescent"}}}}
        preview = self.client.post(f"{self.base}/preview", json=body).json()
        self.assertIn("丹凤眼", preview["description"])
        self.assertEqual(self.repo.get_task("t1")["assets"]["3_characters"][0]["desc"], REAL, "预览不改数据")

        saved = self.client.put(self.base, json=body).json()
        self.assertEqual(saved["revision"], 1)
        self.assertTrue(saved["preview"]["sheet_stale"])
        task = self.repo.get_task("t1")
        self.assertIn("丹凤眼", task["assets"]["3_characters"][0]["desc"])
        dashboard = task["assets"]["3_character_dashboard"]
        lin = next(item for item in dashboard["characters"] if item["name"] == "林婉")
        self.assertIn("丹凤眼", lin["states"][0]["features"])
        self.assertEqual(self.client.get(self.base).json()["sculpt"]["face"]["eye_shape"], "phoenix")

        reset = self.client.delete(self.base).json()
        self.assertEqual(reset["revision"], 0)
        self.assertEqual(self.repo.get_task("t1")["assets"]["3_characters"][0]["desc"], REAL)

    def test_saving_writes_the_description_back_to_the_library_actor(self):
        saved = self.client.put(self.base, json={"face": {"eye_shape": "phoenix"}}).json()
        self.assertEqual(saved["library"], {"updated": True, "element_id": "e1"})
        self.assertEqual(saved["downstream"], {"clips_marked": 0, "sheet_stale": True})
        self.assertEqual(len(self.store.updates), 1)
        self.assertEqual(self.store.updates[0]["description"], saved["preview"]["description"])
        self.assertIn("丹凤眼", self.store.updates[0]["description"])

        reset = self.client.delete(self.base).json()
        self.assertEqual(reset["library"]["updated"], True)
        self.assertEqual(self.store.updates[-1]["description"], REAL, "重置后元素库里也放回原描述")
        self.assertEqual(reset["downstream"]["sheet_stale"], False)

    def test_a_broken_library_does_not_break_saving(self):
        self.store.fail = RuntimeError("db down")
        saved = self.client.put(self.base, json={"face": {"eye_shape": "phoenix"}})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertFalse(saved.json()["library"]["updated"])
        self.assertIn("db down", saved.json()["library"]["error"])
        self.assertIn("丹凤眼", self.repo.get_task("t1")["assets"]["3_characters"][0]["desc"])

    def test_sheet_prompt_is_what_stage_three_would_draw_from(self):
        from unittest.mock import patch

        from app.api import drama_api

        url = "/api/drama/t1/characters/林婉/sheet-prompt"
        before = self.client.get(url).json()
        self.assertEqual(before["revision"], 0)
        self.assertFalse(before["sheet_stale"])
        self.assertEqual(before["prompt"], build_actor_sheet_prompt("林婉", REAL, "现代都市短剧写实电影感"))

        self.client.put(self.base, json={"face": {"eye_shape": "phoenix"}})
        after = self.client.get(url).json()
        desc = self.repo.get_task("t1")["assets"]["3_characters"][0]["desc"]
        self.assertIn("丹凤眼", after["prompt"])
        self.assertEqual(after["prompt"], build_actor_sheet_prompt("林婉", desc, "现代都市短剧写实电影感"))
        self.assertEqual((after["revision"], after["sheet_stale"], after["name"]), (1, True, "林婉"))

        # 对账：真正出图的那条路(不花钱——把文生图调用换成假的)拼出来的提示词以这段开头。
        gateway = drama_api.service.gateway
        with patch.object(gateway, "_generate_image_unmetered", return_value=("", None)) as image:
            gateway._generate_character_sheet_unmetered("img", "林婉", desc, "真人电影写实", gateway.get_genre(""), None, "")
        self.assertTrue(image.call_args.args[1].startswith(after["prompt"]), "接口看到的提示词和第 3 阶段用的不是一份")
        self.assertEqual(self.client.get("/api/drama/t1/characters/无名/sheet-prompt").status_code, 404)

    def test_sheet_prompt_follows_genre_and_director_style(self):
        from app.api import drama_api

        def with_config(**config):
            self.repo.save_task("t1", {"task_id": "t1", "owner_user_id": "u1", "config": config, **_task()})
            return self.client.get("/api/drama/t1/characters/林婉/sheet-prompt").json()["prompt"]

        self.assertEqual(with_config(director_style="anime"), build_actor_sheet_prompt("林婉", REAL, "2D日漫风格"))
        era = drama_api.service.gateway.GENRE_ERA_COSTUME["wuxia"]
        self.assertEqual(
            with_config(title_suggestion="江湖剑客"),
            build_actor_sheet_prompt("林婉", REAL, "符合时代背景的写实影视质感",
                                     era_note=f" The character must wear period-accurate costume — {era}."),
        )

    def test_errors(self):
        self.assertEqual(self.client.put(self.base, json={"face": {"eye_shape": "triangle"}}).status_code, 422)
        self.assertEqual(self.client.get("/api/drama/t1/characters/无名/face-sculpt").status_code, 404)
        self.assertEqual(self.client.get("/api/drama/missing/characters/林婉/face-sculpt").status_code, 404)

    def _fake_gateway(self, answer):
        from app.api import drama_api

        class Gateway:
            def __init__(self):
                self.calls = []

            def call_llm(self, model, system, user, title, max_tokens=None, **_kw):
                self.calls.append({"model": model, "system": system, "user": user, "max_tokens": max_tokens})
                return answer

            def last_answer_was_offline(self):
                return False

        gateway = Gateway()
        previous = drama_api.service.gateway
        drama_api.service.gateway = gateway
        self.addCleanup(setattr, drama_api.service, "gateway", previous)
        return gateway

    def test_instruct_endpoint_previews_without_writing_and_applies_on_request(self):
        gateway = self._fake_gateway('{"face": {"eye_shape": "phoenix", "glow": "x"}, "reply": "眼睛改成丹凤眼"}')
        url = f"{self.base}/instruct"
        self.assertEqual(self.client.post(url, json={"message": "眼睛改成丹凤眼"}).status_code, 422, "没配文本模型不悄悄用模板")
        self.assertEqual(gateway.calls, [])

        previewed = self.client.post(url, json={"message": "眼睛改成丹凤眼", "model": "fake-text"})
        self.assertEqual(previewed.status_code, 200, previewed.text)
        data = previewed.json()
        self.assertFalse(data["saved"])
        self.assertIsNone(data["current"])
        self.assertEqual(data["reply"], "眼睛改成丹凤眼")
        self.assertEqual(data["patch"]["face"], {"eye_shape": "phoenix"})
        self.assertEqual(data["sculpt"]["face"], {"eye_shape": "phoenix"})
        self.assertEqual(len(data["unknown"]), 1)
        self.assertIn("丹凤眼", data["preview"]["description"])
        self.assertEqual(gateway.calls[0]["model"], "fake-text")
        self.assertEqual(gateway.calls[0]["max_tokens"], 1200)
        self.assertEqual(self.repo.get_task("t1")["assets"]["3_characters"][0]["desc"], REAL, "apply=false 不写数据")

        applied = self.client.post(url, json={"message": "眼睛改成丹凤眼", "model": "fake-text", "apply": True}).json()
        self.assertTrue(applied["saved"])
        self.assertEqual(applied["current"]["revision"], 1)
        self.assertEqual([item["label"] for item in applied["current"]["history"]], ["捏脸前"])
        self.assertTrue(applied["current"]["label"].startswith("对话："))
        task = self.repo.get_task("t1")
        self.assertIn("丹凤眼", task["assets"]["3_characters"][0]["desc"])
        lin = next(item for item in task["assets"]["3_character_dashboard"]["characters"] if item["name"] == "林婉")
        self.assertIn("丹凤眼", lin["states"][0]["features"])
        self.assertEqual(self.client.get(self.base).json()["history"][0]["label"], "捏脸前")

    def test_instruct_endpoint_rejects_an_unusable_answer(self):
        self._fake_gateway("这个人应该更好看一点。")
        response = self.client.post(f"{self.base}/instruct", json={"message": "更好看", "model": "fake-text"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("没有给出可用的捏脸改动", response.json()["detail"])

    def test_revert_endpoint(self):
        self.assertEqual(self.client.post(f"{self.base}/revert", json={"snapshot_id": "deadbeef"}).status_code, 404)
        self.client.put(self.base, json={"face": {"eye_shape": "phoenix"}, "label": "第一步"})
        saved = self.client.put(self.base, json={"face": {"eye_shape": "almond"}}).json()
        self.assertEqual([item["label"] for item in saved["history"]], ["第一步", "捏脸前"])
        self.assertEqual(saved["label"], "手动调整")
        reverted = self.client.post(f"{self.base}/revert", json={"snapshot_id": saved["history"][0]["id"]})
        self.assertEqual(reverted.status_code, 200, reverted.text)
        self.assertEqual(reverted.json()["sculpt"]["face"], {"eye_shape": "phoenix"})
        self.assertEqual(reverted.json()["label"], "撤销到「第一步」")
        self.assertIn("丹凤眼", self.repo.get_task("t1")["assets"]["3_characters"][0]["desc"])
        self.assertEqual(self.client.post(f"{self.base}/revert", json={"snapshot_id": "nope"}).status_code, 404)


class HistoryTests(unittest.TestCase):
    def test_history_push_cap_and_revert_round_trip(self):
        task = _task()
        record = task["assets"]["3_characters"][0]
        first = fs.save(task, "林婉", fs.preset_sculpt("heroine_cool"), label="预设")
        self.assertEqual([item["label"] for item in first["history"]], ["捏脸前"])
        self.assertNotIn("sculpt", first["history"][0], "列表里不带整份捏脸")
        fs.save(task, "林婉", fs.preset_sculpt("heroine_cool"), label="原样重存")
        self.assertEqual(len(record[fs.RECORD_KEY]["history"]), 1, "一模一样的再存一次不进历史")

        for step in range(8):
            sculpt = fs.validate({"face": {"eye_shape": "phoenix", "eye_size": (step % 5) - 2, "lips": ["thin", "full"][step % 2]}})
            fs.save(task, "林婉", sculpt, label=f"第{step}步")
        history = record[fs.RECORD_KEY]["history"]
        self.assertEqual(len(history), fs.HISTORY_LIMIT)
        # 历史存的是每次保存之前的那份：当前是第7步，最早的「捏脸前」「预设」「第0步」已经挤出去了。
        self.assertEqual([item["label"] for item in history], ["第1步", "第2步", "第3步", "第4步", "第5步", "第6步"])
        self.assertTrue(all(len(item["id"]) == 8 and item["sculpt"]["face"] for item in history))
        listed = fs.current(task, "林婉")["history"]
        self.assertEqual([item["label"] for item in listed], ["第6步", "第5步", "第4步", "第3步", "第2步", "第1步"])

        target = history[1]
        reverted = fs.revert(task, "林婉", target["id"])
        self.assertEqual(reverted["sculpt"]["face"], target["sculpt"]["face"])
        self.assertEqual(reverted["label"], "撤销到「第2步」")
        self.assertEqual(reverted["history"][0]["label"], "第7步", "退回前的那一步也进了历史")
        self.assertEqual(record["desc"].count("丹凤眼"), 1, "撤销也是从原描述重新合成，不层层加码")
        self.assertEqual(len(record[fs.RECORD_KEY]["history"]), fs.HISTORY_LIMIT)
        with self.assertRaisesRegex(LookupError, "只保留最近几步"):
            fs.revert(task, "林婉", "deadbeef")

    def test_reverting_to_before_sculpting_keeps_the_history(self):
        task = _task()
        original = copy.deepcopy(task)
        fs.save(task, "林婉", fs.preset_sculpt("scholar"))
        before = fs.current(task, "林婉")["history"][-1]
        self.assertEqual(before["label"], "捏脸前")
        reverted = fs.revert(task, "林婉", before["id"])
        self.assertEqual(task["assets"]["3_characters"][0]["desc"], REAL)
        self.assertEqual(task["assets"]["3_dna"], original["assets"]["3_dna"])
        self.assertEqual(reverted["revision"], 0)
        self.assertEqual([item["label"] for item in reverted["history"]], ["手动调整", "捏脸前"])
        fs.revert(task, "林婉", reverted["history"][0]["id"])
        self.assertIn("书卷气", task["assets"]["3_characters"][0]["desc"])

    def test_reset_clears_history(self):
        task = _task()
        fs.save(task, "林婉", fs.preset_sculpt("scholar"))
        fs.save(task, "林婉", fs.preset_sculpt("heroine_cool"))
        self.assertEqual(len(fs.current(task, "林婉")["history"]), 2)
        reset = fs.reset(task, "林婉")
        self.assertEqual(reset["history"], [])
        self.assertNotIn(fs.RECORD_KEY, task["assets"]["3_characters"][0])
        self.assertEqual(fs.save(task, "林婉", fs.validate({})).get("history"), [], "存一份空捏脸等同于重置")

    def test_stale_detection_through_stage_three_sheets(self):
        task = _task()
        record = task["assets"]["3_characters"][0]
        record.pop("sheet")
        task["assets"]["3_sheets"] = {"林婉": "https://cdn/linwan_v1.png"}
        fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}}))
        self.assertEqual(record[fs.SHEET_KEY]["sheet"], "https://cdn/linwan_v1.png", "记在角色记录上、跟着设定集走，不随捏脸一起清掉")
        self.assertTrue(fs.sheet_is_stale(record, task))
        self.assertFalse(fs.sheet_is_stale(record), "不给 task 就只看角色记录自己的 sheet")
        self.assertTrue(fs.current(task, "林婉")["preview"]["sheet_stale"])
        task["assets"]["3_sheets"]["林婉"] = "https://cdn/linwan_v2.png"
        self.assertFalse(fs.sheet_is_stale(record, task))
        self.assertFalse(fs.current(task, "林婉")["preview"]["sheet_stale"])

    def test_a_sheet_redrawn_from_the_sculpted_face_is_stale_once_the_face_goes_back(self):
        task = _task()
        record = task["assets"]["3_characters"][0]
        fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}}))
        self.assertTrue(fs.sheet_is_stale(record, task))
        record["sheet"] = "/media/sheets/linwan_v2.png"      # 第 3 阶段按捏过的脸重出了
        self.assertFalse(fs.sheet_is_stale(record, task))

        reset = fs.reset(task, "林婉")
        self.assertEqual(reset["downstream"], {"clips_marked": 0, "sheet_stale": True}, "脸放回去了，重出的那张画的还是捏过的脸")
        self.assertTrue(fs.current(task, "林婉")["preview"]["sheet_stale"])
        self.assertNotIn(fs.RECORD_KEY, record)
        self.assertEqual(record[fs.SHEET_KEY]["sheet"], "/media/sheets/linwan_v2.png")
        record["sheet"] = "/media/sheets/linwan_v3.png"      # 再重出一次才是现在这张脸
        self.assertFalse(fs.current(task, "林婉")["preview"]["sheet_stale"])

        fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}}))
        saved = fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "almond"}}))
        record["sheet"] = "/media/sheets/linwan_v4.png"
        before = fs.revert(task, "林婉", saved["history"][-1]["id"])
        self.assertEqual(before["label"], "撤销到「捏脸前」")
        self.assertTrue(before["downstream"]["sheet_stale"], "退回捏脸前同样：设定集画的是捏过的脸")
        self.assertTrue(fs.current(task, "林婉")["preview"]["sheet_stale"])

    def test_the_drawing_step_can_record_what_the_sheet_was_drawn_from(self):
        task = _task()
        record = task["assets"]["3_characters"][0]
        fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}}))
        fs.note_sheet_drawn(record, "/media/sheets/linwan_v2.png", record["desc"])
        record["sheet"] = "/media/sheets/linwan_v2.png"
        self.assertFalse(fs.sheet_is_stale(record, task))
        record["desc"] = REAL                                  # 不经捏脸直接改描述，设定集一样是旧的
        self.assertTrue(fs.sheet_is_stale(record, task))

    def test_records_that_only_kept_the_sheet_address_at_save_still_read_as_stale(self):
        task = _task()
        record = task["assets"]["3_characters"][0]
        fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}}))
        record.pop(fs.SHEET_KEY)                               # 老数据：只在捏脸里记了脸动时的设定集地址
        record[fs.RECORD_KEY]["sheet_at_save"] = record["sheet"]
        self.assertTrue(fs.sheet_is_stale(record, task))
        fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}, "expressions": {"smile": {"choices": {"eyes": "crescent"}}}}))
        self.assertTrue(fs.sheet_is_stale(record, task), "补记后仍知道那张画的是捏脸前的描述")
        self.assertEqual(record[fs.SHEET_KEY], {"sheet": "/media/sheets/linwan_v1.png", "desc_hash": fs._desc_hash(REAL)})
        self.assertFalse(fs.reset(task, "林婉")["downstream"]["sheet_stale"])


class InstructTests(unittest.TestCase):
    def test_accepted_parts_apply_and_unknown_parts_are_reported(self):
        task = _task()
        fs.save(task, "林婉", fs.validate({"face": {"lips": "thin"}, "expressions": {"smile": {"tell": "左颊梨涡"}}}))
        calls = []

        def llm(system, user, max_tokens):
            calls.append((system, user, max_tokens))
            return (
                '好的：```json\n{"face": {"eye_shape": "phoenix", "nose_bridge": "1", "eyebrow_glow": "x", "lips": null},'
                ' "notes": {"skin": "' + "细" * 80 + '"},'
                ' "expressions": {"smile": {"choices": {"eyes": "crescent"}}},'
                ' "preset": "", "reply": "眼睛改成丹凤眼，鼻梁高一点。"}\n```'
            )

        before = copy.deepcopy(task)
        result = fs.apply_instruction(task, "林婉", "眼睛改成丹凤眼，鼻梁高一点，皮肤细一点", llm)
        self.assertEqual(task, before, "只预览，不写数据")
        self.assertEqual(result["patch"]["face"], {"eye_shape": "phoenix", "nose_bridge": 1, "lips": None})
        self.assertEqual(result["unknown"], ["没有这个捏脸控件：eyebrow_glow"])
        self.assertEqual(len(result["patch"]["notes"]["skin"]), fs.catalog().limits["note_chars"], "写长了截断而不是报错")
        sculpt = result["sculpt"]
        self.assertEqual(sculpt.face, {"eye_shape": "phoenix", "nose_bridge": 1})
        self.assertEqual(sculpt.expressions["smile"].choices, {"eyes": "crescent"})
        self.assertEqual(sculpt.expressions["smile"].tell, "左颊梨涡", "没提到的表情字段保持原样")
        self.assertEqual(result["reply"], "眼睛改成丹凤眼，鼻梁高一点。")
        self.assertIn("丹凤眼", result["preview"]["description"])

        system, user, max_tokens = calls[0]
        self.assertEqual(max_tokens, 1200)
        self.assertNotIn("{note_chars}", system)
        self.assertIn("60", system)
        for needle in ('"eye_shape"', '"phoenix"', '"丹凤眼"', '"lips":"thin"', "眼睛改成丹凤眼，鼻梁高一点", "女主角/佩剑者"):
            self.assertIn(needle, user)
        self.assertNotIn("清冷疏离的气质", user, "控件表里不带写进提示词的短语")

    def test_a_generated_reply_and_label_lookups(self):
        task = _task()
        result = fs.apply_instruction(task, "林婉", "x", lambda s, u, m: '{"face": {"唇形": "薄唇", "eye_size": 0}, "preset": "温润公子"}')
        self.assertEqual(result["patch"]["preset"], "scholar")
        self.assertEqual(result["patch"]["face"]["lips"], "thin")
        self.assertEqual(result["sculpt"].preset, "scholar")
        self.assertTrue(result["reply"].startswith("按你的要求改了："), result["reply"])
        self.assertIn("薄唇", result["reply"])

    def test_nothing_usable_raises(self):
        task = _task()
        for answer in (None, "", "更好看一点就行", '{"face": {"nope": "x"}}', '{"reply": "好的"}'):
            with self.subTest(answer), self.assertRaisesRegex(fs.SculptError, "没有给出可用的捏脸改动"):
                fs.apply_instruction(task, "林婉", "x", lambda s, u, m: answer)
        with self.assertRaises(LookupError):
            fs.apply_instruction(task, "无名", "x", lambda s, u, m: '{"face": {"lips": "thin"}}')

    def test_an_expression_whose_every_choice_is_rejected_is_not_a_change(self):
        task = _task()
        before = fs.stored_sculpt(fs.record_of(task, "林婉"))
        for answer in ('{"expressions": {"smile": {"choices": {"nope": "x"}}}}', '{"expressions": {"smile": {}}}',
                       '{"expressions": {"笑": {"choices": {"eyes": "没有的选项"}}}}'):
            with self.subTest(answer), self.assertRaisesRegex(fs.SculptError, "没有给出可用的捏脸改动") as caught:
                fs.apply_instruction(task, "林婉", "x", lambda s, u, m: answer)
            if "nope" in answer:
                self.assertIn("nope", str(caught.exception), "被驳回的控件连原因一起说出来")
        self.assertEqual(fs.stored_sculpt(fs.record_of(task, "林婉")), before)
        # 只给 tell / habit、或把表情去掉(null)，仍然算一条改动。
        kept = fs.apply_instruction(task, "林婉", "x", lambda s, u, m: '{"expressions": {"smile": {"tell": "左颊梨涡"}}}')
        self.assertEqual(kept["patch"]["expressions"]["smile"], {"choices": {}, "tell": "左颊梨涡"})
        accepted = fs._Filter()
        accepted.expressions({"smile": None})
        self.assertFalse(accepted.empty)
        self.assertEqual(accepted.patch["expressions"], {"smile": None})

    def test_limits_come_from_the_data_file(self):
        limits = fs.catalog().limits
        self.assertEqual(fs.HISTORY_LIMIT, limits["history_limit"])
        self.assertIn("label_message_chars", limits)


def _clips_task():
    """两段第 5 阶段片段：一段覆盖林婉出镜的镜头(E1S1 第 1、2 镜)，一段只有沈砚(第 3 镜)。"""
    task = _task()
    task["assets"]["4"] = [
        {"scene_id": "E1S1", "shot_id": 1, "characters": ["林婉", "沈砚"]},
        {"scene_id": "E1S1", "shot_id": 2, "characters": ["林婉"]},
        {"scene_id": "E1S1", "shot_id": 3, "characters": ["沈砚"]},
    ]
    task["assets"]["5"] = [
        {"scene_id": "E1S1", "shot_uids": [100101, 100102], "video_url": "/media/a.mp4"},
        {"scene_id": "E1S1", "shot_id": 3, "video_url": "/media/b.mp4"},
    ]
    return task


class DownstreamTests(unittest.TestCase):
    def test_face_change_marks_only_the_clips_covering_this_character(self):
        task = _clips_task()
        hers, his = task["assets"]["5"]
        only_expression = fs.save(task, "林婉", fs.validate({"expressions": {"smile": {"choices": {"eyes": "crescent"}}}}))
        self.assertEqual(only_expression["downstream"], {"clips_marked": 0, "sheet_stale": False}, "只改表情不牵连片段")
        self.assertNotIn("stale", hers)

        saved = fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}}))
        self.assertEqual(saved["downstream"], {"clips_marked": 1, "sheet_stale": True})
        self.assertTrue(hers["stale"])
        self.assertEqual(hers["stale_reason"], "「林婉」的脸已改，需重跑第 5 阶段后生效")
        self.assertNotIn("stale", his)
        self.assertNotIn("stale", task["assets"]["4"][0], "第 4 阶段的图不动")

        again = fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}}))
        self.assertEqual(again["downstream"]["clips_marked"], 0, "原样重存脸没变，不再标")

    def test_revert_and_reset_mark_too(self):
        task = _clips_task()
        hers = task["assets"]["5"][0]
        fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}}), label="第一步")
        saved = fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "almond"}}))
        hers.pop("stale"), hers.pop("stale_reason")
        reverted = fs.revert(task, "林婉", saved["history"][0]["id"])
        self.assertEqual(reverted["downstream"]["clips_marked"], 1)
        self.assertTrue(hers["stale"])

        hers.pop("stale"), hers.pop("stale_reason")
        before = fs.revert(task, "林婉", reverted["history"][-1]["id"])
        self.assertEqual(before["label"], "撤销到「捏脸前」")
        self.assertEqual(before["downstream"], {"clips_marked": 1, "sheet_stale": False}, "退回捏脸前也是换脸")
        self.assertTrue(hers["stale"])

        hers.pop("stale"), hers.pop("stale_reason")
        fs.save(task, "林婉", fs.validate({"face": {"eye_shape": "phoenix"}}))
        hers.pop("stale"), hers.pop("stale_reason")
        reset = fs.reset(task, "林婉")
        self.assertEqual(reset["downstream"], {"clips_marked": 1, "sheet_stale": False})
        self.assertTrue(hers["stale"])
        self.assertEqual(fs.reset(task, "林婉")["downstream"]["clips_marked"], 0, "已经是原脸，再重置不标")

    def test_shots_naming_her_by_title_or_alias_count(self):
        for characters in (["佩剑者"], ["小婉"], "小婉、沈砚"):
            with self.subTest(characters):
                task = _clips_task()
                task["assets"]["3_characters"][0]["aliases"] = ["小婉", "婉儿"]
                task["assets"]["4"][0]["characters"] = characters
                task["assets"]["4"][1]["characters"] = ["沈砚"]
                self.assertEqual(fs.mark_character_clips_stale(task, "林婉", "换脸"), 1)
                self.assertEqual(task["assets"]["5"][0]["stale_reason"], "换脸")
        task = _clips_task()
        task["assets"]["3_characters"][0]["aliases"] = ["小婉", "婉儿"]
        task["assets"]["3_characters"][1]["aliases"] = ["婉儿"]
        task["assets"]["4"][0]["characters"] = ["婉儿"]
        task["assets"]["4"][1]["characters"] = ["沈砚"]
        self.assertEqual(fs.mark_character_clips_stale(task, "林婉", "换脸"), 0, "两个人共用的称呼认不出是谁，不标")

    def test_every_clip_covering_her_shot_is_marked_not_just_the_first(self):
        """同一镜有几段(分镜片段视频旁边还有单镜重拍、没场号的旧片段)就标几段——和整场标过期是同一条对法。"""
        task = _clips_task()
        task["assets"]["5"].append({"scene_id": "E1S1", "shot_id": 2, "video_url": "/media/retake.mp4"})
        task["assets"]["5"].append({"shot_id": 1, "video_url": "/media/legacy.mp4"})
        self.assertEqual(fs.mark_character_clips_stale(task, "林婉", "换脸"), 3)
        self.assertEqual([clip.get("stale") for clip in task["assets"]["5"]], [True, None, True, True])

    def test_helper_without_clips_or_shots_is_a_no_op(self):
        self.assertEqual(fs.mark_character_clips_stale(_task(), "林婉", "换脸"), 0)
        task = _clips_task()
        self.assertEqual(fs.mark_character_clips_stale(task, "无名", "换脸"), 0)
        self.assertNotIn("stale", task["assets"]["5"][0])


class ActorSheetStyleTests(unittest.TestCase):
    def test_style_words_and_the_era_clause_come_from_the_data_file(self):
        """设定集提示词的风格词和时代服饰句只在 actor_sheet.json 里有一份：出图的网关和捏脸页的 sheet-prompt 都读它。"""
        from app.core import actor_sheet_style, prompt_data

        data = prompt_data.load("actor_sheet")
        self.assertEqual(actor_sheet_style.style_word("anime"), data["style_words"]["anime"])
        self.assertEqual(actor_sheet_style.style_word("真人电影写实"), data["style_default"], "表里没有的导演风格用默认词")
        self.assertEqual(actor_sheet_style.style_word("anime", "古代"), data["style_era"], "时代服饰约束压过导演风格")
        self.assertEqual(actor_sheet_style.era_clause(""), "")
        self.assertIn("{era_costume}", data["era_clause"])
        self.assertEqual(actor_sheet_style.era_clause("古代"), data["era_clause"].replace("{era_costume}", "古代"))

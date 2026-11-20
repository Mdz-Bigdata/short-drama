# -*- coding: utf-8 -*-
"""Why a prompt comes out flat: the four checks, the emotion table, and the optimizer's camera mode."""

from __future__ import annotations

import unittest
from unittest import mock

from app.core import camera_doctor, prompt_data
from app.core import canvas_beef_prompt_optimizer as optimizer


def codes(text: str, medium: str = "video") -> list[str]:
    return [finding.code for finding in camera_doctor.diagnose(text, medium).findings]


class TableTests(unittest.TestCase):
    def test_every_emotion_answers_all_six_dimensions_and_says_what_to_avoid(self):
        data = prompt_data.load("emotion_camera")
        self.assertEqual(len(data["emotions"]), 12)
        self.assertEqual(len({row["id"] for row in data["emotions"]}), 12)
        for row in data["emotions"]:
            with self.subTest(row=row["id"]):
                self.assertEqual(len(row["recipe"]), len(data["dimensions"]))
                self.assertTrue(row["cues"] and row["why"] and row["avoid"])

    def test_clash_words_are_words_the_checks_can_actually_find(self):
        data = prompt_data.load("emotion_camera")
        move_names = {name for name, _ in prompt_data.load("camera_amounts")["move_classes"]}
        move_names |= {name for name, _ in data["patterns"]["extra_moves"]}
        for row in data["emotions"]:
            for word in row["clash_sizes"]:
                self.assertRegex(word, data["patterns"]["size"])
            for word in row["clash_angles"]:
                self.assertRegex(word, data["patterns"]["angle"])
            for word in row["clash_moves"]:
                self.assertIn(word, move_names)

    def test_no_cue_word_belongs_to_two_emotions(self):
        seen: dict[str, str] = {}
        for row in prompt_data.load("emotion_camera")["emotions"]:
            for cue in row["cues"]:
                self.assertNotIn(cue, seen, f"{cue} is a cue of both {seen.get(cue)} and {row['id']}")
                seen[cue] = row["id"]

    def test_the_wording_keeps_the_projects_way_of_sizing_a_move(self):
        # camera_amounts: a move is sized by where the frame ends, never by seconds or speed adverbs.
        guide = camera_doctor.guide()
        for word in ("秒内", "匀速推进", "缓慢推进"):
            self.assertNotIn(word, guide)
        self.assertIn("落幅", guide)


class DiagnosisTests(unittest.TestCase):
    def test_a_prompt_with_no_camera_at_all_names_that_first(self):
        found = camera_doctor.diagnose("一个男人站在雨中，电影感")
        self.assertEqual(found.main.code, "no_camera")
        self.assertEqual(found.main.title, "没有说相机在哪")
        self.assertIn("vague", [item.code for item in found.findings])

    def test_a_close_up_for_loneliness_is_a_clash_and_says_how_to_shoot_it(self):
        found = camera_doctor.diagnose("一个女孩站在空荡的地铁站里，孤独，特写，平视")
        clash = next(item for item in found.findings if item.code == "emotion_clash")
        self.assertEqual(found.emotion, "孤独 / 疏离")
        self.assertEqual(clash.evidence, ("特写",))
        self.assertIn("大远景", clash.detail)
        self.assertIn("一靠近就不孤独了", clash.detail)

    def test_a_low_angle_on_the_one_being_crushed_and_a_dolly_zoom_on_grief_are_clashes(self):
        self.assertIn("emotion_clash", codes("老板俯身，员工喘不过气，压迫，近景，低角度仰拍，固定机位"))
        found = camera_doctor.diagnose("她强忍泪水看着信，近景，侧面，镜头推轨变焦，停在信纸上")
        self.assertEqual([item.code for item in found.findings], ["emotion_clash"])
        self.assertEqual(found.moves, ("推轨变焦",))

    def test_an_emotion_word_without_any_camera_gets_the_way_to_shoot_it(self):
        found = camera_doctor.diagnose("他终于释然了，如释重负")
        self.assertEqual([item.code for item in found.findings][:2], ["no_camera", "emotion_only"])
        self.assertIn("拉远并升起", found.findings[1].detail)

    def test_a_move_without_a_landing_stacked_moves_and_a_drifting_default_are_found_on_clips_only(self):
        self.assertIn("no_end", codes("中景，平视，镜头缓缓推近"))
        self.assertNotIn("no_end", codes("中景，平视，镜头推近，停在她握着信的手"))
        stacked = codes("中景，平视，镜头环绕的同时变焦")
        self.assertIn("risky_pair", stacked)
        self.assertIn("move_problem", codes("中景，平视，镜头先推近再拉远，停在门口"))
        self.assertIn("unstated", codes("中景，平视，她低头看信"))
        self.assertNotIn("unstated", codes("中景，平视，她低头看信，固定机位"))
        self.assertEqual(codes("中景，平视，她低头看信", "image"), [])

    def test_what_people_and_things_do_is_not_read_as_a_camera_move(self):
        found = camera_doctor.diagnose("中景，平视，35mm；她站在厨房门口，热气升起，她拉开窗帘，手慢慢下降；固定机位，镜头保持不动")
        self.assertEqual(found.moves, ())
        self.assertEqual(found.findings, ())

    def test_a_move_the_prompt_rules_out_is_not_a_move_it_asks_for(self):
        found = camera_doctor.diagnose("中景，平视；摄影机向右横移约一米，落幅停在门框边，仅有轻微手持呼吸，无推拉、无变焦，不加环绕")
        self.assertEqual(found.moves, ("移", "手持"))
        self.assertEqual(found.findings, ())
        self.assertEqual(codes("中景，平视，固定机位起势，随后镜头推近，停在他抬头的瞬间"), [])

    def test_contradictions_negations_and_undrawable_words_are_named_with_their_words(self):
        found = camera_doctor.diagnose("俯拍，虫视，中景，固定机位；画面里不要出现其他人，高级感")
        by_code = {item.code: item for item in found.findings}
        self.assertEqual(by_code["contradiction"].evidence, ("俯拍", "虫视"))
        self.assertIn("不要出现", by_code["negation"].evidence)
        self.assertEqual(by_code["vague"].evidence, ("高级感",))

    def test_findings_come_in_check_order_and_a_sound_prompt_has_none(self):
        found = camera_doctor.diagnose("孤独，特写，镜头环绕的同时变焦，不要出现路人")
        self.assertEqual([item.check for item in found.findings], sorted(item.check for item in found.findings))
        sound = ("16:9，远景，平视，机位在街道对面，35mm；一个穿深色大衣的男人站在公交站牌下，左手拎着旧皮箱；"
                 "人物压在画面右侧三分线；镜头向前推近，停在他垂下的左手；低饱和暖灰调。")
        self.assertEqual(camera_doctor.diagnose(sound).findings, ())
        self.assertEqual(camera_doctor.diagnose("   ").findings, ())

    def test_the_reference_carries_the_table_the_three_turns_and_the_eight_beats(self):
        reference = camera_doctor.reference()
        self.assertEqual(len(reference["emotions"]), 12)
        self.assertEqual([item["name"] for item in reference["turns"]], ["收紧", "松开", "破水平"])
        self.assertEqual(len(reference["beats"]), 8)
        self.assertEqual([item["dimension"] for item in reference["emotions"][0]["recipe"]],
                         ["景别", "高度", "朝向", "镜头", "构图", "运镜"])


class BareEmotionTests(unittest.TestCase):
    def test_an_emotion_word_standing_alone_is_taken_out_and_named(self):
        text, removed = camera_doctor.without_bare_emotions("远景，背面；一个女孩站在空荡的地铁站里，孤独；她只占画面右下角；固定机位，镜头保持不动。")
        self.assertEqual(text, "远景，背面；一个女孩站在空荡的地铁站里；她只占画面右下角；固定机位，镜头保持不动。")
        self.assertEqual(removed, ["孤独"])
        self.assertEqual(camera_doctor.without_bare_emotions("大片空着的站台；固定机位，镜头保持不动。孤独。")[0],
                         "大片空着的站台；固定机位，镜头保持不动。")
        self.assertEqual(camera_doctor.without_bare_emotions("孤独，大远景，固定机位")[0], "大远景，固定机位")

    def test_an_emotion_written_into_a_sentence_stays(self):
        for text in ("大远景，她孤独地坐在长椅上，固定机位", "中景，她感到孤独与希望，固定机位", "近景，很有压迫感的横梁压在头顶"):
            with self.subTest(text=text):
                self.assertEqual(camera_doctor.without_bare_emotions(text), (text, []))

    def test_suffixed_labels_several_in_a_row_and_line_breaks_are_handled(self):
        text, removed = camera_doctor.without_bare_emotions("中景，固定机位，孤独，悲伤，压抑感")
        self.assertEqual(text, "中景，固定机位")
        self.assertEqual(set(removed), {"孤独", "悲伤", "压抑"})
        self.assertEqual(camera_doctor.without_bare_emotions("中景，平视，她低头看信\n悲伤的氛围\n固定机位")[0], "中景，平视，她低头看信\n固定机位")

    def test_the_guide_asks_for_it_and_the_change_line_names_the_words(self):
        self.assertIn("单独摆着的情绪词", camera_doctor.guide())
        self.assertIn("「孤独、悲伤」", camera_doctor.bare_emotion_change(["孤独", "悲伤"]))


class OptimizerCameraModeTests(unittest.TestCase):
    def request(self, **changes) -> optimizer.Request:
        base = dict(prompt="一个女孩站在空荡的地铁站里，孤独，电影感，特写", medium="video", mode="camera")
        base.update(changes)
        return optimizer.Request(**base)

    def test_the_camera_mode_is_offered_with_its_label(self):
        self.assertIn({"id": "camera", "label": "机位诊断"}, optimizer.modes())

    def test_its_prompt_carries_the_method_the_table_and_what_the_rule_check_found(self):
        system, user = optimizer.prompts(optimizer.checked(self.request()))
        contract = prompt_data.text("canvas_beef_prompt_optimizer", "contract")
        self.assertTrue(system.endswith(contract))
        self.assertIn("只改机位与运镜", system)
        self.assertIn("孤独 / 疏离：", system)
        self.assertLess(system.index("孤独 / 疏离："), system.index(contract))
        self.assertIn("【规则检查先看出的问题】", user)
        self.assertIn("机位和情绪对不上", user)
        self.assertIn("一靠近就不孤独了", user)

    def test_the_avoid_list_is_asked_for_as_a_few_short_items(self):
        system, _ = optimizer.prompts(optimizer.checked(self.request()))
        self.assertIn("规避项只写短词或短语", system)
        self.assertIn("最多五条", system)
        refine, _ = optimizer.prompts(optimizer.checked(self.request(mode="refine")))
        self.assertNotIn("规避项只写短词或短语", refine)

    def test_a_sound_prompt_says_so_and_other_modes_are_untouched(self):
        _, user = optimizer.prompts(optimizer.checked(self.request(prompt="中景，平视，她低头看信，固定机位", medium="image")))
        self.assertIn("没有查出明显问题", user)
        system, user = optimizer.prompts(optimizer.checked(self.request(mode="refine")))
        self.assertNotIn("机位诊断并重写", system)
        self.assertNotIn("规则检查", user)
        self.assertNotIn("孤独 / 疏离：", system)


class RouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api import canvas_beef_api, drama_api
        from app.api.auth_api import get_current_user

        import tempfile
        from pathlib import Path

        from app.repository.task_repo import TaskRepository

        self.drama_api = drama_api
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repo = TaskRepository(str(Path(temp.name) / "tasks.json"))
        repo.save_task("cv-1", {"task_id": "cv-1", "owner_user_id": "u1", "config": {"llm_model": "deepseek-flash"},
                                "assets": {}, "logs": {}, "chat_history": []})
        patch = mock.patch.object(drama_api.service, "repo", repo)
        patch.start()
        self.addCleanup(patch.stop)
        app = FastAPI()
        app.include_router(canvas_beef_api.drama_router)
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1", "username": "u1", "role": "user", "permissions": []}
        self.client = TestClient(app)

    def test_the_rule_check_answers_without_calling_any_model(self):
        with mock.patch.object(self.drama_api.service.gateway, "call_llm", side_effect=AssertionError("no model call")):
            done = self.client.post("/api/drama/cv-1/canvas-beef/camera-diagnosis", json={
                "prompt": "一个女孩站在空荡的地铁站里，孤独，电影感，特写", "medium": "video",
            })
        self.assertEqual(done.status_code, 200)
        body = done.json()
        self.assertEqual(body["emotion"], "孤独 / 疏离")
        self.assertEqual(body["main"], "no_angle")
        self.assertIn("emotion_clash", [item["code"] for item in body["findings"]])
        self.assertEqual(len(body["reference"]["emotions"]), 12)

    def test_a_camera_rewrite_returns_the_rule_checks_findings_beside_the_models_answer(self):
        answer = '{"prompt": "大远景，略高，背面；女孩站在站台右下角", "avoid": [], "changes": ["主因是第②项"], "assumptions": [], "alternatives": []}'
        with mock.patch.object(self.drama_api.service.gateway, "call_llm", return_value=answer) as called:
            done = self.client.post("/api/drama/cv-1/canvas-beef/prompt-optimize", json={
                "prompt": "一个女孩站在空荡的地铁站里，孤独，电影感，特写", "medium": "video", "mode": "camera",
            })
        self.assertEqual(done.status_code, 200)
        self.assertEqual(called.call_count, 1)
        self.assertIn("孤独 / 疏离：", called.call_args.args[1])
        self.assertIn("emotion_clash", [item["code"] for item in done.json()["diagnosis"]["findings"]])
        self.assertTrue(done.json()["prompt"].startswith("大远景"))

    def test_a_bare_emotion_word_the_model_left_in_is_taken_out_and_said_so(self):
        answer = ('{"prompt": "远景，背面；一个女孩站在空荡的地铁站里，孤独；固定机位，镜头保持不动。孤独。", "avoid": ["特写"], '
                  '"changes": ["主因是第①项"], "assumptions": [], "alternatives": ["大远景，背面，孤独，固定机位", "孤独"]}')
        for mode, kept in (("camera", False), ("refine", True)):
            with self.subTest(mode=mode), mock.patch.object(self.drama_api.service.gateway, "call_llm", return_value=answer):
                body = self.client.post("/api/drama/cv-1/canvas-beef/prompt-optimize", json={
                    "prompt": "一个女孩站在空荡的地铁站里，孤独，电影感，特写", "medium": "video", "mode": mode,
                }).json()
            self.assertEqual("孤独" in body["prompt"], kept)
            if not kept:
                self.assertEqual(body["prompt"], "远景，背面；一个女孩站在空荡的地铁站里；固定机位，镜头保持不动。")
                self.assertIn("去掉了单独摆着的情绪词「孤独」", body["changes"][-1])
                # An alternative that would be left empty is kept as the model wrote it.
                self.assertEqual(body["alternatives"], ["大远景，背面，固定机位", "孤独"])
            else:
                self.assertEqual(body["changes"], ["主因是第①项"])


if __name__ == "__main__":
    unittest.main()

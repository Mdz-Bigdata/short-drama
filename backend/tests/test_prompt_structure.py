# -*- coding: utf-8 -*-
"""The optimizer's eight-part structure mode and the rule check of what it returns."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import prompt_data, prompt_structure
from app.core import canvas_beef_prompt_optimizer as optimizer


def structured(spans=("0—3秒｜进场", "3—6秒｜对视", "6—10秒｜拔刀", "10—13秒｜交锋", "13—15秒｜收刀"), drop: str = "") -> str:
    parts = []
    for title in prompt_structure.headings():
        if title == drop:
            continue
        parts.append(title)
        parts.extend(spans if title == "【六、分段镜头脚本】" else ["内容"])
    return "\n".join(parts)


class GuideTests(unittest.TestCase):
    def test_the_guide_names_all_eight_sections_in_order_and_the_clip_length(self):
        guide = prompt_structure.guide(15)
        places = [guide.index(title) for title in prompt_structure.headings()]
        self.assertEqual(len(places), 8)
        self.assertEqual(places, sorted(places))
        self.assertIn("这个片段的时长是 15 秒", guide)
        self.assertIn("原文没有给出时长", prompt_structure.guide(0))
        self.assertIn("原文没有给出时长", prompt_structure.guide(9999))

    def test_it_keeps_the_projects_rules_one_move_per_segment_lines_verbatim_no_invented_lines(self):
        guide = prompt_structure.guide(10)
        self.assertIn("每个时间段最多写一种运镜", guide)
        self.assertIn("一字不改地照抄原文", guide)
        self.assertIn("不要自己编台词", guide)
        self.assertIn("别演成什么", guide)
        self.assertIn("结尾停在什么画面", guide)

    def test_each_layouts_script_index_points_at_its_timed_section(self):
        table = prompt_data.load("prompt_structure")["layouts"]
        self.assertEqual(set(table), {"structure", "fight", "performance"})
        wanted = {"structure": "【六、分段镜头脚本】", "fight": "【动作时间线】", "performance": "【五、分镜脚本与时间线】"}
        for layout, row in table.items():
            self.assertEqual(row["headings"][row["script_heading_index"]], wanted[layout])
            self.assertIn("{headings}", row["guide"])


class CheckTests(unittest.TestCase):
    def test_a_whole_answer_whose_segments_fill_the_clip_passes(self):
        found = prompt_structure.check(structured(), 15)
        self.assertTrue(found["ok"])
        self.assertEqual((found["segments"], found["total_s"]), (5, 15.0))
        self.assertEqual(found["summary"], "八段齐全；分段时间首尾相接，合计 15 秒。")
        self.assertIn("没法核对总长", prompt_structure.check(structured(), 0)["summary"])

    def test_a_missing_section_a_gap_an_overlap_and_a_wrong_total_are_each_named(self):
        missing = prompt_structure.check(structured(drop="【七、声音设计】"), 15)
        self.assertIn("缺了这几段：【七、声音设计】。", missing["problems"])
        gap = prompt_structure.check(structured(spans=("0—3秒｜一", "4—6秒｜二")), 6)
        self.assertEqual(gap["problems"], ["3 秒到 4 秒之间没有安排内容。"])
        overlap = prompt_structure.check(structured(spans=("0—3秒｜一", "2—6秒｜二")), 6)
        self.assertEqual(overlap["problems"], ["有两段的时间重叠：上一段到 3 秒，下一段从 2 秒开始。"])
        total = prompt_structure.check(structured(), 12)
        self.assertEqual(total["problems"], ["分段时间合计 15 秒，片段时长是 12 秒，差了 3 秒。"])
        late = prompt_structure.check(structured(spans=("2—5秒｜一",)), 5)
        self.assertIn("不是从 0 秒开始", late["problems"][0])
        none = prompt_structure.check(structured(spans=("没有时间",)), 5)
        self.assertIn("没有找到", none["problems"][0])

    def test_other_ways_of_writing_a_span_are_read_and_times_elsewhere_are_not(self):
        text = structured(spans=("0.0s–3.5s｜镜头1", "- 3.5s-7s｜镜头2", "7 至 10 秒｜镜头3"))
        text = text.replace("【一、生成任务】\n内容", "【一、生成任务】\n生成一段 10 秒的视频，参考 0-99 秒的素材")
        found = prompt_structure.check(text, 10)
        self.assertTrue(found["ok"], found)
        self.assertEqual(found["segments"], 3)

    def test_a_partial_output_the_creator_asked_for_is_held_only_to_its_timing(self):
        script = "【六、分段镜头脚本】\n0—4秒｜一\n4—8秒｜二"
        self.assertFalse(prompt_structure.check(script, 8)["ok"])
        partial = prompt_structure.check(script, 8, "只要镜头脚本")
        self.assertTrue(partial["ok"])
        self.assertEqual(partial["summary"], "分段时间首尾相接，合计 8 秒。")
        self.assertFalse(prompt_structure.check(script, 9, "只要镜头脚本")["ok"])


def laid_out(layout: str, spans=("0—4秒｜一", "4—8秒｜二"), body: str = "内容") -> str:
    parts = []
    script = prompt_structure.headings(layout)[prompt_data.load("prompt_structure")["layouts"][layout]["script_heading_index"]]
    for title in prompt_structure.headings(layout):
        parts.append(title)
        parts.extend(spans if title == script else [body])
    return "\n".join(parts)


class FightLayoutTests(unittest.TestCase):
    def test_the_guide_asks_for_cause_and_effect_and_keeps_the_projects_fight_rules(self):
        guide = prompt_structure.guide(15, "fight")
        # A long take keeps one fixed set piece and something that flutters on the fighter in every section, from the source only.
        self.assertIn("每一段让同一件不动的大件露一次面", guide)
        self.assertIn("原文没有就不添", guide)
        for piece in ("【动作时间线】", "【结束画面】", "这个片段的时长是 15 秒", "谁先出手", "周围的东西怎么动",
                      "武器在哪只手", "不写血腥的词", "画面不停住", "每段最多一种运镜", "近身交锋 → 蓄势 → 大招倾泻 → 收势"):
            self.assertIn(piece, guide)

    def test_a_fight_that_fills_the_clip_passes_and_a_beat_too_short_for_an_exchange_is_named(self):
        self.assertEqual(prompt_structure.check(laid_out("fight"), 8, layout="fight")["summary"], "八段齐全；分段时间首尾相接，合计 8 秒。")
        rushed = prompt_structure.check(laid_out("fight", spans=("0—1秒｜突袭", "1—4秒｜反击")), 4, layout="fight")
        self.assertEqual(rushed["problems"], ["0—1 秒这一段只有 1 秒，放不下一组完整的攻防和反应。"])
        # The plain eight-part layout has no such floor.
        self.assertTrue(prompt_structure.check(structured(spans=("0—1秒｜一", "1—4秒｜二")), 4)["ok"])

    def test_it_is_for_clips_only(self):
        with self.assertRaises(optimizer.OptimizerError) as refused:
            optimizer.checked(optimizer.Request(prompt="雨巷里两人交手", medium="image", mode="fight"))
        self.assertIn("「动作调度」只用于视频节点", str(refused.exception))


class PerformanceLayoutTests(unittest.TestCase):
    def test_the_guide_turns_emotion_names_into_ordered_measured_movements(self):
        guide = prompt_structure.guide(8, "performance")
        for piece in ("【三、表演基调】", "不出现情绪的名字", "2 到 4 个部位", "都换成数", "只动一侧", "做到一半停下",
                      "台词一字不改", "这个片段的时长是 8 秒"):
            self.assertIn(piece, guide)
        self.assertNotIn("这是一张图片", guide)

    def test_a_picture_gets_one_caught_instant_and_no_timeline_to_check(self):
        guide = prompt_structure.guide(0, "performance", "image")
        self.assertIn("这是一张图片，没有时间线", guide)
        self.assertNotIn("合计等于总时长", guide)
        found = prompt_structure.check(laid_out("performance", spans=("眉头内侧向中间收拢 2 毫米",)), 0, layout="performance", medium="image")
        self.assertEqual((found["ok"], found["summary"], found["segments"]), (True, "五段齐全。", 0))
        optimizer.checked(optimizer.Request(prompt="她低头看信", medium="image", mode="performance"))

    def test_emotion_names_and_unmeasured_adverbs_left_in_the_acting_are_named(self):
        text = laid_out("performance", body="她很伤心，嘴角微微下垂")
        found = prompt_structure.check(text, 8, layout="performance")
        self.assertIn("正文里还留着情绪的名字：伤心。把它们换成看得见的动作。", found["problems"])
        self.assertIn("还有没换成数的程度词：微微。", found["problems"])

    def test_the_ground_rules_section_and_spoken_lines_may_name_an_emotion(self):
        titles = prompt_structure.headings("performance")
        text = "\n".join([
            titles[0], "二十出头的女人，皮肤可见毛孔",
            titles[1], "窗光从左侧来",
            titles[2], "不要出现大哭的戏剧脸，不要把震惊演成张大嘴",
            titles[3], "近景，固定机位",
            titles[4], "0—4秒｜读信", "眉头内侧向中间收拢 2 毫米，约 1 秒后松开", "她说：「我不伤心。」说到「不」字时下唇停顿 0.2 秒",
            "4—8秒｜合上", "右侧嘴角上提不超过 3 毫米，左侧不动",
        ])
        found = prompt_structure.check(text, 8, layout="performance")
        self.assertTrue(found["ok"], found)
        self.assertEqual(found["summary"], "五段齐全；分段时间首尾相接，合计 8 秒。")

    def test_other_layouts_are_not_scanned_for_emotion_words(self):
        self.assertTrue(prompt_structure.check(structured().replace("内容", "她很伤心"), 15)["ok"])


class OptimizerModeTests(unittest.TestCase):
    def request(self, **changes) -> optimizer.Request:
        base = dict(prompt="雨夜码头，林夏提灯上船，回头看了一眼", medium="video", mode="structure", duration=10)
        base.update(changes)
        return optimizer.Request(**base)

    def test_the_mode_is_offered_and_is_for_clips_only(self):
        self.assertIn({"id": "structure", "label": "黄金结构"}, optimizer.modes())
        with self.assertRaises(optimizer.OptimizerError) as refused:
            optimizer.checked(self.request(medium="image"))
        self.assertIn("只用于视频节点", str(refused.exception))

    def test_its_prompt_carries_the_guide_and_the_per_segment_rule_instead_of_the_per_clip_one(self):
        system, user = optimizer.prompts(optimizer.checked(self.request()))
        contract = prompt_data.text("canvas_beef_prompt_optimizer", "contract")
        self.assertTrue(system.endswith(contract))
        self.assertIn("【六、分段镜头脚本】", system)
        self.assertIn("这个片段的时长是 10 秒", system)
        self.assertIn("每个时间段最多写一种运镜", system)
        self.assertNotIn(prompt_data.text("canvas_beef_prompt_optimizer", "video_rules"), system)
        self.assertIn("雨夜码头", user)

    def test_other_modes_do_not_get_the_guide_and_an_absurd_length_is_dropped(self):
        system, _ = optimizer.prompts(optimizer.checked(self.request(mode="refine")))
        self.assertNotIn("【六、分段镜头脚本】", system)
        self.assertEqual(optimizer.checked(self.request(duration=99999)).duration, 0)
        self.assertEqual(optimizer.checked(self.request(duration=12)).duration, 12)


class RouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api import canvas_beef_api, drama_api
        from app.api.auth_api import get_current_user
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

    def ask(self, prompt: str, **body):
        answer = json.dumps({"prompt": prompt, "avoid": [], "changes": ["重排成八段"], "assumptions": [], "alternatives": []}, ensure_ascii=False)
        with mock.patch.object(self.drama_api.service.gateway, "call_llm", return_value=answer) as called:
            done = self.client.post("/api/drama/cv-1/canvas-beef/prompt-optimize", json={
                "prompt": "雨夜码头，林夏提灯上船", "medium": "video", "mode": "structure", **body,
            })
        return done, called

    def test_the_answer_comes_back_with_the_rule_check_of_its_structure(self):
        done, called = self.ask(structured(), duration=15)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["structure_check"]["summary"], "八段齐全；分段时间首尾相接，合计 15 秒。")
        self.assertIn("这个片段的时长是 15 秒", called.call_args.args[1])

    def test_a_script_that_does_not_fill_the_clip_is_said_and_the_prompt_is_left_as_written(self):
        done, _ = self.ask(structured(), duration=10)
        body = done.json()
        self.assertFalse(body["structure_check"]["ok"])
        self.assertIn("差了 5 秒", body["structure_check"]["problems"][0])
        self.assertEqual(body["prompt"], structured())

    def test_a_picture_node_is_refused_before_any_model_is_called(self):
        with mock.patch.object(self.drama_api.service.gateway, "call_llm", side_effect=AssertionError("no model call")):
            done = self.client.post("/api/drama/cv-1/canvas-beef/prompt-optimize", json={
                "prompt": "雨夜码头", "medium": "image", "mode": "structure",
            })
        self.assertEqual(done.status_code, 422)
        self.assertIn("只用于视频节点", done.json()["detail"])

    def test_the_fight_and_performance_modes_are_checked_by_their_own_layout(self):
        def ask(mode, prompt, **body):
            answer = json.dumps({"prompt": prompt, "avoid": [], "changes": [], "assumptions": [], "alternatives": []}, ensure_ascii=False)
            with mock.patch.object(self.drama_api.service.gateway, "call_llm", return_value=answer) as called:
                done = self.client.post("/api/drama/cv-1/canvas-beef/prompt-optimize", json={
                    "prompt": "雨巷里两人交手", "medium": "video", "mode": mode, **body,
                })
            return done.json(), called.call_args.args[1]

        fight, system = ask("fight", laid_out("fight"), duration=8)
        self.assertEqual(fight["structure_check"]["summary"], "八段齐全；分段时间首尾相接，合计 8 秒。")
        self.assertIn("【动作时间线】", system)
        acting, system = ask("performance", laid_out("performance", body="她很伤心"), duration=8)
        self.assertIn("伤心", acting["structure_check"]["problems"][0])
        self.assertIn("【三、表演基调】", system)
        self.assertNotIn("【动作时间线】", system)

    def test_other_modes_carry_no_structure_check(self):
        answer = json.dumps({"prompt": "雨夜码头，中景", "avoid": [], "changes": [], "assumptions": [], "alternatives": []}, ensure_ascii=False)
        with mock.patch.object(self.drama_api.service.gateway, "call_llm", return_value=answer):
            body = self.client.post("/api/drama/cv-1/canvas-beef/prompt-optimize", json={
                "prompt": "雨夜码头", "medium": "video", "mode": "refine",
            }).json()
        self.assertNotIn("structure_check", body)


if __name__ == "__main__":
    unittest.main()

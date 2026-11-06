# -*- coding: utf-8 -*-
"""分镜表定稿前的一次修订：退回的表、衔接自检没过的表，带着原因改一版，都在生图之前。"""

import unittest
from unittest.mock import patch

from app.core import storyboard_revision
from app.core.model_gateway import ModelGateway
from app.service.drama_service import DramaService

_ROW = "| {i} | {size} | 平视 | Fixed | {desc} | | 环境声 | 6s | 线索 | {cast} | E1S02 书房 |"


def _table(rows):
    return "\n".join(_ROW.format(i=i, size=size, desc=desc, cast=cast) for i, (size, desc, cast) in enumerate(rows, start=1))


_FLIP = _table([
    ("远景", "烛火暖光里，林夏推门进来，档案柜在画面右侧", "林夏"),
    ("中景", "月光冷青从窗外切进来，林夏走到桌前，把公文包放在桌角", "林夏"),
    ("近景", "林夏翻开第一页档案，指尖停在一张照片上", "林夏"),
])
_CLEAN = _table([
    ("远景", "烛火暖光里，林夏推门进来，档案柜在画面右侧", "林夏"),
    ("中景", "烛火暖光下，林夏走到桌前，把公文包放在桌角", "林夏"),
    ("近景", "林夏翻开第一页档案，指尖停在一张照片上", "林夏"),
])
_STRANGER = _table([
    ("远景", "烛火暖光里，王二推门进来", "王二"),
    ("中景", "林夏走到桌前", "林夏"),
    ("近景", "林夏翻开档案", "林夏"),
])


def _board(answers):
    service = DramaService.__new__(DramaService)
    service.gateway = ModelGateway.__new__(ModelGateway)
    task = {
        "task_id": "synthetic-storyboard",
        "assets": {"3_sheets": {"林夏": "https://image.test/lin.png"}, "3_characters": [{"name": "林夏", "desc": "青灰大衣"}]},
        # A ten-second clip keeps these rows apart: the revision is judged between panels, not inside one.
        "config": {"llm_model": "m", "image_model": "img", "video_model": "kling-v2"},
    }
    scene = {"scene_id": "E1S02", "content": "林夏追查线索", "characters": ["林夏"], "duration": "20s"}
    with patch.object(service.gateway, "call_llm", side_effect=list(answers)) as llm, \
         patch.object(service.gateway, "generate_image", return_value=("https://image.test/panel.png", {})), \
         patch.object(service.gateway, "validate_image_request", return_value=None, create=True), \
         patch("app.service.drama_service.load_storyboard_elements", return_value=[]), \
         patch("app.service.drama_service.persist_storyboard_frame", return_value=None), \
         patch("app.service.drama_service.compose_nine_grid", side_effect=lambda images, path: path):
        payload = service._generate_scene_board(
            task, task["config"], scene, sys_prompt="s", storyboard_negative="", title="十二小时", genre="mystery",
            dir_style="noir", shot_style="cinematic", guidance="", char_info=("林夏", "记者", "周教授", "反派"),
        )
    return payload, llm


class HandoffIssueTests(unittest.TestCase):
    def test_a_light_flip_between_adjacent_shots_is_an_issue_and_a_steady_light_is_not(self):
        flip = [{"size": "远景", "desc": "烛火暖光里推门"}, {"size": "中景", "desc": "月光冷青，走到桌前"}]
        issues = storyboard_revision.handoff_issues(flip, scene_id="E1S02")
        self.assertEqual(len(issues), 1)
        self.assertIn("光色相反", issues[0])
        steady = [{"size": "远景", "desc": "烛火暖光里推门"}, {"size": "中景", "desc": "烛火暖光下走到桌前"}]
        self.assertEqual(storyboard_revision.handoff_issues(steady, scene_id="E1S02"), [])


    def test_a_shot_that_pushes_in_then_pulls_back_or_stacks_three_moves_is_an_issue(self):
        shots = [
            {"size": "中景", "desc": "烛火暖光里推门", "motion": "缓慢推近，停顿半秒，再缓慢拉回"},
            {"size": "中景", "desc": "烛火暖光下走到桌前", "motion": "手持微晃，缓慢横移带轻推"},
            {"size": "中景", "desc": "烛火暖光下坐下", "motion": "缓慢推近（slow push in），不拉回不左右摇"},
        ]
        issues = storyboard_revision.handoff_issues(shots, scene_id="E1S02")
        self.assertEqual(len(issues), 2)
        self.assertIn("第1镜", issues[0])
        self.assertIn("推近又拉远", issues[0])
        self.assertIn("第2镜", issues[1])
        self.assertIn("3种运镜", issues[1])
        self.assertIn("一个主运镜", storyboard_revision.revision_note(issues))


class RevisionTests(unittest.TestCase):
    def test_a_fight_table_with_vague_moves_goes_back_with_how_to_write_them(self):
        shots = [
            {"size": "中景", "angle": "平视", "motion": "固定", "desc": "沈砚一个旋踢把对方踢飞", "characters": ["沈砚"]},
            {"size": "近景", "angle": "平视", "motion": "固定", "desc": "两人激烈交手，势均力敌", "characters": ["沈砚"]},
        ]
        issues = storyboard_revision.handoff_issues(shots, scene_id="E1S02", fight=True)
        self.assertEqual(len(issues), 2)
        self.assertIn("「旋踢」", issues[0])
        self.assertIn("右腿自下而上斜踢", issues[0])
        self.assertIn("「激烈交手」「势均力敌」", issues[1])
        self.assertIn("哪只手哪只脚", issues[1])
        # The same table in a dialogue scene is judged only on joins and camera moves.
        self.assertEqual(storyboard_revision.handoff_issues(shots, scene_id="E1S02"), [])

    def test_a_specific_fight_table_passes_and_a_measurement_is_not_a_move(self):
        shots = [
            {"size": "中景", "angle": "平视", "motion": "固定", "characters": ["沈砚"],
             "desc": "沈砚右腿自下而上斜踢，脚背击中对方左侧肋部，对方左小臂外旋咬住来势；剑尖离地约一拳"},
        ]
        self.assertEqual(storyboard_revision.handoff_issues(shots, scene_id="E1S02", fight=True), [])

    def test_a_strike_without_a_landing_or_a_reaction_goes_back_for_contact(self):
        shots = [
            {"size": "中景", "angle": "平视", "motion": "固定", "characters": ["沈砚"], "desc": "沈砚右直拳打过去，身子跟着往前压"},
            {"size": "近景", "angle": "平视", "motion": "固定", "characters": ["沈砚"], "desc": "沈砚右直拳击中对方颧骨，拳峰压出褶皱"},
            {"size": "中景", "angle": "平视", "motion": "固定", "characters": ["沈砚"], "desc": "两人隔半个身位对峙，沈砚重心下沉，刀尖扬起"},
        ]
        issues = storyboard_revision.handoff_issues(shots, scene_id="E1S02", fight=True)
        self.assertEqual(len(issues), 2, issues)
        self.assertIn("第1镜出了手（「直拳」）却没写打在哪", issues[0])
        self.assertIn("拳拳到肉", issues[0])
        self.assertIn("第2镜受击方没有反应", issues[1])
        # A shot already sent back for a vague move is not told twice.
        vague = [{"size": "中景", "angle": "平视", "motion": "固定", "characters": ["沈砚"], "desc": "沈砚一个旋踢把对方踢飞"}]
        self.assertEqual(len(storyboard_revision.handoff_issues(vague, scene_id="E1S02", fight=True)), 1)

    def test_a_full_orbit_is_sent_back_as_an_axis_break(self):
        shots = [{"size": "中景", "angle": "平视", "motion": "环绕两人一周", "desc": "两人对视", "characters": ["沈砚"]}]
        issues = storyboard_revision.handoff_issues(shots, scene_id="E1S02")
        self.assertEqual(len(issues), 1)
        self.assertIn("越轴", issues[0])
        half = [{"size": "中景", "angle": "平视", "motion": "绕两人缓慢环绕约90度", "desc": "两人对视", "characters": ["沈砚"]}]
        self.assertEqual(storyboard_revision.handoff_issues(half, scene_id="E1S02"), [])

    def test_a_rejected_table_goes_back_with_the_reason_and_the_revision_is_drawn(self):
        payload, llm = _board([_STRANGER, _CLEAN])
        self.assertEqual(llm.call_count, 2)
        second_prompt = llm.call_args_list[1].args[2]
        self.assertIn("上一版被退回", second_prompt)
        self.assertIn("未出场角色：王二", second_prompt)
        self.assertEqual([shot["characters"] for shot in payload["shots"]], [["林夏"]] * 3)

    def test_a_light_flip_goes_back_and_the_cleaner_version_is_kept(self):
        payload, llm = _board([_FLIP, _CLEAN])
        self.assertEqual(llm.call_count, 2)
        self.assertIn("光色相反", llm.call_args_list[1].args[2])
        self.assertIn("烛火暖光下", payload["shots"][1]["desc"])

    def test_a_clean_table_is_drawn_without_a_second_call(self):
        _payload, llm = _board([_CLEAN])
        self.assertEqual(llm.call_count, 1)

    def test_the_stored_table_is_the_version_that_was_drawn(self):
        # 修订版被退回，画的是初稿：存下来的原文也必须是初稿。
        payload, llm = _board([_FLIP, _STRANGER])
        self.assertEqual(payload["raw"], _FLIP)

    def test_a_revision_that_is_itself_rejected_falls_back_to_the_first_draft(self):
        payload, llm = _board([_FLIP, _STRANGER])
        self.assertEqual(llm.call_count, 2)
        self.assertIn("月光冷青", payload["shots"][1]["desc"])

    def test_a_second_rejection_fails_the_scene_with_its_reason(self):
        with self.assertRaisesRegex(ValueError, "未出场角色：王二"):
            _board([_STRANGER, _STRANGER])


if __name__ == "__main__":
    unittest.main()

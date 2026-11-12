# -*- coding: utf-8 -*-
"""What the stage says in words: posture names, how a pair stands to each other, who is beside
what, and a clip brief that keeps everybody in it.

No model, no network: each sentence is read from positions and headings the test sets.
"""

import unittest
from typing import get_args
from unittest.mock import patch

from app.core import prompt_data
from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan, clip_brief, repair
from app.core.spatial_stage.models import ActionClip, CameraKey, Posture, ShotTimeline, StageLandmark, StagePlan
from app.core.spatial_stage.operations import apply_operations
from app.core.spatial_stage.planner import refresh
from app.core.spatial_stage.prompting import landmark_size, scale_reference, table_brief
from app.core.spatial_stage.wording import move_zh, posture_zh
from tests.test_spatial_stage import _brief

_ENGLISH_POSTURES = get_args(Posture)


def _turned(plan: StagePlan, **yaws: float) -> StagePlan:
    operations = [
        {"op": "move_actor", "name": name, "position": list(plan.actor(name).position), "yaw_deg": yaw}
        for name, yaw in yaws.items()
    ]
    return apply_operations(plan, operations, solve=False)


def _moved(plan: StagePlan, name: str, position: list[float]) -> StagePlan:
    return apply_operations(plan, [{"op": "move_actor", "name": name, "position": position}], solve=False)


def _pair_clause(plan: StagePlan) -> str:
    return plan.shot(1).text.blocking.split("；")[0]


class PostureNameTests(unittest.TestCase):
    def test_every_posture_and_move_has_a_chinese_name(self):
        self.assertEqual(posture_zh("kneel"), "跪地")
        self.assertEqual(posture_zh("stand"), "站立")
        self.assertEqual(move_zh("push"), "推近")
        self.assertEqual(set(prompt_data.value("stage_brief", "postures")), set(_ENGLISH_POSTURES))

    def test_a_posture_check_and_its_repair_read_in_chinese(self):
        plan = build_plan(_brief())
        shots = [
            shot.model_copy(update={"action": "沈砚跪倒在地" if shot.shot_id == 2 else shot.action, "overrides": []})
            for shot in plan.shots
        ]
        plan = refresh(plan.model_copy(update={"shots": shots}))
        check = next(item for item in plan.checks if item.code == "spatial_action_changes_state")
        self.assertEqual(check.detail, "第2镜沈砚的姿态应为「跪地」，空间方案里是「站立」。")
        proposal = next(item for item in repair.propose(plan) if item.code == check.code)
        self.assertEqual(proposal.detail, "第2镜沈砚改为「跪地」。")
        operation = proposal.operations[0]
        # The payload keeps the enum the operation validates; only what a person reads is translated.
        self.assertEqual(operation["posture"], "kneel")
        self.assertEqual(operation["reason"], "分镜写明「跪地」")
        for text in (check.detail, proposal.detail, operation["reason"]):
            self.assertFalse([word for word in _ENGLISH_POSTURES if word in text], text)


class PairRelationTests(unittest.TestCase):
    def setUp(self):
        # 沈砚 stands at stage left facing +X, 黄琰 at stage right facing -X.
        self.plan = build_plan(_brief())

    def test_two_people_turned_to_each_other_are_face_to_face(self):
        self.assertTrue(_pair_clause(self.plan).endswith("相距2.6米面对面"))

    def test_two_people_turned_away_are_back_to_back(self):
        plan = _turned(self.plan, 沈砚=-90, 黄琰=90)
        self.assertTrue(_pair_clause(plan).endswith("相距2.6米背对背"))
        self.assertNotIn("面对面", plan.shot(1).text.blocking)
        self.assertNotIn("看向", plan.shot(1).text.eyeline)

    def test_one_with_the_back_turned_is_said_by_name(self):
        plan = _turned(self.plan, 沈砚=90, 黄琰=90)
        self.assertTrue(_pair_clause(plan).endswith("相距2.6米，沈砚面向黄琰，黄琰背对沈砚"))
        his, hers = plan.shot(1).text.eyeline.split("；")[:2]
        self.assertIn("看向画内的黄琰", his)
        # Nobody looks at a person behind their own back.
        self.assertTrue(hers.startswith("黄琰"))
        self.assertNotIn("看向", hers)

    def test_the_same_heading_shoulder_to_shoulder_is_side_by_side(self):
        self.assertTrue(_pair_clause(_turned(self.plan, 沈砚=0, 黄琰=0)).endswith("相距2.6米同向并肩"))

    def test_an_unclear_relation_is_left_unsaid(self):
        self.assertTrue(_pair_clause(_turned(self.plan, 沈砚=0, 黄琰=180)).endswith("相距2.6米"))


class SetProseTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())
        self.actor = self.plan.actor("沈砚")

    def _door(self, position: list[float]) -> StageLandmark:
        return StageLandmark(id="door-09", name="门", kind="architecture", position=position, size=[1.0, 0.1, 2.4])

    def test_someone_is_beside_a_piece_only_when_standing_by_it(self):
        x, z = self.actor.position
        near = scale_reference(self.plan, self.actor, self._door([x, z - 1.0]))
        self.assertIn("沈砚站在门旁，头顶比门顶低约0.7米", near)
        far = scale_reference(self.plan, self.actor, self._door([x, z - 4.0]))
        self.assertIn("沈砚头顶比门顶低约0.7米", far)
        self.assertNotIn("门旁", far)

    def test_the_third_person_is_placed_where_they_stand(self):
        self.assertIn("内侍在两人后方", table_brief(self.plan))
        self.assertIn("内侍在两人前方", table_brief(_moved(self.plan, "内侍", [0.0, 2.0])))
        beside = table_brief(_moved(self.plan, "内侍", [-3.0, 0.0]))
        self.assertIn("内侍在两人身侧", beside)
        self.assertNotIn("内侍在两人后方", beside)

    def test_a_hand_prop_is_sized_in_centimetres(self):
        pen = StageLandmark(id="prop-09", name="录音笔", kind="prop", position=[0.0, 0.0], size=[0.14, 0.03, 0.03])
        self.assertEqual(landmark_size(pen), "宽约14厘米、高约3厘米")
        desk = StageLandmark(id="desk-09", name="书案", kind="furniture", position=[0.0, 0.0], size=[1.6, 0.7, 0.75])
        self.assertEqual(landmark_size(desk), "宽约1.6米、进深约0.7米、高约0.8米")


def _crowded() -> StagePlan:
    cast = ["沈砚", "黄琰", "林晚", "顾城", "老周", "阿福", "小翠"]
    return build_plan(SceneBrief(
        scene_id="E2S01", location="卧房 / 夜 / 内景", text="沈砚与黄琰在床榻边对峙，众人围在两侧。",
        characters=cast, props=["书案"],
        shots=[
            ShotSpec(1, cast, "", "全景", "平视", "固定", "众人围在床榻边"),
            ShotSpec(2, ["沈砚"], "沈砚", "近景", "过肩", "固定", "沈砚盯着对面"),
        ],
    ))


class ClipBriefTests(unittest.TestCase):
    def test_everyone_in_frame_is_in_the_brief(self):
        plan = _crowded()
        people = [line for line in clip_brief.shot_lines(plan, 1) if line.startswith("人物：")]
        self.assertEqual(
            [line.split("：")[1] for line in people],
            [state.name for state in plan.shot(1).screen if state.visible and plan.actor(state.name)],
        )
        self.assertEqual(len(people), 7)
        # Past the detail threshold a person is kept, in a shorter form.
        self.assertIn("身高约", people[0])
        self.assertNotIn("身高约", people[-1])
        self.assertIn("朝向", people[-1])

    def test_the_detail_threshold_shortens_lines_and_drops_nobody(self):
        plan = _crowded()
        data = {**prompt_data.load("stage_brief"), "full_detail_people": 2}
        with patch.object(clip_brief, "_data", return_value=data):
            people = [line for line in clip_brief.shot_lines(plan, 1) if line.startswith("人物：")]
        self.assertEqual(len(people), 7)
        self.assertEqual([("身高约" in line) for line in people], [True, True, False, False, False, False, False])

    def test_an_action_done_again_later_is_said_again(self):
        plan = build_plan(_brief())
        clips = [
            ActionClip(id="c1", clip="human-walk-v1", start=0, end=1),
            ActionClip(id="c2", clip="human-walk-v1", start=1, end=2),
            ActionClip(id="c3", clip="human-sit-enter-v1", start=2, end=3),
            ActionClip(id="c4", clip="human-walk-v1", start=3, end=4),
        ]
        plan.timelines["2"] = ShotTimeline(duration_s=5, clips={"沈砚": clips})
        person = next(line for line in clip_brief.shot_lines(plan, 2) if line.startswith("人物：沈砚："))
        self.assertIn("动作行走→坐下→行走", person)
        self.assertNotIn("行走→行走", person)

    def test_a_keyed_camera_is_described_once(self):
        plan = build_plan(_brief())
        single = next(line for line in clip_brief.shot_lines(plan, 3) if line.startswith("机位："))
        self.assertIn("推近至", single)
        camera = plan.camera(plan.shot(3).camera_id)
        x, y, z = camera.position
        keys = [
            CameraKey(time=0, position=[x, y, z], target=camera.target),
            CameraKey(time=4, position=[x, y, z + 1.5], target=camera.target),
        ]
        plan.timelines["3"] = ShotTimeline(duration_s=5, camera=keys)
        keyed = next(line for line in clip_brief.shot_lines(refresh(plan), 3) if line.startswith("机位："))
        self.assertIn("机位轨迹2个关键点", keyed)
        self.assertNotIn("推近至", keyed)


if __name__ == "__main__":
    unittest.main()

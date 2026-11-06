# -*- coding: utf-8 -*-
"""规划器按画面文字给每一镜排姿势和动作轨道；人在导演台排过的镜照旧。"""

import unittest

from app.core.spatial_stage import clip_brief, performance
from app.core.spatial_stage.coverage import ShotSpec
from app.core.spatial_stage.models import ActionClip, ActorOverride, ShotTimeline, StagePose
from app.core.spatial_stage.operations import apply_operations
from app.core.spatial_stage.planner import build_plan
from tests.test_spatial_stage import _brief


def _plan(**shots):
    specs = [
        ShotSpec(1, ["沈砚", "黄琰", "内侍"], "", "全景", "平视", "固定", "三人在文思阁内，黄琰坐在案后", seconds=6),
        ShotSpec(2, ["沈砚"], "沈砚", "近景", "过肩", "固定", "沈砚抱臂盯着对面", seconds=4),
        ShotSpec(3, ["黄琰"], "黄琰", "近景", "过肩", "缓推", "黄琰起身，抬手指向沈砚", seconds=5),
        ShotSpec(4, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "沈砚走向黄琰，一拳砸在案上", seconds=8),
    ]
    return build_plan(_brief(shots=specs, **shots))


def _clips(plan, shot, name):
    return [(clip.clip, clip.start, clip.end) for clip in plan.timelines[str(shot)].clips[name]]


class GestureTests(unittest.TestCase):
    def test_a_gesture_is_read_from_the_clause_that_names_the_person(self):
        cast = ["沈砚", "黄琰"]
        self.assertEqual(performance.gesture_in("沈砚", "沈砚抱臂盯着对面，黄琰一拳砸在案上", cast), "cross-arms")
        self.assertEqual(performance.gesture_in("黄琰", "沈砚抱臂盯着对面，黄琰一拳砸在案上", cast), "punch")
        self.assertEqual(performance.gesture_in("沈砚", "沈砚走向黄琰，一拳砸在案上", cast), "punch", "黄琰 is the object, not a new subject")
        self.assertEqual(performance.gesture_in("沈砚", "沈砚抱臂盯着对面，黄琰一拳砸在案上"), "cross-arms", "without a cast, one clause")
        self.assertEqual(performance.gesture_in("内侍", "沈砚抱臂盯着对面"), "")
        # A clause with no subject continues the last person named; it stops where someone else is named.
        self.assertEqual(performance.gesture_in("黄琰", "黄琰起身，抬手指向沈砚", ["沈砚", "黄琰"]), "point-ahead")
        self.assertEqual(performance.gesture_in("黄琰", "黄琰起身，沈砚抬手指向他", ["沈砚", "黄琰"]), "")

    def test_a_pose_comes_from_the_gesture_then_the_posture_and_never_from_standing_or_walking(self):
        self.assertEqual(performance.pose_for("沈砚", "stand", "沈砚躬身行礼").preset, "bow")
        self.assertEqual(performance.pose_for("沈砚", "kneel", "沈砚低头").preset, "kneel-one")
        self.assertIsNone(performance.pose_for("沈砚", "stand", "沈砚低头"))
        self.assertIsNone(performance.pose_for("沈砚", "walk", "沈砚走过去"))


class PlannedShotTests(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()

    def _pose(self, shot, name):
        change = next((item for item in self.plan.shot(shot).overrides if item.name == name), None)
        return change.pose.preset if change is not None and change.pose is not None else None

    def test_every_shot_gets_poses_and_a_timeline_as_long_as_the_shot(self):
        self.assertEqual(self._pose(1, "黄琰"), "sit")
        self.assertEqual(self._pose(2, "沈砚"), "cross-arms")
        self.assertEqual(self._pose(3, "黄琰"), "point-ahead")
        self.assertEqual(self._pose(4, "沈砚"), "punch")
        self.assertEqual([self.plan.timelines[key].duration_s for key in ("1", "2", "3", "4")], [6.0, 4.0, 5.0, 8.0])

    def test_sitting_down_standing_up_talking_and_walking_become_clips(self):
        self.assertEqual(_clips(self.plan, 1, "黄琰"), [("human-sit-enter-v1", 0.0, 1.3), ("human-sit-idle-v1", 1.3, 6.0)])
        self.assertEqual(_clips(self.plan, 2, "沈砚"), [("human-talk-v1", 0.0, 4.0)], "the speaker talks")
        self.assertEqual(_clips(self.plan, 3, "黄琰"), [("human-sit-exit-v1", 0.0, 1.03), ("human-talk-v1", 1.03, 5.0)])
        walk = _clips(self.plan, 4, "沈砚")
        self.assertEqual(walk[0][0], "human-walk-v1")
        self.assertEqual(walk[1][0], "human-idle-v1", "arrived, so standing")
        keys = self.plan.timelines["4"].actors["沈砚"]
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0].time, 0.0)
        self.assertLess(keys[1].time, 8.0 * 0.8 + 1e-6)

    def test_whoever_is_posed_or_moving_gets_a_figure_that_shows_it(self):
        figures = {actor.name: actor.figure for actor in self.plan.actors}
        self.assertEqual(figures["沈砚"], "mannequin", "posed: the jointed figure")
        self.assertEqual(figures["黄琰"], "mannequin")
        self.assertEqual(figures["内侍"], "humanoid", "only an action track: the skinned figure")
        chosen = self.plan.model_copy(update={"actors": [actor.model_copy(update={"figure": "standin"}) if actor.name == "沈砚" else actor for actor in self.plan.actors]})
        kept = performance.figures_for(chosen.model_copy(update={"actors": [actor.model_copy(update={"figure": "humanoid"}) if actor.name == "沈砚" else actor for actor in chosen.actors]}), self.plan.shots, self.plan.timelines)
        self.assertEqual(next(actor.figure for actor in kept if actor.name == "沈砚"), "humanoid", "a person's choice stands")

    def test_the_brief_for_the_video_model_reads_them(self):
        lines = "\n".join(clip_brief.shot_lines(self.plan, 4))
        self.assertIn("姿势出拳", lines)
        self.assertIn("动作行走→站立待机", lines)
        self.assertIn("走位约", lines)
        self.assertIn("姿势坐姿", "\n".join(clip_brief.shot_lines(self.plan, 1)))

    def test_a_table_without_durations_gets_poses_but_no_invented_timeline(self):
        plan = build_plan(_brief(shots=[ShotSpec(1, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "沈砚抱臂盯着黄琰")]))
        self.assertEqual(plan.timelines, {})
        self.assertEqual(next(item.pose.preset for item in plan.shot(1).overrides if item.name == "沈砚"), "cross-arms", "poses do not need a duration")


class EditsTests(unittest.TestCase):
    def test_a_persons_timeline_and_pose_survive_a_re_plan(self):
        plan = _plan()
        edited = apply_operations(plan, [
            {"op": "set_pose", "name": "沈砚", "preset": "think", "shot_id": 2},
            {"op": "set_timeline", "shot_id": 3, "duration_s": 9, "clips": {"黄琰": [{"id": "mine", "clip": "human-talk-v1", "start": 0, "end": 9}]}},
        ], solve=False)
        self.assertEqual(edited.source, "edited")
        again = build_plan(_brief(shots=[
            ShotSpec(1, ["沈砚", "黄琰", "内侍"], "", "全景", "平视", "固定", "三人在文思阁内，黄琰坐在案后", seconds=6),
            ShotSpec(2, ["沈砚"], "沈砚", "近景", "过肩", "固定", "沈砚抱臂盯着对面", seconds=4),
            ShotSpec(3, ["黄琰"], "黄琰", "近景", "过肩", "缓推", "黄琰起身，抬手指向沈砚", seconds=5),
            ShotSpec(4, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "沈砚走向黄琰，一拳砸在案上", seconds=8),
        ]), blocking_from=edited)
        self.assertEqual(next(item.pose.preset for item in again.shot(2).overrides if item.name == "沈砚"), "think")
        self.assertEqual([clip.id for clip in again.timelines["3"].clips["黄琰"]], ["mine"])
        self.assertEqual(again.timelines["3"].duration_s, 9.0)
        self.assertEqual(_clips(again, 1, "黄琰")[0][0], "human-sit-enter-v1", "untouched shots are still planned")

    def test_shortening_a_shot_trims_the_planned_idle_but_not_a_persons_block(self):
        plan = _plan()
        shorter = apply_operations(plan, [{"op": "set_timeline", "shot_id": 1, "duration_s": 3}], solve=False)
        self.assertEqual(_clips(shorter, 1, "黄琰"), [("human-sit-enter-v1", 0.0, 1.3), ("human-sit-idle-v1", 1.3, 3.0)])
        with_mine = apply_operations(plan, [{"op": "set_timeline", "shot_id": 1, "clips": {"内侍": [{"id": "mine", "clip": "human-talk-v1", "start": 0, "end": 6}]}}], solve=False)
        with self.assertRaises(Exception) as refused:
            apply_operations(with_mine, [{"op": "set_timeline", "shot_id": 1, "duration_s": 3}], solve=False)
        self.assertIn("「内侍」动作", str(refused.exception))

    def test_performance_can_be_staged_on_a_plan_by_hand(self):
        plan = build_plan(_brief())
        bare = plan.model_copy(update={"timelines": {}, "shots": [shot.model_copy(update={"overrides": [
            ActorOverride(name=item.name, position=item.position, yaw_deg=item.yaw_deg, posture=item.posture, offstage=item.offstage, hold=item.hold, reason=item.reason)
            for item in shot.overrides
        ]}) for shot in plan.shots]})
        staged = performance.stage(bare, [ShotSpec(spec.shot_id, spec.subjects, spec.speaker, spec.size, spec.angle, spec.motion, spec.desc, seconds=5) for spec in _brief().shots])
        self.assertTrue(staged.timelines)
        self.assertIsInstance(staged.timelines["1"], ShotTimeline)
        self.assertTrue(all(isinstance(clip, ActionClip) for clips in staged.timelines["1"].clips.values() for clip in clips))
        self.assertIsInstance(StagePose(preset="walk"), StagePose)


if __name__ == "__main__":
    unittest.main()

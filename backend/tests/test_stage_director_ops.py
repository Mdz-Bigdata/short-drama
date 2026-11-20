# -*- coding: utf-8 -*-
"""The sidebar assistant's stage operations: committed edits as undoable steps, pinned snapshots, planning from the current stage, batch optimisation."""

import json
import unittest

from app.core.spatial_stage.operations import StageEditError
from app.service import spatial_stage_service as spatial
from app.service import stage_director_ops as ops
from app.service import stage_director_service as director
from tests import test_stage_director as base  # fixtures only; the module is not star-imported so its tests are not collected twice

SCENE = "E1S02"


def _move(name="内侍", z=-4.0):
    return {"op": "move_actor", "name": name, "position": [0, z]}


def _turn(z):
    return json.dumps({"reply": str(z), "operations": [_move(z=z)]})


class _Case(unittest.TestCase):
    def _service(self, *answers, offline=False):
        service = base.FakeService(base.FakeGateway(*answers, offline=offline))
        service.repo.task["assets"]["2_breakdown"] = {"scenes": [
            {"scene_id": SCENE, "content": "沈砚与黄琰隔着书案对峙。", "characters": ["沈砚", "黄琰", "内侍"]},
        ]}
        return service

    def _revision(self, service):
        return spatial.load_plan(service.repo.task, SCENE).revision

    def _position(self, service, name="内侍"):
        return next(a for a in spatial.load_plan(service.repo.task, SCENE).actors if a.name == name).position

    def _entry(self, service):
        return service.repo.task["assets"][director.ASSET_KEY][SCENE]


class CommitTest(_Case):
    def test_an_edit_is_one_step_with_a_chat_row_and_can_be_taken_back(self):
        service = self._service()
        start = self._revision(service)
        response = ops.commit_operations(service, "t1", SCENE, operations=[_move()], base_revision=start, label="内侍退后")
        self.assertEqual(response["changed"]["actors"], ["内侍"])
        self.assertEqual(response["plan"]["revision"], start + 1)
        self.assertTrue(response["snapshot_id"])
        self.assertIn("score", response["measured"])
        self.assertIsInstance(response["failing"], list)
        self.assertEqual(self._position(service), [0.0, -4.0])
        view = director.state(service, "t1", SCENE)
        self.assertEqual([row["role"] for row in view["chat"]], ["assistant"])
        self.assertEqual(view["chat"][0]["text"], "内侍退后")
        self.assertEqual(view["chat"][0]["snapshot_id"], response["snapshot_id"])
        self.assertEqual(view["chat"][0]["changed"]["actors"], ["内侍"])
        self.assertEqual([row["label"] for row in view["snapshots"]], ["内侍退后"])
        director.revert(service, "t1", SCENE, snapshot_id=response["snapshot_id"], base_revision=start + 1)
        self.assertNotEqual(self._position(service), [0.0, -4.0])

    def test_the_default_label_and_no_base_revision(self):
        service = self._service()
        response = ops.commit_operations(service, "t1", SCENE, operations=[_move()])
        self.assertTrue(response["changed"])
        self.assertEqual(director.state(service, "t1", SCENE)["chat"][0]["text"], "助手改动")
        self.assertEqual(director.state(service, "t1", SCENE)["snapshots"][0]["label"], "助手改动")

    def test_operations_that_change_nothing_write_no_step(self):
        service = self._service()
        actor = base._plan().actors[0]
        start = self._revision(service)
        response = ops.commit_operations(service, "t1", SCENE, operations=[{"op": "move_actor", "name": actor.name, "position": actor.position}])
        self.assertFalse(response["changed"])
        self.assertIsNone(response["snapshot_id"])
        self.assertIn("score", response["measured"])
        self.assertEqual(response["plan"]["revision"], start)
        self.assertEqual(self._revision(service), start)
        self.assertEqual(director.state(service, "t1", SCENE)["chat"], [])
        self.assertEqual(director.state(service, "t1", SCENE)["snapshots"], [])

    def test_a_stale_revision_and_a_bad_operation_are_refused(self):
        service = self._service()
        start = self._revision(service)
        with self.assertRaises(spatial.StageConflict):
            ops.commit_operations(service, "t1", SCENE, operations=[_move()], base_revision=start + 3)
        with self.assertRaises(StageEditError):
            ops.commit_operations(service, "t1", SCENE, operations=[{"op": "flying", "name": "内侍"}])
        self.assertEqual(self._revision(service), start)


class SnapshotTest(_Case):
    def test_a_pinned_snapshot_survives_the_services_trimming_and_is_listed_with_its_name(self):
        service = self._service(*[_turn(-2 - i) for i in range(6)])
        first = ops.commit_operations(service, "t1", SCENE, operations=[_move(z=-1.5)], label="第一步")
        pinned = ops.pin_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], name="开场站位")
        self.assertTrue(pinned["pinned"])
        self.assertEqual(pinned["snapshots"][0]["name"], "开场站位")
        for _ in range(6):
            director.chat(service, "t1", SCENE, message="退", base_revision=self._revision(service))
        self.assertEqual(len(director.state(service, "t1", SCENE)["snapshots"]), director.MAX_SNAPSHOTS)
        rows = ops.list_snapshots(service, "t1", SCENE)
        self.assertEqual(len(rows), director.MAX_SNAPSHOTS + 1)
        kept = next(row for row in rows if row["pinned"])
        self.assertEqual((kept["id"], kept["name"], kept["label"]), (first["snapshot_id"], "开场站位", "第一步"))
        self.assertEqual(set(rows[0]), {"id", "label", "name", "pinned", "revision", "at"})
        self.assertEqual(rows[0]["pinned"], False, "newest first: the latest turn, not the old pinned one")
        self.assertEqual(len(self._entry(service)["pinned_snapshots"]), 1)
        self.assertTrue(self._entry(service)["pinned_snapshots"][0]["pinned"])

    def test_restoring_a_pinned_snapshot_keeps_the_stage_it_replaces(self):
        service = self._service()
        start = self._revision(service)
        first = ops.commit_operations(service, "t1", SCENE, operations=[_move(z=-1.5)], label="第一步")
        ops.pin_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], name="开场站位")
        ops.commit_operations(service, "t1", SCENE, operations=[_move(z=-4)], label="第二步")
        self.assertEqual(self._position(service), [0.0, -4.0])
        response = ops.restore_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], base_revision=start + 2)
        self.assertEqual(response["plan"]["revision"], start + 3)
        self.assertEqual(response["restored"], first["snapshot_id"])
        self.assertNotEqual(self._position(service), [0.0, -4.0])
        self.assertNotEqual(self._position(service), [0.0, -1.5], "the pinned snapshot holds the stage before the first step")
        rows = ops.list_snapshots(service, "t1", SCENE)
        self.assertEqual(rows[0]["label"], "恢复「开场站位」")
        # The restore's own snapshot holds the stage it replaced, so it is the undo slot: no separate 撤销前 row on this path.
        self.assertEqual(response["kept_snapshot_id"], rows[0]["id"])
        self.assertEqual([row["label"] for row in rows].count("撤销前"), 0)
        self.assertEqual(len(rows), 3, "second step, pinned first step, and the restore itself")
        chat = director.state(service, "t1", SCENE)["chat"]
        self.assertIn("恢复「开场站位」", chat[-1]["text"])
        self.assertEqual(chat[-1]["changed"]["actors"], ["内侍"])
        # Redo: the kept step brings the replaced stage back.
        ops.restore_snapshot(service, "t1", SCENE, snapshot_id=response["kept_snapshot_id"])
        self.assertEqual(self._position(service), [0.0, -4.0])

    def test_a_refused_restore_leaves_no_stray_undo_slot(self):
        service = self._service()
        first = ops.commit_operations(service, "t1", SCENE, operations=[_move(z=-1.5)], label="第一步")
        ops.pin_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], name="开场站位")
        ops.commit_operations(service, "t1", SCENE, operations=[_move(z=-4)], label="第二步")
        before = [(row["id"], row["label"]) for row in ops.list_snapshots(service, "t1", SCENE)]
        revision = self._revision(service)
        service._has_running_generation = lambda task: True
        with self.assertRaises(spatial.StageConflict):
            ops.restore_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"])
        service._has_running_generation = lambda task: False
        with self.assertRaises(spatial.StageConflict):
            ops.restore_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], base_revision=revision - 1)
        self.assertEqual([(row["id"], row["label"]) for row in ops.list_snapshots(service, "t1", SCENE)], before)
        self.assertEqual(self._revision(service), revision)
        self.assertEqual(self._position(service), [0.0, -4.0])

    def test_restoring_a_service_snapshot_delegates_to_revert_and_can_be_redone(self):
        service = self._service()
        start = self._revision(service)
        first = ops.commit_operations(service, "t1", SCENE, operations=[_move(z=-4)], label="退后")
        with self.assertRaises(spatial.StageConflict):
            ops.restore_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], base_revision=start + 7)
        response = ops.restore_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], base_revision=start + 1)
        self.assertEqual(response["plan"]["revision"], start + 2)
        self.assertNotEqual(self._position(service), [0.0, -4.0])
        self.assertIn("已撤销「退后」", director.state(service, "t1", SCENE)["chat"][-1]["text"])
        rows = ops.list_snapshots(service, "t1", SCENE)
        self.assertEqual([row["label"] for row in rows], ["撤销前"])
        self.assertEqual(rows[0]["id"], response["kept_snapshot_id"])
        ops.restore_snapshot(service, "t1", SCENE, snapshot_id=response["kept_snapshot_id"])
        self.assertEqual(self._position(service), [0.0, -4.0])

    def test_a_full_undo_list_can_still_restore_its_oldest_step(self):
        service = self._service(*[_turn(-2 - i) for i in range(director.MAX_SNAPSHOTS)])
        original = self._position(service)
        for _ in range(director.MAX_SNAPSHOTS):
            director.chat(service, "t1", SCENE, message="退", base_revision=self._revision(service))
        self.assertNotEqual(self._position(service), original)
        oldest = director.state(service, "t1", SCENE)["snapshots"][0]["id"]
        ops.restore_snapshot(service, "t1", SCENE, snapshot_id=oldest)
        self.assertEqual(self._position(service), original, "the oldest snapshot holds the stage before the first turn")

    def test_unpin_and_the_pin_limit(self):
        service = self._service()
        first = ops.commit_operations(service, "t1", SCENE, operations=[_move(z=-1.5)])
        ops.pin_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], name="A")
        renamed = ops.pin_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], name="B")
        self.assertEqual([row["name"] for row in renamed["snapshots"] if row["pinned"]], ["B"])
        self.assertEqual(len(self._entry(service)["pinned_snapshots"]), 1)
        gone = ops.pin_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], pinned=False)
        self.assertFalse(gone["pinned"])
        self.assertEqual([row["pinned"] for row in gone["snapshots"]], [False])
        with self.assertRaises(LookupError):
            ops.pin_snapshot(service, "t1", SCENE, snapshot_id="nope")
        with self.assertRaises(LookupError):
            ops.restore_snapshot(service, "t1", SCENE, snapshot_id="nope")
        self._entry(service)["pinned_snapshots"] = [{"id": f"p{i}", "name": str(i), "label": "", "at": "", "revision": 1, "plan": {}, "pinned": True} for i in range(ops.MAX_PINNED)]
        with self.assertRaisesRegex(ValueError, "最多固定"):
            ops.pin_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], name="C")


class RestoreEndpointTest(_Case):
    def test_the_sidebar_undo_endpoint_takes_a_step_back_without_a_model(self):
        from unittest.mock import patch
        from app.api import drama_api

        service = self._service()
        step = ops.commit_operations(service, "t1", SCENE, operations=[_move()], label="内侍退后")
        self.assertEqual(self._position(service), [0.0, -4.0])
        request = drama_api.StageRestoreRequest(snapshot_id=step["snapshot_id"])
        with patch.object(drama_api, "service", service):
            response = drama_api.restore_stage_snapshot("t1", SCENE, request, current_user={"user_id": "u1"})
        self.assertNotEqual(self._position(service), [0.0, -4.0])
        self.assertEqual(response["restored"], step["snapshot_id"])
        self.assertEqual(service.gateway.llm.prompts, [], "undo never calls the model")


class PlanFromCurrentTest(_Case):
    def test_candidates_start_from_the_edited_stage_and_can_be_adopted(self):
        service = self._service(base._candidate_reply(), json.dumps({"operations": []}))
        ops.commit_operations(service, "t1", SCENE, operations=[{"op": "add_landmark", "name": "屏风", "kit": "desk", "position": [2, -2]}])
        revision = self._revision(service)
        result = ops.plan_from_current(service, "t1", SCENE, base_revision=revision, count=1)
        self.assertTrue(result["used_model"])
        self.assertIn("当前舞台", result["note"])
        self.assertEqual({item["id"] for item in result["candidates"]}, {"model-1", "rules"})
        for item in result["candidates"]:
            self.assertIn("屏风", [piece["name"] for piece in item["plan"]["landmarks"]], item["id"])
        self.assertIn("屏风", service.gateway.llm.prompts[0][1], "the model is shown the current stage as its baseline")
        self.assertEqual([item["id"] for item in director.state(service, "t1", SCENE)["candidates"]], [item["id"] for item in result["candidates"]])
        adopted = director.adopt_candidate(service, "t1", SCENE, candidate_id="model-1", base_revision=revision)
        self.assertEqual(adopted["plan"]["revision"], revision + 1)
        self.assertEqual(director.state(service, "t1", SCENE)["candidates"], [])

    def test_a_stale_revision_is_refused_before_any_model_call(self):
        service = self._service("{}")
        with self.assertRaises(spatial.StageConflict):
            ops.plan_from_current(service, "t1", SCENE, base_revision=self._revision(service) + 1)
        self.assertEqual(service.gateway.llm.prompts, [])

    def test_without_a_model_only_the_rules_candidate_remains(self):
        service = self._service()
        result = ops.plan_from_current(service, "t1", SCENE, base_revision=self._revision(service))
        self.assertFalse(result["used_model"])
        self.assertEqual([item["id"] for item in result["candidates"]], ["rules"])
        self.assertIn("只有规则方案", result["note"])


class OptimizeScenesTest(_Case):
    def test_every_scene_of_the_episode_is_optimised_in_turn_and_model_calls_are_counted(self):
        service = self._service(json.dumps({"reply": "退后", "operations": [_move(z=-4)], "done": True}))
        start = self._revision(service)
        result = ops.optimize_scenes(service, "t1", episode=1)
        self.assertEqual(result["scenes"], 1)
        self.assertEqual(result["calls"], 1)
        row = result["results"][SCENE]
        self.assertEqual(set(row), {"changed", "before", "after", "errors", "snapshot_id", "stale_clips"})
        self.assertIsInstance(row["before"], float)
        self.assertIsInstance(row["after"], float)
        self.assertGreaterEqual(row["after"], row["before"], "a result that scores lower is not kept")
        self.assertEqual(row["errors"], [])
        # The model's move is kept only when it scores at least as well as the rule polish; either way it is one turn.
        self.assertEqual(len(service.gateway.llm.prompts), 1)
        self.assertEqual(self._revision(service), start + (1 if row["changed"] else 0))
        self.assertEqual(bool(row["snapshot_id"]), row["changed"])
        self.assertEqual([item["role"] for item in director.state(service, "t1", SCENE)["chat"]], ["user", "assistant"])

    def test_a_scene_that_cannot_load_is_recorded_and_the_rest_continue(self):
        service = self._service(json.dumps({"reply": "退后", "operations": [_move(z=-4)], "done": True}))
        result = ops.optimize_scenes(service, "t1", scene_ids=["E9S99", SCENE])
        self.assertEqual(result["scenes"], 2)
        self.assertEqual(list(result["results"]), ["E9S99", SCENE])
        self.assertFalse(result["results"]["E9S99"]["changed"])
        self.assertIsNone(result["results"]["E9S99"]["snapshot_id"])
        self.assertIn("E9S99", result["results"]["E9S99"]["errors"][0])
        self.assertEqual(result["results"][SCENE]["errors"], [])
        self.assertEqual(result["calls"], 1)

    def test_without_a_model_nothing_is_counted_as_a_call(self):
        service = self._service(offline=True)
        result = ops.optimize_scenes(service, "t1")
        self.assertEqual(result["scenes"], 1)
        self.assertEqual(result["calls"], 0)
        self.assertIn(SCENE, result["results"])

    def test_an_episode_with_no_scenes_does_nothing(self):
        service = self._service()
        self.assertEqual(ops.optimize_scenes(service, "t1", episode=7), {"results": {}, "scenes": 0, "calls": 0, "stale_clips": 0})

    def test_a_running_task_is_refused_before_any_model_call(self):
        service = self._service(json.dumps({"reply": "退后", "operations": [_move(z=-4)], "done": True}))
        service._has_running_generation = lambda task: True
        with self.assertRaisesRegex(spatial.StageConflict, "正在执行阶段"):
            ops.optimize_scenes(service, "t1", scene_ids=[SCENE, SCENE])
        self.assertEqual(service.gateway.llm.prompts, [], "nothing is asked of the model when no commit can land")
        # A stage that starts running mid-batch stops the batch instead of burning the remaining scenes' calls.
        service = self._service(*[json.dumps({"reply": "退后", "operations": [_move(z=-4)], "done": True})] * 3)
        seen = []

        def running(task):
            seen.append(1)
            return len(seen) > 2   # idle for the batch check and the first scene, then busy

        service._has_running_generation = running
        with self.assertRaises(spatial.StageConflict):
            ops.optimize_scenes(service, "t1", scene_ids=[SCENE, SCENE, SCENE])
        self.assertLessEqual(len(service.gateway.llm.prompts), 1)

    def test_the_batch_is_capped_and_the_scope_is_resolved_the_same_way_for_the_quote(self):
        service = self._service()
        scenes = [{"scene_id": f"E1S{i:02d}", "content": "", "characters": []} for i in range(1, ops.MAX_BATCH + 2)]
        service.repo.task["assets"]["2_breakdown"] = {"scenes": scenes}
        with self.assertRaisesRegex(ValueError, f"有 {ops.MAX_BATCH + 1} 场.*最多优化 {ops.MAX_BATCH} 场"):
            ops.batch_scope(service.repo.task, episode=1)
        with self.assertRaisesRegex(ValueError, "全剧"):
            ops.optimize_scenes(service, "t1")
        self.assertEqual(service.gateway.llm.prompts, [])
        self.assertEqual(ops.batch_scope(service.repo.task, scene_ids=["E1S02", " ", "E1S03"]), ["E1S02", "E1S03"])
        self.assertEqual(len(ops.batch_scope(service.repo.task, scene_ids=[SCENE] * ops.MAX_BATCH)), ops.MAX_BATCH)


def _clips(service):
    """两场的分镜和已出的片段：本场一段带场号、一段按镜头编号表、一段没有场号的旧片段；另一场各一段同形的。"""
    service.repo.task["assets"]["4"] = [
        {"shot_id": 1, "scene_id": SCENE, "characters": ["沈砚"]}, {"shot_id": 2, "scene_id": SCENE, "characters": ["黄琰"]},
        {"shot_id": 7, "scene_id": SCENE, "characters": ["内侍"]},
        {"shot_id": 1, "scene_id": "E1S01", "characters": ["沈砚"]}, {"shot_id": 9, "scene_id": "E1S01", "characters": ["沈砚"]},
    ]
    service.repo.task["assets"]["5"] = [
        {"shot_id": 1, "scene_id": SCENE, "video_url": "a.mp4"},
        {"shot_uids": [100202], "video_url": "b.mp4"},            # E1S02 第 2 镜的编号，没有写场号
        {"shot_id": 7, "video_url": "c.mp4"},                      # 旧片段：只有镜号，对到本场第 7 镜
        {"shot_id": 1, "scene_id": "E1S01", "video_url": "d.mp4"},
        {"shot_uids": [100109], "video_url": "e.mp4"},
        {"shot_id": 9, "video_url": "f.mp4", "stale": False},      # 旧片段，对到另一场
        "not a clip",
    ]


def _stale(service):
    return [bool(clip.get("stale")) for clip in service.repo.task["assets"]["5"] if isinstance(clip, dict)]


class StaleClipsTest(_Case):
    def test_a_commit_marks_only_this_scenes_clips_with_the_assistant_reason(self):
        service = self._service()
        _clips(service)
        response = ops.commit_operations(service, "t1", SCENE, operations=[_move()], label="内侍退后")
        self.assertEqual(response["stale_clips"], 3)
        self.assertEqual(_stale(service), [True, True, True, False, False, False])
        marked = [clip for clip in service.repo.task["assets"]["5"] if isinstance(clip, dict) and clip.get("stale")]
        self.assertEqual({clip["stale_reason"] for clip in marked}, {ops.STALE_CLIP_REASON})
        self.assertIn("第 5 阶段", ops.STALE_CLIP_REASON)
        self.assertNotIn("stale_reason", service.repo.task["assets"]["5"][3], "the other scene's clips are untouched")

    def test_an_edit_that_changes_nothing_marks_nothing(self):
        service = self._service()
        _clips(service)
        actor = base._plan().actors[0]
        response = ops.commit_operations(service, "t1", SCENE, operations=[{"op": "move_actor", "name": actor.name, "position": actor.position}])
        self.assertEqual((response["changed"], response["stale_clips"]), (False, 0))
        self.assertEqual(_stale(service), [False] * 6)

    def test_without_clips_or_with_an_unknown_scene_nothing_is_counted(self):
        service = self._service()
        self.assertEqual(ops.mark_scene_clips_stale(service.repo.task, SCENE), 0)
        _clips(service)
        self.assertEqual(ops.mark_scene_clips_stale(service.repo.task, "E3S01"), 0)
        self.assertEqual(_stale(service), [False] * 6)
        self.assertEqual(ops.mark_scene_clips_stale(service.repo.task, SCENE, "自定义原因"), 3)
        self.assertEqual(service.repo.task["assets"]["5"][0]["stale_reason"], "自定义原因")

    def test_both_restore_paths_mark_the_scenes_clips(self):
        service = self._service()
        first = ops.commit_operations(service, "t1", SCENE, operations=[_move(z=-1.5)], label="第一步")
        ops.pin_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"], name="开场站位")
        second = ops.commit_operations(service, "t1", SCENE, operations=[_move(z=-4)], label="第二步")
        _clips(service)
        # 服务层快照：走 revert，再在「撤销前」那次写里标过期。
        response = ops.restore_snapshot(service, "t1", SCENE, snapshot_id=second["snapshot_id"])
        self.assertEqual(response["stale_clips"], 3)
        self.assertEqual(_stale(service), [True, True, True, False, False, False])
        for clip in service.repo.task["assets"]["5"][:3]:
            clip["stale"] = False
            clip.pop("stale_reason", None)
        # 固定快照：走 _commit，紧跟着标过期。
        response = ops.restore_snapshot(service, "t1", SCENE, snapshot_id=first["snapshot_id"])
        self.assertEqual(response["restored"], first["snapshot_id"])
        self.assertEqual(response["stale_clips"], 3)
        self.assertEqual(_stale(service), [True, True, True, False, False, False])
        self.assertEqual(service.repo.task["assets"]["5"][2]["stale_reason"], ops.STALE_CLIP_REASON)

    def test_a_batch_optimisation_reports_the_clips_each_changed_scene_made_stale(self):
        service = self._service(json.dumps({"reply": "退后", "operations": [_move(z=-4)], "done": True}))
        _clips(service)
        result = ops.optimize_scenes(service, "t1", scene_ids=["E9S99", SCENE])
        row = result["results"][SCENE]
        self.assertEqual(row["stale_clips"], 3 if row["changed"] else 0)
        self.assertEqual(result["results"]["E9S99"]["stale_clips"], 0)
        self.assertEqual(result["stale_clips"], row["stale_clips"])
        self.assertEqual(_stale(service), [row["changed"]] * 3 + [False] * 3)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""The model-first director of a stage: built-in models, scoring, planning, conversation, undo and the GLB export."""

import json
import struct
import unittest
from copy import deepcopy
from threading import Lock

from app.core.blender_previz.from_plan import build_spec
from app.core.spatial_stage import SceneBrief, ShotSpec, blockout, build_plan, director_ai, glb, model_kit, paths, scoring
from app.core.spatial_stage.director_ai import Scope
from app.core.spatial_stage.operations import StageEditError, apply_operations
from app.service import spatial_stage_service as spatial
from app.service import stage_director_service as director


def _brief() -> SceneBrief:
    return SceneBrief(
        scene_id="E1S02", location="文思阁 / 夜 / 内景",
        text="沈砚与黄琰隔着书案对峙，内侍站在后面。",
        characters=["沈砚", "黄琰", "内侍"], props=[],
        shots=[
            ShotSpec(1, ["沈砚", "黄琰", "内侍"], "", "全景", "平视", "固定", "三人在文思阁内"),
            ShotSpec(2, ["沈砚"], "沈砚", "近景", "过肩", "固定", "沈砚盯着对面"),
            ShotSpec(3, ["沈砚", "黄琰"], "", "中景", "平视", "固定", "两人对视"),
        ],
    )


def _plan():
    return build_plan(_brief())


class ModelKitTest(unittest.TestCase):
    def test_every_kit_builds_within_the_limits_and_stays_on_the_ground(self):
        for kit in model_kit.KITS:
            found, parts, size = model_kit.build_kit(kit.id)
            self.assertIs(found, kit)
            for built, nominal in zip(size, kit.size):
                self.assertAlmostEqual(built, nominal, delta=max(0.35, nominal * 0.3), msg=kit.id)
            self.assertTrue(1 <= len(parts) <= 64, kit.id)
            width, depth, height = size
            low = min(
                part.center[1] * height
                - model_kit._rotated_half_extents([part.size[0] * width, part.size[1] * depth, part.size[2] * height], part.rotation)[1]
                for part in parts
            )
            self.assertAlmostEqual(low, 0.0, delta=0.005, msg=kit.id)

    def test_a_kit_is_found_by_chinese_name_alias_and_phrase(self):
        self.assertEqual(model_kit.find_kit("书案").id, "desk")
        self.assertEqual(model_kit.find_kit("SEDAN").id, "sedan")
        self.assertEqual(model_kit.find_kit("一辆老式马车").id, "carriage")
        self.assertIsNone(model_kit.find_kit("量子计算机"))

    def test_a_models_parts_are_fitted_and_a_bad_row_costs_only_that_row(self):
        parts, size, dropped = model_kit.read_parts([
            {"shape": "box", "center": [0, 0.5, 0], "size": [2, 1, 1]},
            {"shape": "cylinder", "center": [0, 1.5, 0], "size": [0.4, 0.4, 1]},
            {"shape": "teapot", "center": [0, 0, 0], "size": [1, 1, 1]},
            {"center": "nowhere"},
        ])
        self.assertEqual(dropped, 2)
        self.assertEqual(size, [2.0, 1.0, 2.0])
        self.assertEqual([part.shape for part in parts], ["box", "cylinder"])
        with self.assertRaises(model_kit.ModelKitError):
            model_kit.read_parts([{"bad": 1}])

    def test_add_landmark_builds_a_kit_and_undo_can_put_it_back_exactly(self):
        plan = apply_operations(_plan(), [{"op": "add_landmark", "name": "车", "kit": "轿车", "position": [3, 3], "yaw_deg": 30}])
        piece = next(item for item in plan.landmarks if item.name == "车")
        self.assertEqual(piece.kit, "sedan")
        for built, nominal in zip(piece.size, (1.8, 4.5, 1.45)):
            self.assertAlmostEqual(built, nominal, delta=0.05)
        self.assertGreater(len(piece.parts), 3)
        gone = apply_operations(plan, [{"op": "remove_landmark", "name": "车"}])
        back = apply_operations(gone, [{
            "op": "add_landmark", "name": "车", "position": piece.position, "size": piece.size, "yaw_deg": piece.yaw_deg, "kind": piece.kind,
            "kit": piece.kit, "fitted_parts": [part.model_dump() for part in piece.parts],
        }])
        again = next(item for item in back.landmarks if item.name == "车")
        self.assertEqual(again.parts, piece.parts)

    def test_an_unknown_kit_is_refused_in_words_and_an_old_plan_still_loads(self):
        with self.assertRaisesRegex(StageEditError, "模型库里没有"):
            apply_operations(_plan(), [{"op": "add_landmark", "name": "x", "kit": "量子计算机", "position": [0, 0]}])
        stored = _plan().model_dump(mode="json")
        for piece in stored["landmarks"]:
            piece.pop("parts"), piece.pop("kit")
        stored.pop("planner"), stored.pop("planner_note")
        self.assertEqual(type(_plan()).model_validate(stored).planner, "rules")

    def test_a_stack_of_large_models_is_refused_at_the_stage_budget(self):
        plan = _plan()
        operations = [{
            "op": "add_landmark", "name": f"楼{index}", "position": [index * 10, 40],
            "parts": [{"shape": "box", "center": [slot, 0.5, 0], "size": [0.5, 0.5, 1]} for slot in range(60)],
        } for index in range(41)]
        with self.assertRaisesRegex(StageEditError, "体块总数"):
            apply_operations(plan, operations)

    def test_a_text_blockout_can_name_library_models(self):
        reply = blockout.parse_blockout(json.dumps({"pieces": [
            {"name": "主桌", "kit": "desk", "center": [0, 0]},
            {"name": "北墙", "shape": "box", "center": [0, -3], "size": [8, 0.2, 3]},
            {"name": "怪东西", "kit": "量子计算机", "center": [1, 1], "size": [1, 1, 1]},
        ]}))
        by_name = {piece.name: piece for piece in reply.pieces}
        self.assertEqual(by_name["主桌"].kit, "desk")
        self.assertEqual(list(by_name["主桌"].size), [1.3, 0.65, 0.75])
        self.assertEqual(by_name["怪东西"].kit, "")
        plan = apply_operations(_plan(), [{"op": "apply_blockout", "pieces": [piece.model_dump(mode="json") for piece in reply.pieces]}])
        placed = {piece.name: piece for piece in plan.landmarks if piece.origin == "blockout"}
        self.assertTrue(placed["主桌"].parts)
        self.assertEqual(placed["北墙"].parts, [])
        for built, nominal in zip(placed["主桌"].size, (1.3, 0.65, 0.75)):
            self.assertAlmostEqual(built, nominal, delta=0.03)

    def test_the_text_prompt_offers_the_library(self):
        system, user = blockout.text_prompt("一间古代书房", 6)
        self.assertIn("模型库", user)
        self.assertIn("desk(书桌", user)
        self.assertIn("一间古代书房", user)
        self.assertIn("6", user)
        self.assertTrue(system)


class ScoringTest(unittest.TestCase):
    def test_a_person_inside_a_wall_and_a_wall_across_the_lens_both_cost_points(self):
        plan = _plan()
        clean = scoring.score_plan(plan)
        actor = plan.actors[0]
        wall = apply_operations(plan, [{"op": "add_landmark", "name": "墙", "shape": "box", "position": list(actor.position), "size": [2, 2, 3], "kind": "architecture"}])
        measured = scoring.score_plan(wall)
        self.assertEqual(measured["standing"], 1)
        self.assertLess(measured["score"], clean["score"])
        self.assertTrue(any("里面" in note for note in measured["notes"]))

    def test_a_piece_between_lens_and_subject_blocks_it_but_a_rug_does_not(self):
        plan = _plan()
        shot = plan.shots[0]
        camera = next(item for item in plan.cameras if item.id == shot.camera_id)
        middle = [camera.position[0] * 0.6, camera.position[2] * 0.6]
        wall = apply_operations(plan, [{"op": "add_landmark", "name": "隔墙", "position": middle, "size": [8, 0.3, 3], "kind": "architecture"}])
        self.assertTrue(any("隔墙" in note for note in scoring.score_plan(wall)["notes"]))
        rug = apply_operations(plan, [{"op": "add_landmark", "name": "地毯", "position": middle, "size": [8, 3, 0.02]}])
        self.assertFalse(any("地毯" in note for note in scoring.score_plan(rug)["notes"]))

    def test_best_camera_steps_around_a_wall_and_keeps_the_axis_side(self):
        plan = _plan()
        shot = plan.shots[1]
        camera = next(item for item in plan.cameras if item.id == shot.camera_id)
        subject = next(item for item in plan.actors if item.name == "沈砚")
        between = [(camera.position[0] + subject.position[0]) / 2, (camera.position[2] + subject.position[1]) / 2]
        blocked = apply_operations(plan, [{"op": "add_landmark", "name": "柱", "shape": "cylinder", "position": between, "size": [0.4, 0.4, 3]}])
        before = scoring.score_shot(blocked, blocked.shots[1])[0]
        better = apply_operations(blocked, [{"op": "best_camera", "shot_id": 2}])
        after = scoring.score_shot(better, better.shots[1])[0]
        self.assertGreater(after, before)
        self.assertNotIn("spatial_axis_consistent", [check.code for check in better.checks if not check.passed])

    def test_best_camera_leaves_a_lens_alone_when_nothing_is_really_better_or_it_has_keys(self):
        plan = _plan()
        polished = apply_operations(plan, [{"op": "best_camera"}])
        for _ in range(2):
            polished = apply_operations(polished, [{"op": "best_camera"}])
        stable = apply_operations(polished, [{"op": "best_camera"}])
        self.assertEqual([c.position for c in stable.cameras], [c.position for c in polished.cameras])
        keyed = apply_operations(plan, [{"op": "apply_camera_move", "shot_id": 1, "preset": "push"}])
        moved = apply_operations(keyed, [{"op": "best_camera", "shot_id": 1}])
        self.assertEqual(moved.cameras[0].position, keyed.cameras[0].position)

    def test_alternates_become_candidate_lenses(self):
        plan = apply_operations(_plan(), [{"op": "best_camera", "shot_id": 1, "alternates": 2}])
        self.assertEqual(len(plan.shots[0].alt_camera_ids), 2)


class RouteTest(unittest.TestCase):
    def test_a_route_goes_around_a_rotated_wall_and_a_person(self):
        wall = (0.0, 0.0, 3.0, 0.2, 30.0)
        route = paths.find_route((-1.0, -3.0), (1.0, 3.0), [wall], [(0.0, 3.0)], 0.3)
        self.assertGreater(len(route), 2)
        grown = [(wall[0], wall[1], wall[2] + 0.29, wall[3] + 0.29, wall[4])]
        for a, b in zip(route, route[1:]):
            self.assertTrue(paths._clear_of_footprints(a, b, grown), (a, b))

    def test_a_goal_inside_a_piece_is_refused(self):
        with self.assertRaisesRegex(paths.PathError, "占"):
            paths.find_route((-5.0, 0.0), (0.0, 0.0), [(0.0, 0.0, 1.0, 1.0, 0.0)])

    def test_auto_route_lays_the_keys_and_walks_around_the_set(self):
        plan = apply_operations(_plan(), [{"op": "add_landmark", "name": "屏", "position": [2, 2], "size": [6, 0.3, 2], "kind": "architecture"}])
        actor = next(item for item in plan.actors if item.name == "沈砚")
        routed = apply_operations(plan, [{"op": "auto_route", "shot_id": 1, "name": "沈砚", "to": [2, 5]}])
        keys = routed.timelines["1"].actors["沈砚"]
        self.assertEqual(keys[0].position, actor.position)
        self.assertEqual(keys[-1].position, [2.0, 5.0])
        wall = next(item for item in routed.landmarks if item.name == "屏")
        self.assertFalse(any(scoring.inside_piece(key.position, wall) for key in keys))


class FakeLLM:
    """Answers from a queue; thread-safe, since candidates are asked for in parallel."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []
        self.lock = Lock()

    def __call__(self, system, user, max_tokens):
        with self.lock:
            self.prompts.append((system, user, max_tokens))
            return self.answers.pop(0) if self.answers else None


def _candidate_reply(name="长案"):
    return json.dumps({
        "title": "隔案对峙", "rationale": "书案把两人隔开，内侍退到纵深。",
        "operations": [
            {"op": "add_landmark", "name": name, "kit": "desk", "position": [0, -1.5]},
            {"op": "move_actor", "name": "内侍", "position": [0, -4], "yaw_deg": 0},
            {"op": "set_pose", "name": "沈砚", "preset": "cross-arms"},
            {"op": "solve_camera", "shot_id": 2, "size": "近景"},
            {"op": "flying", "name": "内侍"},
        ],
    }, ensure_ascii=False)


class PlanningTest(unittest.TestCase):
    def test_a_candidate_carries_the_set_the_pose_and_the_errors_of_what_failed(self):
        llm = FakeLLM(_candidate_reply(), json.dumps({"operations": []}))
        candidate = director_ai.build_candidate(_plan(), "剧本", director_ai.STRATEGIES[0], llm, 0)
        self.assertEqual(candidate.source, "model")
        self.assertEqual(candidate.plan.planner, "model")
        self.assertEqual(candidate.title, "隔案对峙")
        self.assertTrue(any(piece.kit == "desk" for piece in candidate.plan.landmarks))
        posed = next(actor for actor in candidate.plan.actors if actor.name == "沈砚")
        self.assertEqual(posed.pose.preset, "cross-arms")
        self.assertEqual(posed.figure, "mannequin", "a pose on a stand-in would draw nothing")
        self.assertTrue(any("flying" in item for item in llm.prompts[1][1].splitlines()), "the failed op goes back to the model")
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("模型库", llm.prompts[0][0])
        self.assertIn("稳住关系", llm.prompts[0][1])

    def test_prose_or_nothing_from_a_model_is_no_candidate(self):
        self.assertIsNone(director_ai.build_candidate(_plan(), "剧本", director_ai.STRATEGIES[0], FakeLLM("这场戏很精彩。"), 0))
        self.assertIsNone(director_ai.build_candidate(_plan(), "剧本", director_ai.STRATEGIES[0], FakeLLM(None), 0))
        wrong = json.dumps({"operations": [{"op": "flying"}]})
        self.assertIsNone(director_ai.build_candidate(_plan(), "剧本", director_ai.STRATEGIES[0], FakeLLM(wrong), 0))

    def test_a_truncated_reply_keeps_the_operations_it_finished(self):
        text = '{"title":"x","operations":[{"op":"move_actor","name":"内侍","position":[0,-4]},{"op":"move_actor","name":"沈'
        reply = director_ai.read_reply(text)
        self.assertEqual(len(reply["operations"]), 1)
        self.assertFalse(reply["done"])

    def test_ranking_puts_a_passing_model_plan_above_rules_but_a_failing_one_below(self):
        def candidate(source, score, errors=0):
            return director_ai.Candidate(id=source, title="", rationale="", source=source, plan=_plan(), measured={"score": score, "errors": errors, "standing": 0})

        ranked = director_ai.rank([candidate("rules", 95), candidate("model", 80)])
        self.assertEqual(ranked[0].source, "model")
        ranked = director_ai.rank([candidate("model", 90, errors=1), candidate("rules", 70)])
        self.assertEqual(ranked[0].source, "rules")

    def test_a_plan_whose_operations_mostly_failed_ranks_below_one_that_was_carried_out(self):
        def candidate(name, score, failed):
            return director_ai.Candidate(
                id=name, title="", rationale="", source="model", plan=_plan(),
                measured={"score": score, "errors": 0, "standing": 0}, errors=["x"] * failed,
            )

        self.assertEqual(director_ai.rank([candidate("hollow", 98.5, 2), candidate("real", 98.4, 0)])[0].id, "real")


class TurnTest(unittest.TestCase):
    def test_the_model_reads_back_a_failure_and_fixes_it_within_the_turn(self):
        first = json.dumps({"reply": "挪一下", "operations": [{"op": "move_actor", "name": "没这人", "position": [0, 0]}], "done": True})
        second = json.dumps({"reply": "内侍退后了", "operations": [{"op": "move_actor", "name": "内侍", "position": [0, -4]}], "done": True})
        llm = FakeLLM(first, second)
        outcome = director_ai.run_turn(_plan(), "内侍退后一点", llm)
        self.assertEqual(outcome["rounds"], 2)
        self.assertEqual(outcome["reply"], "内侍退后了")
        self.assertEqual(outcome["errors"], [])
        self.assertEqual(next(a for a in outcome["plan"].actors if a.name == "内侍").position, [0.0, -4.0])
        self.assertIn("失败的操作", llm.prompts[1][1])

    def test_a_question_changes_nothing(self):
        plan = _plan()
        outcome = director_ai.run_turn(plan, "现在谁在左边？", FakeLLM(json.dumps({"reply": "沈砚在左", "operations": []})))
        self.assertIs(outcome["plan"], plan)
        self.assertEqual(outcome["applied"], [])

    def test_no_answer_raises_and_prose_is_a_reply(self):
        with self.assertRaises(director_ai.DirectorAIError):
            director_ai.run_turn(_plan(), "往左", FakeLLM(None))
        self.assertEqual(director_ai.run_turn(_plan(), "你好", FakeLLM("你好，有什么要调整？"))["reply"], "你好，有什么要调整？")

    def test_a_scope_refuses_what_was_not_selected_and_tells_the_model(self):
        llm = FakeLLM(
            json.dumps({"reply": "好", "operations": [
                {"op": "move_actor", "name": "黄琰", "position": [3, 3]},
                {"op": "move_actor", "name": "沈砚", "position": [-2, 0]},
            ]}),
            json.dumps({"reply": "只动了沈砚", "operations": []}),
        )
        outcome = director_ai.run_turn(_plan(), "调整", llm, scope=Scope(names=("沈砚",)))
        moved = {actor.name: actor.position for actor in outcome["plan"].actors}
        self.assertEqual(moved["沈砚"], [-2.0, 0.0])
        self.assertNotEqual(moved["黄琰"], [3.0, 3.0])
        self.assertIn("不在选中范围内", llm.prompts[1][1])
        self.assertIn("只选中了", llm.prompts[0][1])

    def test_a_shot_scope_refuses_another_shots_lens(self):
        plan = _plan()
        scope = Scope(shot_id=2)
        self.assertTrue(director_ai.out_of_scope({"op": "frame_shot", "shot_id": 3, "size": "全景"}, scope, plan))
        self.assertFalse(director_ai.out_of_scope({"op": "frame_shot", "shot_id": 2, "size": "全景"}, scope, plan))
        other = plan.shots[2].camera_id
        self.assertTrue(director_ai.out_of_scope({"op": "move_camera", "camera_id": other}, scope, plan))

    def test_optimise_throws_away_a_model_edit_that_scores_lower(self):
        plan = _plan()
        worse = json.dumps({"reply": "挡一下", "operations": [
            {"op": "add_landmark", "name": "巨墙", "position": list(plan.actors[0].position), "size": [20, 3, 5]},
        ]})
        outcome = director_ai.optimize(plan, FakeLLM(worse, json.dumps({"operations": []})))
        self.assertFalse(any(piece.name == "巨墙" for piece in outcome["plan"].landmarks))
        self.assertGreaterEqual(outcome["after"]["score"], outcome["before"]["score"])
        self.assertIn("放弃", outcome["reply"])

    def test_optimise_without_a_model_still_uses_the_rules(self):
        plan = apply_operations(_plan(), [{"op": "move_actor", "name": "黄琰", "position": list(_plan().actors[0].position)}])
        outcome = director_ai.optimize(plan, None)
        self.assertFalse(outcome["used_model"])
        self.assertGreater(outcome["after"]["score"], outcome["before"]["score"])
        self.assertEqual(outcome["after"]["errors"], 0)

    def test_craft_notes_come_from_the_vendored_skills(self):
        notes = director_ai.craft_notes("夜里的城门，一辆马车")
        self.assertIn("set-dressing", notes)
        self.assertIn("camera-cinematography", notes)
        self.assertIn("vehicle-artist", notes)
        self.assertLessEqual(len(notes), director_ai._SKILL_BUDGET + 400)


class ModelReplyTest(unittest.TestCase):
    def test_a_written_model_is_fitted_and_a_library_answer_is_built(self):
        written = director_ai.read_model_reply(json.dumps({"name": "鼎", "kind": "prop", "parts": [
            {"shape": "cylinder", "center": [0, 0.5, 0], "size": [0.8, 0.8, 0.6]},
            {"shape": "cylinder", "center": [0, 0.1, 0.3], "size": [0.08, 0.08, 0.2]},
        ]}), "一只青铜鼎")
        self.assertEqual(written["name"], "鼎")
        self.assertEqual(len(written["parts"]), 2)
        library = director_ai.read_model_reply(json.dumps({"name": "椅", "kit": "chair"}), "椅子")
        self.assertEqual(library["kit"], "chair")
        with self.assertRaises(director_ai.DirectorAIError):
            director_ai.read_model_reply("没有 JSON", "x")


class PipelineTest(unittest.TestCase):
    """The storyboard stage asks the model for each scene's blocking before its table is written."""

    def _generate(self, config=None, *, reachable=True, answer=None):
        from unittest.mock import patch

        from app.service.drama_service import DramaService
        from tests.test_spatial_stage_pipeline import _table, _task

        service, task = DramaService(), _task()
        task["config"].pop("stage_planner")
        task["config"].update(config or {})
        scene = spatial.breakdown_scene(task, "E1S01")
        asked = []

        def llm(model, system, user, *args, **kwargs):
            if "这一场的剧本" in user:
                asked.append(user)
                return answer
            return _table("E1S01")

        with patch.object(service.gateway, "has_text_model", return_value=reachable), \
                patch.object(service.gateway, "last_answer_was_offline", return_value=False), \
                patch.object(service.gateway, "call_llm", side_effect=llm), \
                patch.object(service.gateway, "generate_image", return_value=("http://img.test/x.png", "meta")), \
                patch("app.service.drama_service.load_storyboard_elements", return_value=[]), \
                patch("app.service.drama_service.compose_nine_grid", lambda sources, path: path):
            payload = service._generate_scene_board(
                task, task["config"], scene, sys_prompt="s", storyboard_negative="", title="暗室回声",
                genre="mystery", dir_style="noir", shot_style="cinematic", guidance="", char_info=("林夏", "", "周教授", ""),
            )
        return task, payload, asked

    def test_the_models_set_marks_and_poses_reach_the_stored_plan(self):
        answer = json.dumps({"rationale": "隔案对峙", "operations": [
            {"op": "add_landmark", "name": "长案", "kit": "desk", "position": [0, -2]},
            {"op": "set_pose", "name": "林夏", "preset": "cross-arms"},
            {"op": "solve_camera", "shot_id": 1, "size": "特写"},
        ]}, ensure_ascii=False)
        task, _, asked = self._generate(answer=answer)
        self.assertEqual(len(asked), 1, "one call per scene")
        plan = spatial.load_plan(task, "E1S01")
        self.assertEqual(plan.planner, "model")
        self.assertEqual(plan.source, "auto")
        self.assertEqual(plan.planner_note, "隔案对峙")
        self.assertTrue(any(piece.kit == "desk" for piece in plan.landmarks))
        self.assertEqual(next(a for a in plan.actors if a.name == "林夏").pose.preset, "cross-arms")

    def test_no_model_opting_out_and_a_useless_answer_all_leave_the_rule_plan(self):
        for options in ({"reachable": False}, {"config": {"stage_planner": "rules"}}, {"answer": "这场戏很精彩。"}):
            task, _, asked = self._generate(**{"answer": None, **options})
            self.assertEqual(spatial.load_plan(task, "E1S01").planner, "rules", options)
            if "answer" not in options:
                self.assertEqual(asked, [], options)


class GlbTest(unittest.TestCase):
    def _read(self, data):
        magic, version, total = struct.unpack_from("<4sII", data, 0)
        self.assertEqual((magic, version, total), (b"glTF", 2, len(data)))
        length, kind = struct.unpack_from("<I4s", data, 12)
        self.assertEqual(kind, b"JSON")
        document = json.loads(data[20:20 + length])
        size, kind = struct.unpack_from("<I4s", data, 20 + length)
        self.assertEqual(kind, b"BIN\x00")
        self.assertEqual(size % 4, 0)
        self.assertEqual(document["buffers"][0]["byteLength"] % 4 in (0, 1, 2, 3), True)
        return document

    def test_a_kit_exports_a_well_formed_file_at_its_real_size_with_outward_faces(self):
        plan = apply_operations(_plan(), [{"op": "add_landmark", "name": "车", "kit": "sedan", "position": [3, 3]}])
        piece = next(item for item in plan.landmarks if item.name == "车")
        document = self._read(glb.landmark_glb(piece))
        lows = [min(a["min"][axis] for a in document["accessors"] if "min" in a) for axis in range(3)]
        highs = [max(a["max"][axis] for a in document["accessors"] if "max" in a) for axis in range(3)]
        self.assertAlmostEqual(highs[0] - lows[0], piece.size[0], delta=0.02)
        self.assertAlmostEqual(highs[1] - lows[1], piece.size[2], delta=0.02)
        self.assertAlmostEqual(highs[2] - lows[2], piece.size[1], delta=0.02)
        self.assertAlmostEqual(lows[1], 0.0, delta=0.01)
        self.assertTrue(document["materials"])

    def test_every_unit_shape_faces_outward(self):
        for shape in ("box", "cylinder", "cone", "sphere", "wedge"):
            for a, b, c in glb._unit_triangles(shape):
                normal = glb._normal(a, b, c)
                middle = [(a[axis] + b[axis] + c[axis]) / 3 for axis in range(3)]
                self.assertGreater(sum(normal[axis] * middle[axis] for axis in range(3)), -1e-6, shape)


class BlenderSpecTest(unittest.TestCase):
    def test_parts_become_blocks_in_blender_axes(self):
        plan = apply_operations(_plan(), [{"op": "add_landmark", "name": "车", "kit": "sedan", "position": [3, 4], "yaw_deg": 90}])
        piece = next(item for item in plan.landmarks if item.name == "车")
        spec, _ = build_spec(plan)
        blocks = [block for block in spec.set.blocks if block.id.startswith(piece.id + "-")]
        self.assertEqual(len(blocks), len(piece.parts))
        self.assertTrue(all(len(block.basis) == 9 for block in blocks))
        # A 4.5 m long car turned 90° about the vertical runs along Blender X, around (3, -4).
        xs = [block.position[0] for block in blocks]
        ys = [block.position[1] for block in blocks]
        self.assertGreater(max(xs) - min(xs), max(ys) - min(ys))
        self.assertAlmostEqual(sum(ys) / len(ys), -4.0, delta=0.5)
        # The basis of a yaw of 90° has Z fixed and is a pure rotation.
        body = next(block for block in blocks if block.basis[8] == 1.0)
        self.assertAlmostEqual(sum(value * value for value in body.basis[:3]), 1.0, places=3)

    def test_too_many_parts_fall_back_to_bounding_boxes_instead_of_failing(self):
        operations = [{"op": "add_landmark", "name": f"楼{index}", "kit": "bus", "position": [index, 40]} for index in range(50)]
        plan = apply_operations(_plan(), operations)
        spec, _ = build_spec(plan)
        self.assertLessEqual(len(spec.set.blocks), 400)


class FakeRepo:
    def __init__(self, task):
        self.task = task

    def get_task(self, task_id):
        return deepcopy(self.task)

    def mutate_task(self, task_id, mutation):
        working = deepcopy(self.task)
        result = mutation(working)
        self.task = working
        return result


class FakeGateway:
    def __init__(self, *answers, offline=False):
        self.llm = FakeLLM(*answers)
        self.offline = offline

    def call_llm(self, model, system, user, title, max_tokens=None):
        return self.llm(system, user, max_tokens)

    def last_answer_was_offline(self):
        return self.offline


class FakeService:
    def __init__(self, gateway):
        script = {"episodes": [{"scenes": []}]}
        self.gateway = gateway
        self.repo = FakeRepo({
            "task_id": "t1", "stage_name": "测试", "config": {"llm_model": "m"}, "script": script, "assets": {},
        })
        spatial.save_plan(self.repo.task, _plan())

    def _has_running_generation(self, task):
        return False

    def _spatial_response(self, task, scene_id, plan, *, persisted):
        return {"task_id": "t1", "scene_id": scene_id, "persisted": persisted, "plan": plan.model_dump(mode="json")}


class ServiceTest(unittest.TestCase):
    def _service(self, *answers, offline=False):
        return FakeService(FakeGateway(*answers, offline=offline))

    def _revision(self, service):
        return spatial.load_plan(service.repo.task, "E1S02").revision

    def test_a_turn_is_saved_as_one_step_and_can_be_taken_back(self):
        service = self._service(json.dumps({"reply": "退后了", "operations": [{"op": "move_actor", "name": "内侍", "position": [0, -4]}]}))
        start = self._revision(service)
        response = director.chat(service, "t1", "E1S02", message="内侍退后", base_revision=start)
        self.assertTrue(response["changed"])
        self.assertEqual(response["plan"]["revision"], start + 1)
        self.assertEqual(response["message"]["changed"]["actors"], ["内侍"])
        stored = spatial.load_plan(service.repo.task, "E1S02")
        self.assertEqual(next(a for a in stored.actors if a.name == "内侍").position, [0.0, -4.0])
        view = director.state(service, "t1", "E1S02")
        self.assertEqual([row["role"] for row in view["chat"]], ["user", "assistant"])
        self.assertEqual(view["chat"][1]["snapshot_id"], response["snapshot_id"])
        self.assertEqual(len(view["snapshots"]), 1)
        self.assertNotIn("plan", view["snapshots"][0])
        back = director.revert(service, "t1", "E1S02", snapshot_id=response["snapshot_id"], base_revision=start + 1)
        self.assertEqual(back["plan"]["revision"], start + 2)
        restored = spatial.load_plan(service.repo.task, "E1S02")
        self.assertNotEqual(next(a for a in restored.actors if a.name == "内侍").position, [0.0, -4.0])
        self.assertTrue(restored.shots[0].screen, "what a revert restores is measured again")
        self.assertEqual(director.state(service, "t1", "E1S02")["snapshots"], [])

    def test_a_question_writes_no_revision_and_keeps_the_conversation(self):
        service = self._service(json.dumps({"reply": "沈砚在左", "operations": []}))
        start = self._revision(service)
        response = director.chat(service, "t1", "E1S02", message="谁在左边", base_revision=start)
        self.assertFalse(response["changed"])
        self.assertEqual(self._revision(service), start)
        self.assertEqual(len(director.state(service, "t1", "E1S02")["chat"]), 2)

    def test_operations_that_change_nothing_are_not_a_step_and_the_reply_says_so(self):
        plan_actor = _plan().actors[0]
        service = self._service(json.dumps({"reply": "换了站位", "operations": [
            {"op": "move_actor", "name": plan_actor.name, "position": plan_actor.position},
        ]}))
        start = self._revision(service)
        response = director.chat(service, "t1", "E1S02", message="x", base_revision=start)
        self.assertFalse(response["changed"])
        self.assertEqual(self._revision(service), start)
        self.assertIn("没有实际变化", response["message"]["text"])
        self.assertEqual(director.state(service, "t1", "E1S02")["snapshots"], [])

    def test_a_stale_revision_is_refused_before_any_model_call(self):
        service = self._service("{}")
        with self.assertRaises(spatial.StageConflict):
            director.chat(service, "t1", "E1S02", message="x", base_revision=self._revision(service) + 5)
        self.assertEqual(service.gateway.llm.prompts, [])

    def test_a_stage_edited_while_the_model_was_thinking_is_not_overwritten(self):
        service = self._service()
        start = self._revision(service)

        def answer(system, user, max_tokens):
            spatial.save_plan(service.repo.task, spatial.load_plan(service.repo.task, "E1S02").model_copy(update={"revision": start + 1}))
            return json.dumps({"reply": "好", "operations": [{"op": "move_actor", "name": "内侍", "position": [0, -4]}]})

        service.gateway.llm = answer
        with self.assertRaises(spatial.StageConflict):
            director.chat(service, "t1", "E1S02", message="x", base_revision=start)
        self.assertNotEqual(next(a for a in spatial.load_plan(service.repo.task, "E1S02").actors if a.name == "内侍").position, [0.0, -4.0])

    def test_the_offline_template_is_not_taken_for_a_model(self):
        service = self._service("第一场，夜，内景。赛博朋克霓虹……", offline=True)
        with self.assertRaises(director_ai.DirectorAIError):
            director.chat(service, "t1", "E1S02", message="往左", base_revision=self._revision(service))

    def test_snapshots_are_bounded(self):
        answers = [json.dumps({"reply": str(i), "operations": [{"op": "move_actor", "name": "内侍", "position": [0, -2 - i]}]}) for i in range(6)]
        service = self._service(*answers)
        for _ in answers:
            director.chat(service, "t1", "E1S02", message="退", base_revision=self._revision(service))
        self.assertEqual(len(director.state(service, "t1", "E1S02")["snapshots"]), director.MAX_SNAPSHOTS)

    def test_a_library_model_named_exactly_costs_no_call(self):
        service = self._service()
        proposal = director.propose_model(service, "t1", "E1S02", description="马车")
        self.assertEqual(proposal["kit"], "carriage")
        self.assertEqual(service.gateway.llm.prompts, [])
        with self.assertRaises(director.NoModelError):
            director.propose_model(service, "t1", "E1S02", description="一只会飞的青铜鼎")

    def test_a_proposal_can_be_placed_with_its_fitted_parts(self):
        service = self._service(json.dumps({"name": "鼎", "parts": [{"shape": "cylinder", "center": [0, 0.3, 0], "size": [0.6, 0.6, 0.6]}]}))
        proposal = director.propose_model(service, "t1", "E1S02", description="一只青铜鼎")
        plan = apply_operations(spatial.load_plan(service.repo.task, "E1S02"), [{
            "op": "add_landmark", "name": proposal["name"], "position": [1, 1], "size": proposal["size"], "kind": proposal["kind"],
            "fitted_parts": proposal["parts"],
        }])
        self.assertEqual(len(next(item for item in plan.landmarks if item.name == "鼎").parts), 1)

    def test_export_names_the_file_and_refuses_an_unknown_piece(self):
        service = self._service()
        task = service.repo.task
        plan = apply_operations(spatial.load_plan(task, "E1S02"), [{"op": "add_landmark", "name": "老 轿/车", "kit": "sedan", "position": [3, 3]}])
        spatial.save_plan(task, plan)
        piece = next(item for item in plan.landmarks if item.kit)
        name, data = director.export_model(service, "t1", "E1S02", piece.id)
        self.assertEqual(name, "老_轿_车.glb")
        self.assertTrue(data.startswith(b"glTF"))
        with self.assertRaises(LookupError):
            director.export_model(service, "t1", "E1S02", "mark-404")

    def test_pipeline_blocking_keeps_camera_work_out_and_stays_automatic(self):
        reply = json.dumps({"rationale": "隔案", "operations": [
            {"op": "add_landmark", "name": "案", "kit": "desk", "position": [0, -1.5]},
            {"op": "set_pose", "name": "沈砚", "preset": "think"},
            {"op": "solve_camera", "shot_id": 1, "size": "特写"},
        ]})
        plan = _plan()
        blocked = director.model_blocking(FakeLLM(reply), plan, "剧本")
        self.assertEqual(blocked.planner, "model")
        self.assertEqual(blocked.source, "auto", "the rule planner's promise about who edited a stage holds")
        self.assertEqual(blocked.cameras[0].position, plan.cameras[0].position)
        self.assertEqual(next(a for a in blocked.actors if a.name == "沈砚").figure, "mannequin")
        self.assertIsNone(director.model_blocking(FakeLLM(None), plan, "剧本"))
        self.assertIsNone(director.model_blocking(FakeLLM("不是 JSON"), plan, "剧本"))

    def test_pipeline_only_asks_for_an_untouched_rule_plan_in_a_project_that_has_not_opted_out(self):
        plan = _plan()
        task = {"config": {}}
        self.assertTrue(director.wants_model_blocking(task, plan))
        self.assertFalse(director.wants_model_blocking(task, None))
        self.assertFalse(director.wants_model_blocking(task, plan.model_copy(update={"source": "edited"})))
        self.assertFalse(director.wants_model_blocking(task, plan.model_copy(update={"planner": "model"})))
        self.assertFalse(director.wants_model_blocking({"config": {"stage_planner": "rules"}}, plan))

    def test_a_replan_on_a_models_blocking_keeps_it_and_says_so(self):
        reply = json.dumps({"rationale": "隔案", "operations": [{"op": "add_landmark", "name": "案", "kit": "desk", "position": [0, -1.5]}]})
        blocked = director.model_blocking(FakeLLM(reply), _plan(), "剧本")
        again = build_plan(_brief(), blocking_from=blocked)
        self.assertEqual(again.planner, "model")
        self.assertEqual(again.planner_note, "隔案")
        self.assertTrue(any(piece.kit == "desk" for piece in again.landmarks))


if __name__ == "__main__":
    unittest.main()

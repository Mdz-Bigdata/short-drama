# -*- coding: utf-8 -*-
"""Interactive stories: the expression model, validation, path analysis, the planner, the store and the exported player."""

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.api.interactive_story_api import router
from app.core import interactive_story as story
from app.core import media_compositor
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService
from app.service.interactive_story_service import ASSET_KEY, InteractiveStoryService, StoryPlanError, project_media


def choice(target, text="选", **fields):
    return {"text": text, "target": target, **fields}


def scene(segment_id, *choices, **fields):
    return {"id": segment_id, "title": fields.pop("title", segment_id), "choices": list(choices), **fields}


def ending(segment_id, **fields):
    return {"id": segment_id, "title": fields.pop("title", segment_id), "kind": "ending", **fields}


def graph(*segments, start=None, variables=()):
    return story.parse_graph({"start": start or segments[0]["id"], "variables": list(variables), "segments": list(segments)})


def codes(issues, severity=None):
    return sorted(item["code"] for item in issues if severity is None or item["severity"] == severity)


def num(name="x", initial=0, **fields):
    return {"id": name, "initial": initial, **fields}


def flag(name="f", initial=False):
    return {"id": name, "kind": "flag", "initial": initial}


def add(amount, name="x"):
    return {"var": name, "op": "add", "value": amount}


def gte(amount, name="x"):
    return {"var": name, "op": "gte", "value": amount}


# The same table runs through this module, the exported player's engine (below) and storyEngine.test.ts.
CONDITION_TABLE = [
    (None, {}, True),
    ({"var": "x", "op": "eq", "value": 1}, {"x": 1}, True),
    ({"var": "x", "op": "eq", "value": 1}, {"x": 1.0}, True),
    ({"var": "x", "op": "ne", "value": 1}, {"x": 2}, True),
    ({"var": "x", "op": "gt", "value": 1}, {"x": 1}, False),
    ({"var": "x", "op": "gte", "value": 1}, {"x": 1}, True),
    ({"var": "x", "op": "lt", "value": 1}, {"x": 0.5}, True),
    ({"var": "x", "op": "lte", "value": 1}, {"x": 2}, False),
    ({"var": "missing", "op": "ne", "value": 1}, {"x": 1}, False),
    ({"var": "f", "op": "eq", "value": True}, {"f": True}, True),
    ({"var": "f", "op": "ne", "value": True}, {"f": False}, True),
    ({"var": "f", "op": "gt", "value": False}, {"f": True}, False),
    # true is not 1 in any of the three languages' rules, whatever Python's == thinks.
    ({"var": "f", "op": "eq", "value": 1}, {"f": True}, False),
    ({"var": "x", "op": "eq", "value": True}, {"x": 1}, False),
    ({"var": "x", "op": "ne", "value": True}, {"x": 1}, False),
    ({"all": []}, {}, True),
    ({"any": []}, {}, False),
    ({"all": [{"var": "x", "op": "gt", "value": 0}, {"var": "f", "op": "eq", "value": True}]}, {"x": 1, "f": False}, False),
    ({"any": [{"var": "x", "op": "gt", "value": 5}, {"var": "f", "op": "eq", "value": True}]}, {"x": 1, "f": True}, True),
    ({"all": [{"any": [{"var": "x", "op": "eq", "value": 1}, {"var": "x", "op": "eq", "value": 2}]}, {"var": "x", "op": "ne", "value": 2}]}, {"x": 2}, False),
]


class ExpressionModelTests(unittest.TestCase):
    def test_the_table(self):
        for condition, values, expected in CONDITION_TABLE:
            self.assertEqual(story.evaluate(condition, values), expected, condition)

    def test_a_condition_is_only_ever_data(self):
        for bad in (
            "__import__('os').system('id')",
            {"var": "x", "op": "exec", "value": 1},
            {"var": "x", "op": "eq", "value": "1 or 1"},
            {"var": "x", "op": "eq"},
            {"all": [], "var": "x", "op": "eq", "value": 1},
            {"all": [], "any": []},
            {"var": "x", "op": "eq", "value": 1, "code": "boom"},
        ):
            with self.assertRaises(story.StoryInputError, msg=bad):
                graph(scene("a", choice("b", condition=bad)), ending("b"))

    def test_nesting_and_size_are_bounded(self):
        deep = {"var": "x", "op": "eq", "value": 1}
        for _ in range(story.MAX_CONDITION_DEPTH):
            deep = {"all": [deep]}
        with self.assertRaisesRegex(story.StoryInputError, "嵌套"):
            graph(scene("a", choice("b", condition=deep)), ending("b"), variables=[num()])
        wide = {"any": [{"var": "x", "op": "eq", "value": n} for n in range(story.MAX_CONDITION_NODES + 1)]}
        with self.assertRaisesRegex(story.StoryInputError, "最多"):
            graph(scene("a", choice("b", condition=wide)), ending("b"), variables=[num()])

    def test_values_keep_their_json_type(self):
        parsed = graph(scene("a", choice("b", condition={"var": "f", "op": "eq", "value": True})), ending("b"), variables=[flag()])
        self.assertIs(parsed["segments"][0]["choices"][0]["condition"]["value"], True)

    def test_non_finite_numbers_are_refused(self):
        for bad in (float("inf"), float("nan"), 1e12):
            with self.assertRaises(story.StoryInputError):
                graph(scene("a", choice("b", effects=[{"var": "x", "op": "add", "value": bad}])), ending("b"), variables=[num()])

    def test_effects_apply_clamp_and_ignore_what_does_not_fit(self):
        variables = {"x": {"id": "x", "kind": "number", "min": 0, "max": 10}, "f": {"id": "f", "kind": "flag"}}
        values = {"x": 9, "f": False}
        self.assertEqual(story.apply_effects([add(5)], values, variables)["x"], 10)
        self.assertEqual(story.apply_effects([add(-50)], values, variables)["x"], 0)
        self.assertEqual(story.apply_effects([{"var": "x", "op": "set", "value": 3}, add(1)], values, variables)["x"], 4)
        self.assertEqual(story.apply_effects([{"var": "f", "op": "set", "value": True}], values, variables)["f"], True)
        self.assertEqual(story.apply_effects([{"var": "f", "op": "add", "value": 1}], values, variables), values)
        self.assertEqual(story.apply_effects([{"var": "ghost", "op": "add", "value": 1}], values, variables), values)
        self.assertEqual(values, {"x": 9, "f": False})

    def test_floats_settle_instead_of_drifting(self):
        variables = {"x": {"id": "x", "kind": "number"}}
        self.assertEqual(story.apply_effects([add(0.1), add(0.2)], {"x": 0}, variables)["x"], 0.3)


class GraphShapeTests(unittest.TestCase):
    def test_blank_edge_ids_are_assigned_and_repeats_refused(self):
        parsed = graph(scene("a", choice("b"), choice("b")), ending("b"))
        self.assertEqual([item["id"] for item in parsed["segments"][0]["choices"]], ["a.c1", "a.c2"])
        with self.assertRaisesRegex(story.StoryInputError, "重复"):
            graph(scene("a", {"id": "dup", "target": "b"}), scene("b", {"id": "dup", "target": "a"}))
        with self.assertRaisesRegex(story.StoryInputError, "重复"):
            graph(ending("a"), ending("a"))

    def test_ids_that_mean_something_to_javascript_are_refused(self):
        for bad in ("__proto__", "constructor", "<script>", "a b"):
            with self.assertRaises(story.StoryInputError, msg=bad):
                graph(ending(bad))

    def test_media_cannot_be_a_script_address(self):
        for url in ("javascript:alert(1)", "data:text/html,x", 'https://a/"onload=', "file:///etc/passwd"):
            with self.assertRaises(story.StoryInputError, msg=url):
                graph(ending("a", media={"kind": "image", "url": url}))

    def test_variable_shapes(self):
        for bad in (
            {"id": "f", "kind": "flag", "initial": 1},
            {"id": "x", "initial": True},
            {"id": "x", "min": 5, "max": 1},
            {"id": "f", "kind": "flag", "min": 0},
        ):
            with self.assertRaises(story.StoryInputError, msg=bad):
                graph(ending("a"), variables=[bad])

    def test_a_null_edge_survives_a_round_trip(self):
        parsed = graph(scene("a", {"text": "未连"}), ending("b"))
        self.assertIsNone(parsed["segments"][0]["choices"][0]["target"])
        self.assertEqual(story.parse_graph(parsed), parsed)


class ValidationTests(unittest.TestCase):
    def test_a_sound_story_has_nothing_to_report(self):
        self.assertEqual(story.validate_graph(graph(scene("a", choice("b"), choice("c")), ending("b"), ending("c"))), [])

    def test_empty_and_missing_start(self):
        self.assertEqual(codes(story.validate_graph(story.parse_graph({}))), ["empty_story"])
        self.assertIn("missing_start", codes(story.validate_graph(graph(ending("a"), start="nope"))))

    def test_no_ending_at_all(self):
        self.assertIn("no_ending", codes(story.validate_graph(graph(scene("a", choice("a"))))))

    def test_unreachable_segment(self):
        issues = story.validate_graph(graph(scene("a", choice("b")), ending("b"), ending("orphan")))
        self.assertEqual(codes(issues), ["unreachable_segment"])
        self.assertEqual(issues[0]["segment_id"], "orphan")
        self.assertEqual(issues[0]["params"]["reason"], "no_path")

    def test_dead_end_is_an_error_and_an_ending_is_not(self):
        issues = story.validate_graph(graph(scene("a", choice("b")), scene("b"), ending("c"), start="a"))
        self.assertIn("dead_end", codes(issues, "error"))
        self.assertEqual([item["segment_id"] for item in issues if item["code"] == "dead_end"], ["b"])

    def test_choices_pointing_nowhere(self):
        issues = story.validate_graph(graph(scene("a", {"text": "空"}, choice("ghost", text="鬼"), choice("b")), ending("b")))
        self.assertEqual(codes(issues, "error"), ["choice_target_missing", "choice_unconnected"])

    def test_route_pointing_nowhere(self):
        issues = story.validate_graph(graph(scene("a", routes=[{"target": "ghost"}]), ending("b")))
        self.assertIn("route_target_missing", codes(issues, "error"))

    def test_unknown_variable_and_type_mismatch(self):
        issues = story.validate_graph(graph(
            scene("a",
                  choice("b", condition={"var": "ghost", "op": "eq", "value": 1}),
                  choice("b", effects=[add(1, "ghost")]),
                  choice("b", condition={"var": "f", "op": "gt", "value": True}),
                  choice("b", effects=[{"var": "f", "op": "add", "value": 1}]),
                  choice("b", condition={"var": "x", "op": "eq", "value": True}),
                  choice("b", effects=[{"var": "x", "op": "set", "value": True}])),
            ending("b"), variables=[num(), flag()],
        ))
        self.assertEqual(
            codes(issues, "error"),
            ["condition_type_mismatch", "condition_type_mismatch", "effect_type_mismatch", "effect_type_mismatch", "unknown_variable", "unknown_variable"],
        )
        # A condition that is malformed is reported as that, not also as "can never be true".
        self.assertNotIn("impossible_condition", codes(issues))

    def test_ending_with_exits_and_shadowed_edges(self):
        self.assertIn("ending_has_exits", codes(story.validate_graph(graph(scene("a", choice("b")), ending("b", choices=[choice("a")])))))
        issues = story.validate_graph(graph(scene("a", choice("c"), routes=[{"target": "b"}]), ending("b"), ending("c")))
        self.assertIn("shadowed_edges", codes(issues))
        self.assertIn("unreachable_segment", codes(issues))

    def test_timers(self):
        self.assertIn("timer_without_choices", codes(story.validate_graph(graph(scene("a", timer={"seconds": 5}, routes=[{"target": "b"}]), ending("b")))))
        self.assertIn("timer_default_missing", codes(story.validate_graph(graph(scene("a", choice("b"), timer={"seconds": 5, "default_choice": "x"}), ending("b"))), "error"))
        gated = graph(
            scene("a", {"id": "c1", "text": "甲", "target": "b", "condition": gte(0)}, {"id": "c2", "text": "乙", "target": "b"}, timer={"seconds": 5, "default_choice": "c1"}),
            ending("b"), variables=[num()],
        )
        self.assertEqual(codes(story.validate_graph(gated)), ["timer_default_gated"])


class ImpossibleConditionTests(unittest.TestCase):
    def _impossible(self, *segments, **fields):
        issues = story.validate_graph(graph(*segments, **fields))
        return [item for item in issues if item["code"] == "impossible_condition"], issues

    def test_a_threshold_past_what_the_story_can_give(self):
        found, _ = self._impossible(
            scene("a", choice("b", effects=[add(1)]), choice("b", effects=[add(2)])),
            scene("b", choice("c", condition=gte(5)), choice("d")),
            ending("c"), ending("d"), variables=[num()],
        )
        self.assertEqual(len(found), 1)
        self.assertIn("只可能是 1、2", found[0]["message"])

    def test_the_same_threshold_is_fine_when_the_points_can_add_up(self):
        found, _ = self._impossible(
            scene("a", choice("b", effects=[add(3)]), choice("b")),
            scene("b", choice("c", effects=[add(3)]), choice("c")),
            scene("c", choice("d", condition=gte(5)), choice("e")),
            ending("d"), ending("e"), variables=[num()],
        )
        self.assertEqual(found, [])

    def test_effects_after_the_choice_do_not_count(self):
        # The points are only handed out after the gate; a whole-graph range would have called this fine.
        found, _ = self._impossible(
            scene("a", choice("c", condition=gte(1)), choice("b")),
            scene("b", choice("d", effects=[add(1)])),
            ending("c"), ending("d"), variables=[num()],
        )
        self.assertEqual(len(found), 1)

    def test_a_loop_can_earn_any_amount(self):
        found, _ = self._impossible(
            scene("a", choice("a", effects=[add(1)]), choice("b", condition=gte(100)), choice("c")),
            ending("b"), ending("c"), variables=[num()],
        )
        self.assertEqual(found, [])

    def test_clamps_are_respected_through_loops(self):
        found, _ = self._impossible(
            scene("a", choice("a", effects=[add(1)]), choice("b", condition=gte(11)), choice("c")),
            ending("b"), ending("c"), variables=[num(min=0, max=10)],
        )
        self.assertEqual(len(found), 1)

    def test_contradiction_inside_all(self):
        found, _ = self._impossible(
            scene("a", choice("a", effects=[add(1)]), choice("b", condition={"all": [{"var": "x", "op": "gt", "value": 5}, {"var": "x", "op": "lt", "value": 3}]}), choice("c")),
            ending("b"), ending("c"), variables=[num()],
        )
        self.assertEqual(len(found), 1)

    def test_open_bounds_meet_exactly(self):
        found, _ = self._impossible(
            scene("a", choice("a", effects=[add(1)]), choice("b", condition={"all": [{"var": "x", "op": "gt", "value": 5}, {"var": "x", "op": "lte", "value": 5}]}), choice("c")),
            ending("b"), ending("c"), variables=[num()],
        )
        self.assertEqual(len(found), 1)

    def test_a_flag_nothing_ever_sets(self):
        found, _ = self._impossible(
            scene("a", choice("b", condition={"var": "f", "op": "eq", "value": True}), choice("c")),
            ending("b"), ending("c"), variables=[flag()],
        )
        self.assertEqual(len(found), 1)

    def test_a_flag_something_sets_earlier(self):
        found, _ = self._impossible(
            scene("a", choice("m", effects=[{"var": "f", "op": "set", "value": True}]), choice("m")),
            scene("m", choice("b", condition={"var": "f", "op": "eq", "value": True}), choice("c")),
            ending("b"), ending("c"), variables=[flag()],
        )
        self.assertEqual(found, [])

    def test_any_needs_only_one_side_possible(self):
        found, _ = self._impossible(
            scene("a", choice("b", condition={"any": [gte(9), {"var": "x", "op": "eq", "value": 0}]}), choice("c")),
            ending("b"), ending("c"), variables=[num()],
        )
        self.assertEqual(found, [])

    def test_what_lies_behind_an_impossible_gate_is_unreachable_for_that_reason(self):
        _, issues = self._impossible(
            scene("a", choice("b", condition=gte(5)), choice("c")),
            ending("b"), ending("c"), variables=[num()],
        )
        row = next(item for item in issues if item["code"] == "unreachable_segment")
        self.assertEqual((row["segment_id"], row["params"]["reason"]), ("b", "conditions"))

    def test_a_route_gate_counts_too(self):
        found, _ = self._impossible(
            scene("a", choice("c"), routes=[{"condition": gte(1), "target": "b"}]),
            ending("b"), ending("c"), variables=[num()],
        )
        self.assertEqual(len(found), 1)
        self.assertIn("route_id", found[0])

    def test_big_loop_graphs_settle(self):
        # Many counters in a ring: the walk has to reach a fixed point, not grow forever.
        count = 60
        variables = [num(f"v{n}") for n in range(story.MAX_VARIABLES)]
        segments = [
            scene(f"s{n}", choice(f"s{(n + 1) % count}", effects=[add(1, f"v{m % story.MAX_VARIABLES}") for m in range(n, n + 3)]), choice("end"))
            for n in range(count)
        ]
        issues = story.validate_graph(graph(*segments, ending("end"), variables=variables))
        self.assertEqual(codes(issues, "error"), [])


class CycleTests(unittest.TestCase):
    def test_a_cycle_with_no_exit(self):
        issues = story.validate_graph(graph(scene("a", choice("b")), scene("b", choice("c")), scene("c", choice("b")), ending("end")))
        row = next(item for item in issues if item["code"] == "cycle_no_exit")
        self.assertEqual(row["severity"], "error")
        self.assertEqual(row["segment_ids"], ["b", "c"])
        # The step leading into the trap is told so; the loop itself is not told twice.
        self.assertEqual([item["segment_id"] for item in issues if item["code"] == "cannot_reach_ending"], [])
        self.assertIn("no_reachable_ending", codes(issues))

    def test_a_self_loop_with_no_exit(self):
        self.assertIn("cycle_no_exit", codes(story.validate_graph(graph(scene("a", choice("a")), ending("end")))))

    def test_a_cycle_with_an_exit_is_fine(self):
        self.assertEqual(story.validate_graph(graph(scene("a", choice("b")), scene("b", choice("a"), choice("end")), ending("end"))), [])

    def test_a_cycle_whose_only_exit_can_never_open_has_no_exit(self):
        issues = story.validate_graph(graph(
            scene("a", choice("b")), scene("b", choice("a"), choice("end", condition=gte(1))), ending("end"), variables=[num()],
        ))
        self.assertIn("cycle_no_exit", codes(issues, "error"))

    def test_a_trap_off_to_one_side_warns_the_segment_before_it(self):
        issues = story.validate_graph(graph(
            scene("a", choice("end"), choice("door")), scene("door", choice("loop")), scene("loop", choice("loop")), ending("end"),
        ))
        self.assertEqual([item["segment_id"] for item in issues if item["code"] == "cannot_reach_ending"], ["a", "door"][1:])
        self.assertIn("cycle_no_exit", codes(issues))

    def test_a_long_chain_does_not_hit_the_recursion_limit(self):
        count = story.MAX_SEGMENTS - 1
        chain = [scene(f"s{n}", choice(f"s{n + 1}")) for n in range(count - 1)] + [scene(f"s{count - 1}", choice("end")), ending("end")]
        self.assertEqual(story.validate_graph(graph(*chain)), [])
        self.assertEqual(story.analyze_paths(graph(*chain))["complete_paths"], 1)


class PathAnalysisTests(unittest.TestCase):
    def test_rates_coverage_and_minutes(self):
        parsed = graph(
            scene("a", choice("b"), choice("c"), est_seconds=60),
            scene("b", choice("d"), choice("e"), est_seconds=120, timer={"seconds": 30, "default_choice": "b.c1"}),
            ending("c", est_seconds=30), ending("d", est_seconds=30), ending("e", est_seconds=30),
            ending("orphan"),
        )
        result = story.analyze_paths(parsed)
        self.assertEqual((result["paths"], result["complete_paths"], result["truncated"]), (3, 3, False))
        self.assertEqual(result["rate_method"], "enumeration")
        rates = {row["id"]: row["reach_rate"] for row in result["endings"]}
        self.assertEqual(rates, {"c": 0.5, "d": 0.25, "e": 0.25, "orphan": 0.0})
        coverage = result["coverage"]
        self.assertEqual((coverage["segments_covered"], coverage["segments_total"]), (5, 6))
        self.assertEqual((coverage["choices_covered"], coverage["choices_total"]), (4, 4))
        self.assertEqual((coverage["endings_covered"], coverage["endings_total"]), (3, 4))
        # 60 + 3 decision + 30 ending for the short route; 60 + 3 + 120 + 30 timer + 30 for the long ones.
        self.assertEqual(result["minutes"]["min"], round(93 / 60, 2))
        self.assertEqual(result["minutes"]["max"], round(243 / 60, 2))
        self.assertEqual(result["minutes"]["avg"], round(0.5 * round(93 / 60, 2) + 0.5 * round(243 / 60, 2), 2))

    def test_video_length_wins_over_the_estimate_and_text_is_read_aloud(self):
        self.assertEqual(story.segment_seconds({"media": {"kind": "video", "duration_s": 12}, "est_seconds": 99}), 12)
        self.assertEqual(story.segment_seconds({"est_seconds": 99}), 99)
        self.assertEqual(story.segment_seconds({"narration": "短"}), 3.0)
        self.assertAlmostEqual(story.segment_seconds({"narration": "字" * 45}), 10.0)
        self.assertEqual(story.segment_seconds({"dialogue": [{"text": "one two three four five six seven eight nine ten"}]}), 4.0)

    def test_locked_choices_are_not_taken(self):
        parsed = graph(
            scene("a", choice("m", effects=[add(1)]), choice("m")),
            scene("m", choice("good", condition=gte(1)), choice("bad")),
            ending("good"), ending("bad"), variables=[num()],
        )
        rates = {row["id"]: row["reach_rate"] for row in story.analyze_paths(parsed)["endings"]}
        self.assertEqual(rates, {"good": 0.25, "bad": 0.75})

    def test_routes_send_a_playthrough_by_its_values(self):
        parsed = graph(
            scene("a", choice("gate", effects=[add(5)]), choice("gate")),
            scene("gate", routes=[{"condition": gte(5), "target": "good"}, {"target": "bad"}]),
            ending("good"), ending("bad"), variables=[num()],
        )
        result = story.analyze_paths(parsed)
        self.assertEqual({row["id"]: row["reach_rate"] for row in result["endings"]}, {"good": 0.5, "bad": 0.5})
        self.assertEqual(result["coverage"]["segments_covered"], 4)

    def test_being_stuck_is_found_by_playing_it_out(self):
        # Each choice alone is possible; only the combination strands the viewer, so the static pass cannot see it.
        parsed = graph(
            scene("a", choice("m", effects=[add(1)]), choice("m")),
            scene("m", choice("end", condition={"var": "x", "op": "eq", "value": 0})),
            ending("end"), variables=[num()],
        )
        analysis = story.analyze_story(parsed)
        self.assertEqual(analysis["paths"]["stuck_paths"], 1)
        self.assertEqual(analysis["paths"]["stuck"][0]["values"], {"x": 1.0})
        self.assertEqual(analysis["paths"]["unfinished_rate"], 0.5)
        self.assertIn("stuck_state", codes(analysis["issues"], "warning"))

    def test_too_many_paths_is_reported_as_such_and_rates_are_simulated(self):
        # Twenty coin flips: a million routes, stopped at the limit, and the rate is still about right.
        layers = []
        for n in range(20):
            layers.append(scene(f"a{n}", choice(f"b{n}"), choice(f"b{n}")))
            layers.append(scene(f"b{n}", choice(f"a{n + 1}" if n < 19 else "split")))
        parsed = graph(*layers, scene("split", choice("x"), choice("y")), ending("x"), ending("y"))
        result = story.analyze_paths(parsed, max_paths=200)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["rate_method"], "simulation")
        self.assertLessEqual(result["paths"], 200)
        self.assertLessEqual(len(result["routes"]), story.ROUTES_SHOWN)
        rates = {row["id"]: row["reach_rate"] for row in result["endings"]}
        self.assertAlmostEqual(rates["x"], 0.5, delta=0.1)
        self.assertAlmostEqual(rates["x"] + rates["y"], 1.0, places=6)

    def test_loops_are_cut_and_rates_come_from_simulation(self):
        parsed = graph(scene("a", choice("a"), choice("end")), ending("end"))
        result = story.analyze_paths(parsed)
        self.assertGreater(result["loop_cuts"], 0)
        self.assertEqual(result["rate_method"], "simulation")
        self.assertEqual(result["endings"][0]["reach_rate"], 1.0)
        self.assertEqual(result["unfinished_rate"], 0.0)

    def test_a_trap_shows_as_unfinished_not_as_an_ending(self):
        parsed = graph(scene("a", choice("t"), choice("end")), scene("t", choice("t")), ending("end"))
        result = story.analyze_paths(parsed)
        self.assertAlmostEqual(result["endings"][0]["reach_rate"], 0.5, delta=0.1)
        self.assertAlmostEqual(result["unfinished_rate"], 0.5, delta=0.1)

    def test_simulation_is_repeatable(self):
        parsed = graph(scene("a", choice("a"), choice("end"), choice("other")), ending("end"), ending("other"))
        self.assertEqual(story.analyze_paths(parsed), story.analyze_paths(parsed))

    def test_a_broken_story_still_gets_an_answer(self):
        self.assertEqual(story.analyze_paths(story.parse_graph({}))["paths"], 0)
        result = story.analyze_paths(graph(ending("a"), start="nope"))
        self.assertEqual(result["complete_paths"], 0)
        self.assertEqual(result["endings"][0]["reach_rate"], 0.0)
        self.assertEqual(story.analyze_story(story.parse_graph({"start": "x"}))["ready"], False)


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.graph = graph(scene("a", {"id": "go", "text": "走", "target": "b"}, {"id": "stay", "text": "留", "target": "c"}), ending("b", title="好"), ending("c", title="坏"))

    def run_through(self, stats=None, *, last="b", via="go", **fields):
        return story.record_playtest(stats, self.graph, {"steps": [{"segment": "a"}, {"segment": last, "choice": via}], "ending": last, **fields})

    def test_counts_add_up(self):
        stats = self.run_through()
        stats = self.run_through(stats)
        stats = self.run_through(stats, last="c", via="stay", timeouts=1)
        view = story.stats_view(stats, self.graph, story.analyze_paths(self.graph))
        self.assertEqual((view["runs"], view["completed"], view["timeouts"]), (3, 3, 1))
        self.assertEqual({row["choice_id"]: (row["count"], row["share"]) for row in view["choices"]}, {"go": (2, 0.6667), "stay": (1, 0.3333)})
        self.assertEqual({row["id"]: row["count"] for row in view["endings"]}, {"b": 2, "c": 1})
        self.assertEqual((view["endings_reached"], view["endings_total"]), (2, 2))
        self.assertEqual((view["routes_played"], view["routes_total"], view["route_coverage"]), (2, 2, 1.0))

    def test_an_abandoned_run_counts_as_a_run_only(self):
        stats = story.record_playtest(None, self.graph, {"steps": [{"segment": "a"}]})
        self.assertEqual((stats["runs"], stats["completed"], stats["endings"]), (1, 0, {}))

    def test_unknown_ids_cannot_grow_the_store(self):
        stats = story.record_playtest(None, self.graph, {
            "steps": [{"segment": "ghost", "choice": "boo"}, {"segment": "a", "choice": "boo"}], "ending": "ghost",
        })
        self.assertEqual((stats["segments"], stats["choices"], stats["endings"]), ({"a": 1}, {}, {}))

    def test_an_ending_claim_must_match_the_last_step(self):
        stats = story.record_playtest(None, self.graph, {"steps": [{"segment": "a"}], "ending": "b"})
        self.assertEqual((stats["completed"], stats["endings"]), (0, {}))

    def test_a_replay_from_the_middle_is_not_a_route(self):
        stats = self.run_through(from_start=False)
        self.assertEqual(stats["routes"], {})
        self.assertEqual(stats["completed"], 1)

    def test_a_deleted_choice_stops_being_listed(self):
        stats = self.run_through()
        smaller = graph(scene("a", {"id": "stay", "text": "留", "target": "c"}), ending("c"))
        self.assertEqual(story.stats_view(stats, smaller)["choices"], [])


class PlannerNormalisationTests(unittest.TestCase):
    def test_repeated_edge_ids_and_the_timer_that_named_one(self):
        parsed = story.StoryPlanDraft.model_validate({
            "start": "s1",
            "segments": [
                {"id": "s1", "choices": [{"id": "c1", "target": "s2"}, {"id": "c2", "target": "s3"}], "timer": {"seconds": 5, "default_choice": "c2"}},
                {"id": "s2", "choices": [{"id": "c1", "target": "s3"}]},
                {"id": "s3", "kind": "ending"},
            ],
        }).model_dump(mode="json")
        self.assertEqual(parsed["segments"][0]["timer"]["default_choice"], "s1.c2")
        self.assertEqual(parsed["segments"][1]["choices"][0]["id"], "s2.c1")

    def test_a_model_cannot_choose_media_or_layout(self):
        parsed = story.StoryPlanDraft.model_validate({
            "segments": [{"id": "s", "kind": "ending", "media": {"kind": "video", "url": "https://169.254.169.254/x"}, "position": {"x": 1, "y": 2}}],
        }).model_dump(mode="json")
        self.assertIsNone(parsed["segments"][0]["media"])
        self.assertIsNone(parsed["segments"][0]["position"])

    def test_problems_are_repaired_where_mechanical_and_named_where_not(self):
        data = story.StoryPlanDraft.model_validate({
            "segments": [
                {"id": "s", "choices": [{"text": "a", "target": "e1", "effects": [{"var": "love", "op": "add", "value": 1}]}, {"text": "b", "target": "e1", "condition": {"var": "key", "op": "eq", "value": True}}], "timer": {"seconds": 5}},
                {"id": "e1", "kind": "ending"},
            ],
        }).model_dump(mode="json")
        reasons = story.plan_problems(data, min_endings=2)
        self.assertEqual(data["start"], "s")
        self.assertEqual({item["id"]: item["kind"] for item in data["variables"]}, {"love": "number", "key": "flag"})
        self.assertEqual(data["segments"][0]["timer"]["default_choice"], "s.c1")
        self.assertEqual(len(reasons), 1)
        self.assertIn("至少需要 2 个", reasons[0])

    def test_the_schema_a_model_is_shown_is_valid_json(self):
        from app.core.screenwriting.structured_llm import compact_schema

        self.assertIn("segments", json.loads(compact_schema(story.StoryPlanDraft))["properties"])


def _good_plan():
    return {
        "title": "雨夜来客", "synopsis": "一封信", "outline": ["开场", "抉择", "收束"], "start": "s1",
        "variables": [{"id": "trust", "label": "信任", "kind": "number", "initial": 0}],
        "segments": [
            {"id": "s1", "title": "开门", "narration": "门外有人。", "choices": [
                {"id": "c1", "text": "开门", "target": "s2", "effects": [{"var": "trust", "op": "add", "value": 2}]},
                {"id": "c2", "text": "不开", "target": "s2"},
            ], "timer": {"seconds": 10, "default_choice": "c2"}},
            {"id": "s2", "title": "收束", "routes": [{"id": "r1", "condition": {"var": "trust", "op": "gte", "value": 2}, "target": "good"}, {"id": "r2", "target": "bad"}]},
            {"id": "good", "title": "团圆", "kind": "ending", "ending_label": "好结局"},
            {"id": "bad", "title": "错过", "kind": "ending", "ending_label": "坏结局"},
        ],
    }


class PlanServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("t", {"task_id": "t", "assets": {"3_characters": [{"name": "林晚"}]}, "config": {"llm_model": "m-1", "title_suggestion": "雨夜"}})
        self.gateway = MagicMock()
        self.service = InteractiveStoryService(self.repo, self.gateway)

    def test_a_good_answer_comes_back_and_nothing_is_stored(self):
        self.gateway.call_llm.return_value = json.dumps(_good_plan(), ensure_ascii=False)
        result = self.service.plan("t", "雨夜里的一封信", endings=2)
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["draft"]["start"], "s1")
        self.assertEqual(result["draft"]["segments"][0]["choices"][0]["id"], "s1.c1")
        self.assertEqual(result["draft"]["segments"][0]["timer"]["default_choice"], "s1.c2")
        self.assertTrue(result["analysis"]["ready"])
        self.assertNotIn(ASSET_KEY, self.repo.get_task("t")["assets"])
        args = self.gateway.call_llm.call_args
        self.assertEqual(args.args[0], "m-1")
        self.assertIn("林晚", args.args[2])
        self.assertIn("雨夜里的一封信", args.args[2])

    def test_junk_is_retried_with_the_reason_then_repaired(self):
        self.gateway.call_llm.side_effect = ["我来讲个故事吧。", '{"segments": "很多"}', json.dumps(_good_plan(), ensure_ascii=False)]
        result = self.service.plan("t", "雨夜里的一封信", endings=2)
        self.assertEqual(result["attempts"], 3)
        self.assertIn("上一轮输出未通过校验", self.gateway.call_llm.call_args_list[1].args[2])
        self.assertIn("schema", self.gateway.call_llm.call_args_list[2].args[2])

    def test_a_story_that_goes_nowhere_is_sent_back_with_what_is_wrong(self):
        broken = _good_plan()
        broken["segments"][0]["choices"][0]["target"] = "ghost"
        self.gateway.call_llm.side_effect = [json.dumps(broken, ensure_ascii=False), json.dumps(_good_plan(), ensure_ascii=False)]
        result = self.service.plan("t", "雨夜里的一封信", endings=2)
        self.assertEqual(result["attempts"], 2)
        self.assertIn("ghost", self.gateway.call_llm.call_args_list[1].args[2])

    def test_only_junk_is_a_clear_error(self):
        self.gateway.call_llm.return_value = "（离线模板）第一集……"
        with self.assertRaisesRegex(StoryPlanError, "连续 3 次"):
            self.service.plan("t", "雨夜里的一封信")
        self.assertEqual(self.gateway.call_llm.call_count, 3)
        self.assertNotIn(ASSET_KEY, self.repo.get_task("t")["assets"])

    def test_a_failing_model_call_does_not_leak_its_details(self):
        self.gateway.call_llm.side_effect = RuntimeError("key sk-secret rejected")
        with self.assertRaises(StoryPlanError) as caught:
            self.service.plan("t", "雨夜里的一封信")
        self.assertNotIn("sk-secret", str(caught.exception))

    def test_the_call_is_attributed_to_the_project(self):
        from app.core import usage_ledger

        seen = {}

        def answer(*_args, **_kwargs):
            seen["task"] = usage_ledger.current_task_id()
            return json.dumps(_good_plan(), ensure_ascii=False)

        self.gateway.call_llm.side_effect = answer
        self.service.plan("t", "雨夜里的一封信", endings=2)
        self.assertEqual(seen["task"], "t")


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2048
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048


def _sample(media=None):
    return {
        "title": "雨夜", "start": "a", "variables": [num("love")],
        "segments": [
            scene("a", {"id": "c1", "text": "走", "target": "b", "effects": [add(1, "love")]}, {"id": "c2", "text": "留", "target": "c"}, title="开场", media=media),
            ending("b", title="好"), ending("c", title="坏"),
        ],
    }


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media_dir = Path(self.temp.name) / "media"
        self.media_dir.mkdir()
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.task_id = "task-story"
        self.service.repo.save_task(self.task_id, {
            "task_id": self.task_id, "owner_user_id": "u-1", "config": {"llm_model": "m-1"},
            "assets": {
                "4": [{"shot_id": 1, "scene_id": "E1S01", "desc": "开门", "image_url": "/media/shot1.png"}, {"shot_id": 2, "scene_id": "E1S01", "desc": "未出片"}],
                "5": [{"shot_id": 1, "scene_id": "E1S01", "shot_uid": 100101, "shot_uids": [100101], "video_url": "/media/clip1.mp4", "duration": 8, "candidates": ["/media/clip1.mp4", "/media/clip1b.mp4"]}],
                "7": {"final_video_url": "/media/film.mp4"},
            },
        })
        (self.media_dir / "shot1.png").write_bytes(PNG)
        (self.media_dir / "clip1.mp4").write_bytes(MP4)
        for patcher in (patch.object(drama_api, "service", self.service), patch.object(media_compositor, "MEDIA_DIR", str(self.media_dir))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-1", "role": "user"}
        self.client = TestClient(self.app)
        self.base = f"/api/drama/{self.task_id}/interactive-story"

    def _save(self, graph_data=None, base_revision=0):
        return self.client.put(self.base, json={"base_revision": base_revision, "graph": graph_data or _sample()})

    def test_a_project_starts_with_no_story(self):
        body = self.client.get(self.base).json()
        self.assertEqual((body["revision"], body["graph"], body["analysis"]), (0, None, None))

    def test_save_returns_the_story_with_its_analysis(self):
        response = self._save()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["revision"], 1)
        self.assertTrue(body["analysis"]["ready"])
        self.assertEqual(body["analysis"]["paths"]["complete_paths"], 2)
        self.assertNotIn("route_keys", body["analysis"]["paths"])
        self.assertEqual(self.client.get(self.base).json()["graph"]["segments"][0]["title"], "开场")

    def test_a_stale_revision_is_a_conflict_and_changes_nothing(self):
        self._save()
        changed = _sample()
        changed["title"] = "别的"
        response = self._save(changed, base_revision=0)
        self.assertEqual(response.status_code, 409)
        self.assertIn("刷新", response.json()["detail"])
        current = self.client.get(self.base).json()
        self.assertEqual((current["revision"], current["graph"]["title"]), (1, "雨夜"))
        self.assertEqual(self._save(changed, base_revision=1).json()["revision"], 2)

    def test_junk_is_a_readable_422(self):
        response = self._save({"segments": [{"id": "a", "choices": [{"condition": {"var": "x", "op": "eval", "value": 1}}]}]})
        self.assertEqual(response.status_code, 422)
        self.assertIn("互动剧数据不合法", response.json()["detail"])

    def test_a_broken_story_can_be_saved_and_says_what_is_wrong(self):
        response = self._save({"start": "a", "segments": [{"id": "a", "choices": [{"text": "未连"}]}]})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["analysis"]["ready"])
        self.assertIn("choice_unconnected", codes(response.json()["analysis"]["issues"]))

    def test_analyze_stores_nothing(self):
        response = self.client.post(f"{self.base}/analyze", json={"graph": _sample()})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertEqual(self.client.get(self.base).json()["revision"], 0)

    def test_someone_elses_project_does_not_exist(self):
        self.app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-2", "role": "user"}
        for response in (self.client.get(self.base), self._save(), self.client.get(f"{self.base}/export.html"), self.client.get(f"{self.base}/media")):
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.service.repo.get_task(self.task_id)["assets"].get(ASSET_KEY), None)

    def test_the_media_library_lists_what_the_project_has(self):
        body = self.client.get(f"{self.base}/media").json()
        self.assertEqual(body["shots"][0]["image_url"], "/media/shot1.png")
        self.assertEqual(body["shots"][0]["video_url"], "/media/clip1.mp4")
        self.assertEqual(body["shots"][0]["candidate_urls"], ["/media/clip1b.mp4"])
        self.assertEqual(body["shots"][0]["duration_s"], 8.0)
        self.assertEqual(body["shots"][1]["video_url"], None)
        self.assertEqual([item["video_url"] for item in body["films"]], ["/media/film.mp4"])

    def test_stored_markers_never_reach_the_picker(self):
        task = {"assets": {"4": [{"shot_id": 1, "image_url": "inline:image/png 12KB"}, {"shot_id": 2, "image_url": "data:image/png;base64,AA"}]}}
        self.assertEqual([item["image_url"] for item in project_media(task)["shots"]], [None, None])

    def test_a_segment_can_use_a_clip_of_this_project(self):
        response = self._save(_sample({"kind": "video", "url": "/media/clip1.mp4", "source": "clip", "shot_uid": 100101, "duration_s": 8}))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["graph"]["segments"][0]["media"]["url"], "/media/clip1.mp4")

    def test_a_segment_cannot_name_an_address_of_its_own(self):
        for url in ("https://169.254.169.254/latest/meta-data", "/media/elements/other-user.png", "/media/../../etc/passwd"):
            response = self._save(_sample({"kind": "image", "url": url}))
            self.assertEqual(response.status_code, 422, url)
            self.assertIn("本项目", response.json()["detail"])

    def test_a_clip_regenerated_later_does_not_block_saving(self):
        self._save(_sample({"kind": "video", "url": "/media/clip1.mp4"}))

        def regenerate(task):
            task["assets"]["5"][0]["video_url"] = "/media/clip1-new.mp4"
            task["assets"]["5"][0]["candidates"] = []
        self.service.repo.mutate_task(self.task_id, regenerate)
        self.assertEqual(self._save(_sample({"kind": "video", "url": "/media/clip1.mp4"}), base_revision=1).status_code, 200)

    def _upload(self, content, name="f.png", **data):
        return self.client.post(f"{self.base}/media", files={"file": (name, io.BytesIO(content), "application/octet-stream")}, data=data)

    def test_upload_goes_by_the_bytes_and_can_then_be_used(self):
        response = self._upload(MP4, "movie.bin", duration_s="12.5")
        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()
        self.assertEqual((record["kind"], record["duration_s"]), ("video", 12.5))
        self.assertTrue(record["url"].endswith(".mp4"))
        self.assertTrue((self.media_dir / os.path.basename(record["url"])).is_file())
        self.assertEqual(self._save(_sample({"kind": "video", "url": record["url"]})).status_code, 200)

    def test_upload_refuses_what_is_not_media(self):
        for content in (b"<svg onload=alert(1)>", b"<html>", b""):
            self.assertEqual(self._upload(content, "x.png").status_code, 422)
        self.assertEqual(list(self.media_dir.glob("istory_*")), [])

    def test_upload_refuses_an_oversized_image_and_leaves_no_file(self):
        with patch("app.service.interactive_story_service.MAX_IMAGE_UPLOAD_BYTES", 1024):
            response = self._upload(PNG, "x.png")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(list(self.media_dir.glob("istory_*")), [])

    def test_an_upload_in_use_cannot_be_deleted_and_a_free_one_can(self):
        record = self._upload(PNG, "x.png").json()
        self._save(_sample({"kind": "image", "url": record["url"]}))
        self.assertEqual(self.client.delete(f"{self.base}/media/{record['id']}").status_code, 409)
        self._save(_sample(), base_revision=1)
        body = self.client.delete(f"{self.base}/media/{record['id']}")
        self.assertEqual(body.status_code, 200)
        self.assertEqual(body.json()["uploads"], [])
        self.assertEqual(list(self.media_dir.glob("istory_*")), [])
        self.assertEqual(self.client.delete(f"{self.base}/media/{record['id']}").status_code, 404)

    def test_a_stored_url_cannot_choose_what_gets_deleted(self):
        record = self._upload(PNG, "x.png").json()

        def tamper(task):
            task["assets"][ASSET_KEY]["uploads"][0]["url"] = "/media/shot1.png"
        self.service.repo.mutate_task(self.task_id, tamper)
        self.assertEqual(self.client.delete(f"{self.base}/media/{record['id']}").status_code, 200)
        self.assertTrue((self.media_dir / "shot1.png").is_file())

    def test_playtests_count_without_moving_the_revision(self):
        self._save()
        steps = [{"segment": "a"}, {"segment": "b", "choice": "c1"}]
        response = self.client.post(f"{self.base}/playtest", json={"steps": steps, "ending": "b"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()["runs"], response.json()["routes_played"]), (1, 1))
        current = self.client.get(self.base).json()
        self.assertEqual(current["revision"], 1)
        self.assertEqual(current["stats"]["runs"], 1)
        self.assertEqual(self._save(base_revision=1).status_code, 200)
        self.assertEqual(self.client.delete(f"{self.base}/playtest").json()["runs"], 0)

    def test_a_playtest_with_no_story_is_a_404(self):
        self.assertEqual(self.client.post(f"{self.base}/playtest", json={"steps": []}).status_code, 404)

    def test_the_planner_endpoint_uses_the_projects_gateway(self):
        with patch.object(self.service.gateway, "call_llm", return_value=json.dumps(_good_plan(), ensure_ascii=False)) as call:
            response = self.client.post(f"{self.base}/plan", json={"brief": "雨夜里的一封信", "endings": 2})
        self.assertEqual(response.status_code, 200, response.text)
        call.assert_called_once()
        self.assertEqual(response.json()["draft"]["title"], "雨夜来客")
        self.assertEqual(self.client.get(self.base).json()["revision"], 0)

    def test_the_planner_says_so_when_the_model_gives_junk(self):
        with patch.object(self.service.gateway, "call_llm", return_value="不是 JSON"):
            response = self.client.post(f"{self.base}/plan", json={"brief": "雨夜里的一封信"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("没有给出可用的分支剧情", response.json()["detail"])

    def test_export_is_refused_while_the_story_is_broken(self):
        self._save({"start": "a", "segments": [{"id": "a", "choices": [{"text": "未连"}]}]})
        for path in ("export.html", "export.zip"):
            response = self.client.get(f"{self.base}/{path}")
            self.assertEqual(response.status_code, 422)
            self.assertIn("走不通", response.json()["detail"])
        self.assertFalse(self.client.get(f"{self.base}/export/preview").json()["ready"])

    def test_export_with_no_story_is_refused(self):
        self.assertEqual(self.client.get(f"{self.base}/export.html").status_code, 422)
        self.assertFalse(self.client.get(f"{self.base}/export/preview").json()["ready"])

    def test_preview_says_what_each_piece_of_media_will_do(self):
        data = _sample({"kind": "video", "url": "/media/clip1.mp4"})
        data["segments"][1]["media"] = {"kind": "image", "url": "/media/shot1.png"}
        self._save(data)
        rows = {row["segment_id"]: row for row in self.client.get(f"{self.base}/export/preview").json()["media"]}
        self.assertEqual((rows["a"]["status"], rows["a"]["size"]), ("local", len(MP4)))
        self.assertEqual(rows["b"]["status"], "local")

    def test_html_export_inlines_media_and_downloads_under_the_stories_name(self):
        self._save(_sample({"kind": "image", "url": "/media/shot1.png"}))
        response = self.client.get(f"{self.base}/export.html", params={"lang": "en"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "text/html; charset=utf-8")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertEqual(response.headers["content-disposition"], "attachment; filename=\"interactive-story.html\"; filename*=UTF-8''%E9%9B%A8%E5%A4%9C.html")
        body = response.text
        self.assertIn("data:image/png;base64,", body)
        self.assertNotIn("/media/shot1.png", body)
        self.assertIn('lang="en"', body)
        self.assertIn("Start watching", body)

    def test_html_leaves_out_a_video_too_big_to_inline(self):
        self._save(_sample({"kind": "video", "url": "/media/clip1.mp4"}))
        with patch("app.service.interactive_story_service.MAX_INLINE_BYTES", 16):
            page = self.client.get(f"{self.base}/export.html").text
        self.assertIn('"media":null', page)
        self.assertNotIn("clip1", page)
        self.assertIn("开场", page)

    def test_a_kind_that_does_not_match_the_bytes_is_not_embedded(self):
        self._save(_sample({"kind": "image", "url": "/media/clip1.mp4"}))
        self.assertIn('"media":null', self.client.get(f"{self.base}/export.html").text)

    def test_zip_carries_the_player_and_the_media(self):
        data = _sample({"kind": "video", "url": "/media/clip1.mp4"})
        data["segments"][1]["media"] = {"kind": "image", "url": "/media/shot1.png"}
        data["segments"][2]["media"] = {"kind": "video", "url": "/media/clip1.mp4"}
        self._save(data)
        response = self.client.get(f"{self.base}/export.zip")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            names = sorted(bundle.namelist())
            self.assertEqual(names, ["README.txt", "index.html", "media/0001.mp4", "media/0002.png"])
            self.assertEqual(bundle.read("media/0001.mp4"), MP4)
            page = bundle.read("index.html").decode("utf-8")
        self.assertIn("media/0001.mp4", page)
        self.assertNotIn("/media/clip1.mp4", page)
        self.assertEqual(self._temp_archives(), [])

    def _temp_archives(self):
        return [name for name in os.listdir(tempfile.gettempdir()) if name.startswith("istory_") and name.endswith(".zip")]

    def test_zip_lists_what_it_could_not_include_without_its_signature(self):
        data = _sample({"kind": "video", "url": "/media/clip1.mp4"})
        data["segments"][1]["media"] = {"kind": "video", "url": "https://cdn.example.com/a/clip.mp4?Signature=secret"}

        def add_clip(task):
            task["assets"]["5"][0]["candidates"] = ["https://cdn.example.com/a/clip.mp4?Signature=secret"]
        self.service.repo.mutate_task(self.task_id, add_clip)
        self._save(data)
        with patch.object(media_compositor, "_download", return_value=False) as fetch:
            response = self.client.get(f"{self.base}/export.zip")
        fetch.assert_called_once()
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            readme = bundle.read("README.txt").decode("utf-8")
            page = bundle.read("index.html").decode("utf-8")
        self.assertIn("clip.mp4", readme)
        self.assertNotIn("secret", readme)
        self.assertNotIn("secret", page)

    def test_remote_media_goes_through_the_guarded_download(self):
        # The compositor's _download is what refuses private hosts and re-checks each redirect.
        remote = "https://cdn.example.com/clip.mp4"

        def fake(url, destination, **_kwargs):
            Path(destination).write_bytes(MP4)
            return True

        def add_clip(task):
            task["assets"]["5"][0]["candidates"] = [remote]
        self.service.repo.mutate_task(self.task_id, add_clip)
        self._save(_sample({"kind": "video", "url": remote}))
        with patch.object(media_compositor, "_download", side_effect=fake) as fetch:
            response = self.client.get(f"{self.base}/export.zip")
        self.assertEqual(fetch.call_args.args[0], remote)
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            self.assertEqual(bundle.read("media/0001.mp4"), MP4)


NASTY = '</script><script>alert(1)</script><!-- <img src=x onerror=alert(2)> ]]> %%UI%% \u2028 "quoted" & \'single\''


class PlayerExportTests(unittest.TestCase):
    def _page(self, **fields):
        data = {
            "title": NASTY, "synopsis": NASTY, "start": "a", "variables": [{"id": "x", "label": NASTY[:40]}],
            "segments": [
                {"id": "a", "title": NASTY, "narration": NASTY, "dialogue": [{"speaker": NASTY[:60], "text": NASTY}], "choices": [
                    {"text": NASTY, "target": "b", "locked_hint": NASTY},
                ]},
                {"id": "b", "kind": "ending", "ending_label": NASTY[:60], "title": NASTY},
            ],
        }
        return story.render_player_html(story.player_story(story.parse_graph(data), {}), **fields), data

    def test_story_text_cannot_become_markup(self):
        page, _ = self._page()
        head, _, rest = page.partition("<body>")
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img", page)
        self.assertNotIn("<!-- <", page)
        # U+2028 ends a line for older script parsers; it only has to stay out of the scripts.
        self.assertNotIn("\u2028", rest)
        # Exactly the player's own elements, and each is closed once.
        self.assertEqual(rest.count("<script"), 4)
        self.assertEqual(rest.count("</script>"), 4)
        self.assertIn("&lt;/script&gt;", head)

    def test_a_token_in_the_story_stays_words(self):
        page, _ = self._page()
        self.assertEqual(page.count("var StoryEngine"), 1)
        self.assertIn("%%UI%%", page)

    def test_the_embedded_json_is_the_story_again(self):
        page, data = self._page()
        match = re.search(r'<script type="application/json" id="story-data">(.*?)</script>', page, re.S)
        parsed = json.loads(match.group(1))
        self.assertEqual(parsed["title"], NASTY)
        self.assertEqual(parsed["segments"][0]["dialogue"][0]["speaker"], NASTY[:60])
        self.assertEqual(parsed["segments"][0]["choices"][0]["text"], data["segments"][0]["choices"][0]["text"])

    def test_nothing_points_outside_the_file(self):
        page, _ = self._page()
        self.assertNotRegex(page, r"https?://")
        self.assertNotRegex(page, r"<(link|iframe|object|embed|base|img|video|audio)\b")
        self.assertNotIn("innerHTML", page)
        self.assertNotIn("eval(", page)
        self.assertNotIn("new Function", page)
        self.assertNotIn("fetch(", page)
        self.assertNotIn("XMLHttpRequest", page)
        self.assertIn("default-src &#x27;none&#x27;", page)
        self.assertNotIn("&#x27;self&#x27;", page)

    def test_only_the_bundle_may_read_files_beside_it(self):
        page, _ = self._page(bundled=True)
        self.assertIn("&#x27;self&#x27; file:", page)

    def test_storage_is_guarded_everywhere_it_is_touched(self):
        lines = story.PLAYER_UI_JS.splitlines()
        touched = [number for number, line in enumerate(lines) if "localStorage" in line]
        self.assertEqual(len(touched), 3)
        for number in touched:
            self.assertIn("try {", lines[number] + lines[number - 1], lines[number])

    def test_unknown_language_falls_back(self):
        page, _ = self._page(lang="<x>")
        self.assertIn('lang="zh-CN"', page)

    def test_only_safe_media_sources_survive(self):
        data = _sample({"kind": "video", "url": "/media/clip1.mp4"})
        parsed = story.parse_graph(data)
        for source, expected in (
            ("media/0001.mp4", True), ("data:video/mp4;base64,AAAA", True), ("data:image/png;base64,AAAA", True),
            ("javascript:alert(1)", False), ("data:text/html;base64,AAAA", False), ("data:image/svg+xml;base64,AAAA", False),
            ("https://evil.example/x.mp4", False), ("media/../../x", False), ("/media/clip1.mp4", False),
        ):
            result = story.player_story(parsed, {"/media/clip1.mp4": source})["segments"][0]["media"]
            self.assertEqual(result is not None, expected, source)

    def test_internal_details_are_not_exported(self):
        data = _sample({"kind": "video", "url": "/media/clip1.mp4", "source": "clip", "shot_uid": 100101, "label": "内部"})
        data["segments"][0]["position"] = {"x": 1, "y": 2}
        exported = story.player_story(story.parse_graph(data), {"/media/clip1.mp4": "media/0001.mp4"})
        self.assertNotIn("position", exported["segments"][0])
        self.assertEqual(exported["segments"][0]["media"], {"kind": "video", "src": "media/0001.mp4"})

    def test_saved_progress_survives_a_new_media_address_but_not_a_new_story(self):
        parsed = story.parse_graph(_sample({"kind": "video", "url": "/media/clip1.mp4"}))
        first = story.player_story(parsed, {"/media/clip1.mp4": "media/0001.mp4"})
        second = story.player_story(parsed, {"/media/clip1.mp4": "media/0002.mp4"})
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        changed = story.parse_graph({**_sample(), "title": "别的故事"})
        self.assertNotEqual(first["fingerprint"], story.player_story(changed, {})["fingerprint"])


@unittest.skipUnless(shutil.which("node"), "needs node to run the player's engine")
class PlayerEngineParityTests(unittest.TestCase):
    def _run(self, script):
        completed = subprocess.run(
            ["node", "-e", story.PLAYER_ENGINE_JS + "\n" + script], capture_output=True, text=True, timeout=30, check=True,
        )
        return json.loads(completed.stdout)

    def test_the_player_agrees_with_this_module_on_conditions(self):
        table = json.dumps([[condition, values] for condition, values, _ in CONDITION_TABLE])
        results = self._run(
            f"const rows = {table};"
            "console.log(JSON.stringify(rows.map(([condition, values]) => StoryEngine.evaluate(condition, new Map(Object.entries(values))))));"
        )
        self.assertEqual(results, [expected for _, _, expected in CONDITION_TABLE])

    def test_the_player_agrees_with_this_module_on_effects(self):
        variables = [{"id": "x", "kind": "number", "min": 0, "max": 10}, {"id": "y", "kind": "number", "min": None, "max": None}, {"id": "f", "kind": "flag", "min": None, "max": None}]
        by_id = {item["id"]: item for item in variables}
        cases = [
            ([add(0.1, "y"), add(0.2, "y")], {"x": 0, "y": 0, "f": False}),
            ([add(50)], {"x": 9, "y": 0, "f": False}),
            ([add(-50)], {"x": 9, "y": 0, "f": False}),
            ([{"var": "x", "op": "set", "value": 3}, add(1)], {"x": 9, "y": 0, "f": False}),
            ([{"var": "f", "op": "set", "value": True}], {"x": 0, "y": 0, "f": False}),
            ([{"var": "f", "op": "add", "value": 1}], {"x": 0, "y": 0, "f": False}),
            ([{"var": "ghost", "op": "add", "value": 1}], {"x": 0, "y": 0, "f": False}),
        ]
        payload = json.dumps([[effects, values] for effects, values in cases])
        results = self._run(
            f"const rows = {payload}; const defs = new Map({json.dumps(variables)}.map(v => [v.id, v]));"
            "console.log(JSON.stringify(rows.map(([effects, values]) => Object.fromEntries(StoryEngine.applyEffects(effects, new Map(Object.entries(values)), defs)))));"
        )
        self.assertEqual(results, [story.apply_effects(effects, values, by_id) for effects, values in cases])

    def test_the_player_resolves_a_segment_the_same_way(self):
        segment = {
            "id": "a", "kind": "scene", "timer": {"seconds": 5, "default_choice": "c-gated"},
            "routes": [{"id": "r1", "condition": gte(9), "target": "b"}],
            "choices": [
                {"id": "c-gated", "target": "b", "condition": gte(5), "when_locked": "lock"},
                {"id": "c-hidden", "target": "b", "condition": gte(5), "when_locked": "hide"},
                {"id": "c-open", "target": "b", "when_locked": "lock"},
                {"id": "c-nowhere", "target": "ghost", "when_locked": "lock"},
            ],
        }
        known = {"a": 1, "b": 1}
        script = (
            f"const s = {json.dumps(segment)}; const known = id => {json.dumps(list(known))}.includes(id);"
            "const out = [0, 5, 9].map(x => { const r = StoryEngine.nextStep(s, new Map([['x', x]]), known);"
            " return {kind: r.kind, open: r.options.filter(o => !o.locked).map(o => o.choice.id), shown: r.options.map(o => o.choice.id),"
            " timed: (StoryEngine.timedChoice(s, r.options) || {}).id || null}; });"
            "console.log(JSON.stringify(out));"
        )
        low, mid, high = self._run(script)
        self.assertEqual(low, {"kind": "choices", "open": ["c-open"], "shown": ["c-gated", "c-open"], "timed": "c-open"})
        self.assertEqual(mid, {"kind": "choices", "open": ["c-gated", "c-hidden", "c-open"], "shown": ["c-gated", "c-hidden", "c-open"], "timed": "c-gated"})
        self.assertEqual(high["kind"], "route")
        for x, row in ((0, low), (5, mid), (9, high)):
            outcome, detail = story.step(segment, {"x": x}, known)
            self.assertEqual(outcome, row["kind"])
            if outcome == "choices":
                self.assertEqual([item["id"] for item in detail], row["open"])


if __name__ == "__main__":
    unittest.main()


class CanvasHandoffTests(EndpointTests):
    def setUp(self):
        super().setUp()
        from app.repository.studio_repo import StudioRepository
        from app.service.studio_service import StudioService

        self.studio = StudioService(StudioRepository(Path(self.temp.name) / "studio.sqlite3"))
        patcher = patch("app.api.studio_api.get_studio_service", return_value=self.studio)
        patcher.start()
        self.addCleanup(patcher.stop)

    def canvas(self):
        project = self.studio.repository.project_for_task(self.task_id, "u-1", "x").id
        return self.studio.repository.get_canvas(project, "u-1")

    def test_a_segment_becomes_a_first_frame_and_a_video_node_and_nothing_runs(self):
        graph = _sample()
        segment = graph["segments"][0]
        segment["narration"] = "林晚推开老宅的门"
        self.assertEqual(self._save(graph).status_code, 200)
        response = self.client.post(f"{self.base}/segments/{segment['id']}/canvas")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body["nodes"]), {"frame", "clip"})
        self.assertFalse(body["bound"])
        canvas = self.canvas()
        kinds = {node.kind for node in canvas.nodes}
        self.assertEqual(kinds, {"image_gen", "video_gen"})
        self.assertEqual(len(canvas.edges), 1)
        self.assertEqual(canvas.edges[0].payload.get("role"), "first_frame")
        self.assertIn("林晚推开老宅的门", next(node.payload["prompt"] for node in canvas.nodes if node.kind == "image_gen"))

    def test_a_segment_showing_a_shot_binds_the_video_node_to_it(self):
        graph = _sample()
        segment = graph["segments"][0]
        segment["narration"] = "开门"
        segment["media"] = {"kind": "video", "url": "/media/clip1.mp4", "source": "shot", "shot_uid": 100101, "label": "", "duration_s": 8}
        self.assertEqual(self._save(graph).status_code, 200, self._save(graph).text)
        body = self.client.post(f"{self.base}/segments/{segment['id']}/canvas").json()
        self.assertTrue(body["bound"])
        video = next(node for node in self.canvas().nodes if node.kind == "video_gen")
        self.assertEqual(video.payload["params"]["binding"], {"sceneId": "E1S01", "shotId": 1})

    def test_an_empty_segment_and_a_missing_one_are_refused_in_words(self):
        graph = _sample()
        graph["segments"][0]["narration"] = ""
        graph["segments"][0]["dialogue"] = []
        self._save(graph)
        empty = self.client.post(f"{self.base}/segments/{graph['segments'][0]['id']}/canvas")
        self.assertEqual(empty.status_code, 422)
        self.assertIn("旁白", empty.json()["detail"])
        self.assertEqual(self.client.post(f"{self.base}/segments/nope/canvas").status_code, 404)

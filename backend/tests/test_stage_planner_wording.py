# -*- coding: utf-8 -*-
"""The rule planner says what ``stage_planner.json`` says, and names a pair the way the facing check reads it.

No model, no network. The wording table is checked against the planner's source in both directions
(every entry is read, every entry read is there with the placeholders it fills), and the words a pair
formation opens with come from ``stage_brief.json`` pair_relations for the planner and the check alike.
"""

import ast
import inspect
import string
import unittest
from unittest.mock import patch

from app.core import prompt_data
from app.core.spatial_stage import planner, validation
from app.core.spatial_stage.planner import build_plan, refresh
from tests.test_spatial_stage import _brief

_DATA = "stage_planner"
_READERS = ("_words", "_phrase")


def _paths(node: ast.Call) -> list[tuple[str, ...]]:
    """The key paths one ``_words(...)`` / ``_phrase(...)`` call reads; ``"a" if flag else "b"`` reads both."""
    paths: list[tuple[str, ...]] = [("formations",) if node.func.id == "_phrase" else ()]
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            paths = [(*path, arg.value) for path in paths]
        elif isinstance(arg, ast.IfExp) and all(
            isinstance(branch, ast.Constant) and isinstance(branch.value, str) for branch in (arg.body, arg.orelse)
        ):
            paths = [(*path, branch.value) for path in paths for branch in (arg.body, arg.orelse)]
        else:
            raise AssertionError(f"planner: a {node.func.id} key is not a literal at line {node.lineno}")
    return paths


def _calls() -> list[tuple[str, tuple[str, ...], frozenset[str]]]:
    """Every reader call in the planner: which reader, the key path and the placeholders it fills."""
    found = []
    tree = ast.parse(inspect.getsource(planner))
    # The readers themselves pass their key through; only their callers name entries.
    inner = {
        id(node) for reader in tree.body
        if isinstance(reader, ast.FunctionDef) and reader.name in _READERS for node in ast.walk(reader)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _READERS:
            if id(node) in inner:
                continue
            filled = frozenset(item.arg for item in node.keywords)
            found.extend((node.func.id, path, filled) for path in _paths(node))
    return found


def _leaves(section: dict, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], object]:
    leaves: dict[tuple[str, ...], object] = {}
    for key, value in section.items():
        if isinstance(value, dict):
            leaves.update(_leaves(value, (*prefix, key)))
        else:
            leaves[(*prefix, key)] = value
    return leaves


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _strings(module) -> set[str]:
    return {
        node.value for node in ast.walk(ast.parse(inspect.getsource(module)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _pair(text: str):
    return build_plan(_brief(text=text, characters=["沈砚", "黄琰"], shots=[]))


def _averted(plan):
    return refresh(plan.model_copy(update={"actors": [actor.model_copy(update={"yaw_deg": 0.0}) for actor in plan.actors]}))


def _facing_check(plan):
    return next(check for check in plan.checks if check.code == "spatial_facing_partner")


class PlannerWordingTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)

    def test_every_entry_in_the_table_is_read_and_every_one_read_is_there(self):
        table = _leaves({key: value for key, value in self.data.items() if key != "_about"})
        calls = _calls()
        asked = {path for _, path, _ in calls}
        self.assertEqual(set(table) - asked, set(), "entries nothing in the planner reads")
        self.assertEqual(asked - set(table), set(), "entries the planner reads that are missing")

    def test_every_formation_sentence_gets_the_placeholders_it_names(self):
        phrases = [(path, filled) for reader, path, filled in _calls() if reader == "_phrase"]
        self.assertTrue(phrases)
        for path, filled in phrases:
            template = self.data[path[0]][path[1]]
            self.assertEqual(filled, _fields(template), ".".join(path))

    def test_every_separation_rule_has_its_words_distance_and_name(self):
        source = _strings(planner)
        for rule in self.data["separation_rules"]:
            self.assertEqual(set(rule), {"words", "metres", "label"})
            self.assertTrue(rule["words"])
        self.assertTrue({"words", "metres", "label"} <= source, "the planner reads each field of a rule")
        self.assertEqual(set(self.data["default_separation"]), {"metres", "label"})

    def test_the_names_other_modules_import_are_the_table_itself(self):
        self.assertEqual(planner.EMPTY_CAST, frozenset(self.data["empty_cast"]))
        self.assertEqual(planner.CROWD_MARKERS, tuple(self.data["crowd_markers"]))
        reasons = self.data["reasons"]
        self.assertEqual(planner.ENTRANCE_REASON, reasons["entrance"])
        self.assertEqual(planner.APPROACH_REASON, reasons["approach"])
        self.assertEqual(planner.RETREAT_REASON, reasons["retreat"])

    def test_no_table_word_is_still_written_into_the_planner(self):
        source = _strings(planner)
        words = {
            str(value) for value in _leaves({key: value for key, value in self.data.items() if key != "_about"}).values()
            if isinstance(value, str) and value
        }
        for value in self.data.values():
            if isinstance(value, list):
                words.update(str(item) for item in value if isinstance(item, str) and item)
        for rule in self.data["separation_rules"]:
            words.update([*rule["words"], rule["label"]])
        self.assertEqual(words & source, set())


class PairRelationTests(unittest.TestCase):
    def setUp(self):
        self.relations = prompt_data.value("stage_brief", "pair_relations")

    def test_the_planner_and_the_check_read_the_same_facing_word(self):
        self.assertEqual(validation.pair_relation("facing"), self.relations["facing"])
        self.assertTrue(_pair("沈砚与黄琰对峙。").formation.startswith(self.relations["facing"]))
        self.assertTrue(_pair("沈砚与黄琰并肩而行。").formation.startswith(self.relations["side_by_side"]))
        # Neither module keeps its own copy of the words.
        for module in (planner, validation):
            self.assertFalse({self.relations["facing"], self.relations["side_by_side"]} & _strings(module), module.__name__)

    def test_rewording_the_facing_word_moves_the_planner_and_the_check_together(self):
        before = self.relations["facing"]
        with patch.dict(self.relations, {"facing": "相向而立"}):
            facing = _pair("沈砚与黄琰对峙。")
            self.assertTrue(facing.formation.startswith("相向而立"))
            self.assertTrue(_facing_check(facing).passed)
            self.assertFalse(_facing_check(_averted(facing)).passed)
            # A formation still in the old words is no longer read as a facing pair.
            stale = _averted(facing.model_copy(update={"formation": before + facing.formation[len("相向而立"):]}))
            self.assertTrue(_facing_check(stale).passed)

    def test_a_side_by_side_pair_is_not_held_to_facing_each_other(self):
        side = _pair("沈砚与黄琰并肩而行。")
        self.assertTrue(_facing_check(_averted(side)).passed)
        self.assertFalse(_facing_check(_averted(_pair("沈砚与黄琰对峙。"))).passed)


if __name__ == "__main__":
    unittest.main()

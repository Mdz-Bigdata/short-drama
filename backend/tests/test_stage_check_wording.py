# -*- coding: utf-8 -*-
"""The spatial checks, their repairs and the stage scorer say what ``stage_checks.json`` says.

No model, no network. The wording table is checked against the code that reads it in both
directions: every sentence in the table is used, every sentence the code asks for is there with
the placeholders it fills, and every check the stage runs has its pass and fail sentences.
"""

import ast
import copy
import inspect
import string
import unittest
from unittest.mock import patch

from app.core import prompt_data
from app.core.spatial_stage import build_plan, repair, scoring, validation
from app.core.spatial_stage.operations import apply_operations
from app.schema.spatial_stage import SpatialRepair
from tests.test_spatial_stage import _brief

_DATA = "stage_checks"
# Each reader and the section of the table it reads; a reader's key path is its leading string arguments.
_READERS = {validation: "checks", repair: "repairs", scoring: "scores"}
# Its sentences were data before this table existed and other tests reword them there.
_SET_CLEARANCE = "spatial_set_clearance"


def _calls(module) -> list[tuple[tuple[str, ...], frozenset[str]]]:
    """Every ``_says(...)`` in ``module``: the key path it names and the placeholders it fills."""
    found = []
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_says":
            path = []
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    path.append(arg.value)
                elif isinstance(arg, ast.IfExp):
                    # ``"a" if flag else "b"``: both keys are read.
                    for branch in (arg.body, arg.orelse):
                        found.append(((*path, branch.value), frozenset(item.arg for item in node.keywords)))
                    path = None
                    break
                else:
                    raise AssertionError(f"{module.__name__}: a _says key is not a literal at line {node.lineno}")
            if path is not None:
                found.append((tuple(path), frozenset(item.arg for item in node.keywords)))
    return found


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _leaves(section: dict, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], str]:
    leaves: dict[tuple[str, ...], str] = {}
    for key, value in section.items():
        if isinstance(value, dict):
            leaves.update(_leaves(value, (*prefix, key)))
        else:
            leaves[(*prefix, key)] = value
    return leaves


class WordingTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)

    def test_every_sentence_in_the_table_is_used_and_every_one_asked_for_is_there(self):
        self.assertEqual(set(self.data), set(_READERS.values()))
        for module, section in _READERS.items():
            table = _leaves({key: value for key, value in self.data[section].items() if key != "labels"})
            calls = _calls(module)
            asked = {path for path, _ in calls}
            self.assertEqual(set(table) - asked, set(), f"{section}: sentences nothing reads")
            self.assertEqual(asked - set(table), set(), f"{section}: sentences {module.__name__} reads that are missing")
            for path, filled in calls:
                self.assertEqual(filled, _fields(table[path]), f"{section}.{'.'.join(path)}: placeholders")

    def test_every_repair_has_a_label_and_every_label_a_repair(self):
        labels = self.data["repairs"]["labels"]
        self.assertEqual(set(labels), set(repair._HANDLERS))
        self.assertEqual(repair.LABELS, labels)
        self.assertEqual(repair.LABELS[_SET_CLEARANCE], "绕开布景")
        # The repairs endpoint refuses a longer label, so a reworded one has to stay within it.
        room = SpatialRepair.model_fields["label"].metadata[0].max_length
        for label in (*labels.values(), self.data["repairs"]["unhandled"]):
            self.assertLessEqual(len(label), room, label)

    def test_every_check_has_its_pass_and_fail_sentences(self):
        codes = {check.code for check in build_plan(_brief()).checks}
        # The contact check only runs on a stage with contacts: a recorder lying on the desk gives it one.
        codes |= {check.code for check in build_plan(_brief(props=["黄绫", "炭盆", "录音笔"])).checks}
        sentences = self.data["checks"]
        self.assertEqual(set(sentences), codes - {_SET_CLEARANCE})
        for code in codes - {_SET_CLEARANCE}:
            self.assertTrue(sentences[code].get("passed"), code)
            self.assertTrue(sentences[code].get("failed"), code)
        brief = prompt_data.load("stage_brief")
        self.assertTrue(brief["set_clearance_passed"])
        self.assertTrue(brief["set_clearance_failed"])


class RewordedTableTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(_brief())
        shen = self.plan.actor("沈砚").position
        self.stacked = apply_operations(self.plan, [{"op": "move_actor", "name": "内侍", "position": [shen[0] + 0.1, shen[1]]}])

    def _reworded(self):
        data = copy.deepcopy(prompt_data.load(_DATA))
        spacing = data["checks"]["spatial_actor_spacing"]
        spacing.update(pair="{first}/{second}={gap:.1f}", failed="挤：{findings}", passed="站位都好。")
        data["repairs"]["spacing"] = "推开{names}（{target:g}）"
        data["scores"]["unchanged"] = "持平"
        load = prompt_data.load
        return patch.object(prompt_data, "load", side_effect=lambda name: data if name == _DATA else load(name))

    def test_a_check_says_what_the_table_says(self):
        with self._reworded():
            clear = {check.code: check for check in validation.check_plan(self.plan)}
            crowded = {check.code: check for check in validation.check_plan(self.stacked)}
        self.assertEqual(clear["spatial_actor_spacing"].detail, "站位都好。")
        self.assertEqual(crowded["spatial_actor_spacing"].detail, "挤：沈砚/内侍=0.1")

    def test_a_repair_and_a_score_say_what_the_table_says(self):
        with self._reworded():
            proposal = next(item for item in repair.propose(self.stacked) if item.code == "spatial_actor_spacing")
            score = scoring.score_plan(self.plan)
            line = scoring.compare(score, score)
        self.assertEqual(proposal.detail, "推开沈砚、内侍（0.5）")
        self.assertIn("（持平）", line)

    def test_a_longer_fail_sentence_still_fits_a_crowded_scene(self):
        # Thirty extras on one spot give far more findings than a detail holds; the code cuts them to fit.
        extra = self.plan.actor("内侍")
        shen = self.plan.actor("沈砚").position
        crowd = self.plan.model_copy(update={"actors": [*self.plan.actors, *(
            extra.model_copy(update={"name": f"群演{index}", "position": [shen[0] + 0.01 * index, shen[1]]}) for index in range(30)
        )]})
        tail = "人物会穿模重叠，" * 20 + "请拉开站位。"
        data = copy.deepcopy(prompt_data.load(_DATA))
        data["checks"]["spatial_actor_spacing"]["failed"] = "{findings}，" + tail
        load = prompt_data.load
        with patch.object(prompt_data, "load", side_effect=lambda name: data if name == _DATA else load(name)):
            detail = next(check.detail for check in validation.check_plan(crowd) if check.code == "spatial_actor_spacing")
        self.assertLessEqual(len(detail), 2000)
        self.assertTrue(detail.endswith(tail), detail[-40:])
        self.assertTrue(detail.startswith("沈砚与"), detail[:40])


if __name__ == "__main__":
    unittest.main()

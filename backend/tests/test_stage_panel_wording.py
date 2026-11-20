# -*- coding: utf-8 -*-
"""The stage's panel sentences (prompting.py), the clip brief (clip_brief.py) and the screen words
(projection.py) say what ``stage_panel.json`` and ``stage_brief.json`` say.

No model, no network. The tables are checked against the code that reads them in both directions:
every sentence in the table is read, every sentence the code asks for is there with exactly the
placeholders it fills, and none of the three modules writes a Chinese word of its own.
"""

import ast
import copy
import inspect
import itertools
import re
import string
import unittest
from typing import get_args
from unittest.mock import patch

from app.core import frame_position, prompt_data
from app.core.spatial_stage import build_plan, clip_brief, projection, prompting
from app.core.spatial_stage.coverage import SIZE_RANK, canonical_size
from app.core.spatial_stage.models import Crossing, ScreenSide
from tests.test_spatial_stage import _brief

_PANEL = "stage_panel"
_BRIEF = "stage_brief"
# The sections of stage_brief.json these modules added; the rest of that table belongs to other readers.
_BRIEF_SECTIONS = ("marks", "frame_sides", "clip_lines")
# (module, accessor) -> (table, key prefix the accessor's path starts under, whether it fills a template).
_READERS = {
    (prompting, "_say"): (_PANEL, (), True),
    (prompting, "_entry"): (_PANEL, (), False),
    (prompting, "_brief"): (_BRIEF, (), False),
    (projection, "_entry"): (_PANEL, ("projection",), False),
    (clip_brief, "_say"): (_BRIEF, ("clip_lines",), True),
    (clip_brief, "_brief"): (_BRIEF, (), False),
}
_ACCESSORS = frozenset(accessor for _, accessor in _READERS) | {"_line"}
# Chinese string literals the three modules may still carry, with the reason. Docstrings and comments
# are prose about the code, not prompt wording, and are not literals the check looks at.
_ALLOWED_LITERALS: dict[str, str] = {}
_CHINESE = re.compile(r"[　-〿一-鿿＀-￯→…°]")


def _alternatives(node: ast.AST, module) -> list[str]:
    """The literal keys an argument can be: a string, or each branch of ``a if flag else b``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _alternatives(node.body, module) + _alternatives(node.orelse, module)
    raise AssertionError(f"{module.__name__}: a wording key is not a literal at line {node.lineno}")


def _nodes(node: ast.AST):
    """Every node of ``node`` except inside the accessors themselves, which pass a path along unread."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef) and child.name in _ACCESSORS:
            continue
        yield child
        yield from _nodes(child)


def _calls(module, accessor: str) -> list[tuple[tuple[str, ...], frozenset[str]]]:
    """Every ``accessor(...)`` in ``module``: each key path it can name and the placeholders it fills."""
    found = []
    for node in _nodes(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == accessor:
            filled = frozenset(item.arg for item in node.keywords)
            for path in itertools.product(*(_alternatives(arg, module) for arg in node.args)):
                found.append((tuple(path), filled))
    return found


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _leaves(section, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if isinstance(section, dict):
        return set().union(*(_leaves(value, (*prefix, key)) for key, value in section.items())) if section else set()
    return {prefix}


def _at(data, path: tuple[str, ...]):
    for key in path:
        data = data[key]
    return data


def _chinese_literals(module) -> list[tuple[int, str]]:
    tree = ast.parse(inspect.getsource(module))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
        and _CHINESE.search(node.value) and node.value not in _ALLOWED_LITERALS
    ]


class WordingTableTests(unittest.TestCase):
    def setUp(self):
        self.tables = {_PANEL: prompt_data.load(_PANEL), _BRIEF: prompt_data.load(_BRIEF)}

    def _read(self) -> dict[str, set[tuple[str, ...]]]:
        read: dict[str, set[tuple[str, ...]]] = {_PANEL: set(), _BRIEF: set()}
        for (module, accessor), (table, prefix, fills) in _READERS.items():
            calls = _calls(module, accessor)
            self.assertTrue(calls, f"{module.__name__}.{accessor} reads nothing")
            for path, filled in calls:
                full = (*prefix, *path)
                try:
                    entry = _at(self.tables[table], full)
                except (KeyError, TypeError):
                    self.fail(f"{module.__name__} reads {table}.{'.'.join(full)}, which is missing")
                if fills:
                    self.assertIsInstance(entry, str, f"{table}.{'.'.join(full)}")
                    self.assertEqual(filled, _fields(entry), f"{table}.{'.'.join(full)}: placeholders")
                read[table].add(full)
        return read

    def test_every_entry_asked_for_is_there_with_the_placeholders_it_fills(self):
        self._read()

    def test_every_entry_in_the_tables_is_read(self):
        read = self._read()
        panel = {leaf for leaf in _leaves(self.tables[_PANEL]) if leaf[0] != "_about"}
        brief = {leaf for leaf in _leaves(self.tables[_BRIEF]) if leaf[0] in _BRIEF_SECTIONS}
        for table, leaves in ((_PANEL, panel), (_BRIEF, brief)):
            unread = {leaf for leaf in leaves if not any(leaf[: len(path)] == path for path in read[table])}
            self.assertEqual(unread, set(), f"{table}: entries nothing reads")

    def test_the_word_tables_read_by_key_hold_every_key(self):
        panel = self.tables[_PANEL]
        self.assertEqual(set(panel["axis"]["crossings"]), set(get_args(Crossing)) - {"none"})
        self.assertEqual(set(panel["bearing_sides"]), {"left", "right"})
        self.assertEqual(set(panel["screen_sides"]), {"left", "right", "centre"})
        self.assertEqual(set(panel["bible"]["sides"]), {"left", "right"})
        self.assertEqual(set(panel["table"]["sides"]), set(get_args(ScreenSide)))
        self.assertEqual(
            set(panel["projection"]["depth_layers"]),
            {"near_foreground", "foreground", "midground", "middle_distance", "background"},
        )
        self.assertEqual(set(panel["projection"]["facings"]), {"to_lens", "away", "right", "left"})
        self.assertEqual(set(self.tables[_BRIEF]["frame_sides"]), {"outside", "left", "right", "centre"})
        # Word tables carry no placeholders; the body marks carry the person's name and nothing else.
        for words in (panel["bearing_sides"], panel["screen_sides"], panel["axis"]["crossings"], panel["bible"]["sides"],
                      panel["table"]["sides"], panel["projection"]["depth_layers"], panel["projection"]["facings"]):
            for word in words.values():
                self.assertEqual(_fields(word), frozenset(), word)
        shares = [share for share, _ in panel["scale"]["body_marks"]]
        self.assertEqual(shares, sorted(shares, reverse=True), "body marks are compared from the top down")
        for _, mark in panel["scale"]["body_marks"]:
            self.assertEqual(_fields(mark), {"name"}, mark)
        for _, words in panel["scale"]["heads_words"]:
            self.assertEqual(_fields(words), frozenset(), words)

    def test_the_lens_clause_pattern_finds_the_lens_clause(self):
        blocking = self.tables[_PANEL]["blocking"]
        clause = blocking["lens_clause"].format(name="沈砚", reach=2.345, height=1.5)
        marks = self.tables[_BRIEF]["marks"]
        text = marks["clause"].join(["沈砚在左", clause, "门在右"])
        self.assertEqual(prompting.without_camera_pose(text), marks["clause"].join(["沈砚在左", "门在右"]))
        self.assertEqual(prompting.without_camera_pose(clause + marks["clause"] + "门在右"), "门在右")


class ScreenVocabularyTests(unittest.TestCase):
    """The screen words are the frame-position grammar, and the shot sizes the solver's enum."""

    def setUp(self):
        self.projection = prompt_data.load(_PANEL)["projection"]

    def test_screen_words_are_ones_the_frame_position_parser_reads(self):
        regions = [label for _, label in self.projection["regions"]] + [self.projection["region_right"]]
        self.assertEqual(set(regions) - set(frame_position.REGIONS), set())
        self.assertEqual(set(self.projection["depth_layers"].values()) - set(frame_position.DEPTHS), set())
        self.assertEqual(set(self.projection["facings"].values()) - set(frame_position.FACINGS), set())
        sides = prompt_data.load(_BRIEF)["frame_sides"]
        self.assertEqual({sides["left"], sides["right"], sides["centre"]} - set(frame_position.REGIONS), set())
        edges = [edge for edge, _ in self.projection["regions"]]
        self.assertEqual(edges, sorted(edges), "regions are compared left to right")

    def test_shot_sizes_are_the_names_the_camera_solver_matches(self):
        names = [name for name, _ in projection.SHOT_SIZE_HEIGHTS]
        self.assertEqual(names, [name for name, _ in self.projection["shot_sizes"]])
        for name in names:
            self.assertEqual(canonical_size(name), name)
        self.assertEqual(set(SIZE_RANK), set(names))
        heights = [height for _, height in projection.SHOT_SIZE_HEIGHTS]
        self.assertEqual(heights, sorted(heights), "tightest first: the solver ranks sizes by this order")
        self.assertTrue(all(isinstance(height, float) for height in heights))


class NoWordsInCodeTests(unittest.TestCase):
    def test_no_chinese_string_literal_is_left_in_the_three_modules(self):
        for module in (prompting, clip_brief, projection):
            self.assertEqual(_chinese_literals(module), [], module.__name__)


class RewordedTableTests(unittest.TestCase):
    """A sentence changed in the table is the sentence the stage writes: nothing is cached in code."""

    def _reworded(self, **changes):
        tables = {name: copy.deepcopy(prompt_data.load(name)) for name in (_PANEL, _BRIEF)}
        for dotted, value in changes.items():
            table, *path = dotted.split("__")
            target = tables[table]
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
        load = prompt_data.load
        return patch.object(prompt_data, "load", side_effect=lambda name: tables.get(name) or load(name))

    def test_panel_sentences_follow_the_table(self):
        plan = build_plan(_brief())
        shot = plan.shot(1)
        camera = plan.camera(shot.camera_id)
        with self._reworded(
            stage_panel__axis__relation="轴：{source}/{target}，{left}左{right}右",
            stage_panel__camera__holds="{move}·不动",
            stage_panel__bible__head="【圣经】{place}。",
            stage_brief__marks__clause="|",
        ):
            text = prompting.shot_text(plan, shot, camera)
            bible = prompting.scene_bible(plan)
        self.assertTrue(text.action_axis.startswith("轴：沈砚/黄琰，"), text.action_axis)
        self.assertIn("|", text.action_axis)
        self.assertTrue(text.camera_end.endswith("·不动"), text.camera_end)
        self.assertTrue(bible.startswith("【圣经】文思阁 / 夜 / 内景。"), bible)

    def test_clip_lines_and_screen_words_follow_the_table(self):
        plan = build_plan(_brief())
        with self._reworded(
            stage_brief__clip_lines__height="高{centimetres:.0f}{build}",
            stage_brief__marks__label="=",
            stage_panel__projection__facings={"to_lens": "面向镜头", "away": "背对镜头", "right": "朝右", "left": "朝左"},
        ):
            lines = clip_brief.shot_lines(plan, 1)
            facings = {state.facing for state in projection.screen_states(plan.actors, plan.camera(plan.shot(1).camera_id))}
        person = next(line for line in lines if line.startswith("人物="))
        self.assertIn("高170", person)
        self.assertTrue(facings & {"朝右", "朝左"}, facings)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""The storyboard prompt builders say what their wording tables say.

``panel_still_prompt`` reads ``panel_still.json`` and ``storyboard_prompt_detail`` reads
``storyboard_prompt_detail.json``. No model, no network. Each table is checked against the code
that reads it in both directions: every entry in the table is read, every entry the code asks
for is there, every template is filled with exactly the placeholders it names, and no Chinese
text is left written in either module (docstrings and comments are not prompt text).
"""

import ast
import inspect
import re
import string
import unittest
from collections.abc import Iterator
from unittest.mock import patch

from app.core import panel_still_prompt, prompt_data, storyboard_prompt_detail
from app.core.storyboard_prompt_detail import compile_storyboard_prompt_detail
from app.schema.production import NineGridStoryboard, StoryAssetCatalog
from tests.test_panel_still_prompt import _contract, _prompt
from tests.test_storyboard_prompt_detail import _panel

_CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
# Chinese string literals each module may still carry, with the reason it is not wording.
_ALLOWED_LITERALS: dict[str, dict[str, str]] = {"panel_still_prompt": {}, "storyboard_prompt_detail": {}}
# The sub-tables read one entry at a time through a helper: helper name -> sub-table.
_HELPERS = {
    "panel_still_prompt": {"_says": "says", "_word": "words", "_label": "labels", "_mark": "marks", "_pattern": "patterns"},
    "storyboard_prompt_detail": {"_says": "says", "_mark": "marks", "_pattern": "patterns"},
}
# Entries of panel_still's older grouped tables that are regular expressions, not sentences: their
# braces are repetition counts (``\d{4,5}``), never placeholders.
_PANEL_REGEXES = {"technique.ratio", "technique.temperature"}
_DATA = {"panel_still_prompt": "panel_still", "storyboard_prompt_detail": "storyboard_prompt_detail"}
_MODULES = {"panel_still_prompt": panel_still_prompt, "storyboard_prompt_detail": storyboard_prompt_detail}


def _tree(name: str) -> ast.Module:
    return ast.parse(inspect.getsource(_MODULES[name]))


def _callers(name: str) -> ast.Module:
    """The module without the reading helpers themselves (they take the key as a variable)."""
    tree = _tree(name)
    helpers = {"_fixed", *_HELPERS[name]}
    tree.body = [node for node in tree.body if not (isinstance(node, ast.FunctionDef) and node.name in helpers)]
    return tree


def _fields(template: str) -> frozenset[str]:
    return frozenset(field for _, field, _, _ in string.Formatter().parse(template) if field)


def _literal(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _helper_calls(name: str) -> Iterator[tuple[str, str, frozenset[str], int]]:
    """Every ``_says("k", a=...)`` / ``_word("k")`` / ...: the sub-table, the key, the placeholders filled, the line."""
    helpers = _HELPERS[name]
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in helpers:
            key = _literal(node.args[0]) if len(node.args) == 1 else None
            if key is None:
                raise AssertionError(f"{name}: a {node.func.id} key is not a single literal at line {node.lineno}")
            yield helpers[node.func.id], key, frozenset(item.arg for item in node.keywords), node.lineno


def _is_data(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "_DATA"


def _top_level_reads(name: str) -> set[str]:
    """``_fixed("k")``, ``prompt_data.f(_DATA, "k")`` and ``prompt_data.load(_DATA)["k"]``."""
    keys: set[str] = set()
    for node in ast.walk(_callers(name)):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "_fixed":
                key = _literal(node.args[0]) if node.args else None
                if key is None:
                    raise AssertionError(f"{name}: a _fixed key is not a literal at line {node.lineno}")
                keys.add(key)
            elif (
                isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "prompt_data"
                and node.func.attr != "load" and len(node.args) >= 2 and _is_data(node.args[0])
            ):
                key = _literal(node.args[1])
                if key is None:
                    raise AssertionError(f"{name}: a prompt_data key is not a literal at line {node.lineno}")
                keys.add(key)
        elif (
            isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "load" and node.value.args and _is_data(node.value.args[0])
        ):
            key = _literal(node.slice)
            if key is None:
                raise AssertionError(f"{name}: a load(_DATA)[...] key is not a literal at line {node.lineno}")
            keys.add(key)
    return keys


def _fixed_entry_reads() -> list[tuple[str, ast.AST, int, ast.Call | None, dict[str, list[str]]]]:
    """Entries of panel_still's grouped tables read by subscript: ``_fixed("t")["k"]`` and ``v = _fixed("t")`` then ``v["k"]``.

    Yields the table, the key node (a literal, an f-string, a choice of literals or a loop variable over
    literals), the line, the ``str(...).format(...)`` call that fills it if any, and the module's loop variables.
    """
    found: list[tuple[str, ast.AST, int, ast.Call | None, dict[str, list[str]]]] = []
    tree = _callers("panel_still_prompt")
    formats: dict[int, ast.Call] = {}
    for node in ast.walk(tree):
        # str(<entry>).format(...)
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"
            and isinstance(node.func.value, ast.Call) and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "str" and node.func.value.args
        ):
            formats[id(node.func.value.args[0])] = node
    loops: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.comprehension)) and isinstance(node.target, ast.Name) and isinstance(node.iter, (ast.Tuple, ast.List)):
            values = [_literal(item) for item in node.iter.elts]
            if all(value is not None for value in values):
                loops.setdefault(node.target.id, []).extend(values)
    aliases: dict[str, str | None] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "_fixed"
        ):
            table = _literal(node.value.args[0])
            if aliases.get(node.targets[0].id, table) != table:
                raise AssertionError(f"{node.targets[0].id} names two tables (line {node.lineno})")
            aliases[node.targets[0].id] = table
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        if isinstance(node.value, ast.Name) and node.value.id in aliases:
            table = aliases[node.value.id]
        elif isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "_fixed":
            table = _literal(node.value.args[0])
        else:
            continue
        found.append((table, node.slice, node.lineno, formats.get(id(node)), loops))
    return found


def _matches(key: ast.AST, table: dict, loops: dict[str, list[str]]) -> list[str]:
    """The table entries a subscript key can name; an empty list when one of the names it can take is missing."""
    literal = _literal(key)
    if literal is not None:
        return [literal] if literal in table else []
    if isinstance(key, ast.IfExp):
        either = [_matches(key.body, table, loops), _matches(key.orelse, table, loops)]
        return [*either[0], *either[1]] if all(either) else []
    if isinstance(key, ast.Name) and key.id in loops:
        return list(loops[key.id]) if all(value in table for value in loops[key.id]) else []
    if isinstance(key, ast.JoinedStr):
        shape = "".join(re.escape(part.value) if isinstance(part, ast.Constant) else ".+" for part in key.values)
        return [entry for entry in table if re.fullmatch(shape, entry)]
    raise AssertionError(f"unexpected key {ast.dump(key)}")


class WordingTableTests(unittest.TestCase):
    def test_every_entry_a_helper_asks_for_is_there_and_every_one_is_asked_for(self):
        for name in _MODULES:
            data = prompt_data.load(_DATA[name])
            asked: dict[str, set[str]] = {table: set() for table in _HELPERS[name].values()}
            for table, key, _, _ in _helper_calls(name):
                asked[table].add(key)
            if name == "panel_still_prompt":
                # The step pattern is a template: it is filled with the step name before it is compiled.
                asked["patterns"].add("step")
            for table, keys in asked.items():
                with self.subTest(module=name, table=table):
                    self.assertEqual(keys - set(data[table]), set(), "entries the module reads that are missing")
                    self.assertEqual(set(data[table]) - keys, set(), "entries nothing reads")

    def test_every_top_level_entry_is_read_and_every_one_read_is_there(self):
        for name in _MODULES:
            with self.subTest(module=name):
                table = {key for key in prompt_data.load(_DATA[name]) if not key.startswith("_")}
                read = _top_level_reads(name) | set(_HELPERS[name].values())
                self.assertEqual(read - table, set(), "entries the module reads that are missing")
                self.assertEqual(table - read, set(), "entries nothing reads")

    def test_each_sentence_gets_exactly_the_placeholders_it_names(self):
        for name in _MODULES:
            data = prompt_data.load(_DATA[name])
            for table, key, filled, line in _helper_calls(name):
                if table == "says":
                    with self.subTest(module=name, key=key):
                        self.assertEqual(filled, _fields(data["says"][key]), f"says.{key} (line {line}): placeholders")
                else:
                    self.assertEqual(filled, frozenset(), f"{table}.{key} (line {line}) is used as it stands")

    def test_the_grouped_sentences_of_panel_still_are_there_and_filled_exactly(self):
        data = prompt_data.load("panel_still")
        reads = _fixed_entry_reads()
        self.assertTrue(reads)
        for table, key, line, call, loops in reads:
            with self.subTest(table=table, line=line):
                entries = _matches(key, data[table], loops)
                self.assertTrue(entries, f"{table}[{ast.unparse(key)}] (line {line}) names nothing in the table")
                for entry in entries:
                    if table == "patterns" or f"{table}.{entry}" in _PANEL_REGEXES:
                        re.compile(str(data[table][entry]).format(part="x") if entry == "step" else str(data[table][entry]))
                        continue
                    fields = _fields(str(data[table][entry]))
                    if call is not None:
                        self.assertEqual(frozenset(item.arg for item in call.keywords), fields, f"{table}.{entry} (line {line})")
                    elif table not in ("says", "patterns"):
                        self.assertEqual(fields, frozenset(), f"{table}.{entry} (line {line}) is used unfilled")

    def test_every_template_formats_and_plain_text_has_no_braces(self):
        for name in _MODULES:
            data = prompt_data.load(_DATA[name])
            for key, template in data["says"].items():
                with self.subTest(module=name, key=key):
                    template.format(**{field: "x" for field in _fields(template)})
            for table in ("words", "labels", "marks"):
                for key, word in data.get(table, {}).items():
                    self.assertIsInstance(word, str, f"{table}.{key}")
                    self.assertNotIn("{", word, f"{table}.{key}")

    def test_the_patterns_compile(self):
        for name in _MODULES:
            for key, pattern in prompt_data.load(_DATA[name])["patterns"].items():
                with self.subTest(module=name, key=key):
                    re.compile(pattern.format(part="主动作") if key == "step" else pattern)
        self.assertEqual(_fields(prompt_data.load("panel_still")["patterns"]["step"]), {"part"})

    def test_the_word_tables_are_lists_of_words(self):
        for name, keys in (
            ("panel_still", ("nobody", "no_asset", "no_line", "says_nothing")),
            ("storyboard_prompt_detail", ("empty_names", "narration_markers", "inner_markers", "damage_terms", "crowd_markers", "far_sound_terms", "mid_sound_terms")),
        ):
            for key in keys:
                words = prompt_data.load(name)[key]
                self.assertIsInstance(words, list, f"{name}.{key}")
                self.assertTrue(all(isinstance(word, str) for word in words), f"{name}.{key}")
        # A lone 血 would match names such as 血碑 and invite stains the script never wrote.
        self.assertTrue(all(len(term) > 1 for term in prompt_data.load("storyboard_prompt_detail")["damage_terms"]))

    def test_no_chinese_string_literal_is_left_in_either_module(self):
        for name in _MODULES:
            tree = _tree(name)
            docstrings = {
                id(node.body[0].value) for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.body and isinstance(node.body[0], ast.Expr) and _literal(node.body[0].value) is not None
            }
            left = sorted({
                node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and _CJK.search(node.value) and id(node) not in docstrings
            } - set(_ALLOWED_LITERALS[name]))
            with self.subTest(module=name):
                self.assertEqual(left, [])


class SaysWhatTheTableSaysTests(unittest.TestCase):
    def _reworded(self, name: str, **says: str):
        table = prompt_data.load(name)
        reworded = {**table, "says": {**table["says"], **says}}
        original = prompt_data.load
        return patch.object(prompt_data, "load", lambda wanted: reworded if wanted == name else original(wanted))

    def test_a_reworded_panel_sentence_reaches_the_prompt(self):
        with self._reworded("panel_still", no_extra_holding="手里空着", absent="别让{name}入画"):
            prompt = _prompt(_contract(subject_action="沈砚抬头望月", props=["本格无额外道具"]), absent=["周叔"])
        self.assertIn("持有物与接触点：手里空着。", prompt)
        self.assertIn("别让周叔入画", prompt)

    def test_a_reworded_detail_sentence_reaches_the_page(self):
        board = NineGridStoryboard(
            title="天牢月光", assets=StoryAssetCatalog(characters=["沈砚"], scenes=["天牢"], props=["铁链"], effects=["月光尘埃"]),
            panels=[_panel(1), _panel(2)],
        )
        with self._reworded("storyboard_prompt_detail", stability="机位锁死不动", prop_initial_position="{name}放在第1格的位置"):
            foundation = compile_storyboard_prompt_detail(board, script_text="沈砚抬头望月", visual_style="写实").foundation
        self.assertEqual(foundation["camera_design"]["stability"], "机位锁死不动")
        self.assertIn("石子放在第1格的位置", foundation["scene_and_props"]["props"][0]["initial_position"])

    def test_the_default_episode_is_the_one_in_the_table(self):
        default = inspect.signature(compile_storyboard_prompt_detail).parameters["episode"].default
        self.assertEqual(default, prompt_data.load("storyboard_prompt_detail")["says"]["default_episode"])


if __name__ == "__main__":
    unittest.main()

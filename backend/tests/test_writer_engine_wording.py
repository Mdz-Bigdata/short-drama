# -*- coding: utf-8 -*-
"""The screenwriting engine, the script breakdown, the interactive story, the writer board and the submission pack say
what their wording tables say.

No model, no network. Each module is checked against its table in ``app/data/prompt`` in both
directions: every key the module reads is in the table, every entry of the table is read, every
template is filled with exactly the placeholders it names (and every log line gets as many values
as it has %-fields), the entries whose order means something keep it, and no Chinese text is left
written in the module outside docstrings and comments.
"""

from __future__ import annotations

import ast
import inspect
import re
import string
import unittest
from typing import Any

from app.core import interactive_story, prompt_data, script_breakdown, submission_pack, writer_dashboard
from app.core.screenwriting import engine

# module → its wording table.
TABLES = {
    "screenwriting_engine": engine,
    "script_breakdown": script_breakdown,
    "interactive_story": interactive_story,
    "writer_dashboard": writer_dashboard,
    "submission_pack": submission_pack,
}
# The helpers that read a table: the first argument is the dotted key (``_log`` reads under ``log.``).
_READERS = {"_says", "_word", "_table", "_pattern", "_entry", "_log"}
_HELPER_DEFINITIONS = _READERS | {"_template"}
_CJK = re.compile(r"[⺀-鿿豈-﫿︰-﹏＀-￯　-〿“”‘’·…—–～]")
# Chinese string literals the modules may still carry, by (table, assigned name), each with the reason it is not wording.
_ALLOWED_LITERALS: dict[tuple[str, str], str] = {
    ("interactive_story", "PLAYER_UI_JS"): (
        "the exported player's JavaScript source, not wording: its only non-ASCII text is the ' · ' that joins an "
        "ending's badge to its label; every word the player shows comes from player_text"
    ),
}
_PERCENT_FIELD = re.compile(r"%[-#0 +]*\d*(?:\.\d+)?[sdrfgi]")


def _tree(module) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _helper_bodies(tree: ast.Module) -> set[int]:
    """ids of every node inside the helpers' own definitions (where the key is a variable)."""
    inside: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _HELPER_DEFINITIONS:
            inside.update(id(child) for child in ast.walk(node))
    return inside


def _reads(module) -> list[tuple[str, str, ast.Call]]:
    """Every read of the table: (helper, dotted key, the call)."""
    tree = _tree(module)
    skip = _helper_bodies(tree)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _READERS) or id(node) in skip:
            continue
        first = node.args[0] if node.args else None
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            raise AssertionError(f"{module.__name__}: a {node.func.id} key is not a literal at line {node.lineno}")
        key = f"log.{first.value}" if node.func.id == "_log" else first.value
        found.append((node.func.id, key, node))
    return found


def _lookup(table: dict, key: str) -> Any:
    node: Any = table
    for part in key.split("."):
        node = node[part]
    return node


def _template(entry: Any) -> str:
    return "\n".join(str(line) for line in entry) if isinstance(entry, list) else str(entry)


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _uncovered(node: Any, path: str, read: set[str]) -> list[str]:
    """Entries of the table no read reaches: a read covers its whole subtree, a section is covered when all its entries are."""
    if path in read:
        return []
    if isinstance(node, dict):
        return [missing for key, child in node.items() for missing in _uncovered(child, f"{path}.{key}" if path else key, read)]
    return [path]


def _assigned_name(tree: ast.Module, target_node: ast.AST) -> str:
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)) and any(node is target_node for node in ast.walk(statement)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            return ",".join(target.id for target in targets if isinstance(target, ast.Name))
    return ""


def _docstrings(tree: ast.Module) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


class EveryTableTests(unittest.TestCase):
    def test_every_key_read_is_in_the_table(self):
        for name, module in TABLES.items():
            table = prompt_data.load(name)
            for helper, key, call in _reads(module):
                with self.subTest(table=name, key=key, line=call.lineno):
                    _lookup(table, key)

    def test_every_entry_of_the_table_is_read(self):
        for name, module in TABLES.items():
            table = {key: value for key, value in prompt_data.load(name).items() if key != "_about"}
            read = {key for _helper, key, _call in _reads(module)}
            with self.subTest(table=name):
                self.assertEqual(_uncovered(table, "", read), [], "entries nothing reads")
            with self.subTest(table=name, about=True):
                self.assertTrue(str(prompt_data.load(name).get("_about") or "").strip(), "the table says what it is for")

    def test_each_template_gets_exactly_the_placeholders_it_names(self):
        for name, module in TABLES.items():
            table = prompt_data.load(name)
            for helper, key, call in _reads(module):
                if helper != "_says":
                    continue
                with self.subTest(table=name, key=key, line=call.lineno):
                    if len(call.args) != 1 or any(keyword.arg is None for keyword in call.keywords):
                        raise AssertionError("a template is filled by name only")
                    filled = frozenset(keyword.arg for keyword in call.keywords)
                    self.assertEqual(filled, _fields(_template(_lookup(table, key))))

    def test_words_read_as_they_stand_carry_no_placeholder(self):
        for name, module in TABLES.items():
            table = prompt_data.load(name)
            for helper, key, call in _reads(module):
                if helper != "_word":
                    continue
                with self.subTest(table=name, key=key):
                    value = _lookup(table, key)
                    self.assertIsInstance(value, str)
                    self.assertEqual(_fields(value), frozenset())

    def test_every_pattern_compiles(self):
        for name, module in TABLES.items():
            table = prompt_data.load(name)
            for helper, key, _call in _reads(module):
                if helper == "_pattern" or key.startswith("patterns."):
                    with self.subTest(table=name, key=key):
                        re.compile(_lookup(table, key))

    def test_every_log_line_gets_as_many_values_as_it_has_fields(self):
        for name, module in TABLES.items():
            table = prompt_data.load(name)
            for node in ast.walk(_tree(module)):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "logger" and node.args):
                    continue
                first = node.args[0]
                if isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id == "_log":
                    key = f"log.{first.args[0].value}"
                    with self.subTest(table=name, key=key, line=node.lineno):
                        self.assertEqual(len(_PERCENT_FIELD.findall(_lookup(table, key))), len(node.args) - 1)
                elif isinstance(first, ast.Constant):
                    with self.subTest(table=name, line=node.lineno):
                        self.assertIsNone(_CJK.search(first.value), "a log line written in the module")

    def test_no_chinese_string_literal_is_left_in_the_modules(self):
        for name, module in TABLES.items():
            tree = _tree(module)
            docstrings = _docstrings(tree)
            left = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings and _CJK.search(node.value):
                    if (name, _assigned_name(tree, node)) in _ALLOWED_LITERALS:
                        continue
                    left.append((node.lineno, node.value[:40]))
            with self.subTest(table=name):
                self.assertEqual(left, [])

    def test_every_allowed_literal_is_still_there(self):
        for (name, assigned), reason in _ALLOWED_LITERALS.items():
            with self.subTest(table=name, name=assigned):
                self.assertTrue(reason)
                self.assertTrue(_CJK.search(getattr(TABLES[name], assigned)), "drop the allowance once the literal is gone")


class EngineWordingTests(unittest.TestCase):
    def setUp(self):
        self.table = prompt_data.load("screenwriting_engine")

    def test_the_repair_ask_names_the_reasons_before_the_draft(self):
        lines = self.table["repair_section"]
        self.assertTrue(lines[0].startswith("## "))
        self.assertLess(lines.index("{reasons}"), lines.index("{previous}"))
        text = engine._repair_section({"reasons": ["一", "二"], "plan": {"title": "旧"}})
        self.assertIn("- 一\n- 二\n", text)
        self.assertTrue(text.endswith('{"title": "旧"}'))

    def test_the_preview_stages_are_the_stages_that_have_a_preview(self):
        self.assertEqual(set(self.table["preview_stages"]), {"prose", "visual"} & set(engine.PROMPT_STAGES))

    def test_errors_read_as_the_engine_raises_them(self):
        error = engine.RepairNotImproved(3, ["甲", "乙"])
        self.assertEqual(str(error), self.table["errors"]["repair_not_improved"].format(episode=3, reasons="甲; 乙"))
        with self.assertRaises(ValueError) as raised:
            engine._own_episode_inputs([{"text": "一段文字。", "source_kind": "outline"}])
        self.assertIn("'outline'", str(raised.exception))


class BreakdownWordingTests(unittest.TestCase):
    def setUp(self):
        self.table = prompt_data.load("script_breakdown")

    def test_element_kinds_keep_the_standard_order_and_every_kind_has_a_label(self):
        self.assertEqual(
            [kind for kind, _label in script_breakdown.ELEMENT_KINDS],
            ["extra", "stunt", "vehicle", "prop", "effect", "look", "set_dressing", "product"],
        )
        self.assertEqual(set(self.table["element_labels"]), {kind for kind, _label in script_breakdown.ELEMENT_KINDS})

    def test_coded_tables_are_keyed_by_the_codes_the_module_compares(self):
        self.assertEqual(set(self.table["side_words"]), {"INT", "EXT", "INT/EXT"})
        self.assertEqual(set(self.table["side_short_words"]), {"INT", "EXT"})
        self.assertEqual(set(self.table["side_labels"]), {"INT", "EXT", "INT/EXT"})
        self.assertEqual(set(self.table["day_night_labels"]), {"DAY", "NIGHT"})
        self.assertEqual(set(self.table["strip_labels"]), set(script_breakdown._STRIP_COLOURS.values()))
        # The full heading words are matched before the one-character ones.
        self.assertEqual(list(script_breakdown._SIDES.values()), ["INT", "EXT", "INT/EXT", "INT", "EXT"])

    def test_every_markdown_row_has_as_many_cells_as_its_header(self):
        markdown = self.table["markdown"]
        for table_key, row_key in (("strips_table", "strip_row"), ("cast_table", "cast_row"), ("elements_table", "element_row")):
            with self.subTest(table=table_key):
                header, rule = markdown[table_key]
                self.assertEqual(header.count("|"), rule.count("|"))
                self.assertEqual(header.count("|"), markdown[row_key].count("|"))

    def test_the_csv_header_has_one_column_per_cell_of_a_row(self):
        breakdown = script_breakdown.compile_breakdown({"config": {}, "assets": {}}, [
            {"scene_id": "E1S01", "content": "内景：书房 - 夜 林晚推门。", "description": "林晚推门。", "duration": "8s", "characters": ["林晚"], "label": ""},
        ])
        header, row = [line.split(",") for line in script_breakdown.render_csv(breakdown).lstrip("﻿").splitlines()]
        self.assertEqual(len(header), len(row))
        self.assertEqual(header[: len(self.table["csv_header"])], self.table["csv_header"])


class StoryWordingTests(unittest.TestCase):
    def setUp(self):
        self.table = prompt_data.load("interactive_story")

    def test_every_player_language_has_every_word_the_player_reads(self):
        read = set(re.findall(r"\btext\.([A-Za-z]+)", interactive_story.PLAYER_UI_JS))
        languages = self.table["player_text"]
        self.assertIn("zh-CN", languages)
        for lang, words in languages.items():
            with self.subTest(lang=lang):
                self.assertEqual(set(words), set(languages["zh-CN"]))
                self.assertLessEqual(read, set(words))
        self.assertEqual(interactive_story.PLAYER_TEXT, languages)

    def test_the_unreachable_reasons_are_keyed_by_the_reason_codes_the_issue_carries(self):
        self.assertEqual(set(self.table["unreachable_reasons"]), {"conditions", "no_path"})

    def test_issue_templates_name_only_what_the_issue_params_carry(self):
        params = {"segment", "variable", "text", "target", "count", "reason", "values", "label", "possible", "segments"}
        for key, template in self.table["issues"].items():
            with self.subTest(key=key):
                self.assertLessEqual(_fields(template), params)


class BoardWordingTests(unittest.TestCase):
    def setUp(self):
        self.table = prompt_data.load("writer_dashboard")

    def test_chinese_episode_numbers_read_through_the_table(self):
        digits = self.table["episode_digits"]
        self.assertEqual(sorted(digits.values()), list(range(1, 10)))
        ten = self.table["ten"]
        one, two = (digit for digit, value in digits.items() if value in (1, 2))
        self.assertEqual(writer_dashboard.episode_label_number(ten), 10)
        self.assertEqual(writer_dashboard.episode_label_number(ten + two), 12)
        self.assertEqual(writer_dashboard.episode_label_number(two + ten + one), 21)

    def test_the_phases_run_from_the_opening_to_the_ending(self):
        phases = self.table["phases"]
        self.assertEqual(len(phases), 5)
        events = writer_dashboard._fallback_events([{"content": f"场{index}"} for index in range(5)])
        self.assertEqual([event["phase"] for event in events], phases)

    def test_the_label_words_are_never_taken_for_names(self):
        for word in [*self.table["non_speakers"], *self.table["label_morphemes"]]:
            with self.subTest(word=word):
                self.assertFalse(writer_dashboard.is_character_name(word))


if __name__ == "__main__":
    unittest.main()

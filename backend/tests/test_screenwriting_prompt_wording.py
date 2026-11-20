# -*- coding: utf-8 -*-
"""The screenwriting prompts say what ``screenwriting_prompts.json`` says.

No model, no network. The wording table is checked against the code that reads it in both
directions: every entry in the table is read, every entry the code asks for is there with
exactly the placeholders it fills, and no Chinese text is left written in the module.
"""

import ast
import inspect
import re
import string
import unittest

from app.core import prompt_data
from app.core.screenwriting import prompts

_DATA = "screenwriting_prompts"
_CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
# Chinese string literals prompts.py may still carry, each with the reason it is not wording.
_ALLOWED_LITERALS: dict[str, str] = {
    "＜": "neutralize_tags swaps it in for '<' so source text can never open a prompt tag: a structural escape, not wording",
    "＞": "neutralize_tags swaps it in for '>' so source text can never close a prompt tag: a structural escape, not wording",
}
_READERS = ("_says", "_template", "_table")


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(prompts))


def _docstrings(tree: ast.Module) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _reads() -> list[tuple[str, str, frozenset[str], int]]:
    """Every ``_says`` / ``_template`` / ``_table`` call: the reader, the key, the placeholders it fills, and its line."""
    tree = _tree()
    # The readers themselves pass their key on (``_says`` calls ``_template(key)``): those calls are not reads.
    inside_readers = {
        id(inner) for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in (*_READERS, "_entry")
        for inner in ast.walk(node)
    }
    found = []
    for node in ast.walk(tree):
        if id(node) in inside_readers:
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _READERS:
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)) or len(node.args) != 1:
                raise AssertionError(f"a {node.func.id} key is not a single literal at line {node.lineno}")
            if any(item.arg is None for item in node.keywords):
                raise AssertionError(f"{node.func.id} at line {node.lineno} fills its template from a ** mapping")
            found.append((node.func.id, first.value, frozenset(item.arg for item in node.keywords), node.lineno))
    return found


def _entry(key: str):
    node = prompt_data.load(_DATA)
    for part in key.split("."):
        node = node[part]
    return node


def _template(entry) -> str:
    return "\n".join(entry) if isinstance(entry, list) else entry


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _leaves(node, prefix: str = ""):
    """Every dotted path of the table down to a value that is not a section (``_about`` notes left out)."""
    for key, value in node.items():
        if key.startswith("_"):
            continue
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            yield path
            yield from _leaves(value, f"{path}.")
        else:
            yield path


class WordingTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)
        self.reads = _reads()

    def test_every_key_read_is_in_the_table(self):
        for reader, key, _, line in self.reads:
            with self.subTest(key=key, line=line):
                try:
                    _entry(key)
                except (KeyError, TypeError):
                    self.fail(f"{reader}({key!r}) at line {line} names nothing in {_DATA}.json")

    def test_every_entry_of_the_table_is_read(self):
        read = {key for _, key, _, _ in self.reads}
        sections = {path for path in _leaves(self.data) if isinstance(_entry(path), dict) and path not in read}
        unread = []
        for path in _leaves(self.data):
            if path in sections:
                continue
            if not any(path == key or path.startswith(f"{key}.") for key in read):
                unread.append(path)
        self.assertEqual(unread, [], "entries nothing reads")

    def test_each_template_gets_exactly_the_placeholders_it_names(self):
        for reader, key, filled, line in self.reads:
            if reader != "_says":
                continue
            with self.subTest(key=key, line=line):
                entry = _entry(key)
                self.assertTrue(isinstance(entry, str) or (isinstance(entry, list) and all(isinstance(row, str) for row in entry)), key)
                self.assertEqual(filled, _fields(_template(entry)), f"{key} (line {line}): placeholders")

    def test_every_template_formats(self):
        for reader, key, _, _ in self.reads:
            if reader == "_table":
                continue
            template = _template(_entry(key))
            with self.subTest(key=key):
                template.format(**{name: 1.5 for name in _fields(template)})

    def test_tables_are_tables(self):
        for reader, key, _, line in self.reads:
            if reader == "_table":
                self.assertIsInstance(_entry(key), (dict, list), f"{key} (line {line})")
        self.assertEqual(set(self.data["common"]["languages"]), {"zh", "en", "vi"})
        low, high = self.data["prose"]["length_per_shot"]
        self.assertTrue(0 < low < high)

    def test_no_chinese_string_literal_is_left_in_the_module(self):
        tree = _tree()
        docstrings = _docstrings(tree)
        left = sorted({
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings and _CJK.search(node.value)
        } - set(_ALLOWED_LITERALS))
        self.assertEqual(left, [])


class ReadsTheTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)

    def test_module_constants_come_from_the_table(self):
        self.assertEqual(prompts.USER_INSTRUCTIONS_HEADER, self.data["common"]["user_instructions_header"])
        self.assertEqual(prompts.OUTPUT_LANGUAGES, self.data["common"]["languages"])
        self.assertEqual(prompts.OMITTED_MARK, self.data["common"]["omitted_mark"])
        self.assertIn("{count}", prompts.OMITTED_MARK)

    def test_the_builders_write_the_tables_sentences(self):
        overview = prompts.build_overview_prompt("原文", source_kind="novel")
        self.assertTrue(overview.startswith(self.data["overview"]["task_novel"]))
        inventory = prompts.build_asset_inventory_prompt("原文", source_kind="screenplay", overview=None, existing={"props": ["金针"]})
        self.assertIn(self.data["asset_inventory"]["relation_rules"], inventory)
        self.assertIn("- 已登记道具：金针", inventory)
        plan = prompts.build_script_plan_prompt(
            source_text="正文", source_kind="outline", episode=2, overview=None, style="", characters={}, scenes={}, props={},
            supported_durations=[5, 10], default_duration=None, episode_target_seconds=None, episode_outline=None,
            next_episode_outline=None,
        )
        self.assertIn("`E2S{两位序号}` 格式（如 E2S01）", plan)
        self.assertIn(self.data["script_plan"]["task_director_plan"], plan)
        with self.assertRaises(ValueError) as raised:
            prompts.build_script_plan_prompt(
                source_text="", source_kind="novel", episode=1, overview=None, style="", characters={}, scenes={}, props={},
                supported_durations=[], default_duration=None, episode_target_seconds=None, episode_outline=None, next_episode_outline=None,
            )
        self.assertEqual(str(raised.exception), self.data["script_plan"]["no_durations"])
        low, high = self.data["prose"]["length_per_shot"]
        self.assertIn(f"{low * 2}–{high * 2}", prompts._prose_length_rule(2, "zh"))


if __name__ == "__main__":
    unittest.main()

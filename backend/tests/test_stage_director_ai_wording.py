# -*- coding: utf-8 -*-
"""The AI director and the blockout reader say what ``stage_director_ai.json`` and ``stage_blockout.json`` say.

No model, no network. Each wording table is checked against the module that reads it in both
directions: every entry in the table is read, every one the module asks for is there, each
sentence template gets exactly the placeholders it names, and no Chinese string literal is left
in the module (comments and docstrings may stay Chinese; they are not sent anywhere).
"""

import ast
import inspect
import re
import string
import unittest
from pathlib import Path

from app.core import prompt_data
from app.core.spatial_stage import blockout, director_ai
from app.core.spatial_stage.director_ai import Scope

_CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
_LOG_FIELD = re.compile(r"%[-#0 +]*\d*(?:\.\d+)?[sdifrx]")

# Chinese string literals a module may still carry, each with the reason it is not wording.
_ALLOWED_LITERALS: dict[str, dict[str, str]] = {"director_ai": {}, "blockout": {}}

# (module, its table, the top-level entries that are structured rather than text)
_MODULES = (
    (director_ai, "stage_director_ai", {"strategies", "skill_routes"}),
    (blockout, "stage_blockout", set()),
)


def _short(module) -> str:
    return module.__name__.rsplit(".", 1)[-1]


def _tree(module) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _literal_key(node: ast.Call, helper: str) -> str:
    first = node.args[0] if node.args else None
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        raise AssertionError(f"a {helper} key is not a literal at line {node.lineno}")
    return first.value


def _calls(module, helper: str) -> list[ast.Call]:
    return [
        node for node in ast.walk(_tree(module))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == helper
    ]


def _says_calls(module) -> list[tuple[str, frozenset[str], int]]:
    """Every ``_says(...)``: the key it names, the placeholders it fills, and its line."""
    found = []
    for node in _calls(module, "_says"):
        if len(node.args) != 1 or any(item.arg is None for item in node.keywords):
            raise AssertionError(f"a _says call at line {node.lineno} must name one key and fill values by keyword")
        found.append((_literal_key(node, "_says"), frozenset(item.arg for item in node.keywords), node.lineno))
    return found


def _top_level_reads(module) -> set[str]:
    """The top-level entries a module reads: ``_text("k")`` and ``prompt_data.f(_WORDING, "k")``."""
    keys = {_literal_key(node, "_text") for node in _calls(module, "_text")}
    for node in ast.walk(_tree(module)):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "prompt_data" and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name) and node.args[0].id == "_WORDING"
        ):
            if isinstance(node.args[1], ast.Name) and node.args[1].id == "key":
                continue  # the body of the ``_text`` helper itself
            if not isinstance(node.args[1], ast.Constant):
                raise AssertionError(f"a prompt_data key is not a literal at line {node.lineno}")
            keys.add(node.args[1].value)
    if _says_calls(module):
        keys.add("says")
    if _calls(module, "_log"):
        keys.add("logs")
    return keys


def _log_calls(module) -> list[tuple[str, int, int]]:
    """Every ``logger.<level>(_log("k"), *args)``: the key, how many values it passes, and its line."""
    found = []
    for node in ast.walk(_tree(module)):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger" and node.args and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name) and node.args[0].func.id == "_log"
        ):
            found.append((_literal_key(node.args[0], "_log"), len(node.args) - 1, node.lineno))
    if len(found) != len(_calls(module, "_log")):
        raise AssertionError(f"{_short(module)}: a _log line is used outside a logger call")
    return found


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _docstring_nodes(tree: ast.Module) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and ast.get_docstring(node) is not None:
            found.add(id(node.body[0].value))
    return found


class WordingTableTests(unittest.TestCase):
    def test_every_entry_in_each_table_is_read_and_every_one_read_is_there(self):
        for module, name, _structured in _MODULES:
            with self.subTest(table=name):
                table = set(prompt_data.load(name)) - {"_about"}
                read = _top_level_reads(module)
                self.assertEqual(table - read, set(), "entries nothing reads")
                self.assertEqual(read - table, set(), f"entries {_short(module)}.py reads that are missing")

    def test_every_sentence_in_each_table_is_used_and_every_one_asked_for_is_there(self):
        for module, name, _structured in _MODULES:
            with self.subTest(table=name):
                says = prompt_data.load(name)["says"]
                asked = {key for key, _, _ in _says_calls(module)}
                self.assertEqual(set(says) - asked, set(), "sentences nothing reads")
                self.assertEqual(asked - set(says), set(), f"sentences {_short(module)}.py reads that are missing")

    def test_each_sentence_gets_exactly_the_placeholders_it_names(self):
        for module, name, _structured in _MODULES:
            says = prompt_data.load(name)["says"]
            for key, filled, line in _says_calls(module):
                with self.subTest(table=name, key=key):
                    self.assertEqual(filled, _fields(says[key]), f"{name}.says.{key} ({_short(module)}.py line {line}): placeholders")

    def test_every_sentence_formats(self):
        for _module, name, _structured in _MODULES:
            for key, template in prompt_data.load(name)["says"].items():
                with self.subTest(table=name, key=key):
                    self.assertIsInstance(template, str)
                    template.format(**{field: 1.5 for field in _fields(template)})

    def test_texts_used_as_they_stand_are_plain_non_empty_strings(self):
        # ``_text`` entries are never formatted, so the JSON examples in them keep single braces.
        for module, name, _structured in _MODULES:
            for key in {_literal_key(node, "_text") for node in _calls(module, "_text")}:
                with self.subTest(table=name, key=key):
                    value = prompt_data.load(name)[key]
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())

    def test_log_lines_take_exactly_the_values_the_logger_passes(self):
        logs = prompt_data.load("stage_director_ai")["logs"]
        calls = _log_calls(director_ai)
        self.assertEqual(set(logs), {key for key, _, _ in calls}, "log lines read and in the table")
        for key, values, line in calls:
            with self.subTest(key=key):
                self.assertEqual(len(_LOG_FIELD.findall(logs[key].replace("%%", ""))), values, f"logs.{key} (line {line})")

    def test_no_chinese_string_literal_is_left_in_either_module(self):
        for module, _name, _structured in _MODULES:
            with self.subTest(module=_short(module)):
                tree = _tree(module)
                docstrings = _docstring_nodes(tree)
                left = sorted({
                    node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
                    and _CJK.search(node.value)
                } - set(_ALLOWED_LITERALS[_short(module)]))
                self.assertEqual(left, [])


class StructuredEntriesTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load("stage_director_ai")

    def test_strategies_are_named_directions_enough_for_every_candidate(self):
        self.assertGreaterEqual(len(self.data["strategies"]), director_ai.MAX_CANDIDATES)
        for name, direction in self.data["strategies"]:
            self.assertTrue(name and direction)
        self.assertEqual(director_ai.STRATEGIES, tuple(tuple(item) for item in self.data["strategies"]))

    def test_skill_routes_name_headings_the_vendored_skills_have(self):
        root = director_ai._skills_dir()
        for route in self.data["skill_routes"]:
            with self.subTest(skill=route["skill"]):
                self.assertTrue(route["words"] and all(isinstance(word, str) and word for word in route["words"]))
                self.assertTrue(route["headings"])
                skill = Path(root) / route["skill"] / "SKILL.md"
                if not skill.exists():
                    continue
                text = skill.read_text(encoding="utf-8")
                for heading in route["headings"]:
                    self.assertTrue(director_ai._section(text, heading), f"{route['skill']}: ## {heading}")


class ReadsAsBeforeTests(unittest.TestCase):
    """The names other modules import are still built from the tables, and a few sentences still read the same."""

    def test_the_op_guide_lists_every_pose_preset_between_its_two_halves(self):
        data = prompt_data.load("stage_director_ai")
        self.assertTrue(director_ai.OP_GUIDE.startswith(data["op_guide_people"]))
        self.assertTrue(director_ai.OP_GUIDE.endswith(data["op_guide_set_and_lens"]))
        for preset, label in director_ai.POSE_PRESETS:
            self.assertIn(f"{preset}({label})", director_ai.OP_GUIDE)

    def test_a_scope_reads_as_before(self):
        self.assertEqual(Scope().describe(), "")
        self.assertEqual(
            Scope(names=("沈砚", "黄琰"), shot_id=2).describe(),
            "用户这次只选中了 对象：沈砚、黄琰；镜头：第 2 镜。只改这些，其他保持原样。",
        )

    def test_the_blockout_prompts_carry_the_piece_limit_the_width_and_the_hint(self):
        self.assertEqual(blockout.REFERENCE_CAMERA_LABEL, "参考机位")
        system, prompt = blockout.analysis_prompt("俯拍庭院", 24.5)
        self.assertEqual(system, prompt_data.text("stage_blockout", "system"))
        self.assertIn(f"总数控制在 {blockout.MAX_BLOCKOUT_PIECES} 块以内", prompt)
        self.assertTrue(prompt.endswith("\n\n操作者已知这个场地宽约 24.5 米：以此为准定比例。\n\n操作者的补充说明（只用来判断画面内容）：俯拍庭院"))
        _, text = blockout.text_prompt("一间书房", 6)
        self.assertTrue(text.endswith("宽约 6 米：以此为准定比例。\n\n场景描述：\n一间书房"))

    def test_refusals_read_as_before(self):
        with self.assertRaisesRegex(blockout.BlockoutError, "^有 2 个体块的字段不合法（需要 name、center:\\[x,z\\]、size:\\[宽,进深,高\\]）$"):
            blockout.read_pieces([{"name": "坏"}, {"name": "坏2"}])
        with self.assertRaisesRegex(director_ai.DirectorAIError, "^模型没有返回结果，舞台没有改动；请检查模型配置或稍后重试$"):
            director_ai.run_turn(director_ai_plan(), "往左", lambda system, user, tokens: None)


def director_ai_plan():
    from tests.test_stage_director import _plan

    return _plan()


if __name__ == "__main__":
    unittest.main()

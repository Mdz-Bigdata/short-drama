# -*- coding: utf-8 -*-
"""The storyboard director and the sd25 compiler say what their wording tables say.

No model, no network. ``storyboard_director.json`` and ``sd25_compiler.json`` are checked
against the code that reads them in both directions: every sentence, heading, word and table
in a file is read, every one the code asks for is there with exactly the placeholders it fills,
and no Chinese text is left written in either module outside docstrings and comments.
"""

import ast
import inspect
import re
import string
import typing
import unittest
from unittest.mock import patch

from app.core import prompt_data, sd25_compiler, storyboard_director
from app.core.sd25_compiler import Sd25PromptCompiler
from app.core.storyboard_director import StoryboardDirectorCompiler
from app.schema.production import Sd25Asset, Sd25AssetRole, Sd25CompileRequest, Sd25DialogueEntry
from app.schema.storyboard_director import StoryboardTimeBeat
from tests.test_storyboard_director import _request

_CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
# Each module: its wording file, and which helper reads which section of it. ``_says`` / ``_check``
# fill a template; ``_word`` / ``_heading`` use the entry as it stands.
_MODULES = {
    "storyboard_director": (storyboard_director, {"_says": "says", "_check": "checks", "_word": "words"}),
    "sd25_compiler": (sd25_compiler, {"_says": "says", "_word": "words", "_heading": "headings"}),
}
_FILLED = {"_says", "_check"}
# Chinese string literals the modules may still carry, each with the reason it is not wording.
_ACTION_PHASES = "the action_phase enum values of StoryboardTimeBeat (app/schema/storyboard_director.py); the beat model checks them"
_ALLOWED_LITERALS: dict[str, dict[str, str]] = {
    "storyboard_director": {phase: _ACTION_PHASES for phase in ("准备", "开始", "发展", "峰值", "结果", "收束")},
    "sd25_compiler": {},
}


def _tree(module) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _is_wording(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "_WORDING"


def _helper_calls(module, helper: str) -> list[tuple[str, frozenset[str], int]]:
    """Every ``helper("key", ...)``: the key it names, the placeholders it fills, and its line."""
    found = []
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == helper:
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)) or len(node.args) != 1:
                raise AssertionError(f"a {helper} key is not a single literal at line {node.lineno}")
            found.append((first.value, frozenset(item.arg for item in node.keywords), node.lineno))
    return found


def _top_level_reads(module) -> set[str]:
    """Top-level keys read: ``prompt_data.f(_WORDING, "k")`` and ``prompt_data.load(_WORDING)["k"]``."""
    keys: set[str] = set()
    for node in ast.walk(_tree(module)):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "prompt_data"
            and len(node.args) >= 2 and _is_wording(node.args[0])
        ):
            if not isinstance(node.args[1], ast.Constant):
                raise AssertionError(f"a prompt_data key is not a literal at line {node.lineno}")
            keys.add(node.args[1].value)
        elif (
            isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "load"
            and node.value.args and _is_wording(node.value.args[0])
        ):
            if not isinstance(node.slice, ast.Constant):
                raise AssertionError(f"a wording section is not a literal at line {node.lineno}")
            keys.add(node.slice.value)
    return keys


def _template(entry) -> str:
    return "\n".join(entry) if isinstance(entry, list) else entry


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name is not None)


def _docstrings(tree: ast.Module) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


class WordingTableTests(unittest.TestCase):
    def test_every_entry_in_a_section_is_read_and_every_one_read_is_there(self):
        for name, (module, helpers) in _MODULES.items():
            data = prompt_data.load(name)
            for helper, section in helpers.items():
                with self.subTest(file=name, section=section):
                    asked = {key for key, _, _ in _helper_calls(module, helper)}
                    self.assertEqual(set(data[section]) - asked, set(), "entries nothing reads")
                    self.assertEqual(asked - set(data[section]), set(), "entries the module reads that are missing")

    def test_each_template_gets_exactly_the_placeholders_it_names(self):
        for name, (module, helpers) in _MODULES.items():
            data = prompt_data.load(name)
            for helper in _FILLED & set(helpers):
                for key, filled, line in _helper_calls(module, helper):
                    with self.subTest(file=name, key=key):
                        template = _template(data[helpers[helper]][key])
                        self.assertEqual(filled, _fields(template), f"{helpers[helper]}.{key} (line {line}): placeholders")

    def test_every_template_formats(self):
        for name, (_module, helpers) in _MODULES.items():
            data = prompt_data.load(name)
            for helper in _FILLED & set(helpers):
                for key, entry in data[helpers[helper]].items():
                    with self.subTest(file=name, key=key):
                        if isinstance(entry, list):
                            self.assertTrue(all(isinstance(line, str) for line in entry))
                        template = _template(entry)
                        self.assertTrue(template)
                        template.format(**{field: 1.5 for field in _fields(template)})

    def test_words_and_headings_are_plain_text(self):
        # Used as they stand, never formatted: a brace in one would reach the prompt as written.
        for name, (_module, helpers) in _MODULES.items():
            data = prompt_data.load(name)
            for helper in set(helpers) - _FILLED:
                for key, word in data[helpers[helper]].items():
                    with self.subTest(file=name, key=key):
                        self.assertIsInstance(word, str)
                        self.assertTrue(word)
                        self.assertNotIn("{", word)
                        self.assertNotIn("}", word)

    def test_every_top_level_entry_is_read_and_every_one_read_is_there(self):
        for name, (module, _helpers) in _MODULES.items():
            with self.subTest(file=name):
                table = set(prompt_data.load(name)) - {"_about"}
                read = _top_level_reads(module)
                self.assertEqual(table - read, set(), "entries nothing reads")
                self.assertEqual(read - table, set(), "entries the module reads that are missing")

    def test_no_chinese_string_literal_is_left_in_the_modules(self):
        for name, (module, _helpers) in _MODULES.items():
            with self.subTest(module=name):
                tree = _tree(module)
                docstrings = _docstrings(tree)
                left = sorted({
                    node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and _CJK.search(node.value) and id(node) not in docstrings
                } - set(_ALLOWED_LITERALS[name]))
                self.assertEqual(left, [])

    def test_the_allowed_phase_names_are_the_schema_enum(self):
        # The only Chinese left in the director is the phase enum; it must be exactly the schema's.
        phases = typing.get_args(StoryboardTimeBeat.model_fields["action_phase"].annotation)
        self.assertEqual(set(_ALLOWED_LITERALS["storyboard_director"]), set(phases))


class DirectorTableShapeTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load("storyboard_director")

    def test_the_no_extra_content_exclusion_is_one_of_the_video_exclusions(self):
        self.assertIn(self.data["words"]["no_extra_content"], self.data["video_exclusions"])

    def test_tables_are_lists_of_text_and_patterns_compile(self):
        for key in ("meta_labels", "aside_opens", "aside_closes", "video_exclusions", "grid_markers"):
            with self.subTest(key=key):
                self.assertTrue(self.data[key])
                self.assertTrue(all(isinstance(item, str) and item for item in self.data[key]))
                self.assertEqual(len(set(self.data[key])), len(self.data[key]))
        for key in ("scene_line", "bracket_dialogue", "inline_dialogue", "leading_aside", "sentence_split",
                    "landmark_bearing", "landmark_distance"):
            with self.subTest(key=key):
                re.compile(self.data[key])

    def test_a_grid_marker_never_reaches_a_still_prompt_but_reaches_the_page(self):
        result = StoryboardDirectorCompiler().compile(_request())
        for marker in self.data["grid_markers"]:
            self.assertTrue(all(marker not in item.prompt for item in result.still_prompts), marker)
        self.assertIn("3×3", result.grid_pages[0].composite_prompt)

    def test_a_sentence_changed_in_the_table_changes_the_plan(self):
        data = prompt_data.load("storyboard_director")
        with patch.dict(data["checks"], {"damage_timeline_closed": "改过的说明。"}), \
             patch.dict(data["says"], {"change_first": "改过的首拍变化"}):
            result = StoryboardDirectorCompiler().compile(_request())
        codes = {item.code: item for item in result.continuity_checks}
        self.assertEqual(codes["damage_timeline_closed"].detail, "改过的说明。")
        self.assertEqual(result.beats[0].change_from_previous, "改过的首拍变化")
        self.assertIn("【相对上一拍变化】改过的首拍变化。", result.still_prompts[0].prompt)


class Sd25TableShapeTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load("sd25_compiler")

    def test_every_asset_role_has_its_exclusion(self):
        self.assertEqual(set(self.data["asset_exclusions"]), set(typing.get_args(Sd25AssetRole)))
        self.assertTrue(all(isinstance(text, str) and text for text in self.data["asset_exclusions"].values()))

    def test_both_extension_directions_name_direction_boundary_and_target(self):
        self.assertEqual(set(self.data["extension"]), {"before", "after"})
        for direction, words in self.data["extension"].items():
            with self.subTest(direction=direction):
                self.assertEqual(set(words), {"direction", "boundary", "target"})
                self.assertTrue(all(isinstance(word, str) and word for word in words.values()))

    def test_camera_words_and_time_span_compile(self):
        self.assertTrue(all(isinstance(word, str) and word for word in self.data["camera_language"]))
        pattern = re.compile("|".join(self.data["camera_language"]))
        self.assertEqual(pattern.findall("镜头右摇后推近"), ["右摇", "推近"])
        self.assertTrue(re.compile(self.data["time_span"]).search("0-5秒前倾"))

    def test_a_spoken_line_keeps_its_literal_braces(self):
        request = Sd25CompileRequest(
            goal="说话",
            dialogue=[Sd25DialogueEntry(speaker="林夏", text="我知道了。", delivery="克制")],
        )
        self.assertIn("画内的林夏按输入语言，以克制的表达方式说： {我知道了。}；其他人物自然闭口聆听。",
                      Sd25PromptCompiler().compile(request).prompt)

    def test_a_sentence_changed_in_the_table_changes_the_prompt(self):
        request = Sd25CompileRequest(goal="改色", task="edit", source_video_ref="@视频1", assets=[Sd25Asset(
            ref="@视频1", media_type="video", role="source", subject="母版", observations="雨夜街道",
            duration_seconds=8, required=True,
        )])
        with patch.dict(self.data["headings"], {"timeline": "【改过的标题】"}):
            prompt = Sd25PromptCompiler().compile(request).prompt
        self.assertIn("【改过的标题】", prompt)
        self.assertNotIn("【时间线继承】", prompt)


if __name__ == "__main__":
    unittest.main()

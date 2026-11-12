# -*- coding: utf-8 -*-
"""The model gateway's wording lives in app/data/prompt/model_gateway.json, not in the code.

Checked against the source of app/core/model_gateway.py: every key the code reads exists and every
key in the file is read; each template is filled with exactly the names it has; each %-style log
line has as many slots as the logger call passes arguments; first-match tables keep their order;
and no Chinese string literal is left in the module outside docstrings and comments.
"""

from __future__ import annotations

import ast
import json
import re
import string
import unittest
from pathlib import Path

from app.core import model_gateway, prompt_data
from app.core.model_gateway import ModelGateway

SOURCE = Path(model_gateway.__file__)
DATA = prompt_data.ROOT / "model_gateway.json"
CJK = re.compile(r"[　-〿一-鿿＀-￯]")
# helper -> the section of the file it reads
HELPERS = {"_prompt": "prompts", "_says": "errors", "_log": "logs", "_logf": "logs", "_table": "tables"}
FILLED = {"_prompt", "_says", "_logf"}
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
PERCENT = re.compile(r"%(?:\([^)]*\))?[#0\- +]*(?:\*|\d+)?(?:\.(?:\*|\d+))?[diouxXeEfFgGcrsa%]")
# Chinese literals allowed to stay in model_gateway.py, with the reason. Keep it empty if you can.
ALLOWED_CHINESE: dict[str, str] = {}


def _tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def _data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _text(value) -> str:
    return "\n".join(value) if isinstance(value, list) else str(value)


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def _helper_calls(tree: ast.Module):
    """(helper name, key or None, call node, enclosing function name) for every helper call."""
    found = []

    def visit(node, function):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in HELPERS:
                first = child.args[0] if child.args else None
                key = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
                found.append((child.func.id, key, child, function))
            visit(child, inner)

    visit(tree, None)
    return found


def _logger_calls(tree: ast.Module):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"
        ):
            yield node


def _docstrings(tree: ast.Module) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


class KeysTest(unittest.TestCase):
    def test_every_key_read_exists_and_every_key_is_read(self):
        data = _data()
        read: dict[str, set[str]] = {section: set() for section in set(HELPERS.values())}
        for helper, key, call, function in _helper_calls(_tree()):
            if key is None:
                # only the helpers themselves pass a key through
                self.assertIn(function, HELPERS, f"{helper}() at line {call.lineno} needs a literal key")
                continue
            section = HELPERS[helper]
            self.assertIn(key, data[section], f"{helper}({key!r}) at line {call.lineno}: no {section}.{key}")
            read[section].add(key)
        for section, keys in read.items():
            self.assertEqual(set(data[section]) - keys, set(), f"{section} keys nothing reads")

    def test_sections(self):
        self.assertEqual(set(_data()) - {"_about"}, {"prompts", "errors", "logs", "tables"})


class TemplateTest(unittest.TestCase):
    def test_templates_get_exactly_their_placeholders(self):
        data = _data()
        for helper, key, call, function in _helper_calls(_tree()):
            if key is None or helper == "_table":
                continue
            text = _text(data[HELPERS[helper]][key])
            given = {keyword.arg for keyword in call.keywords}
            self.assertNotIn(None, given, f"{helper}({key!r}) at line {call.lineno}: name every value")
            if helper == "_log":
                self.assertEqual(_placeholders(text), set(), f"logs.{key} has {{names}}: read it with _logf")
                continue
            self.assertIn(helper, FILLED)
            self.assertEqual(_placeholders(text), given, f"{helper}({key!r}) at line {call.lineno}")

    def test_placeholders_are_plain_names(self):
        for section in ("prompts", "errors", "logs"):
            for key, value in _data()[section].items():
                for name in _placeholders(_text(value)):
                    self.assertTrue(name.isidentifier(), f"{section}.{key}: {{{name}}}")
                _text(value).format(**{name: 1 for name in _placeholders(_text(value))})

    def test_bodies_kept_as_lines_are_lists_of_strings(self):
        for key, value in _data()["prompts"].items():
            if isinstance(value, list):
                self.assertTrue(all(isinstance(line, str) for line in value), key)
            else:
                self.assertIsInstance(value, str, key)
        for section in ("errors", "logs"):
            for key, value in _data()[section].items():
                self.assertIsInstance(value, str, f"{section}.{key}")


class LogLineTest(unittest.TestCase):
    def test_percent_slots_match_the_logger_arguments(self):
        logs = _data()["logs"]
        checked = 0
        for call in _logger_calls(_tree()):
            self.assertTrue(call.args, f"logger call at line {call.lineno} has no message")
            first = call.args[0]
            self.assertIsInstance(first, ast.Call, f"line {call.lineno}: log text must come from _log/_logf")
            self.assertIn(first.func.id, ("_log", "_logf"), f"line {call.lineno}")
            key = first.args[0].value
            slots = [match for match in PERCENT.findall(logs[key]) if match != "%%"]
            if first.func.id == "_log":
                self.assertEqual(len(slots), len(call.args) - 1, f"logs.{key} at line {call.lineno}")
            else:
                self.assertEqual(len(call.args), 1, f"line {call.lineno}: a written-out line takes no logger arguments")
                self.assertEqual(slots, [], f"logs.{key}: a written-out line has no % slots")
            checked += 1
        self.assertGreater(checked, 60)

    def test_log_text_is_only_read_by_logger_calls(self):
        tree = _tree()
        firsts = {id(call.args[0]) for call in _logger_calls(tree) if call.args}
        for helper, key, call, function in _helper_calls(tree):
            if helper in ("_log", "_logf") and key is not None:
                self.assertIn(id(call), firsts, f"{helper}({key!r}) at line {call.lineno} is not a logger message")

    def test_every_line_names_the_gateway(self):
        for key, value in _data()["logs"].items():
            self.assertTrue(value.startswith("[ModelGateway] "), key)


class OrderTest(unittest.TestCase):
    """First-match tables are lists, read in order."""

    def test_first_match_tables_are_ordered_lists(self):
        tables = _data()["tables"]
        for key in ("genre_rules", "enhance_expressions", "enhance_colors", "enhance_props"):
            self.assertIsInstance(tables[key], list, key)
            self.assertTrue(all(isinstance(row, list) for row in tables[key]), key)
        self.assertEqual([row[0] for row in tables["genre_rules"]][:3], ["overseas_us", "overseas_other", "interactive"])
        self.assertEqual(tables["genre_rules"][-1][0], "urban_realism")
        self.assertEqual([row[0] for row in tables["enhance_props"]], ["flying_sword", "demon_seal", "magic_circle", "common_blade"])

    def test_genre_precedence(self):
        gateway = ModelGateway.__new__(ModelGateway)
        self.assertEqual(gateway.get_genre("剑 霸总"), "wuxia")
        self.assertEqual(gateway.get_genre("重生 霸总"), "rebirth_revenge")
        self.assertEqual(gateway.get_genre("狼人 仙侠"), "overseas_us")
        self.assertEqual(gateway.get_genre("AI 霸总"), "romance")
        self.assertEqual(gateway.get_genre("车"), "car")
        self.assertEqual(gateway.get_genre("x"), "general")

    def test_name_tables_keep_their_order(self):
        gateway = ModelGateway.__new__(ModelGateway)
        names = [gateway.generate_random_name(title, villain) for title in ("重生之我是女王", "abc") for villain in (False, True)]
        self.assertEqual(names, ["司徒月", "黄强", "顾风", "何建国"])

    def test_enhancement_takes_the_first_row_of_each_table(self):
        gateway = ModelGateway.__new__(ModelGateway)
        enhanced = gateway._enhancePromptWithRules("哭 怒 打斗 雨 剑 飞剑")
        tables = _data()["tables"]
        self.assertIn(tables["enhance_expressions"][0][2], enhanced)
        self.assertNotIn(tables["enhance_expressions"][1][2], enhanced)
        self.assertIn(tables["enhance_colors"][0][2], enhanced)
        self.assertIn(tables["enhance_props"][0][2], enhanced)
        self.assertNotIn(tables["enhance_props"][3][2], enhanced)

    def test_offline_answer_asks_the_writer_first(self):
        gateway = ModelGateway.__new__(ModelGateway)
        markers = _data()["tables"]["offline_markers"]
        self.assertEqual(list(markers), ["writer", "executive", "character", "storyboard", "pr"])
        source = SOURCE.read_text(encoding="utf-8")
        asked = [source.index(f'asks("{role}")') for role in markers]
        self.assertEqual(asked, sorted(asked))

    def test_class_tables_keep_their_types(self):
        self.assertIsInstance(model_gateway._MAX_TOKENS_WORDS, tuple)
        for name in ("BLOCKING_STANDS", "COMPOSITIONS", "CAMERA_MOVEMENTS"):
            self.assertIsInstance(getattr(ModelGateway, name), list, name)
        self.assertEqual(len(ModelGateway.BLOCKING_STANDS), 8)
        self.assertEqual(len(ModelGateway.COMPOSITIONS), 16)
        self.assertEqual(len(ModelGateway.CAMERA_MOVEMENTS), 36)
        self.assertEqual(len(ModelGateway.GENRE_TEMPLATES), 22)
        self.assertEqual(list(ModelGateway.GENRE_TEMPLATES)[-1], "general")


class PatternTest(unittest.TestCase):
    def test_patterns_compile(self):
        tables = _data()["tables"]
        for key in ("optimizer_preamble", "story_title_noise", "story_protagonist_after_of", "story_rename_protagonist",
                    "story_rename_antagonist", "story_rename_location", "preamble_greeting", "preamble_sentence",
                    "agnes_brackets", "agnes_negative_clause"):
            re.compile(tables[key])

    def test_patterns_still_match_what_they_are_for(self):
        gateway = ModelGateway.__new__(ModelGateway)
        self.assertEqual(gateway._strip_model_preamble("你好！我是 Agnes。正文。"), "正文。")
        self.assertEqual(ModelGateway._sanitize_prompt_for_agnes("人物（避免换脸）站立，不要多余手指；死"), "人物站立")
        context = gateway.parse_story_context("老王在火星做修脚", "把主角改名叫阿星，场景改为天台")
        self.assertEqual((context["char1"], context["location"], context["action"]), ("阿星", "天台", "修脚"))


class NoChineseInCodeTest(unittest.TestCase):
    def test_no_chinese_string_literal_outside_docstrings(self):
        tree = _tree()
        docstrings = _docstrings(tree)
        left = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings and CJK.search(node.value):
                if node.value not in ALLOWED_CHINESE:
                    left.append((node.lineno, node.value[:40]))
        self.assertEqual(left, [])

    def test_allow_list_entries_carry_a_reason(self):
        for literal, reason in ALLOWED_CHINESE.items():
            self.assertTrue(reason.strip(), literal)


class ClassConstantsTest(unittest.TestCase):
    def test_class_constants_read_the_file(self):
        prompts = _data()["prompts"]
        pairs = {
            "DEFAULT_STYLE_CAPTION": "default_style_caption", "GLOBAL_NEGATIVE_LABEL": "global_negative_label",
            "SHEET_PROBLEM_NEGATIVE": "sheet_problem_negative", "SHEET_LOCK_POSITIVE": "sheet_lock_positive",
            "SHEET_LOCK_NEGATIVE": "sheet_lock_negative", "DEID_POSITIVE": "deid_positive", "DEID_NEGATIVE": "deid_negative",
            "PANEL_IDENTITY_NEGATIVE": "panel_identity_negative", "SCENE_STABILITY_POSITIVE": "scene_stability_positive",
            "SCENE_STABILITY_NEGATIVE": "scene_stability_negative", "CONTINUITY_POSITIVE": "continuity_positive",
            "CONTINUITY_NEGATIVE": "continuity_negative", "CONTINUITY_CARRY": "continuity_carry",
            "CLONE_NEGATIVE": "clone_negative", "EMOTION_FACE_NEGATIVE": "emotion_face_negative",
        }
        for attribute, key in pairs.items():
            self.assertEqual(getattr(ModelGateway, attribute), prompts[key], attribute)
        self.assertEqual(ModelGateway.GENRE_ERA_COSTUME, _data()["tables"]["era_costume"])


if __name__ == "__main__":
    unittest.main()

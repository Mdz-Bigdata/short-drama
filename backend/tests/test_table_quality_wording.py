# -*- coding: utf-8 -*-
"""The stage-4 shot-table audit and the storyboard prompts say what their tables say.

No model, no network. ``shot_table_rules.json`` and ``storyboard_quality.json`` are checked against
the code that reads them in both directions: every entry in a table is read, every entry the code
asks for is there, every template gets exactly the placeholders it names, the first-match tables
keep their order, and no Chinese text is left written in either module outside docstrings.
"""

import ast
import inspect
import re
import string
import typing
import unittest
from unittest.mock import patch

from app.core import prompt_data, shot_table_rules, storyboard_quality
from app.core.actor_sheet_layout import ACTOR_SHEET_LAYOUT
from app.schema.production import StoryboardPanel

_CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
# Chinese string literals a module may still carry, each with the reason it is not wording.
# Both are empty: every sentence, word and pattern moved to the JSON.
_ALLOWED_LITERALS: dict[str, dict[str, str]] = {"shot_table_rules": {}, "storyboard_quality": {}}
_MODULES = {"shot_table_rules": shot_table_rules, "storyboard_quality": storyboard_quality}


def _tree(module) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _docstrings(tree: ast.Module) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _fields(template: object) -> frozenset[str]:
    text = "".join(template) if isinstance(template, list) else str(template)
    return frozenset(name for _, name, _, _ in string.Formatter().parse(text) if name)


def _literal(node: ast.AST, line: int) -> str:
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        raise AssertionError(f"a table key is not a literal at line {line}")
    return node.value


def _calls(tree: ast.Module, helper: str, position: int) -> list[tuple[str, frozenset[str], int]]:
    """Every ``helper(...)``: the key at ``position``, the placeholders it fills (``severity`` is not one), and its line."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == helper:
            if len(node.args) != position + 1:
                raise AssertionError(f"{helper} at line {node.lineno} does not name exactly one key")
            key = _literal(node.args[position], node.lineno)
            found.append((key, frozenset(item.arg for item in node.keywords if item.arg != "severity"), node.lineno))
    return found


def _is_wording(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "_WORDING"


def _top_level_reads(tree: ast.Module) -> set[str]:
    """``prompt_data.f(_WORDING, "k")`` and ``prompt_data.load(_WORDING)["k"]``."""
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "prompt_data" and len(node.args) >= 2 and _is_wording(node.args[0])
            ):
                keys.add(_literal(node.args[1], node.lineno))
        elif (
            isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "load"
            and node.value.args and _is_wording(node.value.args[0])
        ):
            keys.add(_literal(node.slice, node.lineno))
    return keys


class ShotTableWordingTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load("shot_table_rules")
        self.tree = _tree(shot_table_rules)

    def test_every_top_level_entry_is_read_and_every_one_read_is_there(self):
        table = set(self.data) - {"_about"}
        read = _top_level_reads(self.tree)
        self.assertEqual(table - read, set(), "entries nothing reads")
        self.assertEqual(read - table, set(), "entries shot_table_rules.py reads that are missing")

    def test_every_sentence_is_read_and_gets_exactly_its_placeholders(self):
        says = self.data["says"]
        calls = _calls(self.tree, "_says", 0)
        self.assertEqual(set(says) - {key for key, _, _ in calls}, set(), "sentences nothing reads")
        for key, filled, line in calls:
            self.assertIn(key, says, f"line {line}")
            self.assertEqual(filled, _fields(says[key]), f"says.{key} (line {line}): placeholders")

    def test_every_issue_is_raised_and_gets_exactly_its_placeholders(self):
        issues = self.data["issues"]
        calls = _calls(self.tree, "_issue", 1)
        self.assertEqual(set(issues) - {key for key, _, _ in calls}, set(), "issues nothing raises")
        for key, filled, line in calls:
            self.assertIn(key, issues, f"line {line}")
            self.assertEqual(set(issues[key]), {"rule", "detail"}, key)
            self.assertEqual(_fields(issues[key]["rule"]), frozenset(), f"issues.{key}.rule is a name, not a template")
            self.assertEqual(filled, _fields(issues[key]["detail"]), f"issues.{key} (line {line}): placeholders")

    def test_every_pattern_is_read_and_compiles(self):
        patterns = self.data["patterns"]
        read = {key for key, _, _ in _calls(self.tree, "_pattern", 0)}
        self.assertEqual(read, set(patterns))
        for key, text in patterns.items():
            with self.subTest(key=key):
                re.compile(text)

    def test_issue_rule_names_are_distinct(self):
        # Tests and readers tell problems apart by rule name.
        rules = [spec["rule"] for spec in self.data["issues"].values()]
        self.assertEqual(len(rules), len(set(rules)))

    def test_the_log_line_is_a_logging_format_with_three_values(self):
        self.assertEqual(re.findall(r"%.", self.data["log_issue"]), ["%s", "%s", "%s"])
        self.assertEqual(_fields(self.data["log_issue"]), frozenset())

    def test_the_module_tables_are_the_data_in_order(self):
        # Inner-monologue, abstract-emotion and frozen-frame hits report the first word that matches.
        for name, key in (
            ("SHOT_SIZE_TERMS", "shot_size_terms"), ("ABSTRACT_EMOTION_TERMS", "abstract_emotion_terms"),
            ("PHYSICAL_CUE_TERMS", "physical_cue_terms"), ("INNER_MONOLOGUE_TERMS", "inner_monologue_terms"),
            ("BURST_TERMS", "burst_terms"), ("CLOSE_UP_TERMS", "close_up_terms"),
            ("FROZEN_FRAME_TERMS", "frozen_frame_terms"),
        ):
            with self.subTest(name=name):
                self.assertEqual(getattr(shot_table_rules, name), tuple(self.data[key]))
                self.assertEqual(len(set(self.data[key])), len(self.data[key]))
        self.assertEqual(shot_table_rules.INNER_MONOLOGUE_TERMS[:2], ("心想", "内心"))
        self.assertEqual(shot_table_rules.FROZEN_FRAME_TERMS[0], "定格")
        # The full-width colon is tried before the ASCII one.
        self.assertEqual(self.data["sound_label_separators"], ["：", ":"])
        self.assertIsInstance(shot_table_rules.MAX_MOVING_SHOT_RATIO, float)
        for name in ("MIN_DESC_CHARS", "MAX_SAME_SIZE_RUN", "MIN_BUILDUP_SECONDS", "MAX_BURST_SECONDS",
                     "MAX_CLOSE_UPS_PER_SCENE", "MAX_CLOSE_UPS_PER_FIGHT_SCENE", "MAX_AMBIENT_LAYERS", "MAX_ACTION_SOUNDS"):
            self.assertEqual(getattr(shot_table_rules, name), self.data[name.lower()], name)

    def test_the_first_matching_word_is_reported(self):
        desc = "小六心想他觉得对方一定会回来的，于是站在原地一直等着，等到天色完全暗下来才肯离开这条长街。"
        audit = shot_table_rules.audit_shot_table(
            [{"shot_id": 1, "size": "中景", "duration": "8s", "desc": desc}], video_model="seedance2.0", whole_episode=False,
        )
        issue = next(item for item in audit.issues if item.rule == "出现心理描写")
        self.assertEqual((issue.detail, issue.severity), ("「心想」是摄影机拍不到的内容", "error"))

    def test_the_summary_reads_as_before(self):
        audit = shot_table_rules.ShotTableAudit(
            issues=[shot_table_rules.ShotIssue(1, "b", "x"), shot_table_rules.ShotIssue(2, "a", "y"),
                    shot_table_rules.ShotIssue(3, "b", "z")],
            repaired=2,
        )
        self.assertEqual(audit.summary(), "分镜表检查发现 3 项问题：a × 1；b × 2，已自动修复 2 处超长镜头")
        self.assertEqual(shot_table_rules.ShotTableAudit().summary(), "分镜表通过全部硬性规则检查")

    def test_a_sentence_changed_in_the_table_changes_the_audit(self):
        data = prompt_data.load("shot_table_rules")
        changed = {**data["issues"], "single_shot": {"rule": "改过的规则", "detail": "改过的说明"}}
        with patch.dict(data, {"issues": changed}):
            audit = shot_table_rules.audit_shot_table([{"shot_id": 7, "size": "全景"}], video_model="seedance2.0")
        self.assertIn(shot_table_rules.ShotIssue(7, "改过的规则", "改过的说明", "error"), audit.issues)


class StoryboardQualityWordingTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load("storyboard_quality")
        self.tree = _tree(storyboard_quality)

    def test_every_top_level_entry_is_read_and_every_one_read_is_there(self):
        table = set(self.data) - {"_about"}
        read = _top_level_reads(self.tree)
        self.assertEqual(table - read, set(), "entries nothing reads")
        self.assertEqual(read - table, set(), "entries storyboard_quality.py reads that are missing")

    def test_every_sentence_is_read_and_gets_exactly_its_placeholders(self):
        says = self.data["says"]
        calls = _calls(self.tree, "_says", 0)
        self.assertEqual(set(says) - {key for key, _, _ in calls}, set(), "sentences nothing reads")
        for key, filled, line in calls:
            self.assertIn(key, says, f"line {line}")
            self.assertEqual(filled, _fields(says[key]), f"says.{key} (line {line}): placeholders")

    def test_every_template_formats(self):
        for key, template in self.data["says"].items():
            with self.subTest(key=key):
                text = "".join(template) if isinstance(template, list) else template
                text.format(**{name: 1.5 for name in _fields(template)})

    def test_the_captions_fill_the_sheet_grids_in_order(self):
        self.assertEqual(storyboard_quality._ELEMENT_CAPTIONS, tuple(tuple(row) for row in self.data["element_captions"]))
        self.assertEqual(storyboard_quality._DETAIL_CAPTIONS, tuple(tuple(row) for row in self.data["detail_captions"]))
        for key, grid in (("element_captions", ACTOR_SHEET_LAYOUT.element_grid), ("detail_captions", ACTOR_SHEET_LAYOUT.detail_matrix_grid)):
            with self.subTest(key=key):
                rows, columns = grid
                self.assertEqual([len(row) for row in self.data[key]], [columns] * rows)
                self.assertLessEqual(rows, len(self.data["row_ordinals"]))
        # The first detail row is the three face close-ups the prompt describes, in that order.
        self.assertEqual(self.data["detail_captions"][0], ["正脸特写", "左侧45°侧脸", "右侧45°侧脸"])
        self.assertEqual(self.data["row_ordinals"][:3], "一二三")
        self.assertEqual(
            storyboard_quality._numbered((("甲", "乙"), ("丙",))), ["第一行：1. 甲、2. 乙", "第二行：3. 丙"],
        )

    def test_every_generation_mode_has_its_label(self):
        modes = typing.get_args(StoryboardPanel.model_fields["generation_mode"].annotation)
        self.assertEqual(set(self.data["generation_modes"]), set(modes))
        self.assertTrue(all(isinstance(label, str) and label for label in self.data["generation_modes"].values()))

    def test_continuity_messages_are_named_by_their_codes(self):
        codes = {
            node.value.value for node in ast.walk(self.tree)
            if isinstance(node, ast.keyword) and node.arg == "code" and isinstance(node.value, ast.Constant)
        }
        self.assertEqual(codes, {"missing_continuity_in", "missing_prop_state", "missing_effect_state"})
        self.assertLessEqual(codes, set(self.data["says"]))

    def test_the_nine_grid_lines_come_in_order(self):
        from tests.test_production_contracts import _panel
        from app.schema.production import NineGridStoryboard, StoryAssetCatalog

        board = NineGridStoryboard(
            title="雨夜来信",
            assets=StoryAssetCatalog(characters=["林夏"], scenes=["客厅"], props=["信封"], effects=["雨丝"]),
            panels=[_panel(1), _panel(2)],
        )
        lines = storyboard_quality.build_nine_grid_prompt(board).split("\n")
        self.assertEqual(lines[0], "生成《雨夜来信》的单张3×3九宫格电影分镜图。")
        self.assertEqual(lines[5:9], ["【角色】林夏", "【场景】客厅", "【道具】信封", "【特效】雨丝"])
        self.assertTrue(lines[10].startswith("第1格｜") and lines[11].startswith("第2格｜"))
        self.assertEqual(lines[12], "第3格｜纯留白空格；不得复制、延伸或补造任何叙事拍点。")
        self.assertEqual(len(lines), 10 + 9 + 1)
        self.assertEqual(lines[-1], "不要在画面内生成镜号、说明文字或字幕；用清晰分隔线表达九宫格结构。")

    def test_a_sentence_changed_in_the_table_changes_the_prompt(self):
        data = prompt_data.load("storyboard_quality")
        with patch.dict(data["says"], {"identity_dna": "改过的身份：{dna}。"}):
            prompt = storyboard_quality.build_actor_sheet_prompt("林夏", "米白风衣", "写实电影")
        self.assertIn("改过的身份：米白风衣。", prompt)
        self.assertNotIn("身份DNA：", prompt)


class NoChineseLeftInCodeTests(unittest.TestCase):
    def test_no_chinese_string_literal_is_left_in_the_modules(self):
        for name, module in _MODULES.items():
            with self.subTest(module=name):
                tree = _tree(module)
                docstrings = _docstrings(tree)
                left = sorted({
                    node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and _CJK.search(node.value) and id(node) not in docstrings
                } - set(_ALLOWED_LITERALS[name]))
                self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()

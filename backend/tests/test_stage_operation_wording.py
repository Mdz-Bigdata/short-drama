# -*- coding: utf-8 -*-
"""The desk operations say what ``stage_operations.json`` says.

No model, no network. The wording table is checked against the code that reads it in both
directions: every sentence and word in the table is read, every one the code asks for is there
with exactly the placeholders it fills, and no Chinese text is left written in the module.
"""

import ast
import inspect
import re
import string
import typing
import unittest
from unittest.mock import patch

from app.core import prompt_data
from app.core.spatial_stage import operations
from app.core.spatial_stage.coverage import move_kind
from app.core.spatial_stage.models import CameraMoveKind
from app.core.spatial_stage.operations import StageEditError, apply_operations
from app.core.spatial_stage.wording import move_zh
from tests.test_director_desk import _brief

_DATA = "stage_operations"
_CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
# Chinese string literals operations.py may still carry, each with the reason it is not wording.
# (The one comment in Chinese is not a string literal and is not prompt text.)
_ALLOWED_LITERALS: dict[str, str] = {}


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(operations))


def _is_wording(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "_WORDING"


def _says_calls() -> list[tuple[str, frozenset[str], int]]:
    """Every ``_says(...)``: the key it names, the placeholders it fills, and its line."""
    found = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_says":
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)) or len(node.args) != 1:
                raise AssertionError(f"a _says key is not a single literal at line {node.lineno}")
            found.append((first.value, frozenset(item.arg for item in node.keywords), node.lineno))
    return found


def _top_level_reads() -> set[str]:
    """The top-level keys of the table the module reads: ``_word("k")``, ``prompt_data.f(_WORDING, "k")``, ``load(_WORDING)["k"]``."""
    keys: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "_word":
                first = node.args[0]
                if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                    raise AssertionError(f"a _word key is not a literal at line {node.lineno}")
                keys.add(first.value)
            elif (
                isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "prompt_data" and len(node.args) >= 2 and _is_wording(node.args[0])
                and isinstance(node.args[1], ast.Constant)
            ):
                keys.add(node.args[1].value)
        elif (
            isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "load"
            and node.value.args and _is_wording(node.value.args[0]) and isinstance(node.slice, ast.Constant)
        ):
            keys.add(node.slice.value)
    return keys


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


class WordingTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)
        self.says = self.data["says"]

    def test_every_sentence_in_the_table_is_used_and_every_one_asked_for_is_there(self):
        calls = _says_calls()
        asked = {key for key, _, _ in calls}
        self.assertEqual(set(self.says) - asked, set(), "sentences nothing reads")
        self.assertEqual(asked - set(self.says), set(), "sentences operations.py reads that are missing")

    def test_each_sentence_gets_exactly_the_placeholders_it_names(self):
        for key, filled, line in _says_calls():
            self.assertEqual(filled, _fields(self.says[key]), f"says.{key} (line {line}): placeholders")

    def test_every_template_formats(self):
        for key, template in self.says.items():
            with self.subTest(key=key):
                template.format(**{name: 1.5 for name in _fields(template)})

    def test_every_top_level_entry_is_read_and_every_one_read_is_there(self):
        table = set(self.data) - {"_about"}
        read = _top_level_reads()
        self.assertEqual(table - read, set(), "entries nothing reads")
        self.assertEqual(read - table, set(), "entries operations.py reads that are missing")

    def test_words_and_timeline_messages_are_plain_text(self):
        # ``_word`` and the timeline table are used as they stand, never formatted.
        for key in ("over_shoulder", "level_angle", "list_separator", "note_separator"):
            self.assertIsInstance(self.data[key], str, key)
            self.assertTrue(self.data[key], key)
        self.assertTrue(all(isinstance(word, str) and word for word in self.data["shoulder_words"]))
        self.assertIn(self.data["over_shoulder"], self.data["shoulder_words"])
        for marker, message in self.data["timeline_errors"]:
            self.assertTrue(marker and message)
            self.assertEqual(_fields(message), frozenset(), marker)

    def test_no_chinese_string_literal_is_left_in_the_module(self):
        left = sorted({
            node.value for node in ast.walk(_tree())
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _CJK.search(node.value)
        } - set(_ALLOWED_LITERALS))
        self.assertEqual(left, [])


class ReadsTheCameraMoveNamesTests(unittest.TestCase):
    def test_a_re_solved_lens_keeps_its_move_through_the_shared_names(self):
        # A re-solve describes the lens's move by its name in stage_camera_moves.json; that name must read back as the same move.
        for kind in typing.get_args(CameraMoveKind):
            self.assertEqual(move_kind(move_zh(kind)), kind, kind)


class SaysWhatTheTableSaysTests(unittest.TestCase):
    def setUp(self):
        from app.core.spatial_stage import build_plan

        self.plan = build_plan(_brief())
        self.says = prompt_data.load(_DATA)["says"]

    def _refusal(self, *ops: dict) -> str:
        with self.assertRaises(StageEditError) as raised:
            apply_operations(self.plan, list(ops))
        return str(raised.exception)

    def test_refusals_read_as_before(self):
        self.assertTrue(self._refusal({"op": "fly"}).startswith("operations[0] 未知操作 'fly'；支持：move_actor、place_relative、"))
        self.assertEqual(
            self._refusal({"op": "set_pose", "name": "沈砚", "joints": [1]}),
            "operations[0] set_pose：joints 必须是 {关节名: 角度} 的对象",
        )
        self.assertEqual(
            self._refusal({"op": "set_pose", "name": "沈砚", "joints": {"9bad": 1}}),
            "operations[0] set_pose：关节名 '9bad' 不合法：以字母开头，只含字母、数字和 _ . : -，最长 60",
        )
        self.assertEqual(
            self._refusal({"op": "set_pose", "name": "沈砚", "joints": {"spine.x": 200}}),
            "operations[0] set_pose：关节 spine.x 的角度 必须在 -180 到 180 之间",
        )
        self.assertEqual(
            self._refusal({"op": "set_timeline", "shot_id": 2, "duration_s": 2, "follow": [{"id": "f", "actor": "沈砚", "start": 0, "end": 4}]}),
            "operations[0] set_timeline：片段不能超过时间线时长：跟拍轨最后一段到 4 秒，时长是 2 秒",
        )

    def test_a_reworded_sentence_reaches_the_refusal(self):
        reworded = {**prompt_data.load(_DATA), "says": {**self.says, "no_actor": "没有叫「{name}」的人"}}
        original = prompt_data.load
        with patch.object(prompt_data, "load", lambda name: reworded if name == _DATA else original(name)):
            message = self._refusal({"op": "move_actor", "name": "无名", "yaw_deg": 0})
        self.assertEqual(message, "operations[0] move_actor：没有叫「无名」的人")

    def test_what_the_desk_adds_is_named_from_the_table(self):
        added = apply_operations(self.plan, [{"op": "add_extra", "name": "路人"}, {"op": "add_camera", "shot_id": 2}])
        self.assertEqual(added.actors[-1].note, self.says["extra_note"])
        filming = self.plan.camera(self.plan.shot(2).camera_id)
        self.assertEqual(added.cameras[-1].label, f"{filming.label} · 候选1")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""The generation feedback loop says what ``generation_feedback.json`` says.

No model, no network. The wording table is checked against the code that reads it in both
directions: every entry of the table is read, every one the code asks for is there, every
sentence gets exactly the placeholders it names, the catalogue keeps its matching order, and no
Chinese text is left written in the module.
"""

import ast
import inspect
import re
import string
import unittest

from app.core import generation_feedback as feedback
from app.core import prompt_data

_DATA = "generation_feedback"
_CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
# Chinese string literals generation_feedback.py may still carry, each with the reason it is not
# wording. (Docstrings and the one Chinese comment are not string literals of the code.)
_ALLOWED_LITERALS: dict[str, str] = {}
# The order reports are matched in, and the class each failure changes first: decided by code.
_ORDER = (
    "face_collapse", "hand_failure", "occlusion", "action_blur", "colour_drift", "spatial_break", "style_drift",
    "face_flip", "dead_eyes", "floating",
    "expression_failure", "lip_sync", "audio_muddy", "wrong_speaker", "sfx_timing", "action_dwindle",
    "contact_unclear", "fight_disconnected", "jump_cut", "body_merge", "weapon_failure", "weightless_hit",
    "damage_reset", "endframe_warp", "vfx_unsourced",
    "early_action", "missed_cut", "silent_mouth", "crammed_actions", "tail_extra",
)
_FAILURE_FIELDS = {"name", "triggers", "diagnosis", "fixes", "negatives", "prevention"}


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(feedback))


def _docstrings(tree: ast.Module) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _literal_first_args(name: str) -> list[tuple[str, frozenset[str], int]]:
    """Every ``name(...)`` call: its literal first argument, the keywords it passes, and its line."""
    found = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                raise AssertionError(f"a {name} key is not a literal at line {node.lineno}")
            found.append((first.value, frozenset(item.arg for item in node.keywords), node.lineno))
    return found


def _top_level_reads() -> set[str]:
    """Top-level keys the module reads: ``_entry("k")`` and ``prompt_data.f(_WORDING, "k")``."""
    keys = {key for key, _, _ in _literal_first_args("_entry")}
    tree = _tree()
    # ``_entry`` itself passes its key on; its callers are counted above.
    inside_entry = {
        id(inner) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_entry"
        for inner in ast.walk(node)
    }
    for node in ast.walk(tree):
        if id(node) not in inside_entry and (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "prompt_data"
            and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id == "_WORDING"
        ):
            if not isinstance(node.args[1], ast.Constant):
                raise AssertionError(f"a prompt_data key is not a literal at line {node.lineno}")
            keys.add(node.args[1].value)
    return keys


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


class WordingTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)
        self.says = self.data["says"]

    def test_every_top_level_entry_is_read_and_every_one_read_is_there(self):
        table = set(self.data) - {"_about"}
        read = _top_level_reads()
        self.assertEqual(table - read, set(), "entries nothing reads")
        self.assertEqual(read - table, set(), "entries generation_feedback.py reads that are missing")

    def test_every_sentence_is_used_and_every_one_asked_for_is_there(self):
        asked = {key for key, _, _ in _literal_first_args("_says")}
        self.assertEqual(set(self.says) - asked, set(), "sentences nothing reads")
        self.assertEqual(asked - set(self.says), set(), "sentences generation_feedback.py reads that are missing")

    def test_each_sentence_gets_exactly_the_placeholders_it_names(self):
        for key, filled, line in _literal_first_args("_says"):
            self.assertEqual(filled, _fields(self.says[key]), f"says.{key} (line {line}): placeholders")

    def test_every_template_formats(self):
        for key, template in self.says.items():
            with self.subTest(key=key):
                self.assertIsInstance(template, str)
                template.format(**{name: "x" for name in _fields(template)})

    def test_every_failure_entry_is_read_whole(self):
        # The catalogue reads failures.<id> for each id in code, and fixes.<class> for each class it names.
        catalogue = {item[0]: item for item in feedback._CATALOGUE}
        self.assertEqual(set(self.data["failures"]), set(catalogue), "failure ids: table vs code")
        for failure_id, entry in self.data["failures"].items():
            with self.subTest(failure_id):
                self.assertEqual(set(entry), _FAILURE_FIELDS)
                self.assertEqual(set(entry["fixes"]), set(catalogue[failure_id][2]), "fix classes: table vs code")
                self.assertTrue(all(entry["fixes"].values()), "a fix class with no fix")
                for key in ("name", "diagnosis", "prevention"):
                    self.assertIsInstance(entry[key], str)
                    self.assertTrue(entry[key])
                    self.assertEqual(_fields(entry[key]), frozenset(), "catalogue text is used as it stands")
                for key in ("triggers", "negatives"):
                    self.assertTrue(all(isinstance(word, str) and word for word in entry[key]))
                self.assertTrue(entry["triggers"])

    def test_class_names_and_ladders_cover_every_class(self):
        classes = set(feedback.RECONSIDER_ORDER)
        self.assertEqual(set(self.data["variable_names"]), classes)
        self.assertEqual(set(self.data["escalation"]), classes)
        self.assertTrue(all(self.data["escalation"][key] for key in classes))
        self.assertEqual(self.data["list_separator"], "、")

    def test_no_chinese_string_literal_is_left_in_the_module(self):
        tree = _tree()
        docstrings = _docstrings(tree)
        left = sorted({
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
            and _CJK.search(node.value)
        } - set(_ALLOWED_LITERALS))
        self.assertEqual(left, [])


class OrderAndWordingTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)

    def test_the_catalogue_keeps_its_matching_order(self):
        # classify() breaks a tie at one position by this order: the first failure listed wins.
        self.assertEqual(tuple(failure.id for failure in feedback.FAILURES), _ORDER)
        self.assertEqual(
            [match.failure.id for match in feedback.classify("声音提前")],
            ["audio_muddy", "sfx_timing"], "same position: the earlier catalogue entry comes first",
        )

    def test_the_ladders_keep_their_order(self):
        for variable, rungs in self.data["escalation"].items():
            self.assertEqual(feedback.ESCALATION[variable], tuple(rungs))
        self.assertEqual(list(feedback.ESCALATION), list(feedback.RECONSIDER_ORDER))
        self.assertEqual(list(feedback.VARIABLE_NAMES), list(feedback.RECONSIDER_ORDER))

    def test_the_catalogue_reads_as_the_table_says(self):
        for failure in feedback.FAILURES:
            entry = self.data["failures"][failure.id]
            with self.subTest(failure.id):
                self.assertEqual(failure.name, entry["name"])
                self.assertEqual(failure.triggers, tuple(entry["triggers"]))
                self.assertEqual(failure.diagnosis, entry["diagnosis"])
                self.assertEqual(failure.negatives, tuple(entry["negatives"]))
                self.assertEqual(failure.prevention, entry["prevention"])
                self.assertEqual(
                    [(fix.variable, fix.text) for fix in failure.fixes],
                    [(kind, text) for kind in dict.fromkeys(fix.variable for fix in failure.fixes) for text in entry["fixes"][kind]],
                )
        self.assertEqual(feedback.get_failure("hand_failure").fixes[0].text, "把手势降级为安全档：握拳、摊掌、单手抬起、手扶道具")

    def test_plans_and_notes_read_as_before(self):
        first = feedback.plan_fix("脸崩了")
        self.assertEqual(first.steps[-1], "本轮只改动作，镜头、参考素材保持不变，生成后再判断下一步")
        second = feedback.plan_fix("脸崩了", attempt=2)
        self.assertEqual(second.steps[-2], "第2次重试，按退让顺序执行：简化动作：安全手势、一镜一个主动作")
        third = feedback.plan_fix("脸崩了", attempt=3)
        self.assertEqual(third.steps[0], "连续 2 轮只改动作都没有改善，可能分错了变量：本轮改查镜头")
        picture = feedback.plan_fix("脸崩了", attempt=7)
        self.assertEqual(
            picture.steps,
            ["动作、镜头、参考素材各改了 2 轮都没有改善，已到模型能力边界：换等价表达（剪影打斗、道具发光代替结印）或换一个视频模型"],
        )
        sound = feedback.plan_fix("串台", attempt=5)
        self.assertEqual(
            sound.steps,
            ["声音、动作各改了 2 轮都没有改善：对白移到后期配音，本镜视频只出画面与环境声，台词由 TTS 配好后按口型合入"],
        )
        task = {"assets": {}}
        for shot in (1, 2):
            feedback.record(task, shot_id=shot, result="failed", text="手指畸形", model="m")
            feedback.record(task, shot_id=shot + 10, result="success", model="m", applied_fix="第三人降为虚化")
        self.assertEqual(
            feedback.preventive_notes(task, "m"),
            ["手部畸形：避免双手结印与捏取细小物件；手部特写优先改中景。", "本项目已验证有效：第三人降为虚化"],
        )


if __name__ == "__main__":
    unittest.main()

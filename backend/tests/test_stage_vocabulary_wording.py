# -*- coding: utf-8 -*-
"""The stage's size words, angle words, blocking verbs, camera names, route and move refusals and
export notes are read from ``stage_vocabulary.json`` / ``stage_camera_moves.json``, not written in code.

No model, no network. The tables are checked against the source of the modules that read them in
both directions (every entry is read, every entry read is there with the placeholders it fills), the
first-match tables keep the order that makes them work, and no Chinese is left in a string literal.
"""

import ast
import inspect
import string
import unittest

from app.core import prompt_data
from app.core.spatial_stage import axis, camera_moves, coverage, interchange, language, models, paths
from app.core.spatial_stage.models import StageCamera
from app.core.spatial_stage.projection import SHOT_SIZE_HEIGHTS

_VOCABULARY = "stage_vocabulary"
_MOVES = "stage_camera_moves"
_MODULES = (coverage, language, paths, camera_moves, interchange, axis, models)
# Names the modules bind a part of a table to, and the key path that part sits at.
_BOUND = {
    coverage: {"_SIZES": (_VOCABULARY, "shot_sizes"), "_ANGLES": (_VOCABULARY, "angles"),
               "_LABELS": (_VOCABULARY, "camera_labels"), "table": (_MOVES,)},
    language: {"_VERBS": (_VOCABULARY, "blocking_verbs")},
    interchange: {"wording": (_VOCABULARY, "interchange")},
}
# Helpers that take a key of one section as their first argument.
_READERS = {
    paths: {"_says": (_VOCABULARY, "path_errors")},
    camera_moves: {"_says": (_MOVES, "errors")},
    interchange: {"_refusal": (_VOCABULARY, "interchange", "errors")},
}
# A Chinese (or other non-ASCII) string literal a module may keep, with the reason. None today.
_ALLOWED_LITERALS: dict[str, str] = {}


def _tree(module) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _constants(module) -> dict[str, str]:
    """Module-level ``NAME = "text"`` bindings, so ``prompt_data.value(_VOCABULARY, …)`` resolves its file."""
    found = {}
    for node in _tree(module).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            found.update({target.id: node.value.value for target in node.targets if isinstance(target, ast.Name)})
    return found


def _literal(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _base(node: ast.AST, module, constants: dict[str, str]) -> tuple[str, ...] | None:
    """The key path a subscript chain starts from: a bound name, ``prompt_data.load/value(…)`` or ``_wording()``."""
    if isinstance(node, ast.Name):
        return _BOUND.get(module, {}).get(node.id)
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id == "_wording" and module is interchange:
        return (_VOCABULARY, "interchange")
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "prompt_data":
        parts = [_literal(arg, constants) for arg in node.args]
        if func.attr == "load" and parts and parts[0]:
            return (parts[0],)
        if func.attr in {"value", "text", "words", "pairs", "number"} and len(parts) == 2 and all(parts):
            return tuple(parts)
    return None


def _reads(module) -> tuple[set[tuple[str, ...]], list[tuple[tuple[str, ...], frozenset[str] | None]]]:
    """Every key path the module reads with literal keys, and each reader call with the placeholders it fills.

    A chain indexed by a variable (inside a reader helper) passes its key through and names no entry.
    """
    constants = _constants(module)
    tree = _tree(module)
    paths_read: set[tuple[str, ...]] = set()
    calls = []
    inner: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            inner.add(id(node.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and id(node) not in inner:
            keys, cursor, dynamic = [], node, False
            while isinstance(cursor, ast.Subscript):
                key = _literal(cursor.slice, {})
                dynamic = dynamic or key is None
                keys.append(key)
                cursor = cursor.value
            base = _base(cursor, module, constants)
            if base is not None and not dynamic:
                paths_read.add((*base, *reversed(keys)))
        elif isinstance(node, ast.Call):
            readers = _READERS.get(module, {})
            if isinstance(node.func, ast.Name) and node.func.id in readers and node.args:
                key = _literal(node.args[0], {})
                if key is not None:
                    filled = frozenset(item.arg for item in node.keywords) if all(item.arg for item in node.keywords) else None
                    path = (*readers[node.func.id], key)
                    paths_read.add(path)
                    calls.append((path, filled))
    return paths_read, calls


def _lookup(path: tuple[str, ...]):
    value = prompt_data.load(path[0])
    for key in path[1:]:
        value = value[key]
    return value


def _leaves(section: dict, prefix: tuple[str, ...]) -> set[tuple[str, ...]]:
    leaves = set()
    for key, value in section.items():
        if key == "_about":
            continue
        if isinstance(value, dict):
            leaves |= _leaves(value, (*prefix, key))
        else:
            leaves.add((*prefix, key))
    return leaves


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _all_reads() -> set[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    for module in _MODULES:
        found |= _reads(module)[0]
    return found


def _covered(leaf: tuple[str, ...], reads: set[tuple[str, ...]]) -> bool:
    """A leaf is used when it, or a table it sits in, is read by key (a whole dict read is used whole)."""
    return any(leaf[:len(path)] == path for path in reads)


class TableAndSourceAgreeTests(unittest.TestCase):
    def test_every_key_read_is_in_the_tables(self):
        reads = _all_reads()
        self.assertTrue(reads)
        for path in sorted(reads):
            with self.subTest(path=".".join(path)):
                _lookup(path)

    def test_every_vocabulary_entry_is_read(self):
        reads = _all_reads()
        for leaf in sorted(_leaves(prompt_data.load(_VOCABULARY), (_VOCABULARY,))):
            with self.subTest(leaf=".".join(leaf)):
                self.assertTrue(_covered(leaf, reads))
        # A section read whole would make the check above trivial: each one is read by its keys.
        for section in prompt_data.load(_VOCABULARY):
            self.assertNotIn((_VOCABULARY, section), reads, section)

    def test_every_move_refusal_is_read(self):
        reads = _all_reads()
        for leaf in sorted(_leaves(prompt_data.value(_MOVES, "errors"), (_MOVES, "errors"))):
            with self.subTest(leaf=".".join(leaf)):
                self.assertTrue(_covered(leaf, reads))

    def test_every_refusal_gets_the_placeholders_it_names(self):
        for module in (paths, camera_moves, interchange):
            for path, filled in _reads(module)[1]:
                with self.subTest(module=module.__name__, path=".".join(path)):
                    self.assertEqual(filled or frozenset(), _fields(str(_lookup(path))))

    def test_the_formatted_sentences_get_the_placeholders_they_name(self):
        notes = prompt_data.value(_VOCABULARY, "interchange")
        self.assertEqual(_fields(notes["backdrop_note"]), {"kind", "detail", "yaw", "opacity"})
        self.assertEqual(_fields(notes["element_note"]), {"name", "element_id"})
        self.assertEqual(_fields(prompt_data.value(_VOCABULARY, "camera_labels")["template"]), {"shot_id", "function", "who", "size"})
        self.assertEqual(_fields(prompt_data.value(_VOCABULARY, "path_errors")["one_of"]), {"label", "options"})


class TableOrderTests(unittest.TestCase):
    def setUp(self):
        self.sizes = prompt_data.value(_VOCABULARY, "shot_sizes")
        self.angles = prompt_data.value(_VOCABULARY, "angles")

    def test_the_size_aliases_are_read_in_the_order_the_table_lists_them(self):
        flat = tuple((alias, size) for aliases, size in self.sizes["aliases"] for alias in aliases)
        self.assertEqual(coverage._SIZE_ALIASES, flat)
        self.assertEqual([size for _pattern, size in coverage._SIZE_ABBREVIATIONS], [size for _p, size in self.sizes["abbreviations"]])
        self.assertEqual(
            [pattern.pattern for pattern, _size in coverage._SIZE_ABBREVIATIONS],
            [rf"(?<![a-z]){pattern}(?![a-z])" for pattern, _size in self.sizes["abbreviations"]],
        )

    def test_no_alias_hides_behind_an_earlier_shorter_one(self):
        # Longest first: 中近景 before 近景, 大全景 before 全景, "medium close" before "medium".
        for alias, size in coverage._SIZE_ALIASES:
            with self.subTest(alias=alias):
                self.assertEqual(coverage.named_size(alias), size)
                self.assertEqual(coverage.named_size(alias.upper()), size)
        for pattern, size in self.sizes["abbreviations"]:
            for token in pattern.strip("(?:)").split("|"):
                with self.subTest(token=token):
                    self.assertEqual(coverage.named_size(token.upper()), size)
        self.assertEqual(coverage.canonical_size("固定"), self.sizes["default"])

    def test_the_angle_words_are_read_top_down_first(self):
        self.assertEqual(coverage._PITCH_WORDS, tuple((mode, tuple(words)) for mode, words in self.angles["pitch_words"]))
        self.assertTrue({mode for mode, _words in coverage._PITCH_WORDS} <= set(coverage._PITCH_DEG))
        # 正俯 is a top shot, not a high angle; 低位 is ground level, not a low angle.
        self.assertEqual(coverage._pitch("正俯")[0], "top")
        self.assertEqual(coverage._pitch("低位仰拍")[0], "ground")
        self.assertEqual(coverage._pitch("平视"), ("eye", 0.0))
        self.assertEqual(coverage.wants_over_shoulder(coverage.ShotSpec(1, angle="OTS")), True)

    def test_the_blocking_verbs_keep_their_order(self):
        verbs = prompt_data.value(_VOCABULARY, "blocking_verbs")
        self.assertEqual(language.POSTURE_RULES, tuple(("|".join(words), posture) for words, posture in verbs["postures"]))
        self.assertEqual(language.ENTRANCE_WORDS.pattern, "|".join(verbs["entrance"]))
        self.assertEqual(language.TRAVEL_WORDS.pattern, "|".join([*verbs["approach"], *verbs["retreat"]]))
        self.assertEqual(language.RETREAT_WORDS, frozenset(verbs["retreat"]))
        # The first posture named wins, and a verb only counts in its own clause.
        self.assertEqual(language.posture_in("沈砚", "沈砚站起又跪下"), "stand")
        self.assertEqual(language.posture_in("沈砚", "沈砚。跪下"), "stand")
        self.assertEqual(language.travel_in("沈砚", "沈砚，黄琰后退"), "")

    def test_every_size_word_is_a_size_the_projection_knows(self):
        known = {name for name, _height in SHOT_SIZE_HEIGHTS}
        named = {self.sizes[key] for key in ("default", "detail", "insert", "empty", "pair", "over_shoulder_min")}
        named |= {size for _aliases, size in self.sizes["aliases"]} | {size for _p, size in self.sizes["abbreviations"]}
        named |= {*self.sizes["tight"], *self.sizes["wide"], *self.sizes["close_up"], *self.sizes["pair_too_tight"]}
        self.assertEqual(named - known, set())
        self.assertEqual(set(self.sizes["lens_mm"]), known)
        self.assertEqual(set(self.sizes["aim"]), known)
        self.assertEqual(set(axis._WIDE_SIZES), set(coverage._WIDE_SIZES))

    def test_a_camera_and_a_storyboard_shot_default_to_the_same_words(self):
        self.assertEqual(StageCamera.model_fields["shot_size"].default, self.sizes["default"])
        self.assertEqual(StageCamera.model_fields["angle"].default, self.angles["default"])
        self.assertEqual(coverage.ShotSpec(1).size, self.sizes["default"])

    def test_refusals_and_names_read_as_the_tables_say(self):
        with self.assertRaises(paths.PathError) as caught:
            paths.read_points("x", height_m=None)
        self.assertEqual(str(caught.exception), prompt_data.value(_VOCABULARY, "path_errors")["not_a_list"])
        with self.assertRaises(camera_moves.CameraMoveError) as caught:
            camera_moves._path("bogus", StageCamera(id="c", label="c", position=[0, 1, 3], target=[0, 1, 0]), 1.0, 45.0, 1, 2, [], (0.0, 0.0))
        self.assertEqual(str(caught.exception), "未知的运镜预设 'bogus'")
        self.assertEqual(coverage._label(3, "single", [], "近景"), "03 单人-环境-近景")


class NoWordsInCodeTests(unittest.TestCase):
    def test_no_chinese_string_literal_is_left_in_the_stage_modules(self):
        for module in _MODULES:
            tree = _tree(module)
            docstrings = {
                id(node.body[0].value) for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
                and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            }
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                    if not node.value.isascii() and node.value not in _ALLOWED_LITERALS:
                        self.fail(f"{module.__name__}:{node.lineno} keeps {node.value!r} in code")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""The design sheets, the prop and scene turnarounds and the scene-scoped references say what their tables say.

No model, no network. Four modules write prompt text from four tables in ``app/data/prompt``:
``asset_sheets.json``, ``prop_turnaround.json``, ``scene_turnaround.json`` and
``storyboard_scene_context.json``. Each table is checked against the code that reads it in both
directions (every entry is read, every entry the code asks for is there with exactly the placeholders
it fills), the tables whose order decides a first match keep that order, the sentences the reference
images carry are unchanged word for word, and no Chinese string literal is left in the modules
outside docstrings.
"""

from __future__ import annotations

import ast
import inspect
import re
import string
import unittest

from app.core import asset_sheets, prompt_data, prop_turnaround, scene_turnaround, storyboard_scene_context
from app.core.actor_sheet_layout import FULL_BODY_PROPORTION_RULE

# module → the table it owns.
MODULES = {
    asset_sheets: "asset_sheets",
    prop_turnaround: "prop_turnaround",
    scene_turnaround: "scene_turnaround",
    storyboard_scene_context: "storyboard_scene_context",
}
# Helpers that read a top-level entry of the module's own table by a literal key.
TOP_HELPERS = {"_word", "_pattern", "_lengths"}
# Helpers that read one child of a top-level entry: helper → that entry.
CHILD_HELPERS = {"_limit": "limits", "_family_words": "families"}
# The helper functions themselves read with a variable key; nothing else may.
HELPER_DEFS = {"_says", *TOP_HELPERS, *CHILD_HELPERS}
# Chinese text, CJK punctuation and the typographic marks Chinese prompts use (— · × °).
_CJK = re.compile(r"[—·×°⺀-⿟　-〿㐀-䶿一-鿿豈-﫿︰-﹏＀-￯]")
# Chinese string literals a module may still carry outside docstrings, each with the reason. None.
ALLOWED_LITERALS: dict[str, dict[str, str]] = {module.__name__: {} for module in MODULES}


def _tree(module) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name is not None)


def _joined(body) -> str:
    return "".join(body) if isinstance(body, list) else str(body)


def _constant(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class _Reads(ast.NodeVisitor):
    """What one module reads: keys of its own table, ``_says`` calls, formatted ``_word`` templates, other tables."""

    def __init__(self, module) -> None:
        self.module = module
        self.own = MODULES[module]
        self.top: set[str] = set()
        self.children: dict[str, set[str]] = {}
        self.says: list[tuple[str, frozenset[str], int]] = []
        self.formatted: list[tuple[str, frozenset[str], int]] = []
        self.other: set[tuple[str, str]] = set()
        # Tables other modules own, read with a key the code computes (a frame code, a word-list name).
        self.dynamic: set[str] = set()
        self.problems: list[str] = []
        self.function: list[str] = []

    def _file(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            value = getattr(self.module, node.id, None)
            return value if isinstance(value, str) else None
        return _constant(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function.append(node.name)
        self.generic_visit(node)
        self.function.pop()

    def _in_helper(self) -> bool:
        return bool(self.function) and self.function[-1] in HELPER_DEFS

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in {"_says", *TOP_HELPERS, *CHILD_HELPERS}:
            key = _constant(node.args[0]) if node.args else None
            if key is None:
                self.problems.append(f"{func.id} with a key that is not a literal at line {node.lineno}")
            elif func.id == "_says":
                if len(node.args) != 1 or any(item.arg is None for item in node.keywords):
                    self.problems.append(f"_says({key!r}) must name every value as a keyword (line {node.lineno})")
                self.says.append((key, frozenset(item.arg for item in node.keywords), node.lineno))
            elif func.id in CHILD_HELPERS:
                self.children.setdefault(CHILD_HELPERS[func.id], set()).add(key)
            else:
                self.top.add(key)
        elif isinstance(func, ast.Attribute) and func.attr == "format" and isinstance(func.value, ast.Call):
            inner = func.value
            if isinstance(inner.func, ast.Name) and inner.func.id == "_word" and inner.args and _constant(inner.args[0]):
                if node.args or any(item.arg is None for item in node.keywords):
                    self.problems.append(f"_word(...).format must name every value as a keyword (line {node.lineno})")
                self.formatted.append((_constant(inner.args[0]), frozenset(item.arg for item in node.keywords), node.lineno))
        elif (
            isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "prompt_data"
            and func.attr != "load" and len(node.args) >= 2
        ):
            table = self._file(node.args[0])
            keys = [_constant(node.args[1])]
            if isinstance(node.args[1], ast.IfExp):
                keys = [_constant(node.args[1].body), _constant(node.args[1].orelse)]
            if table is None:
                self.problems.append(f"prompt_data.{func.attr} on an unknown table at line {node.lineno}")
            elif None in keys:
                if table != self.own:
                    self.dynamic.add(table)
                elif not self._in_helper():
                    self.problems.append(f"prompt_data.{func.attr}({table!r}, <not a literal>) at line {node.lineno}")
            else:
                for key in keys:
                    if table == self.own:
                        self.top.add(key)
                    else:
                        self.other.add((table, key))
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        value = node.value
        if (
            isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "load"
            and isinstance(value.func.value, ast.Name) and value.func.value.id == "prompt_data" and value.args
        ):
            table, key = self._file(value.args[0]), _constant(node.slice)
            if table is None or key is None:
                self.problems.append(f"prompt_data.load(...)[...] not literal at line {node.lineno}")
            elif table == self.own:
                self.top.add(key)
            else:
                self.other.add((table, key))
        self.generic_visit(node)


def _reads(module) -> _Reads:
    reads = _Reads(module)
    reads.visit(_tree(module))
    return reads


class TablesMatchTheCodeTests(unittest.TestCase):
    def test_the_modules_read_their_tables_only_by_literal_keys(self):
        for module in MODULES:
            with self.subTest(module=module.__name__):
                self.assertEqual(_reads(module).problems, [])

    def test_every_top_level_entry_is_read_and_every_one_read_is_there(self):
        for module, name in MODULES.items():
            table = set(prompt_data.load(name)) - {"_about"}
            read = _reads(module).top
            with self.subTest(table=name):
                self.assertEqual(table - read, set(), "entries nothing reads")
                self.assertEqual(read - table, set(), "entries the module reads that are missing")

    def test_every_sentence_is_used_and_gets_exactly_its_placeholders(self):
        for module, name in MODULES.items():
            reads = _reads(module)
            says = prompt_data.load(name).get("says", {})
            asked = {key for key, _, _ in reads.says}
            with self.subTest(table=name):
                self.assertEqual(set(says) - asked, set(), "sentences nothing reads")
                self.assertEqual(asked - set(says), set(), "sentences the module reads that are missing")
            for key, filled, line in reads.says:
                with self.subTest(table=name, key=key):
                    self.assertEqual(filled, _fields(_joined(says[key])), f"says.{key} (line {line}): placeholders")
                    self.assertTrue(all(isinstance(part, str) and part for part in (says[key] if isinstance(says[key], list) else [says[key]])))

    def test_child_tables_are_read_entry_by_entry(self):
        for module, name in MODULES.items():
            reads = _reads(module)
            for entry, keys in reads.children.items():
                with self.subTest(table=name, entry=entry):
                    self.assertEqual(set(prompt_data.load(name)[entry]), keys)
        self.assertEqual(set(prompt_data.value("prop_turnaround", "families")), set(prop_turnaround._FAMILIES))
        for family, entry in prompt_data.value("prop_turnaround", "families").items():
            with self.subTest(family=family):
                self.assertEqual(set(entry), {"pose", "nouns"})
                self.assertTrue(entry["pose"] and entry["nouns"])
                self.assertTrue(all(isinstance(length, (int, float)) and length > 0 for length in entry["nouns"].values()))
        self.assertTrue(all(isinstance(limit, int) and limit > 0 for limit in prompt_data.value("asset_sheets", "limits").values()))

    def test_plain_words_are_never_templates_and_templates_get_exactly_their_placeholders(self):
        for module, name in MODULES.items():
            reads = _reads(module)
            data = prompt_data.load(name)
            formatted = {key for key, _, _ in reads.formatted}
            for key, filled, line in reads.formatted:
                with self.subTest(table=name, key=key):
                    self.assertEqual(filled, _fields(data[key]), f"{key} (line {line}): placeholders")
            for key in reads.top - formatted - {"says", "limits", "families", "views", "labels", "markdown_sections"}:
                value = data[key]
                if isinstance(value, str) and not key.endswith("pattern") and not key.endswith("split"):
                    with self.subTest(table=name, key=key):
                        self.assertEqual(_fields(value), frozenset(), f"{key} is used as it stands and must not look like a template")

    def test_patterns_compile(self):
        for module, name in MODULES.items():
            templates = {key for key, _, _ in _reads(module).formatted}
            for key, value in prompt_data.load(name).items():
                if key.endswith("pattern") or key.endswith("split"):
                    with self.subTest(table=name, key=key):
                        body = _joined(value)
                        if key in templates:
                            body = body.format(**{field: "x" for field in _fields(body)})
                        re.compile(body)

    def test_the_tables_other_modules_own_have_what_these_modules_read(self):
        for module in MODULES:
            for table, key in sorted(_reads(module).other):
                with self.subTest(module=module.__name__, table=table, key=key):
                    self.assertIn(key, prompt_data.load(table))
        # Keys the code computes: the scene reference's frame codes and the crowd's word lists.
        self.assertEqual(_reads(storyboard_scene_context).dynamic, {"scene_views", "crowd_presence"})
        for frame in ("composition", "space_only", "reverse", "reverse_space"):
            self.assertIn(frame, prompt_data.load("scene_views"))
        for key in ("enter_words", "leave_words"):
            self.assertIn(key, prompt_data.load("crowd_presence"))
        self.assertEqual(set().union(*(_reads(module).dynamic for module in MODULES if module is not storyboard_scene_context)), set())


class OrderTests(unittest.TestCase):
    def test_the_scene_view_slots_keep_their_order_and_names(self):
        slots = ("scene_main", "scene_45", "scene_depth", "scene_detail", "scene_reverse")
        self.assertEqual(tuple(slot for slot, _, _ in scene_turnaround.SCENE_VIEWS), slots)
        self.assertEqual(scene_turnaround.SCENE_VIEW_SLOTS, slots)
        self.assertEqual(scene_turnaround.SCENE_GRID_SLOTS, slots[:4])
        self.assertEqual(scene_turnaround.SCENE_REVERSE_SLOT, "scene_reverse")
        self.assertEqual(set(prompt_data.value("scene_turnaround", "views")), set(slots))
        self.assertEqual(list(scene_turnaround.SCENE_VIEW_LABELS), list(slots))
        self.assertEqual(list(scene_turnaround.SCENE_VIEW_PURPOSES), list(slots))
        for slot, (label, purpose) in prompt_data.value("scene_turnaround", "views").items():
            self.assertEqual(scene_turnaround.SCENE_VIEW_LABELS[slot], label)
            self.assertEqual(scene_turnaround.SCENE_VIEW_PURPOSES[slot], purpose)

    def test_labels_keep_the_prompt_section_order(self):
        own = ["actor", "scene", "prop", "costume", "effect", "product"]
        self.assertEqual(list(prompt_data.value("storyboard_scene_context", "labels")), own)
        self.assertEqual(list(storyboard_scene_context.LABELS)[: len(own)], own)

    def test_the_sheet_document_lists_characters_then_scenes_then_props(self):
        self.assertEqual([attribute for attribute, _ in prompt_data.value("asset_sheets", "markdown_sections")], ["characters", "scenes", "props"])
        self.assertEqual(len(asset_sheets._SCENE_TRAIT_WORDS), 3)

    def test_first_match_tables_keep_their_order(self):
        # A longer unit is tried before the shorter one it ends with.
        units = prop_turnaround._UNIT.split("|")
        self.assertLess(units.index("厘米"), units.index("米"))
        self.assertLess(units.index("mm"), units.index("m"))
        # Hand words: the first one in the table wins.
        first = next(iter(prop_turnaround._HAND_WORDS))
        self.assertEqual(prop_turnaround.stated_length_cm("".join(prop_turnaround._HAND_WORDS)), prop_turnaround._HAND_WORDS[first])
        # The longer noun wins: 牡丹 is a flower, 九转还魂丹 a pill.
        self.assertEqual(prop_turnaround.plan_prop("牡丹").longest_cm, 15.0)
        self.assertEqual(prop_turnaround.plan_prop("九转还魂丹").longest_cm, 1.5)
        self.assertEqual(prop_turnaround.stated_length_cm("三尺二寸"), 3 * 33.0 + 2 * 3.3)
        # Light, material, time: each group gives its first word that appears.
        self.assertEqual(asset_sheets.scene_name("办公室", "冷白顶灯，深夜"), "顶灯深夜办公室")


class SentencesKeptTests(unittest.TestCase):
    """The sentences other modules and the reference images rely on, word for word."""

    def test_the_empty_scene_phrases_and_layouts(self):
        self.assertEqual(asset_sheets.EMPTY_SCENE_PREFIX, "不能出现其他人, 无人, 纯场景,")
        self.assertEqual(asset_sheets.EMPTY_SCENE_SUFFIX, "no humans, empty, landscape only")
        self.assertTrue(scene_turnaround.SCENE_TURNAROUND_INSTRUCTION.startswith(asset_sheets.EMPTY_SCENE_PREFIX + "生成一张影视拍摄场地四视角定妆参考图"))
        self.assertTrue(scene_turnaround.SCENE_TURNAROUND_CLOSING.endswith("四格里都不出现任何人物。" + asset_sheets.EMPTY_SCENE_SUFFIX))
        self.assertIn(FULL_BODY_PROPORTION_RULE + "画面内不得出现任何文字。", asset_sheets.CHARACTER_LAYOUT)
        self.assertEqual(asset_sheets.MIN_SCENE_NAME_CHARS, 4)

    def test_the_reference_image_sentences(self):
        note = storyboard_scene_context.reference_note
        self.assertEqual(
            note(2, {"kind": "actor", "name": "沈砚", "variant": "婚服；", "makeup": "额角伤口。"}),
            "参考图2仅锁定数字演员「沈砚」（造型：婚服）的脸型、发型、体型与服装，不采用图中背景、版式与其他人物，不是额外剧情或额外人物，"
            "图上没有的妆效按文字加上：额角伤口",
        )
        self.assertEqual(
            note(3, {"kind": "prop", "name": "铜针"}),
            # 铜针在尺寸补充表(everyday_items.json)里：参考图那句后面跟着真实尺寸。
            "参考图3仅锁定拍摄道具「铜针」的外形、材质与颜色，不采用图中背景与人物，不是额外剧情或额外人物，真实尺寸约长8×宽0.2×高0.2厘米，和人物同框时按这个比例画",
        )
        self.assertEqual(
            note(4, {"kind": "scene", "name": "太常寺天文台", "view": "scene_45", "layout": "门在画面左侧；窗在右侧。"}),
            "参考图4仅锁定拍摄场地「太常寺天文台」的45°斜角，用于走位与转身时的透视（门在画面左侧，窗在右侧），图中人物不作参考，不是额外剧情或额外人物",
        )
        self.assertEqual(
            note(5, {"kind": "scene", "name": "太常寺天文台", "view": "bogus"}),
            "参考图5仅锁定拍摄场地「太常寺天文台」的空间布局，光线与天色以本场为准、不照搬此图，图中人物不作参考，不是额外剧情或额外人物",
        )
        for number, reference in enumerate((
            {"kind": "actor", "name": "沈砚", "variant": "婚服", "outfit": "红袍", "look_makeup": "泪痕"},
            {"kind": "scene", "name": "殿", "view": "scene_reverse", "frame": "reverse_space", "pair": True, "layout": "门在左"},
            {"kind": "effect", "name": "雷劫"},
        ), start=1):
            text = note(number, reference)
            with self.subTest(reference=reference):
                self.assertTrue(text.startswith(f"参考图{number}仅锁定"))
                self.assertNotIn("；", text)
                self.assertNotIn("。", text)

    def test_the_shot_check_refusals(self):
        context = {"scene_id": "E1S01", "characters": ["沈砚"], "all_character_names": ["沈砚", "贺兰霆"], "actors": [], "scenes": [],
                   "props": [], "effects": [], "costumes": [], "cast_aliases": {}}
        with self.assertRaisesRegex(ValueError, "^分镜画面仍为通用占位内容，请重新拆解当前剧情$"):
            storyboard_scene_context.panel_context(context, {"desc": "剧情推进分镜 3"})
        with self.assertRaisesRegex(ValueError, "^分镜包含当前剧情未出场角色：贺兰霆$"):
            storyboard_scene_context.panel_context(context, {"desc": "贺兰霆走来"})
        panel = storyboard_scene_context.panel_context(context, {"desc": "空殿", "characters_explicit": True})
        self.assertEqual(panel["characters"], ["空镜（无人物）"])
        self.assertEqual(panel["props"], ["本格无额外道具"])
        self.assertEqual(panel["effects"], ["本格无额外特效"])


class NoChineseLiteralTests(unittest.TestCase):
    def test_no_chinese_string_literal_is_left_outside_docstrings(self):
        for module in MODULES:
            tree = _tree(module)
            docstrings = {
                id(node.body[0].value) for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.body and isinstance(node.body[0], ast.Expr) and _constant(node.body[0].value) is not None
            }
            left = sorted({
                node.value for node in ast.walk(tree)
                if _constant(node) is not None and id(node) not in docstrings and _CJK.search(node.value)
            } - set(ALLOWED_LITERALS[module.__name__]))
            with self.subTest(module=module.__name__):
                self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""The face card's, the camera recipes', the transition catalog's and the creative presets' wording
lives in data, and the code reads all of it.

``app/core/face_card.py``, ``camera_recipes.py``, ``transition_catalog.py`` and ``creative_presets.py``
read ``app/data/prompt/<module>.json``. These tests hold the two sides together: every key the code
reads exists, every key the data holds is read, each template carries exactly the placeholders its
call site fills, the first-match and listing tables keep their order and shape, and no Chinese
wording is left in the code.

No model, no network.
"""

import ast
import inspect
import re
import string
import unittest

from app.core import camera_motion
from app.core import camera_recipes as recipes
from app.core import creative_presets as presets
from app.core import face_card as cards
from app.core import prompt_data
from app.core import transition_catalog as transitions

_MODULES = (cards, recipes, transitions, presets)
# Each module's helpers that take a top-level key of its file as their first argument.
_TABLE_HELPERS = {
    cards: {"_word_table", "_rules"},
    recipes: {"_rows"},
    transitions: {"_rows", "_aliases"},
    presets: set(),
}
# The section a module's ``_says`` reads its templates from.
_SAYS_SECTION = {cards: "issues", recipes: "says", transitions: "says", presets: "compile"}
# Keys holding regular expressions (braces there are quantifiers, not placeholders).
_PATTERN_KEYS = {"negation", "segment_split", "fragment_split", "vague_labels", "hard_cut_words", "formula_pattern"}
# A Chinese (or other non-ASCII) string literal a module may keep outside docstrings, with the reason. None today.
_ALLOWED_LITERALS: dict[str, str] = {}


def _tree(module) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _data(module) -> dict:
    return prompt_data.load(module._WORDING)


def _constant(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _calls(module, name: str):
    """``(first argument's constant, keyword names)`` of each ``name(...)`` call in the module."""
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name and node.args:
            yield _constant(node.args[0]), frozenset(keyword.arg for keyword in node.keywords)


def _top_level_reads(module) -> set[str]:
    """Top-level keys read through ``prompt_data.<reader>(_WORDING, "key")`` or a table helper."""
    found: set[str] = set()
    tree = _tree(module)
    # A table helper passes its key through: the calls inside it name no entry.
    passing = {
        id(inner) for helper in ast.walk(tree)
        if isinstance(helper, ast.FunctionDef) and helper.name in _TABLE_HELPERS[module]
        for inner in ast.walk(helper)
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in passing:
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "prompt_data"
            and func.attr != "load" and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name) and node.args[0].id == "_WORDING"
        ):
            key = _constant(node.args[1])
            assert key is not None, f"{module.__name__}:{node.lineno} reads a key that is not a literal"
            found.add(key)
        elif isinstance(func, ast.Name) and func.id in _TABLE_HELPERS[module] and node.args:
            key = _constant(node.args[0])
            assert key is not None, f"{module.__name__}:{node.lineno} reads a table that is not a literal"
            found.add(key)
    return found


def _says_reads(module) -> list[tuple[str, frozenset[str]]]:
    """``(template key, placeholders filled)`` for every ``_says`` call, slots resolved."""
    reads = []
    for key, filled in _calls(module, "_says"):
        if key is None:
            # The only dynamic key: the transition formula's slots, each filled with the slot's text.
            assert module is transitions, module.__name__
            reads.extend((slot, filled) for slot in transitions._FORMULA_SLOTS)
        else:
            reads.append((key, filled))
    return reads


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name is not None)


class KeysReadAndPresentTests(unittest.TestCase):
    def test_every_top_level_key_is_read_and_every_key_read_exists(self):
        for module in _MODULES:
            data = _data(module)
            reads = _top_level_reads(module) | {_SAYS_SECTION[module]}
            with self.subTest(module=module.__name__):
                self.assertEqual(reads - set(data), set(), "read but missing from the data")
                self.assertEqual({key for key in data if not key.startswith("_")} - reads, set(), "in the data but never read")

    def test_every_template_is_read_and_every_template_read_exists(self):
        for module in _MODULES:
            section = _data(module)[_SAYS_SECTION[module]]
            read = {key for key, _filled in _says_reads(module)}
            if module is cards:
                read |= {key for key, _filled in _calls(cards, "_issue")}
            with self.subTest(module=module.__name__):
                self.assertTrue(read)
                self.assertEqual(read - set(section), set(), "read but missing from the data")
                self.assertEqual(set(section) - read, set(), "in the data but never read")

    def test_inner_rows_have_exactly_the_fields_the_code_reads(self):
        for item in _data(cards)["vague_labels"]:
            self.assertEqual(set(item), {"pattern", "ignore_case"})
            self.assertIsInstance(item["ignore_case"], bool)
        for code in ("mixed_bone_system", "label_anchor_conflict", "skin_overload", "vague_population_label"):
            self.assertEqual(set(_data(cards)["issues"][code]), {"message", "suggestion"}, code)
        for category, entry in _data(recipes)["categories"].items():
            with self.subTest(category=category):
                self.assertEqual(set(entry), {"label", "purpose", "levels"})
                for row in entry["levels"].values():
                    self.assertEqual(len(row), 5)
        for row in _data(transitions)["types"]:
            self.assertEqual(tuple(row), transitions._TYPE_COLUMNS)
        for row in _data(transitions)["categories"]:
            self.assertEqual(tuple(row), transitions._CATEGORY_COLUMNS)
        for item in _data(presets)["presets"]:
            self.assertEqual(set(item), set(presets.CreativePreset.model_fields))
        for table in ("angles", "rhythms"):
            for row in _data(recipes)[table]:
                self.assertEqual(len(row), 3, row)


class PlaceholderTests(unittest.TestCase):
    def test_every_template_gets_exactly_its_placeholders(self):
        for module in _MODULES:
            section = _data(module)[_SAYS_SECTION[module]]
            for key, filled in _says_reads(module):
                with self.subTest(module=module.__name__, key=key):
                    self.assertEqual(_fields(str(section[key])), filled)

    def test_every_face_card_finding_gets_exactly_its_placeholders(self):
        issues = _data(cards)["issues"]
        calls = list(_calls(cards, "_issue"))
        self.assertEqual(len(calls), 4)
        for code, filled in calls:
            with self.subTest(code=code):
                wording = issues[code]
                self.assertEqual(_fields(wording["message"]) | _fields(wording["suggestion"]), filled)

    def test_sentences_and_tables_carry_no_placeholders(self):
        # Words, labels and the guide are written out as they are; a stray brace would be a forgotten value.
        for module in _MODULES:
            for key, value in _data(module).items():
                if key in {"_about", _SAYS_SECTION[module]} or key in _PATTERN_KEYS:
                    continue
                for text in _strings(value):
                    with self.subTest(module=module.__name__, key=key, text=text[:20]):
                        self.assertNotIn("{", text)

    def test_the_patterns_compile(self):
        for key in ("negation", "segment_split", "fragment_split"):
            re.compile(_data(cards)[key])
        for item in _data(cards)["vague_labels"]:
            re.compile(item["pattern"])
        for key in ("hard_cut_words", "formula_pattern"):
            re.compile(_data(transitions)[key])


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


class FaceCardTableTests(unittest.TestCase):
    def test_the_layers_render_in_their_order_and_parse_back(self):
        self.assertEqual([key for key, _label in cards.FACE_LAYERS], ["identity", "bone", "features", "skin", "hair", "physique"])
        self.assertEqual([key for key, _label in cards.STATE_LAYER_FIELDS], ["bone", "features", "skin", "hair", "body"])
        self.assertEqual(cards.FACE_LAYERS, tuple(tuple(pair) for pair in _data(cards)["layers"]))
        self.assertEqual(set(cards._SEGMENT_LABELS.values()), {key for key, _label in cards.FACE_LAYERS} | {"other", "negatives"})
        # Every layer name the card writes is a name the parser sends back to that layer.
        card = cards.parse_face_card(cards.render_face_card(cards.parse_face_card("28岁东亚女性；瓜子脸；内双；冷白肤色；黑长发；高挑；米白风衣")))
        for key, _label in cards.FACE_LAYERS:
            self.assertTrue(card.layer(key), key)
        self.assertEqual(card.other, ["米白风衣"])

    def test_the_layer_rules_are_read_first_match_in_file_order(self):
        self.assertEqual(cards._LAYER_RULES, tuple((layer, tuple(words)) for layer, words in _data(cards)["layer_rules"]))
        self.assertEqual({layer for layer, _words in cards._LAYER_RULES}, {key for key, _label in cards.FACE_LAYERS} | {"other"})
        # Clothing before features, skin before features, bone words before features, the generic face late.
        for fragment, layer in (
            ("眼镜", "other"), ("散发着清冷气质", "identity"), ("眼下细纹", "skin"), ("眉弓突出", "bone"),
            ("细眉", "features"), ("瘦削的脸", "bone"), ("清瘦", "physique"), ("28岁女性", "identity"), ("xyz", "other"),
        ):
            with self.subTest(fragment=fragment):
                self.assertEqual(cards._classify(fragment), layer)

    def test_the_framing_words_read_medium_before_close(self):
        self.assertEqual([framing for framing, _words in cards._FRAMING_PATTERNS], ["full", "close"])
        self.assertEqual(cards.framing_for_shot_size("中近景"), "close")
        self.assertEqual(cards.framing_for_shot_size("大全景"), "full")
        self.assertEqual(cards.framing_for_shot_size("不知道"), "all")

    def test_the_bone_systems_match_longest_first_and_name_both_systems(self):
        systems = {"east_asian", "european"}
        for key in ("bone_system_terms", "mixing_negatives", "population_labels", "system_names"):
            self.assertEqual(list(_data(cards)[key]), ["east_asian", "european"], key)
        self.assertEqual(set(cards._BONE_SYSTEM_TERMS), systems)
        self.assertEqual(cards.bone_systems(cards.parse_face_card("无内眦褶")), {"european": ["无内眦褶"]})
        # A one-system card avoids the anchors listed under its own system.
        self.assertEqual(cards.card_negatives(cards.parse_face_card("浅眼窝")), list(cards._MIXING_NEGATIVES["east_asian"]))

    def test_negation_and_splits_and_the_audit_read_as_the_tables_say(self):
        self.assertEqual(cards._NEGATION.flags & re.I, re.I)
        self.assertEqual([bool(p.flags & re.I) for p in cards._VAGUE_LABELS], [item["ignore_case"] for item in _data(cards)["vague_labels"]])
        self.assertEqual(cards.parse_face_card("不要磨皮；别致的发簪").negatives, ["磨皮"])
        self.assertEqual(cards.MAX_SKIN_TERMS, _data(cards)["max_skin_terms"])
        issue = cards.audit_face_card(cards.parse_face_card("东亚女性，浅眼窝，皮肤有毛孔，绒毛，细纹，雀斑"))[0]
        self.assertEqual(issue.code, "skin_overload")
        self.assertEqual(issue.message, _data(cards)["issues"]["skin_overload"]["message"].format(limit=cards.MAX_SKIN_TERMS))


class CameraRecipeTableTests(unittest.TestCase):
    def test_the_categories_keep_their_listing_order(self):
        self.assertEqual(list(recipes.RECIPE_CATEGORIES), list(_data(recipes)["categories"]))
        self.assertEqual([item["value"] for item in recipes.recipe_catalog()][:2], ["entrance", "tracking"])

    def test_every_level_names_a_known_move_angle_and_rhythm(self):
        intensities = [key for key, _label in recipes.INTENSITIES]
        self.assertEqual(intensities, ["strong", "medium", "soft"])
        angles = {key for key, _zh, _en in recipes.ANGLES}
        rhythms = {key for key, _zh, _en in recipes.RHYTHMS}
        self.assertIn("eye_level", angles)
        self.assertTrue({"fast", "slow", "steady"} <= rhythms)
        for category, entry in recipes.RECIPE_CATEGORIES.items():
            self.assertEqual(list(entry["levels"]), intensities, category)
            for level, (move, angle, rhythm, zh, en) in entry["levels"].items():
                with self.subTest(category=category, level=level):
                    self.assertEqual(camera_motion.normalize_camera_motion(move)[0], move)
                    self.assertIn(move, camera_motion.CAMERA_MOTION_LABELS)
                    self.assertIn(angle, angles)
                    self.assertIn(rhythm, rhythms)
                    self.assertTrue(zh and en)
                    self.assertIsInstance(entry["levels"][level], tuple)

    def test_the_angle_words_are_read_in_table_order(self):
        self.assertEqual(recipes.ANGLES, tuple(tuple(row) for row in _data(recipes)["angles"]))
        self.assertEqual(recipes._angle_key("过肩仰拍"), "low_angle")  # 仰拍 is listed before 过肩
        self.assertEqual(recipes._angle_key("随便"), "eye_level")


class TransitionTableTests(unittest.TestCase):
    def test_the_types_and_categories_keep_their_order_and_ids(self):
        self.assertEqual(
            [value for value, *_ in transitions.TRANSITION_TYPES],
            ["cut", "fade", "dissolve", "flash", "wipe", "push_pull", "match_cut", "montage", "sound_bridge"],
        )
        self.assertEqual(
            [value for value, *_ in transitions.TRANSITION_CATEGORIES],
            ["occlusion", "camera_move", "action", "light", "time", "emotion", "space", "narrative", "opening"],
        )
        self.assertEqual(list(transitions._TYPE_SYNONYMS), [value for value, *_ in transitions.TRANSITION_TYPES])
        self.assertEqual(list(transitions._CATEGORY_SYNONYMS), [value for value, *_ in transitions.TRANSITION_CATEGORIES])
        self.assertTrue({pacing for *_, pacing in transitions.TRANSITION_TYPES} <= {"any", "slow", "medium", "fast"})
        self.assertTrue(all(isinstance(row, tuple) for row in transitions.TRANSITION_TYPES + transitions.TRANSITION_CATEGORIES))

    def test_the_rewrites_and_the_guide_read_as_the_tables_say(self):
        self.assertEqual(transitions.smooth_text("声音先行硬切，直切，切入"), "声音先行衔接，连贯衔接，进入")
        self.assertEqual(transitions.TRANSITION_PROMPT_GUIDE, "".join(_data(transitions)["prompt_guide"]))
        self.assertEqual(transitions.transition_label("bogus"), _data(transitions)["fallback_label"])
        self.assertEqual(transitions.transition_label("bogus"), transitions.transition_label("match_cut"))
        self.assertEqual(
            [slot for slot in transitions._FORMULA_SLOTS],
            [name for name in inspect.signature(transitions.compose_transition).parameters if name in transitions._FORMULA_SLOTS],
        )


class CreativePresetTableTests(unittest.TestCase):
    def test_the_presets_keep_their_order_and_valid_ids(self):
        ids = [preset.id for preset in presets.CreativePresetRegistry().list()]
        self.assertEqual(ids, [item["id"] for item in _data(presets)["presets"]])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "h3-prompt-writing")
        for preset_id in ids:
            self.assertTrue(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", preset_id), preset_id)
        self.assertTrue(all(isinstance(preset.instructions, tuple) and preset.instructions for preset in presets._PRESETS))

    def test_the_compiled_prompt_lists_every_gate_in_order(self):
        compiled = presets.CreativePresetRegistry().compile("deep-emotion", "内容")
        self.assertEqual(compiled.required_gates, list(_data(presets)["global_gates"]))
        lines = compiled.prompt.split("\n")
        gate_lines = [line for line in lines if line.removeprefix("- ") in compiled.required_gates]
        self.assertEqual([line.removeprefix("- ") for line in gate_lines], compiled.required_gates)


class NoWordsInCodeTests(unittest.TestCase):
    def test_no_chinese_string_literal_is_left_in_the_four_modules(self):
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

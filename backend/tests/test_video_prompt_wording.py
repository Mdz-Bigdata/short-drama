# -*- coding: utf-8 -*-
"""The clip prompt's and the prompt packages' wording live in data, and the code reads all of it.

``app/core/video_prompt_engine.py`` reads ``app/data/prompt/video_prompt_engine.json`` (its own
sentences, labels, separators and split patterns) next to the word tables it already read from
``clip_prompt.json``; ``app/core/prompt_packages.py`` reads ``app/data/prompt/prompt_packages.json``.
These tests hold the two sides together: every key the code reads exists, every key the data
holds is read, each template carries exactly the placeholders its call site fills, the tables
keep their order, and no Chinese wording is left in the code.
"""

import ast
import re
import string
import unittest
from pathlib import Path

from app.core import prompt_data, style_packs
from app.core import prompt_packages as pp
from app.core import video_prompt_engine as vpe

CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")
# Chinese string literals allowed to stay in code: (module file, literal) -> why.
ALLOWED_LITERALS: dict[tuple[str, str], str] = {
    ("prompt_packages.py", "正常"): (
        "plan_packages(delivery=...) default: a code value checked against h3_sound_design.PACE_BY_DELIVERY's keys "
        "and passed by agent_tools / drama_api, not wording"
    ),
}

VPE = prompt_data.load("video_prompt_engine")
PP = prompt_data.load("prompt_packages")


def _tree(module) -> ast.Module:
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


VPE_TREE = _tree(vpe)
PP_TREE = _tree(pp)


def _fields(template: str) -> set[str]:
    return {name.split(".")[0].split("[")[0] for _, name, _, _ in string.Formatter().parse(template) if name is not None}


def _named(node: ast.expr) -> set[str]:
    """The key(s) an argument names: a string constant, or either arm of ``a if c else b``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _named(node.body) | _named(node.orelse)
    return set()


def _calls(tree: ast.Module, func_name: str):
    """``(keys named in the first argument, keyword names)`` of each ``func_name(...)`` call."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name and node.args:
            yield _named(node.args[0]), {keyword.arg for keyword in node.keywords}


def _keys_of_calls(tree: ast.Module, func_name: str) -> set[str]:
    return {key for keys, _ in _calls(tree, func_name) for key in keys}


def _data_keys(tree: ast.Module, file_var: str) -> set[str]:
    """Keys read straight through ``prompt_data.<reader>(<file_var>, "key")``."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "prompt_data" and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name) and node.args[0].id == file_var and isinstance(node.args[1], ast.Constant)
        ):
            found.add(node.args[1].value)
    return found


def _chinese_literals(module) -> list[tuple[int, str]]:
    """Chinese string constants outside docstrings (f-string pieces included)."""
    tree = _tree(module)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    return [
        (node.lineno, node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings and CJK.search(node.value)
    ]


# What each template is filled with at its call site.
VPE_FIELDS = {
    "bridge": {"move", "landing"}, "bridge_landing": {"landing"}, "prop_held": {"prop", "holder"},
    "lock_space": {"scene", "blocking"}, "lock_state": {"cast", "state", "eyeline"}, "lock_eyeline": {"eyeline"},
    "structure_single": {"aspect"}, "cut_in": {"label"}, "camera": {"size", "move"}, "dialogue": {"label", "lines"},
    "end_state": {"end_state"}, "anchors": {"notes"}, "structure": {"items"}, "subject": {"timeline"},
    "expression": {"text"}, "composition": {"text"}, "environment": {"text"}, "effects": {"text"},
    "dialogue_notes": {"text"}, "sound_layers": {"text"}, "rules": {"rules"}, "contact": {"how"},
    "contact_support": {"prop"}, "contact_rest": {"prop"}, "contact_grip": {"prop"}, "body_contact": {"how"},
    "body_inside": {"item", "who"}, "body_ride": {"item", "who"}, "body_lie": {"item", "who"}, "body_seat": {"item", "who"},
    "body_lean": {"item", "who"}, "handoff_open": {"surface"},
    "handoff_behind": {"barriers", "item"}, "handoff": {"a", "b", "where", "item", "behind"},
    "distinct_many": {"names", "count"}, "costume_pair": {"wearer", "costume"}, "anchor_cast": {"cast", "distinct"},
    "anchor_costumes": {"costumes"}, "anchor_scene": {"scenes"}, "anchor_props": {"props"},
    "appearance_line": {"name", "look"}, "appearance": {"lines"}, "delivery_note": {"note"}, "lead": {"name", "action"},
    "off_screen_only": {"text"}, "only_speaker": {"names"}, "silent_cast": {"names"}, "speaker_note": {"text", "only", "silent"},
    "extend": {"source", "seconds"}, "extend_light": {"light"}, "extend_space": {"snapshot"}, "extend_mask": {"mask"},
    "expression_reading": {"reading"}, "reaction_after": {"words", "reaction"}, "expression_back": {"text"},
    "expression_back_bare": set(), "off_screen_absent": {"names"},
}
PP_FIELDS = {
    "few_shots": {"package", "count", "seconds", "low", "high"},
    "slow_line": {"package", "shot", "source", "delivery", "spoken", "seconds"},
    "cast_item": {"name", "lock"}, "package_head": {"index", "start", "end"}, "style_lock": {"style", "phase"},
    "cast_lock": {"cast"}, "light_lock": {"lighting"}, "carried_lock": {"state"}, "spatial_lock": {"lock"},
    "package_shot": {"index", "start", "end", "size", "motion", "action", "line"}, "package_line": {"dialogue"},
    "negatives_base": {"negatives"}, "negatives_dynamic": {"risks"},
    "continuous_head": {"index", "seconds", "phase"}, "continuous_cast": {"cast"}, "continuous_space": {"space"},
    "continuous_light": {"light"}, "continuous_style": {"style"},
    "continuous_shot": {"start", "end", "size", "motion", "action", "line"}, "continuous_line": {"dialogue"},
    "continuous_negatives": {"negatives"}, "fight_head": {"index", "count", "phase"}, "fight_style": {"style"},
    "fight_cast": {"fighters"}, "fight_ground": {"scene"}, "fight_shot": {"start", "end", "seconds", "size", "motion", "action"},
    "fight_negatives": {"negatives"}, "script_title": {"title"}, "mention": {"name"}, "script_cast": {"name", "lock"},
    "script_scene": {"scene", "lock"}, "script_light": {"light"}, "script_line": {"order", "shot", "dialogue"},
    "script_line_count": {"count"}, "script_board_head": {"seconds"}, "segment_head": {"order", "seconds"},
    "segment_light": {"scene", "light"}, "shot_head": {"order", "position", "seconds", "size"}, "shot_scene": {"scene"},
    "shot_cast": {"cast"}, "shot_subject": {"subject"}, "shot_action": {"action"}, "shot_line": {"dialogue"},
    "shot_motion": {"motion"}, "shot_light": {"light"}, "shot_sound": {"sound"}, "shot_style": {"style"},
    "shot_bridge": {"landing"}, "segment_check": {"count", "seconds", "max_shots", "max_seconds"},
    "render_head": {"title", "variant", "seconds", "count", "total", "delivery"},
}


class EveryKeyIsReadAndExistsTests(unittest.TestCase):
    def test_the_clip_prompt_reads_exactly_the_keys_its_wording_file_holds(self):
        self.assertEqual(_keys_of_calls(VPE_TREE, "_says"), set(VPE["says"]))
        self.assertEqual(_keys_of_calls(VPE_TREE, "_pattern"), set(VPE["patterns"]))
        top = _keys_of_calls(VPE_TREE, "_word") | _data_keys(VPE_TREE, "_WORDING")
        self.assertEqual(top | {"says", "patterns"}, {key for key in VPE if not key.startswith("_")})

    def test_the_word_tables_it_already_read_are_still_there(self):
        clip = prompt_data.load("clip_prompt")
        read = _data_keys(VPE_TREE, "_DATA")
        self.assertTrue(read)
        self.assertLessEqual(read, set(clip))

    def test_the_packages_read_exactly_the_keys_their_wording_file_holds(self):
        self.assertEqual(_keys_of_calls(PP_TREE, "_says"), set(PP["says"]))
        self.assertEqual(_keys_of_calls(PP_TREE, "_pattern"), set(PP["patterns"]))
        top = _keys_of_calls(PP_TREE, "_word") | _data_keys(PP_TREE, "_WORDING")
        self.assertEqual(top | {"says", "patterns"}, {key for key in PP if not key.startswith("_")})

    def test_every_pattern_compiles(self):
        for data in (VPE, PP):
            for key, text in data["patterns"].items():
                with self.subTest(key):
                    re.compile(text)


class TemplatePlaceholderTests(unittest.TestCase):
    def _check(self, data, tree, expected):
        self.assertEqual(set(expected), set(data["says"]))
        for key, template in data["says"].items():
            self.assertEqual(_fields(template), expected[key], key)
        for keys, keywords in _calls(tree, "_says"):
            for key in keys:
                self.assertEqual(keywords, expected[key], key)

    def test_each_clip_prompt_sentence_names_exactly_what_its_call_site_fills(self):
        self._check(VPE, VPE_TREE, VPE_FIELDS)

    def test_each_package_sentence_names_exactly_what_its_call_site_fills(self):
        self._check(PP, PP_TREE, PP_FIELDS)

    def test_fixed_words_carry_no_placeholders(self):
        for name, data in (("video_prompt_engine", VPE), ("prompt_packages", PP)):
            for key, value in data.items():
                if key.startswith("_") or key in ("says", "patterns"):
                    continue
                for text in value if isinstance(value, list) else [value]:
                    if isinstance(text, str):
                        self.assertEqual(_fields(text), set(), f"{name}.{key}")


class TablesKeepTheirShapeTests(unittest.TestCase):
    def test_the_phases_are_four_and_in_order(self):
        self.assertEqual(len(PP["phases"]), 4)
        self.assertEqual(list(pp._PHASES), PP["phases"])

    def test_the_fight_negatives_keep_their_order(self):
        self.assertEqual(list(pp._FIGHT_NEGATIVES), PP["fight_negative_words"])
        self.assertEqual(PP["fight_negative_words"][-2:], ["无字幕", "无水印"])

    def test_the_no_reference_rewrites_still_find_the_anchor_sentences(self):
        """video_references rewrites these anchor sentences when no picture travels: they must stay verbatim."""
        rewrites = dict(prompt_data.pairs("clip_prompt", "no_reference_rewrites"))
        self.assertIn("脸型、发型、服装与体型以参考图为准", VPE["says"]["anchor_cast"])
        self.assertIn("；" + VPE["same_person"], rewrites)
        anchors = vpe._asset_anchor_sections(vpe.ShotPromptInput(
            shot_index=1, duration_seconds=5, shot_size="中景", camera_movement="固定", subject_action="林夏站着",
            scene="茶馆", blocking="林夏居中", start_state="林夏站定", end_state="林夏站定", characters=["林夏", "周教授"],
            cast_refs=["林夏", "周教授"],
        ))
        self.assertTrue(any(old in anchors["anchor_cast"] for old in rewrites))


class NoChineseInCodeTests(unittest.TestCase):
    def test_no_chinese_literal_is_left_outside_docstrings(self):
        for module in (vpe, pp):
            name = Path(module.__file__).name
            left = [(line, text) for line, text in _chinese_literals(module) if (name, text) not in ALLOWED_LITERALS]
            self.assertEqual(left, [], name)

    def test_every_allowed_literal_is_still_there(self):
        present = {(Path(module.__file__).name, text) for module in (vpe, pp) for _, text in _chinese_literals(module)}
        self.assertLessEqual(set(ALLOWED_LITERALS), present)


class TheWordingReachesThePromptTests(unittest.TestCase):
    def test_a_sentence_changed_in_data_is_what_the_prompt_says(self):
        shot = vpe.ShotPromptInput(
            shot_index=1, duration_seconds=6, shot_size="近景", camera_movement="固定",
            subject_action="林夏把纸杯递给周教授", scene="咖啡店", blocking="隔着柜台", start_state="林夏端着纸杯",
            end_state="周教授接住纸杯", props=["纸杯"], characters=["林夏", "周教授"], dialogue="林夏：拿着。",
        )
        text = vpe.compile_shot_prompt(style_packs.FILM_35MM, shot, model="seedance2.0").text
        self.assertIn(VPE["dialogue_label_native"], text)
        self.assertIn(VPE["says"]["handoff_open"].format(surface="柜台"), text)

    def test_the_package_header_is_the_data_template(self):
        plan = pp.plan_packages([{"shot_id": 1, "duration": "4s", "desc": "林夏推门进来", "characters": ["林夏"]}])
        text = pp.render(plan, pp.PackageContext(pack=style_packs.FILM_35MM))
        self.assertTrue(text.startswith("# " + PP["render_title_default"] + "｜standard｜"))
        self.assertIn(PP["package_no_line"], text)


if __name__ == "__main__":
    unittest.main()

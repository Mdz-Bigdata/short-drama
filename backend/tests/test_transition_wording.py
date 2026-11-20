# -*- coding: utf-8 -*-
"""The cut plan's and the camera vocabulary's wording live in data, and the code reads all of it.

``app/core/shot_transitions.py`` reads ``app/data/prompt/shot_transitions.json``;
``app/core/camera_motion.py`` reads ``app/data/prompt/camera_amounts.json``. These tests hold the
two sides together: every key the code reads exists, every key the data holds is read, each
template carries exactly the placeholders its call site fills, first-match tables keep their
order, the film's cut specs keep their shape, and no Chinese wording is left in the code.
"""

import ast
import re
import string
import unittest
from pathlib import Path

from app.core import camera_motion as cm
from app.core import prompt_data
from app.core import shot_transitions as cuts

CORE = Path(cuts.__file__).resolve().parent
CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")
# Chinese string literals allowed to stay in code: (module file, literal) -> why. Empty on purpose.
ALLOWED_LITERALS: dict[tuple[str, str], str] = {}


def _tree(module) -> ast.Module:
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _fields(template: str) -> set[str]:
    return {name.split(".")[0].split("[")[0] for _, name, _, _ in string.Formatter().parse(template) if name is not None}


def _named(node: ast.expr) -> set[str]:
    """The key(s) an argument names: a string constant, or either arm of ``a if c else b`` (never the condition)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _named(node.body) | _named(node.orelse)
    return set()


def _keys_of_calls(tree: ast.Module, func_name: str) -> set[str]:
    """Every string constant in the first argument of each ``func_name(...)`` call (both arms of an ``a if c else b``)."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name and node.args:
            found |= _named(node.args[0])
    return found


def _calls(tree: ast.Module, func_name: str):
    """``(keys named in the first argument, keyword names)`` of each ``func_name(...)`` call."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name and node.args:
            keys = _named(node.args[0])
            yield keys, {keyword.arg for keyword in node.keywords}


def _words_keys(tree: ast.Module) -> set[str]:
    """Keys read through ``prompt_data.words(_WORDING, "key")`` / ``prompt_data.value(...)``."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "prompt_data" and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)
        ):
            found.add(node.args[1].value)
    return found


ST = prompt_data.load("shot_transitions")
CA = prompt_data.load("camera_amounts")
ST_TREE = _tree(cuts)
CM_TREE = _tree(cm)

# What each template is filled with at its call site.
SAYS_FIELDS = {
    "cut_label": {"device", "technique"}, "edit_line": {"label", "body", "join"}, "opening_in": {"join"},
    "opening_in_fade": {"join"}, "summary_cut": {"from_shot", "to_shot", "label"}, "summary_carries": {"carries"},
    "shot_pair": {"a", "b"}, "exit_entry_pair": {"a", "b", "side"}, "size_step_item": {"a", "a_size", "b", "b_size"}, "thirty_degree_tail": {"min_angle"},
    "thirty_degree_passed": {"min_angle"}, "pov_orphan": {"shot"}, "look_unanswered": {"shot", "looker", "seen"},
    "move_pair": {"a", "a_move", "b", "b_move"}, "state_jump": {"name", "a", "b", "gap"},
    "cause_inverted": {"a", "effect", "b", "cause"}, "light_hours": {"a", "b"}, "light_tones": {"a", "a_tone", "b", "b_tone"},
    "rhythm_even": {"seconds"}, "rhythm_slow": {"shot", "seconds"}, "action_replay": {"a", "action", "b"},
    "energy_clash": {"a", "a_move", "b", "b_move"}, "energy_unmotivated": {"b", "b_move"}, "breath_locked": {"scene", "count"},
    "breath_violent": {"shot", "move"}, "attention_jump": {"name", "a", "b", "span"}, "size_closer": {"steps"},
    "size_wider": {"steps"}, "continuity_in": {"shot", "label", "carries", "step"}, "start_held": {"label"},
    "continuity_out": {"shot", "label", "carries"},
}
CUT_FIELDS = {
    "graphic_match": {"word_a", "word_b", "shape"}, "object_carry": {"token"}, "action_rhyme": {"before", "after"},
    "occlusion": {"occluder"}, "eyeline_match": {"looker"}, "action_match": {"action"},
}
EDIT_OUT_FIELDS = {"action_match": {"carries"}, "eyeline_match": {"looker"}, "graphic_match": {"head"}, "action_rhyme": {"head"},
                   "occlusion": {"head"}, "object_carry": {"carries"}}
EDIT_IN_FIELDS = {"eyeline_match": {"looker"}, "reaction": {"reactor"}, "object_carry": {"carries"}}
EDIT_VALUES = {"carries", "looker", "head", "reactor"}
RENDER_FIELDS = {"with_amount": {"phrase", "amount"}, "minimax": {"command", "phrase"}, "named": {"phrase", "canonical"}}
PROBLEM_FIELDS = {"stacked": {"classes", "count"}}


class EveryKeyIsReadAndExistsTests(unittest.TestCase):
    def test_the_cut_plan_reads_exactly_the_keys_its_data_file_holds(self):
        says = _keys_of_calls(ST_TREE, "_says")
        self.assertEqual(says, set(ST["says"]))
        self.assertEqual(_keys_of_calls(ST_TREE, "_cut"), set(ST["cuts"]))
        self.assertEqual(_keys_of_calls(ST_TREE, "_pattern"), set(ST["patterns"]))
        top = _keys_of_calls(ST_TREE, "_word") | _keys_of_calls(ST_TREE, "_table") | _words_keys(ST_TREE)
        self.assertEqual(top | {"says", "patterns"}, {key for key in ST if not key.startswith("_")})

    def test_tables_keyed_by_code_values_hold_exactly_those_values(self):
        self.assertEqual(list(ST["technique_names"]), list(cuts._TECHNIQUES))
        self.assertEqual(set(ST["watch"]), set(cuts._TECHNIQUES))
        self.assertEqual(set(cuts._TECHNIQUES), set(cuts.Technique.__args__))
        self.assertEqual(set(ST["join_out"]), set(cuts._MOTION_JOINS))
        self.assertEqual(set(ST["join_in"]), set(cuts._MOTION_JOINS))
        self.assertEqual(set(cuts._MOTION_JOINS), set(cuts.MotionJoin.__args__))
        self.assertEqual(list(ST["emotion_words"]), list(cuts._EMOTION_ORDER))
        self.assertEqual(set(ST["tone_names"]), {"warm", "cool"})
        self.assertEqual(set(ST["edit_out"]), set(cuts._TECHNIQUES) - {"opening"})
        self.assertEqual(set(ST["edit_in"]), set(cuts._TECHNIQUES) - {"opening"} | {"time_passage_same_place"})
        self.assertLessEqual(set(ST["carries_heads"]), set(ST["edit_out"]))
        self.assertEqual(set(ST["pan_side_words"]), {"left", "right"})
        self.assertEqual(set(ST["heading_words"]), {"left", "right"})

    def test_the_camera_vocabulary_reads_exactly_the_keys_it_added(self):
        top = _keys_of_calls(CM_TREE, "_table")
        self.assertEqual(top, {key for key in CA if not key.startswith("_")})
        self.assertEqual(_keys_of_calls(CM_TREE, "_says"), set(CA["problems"]))
        motions = [value for value, _ in cm.CAMERA_MOTIONS]
        for key in ("motion_labels", "motion_synonyms", "phrases"):
            self.assertEqual(list(CA[key]), motions, key)
        self.assertEqual(list(CA["amounts"]), [value for value in motions if value != "Static"])
        self.assertEqual(set(CA["minimax_commands"]), set(motions) - {"Orbit"})
        shot_types = [value for value, _ in cm.SHOT_TYPES]
        for key in ("shot_type_labels", "shot_type_synonyms"):
            self.assertEqual(list(CA[key]), shot_types, key)
        self.assertLessEqual(set(CA["opposed_classes"]) | {CA["orbit_class"]}, {name for name, _ in CA["move_classes"]})


class TemplatePlaceholderTests(unittest.TestCase):
    def test_each_sentence_names_exactly_what_its_call_site_fills(self):
        for key, template in ST["says"].items():
            self.assertEqual(_fields(template), SAYS_FIELDS.get(key, set()), key)
        for keys, keywords in _calls(ST_TREE, "_says"):
            for key in keys:
                self.assertEqual(keywords, SAYS_FIELDS.get(key, set()), key)

    def test_each_cut_case_names_exactly_what_the_decision_hands_it(self):
        for case, row in ST["cuts"].items():
            self.assertEqual(set(row), {"carries", "reason"}, case)
            self.assertEqual(_fields(row["carries"]) | _fields(row["reason"]), CUT_FIELDS.get(case, set()), case)
        for keys, keywords in _calls(ST_TREE, "_cut"):
            for key in keys:
                self.assertEqual(keywords, CUT_FIELDS.get(key, set()), key)

    def test_the_two_sides_of_a_cut_use_only_the_values_the_edit_text_offers(self):
        for technique, template in ST["edit_out"].items():
            self.assertEqual(_fields(template), EDIT_OUT_FIELDS.get(technique, set()), technique)
            self.assertLessEqual(_fields(template), EDIT_VALUES)
        for technique, template in ST["edit_in"].items():
            self.assertEqual(_fields(template), EDIT_IN_FIELDS.get(technique, set()), technique)
            self.assertLessEqual(_fields(template), EDIT_VALUES)
        for key in ("technique_names", "watch", "join_out", "join_in", "tone_names"):
            for name, text in ST[key].items():
                self.assertEqual(_fields(text), set(), f"{key}.{name}")
        for text in ST["table_brief"]:
            self.assertEqual(_fields(text), set())

    def test_camera_phrasings_and_lint_sentences_name_exactly_their_values(self):
        for key, template in CA["render"].items():
            self.assertEqual(_fields(template), RENDER_FIELDS[key], key)
        self.assertEqual(set(CA["render"]), set(RENDER_FIELDS))
        for key, template in CA["problems"].items():
            self.assertEqual(_fields(template), PROBLEM_FIELDS.get(key, set()), key)
        for keys, keywords in _calls(CM_TREE, "_says"):
            for key in keys:
                self.assertEqual(keywords, PROBLEM_FIELDS.get(key, set()), key)
        for table in ("phrases", "motion_labels", "shot_type_labels", "minimax_commands"):
            for name, text in CA[table].items():
                self.assertEqual(_fields(text), set(), f"{table}.{name}")


class FirstMatchOrderTests(unittest.TestCase):
    def test_the_code_tables_follow_the_data_in_order(self):
        self.assertEqual(cuts._ACTION_FAMILIES, tuple(tuple(family) for family in ST["action_families"]))
        self.assertEqual(cuts._CAUSALITY, tuple((tuple(c), tuple(e)) for c, e in ST["causality"]))
        self.assertEqual(cuts._SHAPES, tuple((label, tuple(words)) for label, words in ST["shapes"]))
        self.assertEqual(cuts._EMOTIONS, tuple((label, tuple(ST["emotion_words"][label])) for label in ("grief", "fear", "rage", "comic", "tender")))
        self.assertEqual(cuts._TOKENS, tuple(ST["tokens"]))
        self.assertEqual(cm._MOVE_CLASSES[0][0], "推近")
        self.assertEqual([name for name, _ in cm._MOVE_CLASSES], [name for name, _ in CA["move_classes"]])
        self.assertEqual(cm._MOTION_SYNONYMS["Push In"], tuple(CA["motion_synonyms"]["Push In"]))

    def test_the_first_hit_wins(self):
        self.assertEqual(cuts._shape("瞳孔映着剑身"), ("圆形", "瞳孔"))
        self.assertEqual(cuts._emotion("泪中带着哈哈的笑"), "grief")
        self.assertEqual(cuts._time_of_day("深夜，阳光般的灯"), "night")
        first = cuts._view({"shot_id": 1, "desc": "沈砚伸手抓住剑", "characters": ["沈砚"]}, 1, None)
        second = cuts._view({"shot_id": 2, "desc": "沈砚握住剑柄", "characters": ["沈砚"]}, 2, None)
        self.assertEqual(cuts._shared_action(first, second), "伸手")
        self.assertEqual(cm.move_classes("手持环绕，横移，推近"), ["推近", "移", "环绕", "手持"])
        # A label outranks a colloquial alias of the same length.
        self.assertEqual(cm.normalize_camera_motion("缓慢推近"), ("Zoom In", True))


class CutSpecShapeTests(unittest.TestCase):
    def test_the_film_s_cut_specs_keep_their_shape(self):
        from app.service.drama_service import final_cut_transitions

        def row(shot_id, desc, **extra):
            return {"shot_id": shot_id, "scene_id": extra.pop("scene_id", "E1S01"), "scene": extra.pop("scene", "书房"),
                    "size": "中景", "motion": "固定", "desc": desc, "duration": "3s", "characters": extra.pop("cast", ["沈砚"]), **extra}

        plan = cuts.plan_transitions([
            row(1, "沈砚立于庭中"), row(2, "沈砚伸手去拿剑"), row(3, "次日，沈砚仍伏在案上"), row(4, "三年后，沈砚鬓角已白"),
            row(5, "送信人开口", dialogue="他不会来了"), row(6, "空码头", cast=[], scene_id="E1S02", scene="码头"),
        ], first_of_episode=True)
        summaries = [cuts.shot_summary(plan, shot_id) for shot_id in range(1, 7)]
        for summary in summaries:
            self.assertEqual(set(summary), {
                "from_shot", "kind", "technique", "label", "duration_seconds", "motion_join", "compositor", "sound_join", "sound_note", "watch",
            })
            self.assertIn(summary["compositor"], {"crossfade", "match_cut", "dip_to_black"})
            self.assertIn(summary["sound_join"], {"", "j_cut", "l_cut"})
        self.assertEqual([s["kind"] for s in summaries], ["fade", "match_cut", "dissolve", "fade", "match_cut", "push_pull"])
        self.assertEqual(summaries[3]["label"], "淡入淡出·章节转换")
        state = {"characters": ["沈砚"], "scene": "E1S01", "screen_direction": "left_to_right", "action": "对峙", "emotion": "紧张",
                 "props": {}, "lighting": "冷白顶光", "audio_bed": "风声"}
        clips = [{"shot_id": index + 1, "continuity_state": state, "cut_in": summary} for index, summary in enumerate(summaries)]
        specs, reports = final_cut_transitions(clips)
        self.assertEqual(specs, [
            {"type": "match_cut", "duration": 0.12}, {"type": "crossfade", "duration": 0.5}, {"type": "dip_to_black", "duration": 0.8},
            {"type": "match_cut", "duration": 0.12}, {"type": "crossfade", "duration": 0.5, "sound_join": "l_cut"},
        ])
        self.assertEqual([report.get("planned_cut") for report in reports], [s["label"] for s in summaries[1:]])


class NoChineseInCodeTests(unittest.TestCase):
    def test_no_chinese_string_literal_is_left_outside_docstrings(self):
        for module in (cuts, cm):
            tree = _tree(module)
            docstrings = {
                id(node.body[0].value) for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node, clean=False) is not None
            }
            name = Path(module.__file__).name
            left = [
                (node.lineno, node.value) for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and CJK.search(node.value)
                and id(node) not in docstrings and (name, node.value) not in ALLOWED_LITERALS
            ]
            self.assertEqual(left, [], name)


if __name__ == "__main__":
    unittest.main()

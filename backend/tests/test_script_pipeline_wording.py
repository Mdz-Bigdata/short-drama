# -*- coding: utf-8 -*-
"""The script-to-video prompt pipeline says what ``script_prompt_pipeline.json`` says.

No model, no network. The wording table is checked against the code that reads it in both
directions: every entry in the table is read, every entry the code asks for is there with
exactly the placeholders it fills, the word tables whose order decides the first match keep
that order, and no Chinese text is left written in the module.
"""

import ast
import inspect
import re
import string
import unittest

from app.core import prompt_data
from app.core import script_prompt_pipeline as pipeline_module
from app.core.script_prompt_pipeline import ScriptPromptPipeline
from app.schema.script_prompts import ScriptPromptCompileRequest

_DATA = "script_prompt_pipeline"
# CJK punctuation, ideographs and full-width forms.
_CJK = re.compile("[{}-{}{}-{}{}-{}{}-{}]".format(*map(chr, (0x3000, 0x303F, 0x3400, 0x4DBF, 0x4E00, 0x9FFF, 0xFF00, 0xFFEF))))
# Chinese string literals script_prompt_pipeline.py may still carry, each with the reason it is not wording.
# (The docstring of _layered_identity and one comment are Chinese; neither is a string the module writes.)
_ALLOWED_LITERALS: dict[str, str] = {
    "画内": "a code value: the Literal['画内', '画外', '旁白'] of Sd25DialogueEntry.position that the schema checks",
}
_READERS = ("_says", "_table", "_pattern")


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(pipeline_module))


def _docstrings(tree: ast.Module) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _reads() -> list[tuple[str, str, frozenset[str], int]]:
    """Every ``_says`` / ``_table`` / ``_pattern`` call: the reader, the key, the placeholders it fills, and its line."""
    found = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _READERS:
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                raise AssertionError(f"a {node.func.id} key is not a literal at line {node.lineno}")
            if node.func.id != "_pattern" and len(node.args) != 1:
                raise AssertionError(f"{node.func.id} at line {node.lineno} takes more than its key")
            if any(item.arg is None for item in node.keywords):
                raise AssertionError(f"{node.func.id} at line {node.lineno} fills its template from a ** mapping")
            found.append((node.func.id, first.value, frozenset(item.arg for item in node.keywords), node.lineno))
    return found


def _lookup(data: dict, key: str):
    node = data
    for part in key.split("."):
        node = node[part]
    return node


def _leaves(node, prefix: str = ""):
    """Every entry of the table by its dotted key; a list or a string is one entry."""
    if isinstance(node, dict):
        for key, item in node.items():
            yield from _leaves(item, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name is not None)


class WordingTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)

    def test_every_entry_the_code_reads_is_there_and_of_the_right_kind(self):
        for reader, key, _filled, line in _reads():
            with self.subTest(key=key, line=line):
                try:
                    entry = _lookup(self.data, key)
                except (KeyError, TypeError):
                    self.fail(f"{reader}({key!r}) at line {line} names an entry the table does not have")
                if reader in ("_says", "_pattern"):
                    self.assertIsInstance(entry, str, f"{reader} reads a sentence, a word or a pattern")
                else:
                    self.assertNotIsInstance(entry, str, "_table reads a list or a table; a string goes through _says")
                if reader == "_pattern":
                    self.assertTrue(key.startswith("patterns."), key)

    def test_every_entry_in_the_table_is_read(self):
        read = {key for _reader, key, _filled, _line in _reads()}
        unread = [
            leaf for leaf in _leaves(self.data)
            if leaf != "_about" and not any(leaf == key or leaf.startswith(key + ".") for key in read)
        ]
        self.assertEqual(unread, [], "entries nothing reads")

    def test_each_sentence_gets_exactly_the_placeholders_it_names(self):
        for reader, key, filled, line in _reads():
            if reader == "_says":
                with self.subTest(key=key, line=line):
                    self.assertEqual(filled, _fields(_lookup(self.data, key)), f"{key} (line {line}): placeholders")

    def test_every_template_formats(self):
        for leaf in _leaves(self.data):
            entry = _lookup(self.data, leaf)
            if isinstance(entry, str) and leaf != "_about" and not leaf.startswith("patterns."):
                with self.subTest(key=leaf):
                    entry.format(**{name: 1.5 for name in _fields(entry)})

    def test_field_tables_name_model_fields_the_call_does_not_fill_itself(self):
        # ``Model(..., **_table("x_fields"))``: every key is a field of that model and none is passed twice.
        checked = 0
        for node in ast.walk(_tree()):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            for keyword in node.keywords:
                value = keyword.value
                if keyword.arg is None and isinstance(value, ast.Call) and getattr(value.func, "id", "") == "_table":
                    key = value.args[0].value
                    model = getattr(pipeline_module, node.func.id)
                    table = _lookup(self.data, key)
                    explicit = {item.arg for item in node.keywords if item.arg}
                    with self.subTest(model=model.__name__, key=key):
                        self.assertTrue(key.endswith("_fields"), key)
                        self.assertEqual(set(table) - set(model.model_fields), set(), "keys that are not fields")
                        self.assertEqual(set(table) & explicit, set(), "keys the call also fills itself")
                        self.assertTrue(all(isinstance(text, str) and text for text in table.values()))
                    checked += 1
        self.assertEqual(checked, 14)

    def test_patterns_compile_and_word_tables_are_words(self):
        for key, source in self.data["patterns"].items():
            with self.subTest(pattern=key):
                re.compile(source)
        for key in (
            "non_character_labels", "appearance_terms", "costume_terms", "prop_terms", "effect_terms",
            "indoor_locations", "outdoor_locations", "color_terms", "accessory_terms", "weather_terms",
            "season_terms", "daylight_words", "night_words", "director.palette_fallback", "sheet.headers",
            "heading.en_combined_words", "heading.cn_int_ext_words",
        ):
            words = _lookup(self.data, key)
            with self.subTest(table=key):
                self.assertTrue(words)
                self.assertTrue(all(isinstance(word, str) and word for word in words))
                self.assertEqual(len(words), len(set(words)), "a word listed twice")

    def test_shot_coverage_names_every_kind_of_beat(self):
        coverage = self.data["storyboard"]["coverage"]
        self.assertEqual(set(coverage), {"first", "dialogue", "last", "transition", "other"})
        for kind, entry in coverage.items():
            self.assertEqual(set(entry), {"shot_size", "movement"}, kind)

    def test_no_chinese_string_literal_is_left_in_the_module(self):
        tree = _tree()
        docstrings = _docstrings(tree)
        left = sorted({
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings and _CJK.search(node.value)
        } - set(_ALLOWED_LITERALS))
        self.assertEqual(left, [])
        # And the allow-list holds nothing the module no longer carries.
        carried = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)}
        self.assertEqual(set(_ALLOWED_LITERALS) - carried, set())


class FirstMatchOrderTests(unittest.TestCase):
    """The tables where the first hit wins keep the order the code was written in."""

    def setUp(self):
        self.data = prompt_data.load(_DATA)

    def test_order_of_first_match_tables(self):
        self.assertEqual(self.data["weather_terms"], ["暴风雨", "雨", "雪", "雾", "晴", "阴天"])
        self.assertEqual(
            self.data["season_terms"], ["春季", "夏季", "秋季", "冬季", "春天", "夏天", "秋天", "冬天"]
        )
        self.assertEqual(
            list(self.data["mood_visuals"]),
            ["克制", "紧张", "焦虑", "愤怒", "悲伤", "恐惧", "温柔", "开心", "冷静"],
        )
        self.assertEqual(self.data["heading"]["cn_int_ext_words"], ["内景", "外景", "内外景"])
        self.assertEqual(pipeline_module._CN_INT_EXT, {"内景": "INT", "外景": "EXT", "内外景": "INT/EXT"})
        self.assertEqual(list(pipeline_module._MOOD_VISUALS), list(self.data["mood_visuals"]))
        self.assertEqual(pipeline_module._WEATHER_TERMS, tuple(self.data["weather_terms"]))

    def test_the_longer_weather_word_wins_and_the_first_mood_sets_the_expression(self):
        pipeline = ScriptPromptPipeline()
        screenplay = pipeline.parse_screenplay("外景：森林 - 白天\n暴风雨中，他紧张又克制。", "x")
        profile = pipeline.analyze_scenes(screenplay, {})[0]
        self.assertEqual(profile.weather, "暴风雨")
        self.assertEqual(profile.mood_keywords, ["克制", "紧张"])
        self.assertEqual(profile.lighting.source_type, "natural")

    def test_every_heading_form_still_reads(self):
        heading = ScriptPromptPipeline._scene_heading
        self.assertEqual(heading("I/E CAR – DUSK"), ("INT/EXT", "CAR", "DUSK"))
        self.assertEqual(heading("int. house"), ("INT", "house", "UNSPECIFIED"))
        self.assertEqual(heading("内外景：车内 — 傍晚"), ("INT/EXT", "车内", "傍晚"))
        self.assertEqual(heading("外景：街道"), ("EXT", "街道", "未注明时段"))
        self.assertEqual(heading("场景 十 卧室内-夜"), ("INT", "卧室内", "夜"))
        self.assertEqual(heading("第4场：外面的院子"), ("EXT", "外面的院子", "未注明时段"))
        self.assertEqual(heading("第7场 -夜"), ("UNKNOWN", "未注明地点", "夜"))
        self.assertIsNone(heading("今天下雨"))

    def test_transitions_and_cues_follow_the_parsing_tables(self):
        screenplay = ScriptPromptPipeline().parse_screenplay(
            "INT. HALL - DAY\nSMASH CUT TO:\n时间：午夜\nSARAH (V.O.)\n(beat)\nHi.\n\n【林夏】（低声）好。\n淡出",
            "x",
        )
        kinds = [(element.type, element.content) for element in screenplay.scenes[0].elements]
        self.assertEqual(kinds, [
            ("scene_heading", "INT. HALL - DAY"),
            ("transition", "SMASH CUT TO:"),
            ("action", "时间：午夜"),
            ("character", "SARAH"),
            ("parenthetical", "beat"),
            ("dialogue", "Hi."),
            ("character", "林夏"),
            ("parenthetical", "低声"),
            ("dialogue", "好。"),
            ("transition", "淡出"),
        ])


class ReportsReadAsBeforeTests(unittest.TestCase):
    def test_reports_carry_the_table_wording(self):
        result = ScriptPromptPipeline().compile(ScriptPromptCompileRequest(
            title="雨夜来信",
            script_text="场景1：咖啡厅 - 夜晚\n【林夏】（克制）我知道了。",
            character_overrides={"林夏": "28岁女性，椭圆脸，黑色短发，米白风衣"},
            exports=["markdown", "csv", "html"],
        ))
        markdown, csv_text, page = result.exports["markdown"], result.exports["csv"], result.exports["html"]
        seconds = result.screenplay.total_duration_seconds
        self.assertIn(f"\n- 预估时长：{seconds} 秒\n", markdown)
        self.assertTrue(markdown.startswith("# 雨夜来信 - AI视频提示词生产包\n"))
        self.assertIn("| 格 | 目的 | 人物 | 景别 | 运镜 | 动作 | 开始状态 | 结束状态 |\n|---:|", markdown)
        headers = prompt_data.load(_DATA)["sheet"]["headers"]
        self.assertEqual(len(headers), 24)
        self.assertTrue(csv_text.startswith(chr(0xFEFF) + ",".join(headers) + "\n"))
        self.assertIn("<title>雨夜来信 - AI视频提示词</title>", page)
        self.assertIn(f"<p>场景数：1；预估时长：{seconds:g} 秒</p>", page)
        self.assertIn("<h3>场景 1 / 第1页 / 镜头 1</h3><p><strong>模式：</strong>", page)
        self.assertIn("<h2>数字演员设定集</h2>", page)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""The sound design says what ``h3_sound_design.json`` says.

No model, no network. ``app/core/h3_sound_design.py`` reads its voice-lock sentences, the H3
sound layers' wording, the check messages, the word tables and the limits from
``app/data/prompt/h3_sound_design.json``. These tests hold the two sides together: every key the
code reads exists, every key the file holds is read, each template carries exactly the
placeholders its call site fills, the first-match tables keep their order, the reference-audio
lead stays the one ``video_references`` strips, and no Chinese text is left written in the module.
"""

import ast
import inspect
import re
import string
import unittest
from dataclasses import replace
from unittest.mock import patch

from app.core import h3_sound_design as sound
from app.core import prompt_data
from app.core.video_references import plan_video_references, renumber_audio_mentions, voice_placeholder

_DATA = "h3_sound_design"
_CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
# Chinese string literals h3_sound_design.py may still carry, each with the reason it is not wording.
_PACE_TIER = (
    "a pace tier name: a key of PACE_BY_DELIVERY and the delivery= default of build_voice_anchor / "
    "anchors_from_characters; callers pass it as a code value (agent_tools, drama_api pass delivery=\"正常\", "
    "prompt_packages checks plan_packages(delivery=...) against these keys), so renaming it in data would break them"
)
_ALLOWED_LITERALS: dict[str, str] = {"正常": _PACE_TIER, "急切": _PACE_TIER, "沉重": _PACE_TIER}
# Tables whose keys are code values the module indexes by (``_LIMITS["sound_words"]``, ``["female" if … else "male"]``).
_KEYED_TABLES = {
    "limits": "_LIMITS", "tags": "_TAGS", "gender_marks": "_GENDER_MARKS",
    "persona_voice": None, "center_voice": None,
}


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(sound))


def _literal(node: ast.AST | None) -> set[str]:
    """The key(s) an argument or a subscript names: a string constant, or either arm of ``a if c else b``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _literal(node.body) | _literal(node.orelse)
    return set()


def _helper_calls(name: str) -> list[tuple[str, frozenset[str], int]]:
    """Every ``name("key", **values)`` in the module: the key, the keywords it fills, and its line."""
    found = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
            keys = _literal(node.args[0]) if node.args else set()
            if len(node.args) != 1 or len(keys) != 1:
                raise AssertionError(f"a {name} key is not a single literal at line {node.lineno}")
            found.append((keys.pop(), frozenset(item.arg for item in node.keywords), node.lineno))
    return found


def _top_level_reads() -> set[str]:
    """Top-level keys read: ``_word("k")``, ``_table("k")``, ``prompt_data.f(_DATA, "k")``, ``load(_DATA)["k"]``."""
    keys = {key for helper in ("_word", "_table") for key, _, _ in _helper_calls(helper)}
    for node in ast.walk(_tree()):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "prompt_data"
            and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id == "_DATA"
        ):
            keys |= _literal(node.args[1])
        elif (
            isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "load"
            and node.value.args and isinstance(node.value.args[0], ast.Name) and node.value.args[0].id == "_DATA"
        ):
            keys |= _literal(node.slice)
    return keys


def _subscripts_of(table: str, alias: str | None) -> set[str]:
    """String keys the module indexes ``table`` by: through its module alias or straight off ``_table("table")``."""
    keys: set[str] = set()
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Subscript):
            continue
        target = node.value
        via_alias = alias is not None and isinstance(target, ast.Name) and target.id == alias
        via_call = (
            isinstance(target, ast.Call) and isinstance(target.func, ast.Name) and target.func.id == "_table"
            and _literal(target.args[0]) == {table}
        )
        if via_alias or via_call:
            keys |= _literal(node.slice)
    return keys


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _docstrings(tree: ast.Module) -> set[int]:
    """``id`` of every docstring constant (module, class and function), which may be Chinese prose."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


class WordingTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)
        self.says = self.data["says"]

    def test_every_sentence_in_the_table_is_used_and_every_one_asked_for_is_there(self):
        asked = {key for key, _, _ in _helper_calls("_says")}
        self.assertEqual(set(self.says) - asked, set(), "sentences nothing reads")
        self.assertEqual(asked - set(self.says), set(), "sentences h3_sound_design.py reads that are missing")

    def test_each_sentence_gets_exactly_the_placeholders_it_names(self):
        for key, filled, line in _helper_calls("_says"):
            self.assertEqual(filled, _fields(self.says[key]), f"says.{key} (line {line}): placeholders")

    def test_every_template_formats(self):
        for key, template in self.says.items():
            with self.subTest(key=key):
                template.format(**{name: 1.5 for name in _fields(template)})

    def test_every_top_level_entry_is_read_and_every_one_read_is_there(self):
        table = set(self.data) - {"_about"}
        read = _top_level_reads()
        self.assertEqual(table - read, set(), "entries nothing reads")
        self.assertEqual(read - table, set(), "entries h3_sound_design.py reads that are missing")

    def test_every_pattern_is_read_and_compiles(self):
        read = {key for key, _, _ in _helper_calls("_pattern")}
        self.assertEqual(read, set(self.data["patterns"]))
        self.assertEqual(_fields(self.data["patterns"]["layer"]), frozenset({"tag"}))
        for key, text in self.data["patterns"].items():
            with self.subTest(key=key):
                # Only ``layer`` is formatted; the others are used as they stand ({1,2} is a quantifier).
                re.compile(text.format(tag=sound.CENTER_TAG) if key == "layer" else text)

    def test_keyed_tables_hold_exactly_the_keys_the_code_indexes_by(self):
        for table, alias in _KEYED_TABLES.items():
            with self.subTest(table=table):
                self.assertEqual(_subscripts_of(table, alias), set(self.data[table]))

    def test_words_and_limits_are_plain(self):
        for key in ("list_separator", "lock_separator", "voice_separator", "bed_separator", "center_tone_default"):
            self.assertIsInstance(self.data[key], str, key)
            self.assertTrue(self.data[key], key)
        for key in ("music_words", "low_ambient_words", "low_music_words", "space_words", "none_music_values"):
            self.assertTrue(all(isinstance(word, str) for word in self.data[key]), key)
        self.assertTrue(all(isinstance(value, int) and value > 0 for value in self.data["limits"].values()))
        self.assertEqual(
            (sound.MAX_SOUND_WORDS, sound.MAX_VOICE_DESC_CHARS),
            (self.data["limits"]["sound_words"], self.data["limits"]["voice_desc_chars"]),
        )

    def test_no_chinese_string_literal_is_left_in_the_module(self):
        tree = _tree()
        docstrings = _docstrings(tree)
        left = sorted({
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _CJK.search(node.value)
            and id(node) not in docstrings
        } - set(_ALLOWED_LITERALS))
        self.assertEqual(left, [])

    def test_the_allowed_literals_are_still_the_pace_tiers(self):
        self.assertEqual(set(_ALLOWED_LITERALS), set(sound.PACE_BY_DELIVERY))


class TableOrderTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)

    def test_the_timbre_bands_keep_their_first_match_order(self):
        self.assertEqual(
            [(timbre, pitch) for _, timbre, pitch in sound._TIMBRE_RULES],
            [("清亮", "中高音区"), ("苍哑", "低音区"), ("沉稳", "中低音区"), ("沙哑", "低音区"), ("温柔", "中音区"), ("清冷", "中音区")],
        )
        self.assertEqual(sound._TIMBRE_RULES, tuple((tuple(w), t, p) for w, t, p in self.data["timbre_rules"]))
        # 少年 and 老人 both match: the earlier band wins; 冷 and 沙哑 both match: 沙哑 comes first.
        self.assertEqual(sound.build_voice_anchor("甲", description="少年老人").timbre, "清亮")
        self.assertEqual(sound.build_voice_anchor("甲", description="冷 沙哑").timbre, "沙哑")
        self.assertEqual(sound._DEFAULT_TIMBRE, ("清亮", "中音区"))

    def test_the_music_words_are_reported_in_table_order(self):
        self.assertEqual(sound._MUSIC_WORDS, tuple(self.data["music_words"]))
        center = sound._layer_of("center: 旋律 piano bgm; ambient: x, low, surround; music: none", "center")
        leaked = [word for word in sound._MUSIC_WORDS if word in center.lower()]
        self.assertEqual(leaked, ["bgm", "piano", "旋律"])

    def test_every_emotion_maps_to_a_pace_tier_and_every_timbre_has_a_center_word(self):
        self.assertEqual(list(sound._DELIVERY_BY_EMOTION), list(self.data["delivery_by_emotion"]))
        for emotion, (tier, _) in sound._DELIVERY_BY_EMOTION.items():
            self.assertIn(tier, sound.PACE_BY_DELIVERY, emotion)
        timbres = {timbre for _, timbre, _ in sound._TIMBRE_RULES} | {sound._DEFAULT_TIMBRE[0]}
        self.assertEqual(timbres, set(sound._CENTER_TONE))


class SharedReferenceLeadTests(unittest.TestCase):
    """lock_line's 「，音色参考」 clause is the one video_references renumbers or strips."""

    def setUp(self):
        self.anchor = sound.build_voice_anchor("沈砚", description="中年帝王", gender="male")
        self.placed = replace(self.anchor, ref_audio=voice_placeholder("沈砚"))
        self.voices = [("沈砚", "https://x/s.mp3")]

    def test_the_lead_comes_from_voice_reference(self):
        lead = prompt_data.text("voice_reference", "lock_lead")
        separator = prompt_data.text(_DATA, "lock_separator")
        line = replace(self.anchor, ref_audio="@音频1").lock_line()
        self.assertIn(f"{separator}{lead}@音频1", line)
        self.assertEqual(line, "沈砚：沉稳男声，中低音区，音色参考@音频1；全片音色、音调与声线不变")

    def test_an_unsent_sample_leaves_the_line_without_a_reference(self):
        plan = plan_video_references("first_last_frame", first_frame="https://x/a.png", last_frame="https://x/b.png", model="seedance2.0")
        self.assertEqual(renumber_audio_mentions(self.placed.lock_line(), self.voices, plan), self.anchor.lock_line())

    def test_a_sent_sample_is_numbered_in_place(self):
        plan = plan_video_references(
            "multimodal", first_frame=None, reference_images=["https://x/a.png"], reference_audios=["https://x/s.mp3"],
            model="seedance2.0",
        )
        self.assertEqual(
            renumber_audio_mentions(self.placed.lock_line(), self.voices, plan),
            "沈砚：音色照参考音频1（只取音色，语速与情绪按本镜表达）；全片音色、音调与声线不变",
            "a sample that is really sent replaces the adjectives: the voice is pointed at, not described",
        )

    def test_a_voice_whose_sample_is_not_sent_keeps_its_description_and_dialogue_is_never_swallowed(self):
        from app.core.h3_sound_design import VoiceAnchor
        from app.core.video_references import VideoReferencePlan, voice_placeholder

        other = VoiceAnchor(name="苏晚", gender="female", age_years=22, timbre="清亮", pitch="中高音区", ref_audio=voice_placeholder("苏晚"))
        text = "台词：沈砚：先把账对一对，苏晚：账房的事你懂什么！[声音锁]" + self.placed.lock_line() + " " + other.lock_line()
        voices = [*self.voices, ("苏晚", "https://x/w.mp3")]
        one = VideoReferencePlan(mode="multimodal", reference_images=["https://x/a.png"], reference_audios=["https://x/s.mp3"])
        sent = renumber_audio_mentions(text, voices, one)
        self.assertIn("台词：沈砚：先把账对一对，苏晚：账房的事你懂什么！", sent, "the lines themselves are untouched")
        self.assertIn("沈砚：音色照参考音频1（只取音色", sent)
        self.assertIn("苏晚：22岁清亮女声，中高音区；全片音色", sent, "no sample for her in this request, so she is still described")
        self.assertNotIn("〈音频", sent)
        unsent = renumber_audio_mentions(text, voices, VideoReferencePlan(mode="first_frame"))
        self.assertIn("沈砚：沉稳男声，中低音区；全片音色", unsent)
        self.assertNotIn("参考音频", unsent)

    def test_an_empty_pointer_goes_back_to_describing_beside_the_reference(self):
        from unittest.mock import patch

        from app.core import prompt_data

        real = prompt_data.text
        plan = plan_video_references(
            "multimodal", first_frame=None, reference_images=["https://x/a.png"], reference_audios=["https://x/s.mp3"], model="seedance2.0",
        )
        with patch.object(prompt_data, "text", side_effect=lambda name, key: "" if (name, key) == ("voice_reference", "pointed") else real(name, key)):
            line = renumber_audio_mentions(self.placed.lock_line(), self.voices, plan)
        self.assertEqual(line, "沈砚：沉稳男声，中低音区，音色参考：参考音频1（只取音色，语速与情绪按本镜表达）；全片音色、音调与声线不变")


class SaysWhatTheTableSaysTests(unittest.TestCase):
    def test_the_lines_read_as_before(self):
        lin = sound.build_voice_anchor("林夏", description="22岁记者", gender="female")
        designed = sound.build_voice_anchor("周教授", voice_desc="55岁男声，低沉微哑", delivery="急切")
        self.assertEqual(lin.lock_line(), "林夏：22岁清亮女声，中音区；全片音色、音调与声线不变")
        self.assertEqual(designed.lock_line(), "周教授：55岁男声，低沉微哑；全片音色、音调与声线不变")
        self.assertEqual((designed.gender, designed.timbre, designed.center_term()), ("male", "沙哑", "male hoarse"))
        self.assertEqual(
            sound.emotion_overlay([lin, lin], " 压抑 / 慢 "),
            "林夏本镜情绪（压抑 / 慢）只改变语气、力度与停顿，基础音色、音调与声线照上面的锁定句不变",
        )
        prompt = sound.compile_sound_prompt(
            speakers=[lin, designed], tone="tense", ambience=["rain", " ", "wind"], music="low strings",
            spacious=True, foreground=True,
        )
        self.assertEqual(
            prompt.text,
            "center: female bright / male hoarse, clear speech, center channel, synced to mouth, foreground, tense; "
            "ambient: rain, wind, continuous, low volume, surround, low reverb; music: low strings, low frequency, slight spread",
        )
        self.assertEqual(
            sound.compile_sound_prompt(narration=True).text,
            "center: no dialogue, characters silent, mouths closed; "
            "ambient: room tone only, continuous, low volume, surround; music: none",
        )

    def test_the_check_messages_read_as_before(self):
        details = [check.detail for check in sound.check_sound_prompt(
            "center: piano voice; ambient: cafe murmur; music: jazz", speakers=[sound.build_voice_anchor("林夏")],
        )]
        self.assertEqual(details, [
            "center / ambient / music 三层齐备。",
            "对白层混进了配乐词「piano」，人声会和音乐搅在一起。",
            "环境音要写 low volume、配乐要写 low frequency 或 none，否则对白会被盖住。",
            "环境音层缺少 surround 或 left-right spread，声音会全挤在中间发平。",
            "声音提示词 8 词，在 60 词预算内。",
            "林夏 的音色、音调与声线已锁定。",
        ])
        self.assertEqual(
            [check.detail for check in sound.check_sound_prompt("center: " + "雨" * 130)][::4],
            ["缺少 ambient、music 层；三层都要写，模型才会分层生成。", "声音提示词约 66 词，超过 60 词后模型会抓不住主次。"],
        )

    def test_a_reworded_sentence_reaches_the_prompt(self):
        data = prompt_data.load(_DATA)
        reworded = {**data, "says": {**data["says"], "lock_tail": "；嗓音全片不变"}}
        original = prompt_data.load
        with patch.object(prompt_data, "load", lambda name: reworded if name == _DATA else original(name)):
            line = sound.build_voice_anchor("林夏").lock_line()
        self.assertEqual(line, "林夏：清亮女声，中音区；嗓音全片不变")


if __name__ == "__main__":
    unittest.main()

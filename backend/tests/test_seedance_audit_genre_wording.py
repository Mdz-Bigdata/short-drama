# -*- coding: utf-8 -*-
"""The Seedance 2.5 director layer, the five-part prompt audit and the genre clusters say what their tables say.

No model, no network. Each table (``seedance_video_director.json``, ``sd25_prompt_audit.json``,
``genre_clusters.json``) is checked against the module that reads it in both directions: every
entry in the table is read, every entry the code asks for is there with exactly the placeholders
it fills, order is kept where it matters, and no Chinese string is left (nor any other non-ASCII
text: full-width brackets, dashes) written in the module outside its docstrings.
"""

import ast
import copy
import inspect
import string
import unittest
from types import ModuleType
from unittest.mock import patch

from app.core import genre_clusters, knowledge_registry, prompt_data, sd25_prompt_audit
from app.core import seedance_video_director as director
from app.schema.production import Sd25PromptAuditRequest

_MODULES: dict[str, ModuleType] = {
    "seedance_video_director": director,
    "sd25_prompt_audit": sd25_prompt_audit,
    "genre_clusters": genre_clusters,
}
# Helpers that read one top-level entry by a literal key: ``helper("key")``.
_KEY_HELPERS = ("_markers",)
# Non-ASCII string literals a module may still carry outside its docstrings, each with the reason it is
# not wording. None are needed: every sentence, word, heading, joiner and pattern is in the table.
_ALLOWED_LITERALS: dict[str, dict[str, str]] = {name: {} for name in _MODULES}


def _tree(module: ModuleType) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _literal(node: ast.AST | None, what: str) -> str:
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        raise AssertionError(f"a {what} key is not a literal at line {getattr(node, 'lineno', '?')}")
    return node.value


def _calls(module: ModuleType, helper: str) -> list[tuple[str, frozenset[str], int]]:
    """Every ``helper("key", ...)``: the key it names, the keywords it fills, and its line."""
    found = []
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == helper:
            if len(node.args) != 1:
                raise AssertionError(f"{helper} takes one positional key (line {node.lineno})")
            found.append((_literal(node.args[0], helper), frozenset(item.arg for item in node.keywords), node.lineno))
    return found


def _is_wording(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "_WORDING"


def _top_level_reads(module: ModuleType) -> set[str]:
    """Top-level keys read: ``prompt_data.f(_WORDING, "k")``, ``prompt_data.load(_WORDING)["k"]``, ``_markers("k")``."""
    keys = {key for helper in _KEY_HELPERS for key, _, _ in _calls(module, helper)}
    for node in ast.walk(_tree(module)):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "prompt_data" and len(node.args) >= 2 and _is_wording(node.args[0])
            and not (isinstance(node.args[1], ast.Name) and node.args[1].id == "key")  # a key helper itself
        ):
            keys.add(_literal(node.args[1], "prompt_data"))
        elif (
            isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "load"
            and node.value.args and _is_wording(node.value.args[0])
        ):
            keys.add(_literal(node.slice, "load"))
    return keys


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _docstring_nodes(tree: ast.Module) -> set[int]:
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                nodes.add(id(first.value))
    return nodes


def _reworded(name: str, change):
    """Patch ``prompt_data.load`` so the table ``name`` comes back changed by ``change(copy)``."""
    original = prompt_data.load
    table = copy.deepcopy(original(name))
    change(table)
    return patch.object(prompt_data, "load", lambda which: table if which == name else original(which))


class EveryTableMatchesItsModuleTests(unittest.TestCase):
    def test_every_top_level_entry_is_read_and_every_one_read_is_there(self):
        for name, module in _MODULES.items():
            with self.subTest(table=name):
                table = set(prompt_data.load(name)) - {"_about"}
                read = _top_level_reads(module)
                self.assertEqual(table - read, set(), "entries nothing reads")
                self.assertEqual(read - table, set(), "entries the module reads that are missing")

    def test_every_sentence_in_a_table_is_used_and_every_one_asked_for_is_there(self):
        for name, module in _MODULES.items():
            asked = {key for key, _, _ in _calls(module, "_says")}
            with self.subTest(table=name):
                says = prompt_data.load(name).get("says", {})
                self.assertEqual(set(says) - asked, set(), "sentences nothing reads")
                self.assertEqual(asked - set(says), set(), "sentences the module reads that are missing")

    def test_each_sentence_gets_exactly_the_placeholders_it_names(self):
        for name, module in _MODULES.items():
            says = prompt_data.load(name).get("says", {})
            for key, filled, line in _calls(module, "_says"):
                with self.subTest(table=name, key=key):
                    self.assertEqual(filled, _fields(says[key]), f"{name}.says.{key} (line {line}): placeholders")

    def test_every_template_formats(self):
        for name in _MODULES:
            for key, template in prompt_data.load(name).get("says", {}).items():
                with self.subTest(table=name, key=key):
                    template.format(**{field: 1.5 for field in _fields(template)})

    def test_word_lists_are_lists_of_non_empty_words(self):
        for name in _MODULES:
            for key, value in prompt_data.load(name).items():
                if key.endswith("_markers") or key in {"screened_brands", "precedence_note"}:
                    with self.subTest(table=name, key=key):
                        self.assertIsInstance(value, list)
                        self.assertTrue(all(isinstance(item, str) for item in value))
                        if key != "precedence_note":  # the note keeps its blank paragraph line
                            self.assertTrue(all(value), "an empty word would match everything")
                            self.assertEqual(len(value), len(set(value)), "duplicate word")

    def test_no_chinese_or_other_non_ascii_string_literal_is_left_in_the_modules(self):
        for name, module in _MODULES.items():
            with self.subTest(module=name):
                tree = _tree(module)
                docstrings = _docstring_nodes(tree)
                left = sorted({
                    node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings and not node.value.isascii()
                } - set(_ALLOWED_LITERALS[name]))
                self.assertEqual(left, [])


class DirectorLayerTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load("seedance_video_director")
        director.reset_seedance_director_cache()

    def _build(self) -> ast.FunctionDef:
        return next(
            node for node in ast.walk(_tree(director))
            if isinstance(node, ast.FunctionDef) and node.name == "build_director_layer"
        )

    def _parts(self) -> list[tuple[str, str]]:
        """Every ``_part(priority, key, source)``: the section key (both branches of the blueprint choice) and its source."""
        build = self._build()
        blueprint = next(
            node.value for node in ast.walk(build)
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "blueprint" for t in node.targets)
        )
        found = []
        for node in ast.walk(build):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_part":
                key, source = node.args[1], node.args[2]
                keys = (blueprint.body, blueprint.orelse) if isinstance(key, ast.Name) and key.id == "blueprint" else (key,)
                found.extend((_literal(item, "_part"), source.id) for item in keys)
        return found

    def _sources(self) -> dict[str, str]:
        """Each source variable of build_director_layer and the text it reads (SKILL.md or a registered reference)."""
        texts = {}
        for node in ast.walk(self._build()):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                target, call = node.targets[0].id, node.value
                if call.func.id == "_read" and isinstance(call.args[0], ast.Constant):
                    texts[target] = director._read(call.args[0].value)
                elif call.func.id == "_read":
                    texts[target] = director._read(director._reference(_literal(call.args[0].args[0], "_reference")))
                elif call.func.id == "_registered_text":
                    texts[target] = director._registered_text(_literal(call.args[0], "_registered_text"))
        return texts

    def test_every_section_is_read_and_every_one_read_is_there(self):
        read = {key for key, _ in self._parts()}
        self.assertEqual(set(self.data["sections"]) - read, set(), "sections nothing reads")
        self.assertEqual(read - set(self.data["sections"]), set(), "sections the module reads that are missing")

    def test_each_section_is_a_unique_name_and_a_heading(self):
        names = []
        for key, entry in self.data["sections"].items():
            with self.subTest(section=key):
                self.assertEqual(len(entry), 2)
                name, heading = entry
                self.assertTrue(isinstance(name, str) and name and isinstance(heading, str) and heading)
                self.assertNotIn("\n", heading)
                names.append(name)
        self.assertEqual(len(names), len(set(names)), "two sections share a name")
        self.assertNotIn(director._PRECEDENCE_NAME, names)

    def test_every_heading_is_a_level_two_heading_of_the_file_it_is_read_from(self):
        if not director.skill_installed():
            self.skipTest("seedance-2-5-video-director 未安装")
        texts = self._sources()
        for key, source in self._parts():
            heading = self.data["sections"][key][1]
            with self.subTest(section=key):
                self.assertIn(f"## {heading}", [line.strip() for line in texts[source].splitlines()])
                self.assertTrue(director._section(texts[source], heading))

    def test_the_word_lists_are_the_table_in_order(self):
        for constant, key in (
            ("_DIALOGUE_MARKERS", "dialogue_markers"), ("_ACTING_MARKERS", "acting_markers"),
            ("_PHYSICAL_MARKERS", "physical_markers"), ("_SPORTS_MARKERS", "sports_markers"),
            ("_FIGHT_MARKERS", "fight_markers"), ("_MASS_BATTLE_MARKERS", "mass_battle_markers"),
            ("_AUDIO_MARKERS", "audio_markers"), ("_TRANSITION_MARKERS", "transition_markers"),
        ):
            with self.subTest(table=key):
                self.assertEqual(getattr(director, constant), tuple(self.data[key]))
        self.assertEqual(director.DIRECTOR_LAYER_CHAR_CAP, self.data["char_cap"])
        self.assertIsInstance(director.DIRECTOR_LAYER_CHAR_CAP, int)

    def test_the_precedence_note_is_its_lines_joined_and_reads_as_before(self):
        note = director._PRECEDENCE_NOTE
        self.assertEqual(note, "\n".join(self.data["precedence_note"]))
        self.assertTrue(note.startswith("# 导演层：seedance-2-5-video-director（仅 Seedance 2.5 生效）\n\n下面几段来自"))
        self.assertTrue(note.endswith("改写成形状、材质与空间关系。"))
        self.assertEqual(note.count("\n"), 9)

    def test_the_timestamp_pattern_reads_spans_but_not_the_long_dash(self):
        pattern = director._TIMESTAMP_PATTERN
        self.assertEqual(pattern.pattern, self.data["timestamp_pattern"])
        for written in ("0-5s 走进门", "3 至 8 秒", "0~10s", "0–5秒"):
            self.assertTrue(pattern.search(written), written)
        # slice_video writes 「7—10秒」 block heads with the long dash precisely so they are not read as a timeline.
        for written in ("7—10秒", "100-200s", "123-4s"):
            self.assertIsNone(pattern.search(written), written)

    def test_the_layer_reads_as_before(self):
        if not director.skill_installed():
            self.skipTest("seedance-2-5-video-director 未安装")
        layer = director.build_director_layer(video_model="seedance2.5", duration=8, mode="text_to_video", prompt="她低头看信")
        self.assertEqual(layer.primary_mode, "basic-multimodal")
        self.assertEqual(layer.sections[:4], ("precedence-note", "limits/Mode limits", "skill/Timing and reference rules", "blueprints/Basic multimodal"))
        self.assertIn("composition/电影氛围", layer.sections)
        self.assertTrue(layer.text.startswith(director._PRECEDENCE_NOTE + "\n\n## Mode limits"))
        audio = director.build_director_layer(video_model="seedance2.5", duration=30, prompt="风声，音色参考 @Audio1；切镜到街口")
        self.assertEqual(audio.primary_mode, "timestamp-30s")
        for name in ("multimodal/Timbre and dialogue", "cn-handbook/30 秒长视频的三个模块", "cn-handbook/中文转场用语"):
            self.assertIn(name, audio.sections)

    def test_a_renamed_section_reaches_the_layer(self):
        if not director.skill_installed():
            self.skipTest("seedance-2-5-video-director 未安装")

        def change(table):
            table["sections"]["combat_core"] = ["combat/打戏总则", "一、核心原则"]

        with _reworded("seedance_video_director", change):
            sections = director.build_director_layer(video_model="seedance2.5", duration=8, prompt="两人拳脚互打").sections
        self.assertIn("combat/打戏总则", sections)
        self.assertNotIn("combat/核心原则", sections)


class PromptAuditTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load("sd25_prompt_audit")
        self.auditor = sd25_prompt_audit.Sd25PromptAuditor()

    def _audit(self, prompt: str, duration: float | None = None, unbranded: bool = False) -> list[tuple[str, str, str]]:
        result = self.auditor.audit(Sd25PromptAuditRequest(prompt=prompt, duration_seconds=duration, unbranded=unbranded))
        return [(item.level, item.code, item.message) for item in result.findings]

    def test_the_headings_are_the_table_in_the_codes_order(self):
        self.assertEqual(set(self.data["headings"]), set(sd25_prompt_audit._HEADING_CODES))
        self.assertEqual(
            sd25_prompt_audit._REQUIRED_HEADINGS,
            tuple((code, self.data["headings"][code]) for code in sd25_prompt_audit._HEADING_CODES),
        )
        # The delivery order of the five parts is the published contract.
        self.assertEqual(
            [heading for _, heading in sd25_prompt_audit._REQUIRED_HEADINGS], ["【主体】", "【风格】", "【时间线】", "【BGM】", "【限制】"],
        )

    def test_the_span_pattern_is_composed_from_its_fragments(self):
        self.assertEqual(_fields(self.data["span_pattern"]), frozenset({"decimal", "separator"}))
        pattern = sd25_prompt_audit._SPAN_PATTERN
        self.assertEqual(pattern.pattern, self.data["span_pattern"].format(decimal=self.data["decimal"], separator=self.data["separator"]))
        self.assertEqual(set(pattern.groupindex), {"lo", "hi"})
        spans = [(m.group("lo"), m.group("hi")) for m in pattern.finditer("【0—2秒】a 2-3.5秒 b 3.5 秒 ～ 4 秒 c 4~5秒")]
        self.assertEqual(spans, [("0", "2"), ("2", "3.5"), ("3.5", "4"), ("4", "5")])

    def test_the_tolerances_and_word_sets_are_the_table(self):
        self.assertEqual(sd25_prompt_audit._EDGE_TOLERANCE, 0.01)
        self.assertEqual(sd25_prompt_audit._DURATION_TOLERANCE, 0.05)
        for constant, key in (
            ("_ASSET_MARKERS", "asset_markers"), ("_RESPONSIBILITY_MARKERS", "responsibility_markers"),
            ("_ACTION_MARKERS", "action_markers"), ("_CAUSAL_MARKERS", "causal_markers"),
            ("_SCREENED_BRANDS", "screened_brands"), ("_BRAND_BOUNDARY_MARKERS", "brand_boundary_markers"),
        ):
            with self.subTest(table=key):
                self.assertEqual(getattr(sd25_prompt_audit, constant), frozenset(self.data[key]))

    def test_the_findings_read_as_before(self):
        self.assertEqual(self._audit("【主体】\n两人追逐。\n【时间线】\n【1—2秒】A奔跑。\n【3—5秒】B追赶。", duration=6), [
            ("error", "style.missing", "正文里找不到 【风格】 这一段，五段结构不成立。"),
            ("error", "bgm.missing", "正文里找不到 【BGM】 这一段，五段结构不成立。"),
            ("error", "constraints.missing", "正文里找不到 【限制】 这一段，五段结构不成立。"),
            ("error", "timeline.start", "第一个区间从 1 秒起步，时间轴必须由 0 秒接起。"),
            ("error", "timeline.gap", "2 秒到 3 秒之间没有任何段落覆盖。"),
            ("error", "timeline.duration", "时间轴收在 5 秒，与传入的 6 秒不符。"),
            ("warning", "action.causality", "写到了复杂动作，但没有交代它从哪里发起、怎么走、最后停在哪里。"),
        ])
        findings = self._audit("【0—2.5秒】a【2—1.5秒】b【1.5—4秒】c @图1 可口可乐 Nike", unbranded=True)
        self.assertIn(("error", "timeline.invalid", "区间 2—1.5 秒的终点没有落在起点之后。"), findings)
        self.assertIn(("error", "timeline.order", "各区间的起点没有一路递增，事件顺序被打乱。"), findings)
        self.assertIn(("error", "timeline.overlap", "两个区间在 2 秒处彼此压盖。"), findings)
        self.assertIn(("warning", "reference.scope", "引用了参考素材，却没有写清每份素材负责什么、不负责什么。"), findings)
        self.assertIn(("error", "brand.detected", "无品牌交付里出现了受检品牌名：nike、可口可乐"), findings)
        self.assertIn(("warning", "brand.lock", "选了无品牌模式，限制段却没有写明品牌、商标或水印的边界。"), findings)
        self.assertIn(("error", "timeline.missing", "正文里没有可解析的秒数区间，时间轴无法校验。"), self._audit("没有时间"))

    def test_a_reworded_message_reaches_the_findings(self):
        def change(table):
            table["says"]["timeline_gap"] = "空档：{earlier_end:g}→{later_start:g}"
            table["brand_separator"] = " / "

        with _reworded("sd25_prompt_audit", change):
            findings = self._audit("【0—1秒】a【2—3秒】b 可口可乐 Nike", unbranded=True)
        self.assertIn(("error", "timeline.gap", "空档：1→2"), findings)
        self.assertIn(("error", "brand.detected", "无品牌交付里出现了受检品牌名：nike / 可口可乐"), findings)


class GenreClusterTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load("genre_clusters")

    def test_every_cluster_has_exactly_its_words_and_every_one_is_built(self):
        self.assertEqual([cluster.id for cluster in genre_clusters.CLUSTERS], list(self.data["clusters"]))
        for cluster in genre_clusters.CLUSTERS:
            words = self.data["clusters"][cluster.id]
            with self.subTest(cluster=cluster.id):
                self.assertEqual(set(words), {"name", "keywords", "note"})
                self.assertEqual(cluster.name, words["name"])
                self.assertEqual(cluster.keywords, tuple(words["keywords"]))
                self.assertEqual(cluster.note, words["note"])
                self.assertTrue(all(words["keywords"]))

    def test_the_cluster_order_is_kept(self):
        # Order matters: a keyword tie goes to the earlier cluster, and the default is the first.
        self.assertEqual([cluster.id for cluster in genre_clusters.CLUSTERS], ["A", "B", "C", "D", "E", "F", "G"])
        self.assertEqual(genre_clusters.DEFAULT_CLUSTER_ID, "A")
        self.assertEqual(genre_clusters.cluster_for(text="武侠 枪战").id, "B")
        self.assertEqual(genre_clusters.cluster_for(text="无关").id, "A")

    def test_the_brief_reads_as_before(self):
        plan = genre_clusters.plan_direction(genre="xianxia")
        self.assertEqual(
            plan.brief().split("\n")[0],
            "【题材】仙侠玄幻修真（C簇）：法术要有蓄力→释放→命中→余波四拍；特效分层，别盖住人物。",
        )
        self.assertEqual(genre_clusters.get_cluster("d").name, "动作打斗战争")

    def test_a_reworded_note_and_brief_reach_the_brief(self):
        cluster = genre_clusters.get_cluster("G")

        def change(table):
            table["says"]["brief"] = "题材={id}/{name}/{note}"

        with _reworded("genre_clusters", change):
            line = genre_clusters.DirectionPlan(cluster=cluster, intent=genre_clusters.decode("", default="comedic")).brief()
        self.assertEqual(line.split("\n")[0], f"题材=G/{cluster.name}/{cluster.note}")


if __name__ == "__main__":
    unittest.main()

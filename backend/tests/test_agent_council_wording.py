# -*- coding: utf-8 -*-
"""The eight-agent council says what ``agent_council.json`` says.

No model, no network. The wording table is checked against the code that reads it in both
directions: every entry in the table is read, every one the code asks for is there with exactly
the placeholders it fills, tables keyed by roles, capabilities and modules keep their order, and
no Chinese text is left written in the module outside docstrings and comments.
"""

import ast
import inspect
import re
import string
import unittest
from typing import Any

from app.core import agent_council, prompt_data
from app.core.agent_council import (
    ARTIFACT_LABELS,
    CAPABILITIES,
    NEGATIVE_MODULE_LABELS,
    NEGATIVE_MODULE_WORDS,
    AgentCouncilCompiler,
    compile_negative_prompt,
)
from app.schema.agent_council import (
    ALL_AGENT_ROLES,
    POST_WRITER_ROLES,
    AgentRole,
    CouncilCompileRequest,
    CouncilIssue,
)

_DATA = "agent_council"
_CJK = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
# Chinese string literals agent_council.py may still carry outside docstrings, each with the reason
# it is not wording. (Its Chinese comments are not string literals and are not prompt text.)
_ALLOWED_LITERALS: dict[str, str] = {}
# The readers: ``_says`` fills a template; ``_table`` and ``_by_role`` use an entry as it stands.
_READERS = ("_says", "_table", "_by_role")


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(agent_council))


def _reads() -> list[tuple[str, str, frozenset[str], int]]:
    """Every read of the table: (reader, dotted key, placeholders filled, line)."""
    found = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _READERS:
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)) or len(node.args) != 1:
                if node.lineno in _definition_lines():
                    continue
                raise AssertionError(f"a {node.func.id} key is not a single literal at line {node.lineno}")
            found.append((node.func.id, first.value, frozenset(item.arg for item in node.keywords), node.lineno))
    return found


def _definition_lines() -> set[int]:
    """Lines inside the reader helpers themselves (``_by_role`` calls ``_table(key)``)."""
    lines: set[int] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.FunctionDef) and node.name in (*_READERS, "_entry", "_template"):
            lines.update(range(node.lineno, node.end_lineno + 1))
    return lines


def _entry(data: Any, key: str) -> Any:
    node = data
    for part in key.split("."):
        node = node[part]
    return node


def _template(entry: Any) -> str:
    return "\n".join(entry) if isinstance(entry, list) else entry


def _fields(template: str) -> frozenset[str]:
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


def _leaves(node: Any, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    if isinstance(node, dict):
        return [leaf for key, value in node.items() for leaf in _leaves(value, (*path, key))]
    return [path]


def _strings(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [text for value in node.values() for text in _strings(value)]
    if isinstance(node, list):
        return [text for value in node for text in _strings(value)]
    return [node] if isinstance(node, str) else []


class WordingTableTests(unittest.TestCase):
    def setUp(self):
        self.data = prompt_data.load(_DATA)

    def test_every_key_read_is_there_and_every_entry_is_read(self):
        reads = _reads()
        self.assertTrue(reads)
        for reader, key, _, line in reads:
            with self.subTest(key=key, line=line):
                _entry(self.data, key)  # raises KeyError when the code asks for something the table lacks
        read = {key for _, key, _, _ in reads}
        unread = [
            ".".join(path) for path in _leaves({k: v for k, v in self.data.items() if k != "_about"})
            if not any(".".join(path) == key or ".".join(path).startswith(key + ".") for key in read)
        ]
        self.assertEqual(unread, [], "entries nothing reads")

    def test_each_template_gets_exactly_the_placeholders_it_names(self):
        for reader, key, filled, line in _reads():
            if reader != "_says":
                continue
            with self.subTest(key=key, line=line):
                template = _template(_entry(self.data, key))
                self.assertIsInstance(template, str)
                self.assertEqual(filled, _fields(template), f"{key} (line {line}): placeholders")
                template.format(**{name: 1.5 for name in _fields(template)})

    def test_tables_used_as_they_stand_carry_no_placeholders(self):
        for reader, key, _, line in _reads():
            if reader == "_says":
                continue
            for text in _strings(_entry(self.data, key)):
                with self.subTest(key=key, text=text):
                    self.assertNotIn("{", text)
                    self.assertNotIn("}", text)

    def test_role_tables_are_keyed_by_every_role_in_stage_order(self):
        stage_order = [role.value for role in ALL_AGENT_ROLES]
        for key in ("role_names", "missions", "role_gates"):
            self.assertEqual(list(self.data[key]), stage_order, key)
        self.assertEqual(list(self.data["negative"]["role_modules"]), [role.value for role in POST_WRITER_ROLES])
        self.assertEqual(list(agent_council._ROLE_NAMES), list(ALL_AGENT_ROLES))
        self.assertEqual(list(agent_council._MISSIONS), list(ALL_AGENT_ROLES))
        self.assertEqual(list(agent_council._ROLE_GATES), list(ALL_AGENT_ROLES))
        self.assertEqual(list(agent_council._ROLE_NEGATIVE_MODULES), list(POST_WRITER_ROLES))
        for names in self.data["role_names"].values():
            self.assertEqual(len(names), 2)
        for gates in self.data["role_gates"].values():
            self.assertTrue(gates and all(isinstance(gate, str) and gate for gate in gates))

    def test_the_editor_and_mixer_names(self):
        self.assertEqual(agent_council._ROLE_NAMES[AgentRole.AUDIO_DIRECTOR], ("剪辑合成师·声音", "Editor & Mixer · Sound"))
        self.assertEqual(
            agent_council._ROLE_NAMES[AgentRole.COMPOSER_PUBLISHER], ("剪辑合成师·成片", "Editor & Mixer · Final Cut"),
        )
        self.assertEqual(agent_council._ROLE_NAMES[AgentRole.EXECUTIVE_DIRECTOR], ("总导演", "Executive Director"))

    def test_capability_wording_follows_the_catalog_in_order(self):
        table = self.data["capabilities"]
        self.assertEqual(list(table), [capability.id for capability in CAPABILITIES])
        for capability in CAPABILITIES:
            self.assertEqual(set(table[capability.id]), {"label", "policy"}, capability.id)
            self.assertEqual(capability.label, table[capability.id]["label"])
            self.assertEqual(capability.executable_policy, table[capability.id]["policy"])

    def test_artifact_labels_follow_the_role_outputs_in_order(self):
        flattened = [item for outputs in agent_council._ROLE_OUTPUTS.values() for item in outputs]
        self.assertEqual(list(self.data["artifact_labels"]), flattened)
        self.assertEqual(list(ARTIFACT_LABELS), flattened)

    def test_negative_module_tables_agree_and_keep_their_order(self):
        negative = self.data["negative"]
        self.assertEqual(list(negative["module_labels"]), list(negative["module_words"]))
        self.assertEqual(list(NEGATIVE_MODULE_LABELS), list(negative["module_labels"]))
        self.assertEqual(list(NEGATIVE_MODULE_WORDS), list(negative["module_words"]))
        modules = list(negative["module_words"])
        self.assertEqual(negative["base_modules"], modules[:len(negative["base_modules"])])
        for role, selected in negative["role_modules"].items():
            self.assertEqual(selected, [m for m in modules if m in selected], f"{role}: modules out of table order")
        roles = {role.value for role in POST_WRITER_ROLES}
        for module, owners in negative["genre_roles"].items():
            self.assertIn(module, modules)
            self.assertLessEqual(set(owners), roles, module)
        # First the period, then the suspense, then the sci-fi trigger: the catalog appends in this order.
        self.assertEqual(
            [module for module, _ in negative["genre_triggers"]],
            ["period_costume_architecture", "suspense_horror_visibility", "scifi_material_ui"],
        )
        self.assertEqual(negative["high_action_modules"], ["action_physics", "weapon_contact", "crowd_limb_separation"])
        appended = [module for module, _ in negative["genre_triggers"]] + negative["high_action_modules"]
        self.assertEqual(list(negative["genre_roles"]), appended)
        self.assertEqual(modules[len(negative["base_modules"]):], appended)

    def test_no_chinese_string_literal_is_left_in_the_module(self):
        tree = _tree()
        docstrings = {
            id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
        }
        left = sorted({
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _CJK.search(node.value)
            and id(node) not in docstrings
        } - set(_ALLOWED_LITERALS))
        self.assertEqual(left, [])


class SaysWhatTheTableSaysTests(unittest.TestCase):
    def test_negative_prompt_wraps_the_words(self):
        self.assertEqual(compile_negative_prompt(["text_watermark"]), "(避免：subtitles, watermark, logo)")
        self.assertEqual(compile_negative_prompt([]), "")

    def test_role_prompt_reads_as_before(self):
        plan = AgentCouncilCompiler().compile(CouncilCompileRequest(title="冒牌皇帝", premise="乞丐被迫冒充皇帝"))
        director, writer, designer = plan.agents[0].system_prompt, plan.agents[1].system_prompt, plan.agents[2].system_prompt
        self.assertTrue(director.startswith(
            "Role: 总导演 (Executive Director)\n项目：《冒牌皇帝》；题材=auto；受众=18-35 岁短剧观众；平台=douyin；"
            "形式=live_action；语言=zh-CN。\n使命：确立题材、受众、商业边界"
        ))
        self.assertIn("交付基准：1080×1920 9:16 30fps；前3秒钩子；对白默认不超过15个汉字；发布阈值85分；", director)
        self.assertIn("\n本角色可执行能力：\n- [genre_strategy] 从题材库选择主类型", director)
        self.assertIn("必须交付的结构化产物：导演宪法、题材与受众策略、", director)
        self.assertTrue(director.endswith("不得伪造已生成、已授权或已验收。"))
        self.assertNotIn("本角色负面提示词模块", writer)
        self.assertIn("缺失项写「待补」，专业术语用中文（必要时括注英文缩写，如 LUT、fps）。\n本阶段验收：\n- ", writer)
        self.assertIn("）：\n- common_quality（通用画质(一)）\n", designer)
        self.assertIn("- text_watermark（文字水印logo(一·关键压制项)）\n本阶段验收：\n- 每个角色/状态独立交付", designer)
        self.assertEqual(plan.delivery.subtitle_safe_zone, "字幕位于下方1/5上沿；避开顶部约200px与底部约250px平台UI")

    def test_release_details_read_as_before(self):
        issues = [
            CouncilIssue(code="x.b", severity="B", owner=AgentRole.WRITER, detail="台词过长"),
            CouncilIssue(code="x.s", severity="S", owner=AgentRole.PR_AGENT, detail="夸大宣传", resolved=True),
        ]
        self.assertEqual(
            AgentCouncilCompiler.unresolved_issue_summary(issues), {"writer": ["[B] x.b: 台词过长"]},
        )


if __name__ == "__main__":
    unittest.main()

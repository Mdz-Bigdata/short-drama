# -*- coding: utf-8 -*-
"""fight-prompt-director 的登记、许可与「打戏内容真的到达阶段四提示词」验收。

这套用例守的是一件很容易白干的事：打戏资料写在参考文件第三千行，而该章预算只有
四千字符——内容在仓库里，却一个字都进不了提示词。所以下面不测「文件里有没有」，
只测「阶段四那条 prompt 字符串里有没有」。
"""

import json
import unittest
from pathlib import Path

from app.core.capability_manifest import (
    UPSTREAM_CAPABILITIES,
    capability_command_catalog,
    capability_implementation_report,
)
from app.core.provenance import upstream_source_by_id
from app.core.shot_design_skill import (
    SHOT_DESIGN_SECTIONS,
    STAGE_PROMPT_CHAR_CAP,
    reset_shot_design_cache,
    section_budgets,
)
from app.core.skill_registry import SkillRegistry
from app.service.drama_service import DramaService


SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"
FIGHT_SKILL_ROOT = SKILLS_ROOT / "fight-prompt-director"
SOURCE_ID = "fight-prompt-director"


class VendoredSkillPackageTests(unittest.TestCase):
    """MIT 逐字 vendored 的红线：LICENSE 原文 + 归因 + 版权声明必须齐全。"""

    def test_the_registry_discovers_the_skill(self):
        names = {item.name for item in SkillRegistry([SKILLS_ROOT]).list()}

        self.assertIn(SOURCE_ID, names)

    def test_the_front_matter_parses_into_a_usable_description(self):
        skill = SkillRegistry([SKILLS_ROOT]).get(SOURCE_ID)

        self.assertEqual(skill.name, SOURCE_ID)
        self.assertGreater(len(skill.description), 40)
        self.assertNotEqual(skill.description.strip(), ">")
        self.assertIn("动作", skill.description)

    def test_every_reference_the_skill_links_to_exists(self):
        body = (FIGHT_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for reference in ("fight-design.md", "camera-guide.md", "diagnostics.md"):
            self.assertIn(reference, body, reference)
            self.assertTrue((FIGHT_SKILL_ROOT / "references" / reference).is_file(), reference)

    def test_the_mit_licence_ships_verbatim_with_its_copyright_line(self):
        licence = (FIGHT_SKILL_ROOT / "LICENSE").read_text(encoding="utf-8")

        self.assertIn("MIT License", licence)
        self.assertIn("Copyright (c) 2026 fight-prompt-director contributors", licence)
        self.assertIn("The above copyright notice and this permission notice", licence)

    def test_the_source_record_names_what_was_vendored_and_what_is_never_executed(self):
        record = json.loads((FIGHT_SKILL_ROOT / "SOURCE.json").read_text(encoding="utf-8"))

        self.assertEqual(record["reviewed_commit"], upstream_source_by_id()[SOURCE_ID].reviewed_commit)
        self.assertEqual(record["executed_upstream_files"], [])
        # 归因表里列出的每一份文件都必须真的躺在包里，否则归因就是空头支票。
        for relative in record["vendored_upstream_files"]:
            self.assertTrue((FIGHT_SKILL_ROOT / relative).is_file(), relative)
        self.assertIn("LICENSE", record["vendored_upstream_files"])


class CapabilityRegistrationTests(unittest.TestCase):
    """capability_manifest 的位置对齐断言在导入期就会炸；这里把它钉死。"""

    def _source(self) -> dict:
        return next(item for item in UPSTREAM_CAPABILITIES if item["id"] == SOURCE_ID)

    def test_the_source_is_registered_with_pinned_provenance(self):
        record = upstream_source_by_id()[SOURCE_ID]

        self.assertEqual(record.url, self._source()["source"])
        self.assertEqual(record.code_treatment, "attributed-adaptation")
        self.assertIn("MIT", record.license_observation)
        self.assertIn("fight-prompt-director", record.attribution)
        self.assertEqual(len(record.capability_ids), len(self._source()["capabilities"]))

    def test_the_startup_alignment_assertion_still_passes(self):
        # _implementations_for() raises when entrypoints and capabilities drift apart,
        # and the whole report walks every source - so this covers all 15, not just ours.
        report = capability_implementation_report()

        row = next(item for item in report if item["source_id"] == SOURCE_ID)
        self.assertEqual(
            [item["capability"] for item in row["implementations"]],
            self._source()["capabilities"],
        )
        self.assertTrue(all(item["entrypoint"] for item in row["implementations"]))
        self.assertTrue(all(
            item["evidence"] == "backend/tests/test_fight_prompt_skill.py"
            for item in row["implementations"]
        ))

    def test_each_capability_becomes_one_unique_command(self):
        commands = [item for item in capability_command_catalog() if item["source_id"] == SOURCE_ID]

        self.assertEqual(len(commands), len(self._source()["capabilities"]))
        self.assertEqual(len({item["command"] for item in commands}), len(commands))
        self.assertTrue(all(item["command"].startswith("/fight-prompt-director.") for item in commands))

    def test_the_declared_entrypoints_are_real(self):
        row = next(
            item for item in capability_implementation_report() if item["source_id"] == SOURCE_ID
        )
        entrypoints = {item["entrypoint"] for item in row["implementations"]}

        self.assertIn("app.service.drama_service.DramaService._detect_scene_kind", entrypoints)
        self.assertTrue(callable(DramaService._detect_scene_kind))
        by_capability = {item["capability"]: item for item in row["implementations"]}
        # 场次判定不经模型，不该被 drama_service 这个粗标记算成 provider-dependent。
        self.assertEqual(by_capability["fight scene detection"]["implementation_status"], "implemented")
        self.assertTrue(callable(DramaService.storyboard_skill_prefix))
        self.assertTrue(callable(section_budgets))


class SceneKindRoutingTests(unittest.TestCase):
    def test_a_fight_scene_swaps_in_the_action_sections(self):
        kind = DramaService._detect_scene_kind("两人短兵相接，陈九一记扫腿逼退对手，刀光擦着颈侧划过。")

        self.assertEqual(kind, "fight")
        sections = DramaService.storyboard_skill_sections("seedance2.5", scene_kind=kind)
        self.assertIn("performance-action", sections)
        self.assertIn("choreography-beats", sections)

    def test_a_dialogue_scene_keeps_the_original_sections(self):
        kind = DramaService._detect_scene_kind("两人隔着长桌对坐，林夏把信推过去，谁都没有先开口。")

        self.assertEqual(kind, "general")
        self.assertEqual(
            DramaService.storyboard_skill_sections("seedance2.5", scene_kind=kind),
            DramaService.STORYBOARD_SKILL_SECTIONS,
        )

    def test_every_fight_section_is_a_declared_readable_file(self):
        from app.core.shot_design_skill import SKILL_ROOT

        for model in ("", "seedance2.5", "MiniMax-H3"):
            for key in DramaService.storyboard_skill_sections(model, scene_kind="fight"):
                self.assertIn(key, SHOT_DESIGN_SECTIONS, key)
                self.assertTrue((SKILL_ROOT / SHOT_DESIGN_SECTIONS[key]).is_file(), key)


class FightMaterialReachesTheStageFourPromptTests(unittest.TestCase):
    """速度档位与量化节拍必须出现在**提示词字符串**里，不只是出现在文件里。"""

    # 三档速度方案：这些字符串只在 §3.15 里，正文压缩版没有复述。
    SPEED_TIERS = ("节奏档位", "三档主表", "极速档", "标准档", "慢档")
    # 量化节拍：把「快」「慢」变成可数参数的那几行。
    QUANTIFIED_BEATS = (
        "交锋次数",
        "5–7 次",       # 极速档
        "12–15 镜",     # 极速档成片镜数
        "0.6–1.2 秒",   # 极速档成片单镜时长
        "每镜微动作数",
        "选档决策",     # §3.15 的结尾，被截掉就说明整节没读完
    )
    # 打戏专属的动作词典与硬约束，文戏三章里一个都没有。
    FIGHT_CRAFT = ("攻防轮转", "动能运镜", "出招-受击", "防越轴", "打击感五件套")

    def setUp(self):
        reset_shot_design_cache()

    @staticmethod
    def _fight_prefix(video_model: str) -> str:
        return DramaService.storyboard_skill_prefix(
            {"video_model": video_model}, scene_kind="fight",
        )

    def test_the_speed_tiers_reach_every_supported_model(self):
        for model in ("seedance2.5", "seedance2.0", "MiniMax-H3", ""):
            prefix = self._fight_prefix(model)
            for tier in self.SPEED_TIERS:
                self.assertIn(tier, prefix, f"{model}: {tier} 没进阶段四提示词")

    def test_the_quantified_beats_reach_every_supported_model(self):
        for model in ("seedance2.5", "seedance2.0", "MiniMax-H3", ""):
            prefix = self._fight_prefix(model)
            for beat in self.QUANTIFIED_BEATS:
                self.assertIn(beat, prefix, f"{model}: {beat} 被预算截断")

    def test_the_fight_craft_vocabulary_reaches_every_supported_model(self):
        for model in ("seedance2.5", "seedance2.0", "MiniMax-H3", ""):
            prefix = self._fight_prefix(model)
            for term in self.FIGHT_CRAFT:
                self.assertIn(term, prefix, f"{model}: {term} 没进阶段四提示词")

    def test_the_move_translation_table_reaches_the_prompt(self):
        prefix = self._fight_prefix("seedance2.5")

        # choreography-beats 整章过去从未被任何场次装载过。
        self.assertIn("招式", prefix)
        self.assertIn("危险等级", prefix)

    def test_the_anti_collapse_suffix_the_core_cross_references_actually_arrives(self):
        # SKILL.md 写着「打戏防崩坏后缀见 performance-action §3.13」；那一节到不了，
        # 核心里的交叉引用就是一条死链。
        prefix = self._fight_prefix("seedance2.5")

        self.assertIn("动作戏负面词", prefix)
        self.assertIn("deformed limbs", prefix)
        self.assertIn("不要跳轴", prefix)

    def test_a_dialogue_scene_is_not_charged_for_the_fight_tables(self):
        general = DramaService.storyboard_skill_prefix(
            {"video_model": "seedance2.5"}, scene_kind="general",
        )

        # 核心 SKILL.md 只用一行提到「节奏档」并把读者指向附 §3.15，所以这里挑的是
        # 只存在于那张表里的量化数字——它们进了文戏提示词才叫预算被武打表格挤占。
        self.assertNotIn("三档主表", general)
        self.assertNotIn("0.6–1.2 秒", general)
        self.assertNotIn("选档决策", general)
        # 文戏该拿到的两章一个都不能少。
        self.assertIn("九字段站位模板", general)
        self.assertIn("两人站位六式", general)

    def test_every_scene_kind_and_model_stays_under_the_stage_prompt_cap(self):
        for model in ("seedance2.5", "seedance2.0", "MiniMax-H3", "minimax_h3", "hailuo", ""):
            for kind in ("general", "fight", "unknown-kind"):
                prefix = DramaService.storyboard_skill_prefix(
                    {"video_model": model}, scene_kind=kind,
                )
                self.assertLess(len(prefix), STAGE_PROMPT_CHAR_CAP, f"{model}/{kind}")

    def test_an_unknown_scene_kind_degrades_to_the_dialogue_profile(self):
        unknown = DramaService.storyboard_skill_prefix(
            {"video_model": "seedance2.5"}, scene_kind="unknown-kind",
        )
        general = DramaService.storyboard_skill_prefix(
            {"video_model": "seedance2.5"}, scene_kind="general",
        )

        self.assertEqual(unknown, general)

    def test_the_budgets_leave_headroom_under_the_cap(self):
        # 预算表是手工倒推的；一旦某章长胖到把余量吃光，这条先红，而不是线上超顶。
        for model in ("seedance2.5", "MiniMax-H3"):
            headroom = STAGE_PROMPT_CHAR_CAP - len(self._fight_prefix(model))
            self.assertGreater(headroom, 100, f"{model} 打戏前缀余量只剩 {headroom}")

    def test_no_scene_kind_and_model_combination_exceeds_the_cap(self):
        # 打戏档有专门的余量断言；文戏档沿用改造前的默认预算，历史余量本就只有
        # 十几个字符——这里不强求余量，只保证任何组合都不越顶，且未知场景类型
        # 逐字回落文戏档而不是撑出一份更长的前缀。
        for model in ("seedance2.5", "seedance2.0", "MiniMax-H3", ""):
            for scene_kind in ("fight", "general", "unknown_kind"):
                prefix = DramaService.storyboard_skill_prefix(
                    {"video_model": model}, scene_kind=scene_kind,
                )
                self.assertLessEqual(
                    len(prefix), STAGE_PROMPT_CHAR_CAP,
                    f"{model or '默认'}/{scene_kind} 前缀 {len(prefix)} 超过上限",
                )


if __name__ == "__main__":
    unittest.main()

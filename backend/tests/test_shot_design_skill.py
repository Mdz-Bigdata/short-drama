# -*- coding: utf-8 -*-
"""The storyboard-prompt skill must be discoverable, loadable and budget-bounded."""
import os
import unittest
from pathlib import Path

from app.core.shot_design_skill import (
    SHOT_DESIGN_SECTIONS,
    SKILL_ROOT,
    load_shot_design_skill,
    reset_shot_design_cache,
    shot_design_skill_installed,
)
from app.core.skill_registry import SkillRegistry
from app.core.video_references import MIN_SHOT_SECONDS, max_shot_seconds
from app.core.workflow_prompts import build_video_batch_prompt


class SkillPackageTests(unittest.TestCase):
    def setUp(self):
        reset_shot_design_cache()

    def test_the_package_is_installed(self):
        self.assertTrue(shot_design_skill_installed())

    def test_every_declared_section_file_exists(self):
        for key, relative in SHOT_DESIGN_SECTIONS.items():
            self.assertTrue((SKILL_ROOT / relative).is_file(), f"缺少 {key} -> {relative}")

    def test_the_registry_discovers_it(self):
        registry = SkillRegistry([Path(__file__).resolve().parents[1] / "skills"])

        names = {item.name for item in registry.list()}

        self.assertIn("shot-design-master", names)

    def test_the_description_survives_front_matter_parsing(self):
        # A folded YAML scalar ("description: >") makes SkillRegistry capture a bare ">".
        registry = SkillRegistry([Path(__file__).resolve().parents[1] / "skills"])

        skill = next(item for item in registry.list() if item.name == "shot-design-master")

        self.assertGreater(len(skill.description), 40)
        self.assertNotEqual(skill.description.strip(), ">")
        self.assertIn("分镜", skill.description)

    def test_the_core_states_the_hard_rules(self):
        core = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for rule in ("只写摄影机拍得到", "六锚点", "180", "禁止分身", "起幅", "落幅"):
            self.assertIn(rule, core, rule)

    def test_the_six_paragraph_contract_is_named_in_full(self):
        core = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for paragraph in (
            "subject_definitions", "summary", "retention_analysis",
            "detailed_description", "overall_soundscape", "non_diegetic_music",
        ):
            self.assertIn(paragraph, core, paragraph)


class SkillLoadingTests(unittest.TestCase):
    def setUp(self):
        reset_shot_design_cache()

    def test_loading_without_sections_returns_only_the_core(self):
        core_only = load_shot_design_skill()

        self.assertIn("通用分镜提示词大师", core_only)
        self.assertTrue(core_only.strip())

    def test_requested_sections_are_appended(self):
        loaded = load_shot_design_skill(("shot-grammar",), section_budget=100_000)

        self.assertGreater(len(loaded), len(load_shot_design_skill()))

    def test_budgets_are_respected_and_cut_on_a_line_boundary(self):
        loaded = load_shot_design_skill(("shot-grammar",), core_budget=800, section_budget=800)

        # Two truncated blocks plus their notices; never the whole package.
        self.assertLess(len(loaded), 4_000)
        self.assertIn("已按上下文预算截断", loaded)

    def test_an_unknown_section_is_skipped_not_fatal(self):
        self.assertTrue(load_shot_design_skill(("no-such-section",)).strip())

    def test_a_path_traversal_section_reads_nothing(self):
        from app.core import shot_design_skill

        self.assertEqual(shot_design_skill._read("../../../etc/passwd"), "")

    def test_duplicate_sections_are_loaded_once(self):
        once = load_shot_design_skill(("shot-grammar",))
        twice = load_shot_design_skill(("shot-grammar", "shot-grammar"))

        self.assertEqual(once, twice)


class ClipCeilingWiringTests(unittest.TestCase):
    """The skill documents per-model caps; the code must enforce the same ones."""

    def test_a_thirty_second_clip_is_accepted_for_a_thirty_second_model(self):
        prompt = build_video_batch_prompt(
            batch_index=1,
            visual_style="古装权谋",
            duration_seconds=30,
            spatial_relationship="祭坛边柴堆引火区，主体1立于画面左侧，主体2立于画面右侧。",
            timeline="0-30秒，中景，缓慢横移，两人隔火对峙。",
            max_duration_seconds=max_shot_seconds("seedance2.5"),
        )

        self.assertIn("预计时长：30秒", prompt)

    def test_the_same_clip_is_refused_for_a_fifteen_second_model(self):
        with self.assertRaises(ValueError) as caught:
            build_video_batch_prompt(
                batch_index=1,
                visual_style="古装权谋",
                duration_seconds=30,
                spatial_relationship="祭坛边柴堆引火区，主体1立于画面左侧。",
                timeline="0-30秒，中景，缓慢横移。",
                max_duration_seconds=max_shot_seconds("seedance2.0"),
            )

        self.assertIn("15", str(caught.exception))

    def test_the_default_ceiling_preserves_the_previous_contract(self):
        with self.assertRaises(ValueError):
            build_video_batch_prompt(
                batch_index=1, visual_style="x", duration_seconds=16,
                spatial_relationship="祭坛边，主体1立于画面左侧。", timeline="0-16秒，中景。",
            )

    def test_a_clip_below_the_floor_is_refused(self):
        with self.assertRaises(ValueError):
            build_video_batch_prompt(
                batch_index=1, visual_style="x", duration_seconds=MIN_SHOT_SECONDS - 1,
                spatial_relationship="祭坛边，主体1立于画面左侧。", timeline="0-3秒，中景。",
            )


class StoryboardStageWiringTests(unittest.TestCase):
    """Stage 4 writes the shot table with an LLM; the skill must reach that prompt."""

    def setUp(self):
        from app.core.shot_design_skill import reset_shot_design_cache

        reset_shot_design_cache()
        self._saved = {
            key: os.environ.pop(key, None)
            for key in ("SHOT_DESIGN_CORE_BUDGET", "SHOT_DESIGN_SECTION_BUDGET")
        }

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    @staticmethod
    def _prefix(video_model: str) -> str:
        from app.service.drama_service import DramaService

        return DramaService.storyboard_skill_prefix({"video_model": video_model})

    def test_the_prefix_carries_the_skill_and_the_model_ceiling(self):
        prefix = self._prefix("seedance2.5")

        self.assertIn("通用分镜提示词技能", prefix)
        self.assertIn("单镜时长硬上限", prefix)
        self.assertIn("30 秒", prefix)
        self.assertIn("seedance2.5", prefix)

    def test_the_ceiling_tracks_the_selected_model(self):
        for model, cap in (("seedance2.0", 15), ("MiniMax-H3", 15), ("seedance2.5", 30)):
            self.assertIn(f"{cap} 秒", self._prefix(model), model)

    def test_an_unset_model_still_states_a_conservative_ceiling(self):
        prefix = self._prefix("")

        self.assertIn("10 秒", prefix)
        self.assertIn("未指定", prefix)

    def test_the_prefix_stays_within_a_stage_prompt_budget(self):
        # Stage 4 already stacks several project guides (~28k chars); the skill on top
        # must stay bounded or small models hang on the request.
        self.assertLess(len(self._prefix("seedance2.5")), 26_000)

    def test_budgets_are_configurable_by_environment(self):
        from app.core.shot_design_skill import reset_shot_design_cache

        os.environ["SHOT_DESIGN_CORE_BUDGET"] = "600"
        os.environ["SHOT_DESIGN_SECTION_BUDGET"] = "400"
        reset_shot_design_cache()

        self.assertLess(len(self._prefix("seedance2.5")), 4_000)

    def test_the_sections_stage_four_asks_for_all_exist(self):
        from app.service.drama_service import DramaService

        for model in ("", "seedance2.5", "MiniMax-H3"):
            for key in DramaService.storyboard_skill_sections(model):
                self.assertIn(key, SHOT_DESIGN_SECTIONS, key)
                self.assertTrue((SKILL_ROOT / SHOT_DESIGN_SECTIONS[key]).is_file(), key)

    def test_an_h3_project_also_gets_h3s_own_field_contract(self):
        from app.service.drama_service import DramaService

        for model in ("MiniMax-H3", "minimax_h3", "hailuo", "MiniMax-Hailuo-2.3"):
            self.assertIn("h3-native-contract", DramaService.storyboard_skill_sections(model), model)

    def test_a_seedance_project_does_not_load_the_h3_contract(self):
        from app.service.drama_service import DramaService

        for model in ("seedance2.0", "seedance2.5", ""):
            self.assertNotIn("h3-native-contract", DramaService.storyboard_skill_sections(model), model)


class CraftRulesReachThePromptTests(unittest.TestCase):
    """These rules change output quality, so they must survive the stage-4 budget.

    They previously lived in an appended section of shot-grammar.md and were cut
    by the per-section budget, so the generator never saw them.
    """

    RULES = (
        "词序即权重",
        "单帧单景别",
        "审核风险",
        "崩坏风险曲线",
        "竖屏 9:16 修正",
        "黄金 15 秒切片",
        "五镜动作链",
        "八大镜头组合",
    )

    def setUp(self):
        from app.core.shot_design_skill import reset_shot_design_cache

        reset_shot_design_cache()
        self._saved = {
            key: os.environ.pop(key, None)
            for key in ("SHOT_DESIGN_CORE_BUDGET", "SHOT_DESIGN_SECTION_BUDGET")
        }

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_every_craft_rule_reaches_the_storyboard_prompt(self):
        from app.service.drama_service import DramaService

        prefix = DramaService.storyboard_skill_prefix({"video_model": "seedance2.5"})

        for rule in self.RULES:
            self.assertIn(rule, prefix, f"{rule} 被预算截断，生成阶段读不到")

    def test_the_rules_hold_for_every_supported_model(self):
        from app.service.drama_service import DramaService

        for model in ("MiniMax-H3", "seedance2.0", "seedance2.5", ""):
            prefix = DramaService.storyboard_skill_prefix({"video_model": model})
            for rule in self.RULES:
                self.assertIn(rule, prefix, f"{model}: {rule}")

    def test_the_core_fits_its_budget_uncut(self):
        from app.core.shot_design_skill import DEFAULT_CORE_BUDGET, load_shot_design_skill

        core = load_shot_design_skill(core_budget=DEFAULT_CORE_BUDGET)

        # A truncated core would drop the rules at the bottom of SKILL.md.
        self.assertNotIn("已按上下文预算截断", core)

    def test_the_word_order_rule_shows_both_the_wrong_and_right_form(self):
        core = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Close-up shot of a handsome man", core)
        self.assertIn("✗", core)
        self.assertIn("✓", core)


class SourcedMaterialTests(unittest.TestCase):
    """Material harvested from the source articles must stay reachable."""

    def setUp(self):
        from app.core.shot_design_skill import reset_shot_design_cache

        reset_shot_design_cache()

    def _ref(self, name: str) -> str:
        return (SKILL_ROOT / "references" / name).read_text(encoding="utf-8")

    def test_the_eight_blocking_methods_are_documented(self):
        text = self._ref("blocking-lighting.md")

        for method in (
            "核心镜头站位", "对话切换站位", "三角关系站位", "空间象征站位",
            "运动固定站位", "对称仪式站位", "冲突对峙站位", "前后中景层次站位",
        ):
            self.assertIn(method, text, method)

    def test_the_five_axis_prompts_are_documented(self):
        text = self._ref("blocking-lighting.md")

        for axis in ("180° 运动轴线", "视线轴线", "对话轴线", "角色位置轴线", "镜头运动轴线"):
            self.assertIn(axis, text, axis)

    def test_the_z_axis_staging_rule_is_documented(self):
        text = self._ref("blocking-lighting.md")

        self.assertIn("Z 轴舞台", text)
        self.assertIn("前景", text)
        self.assertIn("倒三角站位", text)

    def test_the_blocking_consistency_solutions_are_documented(self):
        text = self._ref("blocking-lighting.md")

        for solution in ("锚点道具", "参考图锁位", "角色记忆卡"):
            self.assertIn(solution, text, solution)

    def test_thirty_copy_paste_templates_are_documented(self):
        text = self._ref("shot-grammar.md")

        self.assertIn("30 组可直接复制", text)
        for term in ("Head-and-Shoulders", "Frame within Frame", "Telephoto Compression",
                     "Environmental Portrait", "Negative Space"):
            self.assertIn(term, text, term)

    def test_motion_and_transition_reach_the_prompt(self):
        # Short, shot-table-relevant tables: they are ordered ahead of the long
        # image-prompt template tables precisely so truncation cannot drop them.
        from app.service.drama_service import DramaService

        prefix = DramaService.storyboard_skill_prefix({"video_model": "seedance2.5"})

        self.assertIn("动势：让静止画面", prefix)
        self.assertIn("转场：镜与镜之间", prefix)

    def test_motion_and_transition_systems_are_documented(self):
        text = self._ref("shot-grammar.md")

        for term in ("动势", "dissolve transition", "match cut transition", "whip pan transition"):
            self.assertIn(term, text, term)

    def test_the_universal_formulas_reach_the_prompt(self):
        from app.service.drama_service import DramaService

        prefix = DramaService.storyboard_skill_prefix({"video_model": "seedance2.5"})

        self.assertIn("镜头景别 + 构图方式 + 人物描述 + 环境光线 + 画质参数", prefix)
        self.assertIn("场景类型 + 角色站位方式 + 轴线关系", prefix)

    def test_the_seven_element_check_reaches_the_prompt(self):
        from app.service.drama_service import DramaService

        prefix = DramaService.storyboard_skill_prefix({"video_model": "seedance2.5"})

        self.assertIn("分镜七要素自查", prefix)
        for element in ("景别", "角度", "构图", "光影", "色调", "动势", "转场"):
            self.assertIn(element, prefix, element)

    def test_the_one_line_mnemonic_reaches_the_prompt(self):
        from app.service.drama_service import DramaService

        prefix = DramaService.storyboard_skill_prefix({"video_model": "seedance2.5"})

        self.assertIn("远景定场 → 中景叙事 → 近景带入 → 特写爆情绪", prefix)


class BlockingAndActionMaterialTests(unittest.TestCase):
    """Person-count blocking and the AI action-safety rules must stay reachable."""

    def setUp(self):
        from app.core.shot_design_skill import reset_shot_design_cache

        reset_shot_design_cache()

    def _prefix(self, model="seedance2.5"):
        from app.service.drama_service import DramaService

        return DramaService.storyboard_skill_prefix({"video_model": model})

    def test_the_two_person_blocking_set_reaches_the_prompt(self):
        prefix = self._prefix()

        self.assertIn("两人站位六式", prefix)
        for form in ("正面相对", "并排站立", "错位站立", "侧身对话", "背对背站立", "镜像站位"):
            self.assertIn(form, prefix, form)

    def test_the_multi_person_blocking_set_reaches_the_prompt(self):
        prefix = self._prefix()

        self.assertIn("三人及以上站位八式", prefix)
        for form in ("三角形站位", "一字横排站位", "梯形站位", "圆形 / 半圆形站位",
                     "分组对立站位", "前中后纵深站位", "交错站位", "中心突出站位"):
            self.assertIn(form, prefix, form)

    def test_the_action_safety_formula_reaches_the_prompt(self):
        prefix = self._prefix()

        self.assertIn("[降速设计] + [单动作单镜] + [暗示代替展示] + [特效加分] + [声音补位]", prefix)
        self.assertIn("运动幅度 ≤ 4", prefix)
        self.assertIn("影子暗示", prefix)

    def test_the_composition_formula_and_pitfalls_reach_the_prompt(self):
        prefix = self._prefix()

        self.assertIn("角色 + 场景 + 景别 + 人物站位 + 前中后景层次 + 人物视线 + 镜头情绪氛围", prefix)
        self.assertIn("五大误区", prefix)

    def test_the_action_reference_documents_the_full_playbook(self):
        text = (SKILL_ROOT / "references" / "performance-action.md").read_text(encoding="utf-8")

        for item in ("降速设计", "单动作单镜", "暗示代替展示", "特效加分", "声音补位",
                     "影子暗示打斗", "翻车急救表", "危险等级"):
            self.assertIn(item, text, item)

    def test_the_sixty_compositions_are_documented(self):
        text = (SKILL_ROOT / "references" / "shot-grammar.md").read_text(encoding="utf-8")

        self.assertIn("60 套标准化构图", text)
        for item in ("边缘孤立构图", "窗格分割构图", "背靠背危机构图", "孤灯单人构图", "转角追逐"):
            self.assertIn(item, text, item)

    def test_the_action_rules_do_not_contradict_the_shot_table_floor(self):
        # The action guide recommends 5s shots; that must stay above the submission floor.
        from app.core.video_references import MIN_SHOT_SECONDS

        self.assertLessEqual(MIN_SHOT_SECONDS, 5)


class H3ContractTests(unittest.TestCase):
    """The H3 reference must keep the upstream field names byte-exact."""

    def setUp(self):
        from app.core.shot_design_skill import reset_shot_design_cache

        reset_shot_design_cache()
        self.text = (SKILL_ROOT / "references" / "h3-native-contract.md").read_text(encoding="utf-8")

    def test_the_five_input_modes_are_named(self):
        for mode in ("T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"):
            self.assertIn(mode, self.text, mode)

    def test_the_base_mode_field_names_are_verbatim(self):
        for field in ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"):
            self.assertIn(field, self.text, field)

    def test_the_six_reference_sections_are_verbatim(self):
        for field in (
            "subject_definitions", "summary", "retention_analysis",
            "detailed_description", "overall_soundscape", "non_diegetic_music",
        ):
            self.assertIn(field, self.text, field)

    def test_the_reference_labels_and_speaker_syntax_survive(self):
        for token in ("<Subject N>", "<Picture N>", "<Video N>", "<Audio N>", "(S1)", "<d>", "<scenetrans>", "<cutoff>"):
            self.assertIn(token, self.text, token)

    def test_the_retention_markers_are_verbatim(self):
        for marker in (
            "fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference",
            "fully_copy", "partially_copy",
        ):
            self.assertIn(marker, self.text, marker)

    def test_the_documented_duration_matches_the_request_schema(self):
        from app.schema.production import H3VideoRequest

        bounds = {type(item).__name__: item for item in H3VideoRequest.model_fields["duration_seconds"].metadata}

        self.assertIn(f"{bounds['Ge'].ge}–{bounds['Le'].le}", self.text)

    def test_the_camera_vocabulary_is_present(self):
        for term in ("Push In", "Truck Left", "Pedestal Up", "Arc Shot", "with small amplitude", "at slow speed"):
            self.assertIn(term, self.text, term)


class NineFieldBlockingTests(unittest.TestCase):
    def test_the_nine_field_template_is_available(self):
        text = (SKILL_ROOT / "references" / "blocking-lighting.md").read_text(encoding="utf-8")

        for field in ("【场景】", "【主角】", "【副手】", "【随从】", "【环境】", "【光影】", "【机位】", "【风格】", "【氛围】"):
            self.assertIn(field, text, field)
        self.assertIn("九字段站位模板", text)

    def test_the_template_survives_the_stage_four_budget(self):
        from app.service.drama_service import DramaService

        prefix = DramaService.storyboard_skill_prefix({"video_model": "seedance2.5"})

        self.assertIn("九字段站位模板", prefix)


class CloneGuardTests(unittest.TestCase):
    def test_the_gateway_carries_an_anti_clone_clause(self):
        from app.core.model_gateway import ModelGateway

        clause = ModelGateway.CLONE_NEGATIVE

        self.assertIn("分身", clause)
        self.assertIn("双胞胎", clause)
        self.assertIn("no duplicated character", clause)


if __name__ == "__main__":
    unittest.main()

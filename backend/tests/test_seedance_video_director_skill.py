# -*- coding: utf-8 -*-
"""seedance-2-5-video-director：许可、登记、上游校验器，以及「导演层真的进了 Seedance 2.5 的提示词」。

和 fight-prompt-director 的用例一样，这里不测「文件里有没有」，只测「优化器发给文本模型的
那条系统提示里有没有」——并且反向断言 2.0 拿不到这一层，因为上游明写 provider-specific。
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from app.core.capability_manifest import (
    UPSTREAM_CAPABILITIES,
    capability_command_catalog,
    capability_implementation_report,
)
from app.core.model_gateway import ModelGateway
from app.core.provenance import upstream_source_by_id
from app.core.seedance_video_director import (
    DIRECTOR_LAYER_CHAR_CAP,
    SKILL_NAME,
    SKILL_ROOT,
    build_director_layer,
    is_seedance_25,
    load_director_layer,
    reset_seedance_director_cache,
    select_primary_mode,
)
from app.core.skill_registry import SkillRegistry


SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"

DIALOGUE_PROMPT = (
    "雨夜街头，林夏站在路灯下，低声说道：“你别走。”她眼神闪躲，肩膀微微颤抖，"
    "对面的男人握紧拳头推开她，转身冲进雨里。"
)
PLAIN_PROMPT = "清晨的咖啡馆，阳光落在木桌上，一杯拿铁冒着热气，镜头缓慢推进。"


class VendoredPackageTests(unittest.TestCase):
    """MIT 逐字 vendored 的红线：LICENSE + NOTICE + 归因齐全，上游校验器对本副本仍然通过。"""

    def test_the_registry_discovers_the_skill(self):
        names = {item.name for item in SkillRegistry([SKILLS_ROOT]).list()}

        self.assertIn(SKILL_NAME, names)

    def test_license_and_notice_travel_with_the_package(self):
        license_text = (SKILL_ROOT / "LICENSE").read_text(encoding="utf-8")
        notice = (SKILL_ROOT / "NOTICE.md").read_text(encoding="utf-8")

        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 liyue-aigc", license_text)
        self.assertIn("independent community project", notice)

    def test_the_source_record_matches_what_is_on_disk(self):
        source = json.loads((SKILL_ROOT / "SOURCE.json").read_text(encoding="utf-8"))
        record = upstream_source_by_id()[SKILL_NAME]

        self.assertEqual(source["reviewed_commit"], record.reviewed_commit)
        self.assertEqual(record.code_treatment, "attributed-adaptation")
        for relative in source["vendored_upstream_files"]:
            self.assertTrue((SKILL_ROOT / relative).is_file(), relative)
        # 唯一被执行的上游文件是它自己的结构校验器，且只在测试里跑。
        self.assertEqual(source["executed_upstream_files"], ["scripts/validate_skill.py"])

    def test_the_upstream_validator_passes_against_the_vendored_copy(self):
        # 上游 CI 就是这条命令；vendored 树要是缺文件或改了结构，这里先红。
        result = subprocess.run(
            [sys.executable, "scripts/validate_skill.py"],
            cwd=SKILL_ROOT, capture_output=True, text=True, timeout=60,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Validation passed", result.stdout)


class CapabilityRegistrationTests(unittest.TestCase):
    def test_manifest_and_provenance_agree_on_capability_count(self):
        source = next(item for item in UPSTREAM_CAPABILITIES if item["id"] == SKILL_NAME)
        record = upstream_source_by_id()[SKILL_NAME]

        self.assertEqual(len(source["capabilities"]), len(record.capability_ids))

    def test_the_startup_assertion_still_passes_and_commands_stay_unique(self):
        report = capability_implementation_report()
        row = next(item for item in report if item["source_id"] == SKILL_NAME)
        commands = capability_command_catalog()

        self.assertEqual(len(row["implementations"]), 6)
        self.assertEqual(len({item["command"] for item in commands}), len(commands))


class ModelGateTests(unittest.TestCase):
    def test_only_seedance_25_spellings_pass_the_gate(self):
        for model in ("seedance2.5", "seedance-2.5", "Seedance 2.5", "doubao-seedance-2-5-260128"):
            self.assertTrue(is_seedance_25(model), model)
        for model in ("seedance2.0", "seedance-2.0", "doubao-seedance-2-0-260128", "seedance", "minimax_h3", ""):
            self.assertFalse(is_seedance_25(model), model)

    def test_the_fallback_model_name_is_consulted(self):
        self.assertTrue(is_seedance_25("", "doubao-seedance-2-5-pro"))

    def test_primary_mode_follows_duration_and_timestamps(self):
        self.assertEqual(select_primary_mode(duration=10, prompt=PLAIN_PROMPT), "basic-multimodal")
        self.assertEqual(select_primary_mode(duration=30, prompt=PLAIN_PROMPT), "timestamp-30s")
        self.assertEqual(select_primary_mode(duration=12, prompt="0-5s 走进门；5-12s 坐下"), "timestamp-30s")


class DirectorLayerContentTests(unittest.TestCase):
    def setUp(self):
        reset_seedance_director_cache()

    def test_the_layer_is_empty_for_other_models(self):
        self.assertEqual(load_director_layer(video_model="seedance2.0", duration=10, prompt=DIALOGUE_PROMPT), "")
        self.assertEqual(load_director_layer(video_model="minimax_h3", duration=10, prompt=DIALOGUE_PROMPT), "")

    def test_the_basic_layer_carries_limits_timing_rules_and_the_selected_blueprint(self):
        layer = build_director_layer(video_model="seedance2.5", duration=10, mode="first_frame", prompt=PLAIN_PROMPT)

        self.assertTrue(layer.applied)
        self.assertEqual(layer.primary_mode, "basic-multimodal")
        self.assertEqual(layer.sections[0], "precedence-note")
        self.assertIn("## Mode limits", layer.text)
        self.assertIn("4-30 seconds output", layer.text)
        self.assertIn("## Timing and reference rules", layer.text)
        self.assertIn("## Basic multimodal", layer.text)
        self.assertNotIn("## Exact 30-second timestamp video", layer.text)
        # 聊天 Agent 的行为不接：安装引导、追问策略、输出模式都不该进提示词。
        self.assertNotIn("Installation onboarding protocol", layer.text)
        self.assertNotIn("## Minimal-question policy", layer.text)
        self.assertNotIn("## Output modes", layer.text)
        self.assertNotIn("学习示例", layer.text)

    def test_thirty_second_shots_get_the_timestamp_blueprint(self):
        layer = build_director_layer(video_model="seedance2.5", duration=30, mode="first_frame", prompt=PLAIN_PROMPT)

        self.assertEqual(layer.primary_mode, "timestamp-30s")
        self.assertIn("## Exact 30-second timestamp video", layer.text)
        self.assertNotIn("## Basic multimodal", layer.text)

    def test_dialogue_and_physical_action_pull_in_the_realistic_direction_patterns(self):
        layer = build_director_layer(video_model="seedance2.5", duration=10, mode="first_frame", prompt=DIALOGUE_PROMPT)

        self.assertIn("## Natural human performance", layer.text)
        self.assertIn("## Dialogue and emotional conflict", layer.text)
        self.assertIn("## Physical causality", layer.text)
        self.assertIn("## Person-reference scope", layer.text)

    def test_a_plain_shot_is_not_charged_for_performance_patterns(self):
        layer = build_director_layer(video_model="seedance2.5", duration=10, mode="text_to_video", prompt=PLAIN_PROMPT)

        self.assertNotIn("## Natural human performance", layer.text)
        self.assertNotIn("## Physical causality", layer.text)
        # 文生视频没有参考素材，素材锁表也不该出现。
        self.assertNotIn("## Asset lock table", layer.text)

    def test_the_layer_stays_within_its_budget_even_when_everything_triggers(self):
        everything = DIALOGUE_PROMPT + " 综艺赛道障碍直播，观众席欢呼，音色参考 @音频1。"
        layer = build_director_layer(video_model="seedance2.5", duration=30, mode="multi_ref", prompt=everything)

        self.assertLessEqual(len(layer.text), DIRECTOR_LAYER_CHAR_CAP)
        # 预算内先保住的是硬约束，最后才轮到直播镜头这类可选段。
        self.assertIn("## Mode limits", layer.text)
        self.assertIn("## Timing and reference rules", layer.text)


class GatewayInjectionTests(unittest.TestCase):
    """导演层要真的出现在优化器发出的系统提示里，而且只对 2.5 出现。"""

    def _gateway(self):
        gateway = ModelGateway()
        gateway.seedance_prompt_opt = True
        gateway.seedance_text_model = "doubao-seed-test"
        gateway.seedance_key = "sk-test-not-a-placeholder"
        gateway.seedance_base_url = "https://example.invalid/api/v3"
        gateway._sd2_opt_prompt_cache = "# 主规范：sd25-pe\n素材逐份负责\n"
        gateway.captured = []

        def fake_chat(api_key, base_url, api_model, system_prompt, user_content, timeout=180, max_tokens=None, deadline=None):
            gateway.captured.append(system_prompt)
            return "优化后的工程化提示词正文"

        gateway._http_chat = fake_chat
        return gateway

    def test_seedance_25_prompts_get_the_director_layer(self):
        gateway = self._gateway()

        result = gateway.optimize_video_prompt(
            DIALOGUE_PROMPT, mode="first_frame", video_model="seedance2.5", duration=10,
        )

        self.assertEqual(result, "优化后的工程化提示词正文")
        system_prompt = gateway.captured[-1]
        self.assertIn("# 导演层：seedance-2-5-video-director", system_prompt)
        self.assertIn("## Mode limits", system_prompt)
        self.assertIn("主模式已选定为「basic-multimodal」", system_prompt)
        # 主规范仍在前面，导演层在后：分工顺序是文档写死的契约。
        self.assertLess(system_prompt.find("# 主规范：sd25-pe"), system_prompt.find("# 导演层"))

    def test_seedance_20_prompts_do_not_get_the_director_layer(self):
        gateway = self._gateway()

        gateway.optimize_video_prompt(DIALOGUE_PROMPT, mode="first_frame", video_model="seedance2.0", duration=10)

        self.assertNotIn("导演层", gateway.captured[-1])
        self.assertNotIn("## Mode limits", gateway.captured[-1])

    def test_the_keyword_only_arguments_keep_old_call_sites_working(self):
        gateway = self._gateway()
        gateway.seedance_model_name = "doubao-seedance-2-0-260128"

        gateway.optimize_video_prompt(PLAIN_PROMPT, mode="text_to_video")

        self.assertNotIn("导演层", gateway.captured[-1])



class ChineseHandbookLayerTests(unittest.TestCase):
    """中文手册补充、运镜规则与镜头交接规则按镜头形态进入导演层，且不突破导演层上限。"""

    def test_a_thirty_second_timestamp_shot_gets_the_three_module_layout(self):
        from app.core.seedance_video_director import DIRECTOR_LAYER_CHAR_CAP, build_director_layer

        layer = build_director_layer(
            video_model="doubao-seedance-2-5", duration=30, prompt="0-10s 少女回头；转场：叠化",
        )
        self.assertEqual(layer.primary_mode, "timestamp-30s")
        for name in ("cn-handbook/四种提示词公式", "cn-handbook/30 秒长视频的三个模块", "cn-handbook/中文转场用语"):
            self.assertIn(name, layer.sections)
        self.assertIn("【时间戳剧本分镜】", layer.text)
        self.assertLessEqual(len(layer.text), DIRECTOR_LAYER_CHAR_CAP)

    def test_a_short_shot_without_a_transition_skips_the_transition_table(self):
        from app.core.seedance_video_director import build_director_layer

        layer = build_director_layer(video_model="doubao-seedance-2-5", duration=8, prompt="少女推门进店")
        self.assertNotIn("cn-handbook/30 秒长视频的三个模块", layer.sections)
        self.assertNotIn("cn-handbook/中文转场用语", layer.sections)
        self.assertIn("four-lock/动作连贯三原则", layer.sections)
        self.assertIn("camera-style/选运镜的总规则", layer.sections)

    def test_other_models_get_no_layer(self):
        from app.core.seedance_video_director import build_director_layer

        self.assertEqual(build_director_layer(video_model="minimax-h3", duration=8, prompt="少女推门").text, "")


if __name__ == "__main__":
    unittest.main()

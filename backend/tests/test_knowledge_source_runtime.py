# -*- coding: utf-8 -*-
"""知识源运行时生效性回归测试。

委员会把 18 个 md 注册成 KNOWLEDGE_SOURCE_FILES 只保证"登记在册"；
这里保证每份知识源的内容真的作用在流水线上——要么内容经
production-knowledge-master 装载器(load_section)读进某个阶段的提示词，
要么(负面提示词.md)经模块词表编译进生成提示词。
同时守住知识进化闭环的接线：8 个阶段都注入 stage_lessons_block，
质检报告经 harvest_from_qc → promote_and_prune 回流教训库。
断言基于源代码静态检查：接线一旦被删，测试立刻变红。
"""

import inspect
import unittest


def _drama_source() -> str:
    from app.service import drama_service
    return inspect.getsource(drama_service)


class EveryKnowledgeSourceReachesRuntimeTests(unittest.TestCase):
    # 经装载器以章节键(全文或按登记预算截断)进入阶段提示词的 15 份文档。
    # 键与文件的对应关系由 production_knowledge.SECTION_FILES 唯一登记。
    READ_AT_RUNTIME = (
        "consistency-checklist",   # AI 生成短剧一致性检查清单.md · 全部 8 阶段的 run_real_consistency_check
        "dialogue-pacing",         # AI影视剧台词语速情绪提示词总结.md · 阶段2 编剧台词标注规范
        "golden-narrative",        # AI漫剧短剧剧本黄金叙事结构.md · 阶段1/2
        "director-shot-guide",     # AI短剧与漫剧导演级拍摄分镜完全指南.md · 阶段4
        "five-view-template",      # AI短剧五视图解决人物一致性提示词模板.md · 阶段3
        "production-guidelines",   # AI短剧注意事项与关键元素.md · 阶段1/2/8
        "martial-arts",            # AI短剧电影级武打镜头设计指南.md · 阶段4
        "performance-details",     # AI短剧表演细节与提示词指南.md · 阶段2/3
        "continuity-design",       # AI短剧连续性设计指南.md · 阶段2/4
        "scene-design",            # 场景设计提示词.md · 阶段4
        "highlight-detection",     # 影视剧高光时刻识别方案.md · 阶段8
        "visual-style",            # 画质风格类型总结.md · 阶段5
        "emotion-expression",      # 短剧情绪与面部表情提示词库.md · 阶段4
        "plot-shot-coherence",     # 短剧情节与镜头连贯性提示词.md · 阶段4
        "genre-summary",           # 短剧题材类型总结.md · 阶段1
    )

    def test_each_guide_is_read_into_a_stage_prompt(self):
        source = _drama_source()
        for section_key in self.READ_AT_RUNTIME:
            self.assertIn(
                f'load_section("{section_key}"', source,
                f"知识源章节《{section_key}》不再被任何阶段读取——内容要求失效",
            )

    def test_section_keys_map_to_real_registered_documents(self):
        # 每个运行时章节键都必须在装载器登记且指向根部真实文件名——键名打错立刻变红。
        from app.core.production_knowledge import SECTION_FILES

        for section_key in self.READ_AT_RUNTIME:
            self.assertIn(
                section_key, SECTION_FILES,
                f"章节键《{section_key}》未在 production_knowledge.SECTION_FILES 登记",
            )

    def test_the_registry_and_runtime_cover_the_same_documents(self):
        # 登记在册的产出类知识源(排除 SKILL/THIRD_PARTY 两份工程文档)必须全部有运行时消费：
        # 装载器 SECTION_FILES 的值域 ∪ 负面提示词(走模块词表) == 委员会登记的产出类文档全集。
        from app.core.agent_council import KNOWLEDGE_SOURCE_FILES
        from app.core.production_knowledge import SECTION_FILES

        production_docs = set(KNOWLEDGE_SOURCE_FILES) - {"SKILL.md", "THIRD_PARTY_NOTICES.md"}
        consumed = set(SECTION_FILES.values()) | {"AI影视剧负面提示词.md"}
        self.assertEqual(
            production_docs, consumed,
            "知识源清单与运行时消费清单漂移：新增文档必须同时接入流水线并登记到 SECTION_FILES",
        )
        # 且值域里除负面提示词外的每份文档都要有 load_section 消费(登记≠消费，两头都要锁死)。
        runtime_files = {SECTION_FILES[key] for key in self.READ_AT_RUNTIME}
        self.assertEqual(
            set(SECTION_FILES.values()) - {"AI影视剧负面提示词.md"}, runtime_files,
            "SECTION_FILES 里存在登记了但没有任何阶段 load_section 消费的文档",
        )


class EvolvedLessonsReachEveryStageTests(unittest.TestCase):
    """知识进化闭环接线：教训注入 8 个阶段，质检报告回流教训库。"""

    def test_stage_lessons_block_is_wired_into_all_eight_stages(self):
        # 有 sys_prompt 的阶段(1/2/3/4/8)拼进提示词，阶段5 拼进视觉总监策略简报，
        # 无 LLM 的阶段(6/7)以 learned_lessons 键随产物归档。
        source = _drama_source()
        for stage in range(1, 9):
            self.assertIn(
                f"stage_lessons_block({stage})", source,
                f"第 {stage} 阶段缺少历史生产教训注入 (stage_lessons_block)",
            )

    def test_qc_report_feeds_the_evolution_engine(self):
        # run_real_consistency_check 产出报告后必须蒸馏教训并晋升/退休。
        source = _drama_source()
        self.assertIn("knowledge_evolution.harvest_from_qc(", source,
                      "质检报告不再回流进化引擎 (harvest_from_qc 接线丢失)")
        self.assertIn("knowledge_evolution.promote_and_prune()", source,
                      "教训晋升/退休钩子丢失 (promote_and_prune 接线丢失)")


class NegativePromptModulesReachGenerationTests(unittest.TestCase):
    """《AI影视剧负面提示词.md》走模块词表：委员会配药单 → 编译 → 真实生成提示词。"""

    def test_every_module_has_words_and_a_label(self):
        from app.core.agent_council import NEGATIVE_MODULE_LABELS, NEGATIVE_MODULE_WORDS

        self.assertEqual(set(NEGATIVE_MODULE_WORDS), set(NEGATIVE_MODULE_LABELS))
        for module, words in NEGATIVE_MODULE_WORDS.items():
            self.assertTrue(words.strip(), module)

    def test_compile_dedups_and_respects_the_budget(self):
        from app.core.agent_council import compile_negative_prompt

        self.assertEqual(compile_negative_prompt([]), "")
        out = compile_negative_prompt(["common_quality", "common_quality", "text_watermark"])
        self.assertTrue(out.startswith("(避免："))
        self.assertEqual(out.count("worst quality"), 1)
        # 预算按整模块丢弃，不出现半个词条
        tight = compile_negative_prompt(["common_quality", "face_anatomy"], budget=50)
        self.assertNotIn("face", tight)
        self.assertLessEqual(len(tight), 70)

    def test_role_suffixes_are_wired_into_the_generation_prompts(self):
        source = _drama_source()
        # 阶段3 五视图 / 阶段4 分镜底片 / 阶段5 首帧+尾帧+视频 / 多集路径
        for marker in (
            "extra_negative=designer_negative",
            "{storyboard_negative}",
            "{visual_negative_image}",
            "{visual_negative_video}",
            "{episode_negative_image}",
        ):
            self.assertIn(marker, source, f"负面词接线点丢失：{marker}")

    def test_image_side_of_the_visual_director_excludes_temporal_words(self):
        source = _drama_source()
        self.assertIn('exclude=("temporal_continuity",)', source)

    def test_character_sheet_accepts_the_extra_negative_channel(self):
        from app.core.model_gateway import ModelGateway

        signature = inspect.signature(ModelGateway.generate_character_sheet)
        self.assertIn("extra_negative", signature.parameters)


class DialoguePacingGuideReachesTheWriterTests(unittest.TestCase):
    def test_the_writer_prompt_carries_the_annotation_rule(self):
        source = _drama_source()
        self.assertIn("台词语速情绪与停顿重音标注规范", source)
        self.assertIn("[角色][情绪类型-强度/克制度][语速][生理表现]", source)


if __name__ == "__main__":
    unittest.main()

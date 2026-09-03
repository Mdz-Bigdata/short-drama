# -*- coding: utf-8 -*-
"""production-knowledge-master 技能专属测试：装载一致性、注册发现、进化生命周期、
单向依赖与内容对等回归。

铁律：16 份知识源只存在于仓库根部（唯一事实源），进化数据全部用临时目录重定向，
本文件绝不写入真实的 skills/production-knowledge-master/learned/。
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from app.core import knowledge_evolution
from app.core.production_knowledge import (
    SECTION_BUDGETS,
    SECTION_FILES,
    STAGE_SECTIONS,
    knowledge_root,
    load_section,
    load_stage_sections,
    reset_knowledge_cache,
    stage_lessons_block,
)
from app.core.skill_registry import SkillRegistry
from app.service.drama_service import DramaService


# load_section 行边界截断后附加的标记（与 production_knowledge._truncate 保持一致）
TRUNCATION_MARK = "（本节已按上下文预算截断）"

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"


def _strip_mark(loaded: str) -> str:
    """去掉截断标记，留下真正来自根部文件的正文。"""
    if loaded.endswith(TRUNCATION_MARK):
        return loaded[: -len(TRUNCATION_MARK)].rstrip()
    return loaded


def _stub_llm_factory(payload):
    """构造返回固定 JSON 的桩 LLM（callable(sys, user) -> str）。"""
    def _stub(sys_prompt: str, user_prompt: str) -> str:
        return json.dumps(payload, ensure_ascii=False)
    return _stub


class LoadingConsistencyTests(unittest.TestCase):
    """A. 装载一致性：章节内容必须逐字来自根部文件，截断落在行边界。"""

    def setUp(self):
        reset_knowledge_cache()
        self.addCleanup(reset_knowledge_cache)

    def test_all_sixteen_sections_are_prefixes_of_their_root_documents(self):
        # 场景：16 个章节逐一装载，产出必须是根部文件的前缀（截断）或全文——
        # 任何一字之差都意味着技能包私藏了副本、违反唯一事实源原则。
        self.assertEqual(len(SECTION_FILES), 16)
        root = knowledge_root()
        for key, filename in SECTION_FILES.items():
            source = (root / filename).read_text(encoding="utf-8")
            loaded = load_section(key)
            self.assertTrue(loaded, f"章节 {key} 装载为空")
            body = _strip_mark(loaded)
            self.assertTrue(source.startswith(body),
                            f"章节 {key} 的输出不是根部文件 {filename} 的前缀")
            budget = SECTION_BUDGETS[key]
            if budget > 0:
                # 截断标记长度计入预算：实注字符数绝不超过登记预算
                self.assertLessEqual(len(loaded), budget,
                                     f"章节 {key} 超出预算 {budget}")

    def test_budget_truncation_lands_on_a_line_boundary(self):
        # 场景：给大文件一个很小的预算，截断必须整行进出——表格绝不留半行。
        filename = SECTION_FILES["director-shot-guide"]
        source = (knowledge_root() / filename).read_text(encoding="utf-8")
        self.assertGreater(len(source), 500)

        loaded = load_section("director-shot-guide", budget=500)

        self.assertTrue(loaded.endswith(TRUNCATION_MARK))
        body = _strip_mark(loaded)
        body_lines = body.split("\n")
        source_lines = source.split("\n")
        # 前 n-1 行逐字相同，最后一行必须是源文件里一整行（允许行尾空白被 rstrip）
        self.assertEqual(body_lines[:-1], source_lines[: len(body_lines) - 1])
        self.assertEqual(body_lines[-1], source_lines[len(body_lines) - 1].rstrip())

    def test_zero_budget_returns_the_full_document(self):
        # 场景：visual-style 登记预算为 0（全文读入，阶段 5 自行切片）。
        filename = SECTION_FILES["visual-style"]
        source = (knowledge_root() / filename).read_text(encoding="utf-8")

        self.assertEqual(load_section("visual-style"), source)

    def test_unknown_section_key_degrades_to_empty_string(self):
        # 场景：未知章节键降级为空串（fail-soft），绝不抛异常阻塞流水线。
        self.assertEqual(load_section("no-such-section"), "")

    def test_drama_prompt_root_env_redirects_loading(self):
        # 场景：部署把提示词放在别处时用 DRAMA_PROMPT_ROOT 重定向，
        # 装载器必须与 read_md_file 同源解析该环境变量。
        original = os.environ.get("DRAMA_PROMPT_ROOT")
        with tempfile.TemporaryDirectory() as tmp:
            fake = "# 假题材总结\n仅用于验证 DRAMA_PROMPT_ROOT 重定向。\n"
            (Path(tmp) / SECTION_FILES["genre-summary"]).write_text(fake, encoding="utf-8")
            os.environ["DRAMA_PROMPT_ROOT"] = tmp
            reset_knowledge_cache()
            try:
                self.assertEqual(load_section("genre-summary"), fake)
            finally:
                if original is None:
                    os.environ.pop("DRAMA_PROMPT_ROOT", None)
                else:
                    os.environ["DRAMA_PROMPT_ROOT"] = original
                reset_knowledge_cache()

    def test_load_stage_sections_follows_the_consumption_matrix(self):
        # 场景：按阶段批量装载必须与消费矩阵逐键对齐（阶段 4 是最重的一档）。
        loaded = load_stage_sections(4)

        self.assertEqual(tuple(loaded.keys()), STAGE_SECTIONS[4])
        for key, text in loaded.items():
            self.assertTrue(text, f"阶段 4 的章节 {key} 装载为空")


class RegistryDiscoveryTests(unittest.TestCase):
    """B. 注册发现：SkillRegistry 必须能自动发现本技能包。"""

    def test_registry_discovers_production_knowledge_master(self):
        # 场景：SkillRegistry 扫描 skills/ 目录时通过 SKILL.md frontmatter 发现技能。
        registry = SkillRegistry([SKILLS_ROOT])

        names = {item.name for item in registry.list()}

        self.assertIn("production-knowledge-master", names)

    def test_front_matter_name_and_description_parse_correctly(self):
        # 场景：frontmatter 的 name/description 必须完整解析（description 不能是空或裸符号）。
        registry = SkillRegistry([SKILLS_ROOT])

        skill = registry.get("production-knowledge-master")

        self.assertEqual(skill.name, "production-knowledge-master")
        self.assertGreater(len(skill.description), 20)
        self.assertIn("知识路由", skill.description)


class EvolutionLifecycleTests(unittest.TestCase):
    """C. 进化生命周期：harvest → 去重强化 → 晋升 → 淘汰 → 注入，全程 tmp 重定向。"""

    def setUp(self):
        # 把教训库与审计日志重定向到临时目录，绝不污染真实 learned/。
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig_lessons = knowledge_evolution.LESSONS_PATH
        self._orig_log = knowledge_evolution.LOG_PATH
        self._orig_archive = knowledge_evolution.ARCHIVE_PATH
        knowledge_evolution.LESSONS_PATH = tmp / "lessons.jsonl"
        knowledge_evolution.LOG_PATH = tmp / "evolution_log.jsonl"
        knowledge_evolution.ARCHIVE_PATH = tmp / "lessons_archive.jsonl"
        self.addCleanup(self._restore)

    def _restore(self):
        knowledge_evolution.LESSONS_PATH = self._orig_lessons
        knowledge_evolution.LOG_PATH = self._orig_log
        knowledge_evolution.ARCHIVE_PATH = self._orig_archive
        self._tmp.cleanup()

    @staticmethod
    def _two_lesson_llm():
        return _stub_llm_factory([
            {"rule": "武打镜头必须写明起幅与落幅", "evidence": "QC 报告：镜头 12 缺少落幅描述"},
            {"rule": "角色服装颜色跨镜头保持一致", "evidence": "QC 报告：第 3 集外套换色"},
        ])

    def test_harvest_writes_candidates_from_stub_llm(self):
        # 场景：桩 LLM 蒸馏出两条教训 → 落库为 candidate 状态。
        touched = knowledge_evolution.harvest_from_qc(
            4, "镜头 12 缺少落幅；第 3 集外套换色。", "task-001", llm=self._two_lesson_llm())

        self.assertEqual(len(touched), 2)
        stored = knowledge_evolution._load_lessons()
        self.assertEqual(len(stored), 2)
        for record in stored:
            self.assertEqual(record.status, "candidate")
            self.assertEqual(record.stage, 4)
            self.assertEqual(record.hits, 1)
            self.assertEqual(record.trigger, "qc_finding")

    def test_duplicate_rule_reinforces_instead_of_appending(self):
        # 场景：同义规则（只差标点空白）第二次 harvest → hits=2、score 上调，不新增条目。
        knowledge_evolution.harvest_from_qc(4, "报告一", "task-001", llm=self._two_lesson_llm())
        rephrased = _stub_llm_factory([
            {"rule": "武打镜头，必须写明起幅与落幅。", "evidence": "又一次缺少落幅"},
        ])

        touched = knowledge_evolution.harvest_from_qc(4, "报告二", "task-002", llm=rephrased)

        stored = knowledge_evolution._load_lessons()
        self.assertEqual(len(stored), 2, "同义规则不得新增条目")
        self.assertEqual(len(touched), 1)
        self.assertEqual(touched[0].hits, 2)
        self.assertGreater(touched[0].score, 1.0)

    def test_same_task_rerun_never_inflates_hits(self):
        # 场景：同一 task_id 重跑质检 → 幂等跳过强化（hits/score 不变），
        # 否则单任务重跑两次即可越过 PROMOTE_HITS 晋升线、把候选虚假刷成 active。
        knowledge_evolution.harvest_from_qc(4, "报告", "task-001", llm=self._two_lesson_llm())
        knowledge_evolution.harvest_from_qc(4, "报告重跑", "task-001", llm=self._two_lesson_llm())

        stored = knowledge_evolution._load_lessons()
        self.assertEqual(len(stored), 2)
        for record in stored:
            self.assertEqual(record.hits, 1, "同任务重跑不得刷 hits")
            self.assertEqual(record.score, 1.0, "同任务重跑不得刷 score")
            self.assertEqual(record.seen_task_ids, ["task-001"])
        result = knowledge_evolution.promote_and_prune()
        self.assertEqual(result["promoted"], [], "单任务重跑不得触发晋升")

    def test_rehit_retired_lesson_revives_as_candidate(self):
        # 场景：retired 教训在新任务再次命中 → 回置 candidate 重新竞争晋升，
        # 否则 retired 记录吸走后续命中、复发的失败模式被永久静音。
        now = knowledge_evolution._now()
        knowledge_evolution._atomic_write_lessons([
            knowledge_evolution.LessonRecord(
                id="Lret", stage=4, rule="武打镜头必须写明起幅与落幅",
                trigger="qc_finding", evidence="旧证据", score=1.0, hits=2,
                status="retired", created_at=now, updated_at=now,
                seen_task_ids=["task-old"]),
        ])

        touched = knowledge_evolution.harvest_from_qc(
            4, "又一次缺少落幅", "task-new", llm=self._two_lesson_llm())

        revived = next(r for r in knowledge_evolution._load_lessons() if r.id == "Lret")
        self.assertEqual(revived.status, "candidate", "复发模式必须复活为 candidate")
        self.assertEqual(revived.hits, 3, "复活保留历史命中数")
        self.assertIn("Lret", [r.id for r in touched])

    def test_untrusted_llm_output_is_capped(self):
        # 场景：LLM 蒸馏输出不可信——单次 50 条候选、10 万字符 evidence，
        # 入库必须限流（≤ MAX_CANDIDATES_PER_HARVEST 条）且 evidence 硬截断（≤ 500 字符）。
        flood = _stub_llm_factory([
            {"rule": f"完全互不相同的教训条目甲乙丙丁{i}号规则用于规避三元组去重{i}" * 2,
             "evidence": "证" * 100_000}
            for i in range(50)
        ])

        knowledge_evolution.harvest_from_qc(2, "报告", "task-flood", llm=flood)

        stored = knowledge_evolution._load_lessons()
        self.assertLessEqual(
            len(stored), knowledge_evolution.MAX_CANDIDATES_PER_HARVEST,
            "单次 harvest 入库条数必须限流")
        for record in stored:
            self.assertLessEqual(len(record.evidence),
                                 knowledge_evolution.MAX_EVIDENCE_CHARS,
                                 "evidence 必须硬截断")

    def test_prune_archives_zombie_candidates_and_retired_overflow(self):
        # 场景：教训库绝不只进不出——过期僵尸候选（超 TTL 且 hits 不足）与
        # 超出每阶段上限的最旧 retired 记录滚动归档：移出热文件、写入归档文件保住审计轨迹。
        from datetime import datetime, timedelta, timezone
        stale_ts = (datetime.now(timezone.utc)
                    - timedelta(days=knowledge_evolution.CANDIDATE_TTL_DAYS + 5)).isoformat()
        records = [
            knowledge_evolution.LessonRecord(
                id="Lzombie", stage=1, rule="三十五天没人再命中的僵尸候选",
                trigger="qc_finding", evidence="QC", score=1.0, hits=1,
                status="candidate", created_at=stale_ts, updated_at=stale_ts),
        ]
        records += [
            knowledge_evolution.LessonRecord(
                id=f"Lr{i:03d}", stage=1, rule=f"退休记录{i}：保持转场节奏统一",
                trigger="manual", evidence="人工注入", score=1.0, hits=3,
                status="retired", created_at=stale_ts,
                updated_at=(datetime.now(timezone.utc) - timedelta(days=i)).isoformat())
            for i in range(knowledge_evolution.MAX_RETIRED_PER_STAGE + 3)
        ]
        knowledge_evolution._atomic_write_lessons(records)

        result = knowledge_evolution.promote_and_prune()

        remaining = knowledge_evolution._load_lessons()
        remaining_ids = {r.id for r in remaining}
        self.assertNotIn("Lzombie", remaining_ids, "过期僵尸候选必须移出热文件")
        self.assertEqual(
            sum(1 for r in remaining if r.status == "retired"),
            knowledge_evolution.MAX_RETIRED_PER_STAGE,
            "retired 热文件条数必须回落到每阶段上限")
        self.assertEqual(len(result["archived"]), 4, "1 条僵尸候选 + 3 条超量 retired")
        archive_lines = knowledge_evolution.ARCHIVE_PATH.read_text(
            encoding="utf-8").strip().splitlines()
        self.assertEqual(len(archive_lines), 4, "归档文件必须逐条保住审计轨迹")

    def test_candidate_with_two_hits_is_promoted_to_active(self):
        # 场景：候选教训命中 ≥2 次后 promote_and_prune 晋升为 active。
        knowledge_evolution.harvest_from_qc(4, "报告一", "task-001", llm=self._two_lesson_llm())
        knowledge_evolution.harvest_from_qc(4, "报告二", "task-002", llm=self._two_lesson_llm())

        result = knowledge_evolution.promote_and_prune()

        self.assertEqual(len(result["promoted"]), 2)
        stored = knowledge_evolution._load_lessons()
        self.assertTrue(all(r.status == "active" for r in stored))

    def test_overflowing_actives_retire_the_lowest_score(self):
        # 场景：某阶段塞 13 条 active → 分数最低者被 retired，active 恰好 12，
        # 且退休只改状态不删除（审计需要完整轨迹）。
        now = knowledge_evolution._now()
        records = [
            knowledge_evolution.LessonRecord(
                id=f"L{i:03d}", stage=6, rule=f"规则编号{i}：保持镜头节奏统一",
                trigger="manual", evidence="人工注入", score=float(i + 1), hits=3,
                status="active", created_at=now, updated_at=now)
            for i in range(13)
        ]
        knowledge_evolution._atomic_write_lessons(records)

        result = knowledge_evolution.promote_and_prune()

        self.assertEqual(result["retired"], ["L000"], "应退休分数最低的 L000")
        stored = knowledge_evolution._load_lessons()
        self.assertEqual(len(stored), 13, "退休不是删除")
        self.assertEqual(sum(1 for r in stored if r.status == "active"), 12)
        self.assertEqual(
            [r.id for r in stored if r.status == "retired"], ["L000"])

    def test_llm_failure_is_fail_soft(self):
        # 场景：LLM 抛异常 / 未注入 LLM → 返回 [] 且不抛，绝不阻塞流水线。
        def broken_llm(sys_prompt, user_prompt):
            raise RuntimeError("gateway 超时")

        self.assertEqual(
            knowledge_evolution.harvest_from_qc(4, "任意报告", "task-x", llm=broken_llm), [])
        self.assertEqual(
            knowledge_evolution.harvest_from_qc(4, "任意报告", "task-x", llm=None), [])
        self.assertFalse(knowledge_evolution.LESSONS_PATH.exists(), "失败路径不应落库")

    def test_corrupted_jsonl_lines_are_skipped(self):
        # 场景：教训库混入损坏行 → 跳过不抛，合法行照常读出。
        now = knowledge_evolution._now()
        good = knowledge_evolution.LessonRecord(
            id="Lgood", stage=2, rule="台词标注语速与情绪", trigger="manual",
            evidence="人工注入", score=2.0, hits=3, status="active",
            created_at=now, updated_at=now)
        knowledge_evolution.LESSONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        knowledge_evolution.LESSONS_PATH.write_text(
            "这不是 JSON\n" + good.model_dump_json() + "\n{\"半截对象\": 1\n",
            encoding="utf-8")

        lessons = knowledge_evolution.active_lessons(2)

        self.assertEqual([r.id for r in lessons], ["Lgood"])

    def test_active_lessons_sorted_by_score_times_hits(self):
        # 场景：注入排序按 score*hits 降序——命中多的老教训优先于高分新教训。
        now = knowledge_evolution._now()
        specs = [("La", 2.0, 1), ("Lb", 1.0, 5), ("Lc", 3.0, 1)]  # 积分：2 / 5 / 3
        records = [
            knowledge_evolution.LessonRecord(
                id=lesson_id, stage=8, rule=f"{lesson_id} 高光片段先立冲突再立反转",
                trigger="manual", evidence="人工注入", score=score, hits=hits,
                status="active", created_at=now, updated_at=now)
            for lesson_id, score, hits in specs
        ]
        knowledge_evolution._atomic_write_lessons(records)

        ordered = [r.id for r in knowledge_evolution.active_lessons(8)]

        self.assertEqual(ordered, ["Lb", "Lc", "La"])

    def test_stage_lessons_block_carries_header_and_respects_budget(self):
        # 场景：stage_lessons_block 组装出「历史生产教训」块且不超预算。
        now = knowledge_evolution._now()
        records = [
            knowledge_evolution.LessonRecord(
                id=f"Ls{i}", stage=2, rule=f"编剧教训{i}：每集结尾必须留钩子",
                trigger="qc_finding", evidence="QC", score=1.0 + i, hits=2,
                status="active", created_at=now, updated_at=now)
            for i in range(5)
        ]
        knowledge_evolution._atomic_write_lessons(records)

        block = stage_lessons_block(2, budget=900)

        self.assertIn("历史生产教训", block)
        self.assertIn("每集结尾必须留钩子", block)
        self.assertLessEqual(len(block), 900)

    def test_stage_lessons_block_is_empty_without_active_lessons(self):
        # 场景：空库（文件不存在视为空库）→ 教训块为空串，不给提示词添噪声。
        self.assertEqual(stage_lessons_block(3), "")


class DependencyDirectionTests(unittest.TestCase):
    """D. 单向依赖：进化引擎绝不 import 装载器（装载器 → 进化引擎单向）。"""

    def test_evolution_engine_never_imports_the_loader(self):
        source = Path(knowledge_evolution.__file__).read_text(encoding="utf-8")
        # 逐行检查 import 语句，避免误伤注释里对模块名的提及
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                self.assertNotIn("production_knowledge", stripped,
                                 f"进化引擎不得 import 装载器：{stripped}")


class ContentParityTests(unittest.TestCase):
    """E. 内容对等回归：load_section 与 read_md_file 在截断长度内逐字相同。"""

    def setUp(self):
        reset_knowledge_cache()
        self.addCleanup(reset_knowledge_cache)
        # read_md_file 不依赖任何实例状态，绕过 __init__ 避免连接任务库/网关
        self.service = DramaService.__new__(DramaService)

    def test_full_text_section_matches_read_md_file_exactly(self):
        # 场景：阶段 2 的黄金叙事结构现状是全文读入（budget=0），必须与旧管道逐字相同。
        legacy = self.service.read_md_file(SECTION_FILES["golden-narrative"])

        self.assertTrue(legacy)
        self.assertEqual(load_section("golden-narrative", budget=0), legacy)

    def test_stage4_director_guide_matches_read_md_file_prefix(self):
        # 场景：阶段 4 的导演分镜指南按 8000 预算截断，截断范围内必须与旧管道逐字相同。
        legacy = self.service.read_md_file(SECTION_FILES["director-shot-guide"])
        body = _strip_mark(load_section("director-shot-guide"))

        self.assertTrue(body)
        self.assertEqual(body, legacy[: len(body)])

    def test_stage8_highlight_guide_matches_read_md_file_prefix(self):
        # 场景：阶段 8 的高光识别方案按 6000 预算截断，截断范围内必须与旧管道逐字相同。
        legacy = self.service.read_md_file(SECTION_FILES["highlight-detection"])
        body = _strip_mark(load_section("highlight-detection"))

        self.assertTrue(body)
        self.assertEqual(body, legacy[: len(body)])


if __name__ == "__main__":
    unittest.main()

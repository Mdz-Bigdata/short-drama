# -*- coding: utf-8 -*-
"""What makes text and image calls shorter without changing what they are asked to make:
smaller reference uploads, corrections instead of rewrites, and reasoning only where it is wanted."""

import base64
import io
import json
import unittest
from unittest.mock import patch

from PIL import Image

from app.core import llm_profile, storyboard_revision
from app.core.model_gateway import ModelGateway
from app.core.reference_fit import compact_image_reference
from app.core.screenwriting.structured_llm import RETRY_HEADER, StructuredOutputError, call_structured
from pydantic import BaseModel


def _data_uri(mode="RGB", size=(900, 1600), fmt="PNG"):
    # Noise compresses badly as PNG, as a rendered sheet does.
    image = Image.effect_noise(size, 40).convert(mode)
    if mode == "RGBA":
        image.putalpha(Image.linear_gradient("L").resize(size))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return f"data:image/{fmt.lower()};base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def _decoded(uri):
    return Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))


class ReferenceCompactionTests(unittest.TestCase):
    def test_a_sheet_goes_out_smaller_at_the_same_size(self):
        original = _data_uri()
        compact = compact_image_reference(original)
        self.assertTrue(compact.startswith("data:image/jpeg;base64,"))
        self.assertLess(len(compact), len(original))
        self.assertEqual(_decoded(compact).size, (900, 1600))

    def test_only_the_long_side_above_the_ceiling_is_shrunk(self):
        compact = compact_image_reference(_data_uri(size=(3000, 1500)))
        self.assertEqual(_decoded(compact).size, (2048, 1024))

    def test_transparency_is_kept(self):
        original = _data_uri(mode="RGBA")
        self.assertEqual(compact_image_reference(original), original)

    def test_remote_urls_and_unreadable_images_pass_through(self):
        for value in ("https://img.test/a.png", "data:image/png;base64,bm90IGFuIGltYWdl", None):
            self.assertEqual(compact_image_reference(value), value)

    def test_it_can_be_turned_off(self):
        original = _data_uri()
        with patch.dict("os.environ", {"IMAGE_REFERENCE_COMPACT": "0"}):
            self.assertEqual(compact_image_reference(original), original)


class RevisionContextTests(unittest.TestCase):
    TABLE = "说明文字\n| 镜号 | 景别 |\n| 1 | 中景 |"

    def test_a_revision_works_on_the_table_it_is_correcting(self):
        note = storyboard_revision.revision_note(["第1镜运镜对冲"], self.TABLE)
        self.assertIn("【上一版分镜表】\n| 镜号 | 景别 |\n| 1 | 中景 |", note)
        self.assertNotIn("说明文字", note)
        self.assertIn("第1镜运镜对冲", note)

    def test_a_rejection_shows_the_table_too_when_there_is_one(self):
        self.assertIn("【上一版分镜表】", storyboard_revision.rejection_note("占位内容", self.TABLE))
        self.assertNotIn("【上一版分镜表】", storyboard_revision.rejection_note("没有表格", "抱歉，我无法完成"))

    def test_an_oversized_reply_is_left_out_rather_than_cut(self):
        huge = "\n".join(f"| {index} | 中景 |" for index in range(5000))
        self.assertNotIn("【上一版分镜表】", storyboard_revision.revision_note(["x"], huge))


class _Shot(BaseModel):
    title: str
    count: int = 0


class StructuredRetryTests(unittest.TestCase):
    def _run(self, replies, validators=()):
        prompts = []

        def caller(system, user, max_tokens):
            prompts.append(user)
            return replies[len(prompts) - 1]

        result = call_structured(
            caller, system_prompt="s", user_prompt="写", schema=_Shot, max_tokens=2000, attempts=3, validators=validators,
        )
        return result, prompts

    def test_a_rejected_object_comes_back_with_the_reasons(self):
        first = json.dumps({"title": "旧", "count": 1}, ensure_ascii=False)
        second = json.dumps({"title": "新", "count": 1}, ensure_ascii=False)
        result, prompts = self._run(
            [first, second], validators=[lambda data: ["标题不能是旧"] if data["title"] == "旧" else []],
        )
        self.assertEqual(result.data["title"], "新")
        self.assertNotIn("上一轮输出", prompts[0])
        self.assertIn(f"【上一轮输出】（只改下面指出的问题，其余内容原样保留）\n{first}", prompts[1])
        self.assertLess(prompts[1].index("上一轮输出"), prompts[1].index(RETRY_HEADER))
        self.assertIn("标题不能是旧", prompts[1])

    def test_only_the_last_rejection_is_carried(self):
        replies = [json.dumps({"title": name}, ensure_ascii=False) for name in ("甲", "乙", "丙")]
        result, prompts = self._run(replies, validators=[lambda data: [] if data["title"] == "丙" else ["再改"]])
        self.assertEqual(result.attempts, 3)
        self.assertIn('"乙"', prompts[2])
        self.assertNotIn('"甲"', prompts[2])

    def test_an_answer_that_did_not_parse_is_not_shown_again(self):
        _, prompts = self._run(["这不是 JSON", json.dumps({"title": "好"}, ensure_ascii=False)])
        self.assertNotIn("【上一轮输出】", prompts[1])
        self.assertNotIn("这不是 JSON", prompts[1])

    def test_exhausted_retries_still_raise(self):
        with self.assertRaises(StructuredOutputError):
            self._run(['{"title": "甲"}'] * 3, validators=[lambda data: ["不行"]])


class ReasoningFieldTests(unittest.TestCase):
    def setUp(self):
        self.gateway = ModelGateway.__new__(ModelGateway)

    def test_nothing_is_sent_unless_a_stage_asks(self):
        self.assertEqual(self.gateway._reasoning_fields("https://api.deepseek.com"), {})

    def test_deepseek_gets_the_documented_fields(self):
        with llm_profile.reasoning_scope("off"):
            self.assertEqual(self.gateway._reasoning_fields("https://api.deepseek.com/v1"), {"thinking": {"type": "disabled"}})
        with llm_profile.reasoning_scope("low"):
            self.assertEqual(self.gateway._reasoning_fields("https://api.deepseek.com"), {"reasoning_effort": "low"})

    def test_other_hosts_are_not_sent_fields_they_may_refuse(self):
        with llm_profile.reasoning_scope("off"):
            self.assertEqual(self.gateway._reasoning_fields("https://dashscope.aliyuncs.com/compatible-mode/v1"), {})
            self.assertEqual(self.gateway._reasoning_fields("https://deepseek.com.example.org"), {})

    def test_the_level_comes_from_the_environment_and_a_typo_is_ignored(self):
        with patch.dict("os.environ", {"STORYBOARD_TABLE_REASONING": "LOW", "QC_REASONING": "fast"}):
            self.assertEqual(llm_profile.reasoning_from_env("STORYBOARD_TABLE_REASONING"), "low")
            self.assertEqual(llm_profile.reasoning_from_env("QC_REASONING", "off"), "off")
        self.assertIsNone(llm_profile.reasoning_from_env("SCREENWRITING_REASONING_UNSET"))

    def test_the_scope_ends_with_its_block(self):
        with llm_profile.reasoning_scope("max"):
            self.assertEqual(llm_profile.current_reasoning(), "max")
        self.assertIsNone(llm_profile.current_reasoning())

    def test_usage_keeps_reasoning_tokens_when_the_provider_reports_them(self):
        self.gateway._remember_chat_usage("m", "https://api.deepseek.com", {
            "prompt_tokens": 10, "completion_tokens": 30, "completion_tokens_details": {"reasoning_tokens": 20},
        })
        self.assertEqual(self.gateway._take_chat_usage()["reasoning_tokens"], 20)


class QualityCheckTests(unittest.TestCase):
    def test_the_self_check_does_not_reason_and_says_so_to_the_gateway(self):
        from app.service.drama_service import DramaService

        service = DramaService.__new__(DramaService)
        service.gateway = ModelGateway.__new__(ModelGateway)
        seen = []

        def llm(*args, **kwargs):
            seen.append(llm_profile.current_reasoning())
            return "| 检查维面 | 状态 |\n| 一致性 | ✅ |"

        with patch.object(service.gateway, "call_llm", side_effect=llm), \
                patch("app.service.drama_service.knowledge_evolution.harvest_from_qc"), \
                patch("app.service.drama_service.knowledge_evolution.promote_and_prune"):
            report = service.run_real_consistency_check(4, "分镜", {"4": []}, {"llm_model": "m"}, "题")
        self.assertEqual(seen, ["off"])
        self.assertIn("一致性", report)


if __name__ == "__main__":
    unittest.main()


class HandbookAlignmentTests(unittest.TestCase):
    """《视频创作工艺手册》里和项目相反的几条：招牌留着、打戏硬切、风格句不堆废词、参考图写明不采用什么。"""

    def test_signage_stays_and_only_overlays_are_forbidden(self):
        from app.core import agent_council, style_packs
        from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt

        shot = ShotPromptInput(
            shot_index=1, duration_seconds=8, shot_size="中景", camera_movement="固定", subject_action="沈知微抬头看匾额",
            scene="正堂", blocking="沈知微居中", start_state="站定", end_state="看着匾额", characters=["沈知微"], native_audio=True,
        )
        text = compile_shot_prompt(style_packs.get_pack(style_packs.DEFAULT_PACK_ID), shot, model="seedance2.0").text
        self.assertIn("匾额、招牌、对联、标语保持原样", text)
        self.assertIn("严禁新增叠加的字幕", text)
        self.assertNotRegex(text, r"(?<![a-z])text(?![a-z])")
        self.assertNotRegex(agent_council.NEGATIVE_MODULE_WORDS["text_watermark"], r"(?<![a-z])text(?![a-z])")
        # The module must still fit the compiled budget behind every other module, or the watermark ban is lost.
        modules = list(agent_council.NEGATIVE_MODULE_WORDS)
        self.assertIn("watermark", agent_council.compile_negative_prompt(modules))

    def test_the_reference_line_says_what_not_to_take(self):
        from app.core.storyboard_scene_context import reference_note

        actor = reference_note(1, {"kind": "actor", "name": "沈知微", "image_url": "a.png"})
        self.assertIn("不采用图中背景、版式与其他人物", actor)
        self.assertIn("脸型、发型、体型与服装", actor)
        prop = reference_note(2, {"kind": "prop", "name": "录音笔", "image_url": "p.png"})
        self.assertIn("不采用图中背景与人物", prop)
        self.assertTrue(actor.endswith("不是额外剧情或额外人物"))

    def test_the_tone_line_carries_no_empty_grandeur(self):
        from app.core import style_packs

        for pack in style_packs.list_packs():
            tone = pack.tone_default if hasattr(pack, "tone_default") else ""
            for word in ("史诗", "震撼", "电影级", "8k", "masterpiece"):
                self.assertNotIn(word, str(tone), pack.id)


class StageFourWritingRulesTests(unittest.TestCase):
    """分镜师的系统提示词里带着《视频创作工艺手册》的写法硬规则：这些规则不走技能章节，不会被预算截掉。"""

    def test_the_table_writer_is_told_the_action_formula_weight_light_and_banned_words(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from app.repository.task_repo import TaskRepository
        from app.service.drama_service import DramaService
        from tests.test_storyboard_scene_parallel import _Providers, _task

        systems: list[str] = []
        providers = _Providers(delay=0)

        def llm(model, system, user, *args, **kwargs):
            systems.append(system)
            return providers.llm(model, system, user, *args, **kwargs)

        task = _task("rules-1")
        task["assets"]["2_breakdown"]["scenes"] = task["assets"]["2_breakdown"]["scenes"][:1]
        with tempfile.TemporaryDirectory() as temp:
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            service.repo.save_task("rules-1", task)
            with patch.object(service.gateway, "call_llm", side_effect=llm), \
                    patch.object(service.gateway, "generate_image", side_effect=providers.image), \
                    patch.object(service.gateway, "validate_image_request", create=True), \
                    patch("app.service.drama_service.load_storyboard_elements", return_value=[]), \
                    patch("app.service.drama_service.persist_storyboard_frame", return_value=None), \
                    patch("app.service.drama_service.compose_nine_grid", lambda sources, path: path), \
                    patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
                service._execute_stage_blocking("rules-1", 4, _claimed_task=task)
        self.assertTrue(systems)
        system = systems[0]
        for rule in ("意图 + 具名技法 + 哪只手哪只脚 + 打在哪里", "格挡/闪避/借力/硬吃换击", "代价可见",
                     "前一招的收势就是下一招的起势", "动作飘逸流畅", "连贯不断档", "【重量线索硬要求】", "【光线写法硬要求】", "光源在哪、朝哪打、经过什么", "【措辞禁令】", "史诗感、震撼"):
            self.assertIn(rule, system)


class QualityCheckMemoTests(unittest.TestCase):
    """同一份资产的质检和教训提炼只问一次：阶段重跑时资产没变，就不再花两次调用。"""

    def _service(self, calls):
        from app.service.drama_service import DramaService

        service = DramaService.__new__(DramaService)
        service.gateway = ModelGateway.__new__(ModelGateway)

        def llm(model, system, user, *args, **kwargs):
            calls.append(user[:40])
            return "| 检查维面 | 状态 |\n| 一致性 | ✅ |" if "质检" in system or "核验" in user else ""

        patch.object(service.gateway, "call_llm", side_effect=llm).start()
        self.addCleanup(patch.stopall)
        patch("app.service.drama_service.knowledge_evolution.promote_and_prune").start()
        return service

    def test_the_same_asset_is_checked_once_and_a_changed_asset_again(self):
        calls: list[str] = []
        service = self._service(calls)
        task = {"task_id": "qc-memo", "assets": {"4": [{"desc": "第一版"}]}}
        first = service.run_real_consistency_check(4, "分镜", task["assets"], {"llm_model": "m"}, "题", task_id="qc-memo", task=task)
        self.assertEqual(len(calls), 2, "the check and the lesson harvest")
        again = service.run_real_consistency_check(4, "分镜", task["assets"], {"llm_model": "m"}, "题", task_id="qc-memo", task=task)
        self.assertEqual(len(calls), 2, "nothing asked again")
        self.assertEqual(again, first)
        task["assets"]["4"] = [{"desc": "第二版"}]
        service.run_real_consistency_check(4, "分镜", task["assets"], {"llm_model": "m"}, "题", task_id="qc-memo", task=task)
        # The check is asked again; the stub's report reads the same, so the lessons it yields are not.
        self.assertEqual(len(calls), 3, "a changed asset is a new question")

    def test_without_a_task_the_check_is_simply_run(self):
        calls: list[str] = []
        service = self._service(calls)
        service.run_real_consistency_check(4, "分镜", {"4": []}, {"llm_model": "m"}, "题")
        service.run_real_consistency_check(4, "分镜", {"4": []}, {"llm_model": "m"}, "题")
        self.assertEqual(len(calls), 4)

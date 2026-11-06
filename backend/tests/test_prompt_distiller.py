# -*- coding: utf-8 -*-
"""MiniMax H3 提示词瘦身：逐字去重 + 文本模型压短；标记与数字一个不少，内容优先、不再逐段裁剪。"""

import unittest
from unittest.mock import patch

from app.core import prompt_budget, prompt_distiller
from app.core.style_packs import DEFAULT_PACK_ID, get_pack
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt

BODY = (
    "画面：真人实拍古装权谋质感，辰时正堂，天光从画面右侧槛窗斜切进来，@[沈知微]垂首端坐在画面左三分之一，"
    "一双粗手自画面右侧入画攥住她的细腕，把拇指往红泥里按，指腹压出湿亮凹痕；前景虚化太师椅椅背遮挡画面左缘，"
    "镜头自前景后缓慢推近，从中远景落到案头中景；机位距@[沈知微]2.9米、机高2.4米，镜头24mm。"
    "表情：眉心骤紧，瞳孔骤缩，唇线抿成一条。落幅：拇指凝在契纸上方半寸，指腹微微发颤。"
)
SHORT = "@[沈知微]垂首端坐画左；粗手自画右入画攥腕按拇指入红泥；前景椅背虚化；缓慢推近至案头中景；机位2.9米、机高2.4米、24mm；眉心紧、瞳孔缩、唇抿；落幅拇指悬契纸半寸微颤"


def _sections(body=BODY):
    return {"style_lock": "[STYLE LOCK] 写实", "locks": "[空间锚]正堂\n[状态锁]@[沈知微]：端坐", "camera": "景别：MS；运镜：推",
            "subject": body, "dialogue": "无台词，人物闭口。", "rules": "【关键约束】\n物理真实", "negatives": "变脸"}


class DedupeTests(unittest.TestCase):
    def test_contract_lines_that_repeat_other_sections_are_removed(self):
        sections = {
            "subject": "画面：她把长剑横举到画面中上部，剑尖斜指画面右上。",
            "camera": "景别：中景起幅，推进至中近景；运镜：缓慢推进",
            "composition": "构图：中景起幅，50mm；@[沈无咎]位于画面中央",
            "motion": "镜头1，严格依据对应分镜契约生成连续运镜视频。机位：平视略低，微荷兰角约5度；景别：中景起幅，推进至中近景；"
                      "动作：她把长剑横举到画面中上部，剑尖斜指画面右上。",
        }
        out = prompt_distiller.dedupe(sections)
        self.assertIn("机位：平视略低，微荷兰角约5度", out["motion"])
        self.assertNotIn("剑尖斜指画面右上", out["motion"])
        self.assertNotIn("推进至中近景", out["motion"])
        self.assertEqual(out["subject"], sections["subject"])

    def test_negatives_already_in_the_rules_and_english_glosses_go(self):
        sections = {
            "rules": "【关键约束】\n风格铁律：NOT 3D rendered + NOT CGI。\n同一人物同一张脸同一服装 (same character, same outfit)；(规避：jump cut, axis flip)",
            "negatives": "NOT 3D rendered + NOT CGI + NOT cartoon + 无字幕",
        }
        out = prompt_distiller.dedupe(sections)
        self.assertEqual(out["negatives"], "NOT cartoon + 无字幕")
        self.assertNotIn("same character", out["rules"])
        self.assertIn("jump cut, axis flip", out["rules"], "带中文的括注是内容，不删")


class PlanAndCheckTests(unittest.TestCase):
    def test_a_body_over_budget_is_planned_against_the_room_the_locks_leave(self):
        plan = prompt_distiller.plan(_sections(), 200)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.mentions, {"@[沈知微]"})
        self.assertEqual(plan.numbers, {"2.9米", "2.4米", "24mm"})
        self.assertEqual(set(prompt_distiller.keep_list(plan).split("、")), {"@[沈知微]", "2.4米", "2.9米", "24mm"})
        self.assertIsNone(prompt_distiller.plan(_sections(), 5000), "预算够就不精炼")
        self.assertIsNone(prompt_distiller.plan(_sections(), 60), "锁定行已占满预算就不精炼")

    def test_the_result_must_keep_every_mention_and_number_and_be_clearly_shorter(self):
        plan = prompt_distiller.plan(_sections(), 200)
        self.assertEqual(prompt_distiller.check(plan, SHORT), "")
        self.assertEqual(prompt_distiller.check(plan, SHORT + "，" + "补充细节" * 10), "", "略超目标也采用：内容优先")
        self.assertIn("丢了数字", prompt_distiller.check(plan, SHORT.replace("24mm", "")))
        self.assertIn("丢了标记", prompt_distiller.check(plan, SHORT.replace("@[沈知微]", "沈知微")))
        self.assertIn("没有明显变短", prompt_distiller.check(plan, BODY[:-4]))
        self.assertIn("不是正文", prompt_distiller.check(plan, "```\n" + SHORT + "\n```"))


class CompressTests(unittest.TestCase):
    def test_a_condensed_prompt_is_never_cut_afterwards(self):
        sections = {**_sections(BODY * 5), "sound": "【声音设计】雨声铺底", "dialogue_notes": "台词表达：压着嗓子"}
        kept, report = prompt_budget.compress(sections, "minimax-h3", distill=lambda s, budget: prompt_distiller.distill_sections(s, budget, rewrite=lambda b, t: SHORT)[0])
        self.assertTrue(report.distilled)
        self.assertEqual((report.dropped, report.trimmed), ([], []))
        self.assertEqual(kept["subject"], SHORT)
        self.assertTrue(report.as_dict()["distilled"])
        still_long = {**_sections(BODY * 5)}
        kept, report = prompt_budget.compress(still_long, "minimax-h3", distill=lambda s, budget: dict(s))
        self.assertTrue(report.distilled)
        self.assertEqual(report.tier, "red")
        self.assertEqual(kept["subject"], BODY * 5, "去重后仍超预算也不裁：内容一个不丢")

    def test_without_a_distiller_the_old_ladder_still_runs(self):
        sections = {**_sections(BODY * 5), "sound": "【声音设计】雨声铺底" * 3}
        kept, report = prompt_budget.compress(sections, "minimax-h3", distill=lambda s, budget: None)
        self.assertFalse(report.distilled)
        self.assertIn("sound", report.dropped)


class CompileTests(unittest.TestCase):
    def test_compile_shot_prompt_passes_the_distiller_through(self):
        calls = []

        def distill(sections, budget):
            calls.append(budget)
            return prompt_distiller.distill_sections(sections, budget, rewrite=lambda body, target: SHORT)[0]

        shot = ShotPromptInput(
            shot_index=1, duration_seconds=8, shot_size="MS", camera_movement="推", subject_action=BODY * 5, scene="正堂",
            blocking="@[沈知微]居中偏左", start_state="端坐", end_state="拇指悬在契纸上方", characters=["沈知微"], cast_refs=["沈知微"],
            sound="雨声铺底", expression="眉心骤紧", composition="左三分线",
        )
        compiled = compile_shot_prompt(get_pack(DEFAULT_PACK_ID), shot, model="minimax-h3", max_duration_seconds=15, distill=distill)
        self.assertEqual(calls, [900])
        self.assertTrue(compiled.pressure.distilled)
        self.assertIn(SHORT, compiled.text)


def _long_shots(count: int) -> list[dict]:
    """画面写得够长的镜头：占位话和重复去掉之后仍超预算，才走得到精炼。"""
    from app.core.shot_motion_contract import ShotMotionContract
    from tests.test_stage_five_queue import _panel, _shot

    shots = []
    for index in range(1, count + 1):
        action = "沈砚推门而入，" + "；".join(f"雨水顺着第{index}镜的第{part}根廊柱往下淌，檐角的灯笼被风吹得一晃一晃" for part in range(1, 6))
        panel = _panel(index).model_copy(update={"subject_action": action})
        contract = ShotMotionContract.from_panel(panel, storyboard_image=f"/media/p{index}.png")
        shots.append({
            **_shot(index), "desc": action,
            "motion_contract": contract.model_dump(mode="json"), "contract_fingerprint": contract.contract_fingerprint,
        })
    return shots


class StageFiveTests(unittest.TestCase):
    def _harness(self):
        from tests.test_stage_five_queue import StageFiveQueueTests

        harness = StageFiveQueueTests("test_shots_are_generated_under_the_video_ceiling_and_the_queue_is_persisted")
        harness.setUp()
        self.addCleanup(harness.temp.cleanup)
        # 这些测试验证中文精炼；H3 官方六段式改写见 tests/test_h3_native.py。
        native_off = patch.dict("os.environ", {"H3_NATIVE_PROMPTS": "0"})
        native_off.start()
        self.addCleanup(native_off.stop)
        return harness

    def test_a_multi_moment_board_is_condensed_once_with_every_block_kept(self):
        from tests.test_stage_five_queue import _task

        harness = self._harness()
        task = _task(3)
        task["assets"]["4"] = _long_shots(3)
        task["config"]["video_model"] = "MiniMax-H3"
        task["config"].pop("video_granularity", None)
        seen = []

        def call_llm(model, system, user, *args, **kwargs):
            seen.append(user)
            mentions, numbers = prompt_distiller.invariants(user)
            blocks = [f"【镜头{k}/3｜精炼】沈砚推门；" for k in (1, 2, 3)]
            return "".join(blocks) + "；".join(sorted(mentions) + sorted(numbers))

        tight = (("minimax-h3", 150, 400),)
        with patch.object(harness.service.gateway, "call_llm", side_effect=call_llm), \
             patch("app.core.prompt_budget.MODEL_PROMPT_BUDGETS", tight):
            stored = harness._run(task)
        self.assertEqual(len(seen), 1, "整段一次精炼，不逐镜")
        self.assertEqual(seen[0].count("【镜头"), 3)
        [clip] = stored["assets"]["5"]
        self.assertTrue(clip["prompt_pressure"]["distilled"])
        self.assertEqual(clip["sent_prompt"].count("【镜头"), 3)
        self.assertIn("沈砚推门", clip["sent_prompt"])

    def test_h3_prompts_are_condensed_in_parallel_and_remembered(self):
        from tests.test_stage_five_queue import _task

        harness = self._harness()
        task = _task(3)
        task["assets"]["4"] = _long_shots(3)
        task["config"]["video_model"] = "MiniMax-H3"
        task["config"]["video_granularity"] = "shot"
        seen = []

        def call_llm(model, system, user, *args, **kwargs):
            seen.append((model, system, user))
            mentions, numbers = prompt_distiller.invariants(user)
            return "；".join(sorted(mentions) + sorted(numbers)) + "；沈砚推门而入，缓慢推近，落幅停在门口"

        tight = (("minimax-h3", 150, 400),)
        with patch.object(harness.service.gateway, "call_llm", side_effect=call_llm), \
             patch("app.core.prompt_budget.MODEL_PROMPT_BUDGETS", tight):
            stored = harness._run(task)
        self.assertEqual(len(seen), 3, "三个镜头各精炼一次(并行)")
        self.assertTrue(all("这些必须原样出现" in system for _, system, _ in seen))
        pressures = [clip["prompt_pressure"] for clip in stored["assets"]["5"]]
        self.assertTrue(all(p["distilled"] and not p["dropped"] and not p["trimmed"] for p in pressures))
        self.assertEqual(len(stored["assets"]["5_prompt_cache"]), 3)

        stored["status"] = "running"
        stored["workflow_control"] = {"run_id": "run-2", "active": True, "pause_requested": False}
        for clip in stored["assets"]["5"]:
            clip["stale"] = True
        with patch.object(harness.service.gateway, "call_llm", side_effect=AssertionError("cached")), \
             patch("app.core.prompt_budget.MODEL_PROMPT_BUDGETS", tight):
            again = harness._run(stored)
        self.assertTrue(all(clip["prompt_pressure"]["distilled"] for clip in again["assets"]["5"]))

    def test_a_rejected_condensation_falls_back_to_the_deduplicated_text(self):
        from tests.test_stage_five_queue import _task

        harness = self._harness()
        task = _task(1)
        task["config"]["video_model"] = "MiniMax-H3"
        with patch.object(harness.service.gateway, "call_llm", return_value="太短"), \
             patch("app.core.prompt_budget.MODEL_PROMPT_BUDGETS", (("minimax-h3", 150, 400),)):
            stored = harness._run(task)
        pressure = stored["assets"]["5"][0]["prompt_pressure"]
        self.assertTrue(pressure["distilled"])
        self.assertEqual((pressure["dropped"], pressure["trimmed"]), ([], []))
        self.assertEqual(stored["assets"]["5_prompt_cache"], {})

    def test_other_video_families_are_not_condensed(self):
        from tests.test_stage_five_queue import _task

        harness = self._harness()
        with patch.object(harness.service.gateway, "call_llm", side_effect=AssertionError("not for seedance")), \
             patch("app.core.prompt_budget.MODEL_PROMPT_BUDGETS", (("seedance", 150, 400),)):
            stored = harness._run(_task(1))
        self.assertFalse(stored["assets"]["5"][0]["prompt_pressure"]["distilled"])



class VideoPromptCleanupTests(unittest.TestCase):
    """发给视频模型的提示词里，占位话和重复内容都不留；有信息的内容一个字不少。"""

    def _compile(self, **changes):
        fields = dict(
            shot_index=1, duration_seconds=8, shot_size="中景", camera_movement="缓慢推近", subject_action="沈知微推门而入，雨水顺着门框往下淌",
            scene="正堂", blocking="沈知微居中偏左", start_state="建立空间与人物关系", end_state="人物姿态、视线与道具停在下一镜可以直接承接的状态",
            characters=["沈知微"], cast_refs=["沈知微"], props=["本格无额外道具"], effects=["本格无额外特效"],
            expression="与本镜触发事件对应的可观察微表情与呼吸变化", lighting="继承场景圣经的主光方向、色温、时间和天气，人物脸部保持自然层次",
            dialogue="无", native_audio=True, sound="雨声铺底",
        )
        fields.update(changes)
        return compile_shot_prompt(get_pack(DEFAULT_PACK_ID), ShotPromptInput(**fields), model="seedance2.0", max_duration_seconds=15)

    def test_placeholders_never_reach_the_model(self):
        text = self._compile().text
        for placeholder in ("本格无额外道具", "本格无额外特效", "可观察微表情与呼吸变化", "场景圣经", "建立空间与人物关系", "可以直接承接的状态", "{无}"):
            self.assertNotIn(placeholder, text)

    def test_what_a_table_actually_wrote_stays(self):
        text = self._compile(
            props=["旧铜钥匙"], expression="眉心骤紧", lighting="主光来自画面右侧的火把", end_state="拇指悬在契纸上方", dialogue="沈知微：我不认。",
        ).text
        for written in ("旧铜钥匙", "眉心骤紧", "主光来自画面右侧的火把", "拇指悬在契纸上方", "我不认", "沈知微推门而入"):
            self.assertIn(written, text)

    def test_the_picture_does_not_copy_the_dialogue_column(self):
        text = self._compile(subject_action="沈知微推门而入。原文台词保持不变：沈知微：我不认。", dialogue="沈知微：我不认。").text
        self.assertNotIn("原文台词保持不变", text)
        self.assertEqual(text.count("我不认"), 1)
        self.assertIn("沈知微推门而入", text)

    def test_a_stage_direction_in_the_dialogue_column_is_not_a_line(self):
        for dialogue in ("无", "无；无", "—", "—（承接上一格“落”字，本格不出新台词）", "（无）", "", "  "):
            self.assertTrue(prompt_distiller.is_no_line(dialogue), dialogue)
        for dialogue in ("沈知微：我不认。", "无所谓", "无（冷笑）：滚开"):
            self.assertFalse(prompt_distiller.is_no_line(dialogue), dialogue)

    def test_negatives_already_written_elsewhere_are_not_written_again(self):
        cleaned = prompt_distiller.dedupe({
            "closing": "无字幕；无水印。",
            "rules": "【关键约束】\n风格铁律：NOT CGI。\n(规避：jump cut, axis flip)",
            "negatives": "NOT CGI + 无字幕 + 无水印 + NOT anime + (避免：jump cut, blurry, axis flip, watermark)",
        })
        self.assertEqual(cleaned["negatives"], "NOT anime + (避免：blurry, watermark)")

    def test_the_same_clause_in_the_rules_is_kept_once(self):
        cleaned = prompt_distiller.dedupe({
            "rules": "音色铁律：甲：男声；全片音色、音调与声线不变\n音色铁律：乙：女声；全片音色、音调与声线不变",
        })
        self.assertEqual(cleaned["rules"].count("全片音色、音调与声线不变"), 1)
        self.assertIn("乙：女声", cleaned["rules"])

    def test_later_shots_do_not_repeat_what_an_earlier_shot_wrote(self):
        blocks = prompt_distiller.dedupe_blocks([
            "【镜头1/2｜中景｜推】构图：沈知微位于画面左侧三分之一；画面：她推门。",
            "【镜头2/2｜中景｜推】衔接：匹配剪辑。构图：沈知微位于画面左侧三分之一；画面：她抬眼。台词：沈知微{我不认。}。",
        ])
        self.assertNotIn("三分之一", blocks[1])
        self.assertIn("她抬眼", blocks[1])
        self.assertTrue(blocks[1].startswith("【镜头2/2"))
        same_line = prompt_distiller.dedupe_blocks(["【镜头1/2｜A】台词：甲{走吧走吧走吧。}。", "【镜头2/2｜A】台词：甲{走吧走吧走吧。}。"])
        self.assertIn("走吧", same_line[1])

    def test_the_end_of_a_line_is_never_taken_for_a_repeat(self):
        ending = "}（只有@[甲]、@[乙]说话，按台词顺序轮流开口）"
        blocks = prompt_distiller.dedupe_blocks([
            f"【镜头1/2｜A】台词：@[甲]{{走吧。{ending}",
            f"【镜头2/2｜A】台词：@[乙]{{不走。{ending}",
        ])
        for block in blocks:
            self.assertEqual(block.count("{"), block.count("}"), block)
            self.assertIn("轮流开口", block)

    def test_each_reference_note_stops_repeating_the_same_two_sentences(self):
        prompt = (
            "【参考素材职责】\n参考图1仅锁定数字演员设定集「甲」，不是额外剧情或额外人物；"
            "参考图2仅锁定拍摄场地「乙」的空间布局，图中人物不作参考，不是额外剧情或额外人物。\n\n【结构声明】单镜。"
        )
        collapsed = prompt_distiller.collapse_reference_notes(prompt)
        self.assertEqual(collapsed.count("不是额外剧情或额外人物"), 1)
        self.assertEqual(collapsed.count("不作参考"), 1)
        self.assertIn("参考图1仅锁定数字演员设定集「甲」", collapsed)
        self.assertIn("参考图2仅锁定拍摄场地「乙」的空间布局", collapsed)
        self.assertIn("【结构声明】单镜。", collapsed)


if __name__ == "__main__":
    unittest.main()

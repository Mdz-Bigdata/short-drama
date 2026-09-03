# -*- coding: utf-8 -*-
"""A 30-episode project must produce 30 episodes of screenplay, not 15.

One LLM call caps its own output, so writing a long series in a single call left
the dashboard advertising "总集数 30" over a script that stopped at episode 15.
Generation is batched instead; these tests pin that contract.
"""
import unittest
from typing import Any, Dict, List

from app.core.writer_dashboard import compile_writer_dashboard
from app.service.drama_service import DramaService


def _episode_text(index: int) -> str:
    return (
        f"第{index}集 副标题{index}\n"
        f"场景1：市井长街 黄昏 外景\n镜头：中近景 缓推\n陈九：第{index}集第一场。\n"
        f"场景2：破屋 夜 内景\n镜头：特写 固定\n小六：第{index}集第二场。\n"
    )


class _BatchGateway:
    """Answers each batch request with exactly the episodes it asked for."""

    def __init__(self, *, honour_span: bool = True, cap: int = 0):
        self.calls: List[Dict[str, Any]] = []
        self.honour_span = honour_span
        self.cap = cap

    def call_llm(self, model, system_prompt, user_prompt, title,
                 director_style="", shot_style="", user_instruction="", max_tokens=None):
        self.calls.append({"user_prompt": user_prompt, "max_tokens": max_tokens})
        first, last = self._span(user_prompt)
        if not self.honour_span:
            return _episode_text(first)
        indexes = range(first, last + 1)
        if self.cap:
            indexes = [index for index in indexes if index <= self.cap]
        return "\n".join(_episode_text(index) for index in indexes)

    @staticmethod
    def _span(user_prompt: str):
        import re
        single = re.search(r"【本次只写 第 (\d+) 集】", user_prompt)
        if single:
            return int(single.group(1)), int(single.group(1))
        span = re.search(r"【本次只写 第 (\d+) 集到第 (\d+) 集】", user_prompt)
        return (int(span.group(1)), int(span.group(2))) if span else (1, 1)


class _NullRepo:
    """Progress checkpoints are persisted; the generation contract is what is under test."""

    def save_task(self, task_id, task):
        return task


def _service(gateway) -> DramaService:
    service = DramaService.__new__(DramaService)
    service.gateway = gateway
    service.repo = _NullRepo()
    # 补写轮次之间的退避是真的 time.sleep；测试里记下等了多久而不是真等，
    # 上游全挂的用例才不会把几分钟的重试窗口拖进测试套件。
    service.waits = []
    service._wait_before_repair = service.waits.append
    return service


def _task() -> Dict[str, Any]:
    return {"task_id": "long-form-1", "stage_progress": {"stage": 2, "calls": []}, "assets": {}}


class BatchedScriptGenerationTests(unittest.TestCase):
    def test_thirty_episodes_are_all_written(self):
        gateway = _BatchGateway()
        service = _service(gateway)

        script = service._generate_full_script(
            _task(), {"llm_model": "m"}, "流氓天子", "palace", "cinematic",
            "系统提示", "导演策划", 30, "",
        )

        self.assertEqual(service._script_episode_indexes(script), list(range(1, 31)))
        # Batched, not one giant call.
        self.assertGreater(len(gateway.calls), 1)
        self.assertLessEqual(len(gateway.calls), 30)

    def test_each_batch_is_told_its_own_span_and_gets_a_token_budget(self):
        gateway = _BatchGateway()
        service = _service(gateway)

        service._generate_full_script(
            _task(), {"llm_model": "m"}, "流氓天子", "palace", "cinematic",
            "系统提示", "导演策划", 8, "",
        )

        self.assertTrue(all(call["max_tokens"] for call in gateway.calls))
        self.assertIn("【本次只写 第 1 集到第 4 集】", gateway.calls[0]["user_prompt"])
        self.assertIn("【本次只写 第 5 集到第 8 集】", gateway.calls[1]["user_prompt"])
        # Later batches carry the earlier text so the story stays continuous.
        self.assertIn("前文结尾原文", gateway.calls[1]["user_prompt"])
        self.assertNotIn("前文结尾原文", gateway.calls[0]["user_prompt"])

    def test_episodes_a_batch_skipped_are_written_by_the_repair_round(self):
        # The model ignores the span and returns only the first episode each time.
        gateway = _BatchGateway(honour_span=False)
        service = _service(gateway)

        script = service._generate_full_script(
            _task(), {"llm_model": "m"}, "流氓天子", "palace", "cinematic",
            "系统提示", "导演策划", 6, "",
        )

        self.assertEqual(service._script_episode_indexes(script), [1, 2, 3, 4, 5, 6])

    def test_episodes_are_emitted_in_order_without_duplicates(self):
        service = _service(_BatchGateway())

        script = service._generate_full_script(
            _task(), {"llm_model": "m"}, "流氓天子", "palace", "cinematic",
            "系统提示", "导演策划", 12, "",
        )

        indexes = service._script_episode_indexes(script)
        self.assertEqual(indexes, sorted(indexes))
        self.assertEqual(len(indexes), len(set(indexes)))


class EpisodeSplittingTests(unittest.TestCase):
    def test_arabic_and_chinese_episode_headings_are_both_read(self):
        script = "第1集 市井\n正文\n第十二集 入宫\n正文\n### 第 30 集 结局\n正文"

        self.assertEqual(DramaService._script_episode_indexes(script), [1, 12, 30])

    def test_every_chinese_numeral_up_to_ninety_nine_is_read(self):
        # 九 and 十 are absent from the class's stage-number table; the episode
        # parser must not borrow it, or 第九集 silently becomes episode 0.
        expected = {
            "一": 1, "九": 9, "十": 10, "十一": 11, "十五": 15, "十九": 19,
            "二十": 20, "二十一": 21, "二十九": 29, "三十": 30, "九十九": 99,
        }
        for label, number in expected.items():
            self.assertEqual(DramaService._episode_label_number(label), number, label)

    def test_headings_survive_markdown_and_bracket_decoration(self):
        for line, number in (
            ("第1集 市井", 1),
            ("## 第5集", 5),
            ("**第5集** 副标题", 5),
            ("【第12集】", 12),
            ("### 第 30 集 结局", 30),
            ("  第八集", 8),
            ("第九集 假皇子", 9),
        ):
            self.assertEqual(DramaService._script_episode_indexes(line), [number], line)

    def test_a_split_keeps_each_episode_body_with_its_heading(self):
        episodes = DramaService._split_script_by_episode(_episode_text(1) + _episode_text(2))

        self.assertEqual(sorted(episodes), [1, 2])
        self.assertTrue(episodes[1].startswith("第1集"))
        self.assertIn("第1集第二场", episodes[1])
        self.assertNotIn("第2集", episodes[1])


class ShortScriptIsReportedTests(unittest.TestCase):
    """A screenplay that falls short must say so rather than hide behind the request."""

    def test_the_dashboard_reports_the_scripted_episode_count(self):
        task = {
            "task_id": "long-form-1",
            "config": {"title_suggestion": "流氓天子", "episode_count": 30},
            "assets": {"2": "".join(_episode_text(index) for index in range(1, 16))},
        }

        stats = compile_writer_dashboard(task).stats

        self.assertEqual(stats.total_episodes, 30)
        self.assertEqual(stats.scripted_episodes, 15)

    def test_a_complete_script_reports_matching_counts(self):
        task = {
            "task_id": "long-form-1",
            "config": {"title_suggestion": "流氓天子", "episode_count": 30},
            "assets": {"2": "".join(_episode_text(index) for index in range(1, 31))},
        }

        stats = compile_writer_dashboard(task).stats

        self.assertEqual(stats.total_episodes, 30)
        self.assertEqual(stats.scripted_episodes, 30)
        self.assertEqual(stats.missing_episodes, [])


class ScriptGapsAreNamedTests(unittest.TestCase):
    """「已写 15 / 共 30」只说得出缺几集，说不出缺哪几集。

    用户是自己盯着分镜明细从 E15S06 跳到 E25S01 才发现 16-24 集整段没了。
    断层集号必须由后端报出来，前端才能高亮并一键补写。
    """

    @staticmethod
    def _stats(body, episode_count=30):
        return compile_writer_dashboard({
            "task_id": "long-form-1",
            "config": {"title_suggestion": "流氓天子", "episode_count": episode_count},
            "assets": {"2": "".join(_episode_text(index) for index in body)},
        }).stats

    def test_a_truncated_tail_names_every_missing_episode(self):
        self.assertEqual(self._stats(range(1, 16)).missing_episodes, list(range(16, 31)))

    def test_a_hole_in_the_middle_is_named(self):
        # 正是用户截图里的病：15 集之后直接跳到 25 集。
        stats = self._stats(list(range(1, 16)) + list(range(25, 31)))

        self.assertEqual(stats.missing_episodes, list(range(16, 25)))
        self.assertEqual(stats.scripted_episodes, 21)

    def test_an_uploaded_script_without_episode_headings_reports_no_gaps(self):
        # 分集标题一个都没有时无从判断断层，绝不能把「1..30 全缺」报给前端。
        stats = compile_writer_dashboard({
            "task_id": "long-form-1",
            "config": {"title_suggestion": "流氓天子", "episode_count": 30},
            "assets": {"2": "场景1：长街 黄昏 外景\n陈九：走。"},
        }).stats

        self.assertEqual(stats.missing_episodes, [])

    def test_the_gap_list_agrees_with_the_scripted_count(self):
        stats = self._stats(list(range(1, 16)) + list(range(25, 31)))

        self.assertEqual(
            len(stats.missing_episodes), stats.total_episodes - stats.scripted_episodes,
        )

    def test_the_audit_logs_which_episodes_are_missing_not_only_how_many(self):
        script = "".join(_episode_text(index) for index in list(range(1, 16)) + list(range(25, 31)))

        with self.assertLogs("app.service.drama_service", level="WARNING") as captured:
            DramaService._audit_scripted_episodes(script, 30, "long-form-1")

        self.assertTrue(
            any("16、17" in line and "24" in line for line in captured.output),
            captured.output,
        )


class _BreakdownGateway:
    """Structures whichever episodes a chunk request carries, at shot granularity."""

    def __init__(self):
        self.calls = []

    def call_llm(self, model, system_prompt, user_prompt, title,
                 director_style="", shot_style="", user_instruction="", max_tokens=None):
        import json
        import re

        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        indexes = sorted({int(match) for match in re.findall(r"第(\d+)集", user_prompt)})
        scenes = [
            {
                "scene_id": f"E{index}S{shot:02d}",
                "duration": "12s",
                "content": f"第{index}集第{shot}镜",
                "characters": ["陈九", "小六"],
            }
            for index in indexes
            for shot in (1, 2, 3, 4)
        ]
        payload = {
            "scenes": scenes,
            "timeline": [{"phase": "进展纠葛", "title": f"第{indexes[0]}集节点", "desc": "描述", "points": ["要点"]}],
            "roles": [{"name": "陈九", "position": "男主角"}],
            "relationships": [{"from": "陈九", "to": "小六", "relation": "主仆"}],
        }
        if "overview 字段可以留空" not in system_prompt:
            payload["overview"] = {"synopsis": "陈九从混混变成皇子。", "genre": "古装权谋"}
        return json.dumps(payload, ensure_ascii=False)


class BatchedBreakdownTests(unittest.TestCase):
    """A 30-episode breakdown in one call overflows the JSON and yields nothing."""

    def _breakdown(self, episode_count: int, video_model: str = "seedance2.5"):
        gateway = _BreakdownGateway()
        service = _service(gateway)
        script = "".join(_episode_text(index) for index in range(1, episode_count + 1))
        return gateway, service._extract_script_breakdown(
            {"llm_model": "m", "video_model": video_model},
            "流氓天子", "palace", "cinematic", script,
        )

    def test_a_long_script_is_analysed_in_batches_and_merged(self):
        gateway, breakdown = self._breakdown(20)

        self.assertGreater(len(gateway.calls), 1)
        self.assertEqual(len(breakdown["scenes"]), 20 * 4)
        # Roles and relationships are unioned, not duplicated per batch.
        self.assertEqual(breakdown["roles"], [{"name": "陈九", "position": "男主角"}])
        self.assertEqual(len(breakdown["relationships"]), 1)

    def test_the_overview_is_written_once_from_the_opening_batch(self):
        gateway, breakdown = self._breakdown(20)

        self.assertEqual(breakdown["overview"]["genre"], "古装权谋")
        blanked = [call for call in gateway.calls if "overview 字段可以留空" in call["system_prompt"]]
        self.assertEqual(len(blanked), len(gateway.calls) - 1)

    def test_a_short_script_still_takes_a_single_call(self):
        gateway, breakdown = self._breakdown(3)

        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(len(breakdown["scenes"]), 12)

    def test_every_episode_is_cut_into_several_shots(self):
        _, breakdown = self._breakdown(12)

        by_episode = {}
        for scene in breakdown["scenes"]:
            episode = scene["scene_id"].split("S")[0]
            by_episode.setdefault(episode, []).append(scene)
        self.assertEqual(len(by_episode), 12)
        for episode, shots in by_episode.items():
            self.assertGreater(len(shots), 1, f"{episode} 只有一个镜头")

    def test_the_contract_leaves_the_split_to_the_model_but_caps_the_clip(self):
        gateway, _ = self._breakdown(3, video_model="seedance2.5")

        contract = gateway.calls[0]["system_prompt"]
        self.assertIn("镜头级", contract)
        self.assertIn("由你根据戏剧节奏", contract)
        self.assertIn("不得超过 30 秒", contract)
        # No fixed shot count is dictated to the model.
        self.assertNotIn("4-10 个镜头", contract)

    def test_the_cap_in_the_contract_follows_the_selected_video_model(self):
        for model, cap in (("seedance2.0", 15), ("seedance2.5", 30), ("MiniMax-H3", 15)):
            gateway, _ = self._breakdown(3, video_model=model)
            self.assertIn(f"不得超过 {cap} 秒", gateway.calls[0]["system_prompt"], model)
            self.assertIn(model, gateway.calls[0]["system_prompt"], model)


class _FlakyBreakdownGateway(_BreakdownGateway):
    """A structuring gateway whose calls fail for a chosen span of episodes.

    ``mode="raise"`` is a provider error; ``mode="garbage"`` is the likelier one -
    a 200 response whose body is not the requested JSON.
    """

    def __init__(self, fail=(), mode="raise", relabel=None):
        super().__init__()
        self.fail = set(fail)
        self.mode = mode
        self.relabel = relabel or {}

    def call_llm(self, model, system_prompt, user_prompt, title,
                 director_style="", shot_style="", user_instruction="", max_tokens=None):
        import json
        import re

        span = re.search(r"以上是第 (\d+) 集到第 (\d+) 集", user_prompt)
        first, last = (int(span.group(1)), int(span.group(2))) if span else (1, 1)
        if any(index in self.fail for index in range(first, last + 1)):
            self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
            if self.mode == "raise":
                raise RuntimeError("upstream 500")
            return "抱歉，我无法完成这个请求。"
        answer = super().call_llm(model, system_prompt, user_prompt, title,
                                  director_style, shot_style, user_instruction, max_tokens)
        offset = self.relabel.get(first)
        if offset:
            payload = json.loads(answer)
            for scene in payload["scenes"]:
                episode, shot = scene["scene_id"].split("S")
                scene["scene_id"] = f"E{int(episode[1:]) + offset}S{shot}"
            answer = json.dumps(payload, ensure_ascii=False)
        return answer


def _episodes_covered(breakdown):
    import re

    return sorted({
        int(re.match(r"E(\d+)S", scene["scene_id"]).group(1))
        for scene in breakdown["scenes"]
    })


class ScriptBatchFailureTests(unittest.TestCase):
    """One failing batch may cost its own episodes - never the whole screenplay."""

    class _FailingGateway(_BatchGateway):
        def __init__(self, fail):
            super().__init__()
            self.fail = set(fail)

        def call_llm(self, model, system_prompt, user_prompt, title,
                     director_style="", shot_style="", user_instruction="", max_tokens=None):
            first, last = self._span(user_prompt)
            if any(index in self.fail for index in range(first, last + 1)):
                self.calls.append({"user_prompt": user_prompt, "max_tokens": max_tokens})
                raise RuntimeError("upstream 503")
            return super().call_llm(model, system_prompt, user_prompt, title,
                                    director_style, shot_style, user_instruction, max_tokens)

    def _write(self, gateway, ep_count=30, service=None):
        return (service or _service(gateway))._generate_full_script(
            _task(), {"llm_model": "m"}, "流氓天子", "palace", "cinematic",
            "系统提示", "导演策划", ep_count, "",
        )

    def test_a_raising_batch_does_not_throw_away_the_episodes_that_worked(self):
        # Before: one 503 anywhere aborted stage 2 with zero episodes written.
        script = self._write(self._FailingGateway(range(1, 5)))

        self.assertEqual(_service(_BatchGateway())._script_episode_indexes(script), list(range(5, 31)))

    def test_a_failing_tail_batch_leaves_the_earlier_episodes_intact(self):
        script = self._write(self._FailingGateway(range(27, 31)))

        self.assertEqual(_service(_BatchGateway())._script_episode_indexes(script), list(range(1, 27)))

    def test_a_run_where_every_batch_fails_raises_rather_than_returning_nothing(self):
        # An empty screenplay must fail the stage loudly, not flow on downstream.
        with self.assertRaises(RuntimeError):
            self._write(self._FailingGateway(range(1, 31)))

    def test_repair_rounds_wait_longer_each_time_after_an_upstream_error(self):
        # 限流/超时是有窗口的：立刻原样重试撞的是同一个坏窗口，两轮补写一起白费，
        # 缺的那几集就永久留在正文里了。
        service = _service(self._FailingGateway(range(1, 5)))

        self._write(None, ep_count=8, service=service)

        self.assertTrue(service.waits, "补写轮次之间没有任何退避等待")
        self.assertEqual(len(service.waits), DramaService.SCRIPT_REPAIR_ROUNDS)
        self.assertEqual(service.waits, sorted(service.waits))
        self.assertLess(service.waits[0], service.waits[-1], "退避没有随轮次增长")
        self.assertGreater(service.waits[0], 0)

    def test_a_model_that_merely_ignored_the_span_is_retried_without_waiting(self):
        # 没有上游报错时干等几分钟对用户毫无意义，只是把阶段 2 拖慢。
        service = _service(_BatchGateway(honour_span=False))

        script = self._write(None, ep_count=6, service=service)

        self.assertEqual(service._script_episode_indexes(script), [1, 2, 3, 4, 5, 6])
        self.assertEqual(service.waits, [])


class ScriptedEpisodeAuditTests(unittest.TestCase):
    def test_a_short_screenplay_is_recorded_not_rejected(self):
        script = "".join(_episode_text(index) for index in range(1, 16))

        self.assertEqual(DramaService._audit_scripted_episodes(script, 30), 15)

    def test_a_refusal_with_no_episode_headings_fails_the_stage(self):
        # "抱歉，我无法完成" would otherwise be stored as the screenplay and read
        # downstream as a one-episode script.
        with self.assertRaises(RuntimeError):
            DramaService._audit_scripted_episodes("抱歉，我无法完成这个请求。", 30)

    def test_a_single_episode_request_may_legitimately_have_no_heading(self):
        self.assertEqual(DramaService._audit_scripted_episodes("场景1：长街\n陈九：走。", 1), 0)


class BreakdownBatchFailureTests(unittest.TestCase):
    """A batch that fails must not delete its episodes from the shot list."""

    def _breakdown(self, gateway, episode_count=30, body=None):
        script = "".join(_episode_text(index) for index in (body or range(1, episode_count + 1)))
        return _service(gateway)._extract_script_breakdown(
            {"llm_model": "m", "video_model": "seedance2.5"},
            "流氓天子", "palace", "cinematic", script,
        )

    def test_a_failed_opening_batch_is_retried_and_still_yields_its_episodes(self):
        for mode in ("raise", "garbage"):
            breakdown = self._breakdown(_FlakyBreakdownGateway(fail=range(1, 3), mode=mode))
            self.assertEqual(_episodes_covered(breakdown), list(range(1, 31)), mode)

    def test_the_overview_survives_an_opening_batch_that_never_answers(self):
        # The overview is only requested once; if that batch dies it must move to
        # the next one, or the dashboard loses its synopsis for the whole series.
        breakdown = self._breakdown(_FlakyBreakdownGateway(fail=range(1, 5)))

        self.assertEqual(breakdown["overview"]["genre"], "古装权谋")

    def test_a_failing_tail_batch_still_produces_the_last_episodes(self):
        breakdown = self._breakdown(_FlakyBreakdownGateway(fail=range(27, 31)))

        self.assertEqual(_episodes_covered(breakdown), list(range(1, 31)))

    def test_several_consecutive_failing_batches_are_split_down_to_single_episodes(self):
        gateway = _FlakyBreakdownGateway(fail=range(16, 25))
        breakdown = self._breakdown(gateway)

        self.assertEqual(_episodes_covered(breakdown), list(range(1, 31)))
        # The recursion narrowed the request instead of giving up on the span.
        import re
        narrowed = [
            call for call in gateway.calls
            if re.search(r"以上是第 (\d+) 集到第 \1 集", call["user_prompt"])
        ]
        self.assertTrue(narrowed, "失败批次没有降批重试")

    def test_when_every_batch_fails_the_shot_list_falls_back_to_the_script_text(self):
        for mode in ("raise", "garbage"):
            gateway = _FlakyBreakdownGateway(fail=range(1, 31), mode=mode)
            breakdown = self._breakdown(gateway)
            # No exception, no hole, and the retries stop once the provider is clearly down.
            self.assertEqual(_episodes_covered(breakdown), list(range(1, 31)), mode)
            self.assertLess(len(gateway.calls), 30, mode)

    def test_a_batch_that_renumbers_its_answer_is_pinned_back_to_its_own_episodes(self):
        # The model is handed episodes 5-8 and replies E1S01..E4S03.  Those shots
        # belong to 5-8: left alone they double episode 1 and erase 5-8.
        gateway = _FlakyBreakdownGateway(relabel={5: -4})
        breakdown = self._breakdown(gateway)

        self.assertEqual(_episodes_covered(breakdown), list(range(1, 31)))
        first = [scene for scene in breakdown["scenes"] if scene["scene_id"].startswith("E1S")]
        fifth = [scene for scene in breakdown["scenes"] if scene["scene_id"].startswith("E5S")]
        self.assertEqual(len(first), len(fifth))

    def test_a_short_script_drops_shots_numbered_for_episodes_it_lacks(self):
        # The single-call path has no batch span to check against, so an answer
        # numbering shots E7S01 for a three-episode script used to sail through.
        class _OverreachingGateway(_BreakdownGateway):
            def call_llm(self, model, system_prompt, user_prompt, title,
                         director_style="", shot_style="", user_instruction="", max_tokens=None):
                import json
                answer = json.loads(super().call_llm(
                    model, system_prompt, user_prompt, title,
                    director_style, shot_style, user_instruction, max_tokens))
                answer["scenes"].append(
                    {"scene_id": "E7S01", "duration": "12s", "content": "凭空第七集", "characters": []})
                return json.dumps(answer, ensure_ascii=False)

        breakdown = self._breakdown(_OverreachingGateway(), episode_count=3)

        self.assertEqual(_episodes_covered(breakdown), [1, 2, 3])
        self.assertNotIn("凭空第七集", [scene["content"] for scene in breakdown["scenes"]])

    def test_a_short_script_whose_only_call_fails_still_gets_a_shot_list(self):
        # Stage 4 storyboards straight off these shots: an empty breakdown here
        # collapses a three-episode project into a single board.
        breakdown = self._breakdown(_FlakyBreakdownGateway(fail=range(1, 4)), episode_count=3)

        self.assertEqual(_episodes_covered(breakdown), [1, 2, 3])

    def test_no_shots_are_invented_for_episodes_the_screenplay_does_not_contain(self):
        # A screenplay that stops at 15 and resumes at 25 must not grow a
        # fabricated 16-24: the script body is the only basis for a shot list.
        body = list(range(1, 16)) + list(range(25, 31))
        breakdown = self._breakdown(_FlakyBreakdownGateway(fail=range(9, 13)), body=body)

        self.assertEqual(_episodes_covered(breakdown), body)


if __name__ == "__main__":
    unittest.main()

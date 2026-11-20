# -*- coding: utf-8 -*-
"""The cross-episode sheet: what each episode leaves changed, who reads it, and the check after a plan.

Scripted model, no network. What is pinned: the ledger planner writes ``state_changes`` and
sees them again when it plans on; every later episode's plan is told the sheet, how the last
episode ended and what it must leave behind; a plan that disagrees with the sheet is sent
back once and then kept with notes; a first episode, a one-episode film and an author's
finished screenplay are neither told nor checked.
"""

import json
import os
import re
import unittest
from unittest import mock

from app.core import prompt_data
from app.core.screenwriting import prompts, story_state
from tests.test_screenwriting_engine import FakeModel, _engine, _scene

_WORDING = prompt_data.load("story_state")
CHANGES = {
    1: ["【知情】林夏听见录音里周教授承认换了数据", "【物件】录音笔在林夏手里"],
    2: ["【伤势】林夏右手被门夹伤", "【约定】周教授限她三天内交出录音"],
    3: ["【兑现】林夏把录音交给了陈警官"],
}


def _row(episode, changes):
    return {"episode": episode, "title": f"第{episode}集", "hook": "钩子", "story_beats": ["A"], "state_changes": list(changes)}


class SheetModel(FakeModel):
    """A fake whose outline ledger writes the sheet, and who answers the supervisor's check from ``verdicts``."""

    def __init__(self, verdicts=()):
        super().__init__()
        self.verdicts = list(verdicts)
        self.checks: list[str] = []

    def __call__(self, system_prompt, user_prompt, max_tokens):
        if user_prompt.startswith("请拿场记表核对本集"):
            self.calls.append({"system": system_prompt, "prompt": user_prompt, "max_tokens": max_tokens})
            self.checks.append(user_prompt)
            verdict = self.verdicts.pop(0) if self.verdicts else []
            return verdict if isinstance(verdict, str) else json.dumps({"findings": verdict}, ensure_ascii=False)
        if "分集大纲" in user_prompt and "episodes 数组长度必须等于" in user_prompt:
            self.calls.append({"system": system_prompt, "prompt": user_prompt, "max_tokens": max_tokens})
            first, last = (int(n) for n in re.search(r"对应第 (\d+) 集(?:到第 (\d+) 集)?", user_prompt).groups(default="0"))
            last = last or first
            return json.dumps({"episodes": [
                {"title": f"第{n}集标题", "hook": f"第{n}集钩子", "story_beats": [f"节点{n}A"], "next_episode_teaser": None, "state_changes": CHANGES.get(n, [])}
                for n in range(first, last + 1)
            ]}, ensure_ascii=False)
        return super().__call__(system_prompt, user_prompt, max_tokens)


def _plan_prompts(model, episode):
    return [c["prompt"] for c in model.calls if f"当前正在生成第 {episode} 集" in c["prompt"] and "scene_description" in c["prompt"]]


FINDING = {"scene_id": "E2S01", "quote": "你到底瞒了什么？", "fact": "【知情】林夏听见录音里周教授承认换了数据", "fix": "她已经知道了，改成拿录音逼他认"}


class SheetTests(unittest.TestCase):
    def test_a_change_names_its_kind_and_the_field_lists_them_all(self):
        self.assertEqual(story_state.kind_of("【伏笔】保人一栏签着顾怀远"), "伏笔")
        self.assertEqual(story_state.kind_of("【心情】她很难过"), "")
        self.assertEqual(story_state.kind_of("没有类型的一句"), "")
        for kind, _ in _WORDING["kinds"]:
            self.assertIn(kind, story_state.field())
        self.assertTrue(set(_WORDING["lasting"]) <= set(story_state.KINDS))

    def test_an_episode_reads_the_episodes_before_it_in_order(self):
        ledger = [_row(n, CHANGES[n]) for n in (1, 2, 3)]
        self.assertEqual(story_state.table_before(ledger, 1), [])
        self.assertEqual(story_state.table_before(ledger, 3), [
            "第 1 集：", "- 【知情】林夏听见录音里周教授承认换了数据", "- 【物件】录音笔在林夏手里",
            "第 2 集：", "- 【伤势】林夏右手被门夹伤", "- 【约定】周教授限她三天内交出录音",
        ])
        self.assertEqual(story_state.table_before([_row(1, []), _row(2, ["  "])], 3), [], "rows that changed nothing say nothing")

    def test_a_long_series_keeps_the_last_episode_whole_and_of_the_old_ones_what_still_holds(self):
        filler = "【知情】" + "某人知道了某事" * 30  # ~210 字一条
        ledger = [_row(1, ["【伏笔】祠堂梁上藏着第二本账", "【知情】秦伯看见了"])]
        ledger += [_row(n, [filler] * 4) for n in range(2, 21)]
        sheet = story_state.table_before(ledger, 21)

        self.assertIn("第 20 集：", sheet, "the previous episode is always told")
        self.assertLessEqual(sum(len(line) for line in sheet), _WORDING["recent_chars"] + _WORDING["lasting_chars"] + 900)
        self.assertNotIn("第 5 集：", sheet, "an old episode with nothing lasting drops out")
        self.assertIn("- 【伏笔】祠堂梁上藏着第二本账", sheet, "a planted setup outlives the budget of recent episodes")
        self.assertNotIn("- 【知情】秦伯看见了", sheet)
        self.assertLess(sheet.index("第 1 集："), sheet.index("第 20 集："))

    def test_the_planner_is_shown_recent_rows_inline_and_older_lasting_ones_above(self):
        ledger = [_row(n, CHANGES[n]) for n in (1, 2, 3)]
        earlier = story_state.earlier_lasting(ledger, 3)
        self.assertEqual(earlier[:2], ["", _WORDING["earlier_heading"]])
        self.assertIn("- 【物件】录音笔在林夏手里", earlier)
        self.assertNotIn("- 【知情】林夏听见录音里周教授承认换了数据", earlier)
        self.assertNotIn("第 3 集：", earlier)
        self.assertEqual(story_state.earlier_lasting(ledger, 1), [])
        prompt = prompts.build_outline_plan_prompt(
            title="暗室回声", director_plan="大纲", overview=None, first=4, last=5, total=5, context_entries=ledger[1:], target_seconds=None,
            instructions=None, earlier_state=story_state.earlier_lasting(ledger, 2),
        )
        self.assertIn("  演完已定：【伤势】林夏右手被门夹伤；【约定】周教授限她三天内交出录音", prompt)
        self.assertLess(prompt.index(_WORDING["earlier_heading"]), prompt.index("# 已规划的前情"))

    def test_nothing_is_said_when_there_is_nothing_to_say(self):
        self.assertEqual(story_state.plan_block(sheet=[], previous_outline=[], landing=[]), "")
        self.assertEqual(story_state.context_changes(_row(1, [])), "")


class LedgerTests(unittest.TestCase):
    def test_the_ledger_keeps_each_episodes_changes_and_the_schema_asks_for_them(self):
        model = SheetModel()
        state = _engine(model, plan_batch_size=2).write(title="暗室回声", director_plan="大纲", episode_count=3)

        self.assertEqual([entry["state_changes"] for entry in state["ledger"]], [CHANGES[1], CHANGES[2], CHANGES[3]])
        batches = [c["prompt"] for c in model.calls if "episodes 数组长度必须等于" in c["prompt"]]
        self.assertIn('"state_changes"', batches[0])
        self.assertIn("类型只能是 伤势、知情、关系", batches[0])
        self.assertNotIn("演完已定", batches[0])
        self.assertIn("  演完已定：【伤势】林夏右手被门夹伤；【约定】周教授限她三天内交出录音", batches[1], "the next batch plans on from what was settled")

    def test_a_novels_cut_keeps_them_too(self):
        class Anchored(FakeModel):
            def __call__(self, system_prompt, user_prompt, max_tokens):
                answer = super().__call__(system_prompt, user_prompt, max_tokens)
                if "end_anchor" in user_prompt and "短剧改编统筹" not in user_prompt:
                    data = json.loads(answer)
                    for number, draft in enumerate(data["episodes"], start=1):
                        draft["state_changes"] = CHANGES[number]
                    return json.dumps(data, ensure_ascii=False)
                return answer

        novel = "林夏推开实验室的门，冷白灯光刺得她眯起眼。她在抽屉里找到了录音笔。周教授站在她身后，声音低沉：现在回头还来得及。"
        state = _engine(Anchored()).write(title="暗室回声", director_plan="", episode_count=2, source_text=novel)
        self.assertEqual([entry["state_changes"] for entry in state["ledger"]], [CHANGES[1], CHANGES[2]])

    def test_a_ledger_planned_before_the_sheet_existed_reads_as_before(self):
        model = FakeModel()
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=2)
        self.assertEqual([entry["state_changes"] for entry in state["ledger"]], [[], []])
        second = _plan_prompts(model, 2)[0]
        self.assertNotIn("<story_state>", second)
        self.assertIn("<previous_episode_outline>", second, "how the last episode ended is told from the ledger it always had")


class EpisodePromptTests(unittest.TestCase):
    def test_a_later_episode_is_told_the_sheet_the_last_ending_and_what_it_must_leave(self):
        model = SheetModel()
        _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=3)
        first, third = _plan_prompts(model, 1)[0], _plan_prompts(model, 3)[0]

        self.assertIn("<previous_episode_outline>", third)
        self.assertIn("集尾钩子：第2集钩子", third.split("</previous_episode_outline>")[0])
        self.assertIn("<story_state>", third)
        self.assertIn("第 2 集：\n- 【伤势】林夏右手被门夹伤", third)
        self.assertIn(_WORDING["plan_rule"], third)
        self.assertIn("<episode_changes>", third)
        self.assertIn("- 【兑现】林夏把录音交给了陈警官", third.split("<episode_changes>")[1].split("</episode_changes>")[0])
        self.assertLess(third.index("<story_state>"), third.index("<episode_outline>"))
        # The first episode has nothing behind it; it is only told what it must leave.
        self.assertNotIn("<story_state>", first)
        self.assertNotIn("<previous_episode_outline>", first)
        self.assertNotIn(_WORDING["plan_rule"], first)
        self.assertIn("- 【物件】录音笔在林夏手里", first.split("<episode_changes>")[1])

    def test_a_one_episode_film_and_an_authors_screenplay_are_told_nothing(self):
        film = SheetModel()
        _engine(film).write(title="暗室回声", director_plan="大纲", episode_count=1)
        self.assertNotIn("<episode_changes>", _plan_prompts(film, 1)[0])
        common = dict(
            source_text="原文", episode=2, overview=None, style="", characters={}, scenes={}, props={},
            supported_durations=[5, 10], default_duration=None, episode_target_seconds=None, episode_outline=None, next_episode_outline=None,
            previous_episode_outline={"title": "上", "hook": "钩子", "story_beats": ["A"]}, sheet=["第 1 集：", "- 【物件】录音笔在林夏手里"], landing=["【伤势】右手夹伤"],
        )
        self.assertNotIn("<story_state>", prompts.build_script_plan_prompt(source_kind="screenplay", **common))
        self.assertIn("<story_state>", prompts.build_script_plan_prompt(source_kind="novel", **common))


@mock.patch.dict(os.environ, {"SCREENWRITING_STATE_CHECK": "1"})
class CheckTests(unittest.TestCase):
    def test_a_plan_that_agrees_costs_one_check_and_the_first_episode_none(self):
        model = SheetModel()
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=2)

        self.assertEqual(len(model.checks), 1)
        check = model.checks[0]
        self.assertIn("第 2 集", check.splitlines()[0])
        self.assertIn("- 【物件】录音笔在林夏手里", check.split("<story_state>")[1].split("</story_state>")[0])
        self.assertIn("- 【伤势】林夏右手被门夹伤", check.split("<episode_changes>")[1].split("</episode_changes>")[0])
        self.assertIn("  林夏：你到底瞒了什么？", check.split("<shots>")[1])
        self.assertEqual(model.calls[[c["prompt"] for c in model.calls].index(check)]["system"], _WORDING["check_system"])
        self.assertEqual(model.plan_attempts, {1: 1, 2: 1})
        self.assertEqual(state["episodes"]["2"]["violations"], [])
        asked = model.calls[[c["prompt"] for c in model.calls].index(check)]
        plan = next(c for c in model.calls if "当前正在生成第 2 集" in c["prompt"] and "scene_description" in c["prompt"])
        self.assertEqual(asked["max_tokens"], plan["max_tokens"], "the engine's own budget: a reasoning model given less answers nothing")

    def test_a_plan_that_disagrees_is_sent_back_once_with_the_finding(self):
        model = SheetModel(verdicts=[[FINDING], []])
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=2)

        self.assertEqual(model.plan_attempts[2], 2)
        self.assertEqual(len(model.checks), 2, "the rewritten plan is looked at again")
        retry = _plan_prompts(model, 2)[1]
        self.assertIn("## 修复上一版草稿", retry)
        self.assertIn("- 分镜 E2S01「你到底瞒了什么？」与前面定下的「【知情】林夏听见录音里周教授承认换了数据」对不上或重演了：她已经知道了，改成拿录音逼他认", retry)
        self.assertNotIn("story_state_conflict", [v["code"] for v in state["episodes"]["2"]["violations"]])

    def test_what_is_still_wrong_after_the_send_back_is_kept_as_a_note(self):
        missing = {"scene_id": "", "quote": "【伤势】林夏右手被门夹伤", "fact": "", "fix": "加一个她的手被门夹住的分镜"}
        model = SheetModel(verdicts=[[FINDING], [missing]])
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=2)

        self.assertEqual(model.plan_attempts[2], 2, "one send-back, not a loop")
        notes = [v for v in state["episodes"]["2"]["violations"] if v["code"] == "story_state_conflict"]
        self.assertEqual(len(notes), 1)
        self.assertIn("本集应当落下的变化没有演出来——【伤势】林夏右手被门夹伤", notes[0]["message"])
        self.assertEqual(notes[0]["severity"], "warning")
        self.assertNotIn("draft", state["episodes"]["2"])

    def test_no_usable_answer_counts_as_agreement(self):
        model = SheetModel(verdicts=["抱歉，我无法完成。", "还是不行。"])
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=2)
        self.assertEqual(model.plan_attempts[2], 1)
        self.assertEqual(state["episodes"]["2"]["violations"], [])

    def test_episodes_written_side_by_side_are_checked_too(self):
        model = SheetModel()
        _engine(model, episode_concurrency=3).write(title="暗室回声", director_plan="大纲", episode_count=3)
        self.assertEqual(sorted(int(re.search(r"第 (\d+) 集", check).group(1)) for check in model.checks), [2, 3])

    def test_a_one_episode_film_an_old_ledger_and_an_authors_screenplay_are_not_checked(self):
        film = SheetModel()
        _engine(film).write(title="暗室回声", director_plan="大纲", episode_count=1)
        self.assertEqual(film.checks, [])

        class Guard(FakeModel):
            def __call__(self, system_prompt, user_prompt, max_tokens):
                assert not user_prompt.startswith("请拿场记表核对本集"), "nothing to check against"
                return super().__call__(system_prompt, user_prompt, max_tokens)

        _engine(Guard()).write(title="暗室回声", director_plan="大纲", episode_count=2)
        script = "第1集 对峙\n场景1：实验室\n林夏：你到底瞒了什么？\n第2集 回声\n场景1：走廊\n周教授：现在回头还来得及。\n"
        _engine(Guard(), episode_shape=None).write(title="暗室回声", director_plan="", episode_count=2, source_text=script, source_kind="screenplay")

    def test_the_switch_turns_the_check_off_and_leaves_the_sheet_in_the_prompts(self):
        with mock.patch.dict(os.environ, {"SCREENWRITING_STATE_CHECK": "0"}):
            model = SheetModel(verdicts=[[FINDING]])
            _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=2)
        self.assertEqual(model.checks, [])
        self.assertIn("<story_state>", _plan_prompts(model, 2)[0])


if __name__ == "__main__":
    unittest.main()

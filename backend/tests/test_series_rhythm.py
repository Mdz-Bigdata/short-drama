# -*- coding: utf-8 -*-
"""A serial stops its episodes in different ways, escalates on a schedule, pays off with results, and names its people freshly.

No model, no network. The kinds, word lists, numbers and sentences are ``series_rhythm.json``; the planner
reads the rules, and what a look at a planned ledger can tell comes back as hints — never an error, never a
reason to send the plan back, never another model call.
"""

import json
import unittest

from app.core import emotion_points, prompt_data, series_rhythm
from app.core.screenwriting.prompts import build_anchored_plan_prompt, build_outline_plan_prompt, build_script_plan_prompt
from tests.test_screenwriting_engine import FakeModel, _engine

DATA = prompt_data.load("series_rhythm")
KINDS = [kind for kind, _how in DATA["cliffhangers"]]


def _hook(kind: str, text: str = "门被踹开") -> str:
    return DATA["hook_tag"].format(kind=kind) + text


def _outline(total: int) -> str:
    return build_outline_plan_prompt(
        title="暗室回声", director_plan="三幕大纲", overview={"genre": "悬疑"}, first=1, last=min(total, 3), total=total,
        context_entries=[], target_seconds=90, instructions=None,
    )


class TableTests(unittest.TestCase):
    def test_the_table_is_usable_as_written(self):
        self.assertEqual(len(KINDS), len(set(KINDS)))
        self.assertGreaterEqual(DATA["same_kind_run"], 2)
        self.assertLess(DATA["same_kind_run"], len(KINDS), "there is always another way to stop")
        for low, high in (DATA["escalate"], DATA["reversal"]):
            self.assertLess(low, high)
        self.assertLessEqual(DATA["escalate"][1], DATA["reversal"][0], "a turn-over is rarer than an escalation")
        self.assertEqual(set(DATA["hollow_words"]) & set(DATA["result_words"]), set())
        # A payoff is one of the emotion points the planner already tags beats with.
        self.assertTrue(set(DATA["payoff_kinds"]) <= set(emotion_points.KINDS))
        # Every whole name in the table is also caught the way a name is judged.
        self.assertEqual(len(series_rhythm.name_warnings(DATA["overused_names"][:1])), 1)


class CliffhangerTests(unittest.TestCase):
    def test_a_hook_names_its_kind_at_the_head(self):
        self.assertEqual(series_rhythm.hook_kind(_hook(KINDS[0])), KINDS[0])
        self.assertEqual(series_rhythm.hook_kind("  " + _hook(KINDS[3])), KINDS[3])
        for loose in ("门被踹开", "【随便写的】门被踹开", f"门被踹开{DATA['hook_tag'].format(kind=KINDS[0])}", None):
            self.assertEqual(series_rhythm.hook_kind(loose), "", loose)

    def test_three_in_a_row_is_pointed_out_once_with_the_other_ways(self):
        same = [(n, _hook(KINDS[0])) for n in (1, 2, 3, 4)]
        found = series_rhythm.repeat_warnings([*same, (5, _hook(KINDS[1])), (6, _hook(KINDS[0]))])
        self.assertEqual(len(found), 1)
        self.assertIn("第 1–4 集", found[0])
        self.assertIn(f"「{KINDS[0]}」", found[0])
        for other in KINDS[1:]:
            self.assertIn(other, found[0])

    def test_two_in_a_row_untagged_hooks_and_gaps_are_fine(self):
        self.assertEqual(series_rhythm.repeat_warnings([(1, _hook(KINDS[0])), (2, _hook(KINDS[0])), (3, _hook(KINDS[1]))]), [])
        self.assertEqual(series_rhythm.repeat_warnings([(n, "门被踹开") for n in range(1, 6)]), [])
        # Episodes 1, 2 and 5 are not consecutive: nobody watches them back to back.
        self.assertEqual(series_rhythm.repeat_warnings([(1, _hook(KINDS[0])), (2, _hook(KINDS[0])), (5, _hook(KINDS[0]))]), [])

    def test_a_new_batch_counts_the_episodes_that_lead_into_it(self):
        earlier = [{"episode": 4, "hook": _hook(KINDS[2])}, {"episode": 5, "hook": _hook(KINDS[2])}]
        found = series_rhythm.outline_warnings([{"episode": 6, "hook": _hook(KINDS[2])}, {"episode": 7, "hook": _hook(KINDS[4])}], earlier=earlier)
        self.assertEqual(len(found), 1)
        self.assertIn("第 4–6 集", found[0])
        # A run that ended before this batch was reported when it was planned.
        old = [{"episode": n, "hook": _hook(KINDS[2])} for n in (1, 2, 3)]
        self.assertEqual(series_rhythm.outline_warnings([{"episode": 4, "hook": _hook(KINDS[4])}], earlier=old), [])


class PayoffTests(unittest.TestCase):
    TAG = emotion_points.tag(DATA["payoff_kinds"][0]) if hasattr(emotion_points, "tag") else "【爽点】"

    def test_a_payoff_that_is_only_a_reaction_is_pointed_out(self):
        found = series_rhythm.hollow_payoffs([f"{self.TAG}刀疤愣住了，你给我等着"], label="第 2 集")
        self.assertEqual(len(found), 1)
        self.assertIn("「愣住」「你给我等着」", found[0])
        self.assertNotIn("「给我等着」", found[0], "the longer word already says it")
        self.assertTrue(found[0].startswith("第 2 集"))

    def test_a_result_in_the_same_beat_makes_it_a_payoff(self):
        self.assertEqual(series_rhythm.hollow_payoffs([f"{self.TAG}刀疤当众赔钱，手下全愣住"], label="第 2 集"), [])

    def test_other_beats_may_freeze_as_they_like(self):
        self.assertEqual(series_rhythm.hollow_payoffs(["【悬念】林夏愣住，门外有人", "刀疤愣住了"], label="第 2 集"), [])


class WindowTests(unittest.TestCase):
    """Over a stretch of episodes: something new every two or three, something strong and some change every ten."""

    WINDOW = DATA["window"]
    NEWS = DATA["news_every"][1]

    @staticmethod
    def _rows(count: int, beats: list[str], changes=None, first: int = 1) -> list[dict]:
        return [
            {"episode": number, "story_beats": list(beats), **({"state_changes": list(changes)} if changes is not None else {})}
            for number in range(first, first + count)
        ]

    def test_the_kinds_are_emotion_points_and_news_comes_more_often_than_a_strong_point(self):
        for key in ("news_kinds", "strong_kinds"):
            self.assertTrue(set(DATA[key]) <= set(emotion_points.KINDS), key)
        self.assertLess(DATA["news_every"][0], self.NEWS)
        self.assertLess(self.NEWS, self.WINDOW)

    def test_the_rules_come_with_the_length_they_make_sense_for(self):
        self.assertFalse(any("新信息" in rule for rule in series_rhythm.outline_rules(self.NEWS - 1)))
        self.assertTrue(any("新信息" in rule for rule in series_rhythm.outline_rules(self.NEWS)))
        self.assertFalse(any("任意连着" in rule for rule in series_rhythm.outline_rules(self.WINDOW - 1)))
        self.assertTrue(any("任意连着" in rule for rule in series_rhythm.outline_rules(self.WINDOW)))

    def test_episodes_that_only_quarrel_are_pointed_out_as_soon_as_the_stretch_is_long_enough(self):
        quarrel = ["【冲突】两人又吵了一架", "【悬念】门外有人"]
        self.assertEqual(series_rhythm.window_warnings(self._rows(self.NEWS - 1, quarrel)), [])
        found = series_rhythm.window_warnings(self._rows(self.NEWS, quarrel))
        self.assertEqual(len(found), 1)
        self.assertIn(f"第 1–{self.NEWS} 集", found[0])
        for kind in DATA["news_kinds"]:
            self.assertIn(kind, found[0])

    def test_ten_episodes_without_a_strong_point_are_pointed_out_and_one_such_beat_clears_them(self):
        flat = ["【冲突】a", "【信息交代】b"]
        found = series_rhythm.window_warnings(self._rows(self.WINDOW, flat))
        self.assertEqual(len(found), 1)
        self.assertIn(f"连着 {self.WINDOW} 集", found[0])
        self.assertIn("强情绪点", found[0])
        rows = self._rows(self.WINDOW, flat)
        rows[4]["story_beats"].append(f"【{DATA['strong_kinds'][0]}】刀疤当众赔钱")
        self.assertEqual(series_rhythm.window_warnings(rows), [])

    def test_an_empty_sheet_for_ten_episodes_is_a_stretch_where_nothing_changed(self):
        beats = ["【揭秘】a", f"【{DATA['strong_kinds'][0]}】b"]
        rows = [*self._rows(1, beats, changes=["【关系】两人翻脸"]), *self._rows(self.WINDOW, beats, changes=[], first=2)]
        found = series_rhythm.window_warnings(rows)
        self.assertEqual(len(found), 1)
        self.assertIn(f"第 2–{self.WINDOW + 1} 集", found[0])
        self.assertIn("场记都是空的", found[0])
        # A ledger that never kept the sheet says nothing about change either way.
        self.assertEqual(series_rhythm.window_warnings(self._rows(self.WINDOW + 1, beats)), [])
        self.assertEqual(series_rhythm.window_warnings(self._rows(self.WINDOW + 1, beats, changes=[])), [])

    def test_untagged_episodes_are_not_judged_and_break_a_stretch(self):
        self.assertEqual(series_rhythm.window_warnings(self._rows(self.WINDOW, ["两人又吵了一架"])), [])
        quarrel = ["【冲突】a"]
        rows = [*self._rows(2, quarrel), *self._rows(1, ["没标类型"], first=3), *self._rows(2, quarrel, first=4)]
        self.assertEqual(series_rhythm.window_warnings(rows), [])

    def test_only_a_stretch_that_reaches_the_new_episodes_is_reported(self):
        quarrel = ["【冲突】a"]
        rows = [*self._rows(self.NEWS, quarrel), *self._rows(2, ["【揭秘】b"], first=self.NEWS + 1)]
        self.assertEqual(len(series_rhythm.window_warnings(rows)), 1)
        self.assertEqual(series_rhythm.window_warnings(rows, fresh={self.NEWS + 1, self.NEWS + 2}), [])
        earlier, batch = rows[: self.NEWS], rows[self.NEWS:]
        self.assertEqual([w for w in series_rhythm.outline_warnings(batch, earlier=earlier) if "新信息" in w], [])
        still = self._rows(2, quarrel, first=self.NEWS + 1)
        found = [w for w in series_rhythm.outline_warnings(still, earlier=earlier) if "新信息" in w]
        self.assertEqual(len(found), 1)
        self.assertIn(f"第 1–{self.NEWS + 2} 集", found[0])


class NameTests(unittest.TestCase):
    def test_worn_names_are_pointed_out_whole_or_by_surname_and_character(self):
        found = series_rhythm.name_warnings(["苏念念", "赵铁柱", "沈星辰", "周教授"])
        self.assertEqual(len(found), 1)
        self.assertIn("「苏念念」「沈星辰」", found[0])
        # A common surname alone, or a worn character under another surname, is an ordinary name.
        self.assertEqual(series_rhythm.name_warnings(["林大山", "赵晚晴", "周教授"]), [])

    def test_leads_who_share_a_surname_are_pointed_out(self):
        found = series_rhythm.name_warnings(["林大山", "林小满", "赵铁柱", "周教授", "林路人"])
        self.assertEqual(len(found), 1)
        self.assertIn("「林大山」「林小满」同姓「林」", found[0])
        self.assertNotIn("林路人", found[0], "only the main cast counts")

    def test_the_director_is_told_before_anyone_is_named(self):
        rule = series_rhythm.naming_rule()
        for name in DATA["overused_names"]:
            self.assertIn(name, rule)
        self.assertIn("姓互不相同", rule)


class PromptTests(unittest.TestCase):
    def test_a_serial_is_told_how_to_stop_and_when_to_escalate(self):
        prompt = _outline(30)
        for kind in KINDS:
            self.assertIn(kind, prompt)
        self.assertIn(f"连续 {DATA['same_kind_run']} 集不用同一种", prompt)
        self.assertIn("每 3–5 集", prompt)
        self.assertIn("每 8–15 集", prompt)
        # The rules sit with the other planning rules, before the director's plan.
        self.assertLess(prompt.index("集尾卡点换着用"), prompt.index("三幕大纲"))

    def test_a_single_film_has_no_next_episode_to_stop_for(self):
        prompt = _outline(1)
        self.assertNotIn("集尾卡点换着用", prompt)
        self.assertNotIn("每 3–5 集", prompt)
        self.assertIn("集尾卡点换着用", _outline(2))
        self.assertNotIn("每 3–5 集", _outline(2), "two episodes are too few to escalate on a schedule")

    def test_the_script_is_told_that_what_a_character_knows_has_a_source(self):
        for kind in ("outline", "novel", "screenplay"):
            prompt = build_script_plan_prompt(
                episode=1, overview={"title": "暗室回声", "genre": "悬疑"}, style="写实", characters={"林夏": {"description": "短发"}},
                scenes={}, props={}, supported_durations=[5, 10], default_duration=None, episode_target_seconds=None,
                episode_outline={"story_beats": ["【钩子】a"]}, next_episode_outline=None,
                source_text="林夏推开实验室的门。", source_kind=kind,
            )
            with self.subTest(kind=kind):
                # An author's finished screenplay is extracted as written: no shot is added and no line dropped for it.
                self.assertEqual(DATA["knowledge_rule"] in prompt, kind != "screenplay")


class AdaptationTests(unittest.TestCase):
    """A novel cut into episodes varies how they stop too, but is not asked to invent escalations on a schedule."""

    @staticmethod
    def _plan(kind: str, max_episodes: int) -> str:
        return build_anchored_plan_prompt(
            window="原文", window_is_final=True, overview=None, source_kind=kind, context_entries=[], target_volume=None,
            max_episodes=max_episodes, remaining_episodes=None, instructions=None,
        )

    def test_a_novel_in_several_episodes_is_told_the_ways_to_stop_and_nothing_about_cadence(self):
        prompt = self._plan("novel", 10)
        self.assertIn("集尾卡点换着用", prompt)
        for kind in KINDS:
            self.assertIn(kind, prompt)
        self.assertNotIn("每 3–5 集", prompt)
        # What an adaptation is still held to over a stretch of episodes: news, a strong point, a change.
        self.assertIn("每 2–3 集至少给观众一个新信息", prompt)
        self.assertIn(f"任意连着的 {DATA['window']} 集里", prompt)
        with_cadence, without = series_rhythm.outline_rules(10), series_rhythm.outline_rules(10, cadence=False)
        self.assertEqual([rule for rule in with_cadence if rule not in without], [with_cadence[1]])

    def test_one_episode_from_a_novel_and_an_authors_screenplay_get_no_such_rule(self):
        self.assertNotIn("集尾卡点换着用", self._plan("novel", 1))
        self.assertNotIn("集尾卡点换着用", self._plan("screenplay", 10))


class TaggedModel(FakeModel):
    """The engine's fake model, with a ledger that stops every episode the same way and a worn name in the cast."""

    def __call__(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        answer = super().__call__(system_prompt, user_prompt, max_tokens)
        if "episodes 数组长度必须等于" in user_prompt:
            data = json.loads(answer)
            for episode in data["episodes"]:
                episode["hook"] = _hook(KINDS[0], episode["hook"])
                episode["story_beats"] = ["【爽点】周教授愣住了"]
            return json.dumps(data, ensure_ascii=False)
        if "角色与世界观分析师" in user_prompt:
            data = json.loads(answer)
            data["characters"] = {"顾北辰": data["characters"]["林夏"], "周教授": data["characters"]["周教授"]}
            return json.dumps(data, ensure_ascii=False)
        return answer


class EngineTests(unittest.TestCase):
    def test_the_hints_reach_the_writer_without_another_call_or_a_retry(self):
        plain, tagged = FakeModel(), TaggedModel()
        clean = _engine(plain).write(title="暗室回声", director_plan="三幕大纲……", episode_count=3, outline_only=True)
        state = _engine(tagged).write(title="暗室回声", director_plan="三幕大纲……", episode_count=3, outline_only=True)
        self.assertEqual(len(tagged.calls), len(plain.calls), "a hint costs no model call")
        self.assertEqual([entry["hook"] for entry in state["ledger"]], [_hook(KINDS[0], f"第{n}集钩子") for n in (1, 2, 3)])
        warnings = "\n".join(state["warnings"])
        self.assertIn("第 1–3 集的集尾都是", warnings)
        self.assertIn("爽点只写到反应", warnings)
        self.assertIn("「顾北辰」", warnings)
        self.assertFalse([line for line in clean["warnings"] if "卡点" in line or "爽点" in line or "角色名" in line])


class QuarrelModel(FakeModel):
    """A ledger in which every episode is one more quarrel."""

    def __call__(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        answer = super().__call__(system_prompt, user_prompt, max_tokens)
        if "episodes 数组长度必须等于" in user_prompt:
            data = json.loads(answer)
            for episode in data["episodes"]:
                episode["story_beats"] = ["【冲突】两人又吵了一架"]
            return json.dumps(data, ensure_ascii=False)
        return answer


class EngineWindowTests(unittest.TestCase):
    def test_a_stretch_is_seen_across_planning_batches_and_reported_once(self):
        state = _engine(QuarrelModel(), plan_batch_size=2).write(title="暗室回声", director_plan="三幕大纲……", episode_count=4, outline_only=True)
        found = [line for line in state["warnings"] if "新信息" in line]
        self.assertEqual(len(found), 1, "two batches of two: the stretch only becomes long enough in the second")
        self.assertIn("第 1–4 集连着 4 集", found[0])
        self.assertEqual(len(state["ledger"]), 4)


class FightRuleTests(unittest.TestCase):
    def test_the_fight_rules_say_who_the_lens_favours_and_how_much_light_a_frame_holds(self):
        plan, visual = prompt_data.text("fight_scene", "plan_rules"), prompt_data.text("fight_scene", "visual_rules")
        self.assertIn("强者有固定标志", plan)
        self.assertIn("机位讲强弱", visual)
        self.assertIn("余波比命中长", visual)
        self.assertIn("能量色不超过两种", visual)
        self.assertIn("能量色不超过两种", prompt_data.text("wuxia_vfx", "plan_rules"))
        self.assertTrue(any("已经发生的结果" in line for line in prompt_data.words("payoff", "formula")))


if __name__ == "__main__":
    unittest.main()

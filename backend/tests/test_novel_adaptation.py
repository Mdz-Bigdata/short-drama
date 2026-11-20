# -*- coding: utf-8 -*-
"""A novel is re-staged, not converted: the adaptation brief, the ledger and the episode plan.

Scripted model, no network. What is pinned: the brief is settled once after the cast and
before the ledger; the ledger planner and every adapted episode are told what it settles;
episode 1 may not open on exposition; a drama adapted from a novel does not tell its story
in narration; an author's finished screenplay and a film written from an outline are left
as they were.
"""

import json
import unittest

from app.core import prompt_data
from app.core.screenwriting import prompts
from app.core.screenwriting.structured_llm import RETRY_HEADER
from tests.test_screenwriting_engine import ADAPTATION_BRIEF, FakeModel, _engine, _scene

NOVEL = "林夏推开实验室的门，冷白灯光刺得她眯起眼。她在抽屉里找到了录音笔。周教授站在她身后，声音低沉：现在回头还来得及。"
SCREENPLAY = "第1集 对峙\n场景1：实验室\n林夏：你到底瞒了什么？\n周教授：现在回头还来得及。\n"
_WORDING = prompt_data.load("screenwriting_prompts")
_ENGINE_WORDING = prompt_data.load("screenwriting_engine")
_LIMIT = _WORDING["adaptation"]["limits"]["narrated_shots"]


def _write_novel(model, **overrides):
    return _engine(model, **overrides).write(title="暗室回声", director_plan="", episode_count=2, source_text=NOVEL)


def _ledger_prompts(model):
    return [call["prompt"] for call in model.calls if "end_anchor" in call["prompt"]]


def _plan_prompts(model, episode):
    return [call["prompt"] for call in model.calls if f"当前正在生成第 {episode} 集" in call["prompt"] and "scene_description" in call["prompt"]]


class _LedgerModel(FakeModel):
    """A fake whose anchored ledger tags its beats; ``openings`` is episode 1's first beat, one per ask."""

    def __init__(self, openings):
        super().__init__()
        self.openings = list(openings)
        self.ledger_asks = 0

    def __call__(self, system_prompt, user_prompt, max_tokens):
        if "end_anchor" not in user_prompt:
            return super().__call__(system_prompt, user_prompt, max_tokens)
        self.calls.append({"system": system_prompt, "prompt": user_prompt, "max_tokens": max_tokens})
        opening = self.openings[min(self.ledger_asks, len(self.openings) - 1)]
        self.ledger_asks += 1
        window = user_prompt.split("---\n", 1)[1].rsplit("\n---", 1)[0]
        midpoint = window.find("。") + 1
        return json.dumps({"episodes": [
            {"title": "上", "hook": "钩子一", "end_anchor": window[max(0, midpoint - 12):midpoint], "story_beats": [opening, "【冲突】周教授拦住去路"], "next_episode_teaser": "下集"},
            {"title": "下", "hook": "钩子二", "end_anchor": window[-12:], "story_beats": ["【反转】录音笔还在转"], "next_episode_teaser": None},
        ]}, ensure_ascii=False)


class BriefTests(unittest.TestCase):
    def test_a_novel_gets_its_brief_after_the_cast_and_before_the_ledger(self):
        model = FakeModel()
        state = _write_novel(model)

        self.assertEqual(state["adaptation"]["protagonist"], "林夏")
        self.assertEqual(state["adaptation"]["keep"], ADAPTATION_BRIEF["keep"])
        kinds = ["cast" if "角色与世界观分析师" in c["prompt"] else "brief" if "短剧改编统筹" in c["prompt"] else "ledger" if "end_anchor" in c["prompt"] else "" for c in model.calls]
        order = [kind for kind in kinds if kind]
        self.assertEqual(order, ["cast", "brief", "ledger"])
        brief = next(c["prompt"] for c in model.calls if "短剧改编统筹" in c["prompt"])
        self.assertIn("- 林夏：黑色短发，白大褂", brief, "the brief names its protagonist from the settled cast")
        self.assertIn("<novel>\n" + NOVEL, brief)
        self.assertIn(f"最多 {_WORDING['adaptation']['limits']['keep']} 条", brief)
        asked = next(c for c in model.calls if "短剧改编统筹" in c["prompt"])
        inventory = next(c for c in model.calls if "角色与世界观分析师" in c["prompt"])
        self.assertEqual(asked["max_tokens"], inventory["max_tokens"], "a reasoning model needs the whole budget, or the brief comes back empty")

    def test_a_brief_that_overruns_its_lists_is_stored_as_long_as_it_is_shown(self):
        limits = _WORDING["adaptation"]["limits"]

        class Wordy(FakeModel):
            def __call__(self, system_prompt, user_prompt, max_tokens):
                if "短剧改编统筹" in user_prompt:
                    self.calls.append({"system": system_prompt, "prompt": user_prompt, "max_tokens": max_tokens})
                    keep = [f"设定{n}" for n in range(limits["keep"] + 3)] + ["  "]
                    return json.dumps({**ADAPTATION_BRIEF, "keep": keep, "compress": [f"过场{n}" for n in range(limits["compress"] + 2)]}, ensure_ascii=False)
                return super().__call__(system_prompt, user_prompt, max_tokens)

        model = Wordy()
        state = _write_novel(model)
        self.assertEqual(state["adaptation"]["keep"], [f"设定{n}" for n in range(limits["keep"])])
        self.assertEqual(len(state["adaptation"]["compress"]), limits["compress"])
        ledger = _ledger_prompts(model)[0]
        self.assertIn(f"  - 设定{limits['keep'] - 1}", ledger)
        self.assertNotIn(f"  - 设定{limits['keep']}\n", ledger)

    def test_an_outline_and_a_finished_screenplay_get_no_brief(self):
        outline = FakeModel()
        state = _engine(outline).write(title="暗室回声", director_plan="大纲", episode_count=1)
        self.assertNotIn("adaptation", state)
        script = FakeModel()
        state = _engine(script).write(title="暗室回声", director_plan="", episode_count=1, source_text=SCREENPLAY, source_kind="screenplay")
        self.assertNotIn("adaptation", state)
        for model in (outline, script):
            self.assertFalse(any("短剧改编统筹" in c["prompt"] for c in model.calls))
            self.assertFalse(any("改编要求" in c["prompt"] or "<adaptation>" in c["prompt"] for c in model.calls))
        ledger = _ledger_prompts(script)[0]
        self.assertIn("提取而非重切", ledger)
        self.assertNotIn("切点跟着戏走", ledger)

    def test_a_brief_the_model_cannot_give_does_not_cost_the_screenplay(self):
        class NoBrief(FakeModel):
            def __call__(self, system_prompt, user_prompt, max_tokens):
                if "短剧改编统筹" in user_prompt:
                    self.calls.append({"system": system_prompt, "prompt": user_prompt, "max_tokens": max_tokens})
                    return "抱歉，我无法完成。"
                return super().__call__(system_prompt, user_prompt, max_tokens)

        model = NoBrief()
        state = _write_novel(model, attempts=2)

        self.assertEqual(state["adaptation"]["keep"], [])
        self.assertEqual(state["adaptation"]["protagonist"], "")
        self.assertEqual(sorted(state["episodes"]), ["1", "2"])
        self.assertNotIn("<adaptation>", _plan_prompts(model, 1)[0])
        self.assertIn("# 改编要求", _plan_prompts(model, 1)[0], "the rules of adapting do not depend on the brief")
        self.assertNotIn(_WORDING["adaptation"]["heading"], _ledger_prompts(model)[0])

    def test_a_state_written_before_the_brief_existed_still_previews(self):
        model = FakeModel()
        engine = _engine(model)
        state = engine.write(title="暗室回声", director_plan="", episode_count=2, source_text=NOVEL)
        state.pop("adaptation")
        prompt = engine.dry_run_prompt(state, 2, "plan")
        self.assertIn("# 改编要求", prompt)
        self.assertNotIn("<adaptation>", prompt)


class LedgerTests(unittest.TestCase):
    def test_the_ledger_planner_restages_the_novel_from_the_brief(self):
        model = FakeModel()
        _write_novel(model)
        ledger = _ledger_prompts(model)[0]

        self.assertIn("改编不是把章节换成剧本格式", ledger)
        self.assertIn("切点跟着戏走，不跟着章节走", ledger)
        self.assertIn("story_beats 写成片里的先后，不必照原文的叙述顺序", ledger)
        self.assertIn("不为铺垫另开回忆的戏", ledger)
        self.assertIn("只排原文里有的事和话", ledger)
        self.assertIn("不另编情节凑数", ledger)
        self.assertIn("配角或反派独处时的盘算不单独成节点", ledger)
        self.assertIn(prompt_data.text("causal_chain", "outline_rule"), ledger)
        self.assertIn(_WORDING["outline_plan"]["no_inner_life"], ledger)
        self.assertIn(_WORDING["adaptation"]["heading"], ledger)
        self.assertIn("- 核心卖点：" + ADAPTATION_BRIEF["selling_point"], ledger)
        self.assertIn("- 主视角人物：林夏。", ledger)
        self.assertIn("  - 实验室的门禁每晚十点自动落锁", ledger)
        self.assertIn("  - 林夏回忆入学那天的大段叙述", ledger)
        # Episode 1 opens on the scene the brief chose, and never on exposition.
        self.assertIn("第 1 集的第一个节点就是开场戏，类型不能是信息交代", ledger)
        self.assertIn("改编方案定的开场戏：" + ADAPTATION_BRIEF["opening"], ledger)
        # The spans still cover the source end to end.
        self.assertIn(_WORDING["anchored_plan"]["anchor_order"], ledger)

    def test_only_the_window_that_holds_episode_one_is_told_how_to_open(self):
        first = prompts.build_anchored_plan_prompt(
            window="原文", window_is_final=True, overview=None, source_kind="novel", context_entries=[], target_volume=None,
            max_episodes=2, remaining_episodes=None, instructions=None, adaptation=ADAPTATION_BRIEF, opens_series=True,
        )
        later = prompts.build_anchored_plan_prompt(
            window="原文", window_is_final=True, overview=None, source_kind="novel", context_entries=[], target_volume=None,
            max_episodes=2, remaining_episodes=None, instructions=None, adaptation=ADAPTATION_BRIEF, opens_series=False,
        )
        self.assertIn("第 1 集的第一个节点就是开场戏", first)
        self.assertNotIn("第 1 集的第一个节点就是开场戏", later)
        self.assertIn("切点跟着戏走", later)

    def test_an_opening_on_exposition_is_replanned_once_with_the_reason(self):
        model = _LedgerModel(["【信息交代】林夏的身世与入学经过", "【钩子】林夏摸到录音笔，周教授已在身后"])
        state = _write_novel(model)

        self.assertEqual(model.ledger_asks, 2)
        self.assertIn("第 1 集的第一个故事节点排成了信息交代", _ledger_prompts(model)[1])
        self.assertTrue(state["ledger"][0]["story_beats"][0].startswith("【钩子】"))
        self.assertEqual(state["warnings"], [])
        self.assertEqual([entry["source_range"]["end"] for entry in state["ledger"]][-1], len(NOVEL))

    def test_an_opening_that_stays_exposition_is_kept_and_flagged(self):
        model = _LedgerModel(["【信息交代】林夏的身世与入学经过"])
        state = _write_novel(model)

        self.assertEqual(model.ledger_asks, 2, "asked again once, not until it gives in")
        self.assertEqual(state["warnings"], [_ENGINE_WORDING["warnings"]["opens_on_exposition"]])
        self.assertEqual(len(state["ledger"]), 2)
        self.assertEqual(sorted(state["episodes"]), ["1", "2"])

    def test_an_untagged_or_dramatic_opening_is_not_replanned(self):
        model = _LedgerModel(["【冲突】周教授按住林夏的手"])
        _write_novel(model)
        self.assertEqual(model.ledger_asks, 1)


class EpisodePlanTests(unittest.TestCase):
    def test_an_adapted_episode_is_told_the_rules_and_what_the_brief_settles(self):
        model = FakeModel()
        _write_novel(model)
        first, second = _plan_prompts(model, 1)[0], _plan_prompts(model, 2)[0]

        for prompt in (first, second):
            self.assertIn("**改编**", prompt)
            self.assertIn("# 改编要求", prompt)
            self.assertIn("- **叙述变成戏**", prompt)
            self.assertIn("大纲节点里有原文没有的事或话时，以原文为准", prompt)
            self.assertIn("<adaptation>", prompt)
            self.assertIn("- 主视角人物：林夏。", prompt)
            self.assertIn("- 主线目标：" + ADAPTATION_BRIEF["main_line"], prompt)
            self.assertIn("  - 录音笔里有周教授亲口承认换数据的一段话", prompt)
            self.assertNotIn("可以带过的内容", prompt, "what to skip over is the ledger's call")
            self.assertLess(prompt.index("# 改编要求"), prompt.index("# 字段写作指引"))
            self.assertNotIn("台词要多", prompt, "lines cut from a source stay the source's own")
        self.assertIn("- **第 1 集**", first)
        self.assertIn("- 主角开篇处境：" + ADAPTATION_BRIEF["situation"], first)
        self.assertNotIn("- **第 1 集**", second)
        self.assertNotIn("主角开篇处境", second)

    def test_a_drama_turns_narration_into_picture_and_a_narrated_film_keeps_it(self):
        common = dict(
            source_text="原文", episode=2, overview=None, style="", characters={}, scenes={}, props={},
            supported_durations=[5, 10], default_duration=None, episode_target_seconds=None, episode_outline=None, next_episode_outline=None,
        )
        drama = prompts.build_script_plan_prompt(source_kind="novel", **common)
        narrated = prompts.build_script_plan_prompt(source_kind="novel", creation_mode="narration", **common)
        outline = prompts.build_script_plan_prompt(source_kind="outline", **common)

        self.assertIn("不设讲故事的旁白", drama)
        self.assertIn(f"全集不超过 {_LIMIT} 个分镜", drama)
        self.assertNotIn("可按剧情语境判断写为旁白", drama)
        self.assertIn("可按剧情语境判断写为旁白", narrated)
        self.assertNotIn("不设讲故事的旁白", narrated)
        self.assertNotIn("# 改编要求", outline)
        self.assertNotIn("不设讲故事的旁白", outline)


class NarrationCheckTests(unittest.TestCase):
    @staticmethod
    def _narrated(episode: int, count: int, *, all_told: bool = False) -> str:
        told = [_scene(episode, index, utterances=[{"kind": "voiceover", "speaker": None, "text": "多年以后，她仍记得那盏灯。"}]) for index in range(1, count + 1)]
        played = [] if all_told else [_scene(episode, count + 1)]
        return json.dumps({"title": "t", "scenes": [*told, *played]}, ensure_ascii=False)

    @staticmethod
    def _played(episode: int) -> str:
        return json.dumps({"title": "t", "scenes": [_scene(episode, 1), _scene(episode, 2, speaker="周教授", text="现在回头还来得及。")]}, ensure_ascii=False)

    def test_a_narrated_plan_is_sent_back_and_a_played_retry_passes_clean(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: self._narrated(1, _LIMIT + 1) if attempt == 1 else self._played(1)
        state = _write_novel(model)

        self.assertEqual(model.plan_attempts[1], 2)
        retry = _plan_prompts(model, 1)[1]
        self.assertIn(RETRY_HEADER, retry)
        self.assertIn(f"旁白太多：这是角色开口说话的剧，{_LIMIT + 1} 个分镜用了旁白（最多 {_LIMIT} 个）", retry)
        self.assertIn("E1S01", retry)
        self.assertNotIn("too_many_narrated_shots", [v["code"] for v in state["episodes"]["1"]["violations"]])

    def test_a_plan_that_still_narrates_is_kept_and_flagged_after_one_send_back(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: self._narrated(1, _LIMIT + 1)
        state = _write_novel(model)

        self.assertEqual(model.plan_attempts[1], 2, "one send-back, then the plan is kept")
        self.assertIn("too_many_narrated_shots", [v["code"] for v in state["episodes"]["1"]["violations"]])
        self.assertNotIn("draft", state["episodes"]["1"], "a narrated episode is a note for the editor, not a quarantined draft")

    def test_narration_within_the_allowance_passes(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: self._narrated(1, _LIMIT)
        state = _write_novel(model)
        self.assertEqual(model.plan_attempts[1], 1)
        self.assertNotIn("too_many_narrated_shots", [v["code"] for v in state["episodes"]["1"]["violations"]])

    def test_a_narrated_film_and_an_authors_screenplay_are_not_checked(self):
        narrated = FakeModel()
        narrated.plan_overrides[1] = lambda attempt, prompt: self._narrated(1, _LIMIT + 2, all_told=True)
        _write_novel(narrated, creation={"creation_mode": "narration"})
        self.assertEqual(narrated.plan_attempts[1], 1)

        script = "第1集 回声\n场景1：实验室\n旁白：多年以后，她仍记得那盏灯。\n林夏：你到底瞒了什么？\n"
        author = FakeModel()
        author.plan_overrides[1] = lambda attempt, prompt: self._narrated(1, _LIMIT + 2)
        state = _engine(author).write(title="暗室回声", director_plan="", episode_count=1, source_text=script, source_kind="screenplay")
        self.assertEqual(author.plan_attempts[1], 1)
        self.assertNotIn("too_many_narrated_shots", [v["code"] for v in state["episodes"]["1"]["violations"]])


class StagedLineChecksTests(unittest.TestCase):
    def test_an_adapted_episode_without_a_key_line_is_noted_and_an_authors_script_is_not(self):
        # The note is left on a plan's last round (it never costs a call of its own).
        novel = FakeModel()
        state = _write_novel(novel, attempts=1)
        self.assertIn("no_key_line", [v["code"] for v in state["episodes"]["1"]["violations"]])

        author = FakeModel()
        state = _engine(author, attempts=1).write(title="暗室回声", director_plan="", episode_count=1, source_text=SCREENPLAY, source_kind="screenplay")
        self.assertNotIn("no_key_line", [v["code"] for v in state["episodes"]["1"]["violations"]])


if __name__ == "__main__":
    unittest.main()

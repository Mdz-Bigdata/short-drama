# -*- coding: utf-8 -*-
"""A one-episode film is read against itself: an errand run twice, a number that changes, a question left hanging.

No real model, no network. ``self_check`` asks once after the shots are planned, sends the findings back to the
planner once, and keeps what is still wrong as notes — it never costs the film its episode. It applies to the
short-film kind only, never to an author's screenplay, and ``SCREENWRITING_SELF_CHECK`` turns it off (the test
suite's default; these tests turn it on).
"""

import json
import os
import unittest
from unittest.mock import patch

from app.core import creation_modes, prompt_data
from app.core.screenwriting import review, self_check
from app.core.screenwriting.engine import ScreenwritingEngine
from app.core.screenwriting.violations import DraftViolation
from tests.test_screenwriting_engine import MINIATURE_EPISODES, FakeModel, _scene

DATA = prompt_data.load("script_self_check")
FILM = {"creation_mode": "film"}
ON = {self_check.ENABLED_ENV: "1"}
OVERVIEW = {"title": "我缝的", "synopsis": "骑手送错一单，开门的是十年没见的父亲。", "world_setting": "北方老城冬夜。", "theme": ""}
LEDGER = {"episode": 1, "hook": "清晨那扇门又开着一条缝。", "story_beats": ["【钩子】门开一条缝", "【反转】父亲推过一沓钱"]}
TWICE = {"scene_id": "E1S04", "quote": "最后一单，剩八分钟", "problem": "E1S02 已经把这一单送到并拍照", "fix": "改成客户投诉后回去道歉"}


def _answer(*findings) -> str:
    return json.dumps({"findings": list(findings)}, ensure_ascii=False)


def _plan(marker: str = "first"):
    scenes = [_scene(1, 1, text="跑错了。"), _scene(1, 2, text="最后一单，剩八分钟。")]
    return ({"title": marker, "scenes": scenes}, [DraftViolation("earlier", "已有的提示", "第 1 集", "warning")], [], None)


class GateTests(unittest.TestCase):
    def test_only_a_film_we_wrote_is_checked_and_only_while_the_switch_is_on(self):
        with patch.dict(os.environ, ON):
            self.assertTrue(self_check.applies(FILM, "outline"))
            self.assertTrue(self_check.applies(FILM, "novel"))
            self.assertFalse(self_check.applies(FILM, "screenplay"), "an author's screenplay is not ours to rewrite")
            for kind in ("drama", "narration", "ad", "", None):
                self.assertFalse(self_check.applies({"creation_mode": kind}, "outline"), kind)
        with patch.dict(os.environ, {self_check.ENABLED_ENV: "0"}):
            self.assertFalse(self_check.applies(FILM, "outline"))


class PromptTests(unittest.TestCase):
    def test_the_shots_are_read_against_the_facts_the_outline_and_each_other(self):
        settled, outline = self_check.facts(OVERVIEW, LEDGER)
        self.assertEqual(settled, ["片名：我缝的", "故事梗概：骑手送错一单，开门的是十年没见的父亲。", "世界与前史：北方老城冬夜。"])
        self.assertEqual(outline, ["- 【钩子】门开一条缝", "- 【反转】父亲推过一沓钱", "结尾：清晨那扇门又开着一条缝。"])
        prompt = self_check.build_check_prompt(episode=1, settled=settled, outline=outline, scenes=_plan()[0]["scenes"])
        for part in ("<facts>", "十年没见", "<outline>", "【反转】父亲推过一沓钱", "<shots>", "E1S02", "最后一单，剩八分钟。"):
            self.assertIn(part, prompt)
        self.assertLess(prompt.index("<facts>"), prompt.index("<outline>"))
        self.assertLess(prompt.index("<outline>"), prompt.index("<shots>"))

    def test_the_supervisor_is_told_the_three_things_to_look_for_and_nothing_else(self):
        system = DATA["system"]
        for part in ("演了两次", "接不上", "数字", "既没有回答", "拿不准的不报", '"findings"'):
            self.assertIn(part, system)

    def test_nothing_settled_reads_as_none_rather_than_an_empty_block(self):
        prompt = self_check.build_check_prompt(episode=1, settled=[], outline=[], scenes=[])
        self.assertEqual(prompt.count(DATA["none"]), 2)


class CheckTests(unittest.TestCase):
    def _check(self, answer):
        calls = []

        def caller(system, user, max_tokens):
            calls.append(user)
            return answer(len(calls)) if callable(answer) else answer

        found = self_check.check(caller, episode=1, settled=["片名：我缝的"], outline=[], scenes=_plan()[0]["scenes"])
        return found, calls

    def test_findings_come_back_worded_for_the_planner_and_the_editor(self):
        whole = {"scene_id": "", "quote": "十三年，一年一万二", "problem": "片名说十年没见", "fix": "统一成十年"}
        found, calls = self._check(_answer(TWICE, whole))
        self.assertEqual(len(calls), 1)
        self.assertEqual(found[0].reason(), "分镜 E1S04「最后一单，剩八分钟」对不上——E1S02 已经把这一单送到并拍照：改成客户投诉后回去道歉")
        self.assertEqual(found[1].reason(), "「十三年，一年一万二」对不上——片名说十年没见：统一成十年")

    def test_a_finding_without_a_quote_or_a_fix_is_dropped_and_the_list_is_capped(self):
        vague = {"scene_id": "E1S01", "quote": "", "problem": "感觉不顺", "fix": ""}
        found, _calls = self._check(_answer(vague, *[TWICE] * (DATA["max_items"] + 3)))
        self.assertEqual(len(found), DATA["max_items"])

    def test_the_call_is_given_room_to_reason_before_it_answers(self):
        asked = []

        def caller(system, user, max_tokens):
            asked.append(max_tokens)
            return _answer()

        self_check.check(caller, episode=1, settled=[], outline=[], scenes=[])
        self_check.check(caller, episode=1, settled=[], outline=[], scenes=[], max_tokens=1_000_000)
        self_check.check(caller, episode=1, settled=[], outline=[], scenes=[], max_tokens=2000)
        # A reasoning model spent 8,000 and then 16,000 tokens thinking and answered nothing: the floor is well above that.
        self.assertGreaterEqual(DATA["max_tokens"], 60000)
        self.assertEqual(asked, [DATA["max_tokens"], 1_000_000, DATA["max_tokens"]])

    def test_no_usable_answer_counts_as_agreement(self):
        found, calls = self._check("这段话不是 JSON")
        self.assertEqual(found, [])
        self.assertEqual(len(calls), 2, "asked twice, then let go")
        self.assertEqual(self._check(_answer())[0], [])


class CheckedTests(unittest.TestCase):
    def _run(self, answers, replan=None, result=None, creation=FILM, source_kind="outline"):
        asked: list[str] = []
        replans: list[dict] = []

        def caller(system, user, max_tokens):
            asked.append(user)
            return answers[min(len(asked), len(answers)) - 1]

        def again(repair):
            replans.append(repair)
            return replan(repair) if replan else _plan("second")

        with patch.dict(os.environ, ON):
            out = self_check.checked(
                result or _plan(), caller=caller, creation=creation, source_kind=source_kind, episode=1,
                overview=OVERVIEW, ledger=LEDGER, replan=again, label="第 1 集",
            )
        return out, asked, replans

    def test_a_clean_plan_costs_one_question_and_comes_back_as_it_was(self):
        first = _plan()
        out, asked, replans = self._run([_answer()], result=first)
        self.assertIs(out, first)
        self.assertEqual((len(asked), replans), (1, []))

    def test_findings_send_the_plan_back_once_and_a_mended_plan_carries_no_note(self):
        out, asked, replans = self._run([_answer(TWICE), _answer()])
        self.assertEqual(out[0]["title"], "second")
        self.assertEqual(len(asked), 2, "checked, then checked again after the rewrite")
        self.assertEqual(len(replans), 1)
        self.assertEqual(replans[0]["reasons"], [self_check.Finding(**TWICE).reason()])
        self.assertEqual(replans[0]["plan"]["title"], "first")
        self.assertEqual([note.code for note in out[1]], ["earlier"])

    def test_what_is_still_wrong_after_the_rewrite_is_a_note_not_a_reason_to_drop_the_episode(self):
        out, _asked, replans = self._run([_answer(TWICE), _answer(TWICE)])
        self.assertEqual(len(replans), 1, "sent back once only")
        notes = [note for note in out[1] if note.code == self_check.CONFLICT]
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0].severity, notes[0].scene_id, notes[0].label), ("warning", "E1S04", "第 1 集"))
        self.assertIsNone(out[3])

    def test_a_rewrite_that_fails_or_is_quarantined_leaves_the_first_plan_with_its_notes(self):
        def fails(_repair):
            raise RuntimeError("the planner could not do better")

        for replan in (fails, lambda _repair: (*_plan("second")[:3], {"reasons": ["bad"]})):
            out, asked, _replans = self._run([_answer(TWICE)], replan=replan)
            self.assertEqual(out[0]["title"], "first")
            self.assertEqual(len(asked), 1)
            self.assertEqual([note.code for note in out[1]], ["earlier", self_check.CONFLICT])

    def test_a_serial_an_authors_screenplay_and_a_quarantined_draft_are_not_asked_about(self):
        for kwargs in ({"creation": {"creation_mode": "drama"}}, {"source_kind": "screenplay"}, {"result": (*_plan()[:3], {"reasons": ["x"]})}):
            out, asked, replans = self._run([_answer(TWICE)], **kwargs)
            self.assertEqual((asked, replans), ([], []), kwargs)


class SupervisedModel(FakeModel):
    """The engine's fake model plus a script supervisor who objects to the first plan and accepts the second."""

    def __init__(self):
        super().__init__()
        self.checks = 0

    def __call__(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        if user_prompt.startswith(DATA["head"].format(episode=1)):
            self.calls.append({"system": system_prompt, "prompt": user_prompt, "max_tokens": max_tokens})
            self.checks += 1
            return _answer(TWICE) if self.checks == 1 else _answer()
        return super().__call__(system_prompt, user_prompt, max_tokens)


class EngineTests(unittest.TestCase):
    def _write(self, model, creation):
        engine = ScreenwritingEngine(
            model, video_model="seedance2.0", attempts=3, system_prompt="SYS", style="写实",
            episode_shape=MINIATURE_EPISODES, creation=creation, instructions=creation_modes.writer_guidance(creation),
        )
        return engine.write(title="借我一天", director_plan="短片策划", episode_count=1)

    def test_a_film_is_checked_rewritten_once_with_the_finding_and_stored_clean(self):
        model = SupervisedModel()
        with patch.dict(os.environ, ON):
            state = self._write(model, FILM)
        self.assertEqual(model.checks, 2)
        self.assertEqual(model.plan_attempts[1], 2, "the plan went back once")
        repair = [call["prompt"] for call in model.calls if TWICE["fix"] in call["prompt"] and "scene_description" in call["prompt"]]
        self.assertTrue(repair, "the planner was told what the supervisor found")
        codes = [violation["code"] for violation in state["episodes"]["1"]["violations"]]
        self.assertNotIn(self_check.CONFLICT, codes)
        self.assertIsNone(review.draft_of(state["episodes"]["1"]))

    def test_a_serial_and_a_film_with_the_switch_off_are_never_asked(self):
        with patch.dict(os.environ, ON):
            serial = SupervisedModel()
            self._write(serial, {"creation_mode": "drama"})
        off = SupervisedModel()
        self._write(off, FILM)
        self.assertEqual((serial.checks, off.checks), (0, 0))


class DirectorLengthTests(unittest.TestCase):
    def test_the_director_is_told_how_long_the_film_is(self):
        text = creation_modes.director_guidance(FILM)
        self.assertIn("片长按 240 秒左右规划，不少于 120 秒、不超过 480 秒", text)
        self.assertIn("片长按 300 秒左右规划", creation_modes.director_guidance({**FILM, "episode_target_duration": 300}))
        with patch.dict(os.environ, {"CREATION_FILM_MAX_SECONDS": "600"}):
            self.assertIn("不超过 600 秒", creation_modes.director_guidance(FILM))
        self.assertEqual(creation_modes.director_guidance({"creation_mode": "drama"}), "")


if __name__ == "__main__":
    unittest.main()

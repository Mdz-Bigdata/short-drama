# -*- coding: utf-8 -*-
"""电影短片: one complete episode — planned, written and checked as a film that ends, not as the first episode of a serial.

No model, no network. The kind's wording, emotion-point names and limits are ``creation_modes.json``; the
frame (how many shots, how long, how much of it must talk) has defaults that ``CREATION_FILM_*`` override.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import creation_modes, emotion_points, prompt_data, series_rhythm
from app.core.screenwriting import review
from app.core.screenwriting.engine import ScreenwritingEngine
from app.core.screenwriting.pacing import pacing_for, render_pacing_section
from app.core.screenwriting.prompts import build_outline_plan_prompt, build_script_plan_prompt, build_visual_prompt
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.service import screenwriting_service as screenwriting
from app.service.drama_service import DramaService
from tests.test_screenwriting_engine import MINIATURE_EPISODES, FakeModel, _scene

FILM = {"creation_mode": "film"}
DATA = prompt_data.load("creation_modes")
REVERSAL = DATA["film_reversal_kind"]


def _shot(index: int, point: str) -> dict:
    return {"scene_id": f"E1S{index:02d}", "emotion_point": point}


def _problems(points: list[str], config=FILM) -> dict[str, tuple]:
    found = creation_modes.plan_problems([_shot(index, point) for index, point in enumerate(points, start=1)], config)
    return {code: (message, scene_id, severity) for code, message, scene_id, severity in found}


class KindTests(unittest.TestCase):
    def test_it_is_offered_with_the_other_kinds_and_named_in_the_table(self):
        info = creation_modes.MODE_INFO["film"]
        self.assertEqual((info.label, info.description), (DATA["module.mode_info.film"], DATA["module.mode_info.film.2"]))
        self.assertEqual(creation_modes.mode_of(FILM), "film")
        self.assertIn({"id": "film", "label": info.label, "description": info.description}, creation_modes.options())
        self.assertEqual(DramaCreateRequest(titleSuggestion="借我一天", creationMode="film").creation_mode, "film")

    def test_the_table_names_emotion_points_the_planner_really_uses(self):
        self.assertIn(REVERSAL, emotion_points.KINDS)
        self.assertTrue(set(DATA["film_open_ending_kinds"]) <= set(emotion_points.KINDS))
        self.assertGreaterEqual(DATA["film_max_reversals"], 2)

    def test_a_film_is_one_episode_whatever_was_asked_for(self):
        self.assertEqual(creation_modes.episode_count_for("film", 30), 1)
        self.assertEqual(creation_modes.episode_count_for("drama", 30), 30)
        self.assertEqual(creation_modes.episode_count_for(None, 5), 5)

    def test_its_frame_is_minutes_long_and_can_be_overridden(self):
        shape = creation_modes.episode_shape_for(FILM)
        self.assertEqual((shape.min_scenes, shape.min_seconds, shape.max_seconds), (6, 120, 480))
        with patch.dict(os.environ, {"CREATION_FILM_MIN_SECONDS": "200", "CREATION_FILM_MAX_SECONDS": "900", "CREATION_FILM_MIN_SCENES": "10"}):
            longer = creation_modes.episode_shape_for(FILM)
        self.assertEqual((longer.min_scenes, longer.min_seconds, longer.max_seconds), (10, 200, 900))
        # The other kinds keep the frames they had.
        self.assertEqual(creation_modes.episode_shape_for({"creation_mode": "ad"}).max_seconds, 60)

    def test_it_aims_at_minutes_unless_the_project_names_a_length_inside_its_frame(self):
        self.assertEqual(creation_modes.episode_target_for(FILM, 90), 240, "no length named: the serial default is not a film's")
        self.assertEqual(creation_modes.episode_target_for({**FILM, "episode_target_duration": 300}, 300), 300)
        self.assertEqual(creation_modes.episode_target_for({**FILM, "episode_target_duration": 60}, 60), 120, "never under the frame")
        self.assertEqual(creation_modes.episode_target_for({"creation_mode": "drama"}, 90), 90)
        engine = screenwriting.build_engine(lambda *a, **k: "", config={**FILM, "video_model": "seedance2.0", "llm_model": "m"}, title="t", system_prompt="S", guidance="")
        self.assertEqual(engine.episode_target_seconds, 240)

    def test_it_may_be_quieter_than_a_serial_but_never_asked_to_talk_more(self):
        self.assertEqual(creation_modes.spoken_shot_ratio_for(FILM, 0.7), 0.4)
        self.assertEqual(creation_modes.spoken_shot_ratio_for(FILM, 0.2), 0.2)
        self.assertEqual(creation_modes.spoken_shot_ratio_for({"creation_mode": "drama"}, 0.7), 0.7)
        with patch.dict(os.environ, {"CREATION_FILM_SPOKEN_SHOT_RATIO": "0.1"}):
            self.assertEqual(creation_modes.spoken_shot_ratio_for(FILM, 0.7), 0.1)


class GuidanceTests(unittest.TestCase):
    def test_the_writer_is_told_what_a_film_is_made_of(self):
        text = creation_modes.writer_guidance(FILM)
        self.assertTrue(text.startswith("创作类型：电影短片"))
        for part in ("表层目标", "隐藏需求", "错误信念", "开场图像", "中点反转", "余味图像", "母题物件出现三次", "结尾必须收"):
            self.assertIn(part, text)
        self.assertIn("next_episode_teaser 为 null", text)
        self.assertEqual(text.count("\n"), len(DATA["writer_guidance.film"]) - 1)

    def test_only_a_film_changes_what_the_director_plans(self):
        self.assertIn("本片只有一集", creation_modes.director_guidance(FILM))
        for kind in ("drama", "narration", "ad", "", None):
            self.assertEqual(creation_modes.director_guidance({"creation_mode": kind}), "", kind)

    def test_the_promotion_copy_does_not_sell_a_next_episode(self):
        self.assertEqual(creation_modes.promotion_guidance(FILM), DATA["promotion_guidance.film"])
        self.assertIn("不剧透结尾", creation_modes.promotion_guidance(FILM))

    def test_a_single_episode_plan_carries_no_serial_rules(self):
        prompt = build_outline_plan_prompt(
            title="借我一天", director_plan="短片策划", overview={"genre": "情感"}, first=1, last=1, total=1,
            context_entries=[], target_seconds=240, instructions=creation_modes.writer_guidance(FILM),
        )
        self.assertIn("创作类型：电影短片", prompt)
        self.assertEqual(series_rhythm.outline_rules(1), [])
        self.assertNotIn("集尾卡点换着用", prompt)


def _script_plan(creation_mode: str, genre: str = "复仇") -> str:
    return build_script_plan_prompt(
        episode=1, overview={"title": "借我一天", "genre": genre}, style="写实", characters={"老何": {"description": "五十五岁"}},
        scenes={}, props={}, supported_durations=[5, 10], default_duration=None, episode_target_seconds=None,
        episode_outline={"story_beats": ["【钩子】a"]}, next_episode_outline=None, source_text="", source_kind="outline",
        creation_mode=creation_mode,
    )


def _visual(creation_mode: str) -> str:
    return build_visual_prompt(
        episode=1, overview={}, style="写实", style_description="电影感", characters={}, scenes={}, props={},
        content_scenes=[{"scene_id": "E1S01", "scene_description": "老何把钱递过去。", "duration_seconds": 5}], creation_mode=creation_mode,
    )


class PacingAndPayoffTests(unittest.TestCase):
    """A film reads its own pacing and never the serial payoff formula, whatever its genre."""

    FILM_PACING = render_pacing_section("film")
    DRAMA_PACING = render_pacing_section("drama")
    PAYOFF_HEAD = prompt_data.words("payoff", "formula")[0]

    def test_the_film_pacing_is_registered_and_is_about_closing(self):
        self.assertTrue(self.FILM_PACING)
        self.assertIn("余味图像", self.FILM_PACING)
        self.assertNotIn("下一集", self.FILM_PACING)
        self.assertIn("必须看下一集", self.DRAMA_PACING, "the serial's pacing still asks for the next episode")
        self.assertEqual(pacing_for("film"), self.FILM_PACING)
        for kind in ("drama", "narration", "ad", "", None):
            self.assertEqual(pacing_for(kind), self.DRAMA_PACING, kind)

    def test_the_script_and_the_visual_layer_of_a_film_follow_the_film_pacing(self):
        for prompt in (_script_plan("film"), _visual("film")):
            self.assertIn(self.FILM_PACING, prompt)
            self.assertNotIn(self.DRAMA_PACING, prompt)
        for prompt in (_script_plan("drama"), _visual("drama")):
            self.assertIn(self.DRAMA_PACING, prompt)
            self.assertNotIn(self.FILM_PACING, prompt)

    def test_a_revenge_film_is_not_handed_the_serial_payoff_formula(self):
        self.assertIn(self.PAYOFF_HEAD, _script_plan("drama"), "the genre does trigger the formula for a serial")
        self.assertNotIn(self.PAYOFF_HEAD, _script_plan("film"))
        outline = dict(
            title="借我一天", director_plan="策划", overview={"genre": "复仇"}, first=1, last=1, total=1,
            context_entries=[], target_seconds=240, instructions=None,
        )
        self.assertIn(self.PAYOFF_HEAD, build_outline_plan_prompt(**outline))
        self.assertNotIn(self.PAYOFF_HEAD, build_outline_plan_prompt(**outline, creation_mode="film"))


class PlanCheckTests(unittest.TestCase):
    def test_a_last_shot_that_asks_a_question_is_pointed_out(self):
        for kind in DATA["film_open_ending_kinds"]:
            found = _problems(["冲突", REVERSAL, kind])
            message, scene_id, severity = found[creation_modes.FILM_OPEN_ENDING]
            with self.subTest(kind=kind):
                self.assertEqual((scene_id, severity), ("E1S03", "warning"))
                self.assertIn(f"「{kind}」", message)

    def test_a_film_that_closes_with_its_turns_in_place_passes(self):
        self.assertEqual(_problems(["钩子", "冲突", REVERSAL, "泪点", REVERSAL, "抒情"]), {})

    def test_no_turn_at_all_or_too_many_is_pointed_out(self):
        none = _problems(["冲突", "泪点", "抒情"])
        self.assertIn("没有一个分镜", none[creation_modes.FILM_REVERSALS][0])
        many = _problems([REVERSAL] * (DATA["film_max_reversals"] + 1) + ["抒情"])
        self.assertIn(f"{DATA['film_max_reversals'] + 1} 个分镜", many[creation_modes.FILM_REVERSALS][0])
        self.assertEqual(_problems([REVERSAL] * DATA["film_max_reversals"] + ["抒情"]), {})

    def test_an_untagged_plan_is_not_judged_on_turns_it_never_labelled(self):
        self.assertEqual(_problems(["", "", ""]), {})

    def test_every_finding_is_a_hint_and_other_kinds_are_left_alone(self):
        found = _problems(["冲突", "悬念"])
        self.assertTrue(found)
        self.assertEqual({severity for _message, _scene, severity in found.values()}, {"warning"})
        self.assertEqual(_problems(["冲突", "悬念"], {"creation_mode": "drama"}), {})


class EngineTests(unittest.TestCase):
    def test_the_engine_built_for_a_film_carries_its_frame_its_guidance_and_its_quiet(self):
        engine = screenwriting.build_engine(lambda *a, **k: "", config={**FILM, "video_model": "seedance2.0", "llm_model": "m"}, title="t", system_prompt="S", guidance="多用长镜头")
        self.assertEqual(engine.creation["creation_mode"], "film")
        self.assertEqual((engine.episode_shape.min_seconds, engine.episode_shape.max_seconds), (120, 480))
        self.assertTrue(engine.instructions.startswith("创作类型：电影短片"))
        self.assertTrue(engine.instructions.endswith("多用长镜头"))
        self.assertLessEqual(engine.spoken_shot_ratio, 0.4)

    def test_an_open_ending_is_a_warning_on_the_episode_not_a_reason_to_rewrite_it(self):
        model = FakeModel()
        points = ["钩子", "冲突", REVERSAL, "悬念"]
        shots = [_scene(1, index, text=f"第{index}句", duration=6, emotion_point=point) for index, point in enumerate(points, start=1)]
        model.plan_overrides[1] = lambda attempt, prompt: json.dumps({"title": "借我一天", "scenes": shots}, ensure_ascii=False)
        engine = ScreenwritingEngine(
            model, video_model="seedance2.0", attempts=3, system_prompt="SYS", style="写实",
            episode_shape=MINIATURE_EPISODES, creation=FILM, instructions=creation_modes.writer_guidance(FILM),
        )
        state = engine.write(title="借我一天", director_plan="短片策划", episode_count=1)

        self.assertEqual(model.plan_attempts[1], 1, "a hint does not send the plan back")
        codes = [violation["code"] for violation in state["episodes"]["1"]["violations"]]
        self.assertIn(creation_modes.FILM_OPEN_ENDING, codes)
        self.assertIsNone(review.draft_of(state["episodes"]["1"]))
        self.assertEqual(len(state["ledger"]), 1)


class ProjectTests(unittest.TestCase):
    def test_a_film_project_is_stored_with_one_episode(self):
        with tempfile.TemporaryDirectory() as temp:
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            film = service.create_task(DramaCreateRequest(titleSuggestion="借我一天", creationMode="film", episodeCount=12), owner_user_id="u1")
            serial = service.create_task(DramaCreateRequest(titleSuggestion="铁血人生", creationMode="drama", episodeCount=12), owner_user_id="u1")
            stored = {name: service.repo.get_task(task.get("task_id") or task.get("taskId"))["config"] for name, task in (("film", film), ("serial", serial))}
        self.assertEqual((stored["film"]["creation_mode"], stored["film"]["episode_count"]), ("film", 1))
        self.assertEqual(stored["serial"]["episode_count"], 12)


if __name__ == "__main__":
    unittest.main()

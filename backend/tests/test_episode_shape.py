"""An episode is more than one shot and at least a minute of film."""

import json
import os
import unittest
from unittest.mock import patch

from app.core.episode_shape import EpisodeShape, configured_episode_shape
from app.core.screenwriting import violations
from app.core.screenwriting.engine import ScreenwritingError
from app.core.screenwriting.structured_llm import RETRY_HEADER
from app.core.writer_dashboard import compile_writer_dashboard
from tests.test_long_form_script_generation import _BreakdownGateway, _episode_text, _service
from tests.test_screenwriting_engine import FakeModel, _engine, _scene

REAL_EPISODES = EpisodeShape()


def _codes(issues) -> list[str]:
    return [issue.code for issue in issues]


class EpisodeShapeRuleTests(unittest.TestCase):
    def test_one_eight_second_shot_is_neither_enough_shots_nor_enough_film(self):
        issues = REAL_EPISODES.issues(scene_count=1, total_seconds=8)

        self.assertEqual(_codes(issues), ["episode_too_few_scenes", "episode_too_short"])
        self.assertTrue(all(issue.severity == "error" for issue in issues))
        self.assertIn("至少需要 2 个", issues[0].message)
        self.assertIn("不能少于 60 秒", issues[1].message)

    def test_two_shots_adding_up_to_a_minute_are_an_episode(self):
        self.assertEqual(REAL_EPISODES.issues(scene_count=2, total_seconds=60), [])
        self.assertEqual(REAL_EPISODES.issues(scene_count=24, total_seconds=360), [])

    def test_just_under_a_minute_is_still_too_short(self):
        self.assertEqual(_codes(REAL_EPISODES.issues(scene_count=6, total_seconds=59)), ["episode_too_short"])

    def test_past_six_minutes_is_advised_against_but_not_refused(self):
        issues = REAL_EPISODES.issues(scene_count=30, total_seconds=361)

        self.assertEqual(_codes(issues), ["episode_over_recommended"])
        self.assertEqual(issues[0].severity, "warning")

    def test_a_deployment_can_move_the_frame_but_never_invert_it(self):
        with patch.dict(os.environ, {
            "SCREENWRITING_EPISODE_MIN_SCENES": "3",
            "SCREENWRITING_EPISODE_MIN_SECONDS": "120",
            "SCREENWRITING_EPISODE_MAX_SECONDS": "90",
        }):
            shape = configured_episode_shape()

        self.assertEqual((shape.min_scenes, shape.min_seconds, shape.max_seconds), (3, 120, 120))
        with patch.dict(os.environ, {
            "SCREENWRITING_EPISODE_MIN_SCENES": "", "SCREENWRITING_EPISODE_MIN_SECONDS": "", "SCREENWRITING_EPISODE_MAX_SECONDS": "",
        }):
            self.assertEqual(configured_episode_shape(), REAL_EPISODES)


def _minute_plan(episode: int) -> str:
    """Four fifteen-second shots: the smallest well-formed episode a 15 s model can film."""
    scenes = [_scene(episode, index, duration=15) for index in (1, 2, 3, 4)]
    return json.dumps({"title": "对峙", "scenes": scenes}, ensure_ascii=False)


def _one_shot_plan(episode: int) -> str:
    return json.dumps({"title": "对峙", "scenes": [_scene(episode, 1, duration=8)]}, ensure_ascii=False)


class StructuredEngineTests(unittest.TestCase):
    def test_plan_validation_reports_the_whole_episode_only_when_asked_to(self):
        scenes = json.loads(_one_shot_plan(3))["scenes"]
        context = dict(episode=3, supported_durations=list(range(4, 16)))

        shots_only = violations.check_script_plan(
            json.loads(json.dumps(scenes)), violations.PlanCheckContext(**context))
        whole_episode = violations.check_script_plan(
            json.loads(json.dumps(scenes)), violations.PlanCheckContext(**context, episode_shape=REAL_EPISODES))

        self.assertEqual(shots_only.errors, [])
        self.assertEqual({v.code for v in whole_episode.errors}, violations.EPISODE_SHAPE_CODES)
        self.assertTrue(all(v.label == "第 3 集" for v in whole_episode.errors))

    def test_a_one_shot_episode_is_sent_back_with_the_reason_until_it_is_an_episode(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: _one_shot_plan(1) if attempt == 1 else _minute_plan(1)

        state = _engine(model, episode_shape=REAL_EPISODES).write(title="暗室回声", director_plan="三幕大纲", episode_count=1)

        self.assertEqual(model.plan_attempts[1], 2)
        retry = next(call["prompt"] for call in model.calls if RETRY_HEADER in call["prompt"] and "scene_description" in call["prompt"])
        self.assertIn("本集只有 1 个分镜，至少需要 2 个", retry)
        self.assertIn("不能少于 60 秒", retry)
        scenes = state["episodes"]["1"]["script"]["scenes"]
        self.assertEqual(len(scenes), 4)
        self.assertEqual(sum(scene["duration_seconds"] for scene in scenes), 60)

    def test_the_planning_prompt_states_the_frame_before_the_model_is_checked_against_it(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: _minute_plan(1)

        _engine(model, episode_shape=REAL_EPISODES).write(title="暗室回声", director_plan="三幕大纲", episode_count=1)

        plan_prompt = next(call["prompt"] for call in model.calls if "scene_description" in call["prompt"])
        self.assertIn("本集至少 2 个分镜，各分镜时长合计不少于 60 秒", plan_prompt)
        self.assertIn("60–360 秒", plan_prompt)

    def test_an_episode_the_model_keeps_writing_too_short_fails_rather_than_being_kept(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: _one_shot_plan(1)

        with self.assertRaisesRegex(ScreenwritingError, "第 1 集分镜内容规划失败"):
            _engine(model, episode_shape=REAL_EPISODES).write(title="暗室回声", director_plan="三幕大纲", episode_count=1)
        self.assertEqual(model.plan_attempts[1], 3)

    def test_a_person_may_save_a_short_episode_and_is_told_what_is_missing(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: _minute_plan(1)
        engine = _engine(model, episode_shape=REAL_EPISODES)
        state = engine.write(title="暗室回声", director_plan="三幕大纲", episode_count=1)
        shortened = [dict(scene) for scene in state["episodes"]["1"]["script"]["scenes"][:1]]

        new_state, _rewritten = engine.replace_plan(state, 1, shortened)

        entry = new_state["episodes"]["1"]
        self.assertEqual(len(entry["script"]["scenes"]), 1)
        self.assertTrue(violations.EPISODE_SHAPE_CODES <= {warning["code"] for warning in entry["violations"]})


class _OneBadEpisodeGateway(_BreakdownGateway):
    """Answers episode ``bad`` with a single eight-second shot until told what was wrong with it."""

    def __init__(self, bad: int, *, learns: bool = True):
        super().__init__()
        self.bad = bad
        self.learns = learns

    def call_llm(self, model, system_prompt, user_prompt, title,
                 director_style="", shot_style="", user_instruction="", max_tokens=None):
        answer = json.loads(super().call_llm(
            model, system_prompt, user_prompt, title, director_style, shot_style, user_instruction, max_tokens))
        if self.learns and "上一次拆分不合格" in user_prompt:
            return json.dumps(answer, ensure_ascii=False)
        prefix = f"E{self.bad}S"
        kept = [scene for scene in answer["scenes"] if not scene["scene_id"].startswith(prefix)]
        if len(kept) != len(answer["scenes"]):
            kept.append({"scene_id": f"{prefix}01", "duration": "8s", "content": "一镜带过", "characters": ["陈九"]})
        answer["scenes"] = kept
        return json.dumps(answer, ensure_ascii=False)


class LegacyBreakdownTests(unittest.TestCase):
    @staticmethod
    def _breakdown(gateway, episode_count: int):
        script = "".join(_episode_text(index) for index in range(1, episode_count + 1))
        return _service(gateway)._extract_script_breakdown(
            {"llm_model": "m", "video_model": "seedance2.0"}, "流氓天子", "palace", "cinematic", script,
        )

    @staticmethod
    def _episode(breakdown, episode: int):
        return [scene for scene in breakdown["scenes"] if scene["scene_id"].startswith(f"E{episode}S")]

    def test_the_contract_states_the_frame(self):
        gateway = _BreakdownGateway()
        self._breakdown(gateway, 3)

        self.assertIn("本集至少 2 个分镜，各分镜时长合计不少于 60 秒", gateway.calls[0]["system_prompt"])

    def test_a_one_shot_episode_is_restructured_on_its_own(self):
        for episode_count in (3, 9):
            gateway = _OneBadEpisodeGateway(bad=3)
            breakdown = self._breakdown(gateway, episode_count)

            third = self._episode(breakdown, 3)
            self.assertEqual([scene["duration"] for scene in third], ["15s"] * 4, episode_count)
            corrections = [call for call in gateway.calls if "上一次拆分不合格" in call["user_prompt"]]
            self.assertEqual(len(corrections), 1, episode_count)
            self.assertIn("本集只有 1 个分镜", corrections[0]["user_prompt"])
            self.assertIn("第 3 集到第 3 集", corrections[0]["user_prompt"])
            # Every other episode is untouched and still in story order.
            self.assertEqual(len(breakdown["scenes"]), episode_count * 4, episode_count)
            self.assertEqual(
                [scene["scene_id"] for scene in breakdown["scenes"]],
                sorted((scene["scene_id"] for scene in breakdown["scenes"]), key=lambda value: (int(value[1:].split("S")[0]), value)),
            )

    def test_a_second_bad_answer_keeps_what_the_first_one_had(self):
        gateway = _OneBadEpisodeGateway(bad=2, learns=False)
        breakdown = self._breakdown(gateway, 3)

        self.assertEqual([scene["content"] for scene in self._episode(breakdown, 2)], ["一镜带过"])
        self.assertEqual(len([call for call in gateway.calls if "上一次拆分不合格" in call["user_prompt"]]), 1)

    def test_well_formed_episodes_cost_no_extra_call(self):
        gateway = _BreakdownGateway()
        self._breakdown(gateway, 3)

        self.assertEqual(len(gateway.calls), 1)


class DashboardTests(unittest.TestCase):
    @staticmethod
    def _dashboard(scenes):
        script = "\n".join(f"第{index}集 标题{index}\n林夏：第{index}句。" for index in (1, 2, 3))
        task = {
            "task_id": "shape-1",
            "config": {"title_suggestion": "回到明朝当皇帝", "episode_count": 3},
            "assets": {"2": script, "2_breakdown": {"scenes": scenes}},
        }
        return {episode.index: episode for episode in compile_writer_dashboard(task).episodes}

    def test_the_overview_names_what_is_wrong_with_a_one_shot_episode(self):
        scenes = [{"scene_id": f"E1S{shot:02d}", "duration": "15s", "content": "镜头", "characters": []} for shot in (1, 2, 3, 4)]
        scenes += [{"scene_id": f"E2S{shot:02d}", "duration": "15s", "content": "镜头", "characters": []} for shot in (1, 2, 3, 4)]
        scenes.append({"scene_id": "E3S01", "duration": "8s", "content": "一镜带过", "characters": []})

        episodes = self._dashboard(scenes)

        self.assertEqual(episodes[1].issues, [])
        self.assertEqual((episodes[3].scene_count, episodes[3].duration_seconds), (1, 8))
        self.assertEqual(_codes(episodes[3].issues), ["episode_too_few_scenes", "episode_too_short"])

    def test_shots_without_an_estimated_length_are_not_called_a_short_episode(self):
        # Shots taken from the script text carry no durations: nothing to judge the running time by.
        scenes = [{"scene_id": f"E1S{shot:02d}", "duration": "", "content": "镜头", "characters": []} for shot in (1, 2, 3)]
        scenes.append({"scene_id": "E2S01", "duration": "", "content": "镜头", "characters": []})

        episodes = self._dashboard(scenes)

        self.assertEqual(episodes[1].issues, [])
        self.assertEqual(_codes(episodes[2].issues), ["episode_too_few_scenes"])


if __name__ == "__main__":
    unittest.main()

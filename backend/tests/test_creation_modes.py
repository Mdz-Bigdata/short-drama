"""Drama, narration and ad: the kind of film changes how episodes are planned and checked."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import creation_modes
from app.core.screenwriting import review
from app.core.screenwriting.engine import ScreenwritingEngine
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.service import screenwriting_service as screenwriting
from app.service.drama_service import DramaService
from tests.test_screenwriting_engine import MINIATURE_EPISODES, FakeModel, _scene

AD = {"creation_mode": "ad", "ad_brief": {"product": "静音吹风机", "selling_points": "三分钟速干，45 分贝", "audience": "合租年轻人", "call_to_action": "立即下单"}}


def _voiceover(episode: int, index: int, text: str = "那一夜，她终于明白了真相。", **extra) -> dict:
    return _scene(episode, index, utterances=[{"kind": "voiceover", "text": text}], characters_in_scene=["林夏"], **extra)


def _engine(model: FakeModel, creation: dict, shape=MINIATURE_EPISODES) -> ScreenwritingEngine:
    return ScreenwritingEngine(
        model, video_model="seedance2.0", attempts=3, system_prompt="SYS", style="写实",
        episode_shape=shape, creation=creation, instructions=creation_modes.writer_guidance(creation),
    )


class ModeRulesTests(unittest.TestCase):
    def test_the_mode_defaults_to_drama_and_unknown_values_fall_back(self):
        self.assertEqual(creation_modes.mode_of({}), "drama")
        self.assertEqual(creation_modes.mode_of({"creation_mode": "musical"}), "drama")
        self.assertEqual(creation_modes.mode_of(AD), "ad")
        self.assertEqual(creation_modes.writer_guidance({}), "")
        self.assertEqual([o["id"] for o in creation_modes.options()], ["drama", "narration", "ad"])

    def test_an_ad_has_its_own_short_frame_and_a_drama_keeps_the_deployments(self):
        shape = creation_modes.episode_shape_for(AD)
        self.assertEqual((shape.min_scenes, shape.min_seconds, shape.max_seconds), (3, 15, 60))
        with patch.dict("os.environ", {"CREATION_AD_MAX_SECONDS": "30"}):
            self.assertEqual(creation_modes.episode_shape_for(AD).max_seconds, 30)
        with patch.dict("os.environ", {"SCREENWRITING_EPISODE_MIN_SECONDS": "90"}):
            self.assertEqual(creation_modes.episode_shape_for({"creation_mode": "narration"}).min_seconds, 90)

    def test_narration_forbids_character_lines_and_an_ad_wants_its_call_to_action_last(self):
        narration = {"creation_mode": "narration"}
        found = creation_modes.plan_problems([_scene(1, 1), _voiceover(1, 2)], narration)
        self.assertEqual([(code, scene_id, severity) for code, _, scene_id, severity in found], [(creation_modes.NARRATION_DIALOGUE, "E1S01", "error")])
        self.assertEqual(creation_modes.plan_problems([_voiceover(1, 1)], narration), [])

        without = creation_modes.plan_problems([_scene(1, 1), _scene(1, 2, text="真的好安静")], AD)
        self.assertEqual([(code, severity) for code, _, _, severity in without], [(creation_modes.AD_MISSING_CTA, "warning")])
        with_cta = creation_modes.plan_problems([_scene(1, 1), _scene(1, 2, text="现在就立即下单！")], AD)
        self.assertEqual(with_cta, [])

    def test_guidance_carries_the_brief_and_promotion_follows_the_kind(self):
        guidance = creation_modes.writer_guidance(AD)
        self.assertIn("广告短片", guidance)
        self.assertIn("产品：静音吹风机", guidance)
        self.assertIn("行动号召：立即下单", guidance)
        self.assertIn("角色在画面里只做动作", creation_modes.writer_guidance({"creation_mode": "narration"}))
        self.assertIn("立即下单", creation_modes.promotion_guidance(AD))
        self.assertIn("旁白解说", creation_modes.promotion_guidance({"creation_mode": "narration"}))
        self.assertEqual(creation_modes.promotion_guidance({}), "")


class EngineModeTests(unittest.TestCase):
    def test_a_narrated_episode_is_planned_with_voiceover_only(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: json.dumps({"title": "回声", "scenes": [_voiceover(1, 1), _voiceover(1, 2, text="她没有回头。")]}, ensure_ascii=False)
        state = _engine(model, {"creation_mode": "narration"}).write(title="暗室回声", director_plan="大纲", episode_count=1)

        self.assertEqual(model.plan_attempts[1], 1)
        self.assertIsNone(review.draft_of(state["episodes"]["1"]))
        plan_prompt = next(c["prompt"] for c in model.calls if "当前正在生成第 1 集" in c["prompt"] and "scene_description" in c["prompt"])
        self.assertIn("创作类型：旁白解说", plan_prompt)

    def test_character_lines_in_a_narrated_episode_are_sent_back_then_quarantined(self):
        model = FakeModel()  # the default plan has the heroine speak
        state = _engine(model, {"creation_mode": "narration"}).write(title="暗室回声", director_plan="大纲", episode_count=1)

        self.assertEqual(model.plan_attempts[1], 3)
        draft = review.draft_of(state["episodes"]["1"])
        self.assertTrue(any("旁白解说模式下角色不开口" in reason for reason in draft["reasons"]))
        codes = [v["code"] for v in state["episodes"]["1"]["violations"]]
        self.assertIn(creation_modes.NARRATION_DIALOGUE, codes)

    def test_an_ad_episode_is_held_to_the_ad_frame_and_flagged_without_its_call_to_action(self):
        model = FakeModel()
        shots = [_scene(1, i, text=f"第{i}句", duration=6) for i in range(1, 4)]
        model.plan_overrides[1] = lambda attempt, prompt: json.dumps({"title": "安静的早晨", "scenes": shots}, ensure_ascii=False)
        state = _engine(model, AD, shape=creation_modes.episode_shape_for(AD)).write(title="静音吹风机", director_plan="大纲", episode_count=1)

        self.assertEqual(model.plan_attempts[1], 1, "three six-second shots fit the ad frame")
        warnings = [v for v in state["episodes"]["1"]["violations"] if v["code"] == creation_modes.AD_MISSING_CTA]
        self.assertEqual(len(warnings), 1)
        self.assertIsNone(review.draft_of(state["episodes"]["1"]), "a missing call to action is a warning, not a draft")
        plan_prompt = next(c["prompt"] for c in model.calls if "当前正在生成第 1 集" in c["prompt"] and "scene_description" in c["prompt"])
        self.assertIn("产品：静音吹风机", plan_prompt)
        self.assertIn("15", plan_prompt, "the planning prompt states the ad frame")

    def test_the_engine_built_for_a_project_carries_its_kind(self):
        engine = screenwriting.build_engine(lambda *a, **k: "", config={**AD, "video_model": "seedance2.0", "llm_model": "m"}, title="t", system_prompt="S", guidance="多用特写")
        self.assertEqual(engine.creation["creation_mode"], "ad")
        self.assertEqual(engine.episode_shape.max_seconds, 60)
        self.assertTrue(engine.instructions.startswith("创作类型：广告短片"))
        self.assertTrue(engine.instructions.endswith("多用特写"))


class ProjectConfigTests(unittest.TestCase):
    def test_a_project_is_created_with_its_kind_and_brief(self):
        with tempfile.TemporaryDirectory() as temp:
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            request = DramaCreateRequest(titleSuggestion="静音吹风机", creationMode="ad", adBrief={"product": "静音吹风机", "callToAction": "立即下单"})
            task = service.create_task(request, owner_user_id="u1")
            stored = service.repo.get_task(task["task_id"] if "task_id" in task else task["taskId"])
        self.assertEqual(stored["config"]["creation_mode"], "ad")
        self.assertEqual(stored["config"]["ad_brief"]["call_to_action"], "立即下单")
        self.assertEqual(DramaCreateRequest(titleSuggestion="一部剧").creation_mode, "drama")


if __name__ == "__main__":
    unittest.main()

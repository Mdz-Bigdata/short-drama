"""Each stage of the structured writer pays only for what it uses: a sampled source, its own
system prompt and sampling temperature, and visual retries that fill gaps instead of starting over."""

import json
import re
import unittest
from unittest.mock import patch

from app.core import llm_profile
from app.core.model_gateway import ModelGateway
from app.core.screenwriting.engine import STAGE_TEMPERATURES
from app.core.screenwriting.prompts import OMITTED_MARK, sample_source
from app.core.screenwriting.structured_llm import call_structured
from app.core.screenwriting.violations import TOO_FEW_SPOKEN_SHOTS, spoken_shot_problem
from app.service import screenwriting_service as screenwriting
from tests.test_screenwriting_engine import FakeModel, _engine, _scene, _visual


class SourceSamplingTests(unittest.TestCase):
    def test_a_short_source_is_read_whole(self):
        self.assertEqual(sample_source("第一章 开始。\n\n第二章 结束。", 1000), "第一章 开始。\n\n第二章 结束。")

    def test_a_long_source_keeps_its_opening_middle_and_ending_within_budget(self):
        chapters = [f"第{n}章 " + ("故事内容" * 300) + "\n\n" for n in range(1, 201)]
        text = "".join(chapters)
        sampled = sample_source(text, 20000)
        self.assertLess(len(sampled), 20000 * 1.1)
        self.assertTrue(sampled.startswith("第1章"))
        self.assertIn("第200章", sampled)
        self.assertTrue(any(f"第{n}章" in sampled for n in range(60, 141)), "an excerpt from the middle")
        marks = re.findall(OMITTED_MARK.replace("{count}", r"(\d+)").replace("（", r"（").replace("）", r"）"), sampled)
        self.assertGreaterEqual(len(marks), 2, "skipped stretches are marked")
        self.assertGreater(sum(int(m) for m in marks), len(text) - 20000 * 1.1)

    def test_the_analysis_stages_read_the_sample_and_the_planner_the_whole(self):
        model = FakeModel()
        novel = "林夏推开实验室的门。" + ("周教授没有回头。" * 2000) + "录音笔还在转。"
        _engine(model, analysis_chars=3000).write(title="暗室回声", director_plan="", episode_count=2, source_text=novel, source_kind="novel")
        overview = next(c["prompt"] for c in model.calls if "提炼项目概述" in c["prompt"])
        inventory = next(c["prompt"] for c in model.calls if "角色与世界观分析师" in c["prompt"])
        self.assertLess(len(overview), 3000 + 1500)
        self.assertLess(len(inventory), 3000 + 4500, "a sample plus the fixed instructions (five asset kinds and relations), far short of the whole source")
        self.assertIn("录音笔还在转", overview, "the ending survives the sampling")
        planner = next(c["prompt"] for c in model.calls if "end_anchor" in c["prompt"])
        self.assertGreater(len(planner), len(novel), "the ledger planner still reads the source itself")


class StagePromptTests(unittest.TestCase):
    def test_each_stage_sends_its_own_system_prompt_and_falls_back_to_the_shared_one(self):
        model = FakeModel()
        _engine(model, system_prompts={"extract": "EXTRACT", "visual": "VISUAL", "prose": "PROSE"}).write(
            title="暗室回声", director_plan="大纲", episode_count=1,
        )
        by_kind = {}
        for call in model.calls:
            prompt = call["prompt"]
            kind = ("extract" if "提炼项目概述" in prompt or "角色与世界观分析师" in prompt else
                    "visual" if "视觉生产层" in prompt else "prose" if "小说体剧本正文" in prompt else "write")
            by_kind.setdefault(kind, set()).add(call["system"])
        self.assertEqual(by_kind["extract"], {"EXTRACT"})
        self.assertEqual(by_kind["visual"], {"VISUAL"})
        self.assertEqual(by_kind["prose"], {"PROSE"})
        self.assertEqual(by_kind["write"], {"SYS"}, "ledger and plan calls keep the shared prompt")

    def test_the_service_builds_lean_prompts_for_extraction_and_visuals(self):
        prompts = screenwriting.writer_system_prompts("Role: 编剧", "山音规范" * 50)
        self.assertEqual(set(prompts), {"ledger", "plan", "prose", "visual", "extract"})
        self.assertEqual(prompts["plan"], prompts["prose"])
        self.assertEqual(prompts["plan"], prompts["ledger"])
        for prompt in prompts.values():
            self.assertTrue(prompt.startswith("Role: 编剧"))
            self.assertIn("单句不超过 15 个字", prompt)
        # The methodology line names the golden structure everywhere; only the writing prompts carry the section itself.
        self.assertIn("【黄金叙事结构", prompts["plan"])
        self.assertIn("山音超级编剧", prompts["plan"])
        self.assertNotIn("【黄金叙事结构", prompts["visual"])
        self.assertNotIn("山音超级编剧", prompts["visual"])
        self.assertIn("【表演细节", prompts["visual"])
        self.assertNotIn("【表演细节", prompts["extract"])
        self.assertLess(len(prompts["extract"]), len(prompts["visual"]))
        self.assertLess(len(prompts["visual"]), len(prompts["plan"]))

    def test_build_engine_wires_the_stage_prompts(self):
        prompts = {"extract": "E", "plan": "P", "prose": "R", "visual": "V", "ledger": "L"}
        engine = screenwriting.build_engine(lambda *a, **k: "", config={}, title="t", system_prompt="P", system_prompts=prompts)
        self.assertEqual(engine._system("extract"), "E")
        self.assertEqual(engine._system("visual"), "V")
        self.assertEqual(engine._system("unknown"), "P")
        self.assertFalse(engine.prose_chain)
        self.assertEqual(engine.analysis_chars, 48000)


class TemperatureTests(unittest.TestCase):
    class RecordingModel(FakeModel):
        def __init__(self):
            super().__init__()
            self.temperatures: dict[str, set] = {}

        def __call__(self, system_prompt, user_prompt, max_tokens):
            kind = ("extract" if "提炼项目概述" in user_prompt or "角色与世界观分析师" in user_prompt else
                    "visual" if "视觉生产层" in user_prompt else "prose" if "小说体剧本正文" in user_prompt else
                    "plan" if "字段写作指引" in user_prompt else "ledger")
            self.temperatures.setdefault(kind, set()).add(llm_profile.current_temperature())
            return super().__call__(system_prompt, user_prompt, max_tokens)

    def test_each_stage_runs_at_its_own_temperature(self):
        model = self.RecordingModel()
        _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=1)
        self.assertEqual(model.temperatures["extract"], {STAGE_TEMPERATURES["extract"]})
        self.assertEqual(model.temperatures["ledger"], {STAGE_TEMPERATURES["ledger"]})
        self.assertEqual(model.temperatures["plan"], {STAGE_TEMPERATURES["plan"]})
        self.assertEqual(model.temperatures["prose"], {STAGE_TEMPERATURES["prose"]})
        self.assertEqual(model.temperatures["visual"], {STAGE_TEMPERATURES["visual"]})
        self.assertIsNone(llm_profile.current_temperature(), "the scope ends with the call")

    def test_a_plan_cut_from_a_source_runs_cooler_than_one_written_from_an_outline(self):
        model = self.RecordingModel()
        novel = "林夏推开实验室的门。" + "周教授没有回头。" * 20 + "录音笔还在转。"
        _engine(model, temperatures={"plan_source": 0.1}).write(title="暗室回声", director_plan="", episode_count=2, source_text=novel, source_kind="novel")
        self.assertEqual(model.temperatures["plan"], {0.1})

    def test_the_scope_reaches_the_gateway_request(self):
        gateway = ModelGateway()
        payloads = []

        class _Response:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

        def post(url, json=None, **kwargs):
            payloads.append(json)
            return _Response()

        with patch("requests.post", side_effect=post), patch.object(gateway, "_is_host_broken", return_value=False), patch.object(gateway, "_proxies_for", return_value=None):
            gateway._http_chat("key", "https://api.example.com/v1", "m", "S", "U")
            with llm_profile.temperature_scope(0.25):
                gateway._http_chat("key", "https://api.example.com/v1", "m", "S", "U")
            gateway._http_chat("key", "https://api.example.com/v1", "m", "S", "U", temperature=1.1)
        self.assertEqual([p["temperature"] for p in payloads], [0.7, 0.25, 1.1])

    def test_call_structured_scopes_the_temperature_around_each_round(self):
        seen = []

        def caller(system, user, max_tokens):
            seen.append(llm_profile.current_temperature())
            return json.dumps({"text": "x"})

        from pydantic import BaseModel

        class Probe(BaseModel):
            text: str

        call_structured(caller, system_prompt="S", user_prompt="U", schema=Probe, max_tokens=100, temperature=0.2)
        call_structured(caller, system_prompt="S", user_prompt="U", schema=Probe, max_tokens=100)
        self.assertEqual(seen, [0.2, None])


class VisualGapFillingTests(unittest.TestCase):
    class GappyModel(FakeModel):
        """The visual layer leaves out the last shot once, then answers only for what was missing."""

        def __init__(self):
            super().__init__()
            self.visual_rounds = 0

        def __call__(self, system_prompt, user_prompt, max_tokens):
            if "视觉生产层" not in user_prompt:
                return super().__call__(system_prompt, user_prompt, max_tokens)
            self.calls.append({"system": system_prompt, "prompt": user_prompt, "max_tokens": max_tokens})
            self.visual_rounds += 1
            ids = re.findall(r"^### (E\d+S\d+(?:_\d+)?)", user_prompt, re.M)
            if self.visual_rounds == 1:
                return json.dumps({"title": "", "scenes": [_visual(sid) for sid in ids[:-1]] + [_visual("E9S99")]}, ensure_ascii=False)
            missing = re.search(r"缺少这些分镜的视觉层：([^（\n]+)", user_prompt).group(1).split(", ")
            return json.dumps({"title": "", "scenes": [_visual(sid) for sid in missing]}, ensure_ascii=False)

    def test_a_retry_only_has_to_fill_the_gap(self):
        model = self.GappyModel()
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=1)
        self.assertEqual(model.visual_rounds, 2)
        retry = [c["prompt"] for c in model.calls if "视觉生产层" in c["prompt"]][1]
        self.assertIn("缺少这些分镜的视觉层：E1S02（只需补齐这些分镜", retry)
        self.assertIn("E9S99", retry, "the stray id is named so the model copies ids from the shots")
        scenes = state["episodes"]["1"]["script"]["scenes"]
        self.assertEqual([s["scene_id"] for s in scenes], ["E1S01", "E1S02"])
        self.assertTrue(all(s["image_prompt"]["scene"].startswith(s["scene_id"]) for s in scenes), "both shots carry model-written prompts")
        self.assertFalse([v for v in state["episodes"]["1"]["violations"] if v["code"] == "visual_fallback"])

    def test_what_the_rounds_covered_is_kept_when_they_run_out(self):
        model = FakeModel()
        model.visual_failures = 3
        state = _engine(model, attempts=3).write(title="暗室回声", director_plan="大纲", episode_count=1)
        scenes = state["episodes"]["1"]["script"]["scenes"]
        self.assertTrue(scenes[0]["image_prompt"]["scene"].startswith("E1S01"), "the covered shot keeps its prompts")
        fallbacks = [v["scene_id"] for v in state["episodes"]["1"]["violations"] if v["code"] == "visual_fallback"]
        self.assertEqual(fallbacks, ["E1S02"])


class TalkHeavyEpisodesTests(unittest.TestCase):
    """Scripts should be full of dialogue: the plan prompt asks for it and a quiet plan is sent back."""

    @staticmethod
    def _quiet_plan(episode: int):
        return json.dumps({"title": f"第{episode}集", "scenes": [
            _scene(episode, 1), _scene(episode, 2, utterances=[]), _scene(episode, 3, utterances=[]), _scene(episode, 4, utterances=[]),
        ]}, ensure_ascii=False)

    @staticmethod
    def _talky_plan(episode: int):
        return json.dumps({"title": f"第{episode}集", "scenes": [
            _scene(episode, 1), _scene(episode, 2, speaker="周教授", text="你没有退路了。"), _scene(episode, 3), _scene(episode, 4, utterances=[]),
        ]}, ensure_ascii=False)

    def test_the_outline_prompt_asks_for_talk_heavy_shots_and_source_modes_do_not(self):
        model = FakeModel()
        _engine(model, spoken_shot_ratio=0.7).write(title="暗室回声", director_plan="大纲", episode_count=1)
        plan_prompt = next(c["prompt"] for c in model.calls if "字段写作指引" in c["prompt"] and "视觉生产层" not in c["prompt"])
        self.assertIn("台词要多", plan_prompt)
        self.assertIn("至少 70% 的分镜要有口播", plan_prompt)
        narration = FakeModel()
        _engine(narration, spoken_shot_ratio=0.7, creation={"creation_mode": "narration"}).write(title="暗室回声", director_plan="大纲", episode_count=1)
        narration_prompt = next(c["prompt"] for c in narration.calls if "字段写作指引" in c["prompt"] and "视觉生产层" not in c["prompt"])
        self.assertIn("口播密度", narration_prompt)
        self.assertNotIn("台词要多", narration_prompt)
        source = FakeModel()
        novel = "林夏推开实验室的门。" + "周教授没有回头。" * 20 + "录音笔还在转。"
        _engine(source, spoken_shot_ratio=0.7).write(title="暗室回声", director_plan="", episode_count=2, source_text=novel, source_kind="novel")
        source_prompt = next(c["prompt"] for c in source.calls if "字段写作指引" in c["prompt"] and "视觉生产层" not in c["prompt"])
        self.assertNotIn("台词要多", source_prompt, "lines cut from a source stay the source's own")

    def test_the_check_counts_shots_with_speech(self):
        shots = [_scene(1, 1), _scene(1, 2, utterances=[]), _scene(1, 3, utterances=[{"kind": "voiceover", "speaker": None, "text": " "}])]
        self.assertIsNone(spoken_shot_problem(shots, 0))
        self.assertIsNone(spoken_shot_problem(shots, 0.3))
        problem = spoken_shot_problem(shots, 0.7)
        self.assertIn("3 个分镜只有 1 个有口播，至少要 3 个（70%）", problem)
        self.assertIn("E1S02, E1S03", problem)

    def test_a_quiet_plan_is_sent_back_for_dialogue_and_a_talky_retry_passes_clean(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: self._quiet_plan(1) if attempt == 1 else self._talky_plan(1)
        state = _engine(model, spoken_shot_ratio=0.7).write(title="暗室回声", director_plan="大纲", episode_count=1)
        self.assertEqual(model.plan_attempts[1], 2)
        retry = [c["prompt"] for c in model.calls if "当前正在生成第 1 集" in c["prompt"]][1]
        self.assertIn("台词太少", retry)
        self.assertIn("E1S02, E1S03, E1S04", retry)
        self.assertEqual(len(state["episodes"]["1"]["script"]["scenes"]), 4)
        self.assertFalse([v for v in state["episodes"]["1"]["violations"] if v["code"] == TOO_FEW_SPOKEN_SHOTS])

    def test_a_plan_that_stays_quiet_is_kept_on_the_last_round_with_a_warning(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: self._quiet_plan(1)
        state = _engine(model, attempts=3, spoken_shot_ratio=0.7).write(title="暗室回声", director_plan="大纲", episode_count=1)
        self.assertEqual(model.plan_attempts[1], 3, "two rounds ask for dialogue, the third keeps the plan")
        warnings = [v for v in state["episodes"]["1"]["violations"] if v["code"] == TOO_FEW_SPOKEN_SHOTS]
        self.assertEqual(len(warnings), 1)
        self.assertIn("台词太少", warnings[0]["message"])
        self.assertNotIn("draft", state["episodes"]["1"], "a quiet episode is a warning, not a quarantined draft")

    def test_a_ratio_of_zero_turns_the_rule_off(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: self._quiet_plan(1)
        state = _engine(model, spoken_shot_ratio=0).write(title="暗室回声", director_plan="大纲", episode_count=1)
        self.assertEqual(model.plan_attempts[1], 1)
        self.assertFalse([v for v in state["episodes"]["1"]["violations"] if v["code"] == TOO_FEW_SPOKEN_SHOTS])
        self.assertNotIn("台词要多", next(c["prompt"] for c in model.calls if "当前正在生成第 1 集" in c["prompt"]))


if __name__ == "__main__":
    unittest.main()

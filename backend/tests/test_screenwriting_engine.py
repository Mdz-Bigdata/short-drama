# -*- coding: utf-8 -*-
"""The structured screenwriting engine: ledger → script plan → visual layer.

A fake model answers every prompt kind with schema-valid JSON so the tests pin
the orchestration contract (what is asked, in which order, what is validated,
what is repaired) rather than any provider.
"""

import json
import re
import unittest
from typing import Any, Dict, List

from app.core.screenwriting import anchors, editing, entries, models, prose, renderer, speech_rate, text_metrics, violations
from app.core.screenwriting.engine import PlanRejected, ScreenwritingEngine, ScreenwritingError, detect_source_kind
from app.core.screenwriting.structured_llm import RETRY_HEADER, extract_json_object
from app.core.writer_dashboard import compile_writer_dashboard, script_episode_indexes


def _scene(episode: int, index: int, *, speaker: str = "林夏", text: str = "你到底瞒了什么？", duration: int = 6, **extra) -> Dict[str, Any]:
    scene = {
        "scene_id": f"E{episode}S{index:02d}",
        "duration_seconds": duration,
        "segment_break": index == 1,
        "setting": "地下实验室 夜 内景",
        "characters_in_scene": [speaker],
        "scenes": ["地下实验室"],
        "props": ["录音笔"],
        "scene_description": f"第{episode}集第{index}个画面：林夏握紧录音笔，指节发白。",
        "utterances": [{"kind": "dialogue", "speaker": speaker, "text": text, "delivery": "压抑-克制 / 慢"}],
        "source_text": "",
    }
    scene.update(extra)
    return scene


def _visual(scene_id: str) -> Dict[str, Any]:
    return {
        "scene_id": scene_id,
        "image_prompt": {
            "scene": f"{scene_id} 林夏坐在实验台前，冷白顶灯从上方打下。",
            "composition": {"shot_type": "medium_close_up", "lighting": "顶部冷白灯", "ambiance": "尘埃在光柱里翻飞"},
        },
        "video_prompt": {"action": "林夏缓缓抬头，手指摩挲录音笔。", "camera_motion": "push_in", "ambiance_audio": "仪器低鸣"},
    }


PROSE_OPENING = "夜色压下来，走廊尽头的应急灯一明一灭，整栋楼只剩仪器的低鸣在墙里回响，像有人隔着水说话。"


def _prose_for(prompt: str) -> str:
    """A prose body that tells every shot of the prompt's <shots> block, lines verbatim inside “”."""
    shots = prompt.split("<shots>", 1)[1].split("</shots>", 1)[0]
    paragraphs = [PROSE_OPENING]
    for line in shots.splitlines():
        line = line.strip()
        if line.startswith("视觉改编："):
            paragraphs.append("灯下，" + line.removeprefix("视觉改编："))
        elif line.startswith("- [台词] "):
            speaker, text = line.removeprefix("- [台词] ").split("：", 1)
            paragraphs.append(f"“{text}”{speaker}没有移开视线。")
        elif line.startswith("- [旁白] "):
            paragraphs.append(line.removeprefix("- [旁白] "))
    return "\n\n".join(paragraphs)


class FakeModel:
    """Routes each prompt to a canned answer by the prompt's own headings."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.visual_failures = 0
        self.plan_overrides: Dict[int, Any] = {}
        self.plan_attempts: Dict[int, int] = {}
        self.prose_overrides: Dict[int, Any] = {}
        self.prose_attempts: Dict[int, int] = {}

    def __call__(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        self.calls.append({"system": system_prompt, "prompt": user_prompt, "max_tokens": max_tokens})
        if "提炼项目概述" in user_prompt:
            return json.dumps({"title": "暗室回声", "synopsis": "林夏追查实验室真相。", "genre": "悬疑", "theme": "真相的代价", "world_setting": "近未来都市"}, ensure_ascii=False)
        if "角色与世界观分析师" in user_prompt:
            return json.dumps({
                "characters": {"林夏": {"description": "黑色短发，白大褂", "voice_style": "冷静", "position": "女主角"},
                               "周教授": {"description": "花白头发，金丝眼镜", "voice_style": "低沉", "position": "反派"}},
                "scenes": {"地下实验室": {"description": "冷白灯光的地下空间"}},
                "props": {"录音笔": {"description": "银色录音笔"}},
            }, ensure_ascii=False)
        if "分集大纲" in user_prompt and "episodes 数组长度必须等于" in user_prompt:
            first, last = map(int, re.search(r"对应第 (\d+) 集到第 (\d+) 集|对应第 (\d+) 集", user_prompt).groups(default="0")[:2]) if "集到第" in user_prompt else (0, 0)
            if first == 0:
                single = int(re.search(r"本批\*\*恰好\*\*输出 (\d+) 集（对应第 (\d+) 集", user_prompt).group(2))
                first = last = single
            return json.dumps({"episodes": [
                {"title": f"第{n}集标题", "hook": f"第{n}集钩子", "story_beats": [f"节点{n}A", f"节点{n}B"], "next_episode_teaser": f"预告{n}"}
                for n in range(first, last + 1)
            ]}, ensure_ascii=False)
        if "end_anchor" in user_prompt:
            window = user_prompt.split("---\n", 1)[1].rsplit("\n---", 1)[0]
            midpoint = window.find("。") + 1
            return json.dumps({"episodes": [
                {"title": "上", "hook": "钩子一", "end_anchor": window[max(0, midpoint - 12):midpoint], "story_beats": ["A"], "next_episode_teaser": "下集"},
                {"title": "下", "hook": "钩子二", "end_anchor": window[-12:], "story_beats": ["B"], "next_episode_teaser": None},
            ]}, ensure_ascii=False)
        if "字段写作指引" in user_prompt and "scene_description" in user_prompt:
            episode = int(re.search(r"当前正在生成第 (\d+) 集", user_prompt).group(1))
            self.plan_attempts[episode] = self.plan_attempts.get(episode, 0) + 1
            override = self.plan_overrides.get(episode)
            if callable(override):
                return override(self.plan_attempts[episode], user_prompt)
            return json.dumps({"title": f"第{episode}集标题", "scenes": [_scene(episode, 1), _scene(episode, 2, speaker="周教授", text="现在回头还来得及。")]}, ensure_ascii=False)
        if "小说体剧本正文" in user_prompt:
            episode = int(re.search(r"下方是第 (\d+) 集", user_prompt).group(1))
            self.prose_attempts[episode] = self.prose_attempts.get(episode, 0) + 1
            override = self.prose_overrides.get(episode)
            if callable(override):
                return override(self.prose_attempts[episode], user_prompt)
            return _prose_for(user_prompt)
        if "视觉生产层" in user_prompt:
            ids = re.findall(r"^### (E\d+S\d+(?:_\d+)?)", user_prompt, re.M)
            if self.visual_failures > 0:
                self.visual_failures -= 1
                ids = ids[:-1]
            return json.dumps({"title": "", "scenes": [_visual(sid) for sid in ids]}, ensure_ascii=False)
        raise AssertionError(f"unexpected prompt: {user_prompt[:120]}")


def _engine(model: FakeModel, **overrides) -> ScreenwritingEngine:
    params = dict(video_model="seedance2.0", attempts=3, system_prompt="SYS", style="写实电影感")
    params.update(overrides)
    return ScreenwritingEngine(model, **params)


class OutlineModeTests(unittest.TestCase):
    def test_writes_every_requested_episode_from_the_director_plan(self):
        model = FakeModel()
        state = _engine(model).write(title="暗室回声", director_plan="三幕大纲……", episode_count=3)

        self.assertEqual(state["source_kind"], "outline")
        self.assertEqual([entry["episode"] for entry in state["ledger"]], [1, 2, 3])
        self.assertEqual(state["ledger"][0]["hook"], "第1集钩子")
        self.assertEqual(sorted(state["episodes"]), ["1", "2", "3"])
        script = state["episodes"]["2"]["script"]
        self.assertEqual(script["hook"], "第2集钩子")
        self.assertEqual([scene["scene_id"] for scene in script["scenes"]], ["E2S01", "E2S02"])
        # Stage B is merged by id: content from the plan, prompts from the visual call.
        self.assertEqual(script["scenes"][0]["utterances"][0]["text"], "你到底瞒了什么？")
        self.assertEqual(script["scenes"][0]["image_prompt"]["composition"]["shot_type"], "Medium Close-up")
        self.assertEqual(script["scenes"][0]["video_prompt"]["camera_motion"], "Push In")
        self.assertTrue(script["scenes"][0][entries.ENTRY_REVISION_FIELD].startswith("sha256-v1:"))
        self.assertTrue(all(entry["ledger_status"] == "written" for entry in state["ledger"]))

    def test_prompts_carry_the_outline_hook_and_model_bound_durations(self):
        model = FakeModel()
        _engine(model).write(title="暗室回声", director_plan="三幕大纲……", episode_count=2)

        prompts = {
            number: next(call["prompt"] for call in model.calls if f"当前正在生成第 {number} 集" in call["prompt"] and "scene_description" in call["prompt"])
            for number in (1, 2)
        }
        plan_prompt = prompts[2]
        self.assertIn("集尾钩子：第2集钩子", plan_prompt)
        # Episode 1 sees episode 2's outline only for its ending; the last episode has no next.
        self.assertIn("<next_episode_outline>", prompts[1])
        self.assertIn("下集标题：第2集标题", prompts[1])
        self.assertNotIn("<next_episode_outline>", plan_prompt)
        # seedance2.0 renders at most 15s per clip, so the legal set is 4..15.
        self.assertIn("4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15", plan_prompt)
        self.assertIn("最长 15 秒", plan_prompt)
        self.assertIn("开篇", plan_prompt)  # pacing rules injected
        self.assertIn('"enum":[4,5,6,7,8,9,10,11,12,13,14,15]', plan_prompt)
        self.assertTrue(all(call["system"] == "SYS" for call in model.calls))

    def test_rendered_screenplay_is_prose_under_episode_headings(self):
        model = FakeModel()
        state = _engine(model).write(title="暗室回声", director_plan="三幕大纲……", episode_count=2)

        text = renderer.render_screenplay(state)
        self.assertEqual(script_episode_indexes(text), [1, 2])
        self.assertTrue(text.startswith("第1集 第1集标题\n\n" + PROSE_OPENING))
        self.assertIn("“你到底瞒了什么？”林夏没有移开视线。", text)
        # One paragraph per block, one blank line between blocks, and no shot-list grammar.
        self.assertNotIn("\n\n\n", text)
        self.assertTrue(all("\n" not in block for block in text.split("\n\n")))
        for line in text.splitlines():
            self.assertNotRegex(line, r"^(?:场景\d*|镜头|画面|动作|环境音|时长|台词提示|集尾钩子|下集悬念钩子|林夏|周教授)[：:]")
        self.assertNotIn("E1S01", text)

        task = {"task_id": "t", "config": {"episode_count": 2}, "assets": {"2": text, "2_breakdown": renderer.render_breakdown(state)}}
        dashboard = compile_writer_dashboard(task)
        self.assertEqual(dashboard.state, "READY")
        self.assertEqual(dashboard.stats.total_episodes, 2)
        self.assertEqual(dashboard.stats.scene_count, 4)
        self.assertEqual(dashboard.scenes[0].duration_seconds, 6)
        self.assertEqual({role.name for role in dashboard.roles}, {"林夏", "周教授"})
        self.assertEqual(dashboard.overview.title, "暗室回声")
        self.assertEqual(len(dashboard.timeline), 2)

    def test_visual_layer_missing_a_shot_is_retried_with_the_reason(self):
        model = FakeModel()
        model.visual_failures = 1
        state = _engine(model).write(title="暗室回声", director_plan="三幕大纲……", episode_count=1)

        visual_calls = [call["prompt"] for call in model.calls if "视觉生产层" in call["prompt"]]
        self.assertEqual(len(visual_calls), 2)
        self.assertIn(RETRY_HEADER, visual_calls[1])
        self.assertIn("缺少这些分镜的视觉层：E1S02", visual_calls[1])
        self.assertEqual(state["episodes"]["1"]["violations"], [])

    def test_visual_layer_falls_back_to_plan_content_when_the_model_never_covers_a_shot(self):
        model = FakeModel()
        model.visual_failures = 5
        state = _engine(model, attempts=2).write(title="暗室回声", director_plan="三幕大纲……", episode_count=1)

        scene = state["episodes"]["1"]["script"]["scenes"][1]
        self.assertIn("第1集第2个画面", scene["image_prompt"]["scene"])
        self.assertEqual([v["code"] for v in state["episodes"]["1"]["violations"]], ["visual_fallback"])

    def test_write_missing_plans_and_writes_only_the_gap(self):
        model = FakeModel()
        engine = _engine(model)
        state = engine.write(title="暗室回声", director_plan="三幕大纲……", episode_count=2)
        calls_before = len(model.calls)

        updated = engine.write_missing(state, [3, 4])

        self.assertEqual(sorted(updated["episodes"]), ["1", "2", "3", "4"])
        self.assertEqual([entry["episode"] for entry in updated["ledger"]], [1, 2, 3, 4])
        self.assertEqual(updated["episode_count"], 4)
        # No overview / inventory again, and episodes 1-2 were not rewritten.
        later = [call["prompt"] for call in model.calls[calls_before:]]
        self.assertFalse(any("提炼项目概述" in prompt for prompt in later))
        self.assertFalse(any("当前正在生成第 1 集" in prompt for prompt in later))
        self.assertEqual(state["episodes"]["1"], updated["episodes"]["1"])


class SpeechDurationTests(unittest.TestCase):
    def test_duration_is_raised_to_the_smallest_tier_that_fits_the_dialogue(self):
        model = FakeModel()
        long_line = "这" * 30  # 30 字 / 5 字每秒 = 6 秒 > 4 秒
        model.plan_overrides[1] = lambda attempt, prompt: json.dumps({"title": "t", "scenes": [_scene(1, 1, text=long_line, duration=4)]}, ensure_ascii=False)
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=1)

        scene = state["episodes"]["1"]["script"]["scenes"][0]
        self.assertEqual(scene["duration_seconds"], 6)
        self.assertIn("duration_raised_for_speech", [v["code"] for v in state["episodes"]["1"]["violations"]])
        self.assertEqual(model.plan_attempts[1], 1)

    def test_dialogue_longer_than_the_longest_clip_is_sent_back_then_flagged(self):
        model = FakeModel()
        too_long = "字" * 120  # 24 秒 > 15 秒上限
        model.plan_overrides[1] = lambda attempt, prompt: json.dumps({"title": "t", "scenes": [_scene(1, 1, text=too_long, duration=8)]}, ensure_ascii=False)
        state = _engine(model, attempts=2).write(title="暗室回声", director_plan="大纲", episode_count=1)

        self.assertEqual(model.plan_attempts[1], 2)
        retry_prompt = [call["prompt"] for call in model.calls if "当前正在生成第 1 集" in call["prompt"] and RETRY_HEADER in call["prompt"]]
        self.assertEqual(len(retry_prompt), 1)
        self.assertIn("超过最长档 15 秒", retry_prompt[0])
        scene = state["episodes"]["1"]["script"]["scenes"][0]
        self.assertTrue(scene["needs_replan"])
        self.assertEqual(scene["duration_seconds"], 15)
        self.assertEqual(state["episodes"]["1"]["needs_replan"], ["E1S01"])

    def test_unknown_speaker_is_added_to_the_cast_and_registered_as_an_asset(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: json.dumps({"title": "t", "scenes": [
            _scene(1, 1, characters_in_scene=["林夏"], utterances=[{"kind": "dialogue", "speaker": "陈警官", "text": "都别动。"}]),
        ]}, ensure_ascii=False)
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=1)

        scene = state["episodes"]["1"]["script"]["scenes"][0]
        self.assertEqual(scene["characters_in_scene"], ["林夏", "陈警官"])
        self.assertIn("陈警官", state["inventory"]["characters"])
        self.assertIn("需补充", state["inventory"]["characters"]["陈警官"]["description"])


class SourceModeTests(unittest.TestCase):
    NOVEL = "林夏推开实验室的门，冷白灯光刺得她眯起眼。她在抽屉里找到了录音笔。周教授站在她身后，声音低沉：现在回头还来得及。"

    def test_detects_source_kind(self):
        self.assertEqual(detect_source_kind(None), "outline")
        self.assertEqual(detect_source_kind(self.NOVEL), "novel")
        self.assertEqual(detect_source_kind("第1集 对峙\n场景1：实验室\n林夏：你瞒了什么？\n周教授：回头。\n场景2：走廊\n林夏：录音就是证据。"), "screenplay")

    def test_novel_is_sliced_on_anchors_and_each_slice_feeds_its_episode(self):
        model = FakeModel()
        state = _engine(model).write(title="暗室回声", director_plan="", episode_count=2, source_text=self.NOVEL)

        self.assertEqual(state["source_kind"], "novel")
        ranges = [entry["source_range"] for entry in state["ledger"]]
        self.assertEqual(ranges[0]["start"], 0)
        self.assertEqual(ranges[0]["end"], ranges[1]["start"])
        self.assertEqual(ranges[1]["end"], len(self.NOVEL))
        plan_prompt = next(call["prompt"] for call in model.calls if "当前正在生成第 2 集" in call["prompt"] and "scene_description" in call["prompt"])
        self.assertIn("<novel>", plan_prompt)
        self.assertIn("周教授站在她身后", plan_prompt)
        self.assertNotIn("林夏推开实验室的门", plan_prompt)
        self.assertIn("**改编**", plan_prompt)

    def test_screenplay_extraction_rejects_rewritten_lines_until_verbatim(self):
        script = "第1集 对峙\n场景1：实验室\n林夏：你到底瞒了什么？\n周教授：现在回头还来得及。\n"
        model = FakeModel()

        def _plan(attempt: int, prompt: str) -> str:
            text = "你到底瞒了什么？" if attempt > 1 else "你隐瞒了什么真相？"
            return json.dumps({"title": "对峙", "scenes": [_scene(1, 1, text=text)]}, ensure_ascii=False)

        model.plan_overrides[1] = _plan
        state = _engine(model).write(title="暗室回声", director_plan="", episode_count=1, source_text=script, source_kind="screenplay")

        self.assertEqual(model.plan_attempts[1], 2)
        retry = [call["prompt"] for call in model.calls if RETRY_HEADER in call["prompt"] and "scene_description" in call["prompt"]][0]
        self.assertIn("必须逐字保留", retry)
        self.assertIn("**提取**", retry)
        self.assertEqual(state["episodes"]["1"]["script"]["scenes"][0]["utterances"][0]["text"], "你到底瞒了什么？")


class ProseBodyTests(unittest.TestCase):
    def test_prose_is_told_from_the_fixed_plan_between_the_plan_and_the_visual_layer(self):
        model = FakeModel()
        state = _engine(model).write(title="暗室回声", director_plan="三幕大纲……", episode_count=2)

        kinds = [
            "plan" if "scene_description" in call["prompt"] and "字段写作指引" in call["prompt"]
            else "prose" if "小说体剧本正文" in call["prompt"]
            else "visual" if "视觉生产层" in call["prompt"] else "other"
            for call in model.calls
        ]
        self.assertEqual([kind for kind in kinds if kind != "other"], ["plan", "prose", "visual", "plan", "prose", "visual"])
        first, second = [call["prompt"] for call in model.calls if "小说体剧本正文" in call["prompt"]]
        self.assertIn("### E1S01", first)
        self.assertIn("- [台词] 林夏：你到底瞒了什么？", first)
        self.assertIn("集尾钩子：第1集钩子", first)
        self.assertNotIn("<previous_ending>", first)
        self.assertNotIn("JSON Schema", first)
        # Episode 2 reads how episode 1 ended, so the telling carries over.
        self.assertIn("<previous_ending>", second)
        self.assertIn("周教授没有移开视线。", second)
        entry = state["episodes"]["1"]
        self.assertEqual(entry["prose_origin"], "model")
        self.assertTrue(entry["prose"].startswith(PROSE_OPENING))
        self.assertTrue(entry["prose_revision"].startswith("sha256-v1:"))
        self.assertEqual(entry["violations"], [])

    def test_a_rewritten_line_is_sent_back_with_the_line_named(self):
        model = FakeModel()

        def _prose(attempt: int, prompt: str) -> str:
            body = _prose_for(prompt)
            return body if attempt > 1 else body.replace("你到底瞒了什么？", "你究竟隐瞒了什么？")

        model.prose_overrides[1] = _prose
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=1)

        self.assertEqual(model.prose_attempts[1], 2)
        retry = [call["prompt"] for call in model.calls if "小说体剧本正文" in call["prompt"] and RETRY_HEADER in call["prompt"]]
        self.assertEqual(len(retry), 1)
        self.assertIn("林夏「你到底瞒了什么？」", retry[0])
        self.assertIn("“你到底瞒了什么？”", state["episodes"]["1"]["prose"])
        self.assertEqual(state["episodes"]["1"]["violations"], [])

    def test_a_shot_list_draft_is_refused_and_the_body_is_assembled_from_the_plan(self):
        model = FakeModel()
        model.prose_overrides[1] = lambda attempt, prompt: (
            "场景1：地下实验室 夜 内景\n镜头：中景 固定\n林夏：你到底瞒了什么？\n周教授：现在回头还来得及。\n" * 3
        )
        state = _engine(model, attempts=2).write(title="暗室回声", director_plan="大纲", episode_count=1)

        self.assertEqual(model.prose_attempts[1], 2)
        entry = state["episodes"]["1"]
        self.assertEqual(entry["prose_origin"], "synthesized")
        self.assertIn("prose_fallback", [v["code"] for v in entry["violations"]])
        text = renderer.render_screenplay(state)
        self.assertIn("“你到底瞒了什么？”林夏说。", text)
        self.assertIn("“现在回头还来得及。”周教授说。", text)
        self.assertNotIn("林夏：", text)
        self.assertEqual(script_episode_indexes(text), [1])

    def test_a_soft_finding_earns_one_retry_and_is_then_kept_with_a_warning(self):
        model = FakeModel()
        model.prose_overrides[1] = lambda attempt, prompt: _prose_for(prompt) + "\n\n“谁在那里？”门外有人问。"
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=1)

        self.assertEqual(model.prose_attempts[1], 2)
        entry = state["episodes"]["1"]
        self.assertEqual(entry["prose_origin"], "model")
        self.assertIn("“谁在那里？”", entry["prose"])
        self.assertEqual([v["code"] for v in entry["violations"]], ["prose_unverified"])
        self.assertIn("谁在那里", entry["violations"][0]["message"])

    def test_the_prose_prompt_can_be_audited_without_a_model_call(self):
        model = FakeModel()
        engine = _engine(model, instructions="多写雨夜的湿冷")
        state = engine.write(title="暗室回声", director_plan="大纲", episode_count=1)
        before = len(model.calls)

        prompt = engine.dry_run_prompt(state, 1, "prose")

        self.assertEqual(len(model.calls), before)
        self.assertIn("小说体剧本正文", prompt)
        self.assertIn("### E1S02", prompt)
        self.assertIn("多写雨夜的湿冷", prompt)

    def test_a_source_episode_reads_as_its_own_slice_and_is_never_retold(self):
        model = FakeModel()
        state = _engine(model).write(title="暗室回声", director_plan="", episode_count=2, source_text=SourceModeTests.NOVEL)

        self.assertFalse(any("小说体剧本正文" in call["prompt"] for call in model.calls))
        self.assertNotIn("prose", state["episodes"]["1"])
        texts = renderer.render_episode_texts(state)
        first_end = state["ledger"][0]["source_range"]["end"]
        self.assertEqual(texts[1], "第1集 第1集标题\n\n" + SourceModeTests.NOVEL[:first_end].strip())
        self.assertEqual(texts[2], "第2集 第2集标题\n\n" + SourceModeTests.NOVEL[first_end:].strip())

    def test_an_uploaded_script_keeps_its_own_episode_heading(self):
        script = "第1集 对峙\n场景1：实验室\n林夏：你到底瞒了什么？\n周教授：现在回头还来得及。\n"
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: json.dumps({"title": "对峙", "scenes": [_scene(1, 1)]}, ensure_ascii=False)
        state = _engine(model).write(title="暗室回声", director_plan="", episode_count=1, source_text=script, source_kind="screenplay")
        # The fake planner cuts a window in two; fold it back into the single episode the script has.
        state["ledger"] = [dict(state["ledger"][0], source_range={"start": 0, "end": len(script)})]
        state["episodes"] = {"1": state["episodes"]["1"]}

        self.assertEqual(renderer.render_screenplay(state), script.strip())

    def test_a_state_written_before_prose_existed_still_reads_as_prose(self):
        model = FakeModel()
        state = _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=1)
        for key in ("prose", "prose_origin", "prose_revision"):
            state["episodes"]["1"].pop(key)

        text = renderer.render_screenplay(state)

        self.assertTrue(text.startswith("第1集 第1集标题\n\n"))
        self.assertIn("“你到底瞒了什么？”林夏说。", text)
        self.assertNotIn("场景1：", text)


class ProseTextTests(unittest.TestCase):
    SCENES = [
        _scene(1, 1, utterances=[{"kind": "dialogue", "speaker": "林夏", "text": "你听好，这不是我写的。"}]),
        _scene(1, 2, speaker="周教授", utterances=[{"kind": "voiceover", "text": "那一夜之后，实验室再没亮过灯。"}]),
    ]
    BODY = (
        "雨下到后半夜，巷口的灯只剩一盏，积水把招牌的红光揉成一团，顺着台阶一级一级淌下去。\n\n"
        "“你听好，”林夏把信纸按在桌上，“这不是我写的。”\n\n"
        "那一夜之后，实验室再没亮过灯。"
    )

    def test_normalize_gives_one_paragraph_per_block_and_chinese_quotes(self):
        raw = "以下是第1集正文：\n```\n## 第1集 对峙\n　　雨下到后半夜。\n\n\n**林夏**抬头：\"走。\"\n- 「别回头。」她说。\n---\n（本集完）\n```"
        self.assertEqual(prose.normalize_prose(raw), "雨下到后半夜。\n\n林夏抬头：“走。”\n\n“别回头。”她说。")

    def test_a_line_split_around_an_action_beat_is_still_verbatim(self):
        check = prose.check_prose(self.BODY, self.SCENES, character_names=["林夏", "周教授"])
        self.assertEqual(check.reasons, [])
        reworded = self.BODY.replace("这不是我写的", "这可不是我写的")
        missing = prose.check_prose(reworded, self.SCENES).errors
        self.assertEqual(len(missing), 1)
        self.assertIn("林夏「你听好，这不是我写的。」", missing[0])

    def test_delivery_marks_inside_a_line_are_not_expected_in_the_prose(self):
        scenes = [_scene(1, 1, utterances=[{"kind": "dialogue", "speaker": "林夏", "text": "十六年了……[停顿2秒]【焚天】，回来了。（低语）"}])]
        body = self.BODY.split("\n\n")[0] + "\n\n“十六年了……”林夏的拇指弹开剑柄，“焚天，回来了。”"
        self.assertEqual(prose.missing_utterances(body, scenes), [])
        self.assertEqual(prose.invented_dialogue(body, scenes), [])

    def test_shot_list_grammar_is_an_error_and_prose_that_merely_mentions_it_is_not(self):
        check = prose.check_prose(self.BODY + "\n\n旁白：多年以后。\n\n林夏（冷笑）：走。\n\n第2集 回声", self.SCENES, character_names=["林夏"])
        self.assertEqual(len(check.errors), 3)
        self.assertTrue(any("标签行" in reason for reason in check.errors))
        self.assertTrue(any("剧本体对白" in reason for reason in check.errors))
        self.assertTrue(any("第N集" in reason for reason in check.errors))
        narrated = self.BODY + "\n\n他压着她的手腕写了四个字：一字不易。画面一转，天已经亮了。"
        self.assertEqual(prose.check_prose(narrated, self.SCENES, character_names=["林夏"]).errors, [])

    def test_emphasis_quotes_are_not_invented_dialogue(self):
        body = self.BODY + "\n\n纸上只有一个“死”字。\n\n“你是谁？”门外有人问。"
        self.assertEqual(prose.invented_dialogue(body, self.SCENES), ["你是谁？"])
        self.assertEqual(prose.check_prose(body + "（她很紧张）", self.SCENES).errors, [])
        self.assertEqual(len(prose.check_prose(body + "（她很紧张）", self.SCENES).warnings), 2)

    def test_a_body_too_short_to_tell_the_shots_is_refused(self):
        self.assertIn("正文过短", prose.check_prose("“你听好，这不是我写的。”", self.SCENES).errors[0])

    def test_synthesized_paragraphs_never_read_as_an_episode_heading(self):
        text = prose.prose_from_scenes([_scene(3, 1)])
        self.assertEqual(script_episode_indexes(text), [])
        self.assertIn("“你到底瞒了什么？”林夏说。", text)


class ProseSourceTests(unittest.TestCase):
    """A prose script the Writer produced comes back as a source after a manual edit."""

    SCRIPT = (
        "第1集 残诏\n\n雨下到后半夜，巷口的灯只剩一盏。\n\n"
        "“你听好，”林夏把信纸按在桌上，“这不是我写的。”\n\n"
        "周教授没有接话，只把录音笔推回她手边。"
    )

    def test_a_line_split_around_an_action_beat_counts_as_verbatim(self):
        ctx = violations.PlanCheckContext(episode=1, supported_durations=[4, 6, 8], source_text=self.SCRIPT, source_kind="screenplay")
        kept = [_scene(1, 1, text="你听好，这不是我写的。")]
        self.assertEqual(violations.check_script_plan(kept, ctx).errors, [])
        reworded = [_scene(1, 1, text="你听好，这可不是我写的。")]
        self.assertEqual([v.code for v in violations.check_script_plan(reworded, ctx).errors], ["utterance_not_verbatim"])

    def test_clauses_from_different_parts_of_the_story_are_not_one_line(self):
        source = "“你听好。”林夏说。" + "夜" * 200 + "“这不是我写的。”周教授说。"
        self.assertFalse(prose.spoken_verbatim_in(source, "你听好，这不是我写的。"))
        self.assertTrue(prose.spoken_verbatim_in(source, "这不是我写的。"))

    def test_the_prose_script_is_extracted_and_shown_as_the_author_left_it(self):
        model = FakeModel()
        model.plan_overrides[1] = lambda attempt, prompt: json.dumps({"title": "残诏", "scenes": [_scene(1, 1, text="你听好，这不是我写的。")]}, ensure_ascii=False)
        state = _engine(model).write(title="暗室回声", director_plan="", episode_count=1, source_text=self.SCRIPT, source_kind="screenplay")
        state["ledger"] = [dict(state["ledger"][0], source_range={"start": 0, "end": len(self.SCRIPT)})]
        state["episodes"] = {"1": state["episodes"]["1"]}

        self.assertEqual(model.plan_attempts[1], 1)
        self.assertEqual(renderer.render_screenplay(state), self.SCRIPT)


class PlanEditingTests(unittest.TestCase):
    def test_replace_plan_rewrites_only_the_changed_shot(self):
        model = FakeModel()
        engine = _engine(model)
        state = engine.write(title="暗室回声", director_plan="大纲", episode_count=1)
        scenes = [dict(scene) for scene in state["episodes"]["1"]["plan"]["scenes"]]
        scenes[1]["scene_description"] = "周教授摘下眼镜，镜片映出仪器的红光。"
        before = len(model.calls)

        updated, rewritten = engine.replace_plan(state, 1, scenes)

        self.assertEqual(rewritten, ["E1S02"])
        visual_prompts = [call["prompt"] for call in model.calls[before:] if "视觉生产层" in call["prompt"]]
        self.assertEqual(len(visual_prompts), 1)
        self.assertIn("### E1S02", visual_prompts[0])
        self.assertNotIn("### E1S01", visual_prompts[0])
        script = updated["episodes"]["1"]["script"]
        self.assertEqual(script["scenes"][0]["image_prompt"], state["episodes"]["1"]["script"]["scenes"][0]["image_prompt"])
        self.assertEqual(script["scenes"][1]["scene_description"], "周教授摘下眼镜，镜片映出仪器的红光。")
        self.assertNotEqual(updated["episodes"]["1"]["plan_revision"], state["episodes"]["1"]["plan_revision"])

    def test_replace_plan_retells_the_prose_only_when_what_it_tells_changed(self):
        model = FakeModel()
        engine = _engine(model)
        state = engine.write(title="暗室回声", director_plan="大纲", episode_count=1)
        scenes = [dict(scene) for scene in state["episodes"]["1"]["plan"]["scenes"]]
        scenes[0]["props"] = []  # a reference the prose never shows
        before = len(model.calls)

        updated, _ = engine.replace_plan(state, 1, scenes)

        self.assertFalse(any("小说体剧本正文" in call["prompt"] for call in model.calls[before:]))
        self.assertEqual(updated["episodes"]["1"]["prose"], state["episodes"]["1"]["prose"])

        scenes = [dict(scene) for scene in updated["episodes"]["1"]["plan"]["scenes"]]
        scenes[1]["utterances"] = [{"kind": "dialogue", "speaker": "周教授", "text": "把录音笔给我。"}]
        before = len(model.calls)

        retold, _ = engine.replace_plan(updated, 1, scenes)

        self.assertEqual(sum("小说体剧本正文" in call["prompt"] for call in model.calls[before:]), 1)
        self.assertIn("“把录音笔给我。”", retold["episodes"]["1"]["prose"])
        self.assertNotIn("现在回头还来得及", renderer.render_screenplay(retold))
        self.assertNotEqual(retold["episodes"]["1"]["prose_revision"], updated["episodes"]["1"]["prose_revision"])

    def test_replace_plan_rejects_a_plan_that_breaks_content_constraints(self):
        model = FakeModel()
        engine = _engine(model)
        state = engine.write(title="暗室回声", director_plan="大纲", episode_count=1)
        scenes = [dict(scene) for scene in state["episodes"]["1"]["plan"]["scenes"]]
        scenes[0]["scene_id"] = scenes[1]["scene_id"]

        with self.assertRaises(PlanRejected) as raised:
            engine.replace_plan(state, 1, scenes)
        self.assertEqual([v.code for v in raised.exception.violations], ["scene_id_duplicate"])

    def test_replace_plan_flags_an_overflowing_shot_instead_of_refusing_the_whole_edit(self):
        model = FakeModel()
        engine = _engine(model)
        state = engine.write(title="暗室回声", director_plan="大纲", episode_count=1)
        scenes = [dict(scene) for scene in state["episodes"]["1"]["plan"]["scenes"]]
        scenes[0]["utterances"] = [{"kind": "dialogue", "speaker": "林夏", "text": "字" * 120}]  # 24 s > 15 s

        updated, rewritten = engine.replace_plan(state, 1, scenes)

        self.assertEqual(rewritten, ["E1S01"])
        self.assertEqual(updated["episodes"]["1"]["needs_replan"], ["E1S01"])
        shot = updated["episodes"]["1"]["script"]["scenes"][0]
        self.assertTrue(shot["needs_replan"])
        self.assertEqual(shot["duration_seconds"], 15)
        self.assertIn("speech_exceeds_max", [v["code"] for v in updated["episodes"]["1"]["violations"]])
        # A later edit to a *different* shot is not blocked by the flagged one.
        again = [dict(scene) for scene in updated["episodes"]["1"]["plan"]["scenes"]]
        again[1]["scene_description"] = "周教授退后半步。"
        updated2, rewritten2 = engine.replace_plan(updated, 1, again)
        self.assertEqual(rewritten2, ["E1S02"])
        self.assertEqual(updated2["episodes"]["1"]["needs_replan"], ["E1S01"])

    def test_batch_operations_update_insert_split_move_remove(self):
        scenes = [_scene(1, 1), _scene(1, 2), _scene(1, 3)]
        result = editing.apply_plan_operations(scenes, [
            {"op": "update", "id": "E1S01", "fields": {"duration_seconds": 9}},
            {"op": "insert_after", "after_id": "E1S01", "item": {"scene_description": "插入的画面", "characters_in_scene": []}},
            {"op": "split", "id": "E1S03", "parts": [{"scene_description": "前半"}, {"scene_description": "后半"}]},
            {"op": "move_after", "id": "E1S02", "after_id": None},
            {"op": "remove", "id": "E1S01_1"},
        ])

        self.assertEqual([scene["scene_id"] for scene in result], ["E1S02", "E1S01", "E1S03_1", "E1S03_2"])
        self.assertEqual(result[1]["duration_seconds"], 9)
        self.assertEqual(result[2]["scene_description"], "前半")
        self.assertEqual(scenes[0]["duration_seconds"], 6)  # input untouched

    def test_batch_operations_report_the_failing_index(self):
        with self.assertRaises(editing.PlanEditError) as raised:
            editing.apply_plan_operations([_scene(1, 1)], [
                {"op": "update", "id": "E1S01", "fields": {"setting": "x"}},
                {"op": "update", "id": "E1S09", "fields": {"setting": "y"}},
            ])
        self.assertIn("E1S09", str(raised.exception))
        with self.assertRaises(editing.PlanEditError):
            editing.apply_plan_operations([_scene(1, 1)], [{"op": "update", "id": "E1S01", "fields": {"image_prompt": {}}}])
        with self.assertRaises(editing.PlanEditError):
            editing.apply_plan_operations([_scene(1, 1)], [{"op": "remove", "id": "E1S01"}])


class PrimitiveTests(unittest.TestCase):
    def test_reading_units_and_speech_seconds_follow_the_language(self):
        self.assertEqual(text_metrics.count_reading_units("你好，世界。", "zh"), 6)
        self.assertEqual(text_metrics.count_reading_units("hello brave new world", "en"), 4)
        self.assertEqual(text_metrics.reading_unit_noun("en"), "词")
        self.assertEqual(speech_rate.estimate_spoken_seconds("十个字十个字十个字十", "zh"), 2.0)
        self.assertEqual(speech_rate.estimate_spoken_seconds("five words in this line", "en"), 2.0)
        self.assertEqual(speech_rate.speech_rate_units_per_second("zh", 3.0), 3.0)
        self.assertEqual(speech_rate.speech_rate_units_per_second("zh", 99.0), 5.0)

    def test_anchor_resolution_tolerates_punctuation_width_and_rejects_ambiguity(self):
        window = "他说：“走吧。”她没有回头。走吧。"
        ends = anchors.resolve_boundaries(window, ['他说:"走吧。"'], snap_whitespace_tail=False)
        self.assertEqual(window[: ends[0]], "他说：“走吧。”")
        with self.assertRaises(anchors.AnchorRejected) as raised:
            anchors.resolve_boundaries(window, ["走吧。"], snap_whitespace_tail=False)
        self.assertIn("出现 2 次", raised.exception.reasons[0])
        with self.assertRaises(anchors.AnchorRejected):
            anchors.resolve_boundaries(window, ["不存在的片段"], snap_whitespace_tail=False)

    def test_enum_drift_is_folded_back_and_unknown_values_degrade(self):
        self.assertEqual(models.normalize_shot_type("MEDIUM_SHOT"), "Medium Shot")
        self.assertEqual(models.normalize_shot_type("特写"), "Close-up")
        self.assertEqual(models.normalize_shot_type("wide_shot"), "Medium Shot")
        self.assertEqual(models.normalize_camera_motion("dolly-in"), "Static")
        self.assertEqual(models.normalize_camera_motion("缓推"), "Push In")

    def test_utterance_kind_and_speaker_are_consistent(self):
        with self.assertRaises(ValueError):
            models.Utterance(kind="dialogue", speaker="", text="x")
        with self.assertRaises(ValueError):
            models.Utterance(kind="voiceover", speaker="林夏", text="x")
        self.assertEqual(models.Utterance(kind="旁白", text="多年以后").kind, "voiceover")

    def test_json_extraction_survives_fences_and_trailing_commas(self):
        self.assertEqual(extract_json_object('```json\n{"a": 1,}\n```'), {"a": 1})
        self.assertEqual(extract_json_object('前言 {"a": [1, 2,]} 后记'), {"a": [1, 2]})
        self.assertIsNone(extract_json_object("no json here"))

    def test_entry_currency_distinguishes_stale_fresh_and_removed(self):
        plan = [_scene(1, 1), _scene(1, 2), _scene(1, 3)]
        script = [dict(scene, **{entries.ENTRY_REVISION_FIELD: entries.entry_revision(scene)}) for scene in plan[:2]]
        script.append(dict(_scene(1, 9), **{entries.ENTRY_REVISION_FIELD: "sha256-v1:old"}))
        plan[1]["scene_description"] = "changed"
        currency = entries.evaluate_entry_currency(plan, script)
        self.assertEqual(currency.stale_ids, ["E1S02"])
        self.assertEqual(currency.fresh_ids, ["E1S03"])
        self.assertEqual(currency.removed_ids, ["E1S09"])

    def test_check_script_plan_rewrites_wrong_episode_prefix_and_snaps_durations(self):
        scenes = [_scene(2, 1, duration=99)]
        ctx = violations.PlanCheckContext(episode=1, supported_durations=[4, 5, 6])
        result = violations.check_script_plan(scenes, ctx)
        self.assertEqual(scenes[0]["scene_id"], "E1S01")
        self.assertEqual(scenes[0]["duration_seconds"], 6)
        self.assertEqual(sorted(v.code for v in result.warnings), ["duration_snapped"])
        self.assertEqual(result.errors, [])


class EngineErrorTests(unittest.TestCase):
    def test_source_mode_requires_text_and_missing_ledger_cannot_be_invented(self):
        engine = _engine(FakeModel())
        with self.assertRaises(ValueError):
            engine.write(title="t", director_plan="", episode_count=1, source_kind="novel")
        state = engine.write(title="t", director_plan="", episode_count=1, source_text=SourceModeTests.NOVEL)
        with self.assertRaises(ScreenwritingError):
            engine.write_missing(state, [7])


if __name__ == "__main__":
    unittest.main()

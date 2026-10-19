"""Batch video admission, provider-call usage records, reference pricing, speech ownership and subtitle drafts."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import usage_ledger, video_admission
from app.core.providers import pricing
from app.core.screenwriting import violations
from app.core.screenwriting.speech import narration_delivery, speech_mode, speech_problems
from app.core.subtitles import episode_cues, render_srt, split_sentences
from app.core.video_admission import assess_video_batch
from app.service.drama_service import DramaService, StagePrerequisiteError, parse_shot_dialogue
from app.repository.task_repo import TaskRepository


def _pricing(**models) -> pricing.PricingTable:
    return pricing.PricingTable.from_mapping(models)


class PricingTests(unittest.TestCase):
    def tearDown(self):
        pricing.set_pricing_table(None)

    def test_prices_are_declared_per_model_and_match_the_longest_contained_id(self):
        table = _pricing(**{
            "seedance": {"kind": "per_second", "currency": "CNY", "price": 1.0},
            "seedance-2-5": {"kind": "per_second", "currency": "CNY", "price": 2.0, "by_resolution": {"1080p": 3.0}},
            "deepseek-chat": {"kind": "per_million_tokens", "currency": "CNY", "input": 1.0, "output": 2.0},
            "eleven_multilingual_v2": {"kind": "per_thousand_characters", "currency": "USD", "price": 0.3},
            "seedream": {"kind": "per_image", "currency": "CNY", "price": 0.25},
        })

        self.assertEqual(table.cost("doubao-seedance-2-5-pro-250428", units={"seconds": 10}), (20.0, "CNY"))
        self.assertEqual(table.cost("doubao-seedance-2-5-pro", units={"seconds": 10, "resolution": "1080p"}), (30.0, "CNY"))
        self.assertEqual(table.cost("seedance2.0", units={"seconds": 5}), (5.0, "CNY"))
        self.assertEqual(table.cost("deepseek-chat", units={"input_tokens": 1_000_000, "output_tokens": 500_000}), (2.0, "CNY"))
        self.assertEqual(table.cost("eleven_multilingual_v2", units={"characters": 2000}), (0.6, "USD"))
        self.assertEqual(table.cost("doubao-seedream-4-5", units={"images": 4}), (1.0, "CNY"))
        self.assertIsNone(table.cost("unknown-model", units={"seconds": 10}))

    def test_an_invalid_entry_is_skipped_and_an_absent_file_prices_nothing(self):
        table = _pricing(bad={"kind": "per_hour", "price": 1}, worse={"kind": "per_image", "price": "many"})
        self.assertEqual(len(table), 0)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(len(pricing.PricingTable.load(Path(directory) / "missing.json")), 0)
            path = Path(directory) / "prices.json"
            path.write_text(json.dumps({"models": {"x-model": {"kind": "per_image", "price": 2}}}), encoding="utf-8")
            self.assertEqual(pricing.PricingTable.load(path).cost("x-model", units={"images": 2}), (4.0, "CNY"))

    def test_the_shipped_example_file_is_a_valid_table(self):
        example = Path(pricing.__file__).resolve().parents[2] / "data" / "model_pricing.example.json"
        table = pricing.PricingTable.load(example)
        self.assertGreater(len(table), 0)


class UsageLedgerTests(unittest.TestCase):
    def setUp(self):
        pricing.set_pricing_table(_pricing(**{
            "seedance-2-5": {"kind": "per_second", "currency": "CNY", "price": 2.0},
            "deepseek-chat": {"kind": "per_million_tokens", "currency": "CNY", "input": 1.0, "output": 2.0},
        }))
        self.addCleanup(pricing.set_pricing_table, None)
        self.sunk: list[tuple[str, dict]] = []
        usage_ledger.configure_sink(lambda task_id, entry: self.sunk.append((task_id, entry)))
        self.addCleanup(usage_ledger.configure_sink, None)
        usage_ledger.unattributed.clear()

    def test_a_call_inside_a_bound_task_is_written_onto_that_task_with_its_cost(self):
        with usage_ledger.bind_task("task-1", "stage_5"):
            entry = usage_ledger.record("video", provider="seedance", model="doubao-seedance-2-5-pro", status="success", units={"seconds": 10})

        self.assertEqual([(task_id, item["id"]) for task_id, item in self.sunk], [("task-1", entry["id"])])
        self.assertEqual((entry["cost"], entry["currency"], entry["purpose"], entry["priced"]), (20.0, "CNY", "stage_5", True))

    def test_a_failed_call_costs_nothing_and_an_unpriced_model_is_counted_as_such(self):
        with usage_ledger.bind_task("task-1"):
            failed = usage_ledger.record("video", provider="seedance", model="doubao-seedance-2-5-pro", status="failed", units={"seconds": 10}, error="HTTP 429")
            unpriced = usage_ledger.record("image", provider="qwen", model="wan-image", status="success", units={"images": 1})

        self.assertEqual((failed["cost"], failed["priced"]), (0.0, False))
        self.assertEqual((unpriced["cost"], unpriced["priced"]), (None, False))
        summary = usage_ledger.summarize([item for _, item in self.sunk])
        self.assertEqual((summary["calls"], summary["failed"], summary["unpriced_calls"]), (2, 1, 1))
        self.assertEqual(summary["unpriced_models"], ["wan-image"])
        self.assertEqual(summary["cost_by_currency"], {})

    def test_a_call_outside_any_task_is_kept_in_memory(self):
        usage_ledger.record("text", provider="deepseek", model="deepseek-chat", status="success", units={"input_tokens": 1000, "output_tokens": 1000})

        self.assertEqual(self.sunk, [])
        self.assertEqual(usage_ledger.unattributed[-1]["cost"], 0.003)

    def test_timed_call_records_success_failure_and_tokens_read_from_the_response(self):
        with usage_ledger.bind_task("task-2"):
            with usage_ledger.timed_call("text", provider="deepseek", model="deepseek-chat") as outcome:
                outcome["units"].update({"input_tokens": 2_000_000, "output_tokens": 0})
            with self.assertRaises(RuntimeError):
                with usage_ledger.timed_call("text", provider="deepseek", model="deepseek-chat"):
                    raise RuntimeError("boom")

        first, second = (item for _, item in self.sunk)
        self.assertEqual((first["status"], first["cost"]), ("success", 2.0))
        self.assertEqual((second["status"], second["cost"]), ("failed", 0.0))
        self.assertIn("RuntimeError", second["error"])
        self.assertIsNotNone(first["duration_ms"])

    def test_summary_totals_are_per_currency_and_never_added_together(self):
        records = [
            {"media_type": "video", "purpose": "stage_5", "status": "success", "priced": True, "cost": 10.0, "currency": "CNY"},
            {"media_type": "audio", "purpose": "stage_6", "status": "success", "priced": True, "cost": 0.5, "currency": "USD"},
            {"media_type": "video", "purpose": "stage_5", "status": "success", "priced": True, "cost": 5.0, "currency": "CNY"},
        ]
        summary = usage_ledger.summarize(records)
        self.assertEqual(summary["cost_by_currency"], {"CNY": 15.0, "USD": 0.5})
        self.assertEqual(summary["primary_currency"], "CNY")
        self.assertEqual(summary["by_purpose"]["stage_5"]["cost"], {"CNY": 15.0})

    def test_a_project_keeps_a_bounded_number_of_records(self):
        task = {"usage_records": [{"id": str(index)} for index in range(usage_ledger.MAX_RECORDS_PER_TASK)]}
        usage_ledger.append_to_task(task, {"id": "newest"})
        self.assertEqual(len(task["usage_records"]), usage_ledger.MAX_RECORDS_PER_TASK)
        self.assertEqual(task["usage_records"][-1]["id"], "newest")
        self.assertEqual(task["usage_records"][0]["id"], "1")


def _shot(shot_id: int, scene_id: str, *, duration: int | None = None, characters=None, dialogue: str = "", visual=None):
    shot = {"shot_id": shot_id, "scene_id": scene_id, "desc": "画面" * 20, "dialogue": dialogue, "characters": characters or []}
    if duration is not None:
        shot["duration"] = f"{duration}s"
    if visual is not None:
        shot["visual"] = visual
    return shot


def _task(shots, *, clips=None, sheets=None, scenes=None, model="seedance2.0", config_extra=None, status="idle"):
    state = {"engine": "structured-screenwriting", "episodes": {"1": {"script": {"scenes": scenes or []}}}}
    return {
        "task_id": "adm-1", "status": status, "stage_progress": {"stage": 5, "status": "running"} if status == "running" else {},
        "config": {"video_model": model, **(config_extra or {})},
        "assets": {"4": shots, "5": clips or [], "3_sheets": sheets or {}, "2_screenwriting": state},
    }


class VideoAdmissionTests(unittest.TestCase):
    def setUp(self):
        pricing.set_pricing_table(_pricing(**{"seedance": {"kind": "per_second", "currency": "CNY", "price": 1.0}}))
        self.addCleanup(pricing.set_pricing_table, None)

    def test_every_shot_in_order_is_admitted_with_a_quote_and_an_estimate(self):
        task = _task([_shot(1, "E1S01", duration=8), _shot(2, "E1S02", duration=10)], clips=[{"shot_id": 1, "video_url": "https://cdn/1.mp4"}])

        admission = assess_video_batch(task, provider_ready=lambda family, model: True)

        self.assertEqual(admission.decision, "admitted")
        self.assertEqual([shot.quote for shot in admission.shots], ["reuse", "generate"])
        self.assertEqual(admission.as_dict()["counts"], {"generate": 1, "reuse": 1, "blocked": 0, "withheld": 0})
        self.assertEqual(admission.estimate, {"shots_to_generate": 1, "requested_seconds": 10, "priced": True, "cost": 10.0, "currency": "CNY"})

    def test_a_stale_clip_is_generated_again_not_reused(self):
        task = _task([_shot(1, "E1S01", duration=8)], clips=[{"shot_id": 1, "video_url": "https://cdn/1.mp4", "stale": True}])
        self.assertEqual(assess_video_batch(task, provider_ready=lambda *_: True).shots[0].quote, "generate")

    def test_one_blocked_shot_withholds_the_whole_batch(self):
        scenes = [{"scene_id": "E1S02", "needs_replan": True, "utterances": []}]
        task = _task([_shot(1, "E1S01", duration=8), _shot(2, "E1S02", duration=8), _shot(3, "E1S03", duration=8, characters=["沈知微"])],
                     sheets={"萧景琰": "https://cdn/sheet.png"}, scenes=scenes)

        admission = assess_video_batch(task, provider_ready=lambda *_: True)

        self.assertEqual(admission.decision, "blocked")
        by_id = {shot.shot_id: shot for shot in admission.shots}
        self.assertEqual([p.code for p in by_id[2].problems], [video_admission.NEEDS_REPLAN])
        self.assertEqual([p.code for p in by_id[3].problems], [video_admission.MISSING_ASSETS])
        self.assertEqual(by_id[1].quote, "generate")
        self.assertEqual(by_id[1].withheld_by, [2, 3])
        self.assertEqual([p.code for p in by_id[1].problems], [video_admission.WITHHELD])
        self.assertIn("未提交任何镜头", admission.summary())
        self.assertEqual(admission.estimate["shots_to_generate"], 1)

    def test_mixed_speech_an_unconfigured_model_and_a_running_stage_all_block(self):
        mixed = {"scene_id": "E1S01", "utterances": [
            {"kind": "dialogue", "speaker": "林夏", "text": "你瞒了什么？"}, {"kind": "voiceover", "text": "她没有回答。"},
        ]}
        task = _task([_shot(1, "E1S01", duration=8)], scenes=[mixed])
        codes = [p.code for p in assess_video_batch(task, provider_ready=lambda *_: True).shots[0].problems]
        self.assertIn(video_admission.MIXED_SPEECH, codes)

        task = _task([_shot(1, "E1S01", duration=8)], model="")
        self.assertEqual([p.code for p in assess_video_batch(task).shots[0].problems], [video_admission.UNRESOLVABLE_MODEL])

        task = _task([_shot(1, "E1S01", duration=8)])
        self.assertEqual([p.code for p in assess_video_batch(task, provider_ready=lambda *_: False).shots[0].problems], [video_admission.PROVIDER_NOT_READY])

        task = _task([_shot(1, "E1S01", duration=8)], status="running")
        self.assertEqual([p.code for p in assess_video_batch(task, provider_ready=lambda *_: True).shots[0].problems], [video_admission.ACTIVE_TASK])

    def test_a_scripted_length_outside_the_tiers_asks_for_confirmation_then_clears(self):
        # seedance2.0 films up to 15 s; a 22 s shot is requested at the longest tier.
        task = _task([_shot(1, "E1S01", visual={"duration_seconds": 22, "candidates": 2}), _shot(2, "E1S02", duration=8)])

        admission = assess_video_batch(task, provider_ready=lambda *_: True)

        # The workspace already caps a shot at the model ceiling, so 22 s reads as the 15 s tier itself.
        self.assertEqual(admission.decision, "admitted")
        first = admission.shots[0]
        self.assertEqual((first.scripted_seconds, first.requested_seconds, first.tier_adjustment, first.candidates), (15, 15, "exact", 2))
        self.assertEqual(admission.confirmations, [])
        # The workspace caps at the model ceiling; a value that lands between tiers is what needs confirming.
        task = _task([_shot(1, "E1S01", duration=8)], model="seedance2.0")
        with patch("app.core.video_admission.renderable_shot_durations", return_value=[5, 10]):
            admission = assess_video_batch(task, provider_ready=lambda *_: True)
            self.assertEqual(admission.decision, "confirmation_required")
            self.assertEqual(admission.confirmations[0]["shot_ids"], [1])
            self.assertEqual((admission.confirmations[0]["scripted_seconds"], admission.confirmations[0]["requested_seconds"]), (8, 10))
            self.assertEqual(admission.confirmations[0]["cost"], 10.0)
            self.assertIn("需先确认请求档位", admission.summary())

            cleared = assess_video_batch(task, provider_ready=lambda *_: True, confirmed_request_durations=[{"scripted_seconds": 8, "requested_seconds": 10}])
            self.assertEqual(cleared.decision, "admitted")
            task["config"]["confirmed_request_durations"] = [{"scripted_seconds": 8, "requested_seconds": 10}]
            self.assertEqual(assess_video_batch(task, provider_ready=lambda *_: True).decision, "admitted")

    def test_an_unpriced_model_shows_no_total_rather_than_a_low_one(self):
        pricing.set_pricing_table(_pricing())
        task = _task([_shot(1, "E1S01", duration=8)])
        admission = assess_video_batch(task, provider_ready=lambda *_: True)
        self.assertEqual((admission.estimate["priced"], admission.estimate["cost"]), (False, None))


class StageFiveGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service = DramaService()
        self.service.repo = self.repo
        pricing.set_pricing_table(_pricing(**{"seedance": {"kind": "per_second", "currency": "CNY", "price": 1.0}}))
        self.addCleanup(pricing.set_pricing_table, None)

    def _save(self, task):
        task = {**task, "logs": {}, "stage_completions": {str(n): {"status": "success", "script_revision": 0} for n in range(1, 5)}}
        task["assets"].update({
            "1": "方案", "2": "第1集 开场", "3": "角色", "3_sheets": task["assets"].get("3_sheets") or {"萧景琰": "https://cdn/s.png"},
            "3_character_dashboard": {"state": "READY"}, "4_storyboard": "sb", "4_grid": "g", "4_quality": {"passed": True},
        })
        self.repo.save_task("adm-1", task)
        return task

    def test_stage_five_refuses_to_start_on_a_blocked_batch_and_records_why(self):
        task = self._save(_task([_shot(1, "E1S01", duration=8, characters=["沈知微"])], sheets={"别人": "https://cdn/s.png"}))

        with patch.object(self.service.gateway, "video_family_ready", return_value=True):
            with self.assertRaisesRegex(StagePrerequisiteError, "沈知微"):
                self.service._assert_stage_prerequisites(task, 5)
        self.assertEqual(task["assets"]["5_admission"]["decision"], "blocked")

    def test_confirmed_tiers_are_kept_on_the_project_and_clear_the_gate(self):
        self._save(_task([_shot(1, "E1S01", duration=8)]))
        with patch("app.core.video_admission.renderable_shot_durations", return_value=[5, 10]), patch.object(self.service.gateway, "video_family_ready", return_value=True):
            first = self.service.assess_video_admission("adm-1")
            self.assertEqual(first["decision"], "confirmation_required")
            second = self.service.assess_video_admission("adm-1", confirmed_request_durations=first["confirmations"], persist_confirmations=True)
            self.assertEqual(second["decision"], "admitted")
            stored = self.repo.get_task("adm-1")
            self.assertEqual(stored["config"]["confirmed_request_durations"], [{"scripted_seconds": 8, "requested_seconds": 10}])
            self.assertEqual(stored["assets"]["5_admission"]["decision"], "admitted")
            self.service._assert_stage_prerequisites(stored, 5)

    def test_usage_summary_reads_the_records_written_by_the_sink(self):
        self._save(_task([]))
        with usage_ledger.bind_task("adm-1", "stage_5"):
            usage_ledger.record("video", provider="seedance", model="seedance2.0", status="success", units={"seconds": 6})
        summary = self.service.usage_summary("adm-1")
        self.assertEqual(summary["summary"]["cost_by_currency"], {"CNY": 6.0})
        self.assertEqual(summary["records"][0]["purpose"], "stage_5")


class SpeechOwnershipTests(unittest.TestCase):
    def test_a_shot_has_one_voice(self):
        dialogue = {"scene_id": "E1S01", "utterances": [{"kind": "dialogue", "speaker": "林夏", "text": "走。"}]}
        narration = {"scene_id": "E1S02", "utterances": [{"kind": "voiceover", "text": "夜深了。"}]}
        narrator_named = {"scene_id": "E1S03", "utterances": [{"kind": "dialogue", "speaker": "旁白", "text": "夜深了。"}]}
        silent = {"scene_id": "E1S04", "utterances": []}
        mixed = {"scene_id": "E1S05", "utterances": dialogue["utterances"] + narration["utterances"]}

        self.assertEqual([speech_mode(s) for s in (dialogue, narration, narrator_named, silent)], ["character_speech", "narrator_voiceover", "narrator_voiceover", "silent"])
        self.assertEqual(speech_problems(dialogue), [])
        self.assertEqual([code for code, _ in speech_problems(mixed)], ["mixed_speech"])

    def test_plan_validation_sends_a_mixed_shot_back_and_flags_it_for_replanning(self):
        scenes = [{"scene_id": "E1S01", "duration_seconds": 8, "characters_in_scene": ["林夏"], "utterances": [
            {"kind": "dialogue", "speaker": "林夏", "text": "走。"}, {"kind": "voiceover", "text": "夜深了。"},
        ]}]
        ctx = violations.PlanCheckContext(episode=1, supported_durations=list(range(4, 16)))
        result = violations.check_script_plan(scenes, ctx, repair=True)
        self.assertIn("mixed_speech", [v.code for v in result.errors])
        self.assertEqual(violations.mark_replan_flags(scenes, ctx), ["E1S01"])

    def test_post_production_projects_leave_narration_out_of_the_voice_track(self):
        self.assertEqual(narration_delivery({}), "use_tts")
        self.assertEqual(narration_delivery({"narration_delivery": "post_production"}), "post_production")
        self.assertEqual(narration_delivery({"narration_delivery": "radio"}), "use_tts")
        cell = "旁白：夜雨压着宫城。 萧景琰：儿臣会回来。"
        voiced = [line[0] for line in parse_shot_dialogue(cell, "萧景琰", "沈氏", "male", "female")]
        later = [line[0] for line in parse_shot_dialogue(cell, "萧景琰", "沈氏", "male", "female", voice_narration=False)]
        self.assertEqual(voiced, ["夜雨压着宫城。", "儿臣会回来。"])
        self.assertEqual(later, ["儿臣会回来。"])


class SubtitleDraftTests(unittest.TestCase):
    def test_sentences_break_at_cjk_and_latin_terminals(self):
        self.assertEqual(split_sentences("你瞒了什么？我不信。走…"), ["你瞒了什么？", "我不信。", "走…"])
        self.assertEqual(split_sentences("Wait. Who are you? Go!"), ["Wait.", "Who are you?", "Go!"])

    def test_cues_share_each_shot_by_reading_length_and_never_overlap(self):
        scenes = [
            {"scene_id": "E1S01", "duration_seconds": 10, "utterances": [
                {"kind": "dialogue", "speaker": "林夏", "text": "你瞒了什么？我不信。"},
            ]},
            {"scene_id": "E1S02", "duration_seconds": 5, "utterances": [{"kind": "voiceover", "text": "夜深了。"}]},
            {"scene_id": "E1S03", "duration_seconds": 4, "utterances": []},
        ]
        cues = episode_cues(scenes)

        self.assertEqual([cue.text for cue in cues], ["你瞒了什么？", "我不信。", "夜深了。"])
        self.assertEqual((cues[0].start, cues[1].end), (0.0, 10.0))
        self.assertLess(cues[0].end, cues[1].start + 1e-9)
        self.assertEqual((cues[2].start, cues[2].end, cues[2].kind, cues[2].speaker), (10.0, 15.0, "voiceover", None))
        self.assertEqual(cues[0].speaker, "林夏")
        srt = render_srt(cues)
        self.assertIn("1\n00:00:00,000 --> ", srt)
        self.assertIn("00:00:10,000 --> 00:00:15,000\n夜深了。", srt)
        self.assertIn("林夏：你瞒了什么？", render_srt(cues, with_speakers=True))


if __name__ == "__main__":
    unittest.main()

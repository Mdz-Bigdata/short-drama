"""成片自动验收：截帧拼联系表交给看图模型打分；完成 = 验收过 + 人说「确认发布」。"""

import asyncio
import base64
import io
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from PIL import Image

from app.core import film_review
from app.service.drama_service import StagePrerequisiteError
from tests import test_workflow_guide as guide
from tests.test_workflow_guide import outputs, task_at

GOOD = {
    "identity_consistency": 0.95, "anatomy_integrity": 0.93, "expression_fidelity": 0.9, "photorealism": 0.92,
    "temporal_continuity": 0.91, "dialogue_emotion_timing": 0.88, "lip_sync": 0.86, "hard_defects": [], "notes": "人物稳定，画面连贯",
}
BAD = {**GOOD, "anatomy_integrity": 0.5, "hard_defects": ["第7格右手六根手指"], "notes": "手部畸形"}


def _frames(count=12):
    return [(second, Image.new("RGB", (320, 568), (20 * index % 255, 90, 120))) for index, second in enumerate(range(count))]


class HelpersTests(unittest.TestCase):
    def test_frames_spread_evenly_and_skip_the_very_ends(self):
        self.assertEqual(film_review.timestamps(60, 4), [7.5, 22.5, 37.5, 52.5])
        self.assertEqual(film_review.timestamps(0, 4), [])

    def test_scores_are_read_clamped_and_a_missing_one_is_an_error(self):
        parsed = film_review.parse_scores("好的：" + json.dumps({**GOOD, "photorealism": 1.4}) + " 以上")
        self.assertEqual(parsed["scores"]["photorealism"], 1.0)
        self.assertEqual(parsed["notes"], "人物稳定，画面连贯")
        with self.assertRaises(film_review.FilmReviewError):
            film_review.parse_scores(json.dumps({key: value for key, value in GOOD.items() if key != "lip_sync"}))
        with self.assertRaises(film_review.FilmReviewError):
            film_review.parse_scores("看不清")

    def test_the_contact_sheet_is_one_picture_in_time_order(self):
        uri = film_review.contact_sheet(_frames(8))
        with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as sheet:
            self.assertEqual(sheet.width, 4 * 640)
            self.assertEqual(sheet.height, 2 * round(640 * 568 / 320))

    def test_one_vision_call_and_recorded_sound_checks_can_only_lower_the_dialogue_score(self):
        calls = []

        def describe(system, prompt, image):
            calls.append(image)
            return json.dumps(GOOD)

        clips = [{"sound_checks": [{"passed": True}, {"passed": False}]}]
        measurements, record = film_review.review("film.mp4", describe, clips=clips, frames=_frames(6))
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("data:image/jpeg;base64,"))
        self.assertEqual(measurements.dialogue_emotion_timing, 0.5)
        self.assertEqual(record["sources"]["dialogue_emotion_timing"], "分镜声音质检通过率")
        self.assertEqual(record["sources"]["lip_sync"], "联系表看图")


class WholeFilmScanTests(unittest.TestCase):
    """ffmpeg 逐帧扫整片：黑场、半边全黑、定格，模型只看十来帧时漏掉的这里补上。"""

    def setUp(self):
        from app.core import media_compositor

        self.ffmpeg = media_compositor._ffmpeg()
        if not self.ffmpeg:
            self.skipTest("no ffmpeg")
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def _film(self, filters: str, seconds: int = 12) -> str:
        import os
        import subprocess

        path = os.path.join(self.temp.name, "film.mp4")
        subprocess.run(
            [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", f"testsrc2=size=360x640:rate=25:duration={seconds}", "-vf", filters, "-pix_fmt", "yuv420p", path],
            check=True, timeout=120,
        )
        return path

    def test_black_half_black_and_frozen_stretches_are_found_with_their_times(self):
        path = self._film(
            "drawbox=enable='between(t,2.5,7)':x=0:y=0:w=iw:h=ih/2:color=black:t=fill,"
            "drawbox=enable='between(t,7.5,8.5)':x=0:y=0:w=iw:h=ih:color=black:t=fill,"
            "loop=loop=75:size=1:start=225",
            seconds=13,
        )
        self.assertEqual(film_review.scan_defects(path), [
            "00:02.5–00:07.0 画面上方大片黑边（4.5 秒，整片扫描）",
            "00:07.5–00:08.5 画面全黑（1.0 秒，整片扫描）",
            "00:09.0–00:12.0 画面定格不动（3.0 秒，整片扫描）",
        ])

    def test_a_short_dark_band_on_one_side_is_composition_not_a_defect(self):
        path = self._film("drawbox=enable='between(t,5,7)':x=0:y=0:w=iw:h=ih*0.4:color=black:t=fill")
        self.assertEqual(film_review.scan_defects(path), [])

    def test_a_landscape_clip_letterboxed_into_the_vertical_frame_is_named_as_such(self):
        path = self._film(
            "drawbox=enable='between(t,5,8)':x=0:y=0:w=iw:h=ih*0.34:color=black:t=fill,"
            "drawbox=enable='between(t,5,8)':x=0:y=ih*0.66:w=iw:h=ih*0.34:color=black:t=fill"
        )
        self.assertEqual(film_review.scan_defects(path), ["00:05.0–00:08.0 画面上下都是黑边，疑似横版素材塞进竖屏（3.0 秒，整片扫描）"])

    def test_the_title_card_and_the_closing_fade_are_not_defects(self):
        path = self._film(
            "drawbox=enable='between(t,0,2)':x=0:y=0:w=iw:h=ih:color=black:t=fill,"
            "drawbox=enable='gte(t,10.5)':x=0:y=0:w=iw:h=ih:color=black:t=fill"
        )
        self.assertEqual(film_review.scan_defects(path), [])

    def test_scan_findings_fail_the_gate_even_when_the_frames_look_fine(self):
        path = self._film("drawbox=enable='between(t,5,6.5)':x=0:y=0:w=iw:h=ih:color=black:t=fill")
        measurements, record = film_review.review(path, lambda *_: json.dumps(GOOD), frames=_frames(4))
        self.assertEqual(record["scanned_defects"], ["00:05.0–00:06.5 画面全黑（1.5 秒，整片扫描）"])
        self.assertIn("00:05.0–00:06.5 画面全黑（1.5 秒，整片扫描）", measurements.hard_defects)


class ReviewFlowTests(guide.WorkflowGuideTests):
    """Runs on the workflow fixtures; only these tests, not the inherited ones."""

    def _finished(self):
        task = task_at(8)
        self.save(task)
        return task

    def _review(self, scores):
        self.service.gateway.describe_image.return_value = (json.dumps(scores), "vision-model")
        with patch.object(film_review, "sample_frames", return_value=_frames()):
            return self.service.review_film("workflow")

    def test_a_good_film_passes_and_waits_for_the_sign_off(self):
        self._finished()
        task = self._review(GOOD)
        self.assertTrue(task["assets"]["7"]["quality_gate"]["passed"])
        self.assertEqual(task["status"], "awaiting_council_review")
        self.assertEqual(task["assets"]["7"]["auto_review"]["notes"], "人物稳定，画面连贯")
        self.assertTrue(task["assets"]["8"]["release_report"]["advisory"])
        self.assertIn("确认发布", task["chat_history"][-1]["content"])
        snapshot = self.service.workflow_snapshot(task)
        self.assertEqual(snapshot["mode"], "review")
        self.assertIn("确认发布", snapshot["hint"])

    def test_a_weak_film_fails_with_its_defects_and_what_to_do(self):
        self._finished()
        task = self._review(BAD)
        self.assertFalse(task["assets"]["7"]["quality_gate"]["passed"])
        said = task["chat_history"][-1]["content"]
        self.assertIn("anatomy_integrity", said)
        self.assertIn("第7格右手六根手指", said)
        self.assertIn("验收成片", said)

    def test_the_sign_off_completes_the_project_only_after_a_review(self):
        self._finished()
        with self.assertRaises(StagePrerequisiteError):
            self.service.confirm_release("workflow")
        self._review(GOOD)
        task = self.service.confirm_release("workflow", by="u1")
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["assets"]["8"]["human_release"]["by"], "u1")
        self.assertTrue(self.service.workflow_snapshot(task)["release_ready"])
        self.assertEqual(self.service.workflow_snapshot(task)["mode"], "completed")

    def test_one_sentence_makes_reviews_and_one_more_releases_the_film(self):
        self.save(task_at(0))

        def fake_worker(task_id, stage, *, _claimed_task):
            task = deepcopy(_claimed_task)
            task["assets"].update(outputs(stage))
            task["stage_progress"]["status"] = "success"
            self.save(task)
            return task

        self.service.gateway.describe_image.return_value = (json.dumps(GOOD), "vision-model")

        async def talk(message):
            response = await self.service.assistant_message("workflow", message)
            pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            await asyncio.gather(*pending)
            return response

        with patch.object(self.service, "_execute_stage_blocking", side_effect=fake_worker), \
             patch.object(film_review, "sample_frames", return_value=_frames()):
            self.assertEqual(asyncio.run(talk("不用确认，帮我从头到尾自动生成成片"))["action"], "run_all")
            task = self.service.repo.get_task("workflow")
            self.assertTrue(task["assets"]["7"]["quality_gate"]["passed"], "the film was reviewed right after the run")
            self.assertIn("成片自动验收已通过", task["chat_history"][-1]["content"])
            self.assertNotIn("auto_review_pending", task["assets"]["7"], "the page stops polling once the verdict is in")
            self.assertEqual(asyncio.run(talk("确认发布"))["action"], "release")
        self.assertEqual(self.service.workflow_snapshot(self.service.repo.get_task("workflow"))["mode"], "completed")


# Only the tests written here; the inherited WorkflowGuideTests run in their own module.
for _name in [name for name in vars(guide.WorkflowGuideTests) if name.startswith("test_")]:
    if _name not in vars(ReviewFlowTests):
        setattr(ReviewFlowTests, _name, None)


if __name__ == "__main__":
    unittest.main()

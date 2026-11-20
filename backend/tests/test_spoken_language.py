# -*- coding: utf-8 -*-
"""对白语言：项目选的方言或外语写进视频提示词的「对白语言」一行。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import clip_skeleton, prompt_data, spoken_language
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService

WORDING = prompt_data.load("spoken_language")


class ChoiceTests(unittest.TestCase):
    def test_the_default_comes_first_and_says_nothing(self):
        self.assertEqual(spoken_language.options()[0], {"key": "", "label": "普通话"})
        self.assertEqual(spoken_language.phrase({}), "")
        self.assertEqual(spoken_language.phrase({"spoken_language": "nope"}), "")

    def test_a_dialect_says_how_it_must_sound(self):
        phrase = spoken_language.phrase({"spoken_language": "Sichuan"})
        for words in ("四川话", "地道的四川话口音和口语节奏", "按当地读音", "不按字面念成普通话"):
            self.assertIn(words, phrase)

    def test_a_project_written_in_english_speaks_english_unless_something_else_was_picked(self):
        self.assertEqual(spoken_language.of({"content_language": "en"}), "english")
        self.assertIn("英语", spoken_language.phrase({"content_language": "en"}))
        self.assertEqual(spoken_language.of({"content_language": "en", "spoken_language": "cantonese"}), "cantonese")
        self.assertEqual(spoken_language.of({"content_language": "zh"}), "")

    def test_no_phrase_breaks_the_line_it_is_written_into(self):
        # The line is cut at its commas when several moments are merged into one clip.
        for item in WORDING["options"]:
            phrase = spoken_language.phrase({"spoken_language": item["key"]})
            self.assertNotIn("，", phrase)
            self.assertNotIn("。", phrase)

    def test_an_unknown_choice_is_refused(self):
        self.assertEqual(spoken_language.checked(" Sichuan "), "sichuan")
        self.assertEqual(spoken_language.checked(None), "")
        with self.assertRaises(ValueError):
            spoken_language.checked("klingon")


class LineTests(unittest.TestCase):
    def test_the_line_is_unchanged_without_a_choice(self):
        self.assertEqual(clip_skeleton.dialogue_language("seedance", ["沈砚"]), clip_skeleton.dialogue_language("seedance", ["沈砚"], language=""))
        self.assertIn("说中文普通话，口型按该语言同步，不说别的语言。", clip_skeleton.dialogue_language("seedance", ["沈砚"]))

    def test_the_line_names_the_dialect_for_models_that_speak_and_stays_empty_for_the_rest(self):
        phrase = spoken_language.phrase({"spoken_language": "sichuan"})
        line = clip_skeleton.dialogue_language("seedance", ["沈砚"], ["先生"], language=phrase)
        self.assertIn(f"说{phrase}，口型按该语言同步，不说别的语言。", line)
        self.assertNotIn("普通话，", line)
        self.assertEqual(clip_skeleton.dialogue_language("plain", ["沈砚"], language=phrase), "")

    def test_several_moments_merged_into_one_clip_keep_the_dialect(self):
        phrase = spoken_language.phrase({"spoken_language": "cantonese"})
        beats = [
            {"dialogue_language": clip_skeleton.dialogue_language("seedance", ["沈砚"], language=phrase)},
            {"dialogue_language": clip_skeleton.dialogue_language("seedance", ["贺兰霆"], language=phrase)},
        ]
        merged = clip_skeleton.merge(beats, model="seedance-2-5", cast=["沈砚", "贺兰霆"])
        self.assertIn(f"说{phrase}，", merged["dialogue_language"])
        self.assertIn("沈砚", merged["dialogue_language"])
        self.assertIn("贺兰霆", merged["dialogue_language"])


class SettingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("t", {"task_id": "t", "config": {"video_model": "seedance-2-5"}, "assets": {}})
        self.service = DramaService()
        self.service.repo = self.repo
        workspace = patch.object(self.service, "get_shot_visual_workspace", return_value={"ok": True})
        workspace.start()
        self.addCleanup(workspace.stop)

    def test_a_choice_is_saved_cleared_and_an_unknown_one_refused(self):
        self.service.set_spoken_language("t", "sichuan")
        self.assertEqual(self.repo.get_task("t")["config"]["spoken_language"], "sichuan")
        self.service.set_spoken_language("t", "")
        self.assertNotIn("spoken_language", self.repo.get_task("t")["config"])
        with self.assertRaises(ValueError):
            self.service.set_spoken_language("t", "klingon")
        self.assertIsNone(self.service.set_spoken_language("nope", "sichuan"))


if __name__ == "__main__":
    unittest.main()

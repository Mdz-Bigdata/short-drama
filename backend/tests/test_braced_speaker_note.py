"""A delivery note in braces right after the speaker (「雷九斤{低沉…}：台词」) is a note, not the spoken line.

Braces usually hold what is said in this project (``{谁？}停顿一拍{谁动的剑？}``), so the note was read as the line:
the subtitle, the dub check, the H3 verbatim check and the clip's length all followed the note instead of the words.
"""

import unittest

from app.core import h3_native
from app.core.shot_table_rules import dialogue_seconds
from app.core.spoken_lines import dialogue_segments, labelled_lines, speaker_notes_in_parentheses, spoken_lines
from app.core.video_prompt_engine import format_dialogue

CELL = "雷九斤{低沉沙哑偏厚、压着嗓子，语速约每秒2.2字，开口前停半拍}：磨刀的，跪下。"


class BracedSpeakerNoteTest(unittest.TestCase):
    def test_the_note_becomes_a_note_and_the_words_are_the_line(self):
        self.assertEqual(spoken_lines([CELL]), ["磨刀的，跪下。"])
        self.assertEqual(labelled_lines(CELL), [("雷九斤", "低沉沙哑偏厚、压着嗓子，语速约每秒2.2字，开口前停半拍", "磨刀的，跪下。")])
        self.assertEqual(dialogue_segments(CELL), ["雷九斤（低沉沙哑偏厚、压着嗓子，语速约每秒2.2字，开口前停半拍）：磨刀的，跪下。"])

    def test_the_clip_is_timed_by_the_words_not_the_note(self):
        self.assertAlmostEqual(dialogue_seconds(CELL), dialogue_seconds("雷九斤（低沉沙哑偏厚、压着嗓子，语速约每秒2.2字，开口前停半拍）：磨刀的，跪下。"))
        self.assertLess(dialogue_seconds(CELL), 4)

    def test_the_h3_check_and_the_video_prompt_keep_the_words(self):
        request = h3_native.request("画面", beat_seconds=[5.0], seconds=5, frames=124, dialogue=[CELL])
        self.assertEqual(request.dialogue, ["磨刀的，跪下。"])
        written = format_dialogue(CELL, ["雷九斤"])
        self.assertIn("{磨刀的，跪下。}", written)
        self.assertNotIn("{低沉沙哑", written)

    def test_braces_that_hold_speech_and_the_other_shapes_read_as_before(self):
        cases = {
            "沈磨：{谁？}停顿一拍{谁动的剑？}": ["谁？", "谁动的剑？"],
            "{落。}（低沉）": ["落。"],
            "裴仲玄（语速缓）：落。": ["落。"],
            "姜照：握着。沈无咎{冷}：握了。": ["握着。", "握了。"],
            "无": [],
        }
        for cell, lines in cases.items():
            with self.subTest(cell=cell):
                self.assertEqual(spoken_lines([cell]), lines)
        self.assertEqual(speaker_notes_in_parentheses("沈磨：{谁？}"), "沈磨：{谁？}")
        self.assertEqual(speaker_notes_in_parentheses("老账{咳(两声)}：走"), "老账（咳［两声］）：走")


if __name__ == "__main__":
    unittest.main()

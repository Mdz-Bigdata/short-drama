"""Only words that are said reach the subtitle (and the video prompt's spoken braces).

From 《钝刀》 (2026-11-16): a delivery note in braces, a 「无台词，嘴唇未动…」 direction and an edit cue
(「第 3.5 秒起，…」——说完停 1.5 秒…) were burnt into the film as if they were lines.
"""

import unittest

from app.core import edit_timeline
from app.core.edit_timeline import _subtitle_of
from app.core.spoken_lines import labelled_lines, spoken_lines
from app.core.video_prompt_engine import format_dialogue

NO_LINE = "雷九斤：沈磨——（先张口无声，气声起，尾音散进雨里，未喊完）／沈磨：无台词，嘴唇未动，只把下颌向上抬起半寸"
CUES = "第 3.5 秒起，沈磨（语速约每秒 3 字，句尾沉下）：「我姓沈，沈家最后一把刀。」——说完不接解释，停 1.5 秒只留雨声。第 7.5 秒起，雷九斤（气声、断续，尾音发虚）：「不……不可能。」"
BRACED_NOTE = "雷九斤{低沉沙哑偏厚、压着嗓子，语速约每秒2.2字，开口前停半拍}：磨刀的，跪下。"


class SubtitleTest(unittest.TestCase):
    def test_a_no_line_direction_is_not_a_line(self):
        self.assertEqual(spoken_lines([NO_LINE]), ["沈磨——"])
        self.assertEqual(_subtitle_of({"dialogue": NO_LINE}), "沈磨——")
        for cell in ("沈磨：无台词", "沈磨：不开口，只抬眼", "沈磨（画外）：无对白。"):
            self.assertEqual(spoken_lines([cell]), [], cell)

    def test_edit_cues_and_directions_after_a_quoted_line_are_not_said(self):
        self.assertEqual(spoken_lines([CUES]), ["我姓沈，沈家最后一把刀。", "不……不可能。"])
        self.assertEqual(_subtitle_of({"dialogue": CUES}), "我姓沈，沈家最后一把刀。 不……不可能。")
        self.assertEqual([line for _, _, line in labelled_lines(CUES)], ["我姓沈，沈家最后一把刀。", "不……不可能。"])

    def test_the_braced_delivery_note_stays_out(self):
        self.assertEqual(_subtitle_of({"dialogue": BRACED_NOTE}), "磨刀的，跪下。")

    def test_real_lines_that_look_alike_are_kept(self):
        cases = {
            "沈磨：无论如何，我不跪。": ["无论如何，我不跪。"],
            "沈磨：不说话我也知道。": ["不说话我也知道。"],
            "沈磨：他说「走」，我就走。": ["他说走，我就走。"],
            "沈磨：三秒后再说。": ["三秒后再说。"],
            "约第10秒起，雷九斤：你——": ["你——"],
        }
        for cell, expected in cases.items():
            self.assertEqual(spoken_lines([cell]), expected, cell)

    def test_the_video_prompt_does_not_ask_anyone_to_say_a_direction(self):
        written = format_dialogue(NO_LINE, ["沈磨", "雷九斤"], on_screen=["沈磨", "雷九斤"])
        self.assertIn("{沈磨——}", written)
        self.assertNotIn("无台词", written)
        self.assertIn("闭口不出声", written)


class SavedTimelineTest(unittest.TestCase):
    """A timeline saved with an older reading gets its automatic subtitles read again; a person's are kept."""

    def setUp(self):
        self.shots = [
            {"scene_id": "E1S01", "shot_id": 1, "video_url": "/media/a.mp4", "duration": 5, "dialogue": BRACED_NOTE},
            {"scene_id": "E1S08", "shot_id": 1, "video_url": "/media/b.mp4", "duration": 5, "dialogue": CUES},
            {"scene_id": "E1S12", "shot_id": 1, "video_url": "/media/c.mp4", "duration": 5, "dialogue": NO_LINE},
            {"scene_id": "E1S13", "shot_id": 1, "video_url": "/media/d.mp4", "duration": 5, "dialogue": "沈磨：走。"},
        ]
        self.task = {"assets": {"5": self.shots}}
        self.timeline = edit_timeline.build(self.task)
        stale = ["低沉沙哑偏厚、压着嗓子，语速约每秒2.2字，开口前停半拍",
                 "我姓沈，沈家最后一把刀。——说完不接解释，停1.5秒只留雨声。第7.5秒起，雷九斤：不……不可能。",
                 "沈磨—— 无台词，嘴唇未动，只把下颌向上抬起半寸", "走吧，别回头。"]
        for clip, text in zip(self.timeline["clips"], stale):
            clip["subtitle"] = text

    def test_automatic_subtitles_are_read_again_and_a_persons_wording_stays(self):
        fixed = edit_timeline.with_spoken_subtitles(self.timeline, self.task)
        self.assertEqual([clip["subtitle"] for clip in fixed["clips"]],
                         ["磨刀的，跪下。", "我姓沈，沈家最后一把刀。 不……不可能。", "沈磨——", "走吧，别回头。"])
        self.assertIsNot(fixed, self.timeline, "a changed timeline is a new one, so it gets saved")
        self.assertIs(edit_timeline.with_spoken_subtitles(fixed, self.task), fixed, "nothing left to change")

    def test_a_subtitle_typed_in_the_editor_is_never_replaced(self):
        typed = edit_timeline.set_subtitle(self.timeline, 1, "低沉沙哑偏厚", shot_uid=self.timeline["clips"][0]["shot_uid"])
        kept = edit_timeline.with_spoken_subtitles(typed, self.task)
        self.assertEqual(kept["clips"][0]["subtitle"], "低沉沙哑偏厚")
        self.assertTrue(edit_timeline.refresh(typed, self.task)["clips"][0]["subtitle_edited"], "the mark survives a rebuild")


class FilmCarriesEveryLineTest(unittest.TestCase):
    def test_a_scripted_line_missing_from_the_cut_is_named_before_delivery(self):
        from app.core import delivery_check

        scenes = [{"scene_id": "E1S08", "dialogue": [
            {"kind": "dialogue", "speaker": "沈磨", "text": "我姓沈，沈家最后一把刀。"},
            {"kind": "dialogue", "speaker": "雷九斤", "text": "不……不可能。"},
            {"kind": "action", "text": "雨声"},
        ]}]
        task = {"assets": {"2_breakdown": {"scenes": scenes}}}
        whole = {"clips": [{"subtitle": "我姓沈，沈家最后一把刀。 不……不可能。"}]}
        cut = {"clips": [{"subtitle": "我姓沈，沈家最后一把刀。"}]}
        self.assertEqual(delivery_check._missing_lines(task, whole), [])
        missing = delivery_check._missing_lines(task, cut)
        self.assertEqual(len(missing), 1)
        self.assertIn("不……不可能。", missing[0]["detail"])
        self.assertEqual((missing[0]["layer"], missing[0]["tier"]), ("内容", "must"))
        self.assertEqual(delivery_check._missing_lines(task, {**cut, "settings": {"subtitles": False}}), [], "no subtitles, nothing to read")


if __name__ == "__main__":
    unittest.main()

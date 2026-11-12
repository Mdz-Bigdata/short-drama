# -*- coding: utf-8 -*-
"""素材来源与授权记录：每样素材记来源；说不清使用范围的进验收单要人确认，记下授权说明后不再列出。"""

import unittest
from unittest.mock import patch

from app.core import delivery_check, rights_ledger
from tests.test_delivery_check import _clip, _task, _timeline


def _cut(**bgm):
    clips = [_clip("S1", 1, "全景"), _clip("S1", 2, "近景")]
    timeline = _timeline(clips)
    timeline["bgm"] = bgm or {"source": "none"}
    for clip in timeline["clips"]:
        clip["native_available"], clip["audio_source"] = True, "native"
    return _task(clips, []), timeline


class RightsTests(unittest.TestCase):
    def test_generated_material_is_recorded_and_a_system_font_needs_confirming(self):
        task, timeline = _cut(source="generated")
        task["config"] = {"video_model": "MiniMax-H3"}
        with patch("app.core.media_compositor._font_path", return_value="/System/Library/Fonts/STHeiti Medium.ttc"):
            items = {item["key"]: item for item in rights_ledger.items(task, timeline)}
        self.assertEqual(items["video"]["status"], "recorded")
        self.assertIn("MiniMax-H3", items["video"]["detail"])
        self.assertEqual(items["music:generated"]["status"], "recorded")
        self.assertEqual(items["voice:native"]["status"], "recorded")
        self.assertEqual(items["font:STHeiti Medium.ttc"]["status"], "confirm")

    def test_an_open_font_and_an_uploaded_track(self):
        task, timeline = _cut(source="library", library_id="abc", name="雨夜")
        with patch("app.core.media_compositor._font_path", return_value="/usr/share/fonts/NotoSansCJK-Regular.ttc"), \
             patch("app.core.bgm_library.get_track", return_value={"id": "abc", "name": "雨夜", "source": "upload"}):
            items = {item["key"]: item for item in rights_ledger.items(task, timeline)}
        self.assertEqual(items["font:NotoSansCJK-Regular.ttc"]["status"], "recorded")
        self.assertEqual(items["music:library:abc"]["status"], "confirm")

    def test_a_noted_licence_takes_the_item_off_the_checklist(self):
        task, timeline = _cut(source="none")
        with patch("app.core.media_compositor._font_path", return_value="/System/Library/Fonts/STHeiti Medium.ttc"):
            rights = [item for item in delivery_check.report(task, timeline) if item["rule"] == "rights"]
            self.assertEqual([item["rights_key"] for item in rights], ["font:STHeiti Medium.ttc"])
            self.assertEqual((rights[0]["layer"], rights[0]["tier_label"]), ("授权", "需人工确认"))
            task["config"] = {}
            rights_ledger.note(task["config"], "font:STHeiti Medium.ttc", "已购方正商用授权，合同在共享盘/授权/字体")
            self.assertEqual([item for item in delivery_check.report(task, timeline) if item["rule"] == "rights"], [])
            items = {item["key"]: item for item in rights_ledger.items(task, timeline)}
        self.assertIn("已购方正商用授权", items["font:STHeiti Medium.ttc"]["detail"])
        rights_ledger.note(task["config"], "font:STHeiti Medium.ttc", "")
        self.assertEqual(task["config"]["rights_notes"], {}, "an empty note takes it back")


class BundledFontTests(unittest.TestCase):
    def test_subtitles_use_the_bundled_open_licence_font_and_it_needs_no_confirming(self):
        import os

        from app.core import media_compositor

        with patch.dict(os.environ, {"SUBTITLE_FONT_PATH": ""}):
            path = media_compositor._font_path()
        self.assertEqual(path, media_compositor.BUNDLED_FONT)
        with open(path, "rb") as font:
            self.assertEqual(font.read(4), b"OTTO", "a real OpenType font, not an error page")
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(path), "SourceHanSans-LICENSE.txt")))
        task, timeline = _cut(source="none")
        self.assertEqual([item for item in delivery_check.report(task, timeline) if item["rule"] == "rights"], [])


if __name__ == "__main__":
    unittest.main()

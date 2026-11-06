"""Fountain uploads become the same episodes, characters and scenes as any other script."""

import unittest

from app.core.script_prompt_pipeline import ScriptPromptPipeline
from app.core.writer_dashboard import split_script_by_episode
from app.ingest.fountain import parse_fountain
from app.ingest.parsers import SourceIngestError, SourceIngestor
from app.story.story_graph import StoryGraphBuilder

ENGLISH = """Title:
    _**BRICK & STEEL**_
Credit: Written by
Author: Stu Maschwitz
Draft date: 1/20/2012

EXT. BRICK'S PATIO - DAY #1-A#

A gorgeous day. /* cut this bit
that spans lines */ Sun everywhere.[[a note for later]]

= synopsis that never prints

BRICK
(quietly)
Screw retirement.

[[standalone note]]

STEEL (V.O.)
They're coming out of the woodwork!
(beat)
No, everybody we've put away!
  
Boyd, Rafa, Fat Tony.

@McCLANE ^
Yippee ki-yay.

THE END

!INT. NOT A HEADING

.SNIPER SCOPE POV

From what seems like only INCHES AWAY.

> Burn to White.

CUT TO:

int. mary's house - night

> THE END <

===

~Willy Wonka! Willy Wonka!

MARY JANE
Hello, *world* and \\*stars\\*.
"""

CHINESE = """片名：雨夜来信
编剧：某人

# 第一集 雨夜

内景 客厅 夜

雨声。林夏坐在桌前。

@林夏
（低声）
我知道了。

周牧
你早该知道。

切至：

外景·街道·日

他走了
她也走了。

# 第2集 反转

1-2 日 内 办公室

老板：开会。

.天台

风很大。
"""


class FountainParseTests(unittest.TestCase):
    def test_title_page_is_metadata_not_a_scene(self):
        script = parse_fountain(ENGLISH)
        self.assertEqual(script.title, "BRICK & STEEL")
        self.assertEqual(script.title_page["author"], "Stu Maschwitz")
        self.assertNotIn("Stu Maschwitz", script.text)
        self.assertTrue(script.text.startswith("EXT. BRICK'S PATIO - DAY"))

    def test_hidden_material_does_not_survive_and_does_not_break_blocks(self):
        script = parse_fountain(ENGLISH)
        for hidden in ("cut this bit", "a note for later", "standalone note", "synopsis", "===", "#1-A#"):
            self.assertNotIn(hidden, script.text)
        self.assertIn("A gorgeous day.  Sun everywhere.", script.text)
        note_in_speech = parse_fountain("BOB\nOne\n[[gone]]\nTwo\n")
        self.assertEqual(note_in_speech.text, "BOB: One Two")

    def test_dialogue_keeps_speaker_directions_and_double_space_continuation(self):
        text = parse_fountain(ENGLISH).text
        self.assertIn("BRICK: （quietly）Screw retirement.", text)
        self.assertIn("STEEL: （V.O.）They're coming out of the woodwork!", text)
        self.assertIn("STEEL: （beat）No, everybody we've put away! Boyd, Rafa, Fat Tony.", text)
        self.assertIn("McCLANE: Yippee ki-yay.", text)
        self.assertIn("MARY JANE: Hello, world and *stars*.", text)
        self.assertNotIn("CONT", parse_fountain("BOB (CONT'D)\nHi\n").text)
        self.assertEqual(parse_fountain("BOB (CONT'D)\nHi\n").text, "BOB: Hi")

    def test_chinese_heading_forms(self):
        for source, expected in [
            ("内景 办公室 夜", "内景：办公室 - 夜"),
            ("外景·街道·日", "外景：街道 - 日"),
            ("内景：医院 走廊 - 清晨", "内景：医院 走廊 - 清晨"),
            ("内外景 车内 傍晚", "内外景：车内 - 傍晚"),
            ("外景 码头", "外景：码头"),
            ("1-1 日 内 办公室", "内景：办公室 - 日"),
            ("办公室 夜 内", "内景：办公室 - 夜"),
            ("第3场 仓库 夜", "第3场 仓库 - 夜"),
            ("场景2：天台 日 外", "外景：天台 - 日"),
        ]:
            self.assertEqual(parse_fountain(f"{source}\n\n雨声。\n").text.split("\n\n")[0], expected, source)

    def test_sentences_mentioning_a_time_are_not_headings(self):
        for line in ("今天 白天 他 外出，没有回来。", "林夏说夜里很冷。"):
            self.assertEqual(parse_fountain(f"{line}\n").text, line)

    def test_plain_action_is_guarded_from_being_read_as_a_cue_or_heading(self):
        text = parse_fountain(ENGLISH).text
        self.assertIn("动作：THE END", text)
        self.assertIn("动作：INT. NOT A HEADING", text)
        self.assertIn("动作：Extras file in.", parse_fountain("Extras file in.\n").text)

    def test_transitions_in_each_form(self):
        text = parse_fountain(ENGLISH).text
        self.assertIn("转场：Burn to White.", text)
        self.assertIn("CUT TO:", text)
        self.assertIn("切至：", parse_fountain(CHINESE).text)

    def test_empty_document_has_no_text(self):
        self.assertEqual(parse_fountain("/* all gone */\n[[and this]]").text, "")


class FountainDownstreamTests(unittest.TestCase):
    def _document(self, name, source):
        return SourceIngestor().ingest(name, source.encode("utf-8"))

    def test_both_extensions_ingest_as_fountain(self):
        for name in ("a.fountain", "a.SPMD"):
            document = self._document(name, CHINESE)
            self.assertEqual(document.format, "fountain")
            self.assertEqual(document.title, "雨夜来信")
            self.assertEqual(len(document.sha256), 64)
            self.assertTrue(document.spans)

    def test_upload_pickers_are_told_about_both_extensions(self):
        self.assertIn("fountain", SourceIngestor.SUPPORTED_EXTENSIONS)
        self.assertIn("spmd", SourceIngestor.SUPPORTED_EXTENSIONS)

    def test_gb18030_and_empty_sources(self):
        document = SourceIngestor().ingest("a.fountain", CHINESE.encode("gb18030"))
        self.assertIn("林夏", document.text)
        with self.assertRaisesRegex(SourceIngestError, "no extractable text"):
            SourceIngestor().ingest("a.fountain", b"/* nothing */")

    def test_screenplay_parser_gets_the_right_scenes_and_characters(self):
        document = self._document("a.fountain", ENGLISH)
        screenplay = ScriptPromptPipeline().parse_screenplay(document.text, document.title)
        self.assertEqual([scene.int_ext for scene in screenplay.scenes][:1], ["EXT"])
        self.assertEqual(screenplay.scenes[0].location, "BRICK'S PATIO")
        self.assertEqual(screenplay.scenes[0].time_of_day, "DAY")
        self.assertEqual(
            sorted(screenplay.all_characters), sorted(["BRICK", "STEEL", "McCLANE", "MARY JANE"]),
        )
        self.assertIn("SNIPER SCOPE POV", screenplay.all_locations)
        kinds = [element.type for scene in screenplay.scenes for element in scene.elements]
        for kind in ("scene_heading", "action", "character", "dialogue", "parenthetical", "transition"):
            self.assertIn(kind, kinds)

    def test_chinese_script_matches_the_equivalent_plain_upload(self):
        document = self._document("a.fountain", CHINESE)
        screenplay = ScriptPromptPipeline().parse_screenplay(document.text, "x")
        self.assertEqual(screenplay.all_characters, ["林夏", "周牧", "老板"])
        # The episode heading before the first scene opens an unnamed one, as it does for a plain upload.
        self.assertEqual(screenplay.all_locations, ["未注明地点", "客厅", "街道", "办公室", "天台"])
        self.assertEqual(screenplay.scenes[1].time_of_day, "夜")
        self.assertEqual(sorted(split_script_by_episode(document.text)), [1, 2])

    def test_story_graph_finds_characters_and_scenes(self):
        graph = StoryGraphBuilder().build(self._document("a.fountain", CHINESE))
        names = [character.name for character in graph.characters]
        self.assertEqual(sorted(names), sorted(["林夏", "周牧", "老板"]))
        scenes = [scene.name for scene in graph.scenes]
        self.assertIn("内景：客厅 - 夜", scenes)
        self.assertIn("外景：街道 - 日", scenes)
        self.assertTrue(any(name.endswith("天台") for name in scenes), scenes)

        english = StoryGraphBuilder().build(self._document("a.fountain", ENGLISH))
        self.assertIn("MARY JANE", [character.name for character in english.characters])
        self.assertNotIn("动作", [character.name for character in english.characters])
        self.assertIn("EXT. BRICK'S PATIO - DAY", [scene.name for scene in english.scenes])


if __name__ == "__main__":
    unittest.main()

"""Final Draft uploads are read by element, so they come out like a Fountain script."""

import unittest

from app.core.script_prompt_pipeline import ScriptPromptPipeline
from app.ingest.fdx import FdxError, parse_fdx
from app.ingest.parsers import SourceIngestError, SourceIngestor


def _fdx(*paragraphs: str, title_page: str = "") -> bytes:
    body = "".join(paragraphs)
    title = f"<TitlePage><Content>{title_page}</Content></TitlePage>" if title_page else ""
    return f'<?xml version="1.0" encoding="UTF-8"?><FinalDraft DocumentType="Script" Template="No" Version="5"><Content>{body}</Content>{title}</FinalDraft>'.encode("utf-8")


def _p(kind: str, *texts: str, number: str = "") -> str:
    attributes = f' Type="{kind}"' + (f' Number="{number}"' if number else "")
    runs = "".join(f"<Text>{text}</Text>" if text != "\n" else "<LineBreak/>" for text in texts)
    return f"<Paragraph{attributes}>{runs}</Paragraph>"


ENGLISH = _fdx(
    _p("Scene Heading", "EXT. BRICK'S PATIO - DAY", number="1"),
    _p("Action", "A gorgeous day. ", "Sun ", "everywhere."),
    _p("Character", "BRICK"),
    _p("Parenthetical", "(quietly)"),
    _p("Dialogue", "Screw retirement."),
    _p("Character", "STEEL (V.O.)"),
    _p("Dialogue", "They're coming out of the woodwork!"),
    _p("Parenthetical", "beat"),
    _p("Dialogue", "No, everybody we've put away!"),
    _p("Action", "Brick turns."),
    _p("Character", "BRICK (CONT'D)"),
    _p("Dialogue", "Yippee ki-yay."),
    _p("Shot", "SNIPER SCOPE POV"),
    _p("Action", "From what seems like only INCHES AWAY."),
    _p("Transition", "CUT TO:"),
    _p("Scene Heading", "INT. MARY'S HOUSE - NIGHT", number="2"),
    "<DualDialogue>" + _p("Character", "MARY") + _p("Dialogue", "Hello.") + _p("Character", "JANE") + _p("Dialogue", "Hi.") + "</DualDialogue>",
    _p("Cast List", "BRICK, STEEL"),
    _p("General", "THE END"),
    title_page=_p("Action", "BRICK &amp; STEEL") + _p("Action", "Written by") + _p("Action", "Stu Maschwitz"),
)

CHINESE = _fdx(
    _p("Scene Heading", "内景 客厅 夜"),
    _p("Action", "雨声。林夏坐在桌前。"),
    _p("Character", "林夏"),
    _p("Parenthetical", "（低声）"),
    _p("Dialogue", "我知道了。"),
    _p("Character", "周牧（画外）"),
    _p("Dialogue", "你早该知道。"),
    _p("Transition", "切至："),
    _p("Scene Heading", "外景·街道·日"),
    _p("Action", "他走了。"),
    title_page=_p("Action", "片名：雨夜来信") + _p("Action", "编剧：某人"),
)


class FdxRenderTests(unittest.TestCase):
    def test_every_element_is_written_in_the_form_the_parser_reads(self):
        text = parse_fdx(ENGLISH).text
        blocks = text.split("\n\n")
        self.assertEqual(blocks[0], "EXT. BRICK'S PATIO - DAY")
        # Runs are joined; the 动作 label is the same guard a Fountain action line gets.
        self.assertEqual(blocks[1], "动作：A gorgeous day. Sun everywhere.")
        self.assertEqual(blocks[2], "BRICK: （quietly）Screw retirement.")
        self.assertEqual(blocks[3], "STEEL: （V.O.）They're coming out of the woodwork!\nSTEEL: （beat）No, everybody we've put away!")
        self.assertEqual(blocks[5], "BRICK: Yippee ki-yay.", "the continued marker is not a direction")
        self.assertEqual(blocks[6], "动作：SNIPER SCOPE POV\n动作：From what seems like only INCHES AWAY.", "a shot reads as action")
        self.assertEqual(blocks[7], "CUT TO:")
        self.assertEqual(blocks[8], "INT. MARY'S HOUSE - NIGHT")
        self.assertIn("MARY: Hello.", text)
        self.assertIn("JANE: Hi.", text)
        self.assertNotIn("BRICK, STEEL", text, "the sitcom cast list is not script text")
        self.assertNotIn("#1", text)

    def test_the_title_page_is_metadata_not_a_scene(self):
        script = parse_fdx(ENGLISH)
        self.assertEqual(script.title, "BRICK & STEEL")
        self.assertNotIn("Stu Maschwitz", script.text)
        chinese = parse_fdx(CHINESE)
        self.assertEqual(chinese.title, "雨夜来信")
        self.assertEqual(chinese.title_page["编剧"], "某人")

    def test_chinese_elements_come_out_like_a_chinese_fountain_script(self):
        text = parse_fdx(CHINESE).text
        self.assertTrue(text.startswith("内景：客厅 - 夜"))
        self.assertIn("林夏：（低声）我知道了。", text)
        self.assertIn("周牧：（画外）你早该知道。", text)
        self.assertIn("切至：", text)
        self.assertIn("外景：街道 - 日", text)

    def test_speech_without_a_speaker_and_unknown_elements_stay_as_action(self):
        text = parse_fdx(_fdx(_p("Dialogue", "Who said that?"), _p("Lyrics", "la la"), _p("Action", ""))).text
        # A short Latin line on its own would read as a character cue downstream, so it is labelled.
        self.assertEqual(text, "Who said that?\n动作：la la")

    def test_a_file_without_typed_paragraphs_falls_back_to_its_text(self):
        text = parse_fdx(b"<FinalDraft><Other><Text>one</Text><Text>two</Text></Other></FinalDraft>").text
        self.assertEqual(text, "one\ntwo")

    def test_entities_and_broken_xml_are_refused(self):
        with self.assertRaises(FdxError):
            parse_fdx(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><FinalDraft/>')
        with self.assertRaises(FdxError):
            parse_fdx(b"<FinalDraft><Content>")


class FdxIngestTests(unittest.TestCase):
    def test_the_upload_keeps_its_title_and_format(self):
        document = SourceIngestor().ingest("brick.fdx", ENGLISH)
        self.assertEqual(document.format, "fdx")
        self.assertEqual(document.title, "BRICK & STEEL")
        self.assertTrue(document.spans)

    def test_the_screenplay_parser_gets_the_right_scenes_and_characters(self):
        document = SourceIngestor().ingest("brick.fdx", ENGLISH)
        screenplay = ScriptPromptPipeline().parse_screenplay(document.text, document.title)
        self.assertEqual([scene.int_ext for scene in screenplay.scenes], ["EXT", "INT"])
        self.assertEqual(screenplay.scenes[0].location, "BRICK'S PATIO")
        names = {name for scene in screenplay.scenes for name in scene.characters}
        self.assertTrue({"BRICK", "STEEL"} <= names, names)

    def test_a_broken_file_is_an_ingest_error(self):
        with self.assertRaisesRegex(SourceIngestError, "parsed safely"):
            SourceIngestor().ingest("x.fdx", b"<FinalDraft><Content>")


if __name__ == "__main__":
    unittest.main()

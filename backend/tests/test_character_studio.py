"""The character studio: skin and body sliders, hairstyles and swatches, placed marks, a library voice, the canvas.

No model is called: descriptions are merged and read, the relink's dubbing is a stand-in, and the canvas is planned.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import canvas_cast, face_sculpt, media_compositor, prompt_data, voice_casting
from app.repository.task_repo import TaskRepository
from app.service import character_voice_choice
from app.service.drama_service import DramaService
from tests.test_voice_casting import FakeStudio
from tests.test_voice_relink import LU, SHEN, TASK, FakeDub, _forbidden, _task

BASE = "女主角/佩剑者。身份锚点：二十出头的东亚女性；毛发：乌黑长发及腰；体态：清瘦挺拔；服装：月白长衫"


class CatalogTest(unittest.TestCase):
    def test_every_control_has_a_place_in_the_studio_and_every_placed_key_exists(self):
        data = prompt_data.load("face_sculpt")
        keys = {control["key"] for control in data["controls"]}
        placed = [key for panel in data["studio"]["panels"] for section in panel.get("sections", []) for key in section["controls"]]
        self.assertEqual(set(placed) - keys, set())
        self.assertEqual(keys - set(placed), set())

    def test_the_frontend_gets_groups_swatches_levels_and_marks(self):
        described = face_sculpt.describe_catalog()
        controls = {control["key"]: control for control in described["controls"]}
        self.assertEqual(controls["skin_smooth"]["type"], "level")
        self.assertEqual(controls["skin_smooth"]["steps"][0], "")
        groups = {option.get("group") for option in controls["hairstyle"]["options"]}
        self.assertTrue({"现代", "古风", "民国", "仙侠", "科幻", "民族", "儿童"} <= groups)
        self.assertTrue(all(option.get("swatch") for option in controls["hair_color"]["options"]))
        self.assertTrue(any(kind["key"] == "tattoo" and kind["text"] for kind in described["marks"]["kinds"]))
        self.assertEqual([panel["key"] for panel in described["studio"]["panels"]][:5], ["retouch", "marks", "body", "style", "voice"])


class DescriptionTest(unittest.TestCase):
    def test_sliders_hairstyle_and_marks_land_in_their_layers_and_replace_what_they_say(self):
        sculpt = face_sculpt.validate({
            "face": {"skin_smooth": 2, "slim": 2, "hairstyle": "forehead_band", "hair_color": "wine", "makeup": "huadian"},
            "marks": [{"kind": "mole", "region": "left_cheek"}, {"kind": "tattoo", "region": "right_arm", "text": "青龙"},
                      {"kind": "freckles_cheek", "region": "chin"}],
        })
        layers = face_sculpt.layer_fragments(sculpt)
        self.assertIn("左颊一颗小痣", layers["features"])
        self.assertIn("两颊与鼻梁散着淡雀斑", layers["features"], "a mark without a place ignores the place it was sent")
        self.assertIn("右臂青龙纹身", layers["physique"])
        self.assertIn("身形纤瘦", layers["physique"])
        description = face_sculpt.merge_description(BASE, sculpt)
        self.assertNotIn("乌黑长发及腰", description, "the hairstyle and colour replace the written hair")
        self.assertIn("服装：月白长衫", description)
        self.assertEqual(face_sculpt.validate(sculpt.dump()), sculpt, "what is stored reads back the same")

    def test_level_zero_and_a_bad_level_or_mark_are_handled(self):
        self.assertEqual(face_sculpt.validate({"face": {"skin_clear": 0}}).face, {})
        for bad in ({"face": {"skin_clear": 2}}, {"face": {"skin_smooth": True}},
                    {"marks": [{"kind": "mole"}]}, {"marks": [{"kind": "tattoo", "region": "chest"}]},
                    {"marks": [{"kind": "wart", "region": "chin"}]}):
            with self.subTest(bad=bad), self.assertRaises(face_sculpt.SculptError):
                face_sculpt.validate(bad)
        many = [{"kind": "mole", "region": region} for region in
                ("forehead", "chin", "left_cheek", "right_cheek", "nose_tip", "neck", "chest", "back", "left_arm")]
        with self.assertRaisesRegex(face_sculpt.SculptError, "最多"):
            face_sculpt.validate({"marks": many})

    def test_clear_skin_with_freckles_is_flagged(self):
        clashing = face_sculpt.validate({"face": {"skin_clear": 1}, "marks": [{"kind": "freckles_full"}]})
        self.assertIn("face_mark_conflict_skin_clear", [issue["code"] for issue in face_sculpt.harmony_issues(clashing)])
        fine = face_sculpt.validate({"face": {"skin_clear": 1}, "marks": [{"kind": "mole", "region": "chin"}]})
        self.assertNotIn("face_mark_conflict_skin_clear", [issue["code"] for issue in face_sculpt.harmony_issues(fine)])

    def test_a_one_sentence_edit_can_set_a_level(self):
        answer = '{"face": {"质感磨皮": "3", "skin_clear": 5}, "reply": "磨皮拉满"}'
        task = {"assets": {"3_characters": [{"name": SHEN, "desc": BASE}]}}
        result = face_sculpt.apply_instruction(task, SHEN, "皮肤磨皮拉满，去痘", lambda *args: answer)
        self.assertEqual(result["sculpt"].face, {"skin_smooth": 3})
        self.assertTrue(any("祛斑祛痘" in reason for reason in result["unknown"]))


class LibraryVoiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service.voice_studio = FakeStudio()
        self.service.voice_relink_background = False
        self.service.repo.save_task(TASK, _task())
        self.dub = FakeDub()
        for target, value in (
            ("synthesize_preferred_dialogue_track", self.dub),
            ("synthesize_elevenlabs_dialogue_track", _forbidden),
            ("synthesize_dialogue_track", _forbidden),
            ("effective_audio_model", lambda model: ("elevenlabs", "eleven_v3")),
            ("attach_audio_to_clip", lambda *args, **kwargs: "http://localhost:8000/media/shotav.mp4"),
        ):
            patcher = patch.object(media_compositor, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_library_voice_is_kept_with_its_sample_and_what_was_said_is_redubbed(self):
        dashboard = character_voice_choice.choose(self.service, TASK, SHEN, "lib-voice", sample_url="https://cdn.test/s.mp3")
        self.assertIsNotNone(dashboard)
        character = voice_casting.dna_character(self.service.repo.get_task(TASK)["assets"], SHEN)
        self.assertEqual(character["voice_id"], "lib-voice")
        self.assertEqual(character["voice_sample_url"], "https://cdn.test/s.mp3")
        self.assertEqual(self.service.voice_studio.created if hasattr(self.service.voice_studio, "created") else [], [])
        self.assertTrue(self.dub.calls, "the character's dubbed lines were re-dubbed with the new voice")
        self.assertIsNotNone(dashboard.voice_relink)

    def test_a_voice_another_character_has_is_refused(self):
        with self.assertRaisesRegex(ValueError, LU):
            character_voice_choice.choose(self.service, TASK, SHEN, "v-lu")
        self.assertEqual(voice_casting.dna_character(self.service.repo.get_task(TASK)["assets"], SHEN)["voice_id"], "v-shen-old")


class CanvasCastTest(unittest.TestCase):
    TASK = {"assets": {"3_sheets": {SHEN: "http://localhost:8000/media/sheet-shen.png"}}}

    def test_the_sheet_goes_to_the_right_of_what_is_there_once(self):
        document = {"nodes": [{"id": "a", "x": 0, "y": 40, "width": 300, "height": 200}], "edges": []}
        planned = canvas_cast.plan(self.TASK, document, SHEN)
        node = planned["operations"][0]
        self.assertEqual(node["kind"], "media")
        self.assertEqual(node["output"]["url"], "http://localhost:8000/media/sheet-shen.png")
        self.assertIn(SHEN, node["label"])
        self.assertGreater(node["x"], 300)
        self.assertEqual(node["y"], 40)
        on_canvas = {"nodes": [{"id": "n9", "kind": "media", "payload": {"output": {"medium": "image", "url": node["output"]["url"]}}}], "edges": []}
        self.assertEqual(canvas_cast.plan(self.TASK, on_canvas, SHEN), {"operations": [], "existing": "n9"})

    def test_no_sheet_yet_is_explained(self):
        with self.assertRaisesRegex(canvas_cast.CastPictureMissing, "还没有定妆设定集"):
            canvas_cast.plan(self.TASK, {"nodes": []}, LU)


if __name__ == "__main__":
    unittest.main()

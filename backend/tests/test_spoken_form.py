# -*- coding: utf-8 -*-
"""配音念对数字和多音字：送去配音的那一句按中文读法写数字、按项目读音表换念法；字幕不动。"""

import unittest
from unittest.mock import patch

from app.core import media_compositor as mc
from app.core import voice_delivery


class SpokenFormTests(unittest.TestCase):
    def test_numbers_are_written_the_way_they_are_read(self):
        cases = {
            "我等了你3年": "我等了你三年", "给我2个人": "给我两个人", "22个": "二十二个",
            "涨了50%": "涨了百分之五十", "7:30见": "七点三十见", "7:05": "七点零五",
            "2026年": "二零二六年", "3.5秒": "三点五秒", "105两银子": "一百零五两银子",
            "电话13800138000": "电话一三八零零一三八零零零", "20000块": "两万块", "第12集": "第十二集", "10个": "十个",
        }
        for text, spoken in cases.items():
            self.assertEqual(voice_delivery.spoken_form(text), spoken, text)

    def test_the_project_reading_table_replaces_words_longest_first(self):
        readings = [{"word": "行长", "say": "航长"}, {"word": "重庆", "say": "崇庆"}, {"word": "重", "say": "众"}]
        self.assertEqual(voice_delivery.spoken_form("重庆的行长很重要", readings), "崇庆的航长很众要")

    def test_the_table_is_cleaned(self):
        rows = voice_delivery.clean_readings([{"word": " 行长 ", "say": "航长"}, {"word": "行长", "say": "杭长"}, {"word": "x", "say": "x"}, {"word": "", "say": "a"}])
        self.assertEqual(rows, [{"word": "行长", "say": "杭长"}])

    def test_the_dub_gets_the_spoken_form_and_the_subtitle_keeps_the_text(self):
        sent = []

        class Client:
            def create_dialogue(self, lines):
                sent.extend(lines)
                return b"x" * 2048

            def close(self):
                pass

        segment = ("我等了你3年，行长", "female", "neutral", "林夏", "")
        with patch.object(mc, "_elevenlabs_available", return_value=True), \
             patch.object(mc, "_elevenlabs_voices", return_value=("F", "M")), \
             patch("app.core.providers.elevenlabs.ElevenLabsClient", Client), \
             patch.object(mc, "_save_provider_audio", return_value=("u", "/p.mp3")), \
             mc.bind_readings([{"word": "行长", "say": "航长"}]):
            mc.synthesize_elevenlabs_dialogue_track([segment])
        self.assertEqual(sent[0].text, "我等了你三年，航长")
        self.assertEqual(segment[0], "我等了你3年，行长", "the subtitle text is untouched")


class ServiceTests(unittest.TestCase):
    def test_the_table_is_stored_on_the_project(self):
        import tempfile
        from pathlib import Path

        from app.repository.task_repo import TaskRepository
        from app.service.drama_service import DramaService

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        service = DramaService()
        service.repo = TaskRepository(str(Path(folder.name) / "tasks.json"))
        service.repo.save_task("t1", {"task_id": "t1", "config": {}, "assets": {}})
        self.assertEqual(service.set_pronunciations("t1", [{"word": "行长", "say": "航长"}]), [{"word": "行长", "say": "航长"}])
        self.assertEqual(service.get_pronunciations("t1"), {"readings": [{"word": "行长", "say": "航长"}]})


class NativeReadingTests(unittest.TestCase):
    """A model that makes its own sound cannot have the word swapped: the prompt says how it is read."""

    def test_only_the_words_this_line_uses_get_a_note(self):
        from app.core import voice_delivery

        readings = [{"word": "御炼", "say": "玉炼"}, {"word": "长乐", "say": "常乐"}, {"word": "", "say": "x"}]
        self.assertEqual(voice_delivery.reading_notes("皇上，御炼蛋白粉。", readings), ["「御炼」念「玉炼」的音"])
        self.assertEqual(voice_delivery.reading_notes("这铁，怎么越练越沉？", readings), [])
        self.assertEqual(voice_delivery.reading_notes("", readings), [])
        self.assertEqual(voice_delivery.reading_notes("御炼", None), [])

    def test_a_line_full_of_listed_words_keeps_the_first_few(self):
        from app.core import prompt_data, voice_delivery

        readings = [{"word": f"词{index}", "say": f"读{index}"} for index in range(8)]
        line = "".join(row["word"] for row in readings)
        self.assertEqual(len(voice_delivery.reading_notes(line, readings)), prompt_data.number("voice_delivery", "native_reading_max"))


if __name__ == "__main__":
    unittest.main()

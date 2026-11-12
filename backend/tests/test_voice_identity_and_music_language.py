# -*- coding: utf-8 -*-
"""角色音色全剧固定且互相不同、配音按语气说明演出来、配乐全剧一套音乐语言。"""

import unittest
from unittest.mock import patch

from app.core import media_compositor as mc
from app.core import post_production, voice_casting, voice_delivery
from app.service.drama_service import DramaService, dialogue_genders, parse_shot_dialogue

POOL = {"female": ["f1", "f2", "f3"], "male": ["m1", "m2"]}


def _assets():
    return {"3_dna": {"characters": [{"name": "林夏"}, {"name": "苏晚"}, {"name": "周烈"}]}}


class VoiceIdentityTests(unittest.TestCase):
    def test_each_woman_gets_her_own_voice_and_keeps_it(self):
        assets = _assets()
        chosen = voice_casting.assign_missing_voices(assets, {"林夏": "female", "周烈": "male", "苏晚": "female", "路人甲": "female"}, POOL)
        self.assertEqual(chosen, {"林夏": "f1", "周烈": "m1", "苏晚": "f2", "路人甲": "f3"})
        self.assertEqual(voice_casting.dna_character(assets, "苏晚")["voice_source"], "auto")
        self.assertEqual(assets[voice_casting.AUTO_VOICES_KEY]["路人甲"]["voice_id"], "f3")
        # 第二集、重配：已经定下的不再挑。
        again = voice_casting.assign_missing_voices(assets, {"苏晚": "female", "林夏": "female"}, {"female": ["f9"], "male": []})
        self.assertEqual(again, {})
        self.assertEqual(voice_casting.speaker_voice_map(assets)["苏晚"], "f2")

    def test_a_cast_voice_is_never_handed_to_someone_else(self):
        assets = _assets()
        voice_casting.dna_character(assets, "林夏")["voice_id"] = "f1"
        chosen = voice_casting.assign_missing_voices(assets, {"苏晚": "female"}, POOL)
        self.assertEqual(chosen, {"苏晚": "f2"})
        self.assertEqual(voice_casting.voice_taken_by(assets, "周烈", "f1"), "林夏")
        self.assertEqual(voice_casting.voice_taken_by(assets, "林夏", "f1"), "")

    def test_casting_a_designed_voice_clears_the_auto_mark(self):
        assets = _assets()
        voice_casting.assign_missing_voices(assets, {"林夏": "female"}, POOL)
        voice_casting.set_voice(assets, "林夏", voice_id="designed")
        self.assertNotIn("voice_source", voice_casting.dna_character(assets, "林夏"))

    def test_a_recast_voice_replaces_the_old_one_everywhere_and_stays_unique(self):
        # 配过音也能换音色：换了以后全剧只认新音色，别人仍不能用它，它也不能拿别人的。
        assets = _assets()
        voice_casting.assign_missing_voices(assets, {"林夏": "female", "苏晚": "female"}, POOL)
        voice_casting.set_voice(assets, "林夏", voice_id="designed")
        voices = voice_casting.speaker_voice_map(assets)
        self.assertEqual(voices["林夏"], "designed")
        self.assertNotIn("f1", voices.values())
        self.assertEqual(voice_casting.voice_taken_by(assets, "苏晚", "designed"), "林夏")
        self.assertEqual(voice_casting.voice_taken_by(assets, "林夏", "f2"), "苏晚")

    def test_a_short_pool_shares_the_least_used_voice(self):
        assets = _assets()
        chosen = voice_casting.assign_missing_voices(assets, {"甲": "male", "乙": "male", "丙": "male"}, POOL)
        self.assertEqual(chosen, {"甲": "m1", "乙": "m2", "丙": "m1"})

    def test_the_voice_matches_the_age_written_in_the_voice_design(self):
        assets = {"3_dna": {"characters": [{"name": "常九斤", "voice_desc": "64岁男声，沙哑"}, {"name": "谢九", "voice_desc": "38岁男声"}]}}
        pool = {"male": [{"voice_id": "young", "age": "young"}, {"voice_id": "mid", "age": "middle_aged"}, {"voice_id": "old", "age": "old"}]}
        chosen = voice_casting.assign_missing_voices(assets, {"常九斤": "male", "谢九": "male"}, pool)
        self.assertEqual(chosen, {"常九斤": "old", "谢九": "mid"})

    def test_the_narrator_gets_one_voice_under_all_its_names(self):
        assets = _assets()
        voice_casting.assign_missing_voices(assets, {"旁白": "female"}, POOL)
        self.assertEqual(voice_casting.narrator_voice(assets)["source"], "auto")
        self.assertEqual(voice_casting.speaker_voice_map(assets)["旁白"], "f1")

    def test_stage_dubbing_casts_missing_voices_from_the_account_pool(self):
        task = {
            "config": {"tts_model": "eleven_v3"},
            "assets": {
                "3_dna": {"characters": [{"name": "林夏"}, {"name": "苏晚"}]},
                "3_characters": [{"name": "林夏", "desc": "女性，主角"}, {"name": "苏晚", "desc": "女性，反派"}],
                "5": [{"dialogue": "林夏（低声）：走吧。\n苏晚：站住。\n店小二：客官里边请。"}],
            },
        }
        with patch.object(mc, "effective_audio_model", return_value=("elevenlabs", "eleven_v3")), \
             patch.object(mc, "elevenlabs_voice_pool", return_value=POOL):
            chosen = DramaService._cast_missing_voices(task)
        self.assertEqual(chosen["林夏"], "f1")
        self.assertEqual(chosen["苏晚"], "f2")
        self.assertIn("店小二", chosen)
        self.assertEqual(len(set(chosen.values())), len(chosen))

    def test_no_pool_lookup_when_dubbing_is_not_elevenlabs(self):
        task = {"config": {"tts_model": "edge-tts"}, "assets": _assets()}
        with patch.object(mc, "effective_audio_model", return_value=("", "edge-tts")), \
             patch.object(mc, "elevenlabs_voice_pool") as pool:
            self.assertEqual(DramaService._cast_missing_voices(task), {})
        pool.assert_not_called()


class GenderFromVoiceTests(unittest.TestCase):
    def test_a_card_that_does_not_say_falls_back_to_the_designed_voice(self):
        cards = [{"name": "谢九", "desc": "磨刀匠，二十七八岁，及腰长发"}, {"name": "裘三娘", "desc": "女性，买刀人"}]
        dna = {"characters": [{"name": "谢九", "voice_desc": "38岁男声，低哑偏沉"}, {"name": "裘三娘", "voice_desc": "33岁男声"}]}
        lead, other, genders = dialogue_genders(cards, "谢九", "裘三娘", dna)
        self.assertEqual((lead, other), ("male", "female"))  # 卡片写明的性别优先于声音设计
        self.assertEqual(genders["谢九"], "male")


class DeliveryTests(unittest.TestCase):
    def test_notes_become_performance_tags_and_the_line_stays_verbatim(self):
        self.assertEqual(voice_delivery.performed_text("你走吧……别回头", "sad", "低声；停顿"), "[whispers][sad][short pause] 你走吧……别回头")
        self.assertEqual(voice_delivery.performed_text("滚！！", "shout"), "[shouting] 滚！！")
        self.assertEqual(voice_delivery.performed_text("就凭你？", "cold", "冷笑"), "[sarcastic][coldly] 就凭你？")
        self.assertEqual(voice_delivery.performed_text("我、不、走。", "angry", "一字一顿"), "[firmly][angry] 我、不、走。")
        self.assertEqual(voice_delivery.performed_text("好。", "neutral"), "好。")
        # 没写说明时情绪是猜的：「磨快它」不加 [nervous]。
        self.assertEqual(voice_delivery.performed_text("三天，磨快它。", "tense"), "三天，磨快它。")
        self.assertEqual(voice_delivery.performed_text("七年前。", "neutral", "低声，开口前停0.3秒"), "[whispers][short pause] 七年前。")
        self.assertEqual(voice_delivery.performed_text("那就三天。", "neutral", "气声压低，说完停半拍才转身"), "[whispers] 那就三天。[short pause]")
        self.assertEqual(voice_delivery.performed_text("你手底下，七个。", "neutral", "指腹停在墨痕上，声音更低"), "[whispers] 你手底下，七个。")

    def test_the_shot_parser_keeps_the_delivery_notes(self):
        lines = parse_shot_dialogue("林夏（压低声音，停顿）：你走吧。", "林夏", "周烈", "female", "male")
        self.assertEqual(lines[0][0], "你走吧。")
        self.assertIn("停顿", lines[0][4])

    def test_elevenlabs_dialogue_receives_the_performed_line(self):
        sent = []

        class Client:
            def create_dialogue(self, lines):
                sent.extend(lines)
                return b"x" * 2048

            def close(self):
                pass

        with patch.object(mc, "_elevenlabs_available", return_value=True), \
             patch.object(mc, "_elevenlabs_voices", return_value=("F", "M")), \
             patch("app.core.providers.elevenlabs.ElevenLabsClient", Client), \
             patch.object(mc, "_save_provider_audio", return_value=("u", "/p.mp3")), \
             mc.bind_speaker_voices({"林夏": "f1"}):
            mc.synthesize_elevenlabs_dialogue_track([("滚出去！", "female", "angry", "林夏", "嘶吼")])
        self.assertEqual(sent[0].voice_id, "f1")
        self.assertEqual(sent[0].text, "[shouting][angry] 滚出去！")
        self.assertEqual(sent[0].emotion, "neutral")


class MusicLanguageTests(unittest.TestCase):
    def test_the_genre_sets_the_instrumentation(self):
        text = post_production.music_prompt("写实", "xianxia")
        self.assertIn("taiko", text)
        self.assertIn("same musical language for every episode", text)
        self.assertIn("cinematic strings", post_production.music_prompt("写实", "未知题材"))
        # 标题认不出题材(general)时按全剧的类型聚类配器：古装江湖用古琴二胡琵琶。
        plain = post_production.music_prompt("真人电影写实", "general", "B")
        self.assertIn("guqin", plain)
        self.assertNotIn("general", plain)

    def test_the_first_music_locks_the_prompt_for_every_later_episode(self):
        assets: dict = {}
        first = post_production.series_music_prompt(assets, "写实", "xianxia")
        post_production.lock_music_language(assets, first, "xianxia")
        self.assertEqual(post_production.series_music_prompt(assets, "电影感", "romance"), first)
        post_production.lock_music_language(assets, "other", "romance")
        self.assertEqual(assets[post_production.MUSIC_LANGUAGE_KEY]["prompt"], first)


if __name__ == "__main__":
    unittest.main()

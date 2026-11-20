# -*- coding: utf-8 -*-
"""人物出场字幕：第一次出场时竖排显示姓名和身份，之后不再出现。"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import character_intro as intro
from app.core import edit_timeline, media_compositor, name_card_render
from app.core.media_compositor import BUNDLED_FONT

FFMPEG = shutil.which("ffmpeg")


def _shot(scene, number, cast, regions=None):
    shot = {"scene_id": scene, "shot_id": number, "characters": list(cast)}
    if regions is not None:
        shot["spatial"] = {"screen": [{"name": name, "region": region} for name, region in regions.items()]}
    return shot


def _clip(scene, number, **extra):
    return {"scene_id": scene, "shot_id": number, "video_url": f"http://x/{scene}-{number}.mp4", "duration": 8, **extra}


def _task(shots, clips=None, characters=None):
    characters = characters if characters is not None else [
        {"name": "石砚", "desc": "外门杂役/编号丁七/绝灵体；骨相：长方脸"},
        {"name": "曹烬", "desc": "丹房管事/炼凝金丹；骨相：方圆脸"},
        {"name": "阿禾", "desc": "丹房帮工少女/替石砚守炉"},
    ]
    return {"config": {}, "assets": {
        "3_characters": characters, "4": shots,
        "5": clips if clips is not None else [_clip(shot["scene_id"], shot["shot_id"]) for shot in shots],
    }}


def _cards(task, timeline=None):
    timeline = timeline or edit_timeline.build(task)
    planned = intro.due(task, timeline)
    return {timeline["clips"][position]["scene_id"]: [(c["name"], c["identity"], c["side"]) for c in cards] for position, cards in planned.items()}


class IdentityTests(unittest.TestCase):
    def test_the_identity_is_the_opening_piece_of_the_record(self):
        self.assertEqual(intro.identity_from("外门杂役/编号丁七/绝灵体；骨相：长方脸"), "外门杂役")
        self.assertEqual(intro.identity_from("丹房管事，五十岁上下"), "丹房管事")
        self.assertEqual(intro.identity_from("一个在山门外扫了十年落叶从不说话的人"), "")     # 太长的整段不要，不截半句
        self.assertEqual(intro.identity_from(None), "")

    def test_a_person_without_a_record_gets_no_card(self):
        task = _task([_shot("E1S01", 1, ["石砚", "弟子-01", "路人"])])
        self.assertEqual(_cards(task), {"E1S01": [("石砚", "外门杂役", "right")]})

    def test_the_inventory_fills_in_when_the_character_list_is_missing(self):
        task = _task([_shot("E1S01", 1, ["卫渠"])], characters=[])
        task["assets"]["2_screenwriting"] = {"inventory": {"characters": [{"卫渠": {"description": "药园老执事，三年前在试丹契上签了押。"}}]}}
        self.assertEqual(_cards(task), {"E1S01": [("卫渠", "药园老执事", "right")]})


class FirstAppearanceTests(unittest.TestCase):
    def test_each_person_is_named_once(self):
        task = _task([_shot("E1S01", 1, ["曹烬"]), _shot("E1S02", 1, ["石砚"]), _shot("E1S03", 1, ["石砚", "曹烬"]), _shot("E1S04", 1, ["曹烬"])])
        self.assertEqual(_cards(task), {"E1S01": [("曹烬", "丹房管事", "right")], "E1S02": [("石砚", "外门杂役", "right")]})

    def test_alone_in_the_shot_the_card_takes_the_free_side(self):
        task = _task([_shot("E1S01", 1, ["曹烬"], {"曹烬": "画面右侧三分之一"})])
        self.assertEqual(_cards(task), {"E1S01": [("曹烬", "丹房管事", "left")]})

    def test_with_others_the_card_stays_on_the_persons_own_side(self):
        task = _task([_shot("E1S01", 1, ["曹烬", "石砚"], {"曹烬": "画面左侧三分之一", "石砚": "画面右侧三分之一"})])
        self.assertEqual(_cards(task), {"E1S01": [("曹烬", "丹房管事", "left"), ("石砚", "外门杂役", "right")]})
        timeline = intro.with_cards(edit_timeline.build(task), task)
        self.assertEqual(intro.unsure(timeline), [])

    def test_a_card_waits_a_few_clips_for_a_moment_it_cannot_be_misread(self):
        crowded = {"曹烬": "画面中左侧", "石砚": "画面右侧三分之一", "阿禾": "画面左侧三分之一"}
        task = _task([_shot("E1S01", 1, ["曹烬"]), _shot("E1S02", 1, ["曹烬", "石砚", "阿禾"], crowded),
                      _shot("E1S03", 1, ["阿禾", "石砚"], {"阿禾": "画面左侧三分之一", "石砚": "画面右侧三分之一"})])
        self.assertEqual(_cards(task)["E1S03"], [("阿禾", "丹房帮工少女", "left")])     # 第一次出场时和曹烬挤在同一侧，等到下一镜
        self.assertEqual(_cards(task)["E1S02"], [("石砚", "外门杂役", "right")])

    def test_a_card_that_never_gets_clear_goes_on_the_entrance_and_is_flagged(self):
        crowded = {"曹烬": "画面中左侧", "阿禾": "画面左侧三分之一"}
        task = _task([_shot("E1S01", 1, ["曹烬"])] + [_shot(f"E1S0{n}", 1, ["曹烬", "阿禾"], crowded) for n in (2, 3, 4, 5, 6)])
        timeline = intro.with_cards(edit_timeline.build(task), task)
        self.assertEqual([card["name"] for card in timeline["clips"][1]["name_cards"]], ["阿禾"])
        self.assertEqual(intro.unsure(timeline), [{"shot_uid": 100201, "scene_id": "E1S02", "name": "阿禾"}])

    def test_extras_the_storyboard_placed_count_as_company(self):
        task = _task([_shot("E1S01", 1, ["阿禾"], {"阿禾": "画面左侧三分之一", "弟子-01": "画面中左侧"})])
        timeline = intro.with_cards(edit_timeline.build(task), task)
        self.assertTrue(timeline["clips"][0]["name_cards"][0]["unsure"])

    def test_a_rejected_clip_passes_the_card_to_the_next_one(self):
        task = _task([_shot("E1S01", 1, ["石砚"]), _shot("E1S02", 1, ["石砚"])])
        timeline = edit_timeline.build(task)
        self.assertEqual(list(_cards(task, timeline)), ["E1S01"])
        timeline = edit_timeline.review(timeline, 1, decision="rejected", shot_uid=100101)
        self.assertEqual(list(_cards(task, timeline)), ["E1S02"])

    def test_a_board_clip_times_the_card_to_the_moment_the_person_is_in(self):
        shots = [_shot("E1S01", 1, ["曹烬"]), _shot("E1S01", 2, ["曹烬", "石砚"], {"曹烬": "画面左侧", "石砚": "画面右侧"})]
        clip = _clip("E1S01", 1, shot_uids=[100101, 100102], slice={"beats": [
            {"shot_id": 1, "shot_uid": 100101, "seconds": 5.0}, {"shot_id": 2, "shot_uid": 100102, "seconds": 6.0}]})
        task = _task(shots, [clip])
        cards = intro.due(task, edit_timeline.build(task))[0]
        self.assertEqual([(card["name"], card["at"]) for card in cards], [("曹烬", 0.6), ("石砚", 5.6)])


class SeriesTests(unittest.TestCase):
    def _series(self):
        return _task([_shot("E1S01", 1, ["石砚"]), _shot("E2S01", 1, ["石砚", "曹烬"], {"石砚": "画面左侧", "曹烬": "画面右侧"})])

    def _episode(self, task, number):
        from app.core import episode_cycle
        timeline = edit_timeline.build(episode_cycle.episode_view(task, number))
        timeline["episode"] = number
        return timeline

    def test_someone_seen_in_an_earlier_episode_is_not_introduced_again(self):
        task = self._series()
        self.assertEqual(_cards(task, self._episode(task, 2)), {"E2S01": [("曹烬", "丹房管事", "right")]})

    def test_the_project_can_ask_for_an_introduction_in_every_episode(self):
        task = self._series()
        task["config"]["name_card_scope"] = "episode"
        self.assertEqual([name for name, *_ in _cards(task, self._episode(task, 2))["E2S01"]], ["石砚", "曹烬"])


class TimelineTests(unittest.TestCase):
    def _timeline(self):
        task = _task([_shot("E1S01", 1, ["石砚"]), _shot("E1S02", 1, ["曹烬"])])
        return task, intro.with_cards(edit_timeline.build(task), task)

    def test_reading_an_up_to_date_timeline_changes_nothing(self):
        task, timeline = self._timeline()
        self.assertIs(intro.with_cards(timeline, task), timeline)

    def test_the_render_plan_carries_the_cards_and_the_switch_turns_them_off(self):
        _task_, timeline = self._timeline()
        plan = edit_timeline.render_plan(timeline)
        self.assertEqual([[card["name"] for card in cards] for cards in plan["name_cards"]], [["石砚"], ["曹烬"]])
        off = edit_timeline.set_settings(timeline, {"name_cards": False})
        self.assertEqual(edit_timeline.render_plan(off)["name_cards"], [[], []])

    def test_an_old_timeline_without_the_switch_shows_the_cards(self):
        _task_, timeline = self._timeline()
        timeline["settings"] = {"transitions": True, "dialogue": True, "subtitles": True, "title_card": True}
        self.assertTrue(edit_timeline.settings_of(timeline)["name_cards"])

    def test_cards_written_by_hand_stay_and_can_be_handed_back(self):
        task, timeline = self._timeline()
        edited = edit_timeline.set_name_cards(timeline, 1, [{"name": "石 砚", "identity": "绝灵体", "side": "left", "at": 2}], shot_uid=100101)
        edited = intro.with_cards(edited, task)
        self.assertEqual(edited["clips"][0]["name_cards"], [{"name": "石砚", "identity": "绝灵体", "side": "left", "slot": 0, "at": 2.0}])
        emptied = intro.with_cards(edit_timeline.set_name_cards(edited, 1, [], shot_uid=100101), task)
        self.assertEqual(emptied["clips"][0]["name_cards"], [])                 # 人说这一镜不出，就不出
        handed_back = intro.with_cards(edit_timeline.set_name_cards(emptied, 1, None, shot_uid=100101), task)
        self.assertEqual([card["name"] for card in handed_back["clips"][0]["name_cards"]], ["石砚"])

    def test_a_card_removed_by_hand_does_not_reappear_on_a_later_clip(self):
        task = _task([_shot("E1S01", 1, ["石砚"]), _shot("E1S02", 1, ["石砚"])])
        timeline = intro.with_cards(edit_timeline.build(task), task)
        timeline = intro.with_cards(edit_timeline.set_name_cards(timeline, 1, [], shot_uid=100101), task)
        self.assertEqual([clip["name_cards"] for clip in timeline["clips"]], [[], []])

    def test_hand_written_cards_survive_a_refresh(self):
        task, timeline = self._timeline()
        edited = edit_timeline.set_name_cards(timeline, 1, [{"name": "石砚", "identity": "丁七"}], shot_uid=100101)
        refreshed = edit_timeline.refresh(edited, task)
        self.assertEqual(refreshed["clips"][0]["name_cards"][0]["identity"], "丁七")
        self.assertTrue(refreshed["clips"][0]["name_cards_edited"])

    def test_bad_cards_are_refused(self):
        _task_, timeline = self._timeline()
        for cards in ("石砚", [{"identity": "杂役"}], [{"name": "石砚", "side": "top"}], [{"name": f"甲{n}"} for n in range(5)]):
            with self.assertRaises(edit_timeline.TimelineError):
                edit_timeline.set_name_cards(timeline, 1, cards, shot_uid=100101)


class WindowTests(unittest.TestCase):
    def test_the_card_shows_for_three_seconds_from_its_moment(self):
        self.assertEqual(intro.window({"at": 0.6}, trim_start=0.0, kept=8.0), (0.6, 3.6))

    def test_a_trimmed_away_moment_moves_to_the_start_of_what_is_left(self):
        self.assertEqual(intro.window({"at": 0.6}, trim_start=2.0, kept=6.0), (0.0, 3.0))

    def test_a_card_near_the_end_moves_earlier_and_a_short_clip_shortens_it(self):
        self.assertEqual(intro.window({"at": 7.0}, trim_start=0.0, kept=8.0), (5.0, 8.0))
        self.assertEqual(intro.window({"at": 0.6}, trim_start=0.0, kept=2.0), (0.0, 2.0))
        self.assertIsNone(intro.window({"at": 0.6}, trim_start=0.0, kept=0.8))


@unittest.skipUnless(os.path.exists(BUNDLED_FONT), "the bundled font is not installed")
class RenderTests(unittest.TestCase):
    def _columns(self, cards):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "card.png")
            self.assertTrue(name_card_render.render(cards, path, width=1080, height=1920, font_path=BUNDLED_FONT))
            image = Image.open(path).convert("RGBA")
            return image.getchannel("A").getbbox()

    def test_the_text_is_a_tall_column_on_its_side_of_the_frame(self):
        left, top, right, bottom = self._columns([{"name": "石砚", "identity": "外门杂役", "side": "right", "slot": 0}])
        self.assertGreater(left, 1080 * 0.7)
        self.assertGreater(bottom - top, right - left)            # 竖排：高大于宽
        self.assertGreaterEqual(top, 1920 * 0.15)
        left, _top, right, _bottom = self._columns([{"name": "阿禾", "identity": "", "side": "left", "slot": 0}])
        self.assertLess(right, 1080 * 0.3)

    def test_cards_in_the_same_window_share_one_picture(self):
        with tempfile.TemporaryDirectory() as folder:
            layers = name_card_render.layers(
                [{"name": "石砚", "side": "right", "slot": 0, "at": 0.6}, {"name": "阿禾", "side": "left", "slot": 0, "at": 0.6},
                 {"name": "曹烬", "side": "right", "slot": 0, "at": 4.0}],
                folder, 0, trim_start=0.0, kept=10.0, width=1080, height=1920, font_path=BUNDLED_FONT)
            self.assertEqual([(start, end) for _png, start, end, _fade in layers], [(0.6, 3.6), (4.0, 7.0)])
            self.assertTrue(all(os.path.exists(png) for png, *_ in layers))

    def test_without_a_font_there_is_nothing_to_lay_over(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(name_card_render.layers([{"name": "石砚", "at": 0.6}], folder, 0, trim_start=0.0, kept=8.0,
                                                     width=1080, height=1920, font_path=None), [])


@unittest.skipUnless(FFMPEG and os.path.exists(BUNDLED_FONT), "needs ffmpeg and the bundled font")
class FilmTests(unittest.TestCase):
    """A black 6-second clip: anything bright near the right edge is the card."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "media"
        self.media.mkdir()
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(self.media))
        patcher.start()
        self.addCleanup(patcher.stop)
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:size=360x640:rate=24:duration=6",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.media / "clip.mp4")], check=True)

    def _film(self, cards, tag):
        url = media_compositor.compose_film([media_compositor.public_url("clip.mp4")], [""], None, tag=tag, title=None, bgm=False, name_cards=cards)
        self.assertTrue(url)
        return media_compositor.local_media_path(url)

    def _brightest(self, film, at):
        from PIL import Image
        frame = str(self.media / f"frame_{at}.png")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", str(at), "-i", film, "-frames:v", "1", frame], check=True)
        image = Image.open(frame).convert("L")
        width, height = image.size
        return image.crop((int(width * 0.7), int(height * 0.15), width, int(height * 0.5))).getextrema()[1]

    def test_the_card_is_on_screen_in_its_window_and_gone_after(self):
        film = self._film([[{"name": "石砚", "identity": "外门杂役", "side": "right", "slot": 0, "at": 0.6}]], "cards")
        plain = self._film(None, "plain")
        self.assertGreater(self._brightest(film, 2.0), 200)       # 0.6–3.6 秒之间在
        self.assertLess(self._brightest(film, 0.2), 40)           # 之前没有
        self.assertLess(self._brightest(film, 4.5), 40)           # 之后没有
        self.assertLess(self._brightest(plain, 2.0), 40)
        self.assertAlmostEqual(media_compositor._probe_duration(film), media_compositor._probe_duration(plain), delta=0.05)
        self.assertNotEqual(os.path.basename(film).replace("cards", ""), os.path.basename(plain).replace("plain", ""))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        from app.repository.task_repo import TaskRepository
        from app.service.drama_service import DramaService
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))

    def _save(self, task_id, task):
        self.service.repo.save_task(task_id, {"task_id": task_id, **task})

    def test_the_timeline_comes_with_cards_and_an_edit_is_kept(self):
        self._save("cards-1", _task([_shot("E1S01", 1, ["石砚"]), _shot("E1S02", 1, ["石砚", "曹烬"], {"石砚": "画面左侧", "曹烬": "画面右侧"})]))
        timeline = self.service.get_timeline("cards-1")["timeline"]
        self.assertEqual([[card["name"] for card in clip["name_cards"]] for clip in timeline["clips"]], [["石砚"], ["曹烬"]])

        result = self.service.edit_timeline("cards-1", "name_cards", {"shot_uid": 100201, "cards": [{"name": "曹烬", "identity": "管事", "side": "left", "at": 1.5}]})
        self.assertEqual(result["timeline"]["clips"][1]["name_cards"][0]["identity"], "管事")
        saved = self.service.repo.get_task("cards-1")["assets"]["7_timeline"]["clips"][1]
        self.assertTrue(saved["name_cards_edited"])
        self.assertEqual(self.service.get_timeline("cards-1")["timeline"]["clips"][1]["name_cards"][0]["at"], 1.5)

        back = self.service.edit_timeline("cards-1", "name_cards", {"shot_uid": 100201})   # 不带 cards：交还给自动排的
        self.assertEqual(back["timeline"]["clips"][1]["name_cards"][0]["identity"], "丹房管事")

    def test_the_film_is_composed_with_the_cards(self):
        self._save("cards-2", _task([_shot("E1S01", 1, ["石砚"])]))
        with patch("app.service.drama_service.media_compositor.compose_film", return_value="/media/film.mp4") as compose:
            self.service.render_timeline("cards-2")
        self.assertEqual([[card["name"] for card in cards] for cards in compose.call_args.kwargs["name_cards"]], [["石砚"]])

    def test_a_later_episode_does_not_name_the_people_of_the_earlier_ones(self):
        task = _task([_shot("E1S01", 1, ["石砚"]), _shot("E2S01", 1, ["石砚", "曹烬"], {"石砚": "画面左侧", "曹烬": "画面右侧"})])
        task["assets"]["4_progress"] = {"episodes": [{"number": n, "total": 1, "done": 1, "complete": True} for n in (1, 2)]}
        task["assets"]["episode_cycle"] = {"version": 1, "episodes": {"1": {"audio": {"audio_url": "a"}, "film": {"final_video_url": "/media/e1.mp4"}}}}
        self._save("cards-3", task)
        second = self.service.get_timeline("cards-3")["timeline"]
        self.assertEqual(second["episode"], 2)
        self.assertEqual([[card["name"] for card in clip["name_cards"]] for clip in second["clips"]], [["曹烬"]])
        with patch("app.service.drama_service.media_compositor.compose_film", return_value="/media/e1_new.mp4") as compose:
            self.service.render_timeline("cards-3", episode=1)                               # 做完的第 1 集重新合成：石砚在这一集出字
        self.assertEqual([[card["name"] for card in cards] for cards in compose.call_args.kwargs["name_cards"]], [["石砚"]])


if __name__ == "__main__":
    unittest.main()

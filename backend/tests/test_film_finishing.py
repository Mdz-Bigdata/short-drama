# -*- coding: utf-8 -*-
"""成片精修: the title card on a chosen frame, the film's subtitle style, the film-wide grade and the ending card.

The settings live beside the four basic switches (``timeline["settings"]["finishing"]``) and are changed through the
same ``settings`` edit. The promise these tests hold: a film nobody finished renders exactly as before — no finishing
argument reaches the compositor, the default subtitle and title card come out pixel for pixel, and no colour filter
is added. The drawing uses PIL; the renders use real local ffmpeg on tiny clips (skipped where ffmpeg is missing).
No model, no network.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import edit_timeline, film_finishing, film_finishing_render, media_compositor, post_production
from app.repository.task_repo import TaskRepository
from app.schema.production import TimelineOperationRequest
from app.service.drama_service import DramaService

FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")
FONT = media_compositor._font_path()


def _task():
    return {
        "task_id": "finish-1",
        "config": {"genre": "古装权谋", "title_suggestion": "雪夜", "tts_model": "macos-say"},
        "assets": {
            "5": [
                {"shot_id": 1, "shot_uid": 1, "scene_id": "S1", "video_url": "http://x/1.mp4", "duration": "4", "dialogue": "沈砚：朕的江山。"},
                {"shot_id": 2, "shot_uid": 2, "scene_id": "S1", "video_url": "http://x/2.mp4", "duration": "4", "dialogue": "苏晚：你敢？"},
                {"shot_id": 1, "shot_uid": 3, "scene_id": "S2", "video_url": "http://x/3.mp4", "duration": "4", "dialogue": ""},
            ],
            "6": {"shot_voices": [None, None, None], "native_audio_shots": [False, False, False]},
            "2_screenwriting": {"ledger": [
                {"episode": 1, "title": "雪夜", "next_episode_teaser": "下一集：\n宫门  紧闭，她一个人回来了。"},
                {"episode": 2, "title": "归来", "next_episode_teaser": None},
            ]},
        },
    }


def _timeline(**finishing):
    timeline = edit_timeline.build(_task(), title="雪夜")
    return edit_timeline.set_settings(timeline, {"finishing": finishing}) if finishing else timeline


class DefaultsTest(unittest.TestCase):
    def test_an_untouched_film_has_no_finishing_at_all(self):
        timeline = edit_timeline.build(_task(), title="雪夜")
        self.assertNotIn("finishing", timeline["settings"])
        self.assertEqual(edit_timeline.finishing_of(timeline), film_finishing.defaults())
        self.assertEqual(edit_timeline.settings_of(timeline), {"transitions": True, "dialogue": True, "subtitles": True, "title_card": True, "name_cards": True})
        plan = edit_timeline.render_plan(timeline)
        self.assertIsNone(plan["finishing"])
        self.assertEqual(plan["title"], "雪夜")
        self.assertTrue(plan["fade_edges"])

    def test_the_defaults_are_todays_look(self):
        self.assertEqual(film_finishing.defaults(), {
            "title": {"animation": "fade", "background": None},
            "subtitle": {"size": "medium", "color": "white", "position": "bottom", "outline": "normal"},
            "color": {"preset": "none", "brightness": 0, "contrast": 0, "saturation": 0, "warmth": 0},
            "ending": {"enabled": False, "text": ""},
        })
        look = film_finishing.subtitle_metrics(None, height=1920)
        self.assertEqual((look["font_px"], look["line_height"], look["bottom_safe"], look["outline_px"], look["color"]),
                         (46, 60, 250, 2, (255, 255, 255)))

    def test_a_timeline_saved_before_the_feature_renders_as_before(self):
        fresh = edit_timeline.build(_task(), title="雪夜")
        old = {key: value for key, value in fresh.items() if key != "settings"}
        self.assertIsNone(edit_timeline.render_plan(old)["finishing"])
        self.assertEqual(edit_timeline.summary(old)["seconds"], edit_timeline.summary(fresh)["seconds"])
        old["settings"] = {"transitions": True, "dialogue": True, "subtitles": True, "title_card": True}
        self.assertEqual(edit_timeline.render_plan(old), edit_timeline.render_plan(fresh))

    def test_settings_written_back_as_defaults_still_render_as_before(self):
        timeline = _timeline(color={"contrast": 20}, subtitle={"size": "large"}, title={"animation": "zoom"})
        timeline = edit_timeline.set_settings(timeline, {"finishing": {
            "color": {"preset": "none"}, "subtitle": {"size": "medium"}, "title": {"animation": "fade"}}})
        self.assertTrue(film_finishing.is_default(edit_timeline.finishing_of(timeline)))
        self.assertIsNone(edit_timeline.render_plan(timeline)["finishing"])


class SettingsTest(unittest.TestCase):
    def test_an_edit_names_only_what_moves(self):
        timeline = _timeline(subtitle={"size": "large"})
        timeline = edit_timeline.set_settings(timeline, {"finishing": {"subtitle": {"color": "pale_yellow"}, "color": {"contrast": 12}}})
        value = edit_timeline.finishing_of(timeline)
        self.assertEqual(value["subtitle"], {"size": "large", "color": "pale_yellow", "position": "bottom", "outline": "normal"})
        self.assertEqual(value["color"]["contrast"], 12)
        self.assertEqual(value["title"], {"animation": "fade", "background": None})

    def test_flipping_a_switch_keeps_the_finishing_and_the_other_way_round(self):
        timeline = _timeline(color={"preset": "warm"})
        timeline = edit_timeline.set_settings(timeline, {"transitions": False})
        self.assertEqual(edit_timeline.finishing_of(timeline)["color"]["preset"], "warm")
        timeline = edit_timeline.set_settings(timeline, {"finishing": {"ending": {"enabled": True, "text": "明晚见"}}})
        self.assertFalse(edit_timeline.settings_of(timeline)["transitions"])
        self.assertEqual(timeline["revision"], 3)

    def test_what_is_not_an_option_is_refused(self):
        timeline = edit_timeline.build(_task(), title="雪夜")
        for changes in (
            {"sticker": {}}, {"title": {"animation": "spin"}}, {"title": {"speed": 2}}, {"subtitle": {"size": "huge"}},
            {"subtitle": {"color": "#fff"}}, {"color": {"preset": "neon"}}, {"color": {"contrast": "high"}}, {"color": {"contrast": True}},
            {"ending": {"enabled": "yes"}}, {"ending": {"text": 12}}, {"title": {"background": {"shot_uid": 99, "at": 1}}},
            {"title": {"background": {"at": 1}}}, {"title": "zoom"}, "zoom",
        ):
            with self.subTest(changes=changes), self.assertRaises(edit_timeline.TimelineError):
                edit_timeline.set_settings(timeline, {"finishing": changes})
        with self.assertRaises(edit_timeline.TimelineError):
            edit_timeline.set_settings(timeline, {"colour": True})

    def test_the_title_frame_names_a_shot_of_the_film_and_a_moment_inside_it(self):
        timeline = _timeline(title={"background": {"shot_uid": 3, "at": 1.234}})
        self.assertEqual(edit_timeline.finishing_of(timeline)["title"]["background"], {"shot_uid": 3, "shot_id": 1, "at": 1.23})
        late = _timeline(title={"background": {"shot_uid": 2, "at": 99}})
        self.assertEqual(edit_timeline.finishing_of(late)["title"]["background"]["at"], 3.9, "kept inside the 4 s clip")
        spec = edit_timeline.render_plan(late)["finishing"]
        self.assertEqual(spec["title"], {"animation": "fade", "background": {"video_url": "http://x/2.mp4", "at": 3.9}})
        cleared = edit_timeline.set_settings(late, {"finishing": {"title": {"background": None}}})
        self.assertIsNone(edit_timeline.render_plan(cleared)["finishing"])

    def test_a_frame_whose_shot_left_the_timeline_falls_back_to_the_plain_card(self):
        timeline = _timeline(title={"background": {"shot_uid": 3, "at": 1}})
        timeline["clips"] = timeline["clips"][:2]
        self.assertIsNone(edit_timeline.render_plan(timeline)["finishing"])

    def test_the_switches_decide_whether_title_and_subtitle_finishing_matter(self):
        timeline = _timeline(title={"animation": "reveal"}, subtitle={"position": "raised"})
        self.assertEqual(set(edit_timeline.render_plan(timeline)["finishing"]), {"title", "subtitle"})
        off = edit_timeline.set_settings(timeline, {"title_card": False, "subtitles": False})
        self.assertIsNone(edit_timeline.render_plan(off)["finishing"])

    def test_a_preset_sets_the_sliders_and_a_moved_slider_is_custom(self):
        timeline = _timeline(color={"preset": "film"})
        self.assertEqual(edit_timeline.finishing_of(timeline)["color"], {"preset": "film", "brightness": -4, "contrast": 14, "saturation": -12, "warmth": 8})
        moved = edit_timeline.set_settings(timeline, {"finishing": {"color": {"warmth": 500}}})
        self.assertEqual(edit_timeline.finishing_of(moved)["color"]["warmth"], 100, "kept inside the slider")
        self.assertEqual(edit_timeline.finishing_of(moved)["color"]["preset"], "custom")
        self.assertEqual(edit_timeline.render_plan(moved)["finishing"]["grade"], {"brightness": -4, "contrast": 14, "saturation": -12, "warmth": 100})
        reset = edit_timeline.set_settings(moved, {"finishing": {"color": dict.fromkeys(film_finishing.sliders(), 0)}})
        self.assertEqual(edit_timeline.finishing_of(reset)["color"]["preset"], "none")
        self.assertIsNone(edit_timeline.render_plan(reset)["finishing"])

    def test_the_ending_card_needs_to_be_on_and_to_have_a_line(self):
        base = edit_timeline.summary(_timeline())["seconds"]
        on_without_text = _timeline(ending={"enabled": True})
        self.assertIsNone(edit_timeline.render_plan(on_without_text)["finishing"])
        self.assertEqual(edit_timeline.summary(on_without_text)["seconds"], base)
        written = _timeline(ending={"enabled": True, "text": "  明晚\n同一时间，  真相揭晓 " + "啊" * 200})
        ending = edit_timeline.render_plan(written)["finishing"]["ending"]
        self.assertTrue(ending["text"].startswith("明晚 同一时间， 真相揭晓 啊"))
        self.assertEqual(len(ending["text"]), 80)
        self.assertEqual(ending["seconds"], 3.0)
        self.assertEqual(edit_timeline.summary(written)["seconds"], base + 3.0)
        off = edit_timeline.set_settings(written, {"finishing": {"ending": {"enabled": False}}})
        self.assertIsNone(edit_timeline.render_plan(off)["finishing"])
        self.assertTrue(edit_timeline.finishing_of(off)["ending"]["text"], "the line is kept for the next time it is switched on")

    def test_a_refresh_keeps_the_finishing(self):
        timeline = _timeline(color={"preset": "cool"}, ending={"enabled": True, "text": "未完待续"})
        task = _task()
        task["assets"]["5"][2]["video_url"] = "http://x/3b.mp4"
        refreshed = edit_timeline.refresh(timeline, task)
        self.assertEqual(edit_timeline.finishing_of(refreshed), edit_timeline.finishing_of(timeline))

    def test_a_damaged_saved_value_reads_as_the_default_for_that_item_only(self):
        timeline = _timeline(subtitle={"size": "small"})
        timeline["settings"]["finishing"]["subtitle"]["color"] = "ultraviolet"
        timeline["settings"]["finishing"]["color"] = "broken"
        value = edit_timeline.finishing_of(timeline)
        self.assertEqual(value["subtitle"], {"size": "small", "color": "white", "position": "bottom", "outline": "normal"})
        self.assertEqual(value["color"], film_finishing.defaults()["color"])


class GradeTest(unittest.TestCase):
    def test_neutral_values_add_no_filter(self):
        self.assertEqual(film_finishing.grade_filters(None), [])
        self.assertEqual(film_finishing.grade_filters(dict.fromkeys(film_finishing.sliders(), 0)), [])
        self.assertEqual(film_finishing_render.grade_prefix("ffmpeg", None), "")

    def test_the_sliders_become_eq_and_colour_temperature(self):
        self.assertEqual(film_finishing.grade_filters({"brightness": 50, "contrast": -25, "saturation": 100, "warmth": 0}),
                         [("eq", "eq=brightness=0.100:contrast=0.900:saturation=2.000")])
        warm = dict(film_finishing.grade_filters({"warmth": 50}))
        cool = dict(film_finishing.grade_filters({"warmth": -50}))
        self.assertEqual(warm, {"colortemperature": "colortemperature=temperature=5500"}, "warmer is a lower colour temperature; no eq when only warmth moved")
        self.assertEqual(cool, {"colortemperature": "colortemperature=temperature=7500"})

    def test_a_filter_this_ffmpeg_lacks_is_left_out(self):
        with patch.object(film_finishing_render, "_filters", return_value=frozenset({"eq"})):
            self.assertEqual(film_finishing_render.grade_prefix("ffmpeg", {"contrast": 25, "warmth": 40}), "eq=brightness=0.000:contrast=1.100:saturation=1.000,")
        with patch.object(film_finishing_render, "_filters", return_value=None):
            self.assertIn("colortemperature=", film_finishing_render.grade_prefix("ffmpeg", {"warmth": 40}))


class ViewTest(unittest.TestCase):
    def test_the_page_gets_the_value_the_options_and_the_teaser(self):
        timeline = _timeline(color={"preset": "warm"})
        timeline["episode"] = 1
        view = post_production.view(_task(), timeline, [])["finishing"]
        self.assertEqual(view["value"]["color"]["preset"], "warm")
        self.assertEqual(view["options"]["title_animations"], ["fade", "zoom", "reveal"])
        self.assertEqual(view["options"]["subtitle"]["sizes"], ["small", "medium", "large"])
        self.assertEqual(view["options"]["color"]["presets"][0], {"id": "none", "brightness": 0, "contrast": 0, "saturation": 0, "warmth": 0})
        self.assertEqual(view["ending_teaser"], "下一集： 宫门 紧闭，她一个人回来了。")

    def test_no_teaser_means_an_empty_suggestion(self):
        timeline = _timeline()
        timeline["episode"] = 2
        self.assertEqual(film_finishing.teaser_of(_task(), 2), "")
        self.assertEqual(film_finishing.teaser_of({"assets": {}}, None), "")
        self.assertEqual(film_finishing.teaser_of(_task(), None), "", "a one-run film ends where its last episode does")
        self.assertEqual(post_production.view(_task(), timeline, [])["finishing"]["ending_teaser"], "")

    def test_nothing_on_the_film_is_labelled_by_default(self):
        defaults = film_finishing.defaults()
        self.assertEqual(defaults["ending"], {"enabled": False, "text": ""})
        self.assertIsNone(film_finishing.render_spec(edit_timeline.build(_task(), title="雪夜")))


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.service.repo.save_task("finish-1", _task())

    def test_the_settings_edit_carries_finishing_from_the_request_to_the_saved_timeline(self):
        request = TimelineOperationRequest(operation="settings", settings={"finishing": {
            "title": {"animation": "zoom", "background": {"shot_uid": 2, "at": 1.5}}, "color": {"preset": "bright"},
            "ending": {"enabled": True, "text": "明晚见"}}})
        result = self.service.edit_timeline("finish-1", request.operation, request.model_dump(exclude={"operation"}, exclude_none=True))
        value = result["post"]["finishing"]["value"]
        self.assertEqual(value["title"], {"animation": "zoom", "background": {"shot_uid": 2, "shot_id": 2, "at": 1.5}})
        self.assertEqual(value["color"]["preset"], "bright")
        self.assertEqual(result["post"]["settings"], {"transitions": True, "dialogue": True, "subtitles": True, "title_card": True, "name_cards": True})
        saved = self.service.repo.get_task("finish-1")["assets"][edit_timeline.TIMELINE_KEY]
        self.assertEqual(edit_timeline.render_plan(saved)["finishing"]["ending"], {"text": "明晚见", "seconds": 3.0})
        cleared = TimelineOperationRequest(operation="settings", settings={"subtitles": False, "finishing": {"title": {"background": None}}})
        result = self.service.edit_timeline("finish-1", cleared.operation, cleared.model_dump(exclude={"operation"}, exclude_none=True))
        self.assertIsNone(result["post"]["finishing"]["value"]["title"]["background"])
        self.assertFalse(result["post"]["settings"]["subtitles"])

    def test_a_bad_value_is_a_timeline_error_with_wording_from_the_data_file(self):
        with self.assertRaises(edit_timeline.TimelineError) as caught:
            self.service.edit_timeline("finish-1", "settings", {"settings": {"finishing": {"title": {"animation": "spin"}}}})
        self.assertIn("spin", str(caught.exception))
        self.assertIn("fade, zoom, reveal", str(caught.exception))


def _pixels(path):
    from PIL import Image

    with Image.open(path) as image:
        return image.mode, image.size, image.tobytes()


def _ink_box(path):
    """The bounding box of everything drawn on a transparent subtitle PNG."""
    from PIL import Image

    with Image.open(path) as image:
        return image.getchannel("A").getbbox()


@unittest.skipUnless(FONT, "needs a CJK font")
class DrawingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def test_the_default_subtitle_is_the_old_one_pixel_for_pixel(self):
        for index, text in enumerate(("你敢？", "朕的江山，岂容你一个外人指手画脚！来人，把她给我拿下，押入天牢，听候发落。", "")):
            old, new = str(self.dir / f"old{index}.png"), str(self.dir / f"new{index}.png")
            self.assertTrue(media_compositor._render_subtitle_png(text, old))
            self.assertTrue(film_finishing_render.render_subtitle_png(text, new, film_finishing.defaults()["subtitle"]))
            self.assertEqual(_pixels(old), _pixels(new), text)

    def test_the_compositor_hands_a_chosen_style_to_the_styled_renderer(self):
        style = {"size": "large", "color": "pale_yellow", "position": "raised", "outline": "bold"}
        with patch.object(film_finishing_render, "render_subtitle_png", return_value=True) as styled:
            media_compositor._render_subtitle_png("你敢？", str(self.dir / "a.png"), style)
            media_compositor._render_subtitle_png("你敢？", str(self.dir / "b.png"))
            media_compositor._render_subtitle_png("你敢？", str(self.dir / "c.png"), None)
        styled.assert_called_once_with("你敢？", str(self.dir / "a.png"), style)

    def test_size_position_colour_and_outline_change_the_picture(self):
        from PIL import Image

        def render(name, **style):
            path = str(self.dir / f"{name}.png")
            self.assertTrue(film_finishing_render.render_subtitle_png("朕的江山。", path, {**film_finishing.defaults()["subtitle"], **style}))
            return path

        base, large, small = _ink_box(render("base")), _ink_box(render("large", size="large")), _ink_box(render("small", size="small"))
        self.assertGreater(large[2] - large[0], base[2] - base[0])
        self.assertLess(small[2] - small[0], base[2] - base[0])
        self.assertAlmostEqual(base[3], large[3], delta=4, msg="the block keeps its bottom edge when the size changes")
        self.assertAlmostEqual(base[3], small[3], delta=4)
        raised = _ink_box(render("raised", position="raised"))
        self.assertLess(raised[3], base[3] - 150, "偏上 clears a platform's bottom bar")
        with Image.open(render("yellow", color="pale_yellow")) as image:
            colours = {colour[:3] for _count, colour in image.getcolors(maxcolors=1 << 24) if colour[3] == 255}
        self.assertIn((255, 236, 150), colours)
        self.assertNotIn((255, 255, 255), colours)
        plain, bold = _pixels(render("plain", outline="none")), _pixels(render("bold", outline="bold"))
        self.assertNotEqual(plain, _pixels(render("base2")))
        self.assertNotEqual(bold, _pixels(render("base3")))

    def test_the_title_painted_on_the_plain_card_is_the_old_title_card(self):
        for index, title in enumerate(("雪夜", "雪夜长歌：朕的江山岂容外人指手画脚之归来的她与那年冬天的大雪 第12集", "")):
            old, new = str(self.dir / f"old{index}.png"), str(self.dir / f"new{index}.png")
            self.assertTrue(media_compositor._render_title_png(title, old))
            card = film_finishing_render._plain_card()
            film_finishing_render.paint_title(film_finishing_render._Painter(card.size, card), title)
            card.save(new)
            self.assertEqual(_pixels(old), _pixels(new), title)

    def test_the_title_layer_over_a_card_matches_the_title_painted_on_it(self):
        from PIL import Image, ImageChops

        card = film_finishing_render._plain_card()
        film_finishing_render.paint_title(film_finishing_render._Painter(card.size, card), "雪夜")
        layer = film_finishing_render._Painter(card.size)
        film_finishing_render.paint_title(layer, "雪夜")
        over = Image.alpha_composite(film_finishing_render._plain_card().convert("RGBA"), layer.image).convert("RGB")
        worst = max(high for _low, high in ImageChops.difference(card, over).getextrema())
        self.assertLessEqual(worst, 3, "soft edges keep the ink's colour: no dark fringe")

    def test_the_reveal_shows_each_character_where_it_ends_up(self):
        from PIL import ImageChops

        self.assertEqual(film_finishing_render.title_characters("雪夜长歌"), 4)
        full, half, none = (film_finishing_render._plain_card() for _ in range(3))
        film_finishing_render.paint_title(film_finishing_render._Painter(full.size, full), "雪夜长歌")
        film_finishing_render.paint_title(film_finishing_render._Painter(half.size, half), "雪夜长歌", upto=2)
        film_finishing_render.paint_title(film_finishing_render._Painter(none.size, none), "雪夜长歌", upto=0)
        left, _top, right, _bottom = ImageChops.difference(full, half).getbbox()
        self.assertGreater(left, full.size[0] / 2 - 10, "the first two characters are already in place; only the right half differs")
        self.assertLess(ImageChops.difference(half, none).getbbox()[2], full.size[0] / 2 + 10)
        self.assertGreater(right, left)

    def test_the_ending_card_carries_only_the_users_line(self):
        from PIL import Image

        path = str(self.dir / "ending.png")
        self.assertTrue(film_finishing_render.render_ending_png("明晚同一时间，真相揭晓。", path))
        with Image.open(path) as image:
            self.assertEqual(image.size, (media_compositor.OUT_W, media_compositor.OUT_H))
            left, top, right, bottom = image.point(lambda value: 255 if value > 60 else 0).convert("L").getbbox()
        self.assertTrue(700 < top < bottom < 1220, "one centred line and nothing else on the card")
        self.assertTrue(100 <= left and right <= media_compositor.OUT_W - 100)


def _make(args, out):
    subprocess.run([FFMPEG, "-v", "error", "-y", *args, str(out)], check=True)


def _seconds(path):
    found = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v", "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True).stdout.strip()
    return float(found or 0)


def _size(path):
    return subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True).stdout.strip()


def _frame(path, at, box="iw:ih:0:0"):
    """A frame of the film as a small RGB picture's bytes (``box`` crops first: w:h:x:y)."""
    return subprocess.run([FFMPEG, "-v", "error", "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1", "-vf", f"crop={box},scale=16:16",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout


def _mean(data):
    return sum(data) / max(1, len(data))


@unittest.skipUnless(FFMPEG and FFPROBE and FONT, "needs ffmpeg, ffprobe and a CJK font")
class RenderTest(unittest.TestCase):
    """Real ffmpeg on two tiny local clips: a bright one and a mid-grey one."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.media = Path(cls.temp.name) / "media"
        cls.media.mkdir()
        patcher = patch.object(media_compositor, "MEDIA_DIR", str(cls.media))
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.clips = []
        for name, source in (("bright.mp4", "testsrc2=size=360x640:rate=24"), ("grey.mp4", "color=c=0x808080:size=360x640:rate=24")):
            _make(["-f", "lavfi", "-i", source, "-t", "1.6", "-c:v", "libx264", "-pix_fmt", "yuv420p"], cls.media / name)
            cls.clips.append(media_compositor.public_url(name))

    def compose(self, **kwargs):
        """The film's local path and every ffmpeg command the compositor ran to make it."""
        commands = []
        real_run = subprocess.run

        def recording(command, *args, **options):
            commands.append([str(part) for part in command])
            return real_run(command, *args, **options)

        with patch.object(media_compositor.subprocess, "run", side_effect=recording):
            url = media_compositor.compose_film(self.clips, ["你敢？", ""], None, tag="finishing", bgm=False, **kwargs)
        self.assertTrue(url, "the film was not composed")
        path = media_compositor.local_media_path(url)
        self.assertTrue(path and os.path.exists(path))
        return path, commands

    @staticmethod
    def shot_filters(commands):
        """The filter text of each shot's own encode (the commands that read raw_N.mp4)."""
        found = []
        for command in commands:
            if any(part.endswith(".mp4") and "raw_" in os.path.basename(part) for part in command) and command[0] != FFPROBE:
                for flag in ("-vf", "-filter_complex"):
                    if flag in command:
                        found.append(command[command.index(flag) + 1])
        return found

    def test_without_finishing_the_filter_graph_is_the_old_one(self):
        plain, commands = self.compose(title="雪夜")
        fit = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
        self.assertEqual(self.shot_filters(commands), [f"[0:v]{fit}[s0];[s0][1:v]overlay=0:0[s1]", fit])
        everything = " ".join(part for command in commands for part in command)
        for filter_name in ("eq=", "colortemperature", "zoompan"):
            self.assertNotIn(filter_name, everything)
        self.assertFalse(any("ending" in part or "title_" in part for command in commands for part in command))
        same, again = self.compose(title="雪夜", finishing=None)
        self.assertEqual(os.path.basename(plain), os.path.basename(same), "no finishing, same film file as before")
        self.assertEqual(self.shot_filters(again), self.shot_filters(commands))
        empty, _ = self.compose(title="雪夜", finishing={})
        self.assertEqual(os.path.basename(plain), os.path.basename(empty))

    def test_the_grade_changes_the_shots_and_leaves_the_bars_and_cards_alone(self):
        plain, _ = self.compose(title="雪夜")
        graded, commands = self.compose(title="雪夜", finishing={"grade": {"brightness": 60, "contrast": 0, "saturation": 0, "warmth": 60}})
        self.assertNotEqual(os.path.basename(plain), os.path.basename(graded))
        for text in self.shot_filters(commands):
            self.assertIn("eq=brightness=0.120:contrast=1.000:saturation=1.000,colortemperature=temperature=5300,scale=1080", text)
        self.assertAlmostEqual(_seconds(graded), _seconds(plain), delta=0.05)
        # 灰色那一镜(成片 4.3 秒处)：调亮、调暖以后更亮，红多于蓝。
        at = _seconds(plain) - 0.6
        before, after = _frame(plain, at, "iw:ih/3:0:ih/3"), _frame(graded, at, "iw:ih/3:0:ih/3")
        self.assertGreater(_mean(after), _mean(before) + 10)
        self.assertGreater(_mean(after[0::3]), _mean(after[2::3]) + 10, "warmer: more red than blue")
        self.assertAlmostEqual(_mean(before[0::3]), _mean(before[2::3]), delta=4)
        # 片名卡不调色。
        self.assertAlmostEqual(_mean(_frame(graded, 1.0)), _mean(_frame(plain, 1.0)), delta=1.5)

    def test_a_narrow_clips_black_bars_stay_black_under_a_grade(self):
        _make(["-f", "lavfi", "-i", "color=c=0x808080:size=640x360:rate=24", "-t", "1.6", "-c:v", "libx264", "-pix_fmt", "yuv420p"], self.media / "wide.mp4")
        url = media_compositor.compose_film([media_compositor.public_url("wide.mp4")], [""], None, tag="finishing_wide", bgm=False,
                                            finishing={"grade": {"brightness": 80, "contrast": 0, "saturation": 0, "warmth": 0}})
        path = media_compositor.local_media_path(url)
        self.assertLess(_mean(_frame(path, 0.8, "iw:ih/5:0:0")), 20, "the bar above the picture")
        self.assertGreater(_mean(_frame(path, 0.8, "iw:ih/8:0:ih*7/16")), 150, "the picture itself got brighter")

    def test_the_ending_card_follows_the_last_shot(self):
        plain, _ = self.compose()
        ended, commands = self.compose(finishing={"ending": {"text": "明晚同一时间，真相揭晓。", "seconds": 3.0}})
        self.assertAlmostEqual(_seconds(ended), _seconds(plain) + 3.0 - 0.35, delta=0.15)
        self.assertEqual(_size(ended), "1080,1920")
        tail = _frame(ended, _seconds(ended) - 1.0)
        self.assertLess(_mean(tail), 30, "the film ends on the dark card")
        self.assertGreater(max(_frame(ended, _seconds(ended) - 1.0, "iw:ih/10:0:ih*9/20")), 60, "with the line on it, in the middle")
        self.assertLess(max(_frame(ended, _seconds(ended) - 1.0, "iw:ih/3:0:0")), 30, "and nothing else above it")
        self.assertLess(max(_frame(ended, _seconds(ended) - 1.0, "iw:ih/3:0:ih*2/3")), 30, "or below it")
        self.assertGreater(_mean(_frame(ended, _seconds(plain) - 0.6)), 90, "the last shot is still there before it")
        self.assertEqual(self.shot_filters(commands), self.shot_filters(self.compose()[1]), "the shots are encoded as before")

    def test_the_title_card_sits_on_the_chosen_frame_with_each_animation(self):
        plain, _ = self.compose(title="雪夜")
        dark = _mean(_frame(plain, 1.0))
        for animation in ("fade", "zoom", "reveal"):
            with self.subTest(animation=animation):
                film, commands = self.compose(title="雪夜", finishing={"title": {"animation": animation, "background": {"video_url": self.clips[0], "at": 0.8}}})
                self.assertAlmostEqual(_seconds(film), _seconds(plain), delta=0.1)
                self.assertEqual(_size(film), "1080,1920")
                self.assertGreater(_mean(_frame(film, 1.5)), dark + 25, "a frame of the bright clip is behind the title")
                self.assertLess(_mean(_frame(film, 1.5)), _mean(_frame(film, 3.2)) - 15, "dimmed so the title reads")
                self.assertEqual(any("zoompan" in part for command in commands for part in command), animation == "zoom")
                # 片名在卡片正中偏上的那一条里：逐字出现时开头字少，后面字全。
                def moved(box):
                    return _mean([abs(a - b) for a, b in zip(_frame(film, 0.05, box), _frame(film, 1.8, box))])

                # 「雪夜」两个字各 64 px，居中：左字在 x 476–540，右字在 540–604，字顶在 y 878 附近。
                first, second = moved("64:80:476:880"), moved("64:80:540:880")
                if animation == "fade":
                    self.assertLess(max(first, second), 2, "a still card")
                elif animation == "reveal":
                    self.assertLess(first, 4, "the first character is there from the start")
                    self.assertGreater(second, 15, "the second one arrives later")
                else:
                    self.assertGreater(moved("iw:ih/3:0:0"), 2, "the frame behind the title moves")

    def test_the_animations_work_on_the_plain_card_too(self):
        plain, _ = self.compose(title="雪夜")
        for animation in ("zoom", "reveal"):
            with self.subTest(animation=animation):
                film, _ = self.compose(title="雪夜", finishing={"title": {"animation": animation, "background": None}})
                self.assertAlmostEqual(_seconds(film), _seconds(plain), delta=0.1)
                self.assertAlmostEqual(_mean(_frame(film, 2.0)), _mean(_frame(plain, 2.0)), delta=6, msg="still the dark card with the title")

    def test_a_frame_that_cannot_be_fetched_leaves_the_plain_card(self):
        plain, _ = self.compose(title="雪夜")
        film, _ = self.compose(title="雪夜", finishing={"title": {"animation": "fade", "background": {"video_url": media_compositor.public_url("gone.mp4"), "at": 1}}})
        self.assertAlmostEqual(_seconds(film), _seconds(plain), delta=0.1)
        self.assertAlmostEqual(_mean(_frame(film, 1.0)), _mean(_frame(plain, 1.0)), delta=1.5)

    def test_every_burned_subtitle_takes_the_style_including_native_sound_ones(self):
        style = {"size": "large", "color": "pale_yellow", "position": "raised", "outline": "bold"}
        seen = []
        real = film_finishing_render.render_subtitle_png

        def spy(text, out_path, used):
            seen.append((text, dict(used)))
            return real(text, out_path, used)

        with patch.object(film_finishing_render, "render_subtitle_png", side_effect=spy):
            film, _ = self.compose(finishing={"subtitle": style}, subtitle_timings=[None, [{"text": "原声里说的话。", "start": 0.2, "end": 1.2}]])
        self.assertEqual(seen, [("你敢？", style), ("原声里说的话。", style)])
        plain, _ = self.compose()
        # 偏上的字幕块在 1920 高的画面里大约 1380–1460；默认的在 1610–1670。
        def moved(box):
            return _mean([abs(a - b) for a, b in zip(_frame(film, 0.8, box), _frame(plain, 0.8, box))])

        self.assertGreater(moved("iw:90:0:1375"), 3, "the styled subtitle sits higher")
        self.assertGreater(moved("iw:60:0:1605"), 3, "and the default place is left empty")
        self.assertLess(moved("iw:300:0:300"), 1.5, "the rest of the picture is the same")


if __name__ == "__main__":
    unittest.main()

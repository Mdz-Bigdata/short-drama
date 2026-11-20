# -*- coding: utf-8 -*-
"""抠像序列帧: a clip on a flat backdrop cut out into same-sized transparent frames.

A tiny clip is made with ffmpeg (a green rectangle moving over magenta) and really keyed, so what is
asserted is what a person would get: one crop box for the whole sequence, transparent corners, an opaque
figure, a manifest that says what was done, and limits that refuse with the reason. No model is called.
"""

import io
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.core import canvas_tools, media_compositor, prompt_data, sprite_frames
from app.core.canvas_tools import CanvasToolError
from app.service import canvas_tool_ops
from tests import test_canvas_tools as canvas_case

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
WIDTH, HEIGHT, SECONDS, SOURCE_FPS = 320, 240, 2, 24
RECT_W, RECT_H = 40, 80
GREEN = (40, 180, 60)


def make_clip(path, backdrop="0xFF00FF", seconds=SECONDS):
    """A green rectangle sliding right and up over a flat backdrop."""
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={backdrop}:s={WIDTH}x{HEIGHT}:d={seconds}:r={SOURCE_FPS}",
        "-f", "lavfi", "-i", "color=c=0x{:02X}{:02X}{:02X}:s={}x{}:d={}:r={}".format(*GREEN, RECT_W, RECT_H, seconds, SOURCE_FPS),
        "-filter_complex", "[0:v][1:v]overlay=x='60+80*t':y='100-20*t'[v]", "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], check=True)


def rect_at(index, fps):
    """Where the rectangle is in kept frame ``index`` (source pixels), a pixel loose for rounding."""
    seconds = index / fps
    left, top = 60 + 80 * seconds, 100 - 20 * seconds
    return (int(left) - 1, int(top) - 1, int(left) + RECT_W + 2, int(top) + RECT_H + 2)


class SettingsTests(unittest.TestCase):
    def test_defaults_and_bounds_come_from_the_data_file(self):
        options = prompt_data.value("sprite_frames", "options")
        plain = sprite_frames.settings_of({})
        self.assertEqual((plain.picked, plain.colour), ("auto", None))
        self.assertEqual((plain.tolerance, plain.fps, plain.max_frames), (40, 12, 120))
        self.assertEqual(plain.fps, options["fps"]["default"])
        wild = sprite_frames.settings_of({"tolerance": 900, "fps": 0, "max_frames": 100000})
        self.assertEqual((wild.tolerance, wild.fps, wild.max_frames), (100, 1, options["max_frames"]["max"]))
        self.assertEqual(sprite_frames.settings_of({"fps": "x"}).fps, 12)

    def test_the_named_colours_and_a_custom_one(self):
        self.assertEqual(sprite_frames.settings_of({"key": "magenta"}).colour, (255, 0, 255))
        self.assertEqual(sprite_frames.settings_of({"key": "blue"}).colour, (0, 0, 255))
        self.assertEqual(sprite_frames.settings_of({"key": "green"}).colour, (0, 255, 0))
        self.assertEqual(sprite_frames.settings_of({"key": "custom", "key_hex": "#12AbcD"}).colour, (0x12, 0xAB, 0xCD))
        self.assertEqual(sprite_frames.settings_of({"key": "custom", "key_hex": "00ff7f"}).colour, (0, 255, 127))
        # An unknown choice (an older client) is the automatic one, not a guess at a colour.
        self.assertEqual(sprite_frames.settings_of({"key": "plaid"}).picked, "auto")

    def test_a_custom_colour_that_is_not_one_is_refused_with_what_was_written(self):
        for written in ("red", "#12345", "#gggggg", "0x112233; rm"):
            with self.assertRaises(CanvasToolError, msg=written) as caught:
                sprite_frames.settings_of({"key": "custom", "key_hex": written})
            self.assertIn(written, str(caught.exception))

    def test_tolerance_maps_onto_similarity_and_a_small_blend(self):
        rules = prompt_data.value("sprite_frames", "keying")
        low, mid, high = (sprite_frames.key_filter((255, 0, 255), value) for value in (0, 50, 100))
        self.assertEqual(low["similarity"], rules["similarity_min"])
        self.assertEqual(high["similarity"], rules["similarity_max"])
        self.assertTrue(low["similarity"] < mid["similarity"] < high["similarity"])
        for made in (low, mid, high):
            self.assertTrue(0 < made["blend"] <= rules["blend_max"])
            self.assertLess(made["blend"], made["similarity"])
            self.assertIn("chromakey=0xFF00FF", made["graph"])
            self.assertTrue(made["graph"].endswith("format=rgba"))

    def test_a_grey_backdrop_is_keyed_by_rgb_because_it_has_no_chroma(self):
        for grey in ((255, 255, 255), (0, 0, 0), (128, 128, 128), (200, 205, 198)):
            made = sprite_frames.key_filter(grey, 40)
            self.assertEqual(made["method"], "colorkey", grey)
            self.assertIn("colorkey=0x", made["graph"])
        for vivid in ((255, 0, 255), (0, 255, 0), (0, 0, 255), (0, 177, 64)):
            self.assertEqual(sprite_frames.key_filter(vivid, 40)["method"], "chromakey", vivid)

    def test_despill_is_only_claimed_for_the_three_backdrops_it_knows(self):
        self.assertEqual(sprite_frames.spill_family((255, 0, 255)), "magenta")
        self.assertEqual(sprite_frames.spill_family((0, 177, 64)), "green")
        self.assertEqual(sprite_frames.spill_family((20, 30, 240)), "blue")
        for other in ((255, 255, 255), (255, 0, 0), (255, 255, 0), (0, 255, 255), (90, 90, 90)):
            self.assertEqual(sprite_frames.spill_family(other), "", other)


class GeometryTests(unittest.TestCase):
    def test_one_box_holds_every_frame_padded_everywhere_but_the_bottom(self):
        box = sprite_frames.union_box([(100, 50, 140, 130), None, (180, 20, 220, 100)], 320, 240)
        # 120 wide, 110 tall: 2% of the longer side, at least 2 px.
        self.assertEqual(box, (98, 18, 222, 130))
        self.assertEqual(box[3], 130)

    def test_the_padding_stays_inside_the_frame(self):
        self.assertEqual(sprite_frames.union_box([(0, 0, 320, 240)], 320, 240), (0, 0, 320, 240))
        self.assertEqual(sprite_frames.union_box([(1, 1, 319, 200)], 320, 240), (0, 0, 320, 200))

    def test_no_visible_frame_is_no_box(self):
        self.assertIsNone(sprite_frames.union_box([None, None], 320, 240))

    def test_a_sheet_is_near_square_row_major_and_refused_past_the_pixel_limit(self):
        self.assertEqual(sprite_frames.sheet_grid(24, 202, 126), (4, 6))
        self.assertEqual(sprite_frames.sheet_grid(1, 100, 100), (1, 1))
        columns, rows = sprite_frames.sheet_grid(10, 50, 200)
        self.assertGreaterEqual(columns * rows, 10)
        self.assertLess(columns * (rows - 1), 10)
        limits = prompt_data.value("sprite_frames", "sheet")
        self.assertIsNone(sprite_frames.sheet_grid(240, 1080, 1920))
        self.assertIsNone(sprite_frames.sheet_grid(2, limits["max_side"] + 1, 10))

    def test_a_clip_that_would_give_too_many_frames_is_refused_with_the_numbers(self):
        settings = sprite_frames.settings_of({"fps": 24, "max_frames": 60})
        with self.assertRaises(CanvasToolError) as caught:
            sprite_frames.check_size({"width": 720, "height": 1280, "duration": 5.0}, settings)
        message = str(caught.exception)
        for part in ("5.0", "24", "120", "60", str(prompt_data.value("sprite_frames", "options")["max_frames"]["max"])):
            self.assertIn(part, message)
        self.assertEqual(sprite_frames.check_size({"width": 720, "height": 1280, "duration": 2.5}, settings), 60)

    def test_a_clip_too_heavy_to_key_is_refused(self):
        settings = sprite_frames.settings_of({"fps": 30, "max_frames": 240})
        with self.assertRaises(CanvasToolError) as caught:
            sprite_frames.check_size({"width": 3840, "height": 2160, "duration": 8.0}, settings)
        self.assertEqual(str(caught.exception), prompt_data.text("sprite_frames", "error.too_heavy").format(3840, 2160, 240))

    def test_a_clip_with_no_length_is_refused(self):
        with self.assertRaises(CanvasToolError):
            sprite_frames.check_size({"width": 320, "height": 240, "duration": 0}, sprite_frames.settings_of({}))


class CornerColourTests(unittest.TestCase):
    def test_the_backdrop_is_read_from_the_corners_not_the_middle(self):
        image = Image.new("RGB", (200, 120), (250, 4, 248))
        image.paste((30, 160, 40), (40, 20, 160, 100))
        red, green, blue = sprite_frames.corner_colour(image)
        self.assertEqual((red, green, blue), (250, 4, 248))

    def test_one_corner_covered_by_the_figure_does_not_change_the_answer(self):
        image = Image.new("RGB", (200, 120), (0, 0, 255))
        image.paste((200, 180, 150), (150, 80, 200, 120))
        self.assertEqual(sprite_frames.corner_colour(image), (0, 0, 255))

    def test_corners_that_are_not_one_colour_are_refused(self):
        image = Image.new("RGB", (200, 120), (255, 0, 255))
        image.paste((0, 255, 0), (100, 0, 200, 120))
        with self.assertRaises(CanvasToolError) as caught:
            sprite_frames.corner_colour(image)
        self.assertEqual(str(caught.exception), prompt_data.text("sprite_frames", "error.corners_differ"))


@unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
class CutOutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.clip = Path(cls.folder.name) / "magenta.mp4"
        make_clip(cls.clip)

    def cut(self, params, clip=None, name="out"):
        clip = clip or self.clip
        zip_out, preview = Path(self.folder.name) / f"{name}.zip", Path(self.folder.name) / f"{name}.png"
        with tempfile.TemporaryDirectory() as scratch:
            manifest = sprite_frames.cut_out(
                str(clip), params, facts=canvas_tool_ops._probe(str(clip)), run_ffmpeg=canvas_tool_ops._run_ffmpeg, scratch=scratch,
                zip_out=str(zip_out), preview_out=str(preview),
            )
        return manifest, zip_out, preview

    def frames(self, zip_out):
        with zipfile.ZipFile(zip_out) as archive:
            names = sorted(name for name in archive.namelist() if name[:4].isdigit())
            return names, [Image.open(io.BytesIO(archive.read(name))).convert("RGBA") for name in names]

    def test_every_frame_is_the_same_size_with_clear_corners_and_an_opaque_figure(self):
        manifest, zip_out, _ = self.cut({})
        names, frames = self.frames(zip_out)
        self.assertEqual(names, [f"{index:04d}.png" for index in range(1, 25)])
        self.assertEqual({frame.size for frame in frames}, {(manifest["frame_width"], manifest["frame_height"])})
        crop = manifest["crop"]
        for index, frame in enumerate(frames):
            width, height = frame.size
            for corner in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
                self.assertEqual(frame.getpixel(corner), (0, 0, 0, 0), (index, corner))
            left, top, right, bottom = rect_at(index, 12)
            # Well inside the rectangle every pixel is fully opaque and still green.
            inside = frame.crop((left - crop["x"] + 6, top - crop["y"] + 6, right - crop["x"] - 6, bottom - crop["y"] - 6))
            self.assertEqual(inside.getchannel("A").getextrema(), (255, 255), index)
            red, green, blue, _ = inside.getpixel((inside.width // 2, inside.height // 2))
            for got, wanted in zip((red, green, blue), GREEN):
                self.assertLess(abs(got - wanted), 16, index)

    def test_one_fixed_box_holds_the_figure_in_every_frame_and_its_bottom_is_the_foot_line(self):
        manifest, zip_out, _ = self.cut({})
        crop = manifest["crop"]
        self.assertEqual(manifest["source"], {"width": WIDTH, "height": HEIGHT})
        self.assertEqual((crop["width"], crop["height"]), (manifest["frame_width"], manifest["frame_height"]))
        for index in range(manifest["count"]):
            left, top, right, bottom = rect_at(index, 12)
            self.assertLessEqual(crop["x"], left + 1, index)
            self.assertLessEqual(crop["y"], top + 1, index)
            self.assertGreaterEqual(crop["x"] + crop["width"], right - 1, index)
            self.assertGreaterEqual(crop["y"] + crop["height"], bottom - 1, index)
        # The box is tight: a little padding, not the whole frame.
        self.assertLess(crop["width"], WIDTH - 60)
        self.assertLess(crop["height"], HEIGHT - 60)
        # The rectangle starts lowest (its bottom at y=180) and rises: the foot line is that bottom, unpadded.
        self.assertEqual(manifest["baseline"]["frame_y"], manifest["frame_height"])
        self.assertEqual(manifest["baseline"]["source_y"], crop["y"] + crop["height"])
        self.assertTrue(180 <= manifest["baseline"]["source_y"] <= 182, manifest["baseline"])
        _, frames = self.frames(zip_out)
        # Each frame's own visible box moves inside the shared one: nothing was cropped per frame.
        lefts = [frame.getchannel("A").getbbox()[0] for frame in frames]
        self.assertGreater(lefts[-1] - lefts[0], 100)
        self.assertEqual(frames[0].getchannel("A").getbbox()[3], manifest["frame_height"])

    def test_the_manifest_in_the_zip_says_what_was_done(self):
        manifest, zip_out, _ = self.cut({"tolerance": 30, "fps": 6})
        with zipfile.ZipFile(zip_out) as archive:
            held = json.loads(archive.read("manifest.json").decode("utf-8"))
            listed = set(archive.namelist())
        self.assertEqual(held, manifest)
        self.assertEqual((held["count"], held["fps"], held["first"], held["last"]), (12, 6, "0001.png", "0012.png"))
        self.assertEqual(listed, {f"{index:04d}.png" for index in range(1, 13)} | {"sheet.png", "manifest.json"})
        key = held["key"]
        self.assertEqual((key["picked"], key["method"], key["tolerance"]), ("auto", "chromakey", 30))
        self.assertEqual(key["similarity"], sprite_frames.key_filter((255, 0, 255), 30)["similarity"])
        self.assertEqual(held["despill"], "magenta")
        self.assertEqual(held["sheet"]["order"], "row-major")

    def test_auto_picks_magenta_from_the_corners(self):
        manifest, _, _ = self.cut({"key": "auto"})
        red, green, blue = sprite_frames.parse_hex(manifest["key"]["colour"])
        self.assertGreater(min(red, blue), 235)
        self.assertLess(green, 20)

    def test_the_named_and_the_custom_colour_give_the_same_cut_as_auto(self):
        auto, _, _ = self.cut({})
        named, _, _ = self.cut({"key": "magenta"})
        custom, _, _ = self.cut({"key": "custom", "key_hex": "#ff00ff"})
        self.assertEqual((named["key"]["colour"], named["key"]["picked"]), ("#ff00ff", "magenta"))
        self.assertEqual(custom["key"]["picked"], "custom")
        self.assertEqual(named["crop"], auto["crop"])
        self.assertEqual(custom["crop"], auto["crop"])

    def test_the_sheet_is_the_frames_in_row_major_order(self):
        manifest, zip_out, preview = self.cut({})
        _, frames = self.frames(zip_out)
        columns, rows = manifest["sheet"]["columns"], manifest["sheet"]["rows"]
        width, height = manifest["frame_width"], manifest["frame_height"]
        with Image.open(preview) as sheet:
            sheet = sheet.convert("RGBA")
        self.assertEqual(sheet.size, (columns * width, rows * height))
        self.assertGreaterEqual(columns * rows, len(frames))
        for index in (0, 1, columns, len(frames) - 1):
            row, column = divmod(index, columns)
            cell = sheet.crop((column * width, row * height, (column + 1) * width, (row + 1) * height))
            self.assertEqual(cell.tobytes(), frames[index].tobytes(), index)
        with zipfile.ZipFile(zip_out) as archive:
            self.assertEqual(archive.read("sheet.png"), preview.read_bytes())

    def test_no_magenta_is_left_on_the_edge_or_under_the_transparent_pixels(self):
        _, zip_out, _ = self.cut({})
        _, frames = self.frames(zip_out)
        for index in (0, 11, 23):
            raw = frames[index].tobytes()
            for offset in range(0, len(raw), 4):
                red, green, blue, alpha = raw[offset:offset + 4]
                if alpha == 0:
                    self.assertEqual((red, green, blue), (0, 0, 0))
                else:
                    # Magenta is red and blue together above green; a visible pixel may carry at most a trace of it.
                    self.assertLess(min(red, blue) - green, 24, (index, offset))

    def test_more_frames_than_allowed_is_refused_and_says_what_to_change(self):
        with self.assertRaises(CanvasToolError) as caught:
            self.cut({"fps": 12, "max_frames": 10})
        expected = prompt_data.text("sprite_frames", "error.too_many_frames").format(2.0, 12, 24, 10, 240)
        self.assertEqual(str(caught.exception), expected)
        manifest, _, _ = self.cut({"fps": 5, "max_frames": 10})
        self.assertEqual(manifest["count"], 10)

    def test_the_wrong_key_colour_is_said_rather_than_handing_back_the_whole_frame(self):
        with self.assertRaises(CanvasToolError) as caught:
            self.cut({"key": "custom", "key_hex": "#ffff00", "tolerance": 5})
        self.assertEqual(str(caught.exception), prompt_data.text("sprite_frames", "error.nothing_keyed").format("#ffff00"))

    def test_a_clip_that_is_all_backdrop_is_said_too(self):
        empty = Path(self.folder.name) / "empty.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0xFF00FF:s=160x120:d=1:r=12", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(empty)], check=True)
        with self.assertRaises(CanvasToolError) as caught:
            self.cut({}, clip=empty, name="empty")
        self.assertEqual(str(caught.exception), prompt_data.text("sprite_frames", "error.all_keyed"))

    def test_a_grey_backdrop_is_keyed_too(self):
        grey = Path(self.folder.name) / "white.mp4"
        make_clip(grey, backdrop="0xFFFFFF", seconds=1)
        manifest, zip_out, _ = self.cut({}, clip=grey, name="white")
        self.assertEqual((manifest["key"]["method"], manifest["despill"]), ("colorkey", "none"))
        _, frames = self.frames(zip_out)
        self.assertEqual(frames[0].getpixel((0, 0))[3], 0)
        left, top, _, _ = rect_at(0, 12)
        self.assertEqual(frames[0].getpixel((left - manifest["crop"]["x"] + 20, top - manifest["crop"]["y"] + 40))[3], 255)

    def test_too_many_pixels_for_a_sheet_leaves_the_first_frame_as_the_picture(self):
        with patch.dict(prompt_data.value("sprite_frames", "sheet"), {"max_pixels": 5000}):
            manifest, zip_out, preview = self.cut({}, name="nosheet")
        self.assertIsNone(manifest["sheet"])
        _, frames = self.frames(zip_out)
        with zipfile.ZipFile(zip_out) as archive:
            self.assertNotIn("sheet.png", archive.namelist())
        with Image.open(preview) as shown:
            self.assertEqual(shown.convert("RGBA").tobytes(), frames[0].tobytes())


class CatalogTests(unittest.TestCase):
    def test_it_is_a_free_local_video_tool_that_hands_on_a_picture(self):
        tool = canvas_tools.get_tool("sprite_frames")
        self.assertEqual((tool.group, tool.engine, tool.output, tool.videos), ("video", "local", "image", 1))
        self.assertEqual(tool.inputs, canvas_tools.VIDEO_INPUT)
        self.assertEqual(tool.label, prompt_data.text("canvas_tools", "module.tools.34"))


@unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
class RunRouteTests(canvas_case.CanvasToolRunCase):
    """Through the real run route: nothing is paid for, and the node ends up with the sheet, the ZIP and the manifest."""

    def clip(self, name="hero.mp4"):
        make_clip(Path(self.media.name) / name)
        return media_compositor.public_url(name)

    def nodes(self, url, **params):
        return [canvas_case._media("v", "video", url), canvas_case._tool("tool", "sprite_frames", params=params)], [canvas_case._edge("e", "v", "tool", role="ref_video")]

    def test_a_run_is_free_and_leaves_the_sheet_the_zip_and_the_manifest_on_the_node(self):
        answer, output = self.run_tool(*self.nodes(self.clip(), key="magenta", fps=6))
        self.assertEqual(answer["status"], "started")
        self.assertEqual(answer["assessment"]["estimate"]["paid_items"], 0)
        self.assertEqual((self.gateway.image_calls, self.gateway.vision_calls, self.gateway.llm_calls), ([], [], []))
        self.assertEqual(output["medium"], "image")
        self.assertEqual(output["provenance"]["tool"], "sprite_frames")
        sprite = output["sprite"]
        self.assertEqual((sprite["count"], sprite["fps"], sprite["key"]["colour"]), (12, 6, "#ff00ff"))
        with Image.open(self.local(output["url"])) as sheet:
            self.assertEqual(sheet.mode, "RGBA")
            self.assertEqual(sheet.size, (sprite["sheet"]["columns"] * sprite["frame_width"], sprite["sheet"]["rows"] * sprite["frame_height"]))
        with zipfile.ZipFile(self.local(output["zip"])) as archive:
            self.assertEqual(json.loads(archive.read("manifest.json").decode("utf-8")), sprite)
            self.assertEqual(len([name for name in archive.namelist() if name[:4].isdigit()]), 12)
        self.assertTrue(self.local(output["zip"]).name.endswith(".zip"))

    def test_a_refused_run_says_why_and_leaves_no_file_behind(self):
        nodes, edges = self.nodes(self.clip(), fps=24, max_frames=5)
        saved = self.put(nodes, edges)
        self.run_nodes(["tool"], saved["version"])
        history = self.client.get(f"{self.base}/canvas/nodes/tool/history").json()["runs"]
        self.assertEqual(history[0]["status"], "failed")
        self.assertEqual(history[0]["error"], prompt_data.text("sprite_frames", "error.too_many_frames").format(2.0, 24, 48, 5, 240))
        self.assertEqual(list(Path(self.media.name).glob("canvas_*_sprite_frames_*")), [])

    def test_with_no_clip_connected_it_is_blocked_before_it_runs(self):
        saved = self.put([canvas_case._tool("tool", "sprite_frames")])
        answer = self.run_nodes(["tool"], saved["version"])
        self.assertEqual(answer["status"], "blocked")
        self.assertIn("no_video", [problem["code"] for problem in answer["assessment"]["nodes"][0]["problems"]])


if __name__ == "__main__":
    unittest.main()

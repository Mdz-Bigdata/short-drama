# -*- coding: utf-8 -*-
"""The canvas tool node: which engine does the work, what a run costs, and that local tools really do what they say."""

import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.core import canvas_tools, media_compositor, studio_canvas
from app.core.canvas_tools import CanvasToolError
from app.service import canvas_tool_ops, studio_canvas_runs
from tests.test_canvas_workspace import CanvasCase, _node

FRONTEND_CATALOG = Path(__file__).resolve().parents[2] / "frontend" / "src" / "features" / "canvas" / "canvasTools.ts"
HAS_FFMPEG = bool(shutil.which("ffmpeg"))


def _tool(node_id, tool, **payload):
    params = {"tool": tool, **payload.pop("params", {})}
    return _node(node_id, "tool", params=params, **payload)


def _media(node_id, medium, url):
    return _node(node_id, "media", medium=medium, output={"medium": medium, "url": url})


def _edge(edge_id, source, target, kind="reference", role=None):
    return {"id": edge_id, "source": source, "target": target, "kind": kind, "payload": {"role": role} if role else {}}


class CatalogTests(unittest.TestCase):
    def test_the_frontend_table_matches_the_backend(self):
        text = FRONTEND_CATALOG.read_text(encoding="utf-8")
        rows = re.findall(r"id: '(\w+)', label: \(\) => t\('[^']*'\), group: '(\w+)', engine: '(\w+)', output: '(\w+)', inputs: (\w+)", text)
        names = {"IMAGE_INPUT": canvas_tools.IMAGE_INPUT, "VIDEO_INPUT": canvas_tools.VIDEO_INPUT, "TEXT_INPUT": canvas_tools.TEXT_INPUT}
        seen = {tool: (group, engine, output, names[inputs]) for tool, group, engine, output, inputs in rows}
        expected = {tool.id: (tool.group, tool.engine, tool.output, tool.inputs) for tool in canvas_tools.TOOLS}
        self.assertEqual(seen, expected)

    def test_the_style_wall_has_forty_five_distinct_looks_in_three_languages(self):
        looks = canvas_tools.style_wall()
        self.assertEqual(len(looks), 45)
        self.assertEqual(len({look.id for look in looks}), 45)
        for look in looks:
            self.assertEqual(set(look.names), {"zh", "en", "vi"})
            for colour in look.swatch:
                self.assertRegex(colour, r"^#[0-9a-f]{6}$")

    def test_an_unknown_tool_is_refused_rather_than_guessed(self):
        with self.assertRaises(CanvasToolError):
            canvas_tools.tool_of({"payload": {"params": {"tool": "nope"}}})

    def test_a_node_with_no_tool_set_is_the_default(self):
        self.assertEqual(canvas_tools.tool_of({"payload": {}}).id, canvas_tools.DEFAULT_TOOL)


class PromptTests(unittest.TestCase):
    def prompt(self, tool, text="", **params):
        return canvas_tools.image_prompt(canvas_tools.get_tool(tool), params, text)

    def test_redraw_needs_to_know_what_to_change(self):
        with self.assertRaises(CanvasToolError):
            self.prompt("redraw")
        self.assertIn("换成红色外套", self.prompt("redraw", "换成红色外套"))

    def test_style_transfer_needs_a_look_and_uses_its_wording(self):
        with self.assertRaises(CanvasToolError):
            self.prompt("style_transfer")
        self.assertIn(canvas_tools.style_look("ink_wash").prompt, self.prompt("style_transfer", style="ink_wash"))

    def test_templates_that_need_words_ask_for_them(self):
        with self.assertRaises(CanvasToolError):
            self.prompt("template_edit", template="change_outfit")
        self.assertIn("黑色风衣", self.prompt("template_edit", "黑色风衣", template="change_outfit"))
        self.assertIn("路人", self.prompt("template_edit", template="remove_people"))
        with self.assertRaises(CanvasToolError):
            self.prompt("template_edit", template="nope")

    def test_every_template_renders_without_a_stray_placeholder(self):
        for key in ("remove_people", "remove_text", "change_outfit", "change_expression", "change_weather", "add_prop"):
            self.assertNotIn("{", self.prompt("template_edit", "雨", template=key))

    def test_an_unknown_light_or_view_falls_back_instead_of_failing_a_paid_run(self):
        self.assertIn("黄昏", self.prompt("relight", light="nope"))
        self.assertIn("四分之三", self.prompt("multi_view", view="nope"))

    def test_outpaint_names_the_ratio_and_keeps_it_to_the_known_ones(self):
        self.assertIn("9:16", self.prompt("outpaint", ratio="9:16"))
        self.assertIn("16:9", self.prompt("outpaint", ratio="99:1"))


class BeatPlanTests(unittest.TestCase):
    def test_reads_beats_and_drops_rows_with_no_prompt(self):
        beats = canvas_tools.parse_beats(json.dumps({"beats": [{"title": "开门", "prompt": "林夏推门"}, {"title": "空"}]}, ensure_ascii=False))
        self.assertEqual(beats, [{"title": "开门", "prompt": "林夏推门"}])

    def test_a_reply_with_no_beats_fails_rather_than_making_an_empty_plan(self):
        for reply in ("不好意思", '{"beats": []}', '{"beats": "一"}', ""):
            with self.assertRaises(CanvasToolError, msg=reply):
                canvas_tools.parse_beats(reply)

    def test_needs_a_story(self):
        with self.assertRaises(CanvasToolError):
            canvas_tools.beat_prompt("  ")


class GeometryTests(unittest.TestCase):
    def test_grid_cells_cover_the_picture_without_gaps(self):
        boxes = [canvas_tools.grid_box(100, 100, 3, 3, index) for index in range(9)]
        self.assertEqual(boxes[0], (0, 0, 33, 33))
        self.assertEqual(boxes[4], (33, 33, 66, 66))
        self.assertEqual(boxes[8], (66, 66, 100, 100))

    def test_a_cell_past_the_end_is_refused(self):
        with self.assertRaises(CanvasToolError):
            canvas_tools.grid_box(100, 100, 3, 3, 9)

    def test_the_erase_box_stays_inside_the_frame(self):
        # delogo refuses a band touching the edge; the bottom-right corner is where a watermark usually is.
        for params in ({"x": 90, "y": 90, "w": 50, "h": 50}, {"x": 0, "y": 0, "w": 100, "h": 100}, {"x": 100, "y": 100}):
            x, y, w, h = canvas_tools.erase_box(params, 640, 360)
            self.assertGreaterEqual(x, 1)
            self.assertGreaterEqual(y, 1)
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)
            self.assertLess(x + w, 640)
            self.assertLess(y + h, 360)

    def test_cuts_ignore_a_flash_and_the_very_ends(self):
        lines = ["[Parsed_showinfo] n:0 pts_time:0.10 x", "pts_time:2.00", "pts_time:2.20", "pts_time:5.00", "pts_time:9.95", "nothing", "pts_time:bad"]
        self.assertEqual(canvas_tools.scene_cuts(lines, 10.0), [2.0, 5.0])


class StudioTableTests(unittest.TestCase):
    def test_a_tool_takes_what_its_tool_takes(self):
        video = {"id": "v", "kind": "media", "payload": {"medium": "video", "output": {"medium": "video", "url": "/media/a.mp4"}}}
        erase = {"id": "t", "kind": "tool", "payload": {"params": {"tool": "video_erase"}}}
        redraw = {"id": "r", "kind": "tool", "payload": {"params": {"tool": "redraw"}}}
        self.assertEqual(studio_canvas.connection(video, erase), ("reference", "ref_video"))
        with self.assertRaises(studio_canvas.CanvasOperationError):
            studio_canvas.connection(video, redraw)

    def test_a_tool_hands_on_what_it_makes(self):
        for tool, produced in (("redraw", "image"), ("audio_extract", "audio"), ("frame_extract", "image"), ("video_erase", "video"), ("reverse_prompt", "text")):
            self.assertEqual(studio_canvas.output_type({"kind": "tool", "payload": {"params": {"tool": tool}}}), produced, tool)

    def test_a_text_result_counts_as_a_result(self):
        node = {"id": "t", "kind": "tool", "payload": {"params": {"tool": "reverse_prompt"}}}
        output = studio_canvas.effective_output(node, {"t": node}, [], {"t": {"output": {"medium": "text", "url": "", "text": "雨夜"}}})
        self.assertEqual(output["text"], "雨夜")


class CanvasToolRunCase(CanvasCase):
    """Runs through the real run route; models are stubs, ffmpeg and PIL are real."""

    def setUp(self):
        super().setUp()
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        for patcher in (
            patch.object(media_compositor, "MEDIA_DIR", self.media.name),
            patch.object(media_compositor, "PUBLIC_BASE_URL", "https://cdn.test/media/"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.gateway.vision_calls = []
        self.gateway.llm_calls = []
        self.gateway.vision_answer = "看到了"
        self.gateway.llm_answer = json.dumps({"beats": [{"title": "开门", "prompt": "林夏推门"}]}, ensure_ascii=False)

        def describe_image(model, system, prompt, image, *, max_tokens=2000):
            self.gateway.vision_calls.append({"prompt": prompt, "image": image})
            return self.gateway.vision_answer, "vision-1"

        def call_llm(model, system, prompt, title, **kwargs):
            self.gateway.llm_calls.append(prompt)
            return self.gateway.llm_answer

        self.gateway.describe_image = describe_image
        self.gateway.call_llm = call_llm
        vision = patch("app.platform.runtime_models.runtime_model_registry.vision_model", return_value=(object(), "vision-1"))
        vision.start()
        self.addCleanup(vision.stop)

    def picture(self, name="source.png", size=(120, 90), colour=(200, 40, 40)):
        Image.new("RGB", size, colour).save(Path(self.media.name) / name)
        return media_compositor.public_url(name)

    def video(self, name="source.mp4", audio=True):
        arguments = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=1.5:r=12", "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=1.5:r=12"]
        if audio:
            arguments += ["-f", "lavfi", "-i", "sine=frequency=440:duration=3"]
        arguments += ["-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]"]
        if audio:
            arguments += ["-map", "2:a", "-c:a", "aac"]
        arguments += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(Path(self.media.name) / name)]
        subprocess.run(arguments, check=True)
        return media_compositor.public_url(name)

    def run_tool(self, nodes, edges, target="tool"):
        saved = self.put(nodes, edges)
        answer = self.run_nodes([target], saved["version"])
        return answer, self.client.get(f"{self.base}/canvas/outputs").json()["outputs"].get(target)

    def local(self, url):
        return Path(media_compositor.local_media_path(url))


class PaidToolRunTests(CanvasToolRunCase):
    def test_an_image_tool_is_paid_and_waits_for_confirmation(self):
        saved = self.put([_media("img", "image", self.picture()), _tool("tool", "redraw", prompt="换成夜景")], [_edge("e", "img", "tool", role="ref_image")])
        answer = self.run_nodes(["tool"], saved["version"], confirm=False)
        self.assertEqual(answer["status"], "needs_confirmation")
        self.assertEqual(self.gateway.image_calls, [])

    def test_it_sends_the_tools_wording_and_the_picture(self):
        url = self.picture()
        answer, output = self.run_tool([_media("img", "image", url), _tool("tool", "relight", params={"light": "neon"})], [_edge("e", "img", "tool", role="ref_image")])
        self.assertEqual(answer["status"], "started")
        self.assertIn("霓虹", self.gateway.image_calls[0]["prompt"])
        self.assertEqual(self.gateway.image_calls[0]["ref_images"], [url])
        self.assertEqual(output["medium"], "image")

    def test_what_a_tool_lacks_is_said_before_anyone_pays(self):
        version = 0
        for tool, needle in (("redraw", "图片"), ("set_background", "2 张"), ("video_erase", "视频"), ("beat_plan", "提示词"), ("style_transfer", "图片")):
            version = self.put([_tool("tool", tool)], expected=version)["version"]
            answer = self.run_nodes(["tool"], version)
            self.assertEqual(answer["status"], "blocked", tool)
            problems = " ".join(item["message"] for item in answer["assessment"]["nodes"][0]["problems"])
            self.assertIn(needle, problems, tool)

    def test_a_missing_style_blocks_the_run(self):
        saved = self.put([_media("img", "image", self.picture()), _tool("tool", "style_transfer")], [_edge("e", "img", "tool", role="ref_image")])
        answer = self.run_nodes(["tool"], saved["version"])
        self.assertEqual(answer["status"], "blocked")
        self.assertIn("风格", answer["assessment"]["nodes"][1 if answer["assessment"]["nodes"][0]["kind"] == "media" else 0]["problems"][0]["message"])
        self.assertEqual(self.gateway.image_calls, [])

    def test_outpaint_sends_a_padded_picture_and_cleans_it_up(self):
        seen = {}
        original = self.gateway.generate_image

        def capture(model, prompt, ref_images=None, size=None, **kwargs):
            with Image.open(self.local(ref_images[0])) as image:
                seen["size"] = image.size
            return original(model, prompt, ref_images=ref_images, size=size, **kwargs)

        self.gateway.generate_image = capture
        self.run_tool([_media("img", "image", self.picture(size=(100, 100))), _tool("tool", "outpaint", params={"ratio": "16:9"})], [_edge("e", "img", "tool", role="ref_image")])
        self.assertEqual(seen["size"], (178, 100))
        self.assertFalse(list(Path(self.media.name).glob("canvas_*_outpaint_*")))

    def test_reverse_prompt_gives_text_that_a_downstream_node_reads(self):
        self.gateway.vision_answer = "雨夜霓虹街道"
        nodes = [_media("img", "image", self.picture()), _tool("tool", "reverse_prompt"), _node("next", "image_gen")]
        edges = [_edge("a", "img", "tool", role="ref_image"), _edge("b", "tool", "next", kind="dependency", role="prompt")]
        answer, output = self.run_tool(nodes, edges)
        self.assertEqual(answer["status"], "started")
        self.assertEqual((output["medium"], output["text"]), ("text", "雨夜霓虹街道"))
        self.assertTrue(self.gateway.vision_calls[0]["image"].startswith("data:image/"))
        saved = self.client.get(f"{self.base}/canvas").json()
        self.run_nodes(["next"], saved["version"], op="downstream")
        self.assertIn("雨夜霓虹街道", self.gateway.image_calls[0]["prompt"])

    def test_a_text_result_is_not_offered_for_commit_as_a_file(self):
        _, output = self.run_tool([_media("img", "image", self.picture()), _tool("tool", "reverse_prompt")], [_edge("a", "img", "tool", role="ref_image")])
        self.assertEqual(output["medium"], "text")
        preview = self.client.post(f"{self.base}/canvas/commit/preview", json={"node_ids": ["tool"]})
        self.assertEqual(preview.status_code, 200, preview.text)
        row = preview.json()["nodes"][0] if "nodes" in preview.json() else preview.json()["rows"][0]
        self.assertEqual(row["state"], "no_result")

    def test_beat_plan_keeps_its_beats_for_laying_out(self):
        answer, output = self.run_tool([_tool("tool", "beat_plan", prompt="林夏回到老宅", params={"model": "text-1"})], [])
        self.assertEqual(answer["status"], "started")
        self.assertEqual(output["beats"], [{"title": "开门", "prompt": "林夏推门"}])
        self.assertIn("1. 开门：林夏推门", output["text"])

    def test_no_vision_model_is_said_before_the_run(self):
        with patch("app.platform.runtime_models.runtime_model_registry.vision_model", return_value=None):
            saved = self.put([_media("img", "image", self.picture()), _tool("tool", "mark_detect")], [_edge("a", "img", "tool", role="ref_image")])
            answer = self.run_nodes(["tool"], saved["version"])
        self.assertEqual(answer["status"], "blocked")
        self.assertEqual(self.gateway.vision_calls, [])

    def test_voice_isolation_is_refused_with_a_way_forward_when_there_is_no_provider(self):
        with patch.object(media_compositor, "_elevenlabs_available", return_value=False):
            saved = self.put([_media("v", "video", "/media/a.mp4"), _tool("tool", "voice_isolate")], [_edge("a", "v", "tool", role="ref_video")])
            answer = self.run_nodes(["tool"], saved["version"])
        self.assertEqual(answer["status"], "blocked")
        rows = [row for row in answer["assessment"]["nodes"] if row["node_id"] == "tool"]
        self.assertIn("提取音轨", rows[0]["problems"][0]["message"])

    def test_scene_360_fits_the_result_for_wrapping(self):
        buffer = io.BytesIO()
        Image.new("RGB", (400, 300), "gray").save(buffer, format="PNG")
        data = "data:image/png;base64," + __import__("base64").b64encode(buffer.getvalue()).decode()
        self.gateway.generate_image = lambda model, prompt, **kwargs: (data, "stub")
        _, output = self.run_tool([_tool("tool", "scene_360", prompt="中世纪庭院")], [])
        with Image.open(self.local(output["url"])) as image:
            self.assertEqual(image.width, image.height * 2)


class LocalToolRunTests(CanvasToolRunCase):
    def assert_free(self, answer):
        self.assertEqual(answer["status"], "started")
        self.assertEqual(answer["assessment"]["estimate"]["paid_items"], 0)

    def test_upscale_is_free_and_really_bigger(self):
        answer, output = self.run_tool([_media("img", "image", self.picture()), _tool("tool", "upscale_image", params={"factor": "3"})], [_edge("e", "img", "tool", role="ref_image")])
        self.assert_free(answer)
        with Image.open(self.local(output["url"])) as image:
            self.assertEqual(image.size, (360, 270))
        self.assertEqual(self.gateway.image_calls, [])

    def test_an_absurd_upscale_is_refused_with_the_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "big.png"
            Image.new("RGB", (3000, 100)).save(source)
            with self.assertRaises(CanvasToolError):
                canvas_tool_ops.upscale_image(str(source), 4, str(Path(folder) / "out.png"))

    def test_grid_cell_cuts_the_cell_it_was_asked_for(self):
        source = Image.new("RGB", (300, 300), "white")
        source.paste((10, 200, 10), (100, 100, 200, 200))
        source.save(Path(self.media.name) / "grid.png")
        answer, output = self.run_tool(
            [_media("img", "image", media_compositor.public_url("grid.png")), _tool("tool", "grid_cell", params={"rows": 3, "columns": 3, "cell": 5})],
            [_edge("e", "img", "tool", role="ref_image")],
        )
        self.assert_free(answer)
        with Image.open(self.local(output["url"])) as image:
            self.assertEqual(image.size, (100, 100))
            self.assertEqual(image.getpixel((50, 50)), (10, 200, 10))

    def test_pad_refuses_a_picture_already_that_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "a.png"
            Image.new("RGB", (160, 90)).save(source)
            with self.assertRaises(CanvasToolError):
                canvas_tool_ops.pad_for_outpaint(str(source), 16 / 9, str(Path(folder) / "b.png"))

    @unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_video_tools_on_a_real_clip(self):
        url = self.video()
        probe = canvas_tool_ops._probe(self.local(url))
        self.assertEqual((probe["width"], probe["height"], probe["has_audio"]), (320, 180, True))
        with self.subTest("upscale"):
            answer, output = self.run_tool([_media("v", "video", url), _tool("tool", "video_upscale", params={"factor": "2"})], [_edge("e", "v", "tool", role="ref_video")])
            self.assert_free(answer)
            self.assertEqual(canvas_tool_ops._probe(self.local(output["url"]))["width"], 640)

    @unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_erasing_a_corner_works_at_the_frame_edge(self):
        url = self.video()
        answer, output = self.run_tool([_media("v", "video", url), _tool("tool", "video_erase", params={"x": 80, "y": 85, "w": 30, "h": 30})], [_edge("e", "v", "tool", role="ref_video")])
        self.assert_free(answer)
        self.assertEqual(canvas_tool_ops._probe(self.local(output["url"]))["width"], 320)

    @unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_extracting_audio_and_a_frame(self):
        url = self.video()
        answer, output = self.run_tool([_media("v", "video", url), _tool("tool", "audio_extract")], [_edge("e", "v", "tool", role="ref_video")])
        self.assert_free(answer)
        self.assertEqual(output["medium"], "audio")
        self.assertGreater(self.local(output["url"]).stat().st_size, 1000)

    @unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_a_clip_with_no_sound_says_so(self):
        url = self.video("silent.mp4", audio=False)
        saved = self.put([_media("v", "video", url), _tool("tool", "audio_extract")], [_edge("e", "v", "tool", role="ref_video")])
        self.run_nodes(["tool"], saved["version"])
        history = self.client.get(f"{self.base}/canvas/nodes/tool/history").json()["runs"]
        self.assertEqual(history[0]["status"], "failed")
        self.assertEqual(history[0]["error"], "这段视频没有声音")

    @unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_frames_come_from_where_they_were_asked_for(self):
        path = str(self.local(self.video()))
        with tempfile.TemporaryDirectory() as folder:
            first, last = str(Path(folder) / "first.png"), str(Path(folder) / "last.png")
            canvas_tool_ops.extract_frame(path, {"at": "first"}, first)
            canvas_tool_ops.extract_frame(path, {"at": "last"}, last)
            with Image.open(first) as image:
                self.assertGreater(image.convert("RGB").getpixel((10, 10))[0], 150)
            with Image.open(last) as image:
                self.assertGreater(image.convert("RGB").getpixel((10, 10))[2], 150)

    @unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_gif(self):
        url = self.video()
        _, output = self.run_tool([_media("v", "video", url), _tool("tool", "to_gif", params={"seconds": 1, "width": 160})], [_edge("e", "v", "tool", role="ref_video")])
        with Image.open(self.local(output["url"])) as image:
            self.assertEqual((image.format, image.width), ("GIF", 160))
            self.assertGreater(getattr(image, "n_frames", 1), 1)

    @unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_shot_analysis_finds_the_cut_and_shows_the_model_each_shot(self):
        self.gateway.vision_answer = "1｜远景"
        url = self.video()
        answer, output = self.run_tool([_media("v", "video", url), _tool("tool", "shot_analysis")], [_edge("e", "v", "tool", role="ref_video")])
        self.assertEqual(answer["status"], "started")
        self.assertEqual(len(output["cuts"]), 1)
        self.assertAlmostEqual(output["cuts"][0], 1.5, delta=0.2)
        self.assertIn("2 个镜头", self.gateway.vision_calls[0]["prompt"])
        self.assertEqual(output["text"], "1｜远景")

    def test_a_local_run_does_not_need_any_model_configured(self):
        answer, _ = self.run_tool([_media("img", "image", self.picture()), _tool("tool", "upscale_image")], [_edge("e", "img", "tool", role="ref_image")])
        row = next(item for item in answer["assessment"]["nodes"] if item["node_id"] == "tool")
        self.assertEqual((row["model"], row["paid"]), ("local", False))


class AgentTests(CanvasToolRunCase):
    def test_the_agent_can_read_the_catalog_and_set_up_a_tool(self):
        from app.core.agent_tools import catalog

        answer = catalog.call("list_canvas_tools", {}, service=self.drama, user=self.user)
        listed = answer.get("result", answer)
        self.assertEqual(len(listed["tools"]), len(canvas_tools.TOOLS))
        self.assertEqual(len(listed["styles"]), 45)
        document, _ = studio_canvas.apply_operations({"nodes": [], "edges": []}, [
            {"op": "add_node", "ref": "a", "kind": "media"},
            {"op": "add_node", "ref": "b", "kind": "tool", "params": {"tool": "upscale_image"}},
        ])
        kinds = [node["kind"] for node in document["nodes"]]
        self.assertIn("tool", kinds)


class WriterTests(CanvasToolRunCase):
    def write(self, tool, reply, **payload):
        self.gateway.llm_answer = reply
        return self.run_tool([_tool("tool", tool, prompt="林夏回到老宅", params={"model": "text-1"}, **payload)], [])

    def test_an_action_is_broken_into_four_parts(self):
        reply = "起始姿态：背对门站着，重心在右脚\n主动作：右手拔刀，转身向左劈下\n身体联动：左脚上步，躯干左转，视线跟刀尖\n结束姿态：刀尖指地，重心压在前脚"
        _, output = self.write("action_breakdown", reply)
        self.assertTrue(output["text"].startswith("起始姿态："))
        self.assertIn("结束姿态：刀尖指地", output["text"])
        self.assertIn("林夏回到老宅", self.gateway.llm_calls[-1])
        self.assertIn("身体联动", self.gateway.llm_calls[-1])

    def test_a_breakdown_missing_a_part_fails_the_run(self):
        saved = self.put([_tool("tool", "action_breakdown", prompt="劈", params={"model": "m"})])
        self.gateway.llm_answer = "主动作：劈"
        self.run_nodes(["tool"], saved["version"])
        history = self.client.get(f"{self.base}/canvas/nodes/tool/history").json()["runs"]
        self.assertEqual(history[0]["status"], "failed")
        self.assertIn("缺", history[0]["error"])

    def test_a_link_is_designed_from_two_shots(self):
        _, output = self.write("link_design", "接法：同一动作换景别\n镜头A：中景\n镜头B：近景")
        self.assertTrue(output["text"].startswith("接法："))
        self.assertIn("林夏回到老宅", self.gateway.llm_calls[-1])
        self.assertIn("顺着看与走", self.gateway.llm_calls[-1])

    def test_a_first_to_last_frame_move_comes_back_as_a_prompt(self):
        _, output = self.write("frame_bridge", "镜头从高空缓缓下移，推进至村庄")
        self.assertEqual(output["text"], "镜头从高空缓缓下移，推进至村庄")
        self.assertIn("空间穿越", self.gateway.llm_calls[-1])

    def test_a_script_comes_back_as_text(self):
        _, output = self.write("script_write", "老宅，夜\n林夏：我回来了。")
        self.assertEqual((output["medium"], output["text"]), ("text", "老宅，夜\n林夏：我回来了。"))

    def test_a_shot_table_reads_as_a_table_and_can_become_nodes(self):
        reply = json.dumps({"shots": [{"size": "全景", "motion": "推", "seconds": 99, "desc": "林夏推门", "dialogue": "有人吗"}, {"desc": ""}]}, ensure_ascii=False)
        _, output = self.write("shot_table", reply)
        self.assertEqual(output["text"], "1. 全景、推｜15 秒｜林夏推门｜「有人吗」")
        self.assertEqual(output["beats"], [{"title": "第 1 镜", "prompt": "林夏推门，全景，推"}])

    def test_a_shot_table_with_no_shots_fails_the_run(self):
        saved = self.put([_tool("tool", "shot_table", prompt="x", params={"model": "m"})])
        self.gateway.llm_answer = "不好意思"
        self.run_nodes(["tool"], saved["version"])
        history = self.client.get(f"{self.base}/canvas/nodes/tool/history").json()["runs"]
        self.assertEqual(history[0]["status"], "failed")
        self.assertIn("镜头表", history[0]["error"])

    def test_svg_is_stored_clean(self):
        reply = '说明<svg viewBox="0 0 10 10" onload="alert(1)"><script>alert(1)</script><a href="https://x"><rect width="5"/></a><circle r="2" fill="url(#g)"/><rect fill="url(https://evil)" width="1"/><foreignObject/><image href="https://x"/></svg>'
        _, output = self.write("svg_art", reply)
        text = self.local(output["url"]).read_text(encoding="utf-8")
        for bad in ("script", "onload", "foreignObject", "https://", "<image", "<a"):
            self.assertNotIn(bad, text)
        self.assertIn("viewBox", text)
        self.assertIn('fill="url(#g)"', text)

    def test_what_is_not_an_svg_is_refused(self):
        for reply in ("没有", "<svg><rect></svg>", "<svg><!ENTITY a></svg>"):
            with self.assertRaises(CanvasToolError, msg=reply):
                canvas_tools.clean_svg(reply)
        # A doctype in front of the drawing is simply left behind.
        self.assertNotIn("ENTITY", canvas_tools.clean_svg('<!DOCTYPE svg [<!ENTITY a "b">]><svg></svg>'))

    def test_a_page_is_held_as_text_never_written_where_it_could_be_served(self):
        before = set(Path(self.media.name).iterdir())
        _, output = self.write("html_page", "好的：```html\n<!doctype html><html><body>hi</body></html>\n```")
        self.assertEqual(output["text"], "<!doctype html><html><body>hi</body></html>")
        self.assertTrue(output["html"])
        self.assertEqual(set(Path(self.media.name).iterdir()), before)

    def test_a_reply_with_no_page_is_refused(self):
        with self.assertRaises(CanvasToolError):
            canvas_tools.clean_html("<div>")


class CompositeTests(CanvasToolRunCase):
    def pictures(self):
        base = Image.new("RGB", (80, 60), (0, 0, 200))
        base.save(Path(self.media.name) / "base.png")
        still = Image.new("RGB", (160, 120), (200, 0, 0))
        still.save(Path(self.media.name) / "still.png")
        mask = Image.new("L", (160, 120), 0)
        mask.paste(255, (0, 0, 80, 120))
        mask.save(Path(self.media.name) / "mask.png")
        return [media_compositor.public_url(name) for name in ("base.png", "still.png", "mask.png")]

    def test_the_cast_lands_on_the_new_picture_whatever_the_order(self):
        base, still, mask = self.pictures()
        for order in ((base, still, mask), (mask, base, still), (still, mask, base)):
            nodes = [_media(f"m{i}", "image", url) for i, url in enumerate(order)] + [_tool("tool", "composite")]
            edges = [_edge(f"e{i}", f"m{i}", "tool", role="ref_image") for i in range(3)]
            saved = self.put(nodes, edges, expected=self.client.get(f"{self.base}/canvas").json()["version"])
            self.run_nodes(["tool"], saved["version"], op=f"op-{order.index(base)}")
            output = self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["tool"]
            with Image.open(self.local(output["url"])) as image:
                self.assertEqual(image.size, (80, 60))
                self.assertEqual(image.getpixel((10, 30)), (200, 0, 0))
                self.assertEqual(image.getpixel((70, 30)), (0, 0, 200))

    def test_without_a_mask_it_says_what_to_connect(self):
        base, still, _ = self.pictures()
        nodes = [_media("a", "image", base), _media("b", "image", still), _media("c", "image", base), _tool("tool", "composite")]
        saved = self.put(nodes, [_edge(f"e{i}", n, "tool", role="ref_image") for i, n in enumerate("abc")])
        self.run_nodes(["tool"], saved["version"])
        history = self.client.get(f"{self.base}/canvas/nodes/tool/history").json()["runs"]
        self.assertEqual(history[0]["status"], "failed")
        self.assertIn("遮罩", history[0]["error"])

    def test_a_previz_mask_may_feed_it_and_nothing_else(self):
        capture = {"kind": "still", "layer": "mask", "url": "/media/a.png"}
        allowed = studio_canvas.Inputs()
        studio_canvas._take_capture(allowed, capture, "s", {"kind": "tool", "payload": {"params": {"tool": "composite"}}})
        self.assertEqual(allowed.ref_images, ["/media/a.png"])
        refused = studio_canvas.Inputs()
        studio_canvas._take_capture(refused, capture, "s", {"kind": "tool", "payload": {"params": {"tool": "enhance"}}})
        self.assertEqual(refused.ref_images, [])


def _data_frame():
    import base64

    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), (120, 90, 60)).save(buffer, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


_DATA_FRAME = _data_frame()


class FrameRatioTests(CanvasToolRunCase):
    def bridge(self, first, last):
        nodes = [_media("first", "image", first), _media("last", "image", last), _node("clip", "video_gen", prompt="镜头缓缓下移", params={"model": "video-1"})]
        edges = [_edge("a", "first", "clip", role="first_frame"), _edge("b", "last", "clip", role="last_frame")]
        return self.run_nodes(["clip"], self.put(nodes, edges)["version"], confirm=True)

    def test_frames_of_different_shapes_stop_before_anything_is_spent(self):
        answer = self.bridge(self.picture("ratio-a.png", (90, 160)), self.picture("ratio-b.png", (160, 90)))
        problems = " ".join(item["message"] for node in answer["assessment"]["nodes"] for item in node["problems"])
        self.assertIn("比例不同", problems)
        self.assertFalse(self.gateway.video_calls)

    def test_frames_of_the_same_shape_pass_whatever_their_size(self):
        answer = self.bridge(self.picture("ratio-c.png", (90, 160)), self.picture("ratio-d.png", (180, 320)))
        self.assertEqual(answer["status"], "started", answer)

    def test_a_remote_frame_is_not_downloaded_to_check_it(self):
        self.assertEqual(studio_canvas_runs.frames_ratio_problem("https://cdn.test/a.png", "https://cdn.test/b.png"), "")


class ContinueFromTests(CanvasToolRunCase):
    """The second part of one continuous shot opens on the first part's last frame, explicitly, or not at all."""

    def chain(self, url, role="continue_from", extra_nodes=(), extra_edges=()):
        nodes = [_node("part1", "media", medium="video", output={"medium": "video", "url": url}, prompt="他冲到巷口。他在巷口停住，手撑着墙喘气"), _node("part2", "video_gen", prompt="接着跑出巷口"), *extra_nodes]
        edges = [_edge("e", "part1", "part2", role=role), *extra_edges]
        saved = self.put(nodes, edges)
        return self.run_nodes(["part2"], saved["version"], confirm=True)

    @unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_the_last_frame_is_read_from_the_clip_and_sent_as_the_first_frame(self):
        answer = self.chain(self.video())
        self.assertEqual(answer["status"], "started", answer)
        sent = self.gateway.video_calls[0]
        self.assertTrue(str(sent["first_frame"]).startswith("data:image/jpeg;base64,"))
        self.assertFalse(sent["ref_videos"])
        import base64
        import io

        with Image.open(io.BytesIO(base64.b64decode(sent["first_frame"].split(",", 1)[1]))) as frame:
            # The clip ends blue; its last frame has to be the blue one, not the red opening.
            self.assertGreater(frame.convert("RGB").getpixel((10, 10))[2], 150)
        self.assertTrue(sent["prompt"].startswith("本段是同一镜头的后半段"))
        # The words catch the ending the clip before was told to reach, then say what comes next.
        self.assertIn("接住上一段结尾：他在巷口停住，手撑着墙喘气。接下来：接着跑出巷口", sent["prompt"])

    def test_the_seam_is_checked_and_kept_with_the_result(self):
        with patch.object(media_compositor, "extract_last_frame_b64", return_value=_DATA_FRAME), \
             patch.object(media_compositor, "extract_first_frame_b64", return_value=_DATA_FRAME):
            answer = self.chain("/media/a.mp4")
        self.assertEqual(answer["status"], "started", answer)
        output = self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["part2"]
        self.assertEqual(output["seam"]["verdict"], "good")
        self.assertEqual(output["seam"]["label"], "接上了")

    def test_a_seam_check_that_cannot_run_costs_nothing(self):
        with patch.object(media_compositor, "extract_last_frame_b64", return_value=_DATA_FRAME), \
             patch.object(media_compositor, "extract_first_frame_b64", side_effect=OSError("boom")):
            answer = self.chain("/media/a.mp4")
        self.assertEqual(answer["status"], "started", answer)
        output = self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["part2"]
        self.assertNotIn("seam", output)

    def test_as_a_mere_reference_the_clip_is_not_a_first_frame(self):
        answer = self.chain("/media/a.mp4", role="ref_video")
        self.assertEqual(answer["status"], "started", answer)
        sent = self.gateway.video_calls[0]
        self.assertIsNone(sent["first_frame"])
        self.assertEqual(sent["ref_videos"], ["/media/a.mp4"])

    def test_a_clip_whose_frame_cannot_be_read_fails_instead_of_jumping(self):
        with patch.object(media_compositor, "extract_last_frame_b64", return_value=None):
            answer = self.chain("/media/gone.mp4")
        self.assertEqual(answer["status"], "started", answer)
        history = self.client.get(f"{self.base}/canvas/nodes/part2/history").json()["runs"]
        self.assertEqual(history[0]["status"], "failed")
        self.assertIn("尾帧", history[0]["error"])
        self.assertEqual(self.gateway.video_calls, [])

    def test_two_first_frames_are_refused_before_anything_is_spent(self):
        answer = self.chain(
            "/media/a.mp4", extra_nodes=[_media("img", "image", self.picture())], extra_edges=[_edge("f", "img", "part2", role="first_frame")],
        )
        self.assertEqual(answer["status"], "blocked")
        problems = " ".join(item["message"] for row in answer["assessment"]["nodes"] for item in row["problems"])
        self.assertIn("首帧只能有一个", problems)

    def test_the_canvas_accepts_the_role_only_for_a_clip_into_a_video(self):
        clip = {"id": "c", "kind": "media", "payload": {"medium": "video", "output": {"medium": "video", "url": "/media/a.mp4"}}}
        video = {"id": "v", "kind": "video_gen", "payload": {}}
        self.assertEqual(studio_canvas.connection(clip, video, role="continue_from"), ("reference", "continue_from"))
        with self.assertRaises(studio_canvas.CanvasOperationError):
            studio_canvas.connection(clip, {"id": "t", "kind": "tool", "payload": {"params": {"tool": "video_erase"}}}, role="continue_from")


class LastFrameTests(unittest.TestCase):
    @unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_it_is_the_very_last_frame_not_the_one_a_fifth_of_a_second_before(self):
        import base64
        import io

        with tempfile.TemporaryDirectory() as folder:
            clip = Path(folder) / "clip.mp4"
            # Red, then blue, then three green frames right at the end: only the true last frame is green.
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=1:r=24", "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=1:r=24",
                "-f", "lavfi", "-i", "color=c=lime:s=320x180:d=0.125:r=24", "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1[v]", "-map", "[v]",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
            ], check=True)
            with patch.object(media_compositor, "MEDIA_DIR", folder):
                uri = media_compositor.extract_last_frame_b64(str(clip))
        self.assertTrue(uri and uri.startswith("data:image/jpeg;base64,"))
        with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as frame:
            red, green, blue = frame.convert("RGB").getpixel((10, 10))
        self.assertGreater(green, 150)
        self.assertLess(blue, 100)
        self.assertLess(red, 100)

    @unittest.skipUnless(HAS_FFMPEG, "needs ffmpeg")
    def test_a_large_clip_is_handed_over_at_a_size_a_model_can_draw_from(self):
        import base64
        import io

        with tempfile.TemporaryDirectory() as folder:
            clip = Path(folder) / "big.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:d=0.5:r=24", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
            with patch.object(media_compositor, "MEDIA_DIR", folder):
                uri = media_compositor.extract_last_frame_b64(str(clip))
        with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as frame:
            self.assertEqual(frame.size, (1280, 720))


class CameraTemplateTests(CanvasToolRunCase):
    def nodes(self, **params):
        return [_media("img", "image", self.picture()), _node("v", "video_gen", prompt="车冲出巷口", params=params)], [_edge("e", "img", "v", role="first_frame")]

    def test_the_move_is_written_into_the_prompt_around_the_action(self):
        nodes, edges = self.nodes(cameraRecipe="tracking", cameraIntensity="strong")
        saved = self.put(nodes, edges)
        answer = self.run_nodes(["v"], saved["version"], confirm=True)
        self.assertIn(answer["status"], {"started", "needs_confirmation"}, answer)
        if answer["status"] == "started":
            prompt = self.gateway.video_calls[0]["prompt"]
            self.assertIn("车冲出巷口", prompt)
            self.assertNotEqual(prompt, "车冲出巷口")

    def test_an_unknown_template_blocks_the_run(self):
        nodes, edges = self.nodes(cameraRecipe="nope")
        saved = self.put(nodes, edges)
        answer = self.run_nodes(["v"], saved["version"])
        self.assertEqual(answer["status"], "blocked")

    def test_options_offer_the_templates(self):
        self.assertTrue(self.client.get(f"{self.base}/canvas/run-options").json()["camera_recipes"])


class OptionsTests(CanvasToolRunCase):
    def test_options_offer_the_style_wall_and_say_what_is_available(self):
        options = self.client.get(f"{self.base}/canvas/run-options").json()
        self.assertEqual(len(options["tools"]["styles"]), 45)
        self.assertEqual(set(options["tools"]["engines"]), {"image", "vision", "text", "local", "voice"})


if __name__ == "__main__":
    unittest.main()

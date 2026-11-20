# -*- coding: utf-8 -*-
"""Cropping a node's picture and cutting it into a grid, on the canvas (app/service/canvas_image_ops.py).

No provider and no network: the canvas's media directory is a temp directory, pictures are made
here with PIL, and the runs go to the stub gateway.

What is pinned. A crop writes one new file of exactly the cropped pixels and adds exactly one media
node in one canvas version; a split of R × C adds R * C nodes whose files tile the picture, laid out
as the grid they came from. The pieces sit beside the source and cover nothing; a media node takes
no input, so there is no edge and the piece says where it came from instead. A node with no picture,
a rectangle outside the picture, 1 × 1 or more than 12, somebody else's project and a private
element path are refused, and a refusal leaves no node, no version and no file behind. A node with
several generations is cut from the one it currently shows.
"""

import io
import os
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.api import element_api
from app.core import media_compositor, prompt_data, studio_canvas
from app.repository.studio_repo import ConcurrencyError
from app.service import canvas_image_ops
from tests.test_canvas_workspace import CanvasCase, _node

RED, GREEN, BLUE, WHITE = (200, 30, 30), (30, 200, 30), (30, 30, 200), (240, 240, 240)


def _words(key: str, **names) -> str:
    return prompt_data.text("canvas_image_ops", key).format(**names)


def _quadrants(width=40, height=20) -> bytes:
    """Red top-left, green top-right, blue bottom-left, white bottom-right."""
    image = Image.new("RGB", (width, height), WHITE)
    image.paste(RED, (0, 0, width // 2, height // 2))
    image.paste(GREEN, (width // 2, 0, width, height // 2))
    image.paste(BLUE, (0, height // 2, width // 2, height))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _plain(colour, size) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _placed(node, x, y, width=260, height=200):
    return {**node, "x": x, "y": y, "width": width, "height": height}


class ImageOpsCase(CanvasCase):
    def setUp(self):
        super().setUp()
        self.media = Path(self.temp.name) / "media"
        self.media.mkdir()
        for target, value in (
            (media_compositor, {"MEDIA_DIR": str(self.media)}),
            (element_api, {"LEGACY_ELEMENT_MEDIA_ROOT": self.media / "elements"}),
        ):
            patcher = patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def crop(self, node_id, **body):
        return self.client.post(f"{self.base}/canvas/nodes/{node_id}/crop", json=body)

    def split(self, node_id, **body):
        return self.client.post(f"{self.base}/canvas/nodes/{node_id}/grid-split", json=body)

    def canvas(self):
        return self.client.get(f"{self.base}/canvas").json()

    def versions(self):
        return [item["version"] for item in self.client.get(f"{self.base}/canvas/versions").json()["versions"]]

    def pieces(self):
        prefixes = (prompt_data.text("canvas_image_ops", "crop_prefix"), prompt_data.text("canvas_image_ops", "cell_prefix"))
        return sorted(name for name in os.listdir(self.media) if name.startswith(prefixes))

    def picture(self, url) -> Image.Image:
        path = media_compositor.local_media_path(url)
        self.assertTrue(path, f"not a file of this canvas's media storage: {url}")
        self.assertEqual(Path(path).parent, self.media.resolve())
        with Image.open(path) as image:
            return image.convert("RGB")

    def assert_no_overlap(self, nodes):
        boxes = [(node["x"], node["y"], node["width"], node["height"]) for node in nodes if node["kind"] != "group"]
        for index, (x, y, width, height) in enumerate(boxes):
            for other_x, other_y, other_width, other_height in boxes[index + 1:]:
                self.assertTrue(
                    x + width <= other_x or other_x + other_width <= x or y + height <= other_y or other_y + other_height <= y,
                    f"{(x, y, width, height)} covers {(other_x, other_y, other_width, other_height)}",
                )


class CropTests(ImageOpsCase):
    def test_a_crop_is_one_new_media_node_holding_exactly_those_pixels_in_one_version(self):
        (self.media / "board.png").write_bytes(_quadrants())
        self.put([
            _placed(_node("pic", "media", label="雨街", output={"medium": "image", "url": "/media/board.png"}), 100, 50),
            # Right where a piece would otherwise go.
            _placed(_node("words", "note", text="雨夜"), 420, 60, 240, 150),
        ])
        done = self.crop("pic", x=0.5, y=0, w=0.5, h=0.5, expected_version=1)
        self.assertEqual(done.status_code, 200, done.text)
        body = done.json()
        self.assertEqual((body["version"], body["source_node_id"], body["connected"]), (2, "pic", False))
        self.assertEqual((body["width"], body["height"]), (20, 10))
        self.assertEqual(self.versions(), [2, 1], "one crop, one canvas version")

        canvas = self.canvas()
        self.assertEqual(len(canvas["nodes"]), 3, "exactly one node was added")
        self.assertEqual(canvas["edges"], [], "a media node takes no input: no edge is forced")
        made = next(node for node in canvas["nodes"] if node["id"] == body["node_ids"][0])
        self.assertEqual(len(body["node_ids"]), 1)
        self.assertEqual((made["kind"], made["payload"]["label"]), ("media", _words("crop_label", label="雨街")))
        output = made["payload"]["output"]
        self.assertEqual(output["medium"], "image")
        # Where it came from is on the piece itself.
        self.assertEqual(output["source"], {"node_id": "pic", "crop": {"x": 0.5, "y": 0.0, "w": 0.5, "h": 0.5}})
        self.assertTrue(studio_canvas.safe_media_url(output["url"]), "a run may hand this to a provider")
        piece = self.picture(output["url"])
        self.assertEqual(piece.size, (20, 10))
        self.assertEqual({piece.getpixel((0, 0)), piece.getpixel((19, 9))}, {GREEN}, "the top-right quarter, nothing else")
        self.assertEqual(len(self.pieces()), 1)
        # Beside the source, on its right, level with it, and covering nothing.
        self.assertGreaterEqual(made["x"], 100 + 260)
        self.assertEqual(made["y"], 50)
        self.assert_no_overlap(canvas["nodes"])
        self.assertGreaterEqual(made["x"], 420 + 240, "moved past the note that was in the way")
        # The source is untouched.
        self.assertEqual(self.picture("/media/board.png").size, (40, 20))

    def test_the_card_takes_the_shape_of_the_piece(self):
        (self.media / "board.png").write_bytes(_quadrants(60, 60))
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/board.png"})])
        tall = self.crop("pic", x=0, y=0, w=0.25, h=1).json()
        wide = self.crop("pic", x=0, y=0, w=1, h=0.25).json()
        nodes = {node["id"]: node for node in self.canvas()["nodes"]}
        first, second = nodes[tall["node_ids"][0]], nodes[wide["node_ids"][0]]
        self.assertGreater(first["height"], first["width"])
        self.assertGreater(second["width"], second["height"])
        self.assert_no_overlap(nodes.values())
        self.assertEqual(self.versions(), [3, 2, 1])

    def test_a_generated_picture_is_cropped_from_the_generation_the_node_shows(self):
        # One run asked for two results: two run records of one node. The crop is of the active one, whichever that is.
        saved = self.put([_node("img", "image_gen", prompt="雨夜老宅", label="老宅", params={"count": 2})])
        self.run_nodes(["img"], saved["version"])
        (self.media / "image_1.png").write_bytes(_plain(RED, (30, 20)))
        (self.media / "image_2.png").write_bytes(_plain(BLUE, (50, 40)))
        sizes = {"/media/image_1.png": ((30, 20), RED), "/media/image_2.png": ((50, 40), BLUE)}

        shown = self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["img"]
        done = self.crop("img", x=0, y=0, w=1, h=0.5)
        self.assertEqual(done.status_code, 200, done.text)
        nodes = {node["id"]: node for node in self.canvas()["nodes"]}
        output = nodes[done.json()["node_ids"][0]]["payload"]["output"]
        (width, height), colour = sizes[shown["url"]]
        piece = self.picture(output["url"])
        self.assertEqual((piece.size, piece.getpixel((0, 0))), ((width, height // 2), colour))
        self.assertEqual(output["source"]["run_id"], shown["run_id"], "which generation it was cut from")

        # Bring the other generation back: the next crop is of that one.
        history = self.client.get(f"{self.base}/canvas/nodes/img/history").json()
        self.assertEqual(len(history["runs"]), 2)
        other = next(run for run in history["runs"] if run["id"] != history["active_run_id"])
        restored = self.client.post(f"{self.base}/canvas/nodes/img/history/{other['id']}/restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        again = self.crop("img", x=0, y=0, w=1, h=0.5)
        self.assertEqual(again.status_code, 200, again.text)
        nodes = {node["id"]: node for node in self.canvas()["nodes"]}
        second = nodes[again.json()["node_ids"][0]]["payload"]["output"]
        (width, height), colour = sizes[other["output"]["url"]]
        piece = self.picture(second["url"])
        self.assertEqual((piece.size, piece.getpixel((0, 0))), ((width, height // 2), colour))
        self.assertEqual(second["source"]["run_id"], other["id"])
        self.assertNotEqual(second["source"]["run_id"], output["source"]["run_id"])

    def test_a_rectangle_that_is_not_inside_the_picture_or_is_too_small_is_refused(self):
        (self.media / "board.png").write_bytes(_quadrants())
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/board.png"})])
        outside = (
            {"x": 0.6, "y": 0, "w": 0.5, "h": 0.5}, {"x": 0, "y": 0.7, "w": 0.5, "h": 0.5}, {"x": -0.1, "y": 0, "w": 0.5, "h": 0.5},
            {"x": 0, "y": 0, "w": 0, "h": 0.5}, {"x": 0, "y": 0, "w": 0.5, "h": -0.2}, {"x": 0, "y": 0, "w": 1.2, "h": 1},
        )
        for rect in outside:
            refused = self.crop("pic", **rect)
            self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("bad_rect")), rect)
        for rect in ({"x": 0, "y": 0, "w": 0.05, "h": 0.5}, {"x": 0.2, "y": 0.2, "w": 0.5, "h": 0.01}):
            refused = self.crop("pic", **rect)
            self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("rect_too_small", percent=6)), rect)
        self.assertEqual(self.crop("pic", x=0, y=0, w=0.5).status_code, 422, "a rectangle has four numbers")
        self.assertEqual((self.versions(), self.pieces(), len(self.canvas()["nodes"])), ([1], [], 1))
        # The smallest rectangle allowed is allowed.
        self.assertEqual(self.crop("pic", x=0, y=0, w=0.06, h=0.06).status_code, 200)

    def test_a_node_with_no_picture_is_refused(self):
        (self.media / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 40)
        (self.media / "note.txt").write_bytes(b"not a picture")
        self.put([
            _node("words", "note", text="雨夜"),
            _node("img", "image_gen", prompt="还没运行过"),
            _node("clip", "media", output={"medium": "video", "url": "/media/clip.mp4"}),
            _node("empty", "media", label="还没传"),
            _node("gone", "media", output={"medium": "image", "url": "/media/gone.png"}),
            _node("fake", "media", output={"medium": "image", "url": "/media/note.txt"}),
        ])
        whole = {"x": 0, "y": 0, "w": 0.5, "h": 0.5}
        for node_id in ("words", "img", "clip", "empty"):
            for refused in (self.crop(node_id, **whole), self.split(node_id, rows=2, columns=2)):
                self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("node_no_image")), node_id)
        for refused in (self.crop("nowhere", **whole), self.split("nowhere")):
            self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("node_missing")))
        for refused in (self.crop("gone", **whole), self.split("gone")):
            self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("result_unreadable")))
        self.assertEqual(self.crop("fake", **whole).status_code, 422, "what a picture is, is checked before it is opened")
        self.assertEqual(self.split("fake").status_code, 422)
        self.assertEqual((self.versions(), self.pieces(), len(self.canvas()["nodes"])), ([1], [], 6))

    def test_a_private_element_path_is_refused(self):
        # Old installations kept element pictures under /media/elements: private, and not this canvas's to cut up.
        (self.media / "elements" / "someone").mkdir(parents=True)
        (self.media / "elements" / "someone" / "face.png").write_bytes(_quadrants())
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/elements/someone/face.png"})])
        for refused in (self.crop("pic", x=0, y=0, w=0.5, h=0.5), self.split("pic", rows=2, columns=2)):
            self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("result_private")))
        self.assertEqual((self.versions(), self.pieces(), len(self.canvas()["nodes"])), ([1], [], 1))

    def test_another_persons_project_is_not_a_way_in(self):
        (self.media / "board.png").write_bytes(_quadrants())
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/board.png"})])
        self.user = {"user_id": "intruder", "role": "user"}
        self.assertEqual(self.crop("pic", x=0, y=0, w=0.5, h=0.5).status_code, 404)
        self.assertEqual(self.split("pic", rows=2, columns=2).status_code, 404)
        self.user = {"user_id": "u1", "role": "user"}
        self.assertEqual((self.versions(), self.pieces(), len(self.canvas()["nodes"])), ([1], [], 1))

    def test_a_stale_version_adds_nothing_and_leaves_no_file(self):
        (self.media / "board.png").write_bytes(_quadrants())
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/board.png"})])
        self.assertEqual(self.crop("pic", x=0, y=0, w=0.5, h=0.5, expected_version=0).status_code, 409)
        self.assertEqual(self.split("pic", rows=2, columns=2, expected_version=0).status_code, 409)
        self.assertEqual((self.versions(), self.pieces()), ([1], []))
        # The canvas moved on between the cutting and the write: the files made for it are removed again.
        with patch.object(self.studio, "edit_canvas", side_effect=ConcurrencyError("canvas version conflict: expected 1, latest is 2")):
            self.assertEqual(self.crop("pic", x=0, y=0, w=0.5, h=0.5, expected_version=1).status_code, 409)
            self.assertEqual(self.split("pic", rows=3, columns=3, expected_version=1).status_code, 409)
        self.assertEqual((self.versions(), self.pieces(), len(self.canvas()["nodes"])), ([1], [], 1))


class GridSplitTests(ImageOpsCase):
    def test_rows_by_columns_cells_become_that_many_media_nodes_in_one_version(self):
        (self.media / "board.png").write_bytes(_quadrants(40, 20))
        self.put([
            _placed(_node("pic", "media", label="九宫格", output={"medium": "image", "url": "/media/board.png"}), 0, 0),
            _placed(_node("words", "note", text="挡路的"), 320, 100, 240, 150),
        ])
        done = self.split("pic", rows=2, columns=2, expected_version=1)
        self.assertEqual(done.status_code, 200, done.text)
        body = done.json()
        self.assertEqual((body["version"], body["rows"], body["columns"], body["connected"]), (2, 2, 2, False))
        self.assertEqual(len(body["node_ids"]), 4)
        self.assertEqual(self.versions(), [2, 1], "four cells, one canvas version")
        canvas = self.canvas()
        self.assertEqual((len(canvas["nodes"]), canvas["edges"]), (6, []))
        nodes = {node["id"]: node for node in canvas["nodes"]}
        cells = [nodes[node_id] for node_id in body["node_ids"]]
        # Left to right, top to bottom; each file is its own quarter.
        self.assertEqual([self.picture(cell["payload"]["output"]["url"]).getpixel((0, 0)) for cell in cells], [RED, GREEN, BLUE, WHITE])
        self.assertTrue(all(self.picture(cell["payload"]["output"]["url"]).size == (20, 10) for cell in cells))
        self.assertEqual([cell["payload"]["label"] for cell in cells], [_words("cell_label", label="九宫格", row=row, column=column) for row in (1, 2) for column in (1, 2)])
        self.assertEqual(
            [cell["payload"]["output"]["source"] for cell in cells],
            [{"node_id": "pic", "grid": {"rows": 2, "columns": 2, "row": row, "column": column}} for row in (1, 2) for column in (1, 2)],
        )
        self.assertEqual(len(self.pieces()), 4)
        # Laid out as the grid they came from, beside the source, covering nothing.
        (a, b), (c, d) = cells[:2], cells[2:]
        self.assertEqual((a["y"], c["y"], a["x"], b["x"]), (b["y"], d["y"], c["x"], d["x"]))
        self.assertLess(a["x"], b["x"])
        self.assertLess(a["y"], c["y"])
        self.assertEqual(a["y"], 0)
        self.assertEqual(len({(cell["width"], cell["height"]) for cell in cells}), 1)
        self.assert_no_overlap(canvas["nodes"])
        self.assertGreaterEqual(a["x"], 320 + 240, "the whole grid moved past the note that was in the way")

    def test_cells_tile_a_picture_that_does_not_divide_evenly(self):
        (self.media / "odd.png").write_bytes(_plain(GREEN, (31, 20)))
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/odd.png"})])
        done = self.split("pic", rows=3, columns=3)
        self.assertEqual(done.status_code, 200, done.text)
        nodes = {node["id"]: node for node in self.canvas()["nodes"]}
        sizes = [self.picture(nodes[node_id]["payload"]["output"]["url"]).size for node_id in done.json()["node_ids"]]
        self.assertEqual(len(sizes), 9)
        self.assertEqual([width for width, _ in sizes[:3]], [10, 10, 11])
        self.assertEqual([height for _, height in sizes[::3]], [6, 7, 7])
        self.assertEqual((sum(width for width, _ in sizes[:3]), sum(height for _, height in sizes[::3])), (31, 20), "no pixel lost, none twice")

    def test_a_generated_picture_can_be_split_and_the_default_is_two_by_two(self):
        saved = self.put([_node("img", "image_gen", prompt="四宫格分镜")])
        self.run_nodes(["img"], saved["version"])
        (self.media / "image_1.png").write_bytes(_quadrants())
        done = self.split("img")
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual((done.json()["rows"], done.json()["columns"], len(done.json()["node_ids"])), (2, 2, 4))
        nodes = {node["id"]: node for node in self.canvas()["nodes"]}
        self.assertTrue(all(nodes[node_id]["payload"]["output"]["source"]["run_id"] for node_id in done.json()["node_ids"]))

    def test_one_by_one_and_out_of_range_counts_are_refused(self):
        (self.media / "board.png").write_bytes(_quadrants())
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/board.png"})])
        single = self.split("pic", rows=1, columns=1)
        self.assertEqual((single.status_code, single.json()["detail"]), (422, _words("single_cell")))
        for rows, columns in ((13, 2), (2, 13), (0, 2), (2, 0), (-1, 3)):
            refused = self.split("pic", rows=rows, columns=columns)
            self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("bad_grid", max=12)), (rows, columns))
        # More cells one way than the picture has pixels.
        (self.media / "thin.png").write_bytes(_plain(RED, (40, 4)))
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/thin.png"})], expected=1)
        thin = self.split("pic", rows=8, columns=2)
        self.assertEqual((thin.status_code, thin.json()["detail"]), (422, _words("cell_too_small", width=40, height=4, rows=8, columns=2)))
        self.assertEqual((self.versions(), self.pieces(), len(self.canvas()["nodes"])), ([2, 1], [], 1))
        # A single row or a single column is a split.
        self.assertEqual(len(self.split("pic", rows=1, columns=12).json()["node_ids"]), 12)

    def test_a_split_that_would_overfill_the_canvas_adds_nothing(self):
        (self.media / "board.png").write_bytes(_quadrants())
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/board.png"})])
        with patch.object(canvas_image_ops, "CANVAS_MAX_NODES", 4):
            refused = self.split("pic", rows=2, columns=2)
            self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("too_many_nodes", limit=4, count=4)))
            self.assertEqual(self.split("pic", rows=1, columns=3).status_code, 200)
        self.assertEqual(len(self.pieces()), 3)


class SourceNoteTests(ImageOpsCase):
    def test_the_edit_operation_keeps_the_note_of_what_a_file_was_cut_from_and_nothing_else(self):
        def held(source):
            document, _ = studio_canvas.apply_operations({"nodes": [], "edges": []}, [{
                "op": "add_node", "kind": "media", "output": {"medium": "image", "url": "/media/a.png", "source": source},
            }])
            return document["nodes"][0]["payload"]["output"]

        kept = held({"node_id": " n1 ", "run_id": "r9", "secret": "x", "url": "/media/elements/private.png", "crop": {"x": "0.25", "y": 0, "w": 0.5, "h": 1, "z": 3}})
        self.assertEqual(kept["source"], {"node_id": "n1", "run_id": "r9", "crop": {"x": 0.25, "y": 0.0, "w": 0.5, "h": 1.0}})
        self.assertEqual(held({"node_id": "n1", "grid": {"rows": 2, "columns": 3, "row": 1, "column": 2.0}})["source"], {"node_id": "n1", "grid": {"rows": 2, "columns": 3, "row": 1, "column": 2}})
        # Half a rectangle, or numbers that are not numbers, are not a rectangle.
        self.assertEqual(held({"node_id": "n1", "crop": {"x": 0, "y": 0}, "grid": {"rows": "two", "columns": 2, "row": 1, "column": 1}})["source"], {"node_id": "n1"})
        self.assertEqual(held({"node_id": "n1", "crop": {"x": float("nan"), "y": 0, "w": 1, "h": 1}})["source"], {"node_id": "n1"})
        self.assertNotIn("source", held({"crop": {"x": 0, "y": 0, "w": 1, "h": 1}}), "no node named, nothing to note")
        self.assertNotIn("source", held("n1"))

    def test_a_media_node_still_takes_no_input(self):
        # The reason a piece is not wired to its source: the connection table has no input for a media node.
        source = _node("pic", "media", output={"medium": "image", "url": "/media/a.png"})
        piece = _node("piece", "media", output={"medium": "image", "url": "/media/b.png"})
        with self.assertRaises(studio_canvas.CanvasOperationError):
            studio_canvas.connection(source, piece)

# -*- coding: utf-8 -*-
"""A canvas with its media as one zip: what is packed, what is left out, and how an import checks every file.

No network, no model. Media live in a temporary media folder; the import stores through a stand-in for
the canvas upload, and through the real ``StudioService.store_canvas_upload`` in the end-to-end case.
"""

import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.core import media_compositor, prompt_data
from app.service import canvas_bundle
from tests.test_canvas_workspace import CanvasCase, _node


def _png(colour=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), colour).save(buffer, format="PNG")
    return buffer.getvalue()


class _Media(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        media = patch.object(media_compositor, "MEDIA_DIR", self.temp.name)
        media.start()
        self.addCleanup(media.stop)

    def file(self, name: str, content: bytes) -> str:
        Path(self.temp.name, name).write_bytes(content)
        return f"/media/{name}"

    @staticmethod
    def entries(data: bytes) -> dict[str, bytes]:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return {info.filename: archive.read(info) for info in archive.infolist()}


class ExportTests(_Media):
    def test_the_board_and_the_files_it_shows_are_packed_once_each(self):
        picture = _png()
        a = self.file("canvas_up_a.png", picture)
        same = self.file("canvas_up_same.png", picture)
        clip = self.file("canvas_up_c.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
        document = {
            "nodes": [
                _node("m1", "media", label="一", output={"medium": "image", "url": a}),
                _node("m2", "media", label="二", output={"medium": "image", "url": same}),
                _node("v1", "video_gen", label="视频", prompt="走"),
                _node("x", "media", label="外站", output={"medium": "image", "url": "https://cdn.example/x.png"}),
                _node("p", "media", label="私有", output={"medium": "image", "url": "/media/elements/u1/secret.png"}),
            ],
            "edges": [{"id": "e1", "source": "m1", "target": "v1", "kind": "reference", "payload": {"role": "first_frame"}}],
        }
        name, data, counts = canvas_bundle.export_bundle(document, {"v1": {"run_id": "r1", "medium": "video", "url": clip}}, title="雨夜/来信")
        self.assertEqual(name, "雨夜 来信.novara-canvas.zip")
        self.assertEqual(counts, {"files": 2, "private": 1, "missing": 0}, "two identical pictures are one file")
        files = self.entries(data)
        manifest = json.loads(files.pop(prompt_data.text("canvas_bundle", "manifest_name")))
        self.assertEqual(len(files), 2)
        self.assertTrue(all(key.startswith("media/") for key in files))
        self.assertIn(picture, files.values())
        self.assertEqual((manifest["format"], manifest["version"]), ("novara-canvas", 2))
        by_id = {node["id"]: node for node in manifest["nodes"]}
        self.assertTrue(by_id["m1"]["payload"]["output"]["url"].startswith(canvas_bundle.REF_PREFIX))
        self.assertEqual(by_id["m1"]["payload"]["output"]["url"], by_id["m2"]["payload"]["output"]["url"])
        self.assertEqual(by_id["v1"]["payload"]["output"], {"medium": "video", "url": by_id["v1"]["payload"]["output"]["url"]}, "the current result travels, without its run id")
        self.assertTrue(by_id["v1"]["payload"]["output"]["url"].endswith(".mp4"))
        self.assertEqual(by_id["x"]["payload"]["output"]["url"], "https://cdn.example/x.png", "a link to another host stays a link")
        self.assertEqual(by_id["p"]["payload"]["output"]["url"], "", "a private element file never leaves")
        self.assertEqual(manifest["edges"][0]["payload"]["role"], "first_frame")

    def test_an_empty_board_and_an_oversized_one_are_refused_in_words(self):
        with self.assertRaisesRegex(canvas_bundle.BundleError, "没有可导出"):
            canvas_bundle.export_bundle({"nodes": [], "edges": []}, {}, title="空")
        nodes = [_node(f"m{i}", "media", output={"medium": "image", "url": self.file(f"canvas_up_{i}.png", _png((i, i, i)))}) for i in range(3)]
        limits = {**prompt_data.value("canvas_bundle", "limits"), "max_files": 2}
        with patch.object(canvas_bundle, "_limit", side_effect=lambda name: limits[name]):
            with self.assertRaisesRegex(canvas_bundle.BundleError, "2"):
                canvas_bundle.export_bundle({"nodes": nodes, "edges": []}, {}, title="多")


class ImportTests(_Media):
    def bundle(self, files: dict[str, bytes], manifest: dict | None = None) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            if manifest is not None:
                archive.writestr("canvas.json", json.dumps(manifest))
            for name, content in files.items():
                archive.writestr(name, content)
        return buffer.getvalue()

    def test_every_file_is_stored_through_the_upload_check_and_the_links_rewritten(self):
        stored = []

        def store(name, content_type, content):
            stored.append((name, content_type, len(content)))
            if content_type == "video/mp4":
                raise ValueError("这个视频文件没通过检查")
            return {"url": f"/media/canvas_up_new_{len(stored)}.png"}

        ref = canvas_bundle.REF_PREFIX
        manifest = {"format": "novara-canvas", "version": 2, "title": "带素材", "nodes": [
            _node("a", "media", output={"medium": "image", "url": f"{ref}{'a' * 32}.png"}),
            _node("b", "media", output={"medium": "image", "url": f"{ref}{'a' * 32}.png"}),
            _node("c", "media", output={"medium": "video", "url": f"{ref}{'c' * 32}.mp4"}),
            _node("d", "media", output={"medium": "image", "url": f"{ref}{'d' * 32}.png"}),
        ], "edges": []}
        data = self.bundle({f"media/{'a' * 32}.png": _png(), f"media/{'c' * 32}.mp4": b"not a video"}, manifest)
        plain, report = canvas_bundle.import_bundle(data, store)
        self.assertEqual((plain["format"], plain["version"], plain["title"]), ("novara-canvas", 1, "带素材"))
        urls = [node["payload"]["output"]["url"] for node in plain["nodes"]]
        self.assertEqual(urls, ["/media/canvas_up_new_1.png", "/media/canvas_up_new_1.png", "", ""])
        self.assertEqual(stored[0][:2], ("a" * 32 + ".png", "image/png"))
        self.assertEqual(len(stored), 2, "a file used twice is stored once")
        self.assertEqual((report["files"], report["missing"]), (1, 1))
        self.assertEqual(report["failed"], [{"name": "c" * 32 + ".mp4", "reason": "这个视频文件没通过检查"}])

    def test_what_is_not_a_bundle_is_refused_before_anything_is_stored(self):
        never = lambda *args: self.fail("nothing may be stored")  # noqa: E731
        cases = {
            "not_zip": b"plain text",
            "no_manifest": self.bundle({f"media/{'a' * 32}.png": _png()}),
            "bad_entry": self.bundle({"../../etc/passwd": b"x"}, {"format": "novara-canvas", "nodes": []}),
            "bad_manifest": self.bundle({}, {"format": "something-else", "nodes": []}),
        }
        for key, data in cases.items():
            with self.subTest(key=key), self.assertRaises(canvas_bundle.BundleError) as raised:
                canvas_bundle.import_bundle(data, never)
            self.assertEqual(str(raised.exception).split("「")[0], prompt_data.text("canvas_bundle", key).split("「")[0])

    def test_an_entry_larger_than_it_claims_is_cut_off(self):
        limits = {**prompt_data.value("canvas_bundle", "limits"), "max_entry_bytes": 100}
        manifest = {"format": "novara-canvas", "nodes": [_node("a", "media", output={"medium": "image", "url": f"{canvas_bundle.REF_PREFIX}{'a' * 32}.png"})]}
        data = self.bundle({f"media/{'a' * 32}.png": _png() + b"\x00" * 500}, manifest)
        with patch.object(canvas_bundle, "_limit", side_effect=lambda name: limits[name]):
            plain, report = canvas_bundle.import_bundle(data, lambda *args: {"url": "/media/x.png"})
        self.assertEqual(plain["nodes"][0]["payload"]["output"]["url"], "")
        self.assertEqual(len(report["failed"]), 1, "refused by the size cap, not by what the header claimed")
        self.assertEqual(report["files"], 0)


class RoundTripTests(CanvasCase):
    def test_a_board_exported_with_its_media_comes_back_with_new_copies(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        with patch.object(media_compositor, "MEDIA_DIR", media.name):
            Path(media.name, "canvas_up_src.png").write_bytes(_png((200, 10, 10)))
            self.put([_node("m1", "media", label="首帧", output={"medium": "image", "url": "/media/canvas_up_src.png"})])
            canvas = self.studio.repository.get_canvas(self.project, "u1")
            _, data, counts = canvas_bundle.export_bundle(canvas.model_dump(mode="json"), {}, title="往返")
            self.assertEqual(counts["files"], 1)
            plain, report = canvas_bundle.import_bundle(
                data, lambda name, content_type, content: self.studio.store_canvas_upload(self.project, "u1", name, content_type, content),
            )
            url = plain["nodes"][0]["payload"]["output"]["url"]
            self.assertEqual(report["files"], 1)
            self.assertNotEqual(url, "/media/canvas_up_src.png")
            self.assertTrue(os.path.exists(media_compositor.local_media_path(url)))
            self.assertEqual(Path(media_compositor.local_media_path(url)).read_bytes(), Path(media.name, "canvas_up_src.png").read_bytes())


if __name__ == "__main__":
    unittest.main()

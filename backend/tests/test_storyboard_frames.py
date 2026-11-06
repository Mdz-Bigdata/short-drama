# -*- coding: utf-8 -*-
"""分镜帧落地：签名链接会失效，分镜图存本地；发给供应商前读成内嵌图；看板能切回原格。"""

import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.core import media_compositor, storyboard_assets
from app.core.storyboard_assets import compose_nine_grid, cut_grid_panels, persist_storyboard_frame


def _png(color=(200, 30, 30), size=(90, 160)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class PersistFrameTests(unittest.TestCase):
    def test_a_provider_image_is_saved_as_a_local_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storyboard_assets, "_download_image", return_value=_png()):
            saved = persist_storyboard_frame("https://ark.example/frame.png?X-Tos-Expires=86400", directory, "t1_E1S01_1_abc")
            self.assertEqual(saved, Path(directory).resolve() / "t1_E1S01_1_abc.png")
            self.assertTrue(saved.read_bytes().startswith(b"\x89PNG"))

    def test_a_failed_download_keeps_the_remote_link(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storyboard_assets, "_download_image", side_effect=ValueError("no")):
            self.assertIsNone(persist_storyboard_frame("https://ark.example/frame.png", directory, "x"))
        self.assertIsNone(persist_storyboard_frame("data:image/png;base64,AAAA", "/tmp", "x"))


class InlineLocalImageTests(unittest.TestCase):
    def test_local_media_is_inlined_and_other_urls_pass_through(self):
        with tempfile.TemporaryDirectory() as media:
            frame = Path(media) / "storyboards" / "frames" / "f.png"
            frame.parent.mkdir(parents=True)
            frame.write_bytes(_png())
            with patch.object(media_compositor, "MEDIA_DIR", media), patch.object(media_compositor, "PUBLIC_BASE_URL", "http://localhost:8000/media"):
                inlined = media_compositor.inline_local_image("http://localhost:8000/media/storyboards/frames/f.png")
                self.assertTrue(str(inlined).startswith("data:image/png;base64,"))
                self.assertEqual(base64.b64decode(str(inlined).split(",", 1)[1])[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(media_compositor.inline_local_image("/media/storyboards/frames/f.png")[:15], "data:image/png;")
                remote = "https://ark.example/frame.png"
                self.assertEqual(media_compositor.inline_local_image(remote), remote)
                self.assertEqual(media_compositor.inline_local_image("http://localhost:8000/media/missing.png"), "http://localhost:8000/media/missing.png")
                self.assertIsNone(media_compositor.local_media_path("http://localhost:8000/media/../secrets.txt"))


class GridRecoveryTests(unittest.TestCase):
    def test_panels_cut_back_from_a_board_match_the_cells(self):
        colors = [(220, 20, 20), (20, 220, 20), (20, 20, 220)]
        with tempfile.TemporaryDirectory() as directory:
            sources = []
            for index, color in enumerate(colors):
                path = Path(directory) / f"{index}.png"
                path.write_bytes(_png(color, (356, 636)))
                sources.append(path)
            board = compose_nine_grid(sources, Path(directory) / "grid.png")
            panels = cut_grid_panels(board, 3)
        self.assertEqual([panel.size for panel in panels], [(356, 636)] * 3)
        for panel, color in zip(panels, colors):
            self.assertEqual(panel.getpixel((178, 318)), color)


class StageFourTests(unittest.TestCase):
    def test_stage_four_stores_local_frames_and_keeps_the_remote_link(self):
        from app.service.drama_service import DramaService
        from tests.test_spatial_stage_pipeline import _generate, _task

        service = DramaService()
        with tempfile.TemporaryDirectory() as media:
            saved_names = []

            def persist(url, directory, name):
                saved_names.append(name)
                path = Path(media) / "storyboards" / "frames" / f"{name}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(_png())
                return path

            with patch("app.service.drama_service.persist_storyboard_frame", side_effect=persist), \
                 patch.object(media_compositor, "MEDIA_DIR", media), patch.object(media_compositor, "PUBLIC_BASE_URL", "http://localhost:8000/media"):
                payload = _generate(service, _task(), "E1S01")
        shots = payload["shots"]
        self.assertTrue(all(str(shot["image_url"]).startswith("http://localhost:8000/media/storyboards/frames/") for shot in shots))
        self.assertTrue(all(str(shot["remote_image_url"]).startswith("http://img.test/") for shot in shots))
        self.assertTrue(all(name.startswith("spatial-_E1S01_") for name in saved_names))


if __name__ == "__main__":
    unittest.main()

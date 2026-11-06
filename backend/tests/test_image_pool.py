"""The image pool: cutting a grid with its borders trimmed, an index that can be rebuilt, and giving a cell to a shot."""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.api import drama_api, image_pool_api
from app.api.auth_api import get_current_user
from app.core import image_pool, media_compositor
from app.core.grid_split import split_grid
from app.core.storyboard_assets import compose_nine_grid
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService


def _textured(size, seed=0):
    """A busy picture, so nothing inside it reads as a seam."""
    image = Image.new("RGB", size, (40 + seed * 20 % 200, 90, 160))
    draw = ImageDraw.Draw(image)
    for step in range(0, size[0], 7):
        draw.line([(step, 0), (size[0] - step, size[1])], fill=((step * 3 + seed * 37) % 200 + 20, (step * 5) % 180 + 20, 60), width=3)
    return image


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _grid(rows, columns, *, cell=(160, 100), gutter=10, border=20, filled=None):
    width = border * 2 + columns * cell[0] + gutter * (columns - 1)
    height = border * 2 + rows * cell[1] + gutter * (rows - 1)
    page = Image.new("RGB", (width, height), "white")
    for index in range(filled if filled is not None else rows * columns):
        row, column = divmod(index, columns)
        page.paste(_textured(cell, index), (border + column * (cell[0] + gutter), border + row * (cell[1] + gutter)))
    return page


class SplitGridTests(unittest.TestCase):
    def test_borders_and_gutters_are_trimmed(self):
        cells = split_grid(_png(_grid(2, 3)), 2, 3)
        self.assertEqual([(cell.row, cell.column) for cell in cells], [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)])
        for cell in cells:
            width, height = cell.box[2] - cell.box[0], cell.box[3] - cell.box[1]
            self.assertLessEqual(abs(width - 160), 6, cell)
            self.assertLessEqual(abs(height - 100), 6, cell)
        with Image.open(io.BytesIO(cells[0].png)) as image:
            corner = image.convert("RGB").getpixel((0, 0))
        self.assertNotEqual(corner, (255, 255, 255))

    def test_a_page_with_no_seams_is_cut_evenly(self):
        cells = split_grid(_png(_textured((300, 200))), 2, 2)
        self.assertEqual([cell.box for cell in cells], [(0, 0, 150, 100), (150, 0, 300, 100), (0, 100, 150, 200), (150, 100, 300, 200)])

    def test_a_pale_edge_of_the_picture_itself_is_not_taken_for_a_border(self):
        page = _textured((300, 200))
        # A sky of soft grey-blue across the top of the whole page: smooth, but not a border.
        page.paste(Image.new("RGB", (300, 30), (170, 190, 215)), (0, 0))
        cells = split_grid(_png(page), 2, 2)
        self.assertEqual(cells[0].box[:2], (0, 0))
        self.assertEqual(cells[1].box[1], 0)

    def test_a_black_letterbox_is_trimmed(self):
        page = Image.new("RGB", (320, 240), "black")
        page.paste(_textured((320, 200)), (0, 20))
        cells = split_grid(_png(page), 1, 2)
        self.assertEqual((cells[0].box[1], cells[0].box[3]), (20, 220))

    def test_blank_cells_of_an_unfilled_page_are_dropped(self):
        cells = split_grid(_png(_grid(3, 3, filled=5)), 3, 3)
        self.assertEqual([(cell.row, cell.column) for cell in cells], [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)])

    def test_a_board_from_compose_nine_grid_comes_back_apart(self):
        with tempfile.TemporaryDirectory() as folder:
            sources = []
            for index in range(9):
                path = Path(folder) / f"{index}.png"
                _textured((356, 636), index).save(path)
                sources.append(path)
            board = compose_nine_grid(sources, Path(folder) / "board.png")
            cells = split_grid(board.read_bytes(), 3, 3)
        self.assertEqual(len(cells), 9)
        for cell in cells:
            self.assertLessEqual(abs(cell.box[2] - cell.box[0] - 356), 4)
            self.assertLessEqual(abs(cell.box[3] - cell.box[1] - 636), 4)

    def test_impossible_requests_are_refused(self):
        page = _png(_textured((64, 64)))
        for rows, columns, message in ((1, 1, "两格"), (9, 1, "1 到 8"), (0, 2, "1 到 8"), (8, 8, "切不出")):
            with self.assertRaisesRegex(ValueError, message):
                split_grid(page, rows, columns)
        with self.assertRaisesRegex(ValueError, "切不出有内容"):
            split_grid(_png(Image.new("RGB", (200, 200), "white")), 2, 2)


class ImagePoolRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "media"
        self.media.mkdir()
        for target, value in ((media_compositor, "MEDIA_DIR"),):
            patcher = patch.object(target, value, str(self.media))
            patcher.start()
            self.addCleanup(patcher.stop)
        base = "http://testserver/media"
        patcher = patch.object(media_compositor, "PUBLIC_BASE_URL", base)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.media / "board.png").write_bytes(_png(_grid(2, 2)))
        (self.media / "shot1.png").write_bytes(_png(_textured((64, 64))))
        self.board_url = f"{base}/board.png"
        self.shot_url = f"{base}/shot1.png"
        self.service = DramaService()
        self.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.task_id = "task-pool"
        self.service.repo.save_task(self.task_id, {
            "task_id": self.task_id, "owner_user_id": "u-1", "config": {}, "status": "idle",
            "assets": {
                "4": [{"shot_id": 1, "scene_id": "E1S01", "image_url": self.shot_url, "desc": "开场"}],
                "4_scene_boards": {"E1S01": {"grid_url": self.board_url}},
                "5": [{"shot_id": 1, "scene_id": "E1S01", "video_url": "http://x/v.mp4"}],
            },
        })
        patcher = patch.object(drama_api, "service", self.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(image_pool_api.router)
        app.dependency_overrides[drama_api.require_owned_drama_task] = lambda: {"user_id": "u-1", "role": "user"}
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u-1", "role": "user"}
        self.client = TestClient(app)
        self.base = f"/api/drama/{self.task_id}/image-pool"

    def _pool(self):
        return self.client.get(self.base).json()

    def _board_id(self):
        return next(image["id"] for image in self._pool()["images"] if image["kind"] == "board")

    def _split(self, **body):
        return self.client.post(f"{self.base}/split", json={"image_id": self._board_id(), "rows": 2, "columns": 2, **body})

    def test_a_project_that_never_used_the_pool_lists_what_it_generated(self):
        pool = self._pool()
        self.assertEqual(pool["revision"], 0)
        self.assertEqual({image["kind"] for image in pool["images"]}, {"shot", "board"})
        shot = next(image for image in pool["images"] if image["kind"] == "shot")
        self.assertEqual((shot["scene_id"], shot["shot_id"], shot["url"]), ("E1S01", 1, self.shot_url))
        self.assertNotIn(image_pool.POOL_KEY, self.service.repo.get_task(self.task_id)["assets"])

    def test_split_adds_cells_with_their_files_and_bumps_the_revision(self):
        response = self._split()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["revision"], 1)
        self.assertEqual(len(body["added"]), 4)
        cells = [image for image in body["images"] if image["kind"] == "cell"]
        self.assertEqual(len(cells), 4)
        self.assertEqual((cells[1]["row"], cells[1]["column"], cells[1]["grid"]), (0, 1, [2, 2]))
        self.assertEqual(cells[0]["parent_id"], self._board_id())
        self.assertTrue(media_compositor.local_media_path(cells[0]["url"]))
        with Image.open(media_compositor.local_media_path(cells[0]["url"])) as image:
            self.assertLessEqual(abs(image.size[0] - 160), 6)

    def test_cutting_the_same_way_twice_does_not_pile_up(self):
        self._split()
        self._split()
        self.assertEqual(sum(image["kind"] == "cell" for image in self._pool()["images"]), 4)

    def test_a_stale_revision_is_refused_and_writes_nothing(self):
        self._split(revision=0)
        stale = self._split(revision=0)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self._pool()["revision"], 1)
        self.assertEqual(self.client.post(f"{self.base}/rebuild", json={"revision": 0}).status_code, 409)

    def test_a_write_racing_past_the_first_check_is_still_caught(self):
        task = self.service.repo.get_task(self.task_id)
        task["assets"][image_pool.POOL_KEY] = {"version": 1, "revision": 5, "images": []}
        with self.assertRaises(image_pool.PoolConflict):
            image_pool.add_cells(task, [], expected_revision=4)

    def test_the_index_comes_back_from_what_is_on_disk(self):
        self._split()
        self.service.repo.mutate_task(self.task_id, lambda task: task["assets"].pop(image_pool.POOL_KEY))
        unindexed = self._pool()
        self.assertEqual(sum(image["kind"] == "cell" for image in unindexed["images"]), 4)
        rebuilt = self.client.post(f"{self.base}/rebuild", json={})
        self.assertEqual(rebuilt.status_code, 200, rebuilt.text)
        cells = [image for image in rebuilt.json()["images"] if image["kind"] == "cell"]
        self.assertEqual(len(cells), 4)
        self.assertEqual(rebuilt.json()["revision"], 1)
        self.assertEqual(cells[0]["parent_id"], self._board_id())
        self.assertIn("E1S01", cells[0]["label"])
        stored = self.service.repo.get_task(self.task_id)["assets"][image_pool.POOL_KEY]
        self.assertEqual(sum(image["kind"] == "cell" for image in stored["images"]), 4)

    def test_a_cell_whose_file_is_gone_is_not_offered(self):
        body = self._split().json()
        cell = next(image for image in body["images"] if image["kind"] == "cell")
        os.remove(media_compositor.local_media_path(cell["url"]))
        self.assertNotIn(cell["id"], [image["id"] for image in self._pool()["images"]])

    def test_a_redrawn_shot_shows_its_new_frame(self):
        self._split()
        (self.media / "shot2.png").write_bytes(_png(_textured((64, 64), 3)))
        new_url = "http://testserver/media/shot2.png"
        self.service.repo.mutate_task(self.task_id, lambda task: task["assets"]["4"][0].update(image_url=new_url))
        shots = [image for image in self._pool()["images"] if image["kind"] == "shot"]
        self.assertEqual([image["url"] for image in shots], [new_url])

    def test_unknown_image_and_bad_grid(self):
        self.assertEqual(self.client.post(f"{self.base}/split", json={"image_id": "nope", "rows": 2, "columns": 2}).status_code, 404)
        self.assertEqual(self._split(rows=9).status_code, 422)
        self.assertEqual(self._split(rows=1, columns=1).status_code, 422)

    def test_a_file_that_is_not_an_image_is_a_422_not_a_crash(self):
        (self.media / "board.png").write_bytes(b"not an image")
        self.assertEqual(self._split().status_code, 422)

    def test_remote_images_go_through_the_validated_download(self):
        remote = "https://cdn.example/board.png"
        self.service.repo.mutate_task(self.task_id, lambda task: task["assets"].update({"4_scene_boards": {"E1S01": {"grid_url": remote}}}))
        with patch.object(image_pool_api, "fetch_remote_image_bytes", return_value=_png(_grid(2, 2))) as fetch:
            self.assertEqual(self._split().status_code, 200)
        fetch.assert_called_once_with(remote)
        with patch.object(image_pool_api, "fetch_remote_image_bytes", side_effect=RuntimeError("boom")):
            self.assertEqual(self._split().status_code, 502)

    def test_assigning_a_cell_sets_the_frame_and_stales_the_clip(self):
        cell = next(image for image in self._split().json()["images"] if image["kind"] == "cell")
        with patch.object(self.service, "get_shot_visual_workspace", return_value={"task_id": self.task_id}) as workspace:
            response = self.client.post(f"{self.base}/assign", json={"image_id": cell["id"], "shot_id": 1, "scene_id": "E1S01"})
        self.assertEqual(response.status_code, 200, response.text)
        workspace.assert_called_once_with(self.task_id)
        assets = self.service.repo.get_task(self.task_id)["assets"]
        self.assertEqual(assets["4"][0]["image_url"], cell["url"])
        self.assertTrue(assets["5"][0]["stale"])
        self.assertIn("图片池", assets["5"][0]["stale_reason"])

    def test_assign_keeps_the_same_rules_as_any_other_shot_edit(self):
        board = self._board_id()
        payload = {"image_id": board, "shot_id": 1, "scene_id": "E1S01"}
        self.assertEqual(self.client.post(f"{self.base}/assign", json={**payload, "image_id": "nope"}).status_code, 404)
        self.assertEqual(self.client.post(f"{self.base}/assign", json={**payload, "shot_id": 9}).status_code, 404)
        self.service.repo.mutate_task(self.task_id, lambda task: task.update(status="running"))
        running = self.client.post(f"{self.base}/assign", json=payload)
        self.assertEqual(running.status_code, 409)
        self.assertEqual(self.service.repo.get_task(self.task_id)["assets"]["4"][0]["image_url"], self.shot_url)


if __name__ == "__main__":
    unittest.main()

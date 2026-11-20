# -*- coding: utf-8 -*-
"""The node canvas and the element library, joined in both directions (app/service/canvas_elements.py).

No provider and no network: the library is a scratch database with its files in a temp directory,
the canvas's media directory is a temp directory too, and the one run here goes to the stub gateway.

What is pinned. Taking: only the person's own elements, the node holds a *copy* in the canvas's
media storage (never the library's private address), a request is one canvas version or nothing
(and then no copy is left behind), and the copy is what a run hands its model as a reference.
Saving: a node's picture becomes a new library element with its file, through the library's own
storage path; a node with no picture, a private path, or somebody else's project is refused and
leaves no element behind.
"""

import asyncio
import hashlib
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

from app.api import element_api
from app.core import media_compositor, prompt_data, studio_canvas
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from main import app
from tests.test_canvas_workspace import CanvasCase, _edge, _node, _task


def _picture(colour) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), colour).save(buffer, format="PNG")
    return buffer.getvalue()


RED, GREEN, BLUE, GREY = (_picture(colour) for colour in ((200, 30, 30), (30, 200, 30), (30, 30, 200), (90, 90, 90)))


def _words(key: str, **names) -> str:
    return prompt_data.text("canvas_elements", key).format(**names)


class ElementCanvasCase(CanvasCase):
    def setUp(self):
        super().setUp()
        root = Path(self.temp.name)
        self.media = root / "media"
        self.media.mkdir()
        self.private = root / "private" / "elements"
        for target, value in (
            (media_compositor, {"MEDIA_DIR": str(self.media)}),
            (element_api, {"ELEMENT_MEDIA_ROOT": self.private, "LEGACY_ELEMENT_MEDIA_ROOT": self.media / "elements"}),
        ):
            patcher = patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # How full this machine's disk is has nothing to do with what is tested here.
        room = patch.object(element_api, "_ensure_disk_capacity", lambda *_: None)
        room.start()
        self.addCleanup(room.stop)

        self.store = PlatformStore(f"sqlite+aiosqlite:///{root / 'library.sqlite3'}")
        self.addCleanup(lambda: asyncio.run(self.store.close()))

        async def prepare():
            await self.store.create_schema()
            self.owner, _ = await self.store.create_user(email="canvas@example.com", phone=None, password="user-password-strong")
            self.other, _ = await self.store.create_user(email="other@example.com", phone=None, password="user-password-strong")
            self.umbrella = await self._element(self.owner.id, "prop", "红伞", {"reference": RED})
            self.lin = await self._element(self.owner.id, "actor", "林晚", {"front": GREEN, "face_front": BLUE})
            self.bare = await self._element(self.owner.id, "scene", "空场地", {})
            self.foreign = await self._element(self.other.id, "prop", "别人的信封", {"reference": GREY})

        asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store

        # The canvas of a task this library's owner owns.
        self.drama.repo.save_task("t-el", _task("t-el", owner=self.owner.id))
        self.user = {"user_id": self.owner.id, "role": "user"}
        opened = self.client.post("/api/studio/tasks/t-el/canvas-project")
        self.assertEqual(opened.status_code, 200, opened.text)
        self.project = opened.json()["project_id"]
        self.base = f"/api/studio/projects/{self.project}"

    async def _element(self, owner_id, kind, name, files):
        item = await self.store.create_element(owner_id=owner_id, kind=kind, name=name, description=f"{name}的说明", metadata={})
        for slot, content in files.items():
            await element_api._persist_element_file(
                element_id=item.id, owner_id=owner_id, slot=slot, suffix=".png", mime="image/png", content=content, store=self.store,
            )
        return item

    def library(self, owner_id=None):
        async def read():
            return [item for kind in ("prop", "actor", "scene") for item in await self.store.list_all_elements(owner_id or self.owner.id, kind)]

        return asyncio.run(read())

    def take(self, **body):
        return self.client.post(f"{self.base}/canvas/elements", json=body)

    def save(self, node_id, **body):
        return self.client.post(f"{self.base}/canvas/nodes/{node_id}/element", json=body)

    def canvas(self):
        return self.client.get(f"{self.base}/canvas").json()

    def versions(self):
        return [item["version"] for item in self.client.get(f"{self.base}/canvas/versions").json()["versions"]]

    def copies(self):
        return sorted(name for name in os.listdir(self.media) if name.startswith(prompt_data.text("canvas_elements", "copy_prefix")))

    def local(self, url):
        path = media_compositor.local_media_path(url)
        self.assertTrue(path, f"not a file of this canvas's media storage: {url}")
        return Path(path)


class PickerListingTests(ElementCanvasCase):
    def test_lists_only_the_persons_own_elements_that_have_a_picture(self):
        listed = self.client.get(f"{self.base}/canvas/elements")
        self.assertEqual(listed.status_code, 200, listed.text)
        body = listed.json()
        self.assertEqual({item["name"] for item in body["items"]}, {"红伞", "林晚"}, "no picture, nothing to take; somebody else's is not listed")
        self.assertEqual(body["total"], 2)
        self.assertIn("actor", body["kinds"])
        lin = next(item for item in body["items"] if item["name"] == "林晚")
        self.assertEqual((lin["kind"], [image["slot"] for image in lin["images"]]), ("actor", ["front", "face_front"]))
        # Thumbnails are the library's own authenticated address: the picker shows them, the canvas never stores them.
        self.assertTrue(all(image["url"].startswith(f"/api/elements/{lin['id']}/files/") for image in lin["images"]))

    def test_kind_and_search_narrow_the_list(self):
        names = lambda **params: [item["name"] for item in self.client.get(f"{self.base}/canvas/elements", params=params).json()["items"]]
        self.assertEqual(names(kind="prop"), ["红伞"])
        self.assertEqual(names(q="林"), ["林晚"])
        self.assertEqual(names(q="红伞的说明"), ["红伞"], "the description is searched too")
        self.assertEqual(names(q="没有这个"), [])
        self.assertEqual(self.client.get(f"{self.base}/canvas/elements", params={"kind": "spaceship"}).status_code, 422)

    def test_another_persons_project_is_not_a_way_in(self):
        self.user = {"user_id": self.other.id, "role": "user"}
        self.assertEqual(self.client.get(f"{self.base}/canvas/elements").status_code, 404)
        self.assertEqual(self.take(element_ids=[self.foreign.id]).status_code, 404)
        self.assertEqual(self.save("anything", name="x", kind="prop").status_code, 404)


class TakeFromLibraryTests(ElementCanvasCase):
    def test_each_element_becomes_a_media_node_holding_a_copy_in_one_version(self):
        self.put([{**_node("words", "note", text="雨夜"), "x": 100, "y": 50, "width": 240, "height": 150}])
        done = self.take(element_ids=[self.umbrella.id, self.lin.id], expected_version=1)
        self.assertEqual(done.status_code, 200, done.text)
        body = done.json()
        self.assertEqual(body["version"], 2)
        self.assertEqual(self.versions(), [2, 1], "two elements, one canvas version")
        self.assertEqual([item["name"] for item in body["elements"]], ["红伞", "林晚"])

        canvas = self.canvas()
        nodes = {node["id"]: node for node in canvas["nodes"]}
        self.assertEqual(len(nodes), 3)
        taken = [nodes[node_id] for node_id in body["node_ids"]]
        self.assertEqual([(node["kind"], node["payload"]["label"]) for node in taken], [("media", "红伞"), ("media", "林晚")])
        for node, element, content in zip(taken, (self.umbrella, self.lin), (RED, GREEN)):
            output = node["payload"]["output"]
            self.assertEqual((output["medium"], output["name"]), ("image", element.name))
            # A copy in the canvas's own storage, not the library's private address.
            self.assertNotIn("/api/elements", output["url"])
            self.assertNotIn("/elements/", output["url"])
            self.assertEqual(self.local(output["url"]).read_bytes(), content)
            self.assertEqual(self.local(output["url"]).parent, self.media.resolve())
            self.assertTrue(studio_canvas.safe_media_url(output["url"]), "a run may hand this to a provider")
            self.assertEqual((output["element"]["id"], output["element"]["name"], output["element"]["kind"]), (element.id, element.name, element.kind))
            self.assertEqual(output["element"]["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(len(self.copies()), 2)
        # Placed to the right of what was there, side by side: nothing overlaps.
        boxes = [(node["x"], node["y"], node["width"], node["height"]) for node in canvas["nodes"]]
        for index, (x, y, width, height) in enumerate(boxes):
            for other_x, other_y, other_width, other_height in boxes[index + 1:]:
                self.assertTrue(x + width <= other_x or other_x + other_width <= x or y + height <= other_y or other_y + other_height <= y)
        self.assertTrue(all(node["x"] >= 340 for node in taken))

    def test_the_copy_is_what_a_run_hands_its_model_as_the_reference(self):
        taken = self.take(element_ids=[self.umbrella.id]).json()
        canvas = self.canvas()
        media = canvas["nodes"][0]
        saved = self.put([media, _node("img", "image_gen", prompt="她撑着这把伞")], [_edge(media["id"], "img", "ref_image")], expected=taken["version"])
        started = self.run_nodes(["img"], saved["version"])
        self.assertEqual(started["status"], "started", started)
        self.assertEqual(self.gateway.image_calls[-1]["ref_images"], [media["payload"]["output"]["url"]])

    def test_somebody_elses_element_is_refused_and_nothing_is_added(self):
        self.put([_node("words", "note", text="雨夜")])
        for ids in ([self.umbrella.id, self.foreign.id], [self.foreign.id], ["no-such-element"]):
            refused = self.take(element_ids=ids, expected_version=1)
            self.assertEqual(refused.status_code, 404, refused.text)
            self.assertEqual(refused.json()["detail"], _words("not_found"))
        self.assertEqual(self.take(picks=[{"element_id": self.foreign.id}]).status_code, 404)
        self.assertEqual(self.versions(), [1])
        self.assertEqual(len(self.canvas()["nodes"]), 1)
        self.assertEqual(self.copies(), [], "the first, allowed element was not copied either")

    def test_a_stale_version_adds_nothing_and_leaves_no_copy(self):
        self.put([_node("words", "note", text="雨夜")])
        self.assertEqual(self.take(element_ids=[self.umbrella.id], expected_version=0).status_code, 409)
        self.assertEqual((self.versions(), self.copies()), ([1], []))
        # The canvas moved on between the copy and the write: the copies made for it are removed again.
        real = self.studio.edit_canvas

        def raced(*args, **kwargs):
            self.put([_node("words", "note", text="别处改了")], expected=1)
            return real(*args, **kwargs)

        with patch.object(self.studio, "edit_canvas", side_effect=raced):
            self.assertEqual(self.take(element_ids=[self.umbrella.id, self.lin.id], expected_version=1).status_code, 409)
        self.assertEqual((self.versions(), self.copies()), ([2, 1], []))

    def test_a_particular_view_can_be_picked_and_the_same_picture_is_taken_once(self):
        files = {item.slot: item.id for item in asyncio.run(self.store.get_element(self.lin.id, self.owner.id)).files}
        done = self.take(
            element_ids=[self.lin.id],
            picks=[{"element_id": self.lin.id, "file_id": files["face_front"]}, {"element_id": self.lin.id, "file_id": files["front"]}],
        )
        self.assertEqual(done.status_code, 200, done.text)
        nodes = {node["id"]: node for node in self.canvas()["nodes"]}
        held = [nodes[node_id]["payload"]["output"] for node_id in done.json()["node_ids"]]
        self.assertEqual([output["element"]["slot"] for output in held], ["front", "face_front"], "the main picture named twice is one node")
        self.assertEqual([self.local(output["url"]).read_bytes() for output in held], [GREEN, BLUE])

    def test_what_cannot_be_taken_says_why(self):
        cases = (
            ({"element_ids": []}, "nothing_chosen", {}),
            ({"element_ids": [self.bare.id]}, "no_image", {"name": "空场地"}),
            ({"picks": [{"element_id": self.umbrella.id, "file_id": "not-a-file"}]}, "no_such_image", {"name": "红伞"}),
        )
        for body, key, names in cases:
            refused = self.take(**body)
            self.assertEqual(refused.status_code, 422, refused.text)
            self.assertEqual(refused.json()["detail"], _words(key, **names))
        with patch.dict(prompt_data.load("canvas_elements"), {"max_take": 1}):
            refused = self.take(element_ids=[self.umbrella.id, self.lin.id])
            self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("too_many", limit=1, count=2)))
        # The file went missing from the library's storage: said, and nothing half-added.
        for path in (self.private / self.owner.id / self.umbrella.id).iterdir():
            path.unlink()
        refused = self.take(element_ids=[self.lin.id, self.umbrella.id])
        self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("image_missing", name="红伞")))
        self.assertEqual((self.versions(), self.copies()), ([], []))

    def test_the_edit_operation_keeps_the_note_of_where_a_file_came_from_and_nothing_else(self):
        document, _ = studio_canvas.apply_operations({"nodes": [], "edges": []}, [{
            "op": "add_node", "kind": "media",
            "output": {"medium": "image", "url": "/media/a.png", "element": {"id": " e1 ", "name": "红伞", "secret": "x", "slot": 7}, "provenance": {"origin": "made-up"}},
        }])
        self.assertEqual(document["nodes"][0]["payload"]["output"], {"medium": "image", "url": "/media/a.png", "element": {"id": "e1", "name": "红伞", "slot": "7"}})
        plain, _ = studio_canvas.apply_operations({"nodes": [], "edges": []}, [{"op": "add_node", "kind": "media", "output": {"medium": "image", "url": "/media/a.png", "element": {"name": "没有 id"}}}])
        self.assertNotIn("element", plain["nodes"][0]["payload"]["output"])


class SaveToLibraryTests(ElementCanvasCase):
    def _saved(self, element_id):
        return asyncio.run(self.store.get_element(element_id, self.owner.id))

    def test_a_media_nodes_picture_becomes_a_new_element_with_its_file(self):
        (self.media / "board.png").write_bytes(BLUE)
        self.put([_node("pic", "media", label="雨街", output={"medium": "image", "url": "/media/board.png"})])
        before = len(self.library())
        done = self.save("pic", name=" 雨街全景 ", kind="scene")
        self.assertEqual(done.status_code, 200, done.text)
        body = done.json()
        self.assertEqual((body["name"], body["kind"]), ("雨街全景", "scene"))
        element = self._saved(body["id"])
        self.assertEqual((element.name, element.kind, element.owner_id), ("雨街全景", "scene", self.owner.id))
        self.assertEqual(len(self.library()), before + 1)
        self.assertEqual([(item.slot, item.mime_type, item.sha256) for item in element.files], [("reference", "image/png", hashlib.sha256(BLUE).hexdigest())])
        # Stored by the library itself: in its private root, under the owner and the element.
        stored = self.private / element.files[0].storage_path
        self.assertEqual(stored.read_bytes(), BLUE)
        self.assertEqual(stored.parent, self.private / self.owner.id / element.id)
        self.assertEqual(element.metadata_json["canvas_source"], {"project_id": self.project, "canvas_id": "main", "node_id": "pic"})
        self.assertEqual(self.versions(), [1], "saving to the library does not change the canvas")
        # And it is an ordinary element from then on: it can be taken back onto a canvas.
        self.assertEqual(self.take(element_ids=[body["id"]]).status_code, 200)

    def test_a_generated_picture_is_saved_from_the_nodes_active_run(self):
        self.put([_node("img", "image_gen", prompt="雨夜老宅", label="老宅")])
        self.run_nodes(["img"], 1)
        (self.media / "image_1.png").write_bytes(GREEN)  # what the stub gateway said it made
        done = self.save("img", name="老宅", kind="actor")
        self.assertEqual(done.status_code, 200, done.text)
        element = self._saved(done.json()["id"])
        self.assertEqual([(item.slot, item.sha256) for item in element.files], [("front", hashlib.sha256(GREEN).hexdigest())], "an actor's picture goes to the front view")
        self.assertTrue(element.metadata_json["canvas_source"]["run_id"])

    def test_a_copy_taken_from_the_library_can_be_saved_back_as_another_element(self):
        taken = self.take(element_ids=[self.umbrella.id]).json()
        done = self.save(taken["node_ids"][0], name="红伞·备份", kind="prop")
        self.assertEqual(done.status_code, 200, done.text)
        self.assertNotEqual(done.json()["id"], self.umbrella.id)
        self.assertEqual(self._saved(done.json()["id"]).files[0].sha256, hashlib.sha256(RED).hexdigest())

    def test_a_node_with_no_picture_is_refused_and_no_element_is_made(self):
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
        before = len(self.library())
        for node_id in ("words", "img", "clip", "empty"):
            refused = self.save(node_id, name="x", kind="prop")
            self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("node_no_image")), node_id)
        missing = self.save("nowhere", name="x", kind="prop")
        self.assertEqual((missing.status_code, missing.json()["detail"]), (422, _words("node_missing")))
        unreadable = self.save("gone", name="x", kind="prop")
        self.assertEqual((unreadable.status_code, unreadable.json()["detail"]), (422, _words("result_unreadable")))
        self.assertEqual(self.save("fake", name="x", kind="prop").status_code, 422, "the library's own check on what a picture is")
        self.assertEqual(len(self.library()), before)

    def test_the_name_and_kind_are_the_librarys(self):
        (self.media / "board.png").write_bytes(BLUE)
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/board.png"})])
        unknown = self.save("pic", name="x", kind="spaceship")
        self.assertEqual((unknown.status_code, unknown.json()["detail"]), (422, _words("bad_kind", kind="spaceship")))
        blank = self.save("pic", name="   ", kind="prop")
        self.assertEqual((blank.status_code, blank.json()["detail"]), (422, _words("name_required")))
        self.assertEqual(self.save("pic", name="", kind="prop").status_code, 422)

    def test_a_private_library_file_cannot_be_copied_out_through_a_canvas_node(self):
        # Old installations kept element pictures under /media/elements; a node pointing there is not a way to copy one.
        legacy = self.media / "elements" / self.other.id / self.foreign.id
        legacy.mkdir(parents=True)
        (legacy / "secret.png").write_bytes(GREY)
        url = f"/media/elements/{self.other.id}/{self.foreign.id}/secret.png"
        self.put([_node("sneak", "media", output={"medium": "image", "url": url})])
        before = len(self.library())
        refused = self.save("sneak", name="偷来的", kind="prop")
        self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("result_private")))
        self.assertEqual(len(self.library()), before)

    def test_a_remote_picture_goes_through_the_librarys_guarded_fetch(self):
        self.put([_node("far", "media", output={"medium": "image", "url": "https://img.test/lin.png"})])
        with patch.object(element_api, "_load_generated_image_bytes", return_value=RED) as fetch:
            done = self.save("far", name="远处的图", kind="prop")
        self.assertEqual(done.status_code, 200, done.text)
        fetch.assert_called_once_with("https://img.test/lin.png")
        with patch.object(element_api, "_load_generated_image_bytes", side_effect=RuntimeError("connection reset")):
            refused = self.save("far", name="远处的图", kind="prop")
        self.assertEqual((refused.status_code, refused.json()["detail"]), (422, _words("result_unreadable")))

    def test_a_file_the_library_will_not_store_leaves_no_empty_element(self):
        (self.media / "board.png").write_bytes(BLUE)
        self.put([_node("pic", "media", output={"medium": "image", "url": "/media/board.png"})])
        before = len(self.library())
        with patch.object(element_api, "_persist_element_file", side_effect=HTTPException(status_code=507, detail="存储空间不足")):
            refused = self.save("pic", name="存不下", kind="prop")
        self.assertEqual((refused.status_code, refused.json()["detail"]), (507, "存储空间不足"))
        self.assertEqual(len(self.library()), before)

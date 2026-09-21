import asyncio
import base64
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.core.storyboard_element_context import load_storyboard_elements


def _image_bytes(color="teal"):
    stream = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(stream, format="PNG")
    return stream.getvalue()


class MemoryStore:
    def __init__(self, items):
        self.items = items
        self.calls = []
        self.closed = False

    async def list_elements(self, owner_id, kind, page, page_size):
        self.calls.append((owner_id, kind, page, page_size))
        # Deliberately do not filter owners: the loader must recheck every row.
        items = [item for item in self.items if item.kind == kind]
        start = (page - 1) * page_size
        return items[start : start + page_size], len(items)

    async def close(self):
        self.closed = True


class StoryboardElementContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.root.mkdir()
        self.task = {"owner_user_id": "owner-one", "task_id": "task-one"}
        self.roots_patch = patch(
            "app.core.storyboard_element_context._image_roots",
            return_value=(self.root,),
        )
        self.roots_patch.start()
        self.addCleanup(self.roots_patch.stop)

    def element(
        self,
        element_id="element-one",
        kind="actor",
        owner="owner-one",
        task_id="task-one",
    ):
        return SimpleNamespace(
            id=element_id,
            owner_id=owner,
            kind=kind,
            name=f"名称-{element_id}",
            description="当前剧情中的资产描述",
            metadata_json={"task_id": task_id},
            files=[],
        )

    def reference(self, item, *, content=None, mime="image/png", slot="front"):
        content = content if content is not None else _image_bytes()
        relative = Path(item.owner_id) / item.id / f"{slot}.png"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        reference = SimpleNamespace(
            slot=slot,
            storage_path=str(relative),
            mime_type=mime,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        item.files.append(reference)
        return target, reference

    def load(self, items, scene=None):
        store = MemoryStore(items)
        with patch(
            "app.core.storyboard_element_context.PlatformStore", return_value=store
        ):
            result = load_storyboard_elements(self.task, scene)
        self.assertTrue(store.closed)
        return result, store

    def test_loads_all_kinds_and_pages_without_cross_project_or_owner_assets(self):
        items = [self.element(f"prop-{index}", kind="prop") for index in range(105)]
        items.extend(
            self.element(kind=kind, element_id=f"{kind}-one")
            for kind in ("actor", "scene", "costume", "effect")
        )
        items += [
            self.element("foreign-owner", owner="owner-two"),
            self.element("foreign-task", task_id="task-two"),
            self.element("unscoped", task_id=""),
        ]
        result, store = self.load(items)
        self.assertEqual(len(result), 109)
        self.assertEqual(
            {entry["kind"] for entry in result},
            {"actor", "scene", "prop", "costume", "effect"},
        )
        self.assertTrue(
            any(kind == "prop" and page == 2 for _, kind, page, _ in store.calls)
        )
        self.assertFalse(
            {"foreign-owner", "foreign-task", "unscoped"}.intersection(
                entry["id"] for entry in result
            )
        )

    def test_loads_assets_linked_from_another_project(self):
        linked = self.element("linked-from-other", kind="prop", task_id="task-two")
        linked.metadata_json["task_ids"] = ["task-two", "task-one"]
        unlinked = self.element("still-foreign", kind="prop", task_id="task-two")

        result, _ = self.load([linked, unlinked])

        self.assertEqual([item["id"] for item in result], ["linked-from-other"])
        self.assertEqual(result[0]["metadata"]["task_id"], "task-two")

    def test_returns_valid_private_image_bytes_and_prefers_actor_front(self):
        item = self.element()
        self.reference(item, slot="back", content=_image_bytes("red"))
        _, front = self.reference(item)
        result, _ = self.load([item])
        encoded = result[0]["image_url"]
        self.assertTrue(encoded.startswith("data:image/png;base64,"))
        self.assertEqual(
            hashlib.sha256(base64.b64decode(encoded.split(",", 1)[1])).hexdigest(),
            front.sha256,
        )
        self.assertEqual(result[0]["metadata"], {"task_id": "task-one"})
        self.assertEqual(result[0]["description"], item.description)

    def test_scene_selection_reads_only_matched_reference_files(self):
        selected = [self.element("current-actor")]
        selected[0].name = "沈砚"
        for kind, name in (
            ("scene", "天文台"),
            ("prop", "铜鱼符"),
            ("costume", "沈砚官袍"),
            ("effect", "血痕"),
        ):
            item = self.element(f"current-{kind}", kind=kind)
            item.name = name
            selected.append(item)
        unrelated = [self.element("unrelated-actor")]
        unrelated[0].name = "太后"
        unrelated += [
            self.element(f"unrelated-{index}", kind="prop") for index in range(120)
        ]
        for item in selected + unrelated:
            self.reference(item)
        scene = {
            "scene_id": "E1S01",
            "characters": ["沈砚"],
            "content": "沈砚身穿官袍在天文台攥紧铜鱼符，指尖划出血痕。",
        }
        expected_paths = {
            str((self.root / item.files[0].storage_path).resolve()) for item in selected
        }
        actual_paths = []
        original_open = Path.open

        def tracked_open(path, *args, **kwargs):
            actual_paths.append(str(path.resolve()))
            self.assertIn(
                str(path.resolve()),
                expected_paths,
                "unselected reference file was read",
            )
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", tracked_open):
            result, store = self.load(selected + unrelated, scene)
        self.assertEqual(
            {item["id"] for item in result}, {item.id for item in selected}
        )
        self.assertEqual(set(actual_paths), expected_paths)
        self.assertTrue(
            all(item["image_url"].startswith("data:image/png;") for item in result)
        )
        self.assertTrue(
            any(kind == "prop" and page == 2 for _, kind, page, _ in store.calls)
        )

    def test_scene_selection_retains_only_matched_identity_for_duplicate_names(self):
        current = self.element("current-look")
        current.name = "沈砚"
        current.metadata_json["scene_ids"] = ["E1S01"]
        later = self.element("later-look")
        later.name = current.name
        later.metadata_json["scene_ids"] = ["E2S01"]
        for item in (current, later):
            self.reference(item)
        scene = {
            "scene_id": "E1S01",
            "characters": ["沈砚"],
            "content": "沈砚攥紧腰间铜鱼符。",
        }
        with patch(
            "app.core.storyboard_element_context._image_data_uri", return_value="image"
        ) as read_image:
            result, _ = self.load([current, later], scene)
        self.assertEqual([item["id"] for item in result], [current.id])
        self.assertEqual(read_image.call_count, 1)

    def test_rejects_traversal_cross_owner_and_symlink_reference_paths(self):
        foreign = self.element("foreign", owner="owner-two")
        foreign_target, foreign_ref = self.reference(foreign)
        items = []
        for element_id, storage in (
            ("traversal", "owner-one/traversal/../../owner-two/foreign/front.png"),
            ("other-owner", foreign_ref.storage_path),
            ("absolute", str(foreign_target)),
        ):
            item = self.element(element_id)
            item.files = [
                SimpleNamespace(**{**vars(foreign_ref), "storage_path": storage})
            ]
            items.append(item)
        symlink = self.element("symlink")
        link = self.root / "owner-one" / "symlink" / "front.png"
        link.parent.mkdir(parents=True)
        link.symlink_to(foreign_target)
        symlink.files = [
            SimpleNamespace(
                **{**vars(foreign_ref), "storage_path": "owner-one/symlink/front.png"}
            )
        ]
        items.append(symlink)
        directory = self.element("linked-directory")
        (self.root / "owner-one" / directory.id).symlink_to(
            foreign_target.parent, target_is_directory=True
        )
        directory.files = [
            SimpleNamespace(
                **{
                    **vars(foreign_ref),
                    "storage_path": f"owner-one/{directory.id}/front.png",
                }
            )
        ]
        items.append(directory)
        result, _ = self.load(items)
        self.assertEqual(len(result), len(items))
        self.assertTrue(all(entry["image_url"] == "" for entry in result))

    def test_rejects_non_images_corrupt_bytes_wrong_mime_and_changed_hash(self):
        items = []
        for element_id, content, mime in (
            ("glb", b"glTF model", "model/gltf-binary"),
            ("text", b"not an image", "image/png"),
            ("signature-only", b"\x89PNG\r\n\x1a\n", "image/png"),
            ("wrong-mime", _image_bytes(), "image/jpeg"),
        ):
            item = self.element(element_id)
            self.reference(item, content=content, mime=mime)
            items.append(item)
        changed = self.element("changed")
        _, reference = self.reference(changed)
        reference.sha256 = "0" * 64
        items.append(changed)
        result, _ = self.load(items)
        self.assertTrue(all(entry["image_url"] == "" for entry in result))

    def test_closes_fresh_store_after_failure_and_skips_ownerless_tasks(self):
        store = MemoryStore([])

        async def fail(*_args):
            raise RuntimeError("database unavailable")

        store.list_elements = fail
        with patch(
            "app.core.storyboard_element_context.PlatformStore", return_value=store
        ) as factory:
            self.assertEqual(load_storyboard_elements({"task_id": "task-one"}), [])
            factory.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "元素库读取失败"):
                load_storyboard_elements(self.task)
        self.assertTrue(store.closed)

    def test_rejects_async_caller_before_creating_a_second_event_loop(self):
        async def call():
            with self.assertRaisesRegex(RuntimeError, "synchronous stage worker"):
                load_storyboard_elements(self.task)

        asyncio.run(call())


if __name__ == "__main__":
    unittest.main()

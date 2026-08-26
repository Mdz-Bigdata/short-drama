import asyncio
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.element_api import (
    ELEMENT_MODEL_ROOT,
    delete_element as delete_element_endpoint,
    delete_element_file as delete_element_file_endpoint,
)
from app.api.auth_api import auth_service
from app.core.media_compositor import MEDIA_DIR
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from main import app


def _glb(document: dict, binary: bytes = b"") -> bytes:
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    chunks = struct.pack("<II", len(payload), 0x4E4F534A) + payload
    if binary:
        padded_binary = binary + b"\x00" * (-len(binary) % 4)
        chunks += struct.pack("<II", len(padded_binary), 0x004E4942) + padded_binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def _triangle_glb(*, generator: str = "test fixture") -> bytes:
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    return _glb({
        "asset": {"version": "2.0", "generator": generator},
        "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions), "target": 34962}],
        "accessors": [{
            "bufferView": 0,
            "componentType": 5126,
            "count": 3,
            "type": "VEC3",
            "min": [0, 0, 0],
            "max": [1, 1, 0],
        }],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }, positions)


class PlatformApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "api.sqlite3"
        self.store = PlatformStore(f"sqlite+aiosqlite:///{db_path}")

        async def prepare():
            await self.store.create_schema()
            await self.store.seed_capabilities()
            await self.store.seed_billing_plans()
            self.admin, _ = await self.store.create_user(
                email="admin-api@example.com", phone=None, password="admin-password-strong", role="admin"
            )
            self.user, _ = await self.store.create_user(
                email="user-api@example.com", phone=None, password="user-password-strong"
            )

        asyncio.run(prepare())
        app.dependency_overrides[get_platform_store] = lambda: self.store
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        asyncio.run(self.store.close())
        self.temp.cleanup()

    def _cookie(self, user_id: str) -> dict:
        return {"auth_token": auth_service.generate_token(user_id)}

    def test_admin_can_toggle_global_capability_and_user_can_invoke_enabled_only(self):
        admin_cookie = self._cookie(self.admin.id)
        user_cookie = self._cookie(self.user.id)
        listed = self.client.get("/api/platform/capabilities", cookies=user_cookie)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 13)
        ability = listed.json()["items"][0]["abilities"][0]
        source_id = listed.json()["items"][0]["source_id"]

        forbidden = self.client.patch(
            f"/api/platform/capabilities/{source_id}/{ability['id']}",
            json={"enabled": False},
            cookies=user_cookie,
        )
        self.assertEqual(forbidden.status_code, 403)

        disabled = self.client.patch(
            f"/api/platform/capabilities/{source_id}/{ability['id']}",
            json={"enabled": False},
            cookies=admin_cookie,
        )
        self.assertEqual(disabled.status_code, 200)
        rejected = self.client.post(
            "/api/platform/commands/invoke",
            json={"command": ability["command"] + " hello"},
            cookies=user_cookie,
        )
        self.assertEqual(rejected.status_code, 422)

        self.client.patch(
            f"/api/platform/capabilities/{source_id}/{ability['id']}",
            json={"enabled": True},
            cookies=admin_cookie,
        )
        invoked = self.client.post(
            "/api/platform/commands/invoke",
            json={"command": ability["command"] + " hello"},
            cookies=user_cookie,
        )
        self.assertEqual(invoked.status_code, 200)
        self.assertEqual(invoked.json()["status"], "accepted")
        self.assertEqual(invoked.json()["payload"], "hello")

    def test_all_four_element_pages_support_add_upload_and_regenerate(self):
        cookie = self._cookie(self.user.id)
        for kind in ("actor", "prop", "scene", "effect"):
            created = self.client.post(
                "/api/elements",
                json={"kind": kind, "name": f"{kind}-sample", "description": "fixture"},
                cookies=cookie,
            )
            self.assertEqual(created.status_code, 200, created.text)
            element_id = created.json()["id"]
            listed = self.client.get(f"/api/elements?kind={kind}", cookies=cookie)
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.json()["total"], 1)

            slot = "front" if kind == "actor" else "reference"
            uploaded = self.client.post(
                f"/api/elements/{element_id}/files",
                data={"slot": slot},
                files={"file": ("image.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
                cookies=cookie,
            )
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            self.assertEqual(len(uploaded.json()["files"]), 1)

            regenerated = self.client.post(
                f"/api/elements/{element_id}/regenerate",
                json={"prompt": "保持身份与风格，仅优化细节"},
                cookies=cookie,
            )
            self.assertEqual(regenerated.status_code, 200)
            self.assertFalse(regenerated.json()["paid_submission_approved"])

    def test_scene_and_prop_models_are_validated_stored_and_served_to_the_owner(self):
        cookie = self._cookie(self.user.id)
        model = _triangle_glb()
        image_root = Path(self.temp.name) / "elements"
        model_root = Path(self.temp.name) / "private-models"
        with (
            patch("app.api.element_api.ELEMENT_MEDIA_ROOT", image_root),
            patch("app.api.element_api.ELEMENT_MODEL_ROOT", model_root),
        ):
            created = self.client.post(
                "/api/elements",
                json={
                    "kind": "scene",
                    "name": "雨夜巷口",
                    "metadata": {"model3d": {"stats": {"triangles": 999_999_999}}},
                },
                cookies=cookie,
            )
            self.assertIsNone(created.json()["model3d"])
            self.assertNotIn("model3d", created.json()["metadata"])
            element_id = created.json()["id"]

            uploaded = self.client.post(
                f"/api/elements/{element_id}/model",
                files={"file": ("alley.glb", model, "model/gltf-binary")},
                cookies=cookie,
            )
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            contract = uploaded.json()["model3d"]
            self.assertEqual(contract["format"], "glb")
            self.assertEqual(contract["stats"]["triangles"], 1)
            self.assertEqual(contract["stats"]["vertices"], 3)
            self.assertEqual(contract["stats"]["drawCalls"], 1)
            self.assertIsNone(next(file for file in uploaded.json()["files"] if file["media_kind"] == "model")["url"])

            protected = self.client.get(contract["contentUrl"], cookies=cookie)
            self.assertEqual(protected.status_code, 200)
            self.assertEqual(protected.content, model)
            self.assertEqual(protected.headers["content-type"], "model/gltf-binary")
            self.assertEqual(protected.headers["cache-control"], "private, no-store")
            self.assertEqual(protected.headers["vary"], "Cookie")
            self.assertEqual(self.client.get(contract["contentUrl"]).status_code, 401)
            self.assertEqual(
                self.client.get(contract["contentUrl"], cookies=self._cookie(self.admin.id)).status_code,
                404,
            )

            replacement = _triangle_glb(generator="replacement")
            replaced = self.client.post(
                f"/api/elements/{element_id}/model",
                files={"file": ("alley-v2.glb", replacement, "model/gltf-binary")},
                cookies=cookie,
            )
            self.assertEqual(replaced.status_code, 200, replaced.text)
            self.assertEqual(self.client.get(contract["contentUrl"], cookies=cookie).status_code, 404)
            current_url = replaced.json()["model3d"]["contentUrl"]
            self.assertEqual(self.client.get(current_url, cookies=cookie).content, replacement)
            self.assertEqual(len(list(model_root.rglob("*.glb"))), 1)
            self.assertEqual(len(list(image_root.rglob("*.glb"))), 0)

            actor = self.client.post(
                "/api/elements", json={"kind": "actor", "name": "角色"}, cookies=cookie
            ).json()
            rejected = self.client.post(
                f"/api/elements/{actor['id']}/model",
                files={"file": ("actor.glb", model, "model/gltf-binary")},
                cookies=cookie,
            )
            self.assertEqual(rejected.status_code, 422)

    def test_default_model_storage_is_outside_the_public_media_tree(self):
        media_root = Path(MEDIA_DIR).resolve()
        private_root = ELEMENT_MODEL_ROOT.resolve()
        self.assertNotEqual(private_root, media_root)
        self.assertNotIn(media_root, private_root.parents)

    def test_owner_can_delete_reference_model_and_whole_asset_files(self):
        owner_cookie = self._cookie(self.user.id)
        stranger_cookie = self._cookie(self.admin.id)
        image_root = Path(self.temp.name) / "delete-elements"
        model_root = Path(self.temp.name) / "delete-models"
        with (
            patch("app.api.element_api.ELEMENT_MEDIA_ROOT", image_root),
            patch("app.api.element_api.ELEMENT_MODEL_ROOT", model_root),
        ):
            created = self.client.post(
                "/api/elements",
                json={"kind": "prop", "name": "可删除道具", "metadata": {"source": "test"}},
                cookies=owner_cookie,
            ).json()
            element_id = created["id"]
            uploaded_image = self.client.post(
                f"/api/elements/{element_id}/files",
                data={"slot": "reference"},
                files={"file": ("reference.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
                cookies=owner_cookie,
            ).json()
            image_file = next(item for item in uploaded_image["files"] if item["media_kind"] == "image")
            uploaded_model = self.client.post(
                f"/api/elements/{element_id}/model",
                files={"file": ("prop.glb", _triangle_glb(), "model/gltf-binary")},
                cookies=owner_cookie,
            ).json()
            model_file = next(item for item in uploaded_model["files"] if item["media_kind"] == "model")
            model_url = uploaded_model["model3d"]["contentUrl"]
            original_version = uploaded_model["version"]
            self.assertEqual(len(list(image_root.rglob("*.png"))), 1)
            self.assertEqual(len(list(model_root.rglob("*.glb"))), 1)

            forbidden = self.client.delete(
                f"/api/elements/{element_id}/files/{image_file['id']}",
                cookies=stranger_cookie,
            )
            self.assertEqual(forbidden.status_code, 404)
            self.assertEqual(len(list(image_root.rglob("*.png"))), 1)

            deleted_image = self.client.delete(
                f"/api/elements/{element_id}/files/{image_file['id']}",
                cookies=owner_cookie,
            )
            self.assertEqual(deleted_image.status_code, 200, deleted_image.text)
            self.assertEqual(deleted_image.json()["version"], original_version + 1)
            self.assertEqual(len(list(image_root.rglob("*.png"))), 0)

            deleted_model = self.client.delete(
                f"/api/elements/{element_id}/files/{model_file['id']}",
                cookies=owner_cookie,
            )
            self.assertEqual(deleted_model.status_code, 200, deleted_model.text)
            self.assertIsNone(deleted_model.json()["model3d"])
            self.assertNotIn("model3d", deleted_model.json()["metadata"])
            self.assertEqual(deleted_model.json()["status"], "draft")
            self.assertEqual(deleted_model.json()["version"], original_version + 2)
            self.assertEqual(len(list(model_root.rglob("*.glb"))), 0)
            self.assertEqual(self.client.get(model_url, cookies=owner_cookie).status_code, 404)

            self.client.post(
                f"/api/elements/{element_id}/files",
                data={"slot": "reference"},
                files={"file": ("again.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
                cookies=owner_cookie,
            )
            self.client.post(
                f"/api/elements/{element_id}/model",
                files={"file": ("again.glb", _triangle_glb(), "model/gltf-binary")},
                cookies=owner_cookie,
            )
            self.assertEqual(len(list(image_root.rglob("*.png"))), 1)
            self.assertEqual(len(list(model_root.rglob("*.glb"))), 1)

            still_forbidden = self.client.delete(
                f"/api/elements/{element_id}", cookies=stranger_cookie
            )
            self.assertEqual(still_forbidden.status_code, 404)
            deleted_asset = self.client.delete(
                f"/api/elements/{element_id}", cookies=owner_cookie
            )
            self.assertEqual(deleted_asset.status_code, 200, deleted_asset.text)
            self.assertEqual(deleted_asset.json(), {"id": element_id, "deleted": True})
            self.assertEqual(self.client.get(f"/api/elements/{element_id}", cookies=owner_cookie).status_code, 404)
            self.assertEqual(len(list(image_root.rglob("*.png"))), 0)
            self.assertEqual(len(list(model_root.rglob("*.glb"))), 0)

    def test_delete_never_unlinks_paths_outside_the_owned_element_directory(self):
        owner_cookie = self._cookie(self.user.id)
        image_root = Path(self.temp.name) / "safe-delete-elements"
        model_root = Path(self.temp.name) / "safe-delete-models"
        outside = Path(self.temp.name) / "outside.png"
        outside.write_bytes(b"outside")

        with (
            patch("app.api.element_api.ELEMENT_MEDIA_ROOT", image_root),
            patch("app.api.element_api.ELEMENT_MODEL_ROOT", model_root),
        ):
            target = self.client.post(
                "/api/elements", json={"kind": "prop", "name": "目标"}, cookies=owner_cookie
            ).json()
            sibling = self.client.post(
                "/api/elements", json={"kind": "prop", "name": "同账户其他资产"}, cookies=owner_cookie
            ).json()
            other_owner_path = image_root / self.admin.id / "foreign-element" / "foreign.png"
            sibling_path = image_root / self.user.id / sibling["id"] / "sibling.png"
            other_owner_path.parent.mkdir(parents=True, exist_ok=True)
            sibling_path.parent.mkdir(parents=True, exist_ok=True)
            other_owner_path.write_bytes(b"foreign")
            sibling_path.write_bytes(b"sibling")

            async def attach_untrusted_paths():
                results = []
                for slot, storage_path in (
                    ("outside", str(outside)),
                    ("other_owner", str(other_owner_path.relative_to(image_root))),
                    ("other_element", str(sibling_path.relative_to(image_root))),
                ):
                    stored = await self.store.add_element_file(
                        element_id=target["id"],
                        owner_id=self.user.id,
                        slot=slot,
                        storage_path=storage_path,
                        mime_type="image/png",
                        size_bytes=1,
                        sha256=slot,
                    )
                    results.append(next(item.id for item in stored.element.files if item.slot == slot))
                return results

            file_ids = asyncio.run(attach_untrusted_paths())
            for file_id in file_ids:
                response = self.client.delete(
                    f"/api/elements/{target['id']}/files/{file_id}", cookies=owner_cookie
                )
                self.assertEqual(response.status_code, 200, response.text)

            self.assertTrue(outside.is_file())
            self.assertTrue(other_owner_path.is_file())
            self.assertTrue(sibling_path.is_file())

    def test_delete_move_failure_keeps_database_record_and_public_file(self):
        owner_cookie = self._cookie(self.user.id)
        image_root = Path(self.temp.name) / "move-failure-elements"
        with patch("app.api.element_api.ELEMENT_MEDIA_ROOT", image_root):
            element = self.client.post(
                "/api/elements",
                json={"kind": "prop", "name": "隔离失败道具"},
                cookies=owner_cookie,
            ).json()
            uploaded = self.client.post(
                f"/api/elements/{element['id']}/files",
                data={"slot": "reference"},
                files={"file": ("reference.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
                cookies=owner_cookie,
            ).json()
            file_id = uploaded["files"][0]["id"]
            public_file = next(image_root.rglob("*.png"))

            with patch("app.api.element_api.os.replace", side_effect=OSError("rename failed")):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(delete_element_file_endpoint(
                        element["id"],
                        file_id,
                        user={"user_id": self.user.id},
                        store=self.store,
                    ))
            self.assertEqual(raised.exception.status_code, 500)
            self.assertIn("资产文件隔离失败", raised.exception.detail)

            persisted = asyncio.run(self.store.get_element(element["id"], self.user.id))
            self.assertEqual([item.id for item in persisted.files], [file_id])
            self.assertTrue(public_file.is_file())

    def test_delete_restores_quarantined_file_when_database_commit_fails(self):
        owner_cookie = self._cookie(self.user.id)
        image_root = Path(self.temp.name) / "db-failure-elements"
        quarantine_root = (
            image_root.parent.parent
            / f".{image_root.parent.name}-{image_root.name}-quarantine"
        )
        self.assertNotIn(image_root.parent, quarantine_root.parents)
        with patch("app.api.element_api.ELEMENT_MEDIA_ROOT", image_root):
            element = self.client.post(
                "/api/elements",
                json={"kind": "prop", "name": "提交失败道具"},
                cookies=owner_cookie,
            ).json()
            uploaded = self.client.post(
                f"/api/elements/{element['id']}/files",
                data={"slot": "reference"},
                files={"file": ("reference.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
                cookies=owner_cookie,
            ).json()
            file_id = uploaded["files"][0]["id"]
            public_file = next(image_root.rglob("*.png"))

            async def fail_commit(_session):
                self.assertFalse(public_file.exists())
                self.assertEqual(len(list(quarantine_root.rglob("*.asset"))), 1)
                self.assertEqual(len(list(quarantine_root.rglob("*.json"))), 1)
                raise RuntimeError("commit failed")

            with patch.object(AsyncSession, "commit", fail_commit):
                with self.assertRaisesRegex(RuntimeError, "commit failed"):
                    asyncio.run(delete_element_file_endpoint(
                        element["id"],
                        file_id,
                        user={"user_id": self.user.id},
                        store=self.store,
                    ))

            persisted = asyncio.run(self.store.get_element(element["id"], self.user.id))
            self.assertEqual([item.id for item in persisted.files], [file_id])
            self.assertTrue(public_file.is_file())
            self.assertEqual([path for path in quarantine_root.rglob("*") if path.is_file()], [])

    def test_delete_defers_task_cancellation_until_commit_has_a_stable_result(self):
        owner_cookie = self._cookie(self.user.id)
        image_root = Path(self.temp.name) / "cancel-delete-elements"
        quarantine_root = (
            image_root.parent.parent
            / f".{image_root.parent.name}-{image_root.name}-quarantine"
        )
        self.assertNotIn(image_root.parent, quarantine_root.parents)
        with patch("app.api.element_api.ELEMENT_MEDIA_ROOT", image_root):
            element = self.client.post(
                "/api/elements",
                json={"kind": "prop", "name": "取消删除道具"},
                cookies=owner_cookie,
            ).json()
            self.client.post(
                f"/api/elements/{element['id']}/files",
                data={"slot": "reference"},
                files={"file": ("reference.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
                cookies=owner_cookie,
            )
            public_file = next(image_root.rglob("*.png"))
            original_commit = AsyncSession.commit

            async def scenario():
                commit_entered = asyncio.Event()
                release_commit = asyncio.Event()

                async def delayed_commit(session):
                    commit_entered.set()
                    self.assertFalse(public_file.exists())
                    await release_commit.wait()
                    await original_commit(session)

                with patch.object(AsyncSession, "commit", delayed_commit):
                    task = asyncio.create_task(delete_element_endpoint(
                        element["id"],
                        user={"user_id": self.user.id},
                        store=self.store,
                    ))
                    await commit_entered.wait()
                    task.cancel()
                    await asyncio.sleep(0)
                    release_commit.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await task

                self.assertIsNone(await self.store.get_element(element["id"], self.user.id))

            asyncio.run(scenario())
            self.assertFalse(public_file.exists())
            self.assertEqual([path for path in quarantine_root.rglob("*") if path.is_file()], [])

    def test_replacement_never_unlinks_other_owner_or_sibling_element_paths(self):
        owner_cookie = self._cookie(self.user.id)
        image_root = Path(self.temp.name) / "safe-replacement-elements"
        with patch("app.api.element_api.ELEMENT_MEDIA_ROOT", image_root):
            sibling = self.client.post(
                "/api/elements",
                json={"kind": "prop", "name": "同账户其他道具"},
                cookies=owner_cookie,
            ).json()
            protected_paths = (
                image_root / self.admin.id / "foreign-element" / "foreign.png",
                image_root / self.user.id / sibling["id"] / "sibling.png",
            )
            for index, protected_path in enumerate(protected_paths):
                target = self.client.post(
                    "/api/elements",
                    json={"kind": "prop", "name": f"替换目标-{index}"},
                    cookies=owner_cookie,
                ).json()
                protected_path.parent.mkdir(parents=True, exist_ok=True)
                protected_path.write_bytes(b"must-survive")
                asyncio.run(self.store.add_element_file(
                    element_id=target["id"],
                    owner_id=self.user.id,
                    slot="reference",
                    storage_path=str(protected_path.relative_to(image_root)),
                    mime_type="image/png",
                    size_bytes=12,
                    sha256=f"protected-{index}",
                ))

                with self.assertLogs("app.api.element_api", level="WARNING") as logs:
                    replaced = self.client.post(
                        f"/api/elements/{target['id']}/files",
                        data={"slot": "reference"},
                        files={"file": ("replacement.png", b"\x89PNG\r\n\x1a\nnew", "image/png")},
                        cookies=owner_cookie,
                    )

                self.assertEqual(replaced.status_code, 200, replaced.text)
                self.assertTrue(protected_path.is_file())
                self.assertTrue(any("replacement cleanup skipped" in entry for entry in logs.output))

    def test_post_commit_close_error_never_restores_deleted_public_files(self):
        owner_cookie = self._cookie(self.user.id)
        image_root = Path(self.temp.name) / "close-error-public" / "elements"
        with patch("app.api.element_api.ELEMENT_MEDIA_ROOT", image_root):
            for delete_whole_asset in (False, True):
                with self.subTest(delete_whole_asset=delete_whole_asset):
                    element = self.client.post(
                        "/api/elements",
                        json={"kind": "prop", "name": f"关闭异常-{delete_whole_asset}"},
                        cookies=owner_cookie,
                    ).json()
                    uploaded = self.client.post(
                        f"/api/elements/{element['id']}/files",
                        data={"slot": "reference"},
                        files={"file": ("reference.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
                        cookies=owner_cookie,
                    ).json()
                    public_file = next(
                        path
                        for path in image_root.rglob("*.png")
                        if element["id"] in path.parts
                    )
                    original_close = AsyncSession.close

                    async def close_then_fail(session):
                        await original_close(session)
                        raise RuntimeError("close failed after commit")

                    with patch.object(AsyncSession, "close", close_then_fail):
                        with self.assertRaisesRegex(RuntimeError, "close failed after commit"):
                            if delete_whole_asset:
                                asyncio.run(delete_element_endpoint(
                                    element["id"],
                                    user={"user_id": self.user.id},
                                    store=self.store,
                                ))
                            else:
                                asyncio.run(delete_element_file_endpoint(
                                    element["id"],
                                    uploaded["files"][0]["id"],
                                    user={"user_id": self.user.id},
                                    store=self.store,
                                ))

                    persisted = asyncio.run(self.store.get_element(element["id"], self.user.id))
                    if delete_whole_asset:
                        self.assertIsNone(persisted)
                    else:
                        self.assertEqual(persisted.files, [])
                    self.assertFalse(public_file.exists())

    def test_partial_quarantine_restore_failure_keeps_durable_path_manifest(self):
        owner_cookie = self._cookie(self.user.id)
        image_root = Path(self.temp.name) / "partial-public" / "elements"
        quarantine_root = Path(self.temp.name) / ".partial-public-elements-quarantine"
        with patch("app.api.element_api.ELEMENT_MEDIA_ROOT", image_root):
            element = self.client.post(
                "/api/elements",
                json={"kind": "prop", "name": "部分隔离失败"},
                cookies=owner_cookie,
            ).json()
            for slot in ("reference", "detail"):
                self.client.post(
                    f"/api/elements/{element['id']}/files",
                    data={"slot": slot},
                    files={"file": (f"{slot}.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
                    cookies=owner_cookie,
                )
            public_files = tuple(sorted(path.resolve() for path in image_root.rglob("*.png")))
            real_replace = os.replace
            moved_public_file = None

            def fail_second_move_and_restore(source, destination):
                nonlocal moved_public_file
                source_path = Path(source).resolve()
                if source_path in public_files:
                    if moved_public_file is None:
                        moved_public_file = source_path
                        return real_replace(source, destination)
                    raise OSError("second quarantine move failed")
                if source_path.suffix == ".tmp":
                    return real_replace(source, destination)
                raise OSError("quarantine restore failed")

            with (
                patch("app.api.element_api.os.replace", side_effect=fail_second_move_and_restore),
                self.assertLogs("app.api.element_api", level="ERROR") as logs,
                self.assertRaises(HTTPException),
            ):
                asyncio.run(delete_element_endpoint(
                    element["id"],
                    user={"user_id": self.user.id},
                    store=self.store,
                ))

            persisted = asyncio.run(self.store.get_element(element["id"], self.user.id))
            self.assertEqual(len(persisted.files), 2)
            self.assertIsNotNone(moved_public_file)
            self.assertFalse(moved_public_file.exists())
            manifests = list(quarantine_root.rglob("*.json"))
            self.assertGreaterEqual(len(manifests), 1)
            durable_mappings = [json.loads(path.read_text()) for path in manifests]
            stranded = next(
                mapping
                for mapping in durable_mappings
                if Path(mapping["quarantined_path"]).exists()
            )
            self.assertEqual(Path(stranded["original_path"]), moved_public_file)
            self.assertTrue(any(str(moved_public_file) in entry for entry in logs.output))
            self.assertTrue(any(stranded["quarantined_path"] in entry for entry in logs.output))

    def test_replacement_purge_failure_keeps_old_file_non_public_and_tracked(self):
        owner_cookie = self._cookie(self.user.id)
        image_root = Path(self.temp.name) / "replacement-public" / "elements"
        quarantine_root = Path(self.temp.name) / ".replacement-public-elements-quarantine"
        with patch("app.api.element_api.ELEMENT_MEDIA_ROOT", image_root):
            element = self.client.post(
                "/api/elements",
                json={"kind": "prop", "name": "替换清理失败"},
                cookies=owner_cookie,
            ).json()
            self.client.post(
                f"/api/elements/{element['id']}/files",
                data={"slot": "reference"},
                files={"file": ("old.png", b"\x89PNG\r\n\x1a\nold", "image/png")},
                cookies=owner_cookie,
            )
            old_public_file = next(image_root.rglob("*.png"))
            old_public_path = old_public_file.resolve()

            with (
                patch("app.api.element_api._remove_file", return_value=False),
                self.assertLogs("app.api.element_api", level="WARNING") as logs,
            ):
                replaced = self.client.post(
                    f"/api/elements/{element['id']}/files",
                    data={"slot": "reference"},
                    files={"file": ("new.png", b"\x89PNG\r\n\x1a\nnew", "image/png")},
                    cookies=owner_cookie,
                )

            self.assertEqual(replaced.status_code, 200, replaced.text)
            self.assertFalse(old_public_file.exists())
            self.assertEqual(len(list(image_root.rglob("*.png"))), 1)
            manifests = list(quarantine_root.rglob("*.json"))
            self.assertEqual(len(manifests), 1)
            mapping = json.loads(manifests[0].read_text())
            self.assertEqual(Path(mapping["original_path"]), old_public_path)
            self.assertTrue(Path(mapping["quarantined_path"]).exists())
            self.assertTrue(any(str(old_public_path) in entry for entry in logs.output))

    def test_user_center_and_sandbox_payment_are_operational(self):
        cookie = self._cookie(self.user.id)
        center = self.client.get("/api/users/me", cookies=cookie)
        self.assertEqual(center.status_code, 200)
        self.assertEqual(center.json()["user"]["role"], "user")

        plans = self.client.get("/api/billing/plans").json()["items"]
        order = self.client.post(
            "/api/billing/orders",
            json={"plan_id": plans[0]["id"], "provider": "sandbox", "idempotency_key": "api-order-once"},
            cookies=cookie,
        )
        self.assertEqual(order.status_code, 200, order.text)
        paid = self.client.post(
            f"/api/billing/orders/{order.json()['id']}/sandbox-confirm", cookies=cookie
        )
        self.assertEqual(paid.status_code, 200, paid.text)
        self.assertEqual(paid.json()["status"], "paid")
        wallet = self.client.get("/api/billing/wallet", cookies=cookie)
        self.assertEqual(wallet.status_code, 200)
        self.assertEqual(int(wallet.json()["points"]), plans[0]["points"])

    def test_security_headers_and_origin_boundary_are_enforced(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        rejected = self.client.post(
            "/api/auth/logout",
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(rejected.json()["detail"], "请求来源不受信任")


if __name__ == "__main__":
    unittest.main()

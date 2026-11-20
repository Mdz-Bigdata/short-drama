import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.api import appearance_api
from app.api.auth_api import get_current_user
from app.core import appearance
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore


def picture(kind="PNG", size=(64, 32)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 40, 40)).save(out, format=kind)
    return out.getvalue()


class TextTest(unittest.TestCase):
    def test_text_is_kept_on_one_line_and_an_empty_field_means_the_built_in_wording(self):
        kept = appearance.updated({}, text={"brand_name": "  青岚\n影业 \x07", "login_tagline": ""}, logo_frame="circle")
        self.assertEqual(kept["brand_name"], "青岚 影业")
        view = appearance.public_view(kept, asset_base="/a", root=Path("/nonexistent"))
        self.assertEqual(view["brand_name"], "青岚 影业")
        self.assertIsNone(view["login_tagline"])
        self.assertIsNone(view["assistant_name"])
        self.assertEqual(view["logo_frame"], "circle")
        self.assertTrue(view["customised"])

    def test_nothing_set_is_the_built_in_appearance(self):
        view = appearance.public_view({}, asset_base="/a", root=Path("/nonexistent"))
        self.assertEqual(view["assets"], {})
        self.assertFalse(view["customised"])
        self.assertEqual(view["logo_frame"], "rounded")
        self.assertTrue(all(view[name] is None for name in appearance.fields()))

    def test_what_does_not_fit_is_refused(self):
        limit = appearance.fields()["brand_name"]["max"]
        for text, frame, said in (
            ({"brand_name": "名" * (limit + 1)}, None, str(limit)),
            ({"owner_email": "x"}, None, "没有这一项"),
            ({}, "hexagon", "没有这种外框"),
        ):
            with self.assertRaises(appearance.AppearanceError) as refused:
                appearance.updated({}, text=text, logo_frame=frame)
            self.assertIn(said, str(refused.exception))

    def test_the_public_view_holds_no_internal_detail(self):
        with tempfile.TemporaryDirectory() as folder:
            kept = appearance.store_image({"brand_name": "青岚"}, "logo", picture(), root=Path(folder))
            view = appearance.public_view(kept, asset_base="/api/public/appearance/assets", root=Path(folder))
        self.assertEqual(set(view), {*appearance.fields(), "logo_frame", "assets", "customised"})
        self.assertRegex(view["assets"]["logo"], r"^/api/public/appearance/assets/logo\?v=[0-9a-f]{12}$")
        self.assertNotIn(folder, repr(view))


class ImageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_png_jpeg_and_webp_are_kept_and_replace_the_slots_old_file(self):
        kept = appearance.store_image({}, "logo", picture("PNG"), root=self.root)
        self.assertEqual(kept["images"]["logo"]["mime"], "image/png")
        kept = appearance.store_image(kept, "logo", picture("WEBP"), root=self.root)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["logo.webp"])
        found = appearance.image(kept, "logo", root=self.root)
        self.assertEqual((found.mime, found.path.name), ("image/webp", "logo.webp"))
        kept = appearance.store_image(kept, "favicon", picture("JPEG", (32, 32)), root=self.root)
        self.assertEqual(kept["images"]["favicon"]["width"], 32)

    def test_svg_text_oversize_and_huge_images_are_refused(self):
        rule = appearance.slots()["favicon"]
        cases = (
            (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "只收 PNG"),
            (b"GIF89a" + b"\0" * 40, "只收 PNG"),
            (picture("GIF"), "只收 PNG"),
            (b"\0" * (rule["max_bytes"] + 1), "最大"),
            (picture("PNG", (rule["max_side"] + 1, 8)), "像素"),
        )
        for data, said in cases:
            with self.assertRaises(appearance.AppearanceError) as refused:
                appearance.store_image({}, "favicon", data, root=self.root)
            self.assertIn(said, str(refused.exception))
        with self.assertRaises(appearance.AppearanceError):
            appearance.store_image({}, "../../etc", picture(), root=self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_removed_or_missing_file_is_not_offered(self):
        kept = appearance.store_image({}, "logo", picture(), root=self.root)
        (self.root / "logo.png").unlink()
        self.assertIsNone(appearance.image(kept, "logo", root=self.root))
        self.assertEqual(appearance.public_view(kept, asset_base="/a", root=self.root)["assets"], {})
        kept = appearance.store_image(kept, "logo", picture(), root=self.root)
        gone = appearance.remove_image(kept, "logo", root=self.root)
        self.assertNotIn("logo", gone["images"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_stored_file_name_cannot_point_outside_the_folder(self):
        outside = self.root.parent / "appearance-outside-test.png"
        self.assertIsNone(appearance.image({"images": {"logo": {"file": f"../{outside.name}"}}}, "logo", root=self.root))


class AppearanceApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'api.sqlite3'}")
        asyncio.run(self.store.create_schema())
        patch = mock.patch.object(appearance, "storage_dir", return_value=Path(self.temp.name) / "appearance")
        patch.start()
        self.addCleanup(patch.stop)
        self.app = FastAPI()
        self.app.include_router(appearance_api.public_router)
        self.app.include_router(appearance_api.router)
        self.app.dependency_overrides[get_platform_store] = lambda: self.store
        self.client = TestClient(self.app)

    def _sign_in(self, *permissions):
        self.app.dependency_overrides[get_current_user] = lambda: {"user_id": "admin-1", "username": "a", "permissions": list(permissions)}

    def test_anyone_reads_the_brand_and_only_an_administrator_changes_it(self):
        public = self.client.get("/api/public/appearance")
        self.assertEqual(public.status_code, 200)
        self.assertFalse(public.json()["customised"])
        self.assertEqual(self.client.put("/api/platform/appearance", json={"text": {"brand_name": "x"}}).status_code, 401)
        self._sign_in()
        self.assertEqual(self.client.put("/api/platform/appearance", json={"text": {"brand_name": "x"}}).status_code, 403)
        self.assertEqual(self.client.post("/api/platform/appearance/assets/logo", files={"file": ("l.png", picture(), "image/png")}).status_code, 403)

    def test_an_administrator_sets_text_and_a_logo_that_the_public_route_serves(self):
        self._sign_in("capability:manage")
        changed = self.client.put("/api/platform/appearance", json={"text": {"brand_name": "青岚影业", "lobby_tagline": "短剧工作室"}, "logo_frame": "circle"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual([item["id"] for item in changed.json()["slots"]], ["logo", "favicon"])
        uploaded = self.client.post("/api/platform/appearance/assets/logo", files={"file": ("l.png", picture(), "image/png")})
        self.assertEqual(uploaded.status_code, 200)
        public = self.client.get("/api/public/appearance").json()
        self.assertEqual((public["brand_name"], public["lobby_tagline"], public["logo_frame"]), ("青岚影业", "短剧工作室", "circle"))
        served = self.client.get(public["assets"]["logo"])
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.headers["content-type"], "image/png")
        self.assertIn("immutable", served.headers["cache-control"])
        self.assertEqual(served.content, picture())
        self.assertIn("max-age=300", self.client.get("/api/public/appearance/assets/logo").headers["cache-control"])
        removed = self.client.delete("/api/platform/appearance/assets/logo")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.client.get("/api/public/appearance/assets/logo").status_code, 404)

    def test_refusals_say_why(self):
        self._sign_in("capability:manage")
        bad = self.client.post("/api/platform/appearance/assets/logo", files={"file": ("l.svg", b"<svg/>", "image/svg+xml")})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("PNG", bad.json()["detail"])
        self.assertEqual(self.client.put("/api/platform/appearance", json={"logo_frame": "star"}).status_code, 422)
        self.assertEqual(self.client.get("/api/public/appearance/assets/nothing").status_code, 404)


if __name__ == "__main__":
    unittest.main()

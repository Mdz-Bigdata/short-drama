import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.auth_api import auth_service
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from main import app


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

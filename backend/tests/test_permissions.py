# -*- coding: utf-8 -*-
"""The permission system: the role matrix cell by cell, the routes that enforce it, and the audit it leaves."""

import asyncio
import sqlite3
import tempfile
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import patch

import anyio
import anyio.to_thread
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.auth_api import _public_user, get_current_user
from app.platform import access_audit
from app.platform.dependencies import get_platform_store
from app.platform.models import PlatformUser
from app.platform.permissions import (
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    SUPER_ADMIN,
    authorize,
    has_permission,
    legacy_role,
    permissions_for,
)
from app.platform.store import PlatformStore

# The table in docs/access-and-billing/DESIGN.md section 3.3, written out on its own so a change to the code has to
# change this too. Columns: super_admin, ops, finance, support, auditor.
MATRIX = {
    "role:assign":           "S....",
    "user:read":             "S.FSA",
    "user:manage":           "S..S.",
    "model_config:manage":   "SO...",
    "skill:manage":          "SO...",
    "market:manage":         "SO...",
    "capability:manage":     "SO...",
    "project:read_any":      "SO.SA",
    "project:write_any":     "SO...",
    "pricing:manage":        "S.F..",
    "order:read_any":        "S.FSA",
    "refund:request":        "S.FS.",
    "refund:approve":        "S.F..",
    "wallet:adjust_request": "S.FS.",
    "wallet:adjust_approve": "S.F..",
    "recon:read":            "S.F.A",
    "recon:resolve":         "S.F..",
    "payment:configure":     "S....",
    "audit:read":            "S.F.A",
}
ROLES = ("super_admin", "ops", "finance", "support", "auditor")

# Routes that need no login, and why. Anything new has to be added here on purpose.
PUBLIC_ROUTES = {
    ("POST", "/api/auth/send_code"), ("POST", "/api/auth/register"), ("POST", "/api/auth/login_password"),
    ("POST", "/api/auth/login_code"), ("GET", "/api/auth/session"), ("POST", "/api/auth/logout"),
    ("GET", "/api/billing/plans"),
    ("POST", "/api/billing/webhooks/{provider}"),  # signed by the payment channel
    ("POST", "/mcp"), ("GET", "/mcp"),  # bearer token, checked inside
    ("GET", "/api/agent/projects/{project_id}/artifacts"),  # agent key
    ("POST", "/api/agent/projects/{project_id}/artifacts"),
    ("POST", "/api/agent/projects/{project_id}/jobs"),
    ("GET", "/api/agent/jobs/{job_id}"),
    ("GET", "/"),
}


def actor(*roles, user_id="me", **extra):
    return {
        "user_id": user_id, "roles": list(roles), "permissions": sorted(permissions_for(roles)), "status": "active",
        **extra,
    }


class MatrixTest(unittest.TestCase):
    def test_every_cell(self):
        self.assertEqual(set(MATRIX), set(ALL_PERMISSIONS))
        self.assertEqual(set(ROLES), set(ROLE_PERMISSIONS))
        for permission, cells in MATRIX.items():
            for role, cell in zip(ROLES, cells):
                with self.subTest(role=role, permission=permission):
                    self.assertEqual(permission in ROLE_PERMISSIONS[role], cell != ".")

    def test_a_customer_has_nothing(self):
        self.assertEqual(permissions_for([]), frozenset())
        self.assertEqual(permissions_for(["no-such-role"]), frozenset())

    def test_roles_add_up(self):
        self.assertEqual(permissions_for(["ops", "auditor"]), ROLE_PERMISSIONS["ops"] | ROLE_PERMISSIONS["auditor"])

    def test_only_a_super_admin_reads_as_the_old_admin(self):
        self.assertEqual(legacy_role(["super_admin", "ops"]), "admin")
        self.assertEqual(legacy_role(["ops"]), "user")
        self.assertEqual(legacy_role([]), "user")


class AuthorizeTest(unittest.TestCase):
    def test_a_suspended_account_gets_nothing_even_on_its_own_things(self):
        decision = authorize({**actor(SUPER_ADMIN), "status": "suspended"}, owner_id="me")
        self.assertEqual((decision.allowed, decision.status), (False, 401))

    def test_a_missing_permission_is_403(self):
        decision = authorize(actor("support"), permission="refund:approve")
        self.assertEqual((decision.allowed, decision.status, decision.reason), (False, 403, "permission_denied"))

    def test_a_permission_waits_for_the_password_change(self):
        decision = authorize(actor(SUPER_ADMIN, must_change_password=True), permission="user:read")
        self.assertEqual((decision.allowed, decision.reason), (False, "must_change_password"))

    def test_your_own_things_need_no_role_and_are_not_audited(self):
        decision = authorize(actor(), owner_id="me", write=True)
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.cross_account)

    def test_someone_elses_things_look_like_they_do_not_exist(self):
        decision = authorize(actor(), owner_id="other")
        self.assertEqual((decision.allowed, decision.status), (False, 404))

    def test_reading_and_writing_someone_elses_things_are_separate(self):
        support = actor("support")
        self.assertTrue(authorize(support, owner_id="other").cross_account)
        self.assertFalse(authorize(support, owner_id="other", write=True).allowed)
        ops = authorize(actor("ops"), owner_id="other", write=True)
        self.assertTrue(ops.allowed and ops.cross_account)

    def test_finance_cannot_open_projects(self):
        self.assertFalse(authorize(actor("finance"), owner_id="other").allowed)

    def test_something_with_no_owner_on_record_is_only_for_operators(self):
        self.assertFalse(authorize(actor(), owner_id="").allowed)
        self.assertTrue(authorize(actor("ops"), owner_id="").allowed)

    def test_an_operator_who_has_not_changed_the_first_password_cannot_cross_accounts(self):
        self.assertFalse(authorize(actor(SUPER_ADMIN, must_change_password=True), owner_id="other").allowed)

    def test_a_hand_built_actor_reads_the_old_way(self):
        self.assertTrue(has_permission({"user_id": "a", "role": "admin"}, "role:assign"))
        self.assertFalse(has_permission({"user_id": "a", "role": "user"}, "user:read"))
        self.assertFalse(has_permission({"user_id": "a", "role": "admin", "permissions": []}, "user:read"))


class RouteScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from main import app
        cls.routes = [route for route in app.routes if isinstance(route, APIRoute)]

    @staticmethod
    def _dependencies(dependant, found=None):
        found = found if found is not None else []
        for item in dependant.dependencies:
            found.append(item.call)
            RouteScanTest._dependencies(item, found)
        return found

    def test_every_admin_route_names_a_permission_that_exists(self):
        admin_routes = [route for route in self.routes if route.path.startswith("/api/admin/")]
        self.assertTrue(admin_routes)
        for route in admin_routes:
            names = [getattr(call, "required_permission", None) for call in self._dependencies(route.dependant)]
            declared = [name for name in names if name]
            self.assertTrue(declared, f"{route.path} declares no permission")

    def test_every_declared_permission_is_a_real_one(self):
        for route in self.routes:
            for call in self._dependencies(route.dependant):
                name = getattr(call, "required_permission", None)
                if name:
                    self.assertIn(name, ALL_PERMISSIONS, route.path)

    def test_a_route_with_no_login_is_on_the_list(self):
        unprotected = {
            (method, route.path)
            for route in self.routes if get_current_user not in self._dependencies(route.dependant)
            for method in route.methods
        }
        self.assertEqual(unprotected - PUBLIC_ROUTES, set(), "a new route without login: protect it or list it here")

    def test_the_old_all_or_nothing_check_is_gone(self):
        import app.api.auth_api as auth_api
        self.assertFalse(hasattr(auth_api, "require_admin"))


class _ApiCase(unittest.IsolatedAsyncioTestCase):
    """The real application and store, with the login replaced by what a real login returns."""

    async def asyncSetUp(self):
        from main import app
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'platform.sqlite3'}")
        self.addAsyncCleanup(self.store.close)
        await self.store.create_schema()
        self.app = app
        self.app.dependency_overrides[get_platform_store] = lambda: self.store
        self.addCleanup(self.app.dependency_overrides.clear)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        access_audit._recent_reads.clear()


class RoleApiTests(_ApiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.boss, _ = await self.store.create_user(
            email="boss@example.com", phone=None, password="boss-password", role="admin",
        )
        self.customer, _ = await self.store.create_user(
            email="customer@example.com", phone=None, password="customer-password",
        )

    async def _login(self, user):
        fresh = await self.store.get_user(user.id)
        self.app.dependency_overrides[get_current_user] = lambda: _public_user(fresh)

    async def _staff(self, *roles, email):
        user, _ = await self.store.create_user(email=email, phone=None, password="staff-password")
        await self.store.set_user_roles(self.boss.id, user.id, list(roles))
        await self._login(user)
        return user

    async def test_the_login_says_what_someone_can_do(self):
        await self._login(self.boss)
        body = self.client.get("/api/users/me").json()["user"]
        self.assertEqual((body["role"], body["roles"]), ("admin", ["super_admin"]))
        self.assertIn("role:assign", body["permissions"])
        await self._login(self.customer)
        body = self.client.get("/api/users/me").json()["user"]
        self.assertEqual((body["role"], body["roles"], body["permissions"]), ("user", [], []))

    async def test_each_route_answers_by_permission(self):
        cases = (
            ("/api/admin/users", {"super_admin", "finance", "support", "auditor"}),
            ("/api/admin/roles", {"super_admin", "finance", "support", "auditor"}),
            ("/api/admin/audit-events", {"super_admin", "finance", "auditor"}),
        )
        for index, role in enumerate(ROLES):
            await self._staff(role, email=f"staff{index}@example.com")
            for path, allowed in cases:
                with self.subTest(role=role, path=path):
                    status = self.client.get(path).status_code
                    self.assertEqual(status, 200 if role in allowed else 403)
        await self._login(self.customer)
        for path, _allowed in cases:
            self.assertEqual(self.client.get(path).status_code, 403, path)

    async def test_the_role_catalog_comes_from_the_matrix(self):
        await self._login(self.boss)
        items = self.client.get("/api/admin/roles").json()["items"]
        self.assertEqual([item["role"] for item in items], list(ROLES))
        self.assertEqual(set(items[1]["permissions"]), ROLE_PERMISSIONS["ops"])

    async def test_granting_roles_takes_effect_and_is_audited(self):
        await self._login(self.boss)
        response = self.client.put(f"/api/admin/users/{self.customer.id}/roles", json={"roles": ["finance", "support"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["roles"], ["finance", "support"])
        self.assertIn("refund:approve", response.json()["user"]["permissions"])
        events = self.client.get("/api/admin/audit-events").json()["items"]
        change = next(item for item in events if item["action"] == "user.roles_change")
        self.assertEqual((change["actor_id"], change["resource_id"]), (self.boss.id, self.customer.id))
        self.assertEqual(change["details"], {"previous": [], "new": ["finance", "support"]})
        cleared = self.client.put(f"/api/admin/users/{self.customer.id}/roles", json={"roles": []})
        self.assertEqual(cleared.json()["user"]["permissions"], [])

    async def test_only_role_assign_can_grant_roles(self):
        await self._staff("support", email="support@example.com")
        response = self.client.put(f"/api/admin/users/{self.customer.id}/roles", json={"roles": ["finance"]})
        self.assertEqual(response.status_code, 403)

    async def test_an_unknown_role_is_refused(self):
        await self._login(self.boss)
        response = self.client.put(f"/api/admin/users/{self.customer.id}/roles", json={"roles": ["god"]})
        self.assertEqual(response.status_code, 422)

    async def test_the_last_super_admin_cannot_go(self):
        await self._login(self.boss)
        removed = self.client.put(f"/api/admin/users/{self.boss.id}/roles", json={"roles": ["ops"]})
        self.assertEqual(removed.status_code, 422)
        suspended = self.client.patch(f"/api/admin/users/{self.boss.id}", json={"status": "suspended"})
        self.assertEqual(suspended.status_code, 422)
        self.client.put(f"/api/admin/users/{self.customer.id}/roles", json={"roles": ["super_admin"]})
        self.assertEqual(self.client.put(f"/api/admin/users/{self.boss.id}/roles", json={"roles": []}).status_code, 200)

    async def test_a_suspended_super_admin_does_not_count_as_the_one_left(self):
        await self._login(self.boss)
        self.client.put(f"/api/admin/users/{self.customer.id}/roles", json={"roles": ["super_admin"]})
        self.assertEqual(self.client.patch(f"/api/admin/users/{self.customer.id}", json={"status": "suspended"}).status_code, 200)
        self.assertEqual(self.client.put(f"/api/admin/users/{self.boss.id}/roles", json={"roles": []}).status_code, 422)

    async def test_support_can_suspend_customers_but_not_staff(self):
        other = await self._staff("ops", email="ops@example.com")
        await self._staff("support", email="support@example.com")
        self.assertEqual(self.client.patch(f"/api/admin/users/{self.customer.id}", json={"status": "suspended"}).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/admin/users/{other.id}", json={"status": "suspended"}).status_code, 403)

    async def test_the_old_way_of_changing_a_role_is_refused_not_ignored(self):
        await self._login(self.boss)
        response = self.client.patch(f"/api/admin/users/{self.customer.id}", json={"role": "admin", "status": "active"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.store.get_user(self.customer.id)).roles, [])

    async def test_the_old_column_alone_grants_nothing(self):
        async with self.store.sessions() as session:
            (await session.get(PlatformUser, self.customer.id)).role = "admin"
            await session.commit()
        await self._login(self.customer)
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)


class ProjectAccessAuditTests(_ApiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        from app.api import drama_api
        self.guard = drama_api.require_owned_drama_task
        patcher = patch.object(
            drama_api.service.repo, "get_task",
            side_effect=lambda task_id: {"task_id": task_id, "owner_user_id": "owner-1"} if task_id == "t1" else None,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _check(self, method, user):
        request = Request({
            "type": "http", "method": method, "path": "/api/drama/t1/status", "path_params": {"task_id": "t1"},
            "headers": [], "query_string": b"", "scheme": "http", "server": ("x", 80),
        })
        return self.guard(request, user, self.store)

    async def _events(self):
        return (await self.store.list_audit_events(1, 50))[0]

    async def test_the_owner_is_let_in_and_nothing_is_written(self):
        await self._check("GET", actor(user_id="owner-1"))
        self.assertEqual(await self._events(), [])

    async def test_a_stranger_gets_404(self):
        with self.assertRaises(HTTPException) as caught:
            await self._check("GET", actor(user_id="stranger"))
        self.assertEqual(caught.exception.status_code, 404)

    async def test_support_reads_with_a_record_and_polling_does_not_flood_it(self):
        for _ in range(5):
            await self._check("GET", actor("support", user_id="staff-1"))
        events = await self._events()
        self.assertEqual([event.action for event in events], ["project.cross_account_read"])
        self.assertEqual((events[0].actor_id, events[0].resource_id), ("staff-1", "t1"))
        self.assertEqual(events[0].details["owner_id"], "owner-1")

    async def test_support_cannot_change_someone_elses_project(self):
        with self.assertRaises(HTTPException) as caught:
            await self._check("POST", actor("support", user_id="staff-1"))
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(await self._events(), [])

    async def test_every_write_by_an_operator_is_recorded(self):
        for _ in range(3):
            await self._check("POST", actor("ops", user_id="staff-2"))
        self.assertEqual([event.action for event in await self._events()], ["project.cross_account_write"] * 3)

    async def test_a_hand_built_actor_writes_nothing(self):
        await self._check("POST", {"user_id": "x", "role": "admin"})
        self.assertEqual(await self._events(), [])

    async def test_from_a_worker_thread_it_reaches_the_table(self):
        with patch("app.platform.dependencies.get_platform_store", return_value=self.store):
            await anyio.to_thread.run_sync(partial(
                access_audit.record_access_from_thread, actor("ops", user_id="staff-3"),
                resource_id="t1", owner_id="owner-1", write=True, via="agent.update_shot",
            ))
        events = await self._events()
        self.assertEqual([(event.actor_id, event.details["via"]) for event in events], [("staff-3", "agent.update_shot")])

    async def test_out_of_reach_of_the_event_loop_it_goes_to_the_log(self):
        with self.assertLogs("app.platform.access_audit", level="WARNING"):
            await asyncio.to_thread(
                access_audit.record_access_from_thread, actor("ops"),
                resource_id="t1", owner_id="o", write=True, via="test",
            )


class MigrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_existing_admins_become_super_admins_and_editors_become_users(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "platform.sqlite3"
            store = PlatformStore(f"sqlite+aiosqlite:///{path}")
            await store.create_schema()
            await store.close()
            connection = sqlite3.connect(path)
            connection.execute("UPDATE alembic_version SET version_num = '0002_keep_financial_records'")
            for user_id, role in (("a1", "admin"), ("e1", "editor"), ("u1", "user")):
                connection.execute(
                    "INSERT INTO platform_users (id, username, email, password_hash, role, status, "
                    "must_change_password, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'h', ?, 'active', 0, '2026-01-01', '2026-01-01')",
                    (user_id, user_id, f"{user_id}@x.test", role),
                )
            connection.commit()
            connection.close()
            store = PlatformStore(f"sqlite+aiosqlite:///{path}")
            await store.create_schema()
            await store.create_schema()
            admin, editor, plain = [await store.get_user(user_id) for user_id in ("a1", "e1", "u1")]
            self.assertEqual((admin.roles, editor.roles, plain.roles), (["super_admin"], [], []))
            self.assertEqual(editor.role, "user")
            await store.close()


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from app.core.capability_manifest import UPSTREAM_CAPABILITIES
from app.platform.bootstrap import initialize_platform
from app.platform.models import PaymentOrder
from app.platform.store import PlatformStore


class PlatformStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db_path = Path(self.temp.name) / "platform.sqlite3"
        self.store = PlatformStore(f"sqlite+aiosqlite:///{db_path}")
        await self.store.create_schema()

    async def asyncTearDown(self):
        await self.store.close()
        self.temp.cleanup()

    async def test_bootstrap_admin_is_idempotent_and_requires_password_change(self):
        first, created = await self.store.bootstrap_admin(
            "admin@123", login="admin@short-drama"
        )
        second, created_again = await self.store.bootstrap_admin(
            "must-not-replace", login="admin@short-drama"
        )

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.email, "admin@short-drama")
        self.assertEqual(first.role, "admin")
        self.assertTrue(first.must_change_password)
        self.assertTrue(await self.store.verify_login("admin@short-drama", "admin@123"))
        self.assertFalse(await self.store.verify_login("admin@short-drama", "must-not-replace"))

    async def test_development_bootstrap_uses_configured_default_and_production_rejects_it(self):
        with patch.dict("os.environ", {
            "ENVIRONMENT": "development",
            "BOOTSTRAP_ADMIN": "1",
            "BOOTSTRAP_ADMIN_LOGIN": "admin@short-drama",
            "BOOTSTRAP_ADMIN_PASSWORD": "admin@123",
        }, clear=False):
            result = await initialize_platform(self.store)
        self.assertTrue(result["admin_created"])
        self.assertEqual(result["admin_login"], "admin@short-drama")
        self.assertTrue(await self.store.verify_login("admin@short-drama", "admin@123"))

        other_temp = tempfile.TemporaryDirectory()
        other = PlatformStore(f"sqlite+aiosqlite:///{Path(other_temp.name) / 'production.sqlite3'}")
        try:
            with patch.dict("os.environ", {
                "ENVIRONMENT": "production",
                "BOOTSTRAP_ADMIN": "1",
                "BOOTSTRAP_ADMIN_LOGIN": "admin@short-drama",
                "BOOTSTRAP_ADMIN_PASSWORD": "admin@123",
            }, clear=False):
                with self.assertRaisesRegex(RuntimeError, "默认管理员密码"):
                    await initialize_platform(other)
        finally:
            await other.close()
            other_temp.cleanup()

    async def test_every_declared_capability_has_a_unique_global_command(self):
        await self.store.seed_capabilities()
        items = await self.store.list_capabilities()
        expected = sum(len(source["capabilities"]) for source in UPSTREAM_CAPABILITIES)

        self.assertEqual(len(items), expected)
        self.assertEqual(len({item.command for item in items}), expected)
        self.assertTrue(all(item.command.startswith("/") for item in items))
        self.assertTrue(all(item.enabled for item in items))

        target = items[0]
        resolved = await self.store.resolve_command(f"{target.command} 雨夜追车")
        self.assertEqual(resolved.capability_id, target.capability_id)
        self.assertEqual(resolved.payload, "雨夜追车")

        await self.store.set_capability_enabled(
            target.source_id, target.capability_id, False, actor_id=None
        )
        with self.assertRaises(ValueError):
            await self.store.resolve_command(target.command)
        with self.assertRaises(ValueError):
            await self.store.resolve_command("/../../bin/sh")

    async def test_actor_readiness_requires_exact_ordered_five_views(self):
        user, _ = await self.store.create_user(
            email="actor-owner@example.com", phone=None, password="owner-password"
        )
        actor = await self.store.create_element(
            owner_id=user.id, kind="actor", name="林夏", description="女主角"
        )
        self.assertEqual(actor.status, "draft")

        slots = [
            "front", "front_three_quarter", "profile",
            "rear_three_quarter", "back",
        ]
        for index, slot in enumerate(slots):
            actor = await self.store.add_element_file(
                element_id=actor.id,
                owner_id=user.id,
                slot=slot,
                storage_path=f"safe/{slot}.png",
                mime_type="image/png",
                size_bytes=100 + index,
                sha256=f"hash-{index}",
            )
        self.assertEqual(actor.status, "ready")
        self.assertEqual([item.slot for item in actor.files], slots)

        with self.assertRaises(ValueError):
            await self.store.add_element_file(
                element_id=actor.id,
                owner_id=user.id,
                slot="left_profile",
                storage_path="safe/bad.png",
                mime_type="image/png",
                size_bytes=10,
                sha256="bad",
            )

    async def test_ledger_and_payment_confirmation_are_append_only_and_idempotent(self):
        user, _ = await self.store.create_user(
            email="buyer@example.com", phone=None, password="buyer-password"
        )
        await self.store.seed_billing_plans()
        plans = await self.store.list_plans()
        order = await self.store.create_order(
            user_id=user.id,
            plan_id=plans[0].id,
            provider="sandbox",
            idempotency_key="order-once",
        )
        same_order = await self.store.create_order(
            user_id=user.id,
            plan_id=plans[0].id,
            provider="sandbox",
            idempotency_key="order-once",
        )
        self.assertEqual(order.id, same_order.id)

        paid = await self.store.confirm_paid_order(order.id, "sandbox:event-1")
        paid_again = await self.store.confirm_paid_order(order.id, "sandbox:event-1")
        self.assertEqual(paid.status, "paid")
        self.assertEqual(paid.id, paid_again.id)

        wallet = await self.store.wallet(user.id)
        self.assertEqual(wallet.points, Decimal(str(plans[0].points)))
        self.assertEqual(len(wallet.entries), 1)

    async def test_provider_webhook_matches_order_facts_and_is_idempotent(self):
        user, _ = await self.store.create_user(
            email="webhook@example.com", phone=None, password="webhook-password"
        )
        await self.store.seed_billing_plans()
        plan = (await self.store.list_plans())[0]
        async with self.store.sessions() as session:
            order = PaymentOrder(
                user_id=user.id,
                plan_id=plan.id,
                provider="wechat",
                amount=plan.price,
                currency=plan.currency,
                status="pending",
                idempotency_key="provider-webhook-order",
            )
            session.add(order)
            await session.commit()
            order_id = order.id

        paid, applied = await self.store.process_webhook_payment(
            provider="wechat",
            event_id="wechat-event-1",
            order_id=order_id,
            amount=plan.price,
            currency=plan.currency,
            payload_sha256="a" * 64,
        )
        same, applied_again = await self.store.process_webhook_payment(
            provider="wechat",
            event_id="wechat-event-1",
            order_id=order_id,
            amount=plan.price,
            currency=plan.currency,
            payload_sha256="a" * 64,
        )
        self.assertTrue(applied)
        self.assertFalse(applied_again)
        self.assertEqual(paid.id, same.id)
        self.assertEqual((await self.store.wallet(user.id)).points, Decimal(plan.points))

        with self.assertRaises(ValueError):
            await self.store.process_webhook_payment(
                provider="wechat",
                event_id="wechat-event-wrong-amount",
                order_id=order_id,
                amount=plan.price + Decimal("1.00"),
                currency=plan.currency,
                payload_sha256="b" * 64,
            )


if __name__ == "__main__":
    unittest.main()

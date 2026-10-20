import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from app.core.capability_manifest import UPSTREAM_CAPABILITIES
from app.platform.bootstrap import initialize_platform
from app.platform.models import PaymentOrder, RegenerationRequest
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
            stored = await self.store.add_element_file(
                element_id=actor.id,
                owner_id=user.id,
                slot=slot,
                storage_path=f"safe/{slot}.png",
                mime_type="image/png",
                size_bytes=100 + index,
                sha256=f"hash-{index}",
            )
            actor = stored.element
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

    async def test_element_storage_quota_uses_replacement_delta(self):
        user, _ = await self.store.create_user(
            email="quota-owner@example.com", phone=None, password="owner-password"
        )
        scene = await self.store.create_element(owner_id=user.id, kind="scene", name="配额场景")
        with patch("app.platform.store.MAX_ELEMENT_STORAGE_BYTES", 150):
            first = await self.store.add_element_file(
                element_id=scene.id,
                owner_id=user.id,
                slot="model_glb",
                storage_path="private/first.glb",
                mime_type="model/gltf-binary",
                size_bytes=100,
                sha256="first",
            )
            replaced = await self.store.add_element_file(
                element_id=scene.id,
                owner_id=user.id,
                slot="model_glb",
                storage_path="private/replaced.glb",
                mime_type="model/gltf-binary",
                size_bytes=120,
                sha256="replaced",
            )
            self.assertIsNone(first.replaced_storage_path)
            self.assertEqual(replaced.replaced_storage_path, "private/first.glb")
            with self.assertRaisesRegex(ValueError, "存储空间"):
                await self.store.add_element_file(
                    element_id=scene.id,
                    owner_id=user.id,
                    slot="reference",
                    storage_path="public/reference.png",
                    mime_type="image/png",
                    size_bytes=40,
                    sha256="image",
                )

    async def test_global_element_storage_quota_spans_accounts(self):
        first_user, _ = await self.store.create_user(
            email="global-one@example.com", phone=None, password="owner-password"
        )
        second_user, _ = await self.store.create_user(
            email="global-two@example.com", phone=None, password="owner-password"
        )
        first_scene = await self.store.create_element(owner_id=first_user.id, kind="scene", name="场景一")
        second_scene = await self.store.create_element(owner_id=second_user.id, kind="scene", name="场景二")
        with (
            patch("app.platform.store.MAX_ELEMENT_STORAGE_BYTES", 1_000),
            patch("app.platform.store.MAX_GLOBAL_ELEMENT_STORAGE_BYTES", 150),
        ):
            await self.store.add_element_file(
                element_id=first_scene.id,
                owner_id=first_user.id,
                slot="reference",
                storage_path="public/one.png",
                mime_type="image/png",
                size_bytes=100,
                sha256="one",
            )
            with self.assertRaisesRegex(ValueError, "全局存储配额"):
                await self.store.add_element_file(
                    element_id=second_scene.id,
                    owner_id=second_user.id,
                    slot="reference",
                    storage_path="public/two.png",
                    mime_type="image/png",
                    size_bytes=60,
                    sha256="two",
                )

    async def test_deleting_files_updates_model_metadata_status_version_and_owner_scope(self):
        owner, _ = await self.store.create_user(
            email="delete-owner@example.com", phone=None, password="owner-password"
        )
        stranger, _ = await self.store.create_user(
            email="delete-stranger@example.com", phone=None, password="owner-password"
        )
        scene = await self.store.create_element(
            owner_id=owner.id,
            kind="scene",
            name="待删除场景",
            metadata={"source": "test"},
        )
        await self.store.add_element_file(
            element_id=scene.id,
            owner_id=owner.id,
            slot="reference",
            storage_path=f"{owner.id}/{scene.id}/reference.png",
            mime_type="image/png",
            size_bytes=10,
            sha256="reference",
        )
        with_model = await self.store.add_element_file(
            element_id=scene.id,
            owner_id=owner.id,
            slot="model_glb",
            storage_path=f"{owner.id}/{scene.id}/model.glb",
            mime_type="model/gltf-binary",
            size_bytes=20,
            sha256="model",
            model_metadata={"format": "glb", "stats": {"triangles": 1}},
        )
        reference_file = next(item for item in with_model.element.files if item.slot == "reference")
        model_file = next(item for item in with_model.element.files if item.slot == "model_glb")
        original_version = with_model.element.version

        with self.assertRaisesRegex(ValueError, "元素不存在"):
            await self.store.delete_element_file(
                scene.id, reference_file.id, stranger.id
            )
        unchanged = await self.store.get_element(scene.id, owner.id)
        self.assertEqual(len(unchanged.files), 2)

        without_reference = await self.store.delete_element_file(
            scene.id, reference_file.id, owner.id
        )
        self.assertEqual(without_reference.deleted_file.id, reference_file.id)
        self.assertEqual(without_reference.element.version, original_version + 1)
        self.assertEqual(without_reference.element.status, "ready")
        self.assertIn("model3d", without_reference.element.metadata_json)

        without_model = await self.store.delete_element_file(
            scene.id, model_file.id, owner.id
        )
        self.assertEqual(without_model.deleted_file.storage_path, f"{owner.id}/{scene.id}/model.glb")
        self.assertEqual(without_model.element.version, original_version + 2)
        self.assertEqual(without_model.element.status, "draft")
        self.assertEqual(without_model.element.metadata_json, {"source": "test"})
        self.assertEqual(without_model.element.files, [])

    async def test_deleting_actor_view_marks_ready_actor_draft(self):
        owner, _ = await self.store.create_user(
            email="delete-actor@example.com", phone=None, password="owner-password"
        )
        actor = await self.store.create_element(owner_id=owner.id, kind="actor", name="演员")
        for index, slot in enumerate((
            "front", "front_three_quarter", "profile", "rear_three_quarter", "back"
        )):
            stored = await self.store.add_element_file(
                element_id=actor.id,
                owner_id=owner.id,
                slot=slot,
                storage_path=f"{owner.id}/{actor.id}/{slot}.png",
                mime_type="image/png",
                size_bytes=10,
                sha256=f"actor-{index}",
            )
        front = next(item for item in stored.element.files if item.slot == "front")
        original_version = stored.element.version

        result = await self.store.delete_element_file(actor.id, front.id, owner.id)

        self.assertEqual(result.element.status, "draft")
        self.assertEqual(result.element.version, original_version + 1)
        self.assertEqual([item.slot for item in result.element.files], [
            "front_three_quarter", "profile", "rear_three_quarter", "back"
        ])

    async def test_deleting_element_is_owner_scoped_and_removes_regeneration_records(self):
        owner, _ = await self.store.create_user(
            email="delete-asset-owner@example.com", phone=None, password="owner-password"
        )
        stranger, _ = await self.store.create_user(
            email="delete-asset-stranger@example.com", phone=None, password="owner-password"
        )
        prop = await self.store.create_element(owner_id=owner.id, kind="prop", name="旧道具")
        stored = await self.store.add_element_file(
            element_id=prop.id,
            owner_id=owner.id,
            slot="reference",
            storage_path=f"{owner.id}/{prop.id}/reference.png",
            mime_type="image/png",
            size_bytes=10,
            sha256="delete-asset-reference",
        )
        regeneration = await self.store.request_regeneration(prop.id, owner.id, "重绘")

        with self.assertRaisesRegex(ValueError, "元素不存在"):
            await self.store.delete_element(prop.id, stranger.id)
        self.assertIsNotNone(await self.store.get_element(prop.id, owner.id))

        result = await self.store.delete_element(prop.id, owner.id)

        self.assertEqual(result.element_id, prop.id)
        self.assertEqual([item.id for item in result.deleted_files], [stored.element.files[0].id])
        self.assertIsNone(await self.store.get_element(prop.id, owner.id))
        async with self.store.sessions() as session:
            orphan = await session.scalar(
                select(RegenerationRequest).where(RegenerationRequest.id == regeneration.id)
            )
        self.assertIsNone(orphan)
        with self.assertRaisesRegex(ValueError, "元素不存在"):
            await self.store.delete_element(prop.id, owner.id)

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

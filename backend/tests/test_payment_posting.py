# -*- coding: utf-8 -*-
"""Marking an order paid: one path for every source, one grant per order, and renewals that keep what was paid for."""

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from app import settings
from app.platform.models import LedgerEntry, PaymentAttempt, PaymentOrder, PaymentRefund, UserMembership
from app.platform.payments.base import PAID, ChannelTrade
from app.platform.store import PlatformStore


def _aware(moment):
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class SandboxSwitchTest(unittest.TestCase):
    def test_off_unless_turned_on_and_never_in_production(self):
        cases = (
            ({}, False), ({"PAYMENT_SANDBOX_ENABLED": "0"}, False), ({"PAYMENT_SANDBOX_ENABLED": "1"}, True),
            ({"PAYMENT_SANDBOX_ENABLED": "1", "ENVIRONMENT": "production"}, False),
        )
        for env, expected in cases:
            kept = {key: value for key, value in os.environ.items() if key not in {"PAYMENT_SANDBOX_ENABLED", "ENVIRONMENT"}}
            with patch.dict(os.environ, {**kept, **env}, clear=True):
                self.assertIs(settings.payment_sandbox_enabled(), expected, env)


class PostingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'platform.sqlite3'}")
        self.addAsyncCleanup(self.store.close)
        await self.store.create_schema()
        await self.store.seed_billing_plans()
        self.user, _ = await self.store.create_user(email="buyer@example.com", phone=None, password="buyer-password")
        self.plans = await self.store.list_plans()
        patcher = patch.dict(os.environ, {"PAYMENT_SANDBOX_ENABLED": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _order(self, key, plan=None, provider="sandbox"):
        order = await self.store.create_order(
            user_id=self.user.id, plan_id=(plan or self.plans[0]).id, provider="sandbox", idempotency_key=key,
        )
        if provider != "sandbox":
            async with self.store.sessions() as session:
                stored = await session.get(PaymentOrder, order.id)
                stored.provider = provider
                await session.commit()
        return order

    async def _webhook(self, order, event_id, provider="wechat"):
        """What a channel reports, through the path every channel uses. A separate attempt per trade, as there would be."""
        out = f"P{event_id}"
        async with self.store.sessions() as session:
            if not await session.scalar(select(PaymentAttempt.id).where(PaymentAttempt.out_trade_no == out)):
                session.add(PaymentAttempt(
                    order_id=order.id, user_id=order.user_id, provider=provider, merchant_id="m", out_trade_no=out,
                    amount_minor=int(order.amount * 100), currency=order.currency,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
                ))
                await session.commit()
        return await self.store.apply_channel_payment(provider=provider, source="notification", trade=ChannelTrade(
            state=PAID, out_trade_no=out, channel_trade_no=f"channel-{event_id}", amount_minor=int(order.amount * 100),
            merchant_id="m",
        ))

    async def _membership(self):
        async with self.store.sessions() as session:
            return await session.get(UserMembership, self.user.id)

    async def _credits(self):
        async with self.store.sessions() as session:
            return list((await session.scalars(select(LedgerEntry).where(LedgerEntry.user_id == self.user.id))).all())

    async def test_confirm_and_webhook_grant_the_same_thing(self):
        by_confirm = await self._order("confirm-1")
        await self.store.confirm_paid_order(by_confirm.id, "sandbox:1")
        first = await self._credits()
        by_webhook = await self._order("webhook-1", provider="wechat")
        self.assertEqual(await self._webhook(by_webhook, "wx-1"), "applied")
        order = await self.store.get_order(by_webhook.id)
        self.assertEqual(order.status, "paid")
        self.assertIsNotNone(order.paid_at)
        rows = await self._credits()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.category for row in rows}, {first[0].category})
        self.assertEqual(rows[0].amount, rows[1].amount)
        self.assertEqual({row.idempotency_key for row in rows}, {f"order:{by_confirm.id}:points", f"order:{by_webhook.id}:points"})

    async def test_the_same_event_arriving_together_grants_once(self):
        order = await self._order("together-1", provider="wechat")
        results = await asyncio.gather(*(self._webhook(order, "wx-same") for _ in range(5)), return_exceptions=True)
        self.assertIn("applied", results)
        self.assertEqual(len(await self._credits()), 1)
        wallet = await self.store.wallet(self.user.id)
        self.assertEqual(wallet.points, Decimal(self.plans[0].points))

    async def test_confirming_twice_together_grants_once(self):
        order = await self._order("confirm-race")
        await asyncio.gather(*(self.store.confirm_paid_order(order.id, "sandbox:race") for _ in range(5)), return_exceptions=True)
        self.assertEqual(len(await self._credits()), 1)

    async def test_a_second_payment_for_a_paid_order_grants_nothing_and_goes_back(self):
        order = await self._order("second-key-1", provider="wechat")
        await self._webhook(order, "wx-a")
        self.assertEqual(await self._webhook(order, "wx-b"), "duplicate")
        self.assertEqual(len(await self._credits()), 1)
        async with self.store.sessions() as session:
            self.assertEqual(len((await session.scalars(select(PaymentRefund))).all()), 1)

    async def test_confirming_a_closed_order_grants_nothing(self):
        order = await self._order("closed-key-1", provider="wechat")
        async with self.store.sessions() as session:
            (await session.get(PaymentOrder, order.id)).status = "closed"
            await session.commit()
        with self.assertRaisesRegex(ValueError, "不允许支付"):
            await self.store.confirm_paid_order(order.id, "sandbox:closed")
        self.assertEqual(await self._credits(), [])
        self.assertIsNone(await self._membership())

    async def test_renewing_early_keeps_the_days_left(self):
        first = await self._order("renew-key-1")
        await self.store.confirm_paid_order(first.id, "sandbox:r1")
        before = await self._membership()
        second = await self._order("renew-key-2")
        await self.store.confirm_paid_order(second.id, "sandbox:r2")
        after = await self._membership()
        self.assertEqual(
            _aware(after.expires_at) - _aware(before.expires_at), timedelta(days=self.plans[0].duration_days),
        )
        self.assertEqual(_aware(after.started_at), _aware(before.started_at))

    async def test_renewing_after_it_ran_out_starts_from_now(self):
        first = await self._order("late-key-1")
        await self.store.confirm_paid_order(first.id, "sandbox:l1")
        async with self.store.sessions() as session:
            stored = await session.get(UserMembership, self.user.id)
            stored.expires_at = datetime.now(timezone.utc) - timedelta(days=5)
            await session.commit()
        second = await self._order("late-key-2")
        await self.store.confirm_paid_order(second.id, "sandbox:l2")
        left = _aware((await self._membership()).expires_at) - datetime.now(timezone.utc)
        self.assertAlmostEqual(left.total_seconds(), timedelta(days=self.plans[0].duration_days).total_seconds(), delta=60)

    async def test_buying_another_plan_takes_over_from_now(self):
        first = await self._order("switch-key-1")
        await self.store.confirm_paid_order(first.id, "sandbox:s1")
        second = await self._order("switch-key-2", plan=self.plans[1])
        await self.store.confirm_paid_order(second.id, "sandbox:s2")
        after = await self._membership()
        self.assertEqual(after.plan_id, self.plans[1].id)
        left = _aware(after.expires_at) - datetime.now(timezone.utc)
        self.assertAlmostEqual(left.total_seconds(), timedelta(days=self.plans[1].duration_days).total_seconds(), delta=60)

    async def test_with_the_sandbox_off_the_store_refuses_too(self):
        order = await self._order("off-key-1")
        with patch.dict(os.environ, {"PAYMENT_SANDBOX_ENABLED": "0"}):
            with self.assertRaisesRegex(ValueError, "沙箱"):
                await self.store.confirm_paid_order(order.id, "sandbox:off")
            with self.assertRaisesRegex(ValueError, "沙箱"):
                await self._order("off-key-2")
        self.assertEqual(await self._credits(), [])


if __name__ == "__main__":
    unittest.main()

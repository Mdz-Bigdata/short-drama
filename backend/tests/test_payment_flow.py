# -*- coding: utf-8 -*-
"""Paying over HTTP with the real adapters: every order the two channels can tell us things in, and what each may grant."""

import asyncio
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.api import billing_api
from app.api.auth_api import get_current_user
from app.platform import payment_flow
from app.platform.dependencies import get_platform_store
from app.platform.models import AuditEvent, LedgerEntry, PaymentAttempt, PaymentOrder, PaymentRefund, PaymentWebhookEvent
from app.platform.store import PlatformStore
from tests.payment_fakes import STRANGER_KEY, FakeAlipay, FakeWeChat

# Point this at a throwaway Postgres database to run with real row locks and real concurrency.
DATABASE_URL = os.getenv("PAYMENT_TEST_DATABASE_URL")


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.store = PlatformStore(DATABASE_URL or f"sqlite+aiosqlite:///{self.folder / 'platform.sqlite3'}")
        self.addAsyncCleanup(self.store.close)
        await self.store.create_schema()
        if DATABASE_URL:
            # Emptied between tests, so this refuses anything that is not plainly a throwaway database.
            self.assertIn("tmp", make_url(DATABASE_URL).database)
            async with self.store.sessions() as session:
                await session.execute(text(
                    "TRUNCATE payment_refunds, payment_attempts, payment_webhook_events, platform_audit_events, payment_orders, "
                    "billing_ledger, point_lots, point_balances, point_holds, membership_terms, user_memberships, recon_items, recon_runs, "
                    "channel_bills, channel_bill_rows, wallet_adjustments, user_roles, point_rates CASCADE"
                ))
                await session.commit()
        await self.store.seed_billing_plans()
        self.user, _ = await self.store.create_user(email=f"{uuid.uuid4().hex}@example.com", phone=None, password="buyer-password")
        self.plan = next(plan for plan in await self.store.list_plans() if plan.price > 0)
        self.wechat, self.alipay = FakeWeChat(self.folder), FakeAlipay(self.folder)
        self.channels = {"wechat": self.wechat.channel(), "alipay": self.alipay.channel()}
        self.fakes = {"wechat": self.wechat, "alipay": self.alipay}

        app = self.app = FastAPI()
        app.include_router(billing_api.router)
        self.current = {"user_id": self.user.id, "role": "user"}
        app.dependency_overrides[get_current_user] = lambda: self.current
        app.dependency_overrides[get_platform_store] = lambda: self.store
        patcher = patch.object(billing_api, "get_payment_channels", lambda: self.channels)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    async def _new_order(self):
        response = await self.client.post("/api/billing/orders", json={"plan_id": self.plan.id, "idempotency_key": f"k-{uuid.uuid4().hex}"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    async def _pay(self, order_id, provider):
        response = await self.client.post(f"/api/billing/orders/{order_id}/pay", json={"provider": provider})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def _out(self, order_id, provider):
        async with self.store.sessions() as session:
            return await session.scalar(
                select(PaymentAttempt.out_trade_no)
                .where(PaymentAttempt.order_id == order_id, PaymentAttempt.provider == provider)
                .order_by(PaymentAttempt.created_at.desc())
            )

    async def _notify(self, provider, *args, **kwargs):
        headers, body = self.fakes[provider].notification(*args, **kwargs)
        return await self.client.post(f"/api/billing/webhooks/{provider}", content=body, headers=headers)

    def _acked(self, provider, response):
        if provider == "alipay":
            self.assertEqual((response.status_code, response.text), (200, "success"))
        else:
            self.assertEqual((response.status_code, response.content), (204, b""))

    async def _order(self, order_id):
        return await self.store.get_order(order_id)

    async def _credits(self):
        async with self.store.sessions() as session:
            return list((await session.scalars(select(LedgerEntry).where(LedgerEntry.user_id == self.user.id))).all())

    async def _alerts(self, action, order_id=None):
        async with self.store.sessions() as session:
            query = select(AuditEvent).where(AuditEvent.action == action)
            if order_id:
                query = query.where(AuditEvent.resource_id == order_id)
            return list((await session.scalars(query)).all())

    async def _refunds(self, order_id):
        async with self.store.sessions() as session:
            return list((await session.scalars(select(PaymentRefund).where(PaymentRefund.order_id == order_id))).all())

    async def _attempt(self, out):
        async with self.store.sessions() as session:
            return await session.scalar(select(PaymentAttempt).where(PaymentAttempt.out_trade_no == out))

    async def _granted_once(self):
        credits = await self._credits()
        self.assertEqual(len(credits), 1, credits)
        self.assertEqual((await self.store.wallet(self.user.id)).points, Decimal(self.plan.points))
        available, held = await self.store.point_balance(self.user.id)
        self.assertEqual((available, held), (Decimal(self.plan.points), Decimal(0)))

    async def _books_balance(self):
        far = datetime.now(timezone.utc) + timedelta(days=1)
        differences = await self.store.billing_differences(settled_before=far)
        order_ids = {credit.order_id for credit in await self._credits()}
        self.assertFalse([item for item in differences["r3"]["samples"] if item["order_id"] in order_ids], differences["r3"])
        self.assertFalse([item for item in differences["r5"]["samples"] if item["user_id"] == self.user.id], differences["r5"])


class EachChannelTests(Base):
    async def test_buy_scan_notify(self):
        for provider, prefix in (("wechat", "weixin://"), ("alipay", "https://qr.alipay.com/")):
            with self.subTest(provider):
                self.user, _ = await self.store.create_user(email=f"{uuid.uuid4().hex}@example.com", phone=None, password="buyer-password")
                self.current["user_id"] = self.user.id
                order_id = await self._new_order()
                self.assertEqual((await self._order(order_id)).provider, "")
                shown = await self._pay(order_id, provider)
                self.assertTrue(shown["attempt"]["qr_code"].startswith(prefix))
                self.assertEqual(shown["status"], "pending")
                out = await self._out(order_id, provider)
                self.assertEqual((await self._attempt(out)).amount_minor, int(self.plan.price * 100))
                self.fakes[provider].pay(out)
                self._acked(provider, await self._notify(provider, out, event_id=f"evt-{provider}"))
                order = await self._order(order_id)
                self.assertEqual((order.status, order.provider), ("paid", provider))
                await self._granted_once()
                await self._books_balance()
                attempt = await self._attempt(out)
                self.assertEqual((attempt.status, attempt.settled_by, attempt.qr_code), ("paid", "notification", None))
                self.assertTrue(attempt.channel_trade_no)

    async def test_the_same_notification_again_changes_nothing(self):
        for provider in ("wechat", "alipay"):
            with self.subTest(provider):
                self.user, _ = await self.store.create_user(email=f"{uuid.uuid4().hex}@example.com", phone=None, password="buyer-password")
                self.current["user_id"] = self.user.id
                order_id = await self._new_order()
                await self._pay(order_id, provider)
                out = await self._out(order_id, provider)
                self.fakes[provider].pay(out)
                event = f"evt-{uuid.uuid4().hex}"
                for _ in range(3):
                    self._acked(provider, await self._notify(provider, out, event_id=event))
                # A different notification about the same trade, as Alipay sends for TRADE_FINISHED.
                self._acked(provider, await self._notify(provider, out))
                await self._granted_once()
                self.assertEqual(await self._refunds(order_id), [])

    async def test_notifications_arriving_together_grant_once(self):
        for provider in ("wechat", "alipay"):
            with self.subTest(provider):
                self.user, _ = await self.store.create_user(email=f"{uuid.uuid4().hex}@example.com", phone=None, password="buyer-password")
                self.current["user_id"] = self.user.id
                order_id = await self._new_order()
                await self._pay(order_id, provider)
                out = await self._out(order_id, provider)
                self.fakes[provider].pay(out)
                event = f"evt-{uuid.uuid4().hex}"
                await asyncio.gather(*(self._notify(provider, out, event_id=event) for _ in range(10)))
                # SQLite may turn some away as busy, and those are told to retry, which the channel would. Retry once.
                self._acked(provider, await self._notify(provider, out, event_id=event))
                await self._granted_once()
                self.assertEqual(await self._refunds(order_id), [])
                async with self.store.sessions() as session:
                    rows = (await session.scalars(select(PaymentWebhookEvent).where(PaymentWebhookEvent.event_id == event))).all()
                self.assertEqual(len(rows), 1)

    async def test_a_notification_and_a_poll_racing_grant_once(self):
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        out = await self._out(order_id, "wechat")
        self.wechat.pay(out)
        await asyncio.gather(
            self._notify("wechat", out), self.client.get(f"/api/billing/orders/{order_id}"),
            self._notify("wechat", out), self.client.get(f"/api/billing/orders/{order_id}"), return_exceptions=True,
        )
        self._acked("wechat", await self._notify("wechat", out))
        self.assertEqual((await self._order(order_id)).status, "paid")
        await self._granted_once()


class WrongNotificationTests(Base):
    async def _ready(self, provider="wechat"):
        order_id = await self._new_order()
        await self._pay(order_id, provider)
        out = await self._out(order_id, provider)
        self.fakes[provider].pay(out)
        return order_id, out

    async def _nothing_granted(self, order_id):
        self.assertEqual((await self._order(order_id)).status, "pending")
        self.assertEqual(await self._credits(), [])

    async def test_a_bad_signature_is_refused_so_the_channel_retries(self):
        order_id, out = await self._ready("wechat")
        response = await self._notify("wechat", out, key=STRANGER_KEY)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"code": "FAIL", "message": "失败"})
        await self._nothing_granted(order_id)
        order_id, out = await self._ready("alipay")
        response = await self._notify("alipay", out, key=STRANGER_KEY)
        self.assertEqual((response.status_code, response.text), (200, "fail"))
        await self._nothing_granted(order_id)

    async def test_wrong_amount_or_merchant_grants_nothing_but_is_acknowledged(self):
        cases = (
            ("wechat", {"amount": {"total": 1, "currency": "CNY"}}), ("wechat", {"mchid": "1900000999"}),
            ("wechat", {"appid": "wxother"}), ("wechat", {"amount": {"total": 2990000, "currency": "USD"}}),
            ("alipay", {"total_amount": "0.01"}), ("alipay", {"seller_id": "2088000000000999"}), ("alipay", {"app_id": "other"}),
        )
        for provider, overrides in cases:
            with self.subTest(provider=provider, overrides=overrides):
                order_id, out = await self._ready(provider)
                self._acked(provider, await self._notify(provider, out, **overrides))
                await self._nothing_granted(order_id)
                self.assertEqual((await self._attempt(out)).status, "mismatch")
                self.assertEqual(len(await self._alerts("payment.mismatch", order_id)), 1)

    async def test_a_mismatched_attempt_is_no_longer_asked_about(self):
        order_id, out = await self._ready("wechat")
        await self._notify("wechat", out, amount={"total": 1, "currency": "CNY"})
        later = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.assertEqual(await self.store.attempts_due(now=later, settled_after=timedelta(0), every=timedelta(0), limit=10), [])

    async def test_a_trade_we_never_issued_is_acknowledged_and_noted(self):
        self.wechat.trades["Pnotours"] = {"trade_state": "SUCCESS", "transaction_id": "wxzzz", "amount": {"total": 2990, "currency": "CNY"}}
        self._acked("wechat", await self._notify("wechat", "Pnotours"))
        self.assertEqual(await self._credits(), [])
        self.assertTrue(await self._alerts("payment.unknown_trade"))

    async def test_a_not_paid_status_changes_nothing(self):
        order_id, out = await self._ready("alipay")
        self._acked("alipay", await self._notify("alipay", out, trade_status="WAIT_BUYER_PAY"))
        await self._nothing_granted(order_id)
        self.assertEqual((await self._attempt(out)).status, "pending")

    async def test_an_unconfigured_channel_has_no_webhook(self):
        self.channels.pop("alipay")
        response = await self.client.post("/api/billing/webhooks/alipay", content=b"a=1")
        self.assertEqual(response.status_code, 404)

    async def test_an_oversized_notification_is_not_processed(self):
        response = await self.client.post("/api/billing/webhooks/wechat", content=b"x" * (64 * 1024 + 1))
        self.assertEqual(response.status_code, 413)


class WithoutNotificationTests(Base):
    async def test_polling_finds_the_payment(self):
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        out = await self._out(order_id, "alipay")
        waiting = (await self.client.get(f"/api/billing/orders/{order_id}")).json()
        self.assertEqual(waiting["status"], "pending")
        self.assertTrue(waiting["attempt"]["qr_code"])
        self.alipay.pay(out)
        async with self.store.sessions() as session:
            (await session.get(PaymentAttempt, (await self._attempt(out)).id)).last_queried_at = None
            await session.commit()
        paid = (await self.client.get(f"/api/billing/orders/{order_id}")).json()
        self.assertEqual((paid["status"], paid["attempt"]), ("paid", None))
        await self._granted_once()
        self.assertEqual((await self._attempt(out)).settled_by, "query")

    async def test_polling_does_not_hammer_the_channel(self):
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        self.wechat.calls.clear()
        await asyncio.gather(*(self.client.get(f"/api/billing/orders/{order_id}") for _ in range(8)))
        queries = [call for call in self.wechat.calls if call[0] == "GET"]
        self.assertLessEqual(len(queries), 1)

    async def test_a_channel_outage_does_not_fail_polling(self):
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        self.alipay.down = True
        response = await self.client.get(f"/api/billing/orders/{order_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pending")

    async def test_the_sweep_finds_a_payment_and_closes_what_expired(self):
        paid_order, expired_order = await self._new_order(), await self._new_order()
        await self._pay(paid_order, "wechat")
        await self._pay(expired_order, "alipay")
        paid_out, expired_out = await self._out(paid_order, "wechat"), await self._out(expired_order, "alipay")
        self.wechat.pay(paid_out)
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=20))
        self.assertEqual((await self._order(paid_order)).status, "paid")
        self.assertEqual((await self._attempt(expired_out)).status, "closed")
        self.assertEqual(self.alipay.closed, [expired_out])
        self.assertEqual((await self._order(expired_order)).status, "pending")
        await self._granted_once()

    async def test_an_expired_code_that_was_paid_is_not_closed(self):
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        out = await self._out(order_id, "alipay")
        self.alipay.pay(out)
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=20))
        self.assertEqual(self.alipay.closed, [])
        self.assertEqual((await self._order(order_id)).status, "paid")
        await self._granted_once()

    async def test_an_outage_during_the_sweep_leaves_things_to_try_again(self):
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        out = await self._out(order_id, "alipay")
        self.alipay.down = True
        moment = datetime.now(timezone.utc) + timedelta(minutes=20)
        await payment_flow.sweep(self.store, self.channels, moment)
        self.assertEqual((await self._attempt(out)).status, "pending")
        self.alipay.down = False
        self.alipay.pay(out)
        await payment_flow.sweep(self.store, self.channels, moment + timedelta(minutes=2))
        self.assertEqual((await self._order(order_id)).status, "paid")

    async def test_orders_left_unpaid_close_after_a_day_but_not_sandbox_or_open_ones(self):
        abandoned, still_open = await self._new_order(), await self._new_order()
        await self._pay(still_open, "alipay")
        with patch.dict(os.environ, {"PAYMENT_SANDBOX_ENABLED": "1"}):
            sandbox = await self.store.create_order(user_id=self.user.id, plan_id=self.plan.id, provider="sandbox", idempotency_key=f"sb-{uuid.uuid4().hex}")
        self.alipay.down = True
        await self.store.close_abandoned_orders(created_before=datetime.now(timezone.utc) + timedelta(minutes=1))
        self.assertEqual((await self._order(abandoned)).status, "closed")
        self.assertEqual((await self._order(still_open)).status, "pending")
        self.assertEqual((await self._order(sandbox.id)).status, "pending")


class ChangingYourMindTests(Base):
    async def test_asking_again_shows_the_same_code(self):
        order_id = await self._new_order()
        first, second = await self._pay(order_id, "wechat"), await self._pay(order_id, "wechat")
        self.assertEqual(first["attempt"]["qr_code"], second["attempt"]["qr_code"])
        self.assertEqual(len(self.wechat.trades), 1)

    async def test_a_code_about_to_expire_is_replaced(self):
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        out = await self._out(order_id, "wechat")
        async with self.store.sessions() as session:
            attempt = await session.get(PaymentAttempt, (await self._attempt(out)).id)
            attempt.expires_at = datetime.now(timezone.utc) + timedelta(seconds=20)
            await session.commit()
        await self._pay(order_id, "wechat")
        self.assertEqual(self.wechat.closed, [out])
        self.assertEqual(len(self.wechat.trades), 2)

    async def test_switching_channel_closes_the_old_code_first(self):
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        old = await self._out(order_id, "wechat")
        shown = await self._pay(order_id, "alipay")
        self.assertEqual(shown["attempt"]["provider"], "alipay")
        self.assertEqual(shown["provider"], "alipay")
        self.assertEqual(self.wechat.closed, [old])
        self.assertEqual((await self._attempt(old)).status, "closed")

    async def test_switching_after_the_old_code_was_paid_gives_no_new_code(self):
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        old = await self._out(order_id, "wechat")
        self.wechat.pay(old)
        shown = await self._pay(order_id, "alipay")
        self.assertEqual((shown["status"], shown["attempt"]), ("paid", None))
        self.assertEqual(self.alipay.trades, {})
        await self._granted_once()

    async def test_cancelling(self):
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        out = await self._out(order_id, "alipay")
        response = await self.client.post(f"/api/billing/orders/{order_id}/cancel")
        self.assertEqual(response.json()["status"], "closed")
        self.assertEqual(self.alipay.closed, [out])
        response = await self.client.post(f"/api/billing/orders/{order_id}/pay", json={"provider": "alipay"})
        self.assertEqual(response.status_code, 422)

    async def test_cancelling_something_already_paid_keeps_it_paid(self):
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        self.alipay.pay(await self._out(order_id, "alipay"))
        response = await self.client.post(f"/api/billing/orders/{order_id}/cancel")
        self.assertEqual(response.json()["status"], "paid")
        await self._granted_once()

    async def test_cancelling_during_an_outage_says_so_and_changes_nothing(self):
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        self.alipay.down = True
        response = await self.client.post(f"/api/billing/orders/{order_id}/cancel")
        self.assertEqual(response.status_code, 502)
        self.assertEqual((await self._order(order_id)).status, "pending")

    async def test_a_channel_down_when_ordering_is_reported_and_leaves_nothing_open(self):
        order_id = await self._new_order()
        self.alipay.down = True
        response = await self.client.post(f"/api/billing/orders/{order_id}/pay", json={"provider": "alipay"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(await self.store.open_attempts(order_id), [])
        self.alipay.down = False
        await self._pay(order_id, "alipay")

    async def test_two_requests_at_once_for_a_code_do_not_make_two_codes(self):
        order_id = await self._new_order()
        responses = await asyncio.gather(*(
            self.client.post(f"/api/billing/orders/{order_id}/pay", json={"provider": "wechat"}) for _ in range(4)
        ), return_exceptions=True)
        ok = [item for item in responses if isinstance(item, httpx.Response) and item.status_code == 200]
        self.assertTrue(ok, responses)
        self.assertEqual(len(self.wechat.trades), 1)


class LateAndDoubleTests(Base):
    async def test_money_after_cancelling_still_buys_what_it_was_for_and_is_flagged(self):
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        out = await self._out(order_id, "alipay")
        await self.client.post(f"/api/billing/orders/{order_id}/cancel")
        self.alipay.pay(out)
        self._acked("alipay", await self._notify("alipay", out))
        self.assertEqual((await self._order(order_id)).status, "paid")
        await self._granted_once()
        self.assertEqual(len(await self._alerts("payment.late", order_id)), 1)
        await self._books_balance()

    async def test_a_closed_alipay_code_paid_with_the_notification_lost_is_still_found(self):
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        out = await self._out(order_id, "alipay")
        await self.client.post(f"/api/billing/orders/{order_id}/cancel")
        self.assertEqual((await self._attempt(out)).status, "closed")
        self.alipay.pay(out)
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=10))
        self.assertEqual((await self._order(order_id)).status, "paid")
        await self._granted_once()
        self.assertEqual(len(await self._alerts("payment.late", order_id)), 1)

    async def test_a_closed_code_stops_being_asked_about_once_it_cannot_be_paid(self):
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        await self.client.post(f"/api/billing/orders/{order_id}/cancel")
        self.alipay.calls.clear()
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(hours=3))
        self.assertEqual(self.alipay.calls, [])

    async def test_closed_wechat_orders_are_final_and_not_asked_about(self):
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        await self.client.post(f"/api/billing/orders/{order_id}/cancel")
        self.wechat.calls.clear()
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=10))
        self.assertEqual(self.wechat.calls, [])

    async def _paid_twice(self, first, second):
        order_id = await self._new_order()
        await self._pay(order_id, first)
        first_out = await self._out(order_id, first)
        with patch.object(self.channels[first], "close", side_effect=payment_flow.ChannelError("down")):
            await self._pay(order_id, second)
        second_out = await self._out(order_id, second)
        self.fakes[first].pay(first_out)
        self.fakes[second].pay(second_out)
        self._acked(first, await self._notify(first, first_out))
        self._acked(second, await self._notify(second, second_out))
        return order_id, first_out, second_out

    async def test_paying_two_codes_grants_once_and_refunds_the_second(self):
        for first, second in (("wechat", "alipay"), ("alipay", "wechat")):
            with self.subTest(first=first):
                self.user, _ = await self.store.create_user(email=f"{uuid.uuid4().hex}@example.com", phone=None, password="buyer-password")
                self.current["user_id"] = self.user.id
                order_id, first_out, second_out = await self._paid_twice(first, second)
                await self._granted_once()
                await self._books_balance()
                self.assertEqual((await self._order(order_id)).provider, first)
                refunds = await self._refunds(order_id)
                self.assertEqual(len(refunds), 1)
                self.assertEqual(
                    (refunds[0].provider, refunds[0].out_trade_no, refunds[0].refund_minor, refunds[0].status, refunds[0].reason),
                    (second, second_out, int(self.plan.price * 100), "pending", "duplicate_payment"),
                )
                self.assertEqual((await self._attempt(second_out)).status, "paid")
                self.assertEqual(len(await self._alerts("payment.duplicate", order_id)), 1)

    async def test_two_channels_reporting_at_the_same_moment_grant_once_and_refund_once(self):
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        wechat_out = await self._out(order_id, "wechat")
        with patch.object(self.channels["wechat"], "close", side_effect=payment_flow.ChannelError("down")):
            await self._pay(order_id, "alipay")
        alipay_out = await self._out(order_id, "alipay")
        self.wechat.pay(wechat_out)
        self.alipay.pay(alipay_out)
        await asyncio.gather(self._notify("wechat", wechat_out), self._notify("alipay", alipay_out))
        # On SQLite one of the two may have been turned away as busy; the channel would send it again.
        self._acked("wechat", await self._notify("wechat", wechat_out))
        self._acked("alipay", await self._notify("alipay", alipay_out))
        await self._granted_once()
        self.assertEqual(len(await self._refunds(order_id)), 1)

    async def test_the_second_payment_replayed_makes_one_refund(self):
        order_id, _, second_out = await self._paid_twice("wechat", "alipay")
        for _ in range(3):
            self._acked("alipay", await self._notify("alipay", second_out))
        self.assertEqual(len(await self._refunds(order_id)), 1)
        await self._granted_once()

    async def test_the_refund_is_sent_and_followed_to_the_end(self):
        order_id, _, second_out = await self._paid_twice("alipay", "wechat")
        moment = datetime.now(timezone.utc)
        await payment_flow.sweep(self.store, self.channels, moment)
        refund = (await self._refunds(order_id))[0]
        self.assertEqual(refund.status, "processing")
        self.assertEqual(self.wechat.refund_sends, 1)
        body = self.wechat.refunds[refund.out_refund_no]["body"]
        self.assertEqual(body["out_trade_no"], second_out)
        await payment_flow.sweep(self.store, self.channels, moment + timedelta(minutes=2))
        refund = (await self._refunds(order_id))[0]
        self.assertEqual(refund.status, "succeeded")
        self.assertIsNotNone(refund.finished_at)
        self.assertEqual(self.wechat.refund_sends, 1)
        await payment_flow.sweep(self.store, self.channels, moment + timedelta(minutes=4))
        self.assertEqual(self.wechat.refund_sends, 1)
        await self._granted_once()

    async def test_a_refund_that_timed_out_goes_again_with_the_same_number(self):
        order_id, _, _ = await self._paid_twice("wechat", "alipay")
        self.alipay.down = True
        moment = datetime.now(timezone.utc)
        await payment_flow.sweep(self.store, self.channels, moment)
        number = (await self._refunds(order_id))[0].out_refund_no
        self.assertEqual((await self._refunds(order_id))[0].status, "pending")
        self.alipay.down = False
        await payment_flow.sweep(self.store, self.channels, moment + timedelta(minutes=2))
        self.assertEqual((await self._refunds(order_id))[0].status, "succeeded")
        self.assertEqual(list(self.alipay.refunds), [number])

    async def test_a_refund_alipay_has_no_record_of_is_sent_again(self):
        order_id, _, _ = await self._paid_twice("wechat", "alipay")
        moment = datetime.now(timezone.utc)
        refund = (await self._refunds(order_id))[0]
        await self.store.record_refund(refund.id, status="processing")
        await payment_flow.sweep(self.store, self.channels, moment)
        self.assertEqual((await self._refunds(order_id))[0].status, "pending")
        self.assertEqual(self.alipay.refund_sends, 0)
        await payment_flow.sweep(self.store, self.channels, moment + timedelta(minutes=2))
        self.assertEqual((await self._refunds(order_id))[0].status, "succeeded")
        self.assertEqual(self.alipay.refund_sends, 1)

    async def test_a_failed_refund_is_flagged_and_final(self):
        order_id, _, _ = await self._paid_twice("alipay", "wechat")
        self.wechat.refund_status = "ABNORMAL"
        moment = datetime.now(timezone.utc)
        await payment_flow.sweep(self.store, self.channels, moment)
        await payment_flow.sweep(self.store, self.channels, moment + timedelta(minutes=2))
        self.assertEqual((await self._refunds(order_id))[0].status, "failed")
        self.assertEqual(len(await self._alerts("payment.refund_failed", order_id)), 1)
        self.assertEqual(await self.store.refunds_due(now=moment + timedelta(minutes=10), every=timedelta(0), limit=10), [])


class ScopeTests(Base):
    async def test_someone_elses_order_does_not_exist(self):
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        other, _ = await self.store.create_user(email=f"{uuid.uuid4().hex}@example.com", phone=None, password="other-password")
        self.current["user_id"] = other.id
        for response in (
            await self.client.get(f"/api/billing/orders/{order_id}"),
            await self.client.post(f"/api/billing/orders/{order_id}/pay", json={"provider": "wechat"}),
            await self.client.post(f"/api/billing/orders/{order_id}/cancel"),
        ):
            self.assertEqual(response.status_code, 404)

    async def test_channels_on_offer_are_listed_and_only_those_can_be_used(self):
        self.channels.pop("wechat")
        self.assertEqual((await self.client.get("/api/billing/plans")).json()["channels"], ["alipay"])
        order_id = await self._new_order()
        response = await self.client.post(f"/api/billing/orders/{order_id}/pay", json={"provider": "wechat"})
        self.assertEqual(response.status_code, 422)
        response = await self.client.post("/api/billing/orders", json={"plan_id": self.plan.id, "provider": "wechat", "idempotency_key": f"k-{uuid.uuid4().hex}"})
        self.assertEqual(response.status_code, 422)

    async def test_the_price_comes_from_the_order_not_the_request(self):
        order_id = await self._new_order()
        response = await self.client.post(f"/api/billing/orders/{order_id}/pay", json={"provider": "wechat", "amount": 1})
        self.assertEqual(response.status_code, 200)
        out = await self._out(order_id, "wechat")
        self.assertEqual(self.wechat.trades[out]["amount"]["total"], int(self.plan.price * 100))

    async def test_a_free_or_foreign_order_cannot_be_paid_online(self):
        order_id = await self._new_order()
        async with self.store.sessions() as session:
            (await session.get(PaymentOrder, order_id)).currency = "USD"
            await session.commit()
        response = await self.client.post(f"/api/billing/orders/{order_id}/pay", json={"provider": "wechat"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

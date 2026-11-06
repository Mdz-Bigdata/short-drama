# -*- coding: utf-8 -*-
"""Refunds and point adjustments: two people, nothing spendable while it is decided, and books that agree afterwards."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import select, update

from app.api import finance_api
from app.platform import payment_flow, reconciliation
from app.platform.billing_book import BillingBook, BillingRefused
from app.platform.models import AuditEvent, LedgerEntry, MembershipTerm, PaymentRefund, PointLot, ReconItem, UserMembership
from app.platform.permissions import permissions_for
from tests.test_payment_flow import DATABASE_URL, Base


class FinanceCase(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.app.include_router(finance_api.router)
        patcher = patch.object(finance_api, "get_payment_channels", lambda: self.channels)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(reconciliation, "get_payment_channels", lambda: self.channels)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.staff = {}
        for name, role in (("asker", "finance"), ("approver", "finance"), ("support", "support"), ("auditor", "auditor"), ("boss", "super_admin")):
            user, _ = await self.store.create_user(email=f"{uuid.uuid4().hex}@example.com", phone=None, password="staff-password")
            self.staff[name] = {"user_id": user.id, "role": "user", "roles": [role], "permissions": sorted(permissions_for([role]))}
        self.buyer = self.user
        self.customer = dict(self.current)
        url = DATABASE_URL or f"sqlite+aiosqlite:///{self.folder / 'platform.sqlite3'}"
        self.book = BillingBook(url, lambda _task: None)
        self.addCleanup(self.book.close)
        await self.store.add_point_rate(
            actor_id=self.staff["boss"]["user_id"], effective_from=datetime.now(timezone.utc) - timedelta(minutes=1),
            model="seedream", kind="per_image", price=Decimal(100),
        )
        self.book._rates = (0.0, [])

    def _as(self, name):
        self.current.clear()
        self.current.update(self.staff[name] if name in self.staff else self.customer)

    async def _bought(self, provider="alipay"):
        self._as("customer")
        order_id = await self._new_order()
        await self._pay(order_id, provider)
        out = await self._out(order_id, provider)
        self.fakes[provider].pay(out)
        self._acked(provider, await self._notify(provider, out))
        return order_id

    def _spend(self, images=1):
        handle = self.book.reserve(media_type="image", provider="x", model="seedream", units={"images": images}, task_id=None, user_id=self.buyer.id)
        self.book.settle(handle, {"id": str(uuid.uuid4()), "status": "success", "units": {"images": images}, "model": "seedream"})

    async def _ask(self, order_id, name="asker", **fields):
        self._as(name)
        return await self.client.post(f"/api/admin/orders/{order_id}/refunds", json={"note": "客户申请", **fields})

    async def _approve(self, refund_id, name="approver", **fields):
        self._as(name)
        return await self.client.post(f"/api/admin/refunds/{refund_id}/approve", json=fields)

    async def _reject(self, refund_id, name="approver"):
        self._as(name)
        return await self.client.post(f"/api/admin/refunds/{refund_id}/reject", json={"note": "不符合条件"})

    async def _balance(self):
        async with self.store.sessions() as session:
            balance = await session.get(__import__("app.platform.models", fromlist=["PointBalance"]).PointBalance, self.buyer.id)
            return balance.available, balance.held, balance.frozen

    async def _lot(self, order_id):
        async with self.store.sessions() as session:
            return await session.scalar(select(PointLot).where(PointLot.order_id == order_id))

    async def _refund(self, refund_id):
        return await self.store.get_refund(refund_id)

    async def _nothing_unexplained(self, *, allow=()):
        run = await reconciliation.run_checks(
            self.store, period=f"manual:{uuid.uuid4()}", rules=reconciliation.DAILY_RULES, channels=self.channels,
        )
        self.assertEqual(run.status, "done", run.summary)
        async with self.store.sessions() as session:
            items = (await session.scalars(select(ReconItem).where(ReconItem.status == "open"))).all()
        left = [(item.rule, item.kind, item.reference, item.expected, item.actual) for item in items if item.kind not in allow]
        self.assertEqual(left, [])


class RefundTests(FinanceCase):
    async def test_nothing_used_refunds_everything_and_ends_the_membership(self):
        order_id = await self._bought("alipay")
        response = await self._ask(order_id)
        self.assertEqual(response.status_code, 201, response.text)
        refund = response.json()
        paid = int(self.plan.price * 100)
        self.assertEqual((refund["amount_minor"], Decimal(str(refund["points"])), refund["status"]), (paid, Decimal(self.plan.points), "requested"))
        response = await self._approve(refund["id"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "succeeded")
        order = await self._order(order_id)
        self.assertEqual(order.status, "refunded")
        self.assertEqual(await self._balance(), (Decimal(0), Decimal(0), Decimal(0)))
        self.assertEqual((await self._lot(order_id)).remaining, Decimal(0))
        async with self.store.sessions() as session:
            term = await session.scalar(select(MembershipTerm).where(MembershipTerm.order_id == order_id))
            membership = await session.get(UserMembership, self.buyer.id)
        self.assertEqual(term.status, "refunded")
        self.assertEqual(membership.status, "refunded")
        self.assertEqual((await self.store.effective_entitlements(self.buyer.id)), (await self.store.effective_entitlements(str(uuid.uuid4()))))
        await self._nothing_unexplained()

    async def test_the_amount_follows_the_points_not_used(self):
        order_id = await self._bought("alipay")
        self._spend(1)  # 100 of the points
        quote = await self.store.refund_quote(order_id)
        paid = int(self.plan.price * 100)
        expected = paid * (self.plan.points - 100) // self.plan.points
        self.assertEqual((quote["suggested_minor"], quote["suggested_points"]), (expected, Decimal(self.plan.points - 100)))
        refund = (await self._ask(order_id)).json()
        self.assertEqual(refund["amount_minor"], expected)
        await self._approve(refund["id"])
        self.assertEqual((await self._order(order_id)).status, "partially_refunded")
        async with self.store.sessions() as session:
            term = await session.scalar(select(MembershipTerm).where(MembershipTerm.order_id == order_id))
        self.assertEqual(term.status, "active")
        self.assertEqual((await self._balance())[0], Decimal(0))
        await self._nothing_unexplained()

    async def test_points_being_decided_on_cannot_be_spent(self):
        await self._bought("alipay")
        order_id = (await self.store.list_orders(self.buyer.id, 1, 1))[0][0].id
        await self._ask(order_id)
        with self.assertRaises(BillingRefused):
            self._spend(1)
        self.assertEqual((await self._balance())[0], Decimal(0))
        self.assertEqual((await self._lot(order_id)).remaining, Decimal(self.plan.points))

    async def test_spending_after_a_partial_freeze_never_touches_what_is_set_aside(self):
        order_id = await self._bought("alipay")
        await self._ask(order_id, points=self.plan.points - 200, amount_minor=100)
        self._spend(2)
        lot = await self._lot(order_id)
        self.assertEqual((lot.remaining, lot.frozen), (Decimal(self.plan.points - 200), Decimal(self.plan.points - 200)))
        with self.assertRaises(BillingRefused):
            self._spend(1)

    async def test_a_call_under_way_keeps_what_it_holds(self):
        order_id = await self._bought("alipay")
        handle = self.book.reserve(media_type="image", provider="x", model="seedream", units={"images": 1}, task_id=None, user_id=self.buyer.id)
        refund = (await self._ask(order_id)).json()
        self.assertEqual(Decimal(str(refund["points"])), Decimal(self.plan.points - 100))
        self.book.settle(handle, {"id": str(uuid.uuid4()), "status": "success", "units": {"images": 1}, "model": "seedream"})
        lot = await self._lot(order_id)
        self.assertEqual((lot.remaining, lot.frozen), (Decimal(self.plan.points - 100), Decimal(self.plan.points - 100)))
        await self._approve(refund["id"])
        await self._nothing_unexplained()

    async def test_spending_and_asking_at_the_same_moment_add_up(self):
        for _ in range(4):
            order_id = await self._bought("alipay")
            spends = [asyncio.to_thread(self._spend, 1) for _ in range(3)]
            await asyncio.gather(self._ask(order_id), *spends, return_exceptions=True)
            available, held, frozen = await self._balance()
            async with self.store.sessions() as session:
                lots = (await session.scalars(select(PointLot).where(PointLot.user_id == self.buyer.id))).all()
            self.assertEqual(available + held + frozen, sum(lot.remaining for lot in lots))
            await self._nothing_unexplained()

    async def test_the_asker_cannot_approve_not_even_a_super_admin(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id, name="boss")).json()
        response = await self._approve(refund["id"], name="boss")
        self.assertEqual(response.status_code, 403)
        self.assertEqual((await self._refund(refund["id"])).status, "requested")
        self.assertEqual(self.alipay.refund_sends, 0)

    async def test_the_database_itself_refuses_one_person_on_both_sides(self):
        if DATABASE_URL is None:
            pass  # the constraint exists on both; this only needs a new table to prove it
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        with self.assertRaises(Exception):
            async with self.store.sessions() as session:
                await session.execute(
                    update(PaymentRefund).where(PaymentRefund.id == refund["id"]).values(approved_by=refund["requested_by"])
                )
                await session.commit()

    async def test_who_may_do_what(self):
        order_id = await self._bought("alipay")
        for name, status in (("customer", 403), ("auditor", 403)):
            self.assertEqual((await self._ask(order_id, name=name)).status_code, status, name)
        response = await self._ask(order_id, name="support")
        self.assertEqual(response.status_code, 201)
        refund_id = response.json()["id"]
        for name in ("customer", "auditor", "support"):
            self.assertEqual((await self._approve(refund_id, name=name)).status_code, 403, name)
            self.assertEqual((await self._reject(refund_id, name=name)).status_code, 403, name)
        self.assertEqual((await self._approve(refund_id)).status_code, 200)

    async def test_rejecting_gives_the_points_back(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        response = await self._reject(refund["id"])
        self.assertEqual(response.json()["status"], "rejected")
        self.assertEqual(await self._balance(), (Decimal(self.plan.points), Decimal(0), Decimal(0)))
        self._spend(1)
        self.assertEqual((await self._approve(refund["id"])).status_code, 422)
        self.assertEqual((await self._order(order_id)).status, "paid")
        await self._nothing_unexplained()

    async def test_a_failed_refund_gives_the_points_back_and_is_flagged(self):
        order_id = await self._bought("wechat")
        self.wechat.refund_status = "ABNORMAL"
        refund = (await self._ask(order_id)).json()
        self.assertEqual((await self._approve(refund["id"])).json()["status"], "processing")
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=2))
        self.assertEqual((await self._refund(refund["id"])).status, "failed")
        self.assertEqual(await self._balance(), (Decimal(self.plan.points), Decimal(0), Decimal(0)))
        self.assertEqual((await self._order(order_id)).status, "paid")
        self.assertEqual(len(await self._alerts("payment.refund_failed", order_id)), 1)
        await self._nothing_unexplained(allow=("refund_failed",))

    async def test_a_refund_in_processing_finishes_at_the_sweep(self):
        order_id = await self._bought("wechat")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        self.assertEqual((await self._order(order_id)).status, "paid")
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=2))
        self.assertEqual((await self._order(order_id)).status, "refunded")
        self.assertEqual(self.wechat.refund_sends, 1)
        await self._nothing_unexplained()

    async def test_an_outage_when_approving_leaves_it_for_the_sweep_with_the_same_number(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        self.alipay.down = True
        self.assertEqual((await self._approve(refund["id"])).json()["status"], "pending")
        self.alipay.down = False
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=2))
        self.assertEqual((await self._refund(refund["id"])).status, "succeeded")
        self.assertEqual(list(self.alipay.refunds), [refund["out_refund_no"]])

    async def test_approving_with_a_channel_gone_is_refused_up_front(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        self.channels.pop("alipay")
        self.assertEqual((await self._approve(refund["id"])).status_code, 409)
        self.assertEqual((await self._refund(refund["id"])).status, "requested")

    async def test_two_approvers_at_once_send_it_once(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await asyncio.gather(self._approve(refund["id"]), self._approve(refund["id"], name="boss"), return_exceptions=True)
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=2))
        self.assertEqual(self.alipay.refunds[refund["out_refund_no"]]["times"], 1)
        self.assertEqual((await self._order(order_id)).status, "refunded")
        await self._nothing_unexplained()

    async def test_the_approver_can_change_the_amount_and_it_is_on_record(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        paid = int(self.plan.price * 100)
        self.assertEqual((await self._approve(refund["id"], amount_minor=paid + 1)).status_code, 422)
        response = await self._approve(refund["id"], amount_minor=paid - 500, note="协商")
        self.assertEqual(response.json()["amount_minor"], paid - 500)
        async with self.store.sessions() as session:
            event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "refund.approve", AuditEvent.resource_id == refund["id"]))
        self.assertEqual((event.details["amount_changed"], event.details["requested_minor"]), (True, paid))
        self.assertEqual(self.alipay.refunds[refund["out_refund_no"]]["body"]["refund_amount"], f"{(paid - 500) / 100:.2f}")
        await self._nothing_unexplained()

    async def test_only_one_at_a_time_and_never_more_than_was_paid(self):
        order_id = await self._bought("alipay")
        paid = int(self.plan.price * 100)
        first = (await self._ask(order_id, points=100, amount_minor=1000)).json()
        self.assertEqual((await self._ask(order_id)).status_code, 422)
        await self._approve(first["id"])
        self.assertEqual((await self._order(order_id)).status, "partially_refunded")
        self.assertEqual((await self._ask(order_id, amount_minor=paid - 999)).status_code, 422)
        second = (await self._ask(order_id, amount_minor=paid - 1000)).json()
        await self._approve(second["id"])
        self.assertEqual((await self._order(order_id)).status, "refunded")
        self.assertEqual((await self._ask(order_id)).status_code, 422)
        await self._nothing_unexplained()

    async def test_unpaid_and_sandbox_orders_cannot_be_refunded(self):
        self._as("customer")
        unpaid = await self._new_order()
        self.assertEqual((await self._ask(unpaid)).status_code, 422)
        with patch.dict("os.environ", {"PAYMENT_SANDBOX_ENABLED": "1"}):
            sandbox = await self.store.create_order(user_id=self.buyer.id, plan_id=self.plan.id, provider="sandbox", idempotency_key=f"sb-{uuid.uuid4().hex}")
            await self.store.confirm_paid_order(sandbox.id, f"sandbox:{sandbox.id}")
        response = await self._ask(sandbox.id)
        self.assertEqual(response.status_code, 422)
        self.assertIn("真实", response.json()["detail"])

    async def test_an_open_critical_difference_stops_the_refund(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        async with self.store.sessions() as session:
            session.add(ReconItem(fingerprint="R1:x:y", rule="R1", kind="x", severity="critical", order_id=order_id, reference="y", first_run_id="r", last_run_id="r"))
            await session.commit()
        self.assertEqual((await self._approve(refund["id"])).status_code, 422)
        await self._reject(refund["id"])
        self.assertEqual((await self._ask(order_id)).status_code, 422)

    async def test_points_expiring_leave_what_a_refund_set_aside(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id, points=100, amount_minor=500)).json()
        async with self.store.sessions() as session:
            await session.execute(update(PointLot).where(PointLot.order_id == order_id).values(expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
            await session.commit()
        await self.store.expire_points()
        lot = await self._lot(order_id)
        self.assertEqual((lot.remaining, lot.frozen), (Decimal(100), Decimal(100)))
        self.assertEqual((await self._balance())[0], Decimal(0))
        await self._reject(refund["id"])
        await self.store.expire_points()
        self.assertEqual((await self._lot(order_id)).remaining, Decimal(0))
        self.assertEqual(await self._balance(), (Decimal(0), Decimal(0), Decimal(0)))
        await self._nothing_unexplained()

    async def test_a_late_second_payment_after_a_full_refund_also_goes_back(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        # A code from the same order, paid after everything: nothing it could buy, so it goes back by itself.
        self._as("customer")
        async with self.store.sessions() as session:
            from app.platform.models import PaymentAttempt
            session.add(PaymentAttempt(
                order_id=order_id, user_id=self.buyer.id, provider="wechat", merchant_id=self.channels["wechat"].merchant_id,
                out_trade_no="Plate0000000001", amount_minor=int(self.plan.price * 100), currency="CNY",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            ))
            await session.commit()
        self.wechat.trades["Plate0000000001"] = {"trade_state": "NOTPAY", "amount": {"total": int(self.plan.price * 100), "currency": "CNY"}}
        self.wechat.pay("Plate0000000001")
        self._acked("wechat", await self._notify("wechat", "Plate0000000001"))
        self.assertEqual(len([item for item in await self._refunds(order_id) if item.reason == "duplicate_payment"]), 1)
        self.assertEqual((await self._order(order_id)).status, "refunded")
        await self._nothing_unexplained()


class AdjustmentTests(FinanceCase):
    async def _ask_adjust(self, points, name="asker"):
        self._as(name)
        return await self.client.post("/api/admin/wallet-adjustments", json={"user_id": self.buyer.id, "points": points, "reason": "补偿"})

    async def _approve_adjust(self, adjustment_id, name="approver"):
        self._as(name)
        return await self.client.post(f"/api/admin/wallet-adjustments/{adjustment_id}/approve", json={})

    async def test_adding_points_takes_two_people_and_then_they_can_be_spent(self):
        adjustment = (await self._ask_adjust(150)).json()
        self.assertEqual(await self.store.point_balance(self.buyer.id), (Decimal(0), Decimal(0)))
        self.assertEqual((await self._approve_adjust(adjustment["id"], name="asker")).status_code, 403)
        self.assertEqual((await self._approve_adjust(adjustment["id"], name="support")).status_code, 403)
        self.assertEqual((await self._approve_adjust(adjustment["id"])).status_code, 200)
        self.assertEqual((await self.store.point_balance(self.buyer.id))[0], Decimal(150))
        self.assertEqual((await self._approve_adjust(adjustment["id"], name="boss")).status_code, 422)
        self._spend(1)
        await self._nothing_unexplained()

    async def test_taking_points_stops_at_what_can_be_spent(self):
        await self._bought("alipay")
        too_many = (await self._ask_adjust(-(self.plan.points + 1))).json()
        self.assertEqual((await self._approve_adjust(too_many["id"])).status_code, 422)
        some = (await self._ask_adjust(-40)).json()
        self.assertEqual((await self._approve_adjust(some["id"])).status_code, 200)
        self.assertEqual((await self.store.point_balance(self.buyer.id))[0], Decimal(self.plan.points - 40))
        await self._nothing_unexplained()

    async def test_rejected_changes_nothing_and_each_writes_one_ledger_line(self):
        rejected = (await self._ask_adjust(50)).json()
        self._as("approver")
        response = await self.client.post(f"/api/admin/wallet-adjustments/{rejected['id']}/reject", json={"note": "不需要"})
        self.assertEqual(response.json()["status"], "rejected")
        self.assertEqual(await self.store.point_balance(self.buyer.id), (Decimal(0), Decimal(0)))
        async with self.store.sessions() as session:
            self.assertEqual((await session.scalars(select(LedgerEntry).where(LedgerEntry.user_id == self.buyer.id))).all(), [])

    async def test_zero_and_unknown_user_are_refused(self):
        self.assertEqual((await self._ask_adjust(0)).status_code, 422)
        self._as("asker")
        response = await self.client.post("/api/admin/wallet-adjustments", json={"user_id": str(uuid.uuid4()), "points": 5, "reason": "x"})
        self.assertEqual(response.status_code, 404)

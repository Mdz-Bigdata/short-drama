# -*- coding: utf-8 -*-
"""R1 to R10: each rule notices what it is for, keeps quiet when the books agree, and differences live and close properly."""

import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import delete, select, update

from app.platform import payment_flow, reconciliation
from app.platform.billing_book import BillingRefused
from app.platform.models import (
    AuditEvent,
    ChannelBill,
    LedgerEntry,
    MembershipTerm,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    PointBalance,
    PointLot,
    ReconItem,
    ReconRun,
)
from app.platform.payments.base import BillRow, DayBill
from app.platform.reconciliation import CHINA, _save_bill, check_r2, check_r4, check_r5_lots, check_r9, load_books
from tests.payment_fakes import alipay_bill, wechat_bill
from tests.test_payment_flow import DATABASE_URL
from tests.test_refund_flow import FinanceCase


class Case(FinanceCase):
    async def _run(self, rules=reconciliation.DAILY_RULES, **kwargs):
        run = await reconciliation.run_checks(self.store, period=f"manual:{uuid.uuid4()}", rules=rules, channels=self.channels, **kwargs)
        self.assertEqual(run.status, "done", run.summary)
        return run

    async def _open(self, *rules):
        async with self.store.sessions() as session:
            items = (await session.scalars(select(ReconItem).where(ReconItem.status == "open"))).all()
        return {(item.rule, item.kind) for item in items if not rules or item.rule in rules}

    async def _attempt_of(self, order_id):
        async with self.store.sessions() as session:
            return await session.scalar(select(PaymentAttempt).where(PaymentAttempt.order_id == order_id, PaymentAttempt.status == "paid"))

    def _day_of(self, moment):
        return moment.astimezone(CHINA).date() if moment.tzinfo else moment.replace(tzinfo=timezone.utc).astimezone(CHINA).date()

    async def _bill(self, provider, day, *rows):
        await _save_bill(self.store, provider, day, DayBill(uuid.uuid4().bytes, tuple(rows)))

    async def _bill_matching(self, order_id):
        attempt = await self._attempt_of(order_id)
        await self._bill(attempt.provider, self._day_of(attempt.paid_at), BillRow("payment", attempt.out_trade_no, attempt.amount_minor, attempt.channel_trade_no))
        return attempt

    async def _write(self, model, condition, **values):
        async with self.store.sessions() as session:
            await session.execute(update(model).where(condition).values(**values))
            await session.commit()


class AgreeingBooksTests(Case):
    async def test_a_day_of_normal_business_finds_nothing(self):
        order_id = await self._bought("wechat")
        self._spend(1)
        await self._bill_matching(order_id)
        run = await self._run()
        self.assertEqual(await self._open(), set())
        self.assertEqual(run.summary["found"], {})

    async def test_nothing_at_all_finds_nothing(self):
        await self._run()
        self.assertEqual(await self._open(), set())


class R1Tests(Case):
    async def test_on_the_bill_and_unknown_here_is_critical(self):
        await self._bill("alipay", date(2026, 11, 4), BillRow("payment", "Pnever", 100, "1"))
        await self._run(("R1",))
        self.assertEqual(await self._open(), {("R1", "on_bill_not_here")})

    async def test_on_the_bill_and_confirmed_by_a_query_gets_posted(self):
        self._as("customer")
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        out = await self._out(order_id, "alipay")
        self.alipay.pay(out)
        attempt = await self._attempt(out)
        await self._bill("alipay", date(2026, 11, 4), BillRow("payment", out, attempt.amount_minor, self.alipay.trades[out]["trade_no"]))
        run = await self._run(("R1",))
        self.assertEqual(run.summary["posted_from_bill"], 1)
        self.assertEqual((await self._order(order_id)).status, "paid")
        self.assertEqual((await self._attempt(out)).settled_by, "reconciliation")
        await self._granted_once()
        self.assertEqual(await self._open("R1"), set())

    async def test_on_the_bill_but_the_channel_denies_it_is_critical_and_stops_refunds(self):
        self._as("customer")
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        out = await self._out(order_id, "alipay")
        await self._bill("alipay", date(2026, 11, 4), BillRow("payment", out, 100, "x"))
        await self._run(("R1",))
        self.assertEqual(await self._open(), {("R1", "on_bill_not_paid_here")})
        self.assertEqual((await self._order(order_id)).status, "pending")
        async with self.store.sessions() as session:
            item = await session.scalar(select(ReconItem).where(ReconItem.rule == "R1"))
        self.assertEqual(item.order_id, order_id)

    async def test_amount_or_number_on_the_bill_differs(self):
        order_id = await self._bought("alipay")
        attempt = await self._attempt_of(order_id)
        day = self._day_of(attempt.paid_at)
        await self._bill("alipay", day, BillRow("payment", attempt.out_trade_no, attempt.amount_minor - 1, attempt.channel_trade_no))
        await self._run(("R1",))
        self.assertEqual(await self._open(), {("R1", "amount_differs")})
        quote = await self.store.refund_quote(order_id)
        self.assertIn("对账差异", quote["blocked"])

    async def test_paid_here_and_missing_from_that_days_bill_is_critical(self):
        order_id = await self._bought("alipay")
        attempt = await self._attempt_of(order_id)
        noon = datetime.combine(self._day_of(attempt.paid_at), datetime.min.time(), CHINA) + timedelta(hours=12)
        await self._write(PaymentAttempt, PaymentAttempt.id == attempt.id, paid_at=noon.astimezone(timezone.utc))
        await self._bill("alipay", noon.date())
        await self._run(("R1",))
        self.assertEqual(await self._open(), {("R1", "paid_here_not_on_bill")})

    async def test_a_payment_near_midnight_waits_for_the_next_bill_and_closes_by_itself(self):
        order_id = await self._bought("alipay")
        attempt = await self._attempt_of(order_id)
        day = date(2026, 10, 1)
        just_before = datetime.combine(day + timedelta(days=1), datetime.min.time(), CHINA) - timedelta(minutes=1)
        await self._write(PaymentAttempt, PaymentAttempt.id == attempt.id, paid_at=just_before.astimezone(timezone.utc))
        await self._bill("alipay", day)
        await self._run(("R1",))
        self.assertEqual(await self._open(), {("R1", "crosses_midnight")})
        await self._bill("alipay", day + timedelta(days=1), BillRow("payment", attempt.out_trade_no, attempt.amount_minor, attempt.channel_trade_no))
        await self._run(("R1",))
        self.assertEqual(await self._open(), set())

    async def test_a_bill_late_by_a_day_is_fine_and_later_it_is_not(self):
        order_id = await self._bought("alipay")
        attempt = await self._attempt_of(order_id)
        now = datetime.now(timezone.utc)
        await self._write(PaymentAttempt, PaymentAttempt.id == attempt.id, paid_at=now - timedelta(days=1))
        await self._run(("R1",))
        self.assertEqual(await self._open(), set())
        await self._write(PaymentAttempt, PaymentAttempt.id == attempt.id, paid_at=now - timedelta(days=5))
        await self._run(("R1",))
        self.assertEqual(await self._open(), {("R1", "bill_missing")})


class FetchingBillsTests(Case):
    async def test_published_bills_are_kept_once_and_compared(self):
        order_id = await self._bought("wechat")
        attempt = await self._attempt_of(order_id)
        today = datetime.now(CHINA).date()
        yesterday = today - timedelta(days=1)
        await self._write(PaymentAttempt, PaymentAttempt.id == attempt.id, paid_at=(datetime.combine(yesterday, datetime.min.time(), CHINA) + timedelta(hours=9)).astimezone(timezone.utc))
        self.wechat.bills[yesterday.isoformat()] = wechat_bill([(attempt.out_trade_no, attempt.channel_trade_no, attempt.amount_minor)])
        self.alipay.bills[yesterday.isoformat()] = alipay_bill()
        await self._run()
        await self._run()
        async with self.store.sessions() as session:
            bills = (await session.scalars(select(ChannelBill))).all()
        self.assertEqual({(bill.provider, bill.bill_date, bill.row_count) for bill in bills}, {("wechat", yesterday, 1), ("alipay", yesterday, 0)})
        self.assertEqual(await self._open(), set())

    async def test_a_bill_that_cannot_be_trusted_is_reported_not_taken_as_empty(self):
        yesterday = datetime.now(CHINA).date() - timedelta(days=1)
        self.wechat.bills[yesterday.isoformat()] = b"\xef\xbb\xbfgarbage"
        await self._run(("R1",))
        self.assertEqual(await self._open(), {("R1", "bill_unusable")})
        async with self.store.sessions() as session:
            self.assertEqual((await session.scalars(select(ChannelBill))).all(), [])
        self.wechat.bills[yesterday.isoformat()] = wechat_bill()
        await self._run(("R1",))
        self.assertEqual(await self._open(), set())


class TamperingTests(Case):
    """Each rule catches what it is for, shown by damaging the books in that one way."""

    async def test_r2_a_second_payment_with_no_refund(self):
        order_id = await self._bought("wechat")
        attempt = await self._attempt_of(order_id)
        async with self.store.sessions() as session:
            session.add(PaymentAttempt(
                order_id=order_id, user_id=attempt.user_id, provider="alipay", merchant_id="m", out_trade_no="Pextra", channel_trade_no="extra",
                amount_minor=attempt.amount_minor, currency="CNY", status="paid", expires_at=datetime.now(timezone.utc), paid_at=datetime.now(timezone.utc),
            ))
            await session.commit()
        await self._run(("R2",))
        self.assertEqual(await self._open(), {("R2", "second_payment_without_refund")})

    async def test_r2_paid_order_with_no_payment_and_payment_with_order_unpaid(self):
        order_id = await self._bought("wechat")
        await self._write(PaymentAttempt, PaymentAttempt.order_id == order_id, status="closed")
        await self._run(("R2",))
        self.assertEqual(await self._open(), {("R2", "order_paid_without_payment")})
        await self._write(PaymentAttempt, PaymentAttempt.order_id == order_id, status="paid")
        await self._write(PaymentOrder, PaymentOrder.id == order_id, status="closed")
        await self._run(("R2",))
        self.assertEqual(await self._open(), {("R2", "payment_but_order_not_paid")})

    async def test_r2_a_mismatched_notification_stays_on_the_list(self):
        self._as("customer")
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        out = await self._out(order_id, "wechat")
        self.wechat.pay(out)
        await self._notify("wechat", out, amount={"total": 1, "currency": "CNY"})
        await self._run(("R2",))
        self.assertEqual(await self._open(), {("R2", "attempt_mismatch")})

    async def test_r3_a_paid_order_that_granted_nothing(self):
        order_id = await self._bought("wechat")
        async with self.store.sessions() as session:
            await session.execute(delete(MembershipTerm).where(MembershipTerm.order_id == order_id))
            await session.commit()
        await self._run(("R3",))
        self.assertEqual(await self._open(), {("R3", "no_term")})

    async def test_r5_points_changed_by_hand(self):
        order_id = await self._bought("wechat")
        await self._write(PointLot, PointLot.order_id == order_id, remaining=Decimal(1))
        await self._run(("R5",))
        self.assertEqual(await self._open(), {("R5", "lot_differs"), ("R5", "balance_differs")})

    async def test_r5_frozen_points_with_no_refund(self):
        order_id = await self._bought("wechat")
        await self._write(PointLot, PointLot.order_id == order_id, frozen=Decimal(10))
        await self._run(("R5",))
        self.assertIn(("R5", "frozen_differs"), await self._open())
        self.assertIn(("R5", "balance_frozen_differs"), await self._open())

    async def test_r5_held_points_with_no_hold(self):
        await self._bought("wechat")
        await self._write(PointBalance, PointBalance.user_id == self.buyer.id, held=Decimal(10), available=Decimal(self.plan.points - 10))
        await self._run(("R5",))
        self.assertEqual(await self._open(), {("R5", "balance_held_differs")})

    def _needs_editable_records(self):
        if DATABASE_URL:
            self.skipTest("Postgres refuses this damage outright; see test_postgres_refuses_changing_financial_records")

    async def test_postgres_refuses_changing_financial_records(self):
        if not DATABASE_URL:
            self.skipTest("the triggers are on Postgres only")
        await self._bought("alipay")
        for statement in (
            delete(LedgerEntry), update(LedgerEntry).values(amount=Decimal(1)),
            delete(AuditEvent), update(AuditEvent).values(action="x"),
        ):
            await self.store.record_audit(actor_id=None, action="payment.test", resource_type="t", resource_id="t")
            with self.subTest(str(statement)), self.assertRaisesRegex(Exception, "append-only"):
                async with self.store.sessions() as session:
                    await session.execute(statement)
                    await session.commit()

    async def test_r4_a_refund_that_did_not_take_its_points(self):
        self._needs_editable_records()
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        async with self.store.sessions() as session:
            await session.execute(delete(LedgerEntry).where(LedgerEntry.category == "refund_clawback"))
            await session.commit()
        await self._run(("R4",))
        self.assertEqual(await self._open(), {("R4", "points_not_taken")})

    async def test_r4_points_taken_when_the_refund_did_not_happen(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        await self._write(PaymentRefund, PaymentRefund.id == refund["id"], status="failed")
        await self._run(("R4",))
        self.assertIn(("R4", "points_taken_without_refund"), await self._open())

    async def test_r4_refunded_more_than_paid_and_status_wrong(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        await self._write(PaymentRefund, PaymentRefund.id == refund["id"], refund_minor=999999)
        await self._run(("R4",))
        self.assertIn(("R4", "refunded_more_than_paid"), await self._open())
        await self._write(PaymentRefund, PaymentRefund.id == refund["id"], refund_minor=int(self.plan.price * 100))
        await self._write(PaymentOrder, PaymentOrder.id == order_id, status="partially_refunded")
        await self._run(("R4",))
        self.assertEqual(await self._open("R4"), {("R4", "order_status_differs")})

    async def test_r4_against_the_bill(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        attempt = await self._attempt_of(order_id)
        day = self._day_of(attempt.paid_at)
        await self._bill("alipay", day + timedelta(days=5),
                         BillRow("refund", attempt.out_trade_no, 1, "x", refund["out_refund_no"]),
                         BillRow("refund", "Pnever", 5, "x", "Rnever"))
        await self._run(("R4",))
        self.assertEqual(await self._open(), {("R4", "refund_amount_differs"), ("R4", "refund_on_bill_not_here")})

    async def test_r4_a_succeeded_refund_missing_from_a_later_bill(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        await self._bill("alipay", datetime.now(CHINA).date() + timedelta(days=2))
        await self._run(("R4",))
        self.assertEqual(await self._open(), {("R4", "refund_not_on_bill")})

    async def test_r4_stuck_and_undecided(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await self._write(PaymentRefund, PaymentRefund.id == refund["id"], created_at=datetime.now(timezone.utc) - timedelta(days=4))
        await self._run(("R4",))
        self.assertEqual(await self._open(), {("R4", "refund_waiting_for_decision")})
        self.alipay.down = True
        await self._approve(refund["id"])
        await self._run(("R4",))
        self.assertEqual(await self._open(), {("R4", "refund_stuck")})

    async def test_r8_a_term_running_on_a_refunded_order(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        await self._write(MembershipTerm, MembershipTerm.order_id == order_id, status="active")
        await self._run(("R8",))
        self.assertEqual(await self._open(), {("R8", "term_without_paid_order")})

    async def test_r9_money_and_points_stop_agreeing(self):
        order_id = await self._bought("alipay")
        await self._write(PointLot, PointLot.order_id == order_id, unit_value_minor=Decimal(1))
        await self._run(("R9",))
        self.assertEqual(await self._open(), {("R9", "money_and_points_differ")})

    async def test_r10_no_audit_record_or_no_right_to_it(self):
        self._needs_editable_records()
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        await self._run(("R10",))
        self.assertEqual(await self._open(), set())
        async with self.store.sessions() as session:
            event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "refund.approve"))
            event.details = {**event.details, "actor_roles": ["support"]}
            await session.commit()
        await self._run(("R10",))
        self.assertEqual(await self._open(), {("R10", "not_allowed_at_the_time")})
        async with self.store.sessions() as session:
            await session.execute(delete(AuditEvent).where(AuditEvent.action == "refund.approve"))
            await session.commit()
        await self._run(("R10",))
        self.assertEqual(await self._open(), {("R10", "no_audit_record")})

    async def test_r10_a_role_granted_with_no_record(self):
        self._needs_editable_records()
        await self.store.set_user_roles(self.staff["boss"]["user_id"], self.buyer.id, ["support"])
        await self._run(("R10",))
        self.assertEqual(await self._open(), set())
        async with self.store.sessions() as session:
            await session.execute(delete(AuditEvent).where(AuditEvent.action == "user.roles_change"))
            await session.commit()
        await self._run(("R10",))
        self.assertEqual(await self._open(), {("R10", "role_grant_not_audited")})


class ItemLifecycleTests(Case):
    async def _damaged(self):
        order_id = await self._bought("wechat")
        await self._write(PointLot, PointLot.order_id == order_id, unit_value_minor=Decimal(1))
        await self._run(("R9",))
        async with self.store.sessions() as session:
            return await session.scalar(select(ReconItem).where(ReconItem.rule == "R9")), order_id

    async def _count(self):
        async with self.store.sessions() as session:
            return len((await session.scalars(select(ReconItem))).all())

    async def test_seen_again_is_the_same_item(self):
        await self._damaged()
        await self._run(("R9",))
        await self._run(("R9",))
        self.assertEqual(await self._count(), 1)

    async def test_no_longer_true_closes_itself(self):
        item, order_id = await self._damaged()
        lot = await self._lot(order_id)
        await self._write(PointLot, PointLot.id == lot.id, unit_value_minor=int(self.plan.price * 100) / Decimal(self.plan.points))
        await self._run(("R9",))
        async with self.store.sessions() as session:
            again = await session.get(ReconItem, item.id)
        self.assertEqual(again.status, "auto_resolved")

    async def test_a_rule_not_in_this_run_leaves_its_items_alone(self):
        item, _ = await self._damaged()
        await self._run(("R2",))
        async with self.store.sessions() as session:
            self.assertEqual((await session.get(ReconItem, item.id)).status, "open")

    async def test_a_person_explains_it_and_it_stays_explained_unless_it_changes(self):
        item, order_id = await self._damaged()
        self._as("auditor")
        url = f"/api/admin/recon/items/{item.id}/resolve"
        self.assertEqual((await self.client.post(url, json={"status": "ignored", "resolution": "x"})).status_code, 403)
        self._as("approver")
        self.assertEqual((await self.client.post(url, json={"status": "wrong", "resolution": "x"})).status_code, 422)
        self.assertEqual((await self.client.post(url, json={"status": "ignored", "resolution": "   "})).status_code, 422)
        response = await self.client.post(url, json={"status": "ignored", "resolution": "已知的测试数据"})
        self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual((await self.client.post(url, json={"status": "resolved", "resolution": "再次"})).status_code, 422)
        async with self.store.sessions() as session:
            event = await session.scalar(select(AuditEvent).where(AuditEvent.action == "recon.resolve"))
        self.assertEqual(event.actor_id, self.staff["approver"]["user_id"])
        await self._run(("R9",))
        self.assertEqual(await self._open(), set())
        self.assertEqual(await self._count(), 1)
        await self._write(PointLot, PointLot.order_id == order_id, unit_value_minor=Decimal(2))
        await self._run(("R9",))
        self.assertEqual(await self._open(), {("R9", "money_and_points_differ")})
        self.assertEqual(await self._count(), 2)

    async def test_critical_items_are_logged_and_audited(self):
        with self.assertLogs("app.platform.reconciliation", "ERROR"):
            await self._damaged()
        self.assertEqual(len(await self._alerts("recon.critical")), 1)

    async def test_each_period_runs_once(self):
        first = await reconciliation.run_checks(self.store, period="hourly:x", rules=("R2",), channels=self.channels)
        second = await reconciliation.run_checks(self.store, period="hourly:x", rules=("R2",), channels=self.channels)
        self.assertEqual(first.status, "done")
        self.assertIsNone(second)

    async def test_a_run_that_breaks_says_so_and_does_not_close_anything(self):
        item, _ = await self._damaged()
        with patch.object(reconciliation, "load_books", side_effect=RuntimeError("boom")), self.assertLogs("app.platform.reconciliation", "ERROR"):
            run = await reconciliation.run_checks(self.store, period="manual:broken", rules=("R9",), channels=self.channels)
        self.assertEqual((run.status, run.summary), ("failed", {"error": "RuntimeError"}))
        async with self.store.sessions() as session:
            self.assertEqual((await session.get(ReconItem, item.id)).status, "open")


class ConsoleTests(Case):
    async def test_who_can_see_what(self):
        order_id = await self._bought("alipay")
        self._as("customer")
        for path in ("/api/admin/orders", f"/api/admin/orders/{order_id}", "/api/admin/refunds", "/api/admin/recon/items", "/api/admin/recon/runs", "/api/admin/finance/summary", "/api/admin/wallet-adjustments"):
            self.assertEqual((await self.client.get(path)).status_code, 403, path)
        self.assertEqual((await self.client.post("/api/admin/recon/runs")).status_code, 403)
        self._as("auditor")
        self.assertEqual((await self.client.get("/api/admin/orders")).status_code, 200)
        self.assertEqual((await self.client.get("/api/admin/finance/summary")).status_code, 200)
        self.assertEqual((await self.client.post("/api/admin/recon/runs")).status_code, 403)
        self._as("support")
        self.assertEqual((await self.client.get("/api/admin/orders")).status_code, 200)
        self.assertEqual((await self.client.get("/api/admin/finance/summary")).status_code, 403)
        self._as("approver")
        response = await self.client.post("/api/admin/recon/runs")
        self.assertEqual(response.status_code, 201, response.text)

    async def test_finding_orders(self):
        order_id = await self._bought("alipay")
        attempt = await self._attempt_of(order_id)
        self._as("support")
        async with self.store.sessions() as session:
            email = (await session.get(__import__("app.platform.models", fromlist=["PlatformUser"]).PlatformUser, self.buyer.id)).email
        for query, expected in ((email, 1), (order_id, 1), (attempt.out_trade_no, 1), (attempt.channel_trade_no, 1), ("nobody%", 0), ("%", 0)):
            body = (await self.client.get("/api/admin/orders", params={"q": query})).json()
            self.assertEqual(body["total"], expected, query)
        detail = (await self.client.get(f"/api/admin/orders/{order_id}")).json()
        self.assertEqual(detail["quote"]["suggested_minor"], int(self.plan.price * 100))
        self.assertEqual(detail["attempts"][0]["out_trade_no"], attempt.out_trade_no)
        self.assertEqual((await self.client.get("/api/admin/orders/none")).status_code, 404)

    async def test_the_summary_adds_up(self):
        order_id = await self._bought("alipay")
        self._spend(1)
        self._as("auditor")
        paid = int(self.plan.price * 100)
        unit = Decimal(paid) / self.plan.points
        body = (await self.client.get("/api/admin/finance/summary")).json()
        self.assertEqual(body["received_minor"], paid)
        self.assertAlmostEqual(Decimal(str(body["earned_usage_minor"])), unit * 100, places=2)
        self.assertAlmostEqual(Decimal(str(body["deferred_minor"])), unit * (self.plan.points - 100), places=2)
        self.assertLessEqual(abs(Decimal(str(body["difference_minor"]))), Decimal(1))
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        self._as("auditor")
        body = (await self.client.get("/api/admin/finance/summary")).json()
        self.assertEqual(body["refunded_minor"], refund["amount_minor"])
        self.assertAlmostEqual(Decimal(str(body["deferred_minor"])), Decimal(0), places=2)
        self.assertEqual(len(body["by_month"]), 1)
        self.assertEqual(body["by_month"][0]["received_minor"], paid)


class RandomBusinessTests(Case):
    """Any order of paying, spending, refunding and expiring leaves the books agreeing, at every step."""

    async def _check(self, step):
        books = await load_books(self.store)
        now = datetime.now(timezone.utc)
        self.assertEqual(check_r5_lots(books), [], step)
        self.assertEqual(check_r2(books), [], step)
        self.assertEqual([item for item in check_r4(books, now) if item.kind != "refund_failed"], [], step)
        self.assertEqual(check_r9(books), [], step)
        differences = await self.store.billing_differences(settled_before=now + timedelta(days=1))
        self.assertEqual(differences["r3"]["differences"], 0, step)
        self.assertEqual(differences["r5"]["differences"], 0, step)

    async def test_random_sequences(self):
        for seed in range(3):
            rng = random.Random(seed)
            orders, asked, approved = [], [], []
            moment = datetime.now(timezone.utc)
            for step in range(45):
                action = rng.choice(("buy", "buy", "spend", "spend", "spend", "ask", "ask", "approve", "reject", "sweep", "expire", "adjust", "fail"))
                label = (seed, step, action)
                if action == "buy":
                    orders.append(await self._bought(rng.choice(("alipay", "wechat"))))
                elif action == "spend":
                    try:
                        self._spend(rng.randint(1, 3))
                    except BillingRefused:
                        pass
                elif action == "ask" and orders:
                    fields = {"points": rng.randint(0, 50), "amount_minor": rng.randint(1, 300)} if rng.random() < 0.3 else {}
                    response = await self._ask(rng.choice(orders), **fields)
                    if response.status_code == 201:
                        asked.append(response.json()["id"])
                elif action in ("approve", "reject") and asked:
                    refund_id = asked.pop(rng.randrange(len(asked)))
                    await (self._approve(refund_id) if action == "approve" else self._reject(refund_id))
                    if action == "approve":
                        approved.append(refund_id)
                elif action == "fail" and asked:
                    self.wechat.refund_status = rng.choice(("SUCCESS", "ABNORMAL"))
                elif action == "sweep":
                    moment += timedelta(minutes=2)
                    await payment_flow.sweep(self.store, self.channels, moment)
                elif action == "expire" and orders:
                    await self._write(PointLot, PointLot.order_id == rng.choice(orders), expires_at=datetime.now(timezone.utc) - timedelta(days=1))
                    await self.store.expire_points()
                elif action == "adjust":
                    self._as("asker")
                    created = await self.client.post("/api/admin/wallet-adjustments", json={"user_id": self.buyer.id, "points": rng.choice((30, -20)), "reason": "随机"})
                    self._as("approver")
                    await self.client.post(f"/api/admin/wallet-adjustments/{created.json()['id']}/approve", json={})
                await self._check(label)

# -*- coding: utf-8 -*-
"""Charging: no provider call without the points for it, the real amount afterwards, and the books agree."""

import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.api.auth_api import _public_user, get_current_user
from app.core import usage_ledger
from app.platform.billing_book import BillingBook, BillingRefused, set_active_book
from app.platform.dependencies import get_platform_store
from app.platform.entitlements import PLAN_ENTITLEMENTS
from app.platform.models import LedgerEntry, MembershipTerm, PointBalance, PointHold, PointLot
from app.platform.store import PlatformStore
from app.platform.usage_billing import UsageSpool, drain
from tests import test_stage_five_queue as queue_tests

FAR_FUTURE_SETTLED = datetime.now(timezone.utc) + timedelta(days=3650)


class _Case(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        url = f"sqlite+aiosqlite:///{Path(self.temp.name) / 'platform.sqlite3'}"
        self.store = PlatformStore(url)
        self.addAsyncCleanup(self.store.close)
        await self.store.create_schema()
        await self.store.seed_billing_plans()
        self.plans = {plan.id: plan for plan in await self.store.list_plans()}
        self.owners = {"t1": None}
        self.book = BillingBook(url, lambda task_id: self.owners.get(task_id))
        self.addCleanup(self.book.close)
        usage_ledger.configure_billing_guard(self.book)
        self.addCleanup(usage_ledger.configure_billing_guard, None)
        set_active_book(self.book)
        self.addCleanup(set_active_book, None)
        self.boss, _ = await self.store.create_user(email="boss@example.com", phone=None, password="boss-password", role="admin")
        self.buyer, _ = await self.store.create_user(email="buyer@example.com", phone=None, password="buyer-password")
        self.owners["t1"] = self.buyer.id
        now = datetime.now(timezone.utc) - timedelta(minutes=1)
        for fields in (
            dict(model="minimax-h3", kind="per_second", price=Decimal(28)),
            dict(model="seedream", kind="per_image", price=Decimal(32)),
            dict(model="deepseek-flash", kind="per_million_tokens", input=Decimal(100), cached_input=Decimal(2), output=Decimal(400)),
        ):
            await self.store.add_point_rate(actor_id=self.boss.id, effective_from=now, **fields)
        patcher = patch.dict(os.environ, {"PAYMENT_SANDBOX_ENABLED": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _buy(self, plan="starter", key="buy-key-0001", user=None):
        order = await self.store.create_order(
            user_id=(user or self.buyer).id, plan_id=plan, provider="sandbox", idempotency_key=key,
        )
        await self.store.confirm_paid_order(order.id, f"sandbox:{key}")
        return order

    async def _balance(self, user=None):
        available, held = await self.store.point_balance((user or self.buyer).id)
        return available, held

    async def _books_agree(self):
        result = await self.store.billing_differences(settled_before=FAR_FUTURE_SETTLED)
        self.assertEqual(result["r3"]["differences"], 0, result["r3"])
        self.assertEqual(result["r5"]["differences"], 0, result["r5"])
        return result

    def _call_video(self, seconds=10, *, succeed=True, task="t1", user=None, model="MiniMax-H3", resolution=None):
        """One gated provider call. Returns whether the provider was reached."""
        provider = MagicMock()

        def run():
            usage_ledger.bind_user(user)
            units = {"seconds": seconds, **({"resolution": resolution} if resolution else {})}
            with usage_ledger.bind_task(task, "stage_5"), usage_ledger.timed_call("video", provider="minimax", model=model, units=units) as outcome:
                provider()
                if not succeed:
                    outcome["failed"] = True

        import contextvars
        contextvars.copy_context().run(run)
        return provider.call_count == 1


class GrantTests(_Case):
    async def test_paying_grants_a_lot_a_term_and_a_balance(self):
        order = await self._buy()
        self.assertEqual(await self._balance(), (Decimal(500), Decimal(0)))
        async with self.store.sessions() as session:
            lot = await session.scalar(select(PointLot).where(PointLot.order_id == order.id))
            term = await session.scalar(select(MembershipTerm).where(MembershipTerm.order_id == order.id))
        self.assertEqual((lot.granted, lot.remaining), (Decimal(500), Decimal(500)))
        self.assertEqual(lot.unit_value_minor, Decimal("5.800000"))
        self.assertEqual(term.entitlements, PLAN_ENTITLEMENTS["starter"])
        await self._books_agree()

    async def test_the_same_payment_twice_grants_once(self):
        order = await self._buy()
        await self.store.confirm_paid_order(order.id, "sandbox:buy-key-0001")
        self.assertEqual(await self._balance(), (Decimal(500), Decimal(0)))
        await self._books_agree()

    async def test_changing_a_plan_later_does_not_change_what_was_bought(self):
        await self._buy()
        with patch.dict(PLAN_ENTITLEMENTS["starter"], {"project.max": 1}):
            self.assertEqual((await self.store.effective_entitlements(self.buyer.id))["project.max"], 10)

    async def test_with_nothing_bought_it_is_the_free_plan(self):
        self.assertEqual(await self.store.effective_entitlements(self.buyer.id), PLAN_ENTITLEMENTS["free"])

    async def test_a_downgrade_waits_for_the_paid_period_to_end(self):
        await self._buy("pro", "pro-key-0001")
        await self._buy("starter", "starter-key-01")
        self.assertEqual((await self.store.get_membership(self.buyer.id))[1].id, "pro")
        self.assertEqual((await self.store.effective_entitlements(self.buyer.id))["project.max"], PLAN_ENTITLEMENTS["pro"]["project.max"])
        async with self.store.sessions() as session:
            terms = (await session.scalars(select(MembershipTerm).where(MembershipTerm.user_id == self.buyer.id))).all()
            for term in terms:
                moved = -timedelta(days=31)
                term.starts_at, term.expires_at = term.starts_at + moved, term.expires_at + moved
            await session.commit()
        self.assertEqual((await self.store.get_membership(self.buyer.id))[1].id, "starter")
        self.assertEqual((await self.store.effective_entitlements(self.buyer.id))["project.max"], 10)

    async def test_when_a_term_runs_out_it_is_the_free_plan_with_no_job_needed(self):
        await self._buy("pro", "pro-key-0002")
        async with self.store.sessions() as session:
            await session.execute(update(MembershipTerm).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await session.commit()
        self.assertEqual(await self.store.effective_entitlements(self.buyer.id), PLAN_ENTITLEMENTS["free"])


class GateTests(_Case):
    async def test_with_no_points_the_provider_is_never_reached(self):
        with self.assertRaises(BillingRefused) as caught:
            self._call_video()
        self.assertEqual(caught.exception.code, "insufficient_points")
        self.assertEqual(caught.exception.required, 280)
        self.assertEqual(caught.exception.available, 0)

    async def test_a_refusal_gets_past_except_exception(self):
        reached = False
        try:
            try:
                self._call_video()
                reached = True
            except Exception:  # noqa: BLE001 - the shape of the fallbacks all over the pipeline
                reached = True
        except BillingRefused:
            pass
        self.assertFalse(reached)

    async def test_a_success_takes_the_real_amount(self):
        await self._buy()
        self.assertTrue(self._call_video(10))
        self.assertEqual(await self._balance(), (Decimal(220), Decimal(0)))
        await self._books_agree()

    async def test_the_real_amount_not_the_estimate(self):
        await self._buy()
        import contextvars

        def run():
            with usage_ledger.bind_task("t1"), usage_ledger.timed_call("text", provider="deepseek", model="deepseek-flash", units={"input_chars": 1000}) as outcome:
                outcome["units"].update(input_tokens=1000, cached_tokens=900, output_tokens=100)

        contextvars.copy_context().run(run)
        # 100 fresh tokens at 100, 900 cached at 2, 100 out at 400, per million.
        available, held = await self._balance()
        self.assertEqual((Decimal(500) - available, held), (Decimal("0.0518"), Decimal(0)))
        await self._books_agree()

    async def test_a_failed_call_takes_nothing_and_gives_the_hold_back(self):
        await self._buy()
        self._call_video(10, succeed=False)
        self.assertEqual(await self._balance(), (Decimal(500), Decimal(0)))
        await self._books_agree()

    async def test_a_call_that_raises_takes_nothing(self):
        await self._buy()
        import contextvars

        def run():
            with usage_ledger.bind_task("t1"), usage_ledger.timed_call("video", provider="minimax", model="MiniMax-H3", units={"seconds": 10}):
                raise RuntimeError("provider down")

        with self.assertRaises(RuntimeError):
            contextvars.copy_context().run(run)
        self.assertEqual(await self._balance(), (Decimal(500), Decimal(0)))

    async def test_two_calls_cannot_spend_the_same_points(self):
        await self._buy()  # 500 points; each call holds 280
        started = threading.Barrier(2)
        reached, refused = [], []

        def worker():
            import contextvars

            def run():
                try:
                    with usage_ledger.bind_task("t1"), usage_ledger.timed_call("video", provider="minimax", model="MiniMax-H3", units={"seconds": 10}):
                        reached.append(1)
                        started.wait(timeout=5)
                except BillingRefused:
                    refused.append(1)
                except threading.BrokenBarrierError:
                    pass

            contextvars.copy_context().run(run)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((len(reached), len(refused)), (1, 1))
        await self._books_agree()

    async def test_a_model_with_no_rate_is_refused_and_never_called(self):
        await self._buy()
        with self.assertRaises(BillingRefused) as caught:
            self._call_video(model="kling-3")
        self.assertEqual(caught.exception.code, "rate_missing")
        self.assertEqual(await self._balance(), (Decimal(500), Decimal(0)))

    async def test_a_call_with_nothing_to_measure_is_refused_not_free(self):
        await self._buy()
        with self.assertRaises(BillingRefused) as caught:
            self._call_video(seconds=0)
        self.assertEqual(caught.exception.code, "rate_missing")

    async def test_2k_with_only_the_base_rate_is_refused(self):
        await self._buy("pro", "pro-key-0003")
        with self.assertRaises(BillingRefused) as caught:
            self._call_video(resolution="2k")
        self.assertEqual(caught.exception.code, "rate_missing")
        self.assertTrue(self._call_video(resolution="768p"))

    async def test_2k_with_its_own_rate_needs_a_plan_that_includes_it(self):
        await self.store.add_point_rate(actor_id=self.boss.id, model="minimax-h3", resolution="2k", kind="per_second", price=Decimal(43), effective_from=datetime.now(timezone.utc) - timedelta(minutes=1))
        with patch.object(self.book, "_rates", (0.0, [])):
            await self._buy("starter", "starter-key-02")
            with self.assertRaises(BillingRefused) as caught:
                self._call_video(resolution="2k")
            self.assertEqual(caught.exception.code, "feature_not_in_plan")
            await self._buy("pro", "pro-key-0004")
            self.assertTrue(self._call_video(resolution="2k"))
        self.assertEqual((await self._balance())[0], Decimal(10500) - Decimal(430))

    async def test_nobody_to_bill_is_refused(self):
        with self.assertRaises(BillingRefused) as caught:
            self._call_video(task=None, user=None)
        self.assertEqual(caught.exception.code, "unattributed")

    async def test_staff_are_not_charged_and_customers_are_not_charged_for_staff(self):
        await self._buy()
        self.assertTrue(self._call_video(user=self.boss.id))  # on the customer's project
        self.owners["t2"] = self.boss.id
        self.assertTrue(self._call_video(task="t2", user=self.boss.id))  # on their own
        self.assertEqual(await self._balance(), (Decimal(500), Decimal(0)))

    async def test_free_providers_need_nothing(self):
        import contextvars

        def run():
            with usage_ledger.timed_call("audio", provider="local", model="", units={"characters": 10}):
                pass

        contextvars.copy_context().run(run)

    async def test_earliest_expiring_points_go_first(self):
        await self._buy("starter", "starter-key-03")
        await self._buy("starter", "starter-key-04")
        self._call_video(10)
        async with self.store.sessions() as session:
            lots = (await session.scalars(select(PointLot).order_by(PointLot.expires_at))).all()
        self.assertEqual([lot.remaining for lot in lots], [Decimal(220), Decimal(500)])

    async def test_more_used_than_held_takes_what_is_there_and_says_what_was_short(self):
        await self._buy()  # 500
        import contextvars

        def run():
            with usage_ledger.bind_task("t1"), usage_ledger.timed_call("video", provider="minimax", model="MiniMax-H3", units={"seconds": 1}) as outcome:
                outcome["units"]["seconds"] = 100  # 2800 points against 28 held

        with self.assertLogs("app.platform.billing_book", level="WARNING"):
            contextvars.copy_context().run(run)
        self.assertEqual(await self._balance(), (Decimal(0), Decimal(0)))
        async with self.store.sessions() as session:
            debit = await session.scalar(select(LedgerEntry).where(LedgerEntry.category == "usage_charge"))
        self.assertEqual((debit.amount, debit.metadata_json["shortfall"]), (Decimal(500), "2300.0000"))
        await self._books_agree()

    async def test_a_hold_left_by_a_dead_process_goes_back(self):
        await self._buy()
        handle = self.book.reserve(media_type="video", provider="minimax", model="MiniMax-H3", units={"seconds": 10}, task_id="t1", user_id=None)
        self.assertEqual(await self._balance(), (Decimal(220), Decimal(280)))
        async with self.store.sessions() as session:
            await session.execute(update(PointHold).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await session.commit()
        self.assertEqual(self.book.release_stale(), 1)
        self.assertEqual(await self._balance(), (Decimal(500), Decimal(0)))
        self.book.settle(handle, {"id": "late", "status": "success", "units": {"seconds": 10}, "model": "m"})
        self.assertEqual(await self._balance(), (Decimal(220), Decimal(0)), "a call that finished late is still paid for")
        await self._books_agree()

    async def test_a_batch_that_cannot_be_paid_for_does_not_start(self):
        await self._buy()
        with self.assertRaises(BillingRefused):
            self.book.preflight(task_id="t1", user_id=None, media_type="video", model="MiniMax-H3", units={"seconds": 18})
        self.book.preflight(task_id="t1", user_id=None, media_type="video", model="MiniMax-H3", units={"seconds": 17})

    async def test_limits_by_plan(self):
        with self.assertRaises(BillingRefused):
            self.book.require_feature(self.buyer.id, "project.max", current=2)
        self.book.require_feature(self.buyer.id, "project.max", current=1)
        with self.assertRaises(BillingRefused):
            self.book.require_feature(self.buyer.id, "mcp.access")
        await self._buy("pro", "pro-key-0005")
        self.book.require_feature(self.buyer.id, "project.max", current=100000)
        self.book.require_feature(self.buyer.id, "mcp.access")
        self.book.require_feature(self.boss.id, "export.jianying")


class ExpiryAndVoidTests(_Case):
    async def test_points_past_their_date_go_with_a_ledger_line(self):
        await self._buy()
        async with self.store.sessions() as session:
            await session.execute(update(PointLot).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await session.commit()
        self.assertEqual(await self.store.expire_points(), 1)
        self.assertEqual(await self.store.expire_points(), 0)
        self.assertEqual(await self._balance(), (Decimal(0), Decimal(0)))
        self.assertEqual((await self.store.wallet(self.buyer.id)).points, 0)
        await self._books_agree()

    async def test_points_in_use_are_left_for_the_next_pass(self):
        await self._buy()
        handle = self.book.reserve(media_type="video", provider="minimax", model="MiniMax-H3", units={"seconds": 10}, task_id="t1", user_id=None)
        async with self.store.sessions() as session:
            await session.execute(update(PointLot).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await session.commit()
        self.assertEqual(await self.store.expire_points(), 0)
        self.book.settle(handle, {"id": "u", "status": "failed", "units": {}, "model": "m"})
        self.assertEqual(await self.store.expire_points(), 1)

    async def test_sandbox_points_are_voided_once_and_the_trail_stays(self):
        await self._buy()
        self.assertEqual(await self.store.void_sandbox_points(), 1)
        self.assertEqual(await self.store.void_sandbox_points(), 0)
        self.assertEqual(await self._balance(), (Decimal(0), Decimal(0)))
        wallet = await self.store.wallet(self.buyer.id)
        self.assertEqual((wallet.points, len(wallet.entries)), (0, 2))
        await self._books_agree()

    async def test_points_from_before_lots_existed_are_voided_too(self):
        order = await self._buy()
        async with self.store.sessions() as session:
            await session.delete(await session.scalar(select(PointLot).where(PointLot.order_id == order.id)))
            await session.execute(update(PointBalance).values(available=0))
            await session.commit()
        result = await self.store.billing_differences(settled_before=FAR_FUTURE_SETTLED)
        self.assertEqual(result["r5"]["differences"], 0, "known and listed, not a difference")
        self.assertEqual(result["sandbox_points_not_voided"], {self.buyer.id: "500.0000"})
        await self.store.void_sandbox_points()
        self.assertEqual((await self.store.wallet(self.buyer.id)).points, 0)
        result = await self.store.billing_differences(settled_before=FAR_FUTURE_SETTLED)
        self.assertEqual(result["sandbox_points_not_voided"], {})
        self.assertEqual(result["r5"]["differences"], 0, result["r5"])


class ReconciliationTests(_Case):
    async def test_a_ledger_that_does_not_match_shows(self):
        await self._buy()
        async with self.store.sessions() as session:
            await session.execute(update(PointBalance).values(available=Decimal(499)))
            await session.commit()
        result = await self.store.billing_differences(settled_before=FAR_FUTURE_SETTLED)
        self.assertEqual(result["r5"]["differences"], 1)

    async def test_a_paid_order_with_nothing_granted_shows(self):
        order = await self._buy()
        async with self.store.sessions() as session:
            await session.delete(await session.scalar(select(MembershipTerm).where(MembershipTerm.order_id == order.id)))
            await session.commit()
        result = await self.store.billing_differences(settled_before=FAR_FUTURE_SETTLED)
        self.assertEqual(result["r3"]["samples"][0]["problems"], ["no_term"])

    async def test_what_a_call_came_to_is_what_was_taken(self):
        await self._buy()
        spool = UsageSpool(Path(self.temp.name) / "spool")
        usage_ledger.configure_billing_sink(spool.append)
        self.addCleanup(usage_ledger.configure_billing_sink, None)
        self._call_video(10)
        await drain(self.store, spool, lambda _task: self.buyer.id)
        rows = await self.store.list_usage_charges()
        self.assertEqual((rows[0].billing_mode, rows[0].points), ("charged", Decimal("280.0000")))
        result = await self._books_agree()
        self.assertEqual((result["usage_vs_ledger"]["checked"], result["usage_vs_ledger"]["differences"]), (1, 0))
        async with self.store.sessions() as session:
            await session.delete(await session.scalar(select(LedgerEntry).where(LedgerEntry.category == "usage_charge")))
            await session.commit()
        result = await self.store.billing_differences(settled_before=FAR_FUTURE_SETTLED)
        self.assertEqual(result["usage_vs_ledger"]["differences"], 1)


class RequestTests(_Case):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        from main import app
        self.app = app
        self.app.dependency_overrides[get_platform_store] = lambda: self.store
        self.addCleanup(self.app.dependency_overrides.clear)
        fresh = await self.store.get_user(self.buyer.id)

        async def logged_in():
            usage_ledger.bind_user(fresh.id)
            return _public_user(fresh)

        self.app.dependency_overrides[get_current_user] = logged_in
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    async def test_a_refusal_in_a_request_is_a_402_that_says_why(self):
        element = self.client.post("/api/elements", json={"kind": "prop", "name": "长剑"}).json()
        generate = MagicMock(return_value=("https://x/a.png", "volcengine"))
        with patch("app.api.element_api.element_image_gateway._generate_image_unmetered", generate):
            response = self.client.post(f"/api/elements/{element['id']}/regenerate", json={"prompt": ""})
        self.assertEqual(response.status_code, 402, response.text)
        body = response.json()
        self.assertTrue(body["code"] in {"insufficient_points", "rate_missing"}, body)
        generate.assert_not_called()

    async def test_a_browser_on_another_origin_can_read_the_402(self):
        from app.api import drama_api
        origin = "http://localhost:5173"
        with patch.object(drama_api.service.repo, "get_task", return_value={"task_id": "t1", "owner_user_id": self.buyer.id}):
            response = self.client.get("/api/drama/t1/timeline/jianying.zip", headers={"Origin": origin})
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.headers.get("access-control-allow-origin"), origin, "without this the browser reports a network error")

    async def test_the_jianying_export_needs_a_plan_that_includes_it(self):
        from app.api import drama_api
        with patch.object(drama_api.service.repo, "get_task", return_value={"task_id": "t1", "owner_user_id": self.buyer.id}):
            response = self.client.get("/api/drama/t1/timeline/jianying.zip")
        self.assertEqual(response.status_code, 402, response.text)
        self.assertEqual(response.json()["code"], "feature_not_in_plan")

    async def test_entitlements_and_wallet_say_what_is_there(self):
        await self._buy()
        self.assertEqual(self.client.get("/api/billing/entitlements").json()["items"]["project.max"], 10)
        wallet = self.client.get("/api/billing/wallet").json()
        self.assertEqual((Decimal(str(wallet["available"])), Decimal(str(wallet["held"]))), (Decimal(500), Decimal(0)))

    async def test_only_finance_sees_the_reconciliation(self):
        self.assertEqual(self.client.get("/api/admin/recon/billing").status_code, 403)
        fresh = await self.store.get_user(self.boss.id)
        self.app.dependency_overrides[get_current_user] = lambda: _public_user(fresh)
        self.assertEqual(self.client.get("/api/admin/recon/billing").status_code, 200)


class SwitchedOffTests(unittest.IsolatedAsyncioTestCase):
    async def test_with_charging_off_nothing_is_gated_or_taken(self):
        self.assertIsNone(usage_ledger._billing_guard)
        import contextvars
        provider = MagicMock()

        def run():
            with usage_ledger.timed_call("video", provider="minimax", model="kling-3", units={"seconds": 10}):
                provider()

        contextvars.copy_context().run(run)
        provider.assert_called_once()


class QueueStopTests(queue_tests.StageFiveQueueTests):
    """Video runs on a worker pool, where a refusal has further to travel. Only this test is added to the inherited ones."""

    def test_a_refusal_on_a_worker_stops_the_stage_and_does_not_hang(self):
        calls = []

        def refuse(_prompt):
            calls.append(1)
            raise BillingRefused("insufficient_points", "积分不足：这一步预计需要 280 积分")

        finished = threading.Event()
        caught: list[BaseException] = []

        def run():
            try:
                self._run(queue_tests._task(3), on_video=refuse)
            except BaseException as exc:  # noqa: BLE001 - whatever comes out is the result
                caught.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(finished.wait(60), "the stage hung on a refusal")
        self.assertTrue(caught, "the stage carried on as if nothing happened")
        self.assertIsInstance(caught[0], (BillingRefused, RuntimeError))
        self.assertIn("积分不足", str(caught[0]))


class StageStopTests(unittest.TestCase):
    """A refusal in the middle of a stage must end the stage in the ordinary failed state, not leave it running."""

    def test_the_stage_reports_it_as_its_failure(self):
        from app.service.drama_service import DramaService, _ClaimedStageExecutionError
        service = DramaService.__new__(DramaService)
        service._execute_stage_blocking = MagicMock(side_effect=BillingRefused("insufficient_points", "积分不足：这一步预计需要 280 积分"))
        with patch("app.service.drama_service.voice_casting.speaker_voice_map", return_value={}):
            with self.assertRaises(_ClaimedStageExecutionError) as caught:
                service._execute_claimed_stage_blocking("t1", 5, claimed_task={"task_id": "t1", "assets": {}})
        self.assertIn("积分不足", str(caught.exception.__cause__ or caught.exception))


if __name__ == "__main__":
    unittest.main()

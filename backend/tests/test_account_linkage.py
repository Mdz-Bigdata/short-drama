# -*- coding: utf-8 -*-
"""Closing an account reaches everything that depends on it, money that is owed still moves, and people are told what they should be."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy import select, update

from app.api import notification_api, user_api
from app.core import generation_queue
from app.platform import account_linkage, billing_book, payment_flow
from app.platform.billing_book import AccountGuard, BillingBook, BillingRefused, set_account_watcher
from app.platform.models import AuditEvent, MembershipTerm, PlatformUser, PointHold, UserNotification
from app.platform.store import ACCOUNT_DELETED
from tests.test_refund_flow import FinanceCase


class Case(FinanceCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.app.include_router(user_api.router)
        self.app.include_router(notification_api.router)
        patcher = patch.object(account_linkage, "get_payment_channels", lambda: self.channels)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.stopped = []
        # The routes stop nothing real: there are no projects here, only a record that they were asked to.
        real = self.real_finish_closing = account_linkage.finish_closing
        async def finish(store, user_id, **kwargs):
            return await real(store, user_id, stop_projects=lambda who: self.stopped.append(who) or 0, **kwargs)
        patcher = patch.object(user_api.account_linkage, "finish_closing", finish)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _suspend(self, name="support", user_id=None):
        self._as(name)
        return await self.client.patch(f"/api/admin/users/{user_id or self.buyer.id}", json={"status": "suspended"})

    async def _notices(self, kind=None, user_id=None):
        async with self.store.sessions() as session:
            items = (await session.scalars(select(UserNotification).where(UserNotification.user_id == (user_id or self.buyer.id)))).all()
        return [item for item in items if not kind or item.kind == kind]

    async def _audit(self, action):
        async with self.store.sessions() as session:
            return (await session.scalars(select(AuditEvent).where(AuditEvent.action == action))).all()


class SuspensionTests(Case):
    async def test_unpaid_orders_close_including_at_the_channel(self):
        self._as("customer")
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        out = await self._out(order_id, "wechat")
        self.assertEqual((await self._suspend()).status_code, 200)
        self.assertEqual((await self._order(order_id)).status, "closed")
        self.assertEqual(self.wechat.closed, [out])
        self.assertEqual((await self._attempt(out)).status, "closed")

    async def test_a_channel_outage_does_not_stop_it_and_the_sweep_finishes(self):
        self._as("customer")
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        out = await self._out(order_id, "alipay")
        self.alipay.down = True
        self.assertEqual((await self._suspend()).status_code, 200)
        self.assertEqual((await self._order(order_id)).status, "closed")
        self.assertEqual((await self._attempt(out)).status, "pending")
        self.alipay.down = False
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=20))
        self.assertEqual((await self._attempt(out)).status, "closed")

    async def test_paying_a_code_as_the_account_closes_still_counts(self):
        self._as("customer")
        order_id = await self._new_order()
        await self._pay(order_id, "alipay")
        out = await self._out(order_id, "alipay")
        self.alipay.pay(out)
        await self._suspend()
        self.assertEqual((await self._order(order_id)).status, "paid")
        await self._granted_once()

    async def test_points_held_for_calls_go_back_and_a_call_finishing_later_still_adds_up(self):
        await self._bought("alipay")
        handle = self.book.reserve(media_type="image", provider="x", model="seedream", units={"images": 1}, task_id=None, user_id=self.buyer.id)
        await self._suspend()
        self.assertEqual(await self._balance(), (Decimal(self.plan.points), Decimal(0), Decimal(0)))
        async with self.store.sessions() as session:
            hold = await session.get(PointHold, handle.hold_id)
        self.assertEqual(hold.status, "released")
        self.book.settle(handle, {"id": str(uuid.uuid4()), "status": "success", "units": {"images": 1}, "model": "seedream"})
        self.assertEqual((await self._balance())[0], Decimal(self.plan.points - 100))
        await self._nothing_unexplained()

    async def test_tokens_stop_for_good(self):
        _token, clear = await self.store.create_mcp_token(self.buyer.id, label="agent")
        self.assertIsNotNone(await self.store.verify_mcp_token(clear))
        await self._suspend()
        self.assertIsNone(await self.store.verify_mcp_token(clear))
        self._as("support")
        await self.client.patch(f"/api/admin/users/{self.buyer.id}", json={"status": "active"})
        self.assertIsNone(await self.store.verify_mcp_token(clear))
        self.assertEqual(await self.store.list_mcp_tokens(self.buyer.id), [])

    async def test_projects_are_stopped_and_it_is_all_on_record(self):
        self._as("customer")
        await self._new_order()
        await self.store.create_mcp_token(self.buyer.id, label="agent")
        await self._suspend()
        self.assertEqual(self.stopped, [self.buyer.id])
        events = [event for event in await self._audit("user.status_change") if event.details["new"] == "suspended"]
        self.assertEqual((events[0].details["orders_closed"], events[0].details["tokens_revoked"]), (1, 1))

    async def test_a_refund_under_way_is_not_affected(self):
        order_id = await self._bought("wechat")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        await self._suspend()
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=2))
        self.assertEqual((await self._order(order_id)).status, "refunded")
        await self._nothing_unexplained()

    async def test_a_refund_can_be_asked_for_and_approved_after_suspension(self):
        order_id = await self._bought("alipay")
        await self._suspend()
        refund = (await self._ask(order_id)).json()
        self.assertEqual((await self._approve(refund["id"])).json()["status"], "succeeded")

    async def test_reactivating_does_not_reopen_anything(self):
        self._as("customer")
        order_id = await self._new_order()
        await self._suspend()
        self._as("support")
        self.assertEqual((await self.client.patch(f"/api/admin/users/{self.buyer.id}", json={"status": "active"})).status_code, 200)
        self.assertEqual((await self._order(order_id)).status, "closed")

    async def test_suspending_twice_does_nothing_new(self):
        await self._suspend()
        self.assertEqual((await self._suspend()).status_code, 200)
        events = [event for event in await self._audit("user.status_change") if event.details["new"] == "suspended"]
        self.assertNotIn("orders_closed", events[-1].details)

    async def test_only_the_right_people_may(self):
        self.assertEqual((await self._suspend(name="customer")).status_code, 403)
        self.assertEqual((await self._suspend(name="auditor")).status_code, 403)
        # Support can act on customers, not on other staff.
        self.assertEqual((await self._suspend(name="support", user_id=self.staff["approver"]["user_id"])).status_code, 200)


class ProviderGuardTests(Case):
    def _guard(self):
        book = BillingBook(self.book.engine.url.render_as_string(hide_password=False), lambda task: self.buyer.id if task == "t1" else None)
        self.addCleanup(book.close)
        return book

    async def test_with_charging_off_a_closed_account_cannot_reach_a_provider(self):
        book = self._guard()
        guard = AccountGuard(book)
        usage = dict(media_type="video", provider="minimax", model="h3", units={"seconds": 5})
        self.assertIsNone(guard.reserve(**usage, task_id="t1", user_id=None))
        await self._suspend()
        book.forget_account(self.buyer.id)
        with self.assertRaises(BillingRefused) as caught:
            guard.reserve(**usage, task_id="t1", user_id=None)
        self.assertEqual(caught.exception.code, "account_closed")

    async def test_someone_elses_project_counts_by_its_owner_and_free_providers_pass(self):
        book = self._guard()
        guard = AccountGuard(book)
        await self._suspend()
        book.forget_account(self.buyer.id)
        with self.assertRaises(BillingRefused):
            guard.reserve(media_type="video", provider="minimax", model="h3", units={}, task_id="t1", user_id=self.staff["boss"]["user_id"])
        self.assertIsNone(guard.reserve(media_type="audio", provider="local", model="m", units={}, task_id="t1", user_id=None))

    async def test_no_known_payer_and_no_record_of_them_both_pass_with_charging_off(self):
        guard = AccountGuard(self._guard())
        self.assertIsNone(guard.reserve(media_type="video", provider="x", model="y", units={}, task_id=None, user_id=None))
        self.assertIsNone(guard.reserve(media_type="video", provider="x", model="y", units={}, task_id=None, user_id="old-owner-id"))

    async def test_the_status_change_takes_effect_at_once_in_this_process(self):
        book = self._guard()
        set_account_watcher(book)
        self.addCleanup(set_account_watcher, None)
        book.require_open_account(self.buyer.id)  # now cached as open
        await self._suspend()
        with self.assertRaises(BillingRefused):
            book.require_open_account(self.buyer.id)
        self._as("support")
        await self.client.patch(f"/api/admin/users/{self.buyer.id}", json={"status": "active"})
        book.require_open_account(self.buyer.id)

    async def test_a_database_failure_does_not_stop_generation(self):
        book = self._guard()
        with patch.object(billing_book, "Session", side_effect=billing_book.SQLAlchemyError("down")), self.assertLogs("app.platform.billing_book", "WARNING"):
            book.require_open_account(self.buyer.id)

    async def test_charging_refuses_a_closed_account_too(self):
        await self._bought("alipay")
        await self._suspend()
        self.book.forget_account(self.buyer.id)
        with self.assertRaises(BillingRefused) as caught:
            self._spend(1)
        self.assertEqual(caught.exception.code, "account_closed")


class StoppingProjectsTests(Case):
    def _service(self, tasks):
        service = MagicMock()
        service.repo.list_all_tasks.return_value = tasks
        return service

    async def test_only_their_running_projects_stop_and_queues_empty(self):
        queued = {"items": [{"status": "queued"}]}
        with patch.object(generation_queue, "snapshot_of", side_effect=lambda task: task.get("q")):
            service = self._service([
                {"task_id": "a", "owner_user_id": "u", "status": "running", "q": queued},
                {"task_id": "b", "owner_user_id": "u", "status": "completed"},
                {"task_id": "c", "owner_user_id": "other", "status": "running"},
                {"task_id": "d", "owner_user_id": "u", "status": "paused", "workflow_control": {"active": True}},
            ])
            self.assertEqual(account_linkage.stop_projects_of("u", service), 2)
        service.cancel_generation_item.assert_called_once_with("a", None)
        self.assertEqual([call.args[0] for call in service.pause_task.call_args_list], ["a", "d"])
        for call in service.pause_task.call_args_list:
            self.assertTrue(call.kwargs["stop"])

    async def test_a_failure_stopping_projects_is_recorded_and_does_not_undo_the_closing(self):
        def broken(_user):
            raise RuntimeError("boom")
        with self.assertLogs("app.platform.account_linkage", "ERROR"):
            await self.real_finish_closing(self.store, self.buyer.id, channels=self.channels, stop_projects=broken)
        self.assertEqual(len(await self._audit("user.close_incomplete")), 1)


class DeletionTests(Case):
    async def _delete(self, user_id=None, name="support"):
        self._as(name)
        return await self.client.delete(f"/api/admin/users/{user_id or self.buyer.id}")

    async def test_who_they_were_goes_and_what_happened_stays(self):
        order_id = await self._bought("alipay")
        self._spend(1)
        async with self.store.sessions() as session:
            before = await session.get(PlatformUser, self.buyer.id)
            email = before.email
        response = await self._delete()
        self.assertEqual(response.status_code, 200, response.text)
        async with self.store.sessions() as session:
            user = await session.get(PlatformUser, self.buyer.id)
        self.assertEqual((user.status, user.email, user.phone, user.display_name, user.roles), (ACCOUNT_DELETED, None, None, None, []))
        self.assertTrue(user.username.startswith("deleted-"))
        self.assertIsNone(await self.store.verify_login(email, "buyer-password"))
        self.assertEqual((await self._order(order_id)).status, "paid")
        self.assertEqual(len(await self._credits()) >= 1, True)
        self.assertEqual(await self._notices(), [])
        self.assertEqual(self.stopped, [self.buyer.id])
        event = (await self._audit("user.delete"))[0]
        self.assertNotIn(email, str(event.details))
        await self._nothing_unexplained()

    async def test_the_email_can_be_used_again(self):
        async with self.store.sessions() as session:
            email = (await session.get(PlatformUser, self.buyer.id)).email
        await self._delete()
        fresh, _ = await self.store.create_user(email=email, phone=None, password="fresh-password")
        self.assertNotEqual(fresh.id, self.buyer.id)

    async def test_it_cannot_be_undone_or_repeated(self):
        await self._delete()
        self._as("support")
        response = await self.client.patch(f"/api/admin/users/{self.buyer.id}", json={"status": "active"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual((await self._delete()).status_code, 422)

    async def test_money_still_owed_goes_back_after_deletion(self):
        order_id = await self._bought("wechat")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        await self._delete()
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=2))
        self.assertEqual((await self._order(order_id)).status, "refunded")
        await self._nothing_unexplained()

    async def test_limits_on_who_and_whom(self):
        self.assertEqual((await self._delete(name="auditor")).status_code, 403)
        self.assertEqual((await self._delete(name="customer")).status_code, 403)
        self.assertEqual((await self._delete(str(uuid.uuid4()))).status_code, 404)
        self.assertEqual((await self._delete(self.staff["boss"]["user_id"], name="boss")).status_code, 422)

    async def test_support_cannot_remove_staff_and_the_last_super_admin_stays(self):
        boss_id = self.staff["boss"]["user_id"]
        await self.store.set_user_roles(boss_id, boss_id, ["super_admin"])
        approver = self.staff["approver"]["user_id"]
        await self.store.set_user_roles(boss_id, approver, ["finance"])
        self.assertEqual((await self._delete(approver, name="support")).status_code, 403)
        with self.assertRaises(ValueError):
            await self.store.delete_account(actor_id=approver, user_id=boss_id)


class NotificationTests(Case):
    async def _inbox(self, name="customer"):
        self._as(name)
        return (await self.client.get("/api/notifications")).json()

    async def test_paying_tells_the_customer_once(self):
        order_id = await self._bought("alipay")
        out = await self._attempt_out(order_id)
        for _ in range(2):
            self._acked("alipay", await self._notify("alipay", out))
        inbox = await self._inbox()
        self.assertEqual(inbox["unread"], 1)
        self.assertEqual(inbox["items"][0]["kind"], "order_paid")
        self.assertEqual(inbox["items"][0]["data"]["points"], self.plan.points)
        self.assertEqual(inbox["to_do"], {})

    async def _attempt_out(self, order_id):
        return await self._out(order_id, "alipay")

    async def test_a_refund_tells_the_customer_only_when_the_money_has_gone(self):
        order_id = await self._bought("wechat")
        refund = (await self._ask(order_id)).json()
        await self._approve(refund["id"])
        self.assertEqual(await self._notices("refund_succeeded"), [])
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=2))
        notices = await self._notices("refund_succeeded")
        self.assertEqual(notices[0].data["amount_minor"], refund["amount_minor"])

    async def test_a_failed_or_rejected_refund_says_nothing_to_the_customer(self):
        order_id = await self._bought("alipay")
        refund = (await self._ask(order_id)).json()
        await self._reject(refund["id"])
        self.assertEqual(await self._notices("refund_succeeded"), [])

    async def test_an_automatic_refund_of_a_second_payment_is_its_own_notice(self):
        order_id = await self._new_order_for_double()
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=2))
        await payment_flow.sweep(self.store, self.channels, datetime.now(timezone.utc) + timedelta(minutes=4))
        notices = await self._notices("duplicate_refunded")
        self.assertEqual(notices[0].data["order_id"], order_id)

    async def _new_order_for_double(self):
        self._as("customer")
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        first = await self._out(order_id, "wechat")
        with patch.object(self.channels["wechat"], "close", side_effect=payment_flow.ChannelError("down")):
            await self._pay(order_id, "alipay")
        second = await self._out(order_id, "alipay")
        self.wechat.pay(first)
        self.alipay.pay(second)
        await self._notify("wechat", first)
        await self._notify("alipay", second)
        return order_id

    async def test_reading_only_touches_your_own(self):
        await self._bought("alipay")
        notice = (await self._notices())[0]
        self._as("auditor")
        self.assertEqual((await self.client.post(f"/api/notifications/{notice.id}/read")).json(), {"marked": 0})
        self.assertEqual((await self._inbox())["unread"], 1)
        self._as("customer")
        self.assertEqual((await self.client.post(f"/api/notifications/{notice.id}/read")).json(), {"marked": 1})
        self.assertEqual((await self._inbox())["unread"], 0)
        await self._bought("alipay")
        self._as("customer")
        self.assertEqual((await self.client.post("/api/notifications/read-all")).json(), {"marked": 1})

    async def test_operators_see_only_what_they_could_act_on(self):
        order_id = await self._bought("alipay")
        await self._ask(order_id)
        self.assertEqual((await self._inbox("customer"))["to_do"], {})
        self.assertEqual((await self._inbox("support"))["to_do"], {})
        self.assertEqual((await self._inbox("asker"))["to_do"]["refunds_to_decide"], 0)  # asked for it themself
        self.assertEqual((await self._inbox("approver"))["to_do"]["refunds_to_decide"], 1)
        self.assertEqual((await self._inbox("auditor"))["to_do"], {"critical_differences": 0, "payment_alerts": 0})

    async def test_money_problems_show_up_as_things_to_look_at(self):
        self._as("customer")
        order_id = await self._new_order()
        await self._pay(order_id, "wechat")
        out = await self._out(order_id, "wechat")
        self.wechat.pay(out)
        await self._notify("wechat", out, amount={"total": 1, "currency": "CNY"})
        self.assertEqual((await self._inbox("approver"))["to_do"]["payment_alerts"], 1)


class MembershipReminderTests(Case):
    async def _term_ending_in(self, delta):
        order_id = await self._bought("alipay")
        async with self.store.sessions() as session:
            await session.execute(
                update(MembershipTerm).where(MembershipTerm.order_id == order_id)
                .values(starts_at=datetime.now(timezone.utc) - timedelta(days=20), expires_at=datetime.now(timezone.utc) + delta)
            )
            await session.commit()
        return order_id

    async def test_seven_days_then_one_day_each_once(self):
        await self._term_ending_in(timedelta(days=6))
        self.assertEqual(await self.store.send_membership_reminders(), 1)
        self.assertEqual(await self.store.send_membership_reminders(), 0)
        notices = await self._notices("membership_expiring")
        self.assertEqual(notices[0].data["days"], 7)
        self.assertEqual(notices[0].data["plan_name"], self.plan.name)
        now = datetime.now(timezone.utc) + timedelta(days=5, hours=12)
        self.assertEqual(await self.store.send_membership_reminders(now=now), 1)
        self.assertEqual(await self.store.send_membership_reminders(now=now), 0)
        self.assertEqual(sorted(item.data["days"] for item in await self._notices("membership_expiring")), [1, 7])

    async def test_far_off_says_nothing(self):
        await self._term_ending_in(timedelta(days=20))
        self.assertEqual(await self.store.send_membership_reminders(), 0)

    async def test_already_renewed_says_nothing(self):
        first = await self._term_ending_in(timedelta(days=3))
        second = await self._bought("alipay")
        self.assertNotEqual(first, second)
        async with self.store.sessions() as session:
            await session.execute(
                update(MembershipTerm).where(MembershipTerm.order_id == second)
                .values(starts_at=datetime.now(timezone.utc) + timedelta(days=3), expires_at=datetime.now(timezone.utc) + timedelta(days=33))
            )
            await session.commit()
        self.assertEqual(await self.store.send_membership_reminders(), 0)

    async def test_ended_is_said_once_and_not_for_ever(self):
        await self._term_ending_in(timedelta(days=-1))
        self.assertEqual(await self.store.send_membership_reminders(), 1)
        self.assertEqual(await self.store.send_membership_reminders(), 0)
        self.assertEqual(len(await self._notices("membership_expired")), 1)

    async def test_long_ended_refunded_or_closed_accounts_hear_nothing(self):
        await self._term_ending_in(timedelta(days=-30))
        self.assertEqual(await self.store.send_membership_reminders(), 0)
        order_id = await self._term_ending_in(timedelta(days=2))
        async with self.store.sessions() as session:
            await session.execute(update(MembershipTerm).where(MembershipTerm.order_id == order_id).values(status="refunded"))
            await session.commit()
        self.assertEqual(await self.store.send_membership_reminders(), 0)
        await self._term_ending_in(timedelta(days=2))
        await self._suspend()
        self.assertEqual(await self.store.send_membership_reminders(), 0)

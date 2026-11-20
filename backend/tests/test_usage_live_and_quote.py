# -*- coding: utf-8 -*-
"""Live usage figures, the cost they come to, and the outward quote at the official price plus 20%."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.auth_api import _public_user, get_current_user
from app.core import quote
from app.core.providers import pricing
from app.core.providers.pricing import PricingTable
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.platform.usage_billing import charge_from
from app.platform.usage_stats import bucket_size, usage_stats
from tests.test_usage_billing import entry

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
TABLE = PricingTable.from_mapping({
    "deepseek-flash": {"kind": "per_million_tokens", "currency": "CNY", "input": 2, "output": 8},
    "seedance-2-5": {"kind": "per_second", "currency": "CNY", "price": 1.51, "by_resolution": {"480p": 0.67, "1080p": 3.74}},
    "music_v2": {"kind": "per_second", "currency": "USD", "price": 0.0025},
})


def charge(minutes_ago, *, model="deepseek-flash", media="text", user="u1", status="success", cost="0.5", currency="CNY", units=None, task="t1"):
    return SimpleNamespace(
        occurred_at=NOW - timedelta(minutes=minutes_ago), media_type=media, provider="p", model=model, purpose="stage", status=status,
        user_id=user, task_id=task, units=units if units is not None else {"input_tokens": 1000, "output_tokens": 200},
        reference_cost=Decimal(cost) if cost is not None else None, reference_currency=currency,
    )


class QuoteTests(unittest.TestCase):
    def test_every_priced_model_is_quoted_at_its_official_price_plus_a_fifth(self):
        rows = {row["model"]: row for row in quote.price_list(TABLE)}
        self.assertEqual(rows["deepseek-flash"]["official"], {"input": 2.0, "output": 8.0})
        self.assertEqual(rows["deepseek-flash"]["quote"], {"input": 2.4, "output": 9.6})
        self.assertEqual(rows["seedance-2-5"]["quote"], {"price": 1.812, "by_resolution": {"480p": 0.804, "1080p": 4.488}})
        # A model priced in dollars is listed in yuan like the rest, at the project's one rate (7.2).
        self.assertEqual(rows["music_v2"]["official"], {"price": 0.018})
        self.assertEqual(rows["music_v2"]["quote"], {"price": 0.0216})
        self.assertEqual((rows["music_v2"]["currency"], rows["music_v2"]["priced_in"]), ("CNY", "USD"))
        self.assertEqual({row["currency"] for row in rows.values()}, {"CNY"})
        # Outward: the quote alone, never the official price beside it, nor what currency it came in.
        outward = quote.price_list(TABLE, with_official=False)
        self.assertTrue(all("official" not in row and "priced_in" not in row and row["currency"] == "CNY" for row in outward))

    def test_dollars_become_yuan_and_a_currency_with_no_rate_keeps_its_name(self):
        self.assertEqual(quote.in_cny("0.03", "USD"), (Decimal("0.216"), "CNY"))
        self.assertEqual(quote.in_cny(5, "cny"), (Decimal("5"), "CNY"))
        self.assertEqual(quote.in_cny(5, "EUR"), (Decimal("5"), "EUR"))
        self.assertEqual(quote.quote_for("music_v2", {"seconds": 60}, TABLE), (Decimal("1.296000"), "CNY"))
        # A rate that is missing or not a positive number converts nothing: better a dollar figure than a wrong yuan one.
        for broken in (0, -1, "abc", None):
            with patch("app.core.quote.prompt_data.value", return_value=broken):
                self.assertEqual(quote.in_cny(1, "USD"), (Decimal("1"), "USD"), broken)

    def test_one_call_is_quoted_from_its_units_and_an_unpriced_model_is_not_guessed(self):
        self.assertEqual(quote.quote_for("deepseek-flash", {"input_tokens": 1_000_000, "output_tokens": 500_000}, TABLE), (Decimal("7.200000"), "CNY"))
        self.assertIsNone(quote.quote_for("some-new-model", {"input_tokens": 10}, TABLE))
        # An empty table is a table: nothing is priced, and the deployment's own prices do not leak in.
        self.assertEqual(quote.price_list(PricingTable()), [])
        self.assertEqual(quote.quoted("10"), Decimal("12.000000"))

    def test_the_markup_can_be_set_and_a_slip_of_the_hand_falls_back_to_a_fifth(self):
        with patch.dict(os.environ, {"QUOTE_MARKUP": "0.35"}):
            self.assertEqual(quote.quoted(100), Decimal("135.000000"))
        for wrong in ("abc", "-0.5", "50", " "):
            with patch.dict(os.environ, {"QUOTE_MARKUP": wrong}):
                self.assertEqual(quote.markup(), Decimal("0.20"), wrong)


class UsageStatsTests(unittest.TestCase):
    def test_totals_count_tokens_cost_and_the_quote_and_keep_currencies_apart(self):
        stats = usage_stats([
            charge(1), charge(2, units={"input_tokens": 3000, "output_tokens": 1000, "reasoning_tokens": 400, "cached_tokens": 2000}, cost="1.5"),
            charge(3, model="music_v2", media="audio", cost="0.03", currency="USD", units={"seconds": 12}),
            charge(4, status="failed", cost=None, currency=None),
            charge(5, model="doubao-seedream-5-5", media="image", cost=None, currency=None, units={"images": 1}),
            charge(90),  # outside the hour
        ], now=NOW, window=timedelta(hours=1))
        total = stats["total"]
        self.assertEqual((total["calls"], total["failed"], total["unpriced_calls"]), (5, 1, 1))
        self.assertEqual((total["input_tokens"], total["output_tokens"], total["reasoning_tokens"], total["cached_tokens"]), (4000, 1200, 400, 2000))
        self.assertEqual(total["tokens"], 5200)
        # The dollar call is counted in yuan with the rest: 2.00 + 0.03 × 7.2.
        self.assertEqual(total["cost"], {"CNY": 2.216})
        self.assertEqual(total["quote"], {"CNY": 2.6592})
        self.assertEqual((stats["markup"], stats["usd_cny"], stats["converted_from_usd"]), (0.2, 7.2, True))
        self.assertEqual(stats["unpriced_models"], [{"model": "doubao-seedream-5-5", "calls": 1}])

    def test_the_same_figures_by_model_and_by_user_biggest_spend_first(self):
        stats = usage_stats([
            charge(1, user="u1", cost="0.2"), charge(2, user="u2", cost="3"), charge(3, user="u2", model="seedance-2-5", media="video", cost="7.55", units={"seconds": 5}),
            charge(4, user=None, cost="0.1"),
        ], now=NOW, window=timedelta(hours=1))
        self.assertEqual([row["model"] for row in stats["by_model"]], ["seedance-2-5", "deepseek-flash"])
        self.assertEqual(stats["by_model"][0]["quote"], {"CNY": 9.06})
        self.assertEqual(stats["by_model"][0]["seconds"], 5.0)
        self.assertEqual([(row["user_id"], row["calls"]) for row in stats["by_user"]], [("u2", 2), ("u1", 1), ("", 1)])
        self.assertEqual(stats["by_user"][0]["cost"], {"CNY": 10.55})

    def test_each_project_is_one_job_to_quote(self):
        stats = usage_stats([
            charge(1, task="drama-a", cost="4"), charge(2, task="drama-a", cost="6"), charge(3, task="drama-b", cost="1"), charge(4, task=None, cost="9"),
        ], now=NOW, window=timedelta(hours=1))
        self.assertEqual([(row["task_id"], row["calls"], row["cost"], row["quote"]) for row in stats["by_task"]], [
            ("drama-a", 2, {"CNY": 10.0}, {"CNY": 12.0}), ("drama-b", 1, {"CNY": 1.0}, {"CNY": 1.2}),
        ])

    def test_the_series_covers_the_window_in_even_steps_and_adds_up_to_the_total(self):
        stats = usage_stats([charge(0.5), charge(10), charge(59.5)], now=NOW, window=timedelta(hours=1))
        self.assertEqual((len(stats["series"]), stats["bucket_seconds"]), (60, 60))
        self.assertEqual(sum(point["calls"] for point in stats["series"]), stats["total"]["calls"])
        self.assertEqual(stats["series"][-1]["calls"], 1)
        self.assertEqual(stats["series"][0]["calls"], 1)
        self.assertEqual(bucket_size(timedelta(hours=2)), timedelta(minutes=5))
        self.assertEqual(bucket_size(timedelta(days=1)), timedelta(hours=1))
        self.assertEqual(bucket_size(timedelta(days=30)), timedelta(days=1))

    def test_the_newest_calls_come_first_each_with_its_cost_and_quote(self):
        stats = usage_stats([charge(9, cost="1"), charge(1, cost="2"), charge(5, status="failed", cost=None, currency=None)], now=NOW, window=timedelta(hours=1))
        self.assertEqual([row["cost"] for row in stats["recent"]], [2.0, None, 1.0])
        self.assertEqual([row["quote"] for row in stats["recent"]], [2.4, None, 1.2])
        self.assertEqual(stats["recent"][0]["input_tokens"], 1000)

    def test_a_dollar_call_is_listed_in_yuan_and_another_currency_is_kept_apart(self):
        stats = usage_stats([
            charge(1, model="music_v2", media="audio", cost="0.15", currency="USD", units={"seconds": 60}),
            charge(2, model="some-eu-model", cost="3", currency="EUR"),
        ], now=NOW, window=timedelta(hours=1))
        self.assertEqual(stats["total"]["cost"], {"CNY": 1.08, "EUR": 3.0})
        self.assertEqual(stats["total"]["quote"], {"CNY": 1.296, "EUR": 3.6})
        self.assertEqual([(row["cost"], row["quote"], row["currency"]) for row in stats["recent"]], [(1.08, 1.296, "CNY"), (3.0, 3.6, "EUR")])
        self.assertFalse(usage_stats([charge(1)], now=NOW, window=timedelta(hours=1))["converted_from_usd"])

    def test_a_failed_call_is_counted_as_a_call_and_nothing_more(self):
        stats = usage_stats([charge(1, model="seedance-2-5", media="video", status="failed", cost=None, currency=None, units={"seconds": 15})], now=NOW, window=timedelta(hours=1))
        self.assertEqual((stats["total"]["calls"], stats["total"]["failed"], stats["total"]["seconds"], stats["total"]["unpriced_calls"]), (1, 1, 0.0, 0))
        self.assertEqual(stats["unpriced_models"], [])

    def test_an_empty_window_is_all_zeroes_not_an_error(self):
        stats = usage_stats([], now=NOW, window=timedelta(minutes=5))
        self.assertEqual(stats["total"]["calls"], 0)
        self.assertEqual(stats["total"]["cost"], {})
        self.assertEqual(len(stats["series"]), 5)
        self.assertEqual((stats["by_model"], stats["by_user"], stats["by_task"], stats["recent"]), ([], [], [], []))


class ApiTests(unittest.IsolatedAsyncioTestCase):
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
        self.boss, _ = await self.store.create_user(email="boss@example.com", phone=None, password="boss-password", role="admin")
        self.customer, _ = await self.store.create_user(email="customer@example.com", phone=None, password="customer-password")

    async def _login(self, user):
        fresh = await self.store.get_user(user.id)
        self.app.dependency_overrides[get_current_user] = lambda: _public_user(fresh)

    async def test_the_live_figures_are_for_finance_only_and_name_the_account(self):
        now = datetime.now(timezone.utc).isoformat()
        await self.store.save_usage_charges([charge_from(entry(id="a", at=now), [], self.customer.id)])
        await self._login(self.customer)
        self.assertEqual(self.client.get("/api/admin/finance/usage/live").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/pricing/quote").status_code, 403)
        await self._login(self.boss)
        body = self.client.get("/api/admin/finance/usage/live?minutes=30").json()
        self.assertEqual(body["total"]["calls"], 1)
        self.assertEqual(body["window_minutes"], 30)
        self.assertEqual(body["by_user"][0]["user_id"], self.customer.id)
        self.assertTrue(body["by_user"][0]["user_name"])
        self.assertEqual(body["recent"][0]["user_name"], body["by_user"][0]["user_name"])
        self.assertEqual([(row["task_id"], row["title"]) for row in body["by_task"]], [("t1", "")])

    async def test_a_project_goes_by_its_own_title(self):
        from app.api import usage_admin_api
        await self.store.save_usage_charges([charge_from(entry(id="b", at=datetime.now(timezone.utc).isoformat(), task_id="drama-9"), [], self.customer.id)])
        await self._login(self.boss)
        with patch.object(usage_admin_api._tasks, "get_task", lambda task_id: {"config": {"title_suggestion": "雪夜归人"}} if task_id == "drama-9" else None):
            body = self.client.get("/api/admin/finance/usage/live").json()
        self.assertEqual([(row["task_id"], row["title"], bool(row["user_name"])) for row in body["by_task"]], [("drama-9", "雪夜归人", True)])
        self.assertEqual(self.client.get("/api/admin/finance/usage/live?minutes=1").status_code, 422)

    async def test_the_inside_list_shows_official_beside_quote_and_the_outward_one_only_the_quote(self):
        # The list is of the installed prices: this test's own, not whatever price file this machine has (or lacks).
        pricing.set_pricing_table(TABLE)
        self.addCleanup(pricing.set_pricing_table, None)
        await self._login(self.boss)
        inside = self.client.get("/api/admin/pricing/quote").json()
        self.assertEqual((inside["markup"], inside["usd_cny"]), (0.2, 7.2))
        self.assertEqual({row["currency"] for row in inside["items"]}, {"CNY"})
        self.assertTrue(inside["items"])
        for row in inside["items"]:
            for key, official in row["official"].items():
                if isinstance(official, (int, float)):
                    self.assertAlmostEqual(row["quote"][key], official * 1.2, places=5, msg=row["model"])
        await self._login(self.customer)
        outward = self.client.get("/api/billing/price-list").json()
        self.assertEqual(len(outward["items"]), len(inside["items"]))
        self.assertTrue(all("official" not in row and "priced_in" not in row and "quote" in row for row in outward["items"]))
        self.assertEqual({row["currency"] for row in outward["items"]}, {"CNY"})


if __name__ == "__main__":
    unittest.main()

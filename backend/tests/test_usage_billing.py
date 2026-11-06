# -*- coding: utf-8 -*-
"""Every provider call recorded in points, by whoever it belongs to, and nothing taken from anyone's balance."""

import asyncio
import contextvars
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.auth_api import _public_user, get_current_user
from app.core import usage_ledger
from app.core.providers.elevenlabs import DialogueLine, ElevenLabsClient
from app.core.providers.minimax_audio import MiniMaxAudioClient
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.platform.usage_billing import (
    CUSTOMER,
    OPERATOR_ABSORBED,
    UNATTRIBUTED,
    UsageSpool,
    charge_from,
    drain,
    find_rate,
    points_for,
    read_records,
    usage_differences,
)
from app.schema.minimax_audio import MiniMaxTTSRequest

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def rate(**fields):
    defaults = {
        "id": "r1", "model": "m", "resolution": "", "kind": "per_second", "input": 0, "cached_input": 0, "output": 0,
        "price": 0, "effective_from": NOW - timedelta(days=30),
    }
    return SimpleNamespace(**{**defaults, **fields})


def entry(**fields):
    return {
        "id": "u1", "at": NOW.isoformat(), "media_type": "video", "provider": "minimax", "model": "m", "status": "success",
        "purpose": "stage_5", "units": {"seconds": 9}, "cost": 1.5, "currency": "CNY", "task_id": "t1", "user_id": "owner",
        **fields,
    }


class PointsTest(unittest.TestCase):
    def test_tokens_with_a_cheaper_cached_part(self):
        tokens = rate(kind="per_million_tokens", input=100, cached_input=10, output=300)
        self.assertEqual(points_for(tokens, {"input_tokens": 1000, "cached_tokens": 800, "output_tokens": 100}), Decimal("0.0580"))

    def test_more_cached_than_read_is_not_a_discount(self):
        tokens = rate(kind="per_million_tokens", input=100, cached_input=10)
        self.assertEqual(points_for(tokens, {"input_tokens": 1000, "cached_tokens": 5000}), Decimal("0.0100"))

    def test_the_other_kinds(self):
        self.assertEqual(points_for(rate(kind="per_image", price=2), {"images": 3}), Decimal("6.0000"))
        self.assertEqual(points_for(rate(kind="per_image", price=2), {}), Decimal("2.0000"))
        self.assertEqual(points_for(rate(kind="per_second", price=5), {"seconds": 9}), Decimal("45.0000"))
        self.assertEqual(points_for(rate(kind="per_thousand_characters", price=3), {"characters": 500}), Decimal("1.5000"))
        self.assertEqual(points_for(rate(kind="per_call", price=7), {}), Decimal("7.0000"))

    def test_nonsense_units_come_to_nothing(self):
        self.assertEqual(points_for(rate(kind="per_second", price=5), {"seconds": "lots"}), Decimal("0.0000"))
        self.assertEqual(points_for(rate(kind="per_second", price=5), {"seconds": True}), Decimal("0.0000"))


class RateLookupTest(unittest.TestCase):
    def test_the_rate_in_force_at_the_time_is_used(self):
        old, new = rate(id="old", price=1, effective_from=NOW - timedelta(days=5)), rate(id="new", price=2, effective_from=NOW + timedelta(days=5))
        self.assertEqual(find_rate([old, new], "m", None, NOW).id, "old")
        self.assertEqual(find_rate([old, new], "m", None, NOW + timedelta(days=6)).id, "new")
        self.assertIsNone(find_rate([new], "m", None, NOW))

    def test_a_full_model_name_finds_its_family(self):
        family, pro = rate(id="family", model="seedance-2-5"), rate(id="pro", model="seedance-2-5-pro")
        self.assertEqual(find_rate([family, pro], "doubao-seedance-2-5-pro-250428", None, NOW).id, "pro")
        self.assertEqual(find_rate([family], "doubao-seedance-2-5-pro-250428", None, NOW).id, "family")
        self.assertIsNone(find_rate([family], "kling-3", None, NOW))

    def test_a_resolution_entry_beats_the_general_one(self):
        general, tall = rate(id="general"), rate(id="2k", resolution="2k")
        self.assertEqual(find_rate([general, tall], "m", "2K", NOW).id, "2k")
        self.assertEqual(find_rate([general, tall], "m", "768p", NOW).id, "general")


class AttributionTest(unittest.TestCase):
    def setUp(self):
        self.rates = [rate(price=5)]

    def test_the_owner_pays_for_their_own_project(self):
        row = charge_from(entry(), self.rates, "owner")
        self.assertEqual((row["user_id"], row["operator_id"], row["billing_mode"], row["points"]), ("owner", None, CUSTOMER, Decimal("45.0000")))

    def test_staff_working_on_a_project_is_not_the_customers_bill(self):
        row = charge_from(entry(user_id="staff"), self.rates, "owner")
        self.assertEqual((row["user_id"], row["operator_id"], row["billing_mode"]), ("owner", "staff", OPERATOR_ABSORBED))

    def test_a_scheduled_run_with_nobody_asking_is_the_owners(self):
        row = charge_from(entry(user_id=None), self.rates, "owner")
        self.assertEqual((row["user_id"], row["billing_mode"]), ("owner", CUSTOMER))

    def test_with_no_project_the_person_asking_pays(self):
        row = charge_from(entry(task_id=None, user_id="me"), self.rates, None)
        self.assertEqual((row["user_id"], row["task_id"], row["billing_mode"]), ("me", None, CUSTOMER))

    def test_nobody_at_all_is_called_out(self):
        row = charge_from(entry(task_id=None, user_id=None), self.rates, None)
        self.assertEqual((row["user_id"], row["billing_mode"]), (None, UNATTRIBUTED))

    def test_failed_calls_come_to_nothing(self):
        row = charge_from(entry(status="failed"), self.rates, "owner")
        self.assertEqual((row["points"], row["rate_id"], row["rate_missing"]), (Decimal(0), None, False))

    def test_reused_answers_and_local_speech_are_free_and_need_no_rate(self):
        for provider in ("memo", "local"):
            row = charge_from(entry(provider=provider), [], "owner")
            self.assertEqual((row["points"], row["rate_missing"]), (Decimal(0), False), provider)

    def test_the_model_actually_called_is_what_is_priced(self):
        row = charge_from(entry(model="deepseek-flash", units={"api_model": "m", "seconds": 1}), self.rates, "owner")
        self.assertEqual((row["model"], row["points"]), ("m", Decimal("5.0000")))

    def test_a_paid_call_with_no_rate_is_marked(self):
        row = charge_from(entry(model="unknown"), self.rates, "owner")
        self.assertEqual((row["points"], row["rate_missing"]), (Decimal(0), True))


class LedgerHookTest(unittest.TestCase):
    def setUp(self):
        self.kept = []
        usage_ledger.configure_billing_sink(self.kept.append)
        self.addCleanup(usage_ledger.configure_billing_sink, None)

    def _in_own_context(self, work):
        contextvars.copy_context().run(work)

    def test_each_call_reaches_billing_with_its_project_and_person(self):
        def work():
            usage_ledger.bind_user("me")
            with usage_ledger.bind_task("t1", "stage_5"):
                usage_ledger.record("video", provider="p", model="m", status="success", units={"seconds": 3})
        self._in_own_context(work)
        self.assertEqual((self.kept[0]["task_id"], self.kept[0]["user_id"]), ("t1", "me"))

    def test_a_call_outside_any_project_reaches_billing_too(self):
        self._in_own_context(lambda: usage_ledger.record("image", provider="p", model="m", status="success"))
        self.assertIsNone(self.kept[0]["task_id"])

    def test_a_billing_failure_never_fails_the_call(self):
        usage_ledger.configure_billing_sink(MagicMock(side_effect=OSError("disk full")))
        with self.assertLogs("app.core.usage_ledger", level="ERROR"):
            row = usage_ledger.record("image", provider="p", model="m", status="success")
        self.assertEqual(row["status"], "success")

    def test_a_thread_with_the_context_carried_keeps_the_project(self):
        def work():
            usage_ledger.bind_user("me")
            with usage_ledger.bind_task("t1"):
                thread = threading.Thread(target=usage_ledger.carrying_context(
                    lambda: usage_ledger.record("text", provider="p", model="m", status="success")
                ))
                thread.start()
                thread.join()
        self._in_own_context(work)
        self.assertEqual((self.kept[0]["task_id"], self.kept[0]["user_id"]), ("t1", "me"))


class PaidAudioTest(unittest.TestCase):
    """Dubbing, music and sound effects were never recorded: the record is now made where the provider is called."""

    def setUp(self):
        self.kept = []
        usage_ledger.configure_billing_sink(self.kept.append)
        self.addCleanup(usage_ledger.configure_billing_sink, None)
        self.client = ElevenLabsClient.__new__(ElevenLabsClient)
        self.client._client = MagicMock()
        self.client._client.post.return_value = MagicMock(status_code=200, content=b"mp3", is_success=True, json=lambda: {"audio_base64": ""})
        patcher = patch.object(ElevenLabsClient, "_raise_safe")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dubbing_is_recorded_by_characters(self):
        self.client.create_dialogue([DialogueLine(voice_id="v", text="站住。"), DialogueLine(voice_id="v", text="奴才不敢站。")])
        row = self.kept[-1]
        self.assertEqual((row["media_type"], row["provider"], row["units"]["characters"], row["status"]), ("audio", "elevenlabs", 9, "success"))

    def test_music_and_effects_are_recorded_by_seconds(self):
        self.client.compose_music("rain", duration_seconds=30)
        self.client.sound_effect("rain", duration_seconds=5)
        self.assertEqual([(row["model"], row["units"]["seconds"]) for row in self.kept], [("music_v2", 30), ("eleven_sound_effects", 5)])

    def test_a_call_that_fails_is_recorded_as_failed(self):
        self.client._client.post.side_effect = RuntimeError("down")
        with self.assertRaises(RuntimeError):
            self.client.sound_effect("rain", duration_seconds=5)
        self.assertEqual(self.kept[-1]["status"], "failed")

    def test_minimax_speech_is_recorded_too(self):
        client = MiniMaxAudioClient.__new__(MiniMaxAudioClient)
        with patch.object(MiniMaxAudioClient, "_post", return_value={"data": {"audio": "00"}, "extra_info": {}}), \
             patch.object(MiniMaxAudioClient, "_artifact", return_value=MagicMock()):
            client.text_to_speech(MiniMaxTTSRequest(text="站住。", voice_id="v"))
        self.assertEqual((self.kept[-1]["provider"], self.kept[-1]["units"]["characters"]), ("minimax", 3))


class CalledModelTest(unittest.TestCase):
    def test_an_image_asked_for_with_no_model_is_recorded_under_the_one_called(self):
        from app.core.model_gateway import ModelGateway
        from app.platform.runtime_models import RuntimeModelConfiguration
        gateway = ModelGateway.__new__(ModelGateway)
        fallback = RuntimeModelConfiguration(
            configuration_id="c", category="image", provider="volcengine", base_url="https://x", api_key="k", model_ids=("seedream-5",),
        )
        kept = []
        usage_ledger.configure_billing_sink(kept.append)
        self.addCleanup(usage_ledger.configure_billing_sink, None)
        with patch("app.core.model_gateway.runtime_model_registry.resolve", return_value=None), \
             patch("app.core.model_gateway.runtime_model_registry.first_for_category", return_value=fallback), \
             patch.object(ModelGateway, "_generate_image_unmetered", return_value=("https://x/a.png", "volcengine")):
            gateway.generate_image("", "a sword")
        self.assertEqual((kept[0]["model"], kept[0]["provider"]), ("seedream-5", "volcengine"))


class SpoolTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.spool = UsageSpool(self.dir)

    def test_records_written_after_taking_go_to_a_new_file(self):
        self.spool.append({"id": "a", "at": "x"})
        first = self.spool.take()
        self.spool.append({"id": "b", "at": "x"})
        self.assertEqual([record["id"] for record in read_records(first[0])], ["a"])
        self.assertEqual(len(self.spool.take()), 2)

    def test_a_dead_processes_file_is_picked_up_and_a_live_ones_is_not(self):
        (self.dir / "999999.jsonl").write_text(json.dumps({"id": "dead", "at": "x"}) + "\n")
        (self.dir / f"{os.getppid()}.jsonl").write_text(json.dumps({"id": "alive", "at": "x"}) + "\n")
        taken = [path.name for path in self.spool.take()]
        self.assertEqual(taken, ["999999.jsonl"])

    def test_a_line_cut_short_by_a_crash_is_reported_and_the_rest_survive(self):
        path = self.dir / "999999.jsonl"
        path.write_text(json.dumps({"id": "a", "at": "x"}) + "\n" + '{"id": "b", "a')
        with self.assertLogs("app.platform.usage_billing", level="ERROR"):
            self.assertEqual([record["id"] for record in read_records(path)], ["a"])


def charge(**fields):
    defaults = {
        "usage_id": "u1", "task_id": "t1", "model": "m", "units": {"seconds": 9}, "points": Decimal("45.0000"),
        "rate_id": "r1", "rate_missing": False, "status": "success", "billing_mode": CUSTOMER, "occurred_at": NOW,
    }
    return SimpleNamespace(**{**defaults, **fields})


class DifferencesTest(unittest.TestCase):
    """R6: a charge is what its units and rate say. R7: the project's records and the charges are the same calls."""

    LATER = NOW + timedelta(hours=1)

    def _check(self, charges, records=None):
        return usage_differences(charges, [rate(price=5)], records if records is not None else {"t1": [{"id": "u1", "at": NOW.isoformat()}]}, settled_before=self.LATER)

    def test_clean(self):
        result = self._check([charge()])
        self.assertEqual((result["r6"]["differences"], result["r7"]["differences"]), (0, 0))

    def test_a_wrong_amount_shows(self):
        self.assertEqual(self._check([charge(points=Decimal("44"))])["r6"]["samples"][0]["problem"], "points")

    def test_a_charged_failure_shows(self):
        result = self._check([charge(status="failed", rate_id=None, points=Decimal("1"))])
        self.assertEqual(result["r6"]["differences"], 1)

    def test_the_wrong_rate_for_the_time_shows(self):
        rates = [rate(price=5), rate(id="r2", price=5, effective_from=NOW - timedelta(days=1))]
        result = usage_differences([charge()], rates, {"t1": [{"id": "u1", "at": NOW.isoformat()}]}, settled_before=self.LATER)
        self.assertEqual(result["r6"]["samples"][0]["problem"], "wrong_rate")

    def test_a_call_with_no_charge_shows(self):
        records = {"t1": [{"id": "u1", "at": NOW.isoformat()}, {"id": "u2", "at": (NOW + timedelta(minutes=1)).isoformat()}]}
        self.assertEqual(self._check([charge()], records)["r7"]["records_without_charge"], [{"usage_id": "u2", "task_id": "t1"}])

    def test_a_charge_missing_from_the_project_shows(self):
        records = {"t1": [{"id": "u0", "at": (NOW - timedelta(minutes=1)).isoformat()}]}
        result = self._check([charge()], records)
        self.assertEqual(result["r7"]["charges_not_on_project"], [{"usage_id": "u1", "task_id": "t1"}])

    def test_records_from_before_charges_were_kept_do_not_count(self):
        records = {"t1": [{"id": "old", "at": (NOW - timedelta(days=30)).isoformat()}, {"id": "u1", "at": NOW.isoformat()}]}
        self.assertEqual(self._check([charge()], records)["r7"]["differences"], 0)

    def test_a_record_that_fell_off_the_project_is_not_a_difference(self):
        records = {"t1": [{"id": "newer", "at": (NOW + timedelta(minutes=1)).isoformat()}]}
        result = usage_differences([charge(), charge(usage_id="newer", occurred_at=NOW + timedelta(minutes=1))], [rate(price=5)], records, settled_before=self.LATER)
        self.assertEqual(result["r7"]["differences"], 0)

    def test_what_is_still_on_its_way_is_not_a_difference(self):
        records = {"t1": [{"id": "u1", "at": NOW.isoformat()}, {"id": "u2", "at": self.LATER.isoformat()}]}
        result = usage_differences([charge()], [rate(price=5)], records, settled_before=self.LATER - timedelta(minutes=1))
        self.assertEqual(result["r7"]["differences"], 0)

    def test_missing_rates_and_nobody_to_bill_are_reported_apart(self):
        result = self._check([charge(rate_id=None, points=Decimal(0), rate_missing=True), charge(usage_id="u2", billing_mode=UNATTRIBUTED, task_id=None)])
        self.assertEqual((result["rate_missing"], result["unattributed"]), (1, 1))


class DrainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'platform.sqlite3'}")
        self.addAsyncCleanup(self.store.close)
        await self.store.create_schema()
        self.spool = UsageSpool(Path(self.temp.name) / "spool")
        self.owner = lambda task_id: "owner" if task_id == "t1" else None

    async def _wallet_is_untouched(self):
        self.assertEqual((await self.store.wallet("owner")).points, 0)

    async def test_a_call_ends_up_as_a_charge_and_no_balance_moves(self):
        await self.store.add_point_rate(actor_id="a", model="m", kind="per_second", price=Decimal(5), effective_from=NOW - timedelta(days=1))
        self.spool.append(entry())
        self.assertEqual(await drain(self.store, self.spool, self.owner), 1)
        rows = await self.store.list_usage_charges()
        self.assertEqual((rows[0].user_id, rows[0].points, rows[0].rate_missing), ("owner", Decimal("45.0000"), False))
        self.assertEqual(self.spool.backlog(), 0)
        await self._wallet_is_untouched()

    async def test_loading_the_same_record_twice_adds_nothing(self):
        self.spool.append(entry())
        await drain(self.store, self.spool, self.owner)
        self.spool.append(entry())
        self.assertEqual(await drain(self.store, self.spool, self.owner), 0)
        self.assertEqual(len(await self.store.list_usage_charges()), 1)

    async def test_when_the_database_is_down_the_file_stays_for_next_time(self):
        self.spool.append(entry())
        with patch.object(self.store, "save_usage_charges", side_effect=OSError("down")):
            with self.assertRaises(OSError):
                await drain(self.store, self.spool, self.owner)
        self.assertEqual(self.spool.backlog(), 1)
        self.assertEqual(await drain(self.store, self.spool, self.owner), 1)
        self.assertEqual(self.spool.backlog(), 0)

    async def test_the_rate_of_the_time_applies_even_if_loaded_late(self):
        await self.store.add_point_rate(actor_id="a", model="m", kind="per_second", price=Decimal(5), effective_from=NOW - timedelta(days=1))
        await self.store.add_point_rate(actor_id="a", model="m", kind="per_second", price=Decimal(99), effective_from=NOW + timedelta(days=1))
        self.spool.append(entry())
        await drain(self.store, self.spool, self.owner)
        self.assertEqual((await self.store.list_usage_charges())[0].points, Decimal("45.0000"))


class AdminApiTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_customers_cannot_see_any_of_it(self):
        await self._login(self.customer)
        for method, path in (("GET", "/api/admin/pricing/rates"), ("GET", "/api/admin/finance/usage"), ("GET", "/api/admin/recon/usage")):
            self.assertEqual(self.client.request(method, path).status_code, 403, path)
        self.assertEqual(self.client.post("/api/admin/pricing/rates", json={"model": "m", "kind": "per_call"}).status_code, 403)

    async def test_a_rate_is_added_for_now_and_audited(self):
        await self._login(self.boss)
        created = self.client.post("/api/admin/pricing/rates", json={"model": " MiniMax-H3 ", "kind": "per_second", "price": "5.5"})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["model"], "minimax-h3")
        listed = self.client.get("/api/admin/pricing/rates").json()
        self.assertEqual(len(listed["items"]), 1)
        events, _ = await self.store.list_audit_events(1, 10)
        self.assertEqual(events[0].action, "pricing.rate_add")

    async def test_a_rate_cannot_rewrite_the_past(self):
        await self._login(self.boss)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        response = self.client.post("/api/admin/pricing/rates", json={"model": "m", "kind": "per_call", "price": "1", "effective_from": past})
        self.assertEqual(response.status_code, 422)

    async def test_nonsense_rates_are_refused(self):
        await self._login(self.boss)
        self.assertEqual(self.client.post("/api/admin/pricing/rates", json={"model": "m", "kind": "per_call", "price": "-1"}).status_code, 422)
        self.assertEqual(self.client.post("/api/admin/pricing/rates", json={"model": "m", "kind": "free"}).status_code, 422)

    async def test_the_summary_shows_points_against_reference_cost(self):
        await self.store.add_point_rate(actor_id="a", model="m", kind="per_second", price=Decimal(5), effective_from=datetime.now(timezone.utc) - timedelta(days=1))
        rates = await self.store.list_point_rates()
        now = datetime.now(timezone.utc).isoformat()
        await self.store.save_usage_charges([
            charge_from(entry(id="a", at=now), rates, "owner"),
            charge_from(entry(id="b", at=now, status="failed", cost=None, currency=None), rates, "owner"),
            charge_from(entry(id="c", at=now, model="other", cost=None, currency=None), rates, "owner"),
        ])
        await self._login(self.boss)
        body = self.client.get("/api/admin/finance/usage").json()
        items = {item["model"]: item for item in body["items"]}
        self.assertEqual((items["m"]["calls"], items["m"]["failed"]), (2, 1))
        self.assertEqual(Decimal(str(items["m"]["points"])), Decimal("45"))
        self.assertEqual(Decimal(str(items["m"]["reference_cost"])), Decimal("1.5"))
        self.assertEqual(items["m"]["units"]["seconds"], 9)
        self.assertEqual(items["other"]["without_rate"], 1)
        self.assertEqual(items["other"]["unpriced_calls"], 1)

    async def test_the_reconciliation_runs_over_what_is_stored(self):
        await self._login(self.boss)
        body = self.client.get("/api/admin/recon/usage").json()
        self.assertEqual((body["checked"], body["r6"]["differences"], body["r7"]["differences"]), (0, 0, 0))


class EndToEndContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_request_binds_whoever_logged_in(self):
        from app.api import auth_api
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = PlatformStore(f"sqlite+aiosqlite:///{Path(temp.name) / 'p.sqlite3'}")
        self.addAsyncCleanup(store.close)
        await store.create_schema()
        user, _ = await store.create_user(email="me@example.com", phone=None, password="my-password1")
        kept = []
        usage_ledger.configure_billing_sink(kept.append)
        self.addCleanup(usage_ledger.configure_billing_sink, None)
        with patch.object(auth_api.auth_service, "verify_token", return_value=user.id):
            async def request():
                await auth_api.get_current_user(auth_token="token", store=store)
                await asyncio.to_thread(usage_ledger.record, "image", provider="p", model="m", status="success")
            await asyncio.create_task(request())
        self.assertEqual(kept[0]["user_id"], user.id)


if __name__ == "__main__":
    unittest.main()

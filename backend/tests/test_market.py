"""The market: sources are repositories, entries install as ordinary endpoints with a record of
their origin, fetches are bounded like any server-side request, and no central service is involved."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.auth_api import auth_service
from app.api.market_api import get_market_fetch
from app.core import market
from app.core.market import MarketError, http_fetch, parse_index, raw_proxied, resolve_source, spec_digest
from app.core.model_configuration import ModelSecretCipher
from app.core.providers.declarative_video import declared_video_endpoints
from app.platform.dependencies import get_model_secret_cipher, get_platform_store
from app.platform.runtime_models import runtime_model_registry
from app.platform.store import PlatformStore
from main import app

SPEC = {
    "label": "Acme 视频", "base_url": "https://api.acme.example", "model_ids": ["acme-v1"], "modes": ["text"],
    "submit": {"method": "POST", "path": "/v1/videos", "body": {"prompt": "{{prompt}}", "model": "{{model}}"}},
    "job_id_path": "id", "poll": {"path": "/v1/videos/{{job_id}}", "status_path": "status", "video_url_path": "url"},
}


def _definition(slug="acme-video", version="1.0.0", name="Acme 视频端点", spec=None):
    return {"meta": {"slug": slug, "name": name, "version": version, "kind": "video_endpoint", "author": "acme"}, "spec": spec or {**SPEC, "family": "acme_video"}}


def _index(entries=None, schema="short-drama-market/1"):
    return {
        "schema": schema, "name": "测试市场源", "entries": entries if entries is not None else [
            {"slug": "acme-video", "name": "Acme 视频端点", "version": "1.0.0", "kind": "video_endpoint", "path": "entries/acme-video/definition.json", "summary": "一个声明式视频供应商", "author": "acme"},
        ],
    }


class FakeRepo:
    """Files a market source serves, keyed by full URL; a missing file is a 404."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.fetched: list[str] = []

    def publish(self, base: str, index: dict, definitions: dict[str, dict]):
        self.files[base + market.INDEX_FILENAME] = json.dumps(index, ensure_ascii=False).encode("utf-8")
        for path, definition in definitions.items():
            self.files[base + path] = json.dumps(definition, ensure_ascii=False).encode("utf-8")

    def fetch(self, url: str, max_bytes: int) -> bytes:
        self.fetched.append(url)
        if url not in self.files:
            raise MarketError(f"抓取失败（HTTP 404）：{url}", code="fetch_failed", status=502)
        body = self.files[url]
        if len(body) > max_bytes:
            raise MarketError("too large", code="fetch_too_large", status=502)
        return body


BASE = "https://raw.githubusercontent.com/acme/market/main/"


class SchemaTests(unittest.TestCase):
    def test_an_index_with_a_higher_major_version_is_refused_but_unknown_fields_are_ignored(self):
        with self.assertRaisesRegex(MarketError, "主版本 2 高于"):
            parse_index(_index(schema="short-drama-market/2"))
        index = parse_index({**_index(), "future_field": True, "entries": [{**_index()["entries"][0], "stars": 12}]})
        self.assertEqual(index.entries[0].slug, "acme-video")

    def test_duplicate_slugs_and_escaping_paths_are_refused(self):
        entry = _index()["entries"][0]
        with self.assertRaisesRegex(MarketError, "slug 重复"):
            parse_index(_index([entry, dict(entry)]))
        with self.assertRaisesRegex(MarketError, "相对路径"):
            parse_index(_index([{**entry, "path": "../secrets.json"}]))
        with self.assertRaisesRegex(MarketError, "相对路径"):
            parse_index(_index([{**entry, "path": "https://evil.example/x.json"}]))
        with self.assertRaisesRegex(MarketError, "slug"):
            parse_index(_index([{**entry, "slug": "Bad Slug"}]))

    def test_sources_resolve_to_raw_addresses_and_only_github_raw_goes_through_the_proxy(self):
        github = resolve_source("https://github.com/acme/market")
        self.assertEqual((github.key, github.base_url, github.index_url), ("github:acme/market@main", BASE, BASE + market.INDEX_FILENAME))
        branch = resolve_source("https://github.com/acme/market.git/tree/release")
        self.assertEqual(branch.key, "github:acme/market@release")
        direct = resolve_source("https://cdn.example.com/market/")
        self.assertEqual((direct.kind, direct.index_url, direct.base_url), ("direct", "https://cdn.example.com/market/market-index.json", "https://cdn.example.com/market/"))
        self.assertEqual(resolve_source("https://cdn.example.com/x/custom.json").base_url, "https://cdn.example.com/x/")
        for bad in ("http://github.com/acme/market", "https://github.com/acme", "ftp://x.example/y"):
            with self.assertRaises(MarketError):
                resolve_source(bad)
        with patch.dict("os.environ", {"MARKET_RAW_PROXY_PREFIX": "https://mirror.example/raw"}):
            self.assertEqual(raw_proxied(BASE + "a.json"), "https://mirror.example/raw/" + BASE + "a.json")
            self.assertEqual(raw_proxied("https://cdn.example.com/a.json"), "https://cdn.example.com/a.json")


class FetchBoundaryTests(unittest.TestCase):
    """The fetcher is a server-side request on the person's behalf, so it carries the usual boundaries."""

    def _transport(self, routes):
        def handler(request: httpx.Request) -> httpx.Response:
            status, headers, body = routes[str(request.url)]
            return httpx.Response(status, headers=headers, content=body)
        return httpx.MockTransport(handler)

    def test_only_public_https_hosts_are_fetched_at_every_hop(self):
        with patch.object(market, "_assert_public_host") as guard:
            guard.side_effect = lambda url: (_ for _ in ()).throw(MarketError("非公网", code="fetch_refused")) if "internal" in url else None
            transport = self._transport({"https://ok.example/i.json": (302, {"location": "https://internal.example/i.json"}, b"")})
            with self.assertRaisesRegex(MarketError, "非公网"):
                http_fetch("https://ok.example/i.json", 1000, transport=transport)
        with self.assertRaisesRegex(MarketError, "https"):
            http_fetch("http://ok.example/i.json", 1000)

    def test_redirects_are_followed_a_few_times_and_the_size_is_capped(self):
        with patch.object(market, "_assert_public_host"):
            chain = {f"https://ok.example/{n}.json": (302, {"location": f"https://ok.example/{n + 1}.json"}, b"") for n in range(6)}
            with self.assertRaisesRegex(MarketError, "重定向超过"):
                http_fetch("https://ok.example/0.json", 1000, transport=self._transport(chain))
            routes = {
                "https://ok.example/a.json": (302, {"location": "/b.json"}, b""),
                "https://ok.example/b.json": (200, {}, b'{"ok": true}'),
                "https://ok.example/big.json": (200, {}, b"x" * 2000),
                "https://ok.example/declared.json": (200, {"content-length": "5000"}, b"x"),
                "https://ok.example/missing.json": (404, {}, b""),
            }
            self.assertEqual(http_fetch("https://ok.example/a.json", 1000, transport=self._transport(routes)), b'{"ok": true}')
            with self.assertRaisesRegex(MarketError, "上限"):
                http_fetch("https://ok.example/big.json", 1000, transport=self._transport(routes))
            with self.assertRaisesRegex(MarketError, "上限"):
                http_fetch("https://ok.example/declared.json", 1000, transport=self._transport(routes))
            with self.assertRaisesRegex(MarketError, "HTTP 404"):
                http_fetch("https://ok.example/missing.json", 1000, transport=self._transport(routes))


class MarketApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'market.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            self.admin, _ = await self.store.create_user(email="market-admin@example.com", phone=None, password="market-admin-pass", role="admin")
            self.member, _ = await self.store.create_user(email="market-user@example.com", phone=None, password="market-user-pass", role="user")

        asyncio.run(prepare())
        self.cipher = ModelSecretCipher(Fernet.generate_key())
        self.repo = FakeRepo()
        self.repo.publish(BASE, _index(), {"entries/acme-video/definition.json": _definition()})
        app.dependency_overrides[get_platform_store] = lambda: self.store
        app.dependency_overrides[get_model_secret_cipher] = lambda: self.cipher
        app.dependency_overrides[get_market_fetch] = lambda: self.repo.fetch
        self.client = TestClient(app)
        self.cookies = {"auth_token": auth_service.generate_token(self.admin.id)}
        self.member_cookies = {"auth_token": auth_service.generate_token(self.member.id)}

    def tearDown(self):
        app.dependency_overrides.clear()
        runtime_model_registry.replace([])
        declared_video_endpoints.replace([])
        asyncio.run(self.store.close())
        self.temp.cleanup()

    def _add_source(self):
        added = self.client.post("/api/market/sources", cookies=self.cookies, json={"url": "https://github.com/acme/market", "label": "Acme"})
        self.assertEqual(added.status_code, 200, added.text)
        return added.json()

    def _install(self, source_id, slug="acme-video", **body):
        return self.client.post(f"/api/market/sources/{source_id}/entries/{slug}/install", cookies=self.cookies, json={"api_key": "acme-key-0001", **body})

    def test_a_source_is_added_fetched_and_browsed_by_anyone_but_changed_only_by_admins(self):
        source = self._add_source()
        self.assertEqual((source["label"], source["entry_count"], source["error"], source["official"]), ("Acme", 1, "", False))
        self.assertEqual(self.repo.fetched, [BASE + market.INDEX_FILENAME], "adding a source fetches its index and nothing else")
        entries = self.client.get("/api/market/entries", cookies=self.member_cookies).json()["items"]
        self.assertEqual([(e["slug"], e["version"], e["installed"], e["source_label"]) for e in entries], [("acme-video", "1.0.0", False, "Acme")])
        self.assertEqual(self.client.post("/api/market/sources", cookies=self.member_cookies, json={"url": "https://github.com/x/y"}).status_code, 403)
        duplicate = self.client.post("/api/market/sources", cookies=self.cookies, json={"url": "https://github.com/acme/market/tree/main"})
        self.assertEqual(duplicate.status_code, 409)
        bad = self.client.post("/api/market/sources", cookies=self.cookies, json={"url": "http://github.com/acme/market"})
        self.assertEqual(bad.status_code, 400)

    def test_install_lands_the_endpoint_and_its_record_together_and_needs_a_key_once(self):
        source = self._add_source()
        missing_key = self.client.post(f"/api/market/sources/{source['id']}/entries/acme-video/install", cookies=self.cookies, json={})
        self.assertEqual(missing_key.status_code, 422)
        self.assertEqual(self.client.get("/api/market/installed", cookies=self.cookies).json()["items"], [], "nothing landed")

        installed = self._install(source["id"])
        self.assertEqual(installed.status_code, 200, installed.text)
        body = installed.json()
        self.assertFalse(body["updated"])
        self.assertEqual((body["endpoint"]["family"], body["endpoint"]["key_hint"]), ("acme_video", "****0001"))
        self.assertEqual((body["record"]["market_status"], body["record"]["modified"], body["record"]["version"]), ("latest", False, "1.0.0"))
        self.assertEqual(self.repo.fetched[-1], BASE + "entries/acme-video/definition.json", "install fetches that one definition")

        centre = self.client.get("/api/model-configurations", cookies=self.cookies).json()
        endpoint = next(e for e in centre["settings"]["video_endpoints"] if e["family"] == "acme_video")
        self.assertTrue(endpoint["ready"], "the installed endpoint is an ordinary declared endpoint, key and all")
        self.assertEqual(declared_video_endpoints.family_for_model("acme-v1"), "acme_video")
        entry = self.client.get("/api/market/entries", cookies=self.cookies).json()["items"][0]
        self.assertEqual((entry["installed"], entry["installed_family"], entry["market_status"]), (True, "acme_video", "latest"))

    def test_the_definition_must_match_the_index(self):
        source = self._add_source()
        self.repo.files[BASE + "entries/acme-video/definition.json"] = json.dumps(_definition(version="1.0.1")).encode()
        mismatch = self._install(source["id"])
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(mismatch.json()["detail"]["code"], "index_mismatch")
        self.assertEqual(self.client.get("/api/market/installed", cookies=self.cookies).json()["items"], [])

    def test_update_is_detected_by_version_only_and_a_local_edit_is_protected(self):
        source = self._add_source()
        self.assertEqual(self._install(source["id"]).status_code, 200)
        # Same version, changed content: not an update (the source must bump versions).
        changed = {**SPEC, "family": "acme_video", "label": "Acme 视频（改）"}
        self.repo.publish(BASE, _index(), {"entries/acme-video/definition.json": _definition(spec=changed)})
        self.client.post(f"/api/market/sources/{source['id']}/refresh", cookies=self.cookies)
        self.assertEqual(self.client.get("/api/market/installed", cookies=self.cookies).json()["items"][0]["market_status"], "latest")

        # A new version in the index is an update; a local edit blocks it until discarded.
        index = _index([{**_index()["entries"][0], "version": "1.1.0"}])
        self.repo.publish(BASE, index, {"entries/acme-video/definition.json": _definition(version="1.1.0", spec=changed)})
        self.client.post(f"/api/market/sources/{source['id']}/refresh", cookies=self.cookies)
        record = self.client.get("/api/market/installed", cookies=self.cookies).json()["items"][0]
        self.assertEqual((record["market_status"], record["available_version"], record["modified"]), ("update_available", "1.1.0", False))

        edited = {**SPEC, "max_seconds": 20}
        saved = self.client.put("/api/model-configurations/settings/video-endpoints/acme_video", cookies=self.cookies, json={"spec": edited})
        self.assertEqual(saved.status_code, 200, saved.text)
        record = self.client.get("/api/market/installed", cookies=self.cookies).json()["items"][0]
        self.assertTrue(record["modified"], "an installed endpoint is editable in place and then reads as modified")
        blocked = self._install(source["id"])
        self.assertEqual((blocked.status_code, blocked.json()["detail"]["code"]), (409, "modified_locally"))
        updated = self.client.post(f"/api/market/sources/{source['id']}/entries/acme-video/install", cookies=self.cookies, json={"discard_local": True})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertTrue(updated.json()["updated"])
        self.assertEqual(updated.json()["endpoint"]["key_hint"], "****0001", "an update keeps the key it has")
        record = self.client.get("/api/market/installed", cookies=self.cookies).json()["items"][0]
        self.assertEqual((record["version"], record["market_status"], record["modified"]), ("1.1.0", "latest", False))

    def test_families_are_not_transferred_between_entries_and_overwrite_is_explicit(self):
        source = self._add_source()
        local = self.client.put("/api/model-configurations/settings/video-endpoints/acme_video", cookies=self.cookies, json={"spec": SPEC, "api_key": "local-key-9999"})
        self.assertEqual(local.status_code, 200, local.text)
        refused = self._install(source["id"])
        self.assertEqual((refused.status_code, refused.json()["detail"]["code"]), (409, "overwrite_needed"))
        self.assertEqual(self._install(source["id"], overwrite=True).status_code, 200)

        other_index = _index([{**_index()["entries"][0], "slug": "other-video", "path": "entries/other-video/definition.json"}])
        other_base = "https://raw.githubusercontent.com/other/market/main/"
        self.repo.publish(other_base, other_index, {"entries/other-video/definition.json": _definition(slug="other-video")})
        other = self.client.post("/api/market/sources", cookies=self.cookies, json={"url": "https://github.com/other/market"}).json()
        bound = self._install(other["id"], slug="other-video")
        self.assertEqual((bound.status_code, bound.json()["detail"]["code"]), (409, "family_bound"))
        elsewhere = self._install(other["id"], slug="other-video", family="other_video")
        self.assertEqual(elsewhere.status_code, 200, elsewhere.text)
        self.assertEqual(sorted(r["family"] for r in self.client.get("/api/market/installed", cookies=self.cookies).json()["items"]), ["acme_video", "other_video"])

    def test_removing_or_disabling_a_source_keeps_installs_and_marks_them_unavailable(self):
        source = self._add_source()
        self._install(source["id"])
        off = self.client.patch(f"/api/market/sources/{source['id']}", cookies=self.cookies, json={"enabled": False})
        self.assertEqual(off.status_code, 200)
        self.assertEqual(self.client.get("/api/market/entries", cookies=self.cookies).json()["items"], [], "a disabled source is not browsed")
        self.assertEqual(self.client.get("/api/market/installed", cookies=self.cookies).json()["items"][0]["market_status"], "unavailable")
        self.assertEqual(self.client.patch(f"/api/market/sources/{source['id']}", cookies=self.cookies, json={"enabled": True}).status_code, 200)
        self.assertEqual(self.client.get("/api/market/installed", cookies=self.cookies).json()["items"][0]["market_status"], "latest")

        gone = self.client.delete(f"/api/market/sources/{source['id']}", cookies=self.cookies)
        self.assertEqual(gone.status_code, 200)
        record = self.client.get("/api/market/installed", cookies=self.cookies).json()["items"][0]
        self.assertEqual((record["market_status"], record["endpoint_present"], record["source_key"]), ("unavailable", True, "github:acme/market@main"))
        centre = self.client.get("/api/model-configurations", cookies=self.cookies).json()
        self.assertTrue(any(e["family"] == "acme_video" for e in centre["settings"]["video_endpoints"]), "the endpoint stays")

    def test_uninstall_is_deleting_the_endpoint(self):
        source = self._add_source()
        self._install(source["id"])
        deleted = self.client.delete("/api/model-configurations/settings/video-endpoints/acme_video", cookies=self.cookies)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/market/installed", cookies=self.cookies).json()["items"], [])
        self.assertFalse(self.client.get("/api/market/entries", cookies=self.cookies).json()["items"][0]["installed"])

    def test_the_official_source_comes_from_the_environment_and_can_only_be_disabled(self):
        self.repo.publish("https://raw.githubusercontent.com/short-drama/market/main/", _index(), {"entries/acme-video/definition.json": _definition()})
        with patch.dict("os.environ", {"MARKET_OFFICIAL_SOURCE_URL": "https://github.com/short-drama/market"}):
            listed = self.client.get("/api/market/sources", cookies=self.cookies).json()["items"]
            self.assertEqual([(s["official"], s["label"], s["entry_count"]) for s in listed], [(True, "官方市场源", 0)], "preset, not yet fetched")
            official = listed[0]
            refreshed = self.client.post(f"/api/market/sources/{official['id']}/refresh", cookies=self.cookies)
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            self.assertEqual(refreshed.json()["entry_count"], 1)
            forbidden = self.client.delete(f"/api/market/sources/{official['id']}", cookies=self.cookies)
            self.assertEqual(forbidden.status_code, 409)
            off = self.client.patch(f"/api/market/sources/{official['id']}", cookies=self.cookies, json={"enabled": False})
            self.assertEqual((off.status_code, off.json()["enabled"], off.json()["official"]), (200, False, True))

    def test_a_broken_index_is_reported_on_the_source_and_the_old_index_is_kept(self):
        source = self._add_source()
        self.repo.files[BASE + market.INDEX_FILENAME] = b"{not json"
        failed = self.client.post(f"/api/market/sources/{source['id']}/refresh", cookies=self.cookies)
        self.assertEqual(failed.status_code, 502)
        listed = self.client.get("/api/market/sources", cookies=self.cookies).json()["items"][0]
        self.assertIn("市场索引不可用", listed["error"])
        self.assertEqual(listed["entry_count"], 1, "the last good index stays browsable")

    def test_the_export_bundle_is_a_definition_plus_an_index_entry_without_the_key(self):
        source = self._add_source()
        self._install(source["id"])
        bundle = self.client.post("/api/market/export/acme_video", cookies=self.cookies, json={"author": "me", "summary": "我的端点"}).json()
        self.assertEqual(bundle["slug"], "acme-video")
        definition = json.loads(bundle["files"]["entries/acme-video/definition.json"])
        self.assertEqual(definition["meta"]["version"], "1.0.0")
        self.assertEqual(definition["spec"]["family"], "acme_video")
        self.assertNotIn("acme-key", json.dumps(bundle))
        self.assertEqual(bundle["index_entry"]["path"], "entries/acme-video/definition.json")
        self.assertEqual(spec_digest(definition["spec"]), self.client.get("/api/market/installed", cookies=self.cookies).json()["items"][0].get("digest", spec_digest(definition["spec"])))
        local = self.client.put("/api/model-configurations/settings/video-endpoints/mine", cookies=self.cookies, json={"spec": SPEC, "api_key": "k-0002"})
        self.assertEqual(local.status_code, 200)
        own = self.client.post("/api/market/export/mine", cookies=self.cookies, json={}).json()
        self.assertEqual((own["slug"], own["index_entry"]["version"]), ("mine", "1.0.0"))
        self.assertEqual(self.client.post("/api/market/export/nope", cookies=self.cookies, json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()

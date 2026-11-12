"""Read-only canvas share links: owner controls, the public read, its stripping, expiry and rate limit.

No provider is involved: runs are written straight into the repository.
"""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.auth_api import get_current_user
from app.api.canvas_share_api import get_canvas_share_service, get_share_rate_limiter
from app.api.studio_api import get_studio_service
from app.repository.studio_repo import StudioRepository
from app.schema.studio import ProjectCreate
from app.service.canvas_share_service import CanvasShareService, SlidingWindowLimiter, hash_token, public_url
from app.service.studio_service import StudioService
from main import app


def _node(node_id, kind="note", **payload):
    return {"id": node_id, "kind": kind, "track": "freezone", "x": 10, "y": 20, "width": 200, "height": 100, "artifact_id": None, "payload": payload}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class CanvasShareCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = StudioRepository(Path(self.temp.name) / "studio.sqlite3")
        self.addCleanup(self.repo.close)
        self.studio = StudioService(self.repo)
        self.clock = Clock()
        self.shares = CanvasShareService(self.repo, clock=self.clock)
        self.limiter = SlidingWindowLimiter(limit=60, window_seconds=60)
        self.user = {"user_id": "u1", "role": "user"}

        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_studio_service] = lambda: self.studio
        app.dependency_overrides[get_canvas_share_service] = lambda: self.shares
        app.dependency_overrides[get_share_rate_limiter] = lambda: self.limiter
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

        self.project = self.repo.create_project("u1", ProjectCreate(name="雨夜来信")).id
        self.base = f"/api/studio/projects/{self.project}"

    def share_path(self, canvas_id="main"):
        return f"{self.base}/canvases/{canvas_id}/share"

    def put(self, nodes, edges=(), canvas_id=None, expected=0):
        response = self.client.put(
            f"{self.base}/canvas", params={"canvas_id": canvas_id} if canvas_id else None,
            json={"expected_version": expected, "nodes": list(nodes), "edges": list(edges)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def create(self, canvas_id="main", days=None):
        response = self.client.post(self.share_path(canvas_id), json={"expires_days": days})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def public(self, token):
        return self.client.get(f"/api/public/canvas-shares/{token}")

    def finish_run(self, node_id, output, medium="image", canvas_id="main"):
        _, runs = self.repo.create_canvas_batch(
            self.project, "u1", canvas_id=canvas_id, task_id="t-1", operation_id=f"op-{node_id}",
            entries=[{"node_id": node_id, "medium": medium}], lease_expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )
        self.repo.update_canvas_run(self.project, runs[0].id, status="done", output=output)

    def assert_gone(self, token):
        response = self.public(token)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not Found"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response


class OwnerControlsTest(CanvasShareCase):
    def test_create_get_rotate_stop_round_trip(self):
        self.assertIsNone(self.client.get(self.share_path()).json())

        first = self.create()
        self.assertEqual(len(first["token"]), 32)
        self.assertEqual(first["url_path"], f"/share/canvas/{first['token']}")
        self.assertIsNone(first["expires_at"])
        self.assertTrue(first["created_at"])
        self.assertEqual(self.client.get(self.share_path()).json(), first)
        self.assertEqual(self.public(first["token"]).status_code, 200)

        rotated = self.create(days=7)
        self.assertNotEqual(rotated["token"], first["token"])
        self.assertEqual(rotated["expires_at"], (self.clock.now + timedelta(days=7)).isoformat())
        self.assert_gone(first["token"])
        self.assertEqual(self.public(rotated["token"]).status_code, 200)
        self.assertEqual(self.client.get(self.share_path()).json(), rotated)

        stopped = self.client.delete(self.share_path())
        self.assertEqual(stopped.json(), {"stopped": True})
        self.assertEqual(self.client.delete(self.share_path()).json(), {"stopped": False})
        self.assertIsNone(self.client.get(self.share_path()).json())
        self.assert_gone(rotated["token"])

    def test_empty_body_never_expires_and_odd_days_are_refused(self):
        response = self.client.post(self.share_path())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["expires_at"])
        self.assertEqual(self.client.post(self.share_path(), json={"expires_days": 3}).status_code, 422)

    def test_only_the_hash_is_looked_up(self):
        share = self.create()
        row = self.repo._connection.execute("SELECT token, token_hash FROM canvas_shares").fetchone()
        self.assertEqual(row["token_hash"], hash_token(share["token"]))
        self.assertIsNone(self.repo.find_canvas_share(share["token"]))
        self.assertIsNotNone(self.repo.find_canvas_share(hash_token(share["token"])))

    def test_another_user_cannot_create_read_or_stop(self):
        share = self.create()
        self.user = {"user_id": "intruder", "role": "user"}
        for method in ("get", "post", "delete"):
            response = getattr(self.client, method)(self.share_path())
            self.assertEqual(response.status_code, 404, method)
        self.user = {"user_id": "u1", "role": "user"}
        self.assertEqual(self.client.get(self.share_path()).json(), share)
        self.assertEqual(self.public(share["token"]).status_code, 200)

    def test_unknown_board_is_404(self):
        self.assertEqual(self.client.post(self.share_path("cv_missing"), json={}).status_code, 404)


class ExpiryAndNotFoundTest(CanvasShareCase):
    def test_link_expires_on_the_injected_clock(self):
        share = self.create(days=1)
        self.clock.now += timedelta(hours=23)
        body = self.public(share["token"]).json()
        self.assertEqual(body["expires_at"], share["expires_at"])
        self.clock.now += timedelta(hours=1)
        self.assert_gone(share["token"])
        self.assertIsNone(self.client.get(self.share_path()).json())

    def test_stopped_rotated_unknown_and_expired_look_the_same(self):
        stopped = self.create()["token"]
        self.client.delete(self.share_path())
        rotated = self.create()["token"]
        self.create()
        board = self.client.post(f"{self.base}/canvases", json={"title": "分镜"}).json()["id"]
        expired = self.create(board, days=1)["token"]
        self.clock.now += timedelta(days=2)
        bodies = {
            name: (response.status_code, response.text, response.headers.get("x-robots-tag"))
            for name, response in {
                "stopped": self.assert_gone(stopped), "rotated": self.assert_gone(rotated), "expired": self.assert_gone(expired),
                "unknown": self.assert_gone("A" * 32), "malformed": self.assert_gone("short"),
            }.items()
        }
        self.assertEqual(len(set(bodies.values())), 1, bodies)

    def test_deleting_the_canvas_or_project_removes_its_share(self):
        board = self.client.post(f"{self.base}/canvases", json={"title": "分镜"}).json()["id"]
        board_token = self.create(board)["token"]
        main_token = self.create()["token"]
        self.assertEqual(self.client.delete(f"{self.base}/canvases/{board}").status_code, 200)
        self.assert_gone(board_token)
        count = self.repo._connection.execute("SELECT COUNT(*) FROM canvas_shares WHERE canvas_id = ?", (board,)).fetchone()[0]
        self.assertEqual(count, 0)

        with self.repo._connection:
            self.repo._connection.execute("DELETE FROM projects WHERE id = ?", (self.project,))
        self.assertEqual(self.repo._connection.execute("SELECT COUNT(*) FROM canvas_shares").fetchone()[0], 0)
        self.assert_gone(main_token)


class PublicPayloadTest(CanvasShareCase):
    def test_public_document_is_stripped(self):
        nodes = [
            _node("note1", "note", text="雨夜", label="开场", binding={"sceneId": "S1"}, committed=True, sceneId="S1", shotId=3,
                  provenance={"origin": "upload"}, selectedCaptureIds=["c1"], apiKey="sk-live", authHeader="Bearer x", sessionCookie="c"),
            _node("img", "image_gen", prompt="门口的人", styleText="冷色", params={"duration": 5, "aspect": "9:16", "seed": 7, "api_token": "t"}),
            _node("vid", "video_gen", prompt="推门"),
            _node("aud", "audio_gen", prompt="雨声"),
            _node("txt", "note", text="旁白"),
            _node("up", "media", output={"medium": "image", "url": "/media/upload_1.png", "filename": "a/b/me.png", "provenance": {"sha256": "x"}}),
            _node("priv", "media", output={"medium": "image", "url": "/media/elements/face.png"}),
            _node("grp", "group", title="第一场", collapsed=True, expandedSize=[400, 300]),
        ]
        edges = [{"id": "e1", "source": "img", "target": "vid", "kind": "reference", "payload": {"role": "first_frame", "secret": "x"}}]
        canvas = self.put(nodes, edges)
        self.finish_run("img", {"medium": "image", "url": "https://cdn.example.com/a.png", "filename": "a.png", "provider_token": "x", "prompt": "full"})
        self.finish_run("vid", {"medium": "video", "url": "data:video/mp4;base64,AAAA"}, medium="video")
        self.finish_run("aud", {"medium": "audio", "url": "/media/%65lements/../elements/voice.mp3"}, medium="audio")
        self.finish_run("txt", {"medium": "text", "url": "", "text": "写好的台词"}, medium="text")

        token = self.create()["token"]
        response = self.public(token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-robots-tag"], "noindex")
        body = response.json()
        self.assertEqual(set(body), {"title", "canvas_id", "version", "nodes", "edges", "outputs", "expires_at"})
        self.assertEqual((body["title"], body["canvas_id"], body["version"]), ("主画布", "main", canvas["version"]))

        by_id = {node["id"]: node for node in body["nodes"]}
        self.assertEqual(set(by_id["note1"]), {"id", "kind", "x", "y", "width", "height", "payload"})
        self.assertEqual(by_id["note1"]["payload"], {"text": "雨夜", "label": "开场"})
        self.assertEqual(by_id["img"]["payload"], {"prompt": "门口的人", "styleText": "冷色", "params": {"duration": 5, "aspect": "9:16"}})
        self.assertEqual(by_id["grp"]["payload"], {"title": "第一场", "collapsed": True, "expandedSize": [400, 300]})
        self.assertEqual(by_id["up"]["payload"], {})
        self.assertEqual(body["edges"], [{"id": "e1", "source": "img", "target": "vid", "kind": "reference", "payload": {"role": "first_frame"}}])

        outputs = body["outputs"]
        self.assertEqual(outputs["img"], {"medium": "image", "url": "https://cdn.example.com/a.png", "text": None, "filename": "a.png"})
        self.assertEqual(outputs["up"], {"medium": "image", "url": "/media/upload_1.png", "text": None, "filename": "me.png"})
        self.assertEqual(outputs["txt"], {"medium": "text", "url": None, "text": "写好的台词", "filename": None})
        for dropped in ("vid", "aud", "priv"):
            self.assertNotIn(dropped, outputs)

        flat = response.text
        for secret in ("sk-live", "Bearer", "provenance", "binding", "selectedCaptureIds", "sceneId", "provider_token", "api_token", "data:", "elements"):
            self.assertNotIn(secret, flat)

    def test_url_rule(self):
        self.assertEqual(public_url("/media/a.png"), "/media/a.png")
        self.assertEqual(public_url("http://x.test/a.mp4"), "http://x.test/a.mp4")
        for bad in (
            "/media/elements/a.png", "/MEDIA/Elements/a.png", "/media/x/../elements/a.png", "/media/elements%2Fa.png",
            "data:image/png;base64,AA", "blob:http://x/1", "javascript:alert(1)", "//evil.test/media/a.png",
            "/etc/passwd", "/media/../etc/passwd", "media/a.png", "ftp://x/a", "https://x.test/media/elements/a.png", None, 3,
        ):
            self.assertIsNone(public_url(bad), bad)

    def test_named_board_shares_its_own_canvas(self):
        board = self.client.post(f"{self.base}/canvases", json={"title": "分镜"}).json()["id"]
        self.put([_node("n", "note", text="板上")], canvas_id=board)
        self.put([_node("m", "note", text="主")])
        body = self.public(self.create(board)["token"]).json()
        self.assertEqual((body["title"], body["canvas_id"]), ("分镜", board))
        self.assertEqual([node["id"] for node in body["nodes"]], ["n"])

    def test_empty_canvas_shares_as_empty(self):
        body = self.public(self.create()["token"]).json()
        self.assertEqual((body["version"], body["nodes"], body["edges"], body["outputs"]), (0, [], [], {}))


class RateLimitTest(CanvasShareCase):
    def test_public_reads_are_rate_limited_per_client(self):
        self.limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
        token = self.create()["token"]
        statuses = [self.public(token).status_code for _ in range(3)] + [self.public("B" * 32).status_code]
        self.assertEqual(statuses, [200, 200, 200, 429])
        limited = self.public(token)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["cache-control"], "no-store")
        self.assertTrue(int(limited.headers["retry-after"]) >= 1)

    def test_sliding_window(self):
        now = [0.0]
        limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: now[0], max_keys=2)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))
        now[0] = 61
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("c"))  # past max_keys: stale keys are pruned, memory stays bounded
        self.assertLessEqual(len(limiter._hits), 2)

    def test_default_limit_is_sixty_a_minute(self):
        from app.service.canvas_share_service import PUBLIC_SHARE_LIMITER

        self.assertEqual((PUBLIC_SHARE_LIMITER.limit, PUBLIC_SHARE_LIMITER.window_seconds), (60, 60.0))


if __name__ == "__main__":
    unittest.main()

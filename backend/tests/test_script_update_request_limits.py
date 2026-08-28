import asyncio
import unittest

from fastapi.responses import JSONResponse

from app.platform.request_limits import ScriptUpdateGuardMiddleware


def _scope(*, token: str | None = "valid", address: str = "203.0.113.10") -> dict:
    headers = [] if token is None else [(b"cookie", f"auth_token={token}".encode("latin-1"))]
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PATCH",
        "scheme": "http",
        "path": "/api/drama/task-1/script",
        "raw_path": b"/api/drama/task-1/script",
        "query_string": b"",
        "headers": headers,
        "client": (address, 12345),
        "server": ("test", 80),
    }


async def _body_app(scope, receive, send) -> None:
    while True:
        message = await receive()
        if message.get("type") != "http.request" or not message.get("more_body", False):
            break
    await JSONResponse({"ok": True})(scope, receive, send)


async def _complete_receive():
    return {"type": "http.request", "body": b"{}", "more_body": False}


async def _invoke(guard, scope, receive) -> tuple[int, list[dict]]:
    messages: list[dict] = []

    async def send(message):
        messages.append(message)

    await guard(scope, receive, send)
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    return status, messages


class ScriptUpdateGuardMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    def _guard(self, **overrides) -> ScriptUpdateGuardMiddleware:
        settings = {
            "max_bytes": 128,
            "global_concurrency": 8,
            "client_concurrency": 3,
            "session_rate_limit": 20,
            "ip_rate_limit": 20,
            "idle_timeout_seconds": 0.05,
            "total_timeout_seconds": 0.01,
            "session_verifier": lambda token: "test-user" if token == "valid" else None,
        }
        settings.update(overrides)
        return ScriptUpdateGuardMiddleware(_body_app, **settings)

    async def test_anonymous_stalled_bodies_never_reserve_global_slots(self):
        guard = self._guard()
        never = asyncio.Event()

        async def stalled_receive():
            await never.wait()
            return {"type": "http.request", "body": b"", "more_body": False}

        anonymous = [
            asyncio.create_task(_invoke(guard, _scope(token=None), stalled_receive))
            for _ in range(8)
        ]
        rejected = await asyncio.wait_for(asyncio.gather(*anonymous), timeout=0.1)
        self.assertEqual([status for status, _ in rejected], [401] * 8)
        self.assertEqual(guard._active_total, 0)

        accepted, _ = await _invoke(guard, _scope(), _complete_receive)
        self.assertEqual(accepted, 200)

    async def test_idle_timeout_releases_the_account_and_ip_reservation(self):
        guard = self._guard(idle_timeout_seconds=0.01)
        never = asyncio.Event()

        async def stalled_receive():
            await never.wait()
            return {"type": "http.request", "body": b"", "more_body": False}

        timed_out, _ = await _invoke(guard, _scope(), stalled_receive)
        self.assertEqual(timed_out, 408)
        self.assertEqual(guard._active_total, 0)
        self.assertEqual(guard._active_by_key, {})

        accepted, _ = await _invoke(guard, _scope(), _complete_receive)
        self.assertEqual(accepted, 200)

    async def test_total_body_deadline_rejects_drip_feed_and_releases_reservation(self):
        guard = self._guard(
            idle_timeout_seconds=0.05,
            total_timeout_seconds=0.025,
        )

        async def drip_receive():
            await asyncio.sleep(0.01)
            return {"type": "http.request", "body": b"x", "more_body": True}

        timed_out, _ = await asyncio.wait_for(
            _invoke(guard, _scope(address="203.0.113.45"), drip_receive),
            timeout=0.2,
        )
        self.assertEqual(timed_out, 408)
        self.assertEqual(guard._active_total, 0)
        self.assertEqual(guard._active_by_key, {})

        accepted, _ = await _invoke(
            guard,
            _scope(address="203.0.113.45"),
            _complete_receive,
        )
        self.assertEqual(accepted, 200)

    async def test_enforces_per_user_and_ip_concurrency_and_rate(self):
        guard = self._guard(client_concurrency=2, idle_timeout_seconds=1)
        release = asyncio.Event()

        async def held_receive():
            await release.wait()
            return {"type": "http.request", "body": b"{}", "more_body": False}

        held = [
            asyncio.create_task(_invoke(guard, _scope(), held_receive))
            for _ in range(2)
        ]
        for _ in range(20):
            if guard._active_total == 2:
                break
            await asyncio.sleep(0)
        self.assertEqual(guard._active_total, 2)
        busy, _ = await _invoke(guard, _scope(), _complete_receive)
        self.assertEqual(busy, 429)
        release.set()
        self.assertEqual([status for status, _ in await asyncio.gather(*held)], [200, 200])

        rate_guard = self._guard(session_rate_limit=1, ip_rate_limit=1)
        first, _ = await _invoke(rate_guard, _scope(), _complete_receive)
        second, _ = await _invoke(rate_guard, _scope(), _complete_receive)
        self.assertEqual(first, 200)
        self.assertEqual(second, 429)

    async def test_bounds_chunked_bodies_without_timing_out_committed_work(self):
        guard = self._guard(max_bytes=10)
        chunks = iter([
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"abcdef", "more_body": False},
        ])

        async def chunked_receive():
            return next(chunks)

        oversized, _ = await _invoke(guard, _scope(), chunked_receive)
        self.assertEqual(oversized, 413)

        started = asyncio.Event()
        release = asyncio.Event()
        commits: list[str] = []

        async def committing_app(scope, receive, send):
            await receive()
            started.set()
            await release.wait()
            commits.append("saved")
            await JSONResponse({"ok": True})(scope, receive, send)

        commit_guard = self._guard()
        commit_guard.app = committing_app
        pending = asyncio.create_task(
            _invoke(commit_guard, _scope(address="203.0.113.44"), _complete_receive)
        )
        await asyncio.wait_for(started.wait(), timeout=0.1)
        # Exceed the guard's former whole-application timeout. A synchronous
        # FastAPI handler cannot be cancelled once its thread has started, so
        # the middleware must keep the request pending instead of emitting a
        # false 408 while the commit continues.
        await asyncio.sleep(0.25)

        self.assertFalse(pending.done())
        self.assertEqual(commit_guard._active_total, 1)
        self.assertEqual(commits, [])

        release.set()
        status, _ = await asyncio.wait_for(pending, timeout=0.1)
        self.assertEqual(status, 200)
        self.assertEqual(commits, ["saved"])
        self.assertEqual(commit_guard._active_total, 0)


if __name__ == "__main__":
    unittest.main()

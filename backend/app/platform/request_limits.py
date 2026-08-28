from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections import deque
from http.cookies import CookieError, SimpleCookie
from typing import Callable

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.service.auth_service import verify_session_token


def _environment_limit(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


MODEL_UPLOAD_REQUEST_MAX_BYTES = _environment_limit(
    "ELEMENT_MODEL_REQUEST_MAX_BYTES",
    26 * 1024 * 1024,
    minimum=25 * 1024 * 1024,
    maximum=64 * 1024 * 1024,
)
IMAGE_UPLOAD_REQUEST_MAX_BYTES = _environment_limit(
    "ELEMENT_IMAGE_REQUEST_MAX_BYTES",
    11 * 1024 * 1024,
    minimum=10 * 1024 * 1024,
    maximum=32 * 1024 * 1024,
)
SCRIPT_UPDATE_REQUEST_MAX_BYTES = _environment_limit(
    "SCRIPT_UPDATE_REQUEST_MAX_BYTES",
    5 * 1024 * 1024,
    minimum=2 * 1024 * 1024,
    maximum=16 * 1024 * 1024,
)


class _RequestBodyTooLarge(RuntimeError):
    pass


class _RequestBodyTimedOut(RuntimeError):
    pass


class ScriptUpdateGuardMiddleware:
    """Authenticate and bound screenplay PATCH bodies before JSON parsing."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int = SCRIPT_UPDATE_REQUEST_MAX_BYTES,
        global_concurrency: int = 8,
        client_concurrency: int = 3,
        session_rate_limit: int = 60,
        ip_rate_limit: int = 120,
        rate_window_seconds: int = 60,
        idle_timeout_seconds: float = 10,
        total_timeout_seconds: float = 30,
        session_verifier: Callable[[str], str | None] = verify_session_token,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.global_concurrency = global_concurrency
        self.client_concurrency = client_concurrency
        self.session_rate_limit = session_rate_limit
        self.ip_rate_limit = ip_rate_limit
        self.rate_window_seconds = rate_window_seconds
        self.idle_timeout_seconds = idle_timeout_seconds
        # This deadline applies only while consuming the request body. A
        # whole-application timeout is unsafe here: FastAPI sync handlers run
        # in a thread pool and continue after cancellation, which could return
        # 408 even though the screenplay is committed moments later.
        self.body_timeout_seconds = total_timeout_seconds
        self.session_verifier = session_verifier
        self._lock = asyncio.Lock()
        self._active_total = 0
        self._active_by_key: dict[str, int] = {}
        self._attempts_by_key: dict[str, deque[float]] = {}
        self._reservation_count = 0

    @staticmethod
    def _matches(scope: Scope) -> bool:
        if scope.get("type") != "http" or scope.get("method") != "PATCH":
            return False
        parts = str(scope.get("path", "")).rstrip("/").split("/")
        return len(parts) == 5 and parts[1:3] == ["api", "drama"] and parts[4] == "script"

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
        await JSONResponse(status_code=status, content={"detail": detail})(scope, receive, send)

    @staticmethod
    def _headers(scope: Scope) -> dict[str, str]:
        return {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }

    def _client_keys(self, scope: Scope, headers: dict[str, str]) -> tuple[str, ...] | None:
        client = scope.get("client")
        address = client[0] if client else "unknown"
        raw_cookie = headers.get("cookie", "")
        try:
            cookie = SimpleCookie()
            cookie.load(raw_cookie)
            token = cookie.get("auth_token")
        except CookieError:
            return None
        if not token or len(token.value) > 4096:
            return None
        user_id = self.session_verifier(token.value)
        if not user_id:
            return None
        digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
        return (f"ip:{address}", f"user:{digest}")

    async def _reserve(self, keys: tuple[str, ...]) -> str | None:
        now = time.monotonic()
        cutoff = now - self.rate_window_seconds
        async with self._lock:
            self._reservation_count += 1
            if self._reservation_count % 100 == 0:
                for key, attempts in list(self._attempts_by_key.items()):
                    while attempts and attempts[0] <= cutoff:
                        attempts.popleft()
                    if not attempts and self._active_by_key.get(key, 0) == 0:
                        self._attempts_by_key.pop(key, None)
            if self._active_total >= self.global_concurrency:
                return "剧本编辑服务繁忙，请稍后重试"
            for key in keys:
                if self._active_by_key.get(key, 0) >= self.client_concurrency:
                    return "同一账号或网络的并发剧本编辑过多"
                attempts = self._attempts_by_key.setdefault(key, deque())
                while attempts and attempts[0] <= cutoff:
                    attempts.popleft()
                limit = self.ip_rate_limit if key.startswith("ip:") else self.session_rate_limit
                if len(attempts) >= limit:
                    return "剧本编辑请求过于频繁，请稍后重试"
            self._active_total += 1
            for key in keys:
                self._active_by_key[key] = self._active_by_key.get(key, 0) + 1
                self._attempts_by_key[key].append(now)
            return None

    async def _release(self, keys: tuple[str, ...]) -> None:
        async with self._lock:
            self._active_total = max(0, self._active_total - 1)
            for key in keys:
                remaining = self._active_by_key.get(key, 0) - 1
                if remaining > 0:
                    self._active_by_key[key] = remaining
                else:
                    self._active_by_key.pop(key, None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._matches(scope):
            await self.app(scope, receive, send)
            return

        headers = self._headers(scope)
        keys = self._client_keys(scope, headers)
        if keys is None:
            await self._reject(scope, receive, send, 401, "未登录或会话已过期")
            return
        content_length = headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                await self._reject(scope, receive, send, 400, "Content-Length 无效")
                return
            if declared_length < 0 or declared_length > self.max_bytes:
                await self._reject(scope, receive, send, 413, "剧本请求体超过大小限制")
                return

        reservation_error = await self._reserve(keys)
        if reservation_error:
            await self._reject(scope, receive, send, 429, reservation_error)
            return

        received = 0
        body_complete = False
        body_deadline = time.monotonic() + self.body_timeout_seconds

        async def limited_receive() -> Message:
            nonlocal body_complete, received
            if body_complete:
                return await receive()
            remaining_total = body_deadline - time.monotonic()
            if remaining_total <= 0:
                raise _RequestBodyTimedOut
            try:
                message = await asyncio.wait_for(
                    receive(),
                    timeout=min(self.idle_timeout_seconds, remaining_total),
                )
            except TimeoutError as exc:
                raise _RequestBodyTimedOut from exc
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _RequestBodyTooLarge
                body_complete = not message.get("more_body", False)
            elif message.get("type") == "http.disconnect":
                body_complete = True
            return message

        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if not response_started:
                await self._reject(scope, receive, send, 413, "剧本请求体超过大小限制")
        except _RequestBodyTimedOut:
            if not response_started:
                await self._reject(scope, receive, send, 408, "剧本请求体等待超时")
        finally:
            await self._release(keys)


class ElementUploadGuardMiddleware:
    """Bound element multipart traffic before Starlette spools it to disk."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        model_max_bytes: int = MODEL_UPLOAD_REQUEST_MAX_BYTES,
        image_max_bytes: int = IMAGE_UPLOAD_REQUEST_MAX_BYTES,
        global_concurrency: int = 12,
        client_concurrency: int = 3,
        session_rate_limit: int = 30,
        ip_rate_limit: int = 60,
        session_byte_limit: int = 256 * 1024 * 1024,
        ip_byte_limit: int = 512 * 1024 * 1024,
        rate_window_seconds: int = 60,
        idle_timeout_seconds: float = 10,
        total_timeout_seconds: float = 90,
        session_verifier: Callable[[str], str | None] = verify_session_token,
    ) -> None:
        self.app = app
        self.model_max_bytes = model_max_bytes
        self.image_max_bytes = image_max_bytes
        self.global_concurrency = global_concurrency
        self.client_concurrency = client_concurrency
        self.session_rate_limit = session_rate_limit
        self.ip_rate_limit = ip_rate_limit
        self.session_byte_limit = session_byte_limit
        self.ip_byte_limit = ip_byte_limit
        self.rate_window_seconds = rate_window_seconds
        self.idle_timeout_seconds = idle_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.session_verifier = session_verifier
        self._lock = asyncio.Lock()
        self._active_total = 0
        self._active_by_key: dict[str, int] = {}
        self._attempts_by_key: dict[str, deque[tuple[float, int]]] = {}
        self._reservation_count = 0

    def _body_limit(self, scope: Scope) -> int | None:
        if scope.get("type") != "http" or scope.get("method") != "POST":
            return None
        path = str(scope.get("path", "")).rstrip("/")
        parts = path.split("/")
        if len(parts) != 5 or parts[1:3] != ["api", "elements"] or not parts[3]:
            return None
        if parts[4] == "model":
            return self.model_max_bytes
        if parts[4] == "files":
            return self.image_max_bytes
        return None

    @staticmethod
    def _headers(scope: Scope) -> dict[str, str]:
        return {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }

    def _client_keys(self, scope: Scope, headers: dict[str, str]) -> tuple[str, ...] | None:
        client = scope.get("client")
        address = client[0] if client else "unknown"
        raw_cookie = headers.get("cookie", "")
        try:
            cookie = SimpleCookie()
            cookie.load(raw_cookie)
            token = cookie.get("auth_token")
        except CookieError:
            return None
        if not token or len(token.value) > 4096:
            return None
        user_id = self.session_verifier(token.value)
        if not user_id:
            return None
        digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
        return (f"ip:{address}", f"user:{digest}")

    async def _reserve(self, keys: tuple[str, ...], reserved_bytes: int) -> str | None:
        now = time.monotonic()
        cutoff = now - self.rate_window_seconds
        async with self._lock:
            self._reservation_count += 1
            if self._reservation_count % 100 == 0:
                for key, attempts in list(self._attempts_by_key.items()):
                    while attempts and attempts[0][0] <= cutoff:
                        attempts.popleft()
                    if not attempts and self._active_by_key.get(key, 0) == 0:
                        self._attempts_by_key.pop(key, None)
            if self._active_total >= self.global_concurrency:
                return "3D 资产上传服务繁忙，请稍后重试"
            for key in keys:
                if self._active_by_key.get(key, 0) >= self.client_concurrency:
                    return "同一账号或网络的并发上传过多"
                attempts = self._attempts_by_key.setdefault(key, deque())
                while attempts and attempts[0][0] <= cutoff:
                    attempts.popleft()
                is_ip = key.startswith("ip:")
                request_limit = self.ip_rate_limit if is_ip else self.session_rate_limit
                byte_limit = self.ip_byte_limit if is_ip else self.session_byte_limit
                if len(attempts) >= request_limit:
                    return "上传请求过于频繁，请稍后重试"
                if sum(size for _, size in attempts) + reserved_bytes > byte_limit:
                    return "上传流量已达到当前时间窗口上限"
            self._active_total += 1
            for key in keys:
                self._active_by_key[key] = self._active_by_key.get(key, 0) + 1
                self._attempts_by_key[key].append((now, reserved_bytes))
            return None

    async def _release(self, keys: tuple[str, ...]) -> None:
        async with self._lock:
            self._active_total = max(0, self._active_total - 1)
            for key in keys:
                remaining = self._active_by_key.get(key, 0) - 1
                if remaining > 0:
                    self._active_by_key[key] = remaining
                else:
                    self._active_by_key.pop(key, None)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
        response = JSONResponse(status_code=status, content={"detail": detail})
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        body_limit = self._body_limit(scope)
        if body_limit is None:
            await self.app(scope, receive, send)
            return

        headers = self._headers(scope)
        content_length = headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                await self._reject(scope, receive, send, 400, "Content-Length 无效")
                return
            if declared_length < 0 or declared_length > body_limit:
                await self._reject(scope, receive, send, 413, "上传请求体超过大小限制")
                return

        keys = self._client_keys(scope, headers)
        if keys is None:
            await self._reject(scope, receive, send, 401, "未登录或会话已过期")
            return
        reserved_bytes = declared_length if content_length else body_limit
        reservation_error = await self._reserve(keys, reserved_bytes)
        if reservation_error:
            await self._reject(scope, receive, send, 429, reservation_error)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            try:
                message = await asyncio.wait_for(receive(), timeout=self.idle_timeout_seconds)
            except TimeoutError as exc:
                raise HTTPException(status_code=408, detail="上传数据等待超时") from exc
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > body_limit:
                    raise HTTPException(status_code=413, detail="上传请求体超过大小限制")
            return message

        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await asyncio.wait_for(
                self.app(scope, limited_receive, tracked_send),
                timeout=self.total_timeout_seconds,
            )
        except TimeoutError:
            if not response_started:
                await self._reject(scope, receive, send, 408, "上传处理超过总时限")
        finally:
            await self._release(keys)

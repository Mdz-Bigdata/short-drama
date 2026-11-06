"""A refused paid call, as the answer to the request that asked for it."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.platform.billing_book import BillingRefused


def _refusal_in(error: BaseException) -> BillingRefused | None:
    if isinstance(error, BillingRefused):
        return error
    # A middleware built on a task group hands it back wrapped.
    if isinstance(error, BaseExceptionGroup):
        for inner in error.exceptions:
            found = _refusal_in(inner)
            if found:
                return found
    return None


class BillingRefusalMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking(message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, tracking)
        except BaseException as error:
            refusal = _refusal_in(error)
            if refusal is None or started:
                raise
            response = JSONResponse(status_code=402, content={
                "detail": refusal.detail, "code": refusal.code, "required": refusal.required, "available": refusal.available,
            })
            await response(scope, receive, send)

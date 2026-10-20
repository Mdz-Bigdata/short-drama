# -*- coding: utf-8 -*-
"""A per-call sampling profile handed from a caller down to the model gateway.

The gateway's text entry point is called through several layers that only pass
a system prompt, a user prompt and an output budget. A stage that wants a
cooler or warmer model (JSON extraction versus prose) sets the profile in a
context scope around its call; the gateway reads it when it builds the request.
The scope is a ``ContextVar``, so it follows the call into thread pools that
copy their context and never leaks into another request.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_TEMPERATURE = 0.7

_TEMPERATURE: ContextVar[float | None] = ContextVar("llm_temperature", default=None)


def current_temperature(default: float | None = None) -> float | None:
    """The temperature the enclosing scope asked for, else ``default``."""
    value = _TEMPERATURE.get()
    return default if value is None else value


@contextmanager
def temperature_scope(value: float | None):
    """Run the block with ``value`` as the requested temperature (``None`` restores the gateway's default)."""
    clamped = None if value is None else max(0.0, min(2.0, float(value)))
    token = _TEMPERATURE.set(clamped)
    try:
        yield
    finally:
        _TEMPERATURE.reset(token)


__all__ = ["DEFAULT_TEMPERATURE", "current_temperature", "temperature_scope"]

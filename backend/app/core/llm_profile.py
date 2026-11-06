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

import os
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_TEMPERATURE = 0.7
REASONING_LEVELS = ("off", "low", "high", "max")

_TEMPERATURE: ContextVar[float | None] = ContextVar("llm_temperature", default=None)
_REASONING: ContextVar[str | None] = ContextVar("llm_reasoning", default=None)


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


def current_reasoning() -> str | None:
    """How hard the enclosing scope asked the model to think; ``None`` keeps the provider's default."""
    return _REASONING.get()


@contextmanager
def reasoning_scope(level: str | None):
    """Run the block with ``level`` (one of ``REASONING_LEVELS``) as the requested reasoning effort."""
    token = _REASONING.set(level if level in REASONING_LEVELS else None)
    try:
        yield
    finally:
        _REASONING.reset(token)


def reasoning_from_env(variable: str, default: str | None = None) -> str | None:
    """A reasoning level from the environment; unset or unknown falls back to ``default``."""
    value = (os.getenv(variable) or "").strip().lower()
    return value if value in REASONING_LEVELS else default


__all__ = [
    "DEFAULT_TEMPERATURE",
    "REASONING_LEVELS",
    "current_reasoning",
    "current_temperature",
    "reasoning_from_env",
    "reasoning_scope",
    "temperature_scope",
]

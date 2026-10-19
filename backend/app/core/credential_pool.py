"""Several keys for one provider: calls take turns, and a key that just failed sits out for a while.

A provider configuration may hold more than one credential. Each call asks the
pool for one, naming the job-type bucket it is for (text / image / video /
audio): only keys allowed in that bucket are considered, in rotation, and a key
the provider rejected (401 / 403 / 429) is skipped for a cooling period so the
next call does not pay the same refusal again. With one key the pool is a
pass-through; nothing here reads the environment.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

from app import settings

# Status codes that say "this key", not "this request": the pool moves on to the next key.
CREDENTIAL_REJECTED = frozenset({401, 403, 429})
DEFAULT_COOLDOWN_SECONDS = 300


@dataclass(frozen=True)
class Credential:
    id: str
    api_key: str
    label: str = ""
    buckets: tuple[str, ...] = ()
    enabled: bool = True

    def serves(self, bucket: str) -> bool:
        return self.enabled and (not self.buckets or bucket in self.buckets)


@dataclass
class _State:
    cursor: int = 0
    cooling: dict[str, float] = field(default_factory=dict)
    last_error: dict[str, str] = field(default_factory=dict)
    uses: dict[str, int] = field(default_factory=dict)


class CredentialPool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, _State] = {}

    def cooldown_seconds(self) -> float:
        return settings.env_float("CREDENTIAL_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS, minimum=0)

    def candidates(self, pool_id: str, credentials: Iterable[Credential], bucket: str) -> list[Credential]:
        """The keys to try for this call, in order: rotation first, cooling ones last."""
        usable = [c for c in credentials if c.serves(bucket)]
        if not usable:
            return []
        with self._lock:
            state = self._states.setdefault(pool_id, _State())
            now = time.monotonic()
            start = state.cursor % len(usable)
            state.cursor = start + 1
            rotated = usable[start:] + usable[:start]
            fresh = [c for c in rotated if state.cooling.get(c.id, 0) <= now]
            cooling = [c for c in rotated if state.cooling.get(c.id, 0) > now]
            return fresh + cooling

    def note_rejected(self, pool_id: str, credential_id: str, status: int | None, error: str = "") -> bool:
        """Record a refusal; returns True when it was a credential problem and the key is now cooling."""
        if status not in CREDENTIAL_REJECTED:
            return False
        with self._lock:
            state = self._states.setdefault(pool_id, _State())
            state.cooling[credential_id] = time.monotonic() + self.cooldown_seconds()
            state.last_error[credential_id] = f"HTTP {status}{(' ' + error) if error else ''}"[:200]
        return True

    def note_used(self, pool_id: str, credential_id: str) -> None:
        with self._lock:
            state = self._states.setdefault(pool_id, _State())
            state.uses[credential_id] = state.uses.get(credential_id, 0) + 1
            state.cooling.pop(credential_id, None)

    def status(self, pool_id: str, credential_id: str) -> dict:
        with self._lock:
            state = self._states.get(pool_id) or _State()
            until = state.cooling.get(credential_id, 0)
            cooling = until > time.monotonic()
            return {
                "cooling": cooling,
                "cooling_seconds_left": max(0, round(until - time.monotonic())) if cooling else 0,
                "last_error": state.last_error.get(credential_id) if cooling else None,
                "uses": state.uses.get(credential_id, 0),
            }

    def reset(self) -> None:
        with self._lock:
            self._states.clear()


credential_pool = CredentialPool()

__all__ = ["CREDENTIAL_REJECTED", "Credential", "CredentialPool", "credential_pool"]

"""What each provider call comes to in points, recorded for every call. Nothing is taken from anyone's balance yet.

A call happens on a worker thread and may outlive the database being reachable, so its record goes to a local file
first and a background job moves it into ``usage_charges``. ``usage_id`` keeps that idempotent: a file replayed after
a crash adds nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool

from app import settings

logger = logging.getLogger("app.platform.usage_billing")

RATE_KINDS = ("per_million_tokens", "per_image", "per_second", "per_thousand_characters", "per_call")
#: Providers that cost nothing: a reused answer, speech made on this machine.
FREE_PROVIDERS = frozenset({"memo", "local", "comfyui"})
#: Points are kept to this many places: a short text call is a small fraction of a point.
_PLACES = Decimal("0.0001")

CUSTOMER = "customer"
#: Taken from a balance, once charging is on.
CHARGED = "charged"
EXEMPT = "exempt"
OPERATOR_ABSORBED = "operator_absorbed"
UNATTRIBUTED = "unattributed"


def _number(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return Decimal(0)
    try:
        number = Decimal(str(value))
    except ArithmeticError:
        return Decimal(0)
    return number if number.is_finite() else Decimal(0)


def points_for(rate: Any, units: Mapping[str, Any]) -> Decimal:
    """What a successful call with these units comes to under ``rate``."""
    if rate.kind == "per_million_tokens":
        tokens_in, cached = _number(units.get("input_tokens")), _number(units.get("cached_tokens"))
        cached = min(cached, tokens_in)
        points = (
            (tokens_in - cached) * _number(rate.input) + cached * _number(rate.cached_input)
            + _number(units.get("output_tokens")) * _number(rate.output)
        ) / 1_000_000
    elif rate.kind == "per_image":
        points = _number(units.get("images") or 1) * _number(rate.price)
    elif rate.kind == "per_second":
        points = _number(units.get("seconds")) * _number(rate.price)
    elif rate.kind == "per_thousand_characters":
        points = _number(units.get("characters")) / 1000 * _number(rate.price)
    else:
        points = _number(rate.price)
    return points.quantize(_PLACES)


def find_rate(rates: Sequence[Any], model: str, resolution: str | None, at: datetime) -> Any | None:
    """The rate in force at ``at``. A longer model name beats a shorter one contained in it, as prices match."""
    key = (model or "").strip().lower()
    wanted = (resolution or "").strip().lower()
    in_force = [rate for rate in rates if _aware(rate.effective_from) <= at]
    names = [rate.model for rate in in_force if rate.model == key] or [rate.model for rate in in_force if rate.model and rate.model in key]
    if not names:
        return None
    name = max(names, key=len)
    candidates = [rate for rate in in_force if rate.model == name and rate.resolution in {wanted, ""}]
    if not candidates:
        return None
    # An entry for this resolution beats the general one; among those, the latest wins.
    return max(candidates, key=lambda rate: (rate.resolution == wanted, _aware(rate.effective_from)))


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def charge_from(entry: Mapping[str, Any], rates: Sequence[Any], owner_id: str | None) -> dict[str, Any]:
    """One record as a ``usage_charges`` row. The project's owner pays; someone else working on it is an operator."""
    occurred = _aware(datetime.fromisoformat(str(entry["at"])))
    units = dict(entry.get("units") or {})
    requester = str(entry.get("user_id") or "") or None
    provider = str(entry.get("provider") or "")
    succeeded = entry.get("status") == "success"
    if owner_id:
        user_id, operator_id = owner_id, requester if requester and requester != owner_id else None
    else:
        user_id, operator_id = requester, None
    mode = UNATTRIBUTED if not user_id else OPERATOR_ABSORBED if operator_id else CUSTOMER
    if mode == CUSTOMER and entry.get("billing_mode") in {CHARGED, EXEMPT}:
        mode = str(entry["billing_mode"])
    chargeable = succeeded and provider not in FREE_PROVIDERS
    # What was actually called: a name the configuration centre resolves can differ from the name asked for.
    model = str(units.get("api_model") or entry.get("model") or "")
    rate = find_rate(rates, model, units.get("resolution"), occurred) if chargeable else None
    return {
        "usage_id": str(entry["id"]),
        "user_id": user_id,
        "task_id": str(entry.get("task_id") or "") or None,
        "operator_id": operator_id,
        "billing_mode": mode,
        "media_type": str(entry.get("media_type") or ""),
        "provider": provider[:64],
        "model": model[:160],
        "purpose": str(entry.get("purpose") or "")[:120],
        "status": str(entry.get("status") or ""),
        "units": units,
        "points": points_for(rate, units) if rate is not None else Decimal(0),
        "rate_id": rate.id if rate is not None else None,
        "rate_missing": bool(chargeable and rate is None),
        "reference_cost": entry.get("cost"),
        "reference_currency": entry.get("currency"),
        "occurred_at": occurred,
    }


class UsageSpool:
    """An append-only file per process. A process only ever empties its own file, or one whose process is gone."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory or settings.RUNTIME_DIR / "usage_spool")
        self._lock = threading.Lock()

    @property
    def _path(self) -> Path:
        return self.directory / f"{os.getpid()}.jsonl"

    def append(self, record: Mapping[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())

    def take(self) -> list[Path]:
        """Files ready to load: this process's, set aside so new records start a new one, and any left by a dead one."""
        if not self.directory.is_dir():
            return []
        with self._lock:
            mine = self._path
            if mine.exists():
                os.replace(mine, mine.with_name(f"{mine.stem}.{os.urandom(4).hex()}.draining"))
        ready = []
        for path in sorted(self.directory.iterdir()):
            pid = path.name.split(".", 1)[0]
            if path.suffix == ".draining" and (pid == str(os.getpid()) or not _process_alive(pid)):
                ready.append(path)
            elif path.suffix == ".jsonl" and path != mine and not _process_alive(pid):
                ready.append(path)
        return ready

    def backlog(self) -> int:
        if not self.directory.is_dir():
            return 0
        return sum(1 for path in self.directory.iterdir() if path.suffix in {".jsonl", ".draining"})


def _process_alive(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError):
        return True
    return True


def read_records(path: Path) -> list[dict[str, Any]]:
    """The records in a file. A line a crash cut short is logged and skipped: it cannot be read back by anyone."""
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            record = json.loads(line)
            if not record.get("id") or not record.get("at"):
                raise ValueError("missing id or at")
            records.append(record)
        except ValueError:
            logger.error("[Billing] 无法读取的用量记录: file=%s line=%s", path.name, number)
    return records


async def drain(store: Any, spool: UsageSpool, owner_of: Callable[[str], str | None]) -> int:
    """Load what is waiting. A file is only removed once its rows are committed; otherwise the next pass tries again."""
    saved = 0
    for path in spool.take():
        records = await run_in_threadpool(read_records, path)
        if records:
            task_ids = {str(record["task_id"]) for record in records if record.get("task_id")}
            owners = {task_id: await run_in_threadpool(owner_of, task_id) for task_id in task_ids}
            rates = await store.list_point_rates()
            rows = [charge_from(record, rates, owners.get(str(record.get("task_id") or ""))) for record in records]
            saved += await store.save_usage_charges(rows)
        path.unlink()
    return saved


async def run_drain_loop(store: Any, spool: UsageSpool, owner_of: Callable[[str], str | None]) -> None:
    interval = settings.env_int("USAGE_DRAIN_SECONDS", 5, minimum=1, maximum=300)
    while True:
        await asyncio.sleep(interval)
        try:
            await drain(store, spool, owner_of)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the file stays; the next pass tries again
            logger.warning("[Billing] 用量入库失败，稍后重试: %s", type(exc).__name__)


def usage_differences(
    charges: Iterable[Any], rates: Sequence[Any], records_by_task: Mapping[str, Sequence[Mapping[str, Any]]],
    *, settled_before: datetime, sample: int = 20,
) -> dict[str, Any]:
    """R6 and R7 of docs/access-and-billing/DESIGN.md. Rows newer than ``settled_before`` may still be on their way."""
    charges = list(charges)
    by_id = {rate.id: rate for rate in rates}
    wrong: list[dict[str, Any]] = []
    for charge in charges:
        rate = by_id.get(charge.rate_id) if charge.rate_id else None
        expected = points_for(rate, charge.units or {}) if rate is not None else Decimal(0)
        chosen = find_rate(rates, charge.model, (charge.units or {}).get("resolution"), _aware(charge.occurred_at))
        problem = (
            "points" if expected != Decimal(str(charge.points)) else
            "failed_call_charged" if charge.status != "success" and Decimal(str(charge.points)) != 0 else
            "wrong_rate" if charge.rate_id and (chosen is None or chosen.id != charge.rate_id) else
            None
        )
        if problem:
            wrong.append({"usage_id": charge.usage_id, "problem": problem, "expected": str(expected), "actual": str(charge.points)})

    first = min((_aware(charge.occurred_at) for charge in charges), default=None)
    charged_by_task: dict[str, set[str]] = {}
    for charge in charges:
        if charge.task_id:
            charged_by_task.setdefault(charge.task_id, set()).add(charge.usage_id)
    not_charged, not_on_project = [], []
    for task_id, records in records_by_task.items():
        kept = {str(record.get("id")): _aware(datetime.fromisoformat(str(record["at"]))) for record in records if record.get("id") and record.get("at")}
        charged = charged_by_task.get(task_id, set())
        for usage_id, at in kept.items():
            # Calls from before charges were kept have nothing to match.
            if first is not None and first <= at <= settled_before and usage_id not in charged:
                not_charged.append({"usage_id": usage_id, "task_id": task_id})
        oldest = min(kept.values(), default=None)
        for charge in charges:
            occurred = _aware(charge.occurred_at)
            # A project keeps only its newest records, so an older one having fallen off is not a difference.
            if charge.task_id == task_id and charge.usage_id not in kept and occurred <= settled_before and (oldest is None or occurred >= oldest):
                not_on_project.append({"usage_id": charge.usage_id, "task_id": task_id})
    return {
        "checked": len(charges),
        "r6": {"differences": len(wrong), "samples": wrong[:sample]},
        "r7": {
            "projects": len(records_by_task),
            "differences": len(not_charged) + len(not_on_project),
            "records_without_charge": not_charged[:sample],
            "charges_not_on_project": not_on_project[:sample],
        },
        # Not differences, but what stands between recording and charging.
        "rate_missing": sum(1 for charge in charges if charge.rate_missing),
        "unattributed": sum(1 for charge in charges if charge.billing_mode == UNATTRIBUTED),
    }

"""Task-level recursion: propose, probe, compose, in parallel (width) or in sequence (depth).

After Harness²'s ``core/recursion.py`` and ``core/ledger.py``. Each mode spends exactly 4k executions
of the stage call (k under the unchanged overlay, 2k candidates, k finals) and 3k improvement calls
(k INV, k DOM, k compositions); the ledger refuses a run that did not land on that. A proposal that
cannot be taken is sent back once with the reason, then the stage inherits the overlay it started from.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app import settings
from app.core.harness_recursion import harness as surface
from app.core.harness_recursion import prompts
from app.core.harness_recursion.harness import Harness, ProposalError

STAGE_ATTEMPTS = 2
MODES = ("agg", "seq")

Improver = Callable[[str, str], str]
"""``(mission, evidence) -> reply``: the model that proposes, composes, selects and reflects."""


def phase_width() -> int:
    """How many calls of one phase run side by side (HARNESS_EVOLUTION_WIDTH, default 2)."""
    return settings.env_int("HARNESS_EVOLUTION_WIDTH", 2, minimum=1, maximum=8)


@dataclass
class Rollout:
    """One execution of the stage call under an overlay. It never carries a score."""

    label: str
    text: str = ""
    ok: bool = True
    delivered: bool = True
    observations: str = ""
    error: str = ""

    def shown(self, size: int) -> str:
        """What an improver reads of this execution."""
        if not self.ok:
            return prompts.says("labels", "failed", error=self.error[:200])
        if not self.delivered:
            return prompts.label("not_delivered")
        body = prompts.clip(self.text, size)
        return body + (prompts.says("context", "observations", observations=self.observations) if self.observations else "")


@dataclass
class Evidence:
    """What every improvement call of one task is shown; the adapter fills it once."""

    work: str
    domain: str
    request: str
    outline: str = ""
    library: str = ""
    # How this kind of work is looked at, what good practice in it looks like, what "correct" means for
    # its output: upstream's per-benchmark lens, yardstick and selection checks. Words about the work only.
    lens: str = ""
    yardstick: str = ""
    checks: str = ""
    # This project's own names (cast, title): allowed in the ``memory`` component only.
    project_terms: tuple[str, ...] = ()


@dataclass
class Stage:
    """One improvement call with its retry, the overlay it settled on, and why."""

    label: str
    dim: str
    harness: Harness
    kept_base: bool = False
    fell_back: bool = False
    attempts: int = 0
    notes: str = ""
    error: str = ""


class BudgetError(AssertionError):
    """The ledger did not land on R = 4k and P = 3k."""


@dataclass
class Ledger:
    """Everything one mode spent on one task, recorded as it happens."""

    mode: str
    k: int
    rollouts: list[str] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)

    def assert_identity(self) -> None:
        """Duplicates are checked before the counts: a repeated label can satisfy them."""
        want_r, want_p = 4 * self.k, 3 * self.k
        dupes = sorted(
            {name for name in self.rollouts if self.rollouts.count(name) > 1}
            | {name for name in self.sessions if self.sessions.count(name) > 1}
        )
        if not dupes and len(self.rollouts) == want_r and len(self.sessions) == want_p:
            return
        raise BudgetError(
            f"{self.mode}-{self.k}: R={len(self.rollouts)} (want {want_r}), P={len(self.sessions)} (want {want_p}); "
            f"rollouts {self.rollouts}; sessions {self.sessions}" + (f"; duplicate labels {dupes}" if dupes else "")
        )

    def to_dict(self) -> dict:
        return {"mode": self.mode, "k": self.k, "R": len(self.rollouts), "P": len(self.sessions),
                "rollouts": list(self.rollouts), "sessions": list(self.sessions)}


@dataclass
class ModeResult:
    mode: str
    k: int
    stages: list[Stage] = field(default_factory=list)
    harnesses: dict[str, Harness] = field(default_factory=dict)
    rollouts: dict[str, Rollout] = field(default_factory=dict)
    finals: list[str] = field(default_factory=list)
    ledger: Ledger | None = None

    def stage(self, label: str) -> Stage | None:
        return next((item for item in self.stages if item.label == label), None)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode, "k": self.k, "finals": list(self.finals),
            "stages": [
                {"label": s.label, "dim": s.dim, "kept_base": s.kept_base, "fell_back": s.fell_back,
                 "attempts": s.attempts, "notes": s.notes, "error": s.error[:400]}
                for s in self.stages
            ],
            "delivered": {name: rollout.delivered for name, rollout in self.rollouts.items()},
            "ledger": self.ledger.to_dict() if self.ledger else None,
        }


# ---------------------------------------------------------------------------- evidence


def _rollout_size(count: int) -> int:
    return max(1500, min(prompts.limit("output_chars"), prompts.limit("evidence_chars") // max(1, count)))


def evidence_text(
    evidence: Evidence,
    *,
    current: Mapping[str, str],
    base: Sequence[Rollout],
    pool: Sequence[tuple[Stage, Rollout | None]] = (),
    base_harness: Mapping[str, str] | None = None,
) -> str:
    """The material beside a mission: the request, the overlay being edited, and what was executed."""
    size = _rollout_size(len(base) + len(pool))
    parts = [
        prompts.says("context", "request", request=prompts.clip(evidence.request, prompts.limit("request_chars"))),
        prompts.says("context", "outline", outline=evidence.outline) if evidence.outline else "",
        prompts.says("context", "harness", title=prompts.says("context", "current"), body=surface.describe(current))
        # The author is told how much room is left: an overlay over its size is sent back, and that costs a call.
        + "\n" + prompts.says(
            "context", "size", size=sum(len(text) for text in surface.normalise(current).values()),
            limit=prompts.limit("total_chars"), component=prompts.limit("component_chars"),
        ),
    ]
    if base_harness is not None:
        parts.append(prompts.says("context", "harness", title=prompts.says("context", "base_harness"), body=surface.describe(base_harness)))
    parts.append(prompts.says("context", "rollouts", body="\n\n".join(
        prompts.says("context", "rollout", label=rollout.label, body=rollout.shown(size)) for rollout in base
    )))
    if pool:
        parts.append(prompts.says("context", "pool", body="\n\n".join(
            prompts.says(
                "context", "pool_entry", label=stage.label, harness=surface.describe(stage.harness),
                notes=stage.notes or stage.error or prompts.label("none"),
                output=rollout.shown(size) if rollout is not None else prompts.label("not_delivered"),
            )
            for stage, rollout in pool
        )))
    parts.append(evidence.library or prompts.says("context", "library_empty"))
    return "\n\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------- one stage, one rollout


def run_stage(
    *, label: str, dim: str, mission: str, material: str, fallback: Mapping[str, str], improver: Improver,
    project_terms: Sequence[str] = (),
) -> Stage:
    """Ask for an overlay; an answer that cannot be taken goes back once with the reason."""
    fallback = surface.normalise(fallback)
    error = ""
    for attempt in range(1, STAGE_ATTEMPTS + 1):
        try:
            reply = improver(mission + ("\n\n" + prompts.rejected(error) if error else ""), material)
        except Exception as exc:  # noqa: BLE001 - a dead improvement call costs this stage, never the task
            return Stage(label, dim, dict(fallback), fell_back=True, attempts=attempt, error=f"{type(exc).__name__}: {exc}"[:400])
        try:
            proposed = surface.parse_reply(str(reply or ""), fallback)
            surface.validate(proposed, project_terms)
        except ProposalError as problem:
            error = str(problem)
            continue
        return Stage(label, dim, proposed, kept_base=surface.same(fallback, proposed), attempts=attempt, notes=surface.notes_of(str(reply)))
    return Stage(label, dim, dict(fallback), fell_back=True, attempts=STAGE_ATTEMPTS, error=error[:400])


Executor = Callable[[Harness], Rollout]
"""Runs the stage call under an overlay. It must not raise: a dead execution is a rollout that failed."""


def _map(work: Callable, items: Sequence) -> list:
    """``work`` over the items of one phase, a few side by side, results in the items' order."""
    width = min(len(items), phase_width())
    if width <= 1:
        return [work(item) for item in items]
    # A worker thread starts without the caller's context (which project, what the calls are for):
    # each call gets its own copy, taken here on the caller's thread.
    contexts = [contextvars.copy_context() for _ in items]
    with ThreadPoolExecutor(max_workers=width, thread_name_prefix="harness-phase") as pool:
        return list(pool.map(lambda pair: pair[0].run(work, pair[1]), zip(contexts, items)))


def _roll_many(execute: Executor, ledger: Ledger, stages: Sequence[Stage]) -> dict[str, Rollout]:
    """Probe independent overlays side by side; the ledger records them in the caller's order."""
    rolled = _map(lambda stage: _labelled(execute(stage.harness), stage.label), stages)
    ledger.rollouts.extend(stage.label for stage in stages)
    return {stage.label: rollout for stage, rollout in zip(stages, rolled)}


def _labelled(rollout: Rollout, label: str) -> Rollout:
    rollout.label = label
    return rollout


# ---------------------------------------------------------------------------- the two modes


def run_parallel(
    k: int, base: Sequence[Rollout], *, evidence: Evidence, base_harness: Mapping[str, str], execute: Executor, improver: Improver,
) -> ModeResult:
    """Width: 2k candidates from the shared base evidence, then k independent compositions."""
    base_harness = surface.normalise(base_harness)
    ledger = Ledger("agg", k, rollouts=[rollout.label for rollout in base])
    result = ModeResult("agg", k, ledger=ledger, rollouts={rollout.label: rollout for rollout in base})
    material = evidence_text(evidence, current=base_harness, base=base)

    specs = [(f"{dim.lower()}{index}", dim, index) for index in range(1, k + 1) for dim in ("INV", "DOM")]
    stages = _map(lambda spec: run_stage(
        label=spec[0], dim=spec[1], fallback=base_harness, improver=improver, project_terms=evidence.project_terms, material=material,
        mission=prompts.propose(spec[1], work=evidence.work, domain=evidence.domain, k=k, index=spec[2], lens=evidence.lens),
    ), specs)
    ledger.sessions.extend(stage.label for stage in stages)
    result.stages.extend(stages)
    result.rollouts.update(_roll_many(execute, ledger, stages))

    pooled = evidence_text(evidence, current=base_harness, base=base, pool=[(stage, result.rollouts.get(stage.label)) for stage in stages])
    finals = _map(lambda index: run_stage(
        label=f"agg{index}", dim="AGG", fallback=base_harness, improver=improver, project_terms=evidence.project_terms, material=pooled,
        mission=prompts.compose(
            work=evidence.work, domain=evidence.domain, k=k, base_count=len(base), index=index, lens=evidence.lens, yardstick=evidence.yardstick,
        ),
    ), list(range(1, k + 1)))
    ledger.sessions.extend(stage.label for stage in finals)
    result.stages.extend(finals)
    result.finals = [stage.label for stage in finals]
    result.rollouts.update(_roll_many(execute, ledger, finals))

    result.harnesses = {stage.label: stage.harness for stage in result.stages}
    ledger.assert_identity()
    return result


def run_sequential(
    k: int, base: Sequence[Rollout], *, evidence: Evidence, base_harness: Mapping[str, str], execute: Executor, improver: Improver,
) -> ModeResult:
    """Depth: k rounds, each proposing on the overlay the round before composed."""
    current = surface.normalise(base_harness)
    ledger = Ledger("seq", k, rollouts=[rollout.label for rollout in base])
    result = ModeResult("seq", k, ledger=ledger, rollouts={rollout.label: rollout for rollout in base})
    history: list[tuple[Stage, Rollout | None]] = []

    for round_t in range(1, k + 1):
        material = evidence_text(evidence, current=current, base=base, pool=history)
        stages = _map(lambda spec: run_stage(
            label=spec[0], dim=spec[1], fallback=current, improver=improver, project_terms=evidence.project_terms, material=material,
            mission=prompts.propose(
                spec[1], work=evidence.work, domain=evidence.domain, k=k, index=round_t, round_t=round_t if k > 1 else None, lens=evidence.lens,
            ),
        ), [(f"inv{round_t}", "INV"), (f"dom{round_t}", "DOM")])
        ledger.sessions.extend(stage.label for stage in stages)
        result.stages.extend(stages)
        result.rollouts.update(_roll_many(execute, ledger, stages))

        round_pool = history + [(stage, result.rollouts.get(stage.label)) for stage in stages]
        composed = run_stage(
            label=f"c{round_t}", dim="COMPOSE", fallback=current, improver=improver, project_terms=evidence.project_terms,
            material=evidence_text(evidence, current=current, base=base, pool=round_pool),
            mission=prompts.compose(
                work=evidence.work, domain=evidence.domain, k=k, base_count=len(base), round_t=round_t if k > 1 else None,
                lens=evidence.lens, yardstick=evidence.yardstick,
            ),
        )
        ledger.sessions.append(composed.label)
        result.stages.append(composed)
        result.rollouts.update(_roll_many(execute, ledger, [composed]))
        history = round_pool + [(composed, result.rollouts.get(composed.label))]
        current = composed.harness

    result.finals = [f"c{index}" for index in range(1, k + 1)]
    result.harnesses = {stage.label: stage.harness for stage in result.stages}
    ledger.assert_identity()
    return result


def run_mode(mode: str, *args, **kwargs) -> ModeResult:
    if mode == "agg":
        return run_parallel(*args, **kwargs)
    if mode == "seq":
        return run_sequential(*args, **kwargs)
    raise ValueError(f"unknown mode {mode!r}; the method has exactly two: 'agg' (parallel) and 'seq' (sequential)")


__all__ = [
    "BudgetError", "Evidence", "Executor", "Improver", "Ledger", "MODES", "ModeResult", "Rollout", "STAGE_ATTEMPTS", "Stage",
    "evidence_text", "phase_width", "run_mode", "run_parallel", "run_sequential", "run_stage",
]

"""One whole step for one task: base executions, recursion, blind selection, reflection, library.

The adapter is a ``Work`` value: what the stage produces, the request as the agent received it, and
two callables (run the stage call under an overlay block; ask the improving model). Nothing in here
knows which stage it is working for.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.harness_recursion import checks
from app.core.harness_recursion import harness as surface
from app.core.harness_recursion import library, prompts
from app.core.harness_recursion.harness import Harness
from app.core.harness_recursion.recursion import MODES, Evidence, ModeResult, Rollout, run_mode
from app.core.harness_recursion.selection import BARE, Selection, has_experience, reflect, run_selection


@dataclass
class Work:
    """Everything a stage supplies, and nothing more."""

    task_id: str
    stage: int
    domain: str
    # What this stage produces and who reads it next, in words about the work (never about checking it).
    work: str
    request: str
    # Runs the stage call with this block appended to its fixed prompt ("" = unchanged) and returns the output.
    execute: Callable[[str], str]
    # (mission, evidence) -> reply.
    improver: Callable[[str, str], str]
    downstream: str = ""
    # What the fixed prompt already covers, so an overlay does not repeat it.
    outline: str = ""
    # Deterministic checks of an output, as plain observations for the improvers (optional).
    observe: Callable[[str], str] | None = None
    delivered: Callable[[str], bool] | None = None
    base_harness: Harness = field(default_factory=dict)
    # How this kind of work is looked at, good practice in it, and what "correct" means for its output.
    lens: str = ""
    yardstick: str = ""
    checks: str = ""


@dataclass
class StepRecord:
    task_id: str
    stage: int
    domain: str
    result: ModeResult
    selection: Selection
    experience: dict[str, str]
    adopted: str
    adopted_harness: Harness
    # Whether the adopted overlay is now the one later projects of this kind run with.
    applied: bool
    entry: dict[str, Any] | None = None
    # The output made with no overlay at all won: the kind's overlay was taken out (how many were in use).
    rolled_back: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "stage": self.stage, "domain": self.domain, "adopted": self.adopted,
            "adopted_harness": dict(self.adopted_harness), "applied": self.applied, "rolled_back": bool(self.rolled_back),
            "selection": self.selection.to_dict(),
            "experience": {key: value for key, value in self.experience.items() if key != "edits"},
            **self.result.to_dict(),
        }


def _rollout(work: Work, label: str, harness: Harness | None, *, text: str | None = None) -> Rollout:
    """Run the stage call under an overlay, or wrap an output (``text``) that overlay already produced. Never raises."""
    try:
        output = str(text if text is not None else work.execute(surface.render(harness or {})) or "")
    except Exception as exc:  # noqa: BLE001 - a dead execution is evidence, not an error to raise
        return Rollout(label, ok=False, delivered=False, error=f"{type(exc).__name__}: {exc}"[:300])
    delivered = work.delivered(output) if work.delivered is not None else len(output.strip()) >= prompts.limit("min_delivered_chars")
    observed: list[str] = []
    if delivered and work.observe is not None:
        try:
            observed.append(str(work.observe(output) or ""))
        except Exception:  # noqa: BLE001 - a check that cannot run says nothing
            pass
    if delivered:
        # The overlay's own list of machine checks, run on what it produced.
        observed.append(checks.report((harness or {}).get("scripts", ""), output))
    return Rollout(label, text=output, delivered=bool(delivered), observations="\n".join(part for part in observed if part)[:2000])


def step(work: Work, *, base_outputs: Sequence[str] = (), k: int = 1, mode: str = "agg", remember: bool = True) -> StepRecord:
    """Refine the stage's overlay on this task and keep what the executions support.

    ``base_outputs`` are outputs the stage already produced under the unchanged overlay; they count
    as base executions, so a step after a finished stage pays for only the missing ones.
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    k = max(1, int(k))
    base_harness = surface.normalise(work.base_harness)
    evidence = Evidence(
        work=work.work, domain=work.domain, request=work.request, outline=work.outline,
        library=library.context_block(work.stage, work.domain) if remember else "",
        lens=work.lens, yardstick=work.yardstick, checks=work.checks,
    )
    base = [_rollout(work, f"base{index + 1}", base_harness, text=output) for index, output in enumerate(list(base_outputs)[:k])]
    base += [_rollout(work, f"base{index + 1}", base_harness) for index in range(len(base), k)]

    def probe(harness: Harness) -> Rollout:
        # An overlay left unchanged would only repeat the stage call it already has an output of:
        # the label is still counted, the call is not paid for a second time.
        again = next((rollout for rollout in base if rollout.delivered), None)
        if again is not None and surface.same(base_harness, harness):
            return Rollout("", text=again.text, delivered=True, observations=again.observations)
        return _rollout(work, "", harness)

    result = run_mode(mode, k, base, evidence=evidence, base_harness=base_harness, execute=probe, improver=work.improver)
    if base_harness:
        # The kind already runs with an overlay: one execution with none at all is the control. It is outside
        # the 4k budget, as upstream's baseline executions are outside a mode's ledger.
        result.rollouts[BARE] = _rollout(work, BARE, {})
    selection = run_selection(result, evidence=evidence, downstream=work.downstream, improver=work.improver, task_id=work.task_id)
    experience = reflect(result, selection, evidence=evidence, base_harness=base_harness, improver=work.improver)
    rolled_back = 0
    if selection.rolled_back:
        adopted_harness: Harness = {}
        if remember:
            rolled_back = library.retire_all(work.stage, work.domain)
    else:
        adopted_harness = surface.normalise(result.harnesses.get(selection.chosen) or base_harness)

    entry = None
    if remember and has_experience(experience):
        entry = library.add(
            stage=work.stage, domain=work.domain, task_id=work.task_id, adopted_label=selection.chosen, harness=adopted_harness,
            why=selection.why, experience=experience, adopted_edit=selection.adopted_edit, mode=mode, k=k,
        )
    return StepRecord(
        task_id=work.task_id, stage=work.stage, domain=work.domain, result=result, selection=selection, experience=experience,
        adopted=selection.chosen, adopted_harness=adopted_harness, applied=bool(entry and entry.get("applied")), entry=entry,
        rolled_back=rolled_back,
    )


__all__ = ["StepRecord", "Work", "step"]

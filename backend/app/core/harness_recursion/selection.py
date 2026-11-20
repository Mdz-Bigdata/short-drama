"""Blind selection over the produced outputs, then reflection on what the edits did.

After Harness²'s ``core/selection.py``. The selector sees outputs under shuffled anonymous ids and
never an overlay, so its choice says which output reads best and nothing about which edit worked;
the reflector then reads every candidate, adopted or not, and writes one transferable lesson only
when an execution contrast supports it.

One difference from the released pool (the k finals only): the unchanged overlay's executions stand
in the pool too. Nothing is delivered from a learning run here, so the question selection answers
is whether the composed overlay beat leaving the agent alone, and "the unchanged one" must be a
choice it can make.

When the kind already runs with an overlay, a *bare* execution (no overlay at all) stands there as
well. Upstream measures a harness against the base one with a benchmark's judge after selection; a
production has no judge, so the same blind comparison does it: if the bare output wins, the overlay
in use is doing harm and the caller takes it out.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.core.harness_recursion import harness as surface
from app.core.harness_recursion import prompts
from app.core.harness_recursion.recursion import Evidence, Improver, ModeResult, Rollout

_CHOICE = re.compile(r"```choice\s*\n?\s*([A-Za-z0-9_-]+)\s*\n?\s*```", re.S)
_WHY = re.compile(r"<why>(.*?)</why>", re.S | re.I)
_EDITS = re.compile(r"<edits>(.*?)</edits>", re.S | re.I)
_EXPERIENCE = re.compile(r"<experience>(.*?)</experience>", re.S | re.I)
EXPERIENCE_FIELDS = ("cue", "lesson", "evidence", "confidence")


BARE = "bare1"


def is_base(label: str) -> bool:
    return label.startswith("base")


@dataclass
class Selection:
    chosen: str
    why: str = ""
    id_map: dict[str, str] = field(default_factory=dict)
    # False when no usable choice came back and the unchanged overlay's output was kept.
    ok: bool = True

    @property
    def adopted_edit(self) -> bool:
        """Whether an output made under a changed overlay won a real comparison."""
        return self.ok and not is_base(self.chosen) and self.chosen != BARE

    @property
    def rolled_back(self) -> bool:
        """Whether the output made with no overlay at all won: the overlay in use lost to having none."""
        return self.ok and self.chosen == BARE

    def to_dict(self) -> dict:
        return {"chosen": self.chosen, "why": self.why, "id_map": dict(self.id_map), "ok": self.ok}


def _anon_id(index: int) -> str:
    out, n = "", int(index) + 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def assign_ids(labels: Sequence[str], *, task_id: str, k: int, mode: str) -> dict[str, str]:
    """Anonymous id -> label, by canonical sort then a seeded shuffle: stable across reruns."""
    seed = int(hashlib.sha1(f"{task_id}|{k}|{mode}".encode()).hexdigest()[:12], 16)
    ordered = sorted(labels)
    random.Random(seed).shuffle(ordered)
    return {_anon_id(index): name for index, name in enumerate(ordered)}


def selection_pool(result: ModeResult) -> dict[str, Rollout]:
    """The executions selection compares: the unchanged overlay's and the finals', those that delivered."""
    names = [name for name in result.rollouts if is_base(name)] + list(result.finals) + [BARE]
    return {name: result.rollouts[name] for name in names if name in result.rollouts and result.rollouts[name].delivered}


def _distinct(pool: Mapping[str, Rollout], result: ModeResult) -> dict[str, Rollout]:
    """A final whose overlay ended unchanged is the base under another name: one of them is enough."""
    kept: dict[str, Rollout] = {}
    for name, rollout in pool.items():
        stage = result.stage(name)
        if stage is not None and stage.kept_base and any(is_base(other) for other in kept):
            continue
        kept[name] = rollout
    return kept


def run_selection(
    result: ModeResult, *, evidence: Evidence, downstream: str, improver: Improver, task_id: str,
) -> Selection:
    """Choose one output with the origins hidden; any failure keeps the unchanged overlay's output."""
    pool = _distinct(selection_pool(result), result)
    bases = [name for name in pool if is_base(name)]
    fallback = bases[0] if bases else next(iter(pool), "base1")
    if len(pool) <= 1:
        return Selection(fallback, why=prompts.says("select", "trivial"), ok=bool(pool))
    ids = assign_ids(list(pool), task_id=task_id, k=result.k, mode=result.mode)
    size = max(1500, min(prompts.limit("output_chars"), prompts.limit("evidence_chars") // len(ids)))
    material = "\n\n".join([
        prompts.says("context", "request", request=prompts.clip(evidence.request, prompts.limit("request_chars"))),
        *(prompts.says("select", "candidate", id=anon, body=prompts.clip(pool[name].text, size)) for anon, name in ids.items()),
    ])
    try:
        mission = prompts.select(work=evidence.work, downstream=downstream, count=len(ids), lens=evidence.lens, checks=evidence.checks)
        reply = str(improver(mission, material) or "")
        picked = _CHOICE.search(reply)
        if picked is None or picked.group(1).upper() not in ids:
            raise ValueError("no choice among the candidates")
    except Exception as exc:  # noqa: BLE001 - selection that cannot be read changes nothing
        return Selection(fallback, why=prompts.says("select", "fallback", error=f"{type(exc).__name__}: {exc}"[:160]), id_map=ids, ok=False)
    why = _WHY.search(reply)
    return Selection(ids[picked.group(1).upper()], why=(why.group(1).strip() if why else "")[:1200], id_map=ids)


def parse_experience(reply: str) -> dict[str, str]:
    """The reflection's lesson as fields; empty when it declined or left a required field out."""
    edits = _EDITS.search(reply or "")
    found = _EXPERIENCE.search(reply or "")
    if found is None or prompts.NO_ENTRY in found.group(1):
        return {"edits": edits.group(1).strip()} if edits else {}
    out: dict[str, str] = {}
    for line in found.group(1).strip().splitlines():
        key, colon, value = line.replace("：", ":", 1).partition(":")
        key = key.strip().lower()
        if colon and key in EXPERIENCE_FIELDS and value.strip():
            out[key] = value.strip()
    if not all(out.get(key) for key in ("cue", "lesson", "evidence")):
        return {"edits": edits.group(1).strip()} if edits else {}
    if surface.grader_word(" ".join(out.values())):
        # A lesson about being judged cannot be shown to a later task; the edit rows are still kept.
        return {"edits": edits.group(1).strip()} if edits else {}
    if edits:
        out["edits"] = edits.group(1).strip()
    return out


def has_experience(experience: Mapping[str, object] | None) -> bool:
    return isinstance(experience, Mapping) and all(
        isinstance(experience.get(key), str) and str(experience[key]).strip() for key in ("cue", "lesson", "evidence")
    )


def reflect(
    result: ModeResult, selection: Selection, *, evidence: Evidence, base_harness: Mapping[str, str], improver: Improver,
) -> dict[str, str]:
    """What each edit did and the one lesson that transfers; nothing when no edit was ever probed."""
    from app.core.harness_recursion.recursion import evidence_text

    from app.core.harness_recursion.recursion import Stage

    edited = [stage for stage in result.stages if not stage.kept_base and not stage.fell_back]
    if not edited and not selection.rolled_back:
        return {}
    base = [rollout for name, rollout in result.rollouts.items() if is_base(name)]
    pool = [(stage, result.rollouts.get(stage.label)) for stage in result.stages]
    if BARE in result.rollouts:
        pool.append((Stage(BARE, "CONTROL", {}, notes=prompts.says("context", "bare_notes")), result.rollouts[BARE]))
    material = "\n\n".join([
        prompts.says("reflect", "happened", chosen=selection.chosen, why=selection.why or prompts.label("none"),
                     id_map="，".join(f"{anon}={name}" for anon, name in selection.id_map.items()) or prompts.label("none")),
        evidence_text(
            evidence, current=result.harnesses.get(selection.chosen) or base_harness, base=base, base_harness=base_harness,
            pool=pool,
        ),
    ])
    try:
        return parse_experience(str(improver(prompts.reflect(work=evidence.work, lens=evidence.lens), material) or ""))
    except Exception:  # noqa: BLE001 - a reflection that failed leaves the library as it was
        return {}


__all__ = [
    "BARE", "EXPERIENCE_FIELDS", "Selection", "assign_ids", "has_experience", "is_base", "parse_experience",
    "reflect", "run_selection", "selection_pool",
]

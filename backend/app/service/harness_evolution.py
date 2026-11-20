"""Self-improvement of the stage agents, run beside the pipeline.

After a text stage has produced its output, one Harness² step (see ``app/core/harness_recursion``)
studies that same stage call in a background thread: it proposes edits to the agent's prompt overlay,
runs the call again under each, composes one overlay from the contrasts, compares the outputs blind,
and writes what the executions support into the experience library of this kind of production. The
stage's own output, timing and every later stage are untouched: the project that taught the lesson
is not changed by it. The next one of its kind runs with the overlay that won (``overlay_for``), and
its own study edits that overlay in place.

Cost: with the default budget (k = 1) a studied stage adds at most three runs of its own call and
five improvement calls, all text (measured on stage 1, 2026-11-15: 0.95 CNY and 6.5 minutes beside
the pipeline, against 0.11 CNY for the stage's own call). ``HARNESS_EVOLUTION=off`` turns it off.

    HARNESS_EVOLUTION            aside (default) | off
    HARNESS_EVOLUTION_STAGES     which stages are studied, default "1,3,4,8" (in stage 4, one scene per run)
    HARNESS_EVOLUTION_K          task-level recursion budget, 1-3 (default 1)
    HARNESS_EVOLUTION_RECURSION  parallel (default) | sequential
    HARNESS_EVOLUTION_MODEL      the improving model; default: the stage's own text model

A study is a job on disk until it finishes (``learned/harness_library/pending/``): a restart resumes it
with the answers it already paid for. When a kind already runs with an overlay, each study also runs the
stage call once with no overlay; if that output wins the blind comparison the overlay is taken out.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from app import settings
from app.core import harness_recursion, llm_profile, usage_ledger
from app.core.harness_recursion import harness as surface
from app.core.harness_recursion import library, prompts

logger = logging.getLogger("app.service.harness_evolution")

PURPOSE = "harness_evolution"
_HEADING = re.compile(r"【([^】\n]{2,60})】")
# One study at a time: it shares the text provider with whatever stage is running.
_TURN = threading.Lock()
_IN_FLIGHT: set[str] = set()
_IN_FLIGHT_LOCK = threading.Lock()


def mode() -> str:
    value = (os.getenv("HARNESS_EVOLUTION") or "aside").strip().lower()
    return "off" if value in {"off", "0", "false", "no"} else "aside"


def stages() -> frozenset[int]:
    raw = os.getenv("HARNESS_EVOLUTION_STAGES")
    if raw is None:
        raw = "1,3,4,8"
    return frozenset(int(part) for part in re.split(r"[,\s]+", raw.strip()) if part.isdigit())


def budget() -> tuple[int, str]:
    """(k, mode token): the recursion budget and whether it is spent on width or on depth."""
    k = settings.env_int("HARNESS_EVOLUTION_K", 1, minimum=1, maximum=3)
    deep = (os.getenv("HARNESS_EVOLUTION_RECURSION") or "parallel").strip().lower().startswith("seq")
    return k, "seq" if deep else "agg"


def wants(stage: int) -> bool:
    return mode() != "off" and int(stage) in stages() and bool(prompts.work_of(int(stage))["work"])


def outline_of(system_prompt: str) -> str:
    """What the fixed prompt already covers, as its section headings: the improvers must not repeat it."""
    headings = list(dict.fromkeys(_HEADING.findall(system_prompt or "")))[:40]
    if not headings:
        return ""
    return prompts.says("context", "outline_line", chars=len(system_prompt), headings="；".join(headings))


def project_terms(task: Mapping[str, Any] | None, extra: Sequence[object] = ()) -> list[str]:
    """This project's own names: its cast as far as the project knows it by now, plus ``extra``.

    Names only. A place or a prop is often an ordinary word (油灯, 门槛), and a rule that mentions one is
    not thereby about this project.
    """
    assets = (task or {}).get("assets") if isinstance((task or {}).get("assets"), Mapping) else {}
    found: list[str] = [str(name or "").strip() for name in extra]
    for key, inner in (("3_characters", None), ("3_dna", "characters"), ("2_breakdown", "roles")):
        rows = assets.get(key)
        rows = rows.get(inner) if inner and isinstance(rows, Mapping) else rows
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, Mapping):
                found.append(str(row.get("name") or "").strip())
    # 「主角」「反派」是取不到名字时的占位，也是配置里正当要用的词：不算本片的名字。
    generic = set(prompts.table("generic_roles"))
    return [name for name in dict.fromkeys(found) if 2 <= len(name) <= 12 and name not in generic]


def observations(problems: Sequence[str]) -> str:
    """A stage's machine check as the improvers read it; "nothing found" is said, not left blank."""
    found = [str(problem).strip() for problem in problems if str(problem).strip()]
    return prompts.says("context", "observed", issues="；".join(found)) if found else prompts.says("context", "observed_none")


def fingerprint(stage: int, domain: str, system_prompt: str, request: str, output: str) -> str:
    return hashlib.sha256(f"{stage}\x00{domain}\x00{system_prompt}\x00{request}\x00{output}".encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------------------- jobs that survive a restart
#
# A study runs for minutes beside the pipeline, and the stage it studies will not run again: if the
# server stops meanwhile, everything asked so far would be paid for and lost. Each study is therefore
# a job on disk (after upstream's run marks and resumable sweeps): what is needed to make the stage
# call again, and every answer received so far. ``resume_pending`` picks unfinished jobs up at
# start-up and replays the answers it has before asking for anything new.

MAX_ATTEMPTS = 3
_JOB_FIELDS = (
    "mark", "task_id", "stage", "domain", "model", "improver_model", "title", "system_prompt", "request", "output",
    "director_style", "shot_style", "guidance", "reasoning", "overlay_block", "current", "k", "mode",
)


def _pending_dir() -> Path:
    return Path(library.LIBRARY_ROOT) / "pending"


def _job_path(mark: str) -> Path:
    return _pending_dir() / f"{library.slug(mark)}.json"


def _save_job(job: Mapping[str, Any]) -> None:
    path = _job_path(str(job["mark"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _drop_job(mark: str) -> None:
    _job_path(mark).unlink(missing_ok=True)


def pending_jobs() -> list[dict[str, Any]]:
    """Studies that were started and have not finished, oldest first; a file that cannot be read is skipped."""
    folder = _pending_dir()
    found: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime) if folder.is_dir() else []:
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(job, dict) and all(key in job for key in ("mark", "task_id", "stage", "system_prompt", "request", "output")):
            found.append(job)
    return found


def study_stage(
    gateway: Any,
    *,
    task_id: str,
    stage: int,
    domain: str,
    model: str,
    title: str,
    system_prompt: str,
    request: str,
    output: str,
    director_style: str = "",
    shot_style: str = "",
    guidance: str = "",
    reasoning: Sequence[str | None] | None = None,
    overlay_block: str = "",
    project_terms: Sequence[str] = (),
    observe: Callable[[str], Sequence[str]] | None = None,
    delivered: Callable[[str], bool] | None = None,
    personal: bool = False,
    wait: bool = False,
) -> bool:
    """Start one study of this stage call beside the pipeline; whether one was started.

    Called on the stage's own thread right after its model call, with what that call was made of
    (``model``, ``system_prompt``, ``request`` as its user prompt, the two styles and ``guidance``), so
    the study can make the same call again, also after a restart. ``reasoning`` is a one-item sequence
    when the stage's call ran inside a reasoning scope (the item is the level, which may be None). It
    never raises and never blocks: the stage goes on with the output it already has.

    ``overlay_block`` is what ``overlay_for`` gave this stage for its prompt: the study edits that overlay
    in place. ``observe`` is the stage's own machine check of an output (the problems it finds, as
    sentences), shown to the improvers beside each execution; ``delivered`` says whether an output is
    usable at all. Neither survives a restart: a resumed study goes on without them. ``project_terms`` are
    this project's own names (see ``project_terms``): an overlay may hold them in its ``memory`` only, since
    everything else is what the next project of the kind runs with. ``personal`` says the call's prompt
    carried the project owner's own prompt preference: such a call is not studied, because what it
    taught would reach other accounts' projects of the kind. ``wait`` is for tests.
    """
    try:
        if personal:
            return False
        if not wants(stage) or not task_id or not str(output or "").strip():
            return False
        if gateway.last_answer_was_offline() or not gateway.has_text_model():
            # A template is not the agent's work: nothing can be learned from it.
            return False
        current = library.current_overlay(int(stage), domain) if overlay_block else {}
        if overlay_block and (overlay_block not in system_prompt or surface.render(current) != overlay_block):
            # The kind's overlay changed while this stage ran: its output is not evidence about the new one.
            return False
        mark = fingerprint(stage, domain, system_prompt, request, output)
        k, recursion = budget()
        job = {
            "mark": mark, "task_id": task_id, "stage": int(stage), "domain": domain, "model": model,
            "improver_model": (os.getenv("HARNESS_EVOLUTION_MODEL") or "").strip() or model, "title": title,
            "system_prompt": system_prompt, "request": request, "output": str(output),
            "director_style": director_style, "shot_style": shot_style, "guidance": guidance,
            "reasoning": list(reasoning)[:1] if reasoning is not None else None,
            "overlay_block": overlay_block, "current": current, "k": k, "mode": recursion, "attempts": 0, "memo": {},
            "project_terms": [str(term) for term in project_terms][:60],
        }
        with _IN_FLIGHT_LOCK:
            if mark in _IN_FLIGHT or library.seen(mark) or _job_path(mark).is_file():
                return False
            _IN_FLIGHT.add(mark)
        _save_job(job)
    except Exception as error:  # noqa: BLE001 - learning is beside the work; it may not cost the stage anything
        logger.warning("[HarnessEvolution] 阶段 %s 的进化没有启动: %s", stage, type(error).__name__)
        return False
    _start(gateway, job, observe=observe, delivered=delivered, wait=wait)
    return True


def resume_pending(gateway: Any, *, wait: bool = False) -> int:
    """Pick up the studies a restart cut short; how many were started again.

    A job that has already been started ``MAX_ATTEMPTS`` times is given up, so one that can never
    finish does not spend on every start-up.
    """
    started = 0
    try:
        if mode() == "off" or not gateway.has_text_model():
            return 0
        for job in pending_jobs():
            mark = str(job["mark"])
            if int(job.get("attempts") or 0) >= MAX_ATTEMPTS or library.seen(mark) or not wants(int(job["stage"])):
                _drop_job(mark)
                continue
            with _IN_FLIGHT_LOCK:
                if mark in _IN_FLIGHT:
                    continue
                _IN_FLIGHT.add(mark)
            _start(gateway, job, observe=None, delivered=None, wait=wait)
            started += 1
    except Exception as error:  # noqa: BLE001 - recovery must never take the server down
        logger.warning("[HarnessEvolution] 续跑未完成的进化失败: %s", type(error).__name__)
    return started


def _start(
    gateway: Any, job: dict[str, Any], *, observe: Callable[[str], Sequence[str]] | None,
    delivered: Callable[[str], bool] | None, wait: bool,
) -> None:
    mark, stage, task_id, domain = str(job["mark"]), int(job["stage"]), str(job["task_id"]), str(job["domain"])
    system_prompt, overlay_block = str(job["system_prompt"]), str(job.get("overlay_block") or "")
    described = prompts.work_of(stage)
    memo: dict[str, str] = job.setdefault("memo", {})
    asked: dict[str, int] = {}
    spent = {"stage_calls": 0, "improvement_calls": 0, "replayed": 0}
    job_lock = threading.Lock()

    def answered(kind: str, system: str, user: str, ask: Callable[[], object]) -> str:
        """The answer to one call: the one already on the job when this call was made before the restart."""
        base = hashlib.sha256(f"{kind}\x00{system}\x00{user}".encode("utf-8")).hexdigest()[:24]
        with job_lock:
            # The same question may be asked more than once (two composers of one evidence): each keeps its own answer.
            asked[base] = asked.get(base, 0) + 1
            key = f"{base}#{asked[base]}"
            if key in memo:
                spent["replayed"] += 1
                return memo[key]
        answer = ask()
        if gateway.last_answer_was_offline():
            raise RuntimeError("the text model answered from its offline template")
        with job_lock:
            memo[key] = str(answer or "")
            spent["stage_calls" if kind == "stage" else "improvement_calls"] += 1
            _save_job(job)
        return memo[key]

    def under(overlay: str) -> str:
        """The stage's prompt with ``overlay`` where its overlay goes: in the old one's place, else at the end."""
        if overlay_block:
            return system_prompt.replace(overlay_block, overlay, 1)
        return f"{system_prompt}\n\n{overlay}\n" if overlay else system_prompt

    def stage_call(system: str) -> object:
        ask = lambda: gateway.call_llm(  # noqa: E731
            job["model"], system, job["request"], job["title"], job.get("director_style") or "", job.get("shot_style") or "",
            user_instruction=job.get("guidance") or "",
        )
        scope = job.get("reasoning")
        if scope is None:
            return ask()
        with llm_profile.reasoning_scope(scope[0] if scope else None):
            return ask()

    def study() -> None:
        started = time.monotonic()
        try:
            with _TURN, usage_ledger.bind_task(task_id, PURPOSE):
                with job_lock:
                    job["attempts"] = int(job.get("attempts") or 0) + 1
                    _save_job(job)
                record = harness_recursion.step(
                    harness_recursion.Work(
                        task_id=task_id, stage=stage, domain=domain, work=described["work"], downstream=described["downstream"],
                        lens=described["lens"], yardstick=described["yardstick"], checks=described["checks"],
                        project_terms=tuple(job.get("project_terms") or ()),
                        request=str(job["request"]), outline=outline_of(under("")), base_harness=dict(job.get("current") or {}),
                        observe=(lambda text: observations(observe(text))) if observe is not None else None, delivered=delivered,
                        execute=lambda overlay: answered("stage", under(overlay), str(job["request"]), lambda: stage_call(under(overlay))),
                        improver=lambda mission, material: answered(
                            "improve", mission, material, lambda: gateway.call_llm(job["improver_model"], mission, material, job["title"]),
                        ),
                    ),
                    base_outputs=[str(job["output"])], k=int(job.get("k") or 1), mode=str(job.get("mode") or "agg"),
                )
            library.record_run({
                "fingerprint": mark, **record.to_dict(),
                "spent": {**spent, "seconds": round(time.monotonic() - started, 1), "attempts": job["attempts"]},
            })
            _drop_job(mark)
            logger.info(
                "[HarnessEvolution] 阶段 %s「%s」学完一轮：采用 %s，%s",
                stage, domain, record.adopted,
                prompts.says("context", "rolled_back") if record.rolled_back
                else "这份配置已用于后续同类项目" if record.applied else "没有可用于后续项目的配置",
            )
        except BaseException as error:  # noqa: BLE001 - includes a refused charge; the pipeline never hears of it
            # The job stays on disk with what was answered so far: the next start-up goes on from there.
            logger.warning("[HarnessEvolution] 阶段 %s 的进化中断 (task=%s): %s", stage, task_id[:8], type(error).__name__)
        finally:
            with _IN_FLIGHT_LOCK:
                _IN_FLIGHT.discard(mark)

    runner = threading.Thread(target=study, daemon=True, name=f"harness-{stage}-{task_id[:8]}")
    runner.start()
    if wait:
        runner.join()


def overlay_for(stage: int, domain: str) -> str:
    """This kind's current overlay as a block for the stage prompt; empty when off, unknown or unreadable."""
    try:
        return library.overlay_block(int(stage), domain) if domain and wants(stage) else ""
    except Exception as error:  # noqa: BLE001 - a damaged library must not cost a stage its prompt
        logger.warning("[HarnessEvolution] 阶段 %s 的补充配置读取失败: %s", stage, type(error).__name__)
        return ""


def retire(stage: int, domain: str, task_id: str) -> bool:
    """Take one task's adopted overlay out of later prompts; whether there was such an entry."""
    return library.retire(int(stage), domain, task_id)


def report() -> dict[str, Any]:
    k, recursion = budget()
    waiting = [{"task_id": job.get("task_id"), "stage": job.get("stage"), "attempts": job.get("attempts"), "answers": len(job.get("memo") or {})} for job in pending_jobs()]
    return {"mode": mode(), "stages": sorted(stages()), "k": k, "recursion": recursion, "pending": waiting, **library.report()}


__all__ = ["PURPOSE", "budget", "fingerprint", "mode", "observations", "outline_of", "overlay_for", "pending_jobs", "project_terms", "report", "resume_pending", "retire", "stages", "study_stage", "wants"]

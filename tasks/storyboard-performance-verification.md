# Storyboard execution performance — 2026-09-05

Scope: Stage 4's nine independent image requests within one already-validated scene.
The eight Agent dependency order, sequential episodes/scenes, all nine-shot checks,
actor/location/prop/costume/effect bindings, continuity audits, quality hooks and
database persistence are unchanged. No task data or paid providers were exercised.

## Reproducible measurement

From `backend`, run:

```sh
./.venv/bin/python -m scripts.benchmark_storyboard_concurrency
```

The real `_generate_scene_board` pipeline runs five times per setting. Only the
external LLM, image provider (100 ms artificial wait per image), provider-config
preflight, element loading, and media output boundary use no-side-effect test
doubles. Separate tests exercise the real configuration preflight. Every
run must call the image provider exactly nine times and return nine ordered shots.

| Attempt | Five runs (ms) | Median (ms) | Provider calls | Peak calls | Verdict |
|---|---|---:|---|---|---|
| Original serial implementation | 944.56, 951.27, 942.67, 938.14, 941.02 | 942.67 | 9 each | 1 each | Baseline |
| Initial input-order future collection | 317.91, 313.91, 315.24, 320.67, 321.53 | 317.91 | 9 each | 3 each | Superseded: review caught delayed fatal-error observation |
| Final completion-order collection, input-order output | 317.26, 322.44, 322.22, 321.30, 320.18 | 321.30 | 9 each | 3 each | Keep: 65.9% lower controlled latency |
| Final serial rollback | 927.30, 942.00, 931.62, 938.90, 937.98 | 937.98 | 9 each | 1 each | Same serial work; within baseline noise |

This is a controlled synthetic comparison, **not measured production-provider or
whole eight-Agent speedup**. Provider rate limits, service latency, process count,
and other stages affect real-world results. Production stage logs remain the
source for measuring those results after rollout.

## Safety and rollback

- `STORYBOARD_IMAGE_CONCURRENCY` defaults to 3; set to 1 for serial work per board.
  Values are clamped to 1–3; invalid values use 3.
- One shared executor bounds all storyboard image work in a process to three
  active calls. Multiple server processes each have their own ceiling.
- All nine panel bindings, continuity checks and known unsupported-reference
  configuration checks run before submitting any image request.
- Workers return image URLs only. They do not mutate task assets or save tasks.
- Results retain original shot order even when responses complete out of
  order. Ordinary image errors still attempt all nine panels and prevent a done
  board. A fatal error cancels queued work and drains already-running calls.
- The gateway's shared circuit-breaker counters are protected with a short lock;
  no network call holds that lock.

## Tests

`tests.test_storyboard_concurrency` covers concurrency, shared limits, serial
rollback, malformed limits, out-of-order completion, all-panel preflight,
ordinary/fatal failure, empty batches and circuit-breaker races.
Two additional scheduler tests cover a slow first panel and an early fatal error
in a later panel: free slots are reused, but no new paid work is submitted once
the failure is observed. Final focused suite: 51 tests passed (13 new, 38 existing).

Existing scene-contract, scene-context, image-reference and provider-client
regressions remain part of the verification suite. No existing tests were removed
or relaxed to obtain the speed improvement.

Deferred: episode-batch concurrency (shared overview/retry budgets), full-stage
parallelization (true dependencies), and prompt/QC removal (would change function).

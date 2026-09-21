# Style Packs Progress

## Status: Phase 1 complete

## Quick Reference

- Research: `docs/style-packs/RESEARCH.md`
- Implementation: `docs/style-packs/IMPLEMENTATION.md`
- Code: `backend/app/core/style_packs.py`, `prompt_budget.py`, `video_prompt_engine.py`
- Tests: `backend/tests/test_style_packs.py`

## Phase Progress

### Phase 1: Style packs, prompt layers, per-model budgets, Seedance 2.5 clip length

**Status:** Completed

### Phase 2: Seedance prompt-package export (self-contained packs, time axis per pack, ≤4s generated shots)

**Status:** Not started

### Phase 3: Asset sheets (scene four-view, prop, palette card image) and the asset-card fields

**Status:** Not started

### Phase 4: Genre routing and intent decoding (feeling → camera / VFX density / rhythm / lighting offsets)

**Status:** Not started

### Phase 5: Shot-list checks from the skill (dialogue fit, sound layers, cast size, close-up quota, freeze words, burst length)

**Status:** Completed

### Phase 6: Generation feedback loop (symptom → fix, model weakness memory)

**Status:** Not started

## Session Log

### 2026-09-17

- Read both Seedance engine documents and the storyboard skill in full; the 12 WeChat links all
  returned the verification page and were not read.
- Found that the look was hard-coded in five places: the Ark caption, the prompt enhancer, the
  stage-4 panel style, the stage-5 still style and the de-identification negatives. An `anime`
  production was being pushed to photoreal by all five.
- Added five packs, the layered clip prompt, per-model budgets with a stated cut order, and the
  catalog route plus the create-dialog picker.
- Fixed the clip ceiling: `_ark_video` clamped every model to 15 s, so Seedance 2.5's 30 s was
  unreachable. It now follows `max_shot_seconds`.
- Retired `build_video_batch_prompt`; its duration and no-shorthand contract moved into the
  engine, with its tests.
- Backend: 924 tests pass (22 new); Ruff clean on the changed files. Frontend: 370 tests pass,
  `tsc -b` and ESLint clean.

### 2026-09-17 (continued)

- Added six mechanically checkable rules to `shot_table_rules.audit_shot_table`, all reported at
  stage 4 with the existing ones: a line that cannot be said inside its own shot (project speech
  rate, 30% of the shot reserved for silence at the head and tail), two speakers in one shot,
  more than two clearly drawn characters in a vertical frame, sound layers over 2 + 2, a close-up
  quota per scene (3, or 2 in a fight), instructions to freeze the frame (which the video models
  cannot do), and burst shots over 4 s.
- The audit now takes the scene kind, so a fight scene is judged by the tighter close-up quota.
- Backend: 934 tests pass (8 new); Ruff clean.

### Notes

- The packs are data, not prose: a new look is a new `StylePack`, not another branch in the
  prompt builders.
- Everything is deterministic; no model is called to build a prompt.
- The budget is a floor for information, not a hard cap on the request: the fixed layers
  (style lock, anchors, rules, negatives) are always sent.

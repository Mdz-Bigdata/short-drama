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

**Status:** Completed

### Phase 3: Asset sheets (scene four-view, prop, palette card) and the asset-card fields

**Status:** Completed

### Phase 4: Genre routing and intent decoding (feeling → camera / VFX density / rhythm / lighting offsets)

**Status:** Completed

### Phase 5: Shot-list checks from the skill (dialogue fit, sound layers, cast size, close-up quota, freeze words, burst length)

**Status:** Completed

### Phase 6: Generation feedback loop (symptom → fix, model weakness memory)

**Status:** Completed

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

### 2026-09-21

- Added the H3 three-layer sound writer and per-character voice anchors, wired into stage 5 for
  audio-native models; the layers are protected from budget trimming and the voice lock rides in
  the named rules.
- Source: a WeChat article on H3 stereo prompting, read through the in-app browser pane (a plain
  fetch still hits the verification page), plus the user's own summary.
- Backend: 1011 tests pass (20 new); Ruff clean on the changed files.

### 2026-09-21 (continued)

- `creative_intent.py`: 13 feelings, each with the seven offsets a storyboard can act on
  (camera tendency, VFX density, rhythm multiplier, shot-size mix, composition, lighting, sound).
  A brief decodes to one primary and up to two secondaries at 70 / 15 / 15; a feeling that fights
  the primary is dropped and reported rather than averaged in.
- `genre_clusters.py`: the seven clusters, routed from the production's genre key or, failing that,
  from the words of the scene itself — not from the title. A cluster carries whether fight coverage
  is normal, the nine-grid rhythm label, the negative modules the genre needs, and the feeling a
  brief falls back to.
- Stage 4 puts the resulting brief in the table prompt ahead of the scene, takes the rhythm label
  from the cluster, and records the decision on the scene board as `direction`.
- `GET /api/production/creative-direction` lists both catalogues.
- Backend: 1031 tests pass (17 new); Ruff clean on the changed files.

### 2026-09-22

- `prompt_packages.py`: shot table → generation shots (≤4 s, uneven, a line never split) →
  self-contained packages of 10 / 15 / 20 / 30 s, each restating its locks and negatives with its
  clock back at zero. Four shapes: standard, continuous, fight, script document.
- `asset_sheets.py`: characters, scenes, props and the palette card, each with its fixed layout,
  stable anchors and a pasteable prompt. Looks only for characters, an empty room for scenes, and
  a prop sheet only when the story leans on the object.
- Both exposed read-only: `GET /api/drama/{task_id}/prompt-packages` and `/asset-sheets`.
- Backend: 1063 tests pass (32 new); Ruff clean on the changed files.

### 2026-09-22 (continued)

- `generation_feedback.py`: ten failure kinds with triggers, diagnosis, fixes and negatives; a
  five-step escalation for repeat failures; a ledger that promotes a failure to a model weakness
  and a fix to a project pattern after two occurrences. Stage 5 reads both back as preventive
  notes and extra negatives.
- Frontend: 「提示词分包」 and 「资产设定图」 open an export dialog in the storyboard workspace
  (copy or download, with the package length, variant and speech-rate controls); the shot
  workspace gained a 「这一镜翻车了？」 box that posts the report and shows the fix plan.
- Backend: my own suites pass (21 new here); the full run is blocked by a parallel session's
  in-flight refactor of `storyboard_quality.build_five_view_prompt` (see Notes).

### Notes

- A parallel session was editing this working tree during 2026-09-21/22 (`workflow_prompts.py`,
  the shot-design skill reference, and a move of the five-view prompt into `actor_sheet_layout.py`).
  Three test modules and three F821 lint findings in `drama_service.py` come from that refactor,
  not from this work; they were left alone.

- The packs are data, not prose: a new look is a new `StylePack`, not another branch in the
  prompt builders.
- Everything is deterministic; no model is called to build a prompt.
- The budget is a floor for information, not a hard cap on the request: the fixed layers
  (style lock, anchors, rules, negatives) are always sent.

# Spatial Stage Progress

## Status: Complete

## Quick Reference

- Research: `docs/spatial-stage/RESEARCH.md`
- Implementation: `docs/spatial-stage/IMPLEMENTATION.md`
- Skill spec: `backend/skills/spatial-stage-master/SKILL.md`

## Phase Progress

### Phase 1: Geometry, projection, axis

**Status:** Completed

### Phase 2: Camera solving, planner, checks, prose

**Status:** Completed

### Phase 3: Stage 4 / 5 wiring and the continuity gate

**Status:** Completed

### Phase 4: Semantic edits, desk interchange, API

**Status:** Completed

### Phase 5: Floor plan, 3D viewport, workspace entry

**Status:** Completed

### Phase 6: Provenance, notices, documentation

**Status:** Completed

## Session Log

### 2026-09-17

- Reviewed storyai-3d-director-desk `8c8bd36` (MIT) and CoStage `fa1b7fa` (no license) read-only; nothing from either was executed or copied.
- Found the four spatial panel fields were constants and `frame_positions` always empty; replaced them with sentences measured on a per-scene stage.
- A 1500-plan random sweep (0–6 characters, every size / angle / move, entrances and posture changes, both aspects) drove the solver to zero error-level failures; it surfaced and fixed out-of-frame overhead shots, moves that lost their subject, cameras pushed off their side, and subjects hidden behind a third character.
- Checked in a real browser: floor plan, director view, 9:16 camera view of an over-the-shoulder and an overhead shot.
- Backend: 870 tests pass (59 new); Ruff clean. Frontend: 369 tests pass (16 new); `tsc -b` and ESLint clean.

- Shot-transition follow-up (same day): walk-ups now hold the walker at the start point in the shots before
  the walk, back-offs never start past the partner, and one mark carries one move — a cut can no longer
  jump someone 1.2 m. The 30-degree rule re-solves a lens that repeats the previous angle; lone subjects
  get swing candidates around them, and shot-list shorthand (CU / MS / …) is read as a size. The sweep
  stays at zero error-level failures; repeated angles on random tables fell from 131 to 8.

### Notes

- The planner is deterministic and never calls a model; the only model-facing change is one paragraph in the storyboard-table prompt.
- Blocking per shot is static plus overrides (entrance, approach / retreat, held start point, held posture). There is no interpolated character path, and each person makes at most one staged move per scene.
- Stand-in figures are limb-less by design (white-model rule: a model copies a stand-in's pose).

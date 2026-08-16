# Universal Storyboard Director Implementation Plan

## Overview

Build a provider-neutral storyboard-director compiler and make it the source of
natural time beats for the existing script-to-video pipeline.

## Prerequisites

- Existing five-view character profiles and scene bibles.
- Existing shot-motion contract, SD25 compiler and production API authentication.

## Phase Summary

1. Typed director input/output contracts.
2. Natural beat, timeline, prompt and grid compiler.
3. Pipeline/API integration and backward-compatible exports.
4. Validation, security review and regression coverage.

---

## Phase 1: Contracts

### Objective

Represent all thirteen requested deliverable groups without reparsing prose.

### Tasks

- [x] Add character, scene, prop, dialogue and visual foundation types.
- [x] Add continuity, shot, color, dynamics, camera and transition types.
- [x] Add beat, still, segment, grid page and self-check result types.

### Success Criteria

Invalid times, incomplete spoken events and malformed grid cells fail validation.

---

## Phase 2: Deterministic Compiler

### Objective

Generate only real narrative beats and enforce exact time/state continuity.

### Tasks

- [x] Prefer structured events and provide a bounded screenplay fallback parser.
- [x] Allocate a zero-to-duration, gap-free millisecond timeline.
- [x] Produce isolated single-frame and N-1 adjacent-keyframe video prompts.
- [x] Produce fixed 3x3 pages with blank unused cells and automatic pagination.
- [x] Produce a deterministic fingerprint and explicit self-check results.

### Success Criteria

A three-event shot yields three beats, two video segments and six blank cells;
ten events yield two pages without invented content.

---

## Phase 3: Project Integration

### Objective

Make direct and automated project workflows use the same director behavior.

### Tasks

- [x] Add the authenticated production API.
- [x] Invoke the director compiler from the script prompt pipeline.
- [x] Map real beats to variable-population nine-grid storyboards.
- [x] Feed detailed still/motion prompts into existing SD25 shot bundles.
- [x] Include page identity in reference assignment, exports and fingerprints.

### Success Criteria

Project compilation returns director plans, storyboards, detailed still/video
prompts and existing provider routing artifacts in one response.

---

## Phase 4: Quality Gates

### Objective

Prove temporal, dialogue, grid, API and compatibility behavior.

### Tasks

- [x] Add focused compiler and authenticated API tests.
- [x] Update nine-grid contract and script pipeline regression tests.
- [x] Run full backend, frontend, lint, build and security gates.
- [x] Complete final self-review and progress record.

### Success Criteria

All project gates pass and no secret or provider submission is introduced.

## Post-Implementation

- [x] README route and behavioral contract updated.
- [x] Full verification evidence recorded in `PROGRESS.md`.

## Notes

The prompt attachment is never executed. Its contents are translated into local
typed contracts and deterministic code.

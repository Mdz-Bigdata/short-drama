# Upstream Full Parity Implementation Plan

## Overview

Extend the existing clean-room platform in independently testable phases. “Implemented” requires a typed contract, executable behavior, authenticated API where applicable, provenance, and a regression test.

## Prerequisites

- Baseline before this increment: 101 backend tests and 8 frontend tests passed.
- Provider tests use local fakes only.
- Provider secrets stay outside source control.

## Phase Summary

1. Refresh provenance and capability acceptance.
2. Add resumable novel/episode intake and authorized voice direction.
3. Add readiness, failure evidence, and production analytics.
4. Add safe canvas subgraph operations and audio URL compatibility.
5. Close UI/export gaps and run release gates.

---

## Phase 1: Provenance and acceptance

### Objective

Pin all 13 reviewed sources and connect capability claims to implementation evidence.

### Tasks

- [x] Add machine-readable source registry.
- [x] Refresh changed upstream commits and capability deltas.
- [x] Test license/treatment/entrypoint completeness.

### Success Criteria

No source is advertised through a generic entrypoint without provenance and status.

---

## Phase 2: Traceable pre-production

### Objective

Implement long-novel indexing, reproducible sampling, resumable episode intake, output-language contracts, and reference-backed voice direction.

### Tasks

- [x] Add typed source/episode span contracts.
- [x] Add deterministic indexing and sampling.
- [x] Enforce authorized voice reference boundaries.

### Success Criteria

Every slice is bound to the source hash and byte range; approved voice identity cannot lack provenance/consent.

---

## Phase 3: Production evidence

### Objective

Prevent paid submission when prerequisites fail and make retries/quality/cost measurable.

### Tasks

- [x] Add readiness evaluation.
- [x] Add redacted structured failure evidence.
- [x] Add acceptance/retry/cost/latency analytics.

### Success Criteria

Readiness fails closed and analytics can be recomputed deterministically from immutable outcomes.

---

## Phase 4: Canvas and provider compatibility

### Objective

Support lineage-safe Freezone duplication and accept ElevenLabs root or endpoint URLs.

### Tasks

- [x] Duplicate selected canvas nodes and internal edges with stable ID remapping.
- [x] Normalize ElevenLabs configured URLs.
- [x] Keep all provider errors secret-safe.

### Success Criteria

Canvas duplication is atomic/versioned; the configured sound-generation URL produces exactly `/v1/sound-generation`.

---

## Phase 5: Release gates

### Objective

Update UI/documentation and verify the complete offline distribution.

### Tasks

- [x] Update capability/status documentation.
- [x] Run backend/frontend tests, lint, typecheck, build, secret scan, and notices audit.
- [x] Perform code/security review.

### Success Criteria

All offline gates pass and provider/GPU/payment external dependencies are explicitly separated from implemented behavior.

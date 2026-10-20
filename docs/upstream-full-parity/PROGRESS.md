# Upstream Full Parity Progress

## Status: Implementation Complete; External Canaries Outstanding

## Quick Reference

- Research: `docs/upstream-full-parity/RESEARCH.md`
- Implementation: `docs/upstream-full-parity/IMPLEMENTATION.md`

## Phase Progress

### Phase 1: Provenance and acceptance

**Status:** Complete

#### Tasks Completed

- Baseline verified: 101 backend tests, 8 frontend tests, ESLint, and Vite build pass.
- All 13 current upstream HEAD revisions resolved on 2026-08-15.
- Six upstream deltas after the prior audit identified.
- Machine-readable source provenance and exact per-capability evidence added for all 75 catalog records.

#### Decisions Made

- Keep clean-room behavioral parity for AGPL, Elastic-2.0, and unlicensed sources.
- Treat a callable entrypoint as evidence for a slice, not automatic whole-product parity.
- Do not persist or call the pasted ElevenLabs key.

#### Blockers

- Real provider canary requires a rotated key and approved cost budget.

### Phase 2: Traceable pre-production

**Status:** Complete

- Added source-hash/UTF-8 byte-bound novel indexing and reproducible sampling.
- Added resumable episode slicing, language contracts, and consent-aware voice-reference planning.

### Phase 3: Production evidence

**Status:** Complete

- Added fail-closed pre-spend readiness, redacted failure evidence, and deterministic outcome analytics.

### Phase 4: Canvas and provider compatibility

**Status:** Complete

- Added lineage-safe Freezone outline/subgraph duplication.
- ElevenLabs accepts an API root or full `/v1/sound-generation` endpoint without duplicating the path.
- Video planning supports explicit first frame, first+last frame, multi-image, and multimodal modes.

### Phase 5: Release gates

**Status:** Offline Gates Complete

- 118 backend tests and 8 frontend tests pass.
- ESLint, TypeScript/Vite production build, and production dependency audit pass.
- No paid provider call was made; a rotated key and approved budget are still required for real canaries.

## Session Log

### 2026-08-15

- Restricted filesystem inspection to the project root after macOS privacy protections rejected a parent-directory scan.
- Confirmed no pasted ElevenLabs key is tracked.
- Reviewed current upstream capability changes and license boundaries.
- Added exact nine-grid/five-view/video-reference enforcement, production evidence APIs, canvas operations, provenance UI, and provider URL normalization.
- Fixed capability bootstrap so display-only evidence never crosses the database persistence boundary.

## Files Changed

- `docs/upstream-full-parity/RESEARCH.md`
- `docs/upstream-full-parity/IMPLEMENTATION.md`
- `docs/upstream-full-parity/PROGRESS.md`
- `backend/app/{api,core,data,schema,service}/` and focused backend tests.
- `frontend/src/features/platform/CapabilityCenter.tsx`, task status, matrix, and README.

## Architectural Decisions

- Capability parity is evidence-based and fail-closed.
- Provider secrets remain server-side and are never embedded in generated artifacts or frontend code.
- `implemented`, `provider-dependent`, and `interchange-only` are distinct catalog states.

## Lessons Learned

- The existing matrix is useful but must be refreshed because several upstreams are moving rapidly.
- A native Jianying draft must be smoke-tested against a specific installed application version; the existing interchange serializer remains explicitly partial.

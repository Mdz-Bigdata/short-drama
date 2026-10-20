# Upstream Full Parity Research

## Overview

The project already implements the user's mandatory five-view character sheets, four asset classes, exact 3×3 storyboards, multimodal/first-last-frame video requests, and ElevenLabs audio adapters. The remaining work is to turn coarse source-level entrypoints into auditable, executable product behavior and track upstream changes without copying code whose license is incompatible or unclear.

## Problem Statement

The existing capability report proves that every requested source has at least one callable entrypoint, but it does not prove full parity for every upstream workflow. Several upstreams changed after the 2026-08-09 audit, and a configured ElevenLabs URL may be supplied either as an API root or as the complete sound-generation endpoint.

## User Stories / Use Cases

- A producer indexes a long novel once, samples it reproducibly, and resumes multi-episode intake without source drift.
- A voice director binds an authorized reference recording to a character without treating emotion or room noise as identity.
- A generation worker checks readiness before spending money, records structured failure evidence, and reports acceptance/cost/retry analytics.
- An editor duplicates a selected Freezone canvas subgraph without breaking artifact lineage.
- A deployment accepts an ElevenLabs API root or the supplied `/v1/sound-generation` endpoint without constructing a duplicate path.

## Technical Research

### Approach Options

1. Vendor every upstream application. This conflicts with AGPL/Elastic/unlicensed boundaries and would replace the existing stack.
2. Treat installed Markdown skills as parity. This supplies guidance but does not create durable application behavior.
3. Keep the FastAPI/React platform and implement clean-room typed contracts, services, APIs, tests, and provenance for each behavior. This preserves the project architecture and license boundary.

### Recommended Approach

Use option 3. MIT/Apache/CC material may inform behavior with attribution. AGPL, Elastic-2.0, and unlicensed repositories remain behavioral references only. Paid providers remain behind server-only configuration and offline fakes.

### Required Technologies

- Existing FastAPI, Pydantic v2, SQLite/PostgreSQL boundaries, React/Vite.
- Existing MiniMax H3 and ElevenLabs provider adapters.
- SHA-256 source/artifact fingerprints and append-only evidence records.
- Deterministic tests; no paid provider calls.

### Data Requirements

- Reviewed source URL, commit, license treatment, capability IDs, entrypoints, and tests.
- Novel/episode byte spans and source hashes.
- Voice-reference authorization, consent, admission state, and identity-control boundaries.
- Readiness checks, failure evidence, generation outcomes, cost, retries, and latency.

## UI/UX Considerations

The capability center must expose truthful implementation status and concrete entrypoints. Project/canvas views should show ready/blocked/stale states rather than a generic “supported” badge.

## Integration Points

- `backend/app/api/production_api.py`
- `backend/app/api/studio_api.py`
- `backend/app/core/capability_manifest.py`
- `backend/app/service/production_service.py`
- `frontend/src/features/platform/CapabilityCenter.tsx`

## Risks and Challenges

- Provider APIs and upstream features evolve; pin reviewed commits and validate configuration.
- A real Jianying package is version/platform sensitive; never equate an interchange JSON with verified native import.
- Stochastic visual/audio quality requires real measurements or signed human approval.
- The supplied ElevenLabs key is exposed by being pasted into chat and must be rotated before a paid canary.

## Open Questions

- Merchant credentials are still required for real WeChat/Alipay checkout.
- GPU/runtime selection is still required for real 3GS/360 reconstruction.
- A real-provider canary needs a rotated key and explicit cost budget.

## References

See `tasks/upstream-capability-matrix.md` and `THIRD_PARTY_NOTICES.md` for the reviewed source list and license treatment.

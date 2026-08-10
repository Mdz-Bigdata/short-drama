# Production implementation status

Date: 2026-08-09

## Implemented and executable

- Mandatory character/scene/prop/effect asset readiness contract; a scene cannot be ready with a missing or unapproved category.
- Ordered character five-view generation, physical five-way splitting, and deterministic image preflight checks.
- Exactly nine detailed storyboard panels and a physically composed 3×3 board. Every panel includes characters, purpose, beat, duration, lens/aperture, camera motivation, composition, blocking, axis, eyeline, action, performance, scene, props, effects, light, sound, edit-in/out, generation mode, and continuity boundaries.
- MiniMax H3 adapter for text, first frame, last frame, first+last frame, multi-image, video, audio, and mixed reference modes, plus fail-fast capability negotiation, async status polling, and final `file_id` download resolution.
- An executable `sd25-pe` compiler for generation/edit/extension, audio-only edits, ordered edit-then-extension workflows, multimodal responsibilities, missing/unused-material enforcement, dialogue ledgers, exact first/last-frame sentences, exact nine-grid references, and coarse/fine blockout routing. Generation parameters remain outside the prompt as required by the local skill.
- ElevenLabs TTS, timed TTS, multi-speaker dialogue, timed dialogue, SFX, music, video-to-music, STT, and legacy dubbing adapters; per-character casting and alignment metadata can feed the editable timeline.
- Motivation-first performance plans covering trigger, containment, emotional leakage, decision, release, gaze, breath, face, body, voice, camera support, power shift, identity locks, and negative constraints.
- Continuity-state transition planning, FFmpeg xfade composition, overlap-corrected dialogue timing, BGM side-chain ducking, `-16 LUFS` normalization, and true-peak limiting.
- Fail-closed video quality decisions for identity, anatomy, expression, photorealism, temporal continuity, emotional dialogue timing, lip sync, and hard defects.
- SQLite-backed owner-isolated projects, optimistic artifact versions, parent lineage, downstream staleness, append-only audit events, idempotent generation jobs, provider task IDs, attempt budgets, and reserved cost units.
- Append-only artifact reviews, stale-approval blocking, a versioned mainline/Freezone canvas, and an explicit Director World contract for metric anchors, actor blocking, camera poses, lens/focus, axis, and deterministic frame plans.
- Atomic worker leases, bounded task logs, cooperative cancellation, expired-lease recovery, and durable provider task IDs that prevent a recovered worker from repeating a paid submission.
- Idempotent estimated/reserved/actual/released cost events summarized independently per currency, plus deterministic SHA-256-verified project archive export/import with traversal, symlink, undeclared-file, expansion, and tamper defenses.
- A locked Video Shotcraft index covering all 152 reviewed cards, 209 reviewed styles/previews, and 149 SFX across 16 categories; an Apache-license-checked checkout loader and canonical shot-plan compiler are callable through the API.
- Safe TXT/Markdown/DOCX/PDF/FDX ingestion with file/archive limits, ZIP traversal/symlink defenses, XML entity/network disabling, normalized source spans, hashes, and evidence-linked deterministic story graphs.
- SRT, ASS, editable mix data, and a documented Jianying-compatible timeline interchange format.
- Project-scoped external Agent keys with least-privilege scopes, one-time plaintext return, digest-only storage, revocation, and cross-project rejection.
- Thirteen-source machine-readable implementation report and a frontend capability/provider panel.
- PostgreSQL 16 product tables for users, global capability settings, actor/prop/scene/effect elements, memberships, orders, webhook events, append-only billing ledgers, and platform audit events. The live `short-drama` database was created and initialized through the requested asyncpg URL.
- All 66 declared abilities across the 13 sources are seeded with unique allowlisted `/commands`, authenticated resolution/invocation, globally persisted state, administrator-only switches, and an expandable frontend control center.
- Dedicated actor/prop/scene/effect UI pages and APIs support create, update, safe raster upload, detail/list, non-spending regeneration queues, and actor readiness only after the exact ordered five views.
- User center, forced password change, admin user pagination/role/status controls, last-admin protection, three membership plans, wallet/order views, sandbox purchase, and transactional signed/idempotent webhook processing.
- The requested local bootstrap identity (`admin@short-drama`) and development password (`admin@123`) are server-configured, idempotent, scrypt-hashed in PostgreSQL, and force a first-login password change. Production startup rejects this public default and requires an independent strong bootstrap secret.
- Server-only provider secrets (environment or encrypted PostgreSQL configuration), TLS verification, SSRF-resistant media downloads, skill ZIP guards, no arbitrary NPX execution, scrypt passwords, expiring HMAC sessions, origin enforcement, and API security headers.
- PostgreSQL-backed global model configuration for text, image, video and audio; provider/Base URL/API Key forms dynamically enumerate remote models, group text multimodal models and ElevenLabs ASR/TTS/BGM/music capabilities, encrypt secrets at rest, support connection tests and global per-model switches, and route enabled selections into the runtime provider layer without a hard-coded browser/backend catalog.
- PostgreSQL-backed project Markdown Skill management is callable from both `Skill` buttons: administrators can create, upload `.md`, safely import a bounded ZIP containing one `SKILL.md`, edit, save/cancel, enable, and disable. Every Skill has a version, SHA-256 digest, audit trail and `/skill.<slug>` command; enabled content refreshes an atomic runtime snapshot and is appended to every text-model system prompt without a restart. Imported content is guidance only and is never executed.

## Verification boundary

Automated verification currently passes 101 backend tests and 8 browser-component tests, plus ESLint, TypeScript/Vite production build, production dependency audit, a live PostgreSQL smoke, and headless-browser login/user-center/element/capability/model-configuration/project-Skill journeys with zero console errors. Provider tests use fakes and local deterministic fixtures. They intentionally do not submit paid MiniMax, ElevenLabs or other provider jobs. A real-provider canary requires rotated credentials and an explicit cost budget. Generative quality cannot be guaranteed mathematically; identity, acting, lip-sync, continuity, and final-edit acceptance still require real multimodal measurements or signed human review through the fail-closed quality gate.

## Not yet equivalent to all 13 complete upstream products

The implementation report exposes real entrypoints for all 13 sources, but an entrypoint is not a claim of complete product parity. The following upstream product-level features remain unfinished and must not be advertised as complete:

- PostgreSQL is authoritative for the new product platform modules, but legacy project/artifact/job/task repositories still require migration from SQLite/JSON before a multi-host worker deployment can be claimed. Atomic leases and crash recovery in the legacy studio profile are not advertised as a distributed queue.
- Full screenplay, review, dual-track canvas, Director World, cost and archive visual editors; the backend contracts/APIs exist, and the new frontend covers capabilities, elements, users and billing, but a full visual timeline editor, localization, and enterprise policy administration remain unfinished.
- A real GPU-backed 3GS/360 reconstruction renderer and spatial viewport; the metric Director World planning contract is implemented but deliberately reports `spatial_plan_only`.
- The locked Video Shotcraft catalog and selection compiler are implemented, but the complete upstream Remotion gallery, all recipe component implementations, bundled media, and headless renderer are not vendored yet.
- The output named `jianying-compatible-draft-v1` is an original documented interchange format, not a guarantee that every current Jianying application build will import it without a converter.
- FastMovieAI-style membership, points, orders, sandbox payment and signed callbacks are implemented. Real WeChat/Alipay checkout adapters remain fail-closed until merchant certificates/identities are provided and independently canary-tested.
- Real-provider canaries, visual golden reviews, deployment backup/restore, observability, and incident-response qualification remain release gates.

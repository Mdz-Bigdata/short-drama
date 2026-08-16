# Implementation Tasks: Unified AI Short-Drama Studio

Each task is intended to be one focused, reviewable increment. A task is complete only when its acceptance criteria and the project Definition of Done in `tasks/plan.md` both pass.

## Current verified increment

- [x] Executable sd25-pe generation/edit/extension compiler with multimodal, keyframe, nine-grid, blockout, dialogue-ledger, unused-material, and parameter-separation rules.
- [x] Fully integrate script-to-video-prompts with sd25-pe through one typed, source-bound production pipeline and safe multi-format exports.
- [x] Owner-scoped SQLite project/artifact/job/audit foundation with optimistic versions, staleness, idempotency, attempts, provider task IDs, and cost reservation.
- [x] Safe TXT/Markdown/DOCX/PDF/FDX ingestion, evidence spans, hashes, and deterministic story graph.
- [x] Mandatory five-view asset readiness and metadata-complete exact 3×3 storyboard contract.
- [x] Motivation-first performance planning and fail-closed identity/anatomy/expression/realism/continuity/dialogue/lip-sync QA.
- [x] ElevenLabs timed TTS/dialogue, SFX, music, video-to-music, STT, dubbing, plus ducked/loudness-limited final mix.
- [x] ElevenLabs Base URL normalization accepts either the API root or a full `/v1/sound-generation` endpoint; provider errors and failure evidence redact labeled and bare secret forms.
- [x] Explicit video reference routing for first frame, first+last frame, multi-image, and multimodal image/video/audio inputs, including safe accepted-tail inline frames.
- [x] Source-hash-bound novel triage, resumable episode intake, consent-aware voice direction, pre-spend readiness, failure evidence, production analytics, and lineage-safe Freezone subgraph duplication.
- [x] SRT/ASS/Jianying-compatible interchange and scoped/revocable external Agent API.
- [ ] Full-product parity items are still listed in `tasks/implementation-status.md`; do not infer completion from the 13-source implementation report.

## Phase 0: Secure and Test the Existing Baseline

### Task 1: Remove tracked runtime secrets and private data

**Description:** Make configuration environment-only, replace tracked runtime config/user/media data with safe templates or migrations, and document key rotation without printing any credential.

**Acceptance criteria:**
- [ ] No credential value, password record, user database, task database, or generated private media is tracked as application source.
- [ ] All provider secrets load from server-side settings and are redacted from errors/logs.
- [ ] The supplied ElevenLabs key and every provider key found in tracked configuration are recorded as requiring rotation.

**Verification:** `git grep` secret-pattern scan; backend startup with placeholder config; negative test proving no secret appears in API responses.

**Dependencies:** User rotates/revokes exposed keys before real provider calls.

**Files likely touched:** `.gitignore`, `backend/config.json`, `backend/.env.example`, `backend/app/core/settings.py`, `README.md`.

**Estimated scope:** Medium.

### Task 2: Add backend and frontend test harnesses

**Description:** Establish offline tests before changing production behavior, including provider fakes and temporary repositories/media directories.

**Acceptance criteria:**
- [ ] Backend tests never call a paid provider and run from a clean checkout.
- [ ] Frontend component/unit tests run independently of the backend.
- [ ] CI runs backend tests, frontend tests, lint, typecheck, and build.

**Verification:** `python -m pytest -q`; `npm test`; `npm run lint`; `npm run build`.

**Dependencies:** Task 1.

**Files likely touched:** `backend/requirements-dev.txt`, `backend/tests/conftest.py`, `frontend/package.json`, `frontend/src/App.test.tsx`, `.github/workflows/ci.yml`.

**Estimated scope:** Medium.

### Task 3: Capture current golden-path regression fixtures

**Description:** Lock the existing eight-stage task, script parse, five-view prompt, video request, tail-frame carry, and composition behavior with deterministic fixtures before refactoring.

**Acceptance criteria:**
- [ ] Tests cover stage progression, pause/resume state, script parsing, character-sheet prompt, and current media fallback behavior.
- [ ] Provider/network calls are replaced with recorded fakes.
- [ ] Tests fail when each protected behavior is deliberately removed.

**Verification:** `python -m pytest -q backend/tests/test_existing_workflow.py`.

**Dependencies:** Task 2.

**Files likely touched:** `backend/tests/test_existing_workflow.py`, `backend/tests/fakes.py`, `backend/tests/fixtures/golden_task.json`.

**Estimated scope:** Medium.

### Task 4: Add source registry and license notices

**Description:** Convert the upstream audit into a machine-readable registry and in-product attribution source.

**Acceptance criteria:**
- [ ] Every reviewed repository has URL, commit, license treatment, attribution, and capability IDs.
- [ ] CC BY and Apache NOTICE requirements are rendered in documentation/UI.
- [ ] CI rejects a reused capability asset without provenance metadata.

**Verification:** registry schema test and attribution snapshot test.

**Dependencies:** Task 2.

**Files likely touched:** `backend/app/data/upstream_sources.json`, `backend/app/schema/provenance.py`, `backend/tests/test_provenance.py`, `NOTICE`, `README.md`.

**Estimated scope:** Medium.

## Phase 1: Typed Domain, Storage, and Durable Jobs

### Task 5: Define canonical artifact and lineage schemas

**Description:** Introduce typed Project, Episode, Script, Asset, StoryboardBoard, Shot, Clip, Audio, Export, Version, and Approval records without changing providers.

**Acceptance criteria:**
- [ ] Every artifact has stable ID, version, status, creator, content hash, parents, and staleness state.
- [ ] Invalid references and dependency cycles fail schema validation.
- [ ] Existing JSON tasks can be migrated into the new records.

**Verification:** schema and migration fixture tests.

**Dependencies:** Task 3.

**Files likely touched:** `backend/app/schema/artifacts.py`, `backend/app/schema/lineage.py`, `backend/app/migrations/legacy_tasks.py`, `backend/tests/test_artifact_schema.py`.

**Estimated scope:** Medium.

### Task 6: Replace JSON repositories with a durable database boundary

**Description:** Add SQLAlchemy repositories with SQLite local and PostgreSQL production profiles while preserving the existing service interface during migration.

**Acceptance criteria:**
- [ ] Project/task/user/artifact writes are transactional and ownership-scoped.
- [ ] Legacy JSON imports are idempotent and backed up rather than overwritten.
- [ ] Concurrent updates use optimistic version checks.

**Verification:** repository tests against temporary SQLite and PostgreSQL integration CI.

**Dependencies:** Task 5.

**Files likely touched:** `backend/app/db/models.py`, `backend/app/db/session.py`, `backend/app/repository/task_repo.py`, `backend/app/repository/artifact_repo.py`, `backend/tests/test_repositories.py`.

**Estimated scope:** Medium.

### Task 7: Implement durable generation jobs and idempotency

**Description:** Replace in-process heavy `BackgroundTasks` with a persistent worker contract carrying immutable submission descriptors, provider task IDs, budgets, and attempt limits.

**Acceptance criteria:**
- [ ] Restart resumes polling/downloading an existing provider task without duplicate submission.
- [ ] Paid attempts reserve budget before submission and release/reconcile it deterministically.
- [ ] Cancel, retry, fail, accept, and stale transitions are auditable.

**Verification:** crash/restart and duplicate-delivery tests using a fake provider.

**Dependencies:** Task 6.

**Files likely touched:** `backend/app/jobs/models.py`, `backend/app/jobs/worker.py`, `backend/app/jobs/idempotency.py`, `backend/app/api/job_api.py`, `backend/tests/test_job_recovery.py`.

**Estimated scope:** Medium.

### Checkpoint A

- [ ] Existing golden path passes on durable repositories/jobs.
- [ ] No real provider call is made by tests.
- [ ] Secret, dependency, lint, type, and build gates pass.

## Phase 2: Source, Story, and Screenplay

### Task 8: Harden multi-format source ingestion

**Description:** Extend the existing parser to TXT, Markdown, DOCX, PDF, and FDX with provenance, size/type limits, safe archives, and normalized source spans.

**Acceptance criteria:**
- [ ] Every parsed scene/dialogue/action points back to a source span and file hash.
- [ ] Unsupported, malformed, oversized, encrypted, or hostile files fail safely.
- [ ] Document text is treated as untrusted content, not agent instruction.

**Verification:** parser fixtures for all formats and abuse cases.

**Dependencies:** Tasks 5 and 7.

**Files likely touched:** `backend/app/ingest/parsers.py`, `backend/app/ingest/security.py`, `backend/app/schema/source.py`, `backend/app/api/drama_api.py`, `backend/tests/test_ingest.py`.

**Estimated scope:** Medium.

### Task 9: Build traceable story graph and adaptation map

**Description:** Extract characters, relationships, timeline, locations, events, conflicts, secrets, and source-to-adaptation decisions.

**Acceptance criteria:**
- [ ] Story graph records evidence spans and separates source fact from creative inference.
- [ ] Episode planning produces causal beats, hooks, and multi-episode arcs.
- [ ] Review can identify omissions, inventions, contradictions, and unresolved source facts.

**Verification:** novel and screenplay golden fixtures with graph/adaptation snapshots.

**Dependencies:** Task 8.

**Files likely touched:** `backend/app/story/graph.py`, `backend/app/story/adaptation.py`, `backend/app/schema/story.py`, `backend/app/prompts/story.py`, `backend/tests/test_story_graph.py`.

**Estimated scope:** Medium.

### Task 10: Add screenplay lifecycle and review/fix loop

**Description:** Support outline, draft, normalized screenplay, review, accepted production script, revision, and rollback states.

**Acceptance criteria:**
- [ ] Dialogue, action, scene headings, beats, timing, and episode hooks are editable structured records.
- [ ] Review findings link to affected records and fixes create a new version.
- [ ] Downstream assets become stale only when their dependencies change.

**Verification:** lifecycle, rollback, and selective-staleness tests.

**Dependencies:** Task 9.

**Files likely touched:** `backend/app/service/script_service.py`, `backend/app/schema/screenplay.py`, `backend/app/repository/script_repo.py`, `backend/app/api/script_api.py`, `backend/tests/test_script_lifecycle.py`.

**Estimated scope:** Medium.

## Phase 3: Asset Bible and Mandatory Five Views

### Task 11: Create versioned role/scene/prop/effect asset registry

**Description:** Replace loose dictionaries with typed reusable assets and state variants used across episodes and shots.

**Acceptance criteria:**
- [ ] Character, costume, voice, scene, prop, and effect assets have typed identity anchors and versions.
- [ ] A scene readiness check reports every missing/stale asset reference.
- [ ] Prop ownership/hand/position/condition and effect source/target/end-state are tracked.

**Verification:** asset resolution and readiness tests.

**Dependencies:** Task 10.

**Files likely touched:** `backend/app/schema/assets.py`, `backend/app/service/asset_service.py`, `backend/app/repository/asset_repo.py`, `backend/app/api/asset_api.py`, `backend/tests/test_asset_registry.py`.

**Estimated scope:** Medium.

### Task 12: Enforce the character five-view pipeline

**Description:** Upgrade the current five-view prompt into a typed generation, exact crop, labeling, and identity-validation pipeline.

**Acceptance criteria:**
- [ ] Every character variant contains front, front-three-quarter, profile, rear-three-quarter, and back views from the same identity anchor.
- [ ] Views share baseline, proportions, face, hair, costume, accessories, palette, and distinguishing marks.
- [ ] Missing/duplicate/inconsistent views prevent approval and downstream storyboard readiness.

**Verification:** five-view geometry/crop tests, fake identity scorer tests, and manual golden-sheet review.

**Dependencies:** Task 11.

**Files likely touched:** `backend/app/assets/character_turnaround.py`, `backend/app/schema/assets.py`, `backend/app/core/model_gateway.py`, `backend/app/service/drama_service.py`, `backend/tests/test_character_turnaround.py`.

**Estimated scope:** Medium.

### Task 13: Generate scene, prop, and effect reference packages

**Description:** Produce reusable scene geography/light views, prop state sheets, and effect lifecycle references instead of character-only anchors.

**Acceptance criteria:**
- [ ] Scene package defines layout, entrances/exits, camera-safe axis, light direction, time/weather, and foreground/midground/background anchors.
- [ ] Prop/effect packages expose all states required by the script and continuity ledger.
- [ ] Every storyboard panel resolves role, scene, prop, and effect references explicitly.

**Verification:** asset-package completeness tests and visual fixture review.

**Dependencies:** Tasks 11 and 12.

**Files likely touched:** `backend/app/assets/scene_package.py`, `backend/app/assets/prop_effect_package.py`, `backend/app/prompts/assets.py`, `backend/tests/test_asset_packages.py`.

**Estimated scope:** Medium.

### Task 14: Add look development and spatial director world

**Description:** Store project style truth, reference provenance, scene variants, 360/3GS or blockout references, camera positions, and consistent spatial coordinates.

**Acceptance criteria:**
- [ ] Approved lookdev settings propagate without overwriting asset identity facts.
- [ ] Scene blockout supports named camera positions and character/prop placement.
- [ ] 3GS/360 is optional through a capability adapter and degrades to 2D spatial plans.

**Verification:** style inheritance and camera/blocking coordinate tests.

**Dependencies:** Task 13.

**Files likely touched:** `backend/app/schema/lookdev.py`, `backend/app/service/lookdev_service.py`, `backend/app/spatial/world.py`, `backend/app/providers/spatial.py`, `backend/tests/test_spatial_world.py`.

**Estimated scope:** Medium.

### Checkpoint B

- [ ] An accepted script produces a complete role/scene/prop/effect bible.
- [ ] No storyboard can start until every character variant has an approved five-view sheet.
- [ ] Asset changes propagate precise staleness to dependent boards/shots.

## Phase 4: Exact Nine-grid Directing and Prompt Intelligence

### Task 15: Define the complete shot and storyboard-board schema

**Description:** Represent directing decisions as typed data before generating images or provider prompts.

**Acceptance criteria:**
- [ ] A panel includes all metadata required by the nine-grid contract in `tasks/plan.md`.
- [ ] Start/end states, asset references, action axis, eyeline, movement reason, sound, and transitions are mandatory where applicable.
- [ ] Time ranges are continuous, non-overlapping, and within board/clip limits.

**Verification:** schema boundary/property tests.

**Dependencies:** Tasks 10 and 14.

**Files likely touched:** `backend/app/schema/storyboard.py`, `backend/app/schema/continuity.py`, `backend/app/storyboard/validator.py`, `backend/tests/test_storyboard_schema.py`.

**Estimated scope:** Medium.

### Task 16: Encode the supplied seven-purpose directing rules

**Description:** Implement the article-derived order, purpose, emotion distance, genre rhythm, and default duration recommendation engine.

**Acceptance criteria:**
- [ ] Information coverage establishes place -> relationship -> emotion unless explicitly overridden.
- [ ] The seven shot purposes map to suitable coverage choices with a reason trace.
- [ ] Duration/rhythm recommendations match the documented defaults and remain overrideable.

**Verification:** table-driven tests for all seven purposes, eight rhythm profiles, and duration classes.

**Dependencies:** Task 15.

**Files likely touched:** `backend/app/storyboard/rules.py`, `backend/app/data/storyboard_rules.json`, `backend/app/storyboard/planner.py`, `backend/tests/test_storyboard_rules.py`.

**Estimated scope:** Medium.

### Task 17: Add action, dialogue, and facial-performance planners

**Description:** Merge action causality, confrontation tension, and motivation-first microexpression direction into compatible shot beats.

**Acceptance criteria:**
- [ ] Action follows initiation -> defense/contact -> physical result -> recovery/new state.
- [ ] Dialogue follows pressure -> reception -> leakage/counter -> new balance without splitting a sentence unnaturally.
- [ ] Facial/body/breath/voice changes are anatomically compatible, timed, motivated, and preserve user-supplied camera decisions.

**Verification:** action, confrontation, and emotional-transition fixture tests.

**Dependencies:** Tasks 15 and 16.

**Files likely touched:** `backend/app/storyboard/action_planner.py`, `backend/app/storyboard/dialogue_planner.py`, `backend/app/storyboard/performance_planner.py`, `backend/tests/test_performance_plans.py`.

**Estimated scope:** Medium.

### Task 18: Generate and split exact 3x3 storyboard boards

**Description:** Replace per-shot loose preview images with a deterministic nine-panel board plus nine independently addressable crops.

**Acceptance criteria:**
- [ ] Every board has exactly three rows, three columns, nine numbered panels, and no blank decorative padding.
- [ ] Panel images and metadata round-trip through compose/split without reordering or crop drift.
- [ ] Board approval freezes the nine panel versions used by video generation.

**Verification:** pixel geometry, metadata round-trip, and final-partial-board tests; manual golden board review.

**Dependencies:** Tasks 13, 15, 16, and 17.

**Files likely touched:** `backend/app/storyboard/grid.py`, `backend/app/service/storyboard_service.py`, `backend/app/api/storyboard_api.py`, `backend/app/service/drama_service.py`, `backend/tests/test_nine_grid.py`.

**Estimated scope:** Medium.

### Task 19: Build provider-native prompt renderers and audits

**Description:** Compile canonical shots into H3, Seedance, Kling, Veo, and universal prompts without losing source fields.

**Acceptance criteria:**
- [ ] Provider syntax is isolated from canonical project data.
- [ ] Renderer output includes assets, performance, timing, camera reason, audio, start/end states, and targeted failure constraints.
- [ ] Prompt audit explains missing/conflicting fields and can produce a stronger version.

**Verification:** provider snapshot tests and round-trip trace to canonical fields.

**Dependencies:** Tasks 17 and 18.

**Files likely touched:** `backend/app/prompts/renderers.py`, `backend/app/prompts/audit.py`, `backend/app/providers/capabilities.py`, `backend/tests/test_prompt_renderers.py`.

**Estimated scope:** Medium.

### Checkpoint C

- [ ] Every production board is an exact nine-grid with complete role/scene/prop/effect references.
- [ ] Five-view and scene bible references are visible in panel lineage.
- [ ] Provider prompts are generated from the same accepted board, not from ad-hoc text.

## Phase 5: Provider Execution, Reference Modes, and QA

### Task 20: Add provider capability negotiation

**Description:** Make model/provider limits explicit and validate them before cost reservation or submission.

**Acceptance criteria:**
- [ ] Text, image, video, TTS, SFX, and music providers publish typed capabilities.
- [ ] Unsupported mode/count/duration/aspect/resolution/audio fails before submission.
- [ ] UI can explain compatible providers and exact incompatibility reasons.

**Verification:** capability matrix tests with positive and negative requests.

**Dependencies:** Tasks 7 and 19.

**Files likely touched:** `backend/app/providers/base.py`, `backend/app/providers/registry.py`, `backend/app/schema/generation.py`, `backend/app/api/provider_api.py`, `backend/tests/test_capabilities.py`.

**Estimated scope:** Medium.

### Task 21: Implement MiniMax H3 adapter

**Description:** Support H3 T2VA, I2VA, FL2VA/L2VA, and Ref2VA with correctly labeled multimodal references and optional local/API backends.

**Acceptance criteria:**
- [ ] First-only, last-only, first-and-last, multi-image, reference video, reference audio, and mixed requests serialize correctly.
- [ ] Adapter enforces up to nine images, three videos, three audios, twelve mixed files, and supported duration/aspect/resolution.
- [ ] Provider task polling, download, cost, error, and content-policy states are persisted.

**Verification:** official-example contract fixtures with a fake HTTP server; no real key required.

**Dependencies:** Task 20.

**Files likely touched:** `backend/app/providers/minimax_h3.py`, `backend/app/schema/generation.py`, `backend/app/core/model_gateway.py`, `backend/tests/test_minimax_h3.py`.

**Estimated scope:** Medium.

### Task 22: Harden Seedance and custom video reference modes

**Description:** Move current loose `Dict` payloads into the canonical generation request and add role/priority metadata, count limits, and safe URL/media validation.

**Acceptance criteria:**
- [ ] Existing text, first-frame, first/last-frame, and multimodal flows remain compatible.
- [ ] Every reference has a role, priority, content hash, provenance, and provider mapping.
- [ ] Audio-only reference requests and unsupported combinations fail clearly.

**Verification:** API schema tests and current Seedance regression fixtures.

**Dependencies:** Task 20.

**Files likely touched:** `backend/app/providers/seedance.py`, `backend/app/api/drama_api.py`, `backend/app/core/model_gateway.py`, `backend/tests/test_seedance_requests.py`.

**Estimated scope:** Medium.

### Task 23: Implement accepted-tail continuity and multimodal QA

**Description:** Replace unconditional tail-frame carry with acceptance-gated continuity state and technical/semantic review.

**Acceptance criteria:**
- [ ] Rejected or technically invalid clips never seed dependent shots.
- [ ] Accepted clip records terminal frame plus role, pose, gaze, screen position, axis, prop/effect, scene/light, wardrobe/damage, and motion state.
- [ ] Semantic retry is targeted, bounded, budgeted, and changes only failed dimensions.

**Verification:** accepted/rejected lineage, stale-context, and bounded-retry tests.

**Dependencies:** Tasks 7, 15, 21, and 22.

**Files likely touched:** `backend/app/qa/video_review.py`, `backend/app/continuity/ledger.py`, `backend/app/jobs/worker.py`, `backend/app/service/drama_service.py`, `backend/tests/test_accepted_tail.py`.

**Estimated scope:** Medium.

## Phase 6: ElevenLabs Speech, SFX, and Music

### Task 24: Implement ElevenLabs TTS and voice casting

**Description:** Connect server-side dialogue/voiceover generation to `/v1/text-to-speech/{voice_id}` with character voice assets and alignment metadata.

**Acceptance criteria:**
- [ ] Each speaking character resolves an approved voice ID/settings/version and consent/provenance state.
- [ ] TTS output records request ID, cost metadata, format, duration, and word/character alignment when available.
- [ ] Key is server-only and redacted; provider errors expose no sensitive request internals.

**Verification:** fake ElevenLabs endpoint tests for success, rate limit, timeout, invalid voice, and redaction.

**Dependencies:** Tasks 1, 7, 11, and 20.

**Files likely touched:** `backend/app/providers/elevenlabs_tts.py`, `backend/app/schema/audio.py`, `backend/app/service/audio_service.py`, `backend/tests/test_elevenlabs_tts.py`.

**Estimated scope:** Medium.

### Task 25: Implement ElevenLabs sound effects

**Description:** Use the requested `/v1/sound-generation` endpoint for diegetic/action/transition effects tied to visible sources and shot timing.

**Acceptance criteria:**
- [ ] SFX prompts reference source, action, material, environment, duration, and sync marker.
- [ ] Output is versioned and aligned to shot events without inventing off-screen sources unintentionally.
- [ ] Endpoint, format, timeout, rate/cost, and fallback behavior are configurable and tested.

**Verification:** fake endpoint and timeline-alignment tests.

**Dependencies:** Tasks 20 and 24.

**Files likely touched:** `backend/app/providers/elevenlabs_sfx.py`, `backend/app/service/audio_service.py`, `backend/app/schema/audio.py`, `backend/tests/test_elevenlabs_sfx.py`.

**Estimated scope:** Medium.

### Task 26: Implement ElevenLabs music and video-to-music BGM

**Description:** Generate instrumental BGM with `/v1/music` or picture-led scoring with `/v1/music/video-to-music`, replacing the current sine-tone placeholder.

**Acceptance criteria:**
- [ ] BGM plan maps story beats, tension curve, section duration, instrumentation, and transition points.
- [ ] Instrumental mode, seed/plan, duration, C2PA option, and picture-led input are supported where available.
- [ ] Local/library BGM remains a provider-independent fallback with provenance.

**Verification:** fake music/video-to-music tests and beat-map fixture review.

**Dependencies:** Tasks 20, 23, and 24.

**Files likely touched:** `backend/app/providers/elevenlabs_music.py`, `backend/app/audio/score_planner.py`, `backend/app/service/audio_service.py`, `backend/tests/test_elevenlabs_music.py`.

**Estimated scope:** Medium.

### Task 27: Build dialogue, SFX, and BGM mix engine

**Description:** Replace fixed-volume amix with a structured timeline, side-chain ducking, loudness normalization, fades, and continuity-aware audio bridges.

**Acceptance criteria:**
- [ ] Dialogue remains intelligible while BGM ducks and recovers around speech.
- [ ] SFX/BGM/dialogue timing is deterministic and recorded in an editable mix manifest.
- [ ] Output passes sample-rate/channel/loudness/peak and no-clipping checks.

**Verification:** FFmpeg command snapshot, synthetic audio fixture, loudness and alignment tests.

**Dependencies:** Tasks 24, 25, and 26.

**Files likely touched:** `backend/app/audio/timeline.py`, `backend/app/audio/mixer.py`, `backend/app/core/media_compositor.py`, `backend/tests/test_audio_mix.py`.

**Estimated scope:** Medium.

### Checkpoint D

- [ ] A test scene has approved voice, synchronized SFX, and story-shaped BGM.
- [ ] No provider key is present in source, logs, frontend bundles, or exports.
- [ ] Audio costs and lineage appear in the task record.

## Phase 7: Natural Assembly, Templates, and Export

### Task 28: Implement continuity-aware transition planning

**Description:** Select edits from narrative state, eye trace, motion direction, composition, audio, and color instead of applying one global transition.

**Acceptance criteria:**
- [ ] Every edit records its purpose and one of cut/action match/eyeline/graphic/J/L/sound bridge/whip/dissolve/black hold.
- [ ] Mismatched axes, motion vectors, identities, props, light, or audio phases trigger repair or review.
- [ ] Transition handles never remove required action/contact/dialogue beats.

**Verification:** edit-decision fixtures and boundary-state mismatch tests.

**Dependencies:** Tasks 23 and 27.

**Files likely touched:** `backend/app/edit/transition_planner.py`, `backend/app/schema/edit.py`, `backend/app/continuity/ledger.py`, `backend/tests/test_transition_planner.py`.

**Estimated scope:** Medium.

### Task 29: Upgrade FFmpeg composition and final QA

**Description:** Normalize clips and execute the transition/audio plan with deterministic output, replacing hard concatenation for final edits.

**Acceptance criteria:**
- [ ] Resolution, frame rate, SAR, color space, codec, audio layout, and loudness are normalized.
- [ ] Crossfades/xfades/J-L cuts/sound bridges follow the approved edit manifest with no black gaps or duplicated boundary frames.
- [ ] Final technical and multimodal semantic QA produces a pass/fail report; a failed film is not marked complete.

**Verification:** synthetic multi-clip fixtures, ffprobe assertions, frame/audio boundary tests, manual golden-cut review.

**Dependencies:** Tasks 27 and 28.

**Files likely touched:** `backend/app/edit/compositor.py`, `backend/app/edit/qa.py`, `backend/app/core/media_compositor.py`, `backend/tests/test_film_composition.py`.

**Estimated scope:** Medium.

### Task 30: Integrate Video Shotcraft Remotion recipes and templates

**Description:** Add the Apache-licensed shot recipe/component catalog, deterministic product-promo rendering, 2.5D page camera, typography, beat sync, and audio assets with notices.

**Acceptance criteria:**
- [ ] Recipe catalog is searchable and each recipe records provenance, purpose, energy, timing, parameters, and known limitations.
- [ ] At least one licensed complete template renders headlessly and accepts project assets/copy/color tokens.
- [ ] Bundled audio/media rights are audited separately from code.

**Verification:** Remotion render smoke test, frame snapshots, NOTICE and media-license checks.

**Dependencies:** Tasks 4, 19, 27, and 29.

**Files likely touched:** `render/package.json`, `render/src/recipes.ts`, `render/src/templates/InkPress.tsx`, `backend/app/templates/shotcraft.py`, `backend/tests/test_template_registry.py`.

**Estimated scope:** Medium.

### Task 31: Add subtitles, platform variants, archive, and Jianying export

**Description:** Produce masters and editable delivery packages with captions, media manifests, project history, and platform-safe variants.

**Acceptance criteria:**
- [ ] Exports include master video, SRT/ASS, audio stems, clips, prompts, asset/provenance manifest, and reproducible edit manifest.
- [ ] 9:16/16:9/1:1/4:5 variants respect safe areas and do not silently crop key subjects/text.
- [ ] Jianying draft export preserves clips, subtitles, voice, BGM, timing, and transition intent where the format allows.

**Verification:** export schema, archive round-trip, safe-area, and Jianying fixture tests.

**Dependencies:** Tasks 29 and 30.

**Files likely touched:** `backend/app/export/package.py`, `backend/app/export/jianying.py`, `backend/app/export/variants.py`, `backend/app/api/export_api.py`, `backend/tests/test_exports.py`.

**Estimated scope:** Medium.

## Phase 8: Preset and Workflow Capability Parity

### Task 32: Ship the nine MiniMax/H3 workflow presets

**Description:** Register H3 prompt writing plus 3D short, brand promo, co-op intro, hand-drawn/live-action, minimalist product ad, lyric MV, paper collage, and papercraft explainer workflows.

**Acceptance criteria:**
- [ ] Every preset defines intake, required assets, approval gates, board/shot policy, audio policy, provider requirements, and final review.
- [ ] Presets share canonical assets/shots rather than embedding independent data formats.
- [ ] Each preset has a golden pre-production/output fixture.

**Verification:** preset registry and golden workflow tests.

**Dependencies:** Tasks 19, 21, 27, and 29.

**Files likely touched:** `backend/app/presets/minimax.py`, `backend/app/presets/registry.py`, `backend/app/schema/preset.py`, `backend/tests/test_minimax_presets.py`.

**Estimated scope:** Medium.

### Task 33: Ship drama workflow, review, and lightweight platform presets

**Description:** Implement source-traceable development, screenplay, assets, image prompts, storyboard, video prompts, independent review, novel adaptation, and 4-15s grouped prompt modes.

**Acceptance criteria:**
- [ ] Full and lightweight paths produce the documented artifact types with shared lineage.
- [ ] Review runs independently and cannot mark its own findings fixed without a new artifact version.
- [ ] Platform-ready grouped prompts include style, scene, role, prop, timing, picture, movement, sound, and constraints.

**Verification:** end-to-end text-only fixtures and lifecycle tests.

**Dependencies:** Tasks 10, 13, 18, and 19.

**Files likely touched:** `backend/app/presets/drama_workflows.py`, `backend/app/review/independent.py`, `backend/app/prompts/grouped_video.py`, `backend/tests/test_drama_presets.py`.

**Estimated scope:** Medium.

### Task 34: Ship visual directing, prompt audit, and shot-engine modes

**Description:** Add dramaturgy/detail gates, image direction, model-native audit, action/confrontation modes, continuous clip splitting, six-slot style locks, and camera terminology.

**Acceptance criteria:**
- [ ] Dramaturgy and three-detail audits can block incomplete shots.
- [ ] Action/confrontation mode selection and clip splitting preserve causal state across clips.
- [ ] Style locks and camera vocabulary are executable descriptions, not creator-name shorthand.

**Verification:** audit failure/pass fixtures, clip continuity tests, and renderer snapshots.

**Dependencies:** Tasks 17 and 19.

**Files likely touched:** `backend/app/presets/visual_directing.py`, `backend/app/storyboard/audits.py`, `backend/app/prompts/camera_language.py`, `backend/tests/test_visual_directing.py`.

**Estimated scope:** Medium.

## Phase 9: Production Workbench and Platform Features

### Task 35: Decompose the frontend into project, asset, board, and timeline features

**Description:** Preserve the existing UI while replacing the single large `App.tsx` with typed feature modules and the new APIs.

**Acceptance criteria:**
- [ ] Users can inspect/edit/approve source, script, five-view assets, scene/prop/effect packages, exact nine-grid boards, shots, clips, audio, edit, and exports.
- [ ] Stale, blocked, generating, review, accepted, failed, and cost states are visible.
- [ ] Existing task creation and stage navigation continue to work during migration.

**Verification:** component tests, typecheck/build, and critical browser journey.

**Dependencies:** Tasks 10, 18, 23, 27, and 31.

**Files likely touched:** `frontend/src/App.tsx`, `frontend/src/features/projects/index.tsx`, `frontend/src/features/assets/index.tsx`, `frontend/src/features/storyboards/index.tsx`, `frontend/src/api/client.ts`.

**Estimated scope:** Medium.

### Task 36: Add canvas, task center, versions, costs, and assistant actions

**Description:** Deliver the dual mainline/infinite-canvas workflow, durable job monitoring, version rollback, budget dashboards, and scoped director-assistant actions.

**Acceptance criteria:**
- [ ] Canvas nodes reference canonical artifacts and cannot diverge into hidden copies.
- [ ] Task center shows provider, progress, logs, cost, attempts, cancel/retry/resume, and dependencies.
- [ ] Assistant suggestions are permission-checked and paid/destructive actions require confirmation.

**Verification:** API/component tests and browser E2E for cancel/resume/rollback/cost.

**Dependencies:** Tasks 7, 14, 31, and 35.

**Files likely touched:** `frontend/src/features/canvas/index.tsx`, `frontend/src/features/jobs/index.tsx`, `frontend/src/features/costs/index.tsx`, `backend/app/api/assistant_api.py`, `backend/tests/test_assistant_permissions.py`.

**Estimated scope:** Medium.

### Task 37: Harden authentication, RBAC, and project isolation

**Description:** Replace prototype auth/storage behavior with secure sessions, modern password hashing, ownership checks, role-scoped settings, and the configured development bootstrap administrator.

**Acceptance criteria:**
- [ ] Every protected endpoint and media/object access checks user/project role.
- [ ] Passwords use Argon2id/bcrypt/scrypt, sessions are secure/httpOnly/sameSite, and login/code endpoints are rate-limited.
- [x] The requested public development admin is isolated to server configuration,
  stored as a scrypt hash, forced to change, and rejected during production startup;
  no provider secret, stack trace, or cross-project artifact is exposed.

**Verification:** auth/IDOR/rate-limit/session/security-header tests.

**Dependencies:** Tasks 1 and 6.

**Files likely touched:** `backend/app/service/auth_service.py`, `backend/app/api/auth_api.py`, `backend/app/security/session.py`, `backend/app/security/authorization.py`, `backend/tests/test_auth_security.py`.

**Estimated scope:** Medium.

### Task 38: Add scoped plugins and external-agent API

**Description:** Preserve skill import while introducing signed manifests, capability permissions, sandboxed execution, and scoped external-agent keys.

**Acceptance criteria:**
- [ ] ZIP/URL imports prevent traversal, SSRF, executable payloads, and unreviewed install scripts.
- [ ] Plugin permissions default deny network, filesystem, provider generation, payment, and destructive actions.
- [ ] External-agent keys are hashed, project-scoped, revocable, rate-limited, and audited.

**Verification:** malicious package/URL tests and permission-boundary tests.

**Dependencies:** Tasks 7, 20, and 37.

**Files likely touched:** `backend/app/plugins/manifest.py`, `backend/app/plugins/installer.py`, `backend/app/api/agent_api.py`, `backend/app/security/api_keys.py`, `backend/tests/test_plugin_security.py`.

**Estimated scope:** Medium.

### Task 39: Add optional commerce, membership, points, WeChat, and localization

**Description:** Reach FastMovieAI platform parity without coupling the creative core to billing or a single locale.

**Acceptance criteria:**
- [ ] Membership/points/payments use an append-only ledger and signed idempotent provider callbacks.
- [ ] WeChat integration is isolated behind an adapter and optional feature flag.
- [ ] Chinese/English UI and API messages are localized; creative content language remains project-specific.

**Verification:** fake payment webhook, ledger invariant, feature-flag, and localization tests.

**Dependencies:** Tasks 7, 35, and 37. May be scheduled after the creative core with user approval.

**Files likely touched:** `backend/app/billing/ledger.py`, `backend/app/billing/providers.py`, `backend/app/integrations/wechat.py`, `frontend/src/i18n/index.ts`, `backend/tests/test_billing.py`.

**Estimated scope:** Medium.

## Phase 10: Final Parity and Release Gate

### Task 40: Build the capability-parity acceptance suite

**Description:** Turn every matrix row and user invariant into a traceable automated/manual release test.

**Acceptance criteria:**
- [ ] Every capability ID maps to implementation, source treatment, test, documentation, and release status.
- [ ] Mandatory five-view, exact nine-grid, multi-reference/FL2V, ElevenLabs, recovery, continuity, transition, and export journeys all pass.
- [ ] No feature is marked supported when only a prompt placeholder exists.

**Verification:** parity report generator and golden project E2E suite.

**Dependencies:** Tasks 1-39 applicable to the selected release scope.

**Files likely touched:** `backend/tests/e2e/test_golden_project.py`, `frontend/e2e/golden-project.spec.ts`, `scripts/capability_report.py`, `docs/capability-status.md`, `docs/release-checklist.md`.

**Estimated scope:** Medium.

### Final Checkpoint

- [ ] Full tests, lint, typecheck, build, E2E, dependency audit, secret scan, license/NOTICE audit, and runtime smoke pass.
- [ ] A real-provider canary is run only with rotated secrets and an approved cost budget.
- [ ] Human reviewers approve five-view identity, nine-grid accuracy, performance, continuity, audio, transition quality, and final edit.
- [ ] Deployment, backup, restore, rollback, observability, and incident instructions are current.

## Active platform completion checklist (2026-08-09)

- [x] Create PostgreSQL database `short-drama` and verify the configured async URL.
- [x] Add SQLAlchemy async models/schema initialization for users, capabilities, elements,
  memberships, orders, webhook events, ledgers, and audit events.
- [x] Seed the configured development administrator `admin@short-drama` /
  `admin@123` idempotently with forced change and a production default-password guard.
- [x] Add admin/user authorization, profile/password, paginated user management,
  active/status/role controls, and last-admin protection.
- [x] Seed every capability of all 13 source manifests with stable `/commands` and
  admin-controlled global enablement.
- [x] Add safe command resolution that cannot execute arbitrary code or disabled
  abilities.
- [x] Add actor/prop/scene/effect library APIs, exact actor five-view readiness,
  safe add/upload, versioning, and non-spending regeneration requests.
- [x] Add plans, memberships, wallet/points ledgers, orders, sandbox payment, and
  signed idempotent provider callback contracts.
- [x] Build the capability dropdown/switch/palette, four element pages, user center,
  and payment center in the React application.
- [x] Run backend regression, PostgreSQL integration smoke, frontend lint/build,
  dependency audit, secret scan, and browser journeys.
- [x] Replace the hard-coded model popover with a PostgreSQL-backed global model
  configuration center, encrypted credentials, dynamic provider enumeration,
  multimodal/audio classification, connection testing, save/cancel, runtime routing,
  and per-model enable/disable controls.

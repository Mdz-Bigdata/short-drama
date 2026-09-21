# Workflow and reading UI verification — 2026-09-05

## Delivered

- Source-grounded repair of whole outline episodes omitted from persisted nonempty breakdowns. Existing valid scene IDs/content/assets are retained; real gaps in the screenplay are not fabricated. Writer, status and storyboard production use the same reconciliation. Source hashes remain consistent before/after repair.
- One authoritative eight-agent readiness snapshot drives continuation, automatic runs and conversation guidance. Failed attempts, incomplete episode storyboards and missing media cannot be skipped. Production completion is distinct from final review approval.
- Durable chat events survive background worker saves. Run reservations prevent duplicate starts; pause/stop control survives old snapshots and process recovery.
- `/pause`, `/resume`, `/stop`, `/start`, `/compose`, `/auto`, `/status`, `/help` are explicit commands. Unknown slash commands show help; questions, greetings and negation do not generate content. Automatic production does not require per-stage confirmation. Pause/stop takes effect after the current stage; existing artifacts/history remain available.
- The right-side eight-agent card is removed. Keyboard-searchable command menu and independently scrolling history keep the composer visible; reading older messages disables automatic bottom-following until the reader returns to the latest messages.
- Prompt reading starts with a bounded current-scene/episode preview. Full source is expandable and scrollable with exact text preserved, including Unicode paragraph boundaries. Uncertain source matches are labelled as reference material rather than falsely identified as a shot.

## Checks

- 242 targeted backend unittest cases covering workflow, source repair, repository/history, storyboard generation contracts, script/version safety, actor persistence and quality/release gates passed.
- Full frontend Vitest suite (47 files, 314 tests), TypeScript/production build and scoped ESLint passed. Code review and Python review approved after fixes.
- New workflow module passes mypy and Black; changed-file whitespace checks pass.
- No paid generation, publication or project deletion was triggered for verification.

## Remaining verification boundaries

- Browser-level visual acceptance at mobile/desktop widths has not been performed: computer-use permissions are unavailable. DOM interaction and CSS/build checks do not replace visual acceptance.
- The historical ancient-costume screenshot project was not found in the current local PostgreSQL task store. The repair method is implemented and tested, but no historical production data was changed without resolving the exact project/environment.
- Existing unrelated React/Three.js test warnings and the large 3D bundle warning remain outside this increment.

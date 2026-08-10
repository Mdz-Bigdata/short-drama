# Product parity closure specification

Date: 2026-08-09

## Objective

Close the largest product-level gaps shared by DramaClaw, ArcReel, InstantVideo,
FastMovieAI, Video Shotcraft, and the local `sd25-pe` contract without copying
AGPL/Elastic/unlicensed source code. A capability is considered implemented only
when its typed contract, durable behavior, authenticated API, and regression test
all exist.

## Runtime and boundaries

- Keep the existing FastAPI, Pydantic v2, React 19, and Vite application stack.
- PostgreSQL 16 with SQLAlchemy async sessions is now the authoritative profile for
  users, global capabilities, elements, memberships, orders, and billing ledgers.
  Existing SQLite project/workflow repositories remain a documented migration
  boundary until their separate parity task is complete.
- Provider submissions are never performed by tests or background recovery. Paid
  execution requires server-side environment credentials and an explicit budget.
- Upstream behavior under AGPL, Elastic License, or missing licenses is reproduced
  through original interfaces and tests only. Apache/MIT/CC BY material keeps its
  required notices.
- Stochastic media quality is fail-closed: an output that has not passed automated
  measurements and signed human review is not marked accepted.

## Increment A: review workbench

Acceptance criteria:

1. Any project artifact can receive append-only review decisions (`request_changes`,
   `approve`, `reject`) with reviewer, comment, structured checks, and timestamp.
2. Approvals are rejected for stale artifacts; the artifact status follows the
   latest decision, and review history cannot be overwritten.
3. Owner isolation is enforced in repository and API tests.

## Increment B: dual-track canvas and Director World

Acceptance criteria:

1. A project stores a versioned graph of positioned nodes and typed edges.
2. Nodes are explicitly `mainline` or `freezone`; promotion to mainline records the
   source node, target artifact kind, and optimistic canvas version.
3. Director World stores metric anchors, actor blocking, camera poses, lens/focus,
   axis, and a continuity state. Camera/actor references must point at existing
   anchors and a generated frame plan is deterministic.
4. This is a production planning contract, not a false claim of neural 3GS
   reconstruction. A real 3GS/360 renderer stays behind an explicit capability
   flag until a GPU-backed implementation passes visual tests.

## Increment C: task center and recovery

Acceptance criteria:

1. A worker acquires one queued job using an atomic lease, increments attempts once,
   heartbeats the lease, appends bounded logs, and releases it through a legal state
   transition.
2. An expired running lease is recovered to queued only while attempts remain;
   otherwise it becomes failed. A provider task ID remains durable across recovery
   so polling does not duplicate a paid submission.
3. Cancellation is cooperative and visible before the next provider action.
4. No recovery path itself calls an external provider.

## Increment D: archive and cost ledger

Acceptance criteria:

1. Estimated, reserved, and actual costs are recorded by project, episode, shot,
   provider, operation, currency, and idempotency key. Summaries never mix currencies.
2. A project archive is a deterministic ZIP containing a versioned manifest and
   SHA-256 checksums. Import rejects traversal, links, undeclared files, duplicates,
   oversized entries, and checksum/schema mismatches before writing any project.
3. Export followed by import preserves artifacts, review history, canvas, Director
   World, and costs while assigning a new owner/project identity.

## Increment E: Video Shotcraft compatibility

Acceptance criteria:

1. The source registry reflects the reviewed catalog advertised at commit
   `41ee360`: 152 recipe cards, 209 style/motion previews, and 149 SFX across 16
   categories.
2. A typed catalog adapter can inspect an optional Apache-2.0 checkout, expose recipe
   metadata without executing JavaScript, and reject a checkout without the license.
3. Recipe selection compiles to the canonical shot/transition/audio plan. A future
   Remotion renderer consumes that plan; catalog discovery alone is not called a
   completed renderer.

## Increment F: complete local sd25-pe prompt contract

Acceptance criteria:

1. Generation, edit, and extension remain mutually exclusive primary tasks.
   A requested edit-then-extension is compiled into two ordered prompts rather than
   one ambiguous prompt.
2. Every material receives one declared responsibility; used and unused materials
   are explicit. Missing referenced materials fail before provider submission.
3. Edit has exactly one master, closed visual/audio scope, and timeline inheritance.
   Audio-only edits preserve picture, phoneme timing, and synchronization.
4. Extension inherits boundary picture, audio, motion, topology, identity, and state.
5. First/last frame sentences remain exact, generation parameters remain outside the
   prompt, storyboard reading order is explicit, and blockout overlays are excluded.

## Verification commands

```bash
cd backend && ../.venv/bin/python -m unittest discover -s tests -v
cd frontend && npm run lint && npm run build && npm audit --omit=dev
rg -n --hidden --glob '!*.sqlite*' --glob '!node_modules/**' 'sk-[A-Za-z0-9_-]{20,}' .
```

Real-provider canaries are a separate, explicitly budgeted release step using newly
rotated credentials. They must never use credentials copied from task text.

The admin/capability/element/user/billing increment is specified in
`tasks/platform-completion-spec.md` and supersedes earlier “no default admin” and
“PostgreSQL later” assumptions where they conflict.

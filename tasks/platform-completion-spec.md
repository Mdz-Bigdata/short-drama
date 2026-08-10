# Platform completion specification

Date: 2026-08-09
Status: implementation contract

## Outcome

The existing FastAPI/React studio becomes a PostgreSQL-backed product surface with:

1. an administrator-controlled global capability registry for all 13 audited
   upstream sources;
2. capability-level enable/disable controls and allowlisted `/command` invocation;
3. an element library with separate actor, prop, scene, and effect routes;
4. actor five-view uploads, safe media uploads, regeneration requests, and version
   history;
5. a user center with profile, password, role, status, membership, wallet, and
   order views;
6. an append-only billing ledger, payment orders, sandbox confirmation, and signed
   idempotent webhook handling;
7. a configured local-development bootstrap administrator that must change its
   password and whose public default is rejected in production.

This increment does not make a provider call, charge a payment method, or claim a
stochastic media output has passed a human quality gate.

## Runtime baseline

- Python 3.13/3.14 compatible FastAPI 0.136 and Pydantic 2.13.
- SQLAlchemy 2 async sessions with the `postgresql+asyncpg` dialect.
- PostgreSQL 16 database `short-drama` is the authoritative profile.
- React 19, TypeScript 6, and Vite 8 remain the browser stack.
- Existing SQLite/JSON production-project repositories are not silently presented
  as PostgreSQL-complete; this increment migrates users, global capabilities,
  elements, memberships, orders, and financial ledgers first.

## Data and security contracts

### Bootstrap administrator

- Stable local login: `admin@short-drama` (username `admin`) with the explicitly
  requested development password `admin@123` in the server environment template.
- PostgreSQL stores only the scrypt hash. Production startup rejects the public
  development password and requires an independently managed strong value when
  bootstrap is explicitly enabled.
- The account has role `admin`, starts active, and `must_change_password=true`.
- Bootstrap is idempotent and never overwrites an existing administrator password.

### Capability registry and slash commands

- Every upstream source and every declared capability receives a stable slug,
  label, allowlisted command, implementation entrypoint, and global enabled flag.
- Only administrators can mutate global flags. Any authenticated user can list the
  registry; only enabled capabilities can resolve or invoke a command.
- The parser accepts `/command` plus a text payload. It never evaluates shell,
  Python, SQL, URLs, or arbitrary internal imports.
- Duplicate/reserved commands fail database seeding and API validation.

### Element library

- `kind` is exactly `actor`, `prop`, `scene`, or `effect`.
- Actor records expose exactly five ordered view slots: front,
  front-three-quarter, profile, rear-three-quarter, and back. An actor cannot be
  marked ready until all five are present.
- Uploads use server-generated names, a strict media allowlist, magic-byte checks,
  byte limits, ownership checks, and non-executable storage.
- Regeneration creates an auditable queued request; it does not automatically
  submit a paid provider task.

### User center and billing

- Users can read/update their own safe profile and change their password.
- Administrators can paginate users and change role/status with last-admin guards.
- Wallet changes use append-only ledger entries with decimal amounts and unique
  idempotency keys. Stored balance is never accepted from the browser.
- Orders have immutable amount/currency/provider/user data. Sandbox confirmation
  and provider webhooks transition state transactionally once.
- Webhooks require HMAC signatures, compare the recorded order amount/currency,
  persist the event ID, and are idempotent. Browser redirect success is never proof
  of payment.
- WeChat/Alipay adapters remain disabled until merchant IDs, callback secrets, and
  signing certificates are configured server-side.

## API contract

All errors use `{ "detail": string }`. Collection endpoints return `items`,
`page`, `page_size`, and `total`.

- `GET /api/platform/capabilities`
- `PATCH /api/platform/capabilities/{source_id}/{capability_id}` (admin)
- `POST /api/platform/commands/resolve`
- `GET|POST /api/elements`
- `GET|PATCH /api/elements/{element_id}`
- `POST /api/elements/{element_id}/files`
- `POST /api/elements/{element_id}/regenerate`
- `GET|PATCH /api/users/me`, `POST /api/users/me/password`
- `GET|PATCH /api/admin/users/{user_id}` and paginated `GET /api/admin/users`
- `GET /api/billing/plans`, `GET /api/billing/wallet`,
  `GET|POST /api/billing/orders`
- `POST /api/billing/orders/{order_id}/sandbox-confirm`
- `POST /api/billing/webhooks/{provider}`

## Browser interaction contract

- Clicking a source card expands a keyboard-accessible list of all abilities.
- Each ability shows its `/command`, implementation entrypoint, and global state;
  administrators can toggle it with an accessible switch.
- A command palette accepts `/`, filters enabled commands, inserts a selected
  command, and returns the resolved ability before execution.
- Clicking “元素” exposes four options. Each opens a dedicated route-like view with
  search, status, add/upload, detail, regenerate, and back navigation.
- User and payment centers are available from the account menu and display role,
  password-change state, membership, wallet ledger, plans, and orders.

## Test-first acceptance

1. Repository tests prove bootstrap idempotency, generated-password behavior,
   capability persistence, command allowlisting, five-view readiness, upload
   rejection, admin authorization, append-only ledger invariants, signed webhook
   verification, and payment idempotency.
2. API tests cover successful and forbidden flows with a temporary test database.
3. Component/runtime checks cover source expansion, switching, command selection,
   all four element pages, regeneration/upload, user center, and payment center.
4. The full existing backend suite, frontend lint/typecheck/build, dependency audit,
   secret scan, and live PostgreSQL smoke test pass.

## Explicit quality boundary

Character consistency, continuity, expression realism, performance nuance, and
dialogue rhythm are controlled by the existing typed asset/performance/continuity
gates and human approvals. No software can guarantee perfect generative media in
all inputs. The release must report measured failures and block unapproved outputs,
not label them “彻底解决” without evidence.

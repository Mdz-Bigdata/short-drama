# Threat Model: Unified AI Short-Drama Studio

## Assets

- Provider credentials, especially ElevenLabs and video-generation keys.
- User scripts, novels, unpublished media, generated assets, and project archives.
- Character likeness, voice identity, brand assets, and rights/provenance records.
- Paid-generation budget, provider task IDs, cost records, and payment balances.
- Authentication sessions, roles, external-agent keys, audit history, and project ownership.

## Trust Boundaries

### Dynamic model configuration

- **Boundary:** administrator browser -> model-configuration API -> third-party
  discovery endpoint. Threats include key disclosure, SSRF, DNS/private-address
  access, redirect abuse, oversized/malicious model metadata, credential probing,
  and globally enabling an unverified model.
- **Controls:** forced-password-change administrator authorization, HTTPS and
  provider-host allowlists, private/reserved IP rejection, redirects disabled,
  response/time/model-count bounds, safe upstream errors, Fernet encryption at
  rest, masked responses, append-only audit events, server-side re-discovery before
  save, and no paid generation during connection tests.

1. Browser/mobile client to application API.
2. Uploaded document, archive, image, audio, and video to parsers/media tools.
3. User-supplied or model-supplied URL to server-side fetcher.
4. LLM/model output to domain records, prompts, filenames, render parameters, or actions.
5. Application/worker to third-party text, image, video, TTS, SFX, music, and payment providers.
6. Queue/database to long-running workers and callback/polling handlers.
7. Plugins/external agents to project actions.
8. FFmpeg/Remotion/headless browser to the operating system and media storage.

## STRIDE Summary

| Threat | Representative abuse | Required control |
|---|---|---|
| Spoofing | Forged provider callback, stolen external-agent key, cross-project session use | Signed callbacks or polling, scoped hashed keys, secure sessions, MFA for sensitive operations, ownership checks. |
| Tampering | Altered asset versions, swapped terminal frame, edited cost/approval record | Content hashes, immutable artifact lineage, append-only audit events, signed submission descriptors, DB constraints. |
| Repudiation | User denies approving a paid run or voice generation | Timestamped approval event with actor, scope, budget, request fingerprint, and provider task IDs. |
| Information disclosure | API key in logs/browser/project export; unpublished script leaks | Server-only encrypted secrets, structured redaction, tenant scoping, private object URLs, generic errors, export allowlist. |
| Denial of service | Oversized media, decompression bomb, infinite agent loop, unbounded generation | Size/duration/frame caps, archive limits, timeouts, queue quotas, recursion/token/take budgets, cancellation. |
| Elevation of privilege | Viewer triggers generation, plugin accesses another project, development bootstrap admin remains reusable | RBAC on every action, scoped plugin capabilities, forced password change, production rejection of the public development default, bootstrap endpoint absent after initialization. |

## Critical Abuse Cases and Tests

### Secret theft

- The plaintext ElevenLabs key supplied in chat must never appear in repository files, fixtures, logs, screenshots, exports, exceptions, or frontend responses.
- Startup fails with a generic configuration error when the environment variable is absent.
- Provider request logging retains only provider name, request ID, cost metadata, and redacted key fingerprint.
- Rotate the exposed key before any real call.

### Prompt injection and unsafe model output

- Uploaded documents and fetched pages are content, never instructions with tool authority.
- LLM output is parsed into strict schemas and cannot directly execute SQL, shell, URLs, filenames, FFmpeg filters, or plugin actions.
- Unknown fields, unresolved asset IDs, invalid time ranges, and provider-unsupported modes fail closed.

### Malicious uploads and archives

- Verify magic bytes, allowlisted media/document types, size, duration, dimensions, frame count, and decompressed total.
- Parse PDFs/DOCX/FDX in isolated workers with CPU/memory/time limits.
- Reject path traversal, absolute paths, symlinks, nested archive bombs, active content, and unexpected executables.
- Media tools receive argument arrays and server-generated filenames, not concatenated shell strings.

### SSRF and unsafe remote media

- Remote imports permit HTTPS and an explicit provider/source host policy.
- Resolve and pin public IPs; reject private, loopback, link-local, multicast, reserved, and metadata addresses across IPv4/IPv6.
- Disable redirects or revalidate every hop; cap bytes and content type.

### Paid-generation abuse and duplication

- Every submission requires permission, project budget, actor budget, rate limit, and immutable idempotency key.
- Resume polls the recorded task; it never submits a replacement unless a new approved attempt is recorded.
- Retries are bounded per shot/provider and reserve cost before submission.
- Provider-side cost/request headers are persisted without sensitive headers.

### Likeness, voice, brand, and copyright abuse

- Store provenance and consent state for identity-bearing character, voice, product, logo, and reference assets.
- Require an explicit rights confirmation before voice cloning or commercial publication involving third-party likeness/brand assets.
- Block attempts to bypass provider safeguards or impersonate a real person without authorization.
- Export includes provenance/attribution manifest and unresolved-rights warnings.

### Cross-project and cross-user access

- Every project, artifact, task, cost record, object URL, archive, and external-agent call performs server-side ownership/role checks.
- Object storage uses private buckets and short-lived signed URLs bound to authorized objects.
- Import/export IDs are remapped and never grant access to existing records by guessed identifiers.

### Plugin and external-agent agency

- Plugins declare capabilities; default deny network, filesystem, provider submission, payments, and destructive actions.
- Destructive or paid operations require explicit confirmation and server-side policy checks.
- Limit tool calls, tokens, wall time, recursion, and total generation attempts.

### Payment and business modules

- Verify payment-provider signatures and amounts server-side; never trust browser success callbacks.
- Use an append-only balance ledger and idempotent webhook processing.
- Separate creative credits from monetary accounting and require admin audit for corrections.

### PostgreSQL and bootstrap administrator

- The explicitly requested development identity is `admin@short-drama` with public
  local password `admin@123`, `must_change_password=true`, and idempotent
  initialization. It is a development convenience, not a production credential.
- Store only its scrypt hash in PostgreSQL. Production startup rejects the public
  default and requires an independently managed strong password if bootstrap is
  explicitly enabled.
- Production startup fails closed without `DATABASE_URL`, a stable authentication
  signing secret, and a payment-webhook secret. Database errors never fall back to
  an unscoped JSON user database.
- Admin APIs require the database role on every request and protect the last active
  administrator from demotion or suspension.

### Global skills and slash commands

- Treat upstream skill names and model output as data. Commands resolve through a
  static allowlist and cannot select arbitrary module paths, SQL, shell, URLs, or
  filesystem targets.
- Only administrators may change global enablement. Changes are audited with actor,
  previous/new state, command, and timestamp.
- Disabled commands fail closed even if a client calls the implementation API
  directly through the command dispatcher.

### Project Markdown Skill management

- Custom Skill Markdown crosses an administrator/upload boundary but remains
  untrusted creative guidance. It is wrapped in a lower-priority project context
  and cannot grant tool, filesystem, network, payment, provider, authentication,
  or policy authority.
- Create, edit, upload, import, and enablement require an administrator who has
  completed the forced password change. Each mutation records actor, action,
  resource, version, digest, and state in the platform audit log.
- Single Markdown and ZIP imports have strict byte, entry-count, decompressed-size,
  UTF-8, extension, traversal, absolute-path, symlink, and executable guards. The
  service reads `SKILL.md` without extracting or executing archive contents.
- Markdown is stored as text and previewed without raw HTML. Skill front matter is
  metadata only; scripts, hooks, commands, module paths, and package lifecycle
  declarations are never executed.
- Enabled Skill context has a deterministic count/aggregate-size budget. Enabling a
  Skill that would exceed it fails closed rather than silently truncating guidance.

### Element uploads and regeneration

- Element kinds are an enum; media type is verified from content, not only filename.
- Upload size/count limits apply before buffering. Server-generated filenames stay
  below a dedicated media root; SVG/HTML/scripts and archive uploads are rejected.
- Regenerate endpoints create an internal request and never infer approval to spend
  provider budget.

## Security Release Gate

- No real secret in git history or staged diff; `.env*` ignored except placeholder examples.
- Authentication, authorization, ownership, and rate-limit tests pass.
- Upload/SSRF/archive/FFmpeg abuse tests pass.
- Dependency manager and lockfile agree; installs block unreviewed lifecycle scripts.
- No unmitigated reachable critical/high dependency finding.
- Provider fakes prove idempotency, redaction, bounded retries, and budget enforcement.
- CSP/HSTS/content-type/frame/referrer/permissions headers are verified in the deployed environment.
- Threat model is revisited when adding a provider, plugin capability, payment method, public sharing, voice cloning, or multi-tenant hosting.

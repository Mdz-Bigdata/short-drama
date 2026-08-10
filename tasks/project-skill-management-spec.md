# Project Skill management specification

Date: 2026-08-10

## Objective

Turn the `Skill: 普通分镜` control into a project-wide Skill management entry.
Administrators can create, upload, import, edit, enable, and disable Markdown
Skills. Enabled Skills are persisted in PostgreSQL and become part of every text
model system prompt without restarting the service.

## Contract

1. A Skill has a stable ASCII slug, display name, optional description, Markdown
   instructions, source type, SHA-256 digest, version, enabled state, audit actor,
   and timestamps.
2. `POST /api/project-skills` creates Markdown; `POST /upload` accepts one `.md`;
   `POST /import` accepts a bounded ZIP containing exactly one `SKILL.md`;
   `PATCH /{id}` edits Markdown metadata; `PATCH /{id}/enabled` toggles it.
3. Authenticated users can inspect the project Skill catalog. Only an administrator
   who has completed the first-login password change can mutate it.
4. Every enabled custom Skill has `/skill.<slug>` as its project command. Disabled
   Skills fail closed in both command resolution and model prompt compilation.
5. Mutations refresh an in-process runtime snapshot immediately. Startup hydrates
   the same snapshot from PostgreSQL. Model calls append the compiled snapshot to
   the system message behind an explicit non-override security boundary.
6. The UI exposes separate actions for new Markdown, `.md` upload, ZIP import,
   inline editing, save/cancel, and enable/disable. Markdown is edited and previewed
   as text; it is never rendered through unsafe HTML.

## Import limits

- Markdown: UTF-8, 1 byte through 128 KiB, no NUL bytes.
- ZIP upload: at most 2 MiB, at most 32 entries, at most 512 KiB decompressed.
- ZIP entries must be directories or Markdown files. Traversal, absolute paths,
  links, nested archives, executables, binary data, and multiple `SKILL.md` files
  are rejected before persistence.
- Skills are instructions, not plugins: imported scripts, shell commands, package
  lifecycle hooks, and arbitrary module entrypoints are never executed.

## Acceptance tests

- Admin create/edit/toggle survives a new database session and records versions.
- Non-admin mutation is rejected while catalog read remains available.
- `.md` upload and safe ZIP import work; invalid UTF-8, wrong extensions, traversal,
  links, executables, oversize data, and missing/duplicate `SKILL.md` fail closed.
- Enabled content appears in the exact system prompt sent by `ModelGateway`; disabled
  content does not. Slash-command resolution follows the same state.
- Component tests cover new, upload, import, edit, enable/disable, save, and cancel.


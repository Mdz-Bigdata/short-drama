# Prompt Template Full Integration Research

## Scope

This work treats the two user-supplied documents as behavioral inputs, not as
instructions to execute arbitrary scripts:

- `script-to-video-prompts.zip`, SHA-256
  `34f3e757ec2e34792f9bfef9c3c67e3acf18eed5dd221a530bf57cbc773fcd26`
- `~/.agents/skills/sd25-pe/SKILL.md`, reviewed in full on 2026-08-15

The ZIP contains 24 regular files. It has no absolute paths, parent traversal,
backslash traversal, or symlinks. Its Python files were inspected as reference
text only and were not executed. The source has no bundled root license, so the
project implements the observed behavior through new, first-party code.

## Behavioral split

`script-to-video-prompts` defines the project-level pipeline:

1. TXT, Markdown, DOCX, PDF, and FDX ingestion.
2. Script-element parsing and duration estimates.
3. Character, costume, prop, and visual identity extraction.
4. Scene, spatial, light, color, weather, and mood analysis.
5. Shot planning and exact nine-grid storyboards.
6. Character, scene, lighting, prop, effect, axis, eyeline, and state checks.
7. Prompt normalization and JSON, Markdown, CSV, XLSX, and HTML exports.

`sd25-pe` defines the final single-video prompt compiler:

- exactly one primary task per prompt: generate, edit, or extend;
- ordered edit-then-extend as two executable prompts;
- explicit, one-role-per-reference asset responsibilities;
- unused and missing reference handling;
- text, first-frame, first-and-last-frame, ordered keyframe, multi-reference,
  multimodal, nine-grid, blockout, edit, audio-edit, and extension modes;
- dialogue/speaker/audio binding and provider parameters outside prompt text;
- hard reference limits and no claims about inaccessible media.

## Existing project coverage and gaps

| Capability | Existing state | Closure in this feature |
|---|---|---|
| Safe multi-format text extraction | Present in `SourceIngestor` | Reused by file compile API |
| Typed screenplay elements | Missing | Add a source-bound parser and schema |
| Character/costume profiles | Partial, LLM-stage only | Add deterministic profiles and five-view prompts |
| Scene/light/color profiles | Partial | Add structured scene bibles |
| Exact 3x3 board | Present | Compile one exact board per parsed scene |
| Image/motion semantic parity | Present | Reuse immutable `ShotMotionContract` fingerprints |
| Full SD25 task modes | Partial | Add ordered keyframes, scope closure, notes, and route metadata |
| Consistency report | Partial | Add cross-shot character/scene/lighting/prop/effect checks |
| JSON/Markdown/CSV/HTML export | Not available for this artifact | Add escaped in-memory exporters |
| XLSX export | Not available | Add dependency-free safe XLSX serializer |
| First-class pipeline API | Missing | Add JSON and file compilation endpoints |

## Security decisions

- Never import or execute Python from an uploaded template ZIP.
- Continue using bounded DOCX/PDF/FDX ingestion with ZIP traversal, symlink,
  entity, encryption, size, and page-count checks.
- Escape all untrusted values in HTML and Markdown table cells.
- Prefix spreadsheet cells beginning with `=`, `+`, `-`, or `@` to prevent
  formula injection in CSV/XLSX viewers.
- Return exports in memory; do not accept arbitrary output paths.
- Keep model/provider parameters separate from prompt text.
- Never include API keys, endpoints, internal analysis, or filesystem paths in
  compiled prompts or export payloads.

## Acceptance criteria

- A single compile call produces parsed scenes, character five-view prompts,
  scene bibles, exact nine-grid boards, image/motion prompts with matching
  fingerprints, SD25-ready prompts, consistency findings, and requested exports.
- File compilation accepts all five documented source formats through the safe
  ingestion layer.
- Every board has exactly nine ordered panels and every panel includes character,
  scene, prop, effect, camera, expression, sound, start, and end state fields.
- Missing identity facts remain explicit review warnings; they are never invented.
- Tests cover parsing, five-view order, exact grids, SD25 integration, export
  escaping/formula hardening, API file ingestion, and failure-closed validation.

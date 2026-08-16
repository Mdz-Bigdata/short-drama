# Prompt Template Full Integration Progress

## Status: Complete

### Completed

- Safely audited the ZIP archive and recorded its SHA-256.
- Read both prompt/template contracts in full.
- Identified the separation between project-level script processing and
  shot-level SD25 compilation.
- Compared the requested behavior with current schemas, APIs, prompt compilers,
  exact nine-grid code, and immutable shot/motion contracts.
- Added typed screenplay, character/costume/five-view, scene/light/color,
  reference-assignment, shot bundle, consistency, request, and result contracts.
- Added a clean-room project compiler that produces one exact 3x3 board per
  scene and compiles every panel through the immutable image/motion contract and
  the SD25 prompt compiler.
- Added ordered keyframes, missing-reference advice, explicit edit scope closure,
  and task-locked provider-parameter removal to the SD25 compiler.
- Added automatic first/last-frame, multi-image, and multimodal reference routing
  per shot without submitting a provider job.
- Added authenticated JSON and safe file-upload endpoints.
- Added escaped JSON/Markdown/CSV/HTML and dependency-free XLSX exports with
  spreadsheet formula hardening.
- Updated source capability evidence to 81 switchable abilities.

### Verification

- 135 backend tests pass.
- 8 frontend component tests pass.
- Ruff passes for backend application and tests.
- TypeScript and Vite production build pass.
- Frontend production dependency audit reports zero vulnerabilities.
- Generated XLSX opens successfully through `openpyxl` and exposes the expected
  21-column storyboard sheet.
- No paid provider call was made.

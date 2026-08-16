# Universal Storyboard Director Research

## Overview

The user-provided universal storyboard prompt is treated as a behavioral product
specification, not as executable instructions. The project needs a storyboard
director that can compile one continuous shot into auditable production data,
single-frame prompts, adjacent-keyframe motion prompts, fixed 3x3 presentation
pages, and continuity evidence.

## Problem Statement

The existing script prompt pipeline always expanded a scene to nine populated
panels. That violates the new requirement that beat count follow actual narrative
need. The correct invariant is a fixed nine-cell presentation canvas, not nine
invented narrative events: unused cells remain blank and more than nine real beats
paginate.

## User Stories / Use Cases

- A storyboard artist supplies one shot and receives a gap-free timeline from
  zero seconds through the exact shot duration.
- Each real event has one start, readable keyframe, and end state.
- Every single-frame prompt is independently generatable and contains no positive
  collage/grid instruction.
- Every adjacent keyframe pair receives one motion-video prompt with exact start
  and end states.
- Verbatim dialogue remains unchanged and is used for timing/performance, not
  rendered as subtitles unless separately requested.
- A three-beat shot produces three populated cells and six blank cells; a ten-beat
  shot produces two 3x3 pages.

## Technical Research

### Approach Options

1. Keep generating nine semantic panels. This is backward-compatible but creates
   false story beats and is rejected.
2. Put placeholder `StoryboardPanel` objects into unused cells. This preserves
   array length but leaks fake camera/action data into downstream prompts.
3. Model real panels separately from the nine-cell presentation layout. This
   preserves narrative truth, supports pagination, and allows blank cells to stay
   content-free. This is the selected approach.

### Recommended Approach

Use a typed `StoryboardDirectorRequest` for the stable shot foundation and a
deterministic compiler for derived artifacts. Keep the full timeline, still
prompts, motion segments and grid cells in separate structures. The existing
script-to-video pipeline invokes the same compiler so direct API and automated
project generation cannot drift.

Time boundaries are calculated with decimal millisecond quantization. State
continuity is structural: beat `i + 1.start_state` is the exact string value of
beat `i.end_state`, not a loosely worded similarity check.

### Required Technologies

- Pydantic v2 contracts and cross-field validation.
- Existing authenticated FastAPI production router.
- Existing SD25 and shot-motion contract compilers.
- Standard-library Decimal, JSON and SHA-256; no new runtime dependency.

FastAPI's official file-upload guidance confirms that uploaded bodies should use
`UploadFile` and explicit bounded reads; the existing safe source-ingestion path
already follows that pattern: <https://fastapi.tiangolo.com/tutorial/request-files/>.

## Data Requirements

- Shot identity, duration, aspect ratio, frame rate and 3x3 layout.
- Characters, scene topology, prop states, timed verbatim lines.
- Global visual rules and character/scene/axis/light locks.
- Stable shot, color, dynamics, camera and transition designs.
- Natural narrative events, derived beats, stills, segments, pages and checks.
- A deterministic plan fingerprint for cache invalidation and audit.

## UI/UX Considerations

The API returns all thirteen requested deliverable groups in one result. A future
editor can render stable foundation sections once, a timeline for beats, one card
per still/video prompt and one 3x3 preview per page without reparsing prose.

## Integration Points

- `ProductionService` and `/api/production/storyboard-director/compile`.
- `ScriptPromptPipeline` for automatic scene compilation.
- `NineGridStoryboard` for variable populated cells and explicit empty slots.
- SD25 compilation and automatic reference routing through existing shot bundles.
- JSON/Markdown/CSV/XLSX/HTML project exports.

## Risks and Challenges

- Automatic beat extraction cannot infer unstated creative intent. Structured
  `events` therefore take priority; free-text parsing is only the fallback.
- Repeated source actions may be intentional. The compiler preserves source event
  cardinality and merely refuses to add filler events.
- Exact dialogue timing can overlap beats. The line remains verbatim in every
  overlapping beat rather than being truncated.
- Provider duration limits remain a later routing concern; this compiler does not
  make paid generation calls.

## Open Questions

- A visual timeline editor and drag-to-adjust beat boundaries can be added later.
- Frame-number and drop-frame timecode output can be added if delivery requires it;
  the present contract uses exact seconds and a declared target FPS.

## References

- User attachment: `pasted-text.txt`, reviewed as a specification on 2026-08-15.
- Existing project shot-motion and storyboard contracts.
- FastAPI request-file documentation linked above.

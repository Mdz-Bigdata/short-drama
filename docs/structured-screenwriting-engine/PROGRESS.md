# Structured Screenwriting Engine Progress

## Status: Complete

### Completed

- Reviewed the ArcReel screenwriting modules at the pinned revision and recorded the gap analysis against this project's free-text stage 2.
- Added the reading-unit, speech-rate and duration primitives, with shot durations derived from the project's own video-model ceiling.
- Added the two-stage contracts: a content schema (boundary, cast, verbatim `utterances`, source anchor, visual adaptation) and a visual-only schema merged by `scene_id`.
- Added anchor-based episode segmentation with punctuation-width tolerant matching and existence / uniqueness / ordering validation.
- Added the constraint checker with mechanical repairs, retry reasons and `needs_replan` flagging for dialogue that cannot fit the longest clip.
- Added JSON-constrained model calls with schema validation and reason-carrying retries over the project's free-text gateway.
- Added every prompt builder, with genre pacing read from the new `screenwriting-master` skill so prompt and skill share one text.
- Added per-shot content fingerprints and ordered plan editing, so an edited plan only re-authors the shots that changed.
- Wired stage 2 to the engine with a legacy fallback, projected the state into the existing screenplay text and breakdown, and rebuilt script continuation on the ledger.
- Added four screenwriting endpoints (state, episode, prompt preview, plan patch) and a "分集规划" panel in the Writer page.
- Registered the ported capabilities in the capability manifest and upstream provenance, and updated the ArcReel attribution row.
- Self-review fixes: API plan errors are readable strings (object details were being stringified to `[object Object]` by the client); an edit to unrendered plan fields (cast, scene / prop refs) still invalidates downstream assets; a shot already flagged `needs_replan` no longer blocks saving edits to other shots; the plan editor asks before archiving downstream work.

- Made the screenplay text novel-style prose: a prose stage tells each outline episode from its fixed plan (verbatim utterances checked, shot-list grammar refused, synthesized fallback), source-based episodes read as their verbatim source slice, the renderer emits `第N集 标题` plus the body, and the prompt preview gained a `prose` stage.

### Verification

- 811 backend tests pass (59 of them across the engine, the pipeline and the API).
- 353 frontend tests pass (11 of them in the screenwriting panel); `tsc -b` clean; ESLint clean on every new and edited file.

### Notes

- No ArcReel source, prompt text or schema is vendored; the behavior is reimplemented and the attribution row records that.
- Two pre-existing ESLint errors in `frontend/src/features/writer/scriptOutlineUtils.ts` (irregular whitespace) are untouched and unrelated.

# Structured Screenwriting Engine Research

## Goal

Port ArcReel's screenwriting capability into this project's Writer Agent (stage 2).

## Upstream review

Reviewed <https://github.com/ArcReel/ArcReel> at the pinned revision recorded in
`backend/app/data/upstream_sources.json`. Its license is AGPL-3.0 with additional
attribution terms under section 7, so no source file, prompt string or schema is
copied. What was studied is behavior; what was written is original code.

The upstream modules that carry the screenwriting behavior:

| Upstream area | Behavior |
|---|---|
| `lib/episode_planner.py` | Reads a source window from a cursor, asks the model for episodes, resolves each `end_anchor` back to an offset, rejects anchors that are missing, ambiguous or out of order, retries with the failure reasons |
| `lib/prompt_builders_script.py` | One prompt per stage; pacing rules injected from a shared reference; field guidance with a positive example and an annotated counter-example instead of a rule list |
| `lib/script_models.py` | Two-stage split: a content schema (utterances, source anchor, cast, duration) and a visual-only schema (`scene_id` + image/video prompts) merged by id; enum drift folded back, unknown values degrade |
| `lib/script_review.py`, `lib/draft_violation.py` | Failed constraints keep the draft as a repairable quarantine with a per-item violation report rather than discarding a paid generation |
| `lib/script_plan_entries.py` | Per-entry content fingerprints so an edited plan only re-authors the entries that changed |
| `lib/speech_rate.py`, `lib/text_metrics.py` | Reading units per language; a shot may not be shorter than the seconds its dialogue needs |
| `lib/script_batch_edit.py`, `lib/script_editor.py` | Ordered edit operations applied to a copy, validated as one aggregate, committed under an optimistic-concurrency token |

## What this project had before

Stage 2 asked one text model for the whole screenplay in free-form Markdown,
batched by contiguous episode runs, then asked a second model call to structure
that text back into shots. Consequences:

- The dialogue that reached production was whatever the structuring pass parsed back out of prose, not what the writer wrote.
- Shot durations were invented by the structuring model and clamped afterwards by `_enforce_shot_durations`; a shot whose dialogue could not be spoken in its duration was undetectable.
- Nothing recorded per-episode hooks or story beats, so a truncated script was continued from raw text tails.
- Editing a shot meant editing the screenplay text and re-running the structuring pass over everything.

## Gap analysis

| Capability | Before | After |
|---|---|---|
| Episode ledger (title / hook / beats / teaser) | absent | first-class, drives per-episode writing and continuation |
| Content vs. visual separation | one free-text pass, then re-parse | two schema-constrained passes merged by `scene_id` |
| Verbatim dialogue | parsed out of prose | authored as `utterances`, carried through untouched |
| Source fidelity | none | `source_text` anchor per shot; verbatim enforcement for uploaded screenplays |
| Duration legality | post-hoc clamp | shot duration constrained to the video model's own tiers, in the schema |
| Dialogue fits duration | unchecked | speech-rate lower bound, auto-raised or sent back for a re-split |
| Incremental editing | rewrite everything | per-shot content fingerprints; only changed shots are re-authored |
| Prompt auditability | none | dry-run endpoint returns the exact prompt for a stage, no model call |

## Constraints taken from this project

- Shot duration tiers come from `app.core.video_references.max_shot_seconds`, which already maps each video model to its single-generation ceiling.
- The screenplay text and `2_breakdown` remain the pipeline's interfaces: stages 3 to 8, the Writer dashboard and the episode splitter read them unchanged.
- The model gateway returns free text with no structured-output parameter, so JSON constraints are enforced in the prompt plus validation plus reason-carrying retries.
- Knowledge sources (golden narrative structure, dialogue pacing, performance detail) stay a single source of truth in the repository root and are budgeted into the Writer's system prompt.

# Structured Screenwriting Engine Implementation

## Architecture

```text
总导演策划 / 上传剧本 / 小说原文
  → Overview            项目概述（作品名 / 题材 / 主题 / 梗概 / 世界观）
  → AssetInventory      角色 / 场景 / 道具（只含视觉描述）
  → 分集账本 LedgerEntry[]   每集标题 / 集尾钩子 / 故事节点 / 下集预告
  → 逐集：
       ScriptPlan       分镜内容层：边界 / 时长 / 出场资产 / 逐字 utterances / 原文锚
       Prose            小说体正文：按定稿分镜写成的叙述段落 + 引号对白（纯文本，仅 outline 模式）
       VisualScript     视觉层：image_prompt / video_prompt（仅按 scene_id 对齐）
       → merge_visual_into_scenes → EpisodeScript
  → renderer            → assets["2"] 剧本正文（小说体）+ assets["2_breakdown"] 结构化大纲
```

The engine is I/O free: it takes `caller(system, user, max_tokens) -> str` and
returns a plain state dict. `app/service/screenwriting_service.py` binds it to
the task's model gateway and persists the state at `assets["2_screenwriting"]`.

## Modules (`backend/app/core/screenwriting/`)

| Module | Responsibility |
|---|---|
| `text_metrics.py` | Reading units per language (CJK characters, Latin words) |
| `speech_rate.py` | Seconds a spoken line needs; the single source for every duration check |
| `durations.py` | Legal shot durations from the project's video model; episode target volume and its soft-target wording |
| `pacing.py` | Genre pacing rules, read from `backend/skills/screenwriting-master/references` |
| `models.py` | Pydantic contracts for every stage, enum drift folding, and the merge by `scene_id` |
| `anchors.py` | `end_anchor` → episode boundary, with punctuation-width tolerant matching |
| `violations.py` | Content constraints, mechanical repairs, and the retry reasons |
| `entries.py` | Per-shot content fingerprints and staleness evaluation |
| `structured_llm.py` | JSON extraction, schema validation, reason-carrying retries; `call_text` runs the same loop for the plain-text prose stage |
| `prose.py` | Prose normalisation, the prose-vs-plan check (verbatim utterances, no shot-list grammar), and prose synthesis from shots |
| `prompts.py` | Every prompt builder |
| `editing.py` | Ordered plan operations (`update` / `insert_after` / `move_after` / `remove` / `split`) |
| `renderer.py` | State → prose screenplay text and `2_breakdown` |
| `engine.py` | Orchestration |

## Three source modes

| `source_kind` | Input | Wording |
|---|---|---|
| `outline` | Director plan only | 按分集大纲**创作** |
| `novel` | Prose source | 把原文**改编**为分镜内容 |
| `screenplay` | An author's finished script | 从剧本中**提取**，台词逐字保留 |

`novel` and `screenplay` slice episodes on verbatim `end_anchor` snippets: an
anchor that is missing, appears more than once, or does not advance past the
previous episode is rejected and its reason goes back to the model. Matching
first tries byte equality, then a punctuation-width and whitespace fold that is
strictly one character to one character, so a folded offset is a real offset.

## Screenplay text is prose

`assets["2"]` is what a person reads, so it is a novel-style body under one
`第N集 标题` line per episode: one paragraph per line, one blank line between
paragraphs, dialogue inside “” with the speaker's action around it. Scene / shot /
duration labels, `角色：台词` lines, bracketed stage directions and shot ids never
appear in it; shot boundaries, camera work and durations live in the structured
state and `2_breakdown`, which is what the dashboard and stages 3 to 8 read.

| `source_kind` | Body of an episode |
|---|---|
| `outline` | Authored by the prose stage from the fixed plan, stored as `episodes[n].prose` |
| `novel` / `screenplay` | The episode's own slice of the source, verbatim; a slice that already carries its `第N集` heading is not given a second one |
| state written before the prose stage existed | Assembled from the shots (`prose_from_scenes`) |

The prose stage answers in plain text and is checked against the plan it was told
from:

| Finding | Handling |
|---|---|
| A plan utterance whose words do not all appear in order (a line may be split around an action beat at its own punctuation) | sent back with the line named |
| A label line, a shot id, a `角色名：台词` line, a `第N集` line, a body too short for its shots | sent back |
| Quoted speech no utterance contains, a bracketed stage direction | one retry, then kept with a `prose_unverified` warning |
| Retries exhausted with a hard finding | body assembled from the shots, `prose_fallback` warning |

## Constraint handling

Nothing is discarded on a constraint failure:

| Violation | Handling |
|---|---|
| Wrong episode prefix or malformed `scene_id` | rewritten to the current episode, recorded as a warning |
| Dialogue speaker missing from the cast | added to the cast and registered as a character asset |
| Duration outside the model's tiers | snapped to the nearest legal tier |
| Dialogue longer than its duration | raised to the smallest tier that fits |
| Dialogue longer than the longest clip | sent back to the model to split; if retries run out the shot is kept and flagged `needs_replan` |
| A rewritten line in `screenplay` mode | sent back with the verbatim requirement |
| Duplicate `scene_id` | sent back |

Visual-layer coverage is validated the same way: a batch that misses a shot,
invents an id or repeats one is retried with the exact ids named. If retries run
out, only the uncovered shots get a mechanically synthesized prompt, and each one
carries a `visual_fallback` warning.

## Incremental editing

Every finished shot stores the fingerprint of the plan entry it was authored
from. `PATCH /screenwriting/episodes/{n}/plan` applies ordered operations to a
copy, validates the aggregate, then re-authors only the shots whose content
fingerprint changed. Unchanged shots keep their prompts. The episode's prose is
told again only when a field it is written from changed (setting, description,
utterances, shot order); an edit to cast or asset references keeps it. The edit goes through
the existing `update_script` path, so the screenplay archive, downstream
invalidation and the confirmation gate all behave as they do for a manual edit.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/drama/{task_id}/screenwriting` | Ledger, inventory, duration constraints, per-episode status |
| `GET /api/drama/{task_id}/screenwriting/episodes/{episode}` | Editable plan plus the authored script |
| `GET .../episodes/{episode}/prompt?stage=plan\|prose\|visual` | The exact prompt a stage would send; no model call |
| `PATCH .../episodes/{episode}/plan` | Ordered edits with an optimistic-concurrency `baseRevision` |

## Compatibility

- `assets["2_breakdown"]` keeps its shape and `assets["2"]` keeps its `第N集` headings, so stages 3 to 8, the Writer dashboard and the episode splitter are unchanged; none of them parses shot labels out of the text when a breakdown exists.
- The legacy free-text engine still writes its labelled `场景N：` / `镜头：` format: its shot list is cut from those headings, so prose there would collapse an episode into one shot.
- Projects written before this change have no structured state; the state endpoint reports `available: false` and everything else behaves as before.
- `WRITER_ENGINE=legacy` selects the previous free-text engine. The structured engine also falls back to it on failure unless `SCREENWRITING_FALLBACK_TO_LEGACY=0`.
- A manual screenplay edit marks the structured state stale; the plan editor refuses to operate on a stale state and asks for stage 2 to be re-run.

# Upstream Capability and License Matrix

Audit date: 2026-08-15. Commit hashes pin the behavior reviewed during planning; upstreams may change later.

| Source | Reviewed commit | Capability parity required | Integration treatment | License observation |
|---|---|---|---|---|
| [MiniMax-H3 skills](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills) | `6da473b` | H3 T2VA/I2VA/FL2VA/L2VA/Ref2VA prompts; multi-image/video/audio reference labeling; first/last frames; 3D animation short, brand promo, co-op intro, hand-drawn/live-action blend, minimalist product ad, lyric MV, paper collage, and papercraft explainer workflows. | Original provider adapter and preset definitions; model/API access remains optional. | No root GitHub LICENSE file observed at the reviewed revision; model/API terms remain separate and must be verified before use. |
| [drama-skills](https://github.com/worldwonderer/drama-skills) | `bc04019` | Project router/lifecycle; traceable adaptation; long-novel triage; resumable multi-episode intake; reference-backed voice direction; output/prompt language contract; episode maps; screenplay; assets; lookdev; storyboards; prompts; independent review; local dashboard. | Adapt MIT-licensed concepts with attribution; enforce media-generation approval gates. | MIT. |
| [facial-expression-prompting](https://github.com/zhouwei713/facial-expression-prompting) | `a3236cc` | Motivation-first acting chain; microexpression/body/breath/voice timelines; adaptive duration; performance-only and audit modes; camera/light support; identity and negative constraints. | Adapt into canonical `PerformancePlan` and shot validation. | MIT. |
| [visual-skills](https://github.com/smixs/visual-skills) | `3c55471` | Dramaturgy, motivated camera, Murch-style edit priorities, detail audits, model-native Seedance/Kling/Veo prompts, Nano Banana/GPT Image direction, prompt audit, stitched continuity, storyboard and animatic keyframes. | Adapt with required author attribution and NOTICE. | CC BY 4.0; retain credit to Serge Shima and source URL. |
| [DramaClaw](https://github.com/dramaclaw/dramaclaw) | `5ae9c3f` | Novel/story graph; character/scene/prop/voice asset library; episode planning; review loops; grid/first-frame generation; TTS; assembly/export; infinite dual-track canvas; Freezone text/video operations, asset folders and outline; spatial world/3GS; assistant; styles; task resume. | Clean-room behavioral parity behind original interfaces. Do not copy service code. | Elastic License 2.0; hosted-service restriction applies to copied upstream code. |
| [InstantVideo](https://github.com/briefness/InstantVideo) | `079e276` | Compiled production plan; action contract; strictly sequential generation; accepted-tail handoff; readiness and provider capability checks; structured failure evidence; production analytics; visual invariants; semantic QA; recovery/budgets; normalization, transitions, BGM, TTS, LUT, subtitles, and export. | Adapt MIT architecture patterns; implement provider-neutral version. | MIT. |
| [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) | `0d6f0b5` | Remotion product-video pipeline; 152 shot cards, 209 style/motion previews, 149 SFX across 16 categories; 2.5D camera; typography, transitions, beat sync, BGM/SFX, deterministic demos, headless rendering, and Jianying draft export (Mac tested upstream, Windows path supplied upstream). | Import/port Apache-licensed recipes and components with NOTICE; wrap as selectable templates. Audit bundled media rights separately. | Apache-2.0; individual media assets/attributions require separate review. |
| [FastMovieAI](https://gitee.com/yc_open/FastMovieAI) | `31c324c` | Full creation platform; character management; TTS; screenplay/storyboard UI; user/auth/VIP; points; Alipay/WeChat pay; WeChat integration; content management; plugins; multilingual UI; WebSocket task progress. | Use product capability list; implement first-party modules in approved stack rather than adopting PHP/Vue stack. | Apache-2.0 at reviewed root. |
| [ArcReel](https://github.com/ArcReel/ArcReel) | `8f9cd89` | Novel/script/product inputs; assets and continuity; human gates/version rollback; artifact source/status tracking; multi-provider text/image/video/TTS including H3/Seedance 2.5/Wan 3; durable queues; costs; final/Jianying exports; archive; agent API; auth and production DB. | Clean-room behavioral parity. Do not copy AGPL service/UI code unless the entire distribution decision changes. | AGPL-3.0 plus NOTICE/additional terms. |
| [script-to-shot-engine](https://github.com/jiayushi1-ux/script-to-shot-engine) | `e139226` | Action and dialogue confrontation modes; causal chains; long-scene clip splitting; six-slot style lock; asset anchors; continuous timestamps; lens/aperture and bilingual camera terms; state continuity. | Clean-room reimplementation of observed behavior. | No root LICENSE file at reviewed commit. |
| [script-to-video-prompts](https://github.com/Morris1029/script-to-video-prompts) | `0616b73` | DOCX/PDF/TXT/Markdown/FDX parsing; character/costume extraction; scene/light/color analysis; shot generation; consistency checking; prompt optimization; Markdown/JSON/CSV/Excel/HTML export. | Clean-room implementation unless license is clarified. | README says MIT, but no root LICENSE file was present at reviewed commit. |
| [video-agent-skills](https://github.com/towardsyoung/video-agent-skills) | `916b1f8` | Chinese novel-to-short-drama adaptation; asset list; lightweight storyboard; 4-15s grouped platform-ready prompts with picture, movement, sound, and continuity constraints. | Clean-room implementation of workflow behavior. | No root LICENSE file at reviewed commit. |
| [short-drama-skills](https://github.com/YvonneMovingon/short-drama-skills.git) | `6d632fd` | Narrative breakdown; power-shift emotional dialogue; detailed action; episode continuity grouping; single-video polish; high-impact drama; slow cinematic emotion. | Clean-room callable presets in the production compiler; retain MIT attribution. | MIT. |
| [WeChat storyboard reference](https://mp.weixin.qq.com/s/rIhJjrGYdqhM9fcsa8BPQg) | Article fetched 2026-08-09 | Shot order, purpose, emotion distance, genre rhythm, and duration guidance used by the exact nine-grid rule engine. | Encode general directing principles and cite source; do not copy article images into the product. | Copyrighted article/reference images; principles are summarized, not redistributed. |

## Cross-source Capability Buckets

| Bucket | Sources | Acceptance evidence |
|---|---|---|
| Novel/source adaptation | drama-skills, DramaClaw, ArcReel, video-agent-skills | Traceable source spans, story graph, episode map, hook and screenplay fixtures. |
| Script and directing | drama-skills, script-to-shot-engine, script-to-video-prompts, visual-skills | Typed shot plans, causal beats, coverage/rhythm validator, provider prompt snapshots. |
| Character performance | facial-expression-prompting, visual-skills | Motivation chain, compatible facial/body actions, exact timeline, camera response tests. |
| Assets and consistency | DramaClaw, ArcReel, drama-skills | Versioned role/scene/prop/effect packages, mandatory five-view sheet, staleness propagation. |
| Exact nine-grid storyboard | User contract, WeChat reference, ArcReel/DramaClaw grids | 3x3 geometry test, nine metadata-complete panels, lossless split/rejoin fixture. |
| Video reference modes | MiniMax H3, ArcReel | Capability negotiation and provider contract tests for T2V, I2V, FL2V, multi-image and multimodal refs. |
| Recovery and quality | InstantVideo, ArcReel, DramaClaw | Resume/idempotency fixtures, accepted-tail lineage, technical/semantic QA and bounded retry tests. |
| Natural assembly | InstantVideo, visual-skills, video-shotcraft | Continuity ledger, transition decision trace, motion/audio/color checks, human final-cut gate. |
| Voice/SFX/music | User contract, ElevenLabs, DramaClaw, ArcReel | TTS/SFX/music endpoint fakes, beat/ducking mix, secret redaction, cost headers. |
| Product and style presets | MiniMax skills, video-shotcraft, visual-skills | Preset registry and golden prompt/render fixtures for every listed family. |
| Workbench/platform | FastMovieAI, ArcReel, DramaClaw | UI E2E for projects, assets, storyboard, timeline, tasks, history, costs, settings, auth and optional commerce. |

## Attribution Requirements

- Preserve MIT and Apache copyright/license notices for reused source portions.
- Include the Apache-2.0 NOTICE chain for Video Shotcraft-derived code and separately verify every bundled audio/media asset.
- Include the CC BY 4.0 attribution: “Serge Shima — https://github.com/smixs/visual-skills” for adapted Visual Skills material.
- Maintain an in-product “Sources and licenses” page generated from a versioned source registry.
- Do not label clean-room parity modules as upstream code forks.

## Implemented evidence (2026-08-15)

- `backend/app/core/creative_presets.py`: 17 callable creative/compiler modes, including all nine reviewed MiniMax H3 families, all seven reviewed short-drama-skills modes, and sd25-pe production compilation.
- `backend/app/schema/production.py`: mandatory four-category asset catalog, ordered five-view contract, exact nine-panel board, H3 reference limits, and stable ordered reference bindings with role/priority/hash/provenance.
- `backend/app/core/preproduction.py`: source-hash-bound novel indexing, reproducible whole-book sampling, resumable episode slices, output/prompt language contract, and authorized reference-backed voice direction.
- `backend/app/core/production_evidence.py`: fail-closed readiness, redacted structured failure evidence, and deterministic acceptance/retry/cost/latency analytics.
- `backend/app/core/storyboard_assets.py`: physical five-view splitting and exact 3×3 board composition.
- `backend/app/core/providers/`: server-only MiniMax H3 and ElevenLabs adapters.
- `backend/app/core/continuity.py` and `backend/app/core/video_quality.py`: semantic transition planning and fail-closed visual/performance/audio acceptance decisions.
- `backend/tests/`: provider, contract, image geometry, continuity, quality, transition, skill, and preset regression coverage.
- `backend/app/platform/` and `backend/app/api/{platform,element,user,billing}_api.py`: PostgreSQL users, all 81 globally switchable slash-command abilities, per-ability evidence/status, source revision/license provenance, four-class element library, configured development admin bootstrap with a production default-password guard, memberships, orders, append-only ledgers, and signed idempotent callbacks.
- `frontend/src/features/`: expandable capability center, `/command` palette, actor/prop/scene/effect pages, user/admin center, and membership/payment center with component tests.
- The idempotent platform bootstrap reconciles the current 81-record capability catalog into PostgreSQL; the prior 66-record live smoke must be rerun after deployment restart before calling the live database updated.

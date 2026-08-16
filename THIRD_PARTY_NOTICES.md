# Third-party capability references and notices

This project uses original, clean-room application code to implement interoperable short-drama production behavior. It does not vendor the reviewed AGPL, Elastic-2.0, unlicensed, or model-weight code. Before redistributing copied upstream assets or code, review the exact upstream revision and its current license.

Exact reviewed revisions, dates, capability IDs, license observations, and attribution strings are stored in `backend/app/data/upstream_sources.json` and rendered in the capability center.

| Reference | Reviewed license observation | Treatment |
|---|---|---|
| MiniMax-AI/MiniMax-H3 | Model/community terms; no root repository LICENSE observed at the reviewed revision | API interoperability and original prompt contracts only |
| worldwonderer/drama-skills | MIT | Concepts adapted with source attribution |
| zhouwei713/facial-expression-prompting | MIT | Acting/performance concepts adapted with source attribution |
| smixs/visual-skills — Serge Shima | CC BY 4.0 | General cinematography principles adapted; attribution retained: https://github.com/smixs/visual-skills |
| dramaclaw/dramaclaw | Elastic License 2.0 stated by upstream | Behavioral reference only; no service code copied |
| briefness/InstantVideo | MIT | Workflow concepts adapted with source attribution |
| Vincentwei1021/video-shotcraft | Apache-2.0 | Behavioral/template reference; bundled media is not copied |
| yc_open/FastMovieAI | Apache-2.0 | Product capability reference; original FastAPI/React implementation |
| ArcReel/ArcReel | AGPL-3.0 plus upstream additional terms | Behavioral reference only; no service/UI code copied |
| jiayushi1-ux/script-to-shot-engine | No root license observed | Behavioral reference only |
| Morris1029/script-to-video-prompts | README states MIT; no root LICENSE observed | Behavioral reference only pending license clarification |
| towardsyoung/video-agent-skills | No root license observed | Behavioral reference only |
| YvonneMovingon/short-drama-skills | MIT | Seven creative modes reimplemented as original callable presets |

The storyboard directing rules also summarize general principles from the supplied WeChat article “7个AI短剧分镜规则：剧情、情绪、节奏、时长，一篇讲清镜头怎么拍”. Its article text and images are not redistributed.

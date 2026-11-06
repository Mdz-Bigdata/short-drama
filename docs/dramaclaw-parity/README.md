# DramaClaw parity

What DramaClaw (`dramaclaw/dramaclaw`, reviewed at `aedddae`, 2026-11-03) offers, and where this project stands on each item.

**Treatment: clean-room.** DramaClaw is under the Elastic License 2.0, which forbids offering the software as a hosted or managed service. This project has accounts and billing, so copying its code would tie that use to the licence. Everything here is written from its published descriptions; nothing is copied (see `THIRD_PARTY_NOTICES.md`).

**Its 3D director stage and interactive stories are not in its public repository.** Its README marks both "closed beta", and only the feature list and demo media are public. They were reimplemented from those.

Status: **done** = built and exercised in a browser against the real backend; **built** = built with tests, not exercised against a real model or provider; **missing** = not built.

## 3D director stage (Previz) → `frontend/src/features/directorDesk/`

| Capability | Status | Where |
|---|---|---|
| Grey-box scene from a reference image | built: UI and apply are done, the prompt has never met a real vision model | `core/spatial_stage/blockout.py`, `panels/BlockoutPanel.tsx` |
| Arrange props | done | existing, plus `elevation_m` |
| Multi-track timeline: action clips, follow clips, routes | done | `panels/ClipLane.tsx`, `lib/timelineClips.ts`, `lib/sampling.ts` |
| Focal length, sensor size, close-up tracking | done | `panels/CameraPanel.tsx`, `followPose` |
| Four-view layout, paced routes (m/s) | done | `three/OrthoViewport.tsx`, `lib/pathTool.ts` |
| Stills and recorded clips into canvas nodes | built: the node opens the desk; captures reaching downstream nodes was tested with a mocked API only | `features/canvas/` |
| Camera-cut track inside one shot | built: a 切机位 lane on the timeline cuts to any of the shot's candidate lenses for a stretch; the lens view, playback and a clip export follow it. Tested, not opened in a browser | `ShotTimeline.cuts`, `cutCameraAt` |

## Interactive stories → `frontend/src/features/interactive/`

| Capability | Status |
|---|---|
| Branch graph, variables, conditions, timed choices, playtest, analysis | done for a small graph; a large one has not been tried |
| HTML and ZIP player export | done: downloads checked, the HTML makes no external requests; playing it in a browser was only tested in jsdom and headless Chrome |
| AI planning from a brief | built: stubbed model |
| Per-segment video generation | built: 在画布上生成这一段 puts a first-frame node and a video node on the canvas, bound to the segment's shot when it shows one; the canvas runs and commits it. Stubbed provider |

## XiaHua canvas → `frontend/src/features/canvas/`

| Capability | Status |
|---|---|
| Pan, zoom, nodes, connect, autosave, minimap, bookmarks, previz node opening the desk | done |
| Running nodes, history, commit to project, agent tools | built: stubbed providers |
| Tool node: 24 one-step tools behind one node kind | the 5 free video tools and `upscale_image` / `grid_cell` ran for real (ffmpeg, PIL); the model tools run through the real route against stubs: `core/canvas_tools.py`, `service/canvas_tool_ops.py`, `features/canvas/ToolBody.tsx` |
| Image tools: redraw, outpaint, relight, multi-view, template edit, enhance, reverse-prompt, mark detection | built: prompts have never met a real model |
| Style wall of 45 looks | built: this project's own looks and wording, with colour swatches, not sample pictures: `data/style_wall.json` |
| Video tools: upscale, region erase, audio extract, frame extract, GIF | done, with limits: upscale is interpolation and erase is a fixed-position blur (`delogo`), neither is generative; both say so on the node |
| Voice isolation, shot analysis | built: ElevenLabs and a vision model, stubbed. Cut detection itself is real ffmpeg |
| One-click skills: sketch, first frame from context, set background, scene 360, frame review, beat plan (lays out as image nodes) | built |
| Generative video erase and upscale | missing: no provider path here does either. Video edit is the existing video node with a reference clip |
| Camera templates on a video node | built: the video node offers the recipe categories and a strength; the move is written round the prompt in the provider's words. Stubbed provider |
| Node types | its script, shot-table, web page and SVG nodes are tools (`script_write`, `shot_table`, `html_page`, `svg_art`): a page is only ever shown in a sandboxed frame, an SVG is reduced to shapes before it is stored. A shot table lays out as first-frame nodes. Stubbed model |
| Workflow agent: brief → validated plan → draft a person can edit → one-transaction apply → confirmed run → retry that reruns only what did not finish | done except the planning call: apply, upload, run, a real tool failure and a retry ran in a browser against the real backend; planning itself and paid steps used stubs. `core/canvas_workflow.py`, `service/canvas_workflow_service.py`, `features/canvas/WorkflowPanel.tsx`, agent tools `plan_canvas_workflow`, `apply_canvas_workflow`, `canvas_workflow_status` |
| Commands waiting in the open browser for approval, a receipt from the page, auto-run across a whole episode | missing: the embedded agent asks for confirmation in chat, and workflows stay on one canvas |

## Director World

| Capability | Status |
|---|---|
| 360° panorama generation, viewer, use as desk backdrop | built: `features/spatial/PanoramaPanel.tsx`, stubbed provider |
| Image → Gaussian splat set, splat viewer | missing. Needs apple/ml-sharp, whose licences restrict use: check them first. Its own NOTICE forbids bundling the weights |
| LLM-written voxel worlds | replaced by the blockout, which needs no generated code to be executed |
| Control frames (empty set, actor mask, composite) | done: 截图库 → 截图内容; checked in a browser, the mask reads 75% black / 21% white. A mask cannot become a first frame, but it can feed the 贴回人物 tool, which pastes the desk's cast onto a generated picture through it (tested with real pictures) |

## Series pipeline and assets

| Capability | Status |
|---|---|
| Fountain ingest | built: `ingest/fountain.py` |
| Task center with retry | done for the empty state; retry tested with stubs: `features/tasks/TaskCenter.tsx` |
| Image pool, grid split | built: `features/storyboard/ImagePoolPanel.tsx` |
| Element folders | built |
| Voice casting UI | built: ElevenLabs path only, no reference voice upload (no provider path supports it) |
| Recipes | built: 22 against its 60, agent access only, no UI: `data/recipes/` |
| Agent Kit | built: `agent-kit/short_drama_mcp.py` (doctor, config for Claude Code / Codex / JSON, a stdio bridge; standard library only) and a skill explaining the workflow. The user centre prints the Claude Code command beside a new token. Tested as a subprocess against a local server; not against a real MCP client |
| Other surfaces in its tree (companion, piko mini game, rewards, HTML artifacts, external skill conversion) | not reviewed in depth; not built |

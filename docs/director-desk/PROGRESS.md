# 3D Director Desk Progress

## Status: complete (P1–P7)

## Quick Reference

- Implementation: `docs/director-desk/IMPLEMENTATION.md`
- What it was modelled on, and the gaps: `docs/director-desk/RESEARCH.md`
- Substrate: `docs/spatial-stage/IMPLEMENTATION.md`
- Backend tests: `backend/tests/test_director_desk.py`, `backend/tests/test_director_desk_user_poses.py`
- Frontend tests: `frontend/src/features/directorDesk/**`, `frontend/src/features/workbench/ShotVisualWorkspace.test.tsx`

## Phase Progress

| Phase | Scope | Status |
|---|---|---|
| 1 | Additive stage model: poses, figures, landmark shape / rotation / model, candidate lenses, crowds, per-shot timelines | Completed |
| 2 | Desk operations (16 new, `move_camera.reset_move`, patch-level `solve`), film-back `frame_shot` | Completed |
| 3 | 14 camera move presets written as editable keys, easing in the key times, axis side kept | Completed |
| 4 | Desk interchange: landmark rotation / shape, figure and pose controls, candidate lenses, version 2 `timeline`; rotation / scale / pose import | Completed |
| 5 | Captures and saved poses: upload, apply / unapply into the stage-5 slots, stale marking, stage-5 gate | Completed |
| 6 | Frontend workspace (`frontend/src/features/directorDesk/`) | Completed |
| P3 | Posable figures: jointed mannequin (58 control keys, fingers), CC0 skinned humanoid with 10 scrubbed clips, two-bone IK with foot lock, pose panel, account-level saved poses, limbs → stage-5 prompt | Completed |
| P4 | Timeline, camera-move previs, blockout clip export: random-access sampling, timeline panel (keys, easing, 14 presets), playback, key-aware editing, deterministic `mediabunny` export, clip upload / apply | Completed |
| P6 | Element-library GLB set pieces with local import, per-scene backdrop, stage-5 entry with the applied still / clip, whole-crowd figure switch, interchange inside the desk, robustness pass | Completed |
| 7 | Provenance, notices, documentation | Completed |
| P7 | Second pass against the two product write-ups and director-desk 0.4.11: automatic repair of failing checks (`repair.py`, `repair_checks`, `GET …/repairs`, 检查 panel with 一键修正), drawn walk / camera routes (`paths.py`, `set_path`, the 路径 tool), depth stills and clips (`depth` capture flag, stage-5 wording, depth pass in the lens view), side-by-side 机位对比, set-piece `array_landmark` / `align_landmarks`, five presets from the articles, stage tools for the tool assistant / MCP (`get_stage_checks`, `edit_stage`, `repair_stage`) | Completed |

## Final numbers (P7, 2026-10-14)

| Check | Result |
|---|---|
| `cd backend && python -m unittest discover -s tests` | 1317 passed (19 new in `test_director_desk_repairs.py`, 1 in `test_embedded_agent.py`) |
| `ruff check app tests` | All checks passed |
| `cd frontend && npx vitest run` | 697 passed (89 files; the desk alone 271 in 27 files) |
| `cd frontend && npx tsc -b --noEmit` | clean for this round's files; two errors in `src/features/elements/*` belong to unrelated uncommitted work in the tree |
| eslint on every file of this round | clean |

Not verified in a browser: the local admin password the example config lists is rejected on this machine, so the
desk could not be opened against the live server; the stroke / orbit interaction, the depth pass and the thumbnail
renderer are exercised by tests and reasoning only and deserve a manual pass.

## Final numbers (P6)

| Check | Result |
|---|---|
| `cd backend && python3 -m pytest tests -q` | 993 passed |
| `cd backend && ruff check app tests` | All checks passed |
| `cd frontend && npm test` | 591 passed (77 files) |
| `cd frontend && npx tsc -b` | clean |
| `cd frontend && npm run lint` | 2 errors, both pre-existing in `src/features/writer/scriptOutlineUtils.ts` |

Bundle (`npm run build`), the chunks that matter — none of them in the entry chunk:

| Chunk | Raw | gzip |
|---|---|---|
| `index-*.js` (entry) | 318.85 kB | 97.72 kB |
| `three.module-*.js` | 725.24 kB | 184.88 kB |
| `src-*.js` (mediabunny) | 688.14 kB | 173.19 kB |
| `DirectorDesk-*.js` | 101.79 kB | 31.76 kB |
| `DeskViewport-*.js` | 47.56 kB | 13.62 kB |
| `LensViewport-*.js` | 5.41 kB | 2.61 kB |
| `GLTFLoader-*.js` | 45.58 kB | 13.46 kB |

## Session Log

### 2026-10-14 — P7: stability, comparison, routes, depth

- The two WeChat write-ups (万兴剧厂 2026-06-23, LUMI AI 2026-09-16) were read in the browser; they are the brief
  `RESEARCH.md` already describes. The five repositories were cloned again: four unchanged since review,
  `mangfufu/director-desk` at 0.4.11 (`f3afacf`). Its new behaviour (hand-drawn paths, depth video, staging
  arrays / alignment) is reimplemented from its descriptions; nothing is copied. It now has its own record in
  `upstream_sources.json` and the capability manifest (19 sources).
- **Repair.** `repair.propose(plan)` maps each failing check to operations: spacing → `geo.separate` and
  `move_actor`; facing → `orient_toward`; a scene that *opens* mirrored → the pair swap marks; subjects out of
  frame / hidden / lost by a move / lens inside someone / axis jump → `solve_camera` for those shots (one solve
  per shot however many checks name it); a named posture → `set_shot_override` carrying the override's other
  fields. A named walk is left to a person with the reason spelled out. Verified on a plan broken four ways at
  once: every check clears in one `repair_checks`. The desk previews through `GET …/repairs` and submits the
  returned operations through the ordinary PATCH, so 一键修正 is one undo.
- **Routes.** `set_path` takes 2–400 points, cuts corners once (Chaikin), resamples at even arc length (≤ 24
  keys), spreads the keys over `start_s…end_s` with the move easings (`eased_time` inverted, so a smooth walk
  has its equidistant keys far apart in time at both ends), and replaces that one track. A walker faces along
  the route, holds, or watches a point; a camera route looks at a subject or ahead, at its own height. A route
  past the end lengthens the shot unless the length was stated.
- **Depth.** A capture carries `depth`. A depth still is kept and downloadable but `apply` refuses it (a first
  frame is copied); a depth clip applies and `motion_inputs` appends `DEPTH_REQUIREMENT` (layers and motion
  only, colour from the text) while it is followed.
- **Set pieces.** `array_landmark` lays line / grid / ring copies with the original kept in place and names
  counted on (`书案 2`, `书案 3`…, skipping numbers already on stage); `align_landmarks` aligns centres or
  distributes evenly on x or z. 80 landmarks stays the cap.
- **Agents.** `get_stage_checks`, `edit_stage` (any operations, current revision when none is given) and
  `repair_stage` join the tool catalog, so the embedded assistant and MCP clients block a scene with the
  operations a person uses.
- Frontend: ChecksPanel, the path tool, depth capture and CameraComparePanel were built in parallel worktrees
  and merged (see the files under `panels/`, `lib/`, `three/`).

### 2026-09-19

- Extended `StagePlan` additively (`version` stays 1); a plan stored before the desk existed loads unchanged. The actor cap went from 60 to 200 for crowd arrays; a 197-person stage refreshes in about 15 ms because crowd members are skipped by the member × member occlusion pass as well as by the spacing and action checks.
- One field beyond the spec: `StagePlan.crowds` records each array's layout (rows, columns, spacing, centre, yaw, body type, seed) so `transform_crowd` is a rigid move plus re-spacing that keeps hand-nudged members. Crowd variation uses mulberry32 seeded with `seed + index` (four draws per member: sideways, depth, turn, height), verified bit-for-bit against the JavaScript generator so the desk can preview the same crowd.
- Extras are recognised by their `extra-NN` id; `remove_extra` refuses anyone from the script's cast. People who leave the stage are pruned from camera subjects, per-shot overrides and timeline tracks.
- `solve` on a patch: `false` promises no lens moves unless an operation names it, `true` re-solves every shot after the operations, omitted leaves it to the operations (the behaviour before).
- Camera moves leave `StageCamera` untouched and only write `timelines[shot].camera`. "auto" side picks the direction the axis bends least; a move is scaled down (1 → 0.15) until its subjects stay in frame; a dolly zoom's lens follows the distance actually reached after axis clearance.
- `use_camera` clears the shot's camera keys (they are world poses along the old lens's path).
- Director-desk export is `version: 1` for a still stage and `version: 2` with the jlmlh `timeline` once any shot is animated; shots are laid end to end in shot order and key positions use the same rig-body convention (1.82 m behind the lens) as the camera records. Import accepts both versions.
- Captures live under `assets["4_director_desk"]`; files are written to `MEDIA_DIR` under a server-made name (`desk_<task>_<scene>_<uuid>.<ext>`) and the type is decided by magic bytes. An MP4 whose `mvhd` says it is longer than 30 s is refused even when the form says otherwise.
- Stage 5: the literal `camera_start` / `camera_end` sentences only ever reach the stage-4 board prompt. What stage 5 carries of the measured lens is the `机位距…米、机高…米` clause of `blocking` (in the shot block and in the compiled motion prompt); that clause is what `director_desk.motion_inputs` withholds while a fresh clip is applied. A stale applied clip is dropped from `reference_videos` with a warning and the clause stays.
- `blockout_standin_limbs` belongs to `Sd25CompileRequest` (`script_prompt_pipeline` / `production_service`), which stage 5 of `DramaService` does not go through. `ShotBlockout.shows_limbs` is computed and exposed; nothing consumes it yet.
- Saved poses are stored per task, in the same asset key, as the data layout in the spec says (the spec's "account-wide" wording would need a user-level store).
- Backend: 979 tests pass (45 new); Ruff clean.

### 2026-09-20 — P3 posable figures

- Figures: `three/figures/{Mannequin,Humanoid,ActorFigure,FigureMarks}.tsx`; both viewports draw the cast through `ActorFigure`, and `actorsInShot` now carries the per-shot `pose`. The mannequin is one unit tall and scaled by `height_m`; `lib/mannequinRig.ts` holds the bone tree as data (shared by the component, the IK and the ground maths) and lifts the figure so its lowest contact (soles, knees, pelvis, chest, head, elbows, palms) sits on y = 0 — tested for all 20 presets × 4 body types.
- Presets are the upstream 20 with two deliberate changes: `body.offsetY` is dropped (grounding is computed) and several arm / kneel angles were re-tuned by eye for this rig's axes (wave, think, cross-arms, kneel-one, kneel-two, sit, crouch, lean, throw, push). Body types fold the upstream eight onto standard / slim / heavy / child; heavy and child narrow the big limb joints (×0.85 / ×0.8).
- IK (`lib/ik.ts`): the hinge is first opened by the law of cosines, then ≤ 10 CCD iterations (ball joint clamped in Euler ZXY, hinge clamped) with early exit under 5 mm; always solved from the grab snapshot. The result is written back as control keys in tenths of a degree — a whole degree at the wrist is already ~5 mm. One `set_pose` per gesture, with `shot_id` when「只改这一镜」is on or the shot already poses the actor.
- Humanoid: the GLB is extracted byte-for-byte (sha256 checked) from upstream's base64 package to `frontend/public/models/director-desk/humanoid-v1.glb` with its `NOTICE.txt`; one shared load, `SkeletonUtils.clone` per figure, freed with `disposeModelResources` when the last figure leaves. A clip's posture is written as the pose's `preset` so the backend's pose-aware height matches what is drawn.
- Saved poses moved to the user: the project has real identities (`PlatformUser`, cookie session), so the library is a `director_desk_poses` table behind `/api/director-desk/poses` (≤ 200, name ≤ 40, unique per owner, replace-by-name). The per-task endpoints still work; the desk uses the new ones.
- Limbs → prompts: `capture.ts` sets `shows_limbs` when a mannequin or humanoid is inside the frame; `director_desk.motion_inputs` appends `LIMBS_REQUIREMENT` only while a fresh limbed clip is applied; the capture record carries `warning` and the captures / pose panels show it. The desk only uploads stills so far (clips are P4), so the prompt gate is exercised by tests, not yet by the UI.
- `deskOperations`: `set_pose` / `set_figure` now preview and undo locally; `set_shot_override` keeps the per-shot pose in the preview, as the server does.
- Verified in a browser with a temporary fake-server harness (deleted): mannequin in director and lens views, 招手 preset, wrist dragged by IK (one PATCH), 左右镜像, humanoid 行走 clip and phase 0.5, a 1080×1920 still uploaded with `shows_limbs=true` and the warning shown. The browser driver could not move a native range input; the slider path was exercised by dispatching input events (two previews, then one `set_pose` on pointer-up).
- Backend 986 tests, Ruff clean; frontend 516 tests, `tsc -b` clean, lint shows only the two known writer errors.

### 2026-09-20 — P4 timeline, previs, blockout clips

- `lib/sampling.ts` (pure): six easings on the arriving key, per-channel sampling of whole-figure keys, shortest-arc yaw, `blendPose`, lens in mm → FOV, legacy `move` as two keys, gait / clip phase from `t` only; sampled values are rounded to 0.1 mm. `stagePlanAt` turns a sample back into a plan so both viewports, the rigs and the gizmo anchor need no second code path; a still stage comes back as the same object.
- `useDeskPlayback`: playhead on whole frames, loop, frame step; a frame delta is clamped at 0.25 s (a slept tab), anything shorter is played in full so a slow stage drops frames instead of running in slow motion. Stopping at the end is derived, not an effect.
- `TimelinePanel` replaces the placeholder (collapsible): duration 1–30 s with the last-key guard, fps 24 / 25 / 30, transport and `MM:SS:FF` timecode, camera track plus a track per keyed or selected actor, keys dragged on whole frames and never past a neighbour, click-to-select (jumps the playhead to the key), arrow / Delete on a focused key, copy / paste at the playhead, per-key easing, clear. Camera key = the sampled lens; actor key = place + facing + the *authored* pose (not a frame of the gait). Presets go to `apply_camera_move` as a barrier edit; there is deliberately no client-side copy of the preset maths.
- Key-aware editing: see IMPLEMENTATION. Found in the browser: a number typed in the inspector but not yet committed was sent on blur *after* a scrub had moved the playhead, and landed in the base plan; the ruler now blurs the active field before it seeks (tested).
- `lib/clipExport.ts` + `capture.enterDeliveryRender` (shared with stills). Export of a 5 s / 24 fps shot takes about a second on an M-series Mac.
- Backend: `set_timeline` names the key a shorter duration would cut off; clip uploads accept 24 / 25 / 30 fps only (the timeline can never be 60, and nothing else produces a desk clip; `fps = 0` stays "not stated" for stills and older clients); whole-pose keys round-trip (test). 988 tests, Ruff clean.
- `mediabunny` is MPL-2.0 on npm (1.58.1), not MIT as the plan assumed; it is used unmodified behind a dynamic import (its own ~690 kB chunk, loaded only on export). Recorded in `THIRD_PARTY_NOTICES.md`.
- Verified in a browser with a temporary harness (deleted) against a throw-away server on :8000 that ran the real `apply_operations` and the real `director_desk_service` on an in-memory task (deleted): push preset → 9 keys bunched by the smooth easing, path and key markers in the director view; scrub and play (stops at the end, key buttons off while playing, no PATCH); 沈砚 as a mannequin with the 行走 preset keyed at 0 s and 4.38 s, the second key moved through the inspector (the note said it was writing the key) — the figure walks between the marks with the stride changing per frame; a key dragged 2.50 → 2.75 s with real pointer events (one PATCH); duration 3 refused naming the 5.00 s camera key; export with 烧入角色名 → H.264 MP4 720×1280, 120 frames, 5.000 s, 1.79 MB (ffprobe), accepted by `validate_upload`, `shows_limbs` with the warning, plays inline; cancel at 88 % restored the 508×905 buffer and saved nothing; apply → `reference_videos` and the real `motion_inputs` dropped `机位距…米、机高…米` and appended the limbs sentence; an fps edit marked the clip 过期 and the gate refused it; undo put fps back. Not exercised by hand: dragging a figure with the 3D gizmo while on a key (the driver cannot hold a TransformControls handle; the same retarget path was exercised through the inspector and in `DirectorDesk.test.tsx`), the 统一白模色 option in a real export, and the WebM fallback (this browser encodes H.264). The embedded pane throttles `requestAnimationFrame` to ~2 / s, so real-time playback speed could not be judged there.
- Frontend 584 tests, `tsc -b` clean, lint shows only the two known writer errors.

### 2026-09-20 — P6 models, backdrops, stage-5 entry, robustness

- **Set-piece models.** `three/props/StageProp.tsx` picks between the primitive and `ElementModelProp`, so both viewports have one path. The GLB is fetched with the session cookie, parsed once per element however many pieces point at it (a refcounted cache, freed with `disposeModelResources` when the last one leaves) and scaled *uniformly* into the piece's `size` box — a model keeps its proportions and fills the box along its tightest side, lowest point on the floor, the piece's `yaw_deg` applied. Picking and the selection glow go through an invisible box, not the GLB's triangles. A fetch or parse failure falls back to the primitive with a 模型加载失败 note. The inspector's 绑定模型 lists the project's prop and scene elements that have a GLB (two listings joined), 解除绑定 clears it, and 导入本地 GLB/GLTF creates the element and uploads the model through the library's own endpoints. The element is created with `metadata.task_id` so the project-scoped listing shows it again — without that a freshly imported model is invisible to the picker that just imported it.
- **Backdrop.** `StagePlan.backdrop` is additive (`kind` / `color` / `url` / `yaw_deg` / `opacity`), written by one new operation `set_backdrop`, with the URL held to http(s) by both the operation and the model. It is drawn in the lens view only: a colour wash or a photograph on a camera-facing plane 120 m out, or an equirectangular sphere for a panorama. The picture is uploaded through the existing captures route as a new kind `backdrop` — same store, same delete, and different everywhere it matters: `shot_id` may be 0, it has its own room of 20 so it never costs a scene one of its sixty stills, `apply` refuses it, and a blocking edit does not date it.
- Two things were got wrong first and found only by looking at a delivered still. (1) The underlay was drawn with `depthTest: false` so it would always be behind — but a `transparent` material renders *after* the opaque pass, so it painted over every figure. It is depth-tested now and writes no depth, and sits far enough back to be behind any stage. (2) The texture came from an `ImageBitmap`, and the renderer ignores `flipY` on one: the backdrop arrived upside down. It goes through an `<img>` on a blob URL instead — which also keeps the lens canvas same-origin, so `toBlob` still hands back the still that was just rendered.
- A third was found the same way: switching kinds swapped one mesh's geometry and material props under the renderer, and the sphere drew black. The two shapes are keyed apart now.
- **Stage 5.** `ShotDeskPanel` sits on the shot's 分镜 / 视频 tab: it opens the desk on *that shot's own scene* with the shot preselected — the same stage the storyboard button opens, keyed by scene id — and shows the applied still and clip with a thumbnail, a 过期 badge and 取消应用. Closing the desk re-reads both the captures and the shot.
- **Crowds.** The pose panel now switches a whole array's figure, body type and colour in one `set_figure` (the backend already took `crowd_id`; P3 left the desk side out). The undo inverse is one operation per member with that member's own values, so an array whose members were switched one at a time comes back mixed the way it was — preceded by a restore of the array's own recorded body type, which the per-member operations then win over.
- **Interchange inside the desk.** 导出 3D 导演台工程 / 导出 CoStage 工程 / 导入工程文件 in the top bar. What no desk format has a field for travels as prose: a `notes` array naming the backdrop and every element binding. Import reads only positions, facings and lens poses, so a round trip leaves both untouched — asserted in both suites.
- **Robustness.** Esc now closes the desk once there is nothing left to back out of (WAI-ARIA wants a dialog dismissible; every edit is already saved by then, so nothing is lost), Tab is trapped inside the desk, the select tool moved to **V** and 1/2/3 pick the layouts, Space plays, and **?** opens a shortcut card. `prefers-reduced-motion` drops the stylesheet's transitions, stops the director view coasting after a drag, and stops a clip in the library playing itself under the pointer. Both canvases already had a `ContextLossGuard` and a read-only banner; those were verified rather than added.
- Pre-existing bug found while carrying the backdrop through a re-plan: `build_plan(blocking_from=…)` kept the crowd *members* but not the crowd *records*, so re-planning a scene that had a crowd failed validation outright ("every crowd member must belong to a crowd of the stage"). Both are carried now.
- Backend 993 tests, Ruff clean. Frontend 591 tests, `tsc -b` clean, lint shows only the two known writer errors.

### 2026-09-20 — P6 end-to-end run

Real backend (`backend/.venv/bin/python -u main.py`, Postgres) and real Vite, a registered account, a project opened
from the lobby, the desk opened from the storyboard button. Port 5173 was taken by another project, so the frontend ran
on 5174 and the backend was started with `ALLOWED_ORIGINS` extended to match; nothing else was changed. No generation
stage was run on purpose (one was started by a misclick on 恢复 and paused immediately — stage 1, text only, which fell
back to the offline engine; the fixture was rebuilt afterwards).

What the run showed, in order: an actor moved (rev 2) · a cube added (rev 3) · a camera added from the view (rev 4) ·
林夏 switched to a jointed mannequin and posed 招手 (rev 6) · a 推进 preset applied as 9 editable camera keys (rev 7) ·
a still taken (1080×1920) and a clip exported (`ffprobe`: H.264, 720×1280, 120 frames, 5.000 s, 602,582 bytes) · both
applied to shot 1, which put the still's URL in `sequence_images` and the clip's in `reference_videos` · a later
blocking edit (rev 8) marked both `stale`, left the URLs in place, and `motion_inputs` then refused the stale clip and
restored the measured lens clause · stage 5 showed both with 过期 badges and 取消应用, and its entry re-opened the same
scene at the same revision with shot 1 preselected · a backdrop uploaded and shown in the lens view only, absent from a
still taken with the toggle off and present with it on · a panorama with its seam turned to 90° · a skinned GLB refused
by the server in its own words ("当前场景与道具预览暂不接受骨骼 skin") and a clean GLB imported, bound, drawn in the
delivered still, unbound and restored by undo · a 12-person crowd switched to jointed mannequins in one operation and
returned by one undo · export → import round trip leaving the backdrop and the binding untouched.

Not exercised by hand: dragging with the 3D gizmo (the driver cannot hold a TransformControls handle; the same paths go
through the inspector and the tests), the WebM fallback, and `Enter` in a number field — the driver's key event does not
reach it, so every number was committed by blurring instead.

### Notes

- A blocking edit marks captures stale but does not remove their URLs from the shot slots; stage 5 filters stale clips at read time, and `unapply` / `delete` still work on a stale capture.
- A backdrop is the one capture kind that is never dated by a blocking edit and can never be applied to a shot.
- One desk still and one desk clip per shot: applying a newer one replaces the older one in the slot.
- Uploads, apply / unapply and delete are refused (409) while a stage is running, like spatial edits.

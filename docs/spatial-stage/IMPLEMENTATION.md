# Spatial Stage Implementation

## Overview

```text
剧本大纲场景 (cast / location / props / text)
  → planner            站位 · 轴线 · 地标（确定性，无模型调用）
      ├ side_memory    人物首次确立的画左 / 画右，跨场景沿用
      └ locations      同一地点的地标坐标，跨场景沿用
  → 分镜表提示词        【空间调度】站位先于分镜表告知表格作者
  → 分镜表 (LLM)        景别 / 机位角度 / 运镜 / 入镜角色 / 画面内容
  → coverage           每镜求解一个机位（景别 → 焦段 + 距离；角度 → 机高；始终在轴线既定一侧）
  → projection         人物在该机位画面里的区域 / 深度层 / 屏幕朝向 / 遮挡
  → prompting          composition · action_axis · eyeline · blocking（四句话都是测量值）
  → StoryboardPanel → ShotMotionContract → 分镜图提示词 / 第 5 阶段运镜提示词
  → validation         越轴 · 出画 · 遮挡 · 左右承诺 · 站位重叠 → 连续性自检 → 第 5 阶段门禁
```

Conventions: right-handed, Y up, meters, floor = XZ. Yaw in degrees, yaw 0 faces `+Z`,
`forward = (sin yaw, cos yaw)` — a three.js object's `rotation.y`. "Right" of any forward (a
person's right hand, a camera's screen right) is `(-f_z, f_x)`. A lens is a full-frame focal length
whose 36 mm side lies along the long side of the delivery frame.

## Modules (`backend/app/core/spatial_stage/`)

| Module | Responsibility |
|---|---|
| `geometry.py` | Ground-plane vectors, yaw, FOV ↔ lens, `visible_height` / `framing_distance`, pair / line / arc / circle / grid marks, overlap relaxation |
| `models.py` | `StagePlan` (actors, landmarks, axis, cameras, shots, checks), per-shot `ActorOverride` (entrance, walk, posture, offstage, `hold`) |
| `language.py` | Entrance / travel / posture verbs, read only inside the clause that names the character |
| `projection.py` | Perspective projection → screen region, depth layer, screen facing, 2D occlusion; shot-size classification |
| `axis.py` | Axis of action, camera side, neutral / moving / re-establishing bridges, illegal crossings |
| `coverage.py` | Shot intent → camera: establishing / relation / single / over-the-shoulder / reaction / insert / empty; angles; moves with end poses; `keep_side`, `fit_move` |
| `planner.py` | Principals, separation, side-by-side, supporting triangle, crowd, set pieces, gaze axis for a lone character, per-shot overrides, `refresh` |
| `validation.py` | The nine checks below |
| `prompting.py` | Panel sentences, frame positions, landmark bearings, scene bible, table brief |
| `operations.py` | Semantic edits, all-or-nothing, revision + 1 |
| `interchange.py` | Export to / import from the two desk formats |

`backend/app/service/spatial_stage_service.py` binds this to a task: storage under
`assets["4_spatial"]` (`scenes`, `side_memory`, `locations`), panel fields, director context,
`redraw`.

## Camera solving

| Shot | Camera |
|---|---|
| 2+ subjects | Square on to the axis from the established side; distance = max(size framing, width fit); swings ±18–52° within the side when someone would stand hidden behind someone else; pulls back until everyone is inside the frame. Two people never share a frame tighter than 中近景. |
| 1 subject with a partner | 32° off the axis toward the established side (25° for a close-up); swings wider when the lens would stand inside someone or the subject would be hidden; a lens pushed back keeps its size by lengthening. |
| 1 subject alone | Square on from the established side; candidates swing ±25–60° around the subject. |
| Over-the-shoulder | 1.1 m behind the partner, ≥ 0.34 m toward the established side; lens solved from the distance; never tighter than 中近景 so the shoulder really is in a 9:16 frame. |
| Nobody + a named set piece | Insert of the piece the description names first. |
| Nobody | Wide of the stage from the established side. |
| 顶拍 | Straight down, high enough for the footprint; neutral on the axis; frame-up is the established side, so left / right survive. |

**30-degree rule.** After the cameras are solved, a shot that repeats the previous one's people, a size
within one step, the same over-the-shoulder-ness and a lens direction less than 30° away
(`coverage.repeats_the_angle`) is solved again with `avoid_bearing`, which makes the solver prefer a
clear candidate at least 30° from the previous lens. If none is clear it keeps the clear one; the cut
plan reports what is left. Sizes are read from Chinese terms first, then whole-token shot-list
shorthand (`ECU / CU / MCU / MS / MLS / FS / LS / ELS`), then English phrases.

Moves (`push / pull / pan / track / follow / orbit / rise / fall`) get an end pose; none may leave
the established side, and `fit_move` shortens one until its subjects are still in frame when it ends.
A camera on someone who walks to their mark lands on the mark with them.

## Walks and holds

An `ActorOverride.position` is where someone *starts* a shot; they end it on their mark. A walk-up
(`走向 / 逼近`) starts 1.2 m behind the mark and a back-off (`后退`) starts up to 0.6 m in front of it,
never past the partner (two people who both back off share what is left above 0.4 m + 0.1 m). The
shots before the walk carry a `hold` override at the same start point — held for the whole shot — so
the cut into the walk does not jump anyone. One mark carries one move: someone who has already entered
or walked in the scene is not staged again, and a second walk stays unstaged rather than teleporting
them back to a start point.

## Checks

| Code | Severity | Meaning |
|---|---|---|
| `spatial_actor_spacing` | error | two marks closer than 0.4 m |
| `spatial_subjects_in_frame` | error | a shot's subject is outside its camera's frame |
| `spatial_axis_consistent` | error | a cut jumps the axis with no neutral / moving / re-establishing bridge |
| `spatial_screen_sides_stable` | error / warning | the pair is mirrored against the promised sides (error when the scene opens that way) |
| `spatial_move_keeps_subjects` | warning | a subject leaves frame by the end of a move |
| `spatial_subject_occlusion` | warning | a subject is hidden behind a nearer character |
| `spatial_facing_partner` | warning | a face-to-face pair is not facing each other |
| `spatial_camera_clearance` | warning | the lens stands inside a character |
| `spatial_action_changes_state` | warning | the table says someone walks / kneels, the stage did not change |

They join `StoryboardDirectorResult.continuity_checks` through
`StoryboardDirectorRequest.spatial_checks`, so an error reaches `audit_prompt_detail` →
`aggregate_scene_boards` → the stage-4 → 5 gate unchanged.

## Pipeline wiring

- `_generate_scene_board` plans the blocking before the table prompt and appends `table_brief`;
  after the table is audited it solves cameras, writes `shot["spatial"]`, and fills
  `camera_angle / lens_mm / composition / action_axis / eyeline / blocking` of each panel.
- `compile_storyboard_prompt_detail` reads `production_context["spatial"]`: measured
  `frame_positions`, anchored `SceneLandmark`s, `ContinuityLocks`, camera start / end, the scene
  bible as `spatial_structure`, and the checks.
- Stage 5 takes `ContinuityState.screen_direction` from the shot's measured axis side; tasks without
  a plan keep the old wording-based inference.
- Blocking is decided once per cast and set: a re-plan keeps the stored marks and only solves
  cameras again. `rebuild` derives it afresh.

## API (`/api/drama/{task_id}/spatial…`)

| Endpoint | Purpose |
|---|---|
| `GET /spatial` | Scene summaries, side memory, location set sizes |
| `GET /spatial/scenes/{scene_id}` | The plan; a scene without one is previewed and nothing is written |
| `PATCH /spatial/scenes/{scene_id}` | Ordered semantic operations pinned to `baseRevision` |
| `POST …/rebuild` | Discard edits, plan again |
| `POST …/redraw` | Send one finished scene back to stage 4 (board → pending, its clips stale) |
| `GET …/export?format=director-desk\|costage` | Desk project documents |
| `POST …/import` | Positions, facings, camera poses back from a desk document, matched by name / camera id |

Operations: `move_actor`, `place_relative` (reference `actor` / `camera` / `world`; `foreground` /
`background` need a camera), `face_pair`, `arrange_group`, `orient_toward`, `set_axis`,
`flip_camera_side`, `move_landmark`, `add_landmark`, `remove_landmark`, `move_camera`, `solve_camera`,
`set_shot_override`, `clear_shot_override`.

## Frontend (`frontend/src/features/spatial/`)

`StoryboardWorkspace` → 「空间调度」 opens `SpatialStageDialog`: shot list with axis badges, a
draggable SVG floor plan drawn from the master camera's side (left of the drawing is screen left),
a lazy three.js viewport with a director view and a camera view in the delivery aspect, the measured
sentences of the selected shot, the checks, and export / import / rebuild / redraw. three.js loads
only when a 3D view is opened.

## Compatibility

- Tasks without `assets["4_spatial"]` behave as before; `get` previews without writing.
- `assets["4_spatial"]` is a stage-4 key, so a script change invalidates it with the rest of stage 4.
- Panel schema, contract fingerprinting and the prompt-detail shape are unchanged; one optional
  request field (`spatial_checks`) was added.

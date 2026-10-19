# What the 3D Director Desk was modelled on

Two commercial products set the brief; four open repositories supplied the parts. This file records what
each contributed, what was taken and in what form, and — the part worth reading — where this desk still
falls short of what the brief asked for.

Licences and the file-by-file record of what was ported live in `THIRD_PARTY_NOTICES.md`. This file is
about *ideas and gaps*, not permission.

## The two products

Both are Chinese short-drama tools whose 3D 导演台 was written up publicly. Neither was run, decompiled or
copied; the write-ups describe a workflow, and it is the workflow that was reproduced.

**万兴剧厂 3D 导演台** and **LUMI AI 3D 导演台** describe the same six-part loop:

1. a 3D stage per shot, built from the script's blocking;
2. a director's view to arrange it beside a camera's view framed to the delivery aspect;
3. a screenshot library of what the camera sees;
4. 应用至分镜 — handing a screenshot back to the storyboard as a generation reference;
5. saved poses, reusable across shots;
6. camera moves laid out on a timeline and played back on the canvas.

## The four repositories

| Repository | What it is | What this desk took |
|---|---|---|
| [jiguang132/storyai-3d-director-desk](https://github.com/jiguang132/storyai-3d-director-desk) | MIT. A per-scene 3D stage of characters, set pieces and look-at cameras, with a director view, a camera view, pose presets and a `DirectorProject` JSON. | The shape of the whole thing: a scene as objects plus look-at cameras, two views side by side, per-scene scoping inside a host workbench, and the project format the desk exports and imports. Its pose-preset angle tables. Its UE mannequin GLB is *not* used — the figures here are procedural. |
| [lkhxxx123/jlmlh-3d-director](https://github.com/lkhxxx123/jlmlh-3d-director) | MIT, a fork of the above. | The jointed mannequin's proportions, the walk / run gait curves, the crowd array, the aspect-frame geometry, and the `timeline` block (`duration` / `tracks` / `cameraTracks`) that a version-2 export writes. |
| [mangfufu/director-desk](https://github.com/mangfufu/director-desk) | MIT; bundles Quaternius motions (CC0). | The animation machinery: easing channels sampled by random access, the 14 camera-move presets, film-back framing, oriented-box snapping, and the deterministic frame-by-frame clip export. Its CC0 humanoid GLB is reused with its NOTICE. |
| [GuiYi-Xi/monoform-previs-studio](https://github.com/GuiYi-Xi/monoform-previs-studio) | No licence — read only, nothing copied. | Descriptions of four things this desk then wrote for itself: finger joints, two-bone IK with a foot lock, whole-pose keys, and the reference underlay that became the backdrop. |

A fifth, [CoStage](https://github.com/cs68614-hash/costage), shaped the *spatial stage underneath* the desk
rather than the desk; see `docs/spatial-stage/IMPLEMENTATION.md`.

## The six requirements, and how far each got

### 1. A 3D stage per shot

**Built.** One `StagePlan` per *scene*, not per shot — the deliberate difference from both products. A scene's
blocking is one fact; a shot is a lens onto it. Every entry point (the storyboard's 3D 导演台 button, the
stage-5 shot panel) opens the same stage by scene id, with a shot preselected. Per-shot differences live in
`ActorOverride` (this shot re-marks someone) and `ShotTimeline` (this shot animates them).

*Gap:* a shot cannot hold set pieces of its own. Moving a prop moves it for the whole scene. Nothing in the
model prevents adding that; nothing asked for it yet.

### 2. Director's view beside the camera's view

**Built.** `DeskViewport` (orbit, picking, TransformControls, grid and face snapping, measure tool, the lens's
travel drawn as a path with a marker per key) and `LensViewport` (the delivery aspect, composition guides laid
over it in the DOM). Three layouts on 1/2/3.

*Gap:* there is no lighting model. The stage is lit by three fixed lights so the white models read; a
`light`-kind landmark is a box that says where a lamp is, not a lamp. A still is a blocking reference, never a
lighting reference — which is the honest thing for it to be, but it is less than the products show.

### 3. Screenshot library

**Built.** Stills at delivery size (long edge 1920, even sides), blockout clips encoded in the browser, both
stored under the task and listed with their revision, size, and badges for 过期 / 已应用 / 白模色 / 带角色名 /
带四肢. Helpers — the grid, the camera rigs, the rulers, the labels — are hidden for the render. 60 per scene.

*Gap:* no folders, tags or search. Sixty items in one list is fine; six hundred would not be.

### 4. 应用至分镜

**Built, and further than the brief asked.** A still leads the shot's `sequence_images`; a clip leads its
`reference_videos` — the two slots stage 5 already reads. A clip also changes how the shot is generated: the
shot is marked as requiring a motion reference, so auto mode picks multimodal, and the measured lens clause
(「机位距…米、机高…米」) is withheld from the prompt, because a blockout owns the camera track and two camera
instructions compete. A limbed white model appends one requirement sentence about writing the limb motion out.
A blocking edit marks every capture of the scene stale, and stage 5 refuses a stale clip and restores the clause.

*Gap:* one still and one clip per shot. Applying a newer one replaces the older.

### 5. Saved poses

**Built, and moved.** The products describe a per-project pose library; this project has real identities, so
the library follows the *person* (`director_desk_poses`, up to 200, unique by name, replace-by-name). The
per-task endpoints still exist for older clients.

*Gap:* a saved pose is joint angles only — not a figure kind, a body type or a prop in hand. Saving a humanoid's
clip is deliberately not supported: a clip is a motion, not a pose.

### 6. Camera moves on a timeline, returned to the canvas

**Built.** Per shot: duration 1–30 s, 24/25/30 fps, a camera track and a track per actor, keys dragged on whole
frames, six easings, copy/paste, and the 14 presets written as ordinary editable keys — so a preset is a
starting point, not a black box. `sampleShot(plan, shot, t)` is random access with no clock and no history, so
the preview, a scrub and an exported frame are the same picture for the same `t`. An edit made while the
playhead sits on a key of the edited track is rewritten into that key, and the panel says which it is doing.

*Gap:* no curve editor — easing is per key from a list, not a bezier the upstream offers. No audio. A
one-shot humanoid clip starts from the first of the consecutive keys that ask for it, which is a rule, not a
motion graph.

## What P6 added beyond the six

- **Element-library models.** A set piece can be drawn as a GLB from the person's element library instead of a
  primitive, with a local `.glb` importable from the desk. *Gap:* the model is decoration — its real geometry
  is not used for occlusion or framing checks, which still measure the landmark's box, and a skinned GLB is
  refused by the library.
- **Backdrops.** A colour, a photograph of the real location, or an equirectangular panorama, drawn in the lens
  view only and left out of what goes to generation unless asked for. *Gap:* nothing about it reaches a prompt,
  so it is a framing aid and not an art-direction reference; and a flat image hangs square to the lens rather
  than standing in the world, so it cannot be walked past.
- **Whole-crowd editing.** An array's figure, body type and colour switch in one operation, and come back
  member by member on undo.

## Second pass (2026-10-14): the two articles, the newer upstream, and what was still missing

The two product write-ups were read again in the browser — 万兴剧厂's 「3D导演台上线：多人站位、镜头关系终于可控了」
(2026-06-23) and LUMI AI's 「3D导演台正式上线：把镜头设计，真正搬进三维空间」 (2026-09-16). They describe the six-part
loop above, with two emphases this desk had not answered in kind: *stability* — the point of the thing is that
多人站位、角色姿势、镜头机位 stop drifting between shots, so what the desk measures it should also be able to put
right — and *choosing between lenses from pictures*, not one lens at a time. The five repositories were cloned
again. Four are at the reviewed revision; `mangfufu/director-desk` had moved from 0.4.8 to 0.4.11 (`f3afacf`,
2026-10-08) and gained hand-drawn walk / camera paths, a grayscale depth video export, keyboard-recorded walks,
and set-piece grouping / alignment / arrays. Nothing of that release is copied; the behaviour is.

What this pass added, against the brief's six points:

| Brief | Was | Now |
|---|---|---|
| 1. 自动调整人物站位、角色姿势、镜头机位 | Nine checks said what was wrong; nothing fixed it | `repair.py` turns every failing check into ordinary operations — push a crowded pair apart, turn someone to their partner, swap a pair that opens mirrored, re-solve the lens of a shot that loses, hides or walks into its subject or jumps the axis, write a posture the storyboard names as that shot's override. `GET …/repairs` previews them; `repair_checks` applies them; the desk's 检查 panel shows 修正 per item and 一键修正. A walk the storyboard names is *not* invented: the proposal says to draw it |
| 2. 三维空间布局与摆场 | Primitives, element-library GLBs, crowd arrays, formations for people | `array_landmark` (line / grid / ring copies of a set piece, the original kept in place) and `align_landmarks` (align by centre, or distribute) for set pieces; five more presets from the articles' own examples (卧倒、背手站立、侧身回头、抬手指向、出拳) |
| 3. 多机位预览与构图规划 | Candidate lenses existed, viewed one at a time | 机位对比: the filming lens and every candidate rendered side by side from one hidden canvas, with 使用此机位 on each; the angle presets (正面 / 侧面 / 过肩 / 俯拍 / 仰拍 / 特写) add candidates in a click |
| 4. 镜头运镜预演与调度 | 14 presets, keys on a timeline, blockout clips | 手绘路径: a route dragged on the ground becomes that track's keys (`set_path`: corner-cut once, resampled at even arc length, spread over the chosen seconds with the chosen easing; a walker faces along the route, holds, or watches a point; a camera route looks at a subject or ahead). Actor tracks are drawn in the director view like the camera's |
| 5. 精准的姿势与动作调节 | 58 control keys, 20 presets, IK, saved poses | unchanged in mechanism; presets above |
| 6. 衔接 AI 生成与工作流 | Stills and clips applied into the stage-5 slots | 深度画面: a still or clip can be rendered as linear depth (near bright, far dark, range taken from the shot's subjects) and uploaded flagged `depth`; a depth clip applied to a shot makes stage 5 say the reference carries layers and motion only; a depth still is refused as a first-frame reference, because an image model would copy the grey. The tool assistant / MCP gain `get_stage_checks`, `edit_stage`, `repair_stage` so an agent can block a scene in the same operations a person uses |

Still open, deliberately: lighting and look (unchanged boundary); FBX / OBJ import (the element library takes GLB; a
converter in the browser is possible but was not asked for in a form that justified it); keyboard-recorded walks
(a drawn route covers the need); groups as a persistent object (an array is enough until someone asks to move a
set as one).

## Honest summary

The loop the two products describe is complete: stage, two views, library, hand-off, poses, timeline. What is
missing is everything to do with *light* and *look* — this desk plans where things are and how the camera
moves, and says nothing about how the scene is lit or graded. That is a deliberate boundary: a white model is
the safest thing to hand a video model, and a stage that pretended to be a render would invite being trusted
as one.

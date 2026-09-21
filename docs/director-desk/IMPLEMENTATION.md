# 3D Director Desk Implementation

The desk is the editable 3D face of the spatial stage. It does not replace the deterministic
planner: the planner still places everyone and solves every lens; the desk lets a person move,
pose, light and film that same stage, then hands stills and blockout clips back to generation.

One stage per scene, one document (`StagePlan`), one write path (`PATCH …/spatial/scenes/{id}`
with semantic operations and `base_revision`). Every entry point opens the same stage.

## Decisions

| Decision | Choice |
|---|---|
| Substrate | Extend `StagePlan` additively. Every new field has a default, so stored plans load unchanged and `version` stays 1 |
| Figures | Three kinds per actor: `standin` (limb-less capsule, the default and the white-model-safe one), `mannequin` (procedural jointed figure), `humanoid` (skinned CC0 figure with clips) |
| Limbs and prompts | A plan whose exported clip shows limbs sets `blockout_standin_limbs`; the compiler then demands a segmented limb sequence (blockout rule 2) |
| Video encoding | In the browser with `mediabunny` (MPL-2.0, an unmodified npm dependency behind a dynamic `import()`; WebCodecs, frame-by-frame, deterministic). H.264 / MP4 first, VP9 / WebM when the browser cannot encode H.264. Without WebCodecs the desk says so and offers stills only |
| Media hand-off | Stills and clips are uploaded, stored under the task, and referenced by absolute http(s) URL. Nothing is inlined as a data URL |
| State | Local React state plus one reducer for the desk session. No store library (project convention) |
| three.js | Behind `lazy()`; R3F components are mocked in tests, pure logic is tested directly |

## Data model additions (`backend/app/core/spatial_stage/models.py`)

```text
StageLandmark  + yaw_deg: float = 0            rotation about Y
               + shape: box|cylinder|sphere|cone|wedge|plane = box
               + color: str = ""               "#rrggbb" or empty for the kind colour
               + element_id: str = ""          element-library GLB bound to this piece
StageActor     + figure: standin|mannequin|humanoid = standin
               + body_type: str = "standard"
               + color: str = ""
               + crowd_id: str = ""            members of one array share it
               + pose: StagePose | None        joint angles in degrees, see below
StagePose        preset: str = ""              preset id the angles came from
                 joints: dict[str, float]      control key -> degrees, |v| <= 180
                 clip: str = ""                humanoid clip id
                 clip_phase: float = 0         0..1 inside the clip
ActorOverride  + pose: StagePose | None        per-shot pose
StageShot      + alt_camera_ids: list[str]     extra candidate lenses; camera_id stays the one that films
StagePlan      + backdrop: StageBackdrop      the scene's framing underlay, lens view only
               + timelines: dict[str, ShotTimeline]   keyed by shot id as a string
StageBackdrop    kind: none|color|image|panorama = none
                 color: HexColor = ""          kept while another kind shows, so switching back needs no re-pick
                 url: str = ""                 http(s) only; an image or a panorama needs one
                 yaw_deg: float = 0            where a panorama's seam sits; a flat image hangs square to the lens
                 opacity: float = 0..1
ShotTimeline     duration_s: float (1..30)
                 fps: 24|25|30
                 camera: list[CameraKey]       time, position, target, lens_mm, easing
                 actors: dict[name, list[ActorKey]]   time, position, yaw_deg, pose, easing
Easing           linear|smooth|ease-in|ease-out|hold|whip
```

A key's `easing` shapes the way *into* that key (the upstream convention): `hold` keeps the key before until this one is
reached. An `ActorKey` may leave out any of `position`, `yaw_deg`, `pose`; each channel is sampled over the keys that
speak about it, so a pose key between two marks does not stop the walk. `set_timeline` replaces `camera` and `actors`
wholesale when they are sent (an actor with an empty list loses its track) and keeps whatever is not sent; a duration
shorter than the last key is refused with the track and the time of that key.

Captures are *not* part of the plan. They live under `assets["4_director_desk"]`:

```text
{version: 1, scenes: {scene_id: {captures: [Capture], applied: {shot_id: {still, clip}}}}, poses: [SavedPose]}
Capture  id, kind: still|clip|backdrop, shot_id, camera_id, url, width, height, duration_s, fps (24|25|30; 0 = still / not stated),
         plan_revision, shows_limbs, monochrome, labelled, created_at, stale, warning
```

A `backdrop` is the scene's framing picture, stored in the same place for the same reasons (one upload route, one
delete, one owner) and treated as a different thing everywhere it matters: it may arrive with `shot_id` 0, it has its
own room (20 per scene) so it never costs a scene one of its sixty stills, `apply` refuses it, and a blocking edit does
not date it — it is not a picture *of* the blocking.

Saved poses follow the *person*: table `director_desk_poses` (owner, name ≤ 40, unique per owner, ≤ 200 per owner),
served by `GET / POST / DELETE /api/director-desk/poses`. The per-task `poses` list above and its endpoints remain for
older clients; the desk no longer uses them.

Pose control keys (`StagePose.joints`): body / torso / head `pitch·yaw·roll`, shoulders and hips `pitch·spread·twist`,
elbows and knees `bend`, hands and feet `pitch·roll·twist`, `body.offsetY` (metres, a manual lift), and per hand per
finger `<side>Hand.<finger>.curl` / `.spread` — 58 keys. Spread is signed by side (left negative = outwards). The
jointed figure is grounded from its own contacts, so presets carry no `body.offsetY`.

## Operations added (`operations.py`)

| op | Args |
|---|---|
| `transform_landmark` | `name` + any of `position`, `size`, `yaw_deg`, `shape`, `color`, `kind` |
| `add_landmark` | now also `size`, `yaw_deg`, `shape`, `color` |
| `bind_landmark_model` | `name`, `element_id` (empty to unbind) |
| `set_backdrop` | any of `kind`, `color`, `url` (http(s)), `yaw_deg`, `opacity` |
| `add_crowd` | `label`, `rows`, `columns`, `spacing`, `center`, `yaw_deg`, `body_type`, `seed` |
| `remove_crowd` | `crowd_id` |
| `transform_crowd` | `crowd_id` + `center` and/or `yaw_deg` and/or `spacing` |
| `add_extra` / `remove_extra` | a supporting stand-in that is not in the script's cast |
| `set_figure` | `name`, `figure`, `body_type`, `color` |
| `set_pose` | `name`, optional `shot_id` (writes the override), `preset`, `joints`, `clip`, `clip_phase` |
| `add_camera` / `remove_camera` | a candidate lens for a shot; `remove_camera` refuses the one that films |
| `use_camera` | `shot_id`, `camera_id` — promote a candidate to the filming lens |
| `frame_shot` | `shot_id`, `size` — solve distance from the film-back equation along the current look direction |
| `set_timeline` / `clear_timeline` | `shot_id`, `duration_s`, `fps`, `camera`, `actors` |
| `apply_camera_move` | `shot_id`, `preset`, `amplitude`, `angle`, `side`, `easing` — writes editable keys |

`move_camera` keeps the camera's `move` unless the caller passes `reset_move`.
A patch may carry `solve: false` so a drag does not re-solve the lens the user is looking through.

## Frontend (`frontend/src/features/directorDesk/`)

```text
DirectorDesk.tsx            full-screen workspace, opened from the storyboard and from stage 5
deskReducer.ts              selection, tool, view layout, pending edits, undo stack
three/DeskViewport.tsx      director canvas: picking, TransformControls, snapping, measure
three/LensViewport.tsx      camera canvas at the delivery aspect
three/figures/*             StandIn, Mannequin, Humanoid
three/props/*               primitive shapes, element-library GLB
three/Backdrop.tsx          the scene's underlay: colour / camera-facing plane / equirectangular sphere
overlays/CompositionGuides  aspect frame, thirds, safe area, centre cross (DOM, not 3D)
panels/*                    outliner, inspector, pose, camera, timeline, captures, backdrop, model binding
elementLibraryApi.ts        the element library's GLBs: list what has one, import a local file as a new element
lib/snapping.ts             grid + oriented-box face snapping
useDeskPlayback.ts          playhead / playing / loop: React state + rAF, never touches the plan or undo
panels/TimelinePanel.tsx    transport, duration / fps, camera + actor tracks, key edit, move presets
lib/sampling.ts             pure (plan, shot, t) -> lens + cast; easing; shortest-arc yaw; gait and clip phase from t
lib/timelineEdits.ts        key edits as whole-track set_timeline operations; edits on a key go to the key
lib/cameraMoves.ts          the menu of the 14 presets (names, parameters); the server lays out the keys
lib/clipExport.ts           deterministic mediabunny clip export through the lens canvas
lib/poses.ts                presets, mirror, clamps, mannequin joint table
lib/ik.ts                   two-bone CCD with foot lock
lib/capture.ts              still; the delivery-render setup (helpers hidden, clay colour, buffer size) shared with the clip
```

## Timeline, playback and clips

`sampleShot(plan, shot, t)` is random access: no clock and no history take part, so preview, scrub and export draw the
same frame for the same `t`. Positions lerp, yaw takes the short way round, poses blend through `poses.blendPose`, the
lens interpolates in millimetres and is converted to a vertical angle with the 36 mm long-side convention and the plan's
aspect. With no keys the shot is the static plan; a camera that only has the planner's `move.end_position / end_target`
is sampled (and drawn in the timeline) as two keys over the duration, and becomes real keys the first time it is keyed.
A humanoid's clip and a mannequin's walk / run gait (pose preset `walk…` / `run…`, only for an actor that has a track)
advance from `t` alone: phase = (t · rate) mod 1, walk 1 cycle/s, run 1.5, a clip 1 / its length; a one-shot clip runs
from the first of the consecutive keys that ask for it. The playhead always sits on a whole frame.

The desk draws `stagePlanAt(plan, shot, playhead)` in both views; the director view adds the lens path with a marker per
key (helpers, hidden from captures) and hides every gizmo while playing. An edit made while the playhead sits on a key
of the edited track is rewritten into that key (`retargetToKeys`: `move_actor`, `set_shot_override` place / facing,
`set_pose`, `move_camera` of the filming lens); anywhere else it edits the base plan, and the side panel says which.
A number still being typed is sent before a scrub moves the playhead. Every timeline edit is a `set_timeline` /
`clear_timeline` / `apply_camera_move` through the PATCH queue with `solve: false`, with a local inverse (a first key
undoes to `clear_timeline`; a preset undoes to the keys that were there; `use_camera` restores the keys it dropped).

`exportClip` probes `canEncodeVideo` (H.264, then VP9) before touching the renderer, sizes the clip from the plan aspect
(short edge 720, even sides), and for frame *i* of `ceil(duration · fps)`: asks the desk to show `i / fps`, waits until
the lens scene has committed that instant (`FrameAck`, the last effect of the lens scene), renders the lens canvas,
copies it to a 2D canvas (burning names in when asked) and hands it to the encoder at timestamp `i / fps`. It yields
every third frame for progress and `AbortSignal`, cancels the output on any failure and restores renderer size, pixel
ratio, camera aspect, helpers and override material in `finally`. The bridge is `LensHandle.renderer()` plus
`frameStamp` / `onFrameShown` on `LensViewport`; waiters are dropped when the desk unmounts. The client refuses what
the server would refuse (type, 60 MB, 0–30 s, 24 / 25 / 30 fps) before uploading.

## Set pieces, backdrops and what reaches generation

A set piece whose `element_id` is set is drawn as that element-library GLB instead of its primitive
(`three/props/StageProp.tsx` chooses; `ElementModelProp` fetches it with the session cookie, parses it once per
element however many pieces point at it, and scales it uniformly into the piece's own `size` box with its lowest point
on the floor and the piece's `yaw_deg` applied). A model that cannot be fetched or parsed falls back to the primitive
with a "模型加载失败" note, so a broken binding never costs a stage. Importing a local `.glb` creates an element in the
library (kind `prop`, linked to the project) and binds it; the library's own caps — 25 MB, 1,000,000 triangles, no
skins — are the server's, and its sentence is what the desk shows.

The backdrop is a framing reference and nothing else. It is drawn in the lens view only, depth-tested and writing no
depth, so the set always stands in front of it; a flat image or colour hangs square to the lens 120 m out, a panorama
is an equirectangular sphere centred on the lens. It is excluded from a delivered still or clip by the same
`HELPER_FLAG` pass that hides the grid and the camera rigs, unless「导出时包含背景」is ticked. Nothing about it reaches a
prompt.

## Hand-off to generation

`POST /api/drama/{task}/director-desk/scenes/{scene}/captures` stores an upload and returns a
`Capture`. `POST …/captures/{id}/apply` writes the still into the shot's `sequence_images` and the
clip into `reference_videos` — the two slots stage 5 already reads. A clip's `fps` is a timeline's rate (24 / 25 / 30); 60 is refused. A blocking edit marks that
scene's captures `stale`; stage 5 refuses a stale clip the same way it refuses a stale board.

A shot with a reference video reaches stage 5 with `motion_reference_required`, so with the reference mode on
auto it is generated as `multimodal` (score 125, above first-and-last-frame's 120), and a video model that cannot do
multimodal fails the shot instead of dropping the clip; the captures panel says this in so many words.

When a clip is applied the shot's measured `camera_start` / `camera_end` sentences are withheld from
the motion prompt: a blockout owns the camera track (blockout rule 3). When that applied, non-stale clip has
`shows_limbs`, the same gate appends one requirement sentence to the motion prompt (blockout rule 2: write the limb
sequence in order), and the capture record carries a `warning` the desk shows.

## Provenance

| Source | Licence | Use |
|---|---|---|
| mangfufu/director-desk | MIT; bundled motions are Quaternius Universal Animation Library, CC0-1.0 | Ported with attribution: easing channels, camera move presets, film-back framing, oriented-box snapping, grid-ray visibility, deterministic clip export. The CC0 humanoid GLB is reused with its NOTICE |
| jiguang132/storyai-3d-director-desk, lkhxxx123/jlmlh-3d-director | MIT (c) 2026 YZ | Ported with attribution: pose preset angles, gait curves, procedural mannequin proportions, crowd array, aspect frame geometry. Their UE mannequin GLB (Sketchfab Standard) is not copied |
| Vanilagy/mediabunny | MPL-2.0 | npm dependency, unmodified, dynamically imported by `lib/clipExport.ts`; nothing copied |
| GuiYi-Xi/monoform-previs-studio | none | Read for ideas only; nothing copied. Finger joints, two-bone IK with a foot lock, whole-pose keys, the reference underlay and the saved-pose library are written from their descriptions |

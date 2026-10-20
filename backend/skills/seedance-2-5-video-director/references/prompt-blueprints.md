# Seedance 2.5 prompt blueprints

## Contents

- Shared assembly order
- Basic multimodal
- Exact 30-second timestamp video
- Long Video
- Video extension
- Video edit
- Clay Renderer
- Seamless transition
- Multi-grid storyboard
- Transition vocabulary

Use one primary blueprint. Add only relevant specialist instructions from `multimodal-patterns.md`.

## Shared assembly order

Prefer this semantic order inside the final copy-ready prompt:

1. Output declaration: mode intent, duration, ratio, resolution when relevant.
2. Asset declaration: what each referenced asset controls and what it must not contribute.
3. One-sentence film intent: subject + place + event + tone/style + special camera idea.
4. Global setting: environment, physical texture, visual style, camera family, subject design, core performance.
5. Chronological plot or edit operation.
6. When needed, request-specific performance, physical causality, live coverage, or cutting rules.
7. Audio: dialogue, sound effects, ambience, timbre, music, subtitle policy.
8. Global continuity and prohibited changes.

Do not emit bracketed template labels in the final prompt unless they improve a long or technical prompt.

## Basic multimodal

Use for a new 4-30 second video that does not require another primary mode.

Formula:

`asset roles + one-sentence intent + chronological visual/action description + camera and sound + global continuity/prohibitions`

For a simple single-beat video, prose may be better than timestamps. Include timestamps only when the user requests timing or the action sequence needs disambiguation.

Match control depth to the request. If the user supplies a detailed layered structure or asks for precise acting, physics, live coverage, or shot/reverse-shot direction, retain comparable hierarchy and granularity using `realistic-direction-patterns.md`; do not flatten it into the compact formula.

## Exact 30-second timestamp video

Use for an exact 30-second video with deliberate pacing.

Build:

1. `Reference layer`: bind identity, scene, composition, movement, timbre, or music sources.
2. `Global setting`: environment and physical texture; visual style and light; camera language; subject design; performance core; request-specific prohibitions.
3. `Timestamp storyboard`: divide the complete `0-30s` interval into readable phases.
4. `Global convergence`: restate continuity, ending state, audio, subtitle, and BGM policy.

Each time segment should include:

`time range + dramatic function + visible action/expression + camera/framing + sound or dialogue + intended end state`

Use emotional interpretation only when it translates into visible acting, gaze, breath, posture, vocal delivery, or camera behavior.

## Long Video

Use for a new 30-180 second video.

Formula:

`global parameters + asset roles + one-sentence overview + act/scene progression + global convergence`

- State total duration and ratio at the beginning.
- Prefer acts or scenes over excessive second-by-second microdirection.
- Give each scene a narrative job, approximate or exact time range, location, action, camera strategy, and transition.
- Maintain an explicit state chain across scenes: subject location, wardrobe, held props, time/weather, and unresolved goal.
- Use exact timestamps only for beats that require synchronization.
- End with a resolved visual state rather than a list of events.

## Video extension

First normalize direction:

- `prepend-before-source`: insert the new interval before the original. The new interval must end at the source's first-frame state and hand camera, motion, lighting, space, and audio into the original opening.
- `append-after-source`: add the new interval after the original. The new interval must begin from the source's last-frame state and continue camera, motion, lighting, space, and audio from the original ending.
- Treat `原片之前 / 补前情 / 前传 / 衔接首帧` as prepend evidence. Treat `原片之后 / 接着结尾 / 然后 / 继续故事` as append evidence.
- Treat bare `向前续写 / 前向续写 / 往前延长 / 向后续写 / 后向续写` as linguistically ambiguous. Do not resolve these phrases from plot progression, opening-state descriptions, or common-language assumptions. Unless the user explicitly places the new interval before or after the original or names the first/last-frame connection, ask `新增片段放在原片之前，还是原片之后？` before drafting.

Required opening after normalization:

`参考 @Video N 的原始内容，在原片之前插入/在原片之后追加 X 秒。原视频区间保持不变，以下提示仅作用于新增区间。`

Then specify:

1. Relevant source boundary state: for prepend, the required destination state from the first frame; for append, the inherited start state from the last frame.
2. New action or scene only for the added interval, arranged in chronological output order.
3. Connection behavior: natural continuation into the original opening for prepend, or out of the original ending for append; use a named transition only when requested.
4. End state of the added interval: match the original first frame for prepend; define the new final state for append.
5. Constraints: smooth action and camera connection; no unexplained reset, hard cut, sudden prop, identity change, lighting jump, or audio discontinuity.

For a transition extension, use:

`transition guide + source-boundary state + destination scene + connection logic + framing change`

## Video edit

Choose the operation subtype:

- `Smart Edit`: text-targeted change to a generated video.
- `Edit with marks`: change located by a box, brush, arrow, line, text, or landmark.
- `Edit Video`: equivalent local editing applied to an uploaded source video.

Formula without marks:

`exact target + add/remove/replace/change instruction + effective time + protected elements`

Formula with marks:

`annotation tool and inside/outside/direction + exact target + add/remove/replace/change instruction + effective time + protected elements`

Use an explicit A-to-B change. Example structure: `在 0-8 秒内，将画面中央人物的蓝色牛仔裤替换为深黑色西装裤；人物身份、上衣、动作、背景、机位和原声保持不变。`

For removal, require physically plausible background completion consistent with original perspective, motion, texture, light, and occlusion.

## Clay Renderer

### Coarse white model

Use when simple geometry primarily controls dynamic structure.

Formula:

`reference declaration + model-to-final-subject mapping + chronological action/camera plot + scene treatment + global convergence`

- Name exactly which motion trajectory, camera move, position, scale relation, lighting change, cut rhythm, or sound timing to borrow.
- Map every distinguishable model by color, shape, or position to a final character, object, or prop.
- Describe complete limb or wing action chains if present; incomplete actions risk stiffness.
- Do not preserve primitive geometry, gray material, guide overlays, or viewport texture.

### Fine white model

Use when geometry, scene, and animation are complete and need final rendering.

Formula:

`render command + timed rendering description + scene treatment + global convergence`

- Start with `将 @Video N 的白模动画渲染为最终成片。`
- Describe environment, tone, material, surface response, light, atmosphere, and timed scene changes.
- Preserve camera, composition, animation, relative positions, and intended occlusion unless the user asks to alter them.
- Remove trajectory lines, coordinate axes, camera cones, viewport grids, and other production overlays.

## Seamless transition

Required opening:

`无缝连接 @Video 1 与 @Video 2，但不要修改两段原视频的既有内容。`

Define:

1. Exit action or visual trigger from Video 1.
2. Full-screen bridge state: occlusion, matching object, blur, particles, light, surface, or camera passage.
3. Entry action into Video 2.
4. Connection locks: shape, screen position, scale, direction, speed, motion trend, camera vector, color/material transformation, and sound bridge.
5. Prohibitions: no black frame unless intentional, frame skip, hard cut, flicker, text, logo, subtitle, or alteration of the source clips.

## Multi-grid storyboard

Build:

1. Declare `@Image 1` as the complete ordered storyboard and state that each panel is one complete shot, not an independent character or scene reference.
2. Map separate character, prop, and environment references.
3. State the story spine and ending.
4. For every panel/shot, provide exact or proportional time, composition, camera height/framing, subject action, spatial relationship, and transition/end state.
5. Close with global style, physical behavior, continuity, and prohibited changes.

Prefer simple line or stick-figure boards for geometry; the prompt must supply appearance, environment, movement, and rendering detail.

## Transition vocabulary

Use transitions only when narratively and physically motivated.

| Transition | Best use | Control to state |
|---|---|---|
| Natural shot switch | Conventional narrative | breathing room, matching action/gaze, no abrupt timing |
| Fade in/out | Opening, ending, passage of time | black/white state and duration |
| Dissolve | Memory, dream, lyrical time passage | overlap duration and matching composition |
| White/black flash | Impact or beat sync | trigger sound/action and exact flash moment |
| Wipe | Clear location change, retro grammar | wipe direction, speed, covering edge |
| Occlusion/mask | Spatial passage | occluding object, full-cover state, reveal direction |
| Match object | Montage | shared shape, position, scale, color, motion |
| Whip/action transition | Action, travel, speed | pan direction, force, blur, entry direction |
| Motion relay | Outfit/location change | continuous body action and landing pose |
| Zoom in/out | Macro-to-micro or nested world | target detail, full-frame moment, destination reveal |
| Ink diffusion | Eastern poetic transition | ink trigger, spread direction, reveal timing |

Never add a transition merely to make a prompt sound cinematic.

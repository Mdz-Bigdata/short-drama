# Multimodal reference and specialist patterns

## Contents

- Asset lock table
- Reference grammar
- Person-reference scope
- Realistic people
- Multiple people
- Timbre and dialogue
- BGM removal
- Creative transfer
- Local removal and replacement
- Perspective reconstruction
- Green-screen compositing
- Conflict handling

## Asset lock table

Before drafting, normalize every supplied or explicitly numbered asset into this internal/public table:

| Asset | Role | Active time | Preserve | Do not inherit |
|---|---|---|---|---|
| `@Image 1` | identity / scene / prop / style / storyboard | global or time range | protected traits | irrelevant background, text, layout, etc. |
| `@Video 1` | source / motion / camera / edit / transition / white model | global or time range | selected motion or footage | unwanted identity, material, audio, overlays, etc. |
| `@Audio 1` | timbre / dialogue delivery / BGM / rhythm / ambience | global or time range | selected acoustic traits | noise, unrelated speech, unwanted music, etc. |

Use only rows backed by actual user inputs. If the user describes roles but does not label upload order, preserve the app's attachment order and state the mapping.

## Reference grammar

Write each reference as a scoped contract:

`Reference source + traits to borrow + target subject/shot + active time + protected invariants + traits not to inherit`

Good:

`20-25 秒仅参考 @Video 2 中“预备—冲刺—起跳—空中举剑—挥砍”的重心和动作节奏，将动作映射给 @Image 1 的小骑士；不要继承 @Video 2 的灰模人物、场景材质或其他时间段动作。`

Weak:

`参考 @Video 2 的动作。`

Separate roles when one asset serves multiple purposes. Do not assume that a motion reference should also control character identity, background, audio, or style.

## Person-reference scope

Interpret ordinary person-reference language conservatively:

- `人物参考图`, `角色参考图`, `人物视觉参考`, `情侣参考图`, or `严格参考人物图片` defaults to the complete visible character: identity, facial features, face shape, skin tone, age impression, hair shape/color, stature, body frame and proportions, visible wardrobe, footwear, accessories, and overall demeanor.
- Do not redesign, replace, recolor, add, or remove visible wardrobe or accessories unless the user explicitly permits styling changes.
- Reconstruct unseen sides or backs consistently from visible cut, color, material, construction, and wearing method; do not invent a different outfit.
- By default, do not inherit the source image's background, composition, pose, text, crop, or lighting unless the user assigns those roles too.
- If the user says `只参考脸`, `只锁身份`, or otherwise narrows the role, preserve only that declared scope and label any wardrobe or styling as a creative supplement.
- If one image contains a couple or group, bind each visible person independently by position or user-named role. Preserve relative height and scale; prohibit face mixing, wardrobe swapping, duplicated bodies, and role reversal.

If the image itself is unavailable for inspection but the user declares it as a person reference, keep the reference contract symbolic and preserve the visible character. Do not compensate for missing inspection by inventing clothing.

## Realistic people

Use this structure only to the level needed by the shot:

`specific adult age and ethnicity + skin tone and real texture + 3-4 distinctive facial traits + gaze/emotional information + hairstyle/color/state + garment cut/color/material/wear + body frame/posture/temperament`

Reality anchors:

- Retain micro-pores, fine skin texture, natural asymmetry, and context-appropriate minor marks; avoid flat plastic skin.
- Describe eyes through visible gaze behavior and underlying emotion, not empty adjectives alone.
- Give hair a cut, texture, condition, and environmental response.
- Give clothing a cut, material, condition, and wearing detail.
- Lock age, face, hair silhouette, garment, body proportions, and identity across all shots.
- Default text-only people to fictional, clearly adult subjects. Preserve a real person's identity only from authorized user-provided references.

Do not overload distant or fast shots with invisible facial microdetail.

For acted dialogue or emotional realism, load `realistic-direction-patterns.md`. Prefer motivated visible behavior over anatomy-by-anatomy expression instructions.

## Multiple people

Bind every important person independently:

`Character A = @Image 1; Character B = @Image 2; ...`

For each character, lock:

- identity and facial features;
- hairstyle and clothing;
- body proportions and scale;
- spatial position or entrance direction;
- owned props;
- action, gaze target, and relationship;
- voice/timbre source when dialogue exists.

State counts explicitly for groups. Keep roles primary/secondary. During physical interaction, describe contact and occlusion so limbs do not merge. Add `no face mixing, wardrobe swapping, duplicated bodies, extra limbs, or prop transfer` only when relevant.

## Timbre and dialogue

- Prefer clear, noise-free human-voice reference audio.
- Bind each voice to one character and quote the exact line.
- State which qualities to retain: pitch/color, emotional tension, pace, pauses, breath, intensity, or whisper/shout behavior.
- Scope the timbre to the relevant line or time range.
- Do not use a single vague instruction such as `use @Audio 1`. Write: `角色 A 在 8-11 秒说“……”，音色参考 @Audio 1，保持低沉、克制、略带停顿的悬疑语气。`
- Keep dialogue duration plausible. Shorten the line or expand the beat when speech cannot fit naturally.

## BGM removal

For lossless dialogue extraction, write:

`移除 @Video N 的背景音乐，仅保留清晰的人声对白和指定现场声；画面、原有字幕及其他受保护视觉元素保持不变。`

Name which non-vocal sounds to preserve or remove. Distinguish:

- `remove BGM, retain dialogue and ambience`;
- `mute all sound`;
- `retain only dialogue`;
- `replace BGM with @Audio N`.

Do not combine `no BGM` with a contradictory music request.

## Creative transfer

Transfer creative logic, not the entire source:

- Identify camera rhythm, motion grammar, transition method, emotional arc, comedic/cute state, composition logic, color progression, or social-media pacing to borrow.
- Map the transferred logic to the target identity, scene, props, and style.
- Lock target appearance and core content.
- Explicitly reject unwanted source identity, background, text, logo, audio, or texture.

Pattern:

`参考 @Video 1 的 [creative traits]，将其转译到 @Image 1 的 [target] 与 [new setting]；保持 [target invariants]，不要继承 [source exclusions]。`

## Local removal and replacement

Use this as a specialist capability within `video-edit`:

- Location: marked region, screen side, named object, or relationship to another object.
- Target: exact person/object/background element.
- Operation: remove, add, or replace A with B.
- Time: global, fixed interval, or gradual onset.
- Reconstruction: fill the background using original geometry, parallax, occlusion, motion, material, and light.
- Protection: list the subjects, actions, framing, background, sound, and text that remain unchanged.

For marked edits, specify `inside/outside the red box`, `at the blue landmark`, `where the arrow points`, or the exact tool and direction. Never rely on `change this`.

## Perspective reconstruction

State source and destination camera explicitly:

`Change [source view/framing] to [target view/framing/movement], while preserving [subjects, action timing, space, background, and identity].`

Control:

- camera height and angle: overhead, eye level, low angle;
- viewpoint: first person, third person, fixed frontal;
- framing/lens: close-up, medium, wide, focal behavior;
- movement: push, pull, pan, tilt, orbit, track;
- reconstructed off-screen space and scale logic.

If a reference video supplies the target perspective, state what perspective traits to borrow and what original content not to inherit.

## Green-screen compositing

Map foreground, background, and effects separately:

- identify the green-screen source and the subject to extract;
- identify the destination scene or plate;
- preserve foreground contour, motion, timing, and identity;
- match camera angle, scale, ground contact, parallax, light direction, color spill, shadow, atmosphere, and motion blur;
- define interaction timing for explosions, weather, particles, or passing objects;
- remove green spill, edge halos, flicker, floating feet, and pasted-on lighting.

Do not call a non-green-screen replacement `green-screen compositing` unless the user requests that workflow.

## Conflict handling

Resolve instructions in this order:

1. Explicit protected source footage or identity.
2. Explicit edit target and time range.
3. Explicit asset role.
4. Explicit duration, dialogue, audio, and subtitle requirements.
5. Style and creative supplements.

If two explicit instructions conflict at the same priority, ask one question rather than choosing silently. If a lower-priority style reference conflicts with an identity or protected-footage lock, preserve the lock and use only compatible style traits.

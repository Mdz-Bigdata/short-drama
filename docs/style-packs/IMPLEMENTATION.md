# Style Packs Implementation

## Overview

```text
项目配置 config["style_pack"]
  → style_packs.resolve_pack        风格锁 (缺省按 director_style / visual_style 的措辞判定)
      ├ lock + tone_line            每条提示词逐字重复的风格锁 + 每段可变的调性行
      ├ camera kit / palette        机身镜头胶片 / 贯穿色与色卡规则
      ├ negatives + situational     常驻负向词 + 情境负向词 (多人、延长、打斗、夜戏…)
      └ anti_leak + iron rules      跨介质参考图的反偷懒铁律 + 具名铁律
  → 第 4 阶段分镜图  image_style_line / identity_negative
  → 第 5 阶段首尾帧  同上
  → 第 5 阶段视频    video_prompt_engine.compile_shot_prompt
        风格锁 → 参考素材职责 → 结构声明 → 六层锁 → 镜头块 → 声音 → 铁律 → 负向词
        prompt_budget.compress 按目标模型预算裁剪（声音→环境→光影数值→色彩→特效→台词表达）
  → ModelGateway.generate_video(style_pack=…)
        pack.style_caption 作为 Ark 风格锚定；写实锁才追加写实增强词
        ark_clip_seconds 按模型钳时长（2.0=15s，2.5=30s）
```

## Modules

| Module | Responsibility |
|---|---|
| `backend/app/core/style_packs.py` | `StylePack` and the five packs; `resolve_pack`, `style_lock_block`, `tone_line`, `build_palette_card` / `palette_lines`, `negatives_for`, `iron_rules`, `image_style_line`, `identity_negative`, `describe` |
| `backend/app/core/prompt_budget.py` | Per-model budgets, `pressure`, `compress` with the cut order, the 100-character description floor, fixed (unmeasured) layers |
| `backend/app/core/video_prompt_engine.py` | `ShotPromptInput` → `compile_shot_prompt` (the layered prompt + `PressureReport`), `extension_prompt` |

## The packs

| id | Medium | What it locks |
|---|---|---|
| `cinematic_realism` | live_action | The project's previous default: photoreal live action, natural light, shallow depth of field, light 35mm grain |
| `film_35mm` | live_action | Vision3 500T grain, practical light, halation, haze, film-print look |
| `atom_punk` | live_action | 1950s retro-futurism on a wasteland: tubes, brass, rivets, rust; warm key + cool rim; amber / verdigris / dark metal through-colours |
| `anime_2d_cel` | anime_2d | Clean line art, two-step cel shading, consistent character model, no photographic texture |
| `anime_3d_cg` | anime_3d | UE5-class PBR, volumetric light, stylised realistic models, not live action |

Each pack carries its `style_caption` (what Ark anchors on), the situational negatives, the
anti-leak guards for reference media, the sound defaults and the sentence an extension repeats.

## Prompt layers and the budget

Order: `style_lock → anchors → structure → locks → camera → subject → motion → expression →
environment → colour → effects → dialogue → dialogue_notes → end_state → sound_layers → sound →
closing → rules → negatives`.

- Lock tags are `[空间锚] [状态锁] [道具锁] [光影锁] [声音锁]`, ahead of the picture, because the
  front of a prompt weighs most. Lighting numbers live in the lock and nowhere else.
- The budget measures the **body**: the style lock, anchors, rules, negatives and closing
  sentence are restated every time and are not counted.
- Cut order: `sound → environment → light numbers → colour → effects → dialogue notes`; the
  locks, subject, action, camera and dialogue are never cut; the description never goes below
  100 characters. The result is `green / yellow / red / unlimited` and lists what was dropped.
- Budgets: Seedance 2.5 900, Seedance 2.0 600, 即梦 400, Kling 500, Runway 800, Veo 700,
  Vidu 350, LibTV 1000, H3 900, Sora unlimited, unknown models 600.
- `compile_shot_prompt` also enforces the clip contract the old batch prompt enforced: the
  duration must be inside the model's range, and space / blocking / start state may not say
  "同上" — a clip prompt cannot refer to a batch the model never saw.

## Pipeline wiring

- `DramaCreateRequest.style_pack` (optional) → `config["style_pack"]`. Omitting it on an
  update keeps the project's pack; omitting it at creation resolves from the style words.
- Stage 4 (`_generate_scene_board`) and stage 5 stills use `image_style_line` and
  `identity_negative`, so an animated production is not pushed toward photoreal.
- Stage 5 clips are compiled by `compile_shot_prompt`; the shot record gains `style_pack` and
  `prompt_pressure`. A red pressure tier is logged with what was cut.
- `ModelGateway.generate_video(..., style_pack=…)` resolves the pack for the Ark
  `style_caption` and only applies the photoreal enhancer for live-action packs.
- `ark_clip_seconds` clamps to `max_shot_seconds(model)`: 15 s for Seedance 2.0, 30 s for 2.5.

## Sound on a model that renders it with the picture

`backend/app/core/h3_sound_design.py`. MiniMax H3 has one sound entry — the prompt — so the
sound is written as three named layers in one line, in descending weight:

```text
center: <人声>; ambient: <环境>; music: <配乐>
```

- **center** carries only the voice: who speaks, `clear speech`, `center channel`, and either
  `synced to mouth` or, for narration, `voice-over, mouths closed`. Music words here make the
  model blend the voice into the score, so they are checked for and refused.
- **ambient** names concrete sources, then `continuous, low volume` and a width word
  (`surround`, plus `low reverb` only in a hall or a street).
- **music** is `none` by default, because this project scores the film in stages 6 and 7; when
  a score is asked for it is pushed under the voice with `low frequency, slight spread`.

**Voice identity.** `build_voice_anchor` derives a character's voice from their character card
once — age, timbre band, pitch band, pace in characters per second, and a reference-audio slot —
and `lock_line()` restates it verbatim in every prompt that gives the character a line, ending
with 「全片音色、音调与声线不变」. The derivation is deterministic, so the same card cannot be
described two different ways in two episodes, which is what makes a voice drift.

**Checks** (`check_sound_prompt`), reported per shot as `sound_checks`: `h3_sound_three_layers`,
`h3_sound_center_clean`, `h3_sound_low_bed`, `h3_sound_space`, `h3_sound_word_budget` (≤60 words)
and `h3_sound_voice_locked`.

**Wiring.** Stage 5 resolves the cast's anchors once (`anchors_from_characters` with the
project's own `guess_gender`), and for each shot of an audio-native model compiles the layers
from the shot's dialogue, emotion and sound cell. The layers go into the prompt as a section the
budget may shorten but never drops, and each speaking character's lock line joins the named rules
as 「音色铁律」. A reference-audio slot is carried but unused until the project stores a clean dry
sample per character.

## Genre and feeling

`backend/app/core/creative_intent.py` and `genre_clusters.py`.

- A **cluster** (A 都市文戏, B 古装权谋, C 仙侠玄幻, D 动作打斗, E 悬疑惊悚, F 科幻末世, G 喜剧) is
  resolved from the production's genre key, else from the words of the scene. It carries whether
  fight coverage is normal here, the nine-grid rhythm label, the negative modules the genre needs,
  and the feeling to fall back to.
- An **intent** is one of 13 feelings, each holding the seven offsets a storyboard can act on:
  camera tendency, VFX density (share of shots with a visible effect), a rhythm multiplier on shot
  length, the wide / medium / close mix, composition, lighting and sound strategy.
- A brief decodes to one primary feeling and up to two secondaries, weighted 70 / 15 / 15 (or
  70 / 30). Conflicting pairs (hot-blooded vs oppressive, healing vs tragic, comedic vs eerie) are
  not blended: the primary stays and the secondary is dropped, with the reason kept for the log.
- Stage 4 writes the combined brief into the table prompt before the scene content, takes
  `rhythm_profile` from the cluster, and stores the decision as `direction` on the scene board and
  in the director's production context.

## Prompt packages (E) and design sheets (F)

**`backend/app/core/prompt_packages.py`** re-cuts an approved shot table into Seedance
packages a person can paste one at a time.

- A storyboard shot is re-cut at its own beats into **generation shots** of at most 4 s
  (3 s for a fight), sized by the weight of each beat so the slices come out uneven. A line
  never straddles two generation shots.
- Generation shots are filled into packages of 10 / 15 / 20 / 30 s. Each package restates its
  own style lock, cast lock, light lock, carried physical state, spatial lock and negatives,
  and its clock restarts at `00:00` while the header keeps the episode span. `package_count`
  is `ceil(total ÷ package)`; the last package may be short.
- Four shapes: `standard` (the package above), `continuous` (one action chain, cutting
  forbidden), `fight` (the fight's rules once, then short uneven beats) and `script_doc`
  (assets → the whole dialogue → `Shot X.Y` rows in ≤15 s / ≤8 shot segments with a duration
  check per segment).
- The speech-rate tier (正常 3.0 / 急切 4.0 / 沉重 2.5 characters per second) is a global
  constraint: a line that cannot be said inside its generation shot is reported, not squeezed.

**`backend/app/core/asset_sheets.py`** reads the task once and writes the sheets that have to
be locked before anything is generated: characters (face close-up beside front / profile /
back, costume broken out, white ground, no text), scenes (one image as a four-angle grid, the
prompt opening with 「不能出现其他人, 无人, 纯场景,」 and closing with `no humans, empty,
landscape only`), props and the palette card. A character sheet keeps only what a camera can
see and reports the temperament words it dropped; a scene with a bare name is renamed by its
light, material or time; a prop earns a sheet only if the sentence that names it also does
something with it.

Both are read-only: `GET /api/drama/{task_id}/prompt-packages` (scene, length, variant,
delivery) and `GET /api/drama/{task_id}/asset-sheets`.

## When a shot comes back wrong

`backend/app/core/generation_feedback.py`. A person watching a clip says 「脸崩了」 or 「手是六
根手指」; that sentence is classified into one of ten failure kinds, each carrying a diagnosis,
concrete fixes and the negative terms it earns.

- **Escalation.** A shot that keeps failing gives something up in a fixed order — simplify the
  action, fewer people, fewer effects, split the shot, widen the framing — so the fourth attempt
  is not the first with a new seed. Past the last cut the shot is declared out of the model's
  reach, with equivalent-expression suggestions.
- **Memory.** The same failure twice on the same model becomes that model's weakness
  (`PROMOTE_AFTER = 2`); a fix that worked twice becomes a project pattern. Stage 5 replays both
  as preventive notes in the named rules and as extra negatives, so the next shot is designed
  around a known weakness instead of rediscovering it.
- The ledger lives in `assets["5_feedback"]` (per-shot history capped at 20 entries, per-model
  profiles, patterns, counts).

`POST /api/drama/{task_id}/shots/{shot_id}/feedback` takes the report and answers with the plan;
`GET /api/drama/{task_id}/feedback` is the ledger plus the catalogue the UI shows.

## API and UI

- `GET /api/production/style-packs` → `{default, packs: [{id, name, medium, summary, lock,
  tone_slots, tone_default, camera, through_colours, negatives, sound}]}`.
- The create dialog has a 「画面风格锁」 select next to 导演风格; `TaskConfig.stylePack` carries it.

## Compatibility

- Projects without `style_pack` behave exactly as before: the default pack reproduces the old
  caption, the old photoreal wording and the old negatives.
- `build_video_batch_prompt` is gone; its duration and no-shorthand contract moved into
  `compile_shot_prompt`, with the same tests.
- Stored tasks are unchanged apart from two new per-shot fields in stage 5.

## Not yet done (tracked in PROGRESS.md)

Palette cards are built and validated but no card image is generated yet; the mask-transition
and white-model capability templates, the Seedance prompt-package export, the asset-sheet
formats, genre / intent routing and the generation feedback loop are later phases.

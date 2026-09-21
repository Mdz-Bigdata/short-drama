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
environment → colour → effects → dialogue → dialogue_notes → end_state → sound → closing →
rules → negatives`.

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

# 数字演员设定集（Actor Sheet）Implementation

Replaces the five-panel turnaround with a 21:9 three-region character design sheet.
One generation call per character, then the sheet is split into independent assets.

## Layout contract

```text
┌──────────────┬───────────────────────────────┬──────────────────────────────┐
│   主肖像     │         全身与元素            │          细节矩阵            │
│    20%       │            40%                │            40%               │
│              │  40% of mid │ 60% of mid      │                              │
│  1 大正面    │  1 全身立绘 │ 上: 1×3 三视图  │  4 行 × 3 列 = 12 格         │
│  近景特写    │             │ 下: 2×4 元素    │                              │
└──────────────┴─────────────┴─────────────────┴──────────────────────────────┘
```

The layout follows the actor-sheet prompt the user supplied on 2026-10-15. The column titles
are Chinese, and every sub-cell carries a numbered Chinese caption in the white gap below it.
Real output often drifts from it: uneven columns, a 2×3 element grid, three views in one panel,
no separate full body. The cutter therefore finds the panels and assigns them by role instead of
using these numbers (see below). Defaults:

```text
left_portrait        0.00 – 0.20
middle               0.20 – 0.60     inner split at 0.40 of the middle
right_details        0.60 – 1.00
title_band_ratio     0.10            dropped; no cell includes it
mid_right_top_ratio  0.62            three-view above, element grid below
```

### Cells, in split order

| # | key | source region | framing |
|---|---|---|---|
| 1 | `portrait` | 左栏 | 正面近景，头部至胸部以上 |
| 2 | `full_body` | 中左 | 正面全身立绘，脚底对齐底基线 |
| 3–5 | `front` `profile` `back` | 中右上 | 正面 / 90° 侧面 / 背面全身 |
| 6–9 | `element_shoe` `element_waist` `element_wrist` `element_collar` | 中右下 第1行 | 鞋履 / 腰部扣环 / 护腕手部配饰 / 领口肩部刺绣 |
| 10–13 | `element_fabric` `element_hair` `element_hand` `element_hem` | 中右下 第2行 | 面料微距 / 发饰拆解 / 手部姿态 / 裙摆刺绣 |
| 14–16 | `face_front` `face_three_quarter` `face_three_quarter_right` | 右栏 第1行 | 正脸 / 左侧 45° 侧脸 / 右侧 45° 侧脸 |
| 17–19 | `face_back_hair` `detail_collar` `detail_chest` | 右栏 第2行 | 后脑发饰 / 领口肩颈 / 前襟胸部纹样 |
| 20–22 | `detail_waist_knot` `detail_cuff` `detail_texture` | 右栏 第3行 | 腰部束结 / 袖口末端 / 材质微距 |
| 23–25 | `detail_shoe` `detail_eye` `detail_accessory` | 右栏 第4行 | 鞋履足部 / 眼妆微距 / 动态姿态或小配件 |

Every cell that was drawn is materialised as an asset (the user asked for every cell).

## Identity views

The five anchors the pipeline locks a character with change from five full-body
angles to **three full-body plus two head**:

```python
IDENTITY_VIEW_ORDER = ("front", "profile", "back", "face_front", "face_three_quarter")
```

`front` / `profile` / `back` come from the three-view strip; `face_front` and
`face_three_quarter` come from the detail matrix. The portrait and the other 20
cells are stored alongside but are not identity anchors.

### Backward compatibility

Stored characters carry the old keys. Reading keeps working through an alias map:

```text
front_three_quarter -> face_three_quarter     rear_three_quarter -> back
```

A record whose views are the old five is still `READY`; it is not regenerated for
the sake of the new layout. `element_library_reuse.REQUIRED_VIEWS` accepts either set.

## Prompt

`build_actor_sheet_prompt(name, identity_dna, visual_style)` writes the sheet in the
user's own terms: 21:9, 高级灰白渐变背景, 极细纯白分隔线, 区域标题
`MAIN PORTRAIT` / `FULL BODY & ELEMENTS` / `DETAIL MATRIX`, the three-region
proportions, the 1×3 / 2×4 / 4×3 grids, 三视图同比例同基线同头高, and the
layout prohibitions (不重叠、不粘连、无环境杂物). Identity DNA and style follow.
The existing problem-negative string and the designer's compiled negatives stay.

Image size moves from `2560x1440` (16:9) to `3360x1440` (21:9), env
`CHARACTER_SHEET_SIZE`.

## Splitting and quality

`split_actor_sheet(source, out_dir)` returns the cells it found, in the order above,
named `NN_<key>.png` with the fixed number from the table. The boxes come from
`actor_sheet_cutter.detect_actor_sheet_cell_boxes`, which does not crop by ratio or
by a fixed grid, because real output varies too much: column widths from a quarter to
a half, three views sharing one panel, two-column detail matrices, panels spanning two
rows, and gray sheets with white divider lines.

1. **Panels.** A row or column with almost no brightness jumps along it, and nothing
   dark, is a separator: a white gutter, a white line, plain background, or a
   gray-to-white gradient. Each column is cut recursively along those lines (XY-cut).
   Each leaf is trimmed to its content with a small margin.
2. **Titles.** Short leaves at the top of a column are title text and are dropped.
3. **Roles.** All left-column leaves together form the portrait. The tallest upright
   middle panel is the full body. The tall panels beside it are the three views,
   split evenly when the model drew them in one panel. The rest of the middle column
   is elements, in reading order, with the closest neighbours merged when there are
   too many. In the right column, the first two face-like panels in reading order
   are the face anchors. A face-like panel has solid skin and dark hair. The rest
   are details.

Element and detail cells the model did not draw are left out, not invented. The seven
`REQUIRED_CELLS` (portrait, full body, three views, two face anchors) always exist,
falling back to the layout's predicted box when no panel is found. It still refuses a
sheet whose aspect is outside 2.0–2.6.

`validate_actor_sheet_images(paths)` reads each cell from its file name, requires the seven
required cells, keeps the old duplicate-angle check on the five
identity views and adds: a cell that is near-uniform (blank or a solid fill) fails
that cell; the three full-body views must differ from each other; the portrait and
`face_front` must not be identical crops.

A failed check retries the whole sheet, as today.

## Frontend

`CharacterDesignerPage` shows the sheet with a region-aware viewer: the five identity
views stay the primary selector, the remaining element and detail cells sit behind a 「细节」 tab
grouped as 元素拆解 (up to 8) and 细节矩阵 (up to 12), listing only cells that were drawn. Labels live in `assetTabLabels.ts`.

## Known limitation

Face anchors are recognised by colour, not by a face detector. A sheet that puts no
face in its detail column's first rows can end up with an eye close-up, or a boot on
skin-coloured sand, as the three-quarter face. The prompt asks for faces in the first
row, so new sheets follow the reading-order rule.

## Six-view selector, fills and regeneration (2026-10-16)

- **Six views:** the identity selector shows the front face, the left 45° face, the right 45° face, the front full body, the 90° profile and the 180° back, in that order.
- **Five-anchor contract unchanged:** the right 45° face is the sheet cell `face_three_quarter_right` and is not an identity anchor. Library, readiness and video references still use the five anchors.
- **Mirrored right 45° face:** when a sheet has no right 45° face, `MIRRORED_CELL_SOURCES` mirrors the left one. The cell is marked `derived_from` and shows a 补位 tag. Mirroring swaps moles and partings to the other side, so it is never used as an identity reference.
- **Filled cells:** element and detail cells the model skipped are cropped from the portrait, full-body or back panel, per `DERIVED_CELL_SOURCES`. They are also marked `derived_from`.
- **Content-hashed file names:** crops are saved as `NN_<key>-<hash8>.png`. A re-split changes the URL, so the browser never shows a cached old crop.
- **Per-character regeneration:** `POST /api/drama/{task}/characters/regenerate {name}` redraws one actor sheet in the background. The current portrait is the identity reference. The old images stay unless the new sheet passes quality. Progress lives in `assets["3_character_regeneration"]`.

## High-definition identity views (2026-10-16)

At 3360×1440, each identity crop of the 25-cell sheet was only about 250–600 px, so it blurred when the page enlarged it.

- **Larger sheet:** the sheet is now generated at 5040×2160. If the provider returns nothing at that size, it retries at 3360×1440.
- **HD pass:** after a sheet passes quality, `app/core/actor_hd_views.py` makes two more images, with the sheet as the identity reference:
  - a face triptych at 3072×1024: front, left 45° and right 45°;
  - a full-body triptych at 3072×2048: front, 90° side and back.
- **Splitting:** each triptych is cut along its gutters and trimmed. The six crops replace the identity cells and are marked `hd`.
- **Turned-face check:** the face group is dropped if the three faces don't really turn, judged by an image-difference check.
- **Fallback:** the HD set is used only if the sheet still passes quality with it; otherwise the sheet crops stay.
- **Switch:** `CHARACTER_HD_VIEWS=0` turns the pass off. Tests turn it off by default.
- **Existing characters:** `POST /api/drama/{task}/characters/regenerate {name, mode: "hd"}` runs only the HD pass. The current portrait, front view and front face are inlined as references, and the sheet itself is kept.

## Regenerating 数字演员 from every entry point (2026-10-16)

- **Character designer, 数字演员 tab.** The toolbar has three buttons:
  - 全部重新生成 reruns every character's sheet. It calls `POST /api/drama/{task}/characters/regenerate` once per name and skips characters already regenerating.
  - 重新生成「name」 reruns only the selected character.
  - 生成缺失图片 reruns stage 3, which fills only characters that are missing or failed quality.

  The cast list shows 重新生成中 while a character's job is running.
- **Asset library, 数字演员.** `POST /api/elements/{id}/regenerate` used to only queue an `element_regeneration_requests` row that nothing consumed. It now:
  - Answers 202 and records `metadata.regeneration = {status: running, started_epoch}`. It answers 409 while a run is fresh; a run counts as stale after 15 minutes.
  - Runs `DramaService.regenerate_library_actor` in the background. If the actor belongs to one of the owner's projects and that project has the character, the project's `regenerate_character` does the work, so the project and the library get the same new sheet. Otherwise (deleted project, or a library-only actor) it renders a sheet from the library description, using the existing face or front image as the identity reference.
  - Copies the five identity views into their slots only when all five can be read and validated; otherwise it replaces nothing. It then records `done`, or `failed` plus the reason; the old images are kept on failure.

  The library page polls silently every 5 seconds while a run is in progress.
- **Project → library sync.** When a project regeneration succeeds, `DramaService.character_regenerated_hook` runs. `drama_api` wires it to `element_api.sync_project_actor_to_library`. It copies the five new identity views into the owner's library actor with the same name that is linked to that project, and records `synced_from_task`. It replaces nothing unless all five read and validate. It skips an actor whose own library regeneration is running, because that run files its result itself. It never creates actors. Failures are only logged; the project's new images stay.

## Redrawing skipped detail cells (2026-10-18)

- **Why.** The model skips some element/detail cells on the sheet. Those were filled by cropping the full-body or portrait panel by proportion (tagged 补位), which often landed on background. 沈知微's full-body cell was even a 151 px sliver, so every crop from it was blank.
- **Fallback crop** (`storyboard_assets._derived_crop`): proportions are taken over the figure's bounding box, not the whole panel; a blank result widens to the figure band, then the whole figure; a sliver source (aspect < 0.28) is swapped for the `front` view. A 补位 cell is never blank.
- **Real redraw** (`actor_detail_fill.py`, mode `details`, also run automatically after a new sheet): the 补位 cells are drawn on one square board (2×2, 3×2 or 3×3, ≤8 real cells) with the sheet as identity reference, then split and blank-checked. Switch: `CHARACTER_DETAIL_FILL=0`.
- **Lessons from the first live run (沈知微):**
  - Asked for 4×2, Seedream drew 5×2 and inserted an unrequested full-body figure in the middle column. Snapping four cut lines onto five gutters mislabelled three cells. The splitter now rejects a board whose gutters don't match the requested grid (missing, duplicated or extra gutters), and the prompt says 不多不少 and forbids full-body figures. Square grids are used because the model follows them better.
  - The provider's "AI生成" watermark sits in the board's bottom-right corner, so the last slot is always a spare that is discarded.
  - Smooth skin (an eye close-up) reads as a gutter to the XY-cut, so the real-panel path is only trusted when every panel is about one cell in size and sits in its own grid cell.
  - That board was salvaged by hand (real 5×2 gutters, middle column skipped), so 沈知微's eight cells come from it; the last one carries the watermark.

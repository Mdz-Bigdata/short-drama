# 数字演员设定集（Actor Sheet）Implementation

Replaces the five-panel turnaround with a 21:9 three-region character design sheet.
One generation call per character, then the sheet is split into independent assets.

## Layout contract

```text
┌──────────────┬───────────────────────────────┬──────────────────────────────┐
│ MAIN PORTRAIT│ FULL BODY & ELEMENTS          │ DETAIL MATRIX                │
│    20%       │            40%                │            40%               │
│              │  40% of mid │ 60% of mid      │                              │
│  1 大正面    │  1 全身立绘 │ 上: 1×3 三视图  │  4 行 × 3 列 = 12 格         │
│  近景特写    │             │ 下: 2×4 元素    │                              │
└──────────────┴─────────────┴─────────────────┴──────────────────────────────┘
```

Region proportions live in one place (`ACTOR_SHEET_LAYOUT`) so they can be tuned
against real output without touching the splitter. Defaults:

```text
left_portrait        0.00 – 0.20
middle               0.20 – 0.60     inner split at 0.40 of the middle
right_details        0.60 – 1.00
mid_right_top_ratio  0.64            three-view above, element grid below
```

### Cells, in split order

| # | key | source region | framing |
|---|---|---|---|
| 1 | `portrait` | 左区 | 正面近景，头部至胸部以上 |
| 2 | `full_body` | 中左 | 正面全身立绘，脚底对齐底基线 |
| 3 | `front` | 中右上 1/3 | 正面全身 |
| 4 | `profile` | 中右上 2/3 | 90° 侧面全身 |
| 5 | `back` | 中右上 3/3 | 背面全身 |
| 6–9 | `element_shoe` `element_waist` `element_wrist` `element_collar` | 中右下 第1行 | 鞋履 / 腰部扣环 / 护腕手部配饰 / 领口肩部刺绣 |
| 10–13 | `element_fabric` `element_hair` `element_hand` `element_hem` | 中右下 第2行 | 面料微距 / 发饰拆解 / 手部姿态 / 裙摆刺绣 |
| 14–16 | `face_front` `face_three_quarter` `face_back_hair` | 右区 第1行 | 正脸 / 3/4 侧脸 / 后脑发饰 |
| 17–19 | `detail_collar` `detail_chest` `detail_waist_knot` | 右区 第2行 | 领口肩颈 / 前襟胸部纹样 / 腰部束结 |
| 20–22 | `detail_cuff` `detail_texture` `detail_back_tie` | 右区 第3行 | 袖口末端 / 材质微距 / 背部暗扣系带 |
| 23–25 | `detail_shoe` `detail_eye` `detail_accessory` | 右区 第4行 | 鞋履足部 / 眼妆微距 / 动态姿态或小配件 |

All 25 are materialised as assets (the user asked for every cell).

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

`split_actor_sheet(source, out_dir)` crops by `ACTOR_SHEET_LAYOUT` and returns 25
paths in the order above. It refuses a sheet whose aspect is outside 2.0–2.6
(the model did not honour 21:9) rather than cropping garbage.

`validate_actor_sheet_images(paths)` keeps the old duplicate-angle check on the five
identity views and adds: a cell that is near-uniform (blank or a solid fill) fails
that cell; the three full-body views must differ from each other; the portrait and
`face_front` must not be identical crops.

A failed check retries the whole sheet, as today.

## Frontend

`CharacterDesignerPage` shows the sheet with a region-aware viewer: the five identity
views stay the primary selector, the 20 remaining cells sit behind a 「细节」 tab
grouped as 元素拆解 (8) and 细节矩阵 (12). Labels live in `assetTabLabels.ts`.

## Known limitation

An image model does not honour a 25-cell grid exactly. Fixed-proportion cropping
therefore drifts. The layout constants are one edit away, the aspect gate rejects a
sheet that ignored 21:9, and the per-cell blank check catches the worst drift — but
the first batch of real output has to be eyeballed and the constants tuned.

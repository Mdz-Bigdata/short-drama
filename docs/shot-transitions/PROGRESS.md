# Shot Transitions Progress

## Status: Complete

## Quick Reference

- Research: `docs/shot-transitions/RESEARCH.md`
- Implementation: `docs/shot-transitions/IMPLEMENTATION.md`
- Skill spec: `backend/skills/shot-transitions-master/SKILL.md`

## Phase Progress

### Phase 1: Cut planner and checks

**Status:** Completed

### Phase 2: 30-degree rule in the spatial solver

**Status:** Completed

### Phase 3: Stage 4 / 5 / 7 wiring

**Status:** Completed

### Phase 4: Spatial fixes the checks exposed (holds, back-off cap, one move per person, solo swings, size shorthand)

**Status:** Completed

### Phase 5: Frontend cut badge, tests, documentation

**Status:** Completed

## Session Log

### 2026-09-17

- The three linked WeChat articles returned WeChat's verification page on every fetch and were not read;
  the user's pasted six-dimension summary is the specification.
- Replaced the four fixed panel cut sentences with a per-cut plan; nine pairwise checks join the
  storyboard continuity list; the final film is composed with the planned device after the continuity gate.
- Writing the teleport check exposed a real staging bug: a walk-up started 1.2 m off the mark while the
  previous shot showed the person on it. Fixed with held start points and one staged move per person.
- A 1500-plan random sweep through both planners: spatial errors 0; teleports 0; repeated angles 131 → 8
  (remaining ones have no clear lens 30° away); a back-off from an embrace no longer crosses the partner.
- Backend: 904 tests pass (34 new); Ruff clean. Frontend: storyboard suite passes (1 new); `tsc -b` and ESLint clean.

### Notes

- Everything is deterministic, reading the table text by vocabulary; a cut the vocabulary does not recognise
  falls through to a plain hard cut.
- All transition checks are warnings. The rules are defaults (see the spec's 「灵活运用」).

## 接镜思路与接不上的诊断（2026-11-04）

- 规划器新增三种接法：动作呼应、遮挡转场、同物换境；图形匹配补斜线；同景换时写明机位与陈设不变。
- 切点新增 `sound_join` / `sound_note`（J-cut、L-cut）和 `watch`（回看核对项）。声画错位不进视频提示词，由成片合成落地：动画面的切点、不单独挪配音，见下一节。
- 新增检查（都是 warning，不触发自动改分镜）：`transition_new_information`、`transition_action_replay`、`transition_screen_direction`、`transition_motion_energy`、`transition_camera_breath`，有空间方案时再加 `transition_attention_jump`。
- 画布新增工具 `link_design`、`frame_bridge`；首尾帧比例不同时阻止运行（只查本机图片）。
- 知识章节 `cut-connection-ideas` 进入阶段 4 分镜写作。没有采用原文的运动幅度数值和模型星级；本项目仍不用硬切。

## 成片合成里的 J-cut / L-cut（2026-11-04）

- `media_compositor.plan_sound_joins` 算每一刀怎么错开。L 把上一镜片尾剪短，台词越过切点；J 剪掉下一镜片头，台词在画面之前响起。配音和画面的相对位置不变。
- 只作用于阶段 6 的逐镜配音。片段自带的声音在合成时本来就被丢弃（`-an`），环境声是整条一轨，所以「下一场鼓声先到」这种做不到。
- 做不到的一刀（没有配音、台词压台词、要剪太多画面、转黑）按同切合成，原因写回 `clip.sound_in.result`。
- 同一连续镜头切开的后半段不自动错开：片头一剪就接不上上一段尾帧。
- 剪映草稿用同一份 `plan_sound_joins` 排画面和配音，配音段按真实长度放，同一轨上不重叠。单集合成（`ep{n}`）还没有带上错开。

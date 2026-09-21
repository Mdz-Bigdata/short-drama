# Shot Transitions Implementation

## Overview

```text
分镜表提示词 ← TABLE_BRIEF【镜头衔接】
  → 分镜表 (LLM) → 镜头列表
  → 空间方案（站位 / 机位；30 度重解）
  → plan_transitions(shots, stage_plan, previous_shot, first_of_episode)
      ├ cuts   每一刀：转场方式 · 衔接手法 · 带过去的线索 · 动势 · 景别变化 · 机位方向变化 · 出剪 / 入剪
      └ checks 九项衔接检查
  → 面板 edit_in / edit_out / start_state / end_state，镜头 continuity_in / continuity_out / cut_in
  → 提示词详情 internal_linkage「逐镜衔接：…」+ continuity_checks
  → 第 5 阶段 clip 记录 cut_in
  → 第 7 阶段 final_cut_transitions：连续性质检先行，再按 cut_in.compositor 合成
```

Spec: `backend/skills/shot-transitions-master/SKILL.md`. Code: `backend/app/core/shot_transitions.py`.
Deterministic, no model call; the only model-facing change is the `TABLE_BRIEF` paragraph.

## Cut decision

`_decide(first, second, first_of_episode)` returns `(kind, technique, carries, reasons)`, first match wins:

| Order | Condition | Kind · technique |
|---|---|---|
| 1 | nothing precedes | `fade · opening` at the top of an episode, else `cut · opening` |
| 2 | enters / leaves a flashback, dream, memory | `dissolve · flashback` |
| 3 | big time jump (N 年 / 月 / 周后, 多年以后) | `fade · chapter` |
| 4 | time passes (次日, 片刻之后, 良久…) or time of day differs | `dissolve · time_passage` |
| 5 | scene or location changes | `match_cut · graphic_match` (shared shape) → `cut · action_match` (exit, same person) → `dissolve · scene_change` (warm ↔ cool) → `cut · scene_change` |
| 6 | a look, then a POV / insert / someone else | `cut · eyeline_match` |
| 7 | a POV / insert, then people | `cut · reaction` |
| 8 | one action family in both, same person | `cut · action_match` |
| 9 | two singles of different people | `cut · shot_reverse` |
| 10 | otherwise | `cut · plain` |

Durations: cut / match cut 0 s, dissolve 0.5 s, fade 0.8 s. `motion_join` comes from `move_kind` of
both shots; an optical transition settles both pictures regardless. With a spatial plan,
`lens_change_deg` is the angle between the two lenses measured at the second shot's target.

## Checks

| Code | Severity | Needs plan | Fails when |
|---|---|---|---|
| `transition_shot_size_step` | warning | no | same scene, size leap > 4 steps, not shock / reversal / insert / POV |
| `transition_thirty_degree` | warning | yes | same scene, `repeats_the_angle` still true after the planner's re-solve |
| `transition_eyeline_answered` | warning | no | POV with nobody looking before it; look → insert → someone else |
| `transition_motion_direction` | warning | no | adjacent moves oppose (push/pull, rise/fall, left/right pan or track) |
| `transition_state_continuous` | warning | yes | same scene hard cut; a person visible at the end of shot A starts shot B > 0.8 m away |
| `transition_cause_before_effect` | warning | no | effect word before its cause word, no earlier cause, not suspense / shock / reversal |
| `transition_light_continuity` | warning | no | same scene hard cut with different time of day or opposite warm / cool tone |
| `transition_rhythm` | warning | no | ≥ 5 timed shots all equal; a fast shot ≥ max(8 s, 1.8 × median) |
| `transition_emotion_bridge` | warning | no | grief / fear directly against comedy |

All are warnings: the 180-degree rule, which is the one that must stop production, stays an
error in the spatial stage. The planner never stages a jump itself (see *Spatial changes*), so
`transition_state_continuous` fires only when an edit moves someone.

## Pipeline wiring (`backend/app/service/drama_service.py`)

- Stage 4 table prompt: `+ shot_transitions.TABLE_BRIEF`.
- After the spatial plan: `scene_lead_in(assets["4"], breakdown scene order, scene_id)` gives the last shot of
  the nearest earlier scene with shots; it is used only inside the same episode, otherwise the scene is
  the top of an episode and fades in. `panel_fields` fills the four panel fields and the shot's
  continuity text; `shot_summary` is stored as `shot["cut_in"]`. Any exception keeps the old constants.
- `production_context["transitions"] = {summary, checks}` → `StoryboardDirectorRequest.transition_checks`
  → `continuity_checks`; `internal_linkage` becomes `逐镜衔接：入场→1 淡入淡出·开场；1→2 …`.
- Stage 5 clip records carry `cut_in`.
- Stage 7 calls `final_cut_transitions(included_shots)`: `continuity.plan_transition` still judges every
  cut and raises on a rejected one; an accepted cut with `cut_in.compositor` in
  `hard_cut / match_cut / crossfade / dip_to_black` is composed that way (`planned_cut` recorded in the
  report); otherwise the gate's own transition is used.

## Spatial changes made for this feature

- `coverage.repeats_the_angle`, `lens_bearing`, `bearing_change_deg`, `size_rank`; `solve_camera(avoid_bearing=…)`;
  a 30-degree pass in `build_plan`.
- Lone subjects get swing candidates (±25–60°) so the solver has somewhere else to go.
- `canonical_size` reads shot-list shorthand as whole tokens after Chinese terms.
- `ActorOverride.hold`; walk-ups / back-offs hold the start point in earlier shots; back-offs never start past
  the partner; one staged move per person per scene; `set_shot_override` accepts `hold`.
- `spatial_action_changes_state` no longer flags a second walk by someone already staged once.

## Frontend

`StoryboardShot.cut_in` (`StoryboardWorkspace.tsx`). Each frame shows the cut into it at the top left:
hard cuts on hover / selection, dissolves, fades and match cuts always (cyan). The new checks appear in
the prompt dialog's continuity list without changes.

## Compatibility

- Shots without `cut_in` (older tasks) render and compose exactly as before.
- Panel schema and prompt-detail shape are unchanged; `transition_checks` is an optional request field.
- Stored spatial plans load unchanged (`hold` defaults to false).

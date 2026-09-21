# Shot Transitions Research

## Overview

How adjacent storyboard shots should hand over to each other: the relations and rules that make a
sequence of separately generated pictures read as one continuous piece of film.

## Sources

| Source | Status | Use |
|---|---|---|
| User-supplied summary 「多张分镜之间自然过渡的关系和规则」 | Received in full | The specification: six dimensions (logic, picture, motion, matching, rhythm, transition device) and their rules |
| Three WeChat articles linked with the summary (`mp.weixin.qq.com/s/lCZsY6HjcELNeXKav9KtHA`, `…/39EfhjwLLHmIWCSoTOCgfA`, `…/nTASqwJh2CYj4yyFq9AsxA`) | **Not read.** Every fetch returned WeChat's 「环境异常，完成验证后即可继续访问」 verification page; the verification was not bypassed | None. Nothing here is attributed to their text |
| This repository | Read | Existing constants, checks and compositor transitions (below) |

The rules themselves are standard film-editing grammar (180/30-degree rules, eyeline match, match on
action, dissolves for elapsed time). The implementation is original.

## The specification, as received

1. **Logic** — time runs forward (a jump in time needs a transition, e.g. night → next day);
   space is coherent (a character walking out of a room is next seen outside the door, not
   teleported); cause precedes effect.
2. **Picture** — shot sizes step gradually (wide → medium → close), a leap only for shock; the
   180-degree rule; the 30-degree rule (a new shot of the same subject changes angle by ≥ 30° or
   size clearly); eyeline matching (A looks → what A sees → A's reaction); match on action (cut
   during the movement, pick it up in the next shot).
3. **Motion** — moving shots join moving shots in a consistent direction; static joins static; a
   move settles (落幅) before a static shot and a static shot holds (起幅) before a move.
4. **Matching** — a shared shape can carry a change of scene (graphic match); colour and light stay
   consistent or change gradually.
5. **Rhythm** — durations fit the content (fast action short, emotion held); emotional transitions
   do not snap (joy → grief without a buffer).
6. **Transition device** — hard cut for continuous action, dissolve for passing time / memory, fade
   for chapters and big jumps, match cut where pictures rhyme.
7. **Note** — the rules are to be combined and applied flexibly.

## What the pipeline did before

| Place | Behaviour |
|---|---|
| Stage-4 panels (`edit_in`, `edit_out`, `start_state`, `end_state`) | Four fixed sentences, identical on every panel of every scene |
| Shot `continuity_in / continuity_out` | Generic sentences, not tied to the neighbouring shot |
| `shot_table_rules.py` | Checks the table on its own (size stacking, durations, composition wording); nothing about pairs of shots except repeated sizes |
| Spatial stage | 180-degree rule measured per scene; no 30-degree rule; walk-ups started 1.2 m off the mark while the previous shot showed the person on it |
| Stage 7 (`continuity.plan_transition`) | Picks hard cut / crossfade / match cut from a six-field continuity state; knows nothing about time passing, flashbacks or chapters |
| Compositor | Already supports `hard_cut`, `match_cut`, `crossfade`, `dip_to_black`, `neutral_bridge` |

## Gaps closed

- Every cut now has a plan (device, technique, what carries across, cut-point behaviour on both sides).
- The panel sentences and shot continuity text describe that cut, not a template.
- Nine pairwise checks join the storyboard continuity list.
- The spatial planner enforces the 30-degree rule and no longer stages a jump into a walk.
- The final film uses the planned device once the continuity gate has passed the cut.

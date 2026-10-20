# Style Packs Research

## Overview

A production has to commit to one look and restate it in every prompt, or a series drifts
clip by clip. This is what the two Seedance 2.5 "engine" documents the user supplied are
about, and what the storyboard skill they sent calls the style prefix and the lock tags.

## Sources

| Source | Status | Use |
|---|---|---|
| `胶片电影风格_Seedance25_v3.0.md` (film-look engine, user's own copy, © notice, no open licence) | Read in full | Five-layer prompt architecture, verbatim style lock, 13-colour object-bound palette card, named iron rules, anti-leak rules for references drawn in another medium, mask transitions, extension restatement, duration tiers, sound policy |
| `Seedance2.5_Manju_Director_Engine_atom_punk.md` (atom-punk engine, personal-use terms) | Read in full | Three-segment architecture, causal chain levels, de-AI keyword list, per-shot camera kit with purpose alternates, 3–4 colour palette with tonal knobs, asset cards, reference budget by priority, QA rubric |
| `feichi-storyboard-skill_v2.zip` + `storyboard-script_用户手册(2).md` (commercial skill, no licence file) | Read in full | Lock tags L1–L7 and prompt assembly order, per-model prompt budgets and the pressure test with its truncation order, negative-prompt tiers, template and asset-extraction formats, genre routing, intent decoding, generation feedback loop |
| 12 WeChat article links | **Not read.** Every fetch returned WeChat's 「环境异常，完成验证后即可继续访问」 verification page; it was not bypassed | None |
| 「MiniMax-H3 立体声提示词实战」 (WeChat, AI漫剧实验室, 2026-09-16) + the user's own summary | Read in the in-app browser pane | The three-layer sound line (`center / ambient / music`), the weight order, the ≤60-word cap, the four-point checklist, the failure table, and voice locking with a reference sample and a fixed persona wording |

None of these carries an open licence, so nothing is vendored: the packs, the budgets and
the prompt layers here are the project's own code and wording, and the documents are
credited in `THIRD_PARTY_NOTICES.md` as behavioural references.

## What the sources agree on

- One **style lock**, copied verbatim into every prompt, plus a **tone line** that changes
  per segment so the lock does not flatten the whole film.
- **Anchors** (`@图片N` / reference notes) declared with what each one is *for*, and an
  anti-leak rule whenever a reference is drawn in a medium the finished frame is not
  (colour card, design sheet, storyboard, white model).
- A **palette card** stated three ways: the card image, a "strictly N colours" sentence, and
  the top HEX values inline. Colours bound to visible objects, never to "shadow" or "mood".
- **Named rules** (identity, parts, camera, palette, physics, mask, extension, reference cap,
  lip sync) so a constraint can be pointed at rather than re-explained.
- **Negatives in tiers**: an always-on list, situational add-ons, and per-film custom items.
- A **per-model prompt budget**, with sound and environment cut first and the locks, subject,
  action and camera never cut.
- An **extension** restates the look, and the clip continues from the last frame's pose.

Where they disagree, the differences are recorded in the implementation doc: reference
count (≤9 core anchors vs 5–10 per character), direct generation length (≤10 s vs ~30 s),
and whether the camera rig may change per shot.

## What the project had

- `ModelGateway.DEFAULT_STYLE_CAPTION` forced *photorealistic live action, not anime, not 3D*
  on every Ark request, and `_enhancePromptWithRules` appended film grain, depth of field
  and colour-grade wording to every prompt — regardless of the chosen `director_style`,
  including the `anime` one.
- Stage-4 and stage-5 still prompts hard-coded "Photorealistic live-action cinematic film
  still"; `DEID_NEGATIVE` additionally banned anime, cartoon and 3D renders outright.
- The stage-5 video prompt (`build_video_batch_prompt`) had five fixed sections and no
  style lock, palette, named rules or negative list of its own.
- No per-model prompt budget anywhere: the same text went to Seedance, Kling and H3.
- `_ark_video` clamped every clip to 15 s, so Seedance 2.5's 30 s was unreachable even
  though `video_references.max_shot_seconds` already knew about it.

## Gaps closed in this phase

- A pack is chosen once per production and reaches the stills, the clips and the Ark
  `style_caption`; an animated production is no longer told to look photoreal.
- Every clip prompt is layered and carries locks, palette, named rules and negatives.
- Prompts are measured against the target model's budget and trimmed in a stated order.
- Seedance 2.5 clips can be 30 s.

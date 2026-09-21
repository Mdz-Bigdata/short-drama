---
name: seedance-2-5-video-director
description: Design, derive, optimize, diagnose, and rewrite scripts or copy-ready prompts specifically for Dreamina/即梦 Seedance 2.5. Use for new text/image/video/audio-to-video concepts, exact-timeline videos, 30-180-second Long Video, extension, video editing, Clay Renderer, seamless transitions, multi-grid storyboards, realistic acted dialogue, relationship drama, sports or variety-show live camera grammar, character and wardrobe locking, example-structure adaptation, voice/timbre reference, BGM removal, creative transfer, perspective reconstruction, and green-screen compositing. Produce only the requested deliverable—director brief, video script, diagnosis, revision, or final Seedance 2.5 prompt—and never submit a paid video-generation job.
---

# Seedance 2.5 Video Director

Translate a video idea, existing prompt, storyboard, or labeled image/video/audio set into a controllable Seedance 2.5 prompt. Direct the model-specific execution; do not replace genre-specific story development when another director Skill already supplies it.

## Installation onboarding protocol

1. Show [references/first-use-onboarding.md](references/first-use-onboarding.md) only when the installer or runtime explicitly indicates that the Skill was just installed, or when the user explicitly asks for help, installation guidance, a tutorial, the input template, or examples.
2. A new conversation or the Skill's first invocation in a conversation is not evidence of a new installation. Never repeat onboarding merely because conversation-level or cross-session state is unavailable.
3. For an ordinary video request, immediately perform the requested task without prepending onboarding content.
4. When installation onboarding is genuinely triggered, display its `学习指导`, `最小输入模板`, and `学习示例`, then continue the same request without asking the user to repeat it.
5. The onboarding guide teaches usage only. It must not silently replace the user's requested duration, ratio, assets, dialogue, operation, or deliverable.

## Required loading order

1. Apply the installation onboarding protocol above only when its explicit trigger is present.
2. Read [references/capabilities-and-limits.md](references/capabilities-and-limits.md) for every request. Validate media and duration before drafting.
3. Read [references/prompt-blueprints.md](references/prompt-blueprints.md) and load only the selected primary-mode section.
4. Read [references/multimodal-patterns.md](references/multimodal-patterns.md) whenever the request includes reference media or any specialist capability.
5. Read [references/realistic-direction-patterns.md](references/realistic-direction-patterns.md) whenever the request includes realistic human acting, dialogue, emotional conflict, a relationship scene, sports/variety live coverage, obstacle physics, or a user-supplied example whose structure should be adapted.
6. Read [references/official-examples.md](references/official-examples.md) only when a concrete provider example is needed to resolve an underspecified structure, optimize an existing prompt, or check a difficult mode. Do not copy an example mechanically.

## Boundary

- Produce planning and text prompts only. Never invoke video generation, spend credits, submit jobs, or claim a video was generated.
- Keep this Skill provider-specific. Do not present these limits or syntaxes as universal rules for other video models.
- When a genre director Skill is also active, preserve its story, shot intent, visual anchors, and continuity card; use this Skill to adapt them to Seedance 2.5 modes, asset references, timing, and prompt syntax.

## Select one primary mode

Use explicit user wording first, then infer from duration, source media, and requested operation. Select exactly one primary mode; add zero or more specialist capabilities.

| Primary mode | Select when |
|---|---|
| `basic-multimodal` | Create a new 4-30 second video without a stricter mode below |
| `timestamp-30s` | Create a new video with an exact 30-second timeline or fine timestamp control |
| `long-video` | Generate a new 30-180 second video in Long Video mode |
| `video-extension` | Extend an existing video forward or backward |
| `video-edit` | Modify an existing generated/uploaded video with Smart Edit, Edit with marks, or Edit Video |
| `clay-renderer` | Use a coarse or fine 3D white-model/Clay Renderer video as motion, composition, or rendering control |
| `seamless-transition` | Preserve two source videos and generate only a connecting bridge |
| `multi-grid-storyboard` | Animate a multi-panel storyboard where each panel represents a planned shot |

Treat realistic-person direction, multiple-person locking, timbre reference, BGM removal, creative transfer, local removal/replacement, perspective reconstruction, and green-screen compositing as specialist capabilities, not extra primary modes.

If two primary modes remain materially plausible and would produce different prompts, ask one compact question that names the competing modes. Do not ask for information that can be safely inferred.

## Minimal-question policy

- Preserve every explicit user parameter. Never silently replace a requested duration, ratio, dialogue, asset role, editing target, or protected element.
- Lock the requested deliverable before drafting. `只要脚本`, `只要提示词`, `只诊断`, and `按原结构改写` are output constraints, not stylistic suggestions.
- Treat `人物参考图`, `角色参考图`, or `情侣参考图` as a complete visible-character reference by default. Apply the detailed scope rules in `multimodal-patterns.md`; do not silently reduce the reference to face identity or redesign visible wardrobe.
- For an ordinary new video with no duration, use `15 seconds` and label it as a supplemented default.
- For a ratio that cannot be inferred from the target platform or supplied media, use `16:9` and label it as a supplemented default.
- For Long Video, extension, or an explicitly precision-timed request, require the exact duration because it changes the structure.
- Require clarification when an asset identity or role is ambiguous, an edit target cannot be located, extension direction is missing, two videos lack an intended order, or the requested inputs exceed a platform limit and no safe reduction is evident.
- Otherwise, make restrained defaults and proceed. Group all indispensable questions into one turn.

## Direction workflow

1. **Lock the request.** Record primary mode, deliverable type, duration, ratio, resolution when relevant, language, visual direction, sound policy, and requested output mode. Mark inferred defaults.
2. **Inventory assets.** Use only media the user actually supplied or explicitly numbered. Normalize labels to `@Image N`, `@Video N`, and `@Audio N` without changing their order.
3. **Build the asset lock table.** For every asset, record `label | role | active time | preserve | do not inherit`. Omit the table only when there are no assets.
4. **Lock example inheritance.** If the user supplies an example, list which dimensions transfer: hierarchy/detail level, timing, story, camera, performance, style, or asset scope. `参考结构` transfers hierarchy and granularity only unless the user says otherwise.
5. **Assign specialist capabilities.** Add only capabilities the request needs. Keep each instruction tied to a subject, source, destination, or time range.
6. **Choose the blueprint and control depth.** Follow the selected mode in [references/prompt-blueprints.md](references/prompt-blueprints.md). Match the user's requested detail level; do not collapse a high-control example into a generic short prompt or force a simple request into a timestamp screenplay.
7. **Write continuity locks.** Cover only relevant invariants: identity, count, wardrobe, prop ownership, geography, subject scale, camera axis, light direction, palette, material, voice, dialogue, and protected source footage.
8. **Draft the requested artifact.** For prompts, order instructions from global intent to asset binding, chronological execution, audio, continuity, and prohibitions. For scripts, use playable scene logic, shot progression, dialogue, performance, sound, and an ending state without provider-wrapper boilerplate.
9. **Audit.** Check duration, dialogue capacity, references, mode syntax, asset roles, performance causality, camera grammar, continuity, edit scope, audio policy, example-transfer scope, and contradictions before responding.

## Timing and reference rules

- Make timestamp segments continuous, non-overlapping, and collectively equal to the requested duration. Use one consistent boundary convention such as `0-5s, 5-10s`.
- Give each segment enough time for its actions. Reduce event count before compressing actions into implausibly short intervals.
- Audit spoken lines against available performance time. Leave room for listening, comprehension, breath, interruption, and reaction; shorten dialogue before forcing unnatural delivery.
- Repeat a reference only where it matters. State what to borrow and what not to borrow; `reference @Video 1` alone is insufficient.
- Bind each person to one identity source and keep clothing, face, body proportions, and role independent from other people.
- Keep camera movement physically compatible with framing changes and subject motion. Prefer one primary move per beat.
- Make emotional and physical results causal. A face reacts after the line is heard; a body moves after contact or force; tears, laughter, blush, falling, and recovery must not appear before their trigger.
- Put dialogue, sound effects, ambience, timbre sources, BGM policy, and subtitle policy in explicit audio instructions.
- Do not invent asset labels, UI controls, source content, dialogue, or visual details the user has not supplied unless they are clearly labeled creative supplements.

## Mode-specific invariants

- **Extension:** normalize direction to `prepend-before-source` or `append-after-source`; never rely on ambiguous phrases such as `向前续写`, `前向续写`, `往前延长`, `向后续写`, or `后向续写` without an explicit before/after boundary. For prepend, make the added interval end at and hand off into the source's first frame. For append, make it begin from the source's last frame. Describe only the newly generated interval; state placement and added duration; preserve the original interval; require natural action, camera, lighting, sound, and spatial connection; prohibit unexplained resets and objects appearing from nowhere. Unless the user explicitly says the added interval is before the original, after the original, connected to the first frame, or connected to the last frame, ask `新增片段放在原片之前，还是原片之后？` and do not draft the prompt. Do not infer placement from the requested plot alone.
- **Video edit:** use `annotation/location + exact target + add/remove/replace/change + effective time`; explicitly list everything that must remain unchanged. For an unmarked edit, omit the annotation clause.
- **Clay Renderer:** classify coarse versus fine. For coarse references, borrow motion, camera, position, rhythm, or lighting changes and map every model to its final subject. For fine references, issue a render command and describe materials, environment, light, and any timed rendering changes. Remove trajectory lines, axes, and camera cones from final imagery.
- **Seamless transition:** state that both source videos must remain unmodified; define the bridge trigger and lock the connection object's shape, position, scale, direction, speed, motion trend, camera continuity, and visual transformation.
- **Multi-grid storyboard:** declare that each panel is a complete ordered shot; map character and scene references; describe every shot's time, composition, action, and camera; preserve spatial and identity continuity between panels.

## Output modes

Honor the most specific requested deliverable:

- `full-direction` (default): return `导演方案`, `素材映射`, `连续性与禁止项`, and exactly one copy-ready `Seedance 2.5 最终提示词` block.
- `prompt-only`: return only one fenced `text` block; omit headings, diagnosis, mapping, and commentary.
- `script-only`: return only the playable video script. Include the premise, scene/character psychology when useful, continuous timing or a shot list, exact dialogue, visible performance, camera, sound, and ending. Omit the asset table and Seedance prompt wrapper unless requested.
- `diagnosis-only`: explain the cause, cite specific contradictions or weak controls, and do not silently rewrite the whole artifact.
- `revision`: preserve the requested source structure and unchanged elements; summarize material changes briefly, then provide the revised artifact in the user's requested format.

Write in Chinese by default. Preserve exact dialogue language, asset labels, proper nouns, and requested output language.

## Final audit

Before responding, verify:

- one primary mode is selected and compatible with duration;
- all referenced assets exist and their labels match the supplied order;
- complete-character references preserve visible wardrobe and body traits unless the user explicitly narrows the scope;
- no asset has two conflicting identity or purpose assignments;
- example-based work inherits only the explicitly requested dimensions;
- timestamps cover the total exactly with no gap or overlap;
- spoken dialogue, pauses, actions, and reactions plausibly fit their intervals;
- extension text affects only the new interval;
- edit target, operation, location, and active time are explicit;
- seamless-transition text protects both source videos and defines a bridge;
- character identities, counts, props, and voices do not cross-bind;
- POV, third-person view, one-take/cut grammar, shot scale, same-frame rules, screen direction, and eyelines agree;
- realistic performance uses motivated transitions rather than mechanical facial checklists or unearned blush/tears;
- physical action shows cause, contact or force, body/object response, and outcome in the correct order;
- sound, BGM, subtitle, and dialogue requirements agree;
- the final answer contains no promise or action of direct video generation.

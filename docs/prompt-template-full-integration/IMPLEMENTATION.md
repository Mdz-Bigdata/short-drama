# Prompt Template Full Integration Implementation

## Architecture

The feature adds one provider-neutral `ScriptPromptPipeline`. It receives
normalized source text and produces a versioned production package:

```text
SourceDocument
  -> ParsedScreenplay
  -> CharacterPromptProfile[] + ScenePromptProfile[]
  -> NineGridStoryboard[]
  -> ShotPromptBundle[] (storyboard image + motion + SD25)
  -> ConsistencyReport
  -> JSON / Markdown / CSV / XLSX / HTML
```

The `ShotMotionContract` remains the sole semantic source for both the image and
motion prompt. The SD25 compiler wraps the motion contract only after the pair's
fingerprints match.

## Phases

1. Add typed screenplay, profile, bundle, report, request, and response schemas.
2. Implement deterministic parsing, extraction, scene analysis, nine-shot
   planning, consistency validation, and safe exports.
3. Extend the SD25 compiler for ordered keyframes and complete delivery notes.
4. Add JSON and multipart file compilation endpoints.
5. Point default SD25 discovery at `~/.agents/skills/sd25-pe` while preserving an
   explicit environment override and legacy fallback.
6. Add focused unit/API/security tests and run the full backend/frontend gates.

## Compatibility

- Existing stage 4 and stage 5 behavior remains unchanged.
- Existing `/api/production/sd25/compile` remains the low-level compiler.
- New `/api/production/script-prompts/*` endpoints return compile artifacts and
  do not submit paid generation jobs.
- Provider submission remains a separate operation selected through the existing
  video-reference router.

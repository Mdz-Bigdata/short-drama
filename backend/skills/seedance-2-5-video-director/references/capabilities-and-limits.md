# Seedance 2.5 capabilities and limits

## Contents

- Source snapshot
- Mode limits
- Input requirements
- Stability guidance
- Validation behavior

## Source snapshot

- Source: `https://bytedance.larkoffice.com/wiki/NjnWwvf4BiFYFLk2RzrcEgaunGf`
- Document title: `【Dreamina】Seedance 2.5 User Guide`
- Document revision: `419`
- Snapshot organized: `2026-08-16`

Treat this local file as the V1 runtime authority so the Skill does not depend on network access or Lark permissions. If the Dreamina UI conflicts with this snapshot, state the discrepancy and follow the current UI for submission constraints; do not silently invent updated limits.

## Mode limits

| Mode | Duration or source rule | Notes |
|---|---|---|
| Basic, first frame, first/last frame, Omni Reference | 4-30 seconds output | Handbook also expresses this as 97-721 frames; output resolution listed as 480p or 720p |
| Long Video | 30-180 seconds output | Select Long Video instead of segment-by-segment extension |
| Video extension | Source video must be under 30 seconds | Describe only the new interval; handbook advertises nested continuation up to 60 seconds total |
| Smart Edit / Edit with marks / Edit Video | Prefer source videos within 20 seconds for stability | Longer sources may work with reduced stability |
| Seamless transition | Two ordered source videos | Keep both originals unchanged and generate the gap/bridge |
| Clay Renderer | Coarse or fine white-model reference video | Coarse is currently described as the more stable generation path |

Do not turn an ordinary `30 seconds` request into Long Video automatically. Use `timestamp-30s` for precise 30-second generation unless the user explicitly asks for Long Video behavior.

## Input requirements

### Images

- Formats: JPEG, PNG, WebP, BMP, TIFF, GIF, HEIC, HEIF.
- Aspect ratio `width / height`: greater than 0.4 and less than 2.5.
- Width and height: 300-6000 px.
- Single-image size: less than 30 MB.
- Request body: at most 64 MB; avoid Base64 for large files.
- Seedance 2.5 maximum: 30 images per request; handbook describes up to 4K for the maximum-count workflow.

### Videos

- Formats: MP4, MOV.
- Resolution: 480p-4K.
- Aspect ratio `width / height`: 0.4-2.5.
- Width and height: 300-6000 px.
- Total pixels: 409,600-8,295,044.
- Single-video size: at most 200 MB.
- Frame rate: 24-60 FPS.
- Single-video nominal duration: 2-30 seconds; implementation tolerance is described as 1.8-30.2 seconds.
- Maximum: 10 reference videos with a combined nominal duration of at most 30 seconds; implementation tolerance is described as 30.2 seconds.

### Audio

- Formats: WAV, MP3.
- Single-audio size: at most 15 MB.
- Request body: at most 64 MB; avoid Base64 for large files.
- Single-audio nominal duration: 2-30 seconds; implementation tolerance is described as 1.8-30.2 seconds.
- Maximum: 10 reference audio clips with a combined nominal duration of at most 30 seconds; implementation tolerance is described as 30.2 seconds.
- Audio-only reference input is supported in Seedance 2.5.

## Stability guidance

- Main subjects driven by reference video or audio: 1-5 is preferred; 6-10 may reduce stability.
- Main reference video/audio duration: 5-10 seconds is preferred; longer inputs may reduce stability.
- Subjects in still images: 1-8 is preferred; 9-12 may reduce stability.
- When all character identities are supplied through still images, apply the still-image guidance above: eight subjects remain within the preferred range and should not trigger a stability warning merely because the cast exceeds five.
- For more than five subjects, separate multi-view references into multiple images rather than one image containing many views. Stability order: multiple images with one view each is better than one image containing multiple views.
- Video edit source: within 20 seconds is preferred.
- Reference images for video editing: 1-5 is preferred; 6-8 may reduce stability.

Treat these as quality recommendations, not hard rejections.

## Validation behavior

1. Count actual or explicitly declared assets. Never count hypothetical placeholders.
2. Check format, individual duration, combined duration, size, ratio, and count when metadata is available.
3. If a hard limit is exceeded, stop prompt drafting and propose a concrete reduction, split, trim, re-encode, or alternate mode.
4. If metadata is unavailable, do not fabricate it. Add a short preflight reminder only when the missing metadata could block submission.
5. If the request is within hard limits but beyond a stability recommendation, continue and label the risk with a practical simplification option.
6. Never claim that a prompt can override an upload or UI limit.

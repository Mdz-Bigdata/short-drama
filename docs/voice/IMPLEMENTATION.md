# Character voices

One voice per character for the whole drama, and no two characters on one voice (user rule, 2026-11-11).

## Where a voice comes from

- **Cast** (stage 3 audition): `POST /api/drama/{task}/characters/voice/audition` renders previews of a neutral
  test line from the character's `voice_prompt`; `POST …/characters/voice/cast {name, generated_voice_id}` turns
  the chosen take into the character's `voice_id` (`app/core/voice_casting.set_voice`). The take is kept as
  `voice_take`, and the voice's public ElevenLabs preview as `voice_sample_url`.
- **Auto** (no audition): `voice_casting.assign_missing_voices` gives every speaker without a voice an unused
  account voice of the right gender, nearest in age to the designed `voice_desc`, and keeps it
  (`voice_source: "auto"` on the DNA, or `assets["3_auto_voices"]` for bit parts), with its preview as sample.
- `voice_taken_by` refuses a voice another character already has.

## Changing a voice after dubbing (`app/service/voice_relink.py`)

Allowed. Casting a new voice re-dubs every line that character speaks across the drama and updates every copy:
the clip's `voice_path`, `assets["6"].shot_voices`, each episode record's audio, the live and per-episode
timelines (`edit_timeline.with_new_sound`), and the shot workbench preview (`clip.preview_url`, the clip with the
new dub laid on; `video_url` is kept so the cut keeps its edits). Native-sound shots, whose voice is baked into
the clip, are switched to dubbing on the timeline. Finished films are not re-rendered; they are marked
`needs_render_for_voice` and each episode can be re-rendered on its own (`POST /timeline/render {episode}`).
`GET …/characters/{name}/voice-relink-preview?voice=` tells the character page what a change would redo (lines,
episodes, native shots, whether it is billed, films to re-render, `taken_by`); the page asks first when it costs
money. A relink in progress blocks stages 5–7 (`voice_relink.stage_refusal`); wording in `voice_relink.json`.

## Native-sound clips (`app/core/voice_reference.py`)

Models that make their own sound (MiniMax H3, Seedance 2.x …) get each speaking character's sample as reference
audio and a voice-lock line naming it (「音色参考：参考音频N」, or `<Audio N>` in the H3 six-part prompt), renumbered
after routing and removed when the request cannot carry the audio. Samples are cut to the model's limits
(`voice_reference.json` → `audio_limits`; H3 takes 2–15 s per audio, measured in a real run) and sent by their
public link; with no public media address and no inline support the sample is dropped, never failing the clip.
A stored clip is reused on a stage-5 rerun, so existing dialogue clips gain the sample only when regenerated.

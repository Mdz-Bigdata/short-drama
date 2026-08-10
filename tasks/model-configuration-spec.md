# Dynamic model configuration specification

Date: 2026-08-10
Status: implementation contract

## Outcome

Replace the browser-local hard-coded model popover with an administrator-managed,
PostgreSQL-backed model configuration center. It exposes text, image, video and
audio categories, dynamically discovers models from the configured provider API,
classifies text-only and multimodal text models together, supports connection
testing, saves selected models, and allows every saved model to be enabled or
disabled globally.

## Provider matrix

- Text: DeepSeek, Volcengine Ark, Alibaba Model Studio/Qwen, Gemini and OpenAI.
- Image: Volcengine Ark, Alibaba Model Studio/Qwen, Gemini and OpenAI.
- Video: MiniMax H3, Seedance and Kling.
- Audio: ElevenLabs, grouped into ASR, TTS, BGM/sound and music.

Provider names, protocol metadata and default official base URLs are product
configuration. The dynamic catalog's model IDs are never embedded in its frontend
or backend implementation. A model
may only appear after an authenticated discovery response from the supplied base
URL. Providers which do not expose a compatible model-enumeration response fail
with a clear error instead of receiving a fabricated catalog.

## Security contract

- Only an active administrator that has completed the forced password change may
  discover, test, save or globally toggle provider/model configuration.
- API keys are submitted only to the backend, never written to localStorage, never
  returned by an API, and never included in logs or upstream error messages.
- Saved API keys are encrypted with a server-side Fernet master key. Production
  requires `MODEL_CONFIG_MASTER_KEY`; local development may create a gitignored,
  mode-0600 key file in `backend/runtime/`.
- Base URLs must be HTTPS and their normalized host must match the selected
  provider's official host allowlist. Redirects are disabled, response sizes are
  bounded, request timeouts are short, and only non-billable GET discovery calls
  are used for discovery/connection tests.
- Third-party responses are untrusted. Model identifiers, names, descriptions and
  capability metadata are length/type checked and rendered as text.

## API contract

- `GET /api/model-configurations/providers`
- `GET /api/model-configurations`
- `POST /api/model-configurations/discover`
- `POST /api/model-configurations/test`
- `POST /api/model-configurations`
- `PATCH /api/model-configurations/{configuration_id}`
- `PATCH /api/model-configurations/{configuration_id}/models/{entry_id}`

Discovery and test inputs contain category, provider, base URL and either a new
API key or an existing configuration ID. Save additionally contains one or more
selected model IDs. The server re-discovers the catalog before saving and rejects
unknown selections. API responses expose only a short key hint and `has_api_key`.

## Classification contract

The normalizer understands OpenAI-compatible `data`, Gemini `models`,
ElevenLabs arrays and common nested `items` responses. Explicit provider metadata
is authoritative. When metadata is incomplete, bounded name/description patterns
classify output modality. Text models include a `multimodal` capability when the
response declares multiple input modalities or signals vision/omni/multimodal
input. Audio models include one of `asr`, `tts`, `bgm`, or `music`.

## Browser contract

- Opening either model button displays one shared modal styled as the supplied
  configuration reference, not the former compact hard-coded popover.
- The header exposes four tabs and a live four-column count summary.
- Provider selection fills its default official base URL. After provider, valid
  HTTPS base URL and API key are present, discovery runs with a debounce; a manual
  reload control remains available.
- Loading, empty, validation, upstream error and success states are visible and
  announced. API key visibility is opt-in and resets when the dialog closes.
- A discovered model can be selected, connection-tested, saved, cancelled, and
  subsequently selected for a drama task only while globally enabled.

## Acceptance tests

1. No previous `LLM_MODELS`, `IMAGE_MODELS`, `VIDEO_MODELS`, `TTS_MODELS` or
   `disabled_models` localStorage catalog remains.
2. A fake OpenAI-compatible response is dynamically normalized and text/vision
   models are grouped correctly; malicious or oversized responses are rejected.
3. Provider-host mismatch, HTTP URL, redirect, missing key, unknown returned model
   and non-admin mutation are rejected.
4. Ciphertext does not contain the plaintext API key, list responses never reveal
   it, and a saved configuration can be decrypted only by the server cipher.
5. Component tests cover four tabs, automatic discovery, model selection,
   connection test, save/cancel and global enable/disable.
6. Full backend tests, frontend tests, lint, build, dependency audit, secret scan,
   live PostgreSQL migration and browser smoke pass.

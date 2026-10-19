/**
 * Limits the browser and the server must agree on.
 *
 * The server sends them with `GET /api/auth/session`, where each one is read
 * from the code that enforces it. The defaults below only cover the moment
 * before that response arrives and the case where it cannot be reached.
 */
export interface ClientConfig {
  passwordMinLength: number;
  verificationCode: { length: number; cooldownSeconds: number };
  episodeCount: { min: number; max: number; default: number };
  scriptUpload: { maxBytes: number; extensions: string[] };
}

export const DEFAULT_CLIENT_CONFIG: ClientConfig = {
  passwordMinLength: 10,
  verificationCode: { length: 6, cooldownSeconds: 60 },
  episodeCount: { min: 1, max: 150, default: 3 },
  scriptUpload: {
    maxBytes: 25 * 1024 * 1024,
    extensions: ['.txt', '.md', '.markdown', '.docx', '.pdf', '.fdx'],
  },
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function positiveInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : fallback;
}

/** Read the server's `client_config`, keeping the default for any field that is missing or malformed. */
export function parseClientConfig(raw: unknown): ClientConfig {
  const source = record(raw);
  const code = record(source.verification_code);
  const episodes = record(source.episode_count);
  const upload = record(source.script_upload);
  const defaults = DEFAULT_CLIENT_CONFIG;

  const min = positiveInteger(episodes.min, defaults.episodeCount.min);
  const max = Math.max(min, positiveInteger(episodes.max, defaults.episodeCount.max));
  const preferred = positiveInteger(episodes.default, defaults.episodeCount.default);
  const extensions = Array.isArray(upload.extensions)
    ? upload.extensions.filter((item): item is string => typeof item === 'string' && /^\.[a-z0-9]+$/i.test(item))
    : [];

  return {
    passwordMinLength: positiveInteger(source.password_min_length, defaults.passwordMinLength),
    verificationCode: {
      length: positiveInteger(code.length, defaults.verificationCode.length),
      cooldownSeconds: positiveInteger(code.cooldown_seconds, defaults.verificationCode.cooldownSeconds),
    },
    episodeCount: { min, max, default: Math.min(max, Math.max(min, preferred)) },
    scriptUpload: {
      maxBytes: positiveInteger(upload.max_bytes, defaults.scriptUpload.maxBytes),
      extensions: extensions.length > 0 ? extensions : defaults.scriptUpload.extensions,
    },
  };
}

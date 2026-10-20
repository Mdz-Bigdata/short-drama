import { describe, expect, it } from 'vitest';

import { DEFAULT_CLIENT_CONFIG, parseClientConfig } from './clientConfig';

describe('parseClientConfig', () => {
  it('uses the defaults when the server sends nothing', () => {
    expect(parseClientConfig(undefined)).toEqual(DEFAULT_CLIENT_CONFIG);
    expect(parseClientConfig('nonsense')).toEqual(DEFAULT_CLIENT_CONFIG);
  });

  it('takes every limit the server names', () => {
    const config = parseClientConfig({
      password_min_length: 14,
      verification_code: { length: 8, cooldown_seconds: 120 },
      episode_count: { min: 2, max: 40, default: 6 },
      script_upload: { max_bytes: 1024, extensions: ['.txt', '.fdx'] },
    });

    expect(config).toEqual({
      passwordMinLength: 14,
      verificationCode: { length: 8, cooldownSeconds: 120 },
      episodeCount: { min: 2, max: 40, default: 6 },
      scriptUpload: { maxBytes: 1024, extensions: ['.txt', '.fdx'] },
    });
  });

  it('keeps the default for a field that is missing or malformed', () => {
    const config = parseClientConfig({
      password_min_length: -3,
      verification_code: { length: '6' },
      episode_count: { min: 5, max: 2, default: 99 },
      script_upload: { extensions: ['exe', 42] },
    });

    expect(config.passwordMinLength).toBe(DEFAULT_CLIENT_CONFIG.passwordMinLength);
    expect(config.verificationCode).toEqual(DEFAULT_CLIENT_CONFIG.verificationCode);
    // A range whose ceiling is below its floor collapses to the floor rather than inverting.
    expect(config.episodeCount).toEqual({ min: 5, max: 5, default: 5 });
    expect(config.scriptUpload).toEqual(DEFAULT_CLIENT_CONFIG.scriptUpload);
  });
});

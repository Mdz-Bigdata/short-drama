// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { API_BASE, ApiError, DEFAULT_API_BASE, apiRequest, apiUrl, isUnauthorized, onUnauthorized, resolveApiBase } from './client';

function respond(status: number, body: unknown = {}) {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as Response));
}

describe('apiRequest session handling', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('notifies every subscriber when the session has expired', async () => {
    respond(401, { detail: '会话已过期，请重新登录' });
    const first = vi.fn();
    const second = vi.fn();
    const unsubscribeFirst = onUnauthorized(first);
    const unsubscribeSecond = onUnauthorized(second);

    await expect(apiRequest('/api/elements?kind=scene')).rejects.toThrow('会话已过期，请重新登录');

    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
    unsubscribeFirst();
    unsubscribeSecond();
  });

  it('stops notifying after unsubscribe', async () => {
    respond(401);
    const listener = vi.fn();
    onUnauthorized(listener)();

    await expect(apiRequest('/api/elements?kind=scene')).rejects.toBeInstanceOf(ApiError);

    expect(listener).not.toHaveBeenCalled();
  });

  it('keeps other subscribers working when one throws', async () => {
    respond(401);
    const healthy = vi.fn();
    const unsubscribeBad = onUnauthorized(() => { throw new Error('listener blew up'); });
    const unsubscribeGood = onUnauthorized(healthy);

    await expect(apiRequest('/api/elements?kind=scene')).rejects.toBeInstanceOf(ApiError);

    expect(healthy).toHaveBeenCalledTimes(1);
    unsubscribeBad();
    unsubscribeGood();
  });

  it('does not confuse a backend outage with an expired session', async () => {
    respond(500, { detail: '内部错误' });
    const listener = vi.fn();
    const unsubscribe = onUnauthorized(listener);

    const error = await apiRequest('/api/elements?kind=scene').catch(caught => caught);

    expect(listener).not.toHaveBeenCalled();
    expect(isUnauthorized(error)).toBe(false);
    expect((error as ApiError).status).toBe(500);
    unsubscribe();
  });

  it('classifies only 401 as unauthorized', () => {
    expect(isUnauthorized(new ApiError('x', 401))).toBe(true);
    expect(isUnauthorized(new ApiError('x', 403))).toBe(false);
    expect(isUnauthorized(new Error('network down'))).toBe(false);
    expect(isUnauthorized(null)).toBe(false);
  });
});

describe('resolveApiBase', () => {
  it('falls back to the local development backend when nothing is configured', () => {
    expect(resolveApiBase(undefined)).toBe(DEFAULT_API_BASE);
  });

  it('uses the configured origin without its trailing slash', () => {
    expect(resolveApiBase(' https://api.example.com/ ')).toBe('https://api.example.com');
    expect(resolveApiBase('https://example.com/drama//')).toBe('https://example.com/drama');
  });

  it('treats an explicitly empty value as the page origin', () => {
    expect(resolveApiBase('')).toBe('');
  });
});

describe('apiUrl', () => {
  it('puts the API origin in front of a backend-relative path', () => {
    expect(apiUrl('/media/film.mp4')).toBe(`${API_BASE}/media/film.mp4`);
    expect(apiUrl('/api/elements/1/content')).toBe(`${API_BASE}/api/elements/1/content`);
  });

  it('leaves a complete address alone', () => {
    expect(apiUrl('https://cdn.example.com/media/film.mp4')).toBe('https://cdn.example.com/media/film.mp4');
    expect(apiUrl('//cdn.example.com/a.png')).toBe('//cdn.example.com/a.png');
    expect(apiUrl('data:image/png;base64,AAAA')).toBe('data:image/png;base64,AAAA');
    expect(apiUrl('blob:http://localhost/1')).toBe('blob:http://localhost/1');
  });
});

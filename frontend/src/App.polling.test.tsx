// @vitest-environment jsdom
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, value: hidden });
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('App polling pauses while the tab is hidden', () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  });

  it('stops the lobby task list poll when hidden and refreshes on return', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/auth/session')) return {
        ok: true,
        status: 200,
        json: async () => ({
          authenticated: true,
          user: { user_id: 'a1', username: 'admin', role: 'admin', must_change_password: false },
        }),
      } as Response;
      if (url.endsWith('/api/model-configurations')) return {
        ok: true, status: 200, json: async () => ({ items: [], globalDefaults: {} }),
      } as Response;
      if (url.includes('/api/drama/list')) return {
        ok: true, status: 200, json: async () => [],
      } as Response;
      return { ok: true, status: 200, json: async () => ({ items: [], total: 0 }) } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    const listCalls = () => fetchMock.mock.calls
      .filter(call => String(call[0]).includes('/api/drama/list')).length;

    await waitFor(() => expect(listCalls()).toBeGreaterThan(0));

    // Visible: the lobby keeps refreshing.
    await act(async () => { await vi.advanceTimersByTimeAsync(4_000); });
    const whileVisible = listCalls();
    expect(whileVisible).toBeGreaterThan(1);

    // Hidden: no further polling at all.
    await act(async () => { setHidden(true); });
    const atHide = listCalls();
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(listCalls()).toBe(atHide);

    // Visible again: refresh immediately rather than waiting out the interval.
    await act(async () => { setHidden(false); });
    expect(listCalls()).toBeGreaterThan(atHide);
  });
});

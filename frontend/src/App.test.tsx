// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from './App';


describe('App model configuration status', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('shows 已配置 and loads global defaults when the account has an enabled model', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/api/auth/session')) return {
        ok: true,
        status: 200,
        json: async () => ({
          authenticated: true,
          user: { user_id: 'admin-1', username: 'admin', role: 'admin', must_change_password: false },
        }),
      } as Response;
      if (url.endsWith('/api/model-configurations')) return {
        ok: true,
        status: 200,
        json: async () => ({
          items: [{ id: 'configuration-1', models: [{ id: 'saved-model-1' }] }],
          summary: { text: 1, image: 0, video: 0, audio: 0 },
          global_status: {
            configured: true,
            enabled_total: 1,
            enabled_model_ids: { text: ['global-writer'], image: [], video: [], audio: [] },
            default_model_ids: { text: 'global-writer', image: null, video: null, audio: null },
          },
        }),
      } as Response;
      if (url.endsWith('/api/drama/list') || url.endsWith('/api/drama/skills')) return {
        ok: true,
        status: 200,
        json: async () => [],
      } as Response;
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<App />);

    expect(await screen.findByRole('button', { name: /模型: 已配置/ })).toBeTruthy();
    expect(globalThis.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/model-configurations',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('keeps 未配置 when saved models exist but none is globally enabled', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/api/auth/session')) return {
        ok: true,
        status: 200,
        json: async () => ({
          authenticated: true,
          user: { user_id: 'admin-1', username: 'admin', role: 'admin', must_change_password: false },
        }),
      } as Response;
      if (url.endsWith('/api/model-configurations')) return {
        ok: true,
        status: 200,
        json: async () => ({
          items: [{ id: 'configuration-1', models: [{ id: 'disabled-model', enabled: false }] }],
          summary: { text: 0, image: 0, video: 0, audio: 0 },
          global_status: {
            configured: false,
            enabled_total: 0,
            enabled_model_ids: { text: [], image: [], video: [], audio: [] },
            default_model_ids: { text: null, image: null, video: null, audio: null },
          },
        }),
      } as Response;
      if (url.endsWith('/api/drama/list') || url.endsWith('/api/drama/skills')) return {
        ok: true,
        status: 200,
        json: async () => [],
      } as Response;
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<App />);

    expect(await screen.findByRole('button', { name: /模型: 未配置/ })).toBeTruthy();
  });
});

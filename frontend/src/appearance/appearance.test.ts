// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as brand from '../features/workbench/agentBrand';
import { applyAppearance, brandText, currentAppearance, isPublicAppearance, loadAppearance, type PublicAppearance } from './appearance';

const custom = (over: Partial<PublicAppearance> = {}): PublicAppearance => ({
  brand_name: '青岚影业', login_tagline: null, lobby_tagline: '短剧工作室', assistant_name: null,
  logo_frame: 'circle', assets: { favicon: '/api/public/appearance/assets/favicon?v=abc123abc123' }, customised: true, ...over,
});

afterEach(() => {
  applyAppearance(null);
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('appearance', () => {
  it('accepts only an answer of the public shape', () => {
    expect(isPublicAppearance(custom())).toBe(true);
    expect(isPublicAppearance({ ...custom(), logo_frame: 'star' })).toBe(false);
    expect(isPublicAppearance({ ...custom(), brand_name: 3 })).toBe(false);
    expect(isPublicAppearance({ ...custom(), assets: { logo: 'https://elsewhere.example/x.png' } })).toBe(false);
    expect(isPublicAppearance(null)).toBe(false);
  });

  it('puts the brand, the title and the icon in use, and the built-in one back', () => {
    document.head.innerHTML = '<link rel="icon" type="image/svg+xml" href="/favicon.svg" />';
    document.title = 'Novara · AI 短剧协同成片';
    applyAppearance(custom());
    expect(brand.PRODUCT_NAME).toBe('青岚影业');
    expect(brand.PRODUCT_TITLE).toBe('青岚影业');
    expect(brand.NOVARA_AGENT_NAME).toBe('青岚影业 AI');
    expect(document.title).toBe('青岚影业 · AI 短剧协同成片');
    const icon = document.querySelector<HTMLLinkElement>('link[rel~="icon"]')!;
    expect(icon.href).toContain('/api/public/appearance/assets/favicon?v=abc123abc123');
    expect(icon.getAttribute('type')).toBeNull();
    expect(brandText('lobby_tagline', 'AI 短剧协同成片')).toBe('短剧工作室');
    expect(brandText('login_tagline', '内置副标题')).toBe('内置副标题');

    applyAppearance(custom({ assistant_name: '小岚' }));
    expect(brand.NOVARA_AGENT_NAME).toBe('小岚');
    applyAppearance(null);
    expect(currentAppearance()).toBeNull();
    expect(brand.PRODUCT_TITLE).toBe(`${brand.DEFAULT_PRODUCT_NAME} ${brand.PRODUCT_VERSION}`);
    expect(brandText('lobby_tagline', 'AI 短剧协同成片')).toBe('AI 短剧协同成片');
  });

  it('an appearance that changes nothing is the built-in one', () => {
    applyAppearance(custom({ brand_name: null, lobby_tagline: null, assets: {}, customised: false }));
    expect(currentAppearance()).toBeNull();
    expect(brand.PRODUCT_NAME).toBe(brand.DEFAULT_PRODUCT_NAME);
  });

  it('falls back to the built-in appearance on an error, a bad answer or no answer in time', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({ ok: false, json: async () => ({}) } as Response);
    expect(await loadAppearance()).toBeNull();
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({ ok: true, json: async () => ({ brand_name: 1 }) } as Response);
    expect(await loadAppearance()).toBeNull();
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'));
    expect(await loadAppearance()).toBeNull();
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({ ok: true, json: async () => custom() } as Response);
    expect((await loadAppearance())?.brand_name).toBe('青岚影业');

    vi.useFakeTimers();
    vi.spyOn(globalThis, 'fetch').mockImplementationOnce((_input, init) => new Promise((_resolve, reject) => {
      (init?.signal as AbortSignal).addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    }));
    const pending = loadAppearance(1000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(await pending).toBeNull();
  });
});

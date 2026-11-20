// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AppearanceSettings, type AppearanceEditView } from './AppearanceSettings';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const view = (over: Partial<AppearanceEditView> = {}): AppearanceEditView => ({
  brand_name: null, login_tagline: null, lobby_tagline: null, assistant_name: null, logo_frame: 'rounded', assets: {}, customised: false,
  fields: [
    { id: 'brand_name', label: '品牌名', max: 6 },
    { id: 'login_tagline', label: '登录页副标题', max: 80 },
    { id: 'lobby_tagline', label: '大厅品牌标签', max: 40 },
    { id: 'assistant_name', label: '助手名', max: 40 },
  ],
  logo_frames: ['rounded', 'square', 'circle', 'none'],
  slots: [{ id: 'logo', label: 'Logo', max_bytes: 1048576, max_side: 2048 }, { id: 'favicon', label: '网页图标', max_bytes: 262144, max_side: 512 }],
  formats: ['PNG', 'JPEG', 'WEBP'],
  ...over,
});

describe('AppearanceSettings', () => {
  it('saves the text and frame that changed', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      if (init?.method === 'PUT') {
        const sent = JSON.parse(String(init.body));
        return { ok: true, status: 200, json: async () => view({ brand_name: sent.text.brand_name.trim(), logo_frame: sent.logo_frame, customised: true }) } as Response;
      }
      return { ok: true, status: 200, json: async () => view() } as Response;
    });
    render(<AppearanceSettings />);
    const name = await screen.findByLabelText('品牌名');
    const save = screen.getByRole('button', { name: '保存文字与外框' }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(name, { target: { value: '青岚影业七个字' } });
    expect(save.disabled).toBe(true);
    fireEvent.change(name, { target: { value: ' 青岚影业 ' } });
    fireEvent.change(screen.getByLabelText('Logo 外框'), { target: { value: 'circle' } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    expect(await screen.findByRole('status')).toBeTruthy();
    const put = fetchMock.mock.calls.find(call => call[1]?.method === 'PUT')!;
    expect(String(put[0])).toContain('/api/platform/appearance');
    expect(JSON.parse(String(put[1]!.body))).toMatchObject({ text: { brand_name: ' 青岚影业 ' }, logo_frame: 'circle' });
    await waitFor(() => expect((screen.getByLabelText('品牌名') as HTMLInputElement).value).toBe('青岚影业'));
    expect(save.disabled).toBe(true);
  });

  it('uploads an image to its slot, keeps typed text, and offers to remove it', async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push(`${init?.method ?? 'GET'} ${url.slice(url.indexOf('/api/'))}`);
      if (init?.method === 'POST') {
        expect(init.body).toBeInstanceOf(FormData);
        return { ok: true, status: 200, json: async () => view({ assets: { logo: '/api/public/appearance/assets/logo?v=0123456789ab' }, customised: true }) } as Response;
      }
      if (init?.method === 'DELETE') return { ok: true, status: 200, json: async () => view() } as Response;
      return { ok: true, status: 200, json: async () => view() } as Response;
    });
    render(<AppearanceSettings />);
    fireEvent.change(await screen.findByLabelText('品牌名'), { target: { value: '未保存的名字' } });
    fireEvent.change(screen.getByLabelText('上传Logo'), { target: { files: [new File(['png'], 'logo.png', { type: 'image/png' })] } });
    const image = await screen.findByRole('img', { name: 'Logo' });
    expect(image.getAttribute('src')).toContain('/api/public/appearance/assets/logo?v=0123456789ab');
    expect((screen.getByLabelText('品牌名') as HTMLInputElement).value).toBe('未保存的名字');
    fireEvent.click(screen.getByRole('button', { name: '移除Logo' }));
    await waitFor(() => expect(screen.queryByRole('img', { name: 'Logo' })).toBeNull());
    expect(calls).toEqual([
      'GET /api/platform/appearance', 'POST /api/platform/appearance/assets/logo', 'DELETE /api/platform/appearance/assets/logo',
    ]);
  });

  it('reports a refused upload', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => (
      init?.method === 'POST'
        ? { ok: false, status: 422, json: async () => ({ detail: '「Logo」只收 PNG、JPEG 或 WebP 图片' }) } as Response
        : { ok: true, status: 200, json: async () => view() } as Response
    ));
    render(<AppearanceSettings />);
    fireEvent.change(await screen.findByLabelText('上传网页图标'), { target: { files: [new File(['<svg/>'], 'a.svg', { type: 'image/svg+xml' })] } });
    expect((await screen.findByRole('alert')).textContent).toContain('只收 PNG');
  });
});

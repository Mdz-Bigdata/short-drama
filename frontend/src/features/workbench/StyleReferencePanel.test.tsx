// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { StyleReferencePanel, type StyleProfile, type StyleReferenceResponse } from './StyleReferencePanel';

const PROFILE: StyleProfile = {
  name: '雨夜霓虹', medium: 'live_action', summary: '湿润街道上的霓虹反光', lighting: '低位霓虹侧光',
  palette: [{ name: '霓虹品红', hex: '#D81B60', role: '招牌与反光' }, { name: '深青', hex: '#0B3C49', role: '' }],
  contrast: '高', temperature: '冷暖对撞', saturation: '偏高', camera_body: '数字电影机', lens: '35mm', grain: '细颗粒',
  texture: '湿润反光路面', composition: '低机位', era: '', mood: '孤独悬疑',
  lock: ['neon-lit rainy night + 霓虹雨夜'], positives: [], negatives: ['白天高调光'],
  style_caption: '霓虹雨夜电影质感',
};

function state(overrides: Partial<StyleReferenceResponse> = {}): StyleReferenceResponse {
  return { task_id: 't1', reference: null, current_pack: { id: 'film_35mm', name: '35mm 胶片', custom: false }, ...overrides };
}

describe('StyleReferencePanel', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('uploads a still, shows what was read and applies it as the project lock', async () => {
    let current = state();
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input).split('/api/drama/t1')[1];
      if (init?.method === 'POST' && url === '/style/reference') {
        calls.push('analyse');
        expect(init.body).toBeInstanceOf(FormData);
        expect((init.body as FormData).get('hint')).toBe('再冷一点');
        current = state({ reference: { profile: PROFILE, model: 'seer', filename: 'ref.png', analyzed_at: 'now', applied: false, base_pack: 'cinematic_realism' } });
        return { ok: true, json: async () => current } as Response;
      }
      if (init?.method === 'POST' && url === '/style/reference/apply') {
        calls.push('apply');
        current = { ...current, reference: { ...current.reference!, applied: true }, current_pack: { id: 'custom_x', name: '参考图·雨夜霓虹', custom: true }, stages_with_old_look: [3, 4] };
        return { ok: true, json: async () => current } as Response;
      }
      if (init?.method === 'POST' && url === '/style/reference/revert') {
        calls.push('revert');
        current = { ...current, reference: { ...current.reference!, applied: false }, current_pack: { id: 'film_35mm', name: '35mm 胶片', custom: false } };
        return { ok: true, json: async () => current } as Response;
      }
      return { ok: true, json: async () => current } as Response;
    });

    render(<StyleReferencePanel taskId="t1" />);
    const panel = await screen.findByRole('region', { name: '风格参考图' });
    expect(await within(panel).findByText(/当前风格锁：35mm 胶片/)).toBeTruthy();
    await userEvent.type(within(panel).getByLabelText('风格补充说明'), '再冷一点');
    await userEvent.upload(within(panel).getByLabelText('选择风格参考图'), new File([new Uint8Array([137, 80, 78, 71])], 'ref.png', { type: 'image/png' }));

    expect(await within(panel).findByText('湿润街道上的霓虹反光')).toBeTruthy();
    expect(within(panel).getByText('#D81B60')).toBeTruthy();
    expect(within(panel).getByText('neon-lit rainy night + 霓虹雨夜')).toBeTruthy();
    expect(within(panel).getByText(/由 seer 分析/)).toBeTruthy();

    await userEvent.click(within(panel).getByRole('button', { name: /设为本片风格/ }));
    expect(await within(panel).findByText(/第 3、4 阶段已生成的画面仍是旧风格/)).toBeTruthy();
    expect(within(panel).getByText(/当前风格锁：参考图·雨夜霓虹（来自参考图）/)).toBeTruthy();

    await userEvent.click(within(panel).getByRole('button', { name: /恢复原风格/ }));
    await waitFor(() => expect(within(panel).getByText('已恢复为「35mm 胶片」。')).toBeTruthy());
    expect(calls).toEqual(['analyse', 'apply', 'revert']);
  });

  it('says why when no model can read the image', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => (init?.method === 'POST'
      ? { ok: false, status: 422, json: async () => ({ detail: '没有可看图的文本模型：请在模型配置里启用一个标为「多模态」的文本模型' }) }
      : { ok: true, json: async () => state() }) as Response);
    render(<StyleReferencePanel taskId="t1" />);
    const panel = await screen.findByRole('region', { name: '风格参考图' });
    await userEvent.upload(within(panel).getByLabelText('选择风格参考图'), new File([new Uint8Array([1])], 'ref.png', { type: 'image/png' }));
    expect(await within(panel).findByText(/多模态/)).toBeTruthy();
    expect(within(panel).queryByRole('button', { name: /设为本片风格/ })).toBeNull();
  });
});

// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CharacterFaceSculpt } from './CharacterFaceSculpt';

const catalog = {
  layers: [{ key: 'bone', label: '骨相' }, { key: 'features', label: '五官' }, { key: 'skin', label: '皮肤' }],
  controls: [
    { key: 'face_shape', layer: 'bone', label: '脸型', type: 'choice', options: [{ value: 'melon', label: '瓜子脸' }, { value: 'oval', label: '鹅蛋脸' }] },
    { key: 'eye_size', layer: 'features', label: '眼睛大小', type: 'scale', steps: ['眼睛偏小', '眼睛略小', '', '眼睛略大', '眼睛大而明亮'] },
    { key: 'skin_tone', layer: 'skin', label: '肤色', type: 'choice', options: [{ value: 'wheat', label: '小麦' }] },
  ],
  presets: [
    { key: 'heroine_cool', label: '古装女主·清冷', values: { face_shape: 'melon', eye_size: 1 } },
    { key: 'look_soft', label: '五官·柔和杏眼', values: { face_shape: 'oval', eye_size: 1 }, scope: ['bone', 'features'], focus: 'eye_size' },
  ],
  focus_layers: ['bone', 'features'],
  expression_controls: [{ key: 'eyes', label: '眼', options: [{ value: 'crescent', label: '弯成月牙' }] }],
  expressions: [{ key: 'smile', label: '笑', words: ['笑'] }, { key: 'cry', label: '哭', words: ['哭'] }],
  limits: { note_chars: 60, tell_chars: 40, habit_chars: 40 },
};

const emptyPreview = {
  description: '女主角；鹅蛋脸', face_text: '骨相：鹅蛋脸', layers: {}, issues: [], expressions: {}, sheet_stale: false, stale_note: '',
};

function mockApi() {
  const calls: Array<{ url: string; method: string; body?: unknown }> = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method || 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const reply = (data: unknown) => ({ ok: true, status: 200, json: async () => data }) as Response;
    if (url.endsWith('/api/face-sculpt/catalog')) return reply(catalog);
    if (url.endsWith('/preview')) {
      return reply({
        ...emptyPreview,
        description: '女主角；骨相：瓜子脸',
        face_text: '骨相：瓜子脸；五官：眼睛略大',
        expressions: body?.expressions?.smile ? { smile: '林婉笑时：眼睛弯成月牙' } : {},
      });
    }
    if (method === 'PUT') {
      return reply({ name: '林婉', sculpt: body, revision: 1, preview: { ...emptyPreview, face_text: '骨相：瓜子脸', sheet_stale: true, stale_note: '脸已经改过，现有设定集和定妆图还是旧脸' } });
    }
    return reply({ name: '林婉', sculpt: { face: {}, notes: {}, expressions: {}, preset: '' }, revision: 0, preview: emptyPreview });
  });
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('CharacterFaceSculpt', () => {
  it('previews a preset, saves it to the character and tells that the sheet is now stale', async () => {
    const calls = mockApi();
    const onSaved = vi.fn();
    render(<CharacterFaceSculpt taskId="t1" characterName="林婉" onSaved={onSaved} />);

    const preset = await screen.findByRole('combobox', { name: /从预设开始/ });
    expect(screen.getByText('骨相：鹅蛋脸')).toBeTruthy();
    expect((screen.getByRole('button', { name: /保存到角色资产/ }) as HTMLButtonElement).disabled).toBe(true);

    await userEvent.selectOptions(preset, 'heroine_cool');
    await waitFor(() => expect(screen.getByText('骨相：瓜子脸；五官：眼睛略大')).toBeTruthy());
    expect(screen.getByRole('button', { name: '眼睛大小：眼睛略大' }).getAttribute('aria-pressed')).toBe('true');
    const previewCall = calls.find(call => call.url.endsWith('/preview'));
    expect(previewCall?.url).toContain(`/characters/${encodeURIComponent('林婉')}/face-sculpt/preview`);
    expect(previewCall?.body).toMatchObject({ face: { face_shape: 'melon', eye_size: 1 }, preset: 'heroine_cool' });

    await userEvent.click(screen.getByRole('button', { name: /保存到角色资产/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(calls.some(call => call.method === 'PUT')).toBe(true);
    expect(screen.getByText(/现有设定集和定妆图还是旧脸/)).toBeTruthy();
  });

  it('reports unsaved changes so the dialog around it can ask before closing', async () => {
    mockApi();
    const onDirtyChange = vi.fn();
    render(<CharacterFaceSculpt taskId="t1" characterName="林婉" onDirtyChange={onDirtyChange} />);

    const preset = await screen.findByRole('combobox', { name: /从预设开始/ });
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
    await userEvent.selectOptions(preset, 'heroine_cool');
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);
    await userEvent.click(screen.getByRole('button', { name: /保存到角色资产/ }));
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  it('sculpts one emotion and shows how that character will play it', async () => {

    mockApi();
    render(<CharacterFaceSculpt taskId="t1" characterName="林婉" />);
    await userEvent.click(await screen.findByRole('tab', { name: '捏表情' }));
    expect(screen.getByText('这个情绪还用通用写法')).toBeTruthy();
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '眼' }), 'crescent');
    await waitFor(() => expect(screen.getByText('林婉笑时：眼睛弯成月牙')).toBeTruthy());
    expect(screen.getByRole('option', { name: '笑' }).className).toContain('is-sculpted');
  });

  it('a features-only preset keeps the skin and brings its focal feature', async () => {
    const calls = mockApi();
    render(<CharacterFaceSculpt taskId="t1" characterName="林婉" />);
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: '肤色' }), 'wheat');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /从预设开始/ }), 'look_soft');
    const focus = screen.getByRole('combobox', { name: /突出点/ }) as HTMLSelectElement;
    expect(focus.value).toBe('eye_size');
    expect([...focus.options].map(option => option.value)).toEqual(['', 'face_shape', 'eye_size']);
    await waitFor(() => expect(calls.some(call => call.url.endsWith('/preview') && (call.body as { preset?: string } | undefined)?.preset === 'look_soft')).toBe(true));
    const previewCall = calls.filter(call => call.url.endsWith('/preview')).at(-1);
    expect(previewCall?.body).toMatchObject({ face: { skin_tone: 'wheat', face_shape: 'oval', eye_size: 1 }, preset: 'look_soft', focus: 'eye_size' });
  });

  it('choosing the middle of a scale means "keep the original description"', async () => {
    const calls = mockApi();
    render(<CharacterFaceSculpt taskId="t1" characterName="林婉" />);
    await userEvent.click(await screen.findByRole('button', { name: '眼睛大小：眼睛偏小' }));
    await userEvent.click(screen.getByRole('button', { name: '眼睛大小：适中' }));
    await waitFor(() => expect(calls.filter(call => call.url.endsWith('/preview')).length).toBeLessThanOrEqual(1));
    expect((screen.getByRole('button', { name: /保存到角色资产/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('CharacterFaceSculpt instruct, history and downstream', () => {
  const blank = { face: {}, notes: {}, expressions: {}, preset: '' };
  const now = () => Date.now() / 1000;

  function mockFlow(overrides: { history?: unknown[]; put?: Record<string, unknown> } = {}) {
    const calls: Array<{ url: string; method: string; body?: unknown }> = [];
    const history = overrides.history ?? [
      { id: 'snap0001', label: '手动保存', at: now() - 180, revision: 2 },
      { id: 'snap0000', label: '第一次捏脸之前', at: now() - 7200, revision: 0 },
    ];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method || 'GET';
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, method, body });
      const reply = (data: unknown) => ({ ok: true, status: 200, json: async () => data }) as Response;
      if (url.endsWith('/api/face-sculpt/catalog')) return reply(catalog);
      if (url.endsWith('/preview')) return reply({ ...emptyPreview, face_text: '骨相：瓜子脸' });
      if (url.endsWith('/instruct')) {
        const sculpt = { ...blank, face: { face_shape: 'melon' } };
        return reply({ reply: '脸型改成瓜子脸', patch: { face: { face_shape: 'melon' } }, unknown: [], sculpt, preview: emptyPreview, saved: false, current: null });
      }
      if (url.endsWith('/revert')) {
        return reply({
          name: '林婉', sculpt: { ...blank, face: { face_shape: 'oval' } }, revision: 3, label: '回到：手动保存', preview: emptyPreview,
          history: [{ id: 'snap0002', label: '回到之前', at: now() - 5, revision: 3 }, ...history],
          downstream: { clips_marked: 0, sheet_stale: true }, library: { updated: false },
        });
      }
      if (method === 'PUT') {
        return reply({ name: '林婉', sculpt: body, revision: 4, preview: emptyPreview, history, ...overrides.put });
      }
      return reply({ name: '林婉', sculpt: blank, revision: 2, preview: emptyPreview, history });
    });
    return calls;
  }

  it('turns a one-sentence instruction into unsaved changes', async () => {
    const calls = mockFlow();
    const onDirtyChange = vi.fn();
    render(<CharacterFaceSculpt taskId="t1" characterName="林婉" onDirtyChange={onDirtyChange} />);

    await userEvent.type(await screen.findByRole('textbox', { name: '用一句话捏' }), '脸改成瓜子脸');
    await userEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    const instruct = calls.find(call => call.url.endsWith('/face-sculpt/instruct'));
    expect(instruct?.body).toEqual({ message: '脸改成瓜子脸', apply: false });
    expect((screen.getByRole('combobox', { name: /^脸型/ }) as HTMLSelectElement).value).toBe('melon');
    expect((screen.getByRole('button', { name: /保存到角色资产/ }) as HTMLButtonElement).disabled).toBe(false);
    expect(calls.some(call => call.method === 'PUT')).toBe(false);
    await waitFor(() => expect(calls.some(call => call.url.endsWith('/preview'))).toBe(true));
  });

  it('lists the edit history and goes back to a step', async () => {
    const calls = mockFlow();
    const onSaved = vi.fn();
    render(<CharacterFaceSculpt taskId="t1" characterName="林婉" onSaved={onSaved} />);

    const list = await screen.findByRole('region', { name: '修改记录' });
    expect(list.textContent).toContain('手动保存');
    expect(list.textContent).toContain('3 分钟前');
    expect(list.textContent).toContain('2 小时前');

    await userEvent.click(screen.getByRole('button', { name: '回到这一步：手动保存' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    const revert = calls.find(call => call.url.endsWith('/face-sculpt/revert'));
    expect(revert?.method).toBe('POST');
    expect(revert?.body).toEqual({ snapshot_id: 'snap0001' });
    expect((screen.getByRole('combobox', { name: /^脸型/ }) as HTMLSelectElement).value).toBe('oval');
    expect((screen.getByRole('button', { name: /保存到角色资产/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('回到之前')).toBeTruthy();
  });

  it('keeps 回到这一步 disabled while there are unsaved changes', async () => {
    mockFlow();
    render(<CharacterFaceSculpt taskId="t1" characterName="林婉" />);
    const back = await screen.findByRole('button', { name: '回到这一步：手动保存' }) as HTMLButtonElement;
    expect(back.disabled).toBe(false);

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /从预设开始/ }), 'heroine_cool');
    expect(back.disabled).toBe(true);
    expect(back.title).toBe('先保存或放弃未保存的改动');
  });

  it('tells what the save marked downstream', async () => {
    mockFlow({ put: { downstream: { clips_marked: 3, sheet_stale: true }, library: { updated: true, element_id: 'e1' } } });
    render(<CharacterFaceSculpt taskId="t1" characterName="林婉" />);
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: /从预设开始/ }), 'heroine_cool');
    await userEvent.click(screen.getByRole('button', { name: /保存到角色资产/ }));

    expect(await screen.findByText(/已保存。3 段视频需重跑第 5 阶段才会换上新脸/)).toBeTruthy();
    expect(screen.getByText(/元素库里的演员描述已同步/)).toBeTruthy();
  });
});

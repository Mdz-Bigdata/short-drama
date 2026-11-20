// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PromptPreferencesPane } from './PromptPreferencesPane';
import { isChanged } from './promptPreferenceDraft';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const MODES = [
  { id: 'follow', label: '跟随平台', hint: '用平台默认的创作方法。' },
  { id: 'append', label: '追加', hint: '平台的方法照用，再加上你写的这几条。' },
  { id: 'rewrite', label: '改写', hint: '用你写的方法代替平台默认的方法。' },
];

const catalogue = (over: Partial<Record<string, { mode: string; text: string }>> = {}) => ({
  text_limit: 20,
  modes: MODES,
  operations: [
    {
      id: 'promo', stage: 8, label: '宣发文案', description: '第 8 阶段的创作方法。', modes: ['follow', 'append', 'rewrite'],
      why_no_rewrite: '', platform_text: 'Role: 宣发\nMethodology: 平台的方法', protected: '不得制造不存在的剧情。',
      mode: 'follow', text: '', ...over.promo,
    },
    {
      id: 'storyboard', stage: 4, label: '分镜', description: '第 4 阶段的创作方法。', modes: ['follow', 'append'],
      why_no_rewrite: '分镜表的列由程序逐项检查，所以只能追加。', platform_text: '', protected: '',
      mode: 'follow', text: '', ...over.storyboard,
    },
  ],
});

describe('isChanged', () => {
  it('compares the choice and, when something is written, its trimmed text', () => {
    expect(isChanged({ mode: 'follow', text: '' }, { mode: 'follow', text: 'left in the box' })).toBe(false);
    expect(isChanged({ mode: 'append', text: '少用旁白' }, { mode: 'append', text: ' 少用旁白 ' })).toBe(false);
    expect(isChanged({ mode: 'append', text: '少用旁白' }, { mode: 'append', text: '少用旁白。' })).toBe(true);
    expect(isChanged({ mode: 'append', text: '少用旁白' }, { mode: 'follow', text: '少用旁白' })).toBe(true);
  });
});

describe('PromptPreferencesPane', () => {
  it('offers each stage only the choices it has and says why a rewrite is missing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, json: async () => catalogue() } as Response);
    render(<PromptPreferencesPane />);
    const promo = await screen.findByRole('article', { name: '宣发文案' });
    const board = screen.getByRole('article', { name: '分镜' });
    expect(within(promo).getAllByRole('radio').map(radio => (radio as HTMLInputElement).value)).toEqual(['follow', 'append', 'rewrite']);
    expect(within(board).getAllByRole('radio').map(radio => (radio as HTMLInputElement).value)).toEqual(['follow', 'append']);
    expect(within(board).getByText(/所以只能追加/)).toBeTruthy();
    expect(within(promo).queryByRole('textbox')).toBeNull();
    expect((within(promo).getByRole('button', { name: '保存' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows what a rewrite replaces and what stays, and saves the choice', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      if (init?.method === 'PUT') {
        const sent = JSON.parse(String(init.body));
        return { ok: true, status: 200, json: async () => catalogue({ promo: { mode: sent.mode, text: sent.text.trim() } }) } as Response;
      }
      return { ok: true, status: 200, json: async () => catalogue() } as Response;
    });
    render(<PromptPreferencesPane />);
    const promo = await screen.findByRole('article', { name: '宣发文案' });
    fireEvent.click(within(promo).getByRole('radio', { name: '改写' }));
    expect(within(promo).getByText(/平台的方法/)).toBeTruthy();
    expect(within(promo).getByText('这一句仍会保留：不得制造不存在的剧情。')).toBeTruthy();
    const save = within(promo).getByRole('button', { name: '保存' }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(within(promo).getByRole('textbox'), { target: { value: ' 标题要冷，不喊口号 ' } });
    expect(within(promo).getByText('9 / 20 字')).toBeTruthy();
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    expect(await within(promo).findByText('已保存')).toBeTruthy();
    const put = fetchMock.mock.calls.find(call => call[1]?.method === 'PUT')!;
    expect(String(put[0])).toContain('/api/users/me/prompt-preferences/promo');
    expect(JSON.parse(String(put[1]!.body))).toEqual({ mode: 'rewrite', text: ' 标题要冷，不喊口号 ' });
    expect((within(promo).getByRole('textbox') as HTMLTextAreaElement).value).toBe('标题要冷，不喊口号');
    expect(save.disabled).toBe(true);
  });

  it('will not save text over the limit and reports what the server refuses', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      if (init?.method === 'PUT') return { ok: false, status: 422, json: async () => ({ detail: '「分镜」不能改写' }) } as Response;
      return { ok: true, status: 200, json: async () => catalogue({ storyboard: { mode: 'append', text: '多给手部特写' } }) } as Response;
    });
    render(<PromptPreferencesPane />);
    const board = await screen.findByRole('article', { name: '分镜' });
    const save = within(board).getByRole('button', { name: '保存' }) as HTMLButtonElement;
    fireEvent.change(within(board).getByRole('textbox'), { target: { value: '字'.repeat(21) } });
    expect(save.disabled).toBe(true);
    fireEvent.click(within(board).getByRole('radio', { name: '跟随平台' }));
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    expect((await screen.findByRole('alert')).textContent).toBe('「分镜」不能改写');
  });

  it('stays out of the page when the answer is not a catalogue', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, json: async () => ({ user: {} }) } as Response);
    const { container } = render(<PromptPreferencesPane />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container.querySelector('.prompt-preferences')).toBeNull();
  });
});

// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ProjectMemory, type MemoryView } from './ProjectMemory';

const BASE = 'http://localhost:8000/api/drama/t1/memory';
const TOKENS = { input: 120000, output: 3000, reasoning: 0, cached_input: 60000, reused_calls: 2, reused_saved: 9000, system_chars_saved: 100 };

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('ProjectMemory', () => {
  const fetchMock = vi.fn();
  let view: MemoryView;

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
    view = {
      prompt_profile: 'standard', tokens: TOKENS,
      entries: [
        { id: 'a', text: '全片不要旁白', kind: 'decision', source: 'model', pinned: false },
        { id: 'b', text: '女主不穿红色', kind: 'preference', source: 'user', pinned: true },
      ],
    };
    fetchMock.mockImplementation(() => json(view));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('lists pinned first, says who noted what and shows what was spent and saved', async () => {
    render(<ProjectMemory taskId="t1" onClose={() => {}} />);
    const rows = await screen.findAllByRole('listitem');
    expect(rows[0].textContent).toContain('女主不穿红色');
    expect(rows[1].textContent).toContain('模型记的');
    expect(screen.getByText('12.0 万')).toBeTruthy();
    expect(screen.getByText('6.0 万（50%）')).toBeTruthy();
    expect(screen.getByText(/9000 · 2/)).toBeTruthy();
  });

  it('adds, pins, deletes and switches the prompt profile', async () => {
    render(<ProjectMemory taskId="t1" onClose={() => {}} />);
    await screen.findAllByRole('listitem');
    await userEvent.type(screen.getByLabelText('要记住的事'), '主色调冷蓝');
    await userEvent.click(screen.getByRole('button', { name: '记住' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(BASE, expect.objectContaining({ method: 'POST' })));
    const post = fetchMock.mock.calls.find(([, options]) => options?.method === 'POST');
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ text: '主色调冷蓝', kind: 'decision', pinned: true });
    await waitFor(() => expect((screen.getByLabelText('要记住的事') as HTMLInputElement).value).toBe(''));

    await userEvent.click(screen.getByRole('button', { name: '固定：全片不要旁白' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(`${BASE}/a`, expect.objectContaining({ method: 'PATCH' })));
    await userEvent.click(screen.getByRole('button', { name: '删除：女主不穿红色' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(`${BASE}/b`, expect.objectContaining({ method: 'DELETE' })));
    await userEvent.click(screen.getByRole('checkbox'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(`${BASE}/prompt-profile`, expect.objectContaining({ method: 'PUT', body: JSON.stringify({ profile: 'lean' }) })));
  });

  it('keeps what was typed when saving fails, and closes on Escape', async () => {
    const onClose = vi.fn();
    render(<ProjectMemory taskId="t1" onClose={onClose} />);
    await screen.findAllByRole('listitem');
    fetchMock.mockImplementation(() => json({ detail: '保存失败' }, 500));
    await userEvent.type(screen.getByLabelText('要记住的事'), '一条');
    await userEvent.click(screen.getByRole('button', { name: '记住' }));
    expect((await screen.findByRole('alert')).textContent).toBeTruthy();
    expect((screen.getByLabelText('要记住的事') as HTMLInputElement).value).toBe('一条');
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });
});

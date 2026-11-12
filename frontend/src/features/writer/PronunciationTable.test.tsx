// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PronunciationTable } from './PronunciationTable';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('PronunciationTable', () => {
  it('loads the table, adds a reading and saves the whole table', async () => {
    const calls: Array<{ url: string; method?: string; body?: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url: String(input), method: init?.method, body });
      return { ok: true, json: async () => ({ readings: body?.readings ?? [{ word: '重庆', say: '崇庆' }] }) } as Response;
    });
    const user = userEvent.setup();
    render(<PronunciationTable taskId="t1" />);
    await waitFor(() => expect(screen.getByText('配音读音表（1）')).toBeTruthy());
    await user.click(screen.getByText('配音读音表（1）'));
    await user.type(screen.getByLabelText('剧本里的写法'), '行长');
    await user.type(screen.getByLabelText('配音时的念法'), '航长');
    await user.click(screen.getByRole('button', { name: '加一条' }));
    await user.click(screen.getByRole('button', { name: '保存读音表' }));
    expect(calls.at(-1)).toMatchObject({
      url: expect.stringContaining('/api/drama/t1/pronunciations'), method: 'PUT',
      body: { readings: [{ word: '重庆', say: '崇庆' }, { word: '行长', say: '航长' }] },
    });
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('已保存'));
  });
});

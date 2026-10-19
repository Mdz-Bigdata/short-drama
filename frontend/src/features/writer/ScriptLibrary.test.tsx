// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ScriptLibrary } from './ScriptLibrary';
import { describeSources, type ScriptDocument } from './scriptLibraryApi';

function document(overrides: Partial<ScriptDocument>): ScriptDocument {
  return { id: 'd', name: 'file.txt', sizeBytes: 1024, updatedAt: '2026-10-13T00:00:00Z', role: 'reference', ...overrides };
}

const library: ScriptDocument[] = [
  document({ id: 'story', name: 'story.txt', sizeBytes: 28_700, role: 'source', sourceKind: 'novel' }),
  document({ id: 'ep1', name: 'episode_1.txt', sizeBytes: 7_300, role: 'episode', sourceKind: 'novel', position: 1, episode: 4 }),
  document({ id: 'ep2', name: 'episode_2.txt', sizeBytes: 5_400, role: 'episode', sourceKind: 'novel', position: 2, episode: null }),
  document({ id: 'notes', name: '人物小传.md', sizeBytes: 900, role: 'reference' }),
];

describe('ScriptLibrary roles', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('shows each file as whole source, own-source episode or reference, with its place and episode', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ({
      ok: true, status: 200, json: async () => ({ documents: library, total: library.length }),
    }) as Response);

    render(<ScriptLibrary taskId="task-1" />);

    const list = await screen.findByRole('list');
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(4);
    expect((within(rows[0]).getByLabelText('story.txt 的角色') as HTMLSelectElement).value).toBe('source');
    expect((within(rows[1]).getByLabelText('episode_1.txt 的角色') as HTMLSelectElement).value).toBe('episode');
    expect(rows[1].textContent).toContain('第 1 位');
    expect(rows[1].textContent).toContain('已排为第 4 集');
    expect(rows[2].textContent).toContain('第 2 位');
    expect(rows[2].textContent).not.toContain('已排为');
    // A reference file has no genre to choose; a source file does.
    expect(within(rows[3]).queryByLabelText('人物小传.md 的体裁')).toBeNull();
    expect((within(rows[0]).getByLabelText('story.txt 的体裁') as HTMLSelectElement).value).toBe('novel');
    expect(screen.getByRole('status').textContent).toContain('整本源文 1 份');
    expect(screen.getByRole('status').textContent).toContain('逐集原文 2 集');
  });

  it('changes a file role through the API and says stage 2 must run again', async () => {
    const patches: Array<{ url: string; body: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === 'PATCH') {
        patches.push({ url, body: JSON.parse(String(init.body)) });
        return { ok: true, status: 200, json: async () => ({ ...library[3], role: 'episode', content: '' }) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({ documents: library, total: library.length }) } as Response;
    });
    const user = userEvent.setup();

    render(<ScriptLibrary taskId="task-1" />);
    const select = await screen.findByLabelText('人物小传.md 的角色');
    await user.selectOptions(select, 'episode');

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].url).toContain('/api/drama/task-1/script-documents/notes');
    expect(patches[0].body).toEqual({ role: 'episode' });
    expect(screen.getByText(/现在是逐集原文/)).toBeTruthy();
  });

  it('reorders own-source episodes with an explicit order for the swapped pair', async () => {
    const patches: Array<{ url: string; body: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === 'PATCH') {
        patches.push({ url, body: JSON.parse(String(init.body)) });
        return { ok: true, status: 200, json: async () => ({ ...library[1], content: '' }) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({ documents: library, total: library.length }) } as Response;
    });
    const user = userEvent.setup();

    render(<ScriptLibrary taskId="task-1" />);
    await user.click(await screen.findByLabelText('episode_2.txt 前移一集'));

    await waitFor(() => expect(patches).toHaveLength(2));
    const orders = Object.fromEntries(patches.map(patch => [patch.url.split('/').pop(), (patch.body as { order: number }).order]));
    expect(orders).toEqual({ ep2: 0, ep1: 1 });
  });

  it('describes an empty library as having no source yet', () => {
    expect(describeSources([])).toContain('尚未指定源文');
    expect(describeSources([document({ role: 'source' })])).toBe('整本源文 1 份（按顺序拼接后切分成集）');
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ElementLibraryPage } from './ElementLibraryPage';

const FOLDER = { id: 'f1', name: '道具组', count: 1, cover_element_id: null, cover_url: null };

function element(id: string, folder_id: string | null) {
  return {
    id, kind: 'costume', name: `元素${id}`, description: '', status: 'ready', version: 1, metadata: {}, model3d: null, folder_id,
    files: [{ id: `${id}-f`, slot: 'reference', mime_type: 'image/png', media_kind: 'image', size_bytes: 1, sha256: 's', url: `/api/elements/${id}/files/x/content` }],
  };
}

function serve() {
  const calls: Array<{ url: string; method: string; body: unknown }> = [];
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null });
    let payload: unknown = {};
    if (url.includes('/api/elements/folders') && (init?.method ?? 'GET') === 'GET') payload = { folders: [FOLDER], total: 2, unfiled: 1 };
    else if (url.includes('folder=f1')) payload = { items: [element('a', 'f1')], total: 1 };
    else if (url.includes('folder=unfiled')) payload = { items: [element('b', null)], total: 1 };
    else if (url.includes('/api/elements?')) payload = { items: [element('a', 'f1'), element('b', null)], total: 2 };
    return { ok: true, status: 200, json: async () => payload } as Response;
  });
  return { calls, fetchMock };
}

describe('element library folders', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('filters the listing by all, unfiled and a folder', async () => {
    const { calls } = serve();
    const onCountChange = vi.fn();
    render(<ElementLibraryPage initialKind="costume" onBack={() => undefined} onCountChange={onCountChange} />);
    const chip = await screen.findByRole('button', { name: /道具组/ });
    expect((await screen.findByRole('button', { name: /未归档/ })).textContent).toContain('1');
    await screen.findByRole('article', { name: /元素b/ });
    fireEvent.click(chip);
    await waitFor(() => expect(calls.some(call => call.url.includes('folder=f1'))).toBe(true));
    await waitFor(() => expect(screen.queryByRole('article', { name: /元素b/ })).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: /未归档/ }));
    await screen.findByRole('article', { name: /元素b/ });
    expect(calls.some(call => call.url.includes('folder=unfiled'))).toBe(true);
    // The parent's count is the whole library, not whichever folder is open.
    expect(onCountChange.mock.calls.every(call => call[1] === 2)).toBe(true);
  });

  it('moves an element in and out from its card', async () => {
    const { calls } = serve();
    render(<ElementLibraryPage initialKind="costume" onBack={() => undefined} />);
    await screen.findByRole('button', { name: /道具组/ });
    const select = await screen.findByLabelText('“元素b”所在文件夹');
    await screen.findByRole('article', { name: /元素a/ });
    fireEvent.change(select, { target: { value: 'f1' } });
    await waitFor(() => expect(calls.find(call => call.url.endsWith('/folders/move'))?.body).toEqual({ element_ids: ['b'], folder_id: 'f1' }));
    fireEvent.change(await screen.findByLabelText('“元素a”所在文件夹'), { target: { value: '' } });
    await waitFor(() => expect(calls.filter(call => call.url.endsWith('/folders/move'))[1]?.body).toEqual({ element_ids: ['a'], folder_id: null }));
  });

  it('creates, sets a cover on and deletes a folder', async () => {
    const { calls } = serve();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<ElementLibraryPage initialKind="costume" onBack={() => undefined} />);
    fireEvent.click(await screen.findByRole('button', { name: '新建文件夹' }));
    fireEvent.change(screen.getByLabelText('文件夹名称'), { target: { value: '新组' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(calls.find(call => call.method === 'POST' && call.url.endsWith('/api/elements/folders'))?.body).toEqual({ name: '新组' }));

    fireEvent.click(await screen.findByRole('button', { name: /道具组/ }));
    await screen.findByRole('button', { name: '删除文件夹' });
    await screen.findByRole('option', { name: '元素a' });
    fireEvent.change(screen.getByLabelText('封面'), { target: { value: 'a' } });
    await waitFor(() => expect(calls.find(call => call.method === 'PATCH')?.body).toEqual({ cover_element_id: 'a' }));
    fireEvent.click(await screen.findByRole('button', { name: '删除文件夹' }));
    await waitFor(() => expect(calls.some(call => call.method === 'DELETE' && call.url.endsWith('/folders/f1'))).toBe(true));
  });

  it('stays out of a project view, which lists by project instead', async () => {
    const { calls } = serve();
    render(<ElementLibraryPage initialKind="costume" embedded taskId="t1" />);
    await screen.findByRole('article', { name: /元素b/ });
    expect(screen.queryByRole('region', { name: '文件夹' })).toBeNull();
    expect(screen.queryByLabelText('“元素b”所在文件夹')).toBeNull();
    expect(calls.some(call => call.url.includes('/folders'))).toBe(false);
  });

  it('still works when the folder routes fail', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      if (String(input).includes('/folders')) return { ok: false, status: 500, json: async () => ({ detail: 'x' }) } as Response;
      return { ok: true, status: 200, json: async () => ({ items: [element('b', null)], total: 1 }) } as Response;
    });
    render(<ElementLibraryPage initialKind="costume" onBack={() => undefined} />);
    await screen.findByRole('article', { name: /元素b/ });
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

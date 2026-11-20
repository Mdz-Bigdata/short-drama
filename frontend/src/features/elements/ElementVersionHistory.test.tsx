// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ASSETS_CHANGED_EVENT, type AssetsChangedDetail } from './assetEvents';
import { ElementLibraryPage } from './ElementLibraryPage';
import { relativeTime, syncCounts, usageShotLabel } from './elementVersions';

const costume = {
  id: 'c1', kind: 'costume', name: '玄黑官袍', description: '金线云纹', status: 'ready', version: 3, metadata: {}, model3d: null,
  files: [{ id: 'c1-f', slot: 'reference', mime_type: 'image/png', media_kind: 'image', size_bytes: 1, sha256: 's', url: '/media/c1.png' }],
};

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const revisions = [
  { revision: 13, version: 3, name: '玄黑官袍', description: '金线云纹', reason: 'file', created_at: minutesAgo(5), files: [{ slot: 'reference', url: '/media/c1.png' }] },
  { revision: 12, version: 2, name: '黑色官袍', description: '素面', reason: 'rename', created_at: minutesAgo(180), files: [{ slot: 'reference', url: '/media/c1-old.png' }] },
];

const usages = [
  { task_id: 't1', title: '雨夜追凶', scene_id: '2', shot_id: '5', shot_uid: 'u5', in_storyboard: true, in_video: false },
  { task_id: 't1', title: '雨夜追凶', scene_id: '3', shot_id: '1', shot_uid: 'u31', in_storyboard: true, in_video: true },
];

const sync = { tasks: [{ task_id: 't1', shots_marked: 2, clips_marked: 1, boards_marked: 0 }], renamed: true };

function serve(kind = 'costume', item: Record<string, unknown> = costume) {
  const calls: Array<{ url: string; method: string; body: unknown }> = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method, body: typeof init?.body === 'string' ? JSON.parse(init.body) : null });
    let payload: unknown = { items: [], total: 0 };
    if (url.includes(`/api/elements?kind=${kind}`)) payload = { items: [item], total: 1 };
    else if (url.endsWith(`/api/elements/${String(item.id)}/revisions`)) payload = { items: revisions };
    else if (url.endsWith(`/api/elements/${String(item.id)}/usages`)) payload = { items: usages };
    else if (url.includes('/restore') && method === 'POST') payload = { ...item, version: 4, name: '黑色官袍', sync };
    else if (url.endsWith(`/api/elements/${String(item.id)}`) && method === 'PATCH') payload = { ...item, name: '玄青官袍', version: 4, sync };
    else if (url.includes('/folders')) payload = { folders: [], total: 0, unfiled: 0 };
    return { ok: true, status: 200, json: async () => payload } as Response;
  });
  const events: AssetsChangedDetail[] = [];
  const listener = (event: Event) => events.push((event as CustomEvent<AssetsChangedDetail>).detail);
  window.addEventListener(ASSETS_CHANGED_EVENT, listener);
  return { calls, events, stop: () => window.removeEventListener(ASSETS_CHANGED_EVENT, listener) };
}

describe('element version history', () => {
  let stop: () => void = () => undefined;
  afterEach(() => { stop(); cleanup(); vi.restoreAllMocks(); });

  it('lists revisions with what changed and the shots that use the asset', async () => {
    const served = serve();
    stop = served.stop;
    render(<ElementLibraryPage initialKind="costume" embedded taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '“玄黑官袍”的版本记录' }));

    const dialog = await screen.findByRole('dialog', { name: '“玄黑官袍”的版本记录' });
    const current = await within(dialog).findByRole('listitem', { name: '版本 v3' });
    expect(within(current).getByText('当前版本')).toBeTruthy();
    expect(within(current).getByText('换了图 · 5 分钟前')).toBeTruthy();
    const older = within(dialog).getByRole('listitem', { name: '版本 v2' });
    expect(within(older).getByText('改名 · 3 小时前')).toBeTruthy();
    expect(within(older).getByText('名称：黑色官袍 → 现在 玄黑官袍')).toBeTruthy();
    expect(within(older).getByText('描述：素面')).toBeTruthy();
    expect(within(older).getByRole('img', { name: 'v2 reference' }).getAttribute('src')).toContain('/media/c1-old.png');

    const used = within(dialog).getByRole('region', { name: '被引用' });
    expect(await within(used).findByText('雨夜追凶 · 场景 2 · 第 5 镜')).toBeTruthy();
    expect(within(used).getByText('雨夜追凶 · 场景 3 · 第 1 镜')).toBeTruthy();
    expect(within(used).getAllByText('分镜')).toHaveLength(2);
    expect(within(used).getAllByText('视频')).toHaveLength(1);
  });

  it('restores an older revision after confirming and tells the rest of the app', async () => {
    const served = serve();
    stop = served.stop;
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<ElementLibraryPage initialKind="costume" embedded taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '“玄黑官袍”的版本记录' }));
    const dialog = await screen.findByRole('dialog', { name: '“玄黑官袍”的版本记录' });
    const older = await within(dialog).findByRole('listitem', { name: '版本 v2' });
    await within(dialog).findByText('雨夜追凶 · 场景 2 · 第 5 镜');
    fireEvent.click(within(older).getByRole('button', { name: /恢复到这个版本/ }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('2 个镜头引用了它'));
    await waitFor(() => expect(served.calls.some(call => call.method === 'POST' && call.url.endsWith('/api/elements/c1/revisions/12/restore'))).toBe(true));
    expect(await screen.findByText('已恢复到 v2，2 个镜头需重画或重跑')).toBeTruthy();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(served.events).toContainEqual({ elementId: 'c1', kind: 'costume', name: '黑色官袍', reason: 'restore', shotsMarked: 2, clipsMarked: 1 });
  });

  it('does not restore when the confirmation is declined', async () => {
    const served = serve();
    stop = served.stop;
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<ElementLibraryPage initialKind="costume" embedded taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '“玄黑官袍”的版本记录' }));
    const older = await screen.findByRole('listitem', { name: '版本 v2' });
    fireEvent.click(within(older).getByRole('button', { name: /恢复到这个版本/ }));
    expect(served.calls.some(call => call.url.includes('/restore'))).toBe(false);
    expect(served.events).toEqual([]);
  });

  it('renames in a dialog that warns about the shots first and reports what was marked', async () => {
    const served = serve();
    stop = served.stop;
    const prompt = vi.spyOn(window, 'prompt');
    render(<ElementLibraryPage initialKind="costume" embedded taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '重命名服装资产“玄黑官袍”' }));

    const dialog = await screen.findByRole('dialog', { name: '重命名服装资产' });
    expect(await within(dialog).findByText('若改名，2 个镜头引用了它，会标记为需重画')).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText('新名称'), { target: { value: ' 玄青官袍 ' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存名称' }));

    expect(await within(dialog).findByText('已重命名为“玄青官袍”，2 个镜头已标记为需重画。')).toBeTruthy();
    expect(served.calls.find(call => call.method === 'PATCH')).toMatchObject({ url: expect.stringContaining('/api/elements/c1'), body: { name: '玄青官袍' } });
    expect(served.events).toContainEqual({ elementId: 'c1', kind: 'costume', name: '玄青官袍', reason: 'rename', shotsMarked: 2, clipsMarked: 1 });
    expect(prompt).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: '完成' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('announces a deleted asset with the counts the server marked', async () => {
    const served = serve();
    stop = served.stop;
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<ElementLibraryPage initialKind="costume" embedded taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '删除服装资产“玄黑官袍”' }));
    await waitFor(() => expect(served.events.map(event => event.reason)).toContain('delete'));
  });

  it('opens the history from the version label of the 3D workspace', async () => {
    const scene = { ...costume, id: 's1', kind: 'scene', name: '雨夜码头' };
    const served = serve('scene', scene);
    stop = served.stop;
    render(<ElementLibraryPage initialKind="scene" embedded taskId="t1" />);
    fireEvent.click(await screen.findByRole('button', { name: '“雨夜码头”的版本记录' }));
    expect(await screen.findByRole('dialog', { name: '“雨夜码头”的版本记录' })).toBeTruthy();
    await waitFor(() => expect(served.calls.some(call => call.url.endsWith('/api/elements/s1/revisions'))).toBe(true));
  });
});

describe('element version helpers', () => {
  it('adds up the marked shots and clips across projects and tolerates a missing sync', () => {
    expect(syncCounts({ sync: { tasks: [{ task_id: 'a', shots_marked: 2, clips_marked: 1 }, { task_id: 'b', shots_marked: 3, clips_marked: 0 }] } }))
      .toEqual({ shotsMarked: 5, clipsMarked: 1 });
    expect(syncCounts(null)).toEqual({ shotsMarked: 0, clipsMarked: 0 });
    expect(syncCounts({ sync: { error: 'x' } })).toEqual({ shotsMarked: 0, clipsMarked: 0 });
  });

  it('labels shots and times in Chinese', () => {
    expect(usageShotLabel({ task_id: 't', title: '', scene_id: 4, shot_id: 12, in_storyboard: true, in_video: false })).toBe('场景 4 · 第 12 镜');
    expect(usageShotLabel({ task_id: 't', title: '', scene_id: null, shot_id: 'S2-03', in_storyboard: true, in_video: false })).toBe('S2-03');
    const now = Date.parse('2026-11-10T12:00:00Z');
    expect(relativeTime('2026-11-10T11:59:30Z', now)).toBe('刚刚');
    expect(relativeTime('2026-11-08T12:00:00Z', now)).toBe('2 天前');
    expect(relativeTime('not a date', now)).toBe('');
  });
});

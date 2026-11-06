// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ElementLibraryPage } from '../elements/ElementLibraryPage';
import { CharacterLooks } from './CharacterLooks';

function look(id: string, of: string, label: string, overrides: Record<string, unknown> = {}, drawn = true) {
  return {
    id, kind: 'actor', name: `${of}·${label}`, description: `${label}的穿戴`, status: 'ready', version: 1, model3d: null,
    metadata: { variant: { of, label, triggers: [`${of}·${label}`], episodes: null, source: 'costume', ...overrides } },
    files: drawn ? [{ id: `${id}-file`, slot: 'front', mime_type: 'image/png', media_kind: 'image', size_bytes: 1, sha256: 's', url: `/media/${id}.png` }] : [],
  };
}

const items = [
  look('a', '沈无咎', '麻灰拭剑奴衣', { episodes: [1, 45], spans: [[1, 8], [11, 45]] }),
  look('b', '沈无咎', '染血残衣', { episodes: [9, 10] }, false),
  look('c', '苏问剑', '月白守冢袍', { episodes: [5, 500] }),
  // 手工设的衍生形象和普通演员不算定妆图。
  { ...look('d', '沈无咎', '少年'), metadata: { variant: { of: '沈无咎', label: '少年', triggers: ['少年'], episodes: null } } },
  { ...look('e', '沈无咎', '本人'), name: '沈无咎', metadata: {} },
];

function mockApi(older: Array<ReturnType<typeof look>> = [], untimed: Array<{ of: string; name: string; label: string; text: string }> = []) {
  const calls: Array<{ url: string; body?: string }> = [];
  let drawn = false;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    calls.push({ url, body: init?.body as string | undefined });
    if (url.includes('/generation-jobs')) {
      drawn = true;
      return { ok: true, status: 202, json: async () => ({ id: 'job', status: 'completed', total: 1, processed: 1, succeeded: 1, failed: 0 }) } as Response;
    }
    if (url.includes('/character-looks/untimed')) {
      return { ok: true, json: async () => ({ items: untimed }) } as Response;
    }
    if (url.includes('/character-looks/timing')) {
      untimed.splice(0, untimed.length);
      return { ok: true, json: async () => ({ readiness: {} }) } as Response;
    }
    const kind = new URL(url).searchParams.get('kind');
    if (init?.method === 'DELETE') {
      older.splice(0, older.length);
      return { ok: true, json: async () => ({}) } as Response;
    }
    if (kind === 'costume' || kind === 'makeup') {
      const rows = older.filter(item => item.kind === kind);
      return { ok: true, json: async () => ({ items: rows, page: 1, page_size: 100, total: rows.length }) } as Response;
    }
    const listed = drawn ? items.map(item => (item.id === 'b' ? look('b', '沈无咎', '染血残衣', { episodes: [9, 10] }) : item)) : items;
    return { ok: true, json: async () => ({ items: listed, page: 1, page_size: 100, total: listed.length }) } as Response;
  });
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('CharacterLooks', () => {
  it('shows only this character\'s costume looks and when each is worn', async () => {
    mockApi();
    render(<CharacterLooks taskId="t1" characterName="沈无咎" />);

    const grid = await screen.findByRole('list', { name: '沈无咎的定妆图' });
    expect(within(grid).getAllByRole('listitem')).toHaveLength(2);
    expect(within(grid).getByText('麻灰拭剑奴衣')).toBeTruthy();
    expect(within(grid).getByText('第 1–8、11–45 集')).toBeTruthy();
    expect(within(grid).getByText('定妆图待生成')).toBeTruthy();
    expect(within(grid).queryByText('少年')).toBeNull();
    expect(screen.getByText('全剧 3 套，已生成 2 套')).toBeTruthy();
  });

  it('marks a look in the library as a look, without asking for the five identity views', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [look('a', '沈无咎', '麻灰拭剑奴衣', { episodes: [1, 8], spans: [[1, 1], [3, 8]] }), { ...look('e', '沈无咎', '本人'), name: '沈无咎', metadata: {} }], page: 1, page_size: 50, total: 2 }),
    } as Response);
    render(<ElementLibraryPage initialKind="actor" embedded />);

    const worn = await screen.findByRole('article', { name: '演员资产“沈无咎·麻灰拭剑奴衣”' });
    expect(within(worn).queryByText(/身份视图 /)).toBeNull();
    expect(within(worn).getByText(/第 1、3–8 集/)).toBeTruthy();
    expect(within(worn).queryByRole('button', { name: /取消.*衍生形象/ })).toBeNull();
    const person = screen.getByRole('article', { name: '演员资产“沈无咎”' });
    expect(within(person).getByText('身份视图 1/5')).toBeTruthy();
  });

  it('says when a look begins partway through an episode', async () => {
    mockApi();
    items.push(look('s', '路人甲', '带伤', { episodes: [9, 10], starts: [9, 2] }));
    render(<CharacterLooks taskId="t1" characterName="路人甲" />);
    const found = await screen.findByText('第 9–10 集（第 9 集从第 2 场起）');
    items.pop();
    expect(found).toBeTruthy();
  });

  it('flags a look whose description changed after it was drawn', async () => {
    mockApi();
    const stale = look('t', '路人甲', '旧写法');
    items.push({ ...stale, metadata: { ...stale.metadata, needs_redraw: true } as typeof stale.metadata });
    render(<CharacterLooks taskId="t1" characterName="路人甲" />);
    const flag = await screen.findByText('设定改过，这张图还是旧写法，建议重新生成');
    items.pop();
    expect(flag).toBeTruthy();
  });

  it('shows what the makeup check still found wrong, and nothing for a look that passed', async () => {
    mockApi();
    const failed = look('f', '路人甲', '左颊刀伤');
    const passed = look('p', '路人甲', '麻衣');
    items.push(
      { ...failed, metadata: { ...failed.metadata, look_check: { passed: false, problems: ['正脸特写右颊多了一道伤', '血色鲜红'] } } as typeof failed.metadata },
      { ...passed, metadata: { ...passed.metadata, look_check: { passed: true, problems: [] } } as typeof passed.metadata },
    );
    render(<CharacterLooks taskId="t1" characterName="路人甲" />);
    const flag = await screen.findByText('妆效核对没过：正脸特写右颊多了一道伤；血色鲜红。建议重新生成，或把妆效写得更具体');
    items.splice(-2);
    expect(flag).toBeTruthy();
    expect(screen.getAllByText(/妆效核对没过/)).toHaveLength(1);
  });

  it('lets someone date a wound the script does not place, and only for this character', async () => {
    const calls = mockApi([], [
      { of: '沈无咎', name: '沈无咎·老年妆', label: '老年妆', text: '两鬓斑白' },
      { of: '苏问剑', name: '苏问剑·旧伤', label: '旧伤', text: '肩头旧疤' },
    ]);
    const onGenerated = vi.fn();
    render(<CharacterLooks taskId="t1" characterName="沈无咎" onGenerated={onGenerated} />);

    const section = await screen.findByRole('region', { name: '还没定时间的妆效' });
    expect(within(section).getByText('两鬓斑白')).toBeTruthy();
    expect(within(section).queryByText('肩头旧疤')).toBeNull();
    const save = within(section).getByRole('button', { name: '保存' }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    await userEvent.type(within(section).getByRole('textbox', { name: '“老年妆”的时间' }), '第12集起');
    await userEvent.click(save);

    await waitFor(() => expect(onGenerated).toHaveBeenCalledTimes(1));
    const put = calls.find(call => call.url.includes('/character-looks/timing'));
    expect(JSON.parse(put?.body || '{}')).toEqual({ name: '沈无咎·老年妆', episodes: '第12集起' });
    expect(await screen.findByText('“老年妆”已合进当时穿的那身，点生成就能出图。')).toBeTruthy();
    expect(screen.queryByRole('region', { name: '还没定时间的妆效' })).toBeNull();
  });

  it('hides a look the script no longer calls for', async () => {
    mockApi();
    items.push(look('r', '沈无咎', '已退役', { retired: true }));
    render(<CharacterLooks taskId="t1" characterName="沈无咎" />);
    const grid = await screen.findByRole('list', { name: '沈无咎的定妆图' });
    items.pop();
    expect(within(grid).queryByText('已退役')).toBeNull();
    expect(screen.getByText('全剧 3 套，已生成 2 套')).toBeTruthy();
  });

  it('shows earlier costume and makeup images, and deletes one only after asking', async () => {
    const older = [{ ...look('o', '沈无咎', '旧袍'), kind: 'costume' }];
    const calls = mockApi(older);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<CharacterLooks taskId="t1" characterName="沈无咎" />);

    const section = await screen.findByRole('region', { name: '之前的服装和妆效图' });
    expect(within(section).getByText('沈无咎·旧袍')).toBeTruthy();
    await userEvent.click(within(section).getByRole('button', { name: '删除旧图“沈无咎·旧袍”' }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(calls.some(call => call.url.endsWith('/api/elements/o'))).toBe(false);

    confirm.mockReturnValue(true);
    await userEvent.click(within(section).getByRole('button', { name: '删除旧图“沈无咎·旧袍”' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: '之前的服装和妆效图' })).toBeNull());
  });

  it('shows no such section when there is nothing earlier', async () => {
    mockApi();
    render(<CharacterLooks taskId="t1" characterName="沈无咎" />);
    await screen.findByText('全剧 3 套，已生成 2 套');
    expect(screen.queryByRole('region', { name: '之前的服装和妆效图' })).toBeNull();
  });

  it('reads an open-ended range as "from that episode"', async () => {
    mockApi();
    render(<CharacterLooks taskId="t1" characterName="苏问剑" />);
    expect(await screen.findByText('第 5 集起')).toBeTruthy();
  });

  it('says a character with no costume change keeps the sheet outfit', async () => {
    mockApi();
    render(<CharacterLooks taskId="t1" characterName="路人甲" />);
    await screen.findByText('全剧 3 套，已生成 2 套');
    expect(screen.getByText('剧本里没有写路人甲换装或特殊妆效，全程是设定集上的样子。')).toBeTruthy();
  });

  it('generates only the looks, then reloads and tells the page', async () => {
    const calls = mockApi();
    const onGenerated = vi.fn();
    render(<CharacterLooks taskId="t1" characterName="沈无咎" onGenerated={onGenerated} />);

    await userEvent.click(await screen.findByRole('button', { name: '生成缺失定妆图' }));

    await waitFor(() => expect(onGenerated).toHaveBeenCalledTimes(1));
    const job = calls.find(call => call.url.includes('/generation-jobs'));
    expect(JSON.parse(job?.body || '{}')).toEqual({ kind: 'actor', looks: true, task_id: 't1' });
    expect(await screen.findByText('全剧 3 套，已生成 3 套')).toBeTruthy();
    expect((screen.getByRole('button', { name: '生成缺失定妆图' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('asks before replacing a drawn look and draws a missing one straight away', async () => {
    const calls = mockApi();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<CharacterLooks taskId="t1" characterName="沈无咎" />);

    await userEvent.click(await screen.findByRole('button', { name: '重新生成“沈无咎·麻灰拭剑奴衣”的定妆图' }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(calls.some(call => call.url.includes('/regenerate'))).toBe(false);

    await userEvent.click(screen.getByRole('button', { name: '重新生成“沈无咎·染血残衣”的定妆图' }));
    expect(confirm).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(calls.some(call => call.url.includes('/api/elements/b/regenerate'))).toBe(true));
  });
});

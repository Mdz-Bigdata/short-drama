// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ASSETS_CHANGED_EVENT } from '../elements/assetEvents';
import { ChapterAssets } from './ChapterAssets';
import type { ChapterAssetsView } from './chapterAssetsApi';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const LISTS = [{ id: 'characters', label: '角色' }, { id: 'scenes', label: '场景' }, { id: 'props', label: '道具' }] as ChapterAssetsView['lists'];

const empty: ChapterAssetsView = {
  chapters: [
    { id: 'part:1', title: '第1集 雨夜', chars: 1200, extracted_at: null, counts: null, changed: false },
    { id: 'part:2', title: '第2集 天亮', chars: 800, extracted_at: null, counts: null, changed: false },
  ],
  items: [],
  lists: LISTS,
};

const extracted: ChapterAssetsView = {
  ...empty,
  chapters: [{ ...empty.chapters[0], extracted_at: '2026-11-16T03:00:00+00:00', counts: { characters: 1, scenes: 1, props: 1 } }, empty.chapters[1]],
  items: [
    { id: 'a', list: 'characters', label: '角色', name: '林夏', aliases: [], description: '短发', chapters: ['part:1'], status: 'pending', known: true },
    { id: 'b', list: 'props', label: '道具', name: '油灯', aliases: ['旧油灯'], description: '', chapters: ['part:1'], status: 'pending', known: false },
  ],
  added: { characters: 1, scenes: 0, props: 1 },
};

describe('ChapterAssets', () => {
  it('extracts a chapter and lists what is waiting by kind', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => (
      { ok: true, status: 200, json: async () => (init?.method === 'POST' ? extracted : empty) } as Response
    ));
    render(<ChapterAssets taskId="t-1" />);
    const first = (await screen.findByText('第1集 雨夜')).closest('li')!;
    expect(within(first).getByText('1200 字，未提取')).toBeTruthy();
    fireEvent.click(within(first).getByRole('button', { name: '提取' }));
    expect((await screen.findByRole('status')).textContent).toBe('「第1集 雨夜」提取完成：新增角色 1、场景 0、道具 1');
    const post = fetchMock.mock.calls.find(call => call[1]?.method === 'POST')!;
    expect(String(post[0])).toContain('/api/drama/t-1/chapter-assets/extract');
    expect(JSON.parse(String(post[1]!.body))).toEqual({ chapter_id: 'part:1' });
    expect(screen.getByText('待确认的角色（1）')).toBeTruthy();
    expect(screen.getByText('待确认的道具（1）')).toBeTruthy();
    expect(screen.queryByText(/待确认的场景/)).toBeNull();
    expect(screen.getByText('项目里已有')).toBeTruthy();
    expect(screen.getByText('又称 旧油灯')).toBeTruthy();
    expect(within(first).getByRole('button', { name: '重新提取' })).toBeTruthy();
  });

  it('confirms an entry into the library and tells the asset pages', async () => {
    const heard = vi.fn();
    window.addEventListener(ASSETS_CHANGED_EVENT, heard);
    const confirmed: ChapterAssetsView = {
      ...extracted, items: extracted.items.map(item => (item.id === 'b' ? { ...item, status: 'confirmed', element_id: 'el-1' } : item)),
    };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => (
      { ok: true, status: 200, json: async () => (init?.method === 'POST' ? confirmed : extracted) } as Response
    ));
    render(<ChapterAssets taskId="t-1" />);
    fireEvent.click(await screen.findByRole('button', { name: '确认「油灯」' }));
    expect((await screen.findByRole('status')).textContent).toBe('「油灯」已放进资产库并关联到本项目');
    await waitFor(() => expect(heard).toHaveBeenCalledTimes(1));
    expect(screen.getByText('已处理 1 条')).toBeTruthy();
    window.removeEventListener(ASSETS_CHANGED_EVENT, heard);
  });

  it('reports an extraction the server did not count', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => (
      init?.method === 'POST'
        ? { ok: false, status: 422, json: async () => ({ detail: '模型的回答缺了「道具」清单，这一章没算提取成功' }) } as Response
        : { ok: true, status: 200, json: async () => empty } as Response
    ));
    render(<ChapterAssets taskId="t-1" />);
    fireEvent.click((await screen.findAllByRole('button', { name: '提取' }))[1]);
    expect((await screen.findByRole('alert')).textContent).toContain('没算提取成功');
  });

  it('says how to get chapters when there are none', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, json: async () => ({ chapters: [], items: [], lists: LISTS }) } as Response);
    render(<ChapterAssets taskId="t-1" />);
    expect(await screen.findByText(/还没有章节/)).toBeTruthy();
  });
});
